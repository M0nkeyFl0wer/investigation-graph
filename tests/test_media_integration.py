"""Phase B integration — investigation-graph uses the SHARED kg_common.media,
wired via media_setup.configure_media().

Unit-level media behavior (processors, OCR, visual backends) is tested in
kg-common. Here we only confirm the consumer wiring + dispatch work: config →
configure_media() → kg_common.media registry → process_media().
"""
from pathlib import Path

from investigation_graph.media_setup import configure_media
from kg_common.media import SUPPORTED_SUFFIXES, process_media


def test_configure_is_idempotent_and_processes_text(tmp_path):
    configure_media()
    configure_media()  # safe to call twice
    f = tmp_path / "note.txt"
    f.write_text("Acme Corp paid a contractor.")
    r = process_media(f)
    assert "Acme Corp" in r.text and r.metadata["kind"] == "text"


def test_supported_suffixes_come_from_library():
    for s in (".txt", ".md", ".html", ".pdf", ".png", ".jpg"):
        assert s in SUPPORTED_SUFFIXES


def test_read_document_wrapper_uses_library(tmp_path):
    from scripts.ingest_folder import read_document
    f = tmp_path / "d.txt"
    f.write_text("Robert Chen, Meridian Holdings LLC")
    assert "Meridian Holdings" in read_document(Path(f))
