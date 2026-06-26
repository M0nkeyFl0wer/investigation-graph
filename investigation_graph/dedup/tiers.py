"""
Structured-dedup resolution tiers (P2.4 / PUB.5).

A batch deduper produces a ``{record_id: cluster_id}`` map; ``make_cluster_tier``
turns ANY such map (deterministic or probabilistic) into a ResolutionTier that
merges each candidate onto an already-registered member of its cluster. So the same
lookup serves the cheap deterministic tier below AND Splink (see splink_tier.py).

**Empirical finding (scripts/eval_structured_dedup.py, 2026-06-23):** on single-field
clean-variant data ("Brightpath Advisors" vs "…LLC"), the deterministic
**normalized-name** tier closes the gap the exact+fuzzy cascade misses (recall up,
precision held at 1.0), while **Splink is undertrained** there — its F-S match
probabilities sit ~0.48 because there are no exact duplicates to learn from, so any
lift would come from the *blocking rule*, not the model. Conclusion: adopt the
deterministic tier for the common structured case; reserve Splink for **multi-field
messy records** (name+DOB+address, typos, missing fields) where cross-field
probabilistic weighting genuinely beats a single rule — gated behind a multi-field
eval, never shipped as "looks great on synthetic". Both still route merges through
the P1.3 review gate (a confident-but-wrong merge is the libel surface).
"""
from __future__ import annotations

import re
from collections import defaultdict

# ── Legal-entity suffix normalization ────────────────────────────────────────
# Goal: a bare company name and the SAME name carrying any legal-entity suffix
# normalize to one key ("Acme 7" == "Acme 7 LLC" == "Acme 7 Corporation"), WITHOUT
# over-merging genuinely distinct names ("Acme 1" != "Acme 10", "Jordan Lee 0" !=
# "Jordan Lee 7").
#
# Design choices that keep it GENERAL (not fixture-fitted) and precise:
#
#  * Comprehensive, DOCUMENTED suffix vocabulary (below), covering the common
#    English/US, European, and abbreviation forms a real registry feed mixes —
#    not a short hand-picked list. Adding a form here is the documented extension
#    point; the prior build fragmented because "Corporation"/"Company"/"GmbH"/
#    "LLP" were simply absent.
#  * Suffixes are stripped only from the END of the name (and may repeat, e.g.
#    "Foo Group Holdings Inc"). Legal suffixes are positionally terminal, so
#    end-anchored stripping equates the variants while never removing a token that
#    is part of the core name mid-string (e.g. it will not maul "Sons of Anarchy"
#    or a company literally named "Group Therapy Co" down to nothing meaningful).
#  * Punctuation/dotted forms are equated by de-punctuating BEFORE matching, so
#    "L.L.C." == "LLC", "& Sons" == "and Sons", "S.A." == "SA".
#  * Matching is whole-token and case-insensitive; multi-word suffixes ("& Sons")
#    are handled explicitly.
#
# We deliberately do NOT strip generic descriptors that distinguish real entities
# (e.g. "Bank", "Partners", "Capital") — only true legal-form designators.

# Single-token legal-form designators (each may be dotted/spaced in the raw text;
# de-punctuation collapses "l.l.c." -> "llc" before we match here).
_SUFFIX_TOKENS = frozenset({
    # US / general English forms and their abbreviations
    "llc", "llp", "lllp", "lp", "pllc", "pc", "pa",
    "inc", "incorporated",
    "corp", "corporation",
    "co", "company",
    "ltd", "limited",
    "plc",
    "lc",
    # NB: we deliberately do NOT strip business DESCRIPTORS like "Holdings",
    # "Group", "Partners", "Capital", "Bank" — they are not legal-entity FORMS and
    # they carry identity ("Apex Holdings" is a distinct entity from "Apex"). The
    # prior regex stripped "group/grp"; the existing test contract (test_dedup_tiers)
    # pins that "Apex Holdings Ltd" -> "apex holdings", i.e. only the legal form
    # "Ltd" comes off. Stripping descriptors would over-merge.
    # European / international legal forms
    "gmbh", "mbh", "ag", "kg", "kgaa", "ohg", "ug",          # German
    "sa", "sas", "sarl", "sca",                              # French / Romance
    "spa", "srl", "snc",                                      # Italian
    "nv", "bv", "cv",                                         # Dutch / Belgian
    "ab", "as", "asa", "oy", "oyj",                          # Nordic
    "pty", "pte", "bhd", "sdn",                               # Australian / SE-Asian
    "sl", "slu",                                              # Spanish
    "aps",                                                    # Danish
    "doo",                                                    # SE-European
    "ojsc", "oao", "zao", "ooo",                              # Russian transliterations
})

