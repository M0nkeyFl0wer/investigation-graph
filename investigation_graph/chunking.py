"""
One chunker, used by BOTH ingestion (what gets embedded into DuckDB) and
extraction (what the LLM reads). Sharing it is what makes edge/entity provenance
real: an entity or edge can cite the SAME chunk id that holds its source text
(``chunk_store.chunk_id_from_uri(source_uri, index)``), so grounding checks the
actual span — not a whole-document substring guess.

Defaults: 1000-char windows with 200-char overlap. Overlap keeps a sentence that
straddles a boundary recoverable in at least one window.
"""
from __future__ import annotations

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 200


def chunk_text(text: str, chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """Split text into overlapping fixed-width windows.

    Returns [] for empty/whitespace text. Window i spans
    [i*(size-overlap), i*(size-overlap)+size), so chunk index lines up with
    ``chunk_id_from_uri(source_uri, index)`` everywhere.
    """
    if not text or not text.strip():
        return []
    step = max(1, chunk_size - overlap)
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += step
    return chunks
