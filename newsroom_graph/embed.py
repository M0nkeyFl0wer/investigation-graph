"""
Embedding computation via Ollama. Runs locally, nothing leaves the machine.

Note on timeouts: the Ollama HTTP client's timeout is governed by the
``OLLAMA_*`` env / client config, not by a model ``options`` key — passing
``options={"timeout": ...}`` is a no-op (``options`` carries model params like
temperature, not transport timeouts), so we don't. If the daemon is cold or the
GPU is loaded, the FIRST call blocks while the model loads; that's expected.
Callers that need a hard wall-clock bound should wrap these in their own timeout.
"""
import logging

import ollama

from . import config

logger = logging.getLogger(__name__)


def embed_text(text: str) -> list[float]:
    """Compute an embedding for one string via local Ollama.
    Raises if Ollama is unreachable."""
    try:
        response = ollama.embed(model=config.EMBEDDING_MODEL, input=text)
        return response["embeddings"][0]
    except Exception as e:
        logger.warning("Embedding failed: %s", e)
        raise


def embed_batch(texts: list[str], batch_size: int = 50) -> list[list[float]]:
    """Compute embeddings for many texts, batched to avoid overwhelming Ollama.
    Raises on first failure — the caller decides how to handle partial results."""
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        try:
            response = ollama.embed(model=config.EMBEDDING_MODEL, input=batch)
            all_embeddings.extend(response["embeddings"])
        except Exception as e:
            logger.warning("Batch embedding failed at offset %d: %s", i, e)
            raise
    return all_embeddings
