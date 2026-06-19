"""OCR routing + graceful-degradation tests (P0.3).

These run WITHOUT tesseract installed: they assert the optional OCR path degrades
cleanly (returns "" instead of crashing) and that image/scanned routing is wired
up. Real OCR-output quality is validated where the tesseract binary is present.
"""
import sys
from pathlib import Path

from investigation_graph.ocr import IMAGE_SUFFIXES, ocr_available, ocr_image, ocr_pdf

sys.path.insert(0, ".")  # so `scripts` imports resolve when run from repo root


def test_ocr_available_returns_bool():
    assert isinstance(ocr_available(), bool)


def test_ocr_image_degrades_gracefully(tmp_path):
    # A bogus image: ocr returns "" whether tesseract is absent or the file is
    # unreadable — never raises.
    img = tmp_path / "scan.png"
    img.write_bytes(b"not really a png")
    assert ocr_image(img) == ""


def test_ocr_pdf_degrades_gracefully(tmp_path):
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 not a real pdf")
    assert ocr_pdf(pdf) == ""


def test_image_formats_are_supported_for_ingest():
    from scripts.ingest_folder import SUPPORTED
    assert ".png" in SUPPORTED and ".jpg" in SUPPORTED
    assert all(s in SUPPORTED for s in IMAGE_SUFFIXES)


def test_read_document_routes_image_to_ocr(tmp_path):
    # An image with no OCR available reads as "" (routed, not "unsupported").
    from scripts.ingest_folder import read_document
    img = tmp_path / "evidence.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0 jpeg-ish bytes")
    assert read_document(img) == ""  # graceful, not a crash


def test_read_document_still_reads_text(tmp_path):
    from scripts.ingest_folder import read_document
    doc = tmp_path / "note.txt"
    doc.write_text("Acme Corp paid a contractor.")
    assert "Acme Corp" in read_document(Path(doc))
