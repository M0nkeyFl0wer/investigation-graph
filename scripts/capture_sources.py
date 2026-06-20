#!/usr/bin/env python3
"""
capture_sources.py — drive the evidentiary capture layer over a declared source list.

The source list is a committed, human-auditable JSON file (the *plan of what we
tried to collect* is itself part of the methodology record). Each entry:

    {
      "artifact_id": "tina-federal-filing",     # stable id, used in the manifest + case study
      "url": "https://truthinadvertising.org/articles/federal-filing-government-imposter-scam/",
      "type": "web",                             # "web" (rendered) | "download" (served file, e.g. PDF)
      "notes": "TINA scam advisory"             # optional free-text caveat
    }

Captures are **idempotent**: an entry whose artifact_id is already in the manifest
is skipped (re-run safely after adding new sources). Use --force to recapture.

A single source failing is logged and the run continues — the gap is then visible
as "declared in sources.json but absent from manifest.jsonl", which is honest
(a documented failure to collect), not a silent omission.

Usage:
    python scripts/capture_sources.py \
        --sources examples/fedfiling-case/sources.json \
        --evidence examples/fedfiling-case/evidence
    # set CAPTURE_COLLECTOR="Jane Doe (investigator)" to attribute the collection.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from investigation_graph.capture import EvidenceManifest
from investigation_graph.capture.registry import capture_download
from investigation_graph.capture.web import capture_url


def _already_captured(manifest: EvidenceManifest, artifact_id: str) -> bool:
    """True if any artifact whose id starts with this base id is already recorded.

    Web captures expand one base id into ``-screenshot``/``-html``/``-pdf`` rows, so
    we match by prefix rather than exact id.
    """
    existing = manifest.ids()
    return any(eid == artifact_id or eid.startswith(artifact_id + "-") for eid in existing)


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture declared sources with provenance.")
    ap.add_argument("--sources", required=True, type=Path, help="JSON list of sources")
    ap.add_argument("--evidence", required=True, type=Path, help="evidence root (holds manifest.jsonl + artifacts/)")
    ap.add_argument("--force", action="store_true", help="recapture even if already in the manifest")
    ap.add_argument("--only", default="", help="capture only this artifact_id (substring match)")
    args = ap.parse_args()

    sources = json.loads(args.sources.read_text(encoding="utf-8"))
    manifest = EvidenceManifest(args.evidence)

    captured, skipped, failed = 0, 0, 0
    for src in sources:
        aid = src["artifact_id"]
        if args.only and args.only not in aid:
            continue
        if not args.force and _already_captured(manifest, aid):
            print(f"= skip (already captured): {aid}")
            skipped += 1
            continue

        stype = src.get("type", "web")
        url = src["url"]
        notes = src.get("notes", "")
        print(f"> capturing [{stype}] {aid} <- {url}")
        try:
            if stype == "web":
                arts = capture_url(url, manifest, artifact_id=aid, notes=notes)
                print(f"  ok: {len(arts)} files")
            elif stype == "download":
                art = capture_download(url, manifest, artifact_id=aid, notes=notes,
                                       kind=src.get("kind", "registry_pdf"))
                print(f"  ok: {art.kind} {art.bytes}B http={art.http_status}")
            else:
                print(f"  ! unknown type {stype!r}; skipping")
                failed += 1
                continue
            captured += 1
        except Exception as e:
            print(f"  ! FAILED {aid}: {e}")
            failed += 1

    print(f"\nsummary: captured={captured} skipped={skipped} failed={failed}")
    print(f"manifest: {manifest.path} ({len(manifest.load())} rows)")
    # Non-zero exit if any declared source failed, so a CI/automation step notices.
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
