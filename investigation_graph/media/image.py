"""
ImageProcessor (P2.1) — photos, screenshots, maps.

A lot of OSINT signal is in images, not just their text. This processor combines:
  - OCR text in the image (any words: signage, captions, document photos), and
  - an optional VLM **description** (people, objects, places — content OCR misses),

so an image's meaning enters the graph as searchable text + extraction input.
The VLM step runs only if a visual backend is enabled (config.VISUAL_BACKEND);
otherwise it's OCR-only (graceful — identical to the prior behavior). Registered
ahead of DocumentProcessor so it wins for image files.
"""
from __future__ import annotations

from pathlib import Path

from ..ocr import IMAGE_SUFFIXES, ocr_image
from .base import BaseProcessor, ProcessorResult
from .visual_backend import VisualBackend, get_visual_backend


class ImageProcessor(BaseProcessor):
    def __init__(self, backend: VisualBackend | None = None):
        # Resolve the backend lazily/once; tests can inject a StubBackend.
        self._backend = backend or get_visual_backend()

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in IMAGE_SUFFIXES

    def process(self, path: Path) -> ProcessorResult:
        ocr_text = ocr_image(path)
        caption = self._backend.describe_image(path) if self._backend.available() else ""

        # Compose the searchable text: caption first (the gist), then OCR'd words.
        parts = []
        if caption:
            parts.append(caption)
        if ocr_text.strip():
            parts.append(ocr_text.strip())
        text = "\n\n".join(parts)

        return ProcessorResult(
            text=text,
            structured={"caption": caption, "ocr_text": ocr_text},
            metadata={
                "kind": "image",
                "ocr_used": bool(ocr_text.strip()),
                "vlm_used": bool(caption),
            },
        )
