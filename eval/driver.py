"""Reusable real-execution evidence harness for the investigation-graph eval.

Adapted from the newmode-integration eval protocol (backend/eval/driver.py): a
change isn't "done" on green unit tests + lint alone — it must be **exercised in
the actual running pipeline**, on a **throwaway provisioned instance**, with
**captured evidence**. For a CLI tool the "running system" is the real
scope→ingest→extract→ground→build pipeline (not a web server), so this harness:

  throwaway_investigation(corpus) — provisions an isolated investigation in a
                          temp dir (its own graph.lbug + chunks.duckdb + ingest/,
                          NEVER the dev data/), copies the corpus in, points the
                          package config at it, and tears the temp dir down on
                          exit. Evidence is written under eval/evidence/<name>/
                          (gitignored) and survives.

  Checks                — an assertion accumulator: each check records pass/fail
                          with a message; the eval exits non-zero if any failed,
                          so it's a real gate, not a print.

Run an eval script with:  python -m eval.eval_full_pipeline
"""
from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from investigation_graph import config

EVAL_ROOT = Path(__file__).resolve().parent
EVIDENCE_ROOT = EVAL_ROOT / "evidence"
SUPPORTED = (".txt", ".md", ".pdf", ".html")


@dataclass
class Investigation:
    """Handles + paths for one throwaway investigation."""
    root: Path
    graph_dir: Path
    chunk_db: Path
    ingest_dir: Path
    evidence_dir: Path

    def write_evidence(self, name: str, obj) -> Path:
        """Persist an evidence artifact (str → .txt, else → .json)."""
        if isinstance(obj, str):
            path = self.evidence_dir / name
            path.write_text(obj, encoding="utf-8")
        else:
            path = self.evidence_dir / name
            path.write_text(json.dumps(obj, indent=2, default=str), encoding="utf-8")
        return path


@contextlib.contextmanager
def throwaway_investigation(corpus: Path, name: str) -> Iterator[Investigation]:
    """Provision an isolated investigation in a temp dir and point config at it.

    Restores the original config paths and removes the temp dir on exit; the
    evidence dir under eval/evidence/<name>/ is kept.
    """
    tmp = Path(tempfile.mkdtemp(prefix=f"ig-eval-{name}-"))
    ingest_dir = tmp / "ingest"
    ingest_dir.mkdir(parents=True)
    # Copy only real documents (not any explainer README) into the throwaway ingest.
    n = 0
    for f in sorted(Path(corpus).iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED:
            shutil.copy2(f, ingest_dir / f.name)
            n += 1
    if n == 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"no supported documents in corpus {corpus}")

    evidence_dir = EVIDENCE_ROOT / name
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Redirect the package config at the throwaway instance.
    saved = (config.GRAPH_DIR, config.CHUNK_DB, config.INGEST_DIR)
    config.GRAPH_DIR = tmp / "graph.lbug"
    config.CHUNK_DB = tmp / "chunks.duckdb"
    config.INGEST_DIR = ingest_dir
    try:
        yield Investigation(tmp, config.GRAPH_DIR, config.CHUNK_DB, ingest_dir,
                            evidence_dir)
    finally:
        config.GRAPH_DIR, config.CHUNK_DB, config.INGEST_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)


def run_capturing(fn) -> str:
    """Run fn() capturing stdout+stderr; return the captured text."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        fn()
    return buf.getvalue()


@dataclass
class Checks:
    """A real gate: accumulate pass/fail checks; nonzero exit if any fail."""
    results: list[tuple[bool, str]] = field(default_factory=list)

    def check(self, ok: bool, label: str) -> bool:
        self.results.append((bool(ok), label))
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        return bool(ok)

    @property
    def failed(self) -> int:
        return sum(1 for ok, _ in self.results if not ok)

    def summary(self) -> dict:
        return {
            "total": len(self.results),
            "passed": len(self.results) - self.failed,
            "failed": self.failed,
            "checks": [{"ok": ok, "label": label} for ok, label in self.results],
        }
