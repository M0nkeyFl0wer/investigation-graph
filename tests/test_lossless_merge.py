"""
Tests for the lossless edge-merge guard (``investigation_graph.lossless_merge``).

The headline test reproduces the real money-loss bug: two name-variant donor
nodes, each carrying a distinct aggregate FUNDS edge to the same party, get
re-pointed onto the same (src, tgt, edge_type) key during entity resolution. The
naive keep-first dedup the pipeline does today would silently throw one aggregate
away — in a sibling project that lost a donor $6,650 across 10 contributions.

We assert two things about that case:
  1. the naive dedup REALLY loses money (demonstrated explicitly, so the test
     documents the bug it guards against), and
  2. the guard either re-aggregates correctly (summed total, summed count,
     unioned dates) or routes to review — never silently drops.

The remaining tests cover the contract's edges: identical-prop collisions are
lossless, currency mismatches route to review (not silently summed), a
propertyless collision collapses cleanly, and a non-colliding edge passes
through untouched.

No LLM, no network, no graph DB — pure simulation over edge dicts.
"""
from investigation_graph.lossless_merge import (
    ReviewCluster,
    plan_lossless_merge,
    reaggregate,
)


def _naive_keep_first(edges, id_map):
    """The buggy behaviour the guard replaces: re-point, drop self-loops, then
    keep the FIRST edge per (src, tgt, edge_type) and silently drop the rest.

    Used by the headline test to *demonstrate* the loss, so the test proves the
    bug exists rather than just asserting the fix.
    """
    seen = {}
    for ed in edges:
        src = id_map.get(ed["source_id"], ed["source_id"])
        tgt = id_map.get(ed["target_id"], ed["target_id"])
        if src == tgt:
            continue
        key = (src, tgt, ed["edge_type"])
        if key not in seen:                      # first wins; rest vanish
            seen[key] = {**ed, "source_id": src, "target_id": tgt}
    return list(seen.values())


# ── The $6,650 case ─────────────────────────────────────────────────────────
def test_reproduces_the_6650_money_loss_and_guard_reaggregates():
    # Three spellings of one donor, all resolved to the canonical id. Each
    # spelling carries its OWN aggregate FUNDS edge to the same party with a
    # distinct amount_total / contribution_count / dates. These are the exact
    # aggregate shape a campaign-finance filing produces per filer.
    edges = [
        {
            "source_id": "donor_ascii", "target_id": "party_x", "edge_type": "FUNDS",
            "amount_total": 2700.0, "contribution_count": 4,
            "dates": [{"date": "2024-01-10", "amount": 1350.0},
                      {"date": "2024-02-10", "amount": 1350.0}],
            "currency": "USD", "source_url": "filing_a.pdf",
        },
        {
            "source_id": "donor_accent", "target_id": "party_x", "edge_type": "FUNDS",
            "amount_total": 2700.0, "contribution_count": 4,
            "dates": [{"date": "2024-03-10", "amount": 1350.0},
                      {"date": "2024-04-10", "amount": 1350.0}],
            "currency": "USD", "source_url": "filing_b.pdf",
        },
        {
            "source_id": "donor_mojibake", "target_id": "party_x", "edge_type": "FUNDS",
            "amount_total": 1250.0, "contribution_count": 2,
            "dates": [{"date": "2024-05-10", "amount": 1250.0}],
            "currency": "USD", "source_url": "filing_c.pdf",
        },
    ]
    # All three spellings collapse to one canonical donor node.
    id_map = {
        "donor_ascii": "donor_canonical",
        "donor_accent": "donor_canonical",
        "donor_mojibake": "donor_canonical",
    }

    # The TRUE total this donor gave: 2700 + 2700 + 1250 = 6650, over 10
    # contributions, across 5 distinct dates.
    true_total = 2700.0 + 2700.0 + 1250.0
    true_count = 4 + 4 + 2
    assert true_total == 6650.0 and true_count == 10

    # 1. Demonstrate the BUG: the naive keep-first dedup keeps only the first
    #    aggregate (2700 / 4) and silently drops the other 3950 / 6.
    naive = _naive_keep_first(edges, id_map)
    assert len(naive) == 1                              # three collapsed to one
    assert naive[0]["amount_total"] == 2700.0           # only the first survived
    lost = true_total - naive[0]["amount_total"]
    assert lost == 3950.0                               # $3,950 silently vanished

    # 2. The guard catches the collision and re-aggregates losslessly.
    plan = plan_lossless_merge(edges, id_map)
    assert not plan.review_clusters                     # additive -> no review
    write = plan.write_edges()
    assert len(write) == 1                              # one edge written
    merged = write[0]
    assert merged["source_id"] == "donor_canonical"
    assert merged["target_id"] == "party_x"
    assert merged["amount_total"] == true_total         # full $6,650 preserved
    assert merged["contribution_count"] == true_count   # all 10 contributions
    # All 5 dated contributions unioned, none lost, none duplicated.
    assert len(merged["dates"]) == 5
    assert merged["currency"] == "USD"
    # The re-aggregated edge is also exposed on its own bucket for reporting.
    assert plan.reaggregated_edges == [merged]


