#!/usr/bin/env python
"""``make audit`` — the recurrence net, NOT the novelty net.

WHAT THIS IS (read this; the scope is the point)
------------------------------------------------
This catches regressions of failures we have ALREADY found and fixed:
  * a user-facing doc re-asserting the disproven LadybugDB corruption claim,
  * the pipeline "passing" on an empty graph (the eval that greened on 0 edges),
  * grounding silently ceasing to quarantine a hallucinated entity,
  * the honest interop evals (FtM loss-ledger, dedup recall delta) rotting.

It does NOT find new failure shapes. Only an adversarial human/agent pass —
reading the claims against the code with intent to embarrass the docs — does that
(see the dated "adversarial audit" standing practice in docs/ROADMAP.md). Treating
a green ``make audit`` as proof the tool is sound is exactly how you'd rebuild this
project's whole lesson one level up: the automation is subject to the same law it
enforces — a check that quietly goes vacuous passes green while verifying nothing.

DESIGN RULES (each one a scar)
------------------------------
  * FLOORS, NOT COMPLETION. Every substance check asserts a NON-TRIVIAL floor
    (a quarantine actually fired; edges > 0) so "it ran" can never masquerade as
    "it worked."
  * DEGRADED != GREEN. The real-model floor probes responsiveness with a TIMEOUT
    (the real failure mode was contention, not absence). If the model can't be
    reached in time, the audit is DEGRADED (exit 2), never PASS.
  * SELF-REPORTED COVERAGE. It ends by printing what it did AND did NOT verify, so
    the gap (no extraction-quality metric, no retrieval relevance@k) is on screen
    every run, not hidden behind a checkmark. Same move as the FtM ledger refusing
    the vanity 1.00.
  * SHARED SOURCE. The doc-claims rule is imported from
    ``investigation_graph.doc_claims`` — the same module the pre-push gate uses —
    so the gate and the audit cannot drift.
  * META-TESTED. ``tests/test_doc_claims.py::test_gate_still_bites`` proves the
    sweep still catches a fresh phrasing; if it goes vacuous, that test reds.

Exit codes: 0 = PASS (every floor met, incl. a real-model run); 1 = FAIL (a floor
was violated); 2 = DEGRADED (a model-free floor passed but the real-model floor
could not be verified — honestly NOT green).
"""
from __future__ import annotations

import os

# Bound a single LLM chunk so the audit can never hang on a contended box (the
# real failure mode). Must be set before any project import reads config.
os.environ.setdefault("EXTRACT_TIMEOUT", "30")

import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PASS, FAIL, DEGRADED = "PASS", "FAIL", "DEGRADED"
_RED, _GRN, _YEL, _DIM, _OFF = "\033[31m", "\033[32m", "\033[33m", "\033[2m", "\033[0m"
_COLOR = {PASS: _GRN, FAIL: _RED, DEGRADED: _YEL}

# Each check appends (name, status, detail). not_verified holds the standing
# coverage gaps printed every run (things no check can honestly claim).
results: list[tuple[str, str, str]] = []
not_verified: list[str] = [
    "extraction quality — no metric exists (the LLM-extracted graph is never "
    "scored against a gold graph; only example-validated).",
    "retrieval relevance@k — no metric exists (search returns ≥1 hit; relevance "
    "is never measured).",
]


def add(name: str, status: str, detail: str) -> None:
    results.append((name, status, detail))
    print(f"  {_COLOR[status]}{status:8}{_OFF} {name}{_DIM} — {detail}{_OFF}")


