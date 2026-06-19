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
