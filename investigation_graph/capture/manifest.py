"""
Evidence manifest — the chain-of-custody spine for captured sources.

One :class:`Artifact` row per file we acquire. The manifest is an append-only
JSONL file (one JSON object per line) so it is diff-friendly, human-readable, and
never rewrites prior rows (append-only is itself a chain-of-custody property: you
can see exactly what was collected, in order, and nothing silently changes).

What each row must answer, per the Berkeley Protocol (integrity + provenance):

  - WHAT is it?      sha256 (content hash), bytes, media_type, local path
  - WHERE from?      source_url (with query string) or source_path; redirect_chain
  - WHEN captured?   captured_at_utc (ISO-8601, timezone-aware)
  - WHO captured?    collector (operator identity)
  - HOW captured?    capture_method + tool_version (the exact mechanism)
  - In what state?   http_status (for web), notes (free-text caveats)

This module is standard-library only, so it imports with no extra dependencies.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import socket
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Manifest schema version — bump if the Artifact fields change, so downstream
# readers can detect format drift rather than silently mis-parse old rows.
MANIFEST_SCHEMA = "ig-evidence/1"


def utc_now_iso() -> str:
    """Timezone-aware UTC timestamp, ISO-8601 (e.g. 2026-06-20T17:05:03.123456+00:00).

    Capture time is evidentiary, so it is always UTC and always tz-aware — never a
    naive local-clock string that can't be compared across machines/timezones.
    """
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: str | Path, _chunk: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes, streamed in 1 MiB blocks (handles large media).

    SHA-256 is the integrity anchor: a third party can re-hash the same bytes and
    confirm the artifact is unaltered since capture.
    """
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(_chunk), b""):
            h.update(block)
    return h.hexdigest()


def default_collector() -> str:
    """Best-effort operator identity: ``user@host``.

    Override with the ``CAPTURE_COLLECTOR`` env var when the running account is not
    the responsible investigator (e.g. a shared box or an automation user). The
    point is to attribute the collection to a *person*, not a process.
    """
    override = os.environ.get("CAPTURE_COLLECTOR")
    if override:
        return override
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:  # pragma: no cover - identity lookup should never block a capture
        return "unknown@unknown"


@dataclass
class Artifact:
    """One captured file and its full provenance — a single manifest row.

    Multiple files from one logical capture (e.g. the screenshot, the rendered
    HTML, and the print-to-PDF of the same page load) share a ``capture_group`` so
    they can be reassembled, while each keeps its own content hash.
    """

    artifact_id: str            # stable, human-meaningful id (e.g. "tina-federal-filing-screenshot")
    capture_group: str          # groups files from one capture event (e.g. one page load)
    kind: str                   # "screenshot" | "html" | "pdf" | "registry_pdf" | "video" | "video_frame" | "transcript" | "email" | "note"
    local_path: str             # path relative to the evidence root
    sha256: str                 # content hash at capture time
    bytes: int                  # file size

    captured_at_utc: str        # ISO-8601 UTC
    collector: str              # who collected it (user@host or CAPTURE_COLLECTOR)
    capture_method: str         # tool/mechanism, e.g. "playwright-chromium-fullpage"
    tool_version: str           # version string of the capturing tool

    media_type: str = ""        # MIME type where known
    source_url: str = ""        # original URL (with query), if web-sourced
    source_path: str = ""       # original local path, if file-sourced (e.g. the email, the video)
    http_status: int | None = None      # HTTP response status, for web captures
    redirect_chain: list[str] = field(default_factory=list)  # URLs traversed before the final one
    derived_from: str = ""      # sha256 of a master artifact, if this is a derivative (e.g. a video frame)
    notes: str = ""             # caveats: "JS-rendered", "behind consent wall", "trainer-redacted", etc.
    schema: str = MANIFEST_SCHEMA

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


class EvidenceManifest:
    """Append-only JSONL manifest at ``<evidence_root>/manifest.jsonl``.

    Typical use::

        m = EvidenceManifest(evidence_root)
        art = m.record_file(path, artifact_id="...", kind="screenshot",
                            capture_method="playwright-chromium-fullpage",
                            tool_version=pw_version, source_url=url,
                            http_status=200, capture_group="tina-federal-filing")

    ``record_file`` hashes the file, stamps the time/collector, appends the row,
    and returns the :class:`Artifact`.
    """

    def __init__(self, evidence_root: str | Path):
        self.root = Path(evidence_root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "manifest.jsonl"

    # -- reading -------------------------------------------------------------
    def load(self) -> list[Artifact]:
        """Return all recorded artifacts (empty list if the manifest doesn't exist)."""
        if not self.path.exists():
            return []
        out: list[Artifact] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            # Tolerate unknown future fields by filtering to known dataclass keys.
            known = {f for f in Artifact.__dataclass_fields__}  # type: ignore[attr-defined]
            out.append(Artifact(**{k: v for k, v in data.items() if k in known}))
        return out

    def ids(self) -> set[str]:
        """Set of artifact_ids already recorded — used to make captures idempotent."""
        return {a.artifact_id for a in self.load()}

    # -- writing -------------------------------------------------------------
    def append(self, artifact: Artifact) -> Artifact:
        """Append one already-built Artifact row (append-only; never rewrites)."""
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(artifact.to_json() + "\n")
        return artifact

    def record_file(
        self,
        local_path: str | Path,
        *,
        artifact_id: str,
        kind: str,
        capture_method: str,
        tool_version: str,
        capture_group: str = "",
        media_type: str = "",
        source_url: str = "",
        source_path: str = "",
        http_status: int | None = None,
        redirect_chain: list[str] | None = None,
        derived_from: str = "",
        notes: str = "",
        captured_at_utc: str | None = None,
        collector: str | None = None,
    ) -> Artifact:
        """Hash a file on disk, stamp provenance, append a manifest row, return it.

        ``local_path`` is stored relative to the evidence root when possible, so the
        manifest is portable (it doesn't bake in an absolute machine path).
        """
        p = Path(local_path)
        try:
            rel = str(p.resolve().relative_to(self.root.resolve()))
        except ValueError:
            rel = str(p)  # outside the evidence root; keep as given
        art = Artifact(
            artifact_id=artifact_id,
            capture_group=capture_group or artifact_id,
            kind=kind,
            local_path=rel,
            sha256=sha256_file(p),
            bytes=p.stat().st_size,
            captured_at_utc=captured_at_utc or utc_now_iso(),
            collector=collector or default_collector(),
            capture_method=capture_method,
            tool_version=tool_version,
            media_type=media_type,
            source_url=source_url,
            source_path=source_path,
            http_status=http_status,
            redirect_chain=list(redirect_chain or []),
            derived_from=derived_from,
            notes=notes,
        )
        return self.append(art)
