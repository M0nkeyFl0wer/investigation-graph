#!/usr/bin/env python3
"""
EVAL for deterministic tabular ingestion (P2.4 / interop brief G1).

Per the kg-ingestion skill and our own measured-DoD: a green unit test proves the
processor *runs*; this eval proves it *helps* — it pushes a tabular fixture through
the FULL safety pipeline (grounding → entity resolution → grade-locality → graph
build) and measures precision / recall / completeness of the resulting graph
against a hand-specified GOLD expectation. Deterministic ingestion should score a
perfect 1.0; anything less means the pipeline dropped or mangled a record.

Run:  PYTHONPATH=. python scripts/eval_tabular.py
Exit code is non-zero if precision or recall < 1.0 (so it can gate a commit/CI).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, ".")

from investigation_graph.graph import build_graph
from investigation_graph.ontology import Ontology
from investigation_graph.pipeline import ground_and_resolve
from investigation_graph.processors import maybe_ingest_tabular

FIX = Path("tests/fixture_tabular/ownership.csv")

# GOLD — what a correct graph MUST contain for this fixture (hand-specified).
GOLD_ENTITIES = {
    ("Jane Roe", "person"),
    ("Brightpath Advisors", "organization"),
    ("Harbor City RDA", "organization"),
    ("Acme Holdings", "organization"),
}
GOLD_EDGES = {
    ("Jane Roe", "OWNS", "Brightpath Advisors"),
    ("Brightpath Advisors", "OWNS", "Harbor City RDA"),
    ("Acme Holdings", "OWNS", "Brightpath Advisors"),
}


def _prf(pred: set, gold: set) -> tuple[float, float, float]:
    """Precision, recall, F1 of a predicted set against gold."""
    tp = len(pred & gold)
    precision = tp / len(pred) if pred else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def _open(path):
    try:
        import ladybug as lb
    except ImportError:
        import real_ladybug as lb
    return lb.Connection(lb.Database(str(path), read_only=True))


def run_eval() -> int:
    ont = Ontology()
    doc_id, source_url = "evaltab", str(FIX)
    staged = maybe_ingest_tabular(FIX, doc_id, source_url, ontology=ont)
    assert staged is not None, "fixture should be recognized as tabular"

    # Push through the SAME safety pipeline real ingestion uses (no shortcuts):
    # grounding gate + entity resolution, then the reconstruct-and-swap build.
    chunks = [{"id": c["id"], "text": c["body"]} for c in staged["chunks"]]
    build_records, report = ground_and_resolve(chunks, staged["entities"],
                                               staged["edges"])
    mentions = [{"entity_id": e["id"], "doc_id": e.get("doc_id")}
                for e in build_records["entities"] if e.get("doc_id")]
    for e in build_records["entities"]:
        e.pop("doc_id", None)
    for ed in build_records["edges"]:
        ed.pop("doc_id", None)

    with tempfile.TemporaryDirectory() as tmp:
        graph_dir = Path(tmp) / "graph.lbug"
        build_graph({"documents": [{"id": doc_id, "path": source_url}],
                     "entities": build_records["entities"],
                     "edges": build_records["edges"], "mentions": mentions},
                    graph_dir=graph_dir, ontology=ont)
        conn = _open(graph_dir)

        def q(c):
            r = conn.execute(c)
            out = []
            while r.has_next():
                out.append(r.get_next())
            return out

        got_entities = {(r[0], r[1]) for r in
                        q("MATCH (e:Entity) RETURN e.label, e.entity_type")}
        got_edges = {(r[0], r[1], r[2]) for r in
                     q("MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                       "RETURN a.label, r.edge_type, b.label")}

    ep, er, ef = _prf(got_entities, GOLD_ENTITIES)
    dp, dr, df = _prf(got_edges, GOLD_EDGES)
    quarantined = report["entities_quarantined"] + report["edges_quarantined"]

    print("=== Tabular ingestion eval (P2.4) — through grounding+ER+grade-locality+build ===")
    print(f"  entities:  P={ep:.2f} R={er:.2f} F1={ef:.2f}  ({len(got_entities)} built)")
    print(f"  edges:     P={dp:.2f} R={dr:.2f} F1={df:.2f}  ({len(got_edges)} built)")
    print(f"  quarantined (grounding gate): {quarantined}")
    print(f"  skipped (bad rows): {len(staged['skipped'])}")

    # Completeness gate (skill): the whole entity + edge layers must be present.
    ok = ep == er == dp == dr == 1.0 and not staged["skipped"]
    print("RESULT:", "PASS — deterministic graph matches gold exactly" if ok
          else "FAIL — graph diverged from gold")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_eval())
