"""Visual backend + ImageProcessor tests (P2.1).

Deterministic, no GPU/model: the StubBackend stands in for a real VLM so the
plumbing (backend selection, ImageProcessor composition, graceful disable) is
validated in-repo. Real backends (Ollama VLM / a self-hosted endpoint) are a
config flip, exercised where GPU compute is available.
"""

from investigation_graph.media.image import ImageProcessor
from investigation_graph.media.visual_backend import (
    NoneBackend,
    StubBackend,
    get_visual_backend,
)


def test_backend_selection():
    assert isinstance(get_visual_backend("none"), NoneBackend)
    assert isinstance(get_visual_backend("stub"), StubBackend)
    # remote/api have no built-in client in the public repo → safe fallback
    assert isinstance(get_visual_backend("remote"), NoneBackend)
    assert isinstance(get_visual_backend(None), NoneBackend)  # default disabled


def test_none_backend_is_disabled(tmp_path):
    b = NoneBackend()
    assert b.available() is False
    assert b.describe_image(tmp_path / "x.png") == ""


def test_image_processor_uses_caption_when_backend_enabled(tmp_path):
    img = tmp_path / "evidence.png"
    img.write_bytes(b"not a real png")          # OCR will yield "" (no tesseract)
    r = ImageProcessor(backend=StubBackend()).process(img)
    assert "stub description" in r.text          # caption became searchable text
    assert r.metadata["kind"] == "image" and r.metadata["vlm_used"] is True
    assert r.structured["caption"]               # caption captured for provenance


def test_image_processor_degrades_to_ocr_only_when_disabled(tmp_path):
    img = tmp_path / "evidence.png"
    img.write_bytes(b"not a real png")
    r = ImageProcessor(backend=NoneBackend()).process(img)
    # No backend + no tesseract → empty, but graceful (kind=image, vlm_used False)
    assert r.metadata["vlm_used"] is False and r.metadata["kind"] == "image"
    assert r.text == ""
