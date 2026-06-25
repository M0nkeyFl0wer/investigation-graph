"""Fail-closed gate: no user-facing doc may assert a LadybugDB edge-write DEFECT
as established fact.

WHY THIS EXISTS
---------------
A disproven claim — "incremental edge writes into a populated REL table corrupt
other rows on this LadybugDB build" — kept reappearing in user-facing docs even
after the 2026-06-19 standalone repro disproved it (SPEC §2.1). It survived
because it was encoded in a *name* (`CORRUPTION GUARD`) that every honest
description of the code regenerated, and a point-fix to one doc never reached the
derivatives. This gate is the backstop so it cannot silently re-assert.

SUBSTANCE, NOT STRING (deliberately)
------------------------------------
A naive grep for "corruption" would (a) false-positive on the *legitimate,
different* fact that mixing embedding models corrupts retrieval (a real
dimension-mismatch issue, nothing to do with the engine), and (b) miss a rephrase
that asserts the defect without the word. So this gate matches the *claim shape*
(an edge/row/REL write corrupting/scrambling data, or a "corruption guard"
framing) and WHITELISTS:
  - any line about *embedding* models / retrieval (the legit fact), and
  - any line that hedges or debunks the claim (SPEC §2.1's own correction, or a
    "suspected / did not reproduce / measurement artifact / not a bug" framing).

Scope is the user-facing surface only. SPEC.md and the ROADMAP are the technical
record and are *allowed* to discuss the disproof in detail, so they're excluded —
this gate guards what a reader/reviewer sees as the product's claims.

If this fails: a doc started asserting the edge-write defect as fact again.
Reframe to the honest, version-independent reason for reconstruct-and-swap
(idempotent rebuild), not an engine-corruption claim.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The user-facing surface (what a reviewer reads as the tool's claims).
USER_FACING_DOCS = [
    "README.md",
    "docs/FOR-INVESTIGATORS.md",
    "docs/database-choice.md",
    "requirements.txt",
    "pyproject.toml",
]

# Claim-SHAPE patterns: an edge/row/REL write corrupting/scrambling data, or the
# "corruption guard / corruption-guarded / edge-write corruption mode" framing.
DEFECT_AS_FACT = [
    r"corruption[- ]guard",
    r"corruption-guarded",
    r"edge[- ]write corruption",
    r"corruption mode",
    r"(?:edge|incremental|rel table|row)[^.\n]{0,50}\bcorrupt",
    r"\bcorrupt[^.\n]{0,50}(?:row|rows|edge|edges|rel table)\b",
    r"scrambl[^.\n]{0,40}(?:row|rows|edge|edges)",
]

# A matched line is OK if it ALSO carries one of these — the legitimate
# embedding-dimension fact, or a hedge/debunk of the engine claim.
WHITELIST = [
    r"embedding",                 # "mixing embedding models corrupts retrieval" — a real, different fact
    r"not substantiated",
    r"did ?n.?t reproduce",
    r"disproven",
    r"suspected",
    r"unverified",
    r"measurement artifact",
    r"not (?:a|an) .{0,20}bug",
    r"not as proof",
    r"idempotent",
]

_DEFECT = re.compile("|".join(DEFECT_AS_FACT), re.IGNORECASE)
_OK = re.compile("|".join(WHITELIST), re.IGNORECASE)


@pytest.mark.parametrize("rel", USER_FACING_DOCS)
def test_no_ladybug_edge_write_defect_asserted_as_fact(rel: str) -> None:
    path = REPO / rel
    if not path.exists():
        pytest.skip(f"{rel} not present")
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if _DEFECT.search(line) and not _OK.search(line):
            offenders.append((i, line.strip()))
    assert not offenders, (
        f"{rel}: asserts a LadybugDB edge-write defect as fact "
        f"(the 2026-06-19-disproven claim) at: {offenders}. Reframe to the honest, "
        f"version-independent reason for reconstruct-and-swap — an idempotent "
        f"rebuild — not an engine-corruption claim. If this is the legitimate "
        f"embedding-dimension fact, it already names 'embedding' and is whitelisted."
    )
