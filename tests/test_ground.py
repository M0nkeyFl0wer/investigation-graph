"""Ground-stage P1 tests — tighter grounding, semantic ER, merge review.

All deterministic and Ollama-free: the embedding tier is exercised with synthetic
vectors passed straight in, so the cosine-merge logic is validated without a
model.
"""
from investigation_graph.pipeline import _label_in_text, ground_and_resolve


# ── P1.2 — whole-word grounding ──────────────────────────────────────────────

def test_label_in_text_is_whole_word():
    assert _label_in_text("acme", "acme corp paid a contractor")
    # substring-but-not-word must NOT match (the spurious-grounding bug)
    assert not _label_in_text("cap", "capacity planning at city hall")
    assert not _label_in_text("x", "too short to ground")


def test_grounding_quarantines_substring_only_entity():
    chunks = [{"id": "c1", "text": "Capacity planning at the harbor."}]
    entities = [
        {"id": "good", "entity_type": "location", "label": "harbor"},   # whole word
        {"id": "bad", "entity_type": "organization", "label": "cap"},   # only in 'Capacity'
    ]
    out, rep = ground_and_resolve(chunks, entities, [])
    ids = {e["id"] for e in out["entities"]}
    assert "good" in ids
    assert "bad" not in ids                       # quarantined — not a whole word
    assert rep["entities_quarantined"] == 1


# ── P1.1 — semantic (embedding) tier ─────────────────────────────────────────

def test_embedding_tier_merges_non_fuzzy_aliases():
    # Two same-type entities with unrelated labels (no exact/fuzzy match) but
    # near-identical embeddings → should merge ONLY via the cosine tier.
    chunks = [{"id": "c1", "text": "Globex and Initech operate together."}]
    entities = [
        {"id": "globex", "entity_type": "organization", "label": "Globex"},
        {"id": "initech", "entity_type": "organization", "label": "Initech"},
    ]
    embeddings = {"globex": [1.0, 0.0, 0.0, 0.0], "initech": [0.98, 0.2, 0.0, 0.0]}
    out, rep = ground_and_resolve(chunks, entities, [], embeddings=embeddings,
                                  threshold=0.92)
    assert rep["entities_merged"] == 1
    assert rep["entities_out"] == 1
    assert rep["merges"][0]["via_embedding"] is True


def test_stance_type_is_excluded_from_cosine_tier():
    """A stance-bearing type (here ``claim``) must NOT be merged by the cosine
    tier even when its vectors are near-identical: opposing stances embed alike,
    so an embedding merge would fuse two contradictory claims. The pipeline
    withholds the embedding for stance types, so the high-cosine pair survives as
    two nodes. (An ``organization`` with the same vectors WOULD merge — proven by
    test_embedding_tier_merges_non_fuzzy_aliases — so this isolates the exclusion.)
    """
    # Distinct labels with NO shared tokens (so fuzzy can't merge them) but
    # near-identical embeddings (so the cosine tier WOULD, if engaged).
    chunks = [{"id": "c1", "text": "The payment occurred according to one source; "
                                    "another source says nothing happened."}]
    entities = [
        {"id": "claim_a", "entity_type": "claim", "label": "The payment occurred"},
        {"id": "claim_b", "entity_type": "claim", "label": "Nothing happened"},
    ]
    # Near-identical vectors that WOULD merge if the cosine tier were engaged.
    embeddings = {"claim_a": [1.0, 0.0, 0.0, 0.0], "claim_b": [0.98, 0.2, 0.0, 0.0]}
    out, rep = ground_and_resolve(chunks, entities, [], embeddings=embeddings,
                                  threshold=0.92)
    assert rep["entities_merged"] == 0       # cosine tier never saw the embeddings
    assert rep["entities_out"] == 2


def test_no_embedding_merge_below_threshold():
    chunks = [{"id": "c1", "text": "Globex and Initech operate together."}]
    entities = [
        {"id": "globex", "entity_type": "organization", "label": "Globex"},
        {"id": "initech", "entity_type": "organization", "label": "Initech"},
    ]
    # Orthogonal vectors → cosine 0 → no merge.
    embeddings = {"globex": [1.0, 0.0, 0.0, 0.0], "initech": [0.0, 1.0, 0.0, 0.0]}
    out, rep = ground_and_resolve(chunks, entities, [], embeddings=embeddings,
                                  threshold=0.92)
    assert rep["entities_merged"] == 0
    assert rep["entities_out"] == 2


# ── P1.3 — merge-review record ───────────────────────────────────────────────

