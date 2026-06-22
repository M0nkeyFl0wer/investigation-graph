"""Tests for money-flow tracing (P2.8 / interop brief G5).

Pins the safety properties: amount-weighted chains, the currency discipline (never
sum across currencies), no-amount edges skipped, single-currency max-flow, and the
graph-native read (amount survives the write).
"""
from pathlib import Path

import pytest

from investigation_graph.flow import (
    max_flow_between,
    trace_funds,
    trace_funds_from_graph,
)
from investigation_graph.graph import build_graph
from investigation_graph.ontology import Ontology
from investigation_graph.processors import ingest_table
from investigation_graph.processors.tabular import MappingSpec

FIX = Path(__file__).parent / "fixture_tabular"
ONT = Ontology()


def _ledger():
    out = ingest_table(FIX / "payments.csv",
                       MappingSpec.from_yaml(FIX / "payments.map.yaml", ONT),
                       ontology=ONT)
    label = {e["id"]: e["label"] for e in out["entities"]}
    src = next(i for i, lab in label.items() if lab == "Apex Corp")
    return out, label, src


def test_traces_the_layering_chain_with_bottleneck():
    out, label, src = _ledger()
    chains = trace_funds(out["edges"], src)
    full = next(c for c in chains if len(c.path) == 4)
    assert [label[n] for n in full.path] == [
        "Apex Corp", "Shell One Ltd", "Shell Two Ltd", "Final Beneficiary"]
    assert full.currency == "USD"
    assert full.amounts == [100000.0, 90000.0, 80000.0]
    assert full.bottleneck == 80000.0  # the most that fully traversed


def test_currencies_are_never_summed():
    out, label, src = _ledger()
    chains = trace_funds(out["edges"], src)
    # The USD layering chain and the EUR direct payment are distinct paths; none
    # is flagged MIXED, and the EUR chain stays EUR.
    assert all(c.currency != "MIXED" for c in chains)
    eur = next(c for c in chains if label[c.path[-1]] == "Direct Vendor")
    assert eur.currency == "EUR" and eur.total_in == 5000.0


def test_mixed_currency_chain_is_flagged_not_summed():
    # A chain whose hops differ in currency must be MIXED with no bottleneck total.
    edges = [
        {"source_id": "a", "target_id": "b", "edge_type": "FUNDED_BY",
         "amount": 100.0, "currency": "USD"},
        {"source_id": "b", "target_id": "c", "edge_type": "FUNDED_BY",
         "amount": 90.0, "currency": "EUR"},
    ]
    chains = trace_funds(edges, "a")
    mixed = next(c for c in chains if c.path == ["a", "b", "c"])
    assert mixed.currency == "MIXED"
    assert mixed.bottleneck is None  # refuses to pick a cross-currency total


def test_edges_without_amount_are_not_traced():
    edges = [{"source_id": "a", "target_id": "b", "edge_type": "FUNDED_BY"},
             {"source_id": "a", "target_id": "c", "edge_type": "FUNDED_BY",
              "amount": 0.0, "currency": "USD"}]
    assert trace_funds(edges, "a") == []


def test_max_flow_single_currency_and_rejects_mixed():
    out, _, src = _ledger()
    # All four payments mix USD + EUR -> max_flow must refuse.
    with pytest.raises(ValueError):
        max_flow_between(out["edges"], src, src)
    # A single-currency sub-ledger computes a real max flow.
    usd = [e for e in out["edges"] if e.get("currency") == "USD"]
    label = {e["id"]: e["label"] for e in out["entities"]}
    apex = next(i for i, lab in label.items() if lab == "Apex Corp")
    fin = next(i for i, lab in label.items() if lab == "Final Beneficiary")
    res = max_flow_between(usd, apex, fin)
    assert res["currency"] == "USD" and res["max_flow"] == 80000.0


def test_graph_native_trace_reads_amount_off_the_live_graph(tmp_path):
    out, label, src = _ledger()
    graph_dir = tmp_path / "g.lbug"
    build_graph({"documents": [], "entities": out["entities"],
                 "edges": out["edges"], "mentions": []},
                graph_dir=graph_dir, ontology=ONT)
    chains = trace_funds_from_graph(graph_dir, src)
    full = next(c for c in chains if len(c.path) == 4)
    # Amounts came BACK OFF THE GRAPH (typed columns), not the in-memory edges.
    assert full.currency == "USD" and full.bottleneck == 80000.0
