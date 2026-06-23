"""
Splink structured-dedup tier (P2.4 / PUB.5 — the `[dedup-structured]` extra).

Splink (UK MoJ, MIT) is a Fellegi-Sunter probabilistic linker that runs *natively
on the DuckDB base we already have*. It is a BATCH deduper (train a model → cluster
the whole record set), not a per-record lookup — so it plugs into the resolution-tier
seam as a **pre-pass + lookup**: `splink_dedupe` clusters the structured entity batch
once, and `make_splink_tier` turns that cluster map into a `ResolutionTier` that
merges each candidate onto an already-registered member of its cluster.

Scope + safety (review): Splink is NOT zero-config like the base resolver — it needs
column comparisons + an EM pass — so it is for the STRUCTURED path (tabular), not the
free-text cascade. And it fails *confidently* (calibrated-looking weights behind a
wrong merge), which is the libel surface — so its merges must still route through the
P1.3 merge-review gate, and the bundled model must beat the base resolver on
sme-eval BEFORE it's trusted (see scripts/eval_splink_delta.py). Blocking is on
`entity_type` so it never proposes a cross-type merge (our hard rule).
"""
from __future__ import annotations

import logging

from investigation_graph.dedup.tiers import norm_name

# Splink is chatty; keep its INFO noise out of our logs.
for _n in ("splink", "py4j"):
    logging.getLogger(_n).setLevel(logging.WARNING)


def splink_dedupe(records: list[dict], *, match_threshold: float = 0.9,
                  seed: int = 42) -> dict[str, str]:
    """Cluster structured entity records with Splink (Fellegi-Sunter, on DuckDB).

    ``records``: ``[{"unique_id", "name", "entity_type"}, ...]``. Returns
    ``{unique_id: cluster_id}``. Blocks within ``entity_type`` so cross-type pairs
    are never even compared. Degrades gracefully (each record its own cluster) if
    the batch is too small for the model to estimate.
    """
    import pandas as pd
    from splink import DuckDBAPI, Linker, SettingsCreator
    from splink import comparison_library as cl

    df = pd.DataFrame(records)
    if len(df) < 4:
        return {str(r["unique_id"]): str(r["unique_id"]) for _, r in df.iterrows()}
    df["name_norm"] = df["name"].map(norm_name)

    settings = SettingsCreator(
        link_type="dedupe_only",
        comparisons=[cl.NameComparison("name")],
        # Block predictions on the normalized name AND restrict to same type — so
        # cross-type pairs are never compared (our hard rule), and the variant pairs
        # actually enter the candidate set.
        blocking_rules_to_generate_predictions=[
            "l.name_norm = r.name_norm and l.entity_type = r.entity_type"],
    )
    linker = Linker(df, settings, db_api=DuckDBAPI())
    try:
        # Prior from a deterministic rule that DOES observe matches (normalized-name
        # equality), then u by sampling, then m by EM over those blocked pairs.
        linker.training.estimate_probability_two_random_records_match(
            ["l.name_norm = r.name_norm"], recall=0.9)
        linker.training.estimate_u_using_random_sampling(max_pairs=1e6, seed=seed)
        linker.training.estimate_parameters_using_expectation_maximisation(
            "l.name_norm = r.name_norm")
        preds = linker.inference.predict()
        clusters = linker.clustering.cluster_pairwise_predictions_at_threshold(
            preds, threshold_match_probability=match_threshold)
        cdf = clusters.as_pandas_dataframe()
        return {str(r["unique_id"]): str(r["cluster_id"]) for _, r in cdf.iterrows()}
    except Exception as e:  # estimation can fail on degenerate batches — degrade safe
        logging.getLogger(__name__).warning("Splink dedup degraded (%s); identity clusters", e)
        return {str(r["unique_id"]): str(r["unique_id"]) for _, r in df.iterrows()}

