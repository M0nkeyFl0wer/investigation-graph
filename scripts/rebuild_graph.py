#!/usr/bin/env python3
"""
Rebuild the LadybugDB graph from the CACHED DuckDB record set — re-running only
the ground + resolve + build stages, with NO re-extraction.

Extraction (the slow, LLM-bound phase) already wrote its entities/edges/chunks to
DuckDB during ingest. When only the grounding/resolution logic changes (e.g. the
alias-driven merge in pipeline.ground_and_resolve), there is no need to pay for
extraction again: read the records back, re-ground, re-resolve, and reconstruct
the graph projection. Same corruption-safe reconstruct-and-swap as a full ingest.

Honors the same env knobs as ingest_folder (GRAPH_DIR, CHUNK_DB, ONTOLOGY_PATH,
EMBED_ENDPOINT/EXTRACT_ENDPOINT for the resolver's cosine tier).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, ".")

from investigation_graph import config
from investigation_graph.chunk_store import get_chunk_store
from investigation_graph.embed import embed_batch
from investigation_graph.graph import build_graph
from investigation_graph.ontology import Ontology
from investigation_graph.pipeline import ground_and_resolve


def main():
    ontology = Ontology()
    store = get_chunk_store()
    print(f"Scope: {ontology!r}")
    try:
        all_chunks = store.all_chunks()
        all_entities = store.all_entities()
        all_edges = store.all_edges()
        print(f"Cached records: {len(all_entities)} entities / {len(all_edges)} "
              f"edges / {len(all_chunks)} chunks (no re-extraction).")

        # Entity embeddings re-engage the resolver's semantic tier (P1.1).
        ent_vecs = embed_batch([f"{e.get('label', '')}: {e.get('description', '')}"
                                for e in all_entities])
        entity_embeddings = {e["id"]: v for e, v in zip(all_entities, ent_vecs)
                             if v is not None}

        build_records, report = ground_and_resolve(
            all_chunks, all_entities, all_edges, embeddings=entity_embeddings)

        # Mentions (entity -> its source document) before stripping doc_id.
        mentions = [{"entity_id": e["id"], "doc_id": e["doc_id"]}
                    for e in build_records["entities"] if e.get("doc_id")]
        for e in build_records["entities"]:
            e.pop("doc_id", None)
        for ed in build_records["edges"]:
            ed.pop("doc_id", None)

        documents = store.all_documents()
        counts = build_graph(
            {"documents": documents, "entities": build_records["entities"],
             "edges": build_records["edges"], "mentions": mentions},
            ontology=ontology,
        )

        merges = report.get("merges", [])
        if merges:
            review_path = Path(config.GRAPH_DIR).parent / "merges.jsonl"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            with review_path.open("w", encoding="utf-8") as fh:
                for m in merges:
                    fh.write(json.dumps(m) + "\n")

        alias_merges = sum(1 for m in merges if m.get("via_alias"))
        print(f"\nRebuilt: {counts['entities']} entities, {counts['edges']} edges "
              f"({report['entities_merged']} merged — {alias_merges} via alias).")
    finally:
        store.close()


if __name__ == "__main__":
    main()
