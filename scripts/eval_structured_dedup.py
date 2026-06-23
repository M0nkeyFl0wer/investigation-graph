#!/usr/bin/env python3
"""
EVAL-DELTA for structured dedup tiers (P2.4 / PUB.5).

The acceptance bar (per review): a probabilistic deduper fails *confidently*, so a
tier is adopted only if it raises recall vs the base resolver on the SAME data
WITHOUT dropping precision — shown as a measured delta, never asserted. This runs
three resolvers over a labelled dataset of name variants + distinct entities and
reports the B-Cubed delta (the kg-common ER metric):

  1. base resolver (exact + fuzzy)
  2. base + deterministic normalized-name tier   <- the adopted common-case tier
  3. base + Splink Fellegi-Sunter tier            <- benchmarked honestly

Finding (single-field clean variants): the deterministic tier wins cleanly; Splink
is undertrained here (no exact dups to learn from) so it adds nothing over its
blocking — it is reserved for multi-field messy records. The eval PASSES on the
adopted deterministic tier; the Splink row is reported for honesty.

Run:  PYTHONPATH=. python scripts/eval_structured_dedup.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from kg_common.measure.er_quality import bcubed
from kg_common.write.dedup import ResolutionIndex

from investigation_graph.dedup import make_cluster_tier, norm_dedupe
from investigation_graph.resolution import resolve_with_tiers

_ORG_CLUSTERS = {
    "bright": ["Brightpath Advisors", "Brightpath Advisors LLC", "Brightpath Advisors, L.L.C."],
    "harbor": ["Harbor City Authority", "Harbor City Authority Inc", "Harbor City Authority, Inc."],
    "apex": ["Apex Holdings", "Apex Holdings Ltd", "Apex Holdings Limited"],
    "shell": ["Shell One", "Shell One Ltd", "Shell One Limited"],
    "zenith": ["Zenith Group", "Zenith Group LLC", "Zenith Group, LLC"],
}
_ORG_SINGLETONS = ["Northwind Trading", "Globex Corporation", "Initech Systems",
                   "Umbrella Holdings", "Wayne Enterprises", "Stark Industries",
                   "Acme Anvils", "Cyberdyne Robotics", "Soylent Foods", "Tyrell Group"]
_PERSON_CLUSTERS = {
    "mullen": ["Jonathan P Mullen", "Jonathan Mullen", "Jonathan P. Mullen"],
    "roe": ["Jane Roe", "Jane A Roe", "Jane A. Roe"],
}
_PERSON_SINGLETONS = ["David Holland", "Adrian Gobea", "Dana Foit", "Marie Curie"]


def _dataset():
    records, gold, n = [], {}, 0

    def add(name, etype, cluster):
        nonlocal n
        uid = f"r{n}"
        n += 1
        records.append({"unique_id": uid, "name": name, "entity_type": etype})
        gold[uid] = cluster

    for c, names in _ORG_CLUSTERS.items():
        for nm in names:
            add(nm, "organization", c)
    for nm in _ORG_SINGLETONS:
        add(nm, "organization", f"org_{nm}")
    for c, names in _PERSON_CLUSTERS.items():
        for nm in names:
            add(nm, "person", c)
    for nm in _PERSON_SINGLETONS:
        add(nm, "person", f"per_{nm}")
    return records, gold


def _resolve_all(records, tiers):
    idx, pred = ResolutionIndex(), {}
    for r in records:
        pred[r["unique_id"]] = resolve_with_tiers(
            r["unique_id"], r["name"], r["entity_type"], idx, tiers=tiers)
    return pred


def run_eval() -> int:
    records, gold = _dataset()
    base = bcubed(gold, _resolve_all(records, ()))
    norm = bcubed(gold, _resolve_all(records, (make_cluster_tier(norm_dedupe(records)),)))

    splink_row = None
    try:
        from investigation_graph.dedup import splink_dedupe
        sp = _resolve_all(records, (make_cluster_tier(splink_dedupe(records)),))
        splink_row = bcubed(gold, sp)
    except Exception as e:  # splink optional / may not be installed
        print(f"  (splink not benchmarked: {e})")

    print(f"=== Structured-dedup eval-delta (P2.4/PUB.5) — {len(records)} records, "
          f"B-Cubed vs base on the SAME data ===")
    print(f"  base (exact+fuzzy):   P={base.precision:.3f} R={base.recall:.3f} F1={base.f1:.3f}")
    print(f"  + norm-name tier:     P={norm.precision:.3f} R={norm.recall:.3f} F1={norm.f1:.3f}"
          f"   ΔR={norm.recall - base.recall:+.3f}")
    if splink_row:
        print(f"  + Splink F-S tier:    P={splink_row.precision:.3f} R={splink_row.recall:.3f} "
              f"F1={splink_row.f1:.3f}   ΔR={splink_row.recall - base.recall:+.3f}  "
              f"(undertrained on single-field clean variants -> reserved for multi-field)")

    # Adopted tier = deterministic norm: must beat base on recall, hold precision.
    ok = norm.recall > base.recall + 1e-9 and norm.precision >= base.precision - 1e-9
    print("RESULT:", "PASS — the deterministic norm-name tier raises recall without "
          "losing precision (merges still route through P1.3)" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_eval())
