"""
Video source capture via ffmpeg — for walkthrough/screen-recording sources such
as the trainer's ``demo.mp4``.

Chain-of-custody model for video:
  - The **master** is the original file, hashed in place and recorded once. It is
    never modified.
  - **Keyframes** (stills sampled at a fixed interval) and the **transcript** are
    *derivatives*: each records ``derived_from`` = the master's SHA-256, so anyone
    can see it descends from the authenticated original and re-derive it with the
    same ffmpeg command.

ffmpeg is a system binary (verified present on this host). Transcription is heavy
and GPU-bound, so it runs on the operator's GPU box (seshat) and the resulting
transcript file is recorded here via :func:`record_transcript`.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from investigation_graph.capture.manifest import Artifact, EvidenceManifest


def _ffmpeg_version() -> str:
    try:
        out = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, text=True, check=True
        ).stdout.splitlines()[0]
        return out.strip()
    except Exception:
        return "ffmpeg (version unknown)"


def register_master(
    video_path: str | Path,
    manifest: EvidenceManifest,
    *,
    artifact_id: str,
    source_url: str = "",
    notes: str = "",
) -> Artifact:
    """Hash and record the original video as the master artifact (no modification).

    The file is recorded in place (it is typically large and gitignored); its hash
    is the anchor every derivative points back to.
    """
    return manifest.record_file(
        video_path,
        artifact_id=artifact_id,
        kind="video",
        capture_method="master-register",
        tool_version="sha256",
        media_type="video/mp4",
        source_url=source_url,
        source_path=str(video_path),
        notes=notes or "Original walkthrough video; master copy, unmodified.",
    )


def extract_keyframes(
    video_path: str | Path,
    manifest: EvidenceManifest,
    *,
    master_sha256: str,
    artifact_id_prefix: str,
    every_seconds: int = 15,
    out_subdir: str = "video/frames",
) -> list[Artifact]:
    """Sample one still every ``every_seconds`` via ffmpeg; record each as a derivative.

    Returns the recorded frame :class:`Artifact` rows. Each frame's ``derived_from``
    is the master hash and its ``notes`` carry the sampling interval, so the
    derivation is fully documented and reproducible.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH — cannot extract keyframes")

    art_dir = manifest.root / "artifacts" / out_subdir
    art_dir.mkdir(parents=True, exist_ok=True)
    pattern = art_dir / f"{artifact_id_prefix}-%04d.png"

    # fps=1/N -> one frame every N seconds. Deterministic given the same input.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-vf", f"fps=1/{every_seconds}",
        str(pattern),
    ]
    subprocess.run(cmd, check=True)

    ffv = _ffmpeg_version()
    recorded: list[Artifact] = []
    for i, frame in enumerate(sorted(art_dir.glob(f"{artifact_id_prefix}-*.png"))):
        approx_ts = i * every_seconds  # seconds into the video for this still
        recorded.append(manifest.record_file(
            frame,
            artifact_id=f"{artifact_id_prefix}-frame-{i:04d}",
            kind="video_frame",
            capture_method=f"ffmpeg-fps-1/{every_seconds}",
            tool_version=ffv,
            media_type="image/png",
            derived_from=master_sha256,
            notes=f"Keyframe at ~{approx_ts}s; sampled 1 frame / {every_seconds}s.",
        ))
    return recorded


def record_transcript(
    transcript_path: str | Path,
    manifest: EvidenceManifest,
    *,
    artifact_id: str,
    master_sha256: str,
    model: str,
    host: str,
    notes: str = "",
) -> Artifact:
    """Record an externally-produced transcript (e.g. faster-whisper on seshat).

    The transcript is a derivative of the master video; ``model``/``host`` document
    exactly what produced it (responsible-AI provenance: the ASR model is named).
    """
    return manifest.record_file(
        transcript_path,
        artifact_id=artifact_id,
        kind="transcript",
        capture_method=f"asr:{model}@{host}",
        tool_version=model,
        media_type="text/plain",
        derived_from=master_sha256,
        notes=notes or f"Speech-to-text via {model} on {host}.",
    )
