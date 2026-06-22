"""Tests the inferred-edge review queue + the extracted-only query filter (P2.7 G4).

Inferred control must never leak into an extracted view, and must land in a review
queue for human confirmation (the P1.3 gate) rather than being asserted as fact.
"""
import json
from pathlib import Path

from investigation_graph.graph import build_graph
from investigation_graph.infer import InferredEdge, write_review_queue
from investigation_graph.ontology import Ontology
from investigation_graph.queries import QUERIES

ONT = Ontology()

ENTITIES = [
    {"id": "jane", "entity_type": "person", "label": "Jane Roe"},
    {"id": "bright", "entity_type": "organization", "label": "Brightpath"},
    {"id": "harbor", "entity_type": "organization", "label": "Harbor City RDA"},
    {"id": "acme", "entity_type": "organization", "label": "Acme Holdings"},
]
# Three extracted OWNS edges + ONE inferred one (provenance='inferred').
EDGES = [
    {"source_id": "jane", "target_id": "bright", "edge_type": "OWNS", "provenance": "tabular"},
    {"source_id": "bright", "target_id": "harbor", "edge_type": "OWNS", "provenance": "tabular"},
    {"source_id": "acme", "target_id": "bright", "edge_type": "OWNS", "provenance": "tabular"},
    {"source_id": "jane", "target_id": "harbor", "edge_type": "OWNS",
     "provenance": "inferred", "confidence": 0.55,
     "evidence": "inferred control via jane -> bright -> harbor (effective 55.0%)"},
]


def _open(path):
    try:
        import ladybug as lb
    except ImportError:
        import real_ladybug as lb
    return lb.Connection(lb.Database(str(path), read_only=True))


def _run(conn, cypher):
    r = conn.execute(cypher)
    out = []
    while r.has_next():
        out.append(r.get_next())
    return out


def test_extracted_view_excludes_inferred_edges(tmp_path):
    graph_dir = tmp_path / "graph.lbug"
    build_graph({"documents": [], "entities": ENTITIES, "edges": EDGES, "mentions": []},
                graph_dir=graph_dir, ontology=ONT)
    conn = _open(graph_dir)

    extracted = _run(conn, QUERIES["extracted_edges"])
    inferred = _run(conn, QUERIES["inferred_edges"])

    # 3 extracted (the directly-observed OWNS), 1 inferred — and the inferred
    # Jane->Harbor pair must NOT appear in the extracted view.
    assert len(extracted) == 3
    assert ("Jane Roe", "OWNS", "Harbor City RDA") not in {(r[0], r[1], r[2]) for r in extracted}
    assert len(inferred) == 1
    assert (inferred[0][0], inferred[0][2]) == ("Jane Roe", "Harbor City RDA")


def test_write_review_queue_persists_records(tmp_path):
    edges = [InferredEdge(source_id="jane", target_id="harbor", effective_pct=0.55,
                          hops=2, chain=["jane", "bright", "harbor"], confidence=0.55)]
    qpath = tmp_path / "review" / "inferred.jsonl"
    n = write_review_queue(edges, qpath)
    assert n == 1
    rec = json.loads(Path(qpath).read_text().splitlines()[0])
    assert rec["provenance"] == "inferred"
    assert rec["needs_review"] is True
    assert rec["source_id"] == "jane" and rec["target_id"] == "harbor"
