#!/usr/bin/env python3
"""Search the knowledge graph from the command line."""
import argparse
import sys

sys.path.insert(0, ".")

from newsroom_graph.graph import Graph
from newsroom_graph.queries import QUERIES


def search_keyword(graph, query, entity_type, limit):
    """Keyword search via Cypher CONTAINS."""
    if entity_type:
        return graph.query(QUERIES["entity_by_label_and_type"],
                           parameters={"query": query, "etype": entity_type,
                                       "limit": limit})
    return graph.query(QUERIES["entity_by_label"],
                       parameters={"query": query, "limit": limit})


def search_semantic(graph, query, limit):
    """Semantic search via embedding similarity."""
    from newsroom_graph.embed import embed_text
    query_embedding = embed_text(query)
    return graph.vector_search(query_embedding, limit=limit)


def search_hybrid(graph, query, entity_type, limit):
    """Merge keyword and semantic results, deduplicate by entity ID."""
    keyword_results = search_keyword(graph, query, entity_type, limit)
    semantic_results = search_semantic(graph, query, limit)

    # Merge: keyword results get a boost, semantic results contribute score
    merged = {}
    for r in keyword_results:
        merged[r["id"]] = {
            **r,
            "match": "keyword",
            "score": r.get("confidence", 0.5),
        }

    for r in semantic_results:
        eid = r["id"]
        if eid in merged:
            merged[eid]["match"] = "both"
            merged[eid]["score"] = max(merged[eid]["score"],
                                       r.get("score", 0))
        else:
            merged[eid] = {
                **r,
                "match": "semantic",
                "score": r.get("score", 0),
            }

    results = sorted(merged.values(), key=lambda r: -r["score"])
    return results[:limit]


def display_results(results, mode):
    """Pretty-print search results."""
    if not results:
        print("No results found.")
        return

    print(f"Found {len(results)} entities:\n")
    for r in results:
        label = r.get("label", "")
        etype = r.get("type", "")
        source = r.get("source", r.get("source_url", "")) or "—"

        if mode == "semantic":
            score = r.get("score", 0)
            print(f"  [{etype:15}] {label}")
            print(f"                    similarity: {score:.3f} | source: {source}")
        elif mode == "hybrid":
            score = r.get("score", 0)
            match = r.get("match", "")
            print(f"  [{etype:15}] {label}")
            print(f"                    score: {score:.3f} ({match}) | source: {source}")
        else:
            conf = r.get("confidence", 0)
            print(f"  [{etype:15}] {label}")
            print(f"                    confidence: {conf:.2f} | source: {source}")


def display_paths(paths):
    """Pretty-print path results."""
    if not paths:
        print("No paths found.")
        return

    print(f"Found {len(paths)} paths:\n")
    for i, p in enumerate(paths, 1):
        labels = p["node_labels"]
        types = p["edge_types"]
        conf = p["path_confidence"]

        chain = []
        for j, label in enumerate(labels):
            chain.append(label)
            if j < len(types):
                chain.append(f" --[{types[j]}]--> ")

        print(f"  Path {i} (confidence: {conf:.2f}):")
        print(f"    {''.join(chain)}")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="Search the knowledge graph",
        epilog="Examples:\n"
               "  %(prog)s -q 'Robert Chen'\n"
               "  %(prog)s -q 'corruption' --mode semantic\n"
               "  %(prog)s -q 'financial fraud' --mode hybrid\n"
               "  %(prog)s --path 'Chen' 'Meridian'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--query", "-q", help="Search query")
    parser.add_argument("--path", "-p", nargs=2, metavar=("FROM", "TO"),
                        help="Find paths between two entities")
    parser.add_argument("--type", "-t", help="Filter by entity type")
    parser.add_argument("--limit", "-l", type=int, default=10, help="Max results")
    parser.add_argument("--mode", "-m", choices=["keyword", "semantic", "hybrid"],
                        default="keyword", help="Search mode (default: keyword)")
    args = parser.parse_args()

    if not args.query and not args.path:
        parser.error("Provide --query or --path")

    graph = Graph()

    if args.path:
        source, target = args.path
        print(f"Finding paths: {source} → {target}\n")
        paths = graph.find_path(source, target)
        display_paths(paths)
        graph.close()
        return

    if args.mode == "keyword":
        results = search_keyword(graph, args.query, args.type, args.limit)
    elif args.mode == "semantic":
        results = search_semantic(graph, args.query, args.limit)
    elif args.mode == "hybrid":
        results = search_hybrid(graph, args.query, args.type, args.limit)
    else:
        results = []

    display_results(results, args.mode)
    graph.close()


if __name__ == "__main__":
    main()
