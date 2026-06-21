#!/usr/bin/env python3
"""
Build the companion knowledge graph from the curated, human-verified findings dataset
(report-private/findings/{entities,edges}.jsonl) via the corruption-safe
reconstruct-and-swap (`investigation_graph.graph.build_graph`).

This is the flagship-example KG: instead of re-running noisy LLM extraction over raw
HTML, we load the audited, ontology-typed, provenance+confidence-tagged seed (which
already passes all eval-gates). Every evidence artifact_id becomes a `document` node and
every entity links to its provenance via `mentions`, so the graph itself carries the
chain of custody the viz renders.

Usage:
  PYTHONPATH=. python scripts/build_graph_from_findings.py
"""
from __future__ import annotations

import json
from pathlib import Path

from investigation_graph.graph import build_graph

FINDINGS = Path("examples/fedfiling-case/report-private/findings")


def _load(name):
    return [json.loads(ln) for ln in (FINDINGS / name).read_text().splitlines() if ln.strip()]


def main() -> int:
    ents = _load("entities.jsonl")
    edges = _load("edges.jsonl")

    # entity → graph node (id/entity_type/label; confidence kept as a node property)
    g_entities = [{"id": e["id"], "entity_type": e["type"], "label": e["label"]} for e in ents]

    # evidence artifacts → document nodes (provenance layer)
    doc_ids = set()
    for e in ents:
        doc_ids.update(e.get("provenance", []))
    for ed in edges:
        if ed.get("evidence_artifact"):
            doc_ids.add(ed["evidence_artifact"])
    g_documents = [{"id": d} for d in sorted(doc_ids)]

    # entity → its provenance artifacts (MENTIONED_IN), the chain-of-custody links
    g_mentions = [{"entity_id": e["id"], "doc_id": d, "mention_count": 1}
                  for e in ents for d in e.get("provenance", [])]

    # edge → graph edge; carry evidence quote + confidence as edge properties
    g_edges = [{"source_id": ed["from"], "target_id": ed["to"], "edge_type": ed["type"],
                "evidence": ed.get("evidence_fact", "")[:480], "confidence": float(ed.get("conf", 0.5))}
               for ed in edges]

    counts = build_graph({"documents": g_documents, "entities": g_entities,
                          "edges": g_edges, "mentions": g_mentions})
    print("companion KG built (reconstruct-and-swap):", counts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
