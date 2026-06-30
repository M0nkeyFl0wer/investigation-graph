"""Tests for the deterministic address canonicalization that recovers the documented
"RECALL TRADE" in `splink_multifield` — abbreviation-only address variants now MERGE,
while genuinely different addresses (and the libel/human-judgment floor) still REVIEW.

These pin that the recovery is pure deterministic canonicalization (token substitution
+ the EXISTING exact-equality test) with NO fuzzy ratio: the only way two addresses
merge is if they are character-for-character equal AFTER canonicalization.
"""
from investigation_graph.dedup.splink_multifield import _decide, _norm_address


def _row(uid, *, reg_id, address, name="X", jurisdiction="", entity_type="organization"):
    """Build a normalized row dict shaped exactly as `splink_dedupe_multifield` feeds
    `_decide`: address already canonicalized, reg_id `None` for 'no reg_id'."""
    return {
        "unique_id": uid,
        "entity_type": entity_type,
        "reg_id": reg_id,                 # None == no reg_id (already validated)
        "address": _norm_address(address),
        "jurisdiction": jurisdiction,
        "name_norm": name.lower(),
        "name": name,
    }


# ── _norm_address: canonicalization is exact substitution, not fuzzy ──────────────
def test_norm_address_expands_street_suffix_abbreviation():
    # The headline case: "Ave" and "Avenue" canonicalize to the SAME string.
    assert _norm_address("270 Park Ave") == _norm_address("270 Park Avenue")
    assert _norm_address("270 Park Ave") == "270 park avenue"


def test_norm_address_handles_trailing_punctuation_and_directionals():
    # "Ave." == "Ave", and directionals + unit markers expand to full words.
    assert _norm_address("270 Park Ave.") == _norm_address("270 Park Avenue")
    assert _norm_address("1 N Main St") == "1 north main street"
    assert _norm_address("5 W 5th St Ste 200") == "5 west 5th street suite 200"


def test_norm_address_leaves_genuinely_different_addresses_different():
    # No dictionary entry bridges these — the canonical strings stay DIFFERENT, so the
    # exact-equality test downstream keeps the pair in REVIEW (no fuzzy bridging).
    assert _norm_address("270 Park Ave") != _norm_address("5th Avenue")
    # Different street NUMBER never merges (digits are never substituted).
    assert _norm_address("270 Park Ave") != _norm_address("207 Park Ave")
    # The "#5" vs "Suite 5" ambiguity is deliberately NOT bridged (documented boundary).
    assert _norm_address("270 Park Ave #5") != _norm_address("270 Park Ave Suite 5")


# ── _decide: the recovered recall, and the preserved libel/human-judgment floor ───
def test_same_regid_abbrev_address_variant_now_merges():
    """RECOVERED RECALL: same reg_id + ("270 Park Ave" vs "270 Park Avenue") -> MERGE.
    Before address canonicalization this routed to REVIEW (the documented trade)."""
    la = _row("a", reg_id="us-1", address="270 Park Ave")
    lb = _row("b", reg_id="us-1", address="270 Park Avenue")
    assert _decide(la, lb) == "merge"


def test_same_regid_genuinely_different_address_still_reviews():
    """PRESERVED FLOOR: same reg_id but a genuinely different address
    ("270 Park Ave" vs "5th Avenue") is NOT bridged by canonicalization, so it stays in
    REVIEW for a human (the data-error-vs-two-companies judgment) — never auto-merged."""
    la = _row("a", reg_id="us-1", address="270 Park Ave")
    lb = _row("b", reg_id="us-1", address="5th Avenue")
    assert _decide(la, lb) == "review"
