"""Consumer-side gate for the semantic (cosine) entity-resolution tier.

WHY THIS MODULE EXISTS — the "libel vector"
-------------------------------------------
The pipeline's entity resolver (``kg_common.write.dedup.resolve_or_create_semantic``,
called from ``investigation_graph.pipeline.ground_and_resolve``) runs a tiered
cascade: exact name → fuzzy (rapidfuzz) → **embedding cosine** → LLM adjudication.
When the embedding (cosine) tier fires, the duplicate is folded into the canonical
node and its edges are re-pointed — i.e. it AUTO-MERGES, and that graph write
happens BEFORE any human reviews ``merges.jsonl``.

A sibling project measured this cosine tier on real entity embeddings and found it
is NOT safe to auto-merge:

1. **Antonyms / stance embed as near-identical.** "Oppose provincial tree-cutting
   authority" vs "Support provincial tree-cutting authority" came back at cosine
   ~0.97. Auto-merging those two INVERTS a stance — it makes the graph assert the
   opposite of what a source said. For an investigative tool that is a libel-grade
   error. → Stance-bearing entity types must be excluded from the cosine tier
   ENTIRELY (no band, no review — just never let cosine touch them).

2. **Degenerate vectors.** ~1.2% of entity-vector PAIRS came back at essentially
   EXACTLY 1.000 — identical vectors, an embedding-store artifact (e.g. entities
   with empty/placeholder descriptions all embed to the same point). These produce
   confident-looking FALSE matches such as ``Parks Canada`` ↔ ``Transport Canada``
   at cosine 1.000. A genuine alias ("IBM" / "International Business Machines")
   lands around 0.93–0.99 — it is NEVER essentially exactly 1.0. → Treat cosine at
   or above ~0.9985 as a degenerate artifact, not an alias, and exclude it.

3. **Low precision (~30%)** even after restricting to mutual-NN + shared-token +
   the [0.93, 0.9985] band. Good enough for an OPT-IN review feed, NOT for an
   auto-merge. → Even a match that survives both exclusions above is REVIEW-ONLY:
   it is recorded for a human to confirm, and is NEVER applied to the graph
   automatically.

WHAT THIS MODULE DOES
---------------------
It is a pure, side-effect-free decision layer the pipeline can consult BEFORE it
accepts a cosine-tier merge. Given the two entities' types and the cosine score,
``classify_semantic_match`` returns one of three verdicts:

- ``EXCLUDE``  — drop the match outright (stance type, or degenerate ~1.0 band,
                 or below the alias floor). The graph is NOT touched.
- ``REVIEW``   — plausible alias in the safe band, but precision is too low to
                 trust: record it for human confirmation, do NOT auto-apply.
- (there is deliberately no ``AUTO_MERGE`` verdict — the whole point is that the
  cosine tier never auto-merges. The fuzzy/exact tiers, which are precise, are
  unaffected and continue to auto-merge in the pipeline as before.)

INTENDED CALL-SITE
------------------
See ``classify_semantic_match`` and ``gate_semantic_merge`` docstrings below for
exactly how the pipeline should wire this into ``ground_and_resolve`` so a
cosine-tier match is routed to review (or dropped) instead of auto-applied. This
module imports nothing from the pipeline and edits no graph — it only decides.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "STANCE_BEARING_TYPES",
    "ALIAS_BAND_LOWER",
    "ALIAS_BAND_UPPER",
    "SemanticVerdict",
    "is_stance_bearing_type",
    "in_alias_band",
    "is_degenerate_score",
    "classify_semantic_match",
    "gate_semantic_merge",
]


# ---------------------------------------------------------------------------
# Stance-bearing entity types
# ---------------------------------------------------------------------------
#
# A "stance-bearing" type is one whose entities encode a POSITION on something —
# support vs oppose, for vs against, approve vs reject. Two such entities can be
# semantic OPPOSITES while embedding almost identically (the cosine ~0.97
# Support/Oppose case above), so the cosine tier must never be allowed to merge
# them. This is type-level exclusion: if EITHER side of a candidate pair is a
# stance type, the cosine tier is off the table for that pair.
#
# NOTE ON THIS REPO'S ONTOLOGY: the investigation-generic ``ONTOLOGY.md`` in this
# repo does NOT currently declare a ``policy_position`` type — the closest
# stance-carrier here is ``claim`` (a factual assertion / quote / statement from a
# source, which can encode a position, e.g. "No money was exchanged" vs an
# opposing claim). A beat/sample ontology (e.g. a CPAWS/fed-filing policy beat)
# WOULD add ``policy_position``. So this set is a configurable, extensible
# DEFAULT, not a hard-coded truth:
#
#   - ``policy_position`` — included per the measured Support/Oppose failure, even
#     though the generic ontology here doesn't (yet) declare it, so the gate is
#     correct the moment a beat adds it.
#   - ``claim``           — this repo's actual stance-carrier; included so the gate
#     is protective under the shipped generic ontology too.
#   - ``stance`` / ``position`` — common alternative names a beat might use.
#
# HOW TO EXTEND for your beat: pass your own frozenset/iterable as the
# ``stance_types`` argument to ``is_stance_bearing_type`` /
# ``classify_semantic_match`` / ``gate_semantic_merge`` (they all default to this
# set). Keep type names lowercased — matching is case-insensitive but the set is
# stored lowercased for a cheap membership test. Add any type whose LABEL encodes
# a stance (the failure mode is "the label says support/oppose and the vectors
# don't separate them").
STANCE_BEARING_TYPES: frozenset[str] = frozenset({
    "policy_position",
    "claim",
    "stance",
    "position",
})


# ---------------------------------------------------------------------------
# The alias cosine band
# ---------------------------------------------------------------------------
#
# A genuine alias of the SAME entity (same type already enforced upstream by the
# resolver) lands in a band that is high-but-not-perfect:
#
#       below LOWER ───────[  ALIAS BAND  ]─────── above UPPER
#         reject          accept (REVIEW)            reject
#       (too weak)      ~0.93 .. ~0.9985        (degenerate ~1.0 artifact)
#
#   * ALIAS_BAND_LOWER (0.93) — below this, the pair is not similar enough to be a
#     plausible alias; the sibling-project precision measurement used 0.93 as the
#     floor of the usable band.
#   * ALIAS_BAND_UPPER (0.9985) — at/above this the score is essentially exactly
#     1.0, which a REAL alias never is; it is the degenerate-identical-vector
#     artifact (Parks Canada ↔ Transport Canada at 1.000). We treat the tiny top
#     slice [0.9985, 1.0] as "not an alias, a bug in the embedding store" and
#     reject it. 0.9985 leaves alias-grade scores like 0.998 inside the band while
#     catching the exact-1.0 cluster.
#
# Both bounds are module-level so a beat can tune them without editing logic; the
# classifier reads these defaults but every entry point also accepts explicit
# ``lower``/``upper`` overrides.
ALIAS_BAND_LOWER: float = 0.93
ALIAS_BAND_UPPER: float = 0.9985


# Use a tiny str-enum-like set of constants rather than an Enum import, to keep
# this module dependency-free and the verdicts trivially loggable/serializable as
# plain strings (they go into merges.jsonl-style review records).
@dataclass(frozen=True)
class _Verdicts:
    """The three possible outcomes of gating a cosine-tier match.

    Deliberately NO ``AUTO_MERGE`` — the cosine tier is never allowed to
    auto-apply; that is the entire safety property this module enforces.
    """
    EXCLUDE: str = "exclude"   # drop the match; do not touch the graph
    REVIEW: str = "review"     # plausible alias, record for a human, do NOT apply


# Singleton holding the verdict string constants (import as
# ``from .semantic_gate import SemanticVerdict`` and use ``SemanticVerdict.REVIEW``).
SemanticVerdict = _Verdicts()


def is_stance_bearing_type(
    entity_type: str,
    stance_types: frozenset[str] | set[str] | None = None,
) -> bool:
    """True iff ``entity_type`` encodes a stance/position and must therefore be
    excluded from the cosine tier ENTIRELY.

    Matching is case-insensitive and whitespace-trimmed. ``stance_types`` defaults
    to :data:`STANCE_BEARING_TYPES`; pass your beat's own set to extend/replace it
    (see that constant's docstring for how to extend).
    """
    if not entity_type:
        return False
    types = STANCE_BEARING_TYPES if stance_types is None else {t.lower() for t in stance_types}
    return entity_type.strip().lower() in types


def is_degenerate_score(
    cosine: float,
    upper: float = ALIAS_BAND_UPPER,
) -> bool:
    """True iff ``cosine`` is in the degenerate near-1.0 band (an identical-vector
    embedding-store artifact, NOT a real alias).

    A genuine alias never embeds at essentially exactly 1.0; scores at/above
    ``upper`` (default :data:`ALIAS_BAND_UPPER` = 0.9985) are the false matches the
    sibling project saw (e.g. Parks Canada ↔ Transport Canada at 1.000).
    """
    return cosine >= upper


def in_alias_band(
    cosine: float,
    lower: float = ALIAS_BAND_LOWER,
    upper: float = ALIAS_BAND_UPPER,
) -> bool:
    """True iff ``cosine`` is in the usable alias band ``[lower, upper)`` — high
    enough to be a plausible same-entity alias, but below the degenerate ~1.0
    artifact band. Half-open on the top so a degenerate exactly-``upper`` score is
    excluded (it belongs to :func:`is_degenerate_score`).
    """
    return lower <= cosine < upper


def classify_semantic_match(
    type_a: str,
    type_b: str,
    cosine: float,
    *,
    stance_types: frozenset[str] | set[str] | None = None,
    lower: float = ALIAS_BAND_LOWER,
    upper: float = ALIAS_BAND_UPPER,
) -> str:
    """Decide what to do with a single cosine-tier match between two entities.

    This is the core decision function. Given the two candidate entities' types
    and the cosine similarity the resolver computed between them, return a
    :class:`SemanticVerdict` constant:

    - :data:`SemanticVerdict.EXCLUDE` when the match must be dropped:
        * EITHER side is a stance-bearing type (Support/Oppose inversion risk), OR
        * the score is in the degenerate near-1.0 band (identical-vector artifact),
        * OR the score is below the alias floor (too weak to be an alias).
      In all three cases the graph is left untouched.

    - :data:`SemanticVerdict.REVIEW` when the match is a plausible alias inside the
      safe band ``[lower, upper)`` and neither side is a stance type. Cosine-tier
      precision (~30%) is too low to auto-apply, so this is RECORDED for a human to
      confirm and NEVER applied automatically.

    The verdict set intentionally contains no "auto-merge" — the cosine tier can,
    at best, suggest a review. (Exact/fuzzy tiers are precise and unaffected.)

    Ordering of the checks matters: stance exclusion is FIRST, so a stance-type
    pair is excluded even if its score happens to sit in the alias band — a stance
    inversion must never be downgraded to a mere review item.
    """
    # 1. Stance exclusion — highest priority. If either endpoint is a stance type,
    #    cosine is untrustworthy regardless of score (Support ~ Oppose at 0.97), so
    #    the tier is off the table for this pair.
    if is_stance_bearing_type(type_a, stance_types) or is_stance_bearing_type(type_b, stance_types):
        return SemanticVerdict.EXCLUDE

    # 2. Degenerate near-1.0 artifact — exclude (false match from identical vectors).
    if is_degenerate_score(cosine, upper):
        return SemanticVerdict.EXCLUDE

    # 3. Genuine alias band → eligible, but REVIEW-ONLY (never auto-applied).
    if in_alias_band(cosine, lower, upper):
        return SemanticVerdict.REVIEW

    # 4. Anything left is below the alias floor — too weak to be an alias. Exclude.
    return SemanticVerdict.EXCLUDE


def gate_semantic_merge(
    type_a: str,
    type_b: str,
    cosine: float,
    *,
    stance_types: frozenset[str] | set[str] | None = None,
    lower: float = ALIAS_BAND_LOWER,
    upper: float = ALIAS_BAND_UPPER,
) -> bool:
    """Convenience boolean wrapper for the pipeline's accept/reject decision.

    Returns ``True`` IFF a cosine-tier match should be ALLOWED TO AUTO-MERGE.
    Because this module's whole purpose is that the cosine tier never auto-merges,
    this currently ALWAYS returns ``False`` for a cosine-tier match — even an
    in-band, non-stance match is REVIEW-ONLY, not an auto-merge.

    It exists as a clean, intention-revealing call-site helper:

        INTENDED USE in ``investigation_graph.pipeline.ground_and_resolve``:

        Inside the entity-resolution loop, the resolver currently does:

            canon = resolve_or_create_semantic(..., embedding=embeddings.get(e["id"]), ...)
            if canon != e["id"]:   # a merge happened
                ... fold duplicate into canonical, re-point edges ...

        A cosine-tier merge is one where ``e["id"] in embeddings`` AND the merge
        was NOT already decided by the exact/fuzzy tiers. Before ACCEPTING such a
        merge, consult this gate with the two entities' types and the cosine score:

            if not gate_semantic_merge(kept_type, e["entity_type"], cosine_score):
                # do NOT fold; instead record the (kept, candidate, cosine, verdict)
                # pair into the review feed (e.g. merge_records with a
                # "review_only": True flag) and keep the candidate as its OWN node.
                ...continue without merging...

        Use :func:`classify_semantic_match` instead when you want the three-way
        verdict (to distinguish "dropped" from "queued for review") for the review
        feed; use this boolean when you only need accept/reject.
    """
    return classify_semantic_match(
        type_a, type_b, cosine,
        stance_types=stance_types, lower=lower, upper=upper,
    ) not in (SemanticVerdict.EXCLUDE, SemanticVerdict.REVIEW)
