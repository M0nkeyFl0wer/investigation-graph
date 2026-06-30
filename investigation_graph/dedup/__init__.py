"""Structured / probabilistic dedup tiers (P2.4 / PUB.5). The deterministic
normalized-name tier (`norm_dedupe`) is dep-free and the adopted common-case tier;
Splink (`splink_dedupe`) is optional (`[dedup-structured]` extra), reserved for
multi-field messy records. Both produce a cluster map that `make_cluster_tier` turns
into a resolution tier for the seam (investigation_graph.resolution)."""
from investigation_graph.dedup.tiers import make_cluster_tier, norm_dedupe, norm_name

__all__ = [
    "norm_dedupe", "make_cluster_tier", "norm_name",
    "splink_dedupe", "splink_dedupe_multifield",
]


def __getattr__(name):
    # Lazy import so the dep-light core never imports splink unless asked. (The
    # multi-field function itself ALSO imports splink only inside its body, so even
    # referencing it here stays import-light until it is actually called.)
    if name == "splink_dedupe":
        from investigation_graph.dedup.splink_tier import splink_dedupe
        return splink_dedupe
    if name == "splink_dedupe_multifield":
        from investigation_graph.dedup.splink_multifield import splink_dedupe_multifield
        return splink_dedupe_multifield
    raise AttributeError(name)
