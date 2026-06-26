"""Proof that the frontier tier's scoring path is complete — WITHOUT a real key.

We can't call a real frontier model here (no key), so to prove the wiring
(vocab derivation -> structured tool call -> parse -> exact-triple `_prf` against
gold) actually works end-to-end, we inject a STUB anthropic client via the
`_run_frontier(_client=...)` test seam.

The stub is an ORACLE:
  - on sentences that have a gold relationship, it returns exactly the gold
    triples (as if a perfect frontier model extracted them);
  - on the negation / no-relation / co-occurrence / hypothetical distractors,
    it returns NOTHING — exactly as a model correctly told "negation means no
    edge" should behave.

If the scoring path is wired correctly, an oracle that's right on real relations
and silent on the traps must score P=1.00, R=1.00, F1=1.00. That is NOT a fake
frontier number — it's a unit test of the code path the real model will run
through. It also proves the no-relation traps don't spuriously cost precision
(an always-emit oracle, tested below, is punished instead).

Run:  .venv/bin/python -m eval._frontier_oracle_check
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval.eval_edge_extraction import FIXTURE, _run_frontier  # noqa: E402


class _ToolUseBlock:
    """Mimics an anthropic SDK tool_use content block."""
    def __init__(self, payload):
        self.type = "tool_use"
        self.input = payload


class _Response:
    def __init__(self, content):
        self.content = content


class _Messages:
    """Mimics client.messages with a .create() that an oracle drives."""
    def __init__(self, decide):
        self._decide = decide

    def create(self, *, model, max_tokens, system, tools, tool_choice, messages):
        # Pull the sentence back out of the user message exactly as the real
        # call constructs it ("Sentence: <text>").
        user_text = messages[0]["content"]
        sentence = user_text.split("Sentence:", 1)[1].strip()
        triples = self._decide(sentence)
        return _Response([_ToolUseBlock({"triples": triples})])


class _StubClient:
    def __init__(self, decide):
        self.messages = _Messages(decide)


def _oracle_decide(sentence):
    """Perfect extractor: emit the gold triples for this sentence, nothing else.
    Returns triples in the tool's schema shape (list of {source,edge_type,target})."""
    for sent, gold in FIXTURE:
        if sent == sentence:
            return [{"source": s, "edge_type": t, "target": o} for (s, t, o) in gold]
    raise AssertionError(f"oracle saw an unexpected sentence: {sentence!r}")


def _always_emit_decide(sentence):
    """Adversarial: always claim a relation (a fixed bogus triple). This is the
    'always say yes, they're connected' extractor the distractors are meant to
    punish. It should score badly on PRECISION because of the no-relation traps."""
    return [{"source": "X", "edge_type": "PAID", "target": "Y"}]


def main() -> int:
    print("\nfrontier tier — scoring-path proof via injected oracle stub (no real key)\n")

    # 1. Oracle stub: correct on real relations, silent on the traps.
    kind, p, r, f = _run_frontier(_client=_StubClient(_oracle_decide))
    print(f"  oracle stub      -> {kind} P={p:.2f} R={r:.2f} F1={f:.2f}")
    assert kind == "SCORE", f"expected SCORE, got {kind}"
    assert (p, r, f) == (1.0, 1.0, 1.0), f"oracle should be perfect, got P={p} R={r} F1={f}"

    # 2. Always-emit stub: the no-relation distractors must drag precision down,
    #    proving the traps are load-bearing and the scoring isn't blindly lenient.
    kind2, p2, r2, f2 = _run_frontier(_client=_StubClient(_always_emit_decide))
    print(f"  always-emit stub -> {kind2} P={p2:.2f} R={r2:.2f} F1={f2:.2f}")
    assert kind2 == "SCORE"
    assert p2 < 0.5, f"always-emit should be punished on precision, got P={p2}"

    print("\n  PASS — scoring path is complete: an oracle scores 1.00/1.00/1.00, "
          "and an always-emit model is punished by the traps (P<0.50).")
    print("  (These are stub results proving the WIRING, not a real frontier number.)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
