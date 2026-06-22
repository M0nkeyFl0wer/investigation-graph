"""Tests for deterministic ownership-control inference (P2.7 / interop brief G4).

These pin the SAFETY properties the review demanded: multiplicative threshold (no
false control from a sub-threshold chain), type-compatible chaining, no assumed
share, depth cap, and the inferred≠extracted tagging.
"""
from investigation_graph.infer import InferredEdge, infer_control_edges


def _owns(s, t, pct):
    return {"source_id": s, "target_id": t, "edge_type": "OWNS", "share_pct": str(pct)}


# The fixture ownership chain, by id.
CHAIN = [
    _owns("jane", "bright", 100),
    _owns("bright", "harbor", 55),
    _owns("acme", "bright", 30),
]


def test_infers_control_above_threshold_only():
    inferred, _ = infer_control_edges(CHAIN, threshold=0.25)
    pairs = {(e.source_id, e.target_id): e for e in inferred}
    # Jane 100%*55% = 55% >= 25% -> control. Acme 30%*55% = 16.5% < 25% -> none.
    assert ("jane", "harbor") in pairs
    assert ("acme", "harbor") not in pairs
    assert abs(pairs[("jane", "harbor")].effective_pct - 0.55) < 1e-9


def test_threshold_is_configurable():
    # Drop the threshold below 16.5% and Acme's indirect stake now qualifies.
    inferred, _ = infer_control_edges(CHAIN, threshold=0.10)
    pairs = {(e.source_id, e.target_id) for e in inferred}
    assert ("acme", "harbor") in pairs


def test_only_chains_OWNS_edges():
    # A non-OWNS edge in the path must not be composed (type-compatible only).
    mixed = [_owns("jane", "bright", 100),
             {"source_id": "bright", "target_id": "harbor",
              "edge_type": "EMPLOYED_BY", "share_pct": "55"}]
    inferred, _ = infer_control_edges(mixed, threshold=0.25)
    assert not inferred  # OWNS∘EMPLOYED_BY is never chained


def test_missing_share_is_skipped_not_assumed():
    # An OWNS edge with no share_pct cannot contribute — it must be skipped, never
    # assumed 1.0 (which would silently manufacture control).
    edges = [_owns("jane", "bright", 100),
             {"source_id": "bright", "target_id": "harbor", "edge_type": "OWNS"}]
    inferred, skipped = infer_control_edges(edges, threshold=0.25)
    assert not inferred
    assert len(skipped) == 1 and "share_pct" in skipped[0]["reason"]


def test_depth_cap_limits_chains():
    long_chain = [_owns("a", "b", 100), _owns("b", "c", 100), _owns("c", "d", 100)]
    shallow, _ = infer_control_edges(long_chain, threshold=0.25, max_depth=1)
    # With max_depth=1 no multi-hop inference is possible.
    assert not shallow
    deep, _ = infer_control_edges(long_chain, threshold=0.25, max_depth=6)
    assert ("a", "d") in {(e.source_id, e.target_id) for e in deep}


def test_inferred_edges_are_tagged_for_review_not_extracted():
    inferred, _ = infer_control_edges(CHAIN, threshold=0.25)
    rec = inferred[0].as_record()
    assert rec["provenance"] == "inferred"
    assert rec["extraction_source"] == "inferred"
    assert rec["needs_review"] is True
    assert "inferred control via" in rec["evidence"]


def test_aggregates_multiple_paths():
    # Two independent paths A->C should sum (beneficial ownership aggregates).
    diamond = [_owns("a", "b", 50), _owns("a", "c", 50),
               _owns("b", "d", 40), _owns("c", "d", 40)]
    # A->D via b: .5*.4=.2 ; via c: .5*.4=.2 ; sum = .4 >= .25 -> control.
    inferred, _ = infer_control_edges(diamond, threshold=0.25)
    pairs = {(e.source_id, e.target_id): e for e in inferred}
    assert ("a", "d") in pairs
    assert abs(pairs[("a", "d")].effective_pct - 0.40) < 1e-9


def test_inferrededge_record_shape():
    e = InferredEdge(source_id="x", target_id="y", effective_pct=0.6, hops=2,
                     chain=["x", "z", "y"], confidence=0.6)
    rec = e.as_record()
    assert rec["edge_type"] == "OWNS" and rec["effective_pct"] == 0.6
