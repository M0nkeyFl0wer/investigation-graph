#!/usr/bin/env python3
"""
eval_gates.py — automated eval-gates for the Fed Filing investigation case.

Three independent gates, each a subcommand, each printing a clear PASS/FAIL with
details and returning 0 (pass) / 1 (fail). `--all` runs all three and fails if
any one fails. These are meant to run in CI / a gated review before the public
case study or the companion graph is shipped:

  provenance-linkage   The court-grade keystone. Every artifact the PRIVATE
                       provenance ledger (report-private/REPORT.md §7) cites must
                       (a) exist in the evidence manifest, (b) have its file on
                       disk under the evidence root, and (c) re-hash to the exact
                       sha256 the manifest recorded. A broken link = a claim with
                       no verifiable chain of custody.

  ledger-completeness  Every ledger row's Status must be in a known closed set.
                       A row still sitting at plain "UNVERIFIED" with no captured
                       artifact is an un-actioned claim and fails the gate.

  minimization         No PRIVATE token (home address / family name / trust street
                       / course material) may appear in a PUBLIC (git-tracked)
                       file. Fails CLOSED if the denylist is missing or empty.

Read-only with respect to the evidence manifest, sources.json, and report-private/
— this tool only reads them. It writes nothing.

Usage:
  python scripts/eval_gates.py provenance-linkage
  python scripts/eval_gates.py ledger-completeness
  python scripts/eval_gates.py minimization
  python scripts/eval_gates.py --all
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from investigation_graph.capture import EvidenceManifest
from investigation_graph.capture.manifest import sha256_file

# --- repo-relative defaults -------------------------------------------------
# Resolve paths relative to the repo root (this file lives in <root>/scripts/),
# so the gates work regardless of the caller's current working directory.
REPO_ROOT = Path(__file__).resolve().parent.parent
CASE_ROOT = REPO_ROOT / "examples" / "fedfiling-case"
EVIDENCE_ROOT = CASE_ROOT / "evidence"
LEDGER_PATH = CASE_ROOT / "report-private" / "REPORT.md"
DENYLIST_PATH = REPO_ROOT / "scripts" / "minimization_denylist.txt"

# Files outside the case dir that are still "public" and worth minimization-scanning.
EXTRA_PUBLIC_FILES = [REPO_ROOT / "ONTOLOGY.md", REPO_ROOT / "README.md"]

# Closed set of allowed Status values (case-insensitive). A row's Status cell is
# normalized (decoration stripped) and must START WITH one of these.
ALLOWED_STATUSES = {
    "VERIFIED",
    "CORROBORATED",
    "CAPTURED",
    "INFERRED",
    "REFUTED",
    "DRAFT-ONLY",
    "GAP",
    "UNSUPPORTED",
    # Workflow synonyms that map onto the closed set (the live ledger uses a few
    # decorated variants; treat each as the closed-set member it stands for).
    "DOWNGRADED",   # "DOWNGRADED → DRAFT-ONLY"
    "DISPUTED",     # documented dispute == a REFUTED-class outcome
}

# Markers in the Artifact cell that mean "no primary source captured yet".
_NOT_CAPTURED = re.compile(r"\b(pending|uncaptured|draft-only|incoming|none)\b", re.IGNORECASE)

# A plausible artifact_id / capture_group token: lowercase words joined by - or .
# (e.g. "sunbiz-fed-filing-llc-detail", "domain-fedfiling.com-rdap"). We extract
# these candidates from the free-text Artifact cell and resolve them against the
# manifest; prose words that don't resolve are ignored (the cell mixes ids + notes).
_ARTIFACT_TOKEN = re.compile(r"[a-z0-9][a-z0-9.]*(?:-[a-z0-9.]+)+")


# ===========================================================================
# Ledger parsing (shared by provenance-linkage and ledger-completeness)
# ===========================================================================
class LedgerRow:
    """One parsed row of the §7 Provenance Ledger markdown table."""

    __slots__ = ("ledger_id", "finding", "origin", "status", "source", "artifact")

    def __init__(self, cells: list[str]):
        # Column order in §7: ID | Finding | Origin | Status | Source | Artifact
        self.ledger_id = cells[0]
        self.finding = cells[1]
        self.origin = cells[2]
        self.status = cells[3]
        self.source = cells[4]
        self.artifact = cells[5]

    def status_norm(self) -> str:
        """Status with **bold**, parentheticals, arrows, and notes stripped → leading text.

        Strips markdown bold, "(notes…)" asides, em-dash asides, and "X → Y"
        decoration, returning the uppercased leading phrase (e.g.
        "**UNSUPPORTED as stated** (…)" → "UNSUPPORTED AS STATED").
        """
        s = self.status
        s = s.replace("*", " ")            # drop bold/italic markers
        s = re.split(r"[(—]", s, 1)[0]     # drop "(notes...)" and em-dash asides
        s = s.split("→")[0]                # drop "X → Y" decoration, keep the X token
        return s.strip().upper()

    def status_token(self) -> str:
        """The closed-set Status member this row resolves to (or "" if none).

        The live ledger decorates statuses with trailing qualifiers separated by a
        space, comma, or slash ("UNSUPPORTED as stated", "INFERRED, not documented",
        "CAPTURED/grounded"). We accept the row if its normalized status STARTS WITH
        a closed-set token, and return that token; otherwise "".
        """
        norm = self.status_norm()
        for allowed in sorted(ALLOWED_STATUSES, key=len, reverse=True):
            if norm == allowed or re.match(rf"{re.escape(allowed)}(?:[\s,/]|$)", norm):
                return allowed
        return ""


def parse_ledger(text: str) -> list[LedgerRow]:
    """Extract the §7 Provenance Ledger rows from the report markdown.

    We locate the table by its header (the row that names all six columns), skip
    the markdown separator line, and read data rows until the table ends. Pipe
    escaping inside cells is not used in this ledger, so a simple split is safe.
    """
    rows: list[LedgerRow] = []
    in_table = False
    for line in text.splitlines():
        stripped = line.strip()
        is_table_row = stripped.startswith("|") and stripped.endswith("|")
        if not in_table:
            # Header row contains all the column names we expect.
            low = stripped.lower()
            if is_table_row and "finding" in low and "origin" in low and "artifact" in low:
                in_table = True
            continue
        # Inside the table now.
        if not is_table_row:
            break  # table ended
        # The markdown separator row (|----|----|...) — skip it.
        if set(stripped) <= set("|-: "):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 6:
            continue  # malformed / not a data row
        rows.append(LedgerRow(cells))
    return rows


def referenced_artifact_ids(cell: str) -> list[str]:
    """Pull candidate artifact_id / capture_group tokens out of an Artifact cell.

    The cell is free text that may embed one or more ids plus prose (e.g.
    "domain-fedfiling.com-rdap / domain-federalfiling.com-rdap" or
    "email-fedfiling-davidholland (pending)"). We return every hyphen/dot token;
    the caller resolves each against the manifest and ignores prose non-matches.
    """
    return _ARTIFACT_TOKEN.findall(cell)


# ===========================================================================
# Gate 1 — provenance-linkage
# ===========================================================================
def gate_provenance_linkage() -> bool:
    """Every cited artifact must exist in the manifest, on disk, and re-hash correctly.

    Ledger cells reference either a per-file ``artifact_id`` (e.g.
    ``domain-fedfiling.com-rdap``) or a ``capture_group`` that bundles several
    files (e.g. ``sunbiz-fed-filing-llc-detail`` → screenshot/html/pdf). For a
    group reference we verify EVERY member file. Returns True on PASS.
    """
    print("== provenance-linkage ==")
    if not LEDGER_PATH.exists():
        print(f"  FAIL: ledger not found at {LEDGER_PATH}")
        return False
    if not EvidenceManifest(EVIDENCE_ROOT).path.exists():
        print(f"  FAIL: manifest not found at {EVIDENCE_ROOT / 'manifest.jsonl'}")
        return False

    manifest = EvidenceManifest(EVIDENCE_ROOT)
    artifacts = manifest.load()
    by_id = {a.artifact_id: a for a in artifacts}
    by_group: dict[str, list] = {}
    for a in artifacts:
        by_group.setdefault(a.capture_group, []).append(a)

    rows = parse_ledger(LEDGER_PATH.read_text(encoding="utf-8"))
    broken: list[str] = []     # hard failures (missing/!hash/missing-file)
    checked = 0                # number of (row, resolved-artifact) links verified
    rows_with_link = 0         # rows that referenced at least one resolvable id

    for row in rows:
        # A row that's explicitly not-yet-captured carries no linkage obligation.
        if _NOT_CAPTURED.search(row.artifact) and not _resolves_any(
            referenced_artifact_ids(row.artifact), by_id, by_group
        ):
            continue

        resolved_here = False
        for token in referenced_artifact_ids(row.artifact):
            members = None
            if token in by_id:
                members = [by_id[token]]
            elif token in by_group:
                members = by_group[token]
            if members is None:
                continue  # token is prose, not a real id — skip
            resolved_here = True
            for art in members:
                checked += 1
                fp = EVIDENCE_ROOT / art.local_path
                if not fp.exists():
                    broken.append(
                        f"[{row.ledger_id}] artifact '{art.artifact_id}': "
                        f"file missing on disk → {art.local_path}"
                    )
                    continue
                actual = sha256_file(fp)
                if actual != art.sha256:
                    broken.append(
                        f"[{row.ledger_id}] artifact '{art.artifact_id}': sha256 MISMATCH "
                        f"(manifest={art.sha256[:12]}… disk={actual[:12]}…) → {art.local_path}"
                    )
        if resolved_here:
            rows_with_link += 1

    print(f"  ledger rows parsed: {len(rows)}; rows with a resolvable artifact: {rows_with_link}")
    print(f"  artifact files verified (exists + sha256): {checked}")
    if broken:
        print(f"  FAIL: {len(broken)} broken provenance link(s):")
        for b in broken:
            print(f"    - {b}")
        return False
    print("  PASS: every cited artifact exists, is on disk, and re-hashes correctly.")
    return True


def _resolves_any(tokens, by_id, by_group) -> bool:
    """True if any token names a real artifact_id or capture_group."""
    return any(t in by_id or t in by_group for t in tokens)


# ===========================================================================
# Gate 2 — ledger-completeness
# ===========================================================================
def gate_ledger_completeness() -> bool:
    """Every row's Status must be in the closed set; no un-actioned UNVERIFIED rows.

    A row is an *un-actioned claim* (FAIL) when its normalized Status is the plain
    "UNVERIFIED" AND it cites no captured artifact. UNVERIFIED is deliberately NOT
    in the allowed closed set — it's the "still needs work" state a completed
    ledger should not contain. Returns True on PASS.
    """
    print("== ledger-completeness ==")
    if not LEDGER_PATH.exists():
        print(f"  FAIL: ledger not found at {LEDGER_PATH}")
        return False

    manifest = EvidenceManifest(EVIDENCE_ROOT)
    artifacts = manifest.load()
    known = {a.artifact_id for a in artifacts} | {a.capture_group for a in artifacts}

    rows = parse_ledger(LEDGER_PATH.read_text(encoding="utf-8"))
    counts: Counter[str] = Counter()
    unactioned: list[str] = []   # plain UNVERIFIED with no captured artifact
    unknown_status: list[str] = []

    for row in rows:
        token = row.status_token()       # closed-set member, or "" if none
        norm = row.status_norm()
        counts[token or norm or "(blank)"] += 1
        has_artifact = _resolves_any(referenced_artifact_ids(row.artifact), known, {})

        if token:
            continue  # decorated form of a closed-set status — accepted
        if norm == "UNVERIFIED":
            if not has_artifact:
                unactioned.append(
                    f"[{row.ledger_id}] UNVERIFIED, no captured artifact: {row.finding[:70]}"
                )
            else:
                # UNVERIFIED but with an artifact — status not advanced past the work.
                unactioned.append(
                    f"[{row.ledger_id}] UNVERIFIED (has artifact but status not advanced): {row.finding[:60]}"
                )
        else:
            unknown_status.append(
                f"[{row.ledger_id}] status not in closed set: '{norm}' :: {row.finding[:50]}"
            )

    # --- summary count by status ------------------------------------------
    print(f"  ledger rows parsed: {len(rows)}")
    print("  status counts:")
    for st, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {st or '(blank)':<14} {n}")

    ok = True
    if unactioned:
        ok = False
        print(f"  FAIL: {len(unactioned)} un-actioned (plain UNVERIFIED) row(s):")
        for u in unactioned:
            print(f"    - {u}")
    if unknown_status:
        ok = False
        print(f"  FAIL: {len(unknown_status)} row(s) with a status outside the closed set:")
        for u in unknown_status:
            print(f"    - {u}")
    if ok:
        print("  PASS: every row has a closed-set status; no un-actioned UNVERIFIED claims.")
    return ok


# ===========================================================================
# Gate 3 — minimization
# ===========================================================================
def load_denylist(path: Path) -> list[str]:
    """Read denylist tokens (one per non-comment, non-blank line). Empty ⇒ []."""
    if not path.exists():
        return []
    tokens: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        tokens.append(s)
    return tokens


def public_files() -> list[Path]:
    """Git-tracked (PUBLIC) files under the case dir + the extra public files.

    Uses `git ls-files` so only committed/tracked files are scanned — untracked
    private working files (e.g. report-private/, an uncommitted draft) are not.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "examples/fedfiling-case/"],
            cwd=REPO_ROOT, capture_output=True, text=True, check=True, timeout=30,
        ).stdout
    except (subprocess.CalledProcessError, OSError) as e:
        print(f"  (warning: git ls-files failed: {e})", file=sys.stderr)
        out = ""
    files = [REPO_ROOT / line for line in out.splitlines() if line.strip()]
    for extra in EXTRA_PUBLIC_FILES:
        if extra.exists():
            files.append(extra)
    return files


