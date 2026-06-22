#!/usr/bin/env python3
"""
EVAL for deterministic ownership-control inference (P2.7 / interop brief G4).

Proves the inference *helps and is safe*, not just that it *runs*. It runs over the
ownership fixture G1 produces and scores the inferred control edges against a gold
expectation — crucially including the NEGATIVE case the review flagged: a
sub-threshold chain must produce NO control edge (don't manufacture false control).

Fixture ownership:
    Jane Roe --100%--> Brightpath --55%--> Harbor City RDA   => 55% effective  ✓ control
    Acme     --30%---> Brightpath --55%--> Harbor City RDA   => 16.5% effective ✗ below 25%

Run:  PYTHONPATH=. python scripts/eval_inference.py   (exit non-zero on divergence)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, ".")

from investigation_graph.infer import infer_control_edges
from investigation_graph.ontology import Ontology
from investigation_graph.processors import ingest_table
from investigation_graph.processors.tabular import MappingSpec

FIX = Path("tests/fixture_tabular")

# GOLD: the ONLY control edge that should be inferred (by label, for readability).
GOLD_INFERRED = {("Jane Roe", "Harbor City RDA")}
# And the one that must NEVER be inferred (sub-threshold) — the safety case.
MUST_NOT_INFER = ("Acme Holdings", "Harbor City RDA")


def _prf(pred: set, gold: set) -> tuple[float, float, float]:
    tp = len(pred & gold)
    p = tp / len(pred) if pred else (1.0 if not gold else 0.0)
    r = tp / len(gold) if gold else 1.0
    f = (2 * p * r / (p + r)) if (p + r) else 0.0
    return p, r, f


def run_eval() -> int:
    ont = Ontology()
    out = ingest_table(FIX / "ownership.csv",
                       MappingSpec.from_yaml(FIX / "ownership.map.yaml", ont),
                       ontology=ont)
    label = {e["id"]: e["label"] for e in out["entities"]}

    inferred, skipped = infer_control_edges(out["edges"], threshold=0.25)
    got = {(label[e.source_id], label[e.target_id]) for e in inferred}

    p, r, f = _prf(got, GOLD_INFERRED)
    safe = MUST_NOT_INFER not in got

    print("=== Ownership-control inference eval (P2.7) — threshold 25%, OWNS∘OWNS ===")
    for e in inferred:
        print(f"  INFER {label[e.source_id]} --controls--> {label[e.target_id]} "
              f"(effective {e.effective_pct:.1%}, {e.hops} hops, needs_review={e.needs_review})")
    print(f"  precision={p:.2f} recall={r:.2f} F1={f:.2f}")
    print(f"  NEGATIVE case (Acme 16.5% < 25%): "
          f"{'NOT inferred ✓' if safe else 'WRONGLY inferred ✗'}")
    print(f"  skipped (no share_pct): {len(skipped)}")

    ok = p == r == 1.0 and safe
    print("RESULT:", "PASS — controls the real chain, refuses the sub-threshold one"
          if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run_eval())
