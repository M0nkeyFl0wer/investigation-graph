"""Tests for deterministic tabular ingestion (P2.4 / interop brief G1).

Sample-before-scale: these assert the artifact contract + the safety guards on a
tiny fixture before the path ever runs on real data. No LLM, no network.
"""
from pathlib import Path

import pytest

from investigation_graph.ontology import Ontology
from investigation_graph.processors.tabular import (
    MappingSpec,
    SpecError,
    TabularProcessor,
    ingest_table,
)

FIX = Path(__file__).parent / "fixture_tabular"
ONT = Ontology()


def _load():
    spec = MappingSpec.from_yaml(FIX / "ownership.map.yaml", ONT)
    return ingest_table(FIX / "ownership.csv", spec, ontology=ONT)


def test_emits_typed_entities_and_edges_with_no_skips():
    out = _load()
    # 4 unique entities (Brightpath appears 3x but dedups to one node by id).
    labels = {e["label"]: e["entity_type"] for e in out["entities"]}
    assert labels == {
        "Jane Roe": "person",
        "Brightpath Advisors": "organization",
        "Harbor City RDA": "organization",
        "Acme Holdings": "organization",
    }
    assert len(out["edges"]) == 3
    assert not out["skipped"]


def test_provenance_and_extraction_source_on_every_record():
    out = _load()
    for e in out["entities"]:
        assert e["source_url"].endswith("ownership.csv")
        assert e["extraction_source"] == "deterministic"
        assert e["provenance"] == "tabular"
        assert e["confidence"] == 0.9
    for ed in out["edges"]:
        assert ed["edge_type"] == "OWNS"
        assert ed["extraction_source"] == "deterministic"
        assert ed["evidence"].startswith("row ")          # cites its source row
        assert ed["source_url"].endswith("ownership.csv")


def test_edge_properties_and_temporal_carry_through():
    out = _load()
    by_pair = {(e["source_id"], e["target_id"]): e for e in out["edges"]}
    # Every OWNS edge carries the share % and the as_of date.
    for ed in out["edges"]:
        assert "share_pct" in ed
        assert ed["valid_from"].startswith("2024-")
    assert len(by_pair) == 3  # three distinct ownership relationships


def test_emits_one_row_chunk_per_row_containing_the_labels():
    # Grounding needs a chunk that contains each entity's label; the row-chunk is it.
    out = _load()
    assert len(out["chunks"]) == 3
    joined = " ".join(c["text"] for c in out["chunks"])
    for label in ("Jane Roe", "Brightpath Advisors", "Harbor City RDA", "Acme Holdings"):
        assert label in joined
    # Each edge's endpoints co-occur in their row-chunk (so the edge grounds).
    chunk_by_row = {c["row"]: c["text"] for c in out["chunks"]}
    assert "Jane Roe" in chunk_by_row[1] and "Brightpath Advisors" in chunk_by_row[1]


def test_grade_locality_violation_in_spec_fails_loud():
    # OWNS cannot connect organization -> person; a literal-typed spec must reject
    # this AT LOAD, not silently at write.
    bad = FIX / "_bad_grade.map.yaml"
    bad.write_text(
        "entities:\n"
        "  - {column: a, type: organization}\n"
        "  - {column: b, type: person}\n"
        "edges:\n"
        "  - {source: a, type: OWNS, target: b}\n"
    )
    try:
        with pytest.raises(SpecError):
            MappingSpec.from_yaml(bad, ONT)
    finally:
        bad.unlink()


def test_unknown_edge_type_fails_loud():
    bad = FIX / "_bad_edge.map.yaml"
    bad.write_text(
        "entities:\n"
        "  - {column: a, type: person}\n"
        "  - {column: b, type: organization}\n"
        "edges:\n"
        "  - {source: a, type: NOT_A_REAL_EDGE, target: b}\n"
    )
    try:
        with pytest.raises(SpecError):
            MappingSpec.from_yaml(bad, ONT)
    finally:
        bad.unlink()


def test_amount_without_currency_is_rejected():
    # Review requirement: a money column must carry currency.
    bad = FIX / "_bad_amount.map.yaml"
    bad.write_text(
        "entities:\n"
        "  - {column: t, type: transaction}\n"
        "  - {column: p, type: organization}\n"
        "edges:\n"
        "  - {source: t, type: PAID_TO, target: p, amount: amt}\n"
    )
    try:
        with pytest.raises(SpecError):
            MappingSpec.from_yaml(bad, ONT)
    finally:
        bad.unlink()


def test_media_shaped_processor_returns_structured_records():
    proc = TabularProcessor(ontology=ONT)
    assert proc.accepts(FIX / "ownership.csv")
    result = proc.process(FIX / "ownership.csv")
    assert result.metadata["kind"] == "tabular"
    assert result.metadata["mapped"] is True
    assert len(result.structured["entities"]) == 4
    assert len(result.structured["edges"]) == 3
