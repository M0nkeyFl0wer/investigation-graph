#!/usr/bin/env python3
"""
capture_breach.py — DeHashed breach-footprint capture with provenance.

Queries DeHashed for selectors (emails / usernames) and records EACH result as a
hashed artifact in the evidence manifest — INCLUDING empty/negative results. The
negative result is itself the evidence: "no breach footprint found for X" is a
captured, hashed, time-stamped artifact, not an unbacked claim. That is the
negative-evidence discipline — you can later prove you looked and found nothing,
to the same chain-of-custody standard as a positive hit.

  - DeHashed v2  POST https://api.dehashed.com/v2/search
                 header `Dehashed-Api-Key: <key>`
                 body  {"query":"email:<addr>","page":1,"size":100}
                 (also supports `username:` query form)

Each saved response → a manifest row (sha256 + source + UTC time + method), so a
breach finding carries the same provenance as a captured web page. A selector that
errors is logged per-selector and never crashes the batch.

SENSITIVITY: breach data is third-party PII. Raw responses are written under the
gitignored `artifacts/breach/` tree and are NEVER republished; this script never
prints result CONTENTS, only counts. Integrity is provable from the committed
manifest SHA-256 hashes.

Key handling (STRICT, per repo credential policy): the key is read ONLY from the
`DEHASHED_API_KEY` env var, which the operator pipes in from keyring, e.g.
  DEHASHED_API_KEY=$(ssh flowerpowered 'bash ~/manage-api-keys.sh get dehashed api_key') \
      python scripts/capture_breach.py --evidence <dir> email:a@b.com
The key is never hardcoded, logged, echoed, or written to any file. If the env
var is missing the script exits immediately and does nothing.

Usage:
  DEHASHED_API_KEY=... python scripts/capture_breach.py \
      --evidence examples/fedfiling-case/evidence \
      email:david.holland@fedfiling.com username:fedfiling
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

from investigation_graph.capture import EvidenceManifest

# DeHashed v2 surface. Kept as top-of-file constants because the exact v2 shape is
# assumed (we are NOT calling it to confirm — see the module note and the returned
# assumptions). Adjust here if the live API differs.
DEHASHED_URL = "https://api.dehashed.com/v2/search"
DEHASHED_KEY_HEADER = "Dehashed-Api-Key"
DEHASHED_ENV = "DEHASHED_API_KEY"
PAGE_SIZE = 100

# Accepted selector prefixes → the DeHashed query field they map to. A selector is
# given on the CLI as `email:<addr>` or `username:<name>`.
SELECTOR_FIELDS = ("email", "username")


def slugify(text: str) -> str:
    """Filesystem-safe slug for a selector (e.g. `email:a@b.com` → `email-a-b-com`).

    Used only for the on-disk artifact filename; the full selector/query is recorded
    verbatim in the manifest notes, so no information is lost to slugging.
    """
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "selector"


def parse_selector(raw: str) -> tuple[str, str]:
    """Split `field:value` into (field, value); raise ValueError on a bad prefix.

    The prefix is required so the operator is explicit about what is being searched
    (an email vs a username changes the DeHashed query and the meaning of a hit).
    """
    if ":" not in raw:
        raise ValueError(f"selector must be prefixed (email:/username:): {raw!r}")
    field, value = raw.split(":", 1)
    field = field.strip().lower()
    value = value.strip()
    if field not in SELECTOR_FIELDS:
        raise ValueError(f"unknown selector field {field!r}; use one of {SELECTOR_FIELDS}")
    if not value:
        raise ValueError(f"empty selector value: {raw!r}")
    return field, value


def dehashed_search(api_key: str, query: str, *, timeout: int = 30) -> tuple[int, bytes]:
    """POST one query to DeHashed v2; return (http_status, raw_body_bytes).

    The key is passed straight into the request header and never stored, logged, or
    returned. HTTP errors are surfaced as (code, body) rather than raised, so a 4xx
    (e.g. quota/auth) is captured as a documented gap instead of crashing the batch.
    """
    body = json.dumps({"query": query, "page": 1, "size": PAGE_SIZE}).encode()
    headers = {
        DEHASHED_KEY_HEADER: api_key,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    req = urllib.request.Request(DEHASHED_URL, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed trusted endpoint)
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if hasattr(e, "read") else b""


def count_results(body: bytes) -> int:
    """Best-effort result count from a DeHashed v2 body (0 if unparseable/empty).

    v2 is assumed to return a JSON object with an `entries` array (and often a
    `total`); we try both, falling back to 0. The count drives the negative-evidence
    note — a wrong count is cosmetic (the raw body is the artifact), so we never let
    a parse error crash the capture.
    """
    try:
        data = json.loads(body)
    except Exception:
        return 0
    if isinstance(data, dict):
        entries = data.get("entries")
        if isinstance(entries, list):
            return len(entries)
        total = data.get("total")
        if isinstance(total, int):
            return total
    return 0


def capture_selector(manifest: EvidenceManifest, api_key: str, raw_selector: str) -> dict:
    """Search one selector, save the raw response, record a manifest row, return a summary.

    Returns a dict with selector / n_results / artifact_id (or an `error`). Never
    raises and never includes result CONTENTS — only the count — because the body is
    sensitive PII that must not reach stdout or any non-gitignored sink.
    """
    field, value = parse_selector(raw_selector)
    query = f"{field}:{value}"
    art_dir = manifest.root / "artifacts" / "breach"
    art_dir.mkdir(parents=True, exist_ok=True)

    status, body = dehashed_search(api_key, query)
    n = count_results(body) if status == 200 else 0

    dest = art_dir / f"{slugify(raw_selector)}.json"
    dest.write_bytes(body or b"{}")  # always write something so the gap is itself hashed

    # 0 results == negative evidence: the documented absence of a breach footprint.
    note = (
        f"query={query}; results={n}; http={status}; SENSITIVE-PRIVATE"
        + ("; 0 results = negative evidence (no breach footprint found)" if n == 0 else "")
    )
    artifact_id = f"breach-{slugify(raw_selector)}"
    manifest.record_file(
        dest,
        artifact_id=artifact_id,
        kind="osint_breach",
        capture_method="dehashed-api-v2",
        tool_version="dehashed",
        source_url=DEHASHED_URL,
        http_status=status,
        notes=note,
    )
    return {"selector": raw_selector, "n_results": n, "http": status, "artifact_id": artifact_id}


def main() -> int:
    ap = argparse.ArgumentParser(description="DeHashed breach-footprint capture with provenance.")
    ap.add_argument("--evidence", required=True, type=Path)
    ap.add_argument("selectors", nargs="+", help="one or more email:<addr> / username:<name>")
    args = ap.parse_args()

    # Key handling: env-only, never hardcoded. Missing key → do nothing.
    api_key = os.environ.get(DEHASHED_ENV)
    if not api_key:
        print(
            f"ERROR: {DEHASHED_ENV} is not set. Pipe it from keyring, e.g.\n"
            f"  {DEHASHED_ENV}=$(ssh flowerpowered 'bash ~/manage-api-keys.sh get dehashed api_key') \\\n"
            f"      python scripts/capture_breach.py --evidence <dir> email:a@b.com",
            file=sys.stderr,
        )
        return 2

    manifest = EvidenceManifest(args.evidence)

    # Privacy reminder: the breach artifact tree must stay gitignored. The repo
    # .gitignore already covers `examples/fedfiling-case/evidence/artifacts/` (which
    # includes `artifacts/breach/`); verify it stays that way for any other case dir.
    print(
        "REMINDER: breach data is sensitive third-party PII. Ensure "
        f"{manifest.root}/artifacts/breach/ is gitignored before committing.\n"
    )

    summaries = []
    for raw in args.selectors:
        try:
            s = capture_selector(manifest, api_key, raw)
            summaries.append(s)
            tag = "NEGATIVE (no footprint)" if s["n_results"] == 0 else f"{s['n_results']} result(s)"
            # NB: never print result contents — counts only.
            print(f"  {s['selector']:<40} {tag:<28} http={s['http']}  id={s['artifact_id']}")
        except Exception as e:  # per-selector isolation: one bad selector never kills the batch
            print(f"  {raw:<40} ERROR: {e}")
            summaries.append({"selector": raw, "error": str(e)})

    ok = [s for s in summaries if "error" not in s]
    print(f"\nmanifest: {manifest.path} ({len(manifest.load())} rows); {len(ok)}/{len(summaries)} captured")
    return 0


if __name__ == "__main__":
    sys.exit(main())
