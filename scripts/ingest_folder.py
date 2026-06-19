#!/usr/bin/env python3
"""
Ingest documents into the investigation — the scope → ingest → extract → ground
→ build pipeline (see SPEC.md).

Flow:
  scope    confirm the ontology + corpus directory.
  ingest   each document is read, chunked, embedded, and written to DuckDB
           (the source of truth for chunks + embeddings + records).
  extract  three-phase extraction emits candidate entities + edges → DuckDB.
  ground   over the FULL DuckDB record set, the ground stage runs the grounding
           gate (drop hallucinations) and entity resolution (merge duplicates).
  build    the LadybugDB graph is rebuilt as a projection of the survivors
           (reconstruct-and-swap; grade-locality enforced at write).

Re-running is idempotent per document: a document's prior chunks/entities/edges
are deleted before it is re-ingested. The graph is always rebuilt from the full
DuckDB record set, so adding documents never corrupts the existing graph.
"""
import hashlib
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from newsroom_graph import config
from newsroom_graph.chunk_store import chunk_id_from_uri, get_chunk_store
from newsroom_graph.embed import embed_batch
from newsroom_graph.extract import Extractor
from newsroom_graph.graph import build_graph
from newsroom_graph.ontology import Ontology
from newsroom_graph.pipeline import ground_and_resolve

SUPPORTED = (".txt", ".md", ".pdf", ".html")


def read_document(path: Path) -> str:
    """Read document content. Handles txt, md, html. PDF needs pdftotext."""
    suffix = path.suffix.lower()
    if suffix in (".txt", ".md"):
        return path.read_text(errors="replace")
    if suffix == ".html":
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.text = []

            def handle_data(self, data):
                self.text.append(data)

        parser = TextExtractor()
        parser.feed(path.read_text(errors="replace"))
        return " ".join(parser.text)
    if suffix == ".pdf":
        try:
            import subprocess
            result = subprocess.run(
                ["pdftotext", str(path), "-"],
                capture_output=True, text=True, timeout=30,
            )
            return result.stdout
        except FileNotFoundError:
            print("  Warning: pdftotext not found. Install: sudo apt install poppler-utils")
            return ""
        except Exception as e:
            print(f"  Warning: could not read PDF {path.name}: {e}")
            return ""
    print(f"  Skipping unsupported format: {path.name}")
    return ""


def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    """Split text into overlapping chunks for embedding."""
    if not text.strip():
        return []
    chunks = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += chunk_size - overlap
    return chunks


