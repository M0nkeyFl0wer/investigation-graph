"""eval-gates tests — fully offline, deterministic, no network.

We build tiny fake fixtures in ``tmp_path`` (a manifest with a real hashed file, a
minimal ledger markdown, a fake "public" file) and point the gate functions at
them by monkeypatching the module-level path constants. Each test asserts one
gate's PASS / FAIL behaviour in isolation:

  - provenance-linkage FAILS on a missing artifact and on a hash mismatch, PASSES
    on a good link;
  - ledger-completeness FAILS on a plain-UNVERIFIED row with no artifact;
  - minimization FAILS when a denylist token appears in a public file and
    FAILS CLOSED on an empty denylist.
"""
from __future__ import annotations

import pytest

import scripts.eval_gates as eg
from investigation_graph.capture import EvidenceManifest


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
def _write_manifest(evidence_root, *, good_path):
    """Build an evidence manifest with one real, correctly-hashed artifact.

    Returns the EvidenceManifest. ``good_path`` is created on disk and recorded so
    its sha256 matches; we'll mutate or remove it per-test to drive failures.
    """
    m = EvidenceManifest(evidence_root)
    good_path.parent.mkdir(parents=True, exist_ok=True)
    good_path.write_bytes(b"good artifact bytes")
    m.record_file(
        good_path,
        artifact_id="good-artifact",
        kind="html",
        capture_method="test",
        tool_version="test",
        capture_group="good-artifact",
    )
    return m


def _ledger(rows: str) -> str:
    """Wrap data rows in a minimal §7-style ledger table the parser recognizes."""
    return (
        "# fixture report\n\n## 7. Provenance Ledger\n\n"
        "| ID | Finding | Origin | Status | Source | Artifact |\n"
        "|----|---------|--------|--------|--------|----------|\n"
        + rows
        + "\n"
    )


@pytest.fixture
def case(tmp_path, monkeypatch):
    """Point all eval_gates path constants at a sandbox under tmp_path."""
    repo = tmp_path
    case_root = repo / "examples" / "fedfiling-case"
    evidence = case_root / "evidence"
    ledger = case_root / "report-private" / "REPORT.md"
    denylist = repo / "scripts" / "minimization_denylist.txt"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    denylist.parent.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(eg, "REPO_ROOT", repo)
    monkeypatch.setattr(eg, "CASE_ROOT", case_root)
    monkeypatch.setattr(eg, "EVIDENCE_ROOT", evidence)
    monkeypatch.setattr(eg, "LEDGER_PATH", ledger)
    monkeypatch.setattr(eg, "DENYLIST_PATH", denylist)
    monkeypatch.setattr(eg, "EXTRA_PUBLIC_FILES", [])
    return {
        "repo": repo, "case_root": case_root, "evidence": evidence,
        "ledger": ledger, "denylist": denylist,
    }


# ---------------------------------------------------------------------------
# provenance-linkage
# ---------------------------------------------------------------------------
def test_provenance_linkage_passes_on_good_link(case):
    good = case["evidence"] / "artifacts" / "good.html"
    _write_manifest(case["evidence"], good_path=good)
    case["ledger"].write_text(_ledger(
        "| r1 | a good finding | NEW | VERIFIED | src | good-artifact |"
    ))
    assert eg.gate_provenance_linkage() is True


def test_provenance_linkage_fails_on_missing_file(case):
    good = case["evidence"] / "artifacts" / "good.html"
    _write_manifest(case["evidence"], good_path=good)
    good.unlink()  # file recorded in manifest but now gone from disk
    case["ledger"].write_text(_ledger(
        "| r1 | a finding | NEW | VERIFIED | src | good-artifact |"
    ))
    assert eg.gate_provenance_linkage() is False


def test_provenance_linkage_fails_on_hash_mismatch(case):
    good = case["evidence"] / "artifacts" / "good.html"
    _write_manifest(case["evidence"], good_path=good)
    good.write_bytes(b"TAMPERED - different bytes than recorded")  # sha256 now differs
    case["ledger"].write_text(_ledger(
        "| r1 | a finding | NEW | VERIFIED | src | good-artifact |"
    ))
    assert eg.gate_provenance_linkage() is False


# ---------------------------------------------------------------------------
# ledger-completeness
# ---------------------------------------------------------------------------
def test_ledger_completeness_fails_on_plain_unverified(case):
    good = case["evidence"] / "artifacts" / "good.html"
    _write_manifest(case["evidence"], good_path=good)
    case["ledger"].write_text(_ledger(
        "| r1 | a verified finding | NEW | VERIFIED | src | good-artifact |\n"
        "| r2 | an un-actioned claim | DRAFT | UNVERIFIED | trainer | pending |"
    ))
    assert eg.gate_ledger_completeness() is False


def test_ledger_completeness_passes_with_decorated_closed_set(case):
    good = case["evidence"] / "artifacts" / "good.html"
    _write_manifest(case["evidence"], good_path=good)
    # Decorated closed-set statuses (bold + trailing qualifiers) must be accepted.
    case["ledger"].write_text(_ledger(
        "| r1 | x | NEW | **VERIFIED** | src | good-artifact |\n"
        "| r2 | y | DRAFT | **UNSUPPORTED as stated** (note) | src | pending |\n"
        "| r3 | z | NEW | CAPTURED/grounded | src | pending |"
    ))
    assert eg.gate_ledger_completeness() is True


# ---------------------------------------------------------------------------
# minimization
# ---------------------------------------------------------------------------
def _fake_git_ls_files(case, monkeypatch, tracked_rel_paths):
    """Stub subprocess.run so public_files() returns our chosen tracked files."""
    out = "\n".join(tracked_rel_paths) + "\n"

    class _R:
        stdout = out

    def fake_run(*a, **k):
        return _R()

    monkeypatch.setattr(eg.subprocess, "run", fake_run)


def test_minimization_fails_on_denylisted_token(case, monkeypatch):
    case["denylist"].write_text("# header\n2407 Courtney Meadows Court\nLiam Foit\n")
    leaky = case["case_root"] / "CASE-STUDY.md"
    leaky.write_text("Public study. Registered agent at 2407 Courtney Meadows Court, Tampa.")
    _fake_git_ls_files(case, monkeypatch, ["examples/fedfiling-case/CASE-STUDY.md"])
    assert eg.gate_minimization() is False


def test_minimization_passes_when_clean(case, monkeypatch):
    case["denylist"].write_text("# header\n2407 Courtney Meadows Court\nLiam Foit\n")
    clean = case["case_root"] / "CASE-STUDY.md"
    clean.write_text("Public study naming operators only via public business records.")
    _fake_git_ls_files(case, monkeypatch, ["examples/fedfiling-case/CASE-STUDY.md"])
    assert eg.gate_minimization() is True


def test_minimization_fails_closed_on_empty_denylist(case, monkeypatch):
    case["denylist"].write_text("# only comments, no tokens\n\n")
    clean = case["case_root"] / "CASE-STUDY.md"
    clean.write_text("totally clean public content")
    _fake_git_ls_files(case, monkeypatch, ["examples/fedfiling-case/CASE-STUDY.md"])
    assert eg.gate_minimization() is False


def test_minimization_fails_closed_on_missing_denylist(case, monkeypatch):
    case["denylist"].unlink(missing_ok=True)
    _fake_git_ls_files(case, monkeypatch, [])
    assert eg.gate_minimization() is False
