"""
Deterministic edge inference / logical closure (P2.7 / interop brief G4).

Topology *detects* missing edges; this *derives* implied ones — specifically
beneficial-ownership control through chains of `OWNS` edges. It is the dangerous
gap, so it is built defensively (per review):

- **Multiplicative percentages with a threshold, not edge-existence.** *A owns 5%
  of B, B owns 5% of C* does NOT make A control C. Effective ownership is the
  product of share fractions along a path, summed across paths; a control edge is
  inferred only when that effective stake meets a **configurable threshold**
  (default 0.25 — the ~25% beneficial-ownership line in UK PSC / EU AMLD regimes).
- **Type-compatible chaining only.** We chain `OWNS ∘ OWNS`, never `OWNS ∘
  EMPLOYED_BY` — composing incompatible relations would fabricate meaning.
- **Depth-capped.** Long chains decay to noise; `max_depth` bounds them.
- **Inferred ≠ extracted.** Every derived edge is tagged `provenance="inferred"`
  with the source chain as `evidence`, and `needs_review=True` — it is routed to a
  review queue for human confirmation (the P1.3 gate), NOT asserted as fact. A
  `provenance` tag alone keeps it out of extracted-only views but does not stop a
  false control claim reaching a draft; the review gate does.

PSL / probabilistic inference is explicitly out of scope (heavy, against the
deterministic grain).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

# Default beneficial-ownership control threshold (configurable). 0.25 ≈ the 25%
# line used by the UK Persons-with-Significant-Control regime and EU AMLD.
DEFAULT_THRESHOLD = 0.25
DEFAULT_MAX_DEPTH = 6


@dataclass
class InferredEdge:
    source_id: str
    target_id: str
    edge_type: str = "OWNS"          # beneficial ownership is still OWNS
    effective_pct: float = 0.0       # summed multiplicative stake, 0..1
    hops: int = 0
    chain: list[str] = field(default_factory=list)  # entity-id path
    confidence: float = 0.0
    provenance: str = "inferred"
    extraction_source: str = "inferred"
    needs_review: bool = True        # routes to the P1.3 review gate, not the graph

    def as_record(self) -> dict:
        """Edge dict in the artifact-contract shape, tagged inferred + for review."""
        return {
            "source_id": self.source_id, "target_id": self.target_id,
            "edge_type": self.edge_type, "confidence": round(self.confidence, 4),
            "provenance": self.provenance, "extraction_source": self.extraction_source,
            "needs_review": self.needs_review,
            "effective_pct": round(self.effective_pct, 4), "hops": self.hops,
            "evidence": "inferred control via "
                        + " -> ".join(self.chain)
                        + f" (effective {self.effective_pct:.1%} ≥ threshold)",
        }


def _share_fraction(edge: dict) -> float | None:
    """The ownership share of an OWNS edge as a 0..1 fraction, or None if absent.

    Reads ``share_pct`` (a percent like "55") — a value WITHOUT a percentage can't
    contribute to a multiplicative stake, so it's reported as None (not assumed 1.0,
    which would silently fabricate control)."""
    raw = edge.get("share_pct")
    if raw in (None, ""):
        return None
    try:
        return float(str(raw).strip().rstrip("%")) / 100.0
    except ValueError:
        return None


def infer_control_edges(
    edges: list[dict], *,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[list[InferredEdge], list[dict]]:
    """Infer beneficial-ownership control edges from a set of OWNS edges.

    Returns ``(inferred, skipped)``. ``inferred`` holds the control edges whose
    effective stake meets ``threshold`` (excluding pairs that already have a direct
    OWNS edge). ``skipped`` records OWNS edges dropped because they carry no
    ``share_pct`` (we will not assume a percentage and manufacture control).

    Only `OWNS` edges are chained (type-compatible closure). Effective ownership of
    A in C is the sum over all simple A→C paths of the product of the per-edge share
    fractions; confidence is that effective fraction.
    """
    G = nx.DiGraph()
    direct: set[tuple[str, str]] = set()
    skipped: list[dict] = []
    for ed in edges:
        if ed.get("edge_type") != "OWNS":
            continue  # type-compatible chaining: OWNS ∘ OWNS only
        frac = _share_fraction(ed)
        if frac is None:
            skipped.append({"edge": ed, "reason": "no share_pct — cannot compute stake"})
            continue
        s, t = ed["source_id"], ed["target_id"]
        # If two rows assert the same A→B ownership, keep the max (don't double-count).
        if G.has_edge(s, t):
            G[s][t]["share"] = max(G[s][t]["share"], frac)
        else:
            G.add_edge(s, t, share=frac)
        direct.add((s, t))

    inferred: list[InferredEdge] = []
    for a in G.nodes:
        for c in nx.descendants(G, a):
            if (a, c) in direct or a == c:
                continue  # already a direct owner, or self
            effective = 0.0
            best_chain: list[str] = []
            best_hops = 0
            for path in nx.all_simple_paths(G, a, c, cutoff=max_depth):
                stake = 1.0
                for u, v in zip(path, path[1:]):
                    stake *= G[u][v]["share"]
                effective += stake
                if len(path) - 1 > best_hops or not best_chain:
                    best_chain, best_hops = path, len(path) - 1
            if effective >= threshold:
                inferred.append(InferredEdge(
                    source_id=a, target_id=c, effective_pct=min(effective, 1.0),
                    hops=best_hops, chain=best_chain, confidence=min(effective, 1.0),
                ))
    return inferred, skipped


def infer_control_from_graph(
    graph_dir: str | Path, *,
    threshold: float = DEFAULT_THRESHOLD,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> tuple[list[InferredEdge], list[dict]]:
    """Read observed `OWNS` edges (with `share_pct`) off the LIVE graph and infer
    control. This is the operational path: it depends on share_pct surviving the
    write as a typed column (the regression we fixed). Returns ``(inferred, skipped)``
    exactly like ``infer_control_edges``.
    """
    from investigation_graph.queries import QUERIES
    try:
        import ladybug as lb
    except ImportError:
        import real_ladybug as lb

    conn = lb.Connection(lb.Database(str(graph_dir), read_only=True))
    res = conn.execute(QUERIES["ownership_edges"])
    edges: list[dict] = []
    while res.has_next():
        src, tgt, share = res.get_next()
        # share_pct is a typed DOUBLE off the graph; 0.0 is the unset sentinel, so
        # we only treat a positive share as a real ownership stake.
        ed = {"source_id": src, "target_id": tgt, "edge_type": "OWNS"}
        if share and float(share) > 0:
            ed["share_pct"] = float(share)
        edges.append(ed)
    return infer_control_edges(edges, threshold=threshold, max_depth=max_depth)


def write_review_queue(inferred: list[InferredEdge], path: str | Path) -> int:
    """Write inferred control edges to a human-review queue (one JSON record per
    line), mirroring the P1.3 ``merges.jsonl`` gate. Inferred control is a libel
    vector, so it lands HERE for confirmation — it is not asserted into the graph as
    fact by the inference step. Returns the number of edges queued.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for e in inferred:
            fh.write(json.dumps(e.as_record()) + "\n")
    return len(inferred)