def main():
    # ── SCOPE ────────────────────────────────────────────────────────────
    ingest_dir = config.INGEST_DIR
    if not ingest_dir.exists():
        ingest_dir.mkdir(parents=True)
        print(f"Created ingest directory: {ingest_dir}/\nAdd documents there and run again.")
        return

    supported = [f for f in ingest_dir.iterdir()
                 if f.is_file() and f.suffix.lower() in SUPPORTED]
    if not supported:
        print(f"No supported documents in {ingest_dir}/\nSupported: {', '.join(SUPPORTED)}")
        return

    ontology = Ontology()
    store = get_chunk_store()  # DuckDB; schema (chunks + record tables) ensured
    extractor = Extractor(ontology)

    print(f"Scope: {ontology!r}")
    print(f"Corpus: {len(supported)} document(s) in {ingest_dir}/  →  DuckDB {store.db_path.name}\n")

    t_start = time.time()
    try:
        # ── INGEST + EXTRACT (per document → DuckDB source of truth) ───────
        for i, filepath in enumerate(supported, 1):
            print(f"[{i}/{len(supported)}] {filepath.name}")
            text = read_document(filepath)
            if not text.strip():
                print("  Empty or unreadable, skipping.")
                continue

            source_url = str(filepath)
            doc_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]

            # Idempotent re-ingest: clear this document's prior records first.
            store.delete_doc_records(doc_id)
            store.write_documents([{"id": doc_id, "path": source_url, "title": filepath.stem}])

            # Chunk + embed → DuckDB.
            chunks = chunk_text(text)
            n_embedded = 0
            if chunks:
                embeddings = embed_batch(chunks)
                chunk_rows = [
                    {
                        "id": chunk_id_from_uri(source_url, idx),
                        "doc_id": doc_id,
                        "source_uri": source_url,
                        "title": filepath.stem,
                        "body": body,
                        "chunk_index": idx,
                        "embedding": embeddings[idx] if idx < len(embeddings) else None,
                    }
                    for idx, body in enumerate(chunks)
                ]
                store.write_chunks(chunk_rows)
                n_embedded = sum(1 for r in chunk_rows if r["embedding"] is not None)

            # Extract → DuckDB (tagged with doc_id so re-ingest can target them).
            result = extractor.extract_from_text(text, source_url=source_url, doc_id=doc_id)
            for e in result["entities"]:
                e["doc_id"] = doc_id
                e.setdefault("extraction_source", e.get("provenance", "unknown"))
            for ed in result["edges"]:
                ed["doc_id"] = doc_id
                ed.setdefault("extraction_source", ed.get("provenance", "unknown"))
            store.write_entities(result["entities"])
            store.write_edges(result["edges"])
            print(f"  {len(chunks)} chunks ({n_embedded} embedded), "
                  f"{len(result['entities'])} entities, {len(result['edges'])} edges → DuckDB")

        # ── GROUND (over the FULL record set) ─────────────────────────────
        all_chunks = store.all_chunks()
        all_entities = store.all_entities()
        all_edges = store.all_edges()
        print(f"\nGrounding {len(all_entities)} entities / {len(all_edges)} edges "
              f"against {len(all_chunks)} chunks...")
        build_records, report = ground_and_resolve(all_chunks, all_entities, all_edges)

        # Mentions (entity → its source document) before stripping doc_id.
        mentions = [{"entity_id": e["id"], "doc_id": e["doc_id"]}
                    for e in build_records["entities"] if e.get("doc_id")]
        for e in build_records["entities"]:
            e.pop("doc_id", None)
        for ed in build_records["edges"]:
            ed.pop("doc_id", None)

        # ── BUILD (rebuild the graph projection) ──────────────────────────
        documents = store.all_documents()
        counts = build_graph(
            {"documents": documents, "entities": build_records["entities"],
             "edges": build_records["edges"], "mentions": mentions},
            ontology=ontology,
        )

        # ── REPORT ────────────────────────────────────────────────────────
        elapsed = time.time() - t_start
        qr = report["quarantine_rate"]
        print(f"\n{'=' * 56}")
        print(f"Ingestion complete in {elapsed:.1f}s.")
        print(f"  Documents:            {counts['documents']}")
        print(f"  Chunks in DuckDB:     {store.chunk_count()}")
        print(f"  Entities (graph):     {counts['entities']}  "
              f"(merged {report['entities_merged']} duplicates)")
        print(f"  Edges (graph):        {counts['edges']}")
        print(f"  Quarantined:          {report['entities_quarantined']} entities "
              f"({qr['entities']:.0%}), {report['edges_quarantined']} edges "
              f"({qr['edges']:.0%}) — failed the grounding gate")
        print("\nNext steps:")
        print("  Search:    python scripts/search_cli.py -q 'your query'")
        print("  Analyze:   python scripts/run_analysis.py")
        print("  Briefing:  python scripts/daily_briefing.py")

        rejections = ontology.get_rejection_counts()
        if rejections:
            print("\nOntology rejections (types not in ONTOLOGY.md):")
            for type_name, count in list(rejections.items())[:10]:
                print(f"  {type_name}: {count}")
            print("  Tip: add frequently rejected types to ONTOLOGY.md")
    finally:
        store.close()


if __name__ == "__main__":
    main()
