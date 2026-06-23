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

# Normalized name = lowercased, legal-suffix-stripped, de-punctuated.
_SUFFIX = re.compile(r"\b(l\.?l\.?c|ltd|inc|incorporated|limited|corp|co|group|grp)\b",
                     re.I)


def norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", _SUFFIX.sub("", str(s).lower())).strip()


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
