"""GATE-R2 — measure how well each model tier extracts REAL relationships from
prose, on text with traps, so the prose-path claim is set by a number not a guess.

Plain English: the core value is turning sentences into "who did what to whom."
This gate scores three model tiers — the current small local model, a smarter
local approach (entity-pair classification + constrained decoding), and a frontier
model — against a labeled set that INCLUDES sentences with no relationship and with
negation, so an extractor that just always says "yes, they're connected" scores
badly. The output is the precision/recall number that decides what we can honestly
claim. It is degraded-aware: a tier it can't run is reported as not-verified, never
counted as a pass.

Run:  .venv/bin/python -m eval.eval_edge_extraction

Today this is expected to be RED: the smarter local extractor isn't built, the
frontier tier needs a key, and the small local model is contended — so there is no
usable number yet. That absence IS the finding.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Labeled fixture: (sentence, gold triples). Includes NO-RELATION distractors and
# a NEGATION case so "always extract an edge" is punished by precision.
FIXTURE: list[tuple[str, set[tuple[str, str, str]]]] = [
    ("Acme Corp paid John Smith $5,000 in March.", {("Acme Corp", "PAID", "John Smith")}),
    ("Globex Ltd owns Initech Systems outright.", {("Globex Ltd", "OWNS", "Initech Systems")}),
    ("Jane Doe is a director of Northwind Trust.", {("Jane Doe", "DIRECTOR_OF", "Northwind Trust")}),
    ("Acme Corp did NOT pay the contractor.", set()),                       # negation -> no edge
    ("The quarterly weather report was unremarkable.", set()),             # no entities, no edge
    ("Mary Lee and Tom Reed both attended the gala.", set()),             # co-occurrence, no stated relation
    ("Brightpath Advisors loaned $2M to Vertex Holdings.", {("Brightpath Advisors", "FUNDS", "Vertex Holdings")}),
    ("Initech Systems is headquartered in Dallas.", {("Initech Systems", "LOCATED_IN", "Dallas")}),
    ("No payment was ever made between the two firms.", set()),           # negation -> no edge
    ("Vertex Holdings acquired a 30% stake in Globex Ltd.", {("Vertex Holdings", "OWNS", "Globex Ltd")}),
]


def _prf(pred: set, gold: set) -> tuple[float, float, float]:
    tp = len(pred & gold)
    p = tp / len(pred) if pred else (1.0 if not gold else 0.0)
    r = tp / len(gold) if gold else 1.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f


def run_config(name: str):
    """Return ('SCORE', p, r, f) | ('MISSING', reason) | ('DEGRADED', reason)."""
    from investigation_graph import config
    if name == "pairwise-constrained":
        # The smarter local approach (R2's build target). Detect its presence.
        from investigation_graph.extract import Extractor
        if not hasattr(Extractor, "extract_pairwise"):
            return ("MISSING", "the entity-pair + constrained-decoding extractor is not built")
        # (when built, would run it over the fixture and score)
        return ("MISSING", "extract_pairwise present but unscored stub")
    if name == "frontier":
        import os
        if not (os.environ.get("FRONTIER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            return ("MISSING", "no frontier key set (FRONTIER_API_KEY/ANTHROPIC_API_KEY)")
        return ("MISSING", "frontier client not wired")
    if name == "3B-open-json":
        # Probe the local model with a timeout — contention, not absence, is the
        # real failure. If it can't answer fast, this tier is DEGRADED, not scored.
        try:
            import ollama
            ollama.Client(host=config.EXTRACT_ENDPOINT or None, timeout=20).generate(
                model=config.LOCAL_EXTRACTION_MODEL, prompt="ok", options={"num_predict": 2})
        except Exception as e:
            return ("DEGRADED", f"local model {config.LOCAL_EXTRACTION_MODEL} unreachable/contended ({type(e).__name__})")
        # reachable -> run the real extractor on the fixture and score exact triples
        from investigation_graph.extract import Extractor
        from investigation_graph.ontology import Ontology
        ex = Extractor(Ontology())
        ps = rs = fs = 0.0
        t0 = time.time()
        for sent, gold in FIXTURE:
            res = ex.extract_from_text(sent, source_url="audit://r2", doc_id="r2")
            ent_by_id = {e["id"]: e.get("label", "") for e in res.get("entities", [])}
            pred = {(ent_by_id.get(ed["source_id"], ed["source_id"]), ed["edge_type"],
                     ent_by_id.get(ed["target_id"], ed["target_id"])) for ed in res.get("edges", [])}
            p, r, f = _prf(pred, gold)
            ps, rs, fs = ps + p, rs + r, fs + f
            if time.time() - t0 > 120:  # hard wall
                return ("DEGRADED", "exceeded time wall mid-fixture")
        n = len(FIXTURE)
        return ("SCORE", ps / n, rs / n, fs / n)
    return ("MISSING", "unknown config")


def main() -> int:
    print("\nGATE-R2 — edge-extraction measurement (3 tiers, exact-triple, with distractors)\n")
    scored = 0
    for name in ("3B-open-json", "pairwise-constrained", "frontier"):
        out = run_config(name)
        if out[0] == "SCORE":
            _, p, r, f = out
            print(f"  \033[32mSCORED\033[0m   {name:22} P={p:.2f} R={r:.2f} F1={f:.2f}")
            scored += 1
        elif out[0] == "DEGRADED":
            print(f"  \033[33mDEGRADED\033[0m {name:22} {out[1]} — not verified")
        else:
            print(f"  \033[31mMISSING\033[0m  {name:22} {out[1]}")
    if scored >= 2:
        print("\n  RESULT: \033[32mPASS\033[0m — a real comparison exists to set the claim.")
        return 0
    print("\n  RESULT: \033[31mFAIL\033[0m — no usable comparison: the smarter local extractor "
          "isn't built and/or tiers are unavailable. There is no number to set the prose-path claim yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
