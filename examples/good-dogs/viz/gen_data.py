#!/usr/bin/env python3
"""gen_data.py — build viz/data.js from the GOLD knowledge graph.

Reads the two source-of-truth JSONL files:

    examples/good-dogs/findings-gold/entities.jsonl   {id, entity_type, label}
    examples/good-dogs/findings-gold/edges.jsonl      {source_id, target_id,
                                                        edge_type, evidence,
                                                        confidence}

and emits a single self-contained `data.js` that the offline viz loads with no
network access at all (the graph is inlined as a JS object literal — there is no
runtime fetch, so the page works from `file://` as well as a static server).

Why inline instead of fetch()? The Fed Filing template fetched JSONL at runtime,
which only works when served over http(s). This public sample should also open
straight off disk, so we bake the data in at generation time.

Two pieces of derived structure are computed HERE (deterministically) rather than
in the browser, because they are corpus knowledge, not view logic:

  1. DOMAIN  — each entity is assigned to one of the corpus's six knowledge
     domains (veterinary_research, behavioral_research, nutrition_safety,
     municipal_policy, community_journalism, breed_standards). The gold entity
     rows carry only {id, entity_type, label}, so the domain is inferred from
     keyword signatures in the id/label. This drives the community colouring in
     View B; the whole point of the sample is that the cross-domain *bridges*
     (a breed or concept that links research <-> policy <-> journalism) are what
     flat search misses.

  2. The AVMA loop-demo BRIDGE — the node `pub_avma_2014_breed_bite_risk` and its
     six edges are tagged `bridge:true`. The viz BEFORE/AFTER toggle hides them
     ("before": the research<->policy gap is open) then reveals + highlights them
     ("after": the path concept_safer_assessment -> AVMA review -> concept_bsl
     closes — behavioural research feeding the AVMA literature review feeding the
     breed-specific-legislation debate).

To regenerate after the gold graph changes:

    python3 examples/good-dogs/viz/gen_data.py

(no third-party deps; stdlib only.)
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLD = HERE.parent / "findings-gold"
OUT = HERE / "data.js"

# ---- the loop-demo bridge: the AVMA review + its 6 edges -------------------
BRIDGE_NODE = "pub_avma_2014_breed_bite_risk"

# ---------------------------------------------------------------------------
# Domain assignment. Six corpus domains. We test each entity's id+label against
# an ordered list of keyword signatures; FIRST match wins, so more-specific
# domains are listed before catch-alls. Tuned by reading the gold ids/labels.
# ---------------------------------------------------------------------------
DOMAIN_RULES = [
    # (domain, [regex keyword fragments tested against id+label, case-insensitive])
    ("municipal_policy", [
        r"\bbsl\b", r"breed[-_ ]specific", r"bylaw", r"\bban\b", r"ordinance",
        r"statute", r"legislation", r"dola", r"council", r"municipal",
        r"\bdenver\b", r"montreal", r"calgary", r"ontario", r"aurora",
        r"\bv_", r"_v_", r"ballot", r"repeal", r"rpob", r"bill_132",
        r"toledo", r"tellings", r"council_bluffs", r"danker", r"colorado_dog_fanciers",
        r"pit_bull_ban", r"dangerous_dog", r"responsible_pet_ownership",
    ]),
    ("nutrition_safety", [
        r"\bdcm\b", r"grain[-_ ]free", r"melamine", r"vitamin", r"vit_?d",
        r"hills?_", r"recall", r"raw[-_ ]?(pet|meat|food)", r"\bfda\b.*food",
        r"taurine", r"pulses", r"nutrition", r"freeman", r"diet",
        r"performance_dog", r"factsheet", r"premix",
    ]),
    ("behavioral_research", [
        r"schenkel", r"\bmech\b", r"avsab", r"dominance", r"alpha",
        r"positive[-_ ]reinforcement", r"reinforcement", r"aversive",
        r"vieira_de_castro", r"behavior_assessment", r"safer",
        r"bollen", r"horowitz", r"training", r"wolf", r"pack",
        r"cognition", r"watowich", r"cognitive",
    ]),
    ("breed_standards", [
        r"\bakc\b", r"\bukc\b", r"\bfci\b", r"\brkc\b", r"kennel",
        r"breed_standard", r"_standard", r"stud_book", r"open_registry",
        r"closed_stud", r"conformation", r"registry", r"teems", r"\bgdc\b",
        r"pedigree", r"breed_club",
    ]),
    ("veterinary_research", [
        r"leptospir", r"lepto", r"\bgdv\b", r"bloat", r"mortality", r"brourman",
        r"acvim", r"consensus", r"vaccine", r"vaccinat", r"welfare",
        r"jvim", r"clinical", r"veterinary", r"\bavma\b", r"serovar",
    ]),
    ("community_journalism", [
        r"\bnpr\b", r"\bcpr\b", r"\bcbc\b", r"newsroom", r"reporting",
        r"shelter", r"adoption", r"intake", r"journalism", r"news",
        r"coverage", r"story",
    ]),
]

# A few entities resist keyword inference (bare breeds, generic orgs). Pin them.
DOMAIN_PINS = {
    # the breeds are the spine — they belong to no single domain, but for the
    # community colouring we anchor them to breed_standards (their definitional home).
    "breed_german_shepherd_dog": "breed_standards",
    "breed_american_pit_bull_terrier": "breed_standards",
    "breed_american_staffordshire_terrier": "breed_standards",
    "breed_golden_retriever": "breed_standards",
    # the loop-demo concepts sit at the research<->policy seam:
    "concept_bsl": "municipal_policy",
    "concept_safer_assessment": "behavioral_research",
}

DEFAULT_DOMAIN_BY_TYPE = {
    "breed": "breed_standards",
    "person": "behavioral_research",
    "organization": "veterinary_research",
    "document": "veterinary_research",
    "concept": "behavioral_research",
    "product": "nutrition_safety",
    "event": "community_journalism",
    "location": "municipal_policy",
}


def assign_domain(ent):
    if ent["id"] in DOMAIN_PINS:
        return DOMAIN_PINS[ent["id"]]
    hay = (ent["id"] + " " + ent["label"]).lower()
    for domain, frags in DOMAIN_RULES:
        for frag in frags:
            if re.search(frag, hay):
                return domain
    return DEFAULT_DOMAIN_BY_TYPE.get(ent["entity_type"], "veterinary_research")


# ---------------------------------------------------------------------------
# Date extraction for the timeline. Pull the first 4-digit year out of the
# label, then the id, then the evidence. Documents/events are genuinely dated;
# concepts/breeds/people usually are not (and that is fine — they don't plot).
# ---------------------------------------------------------------------------
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
# explicit ISO dates that appear inside evidence text, e.g. 2020-11-03
ISO_RE = re.compile(r"\b(19|20)\d{2}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])\b")


def extract_year(ent):
    for field in (ent["label"], ent["id"]):
        m = YEAR_RE.search(field)
        if m:
            return int(m.group(0))
    return None


def main():
    ents = [json.loads(ln) for ln in (GOLD / "entities.jsonl").read_text().splitlines() if ln.strip()]
    edges = [json.loads(ln) for ln in (GOLD / "edges.jsonl").read_text().splitlines() if ln.strip()]

    ent_ids = {e["id"] for e in ents}

    # which edges touch the AVMA bridge node?
    bridge_edge_keys = set()

    # ---- build the entity rows the viz consumes ----
    out_entities = []
    for e in ents:
        out_entities.append({
            "id": e["id"],
            "type": e["entity_type"],
            "label": e["label"],
            "domain": assign_domain(e),
            "year": extract_year(e),
            "bridge": e["id"] == BRIDGE_NODE,
        })

    # ---- build the edge rows ----
    out_edges = []
    skipped = 0
    for i, ed in enumerate(edges):
        s, t = ed["source_id"], ed["target_id"]
        if s not in ent_ids or t not in ent_ids:
            # dangling edge — skip so the viz never references a phantom node
            skipped += 1
            continue
        is_bridge = (s == BRIDGE_NODE or t == BRIDGE_NODE)
        if is_bridge:
            bridge_edge_keys.add(i)
        out_edges.append({
            "id": f"e{i}",
            "from": s,
            "to": t,
            "type": ed["edge_type"],
            "evidence": ed.get("evidence", ""),
            "confidence": ed.get("confidence", None),
            "bridge": is_bridge,
        })

    # ---- sanity counts (mirrored into the file as a comment + __META) ----
    from collections import Counter
    etypes = Counter(e["type"] for e in out_entities)
    edtypes = Counter(e["type"] for e in out_edges)
    domains = Counter(e["domain"] for e in out_entities)
    contradicts = sum(1 for e in out_edges if e["type"] == "CONTRADICTS")
    bridge_edges = sum(1 for e in out_edges if e["bridge"])

    meta = {
        "entities": len(out_entities),
        "edges": len(out_edges),
        "skipped_dangling_edges": skipped,
        "contradicts": contradicts,
        "supersedes": sum(1 for e in out_edges if e["type"] == "SUPERSEDES"),
        "bridgeNode": BRIDGE_NODE,
        "bridgeEdges": bridge_edges,
        "datedEntities": sum(1 for e in out_entities if e["year"] is not None),
        "entity_types": dict(etypes),
        "edge_types": dict(edtypes),
        "domains": dict(domains),
    }

    header = (
        "/* data.js — GENERATED by gen_data.py. DO NOT EDIT BY HAND.\n"
        " *\n"
        " * Source of truth: examples/good-dogs/findings-gold/{entities,edges}.jsonl\n"
        " * Regenerate:      python3 examples/good-dogs/viz/gen_data.py\n"
        " *\n"
        " * The graph is INLINED (no runtime fetch) so the page opens offline from\n"
        " * file:// as well as a static server. The AVMA review node + its edges are\n"
        " * tagged bridge:true for the BEFORE/AFTER loop-demo toggle.\n"
        " *\n"
        f" * {meta['entities']} entities · {meta['edges']} edges · "
        f"{meta['contradicts']} CONTRADICTS · {meta['supersedes']} SUPERSEDES · "
        f"{meta['bridgeEdges']} bridge edges\n"
        " */\n\n"
    )

    body = (
        "const GOOD_DOGS_GRAPH = "
        + json.dumps({"entities": out_entities, "edges": out_edges, "meta": meta},
                     indent=2, ensure_ascii=False)
        + ";\n\n"
        "if (typeof module !== 'undefined') { module.exports = GOOD_DOGS_GRAPH; }\n"
    )

    OUT.write_text(header + body)
    print(f"wrote {OUT}")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