# Multi-word legal-form designators, matched as whole phrases at the end.
# (De-punctuation has already turned "& Sons" -> "and sons" by this point.)
_SUFFIX_PHRASES = (
    ("and", "sons"),   # "Smith & Sons" -> "smith"
    ("and", "son"),    # "Smith & Son"  -> "smith"
    ("and", "co"),     # "Smith & Co"
    ("and", "company"),
)


def _depunct(s: str) -> str:
    """Lowercase, turn '&' into the word 'and', drop all other punctuation, and
    collapse whitespace. Run BEFORE suffix matching so dotted/ampersand forms
    ("L.L.C.", "S.A.", "& Sons") compare equal to their plain spellings."""
    s = str(s).lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]", " ", s)      # strip remaining punctuation to spaces
    return " ".join(s.split())


def _strip_legal_suffixes(tokens: list[str]) -> list[str]:
    """Remove trailing legal-form designators (single-token and multi-word),
    repeatedly, from the END of an already-de-punctuated token list.

    End-anchored + repeated so chained forms collapse ("foo group holdings inc"
    -> "foo"), while a core-name token in the MIDDLE is never touched. We never
    strip the name down to empty: if stripping would remove everything, we keep
    the last meaningful state so distinct bare designators don't all collide on ""."""
    toks = list(tokens)
    changed = True
    while changed and toks:
        changed = False
        # Try multi-word phrases first (longest match wins over a single token).
        for phrase in _SUFFIX_PHRASES:
            n = len(phrase)
            if len(toks) > n and tuple(toks[-n:]) == phrase:
                toks = toks[:-n]
                changed = True
                break
        if changed:
            continue
        # Dotted/spaced abbreviation forms ("L.L.C." / "S.A.") de-punctuate to a
        # run of single-letter tokens ("l l c" / "s a"). Join a trailing run of
        # single letters and test the joined form against the suffix vocabulary, so
        # "L.L.C." == "LLC" and "S.A." == "SA". Only fires when the join is a known
        # legal form, so initials that are NOT a suffix (e.g. a name "J P Morgan")
        # are left intact.
        max_run = 0
        while max_run < len(toks) and len(toks[len(toks) - 1 - max_run]) == 1:
            max_run += 1
        # Try the longest joinable run down to 2 letters, requiring that something
        # remains in front (so we never consume a single-letter CORE token: "X B.V."
        # tries "xbv" (no), then "bv" (yes) and stops with "x" intact).
        matched = False
        for run_len in range(max_run, 1, -1):
            if len(toks) <= run_len:
                continue
            joined = "".join(toks[len(toks) - run_len:])
            if joined in _SUFFIX_TOKENS:
                toks = toks[:len(toks) - run_len]
                changed = matched = True
                break
        if matched:
            continue
        # Then a single trailing legal-form token — but only if something remains
        # in front of it, so a name that IS just "Inc" (degenerate) is preserved.
        if len(toks) > 1 and toks[-1] in _SUFFIX_TOKENS:
            toks = toks[:-1]
            changed = True
    return toks


def norm_name(s: str) -> str:
    """Canonical comparison key for a (company) name: lowercased, de-punctuated,
    with trailing legal-entity suffixes stripped. Equates a bare name with any
    legal-suffix variant while preserving distinctions that carry identity
    (trailing digits, distinct core words). See module header for the rationale."""
    tokens = _depunct(s).split()
    return " ".join(_strip_legal_suffixes(tokens))


def norm_dedupe(records: list[dict]) -> dict[str, str]:
    """Deterministic structured dedup: cluster records whose (entity_type,
    normalized-name) match. No training, no deps — the robust common-case tier.
    ``records``: ``[{"unique_id","name","entity_type"}, ...]`` ->
    ``{unique_id: cluster_id}``."""
    return {str(r["unique_id"]): f"{r['entity_type']}|{norm_name(r['name'])}"
            for r in records}


def make_cluster_tier(cluster_map: dict[str, str]):
    """Turn a ``{record_id: cluster_id}`` map (from any deduper) into a
    ResolutionTier. The first record of a cluster to resolve creates + registers;
    every later member merges onto it. Consults only already-registered ids, so it
    never invents a target."""
    members: dict[str, list[str]] = defaultdict(list)
    for rid, cid in cluster_map.items():
        members[cid].append(rid)

    def tier(candidate_id, name, entity_type, index, embedding=None):
        cid = cluster_map.get(candidate_id)
        if cid is None:
            return None
        registered = {i for i, _, _ in index.names}
        for rid in members[cid]:
            if rid != candidate_id and rid in registered:
                return rid
        return None

    return tier
