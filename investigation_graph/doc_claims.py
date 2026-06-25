"""Shared source of truth for the doc-claims gate.

Both ``tests/test_doc_claims.py`` (the pre-push gate + its meta-test) and
``scripts/audit.py`` (the recurrence net) import from here, so the rule the gate
enforces and the rule the audit reports can never drift apart. (Drift between a
check and the thing it derives from is the exact failure this whole apparatus
exists to prevent — so the patterns live in ONE place.)

The gate asserts a *substance* claim, not a string: **no user-facing doc may
present a LadybugDB edge-write defect as established fact.** A naive grep for
"corruption" would false-positive on the legitimate, different fact that *mixing
embedding models corrupts retrieval* (a dimension-mismatch issue, not the engine)
and would miss a rephrase that asserts the defect without the word. So we match
the claim SHAPE and whitelist the embedding-dimension fact plus any hedged /
debunking mention (SPEC §2.1's own correction lives in that register).
"""
from __future__ import annotations

import re
from pathlib import Path

# The user-facing surface — what a reader/reviewer takes as the tool's claims.
# SPEC.md and the ROADMAP are the technical record (allowed to discuss the
# disproof in detail) and are deliberately NOT gated here.
USER_FACING_DOCS: list[str] = [
    "README.md",
    "docs/FOR-INVESTIGATORS.md",
    "docs/database-choice.md",
    "requirements.txt",
    "pyproject.toml",
]

# Claim-SHAPE patterns: an edge/row/REL write corrupting/scrambling data, or the
# "corruption guard / corruption-guarded / edge-write corruption mode" framing.
DEFECT_AS_FACT: list[str] = [
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
WHITELIST: list[str] = [
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


def scan_text(text: str) -> list[tuple[int, str]]:
    """Return ``(line_no, line)`` for every line that asserts the defect as fact
    (matches the claim shape and is NOT whitelisted). Empty list = clean.
    """
    offenders: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if _DEFECT.search(line) and not _OK.search(line):
            offenders.append((i, line.strip()))
    return offenders


def scan_repo(repo_root: Path) -> dict[str, list[tuple[int, str]]]:
    """Scan every user-facing doc under ``repo_root``. Returns {rel_path:
    offenders} for docs that exist and have ≥1 offending line."""
    hits: dict[str, list[tuple[int, str]]] = {}
    for rel in USER_FACING_DOCS:
        p = repo_root / rel
        if not p.exists():
            continue
        offenders = scan_text(p.read_text(encoding="utf-8"))
        if offenders:
            hits[rel] = offenders
    return hits
