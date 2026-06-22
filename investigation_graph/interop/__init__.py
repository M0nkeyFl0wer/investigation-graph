"""Interop adapters (P2.5+). Thin local adapters so the eventual kg-common ABC
hooks (PUB.6) are a lift-and-shift, not a redesign."""
from investigation_graph.interop.ftm import (
    FTM_VERSION_VERIFIED,
    NO_FTM_HOME,
    CrosswalkResult,
    from_ftm,
    to_ftm,
)

__all__ = ["to_ftm", "from_ftm", "CrosswalkResult", "NO_FTM_HOME",
           "FTM_VERSION_VERIFIED"]
