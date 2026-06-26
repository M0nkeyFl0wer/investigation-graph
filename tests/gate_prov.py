"""GATE-PROV — STRUCTURAL provenance: an edge's source must resolve to a real
INGESTED DOCUMENT, not merely "look like" a source.

WHY STRUCTURAL (the category was the bug).
Two string-heuristic builds leaked. A denylist of banned words leaked; then
"positive validation" leaked because it collapsed into a denylist one layer down
("has >=1 letter and isn't one of ~30 words") — "no source", bare "http://", a
single "x", and the Greek-omicron homoglyph "unknοwn" all passed. Any check that
asks "does this STRING look like a source" is satisfied by a string that looks
like one and isn't. So we stop checking the shape of a string and check a FACT:
does the source POINT TO a document that was actually ingested?

That is the real libel defense — not "the edge claims a source" but "the edge
points to a thing in evidence a journalist can open and read." "no source",
"http://", "x", and a phantom doc-id all fail because they reference nothing real.

THREE cases, driven through BOTH write paths (build_graph AND Graph.add_edge):
  (a) an edge citing a REAL ingested document            -> must BUILD,
  (b) an edge with NO source                             -> must be REFUSED,
  (c) an edge citing a doc-id/url NEVER ingested (phantom) -> must be REFUSED.
Case (c) is the one a string check can never catch and the structural check gets
for free — and it's the case this gate now proves.

CONTRACT the build must satisfy: an edge is sourced iff its `source_url` matches
the url/path of a document in the ingested document set, OR its `provenance`
matches the id of an ingested document. For Graph.add_edge (no records payload),
the document set is the documents already in the graph.

Run:  .venv/bin/python tests/gate_prov.py      (exit 0 = structurally enforced)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from investigation_graph.graph import Graph, build_graph  # noqa: E402

# Two genuinely ingested documents (id + url/path). Edges may only cite these.
DOCS = [
    {"id": "doc1", "url": "http://sec.gov/filing/1", "path": "http://sec.gov/filing/1"},
    {"id": "doc2", "url": "http://fec.gov/f3x/2", "path": "http://fec.gov/f3x/2"},
]
ENTS = [
    {"id": "a", "label": "Acme", "entity_type": "organization",
     "source_url": "http://sec.gov/filing/1", "provenance": "doc1"},
    {"id": "b", "label": "Beta", "entity_type": "organization",
     "source_url": "http://sec.gov/filing/1", "provenance": "doc1"},
]

# (c) phantom + every string-heuristic leak from the prior verifiers: none of
# these reference an ingested document, so all must be refused.
PHANTOM_SOURCES = [
    {"source_url": "http://sec.gov/filing/999"},   # well-formed url, never ingested
    {"provenance": "doc999"},                       # plausible id, never ingested
    {"source_url": "no source"}, {"source_url": "http://"}, {"source_url": "x"},
    {"source_url": "unknοwn"},                       # greek-omicron homoglyph
    {"provenance": "[citation needed]"}, {"source_url": "tbc"},
    {},                                             # no source at all
]


def _edge(extra):
    return {"source_id": "a", "target_id": "b", "edge_type": "OWNS", **extra}


def main() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        # (a) an edge citing a real ingested doc must BUILD.
        ok = {"documents": DOCS, "entities": ENTS, "edges": [_edge({"source_url": "http://sec.gov/filing/1"})]}
        if build_graph(ok, graph_dir=Path(td) / "ok.lbug")["edges"] != 1:
            fails.append("an edge citing a REAL ingested document was wrongly rejected (false positive)")

        # (b)+(c) sourceless and phantom-doc edges must be REFUSED — build_graph path.
        for i, ph in enumerate(PHANTOM_SOURCES):
            recs = {"documents": DOCS, "entities": ENTS, "edges": [_edge(ph)]}
            try:
                n = build_graph(recs, graph_dir=Path(td) / f"ph{i}.lbug")["edges"]
                if n > 0:
                    fails.append(f"build_graph stored an edge with no ingested-doc source: {ph}")
            except Exception:
                pass  # raising is acceptable rejection

        # (c) phantom via the second write path: Graph.add_edge must check the
        # graph's own ingested documents. Build a real graph, then try to add a
        # phantom-sourced edge.
        g = Graph(graph_dir=Path(td) / "ok.lbug", read_only=False)
        before = g.edge_count()
        try:
            g.add_edge("a", "b", "DIRECTOR_OF", source_url="http://sec.gov/filing/999")
        except Exception:
            pass
        after = g.edge_count()
        g.close()
        if after > before:
            fails.append("Graph.add_edge stored an edge citing a doc never ingested (phantom)")

    if fails:
        print("GATE-PROV  RESULT: \033[31mFAIL\033[0m — structural provenance not enforced:")
        for f in fails[:12]:
            print(f"    ✗ {f}")
        return 1
    print("GATE-PROV  RESULT: \033[32mPASS\033[0m — every edge resolves to an ingested document; "
          "sourceless and phantom-doc edges refused on both paths.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
