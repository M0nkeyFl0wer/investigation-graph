"""Tests for the PUB.5 resolution-tier seam (local consumer shim).

Proves: (1) the base cascade runs first and unchanged (exact match never reaches a
tier); (2) extra tiers run only on a miss; (3) a structured tier closes the exact
name-variant gap that exact+fuzzy alone misses (the Splink use case, demonstrated
with a suffix-stripping stand-in); (4) a tier returning None falls through to create.
"""
import re

from kg_common.write.dedup import ResolutionIndex

from investigation_graph.resolution import resolve_with_tiers

_SUFFIX = re.compile(r"\b(llc|ltd|inc|incorporated|limited|corp|co)\b\.?", re.I)


def _strip(s: str) -> str:
    return _SUFFIX.sub("", s).replace(",", " ").strip().lower()


def suffix_tier(name, entity_type, index, embedding=None):
    """Stand-in for a structured-dedup tier (Splink): match on the legal-suffix-
    stripped name. Real Splink would do Fellegi-Sunter on the DuckDB base."""
    target = _strip(name)
    for eid, surface, etype in index.names:
        if etype == entity_type and _strip(surface) == target:
            return eid
    return None


def _raising_tier(*a, **k):
    raise AssertionError("tier must not run when the base cascade already matched")


def _seed_brightpath():
    idx = ResolutionIndex()
    bid = resolve_with_tiers("bright", "Brightpath Advisors", "organization", idx)
    return idx, bid


def test_exact_match_short_circuits_before_any_tier():
    idx, bid = _seed_brightpath()
    # Exact match on the canonical name → returns bid; the (raising) tier is never
    # reached, because create_fn only fires on a full miss.
    got = resolve_with_tiers("dup", "Brightpath Advisors", "organization", idx,
                             tiers=(_raising_tier,))
    assert got == bid


def test_structured_tier_merges_variant_the_base_cascade_misses():
    idx, bid = _seed_brightpath()
    # "Brightpath Advisors LLC" misses exact+fuzzy (documented in the robustness
    # test). The suffix tier closes it → merges onto the existing id.
    got = resolve_with_tiers("v1", "Brightpath Advisors LLC", "organization", idx,
                             tiers=(suffix_tier,))
    assert got == bid


def test_without_the_tier_the_variant_creates_a_new_node_control():
    idx, bid = _seed_brightpath()
    # Same input, NO tier → the base cascade misses and a new id is created. This is
    # the gap the tier exists to close (and why the seam matters).
    got = resolve_with_tiers("v1", "Brightpath Advisors LLC", "organization", idx)
    assert got == "v1" and got != bid


def test_tier_returning_none_falls_through_to_create():
    idx, _ = _seed_brightpath()
    none_tier = lambda *a, **k: None  # noqa: E731 - trivial test tier
    got = resolve_with_tiers("fresh", "Wholly Unrelated Co", "organization", idx,
                             tiers=(none_tier,))
    assert got == "fresh"  # created, since neither base nor tier matched
