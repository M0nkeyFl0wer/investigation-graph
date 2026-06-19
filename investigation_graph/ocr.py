"""
OCR fallback — get text out of scanned PDFs and image files (P0.3).

A lot of an OSINT/journalism corpus is scanned filings, photographed documents,
and screenshots. ``pdftotext`` returns nothing on those (no text layer), so they
were silently invisible to the graph. This module adds an OCR path.

**Optional by design.** OCR needs the Tesseract binary + ``pytesseract``; PDF
rasterization uses poppler's ``pdftoppm`` (already a dependency for PDF text).
If any piece is missing, every function here degrades gracefully — it logs a
single clear install hint and returns ``""`` — so the tool still runs (you just
can't read scans until you install the optional deps). Install:

    pip install "investigation-graph[ocr]"      # pytesseract
    # plus the system binaries:
    #   Debian/Ubuntu: sudo apt install tesseract-ocr poppler-utils
    #   macOS:         brew install tesseract poppler

This is the pragmatic first cut. Full visual understanding (layout-aware OCR,
ColQwen visual retrieval, region grounding) is the larger subsystem in
docs/proposals/visual-ingestion.md.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Image formats we'll route through OCR.
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif")

_warned = False


def _warn_once(msg: str) -> None:
    """Emit the install hint once per process (don't spam per file/page)."""
    global _warned
    if not _warned:
        logger.warning("%s", msg)
        _warned = True


def ocr_available() -> bool:
    """True iff OCR can actually run: ``pytesseract`` importable + a ``tesseract``
    binary on PATH. Cheap to call; used to decide whether to attempt OCR."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return shutil.which("tesseract") is not None


def ocr_image(path: Path) -> str:
    """OCR a single image file → text. Returns "" (with a one-time hint) if OCR
    isn't available or the image can't be read."""
    if not ocr_available():
        _warn_once("OCR unavailable (need tesseract + pytesseract) — skipping "
                   "image/scanned files. Install: pip install "
                   "'investigation-graph[ocr]' + the tesseract binary.")
        return ""
    try:
        import pytesseract
        from PIL import Image
        with Image.open(path) as img:
            return pytesseract.image_to_string(img) or ""
    except Exception as e:  # noqa: BLE001 — any read/decode error → skip this file
        logger.warning("OCR failed for %s: %s", path.name, e)
        return ""


def ocr_pdf(path: Path, *, dpi: int = 300, max_pages: int = 50) -> str:
    """OCR a scanned PDF by rasterizing pages (poppler ``pdftoppm``) and running
    Tesseract on each. Returns "" gracefully if OCR/poppler aren't available.

    ``max_pages`` bounds work on huge scans; ``dpi`` 300 is the Tesseract sweet
    spot (lower loses small print, higher mostly costs time).
    """
    if not ocr_available():
        _warn_once("OCR unavailable (need tesseract + pytesseract) — scanned "
                   "PDFs will yield no text. Install the [ocr] extra + tesseract.")
        return ""
    if shutil.which("pdftoppm") is None:
        _warn_once("pdftoppm (poppler-utils) not found — cannot rasterize PDFs "
                   "for OCR. Install poppler-utils.")
        return ""
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return ""

    with tempfile.TemporaryDirectory(prefix="ig-ocr-") as tmp:
        prefix = Path(tmp) / "page"
        # Rasterize → page-1.png, page-2.png, … (one checkpoint of work, then read)
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", str(dpi), str(path), str(prefix)],
                check=True, capture_output=True, timeout=300,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("pdftoppm failed for %s: %s", path.name, e)
            return ""
        pages = sorted(Path(tmp).glob("page*.png"))[:max_pages]
        out: list[str] = []
        for pg in pages:
            try:
                with Image.open(pg) as img:
                    out.append(pytesseract.image_to_string(img) or "")
            except Exception as e:  # noqa: BLE001
                logger.warning("OCR failed on %s page %s: %s", path.name, pg.name, e)
        return "\n".join(out)
