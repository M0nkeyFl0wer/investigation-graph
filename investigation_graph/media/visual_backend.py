"""
Pluggable visual backend (P2.1) — where heavy vision compute happens.

Image captioning (and, later, ColQwen page-retrieval) needs a real GPU, so the
backend is pluggable and OFF by default. The rest of the code talks to this
interface; *which* machine runs the model is the operator's deployment choice,
configured via ``config.VISUAL_BACKEND`` (+ a local, uncommitted endpoint/key).
This keeps the public repo free of any specific server/API while still shipping a
working seam — flip the knob to turn it on.

Backends:
  none   — disabled (default). describe_image() returns "" → images fall back to
           OCR only. Nothing leaves the machine.
  ollama — a local Ollama vision model (config.VISUAL_MODEL), if you have the GPU.
  remote — an operator-controlled OpenAI-compatible endpoint (your own box).
  api    — an external inference API; NON-SENSITIVE material only (like the
           remote text tier).
  stub   — deterministic, no I/O; for tests.

All methods degrade gracefully (return "" on any failure/timeout) so a flaky or
absent backend never breaks ingestion.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)


class VisualBackend(ABC):
    """A vision-model backend. (Caption today; ColQwen page-embedding later.)"""

    @abstractmethod
    def available(self) -> bool:
        """True if this backend can actually run a vision call right now."""

    @abstractmethod
    def describe_image(self, path: Path) -> str:
        """A short factual description of the image, or "" on failure/disabled.
        Becomes searchable text + extraction input (so a photo's content can
        enter the graph). Must never raise."""


class NoneBackend(VisualBackend):
    """Disabled — the default. Images get OCR only."""

    def available(self) -> bool:
        return False

    def describe_image(self, path: Path) -> str:
        return ""


class StubBackend(VisualBackend):
    """Deterministic, no I/O — for tests and dry runs."""

    def available(self) -> bool:
        return True

    def describe_image(self, path: Path) -> str:
        return f"[stub description of {Path(path).name}]"


class OllamaVisionBackend(VisualBackend):
    """Local Ollama vision model (e.g. a multimodal gemma/llava/qwen-vl)."""

    def __init__(self, model: str | None = None, timeout: int | None = None,
                 host: str | None = None):
        self.model = model or config.VISUAL_MODEL
        self.timeout = timeout or getattr(config, "VISUAL_TIMEOUT", 120)
        # Ollama host: an operator can point this at a controlled GPU box (e.g. a
        # self-hosted server, reached over SSH tunnel / VPN) via VISUAL_ENDPOINT —
        # kept in local config, not committed. Empty → local Ollama (localhost).
        self.host = host or getattr(config, "VISUAL_ENDPOINT", "") or None

    def available(self) -> bool:
        try:
            import ollama  # noqa: F401
        except ImportError:
            return False
        return True

    def describe_image(self, path: Path) -> str:
        if not self.available():
            return ""
        try:
            import ollama
            client = ollama.Client(host=self.host, timeout=self.timeout)
            resp = client.chat(
                model=self.model,
                messages=[{
                    "role": "user",
                    "content": ("Describe this image factually for an investigator: "
                                "people, text, objects, places, dates. Be concise; "
                                "do not speculate."),
                    "images": [str(path)],
                }],
            )
            return (resp.get("message", {}).get("content") or "").strip()
        except Exception as e:  # noqa: BLE001 — flaky/absent vision model → skip
            logger.warning("Vision backend (ollama) failed for %s: %s", Path(path).name, e)
            return ""


def get_visual_backend(name: str | None = None) -> VisualBackend:
    """Construct the configured backend. ``remote``/``api`` are not implemented in
    the public repo (operator wires their own endpoint); they fall back to None
    with a warning so the seam is present without shipping a specific provider."""
    name = (name or getattr(config, "VISUAL_BACKEND", "none") or "none").lower()
    if name == "ollama":
        return OllamaVisionBackend()
    if name == "stub":
        return StubBackend()
    if name in ("remote", "api"):
        logger.warning("VISUAL_BACKEND=%s has no built-in client — wire an "
                       "operator endpoint (config.VISUAL_ENDPOINT) or use "
                       "'ollama'/'none'. Falling back to disabled.", name)
        return NoneBackend()
    return NoneBackend()
