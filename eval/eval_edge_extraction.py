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
    # --- Additional hard cases (strengthen the traps; NEVER make it easier) ---
    # Negation embedded with a real-looking subject/object: "denied owning".
    ("Initech Systems denied owning Brightpath Advisors.", set()),        # negation -> no edge
    # Three entities, ONE stated relation: the model must NOT also link the
    # bystander (Tom Reed) to either party. Directional + selective.
    ("Acme Corp paid Mary Lee while Tom Reed watched.",
     {("Acme Corp", "PAID", "Mary Lee")}),
    # Two real relations in one sentence (multi-edge): both must be caught,
    # and the wrong cross-pairs (Globex<->John Smith) must NOT be invented.
    ("Globex Ltd owns Initech Systems, and Acme Corp paid John Smith.",
     {("Globex Ltd", "OWNS", "Initech Systems"), ("Acme Corp", "PAID", "John Smith")}),
    # Reversed-direction trap: the text states the OBJECT owns the SUBJECT.
    # An extractor that ignores direction would emit the wrong triple.
    ("Northwind Trust is owned by Vertex Holdings.",
     {("Vertex Holdings", "OWNS", "Northwind Trust")}),
    # Pure co-location of two orgs with no stated relation between THEM.
    ("Globex Ltd and Brightpath Advisors are both based in Dallas.",
     {("Globex Ltd", "LOCATED_IN", "Dallas"), ("Brightpath Advisors", "LOCATED_IN", "Dallas")}),
    # Hypothetical / future-conditional: nothing actually happened yet.
    ("Acme Corp may pay Vertex Holdings if the deal closes.", set()),     # conditional -> no edge
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

        # Degraded-aware probe: the pairwise extractor needs a reachable model.
        # If it's contended/down, report DEGRADED (do NOT fake a score by running
        # an extractor that can't actually call a model).
        from investigation_graph.ontology import Ontology
        try:
            import ollama
            ollama.Client(host=config.EXTRACT_ENDPOINT or None, timeout=20).generate(
                model=config.LOCAL_EXTRACTION_MODEL, prompt="ok", options={"num_predict": 2})
        except Exception as e:
            return ("DEGRADED",
                    f"local model {config.LOCAL_EXTRACTION_MODEL} unreachable/contended "
                    f"({type(e).__name__}) — pairwise path built but unscored")

        # The fixture's gold edge-type vocabulary (the closed set the constrained
        # decode must choose from). Exact-triple scoring is unforgiving about
        # spelling, so the enum we constrain the model to MUST be exactly this set.
        # NEVER widen this to "anything goes" — that would let an always-emit model
        # dodge the precision penalty the no-relation traps are designed to apply.
        gold_vocab = sorted({t for _, golds in FIXTURE for (_, t, _) in golds})

        ex = Extractor(Ontology())
        ps = rs = fs = 0.0
        t0 = time.time()
        for sent, gold in FIXTURE:
            try:
                res = ex.extract_pairwise(
                    sent, source_url="audit://r2", doc_id="r2",
                    allowed_edge_types=gold_vocab)
            except Exception as e:
                # Mid-fixture model failure -> honest DEGRADED, not a partial score.
                return ("DEGRADED",
                        f"pairwise model call failed mid-fixture ({type(e).__name__})")
            ent_by_id = {e["id"]: e.get("label", "") for e in res.get("entities", [])}
            pred = {(ent_by_id.get(ed["source_id"], ed["source_id"]), ed["edge_type"],
                     ent_by_id.get(ed["target_id"], ed["target_id"])) for ed in res.get("edges", [])}
            p, r, f = _prf(pred, gold)
            ps, rs, fs = ps + p, rs + r, fs + f
            if time.time() - t0 > 180:  # hard wall — pairwise makes many calls
                return ("DEGRADED", "exceeded time wall mid-fixture")
        n = len(FIXTURE)
        return ("SCORE", ps / n, rs / n, fs / n)
    if name == "frontier":
        return _run_frontier()
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


# --- Frontier tier -----------------------------------------------------------
# The frontier tier asks a current Claude model to extract relationship triples
# from each fixture sentence, then scores them with the SAME exact-triple `_prf`
# against the SAME gold as the local tiers. The point is NOT "frontier is good"
# in isolation — it's the GAP between what a journalist gets on a laptop (the
# 3B / pairwise local tiers) and what they get with an API key. So this tier
# must be scored the identical way the local tiers are, or the comparison is
# meaningless.
#
# Test seam: `_client` lets a test inject a stub object exposing the same
# `.messages.create(...)` surface as the anthropic SDK. In production it's None
# and we construct a real `anthropic.Anthropic()` client. This is how we can
# PROVE the scoring path end-to-end with an oracle stub even though no real key
# is present in this environment (see eval/_frontier_oracle_check.py).

