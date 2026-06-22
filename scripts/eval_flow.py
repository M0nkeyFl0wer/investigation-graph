#!/usr/bin/env python3
"""
EVAL for money-flow tracing (P2.8 / interop brief G5).

Proves "follow the money" works and is currency-safe, not just that it runs. Traces
funds downstream from a source through a layering ledger and scores the discovered
fund chains against gold — including the safety case: a USD layering chain and a
separate EUR payment must NEVER be summed into one cross-currency number.

Ledger (tests/fixture_tabular/payments.csv):
    Apex Corp --100k USD--> Shell One --90k--> Shell Two --80k--> Final Beneficiary
    Apex Corp --5k EUR--> Direct Vendor

Run:  PYTHONPATH=. python scripts/eval_flow.py   (exit non-zero on divergence)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from investigation_graph.flow import trace_funds
from investigation_graph.ontology import Ontology
from investigation_graph.processors import ingest_table
from investigation_graph.processors.tabular import MappingSpec

FIX = Path("tests/fixture_tabular")

# GOLD: the fund chains (by label-path) + their currency that tracing should find.
GOLD = {
    (("Apex Corp", "Shell One Ltd"), "USD"),
    (("Apex Corp", "Shell One Ltd", "Shell Two Ltd"), "USD"),
    (("Apex Corp", "Shell One Ltd", "Shell Two Ltd", "Final Beneficiary"), "USD"),
    (("Apex Corp", "Direct Vendor"), "EUR"),
}


def run_eval() -> int:
    ont = Ontology()
    out = ingest_table(FIX / "payments.csv",
                       MappingSpec.from_yaml(FIX / "payments.map.yaml", ont),
                       ontology=ont)
    label = {e["id"]: e["label"] for e in out["entities"]}
    src = next(i for i, lab in label.items() if lab == "Apex Corp")

    chains = trace_funds(out["edges"], src)
    got = {(tuple(label[n] for n in c.path), c.currency) for c in chains}

    tp = len(got & GOLD)
    precision = tp / len(got) if got else 0.0
    recall = tp / len(GOLD)
    # Safety: no chain may be MIXED currency (the USD chain and EUR payment are
    # distinct paths and must never be combined into a cross-currency total).
    no_mixed = all(c.currency != "MIXED" for c in chains)
    full = next((c for c in chains if len(c.path) == 4), None)

    print("=== Money-flow eval (P2.8) — follow the money from Apex Corp ===")
    for c in sorted(chains, key=lambda c: -c.total_in):
        path = " -> ".join(label[n] for n in c.path)
        print(f"  {path}  [{c.currency}] in={c.total_in:,.0f} bottleneck={c.bottleneck}")
    print(f"  precision={precision:.2f} recall={recall:.2f}")
    print(f"  full layering chain bottleneck = "
          f"{full.bottleneck if full else None} (expect 80000)")
    print(f"  currency-safety (no MIXED sum): {'✓' if no_mixed else '✗'}")

    ok = (precision == recall == 1.0 and no_mixed
          and full is not None and full.bottleneck == 80000.0)
    print("RESULT:", "PASS — traces the layering chain, keeps currencies apart"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_eval())
