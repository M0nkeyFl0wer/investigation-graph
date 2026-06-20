"""
Direct file download capture — for endpoints that already serve the primary
document (typically a PDF), such as government corporate-registry records.

When a source *is* the authoritative document (e.g. a Florida Sunbiz annual-report
PDF, an officer-search result PDF), we want the bytes the registry served, not a
browser rendering of a viewer around them. We GET the URL, save the body verbatim,
record the HTTP status + Content-Type + redirect chain, and hash it.

Standard library only (urllib) — no extra dependency, because there's no rendering
to do. If a registry hides its PDF behind JavaScript, fall back to ``web.capture_url``.
"""

from __future__ import annotations

import urllib.request
from pathlib import Path

from investigation_graph.capture.manifest import Artifact, EvidenceManifest

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# Map common served content types to a sensible file extension.
_EXT = {
    "application/pdf": ".pdf",
    "text/html": ".html",
    "application/json": ".json",
    "text/plain": ".txt",
}


def capture_download(
    url: str,
    manifest: EvidenceManifest,
    *,
    artifact_id: str,
    kind: str = "registry_pdf",
    out_subdir: str = "registry",
    notes: str = "",
    timeout_s: int = 60,
) -> Artifact:
    """Download a URL's body to disk and record one manifest row with its hash.

    Returns the recorded :class:`Artifact`. Raises on HTTP/network failure (a
    registry record we can't fetch is a gap to note, not a silent skip).
    """
    art_dir = manifest.root / "artifacts" / out_subdir
    art_dir.mkdir(parents=True, exist_ok=True)

    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    redirect_chain = [url]
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:  # noqa: S310 (trusted operator-supplied URL)
        status = resp.status
        content_type = (resp.headers.get("Content-Type") or "").split(";")[0].strip()
        final_url = resp.geturl()
        if final_url != url:
            redirect_chain.append(final_url)
        body = resp.read()

    ext = _EXT.get(content_type, Path(url.split("?")[0]).suffix or ".bin")
    dest = art_dir / f"{artifact_id}{ext}"
    dest.write_bytes(body)

    return manifest.record_file(
        dest,
        artifact_id=artifact_id,
        kind=kind,
        capture_method="urllib-direct-download",
        tool_version="python-urllib",
        media_type=content_type,
        source_url=url,
        http_status=status,
        redirect_chain=redirect_chain,
        notes=(f"final_url={final_url}." + (f" {notes}" if notes else "")),
    )
