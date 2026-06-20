"""
investigation_graph.capture — evidentiary source acquisition.

This subpackage acquires source material to a defensible standard *before* any
extraction touches it. The guiding bar is the Berkeley Protocol on Digital Open
Source Investigations (UC Berkeley Human Rights Center & UN OHCHR, 2022), whose
three operational pillars we implement here:

  1. Integrity      — every artifact is SHA-256 hashed at the moment of capture;
                      originals are never modified; downstream work uses copies.
  2. Provenance     — for each artifact we record source (URL/path), capture
                      timestamp (UTC), collector identity, the exact method/tool
                      + version, the HTTP status, and any redirect chain.
  3. Reproducibility— capture is performed by committed, deterministic code (this
                      package), not by an opaque interactive agent, so a third
                      party can re-run it against the same sources.

The manifest (`manifest.py`) is the chain-of-custody spine: one row per artifact.
The capture modules (`web.py`, `registry.py`, `video.py`) write artifacts to disk
and append a manifest row for each. The rest of the pipeline links every graph
node/edge -> source chunk -> artifact_id -> manifest row, so every published
claim traces back to a hash-verified primary source.

`manifest` imports only the standard library, so it is always available. The
capture engines lazily import their heavy dependencies (Playwright, ffmpeg) and
are only needed when actually acquiring sources, e.g. `pip install -e '.[capture]'`.
"""

from investigation_graph.capture.manifest import (
    Artifact,
    EvidenceManifest,
    sha256_file,
    utc_now_iso,
)

__all__ = ["Artifact", "EvidenceManifest", "sha256_file", "utc_now_iso"]