# ── Lossless collision (identical props -> safe collapse) ────────────────────
def test_identical_prop_collision_is_lossless():
    # Two spellings whose aggregate edges carry the SAME data-bearing props.
    # Collapsing loses nothing, so it's a clean safe-collapse — NOT a review.
    edges = [
        {"source_id": "a1", "target_id": "p", "edge_type": "FUNDS",
         "amount_total": 500.0, "currency": "USD", "source_url": "x.pdf"},
        {"source_id": "a2", "target_id": "p", "edge_type": "FUNDS",
         "amount_total": 500.0, "currency": "USD", "source_url": "y.pdf"},
    ]
    plan = plan_lossless_merge(edges, {"a1": "a", "a2": "a"})
    assert not plan.review_clusters
    assert not plan.reaggregated_edges                  # nothing summed
    assert len(plan.write_edges()) == 1
    # Value unchanged: identical 500 stays 500 (NOT doubled to 1000).
    assert plan.write_edges()[0]["amount_total"] == 500.0


# ── Currency mismatch -> review, never silently summed ───────────────────────
def test_currency_mismatch_routes_to_review_not_summed():
    edges = [
        {"source_id": "a1", "target_id": "p", "edge_type": "FUNDS",
         "amount_total": 100.0, "currency": "USD"},
        {"source_id": "a2", "target_id": "p", "edge_type": "FUNDS",
         "amount_total": 100.0, "currency": "CAD"},
    ]
    plan = plan_lossless_merge(edges, {"a1": "a", "a2": "a"})
    # You cannot sum USD + CAD into a meaningful total -> human decision.
    assert len(plan.review_clusters) == 1
    cluster = plan.review_clusters[0]
    assert isinstance(cluster, ReviewCluster)
    assert cluster.reason == "currency_mismatch"
    assert len(cluster.edges) == 2                      # both edges preserved
    # CRITICAL: the conflicting edges are NOT in the safe-write set (not dropped,
    # not blindly written) — they wait for a human.
    assert plan.write_edges() == []
    # And we never invented a 200 total.
    assert all(e["amount_total"] == 100.0 for e in cluster.edges)


def test_non_additive_share_pct_conflict_routes_to_review():
    # share_pct is data-bearing but NOT additive: 55% and 30% to the same target
    # are a contradiction, not two halves of one share. Summing -> wrong number.
    edges = [
        {"source_id": "a1", "target_id": "co", "edge_type": "OWNS", "share_pct": 55.0},
        {"source_id": "a2", "target_id": "co", "edge_type": "OWNS", "share_pct": 30.0},
    ]
    plan = plan_lossless_merge(edges, {"a1": "a", "a2": "a"})
    assert len(plan.review_clusters) == 1
    assert plan.review_clusters[0].reason == "non_additive_conflict:share_pct"
    assert plan.write_edges() == []                     # never summed to 85


# ── Propertyless collision collapses cleanly ─────────────────────────────────
def test_propertyless_collision_collapses_cleanly():
    # Two edges with NO data-bearing props (only provenance, which differs).
    # Provenance differences are not conflict-significant -> lossless collapse.
    edges = [
        {"source_id": "a1", "target_id": "p", "edge_type": "KNOWS",
         "source_url": "x.pdf", "evidence": "row 1"},
        {"source_id": "a2", "target_id": "p", "edge_type": "KNOWS",
         "source_url": "y.pdf", "evidence": "row 9"},
    ]
    plan = plan_lossless_merge(edges, {"a1": "a", "a2": "a"})
    assert not plan.review_clusters
    assert not plan.reaggregated_edges
    assert len(plan.write_edges()) == 1


# ── Non-colliding edge passes through untouched ──────────────────────────────
def test_non_colliding_edge_passes_through_untouched():
    # Distinct targets -> distinct keys -> no collision. Both edges survive,
    # unchanged, with endpoints re-pointed through the id_map.
    edges = [
        {"source_id": "a1", "target_id": "p1", "edge_type": "FUNDS",
         "amount_total": 100.0, "currency": "USD"},
        {"source_id": "a1", "target_id": "p2", "edge_type": "FUNDS",
         "amount_total": 200.0, "currency": "USD"},
    ]
    plan = plan_lossless_merge(edges, {"a1": "donor"})
    assert not plan.review_clusters
    assert not plan.reaggregated_edges
    write = plan.write_edges()
    assert len(write) == 2
    # Endpoints re-pointed, amounts untouched (no merge happened).
    assert {e["target_id"] for e in write} == {"p1", "p2"}
    assert {e["amount_total"] for e in write} == {100.0, 200.0}
    assert all(e["source_id"] == "donor" for e in write)


# ── reaggregate() unit contract ──────────────────────────────────────────────
def test_reaggregate_unions_dates_dedup_by_date_amount():
    # Two filings reporting the SAME dated contribution must collapse to one in
    # the union (de-duped by (date, amount)); genuinely distinct ones survive.
    edges = [
        {"source_id": "d", "target_id": "p", "edge_type": "FUNDS",
         "contribution_count": 2,
         "dates": [{"date": "2024-01-01", "amount": 50.0},
                   {"date": "2024-02-01", "amount": 50.0}]},
        {"source_id": "d", "target_id": "p", "edge_type": "FUNDS",
         "contribution_count": 1,
         # First element duplicates the other edge's first; second is new.
         "dates": [{"date": "2024-01-01", "amount": 50.0},
                   {"date": "2024-03-01", "amount": 50.0}]},
    ]
    merged, reason = reaggregate(edges)
    assert reason is None
    assert merged["contribution_count"] == 3            # counts still sum
    assert len(merged["dates"]) == 3                    # 4 entries, 1 duplicate
    seen = {(d["date"], d["amount"]) for d in merged["dates"]}
    assert seen == {("2024-01-01", 50.0), ("2024-02-01", 50.0), ("2024-03-01", 50.0)}
