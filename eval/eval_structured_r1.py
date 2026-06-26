"""GATE-R1 — structured-first ingest must produce a CONNECTED, edge-rich,
resolved, provenance-complete graph from structured data, with no LLM.

This is the Definition of Done for R1, written as a gate a *toy* fails. It runs
the REAL pipeline (ground_and_resolve → build_graph) on an adversarial structured
corpus and asserts non-trivial floors. A keep-first ER, an exact-match-only
resolver, a load that drops provenance, or anything that leaves the graph
fragmented FAILS here — which is the point: the agent that makes this pass has to
build the real thing.

Run:  .venv/bin/python -m eval.eval_structured_r1   (exit 0 = all floors met)

The corpus is deliberately adversarial:
  * 30 company groups, each with a bare name + a legal-suffix variant
    ("Acme 7" / "Acme 7 LLC") — exact+fuzzy alone MISSES the suffix variants, so
    the ER-recall floor forces a structured-dedup tier, not the toy resolver.
  * an ownership CHAIN across the canonical companies — only a correct ER +
    re-point yields a connected component (under-merging fragments it, so the
    connectedness floor catches ER failure a second way).
  * 8 distinct people with similar names that must NOT over-merge (precision).
  * a name-variant donor pair carrying distinct FUNDS amounts (2700 + 3950) that
    must re-aggregate to 6650 on merge (no silent money loss).
  * a planted poison entity referenced by an edge but present in NO chunk — must
    be quarantined and its edge dropped (grounding actually firing).
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from investigation_graph.pipeline import ground_and_resolve  # noqa: E402
from investigation_graph.graph import build_graph  # noqa: E402

N_GROUPS = 30            # company duplicate groups
N_PEOPLE = 8             # distinct people that must NOT over-merge
SRC = "https://registry.example.gov/filing"   # a provenance source on every record


def gen_gold():
    """Build (chunks, entities, edges, gold) — deterministic, no randomness."""
    entities, edges, chunks = [], [], []
    # canonical id per group = the bare-name variant's id; both variants share a group
    dup_groups: list[set[str]] = []

    def ent(eid, label, etype):
        entities.append({"id": eid, "label": label, "entity_type": etype,
                         "source_url": SRC, "provenance": "structured_import"})

    def chunk(cid, text):
        chunks.append({"id": cid, "text": text})

    def edge(sid, tid, etype, **extra):
        edges.append({"source_id": sid, "target_id": tid, "edge_type": etype,
                      "source_url": SRC, "provenance": "structured_import", **extra})

    # 30 company groups: bare + legal-suffix variant (same real entity)
    canon_ids = []
    for i in range(N_GROUPS):
        bare_id, llc_id = f"co{i}", f"co{i}_llc"
        ent(bare_id, f"Acme {i}", "organization")
        ent(llc_id, f"Acme {i} LLC", "organization")
        dup_groups.append({bare_id, llc_id})
        canon_ids.append(bare_id)

    # ownership CHAIN across the companies — a correct ER+re-point => one big
    # connected component. Reference DIFFERENT variants on each side so the edge
    # only connects the chain if ER actually merges the variants.
    for i in range(N_GROUPS - 1):
        # co{i} (bare) OWNS co{i+1}_llc (suffix variant). Only connected if the
        # suffix variant resolves to co{i+1}.
        s, t = f"co{i}", f"co{i+1}_llc"
        edge(s, t, "OWNS")
        chunk(f"c_own_{i}", f"Acme {i} owns Acme {i+1} LLC, per the filing.")

    # 8 distinct people with SIMILAR names — must NOT over-merge (precision).
    for i in range(N_PEOPLE):
        pid = f"p{i}"
        ent(pid, f"Jordan Lee {i}", "person")
        edge(pid, f"co{i}", "DIRECTOR_OF")
        chunk(f"c_dir_{i}", f"Jordan Lee {i} is a director of Acme {i}.")

    # name-variant donor pair with distinct FUNDS amounts -> must merge to 6650.
    ent("donorA", "Northwind Trust", "organization")
    ent("donorA_llc", "Northwind Trust LLC", "organization")
    dup_groups.append({"donorA", "donorA_llc"})
    edge("donorA", "co0", "FUNDS", amount_total=2700, currency="USD")
    edge("donorA_llc", "co0", "FUNDS", amount_total=3950, currency="USD")
    chunk("c_fundA", "Northwind Trust funded Acme 0.")
    chunk("c_fundB", "Northwind Trust LLC funded Acme 0.")

    # planted POISON: an edge to a ghost entity that is in NO chunk -> grounding
    # must quarantine the ghost and drop the edge.
    ent("ghost", "Zzz Phantom Holdings", "organization")
    edge("co1", "ghost", "OWNS")   # no chunk mentions "Zzz Phantom Holdings"

    gold = {
        "dup_groups": dup_groups,
        "expected_unique_orgs": N_GROUPS + 1,     # 30 companies + 1 donor (ghost quarantined)
        "expected_people": N_PEOPLE,
        "money_total": 6650,
        "poison_id": "ghost",
        "canon_ids": canon_ids,
    }
    return chunks, entities, edges, gold


def main() -> int:
    chunks, entities, edges, gold = gen_gold()
    build_records, report = ground_and_resolve(chunks, entities, edges)
    out_ents = build_records["entities"]
    out_edges = build_records["edges"]
    surviving = {e["id"] for e in out_ents}

    fails: list[str] = []

    # 1. edge floor
    if len(out_edges) < 45:
        fails.append(f"edges={len(out_edges)} < 45 (edges dropped / not built)")

    # 2. connectedness floor (counters the '512 isolated nodes' toy)
    G = nx.Graph()
    G.add_nodes_from(surviving)
    for e in out_edges:
        G.add_edge(e["source_id"], e["target_id"])
    largest = max((len(c) for c in nx.connected_components(G)), default=0)
    frac = largest / max(len(surviving), 1)
    if frac < 0.6:
        fails.append(f"largest_component/entities={frac:.2f} < 0.60 (graph fragmented — ER under-merged)")

    # 3. ER recall on suffix-variant duplicate groups (forces a structured tier)
    merged = sum(1 for grp in gold["dup_groups"] if len(grp & surviving) <= 1)
    recall = merged / len(gold["dup_groups"])
    if recall < 0.8:
        fails.append(f"ER dup-merge recall={recall:.2f} < 0.80 (exact+fuzzy miss legal-suffix variants)")

    # 4. ER precision — distinct people must NOT over-merge
    people = sum(1 for e in out_ents if e.get("entity_type") == "person")
    if people < gold["expected_people"]:
        fails.append(f"people={people} < {gold['expected_people']} (distinct people wrongly merged)")

    # 5. provenance on 100% of edges
    no_prov = [e for e in out_edges if not (e.get("provenance") or e.get("source_url"))]
    if no_prov:
        fails.append(f"{len(no_prov)} edges have no provenance/source")

    # 6. poison quarantined
    if gold["poison_id"] in surviving:
        fails.append("poison entity survived (grounding did not quarantine it)")
    if any(gold["poison_id"] in (e["source_id"], e["target_id"]) for e in out_edges):
        fails.append("poison edge survived")

    # 7. money preserved through the name-variant donor merge
    funds = [e for e in out_edges if e.get("edge_type") == "FUNDS"]
    total = sum(e.get("amount_total", 0) for e in funds)
    if total != gold["money_total"]:
        fails.append(f"FUNDS total={total} != {gold['money_total']} (money lost on merge)")

    # 8. round-trip: it actually builds a persistent graph
    with tempfile.TemporaryDirectory() as td:
        counts = build_graph({"documents": [{"id": "src"}], **build_records},
                             graph_dir=Path(td) / "g.lbug")
        if counts.get("edges", 0) < 45:
            fails.append(f"built graph edges={counts.get('edges')} < 45 (did not persist)")

    print("\nGATE-R1 — structured-first acceptance")
    print(f"  entities_out={len(surviving)} edges_out={len(out_edges)} "
          f"largest_cc={frac:.2f} dup_recall={recall:.2f} people={people} funds_total={total}")
    if fails:
        print("  RESULT: \033[31mFAIL\033[0m — floors not met:")
        for f in fails:
            print(f"    ✗ {f}")
        print("  (expected to fail until R1 is built — this gate IS the target.)")
        return 1
    print("  RESULT: \033[32mPASS\033[0m — connected, resolved, provenance-complete, no money lost.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
