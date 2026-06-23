"""Tests for structured-dedup tiers (P2.4 / PUB.5).

The deterministic normalized-name tier is the adopted common-case tier; these pin
that it merges variants WITHOUT false-merging distinct entities, and that it plugs
into the resolution seam. Splink is benchmarked in scripts/eval_structured_dedup.py
(undertrained on single-field data → reserved for multi-field), not asserted here.
"""
from kg_common.write.dedup import ResolutionIndex

from investigation_graph.dedup import make_cluster_tier, norm_dedupe, norm_name
from investigation_graph.resolution import resolve_with_tiers

RECORDS = [
    {"unique_id": "a", "name": "Brightpath Advisors", "entity_type": "organization"},
    {"unique_id": "b", "name": "Brightpath Advisors LLC", "entity_type": "organization"},
    {"unique_id": "c", "name": "Brightpath Advisors, L.L.C.", "entity_type": "organization"},
    {"unique_id": "d", "name": "Northwind Trading", "entity_type": "organization"},
    {"unique_id": "e", "name": "Brightpath Advisors", "entity_type": "person"},  # diff type!
]


def test_norm_name_strips_suffix_and_punctuation():
    assert norm_name("Brightpath Advisors, L.L.C.") == "brightpath advisors"
    assert norm_name("Apex Holdings Ltd") == "apex holdings"


def test_norm_dedupe_clusters_variants_but_not_distinct_or_cross_type():
    cmap = norm_dedupe(RECORDS)
    # a/b/c are one cluster; d is its own; e is a DIFFERENT cluster (person, not org).
    assert cmap["a"] == cmap["b"] == cmap["c"]
    assert cmap["d"] != cmap["a"]
    assert cmap["e"] != cmap["a"]  # cross-type never merges


def test_cluster_tier_merges_variants_through_the_seam():
    cmap = norm_dedupe(RECORDS)
    tier = make_cluster_tier(cmap)
    idx = ResolutionIndex()
    got = {r["unique_id"]: resolve_with_tiers(
        r["unique_id"], r["name"], r["entity_type"], idx, tiers=(tier,))
        for r in RECORDS}
    # a,b,c collapse to one canonical id; d and the person-e stay separate.
    assert got["a"] == got["b"] == got["c"]
    assert got["d"] != got["a"]
    assert got["e"] != got["a"]


def test_cluster_tier_never_invents_a_target():
    # A candidate whose cluster has no already-registered member returns None
    # (creates), never a fabricated id.
    tier = make_cluster_tier({"x": "cl1"})
    assert tier("x", "X", "organization", ResolutionIndex()) is None
