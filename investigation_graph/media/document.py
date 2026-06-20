"""
DocumentProcessor — text, HTML, PDF (with scanned-PDF OCR fallback), and image
files (OCR). This is the default processor; it consolidates what used to live in
``scripts/ingest_folder.read_document`` behind the BaseProcessor interface so
future visual processors (ColQwen, VLM) can sit alongside it.

Records provenance in ``metadata``: which reader was used and whether OCR fired —
useful downstream (e.g. an investigator wants to know a value came from OCR, not
a clean text layer).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..ocr import IMAGE_SUFFIXES, ocr_image, ocr_pdf
from .base import BaseProcessor, ProcessorResult

# Below this many chars from a PDF's text layer, treat it as scanned → OCR.
_SCANNED_PDF_THRESHOLD = 40
_TEXT_SUFFIXES = (".txt", ".md")


class DocumentProcessor(BaseProcessor):
    """Default reader for text/HTML/PDF/image sources."""

    def accepts(self, path: Path) -> bool:
        s = path.suffix.lower()
        return s in _TEXT_SUFFIXES or s in (".html", ".pdf") or s in IMAGE_SUFFIXES

    def process(self, path: Path) -> ProcessorResult:
        suffix = path.suffix.lower()
        if suffix in _TEXT_SUFFIXES:
            return ProcessorResult(text=path.read_text(errors="replace"),
                                   metadata={"kind": "text", "ocr_used": False})
        if suffix == ".html":
            return ProcessorResult(text=self._read_html(path),
                                   metadata={"kind": "html", "ocr_used": False})
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix in IMAGE_SUFFIXES:
            text = ocr_image(path)
            return ProcessorResult(text=text,
                                   metadata={"kind": "image", "ocr_used": bool(text.strip())})
        return ProcessorResult(metadata={"kind": "unsupported"})

    # ── format readers ────────────────────────────────────────────────────

    @staticmethod
    def _read_html(path: Path) -> str:
        from html.parser import HTMLParser

        class _Text(HTMLParser):
            def __init__(self):
                super().__init__()
                self.parts: list[str] = []

            def handle_data(self, data):
                self.parts.append(data)

        p = _Text()
        p.feed(path.read_text(errors="replace"))
        return " ".join(p.parts)

    def _read_pdf(self, path: Path) -> ProcessorResult:
        text = ""
        try:
            result = subprocess.run(
                ["pdftotext", str(path), "-"],
                capture_output=True, text=True, timeout=30,
            )
            text = result.stdout
        except FileNotFoundError:
            # poppler missing — note it; OCR fallback will also need it to render.
            pass
        except Exception:
            pass
        # Scanned PDF (no/scant text layer) → OCR the rasterized pages.
        if len((text or "").strip()) < _SCANNED_PDF_THRESHOLD:
            ocr_text = ocr_pdf(path)
            if ocr_text.strip():
                return ProcessorResult(text=ocr_text,
                                       metadata={"kind": "pdf", "ocr_used": True})
        return ProcessorResult(text=text, metadata={"kind": "pdf", "ocr_used": False})