def gate_minimization() -> bool:
    """No denylisted PRIVATE token may appear in a PUBLIC file. Fails CLOSED on empty denylist.

    Conservative by design: we report every (file, token) hit. The private report
    itself (report-private/) is never git-tracked, so it is excluded by construction
    from the `git ls-files` scan. Returns True on PASS.
    """
    print("== minimization ==")
    denylist = load_denylist(DENYLIST_PATH)
    if not denylist:
        # FAIL-CLOSED: an empty/missing denylist must not silently "pass".
        print(f"  FAIL (fail-closed): denylist missing or empty at {DENYLIST_PATH}")
        return False

    lowered = [(t, t.lower()) for t in denylist]
    files = public_files()
    hits: list[str] = []
    scanned = 0
    for fp in files:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeError):
            continue  # binary/unreadable — skip (denylist tokens are textual)
        scanned += 1
        low = content.lower()
        rel = fp.relative_to(REPO_ROOT) if fp.is_relative_to(REPO_ROOT) else fp
        for original, tok in lowered:
            if tok in low:
                hits.append(f"{rel}: contains denylisted token '{original}'")

    print(f"  denylist tokens: {len(denylist)}; public files scanned: {scanned}")
    if hits:
        print(f"  FAIL: {len(hits)} PII/denylist leak(s) into public files:")
        for h in hits:
            print(f"    - {h}")
        return False
    print("  PASS: no denylisted private token found in any public file.")
    return True


# ===========================================================================
# CLI
# ===========================================================================
GATES = {
    "provenance-linkage": gate_provenance_linkage,
    "ledger-completeness": gate_ledger_completeness,
    "minimization": gate_minimization,
}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command")
    for name in GATES:
        sub.add_parser(name, help=GATES[name].__doc__.splitlines()[0] if GATES[name].__doc__ else name)
    ap.add_argument("--all", action="store_true", help="run all gates; fail if any fails")
    args = ap.parse_args(argv)

    # `--all`, or no subcommand at all, runs every gate and fails if any fails.
    if args.all or args.command is None:
        results = {name: fn() for name, fn in GATES.items()}
        print("\n== SUMMARY ==")
        for name, ok in results.items():
            print(f"  {name:<22} {'PASS' if ok else 'FAIL'}")
        return 0 if all(results.values()) else 1

    ok = GATES[args.command]()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