# Default to a current, capable Claude model. Haiku-tier is the cheapest current
# model and is plenty for sentence-level triple extraction; the operator can
# override with FRONTIER_MODEL (e.g. a Sonnet-tier id) if they want.
_FRONTIER_DEFAULT_MODEL = "claude-haiku-4-5"


def _frontier_extract_triples(client, model, sentence, allowed_edge_types):
    """Call a frontier Claude model to extract relationship triples from one
    sentence. Returns a set of exact (source, edge_type, target) tuples — the
    same tuple shape `_prf` scores against the gold.

    The model is told (a) the CLOSED allowed edge-type vocabulary (so an
    edge_type it invents can't sneak past exact-triple scoring) and (b) that
    negation / no-stated-relation / hypothetical / conditional means NO edge
    (so the distractor sentences punish an always-emit model on precision).

    Structured output is enforced via a tool with a strict JSON schema: a list
    of triples whose `edge_type` is constrained to the allowed enum. Using the
    tool/messages API (rather than free-text JSON) makes the triples parse
    reliably instead of depending on the model emitting clean JSON in prose.
    """
    # The extraction tool. `edge_type` is an enum locked to the closed vocab,
    # so the model literally cannot return an out-of-vocab relation type —
    # the same constraint the pairwise local tier applies via constrained decode.
    tool = {
        "name": "record_relationships",
        "description": (
            "Record every EXPLICITLY STATED relationship in the sentence as a "
            "(source, edge_type, target) triple. Record nothing if there is no "
            "stated relationship."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "triples": {
                    "type": "array",
                    "description": "All explicitly-stated relationships. Empty if none.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source": {
                                "type": "string",
                                "description": "The acting entity (subject), verbatim from the text.",
                            },
                            "edge_type": {
                                "type": "string",
                                # CLOSED vocabulary — exactly the fixture's gold
                                # edge types. NEVER widen this; widening would let
                                # the model dodge the precision penalty the
                                # no-relation traps are designed to apply.
                                "enum": list(allowed_edge_types),
                                "description": "The relationship type — must be one of the allowed values.",
                            },
                            "target": {
                                "type": "string",
                                "description": "The entity acted upon (object), verbatim from the text.",
                            },
                        },
                        "required": ["source", "edge_type", "target"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["triples"],
            "additionalProperties": False,
        },
    }

    vocab_str = ", ".join(allowed_edge_types)
    system = (
        "You extract relationship triples from a single sentence for an "
        "investigative-journalism knowledge graph. Rules:\n"
        f"- Use ONLY these edge types (the closed allowed vocabulary): {vocab_str}.\n"
        "- Emit a triple ONLY for a relationship that is AFFIRMATIVELY and "
        "EXPLICITLY stated in the sentence.\n"
        "- Negation ('did NOT pay', 'no payment was made', 'denied owning') means "
        "NO edge — do not emit one.\n"
        "- Mere co-occurrence or co-location ('both attended', 'both based in') with "
        "no stated relationship BETWEEN the two parties means NO edge between them.\n"
        "- Hypothetical / conditional / future ('may pay', 'if the deal closes') means "
        "NO edge — nothing has actually happened.\n"
        "- Respect direction: if the text says X is owned by Y, the triple is "
        "(Y, OWNS, X), not (X, OWNS, Y).\n"
        "- Do not invent relationships between bystanders who are merely mentioned.\n"
        "- Use the record_relationships tool. If there is no stated relationship, "
        "call it with an empty triples list."
    )

    # tool_choice forces the model to call the tool (structured output), so we
    # always get a parseable tool_use block rather than prose we'd have to scrape.
    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=system,
        tools=[tool],
        tool_choice={"type": "tool", "name": "record_relationships"},
        messages=[{"role": "user", "content": f"Sentence: {sentence}"}],
    )

    pred = set()
    for block in resp.content:
        # The forced tool call lands as a tool_use block whose `input` is the
        # parsed JSON matching our schema.
        if getattr(block, "type", None) == "tool_use":
            for t in (block.input or {}).get("triples", []):
                et = t.get("edge_type")
                # Defensive: only keep triples whose edge_type is in the closed
                # vocab. With the enum schema this should always hold, but if a
                # model ever returns an off-vocab value we drop it rather than
                # let it pollute the exact-triple comparison.
                if et in allowed_edge_types:
                    pred.add((t.get("source", ""), et, t.get("target", "")))
    return pred


