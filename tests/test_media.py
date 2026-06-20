"""Media subsystem tests (P2.1) — the processor interface + dispatch.

Validates the ProcessorResult contract and DocumentProcessor routing without OCR
(image/scanned paths degrade to "" when tesseract is absent — covered in
test_ocr.py). Future visual processors register against this same interface.
"""
from investigation_graph.media import (
    DocumentProcessor,
    ProcessorResult,
    SUPPORTED_SUFFIXES,
    process_media,
)


def test_process_text(tmp_path):
    f = tmp_path / "note.txt"
    f.write_text("Acme Corp paid a contractor.")
    r = process_media(f)
    assert isinstance(r, ProcessorResult)
    assert "Acme Corp" in r.text
    assert r.metadata["kind"] == "text" and r.metadata["ocr_used"] is False


def test_process_html_strips_tags(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<html><body><p>Robert Chen</p><script>x=1</script></body></html>")
    r = process_media(f)
    assert "Robert Chen" in r.text
    assert r.metadata["kind"] == "html"


def test_unsupported_type_is_empty(tmp_path):
    f = tmp_path / "archive.zip"
    f.write_bytes(b"PK\x03\x04")
    r = process_media(f)
    assert r.text == "" and r.metadata["kind"] == "unsupported"


def test_document_processor_accepts():
    dp = DocumentProcessor()
    from pathlib import Path
    assert dp.accepts(Path("a.pdf")) and dp.accepts(Path("a.PNG")) and dp.accepts(Path("a.md"))
    assert not dp.accepts(Path("a.zip"))


def test_supported_suffixes_cover_text_and_images():
    for s in (".txt", ".md", ".html", ".pdf", ".png", ".jpg"):
        assert s in SUPPORTED_SUFFIXES
