"""GATE-PROV — an edge with NO provenance must be REJECTED, never silently stored.

Plain English: a journalist's whole defense is "every connection traces to a
source." This gate proves the tool *enforces* that at the write — you cannot put
an edge in the graph without a source. It builds the same edge twice, once with a
source and once without, and demands the source-less one be refused (raised) or
dropped. If both get written, provenance is a promise, not a guarantee.

Run:  .venv/bin/python tests/gate_prov.py    (exit 0 = enforced)
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from investigation_graph.graph import build_graph  # noqa: E402

_ENTS = [
    {"id": "a", "label": "Acme", "entity_type": "organization",
     "source_url": "http://reg.example/x", "provenance": "registry"},
    {"id": "b", "label": "Beta", "entity_type": "organization",
     "source_url": "http://reg.example/x", "provenance": "registry"},
]


def main() -> int:
    with tempfile.TemporaryDirectory() as td:
        no_prov = {"documents": [{"id": "d"}], "entities": _ENTS,
                   "edges": [{"source_id": "a", "target_id": "b", "edge_type": "OWNS"}]}
        with_prov = {"documents": [{"id": "d"}], "entities": _ENTS,
                     "edges": [{"source_id": "a", "target_id": "b", "edge_type": "OWNS",
                                "provenance": "registry", "source_url": "http://reg.example/x"}]}
        try:
            n_bad = build_graph(no_prov, graph_dir=Path(td) / "bad.lbug")["edges"]
        except Exception:
            print("GATE-PROV  RESULT: \033[32mPASS\033[0m — source-less edge rejected at write (raised).")
            return 0
        n_good = build_graph(with_prov, graph_dir=Path(td) / "good.lbug")["edges"]
        if n_bad >= n_good and n_good > 0:
            print("GATE-PROV  RESULT: \033[31mFAIL\033[0m — the source-less edge was written anyway "
                  f"(no-provenance build kept {n_bad} edge(s); with-provenance kept {n_good}). "
                  "No enforcement: an edge with no source is silently stored (as 'unknown').")
            return 1
        print("GATE-PROV  RESULT: \033[32mPASS\033[0m — source-less edge dropped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
