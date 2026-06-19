"""Full-pipeline eval — real execution on the bundled sample corpus.

The newmode protocol: exercise the ACTUAL running pipeline on a throwaway
provisioned instance, capture evidence, and gate on invariants. This runs the
real scope→ingest→extract→ground→build pipeline (real Ollama if available; it
degrades to deterministic+spaCy otherwise), then verifies — against the REAL
built graph — that the three safety gates held and the system is usable.

Evidence lands in eval/evidence/full-pipeline/. Exits non-zero if any check
fails (a true gate, not a print).

Run:  python -m eval.eval_full_pipeline
"""
from __future__ import annotations

import sys
from pathlib import Path

from eval.driver import Checks, run_capturing, throwaway_investigation

CORPUS = Path(__file__).resolve().parents[1] / "examples" / "sample-investigation"


def main() -> int:
    print("=== investigation-graph :: full-pipeline eval ===")
    with throwaway_investigation(CORPUS, "full-pipeline") as inv:
        n_docs = sum(1 for _ in inv.ingest_dir.iterdir())

        # ── Exercise the REAL ingest entry point ──────────────────────────
        from scripts.ingest_folder import main as ingest_main
        log = run_capturing(ingest_main)
        inv.write_evidence("ingest.log", log)

        # ── Gather evidence from the REAL built graph ─────────────────────
        from investigation_graph.chunk_store import ChunkStore
        from investigation_graph.graph import Graph
        from investigation_graph.ontology import Ontology

        onto = Ontology()
        store = ChunkStore(read_only=True)
        graph = Graph(read_only=True, ontology=onto)
        checks = Checks()
        try:
            n_chunks = store.chunk_count()
            n_entities = graph.entity_count()
            n_edges = graph.edge_count()
            n_graph_docs = graph.document_count()
            stats = {"documents_in": n_docs, "chunks": n_chunks,
                     "entities": n_entities, "edges": n_edges,
                     "graph_documents": n_graph_docs}
            inv.write_evidence("graph_stats.json", stats)
            print(f"  stats: {stats}")

            # Grade-locality on REAL edges: every edge must satisfy domain/range.
            edge_rows = graph.query(
                "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                "RETURN a.entity_type AS s, r.edge_type AS e, b.entity_type AS t"
            )
            violations = [r for r in edge_rows
                          if not onto.validate_grade(r["e"], r["s"], r["t"])]
            inv.write_evidence("grade_locality_report.json",
                               {"edges_checked": len(edge_rows),
                                "violations": violations})

            # Search evidence (FTS always; hybrid only if embeddings present).
            fts_hits = store.search_fts("Harbor", limit=5)
            inv.write_evidence("search_fts_Harbor.json", fts_hits)

            # Topology evidence.
            topo = {}
            try:
                from investigation_graph.topology import run_topology
                rep = run_topology(graph)
                topo = {"components": rep.component_count,
                        "communities": rep.community_count,
                        "bridges": len(rep.bridges)}
            except Exception as exc:  # noqa: BLE001
                topo = {"error": str(exc)}
            inv.write_evidence("topology.json", topo)

            # ── The gate ──────────────────────────────────────────────────
            checks.check("Ingestion complete" in log, "ingest ran to completion")
            checks.check(n_chunks > 0, f"chunks stored in DuckDB ({n_chunks})")
            checks.check(n_entities > 0, f"entities in graph ({n_entities})")
            checks.check(n_graph_docs == n_docs,
                         f"all documents in graph ({n_graph_docs}/{n_docs})")
            checks.check(len(violations) == 0,
                         f"grade-locality holds on all {len(edge_rows)} edges "
                         f"({len(violations)} violations)")
            checks.check(len(fts_hits) >= 1,
                         f"FTS search returns hits for 'Harbor' ({len(fts_hits)})")
            checks.check("error" not in topo, "topology analysis produced a report")
            checks.check("Quarantined" in log,
                         "grounding gate reported a quarantine line")
        finally:
            graph.close()
            store.close()

        summary = checks.summary()
        inv.write_evidence("summary.json", summary)
        print(f"\n  {summary['passed']}/{summary['total']} checks passed; "
              f"evidence in {inv.evidence_dir}")
        return 1 if checks.failed else 0


if __name__ == "__main__":
    sys.exit(main())
