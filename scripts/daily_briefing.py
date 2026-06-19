#!/usr/bin/env python3
"""Generate a daily briefing from the knowledge graph."""
import sys
sys.path.insert(0, ".")

from newsroom_graph import config
from newsroom_graph.briefing import generate_briefing
from newsroom_graph.graph import Graph

def main():
    # Read-only: briefings never write the graph.
    if not config.GRAPH_DIR.exists():
        print("No graph yet. Ingest documents first:  python scripts/ingest_folder.py")
        return
    graph = Graph(read_only=True)
    try:
        entities = graph.entity_count()
        edges = graph.edge_count()

        if entities == 0:
            print("Graph is empty. Ingest some documents first:")
            print("  python scripts/ingest_folder.py")
            return

        print(f"Analyzing graph ({entities} entities, {edges} edges)...")
        content = generate_briefing(graph)
        print(content)
        print("\nBriefing saved to briefings/ directory.")
    finally:
        graph.close()

if __name__ == "__main__":
    main()
