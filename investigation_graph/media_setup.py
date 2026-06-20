"""
Wire this project's config into the shared ``kg_common.media`` subsystem (Phase B).

``kg_common.media`` is a config-agnostic library: it defaults the image backend
to a disabled NoneBackend. This module reads investigation_graph's config
(VISUAL_BACKEND / VISUAL_MODEL / VISUAL_ENDPOINT / VISUAL_TIMEOUT) and registers
an ImageProcessor whose visual backend is built from it — so the operator's
config drives the shared subsystem without kg-common ever importing a consumer
config (the boundary the promotion established).

Call ``configure_media()`` once at ingest startup. Idempotent.
"""
from __future__ import annotations

from kg_common.media import ImageProcessor, get_visual_backend, register_processor

from . import config

_configured = False


def configure_media() -> None:
    """Register a config-driven ImageProcessor ahead of the library defaults."""
    global _configured
    if _configured:
        return
    backend = get_visual_backend(
        getattr(config, "VISUAL_BACKEND", "none"),
        model=getattr(config, "VISUAL_MODEL", None) or None,
        endpoint=getattr(config, "VISUAL_ENDPOINT", "") or None,
        timeout=getattr(config, "VISUAL_TIMEOUT", 120),
    )
    # first=True so this configured processor wins over the library's disabled
    # default ImageProcessor for image files.
    register_processor(ImageProcessor(backend=backend), first=True)
    _configured = True
