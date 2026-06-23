"""
The resolution-tier seam (PUB.5), as a LOCAL CONSUMER SHIM (no kg-common change).

kg-common's ``resolve_or_create_semantic`` is a hardwired cascade
(exact→fuzzy→embedding→``adjudicate_fn``) with no plugin point — and we must NOT
edit the freezing public ABC without the maintainer's nod. But its public
``create_fn`` parameter (called only on a *full miss*, before the entity is
created) is exactly the hook we need: we wrap it so an ordered list of extra
**resolution tiers** runs before create-on-miss. That gives us the single general
seam PUB.5 will land natively — built consumer-side first, so the eventual ABC
change is a lift-and-shift of this exact shape, not a redesign.

Two tiers will plug in here (decided in `docs/proposals/dedup-tools.md`):
- **Splink** (MIT, DuckDB-native) — the structured-dedup tier on the P2.4 tabular
  path: merges name variants the exact+fuzzy cascade misses ("Brightpath Advisors"
  vs "…LLC", which `tests/test_tabular_robustness.py` documents as the gap).
- **nomenklatura** (MIT, FtM-native) — the external-authority tier for P2.6: returns
  an OpenSanctions canonical id on a confirmed match, gated through P1.3 (its
  same/not-same/undecided Judgement model *is* the merge-review artifact). An
  external match is an ATTRIBUTED claim with OpenSanctions' name on it, never
  laundered into our own assertion.

CAUTION (review): a probabilistic tier (Splink) fails *confidently* — calibrated-
looking weights behind a wrong merge — which is the libel surface. So a tier's
output on the structured path must still route through the P1.3 merge-review gate,
and the bundled model must be measured on sme-eval against the base resolver on the
SAME data before it's trusted. The seam does not lower the bar; it just adds where
tiers attach.
"""
from __future__ import annotations

from typing import Callable, Optional, Protocol

from kg_common.write.dedup import ResolutionIndex, resolve_or_create_semantic


class ResolutionTier(Protocol):
    """A pluggable resolution tier. Return a canonical entity id to merge into, or
    ``None`` to fall through to the next tier / create. ``candidate_id`` identifies
    the record being resolved (a batch deduper like Splink needs it to find the
    record's precomputed cluster); ``index`` is the in-batch entity universe; an
    external-authority tier may ignore both and consult its own source (e.g. an
    OpenSanctions snapshot closed over at construction)."""

    def __call__(self, candidate_id: str, name: str, entity_type: str,
                 index: ResolutionIndex,
                 embedding: Optional[list[float]] = None) -> Optional[str]:
        ...


def resolve_with_tiers(
    candidate_id: str,
    name: str,
    entity_type: str,
    index: ResolutionIndex,
    *,
    tiers: tuple[ResolutionTier, ...] = (),
    create_fn: Optional[Callable[[], str]] = None,
    **base_kwargs,
) -> str:
    """``resolve_or_create_semantic`` + an ordered list of extra ``tiers``.

    The base cascade (exact/fuzzy/embedding/adjudicate) runs FIRST and unchanged.
    Only on a full miss do the extra tiers run, in order; the first to return an id
    wins, otherwise the real ``create_fn`` (or ``candidate_id``) creates. This is
    the PUB.5 seam — extra tiers attach AFTER the cheap deterministic ones, never
    replacing them.
    """
    real_create = create_fn or (lambda: candidate_id)
    embedding = base_kwargs.get("embedding")

    def tiered_create() -> str:
        for tier in tiers:
            match = tier(candidate_id, name, entity_type, index, embedding)
            if match is not None:
                return match  # a tier matched → re-point onto the existing id
        return real_create()

    return resolve_or_create_semantic(
        candidate_id, name, entity_type, index,
        create_fn=tiered_create, **base_kwargs,
    )
