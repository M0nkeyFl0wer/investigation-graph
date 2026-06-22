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
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, ".")

from investigation_graph import config
from investigation_graph.chunk_store import chunk_id_from_uri, get_chunk_store
from investigation_graph.chunking import chunk_text
from investigation_graph.embed import embed_batch
from investigation_graph.extract import Extractor
from investigation_graph.graph import build_graph
from investigation_graph.ontology import Ontology
from investigation_graph.pipeline import ground_and_resolve

from investigation_graph.media_setup import configure_media
from investigation_graph.processors import maybe_ingest_tabular
from kg_common.media import SUPPORTED_SUFFIXES, process_media

# Formats the prose path reads (text/HTML/PDF+OCR/image-OCR today; visual
# processors register here later — see media/ + P2.1), PLUS the structured tabular
# formats (P2.4), which take the deterministic, no-LLM path below.
SUPPORTED = tuple(SUPPORTED_SUFFIXES) + (".csv", ".tsv")


# Matches a leading YAML frontmatter block: '---' on the first line through the
# next '---' line. Markdown notes (Obsidian, Jekyll, annotated corpora) put
# metadata here.
_FRONTMATTER_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)


def strip_frontmatter(text: str) -> str:
    """Drop a leading YAML frontmatter block before extraction.

    Frontmatter is document *metadata* (license, date, tags), not prose — and in
    an annotated corpus it can even hold the gold entity/edge answer key. Either
    way we don't want the extractor mining it: that would pull metadata keys in as
    entities, or (worse) let the tool parrot a corpus's own labels instead of
    honestly extracting from the body. The frontmatter stays on disk for separate
    evaluation; the graph is built from the prose."""
    return _FRONTMATTER_RE.sub("", text, count=1)


def read_document(path: Path) -> str:
    """Read a source's text via the media subsystem (P2.1). Thin wrapper over
    ``process_media`` so ingest doesn't care whether the bytes came from a text
    layer, OCR, or (later) a vision model. Strips leading YAML frontmatter so
    extraction runs on prose, not metadata."""
    result = process_media(path)
    if result.metadata.get("ocr_used"):
        print(f"  ({result.metadata.get('kind')} — recovered "
              f"{len(result.text)} chars via OCR)")
    return strip_frontmatter(result.text)


# chunk_text now lives in investigation_graph.chunking (shared with extraction so
# embedded chunks and the LLM's chunks line up — see chunking.py / P0.1).


def main():
    # ── SCOPE ────────────────────────────────────────────────────────────
    ingest_dir = config.INGEST_DIR
    if not ingest_dir.exists():
        ingest_dir.mkdir(parents=True)
        print(f"Created ingest directory: {ingest_dir}/\nAdd documents there and run again.")
        return

    # Recurse so foldered corpora (e.g. the good-dogs sample, organized into
    # domain subdirs) ingest fully — not just files at the top level. Skip
    # dot/underscore files and any hidden directory (vendored ontology sources,
    # .git, editor state) so only real documents are picked up. Sorted for a
    # stable, reproducible ingest order.
    supported = sorted(
        f for f in ingest_dir.rglob("*")
        if f.is_file()
        and f.suffix.lower() in SUPPORTED
        and not f.name.startswith((".", "_"))
        and not any(part.startswith(".") for part in f.relative_to(ingest_dir).parts)
    )
    if not supported:
        print(f"No supported documents in {ingest_dir}/\nSupported: {', '.join(SUPPORTED)}")
        return

    ontology = Ontology()
    store = get_chunk_store()  # DuckDB; schema (chunks + record tables) ensured
    extractor = Extractor(ontology)

    print(f"Scope: {ontology!r}")
    print(f"Corpus: {len(supported)} document(s) in {ingest_dir}/  →  DuckDB {store.db_path.name}\n")

    # Wire our config into the shared kg_common.media subsystem (visual backend).
    configure_media()

    t_start = time.time()
    try:
        # ── INGEST + EXTRACT (per document → DuckDB source of truth) ───────
        for i, filepath in enumerate(supported, 1):
            print(f"[{i}/{len(supported)}] {filepath.name}")
            source_url = str(filepath)
            doc_id = hashlib.sha256(source_url.encode()).hexdigest()[:16]

            # Idempotent re-ingest: clear this document's prior records first.
            store.delete_doc_records(doc_id)
            store.write_documents([{"id": doc_id, "path": source_url, "title": filepath.stem}])

            # ── STRUCTURED PATH (P2.4) ────────────────────────────────────
            # A tabular source (.csv/.tsv with a sibling <stem>.map.yaml) is
            # deterministic — a row IS a typed edge — so it skips chunk/embed/
            # LLM-extract entirely. The row-chunks it emits still go to DuckDB so
            # the entities/edges ground normally. Returns None for the prose path.
            staged = maybe_ingest_tabular(filepath, doc_id, source_url, ontology=ontology)
            if staged is not None:
                if staged["chunks"]:
                    # Embed the row-chunks for retrieval (graceful: Nones if the
                    # embedder is unavailable — grounding/build don't need vectors).
                    embs = embed_batch([c["body"] for c in staged["chunks"]])
                    for idx, c in enumerate(staged["chunks"]):
                        c["embedding"] = embs[idx] if idx < len(embs) else None
                    store.write_chunks(staged["chunks"])
                store.write_entities(staged["entities"])
                store.write_edges(staged["edges"])
                print(f"  tabular: {len(staged['chunks'])} rows, "
                      f"{len(staged['entities'])} entities, {len(staged['edges'])} "
                      f"edges (deterministic, no LLM)")
                if staged["skipped"]:
                    print(f"    ↳ {len(staged['skipped'])} row(s) skipped (type/grade)")
                continue

            # ── PROSE PATH (chunk → embed → 3-phase extract) ──────────────
            text = read_document(filepath)
            if not text.strip():
                print("  Empty or unreadable, skipping.")
                continue

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
        # Entity embeddings engage the resolver's semantic tier (P1.1) so aliases
        # that aren't fuzzy-close still merge. Graceful: if Ollama is unavailable,
        # embed_batch returns Nones → empty map → ER falls back to exact+fuzzy.
        ent_vecs = embed_batch([f"{e.get('label', '')}: {e.get('description', '')}"
                                for e in all_entities])
        entity_embeddings = {e["id"]: v for e, v in zip(all_entities, ent_vecs)
                             if v is not None}
        build_records, report = ground_and_resolve(
            all_chunks, all_entities, all_edges, embeddings=entity_embeddings)

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
        # Merge-review artifact (P1.3): every (kept, merged) pair, so a human can
        # confirm fused identities before trusting them — a wrong merge fuses two
        # real entities (the libel vector). Lands beside the investigation data.
        merges = report.get("merges", [])
        if merges:
            import json
            review_path = Path(config.GRAPH_DIR).parent / "merges.jsonl"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            with review_path.open("w", encoding="utf-8") as fh:
                for m in merges:
                    fh.write(json.dumps(m) + "\n")
            print(f"    ↳ review {len(merges)} merge(s): {review_path}")
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
