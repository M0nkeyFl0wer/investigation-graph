"""GATE-PROV — an edge with NO real source must be REJECTED, never silently stored.

Plain English: a journalist's whole defense is "every connection traces to a
source." This gate proves the tool *enforces* that — you cannot put an edge in the
graph without a real, traceable source.

STRENGTHENED 2026-06-26 after an independent verifier broke the first version. It
was a denylist of 6 literal words guarding only ONE of two write paths. This
version demands the real guarantee:
  (a) a large matrix of "no real source" values — alternate placeholders, a typo,
      a zero-width space, non-string junk — ALL must be refused;
  (b) BOTH write paths are covered (build_graph AND Graph.add_edge), so a guard in
      one caller's loop isn't enough — it must live at the writer boundary;
  (c) a genuinely real source still passes (no false positives).
The cheap fake this blocks: a denylist of the exact strings the builder thought of.
Passing this requires positive validation (a real source looks like X), at the
write boundary, applied to every path — not a blocklist in one function.

Run:  .venv/bin/python tests/gate_prov.py     (exit 0 = enforced everywhere)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from investigation_graph.graph import Graph, build_graph  # noqa: E402

_ENTS = [
    {"id": "a", "label": "Acme", "entity_type": "organization",
     "source_url": "http://reg.example/x", "provenance": "registry"},
    {"id": "b", "label": "Beta", "entity_type": "organization",
     "source_url": "http://reg.example/x", "provenance": "registry"},
]

# Values that DO NOT constitute a real, traceable source. Every one must be refused
# (as either provenance or source_url) — these are the fresh inputs the verifier
# used to break the denylist.
NOT_A_SOURCE = [
    "", "unknown", "none", "null", "n/a", "na",            # the originals
    "N/A.", "tbd", "TODO", "see source", "-", "—",     # alt placeholders / em-dash
    "...", "n.a.", "unkown", "0", "false", "pending",
    "​", "unknown​", "  unknown  ", "\t", " ",    # zero-width / whitespace tricks
    1, True, 3.14, ["x"], {"k": "v"}, None,                 # non-string junk
]


def _edge(prov, src):
    e = {"source_id": "a", "target_id": "b", "edge_type": "OWNS"}
    if prov is not None:
        e["provenance"] = prov
    if src is not None:
        e["source_url"] = src
    return e


def main() -> int:
    fails: list[str] = []
    with tempfile.TemporaryDirectory() as td:
        # (a)+(b) every non-source value must be refused on BOTH paths.
        for i, bad in enumerate(NOT_A_SOURCE):
            recs = {"documents": [{"id": "d"}], "entities": _ENTS,
                    "edges": [_edge(bad, bad)]}
            try:
                n = build_graph(recs, graph_dir=Path(td) / f"bg{i}.lbug")["edges"]
                if n > 0:
                    fails.append(f"build_graph stored a source-less edge (value={bad!r})")
            except Exception:
                pass  # raising is an acceptable form of rejection

            # second write path: Graph.add_edge must enforce the same boundary
            try:
                g = Graph(graph_dir=Path(td) / f"ge{i}.lbug", read_only=False)
                try:
                    g.add_edge("a", "b", "OWNS", provenance=bad, source_url=bad)
                except TypeError:
                    g.add_edge("a", "b", "OWNS")  # no source at all
                except Exception:
                    g.close()
                    continue
                leaked = g.edge_count()
                g.close()
                if leaked > 0:
                    fails.append(f"Graph.add_edge stored a source-less edge (value={bad!r})")
            except Exception:
                pass  # construction/other errors are not a leak

        # (c) a genuinely real source must still build (no false positives).
        ok = {"documents": [{"id": "d"}], "entities": _ENTS,
              "edges": [_edge("registry", "http://reg.example/x")]}
        if build_graph(ok, graph_dir=Path(td) / "ok.lbug")["edges"] != 1:
            fails.append("a real-sourced edge was wrongly rejected (false positive)")

    if fails:
        print("GATE-PROV  RESULT: \033[31mFAIL\033[0m — source-less edges leaked / over-rejection:")
        for f in fails[:12]:
            print(f"    ✗ {f}")
        if len(fails) > 12:
            print(f"    … +{len(fails) - 12} more")
        return 1
    print("GATE-PROV  RESULT: \033[32mPASS\033[0m — no source-less edge enters via any path.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
