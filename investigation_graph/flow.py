"""
Money-flow tracing (P2.8 / interop brief G5).

Topology gives betweenness/communities; this follows the *money* — amount-weighted
flow over `FUNDED_BY` / `PAID_TO` edges, the funds-in → shell-chain → funds-out
pattern the ontology was built for. Depends on the typed `amount`/`currency` edge
columns (the regression we fixed) surviving the graph write.

Currency discipline (review): amounts in different currencies are NOT summed —
flow across currencies is meaningless without FX normalization, so a chain that
mixes currencies is flagged ``currency="MIXED"`` with ``total=None`` rather than
silently added. A single-currency chain reports its bottleneck (the min amount
along the path = the most that could have fully traversed it).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

# Edge types that move money. FUNDED_BY (org → org/person) is a transfer; PAID_TO
# (transaction → person/org) is a payment recipient. Both carry an `amount`.
MONEY_EDGE_TYPES = ("FUNDED_BY", "PAID_TO")
DEFAULT_MAX_DEPTH = 8


@dataclass
class FundChain:
    """One money trail from a source to a downstream node."""
    path: list[str]                       # entity ids: source -> ... -> sink
    hops: int
    amounts: list[float]                  # per-hop amount
    currency: str                         # single ISO code, or "MIXED"
    total_in: float = 0.0                 # amount entering the chain (first hop)
    bottleneck: float | None = None       # min amount along it (None if MIXED)
    currencies: list[str] = field(default_factory=list)

    def as_record(self) -> dict:
        return {"path": self.path, "hops": self.hops, "amounts": self.amounts,
                "currency": self.currency, "total_in": self.total_in,
                "bottleneck": self.bottleneck}


def _money_graph(edges: list[dict]) -> nx.DiGraph:
    """Directed graph of money edges, carrying amount + currency per edge."""
    G = nx.DiGraph()
    for ed in edges:
        if ed.get("edge_type") not in MONEY_EDGE_TYPES:
            continue
        amt = ed.get("amount")
        if amt in (None, "", 0, 0.0):
            continue  # no amount = not a traceable transfer
        s, t = ed["source_id"], ed["target_id"]
        # Parallel transfers between the same pair aggregate only if same currency.
        cur = (ed.get("currency") or "").strip()
        if G.has_edge(s, t) and G[s][t]["currency"] == cur:
            G[s][t]["amount"] += float(amt)
        else:
            G.add_edge(s, t, amount=float(amt), currency=cur)
    return G


def trace_funds(edges: list[dict], source_id: str, *,
                max_depth: int = DEFAULT_MAX_DEPTH) -> list[FundChain]:
    """Follow the money downstream from ``source_id``.

    Returns every money trail (simple path) from the source to a reachable node,
    each with its per-hop amounts and currency, ordered by amount entering the chain
    (largest first). A chain mixing currencies is flagged ``MIXED`` and not summed.
    """
    G = _money_graph(edges)
    if source_id not in G:
        return []
    chains: list[FundChain] = []
    for target in nx.descendants(G, source_id):
        for path in nx.all_simple_paths(G, source_id, target, cutoff=max_depth):
            amounts = [G[u][v]["amount"] for u, v in zip(path, path[1:])]
            currencies = [G[u][v]["currency"] for u, v in zip(path, path[1:])]
            single = len(set(currencies)) == 1
            chains.append(FundChain(
                path=path, hops=len(path) - 1, amounts=amounts,
                currency=currencies[0] if single else "MIXED",
                total_in=amounts[0],
                bottleneck=min(amounts) if single else None,
                currencies=currencies,
            ))
    chains.sort(key=lambda c: c.total_in, reverse=True)
    return chains


def trace_funds_from_graph(graph_dir, source_id: str, *,
                           max_depth: int = DEFAULT_MAX_DEPTH) -> list[FundChain]:
    """Trace funds from ``source_id`` reading money edges off the LIVE graph
    (depends on the typed amount/currency columns surviving the write)."""
    from investigation_graph.queries import QUERIES
    try:
        import ladybug as lb
    except ImportError:
        import real_ladybug as lb
    conn = lb.Connection(lb.Database(str(graph_dir), read_only=True))
    res = conn.execute(QUERIES["money_edges"])
    edges = []
    while res.has_next():
        src, tgt, etype, amount, currency = res.get_next()
        edges.append({"source_id": src, "target_id": tgt, "edge_type": etype,
                      "amount": amount, "currency": currency})
    return trace_funds(edges, source_id, max_depth=max_depth)


def max_flow_between(edges: list[dict], source_id: str, target_id: str) -> dict:
    """Amount-weighted maximum flow from source to target (SINGLE currency only).

    Uses amount as edge capacity. Raises ValueError if the relevant edges mix
    currencies — max-flow across currencies is meaningless without FX normalization.
    Returns ``{"max_flow": value, "currency": code}``.
    """
    G = _money_graph(edges)
    if source_id not in G or target_id not in G:
        return {"max_flow": 0.0, "currency": ""}
    currencies = {d["currency"] for _, _, d in G.edges(data=True)}
    if len(currencies) > 1:
        raise ValueError("max_flow_between requires a single currency; got "
                         f"{sorted(currencies)} — normalize FX first")
    cap = nx.DiGraph()
    for u, v, d in G.edges(data=True):
        cap.add_edge(u, v, capacity=d["amount"])
    value, _ = nx.maximum_flow(cap, source_id, target_id)
    return {"max_flow": value, "currency": currencies.pop() if currencies else ""}
