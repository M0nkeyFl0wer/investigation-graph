"""
Smoke + integration tests for the DuckDB(base)+LadybugDB(graph) hybrid.

These lock in the behaviors verified by hand during the kg-common alignment and
require NO Ollama (embeddings/extraction are synthetic) — so the suite is
deterministic and fast, and the pre-push gate has real teeth. The full
Ollama-backed end-to-end is exercised separately by running scripts/ingest_folder
against a real corpus.
"""
import pytest

from investigation_graph.ontology import Ontology


# ── Ontology: grade-locality + alias normalization ───────────────────────────

def test_ontology_loads_expected_types():
    o = Ontology()
    assert "person" in o.NODE_TYPES and "organization" in o.NODE_TYPES
    assert "EMPLOYED_BY" in o.EDGE_TYPES
    # property/structural edges are excluded from the relation vocabulary
    assert "OCCURRED_ON" not in o.EDGE_TYPES
    assert "MENTIONED_IN" not in o.EDGE_TYPES


def test_grade_locality_rejects_bad_endpoints():
    o = Ontology()
    ok, _ = o.validate_edge("person", "EMPLOYED_BY", "organization")
    assert ok
    bad, reason = o.validate_edge("organization", "EMPLOYED_BY", "person")
    assert not bad and "grade" in reason.lower()


def test_alias_normalization():
    o = Ontology()
    assert o.normalize_node_type("company") == "organization"
    assert o.canonical_edge_type("WORKS_FOR") == "EMPLOYED_BY"
    assert o.validate_entity_type("company")          # via alias
    assert not o.validate_entity_type("weapon")       # genuinely unknown


# ── Ground stage: grounding gate + entity resolution ─────────────────────────

def test_ground_quarantines_hallucination_and_merges_duplicate():
    from investigation_graph.pipeline import ground_and_resolve

    chunks = [
        {"id": "c1", "text": "Jane Smith works at Acme Corp."},
        {"id": "c2", "text": "Acme Corp later paid Jane Smith."},
    ]
    entities = [
        {"id": "j1", "entity_type": "person", "label": "Jane Smith"},
        {"id": "a1", "entity_type": "organization", "label": "Acme Corp"},
        {"id": "j2", "entity_type": "person", "label": "Jane Smith"},        # duplicate
        {"id": "g1", "entity_type": "person", "label": "Phantom Person"},    # hallucinated
    ]
    edges = [
        {"source_id": "j1", "target_id": "a1", "edge_type": "EMPLOYED_BY"},
        {"source_id": "j2", "target_id": "a1", "edge_type": "EMPLOYED_BY"},
        {"source_id": "j1", "target_id": "g1", "edge_type": "ASSOCIATED_WITH"},  # endpoint ungrounded
    ]
    out, rep = ground_and_resolve(chunks, entities, edges)

    ids = {e["id"] for e in out["entities"]}
    assert "g1" not in ids                     # hallucination quarantined
    assert rep["entities_merged"] == 1         # j2 → j1
    assert rep["entities_out"] == 2            # Jane + Acme
    assert all(e["target_id"] != "g1" for e in out["edges"])  # fabricated edge dropped
    assert all(e["source_id"] == "j1" for e in out["edges"])  # re-pointed to canonical


# ── Graph projection: build + grade-locality at write + read ─────────────────

def test_build_graph_projection_rejects_grade_violation(tmp_path):
    from investigation_graph.graph import Graph, build_graph

    gdir = tmp_path / "g.lbug"
    onto = Ontology()
    records = {
        "documents": [{"id": "doc1", "title": "Expose", "path": "doc1.txt"}],
        "entities": [
            {"id": "e_jane", "entity_type": "person", "label": "Jane Smith"},
            {"id": "e_acme", "entity_type": "organization", "label": "Acme Corp"},
        ],
        "edges": [
            {"source_id": "e_jane", "target_id": "e_acme", "edge_type": "EMPLOYED_BY"},
            # grade violation: org --EMPLOYED_BY--> person must be rejected at write
            {"source_id": "e_acme", "target_id": "e_jane", "edge_type": "EMPLOYED_BY"},
        ],
    }
    counts = build_graph(records, graph_dir=gdir, ontology=onto)
    assert counts["entities"] == 2
    assert counts["edges"] == 1               # the violating edge dropped

    g = Graph(graph_dir=gdir, ontology=onto, read_only=True)
    try:
        assert g.entity_count() == 2
        assert g.edge_count() == 1
        paths = g.find_path("Jane", "Acme")
        assert paths and paths[0]["edge_types"] == ["EMPLOYED_BY"]
    finally:
        g.close()


# ── Chunk store: write + retrieval (vector legs skip if vss unavailable) ──────

def test_chunk_store_write_and_fts(tmp_path):
    from investigation_graph.chunk_store import ChunkStore, chunk_id_from_uri

    s = ChunkStore(db_path=tmp_path / "chunks.duckdb", embedding_dim=4)
    s.init_schema()
    rows = [
        {"id": chunk_id_from_uri("d1", 0), "doc_id": "d1", "source_uri": "d1",
         "title": "Harbor", "body": "Acme Corp paid contractors for harbor work",
         "chunk_index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
        {"id": chunk_id_from_uri("d2", 0), "doc_id": "d2", "source_uri": "d2",
         "title": "Board", "body": "The board discussed funding and contracts",
         "chunk_index": 0, "embedding": [0.9, 0.1, 0.0, 0.2]},
    ]
    assert s.write_chunks(rows) == 2
    assert s.chunk_count() == 2
    hits = s.search_fts("contractors")
    assert hits and hits[0]["id"] == rows[0]["id"]
    s.close()


def test_chunk_store_vector_search(tmp_path):
    from investigation_graph.chunk_store import ChunkStore, chunk_id_from_uri

    s = ChunkStore(db_path=tmp_path / "chunks.duckdb", embedding_dim=4)
    s.init_schema()
    s.write_chunks([
        {"id": chunk_id_from_uri("d1", 0), "doc_id": "d1", "source_uri": "d1",
         "title": "A", "body": "alpha", "chunk_index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
        {"id": chunk_id_from_uri("d2", 0), "doc_id": "d2", "source_uri": "d2",
         "title": "B", "body": "beta", "chunk_index": 0, "embedding": [0.9, 0.1, 0.0, 0.2]},
    ])
    try:
        hits = s.search_vector([0.1, 0.2, 0.3, 0.4])
    except Exception as exc:  # vss extension not installable (offline CI)
        pytest.skip(f"vss extension unavailable: {exc}")
    finally:
        s.close()
    assert hits and hits[0]["id"] == chunk_id_from_uri("d1", 0)
