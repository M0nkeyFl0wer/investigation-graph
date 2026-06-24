"""
Lossless edge-merge guard for entity resolution.

WHY THIS EXISTS
---------------
When entity resolution collapses two duplicate nodes to one canonical id, the
pipeline re-points their edges to the canonical id and then drops self-loops
(see ``pipeline.ground_and_resolve`` — the loop under the comment "Re-point
edges to canonical ids; drop self-loops created by a merge", and the later
alias-merge re-point block). After re-pointing, two formerly-distinct edges can
land on the SAME ``(source_id, target_id, edge_type)`` triple. The naive graph
write keeps the first such edge and silently drops the rest.

That silent drop is a *data-loss bug*, not a cosmetic one. Campaign-finance
filings (what THIS repo ingests) carry per-filer aggregate FUNDS/contribution
edges — ``{amount_total, contribution_count, dates: [...]}``. If a donor's name
appears in three spellings (``Álvaro Sánchez`` / mojibake ``Alvaro SÃ¡nchez`` /
ASCII ``Alvaro Sanchez``) and each spelling carries its own aggregate edge to
the same party, a keep-first dedup throws away two of the three aggregates. In a
sibling project this lost one donor $6,650 across 10 contributions — money that
silently vanished from the graph during a routine merge.

This module is the GUARD that runs *before* the dedup so the loss is detected,
not discovered later (or never). It never mutates the pipeline's edges; it
SIMULATES the dedup and classifies every collision. The main agent wires the
result into ``pipeline.py`` — see the "WIRING" note at the bottom of this file.

WHAT COUNTS AS A COLLISION, AND WHEN IS IT SAFE
-----------------------------------------------
A collision is two or more edges that, AFTER re-pointing through the
duplicate->canonical id_map, share the same ``(source_id, target_id,
edge_type)`` key. We compare only the *data-bearing* properties of the edges in
a collision (provenance / bookkeeping props like ``source_url`` are ignored —
they differ all the time and carry no graph value):

  - **lossless** — the data-bearing props are identical (or absent) across the
    whole collision group. Collapsing to one edge loses nothing. Safe.
  - **lossy**    — the data-bearing props DIFFER. A keep-first dedup would throw
    real data away. This group must NOT be silently collapsed. We try to
    re-aggregate it; if that's not sound, it routes to human review.

RE-AGGREGATION CONTRACT (read this before trusting a summed total)
------------------------------------------------------------------
Re-aggregation is correct ONLY for *additive aggregates* — values where summing
the per-spelling edges reconstructs the true total:

  - additive numerics (``amount``, ``amount_total``, ``contribution_count``) are
    SUMMED across the group;
  - list props (``dates``) are UNIONed and de-duplicated (by the natural key of
    the element: a bare scalar by value, a dict by its ``(date, amount)`` pair
    when present, else by a stable repr);
  - ``currency`` is kept ONLY if every edge in the group agrees on it.

A collision is **un-reaggregatable** (-> route to review, never sum) when:

  - the edges disagree on ``currency`` — you cannot sum 100 USD and 100 CAD into
    a meaningful total; the right answer is a human decision, not arithmetic; or
  - a data-bearing prop conflicts but is NOT additive (e.g. ``share_pct`` — two
    different ownership percentages to the same target are a genuine
    contradiction, not two halves of one total). Summing those would invent a
    wrong number, which is worse than the original silent drop.

So the rule is: additive conflicts re-aggregate; everything else routes to
review. We never silently drop, and we never silently invent.

RETURN SHAPE
------------
``plan_lossless_merge(edges, id_map)`` returns a ``MergePlan`` with three
clearly separated buckets, each a list of edge dicts ready to write:

  - ``plan.safe_edges``        — the de-duplicated survivors that lost nothing.
                                 This includes every non-colliding edge passed
                                 straight through, every lossless collision
                                 collapsed to its single representative, and the
                                 single re-aggregated edge for each additive
                                 lossy collision.
  - ``plan.reaggregated_edges``— the subset of ``safe_edges`` that were produced
                                 by summing/union (exposed separately so the
                                 caller can log/report exactly what was merged).
  - ``plan.review_clusters``   — list of ``ReviewCluster``; each holds the full
                                 set of conflicting edges for one un-reaggregatable
                                 collision. These are NEVER dropped and NEVER
                                 written blind — the caller surfaces them for a
                                 human, exactly like ``report["merges"]`` already
                                 does for entity merges.

``plan.write_edges()`` is a convenience returning the edges that are safe to
write directly (== ``safe_edges``). The review clusters are deliberately NOT in
that list — handling them is a caller decision, so the loss can never happen by
omission.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Property classification ────────────────────────────────────────────────
# Data-bearing props whose disagreement makes a collision LOSSY. Splitting them
# by re-aggregation behaviour keeps the contract above honest in code.

# Numerics that are genuinely additive: summing per-spelling edges reconstructs
# the real total. These are the campaign-finance aggregates the bug threatens.
ADDITIVE_NUMERIC_PROPS = frozenset({"amount", "amount_total", "contribution_count"})

# List props that union (de-duped) across a group.
LIST_PROPS = frozenset({"dates"})

# Currency is data-bearing but NOT summable; it gates whether a numeric sum is
# even meaningful (you cannot add USD to CAD). Disagreement -> review.
CURRENCY_PROPS = frozenset({"currency"})

# Data-bearing numerics that are NOT additive — a per-target ratio/share. Two
# different values to the same target are a contradiction, not two halves of a
# whole; summing them invents a wrong number. Disagreement -> review.
NON_ADDITIVE_VALUE_PROPS = frozenset({"share_pct"})

# Everything that, if it differs, makes a collision lossy and must be reconciled
# (either re-aggregated or sent to review). The union of the above.
DATA_BEARING_PROPS = (
    ADDITIVE_NUMERIC_PROPS | LIST_PROPS | CURRENCY_PROPS | NON_ADDITIVE_VALUE_PROPS
)

# Provenance / bookkeeping props — explicitly NOT conflict-significant. They
# routinely differ between two spellings of the same donor and carry no graph
# value, so a difference here does NOT make a collision lossy.
PROVENANCE_PROPS = frozenset(
    {"source_url", "extraction_source", "evidence", "provenance"}
)


# ── Result types ────────────────────────────────────────────────────────────
@dataclass
class ReviewCluster:
    """One un-reaggregatable collision, held for human review (never dropped).

    ``key`` is the ``(source_id, target_id, edge_type)`` the edges collide on.
    ``edges`` is the full list of conflicting edges (post re-point). ``reason``
    is a short machine-readable code explaining why it can't be auto-merged.
    """

    key: tuple[str, str, str]
    edges: list[dict]
    reason: str  # e.g. "currency_mismatch", "non_additive_conflict:share_pct"


@dataclass
class MergePlan:
    """The outcome of simulating the post-resolution edge dedup.

    See module docstring for the contract on each bucket. ``safe_edges`` is the
    complete set of edges safe to write; ``review_clusters`` must be handled by
    the caller (surfaced to a human), never written blind.
    """

    safe_edges: list[dict] = field(default_factory=list)
    reaggregated_edges: list[dict] = field(default_factory=list)
    review_clusters: list[ReviewCluster] = field(default_factory=list)

    def write_edges(self) -> list[dict]:
        """Edges that are safe to write directly (== ``safe_edges``).

        Review clusters are intentionally excluded so a caller that forgets to
        handle them drops *nothing* silently — the conflicting edges simply
        aren't written until a human (or explicit caller policy) decides.
        """
        return list(self.safe_edges)

    @property
    def has_review(self) -> bool:
        return bool(self.review_clusters)


# ── Helpers ───────────────────────────────────────────────────────────────
def _edge_key(edge: dict) -> tuple[str, str, str]:
    """The dedup key the naive graph write collapses on."""
    return (edge.get("source_id"), edge.get("target_id"), edge.get("edge_type"))


def _data_props(edge: dict) -> dict:
    """The conflict-significant (data-bearing) subset of an edge's props.

    Provenance/bookkeeping and the structural keys (source_id/target_id/
    edge_type) are excluded — only values whose disagreement means real data
    loss remain.
    """
    return {
        k: v
        for k, v in edge.items()
        if k in DATA_BEARING_PROPS and v is not None
    }


def _props_identical(edges: list[dict]) -> bool:
    """True iff every edge in the group carries the SAME data-bearing props.

    Lists are compared as multisets-by-value via sorted repr so that ordering
    differences ([a, b] vs [b, a]) don't read as a conflict; identical content
    in any order is still identical.
    """

    def canon(props: dict) -> tuple:
        items = []
        for k in sorted(props):
            v = props[k]
            if isinstance(v, list):
                # Order-insensitive comparison of list contents.
                v = tuple(sorted(repr(x) for x in v))
            items.append((k, v))
        return tuple(items)

    first = canon(_data_props(edges[0]))
    return all(canon(_data_props(e)) == first for e in edges[1:])


def _elem_key(elem):
    """Natural de-dup key for one element of a list prop (e.g. ``dates``).

    A dict entry de-dupes by its ``(date, amount)`` pair when both are present
    (the campaign-finance shape: each contribution dated and sized); otherwise
    by a stable repr. A bare scalar de-dupes by its own value. This keeps the
    union honest: two filings reporting the same dated contribution collapse to
    one, but two genuinely distinct contributions on the same date survive.
    """
    if isinstance(elem, dict):
        if "date" in elem and "amount" in elem:
            return ("date+amount", elem["date"], elem["amount"])
        return ("repr", repr(sorted(elem.items())))
    return ("scalar", elem)


def _union_list(values: list[list]) -> list:
    """Union several list-prop values into one de-duplicated list.

    First occurrence wins for ordering stability (deterministic output across
    runs), de-duped by ``_elem_key``.
    """
    seen = set()
    out = []
    for lst in values:
        for elem in lst:
            k = _elem_key(elem)
            if k not in seen:
                seen.add(k)
                out.append(elem)
    return out


# ── Re-aggregation ──────────────────────────────────────────────────────────
def reaggregate(edges: list[dict]) -> tuple[dict | None, str | None]:
    """Try to fold an additive lossy collision into ONE re-aggregated edge.

    Contract (see module docstring): correct ONLY for additive aggregates.

    Returns ``(merged_edge, None)`` on success, or ``(None, reason)`` when the
    group is NOT soundly re-aggregatable and must route to review instead.

    Behaviour:
      - additive numerics (amount/amount_total/contribution_count) are SUMMED;
      - list props (dates) are UNIONed + de-duped;
      - currency is kept only if consistent; a mismatch -> ``(None,
        "currency_mismatch")``;
      - a NON-additive value prop (share_pct) that actually DIFFERS across the
        group -> ``(None, "non_additive_conflict:<prop>")`` — summing it would
        invent a wrong number, so it is a human decision, not arithmetic.

    The merged edge is built from a copy of the first edge (so it keeps the
    structural key + one set of provenance props) with the aggregated values
    overwritten. The original edges are never mutated.
    """
    # 1. A currency mismatch makes any numeric sum meaningless — bail to review
    #    BEFORE summing, so we never produce a total in mixed units.
    currencies = {
        e[c]
        for e in edges
        for c in CURRENCY_PROPS
        if e.get(c) not in (None, "")
    }
    if len(currencies) > 1:
        return None, "currency_mismatch"

    # 2. A non-additive value prop (e.g. share_pct) that genuinely differs is a
    #    contradiction, not an aggregate. Summing it is wrong; route to review.
    for prop in NON_ADDITIVE_VALUE_PROPS:
        distinct = {e[prop] for e in edges if e.get(prop) is not None}
        if len(distinct) > 1:
            return None, f"non_additive_conflict:{prop}"

    # 3. Sound to aggregate. Start from a copy of the first edge to preserve the
    #    structural key (source/target/type) and a representative provenance set.
    merged = dict(edges[0])

    # Sum every additive numeric that appears anywhere in the group.
    for prop in ADDITIVE_NUMERIC_PROPS:
        present = [e[prop] for e in edges if e.get(prop) is not None]
        if present:
            merged[prop] = sum(present)

    # Union + de-dupe every list prop that appears in the group.
    for prop in LIST_PROPS:
        present = [e[prop] for e in edges if isinstance(e.get(prop), list)]
        if present:
            merged[prop] = _union_list(present)

    # Currency was already verified consistent above; pin the agreed value.
    if currencies:
        for c in CURRENCY_PROPS:
            if any(e.get(c) for e in edges):
                merged[c] = next(iter(currencies))
                break

    return merged, None


# ── Public entry point ────────────────────────────────────────────────────
def plan_lossless_merge(edges: list[dict], id_map: dict[str, str]) -> MergePlan:
    """Simulate the post-resolution edge dedup and classify every collision.

    This is the primitive ``pipeline.py`` calls. It does NOT mutate ``edges`` or
    write anything — it returns a :class:`MergePlan` the caller uses to write the
    safe edges and surface the review clusters.

    Args:
        edges:  the edges to dedup. Each is a dict with at least ``source_id``,
                ``target_id``, ``edge_type`` and possibly data-bearing props.
                These are the edges *after* the pipeline has already re-pointed
                them through ``id_map`` — OR the pre-re-point edges plus the
                ``id_map`` to re-point with (we re-point here so the simulation
                matches exactly what the naive dedup would collapse).
        id_map: duplicate_id -> canonical_id from entity resolution. Endpoints
                are mapped through it before collision detection. Pass an empty
                dict if the edges are already re-pointed.

    Returns:
        A :class:`MergePlan`. See module docstring for the bucket semantics.
    """
    id_map = id_map or {}

    # Re-point endpoints exactly as the pipeline does, and drop self-loops a
    # merge created (mirrors the ``if src == tgt: continue`` in pipeline.py), so
    # our simulated key-space matches the real write's key-space precisely.
    repointed: list[dict] = []
    for ed in edges:
        src = id_map.get(ed.get("source_id"), ed.get("source_id"))
        tgt = id_map.get(ed.get("target_id"), ed.get("target_id"))
        if src == tgt:
            continue
        repointed.append({**ed, "source_id": src, "target_id": tgt})

    # Group edges by the naive dedup key, preserving first-seen order so the
    # output (and any kept-first representative) is deterministic across runs.
    groups: dict[tuple, list[dict]] = {}
    for ed in repointed:
        groups.setdefault(_edge_key(ed), []).append(ed)

    plan = MergePlan()
    for key, group in groups.items():
        if len(group) == 1:
            # No collision — the edge passes through untouched.
            plan.safe_edges.append(group[0])
            continue

        if _props_identical(group):
            # Lossless collision: data-bearing props agree (or are absent).
            # Collapsing to the first representative loses nothing.
            plan.safe_edges.append(group[0])
            continue

        # Lossy collision: a keep-first dedup WOULD drop real data. Try to
        # re-aggregate; if not sound, route the whole group to human review.
        merged, reason = reaggregate(group)
        if merged is not None:
            plan.safe_edges.append(merged)
            plan.reaggregated_edges.append(merged)
        else:
            plan.review_clusters.append(
                ReviewCluster(key=key, edges=list(group), reason=reason)
            )

    return plan
