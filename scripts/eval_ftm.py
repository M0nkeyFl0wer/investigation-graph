#!/usr/bin/env python3
"""
EVAL for the FollowTheMoney crosswalk (P2.5 / interop brief G2).

A crosswalk's real metric is NOT "P=R=1.00" — it's a **loss ledger**: the mappable
types must round-trip lossless, AND the known-unmappable set must land in a
documented dropped bucket (not silently lost, not force-fit). This eval asserts
exactly that, against the real followthemoney model (pinned version).

Run:  PYTHONPATH=. python scripts/eval_ftm.py   (exit non-zero on divergence)
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from investigation_graph.interop import FTM_VERSION_VERIFIED, from_ftm, to_ftm

# A corpus spanning mappable + deliberately-unmappable items.
ENTITIES = [
    {"id": "p1", "entity_type": "person", "label": "Jane Roe"},
    {"id": "o1", "entity_type": "organization", "label": "Acme Corp"},
    {"id": "o2", "entity_type": "organization", "label": "Shell Ltd"},
    {"id": "a1", "entity_type": "asset", "label": "Parcel 44-201"},
    {"id": "c1", "entity_type": "claim", "label": "No money changed hands"},   # no FtM home
    {"id": "d1", "entity_type": "domain", "label": "fedfiling.com"},           # no FtM home
    {"id": "t1", "entity_type": "transaction", "label": "wire #9"},            # absorbed into Payment
]
EDGES = [
    {"source_id": "p1", "target_id": "o1", "edge_type": "OWNS", "share_pct": 55.0},
    {"source_id": "o1", "target_id": "o2", "edge_type": "FUNDED_BY",
     "amount": 50000.0, "currency": "USD"},
    {"source_id": "p1", "target_id": "o1", "edge_type": "EMPLOYED_BY"},
    {"source_id": "o1", "target_id": "o2", "edge_type": "ASSOCIATED_WITH"},   # -> UnknownLink
    {"source_id": "c1", "target_id": "c1", "edge_type": "CONTRADICTS"},       # no FtM home
    {"source_id": "p1", "target_id": "d1", "edge_type": "MENTIONED_IN"},      # no FtM home
]

EXPECT_DROPPED_ENTITY = {"c1", "d1", "t1"}
EXPECT_DROPPED_EDGE_TYPES = {"CONTRADICTS", "MENTIONED_IN"}


def run_eval() -> int:
    cw = to_ftm(ENTITIES, EDGES)
    back = from_ftm(cw.proxies)

    # 1. Mappable entities round-trip lossless (id + type preserved).
    src_ent = {e["id"]: e["entity_type"] for e in ENTITIES
               if e["id"] not in EXPECT_DROPPED_ENTITY}
    got_ent = {e["id"]: e["entity_type"] for e in back["entities"]}
    ent_ok = got_ent == src_ent

    # 2. The OWNS percentage and the Payment amount/currency survive the crossing.
    owns = next((e for e in back["edges"] if e["edge_type"] == "OWNS"), {})
    pay = next((e for e in back["edges"] if e["edge_type"] == "FUNDED_BY"), {})
    money_ok = (str(owns.get("share_pct")) == "55.0"
                and str(pay.get("amount")) == "50000.0"
                and pay.get("currency") == "USD")

    # 3. The loss ledger: the known-unmappable set is dropped (not silent, not forced).
    dropped_ent = {d["id"] for d in cw.dropped if d["kind"] == "entity"}
    dropped_edge_types = {d["edge"].split("-")[1].split("->")[0]
                          for d in cw.dropped if d["kind"] == "edge"}
    ledger_ok = (dropped_ent == EXPECT_DROPPED_ENTITY
                 and EXPECT_DROPPED_EDGE_TYPES <= dropped_edge_types)

    print(f"=== FtM crosswalk eval (P2.5) — verified against followthemoney {FTM_VERSION_VERIFIED} ===")
    print(f"  mappable entities round-trip lossless: {'✓' if ent_ok else '✗'} "
          f"({len(got_ent)}/{len(src_ent)})")
    print(f"  money survives (OWNS %, Payment amount/currency): {'✓' if money_ok else '✗'}")
    print("  LOSS LEDGER (no FtM home — dropped, not force-fit):")
    for d in cw.dropped:
        print(f"     - {d.get('id') or d.get('edge')}: {d['reason']}")
    print(f"  dropped set matches the documented boundary: {'✓' if ledger_ok else '✗'}")

    ok = ent_ok and money_ok and ledger_ok
    print("RESULT:", "PASS — mappable lossless, unmappable documented"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_eval())
