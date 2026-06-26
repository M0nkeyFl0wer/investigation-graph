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

# The edge floor, DERIVED from the corpus (not a magic number). A correct pipeline
# keeps every legitimate edge and drops only the planted poison:
#   (N_GROUPS-1) ownership-chain edges + N_PEOPLE director edges + 1 FUNDED_BY edge
#   (the two name-variant donor FUNDED_BY edges re-aggregate to one on merge).
# The poison OWNS edge MUST be dropped (floor #6), so 39 is the absolute ceiling
# and 38 the correct count. Demanding >= this many proves no real edge was lost.
EXPECTED_MIN_EDGES = (N_GROUPS - 1) + N_PEOPLE + 1   # = 38


# Legal-suffix forms a real registry corpus mixes — NOT just "LLC". A correct
# structured-dedup must merge a bare name with ANY of these, generally (the first
# build overfit to a short suffix list and fragmented "Corporation"/"Company"/"GmbH").
SUFFIXES = ["LLC", "Inc", "Corporation", "Company", "GmbH", "Ltd"]


def _suffix(i: int) -> str:
    return SUFFIXES[i % len(SUFFIXES)]


def gen_gold():
    """Build (chunks, entities, edges, gold) — deterministic, no randomness."""
    entities, edges, chunks = [], [], []
    # canonical id per group = the bare-name variant's id; both variants share a group
    dup_groups: list[set[str]] = []

    # Authoritative-structured records carry a STABLE marker (extraction_source),
    # the way the real structured-ingest path tags them — NOT a magic provenance
    # string. provenance/source_url are the human-facing source and VARY per record.
    # (The first build keyed its grounding-rescue on the literal provenance
    # "structured_import"; relabel the same data and its edges silently dropped.
    # Keying on the stable marker is the general fix this now forces.)
    def ent(eid, label, etype):
        entities.append({"id": eid, "label": label, "entity_type": etype,
                         "source_url": SRC, "provenance": f"{SRC}#{eid}",
                         "extraction_source": "structured"})

    def chunk(cid, text):
        chunks.append({"id": cid, "text": text})

    def edge(sid, tid, etype, **extra):
        edges.append({"source_id": sid, "target_id": tid, "edge_type": etype,
                      "source_url": SRC, "provenance": f"{SRC}#{sid}-{tid}",
                      "extraction_source": "structured", **extra})

    # company groups: bare + a VARIED legal-suffix variant (same real entity)
    canon_ids = []
    for i in range(N_GROUPS):
        bare_id, var_id = f"co{i}", f"co{i}_v"
        ent(bare_id, f"Acme {i}", "organization")
        ent(var_id, f"Acme {i} {_suffix(i)}", "organization")
        dup_groups.append({bare_id, var_id})
        canon_ids.append(bare_id)

    # ownership CHAIN across the companies — a correct ER+re-point => one big
    # connected component. Reference the SUFFIX VARIANT on the target side so the
    # edge only connects the chain if ER actually merges the variant.
    for i in range(N_GROUPS - 1):
        s, t = f"co{i}", f"co{i+1}_v"
        edge(s, t, "OWNS")
        chunk(f"c_own_{i}", f"Acme {i} owns Acme {i+1} {_suffix(i+1)}, per the filing.")

    # 8 distinct people with SIMILAR names — must NOT over-merge (precision).
    for i in range(N_PEOPLE):
        pid = f"p{i}"
        ent(pid, f"Jordan Lee {i}", "person")
        edge(pid, f"co{i}", "DIRECTOR_OF")
        chunk(f"c_dir_{i}", f"Jordan Lee {i} is a director of Acme {i}.")

    # name-variant donor pair (a NON-"LLC" suffix) each funding Acme 0 with a
    # distinct amount. After ER merges the variants, the two FUNDED_BY edges
    # collide on the canonical donor and must re-aggregate to 6650 (no money lost).
    ent("donorA", "Northwind Trust", "organization")
    ent("donorA_v", "Northwind Trust GmbH", "organization")
    dup_groups.append({"donorA", "donorA_v"})
    edge("co0", "donorA", "FUNDED_BY", amount_total=2700, currency="USD")
    edge("co0", "donorA_v", "FUNDED_BY", amount_total=3950, currency="USD")
    chunk("c_fundA", "Acme 0 was funded by Northwind Trust.")
    chunk("c_fundB", "Acme 0 was funded by Northwind Trust GmbH.")

    # planted POISON: an edge to a ghost entity that is in NO chunk -> grounding
    # must quarantine the ghost and drop the edge (even though it carries the same
    # authoritative-structured marker — origin alone must not rescue an unsupported row).
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

    # 1. edge floor — every legit structured edge must survive (no mass-drop)
    if len(out_edges) < EXPECTED_MIN_EDGES:
        fails.append(f"edges={len(out_edges)} < {EXPECTED_MIN_EDGES} (structured edges dropped)")

    # 2. connectedness floor. This fixture is CONSTRUCTED so that, with correct
    #    ER, every legit entity (the ownership chain + the people + the donor)
    #    sits in ONE component — a correct build scores ~1.0. The floor is an
    #    ADEQUACY bar, not "better than the toy": below ~0.90 means real ownership
    #    links are still broken (ER under-merged), i.e. "looks connected, isn't".
    #    (This metric is the ER-fragmentation canary on data designed to connect;
    #    it does NOT claim a universal "graph is 90% complete" on arbitrary data —
    #    the real ER-adequacy floors are #3 dup-recall and #4 people-precision.)
    G = nx.Graph()
    G.add_nodes_from(surviving)
    for e in out_edges:
        G.add_edge(e["source_id"], e["target_id"])
    largest = max((len(c) for c in nx.connected_components(G)), default=0)
    frac = largest / max(len(surviving), 1)
    if frac < 0.90:
        fails.append(f"largest_component/entities={frac:.2f} < 0.90 (graph fragmented — ER under-merged; "
                     "a correct build connects ~all of this designed-connected corpus)")

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
    funds = [e for e in out_edges if e.get("edge_type") == "FUNDED_BY"]
    total = sum(e.get("amount_total", 0) for e in funds)
    if total != gold["money_total"]:
        fails.append(f"FUNDS total={total} != {gold['money_total']} (money lost on merge)")

    # 8. round-trip: it actually builds a persistent graph
    with tempfile.TemporaryDirectory() as td:
        counts = build_graph({"documents": [{"id": "src"}], **build_records},
                             graph_dir=Path(td) / "g.lbug")
        if counts.get("edges", 0) < EXPECTED_MIN_EDGES:
            fails.append(f"built graph edges={counts.get('edges')} < {EXPECTED_MIN_EDGES} (did not persist)")

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
