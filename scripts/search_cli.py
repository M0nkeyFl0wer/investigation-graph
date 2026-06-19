#!/usr/bin/env python3
"""
Search the investigation.

Two surfaces, matching the hybrid architecture:
  - CONTENT search runs over DuckDB chunks (BM25 + vector + RRF) — this is how
    you find passages by keyword or meaning. Modes: hybrid (default), fts,
    semantic.
  - GRAPH lookups run over the read-only LadybugDB graph:
      --path FROM TO   typed relationship chains between two entities
      --entity NAME    find an entity node by name

Both open read-only handles, so search never collides with an ingest/build.
"""
import argparse
import sys

sys.path.insert(0, ".")

from investigation_graph import config
from investigation_graph.chunk_store import ChunkStore


def _embed(query: str) -> list[float]:
    """Embed the query for vector/hybrid search (local Ollama)."""
    from investigation_graph.embed import embed_text
    return embed_text(query)


def display_chunks(results: list[dict], mode: str) -> None:
    if not results:
        print("No matching passages found.")
        return
    print(f"Found {len(results)} passage(s):\n")
    for r in results:
        title = r.get("title") or r.get("source_uri") or r.get("doc_id") or "—"
        body = (r.get("body") or "").strip().replace("\n", " ")
        snippet = (body[:200] + "…") if len(body) > 200 else body
        score = r.get("rrf_score")
        score_str = f"  (score {score:.4f})" if isinstance(score, (int, float)) else ""
        print(f"  • {title}{score_str}")
        print(f"      {snippet}")
        print(f"      source: {r.get('source_uri', '—')}")
        print()


def display_paths(paths: list[dict]) -> None:
    if not paths:
        print("No paths found.")
        return
    print(f"Found {len(paths)} path(s):\n")
    for i, p in enumerate(paths, 1):
        labels, types = p["node_labels"], p["edge_types"]
        chain = []
        for j, label in enumerate(labels):
            chain.append(label)
            if j < len(types):
                chain.append(f" --[{types[j]}]--> ")
        print(f"  Path {i} (confidence: {p['path_confidence']:.2f}):")
        print(f"    {''.join(chain)}\n")


def display_entities(rows: list[dict]) -> None:
    if not rows:
        print("No entities found.")
        return
    print(f"Found {len(rows)} entit(y/ies):\n")
    for r in rows:
        print(f"  [{r.get('entity_type', ''):14}] {r.get('label', '')}  "
              f"(confidence {r.get('confidence', 0):.2f})")


def main():
    parser = argparse.ArgumentParser(
        description="Search the investigation (content over DuckDB chunks; "
                    "paths/entities over the graph)",
        epilog="Examples:\n"
               "  %(prog)s -q 'payments to contractors'\n"
               "  %(prog)s -q 'harbor' --mode fts\n"
               "  %(prog)s --path 'Chen' 'Meridian'\n"
               "  %(prog)s --entity 'Acme'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", "-q", help="Content query (searches passages)")
    parser.add_argument("--mode", "-m", choices=["hybrid", "fts", "semantic"],
                        default="hybrid", help="Content search mode (default: hybrid)")
    parser.add_argument("--path", "-p", nargs=2, metavar=("FROM", "TO"),
                        help="Find typed paths between two entities (graph)")
    parser.add_argument("--entity", "-e", help="Find an entity node by name (graph)")
    parser.add_argument("--limit", "-l", type=int, default=config.DEFAULT_SEARCH_LIMIT,
                        help="Max results")
    args = parser.parse_args()

    if not (args.query or args.path or args.entity):
        parser.error("Provide --query (content), --path (graph), or --entity (graph)")

    # ── Graph surfaces (read-only; no writer lock) ─────────────────────────
    if args.path or args.entity:
        from investigation_graph.graph import Graph
        graph = Graph(read_only=True)
        try:
            if args.path:
                src, tgt = args.path
                print(f"Finding paths: {src} → {tgt}\n")
                display_paths(graph.find_path(src, tgt))
            if args.entity:
                rows = graph.query(
                    "MATCH (e:Entity) WHERE e.label CONTAINS $q "
                    "RETURN e.id AS id, e.label AS label, e.entity_type AS entity_type, "
                    "e.confidence AS confidence LIMIT $limit",
                    {"q": args.entity, "limit": args.limit},
                )
                display_entities(rows)
        finally:
            graph.close()
        return

    # ── Content search over DuckDB chunks ──────────────────────────────────
    store = ChunkStore(read_only=True)
    try:
        if args.mode == "fts":
            # BM25 only — hydrate the {id, rank} hits for display.
            hits = store.search_fts(args.query, limit=args.limit)
            results = [c for c in (store.get_chunk_by_id(h["id"]) for h in hits) if c]
        elif args.mode == "semantic":
            # Vector only — hydrate the {id, rank} hits for display.
            hits = store.search_vector(_embed(args.query), limit=args.limit)
            results = [c for c in (store.get_chunk_by_id(h["id"]) for h in hits) if c]
        else:  # hybrid — already hydrated with an rrf_score
            results = store.search_hybrid(args.query, _embed(args.query), limit=args.limit)
        display_chunks(results, args.mode)
    finally:
        store.close()


if __name__ == "__main__":
    main()
