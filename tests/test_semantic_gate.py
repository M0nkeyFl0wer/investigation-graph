"""Tests for the consumer-side semantic-tier gate (``investigation_graph.semantic_gate``).

These tests pin the four failure modes the gate exists to stop — the "libel
vector" cases measured by the sibling project on real embeddings:

1. **Stance inversion** — two OPPOSING stance entities embed at cosine 0.97;
   auto-merging would invert a stance, so they must be EXCLUDED (never merged,
   never even queued for review — stance exclusion is unconditional).
2. **Degenerate vector artifact** — a pair at cosine 1.000 is an identical-vector
   embedding-store artifact (e.g. Parks Canada ↔ Transport Canada), not a real
   alias; EXCLUDED.
3. **Legit alias** — a non-stance pair at cosine ~0.95 is a plausible alias, but
   cosine precision (~30%) is too low to auto-apply: eligible but REVIEW-ONLY.
4. **Below the band** — cosine 0.90 is too weak to be an alias; EXCLUDED.

The gate is pure (types + score in, verdict out), so these are plain unit tests
with no graph/embedding fixtures.
"""
from investigation_graph.semantic_gate import (
    ALIAS_BAND_LOWER,
    ALIAS_BAND_UPPER,
    SemanticVerdict,
    classify_semantic_match,
    gate_semantic_merge,
    in_alias_band,
    is_degenerate_score,
    is_stance_bearing_type,
)


# ---------------------------------------------------------------------------
# 1. Stance inversion — the headline libel case.
# ---------------------------------------------------------------------------

def test_opposing_stance_entities_at_high_cosine_are_excluded():
    """"Oppose ..." vs "Support ..." embed at ~0.97 but mean opposite things.

    Both are ``policy_position`` (the stance-bearing type), so even though 0.97
    sits inside the alias band, stance exclusion fires FIRST and the verdict is
    EXCLUDE — the match is dropped entirely, never auto-merged and never queued
    for review. Auto-merging here would invert the stance the source took.
    """
    verdict = classify_semantic_match("policy_position", "policy_position", 0.97)
    assert verdict == SemanticVerdict.EXCLUDE
    # And the boolean accept-gate must refuse it (no auto-merge).
    assert gate_semantic_merge("policy_position", "policy_position", 0.97) is False


def test_stance_exclusion_applies_if_either_side_is_a_stance_type():
    """The exclusion is per-pair: a stance type on EITHER endpoint poisons the
    pair, even if the other endpoint is an ordinary type and the score is band-legal."""
    assert classify_semantic_match("policy_position", "organization", 0.95) == SemanticVerdict.EXCLUDE
    assert classify_semantic_match("organization", "policy_position", 0.95) == SemanticVerdict.EXCLUDE


def test_claim_is_treated_as_stance_bearing_in_this_repos_ontology():
    """This repo's generic ONTOLOGY.md has no ``policy_position``; its actual
    stance-carrier is ``claim`` (a source assertion that can encode a position).
    The default stance set includes it, so the gate is protective under the
    shipped ontology too."""
    assert is_stance_bearing_type("claim") is True
    assert classify_semantic_match("claim", "claim", 0.96) == SemanticVerdict.EXCLUDE


def test_stance_type_check_is_case_insensitive_and_trimmed():
    assert is_stance_bearing_type("Policy_Position") is True
    assert is_stance_bearing_type("  CLAIM  ") is True
    assert is_stance_bearing_type("organization") is False
    assert is_stance_bearing_type("") is False


def test_stance_set_is_extensible_per_beat():
    """A beat can pass its own stance-type set; ``viewpoint`` isn't a default
    stance type, but becomes one when supplied — and the built-in defaults are
    then NOT implied (the caller's set replaces the default)."""
    custom = {"viewpoint"}
    assert is_stance_bearing_type("viewpoint", custom) is True
    assert is_stance_bearing_type("policy_position", custom) is False  # replaced, not merged
    # Routed through the classifier with the custom set:
    assert classify_semantic_match("viewpoint", "viewpoint", 0.97, stance_types=custom) == SemanticVerdict.EXCLUDE


# ---------------------------------------------------------------------------
# 2. Degenerate near-1.0 vectors — confident-looking FALSE matches.
# ---------------------------------------------------------------------------

def test_degenerate_identical_vectors_at_cosine_one_are_excluded():
    """cosine 1.000 between two DIFFERENT real entities (e.g. Parks Canada vs
    Transport Canada) is an identical-vector artifact, not an alias. Non-stance
    types, so this exercises the degenerate-band exclusion specifically."""
    verdict = classify_semantic_match("organization", "organization", 1.000)
    assert verdict == SemanticVerdict.EXCLUDE
    assert gate_semantic_merge("organization", "organization", 1.000) is False


def test_degenerate_band_boundary():
    """Scores at/above the upper bound are degenerate; just below it are still
    alias-band. The boundary is the documented ~0.9985 artifact line."""
    assert is_degenerate_score(ALIAS_BAND_UPPER) is True          # exactly at the line → degenerate
    assert is_degenerate_score(0.999) is True                     # inside the degenerate band
    assert is_degenerate_score(ALIAS_BAND_UPPER - 0.001) is False  # just below → not degenerate


# ---------------------------------------------------------------------------
# 3. Legit alias — eligible but REVIEW-ONLY (never auto-applied).
# ---------------------------------------------------------------------------

def test_legit_alias_in_band_is_review_only_not_auto_merge():
    """A non-stance pair at ~0.95 is a plausible alias ("IBM" /
    "International Business Machines"), but cosine precision is ~30% — too low to
    trust. Verdict is REVIEW (recorded for a human), and the boolean accept-gate
    still returns False (NOT auto-applied)."""
    verdict = classify_semantic_match("organization", "organization", 0.95)
    assert verdict == SemanticVerdict.REVIEW
    # REVIEW is explicitly NOT an auto-merge: the accept-gate refuses it.
    assert gate_semantic_merge("organization", "organization", 0.95) is False


def test_alias_band_membership():
    """The usable band is half-open ``[lower, upper)``: the lower bound is in,
    the upper bound is out (it belongs to the degenerate band)."""
    assert in_alias_band(ALIAS_BAND_LOWER) is True            # floor is inclusive
    assert in_alias_band(0.95) is True
    assert in_alias_band(ALIAS_BAND_UPPER) is False           # top is exclusive (degenerate)
    assert in_alias_band(ALIAS_BAND_LOWER - 0.001) is False   # below floor


# ---------------------------------------------------------------------------
# 4. Below the band — too weak to be an alias.
# ---------------------------------------------------------------------------

def test_below_band_cosine_is_excluded():
    """0.90 is below the 0.93 alias floor → not similar enough to be an alias.
    Non-stance types, so this isolates the below-floor exclusion."""
    verdict = classify_semantic_match("organization", "organization", 0.90)
    assert verdict == SemanticVerdict.EXCLUDE
    assert gate_semantic_merge("organization", "organization", 0.90) is False


# ---------------------------------------------------------------------------
# Cross-cutting: there is NO verdict that authorizes an auto-merge.
# ---------------------------------------------------------------------------

def test_no_cosine_score_or_type_combo_ever_authorizes_auto_merge():
    """The core safety property: across stance/non-stance types and the whole
    score range, the boolean accept-gate NEVER returns True for a cosine-tier
    match. The cosine tier can only ever suggest a review."""
    for score in (0.0, 0.5, 0.90, 0.93, 0.95, 0.998, 0.9985, 1.0):
        for t in ("organization", "person", "policy_position", "claim"):
            assert gate_semantic_merge(t, "organization", score) is False
