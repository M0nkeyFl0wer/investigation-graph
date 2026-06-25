"""Fail-closed gate: no user-facing doc may assert a LadybugDB edge-write DEFECT
as established fact — PLUS a meta-test that the gate itself still bites.

WHY THIS EXISTS
---------------
A disproven claim ("incremental edge writes into a populated REL table corrupt
other rows on this LadybugDB build") kept reappearing in user-facing docs after
the 2026-06-19 standalone repro disproved it (SPEC §2.1). It survived because it
was encoded in a *name* (`CORRUPTION GUARD`) that every honest description of the
code regenerated. This gate is the backstop so it can't silently re-assert.

The sweep rule is substance-not-string and lives in ``investigation_graph.doc_claims``
(shared with ``scripts/audit.py`` so the gate and the audit can't drift). See that
module for the rationale and the whitelist (the legitimate embedding-dimension
fact + hedged/debunking mentions).

THE META-TEST (audit-of-the-audit)
----------------------------------
``make audit`` and this gate are themselves derived representations of "reality
matches the docs" — subject to the exact law they enforce: a check that quietly
goes vacuous passes green while verifying nothing. So ``test_gate_still_bites``
feeds the sweep a deliberately NEW phrasing of the corruption claim (not a string
the patterns trivially contain) and asserts the sweep still catches it AND still
spares the legitimate embedding fact. The day someone loosens the patterns into
vacuity, this test goes red — the gate cannot rot silently.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from investigation_graph.doc_claims import USER_FACING_DOCS, scan_text

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize("rel", USER_FACING_DOCS)
def test_no_ladybug_edge_write_defect_asserted_as_fact(rel: str) -> None:
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    offenders = scan_text(path.read_text(encoding="utf-8"))
    assert not offenders, (
        f"{rel}: asserts a LadybugDB edge-write defect as fact "
        f"(the 2026-06-19-disproven claim) at: {offenders}. Reframe to the honest, "
        f"version-independent reason for reconstruct-and-swap — an idempotent "
        f"rebuild — not an engine-corruption claim. If this is the legitimate "
        f"embedding-dimension fact, it already names 'embedding' and is whitelisted."
    )


def test_gate_still_bites() -> None:
    """Meta-test: the sweep must catch a FRESH phrasing of the claim and must
    spare the legitimate embedding fact + the honest reframe. If this reds, the
    patterns have gone vacuous and the gate above is no longer protecting anything.
    """
    must_catch = [
        # phrasings the patterns must flag, none identical to a doc string
        "writes into an already-populated REL table will corrupt neighbouring rows",
        "the GraphWriter is a corruption-guard around a flaky edge store",
        "appending edges scrambles unrelated rows on reopen",
    ]
    must_spare = [
        "Mixing embedding models corrupts retrieval, so we pin one model",
        "the anomaly did not reproduce in isolation and is likely a measurement artifact",
        "the graph is rebuilt in one pass, so re-ingestion is idempotent",
    ]
    for s in must_catch:
        assert scan_text(s), f"gate went vacuous — failed to catch: {s!r}"
    for s in must_spare:
        assert not scan_text(s), f"gate over-reaches — wrongly flagged: {s!r}"