def test_merge_record_has_both_labels_for_review():
    chunks = [{"id": "c1", "text": "Jane Smith works at Acme Corp."},
              {"id": "c2", "text": "Acme Corp later paid Jane Smith."}]
    entities = [
        {"id": "j1", "entity_type": "person", "label": "Jane Smith"},
        {"id": "j2", "entity_type": "person", "label": "Jane Smith"},  # exact dup
    ]
    out, rep = ground_and_resolve(chunks, entities, [])
    assert rep["entities_merged"] == 1
    rec = rep["merges"][0]
    assert rec["kept_label"] == "Jane Smith" and rec["merged_label"] == "Jane Smith"
    assert rec["kept_id"] == "j1" and rec["merged_id"] == "j2"
    assert rec["via_embedding"] is False          # merged by exact-name, not cosine


# ── Lossless edge merge — the $6,650 silent-drop bug, end-to-end ─────────────

def test_merge_preserves_aggregate_edge_data_end_to_end():
    """When two duplicate donor nodes merge, their distinct aggregate FUNDS edges
    to the same party must be RE-AGGREGATED, not keep-first-dropped.

    This is the integration-level proof for the lossless_merge guard: the unit
    tests exercise the primitive, this one proves the wiring inside
    ground_and_resolve actually preserves the money along the real path.
    """
    chunks = [
        {"id": "c1", "text": "Acme PAC contributed to the Northside Party."},
        {"id": "c2", "text": "Acme PAC again funded the Northside Party."},
    ]
    # Two exact-duplicate donor surface forms (a real filing artifact: the same
    # PAC keyed twice) that collapse to one canonical node via the exact tier.
    entities = [
        {"id": "d1", "entity_type": "organization", "label": "Acme PAC"},
        {"id": "d2", "entity_type": "organization", "label": "Acme PAC"},
        {"id": "p1", "entity_type": "organization", "label": "Northside Party"},
    ]
    # Each donor copy carries a DISTINCT aggregate FUNDS edge to the same party.
    # A keep-first dedup would keep $2,700 and silently lose $3,950.
    edges = [
        {"source_id": "d1", "target_id": "p1", "edge_type": "FUNDS",
         "amount_total": 2700, "contribution_count": 4,
         "dates": ["2024-01-10", "2024-02-14"], "currency": "USD"},
        {"source_id": "d2", "target_id": "p1", "edge_type": "FUNDS",
         "amount_total": 3950, "contribution_count": 6,
         "dates": ["2024-03-01", "2024-04-02"], "currency": "USD"},
    ]
    out, rep = ground_and_resolve(chunks, entities, edges)

    assert rep["entities_merged"] == 1          # d1/d2 folded to one donor
    funds = [e for e in out["edges"] if e["edge_type"] == "FUNDS"]
    assert len(funds) == 1                       # collapsed to a single edge...
    assert funds[0]["amount_total"] == 6650      # ...but the money is SUMMED, not lost
    assert funds[0]["contribution_count"] == 10
    assert sorted(funds[0]["dates"]) == [
        "2024-01-10", "2024-02-14", "2024-03-01", "2024-04-02",
    ]
    assert not rep["lossy_edge_clusters"]        # additive → re-aggregated, no review needed


def test_currency_conflict_routes_to_review_not_silent_sum():
    """A merge that would collide two FUNDS edges in DIFFERENT currencies must NOT
    invent a mixed-unit sum — it routes to human review and writes neither blind.
    """
    chunks = [
        {"id": "c1", "text": "Globex Ltd contributed to the Northside Party."},
        {"id": "c2", "text": "Globex Ltd again funded the Northside Party."},
    ]
    entities = [
        {"id": "g1", "entity_type": "organization", "label": "Globex Ltd"},
        {"id": "g2", "entity_type": "organization", "label": "Globex Ltd"},
        {"id": "p1", "entity_type": "organization", "label": "Northside Party"},
    ]
    edges = [
        {"source_id": "g1", "target_id": "p1", "edge_type": "FUNDS",
         "amount_total": 1000, "currency": "USD"},
        {"source_id": "g2", "target_id": "p1", "edge_type": "FUNDS",
         "amount_total": 1000, "currency": "CAD"},
    ]
    out, rep = ground_and_resolve(chunks, entities, edges)

    assert rep["entities_merged"] == 1
    # The conflicting collision is surfaced for review, not collapsed.
    assert len(rep["lossy_edge_clusters"]) == 1
    assert rep["lossy_edge_clusters"][0]["reason"] == "currency_mismatch"
    # And the conflicting FUNDS edge is NOT written blind (no invented mixed sum).
    assert not [e for e in out["edges"] if e["edge_type"] == "FUNDS"]
