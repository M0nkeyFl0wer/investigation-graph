"""
The media processor interface (P2.1 scaffold).

Every kind of source — a digital PDF, a scanned image, (later) a visually-rich
page handled by a vision model — is turned into the SAME shape by a processor, so
the rest of the pipeline (chunk → embed → extract → ground → build) never has to
care how the bytes were read:

    ProcessorResult{ text, structured, metadata }

- ``text``       — extracted text, what gets chunked/embedded/extracted.
- ``structured`` — processor-specific structured output (tables, regions, page
                   boxes…), for future visual processors. Empty for plain text.
- ``metadata``   — provenance about HOW it was read (kind, ocr_used, pages…).

A ``BaseProcessor`` declares what it ``accepts`` and how it ``process``es. The
registry (``__init__.process_media``) dispatches to the first that accepts a path.
New capabilities (ColQwen visual retrieval, VLM captioning — see
docs/proposals/visual-ingestion.md) are added as new processors, not by touching
the pipeline. This mirrors the ``kg_common/media`` interface sketched in the
seabrick handoff and is a candidate to promote to kg-common (ROADMAP PUB.1).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ProcessorResult:
    """Uniform output of any media processor."""
    text: str = ""
    structured: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class BaseProcessor(ABC):
    """A handler for one family of source formats."""

    @abstractmethod
    def accepts(self, path: Path) -> bool:
        """True if this processor can handle the file at ``path``."""

    @abstractmethod
    def process(self, path: Path) -> ProcessorResult:
        """Read ``path`` into a ProcessorResult. Must degrade gracefully —
        return an empty/near-empty result rather than raising on a bad file."""