def _eval(script: str) -> tuple[int, str]:
    """Run an eval script with the SAME interpreter; return (rc, combined output)."""
    p = subprocess.run(
        [sys.executable, str(REPO / "scripts" / script)],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    return p.returncode, (p.stdout + p.stderr)


# ── Check 1 — doc-claims sweep (model-free) ─────────────────────────────────
def check_doc_claims() -> None:
    from investigation_graph.doc_claims import scan_repo
    hits = scan_repo(REPO)
    if not hits:
        add("docs: no edge-write-defect claim asserted as fact", PASS,
            "0 offending lines across the user-facing surface")
    else:
        add("docs: no edge-write-defect claim asserted as fact", FAIL,
            f"a doc re-asserts the disproven claim: {hits}")


# ── Check 2 — grounding quarantine FLOOR (model-free, non-trivial) ──────────
def check_quarantine_floor() -> None:
    # A real entity (in the text) must survive; a hallucinated one (in no chunk)
    # must be quarantined. If grounding ever silently stops quarantining, this
    # reds instead of greening on a graph that quietly admits fabrications.
    from investigation_graph.pipeline import ground_and_resolve
    chunks = [{"id": "c1", "text": "Acme Corp paid a contractor in March 2024."}]
    entities = [
        {"id": "real", "entity_type": "organization", "label": "Acme Corp"},
        {"id": "ghost", "entity_type": "person", "label": "Zebediah Quagmire"},
    ]
    try:
        out, rep = ground_and_resolve(chunks, entities, [])
        ids = {e["id"] for e in out["entities"]}
        fired = rep.get("entities_quarantined", 0) >= 1
        if "real" in ids and "ghost" not in ids and fired:
            add("grounding quarantines a hallucinated entity", PASS,
                "kept the in-text entity, dropped the fabricated one")
        else:
            add("grounding quarantines a hallucinated entity", FAIL,
                f"kept={ids} quarantined={rep.get('entities_quarantined')} — the "
                f"quarantine gate did not fire as expected")
    except Exception as e:  # never let a check crash the audit into a false pass
        add("grounding quarantines a hallucinated entity", FAIL, f"raised {e!r}")


# ── Check 3 — deterministic edge FLOOR (model-free) ─────────────────────────
def check_deterministic_edges() -> None:
    # eval_tabular runs the REAL deterministic ingest path and internally requires
    # edge precision/recall = 1.00 on its gold — which is only possible with
    # edges > 0. So "RESULT: PASS" here is a genuine edges-exist floor with no LLM.
    try:
        rc, out = _eval("eval_tabular.py")
        ok = rc == 0 and "RESULT: PASS" in out
        add("deterministic ingest produces edges (eval_tabular)",
            PASS if ok else FAIL,
            "tabular path yields edges at P=R=1.00" if ok
            else f"rc={rc}; expected 'RESULT: PASS'")
    except Exception as e:
        add("deterministic ingest produces edges (eval_tabular)", FAIL, f"raised {e!r}")


# ── Check 4 — FtM loss-ledger intact ────────────────────────────────────────
def check_ftm_ledger() -> None:
    try:
        rc, out = _eval("eval_ftm.py")
        ok = rc == 0 and "RESULT: PASS" in out
        add("FtM crosswalk loss-ledger intact (eval_ftm)", PASS if ok else FAIL,
            "mappable lossless; unmappable documented" if ok else f"rc={rc}")
    except Exception as e:
        add("FtM crosswalk loss-ledger intact (eval_ftm)", FAIL, f"raised {e!r}")


# ── Check 5 — dedup recall delta still positive ─────────────────────────────
def check_dedup_delta() -> None:
    try:
        rc, out = _eval("eval_structured_dedup.py")
        # Pull the measured recall delta; floor it at > 0 (the tier must still help).
        import re
        delta = None
        for line in out.splitlines():
            mm = re.search(r"norm-name tier:.*ΔR=\+?(-?\d+\.\d+)", line)
            if mm:
                delta = float(mm.group(1))
        ok = rc == 0 and "RESULT: PASS" in out and (delta is None or delta > 0)
        add("dedup norm-name tier still raises recall (eval_structured_dedup)",
            PASS if ok else FAIL,
            f"ΔR={delta:+.3f} (>0)" if delta is not None and ok
            else f"rc={rc}; ΔR={delta}")
    except Exception as e:
        add("dedup norm-name tier still raises recall (eval_structured_dedup)", FAIL, f"raised {e!r}")


# ── Check 6 — REAL-MODEL extraction FLOOR (degraded-or-real, bounded) ───────
def check_real_extraction() -> None:
    # The one floor that needs a live model. Probe responsiveness with a TIMEOUT
    # first (contention, not absence, is the real failure). If the model can't be
    # reached in time → DEGRADED (never a silent green). If it IS reachable, the
    # real extraction code path must turn a relationship sentence into ≥1 edge
    # (edges come only from the LLM phase — Phase 1/2 produce entities, not edges).
    from investigation_graph import config
    try:
        import ollama
        t0 = time.time()
        client = ollama.Client(host=config.EXTRACT_ENDPOINT or None, timeout=25)
        client.embeddings(model=config.EMBEDDING_MODEL, prompt="audit responsiveness probe")
        probe_s = time.time() - t0
    except Exception as e:
        not_verified.append(
            f"real-model prose extraction — DEGRADED: model not reachable in time "
            f"({type(e).__name__}). Run on a box with a warm, uncontended Ollama.")
        add("real-model extraction yields an edge", DEGRADED,
            "model unreachable/contended — edge-from-prose floor NOT verified")
        return

    try:
        from investigation_graph.extract import Extractor
        from investigation_graph.ontology import Ontology
        ex = Extractor(Ontology())
        res = ex.extract_from_text(
            "Acme Corp paid John Smith $5,000 in March 2024.",
            source_url="audit://fixture", doc_id="audit",
        )
        n_edges = len(res.get("edges", []))
        if n_edges >= 1:
            add("real-model extraction yields an edge", PASS,
                f"probe {probe_s:.1f}s; produced {n_edges} edge(s) from a relationship sentence")
        else:
            # Model responded but produced no relationship — a real regression
            # signal (model too weak / extraction broken), NOT degraded.
            add("real-model extraction yields an edge", FAIL,
                f"model responsive ({probe_s:.1f}s) but extracted 0 edges from a "
                f"clear relationship sentence")
    except Exception as e:
        not_verified.append(f"real-model prose extraction — DEGRADED: {type(e).__name__} during extraction.")
        add("real-model extraction yields an edge", DEGRADED, f"extraction errored: {e!r}")


def main() -> int:
    print(f"\n{_DIM}make audit — recurrence net (regressions of known failures; "
          f"NOT a substitute for an adversarial pass){_OFF}\n")
    for chk in (check_doc_claims, check_quarantine_floor, check_deterministic_edges,
                check_ftm_ledger, check_dedup_delta, check_real_extraction):
        chk()

    statuses = [s for _, s, _ in results]
    if FAIL in statuses:
        overall, code = FAIL, 1
    elif DEGRADED in statuses:
        overall, code = DEGRADED, 2
    else:
        overall, code = PASS, 0

    verified = [n for n, s, _ in results if s == PASS]
    print(f"\n  {_DIM}VERIFIED ({len(verified)}):{_OFF}")
    for n in verified:
        print(f"    {_GRN}✓{_OFF} {n}")
    print(f"\n  {_DIM}NOT VERIFIED (coverage gaps — visible by design):{_OFF}")
    for n in not_verified:
        print(f"    {_YEL}•{_OFF} {n}")

    print(f"\n  STATUS: {_COLOR[overall]}{overall}{_OFF}  (exit {code})")
    if overall == DEGRADED:
        print(f"  {_YEL}A DEGRADED audit is NOT a pass — it ran without verifying the "
              f"real-model floor. Do not read this as green.{_OFF}")
    print(f"  {_DIM}This net catches recurrence only. New failure shapes need an "
          f"adversarial human/agent pass (ROADMAP: 'adversarial audit').{_OFF}\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