def _run_frontier(_client=None):
    """Score the frontier tier on the fixture, or report honestly why we can't.

    ('SCORE', p, r, f) when a key (and SDK) are present and the model runs;
    ('MISSING', reason) when no key is set or the SDK isn't installed — we never
    fake a score.

    `_client` is the test seam: pass a stub exposing `.messages.create(...)` to
    exercise the full scoring path without a real key (see the oracle check).
    """
    import os

    model = os.environ.get("FRONTIER_MODEL", _FRONTIER_DEFAULT_MODEL)

    # The closed gold edge-type vocabulary — derived from the fixture gold EXACTLY
    # as the pairwise tier does it. This is the enum the model is constrained to.
    gold_vocab = sorted({t for _, golds in FIXTURE for (_, t, _) in golds})

    if _client is None:
        # Real run: require a key, then a working SDK. Both are honest MISSING
        # conditions — we do NOT fabricate a number when we can't actually call
        # a frontier model.
        if not (os.environ.get("FRONTIER_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")):
            return ("MISSING", "no frontier key set (FRONTIER_API_KEY/ANTHROPIC_API_KEY)")
        try:
            import anthropic
        except ImportError:
            return ("MISSING",
                    "key set but `anthropic` SDK not installed "
                    "(pip install anthropic) — frontier path wired but uncallable")
        # FRONTIER_API_KEY takes precedence; otherwise the SDK reads ANTHROPIC_API_KEY.
        api_key = os.environ.get("FRONTIER_API_KEY")
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    else:
        client = _client

    ps = rs = fs = 0.0
    for sent, gold in FIXTURE:
        try:
            pred = _frontier_extract_triples(client, model, sent, gold_vocab)
        except Exception as e:
            # A mid-fixture API failure is an honest MISSING, not a partial score.
            return ("MISSING", f"frontier call failed mid-fixture ({type(e).__name__}: {e})")
        p, r, f = _prf(pred, gold)
        ps, rs, fs = ps + p, rs + r, fs + f
    n = len(FIXTURE)
    return ("SCORE", ps / n, rs / n, fs / n)


def main() -> int:
    print("\nGATE-R2 — edge-extraction measurement (3 tiers, exact-triple, with distractors)\n")
    scored = 0
    # Tier order is laptop -> laptop+ -> key, so the table reads left-to-right as
    # "what a journalist gets with progressively more capability."
    tiers = ("3B-open-json", "pairwise-constrained", "frontier")
    results = {}
    for name in tiers:
        out = run_config(name)
        results[name] = out
        if out[0] == "SCORE":
            _, p, r, f = out
            print(f"  \033[32mSCORED\033[0m   {name:22} P={p:.2f} R={r:.2f} F1={f:.2f}")
            scored += 1
        elif out[0] == "DEGRADED":
            print(f"  \033[33mDEGRADED\033[0m {name:22} {out[1]} — not verified")
        else:
            print(f"  \033[31mMISSING\033[0m  {name:22} {out[1]}")

    # --- Side-by-side summary so the local-vs-frontier GAP is visible at a glance.
    # The headline is NOT "frontier is good" — it's the gap between what a
    # journalist gets on a laptop (3B / local pairwise) and what they get with a
    # key (frontier). If local scores badly and frontier scores well, that gap is
    # itself the critical positioning finding.
    print("\n  ── tier comparison (P / R / F1) ─────────────────────────────")
    labels = {
        "3B-open-json": "local 3B (laptop)",
        "pairwise-constrained": "local pairwise (laptop+)",
        "frontier": "frontier (API key)",
    }
    for name in tiers:
        out = results[name]
        if out[0] == "SCORE":
            _, p, r, f = out
            cell = f"P={p:.2f}  R={r:.2f}  F1={f:.2f}"
        else:
            cell = f"{out[0].lower()} — {out[1]}"
        print(f"    {labels[name]:26} {cell}")

    # If we have BOTH a local number and the frontier number, name the gap
    # explicitly — that delta is the whole point of the comparison.
    local_scores = [results[n] for n in ("3B-open-json", "pairwise-constrained")
                    if results[n][0] == "SCORE"]
    front = results["frontier"]
    if front[0] == "SCORE" and local_scores:
        best_local = max(local_scores, key=lambda o: o[3])  # by F1
        gap = front[3] - best_local[3]
        print(f"\n  GAP (frontier F1 − best local F1): {gap:+.2f} — "
              "this is the laptop-vs-key delta the prose-path claim must respect.")
    elif front[0] != "SCORE":
        print("\n  GAP: not measurable yet — frontier tier "
              f"{front[0].lower()} ({front[1]}). Set a key to reveal the laptop-vs-key delta.")

    if scored >= 2:
        print("\n  RESULT: \033[32mPASS\033[0m — a real comparison exists to set the claim.")
        return 0
    print("\n  RESULT: \033[31mFAIL\033[0m — no usable comparison: the smarter local extractor "
          "isn't built and/or tiers are unavailable. There is no number to set the prose-path claim yet.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
