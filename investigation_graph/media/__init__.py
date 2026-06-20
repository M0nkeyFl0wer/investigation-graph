"""
Media subsystem (P2.1 scaffold) — one interface for turning any source into a
``ProcessorResult{text, structured, metadata}``.

``process_media(path)`` dispatches to the first registered processor that accepts
the file. Today that's just ``DocumentProcessor`` (text/HTML/PDF+OCR/image-OCR);
future visual processors (ColQwen page retrieval, VLM captioning — see
docs/proposals/visual-ingestion.md) register here without touching the pipeline.

Promotion candidate: this mirrors the ``kg_common/media`` interface and should
move to kg-common so every consumer shares it (ROADMAP PUB.1).
"""
from __future__ import annotations

from pathlib import Path

from .base import BaseProcessor, ProcessorResult
from .document import DocumentProcessor

# Ordered registry. Later/more-specialized processors (visual, image-VLM) go
# BEFORE DocumentProcessor when they should win for a given type.
_PROCESSORS: list[BaseProcessor] = [DocumentProcessor()]

# Suffixes any registered processor will handle (drives ingest's file filter).
SUPPORTED_SUFFIXES: tuple[str, ...] = (
    ".txt", ".md", ".html", ".pdf",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif",
)


def register_processor(processor: BaseProcessor, *, first: bool = True) -> None:
    """Add a processor to the registry (``first=True`` = higher priority)."""
    _PROCESSORS.insert(0, processor) if first else _PROCESSORS.append(processor)


def process_media(path: str | Path) -> ProcessorResult:
    """Read a source into a ProcessorResult via the first processor that accepts
    it. Unknown types return an empty result (kind='unsupported')."""
    p = Path(path)
    for proc in _PROCESSORS:
        if proc.accepts(p):
            return proc.process(p)
    return ProcessorResult(metadata={"kind": "unsupported"})


__all__ = ["BaseProcessor", "ProcessorResult", "DocumentProcessor",
           "process_media", "register_processor", "SUPPORTED_SUFFIXES"]
