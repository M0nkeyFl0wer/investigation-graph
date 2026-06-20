"""
Embedding computation via Ollama. Runs locally, nothing leaves the machine.

Robustness: a cold or GPU-saturated Ollama can take a long time or hang. We use
a client with a hard wall-clock timeout so a stuck daemon fails fast instead of
blocking ingestion forever, and ``embed_batch`` degrades gracefully — a failed
batch yields ``None`` embeddings (those chunks still get keyword/FTS search; only
semantic search skips them) rather than aborting the whole run. This matters for
a tool that non-experts run on whatever hardware they have.
"""
import logging

import ollama

from . import config

logger = logging.getLogger(__name__)

# Hard per-request timeout (seconds). Generous enough for slow CPU embedding of a
# batch, short enough that a hung daemon doesn't wedge an ingest. Configurable.
EMBED_TIMEOUT = getattr(config, "EMBED_TIMEOUT", 120)

# One client with the timeout baked in (httpx transport-level, the real knob —
# unlike a model `options` key, which does nothing for timeouts). host=None uses the
# local Ollama; EMBED_ENDPOINT (defaults to EXTRACT_ENDPOINT) routes to a remote GPU box.
_client = ollama.Client(host=getattr(config, "EMBED_ENDPOINT", "") or None,
                        timeout=EMBED_TIMEOUT)


def embed_text(text: str) -> list[float]:
    """Embed one string. Raises on failure/timeout (single-use callers handle it)."""
    try:
        return _client.embed(model=config.EMBEDDING_MODEL, input=text)["embeddings"][0]
    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        raise


def embed_batch(texts: list[str], batch_size: int = 50) -> list[list[float] | None]:
    """Embed many texts, batched. Returns a list aligned to ``texts``; entries for
    a batch that failed or timed out are ``None`` (graceful degradation — the run
    continues with those chunks unembedded rather than hanging or aborting)."""
    out: list[list[float] | None] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            resp = _client.embed(model=config.EMBEDDING_MODEL, input=batch)
            out.extend(resp["embeddings"])
        except Exception as e:
            logger.warning(
                "Batch embedding failed at offset %d (%d texts): %s — "
                "storing those chunks without embeddings (keyword search still works)",
                i, len(batch), e,
            )
            out.extend([None] * len(batch))
    return out
