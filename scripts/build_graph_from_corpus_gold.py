#!/usr/bin/env python3
"""
Build the *gold* good-dogs graph from the corpus's own hand-curated frontmatter
``entities:``/``edges:`` blocks — the canonical graph the corpus was designed to
materialize, as opposed to the noisy graph the LLM extractor produces from raw
prose. This is the clean graph the flagship viz + case study render.

Each note's YAML frontmatter carries gold entities (id/type/canonical) and gold
edges (from/type/to/evidence) with IDs that interconnect across notes. We parse
all of them, map the corpus vocabulary onto ours (publication→document; the 12
corpus edge types → our UPPERCASE names; authored_by's direction normalized to
person→document), and build via the corruption-safe reconstruct-and-swap. Builds
with the permissive ONTOLOGY-gold.md so the curated data renders faithfully (no
grade-locality drops — the data is already clean by construction).

Usage:
  PYTHONPATH=. GRAPH_DIR=examples/good-dogs/data-gold/graph.lbug \
    python scripts/build_graph_from_corpus_gold.py examples/good-dogs/corpus examples/good-dogs/enrichment
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

from investigation_graph.graph import build_graph
from investigation_graph.ontology import Ontology

_FM = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

# corpus entity type -> our type
TYPE_MAP = {"publication": "document"}
# corpus edge type -> (our UPPERCASE type, flip_direction?)
EDGE_MAP = {
    "authored_by": ("AUTHORED", True),      # pub->person  =>  person->document
    "affiliated_with": ("AFFILIATED_WITH", False),
    "subject_of": ("ABOUT", False),
    "mentions": ("MENTIONS", False),
    "cites": ("CITES", False),
    "contradicts": ("CONTRADICTS", False),
    "supersedes": ("SUPERSEDES", False),
    "alias_of": ("ALIAS_OF", False),
    "regulates": ("REGULATES", False),
    "member_of": ("MEMBER_OF", False),
    "located_in": ("LOCATED_AT", False),
    "grouped_under": ("GROUPED_UNDER", False),
}


def parse_note(path: Path):
    """Return (entities_dict, edges_list) from one note's gold frontmatter."""
    m = _FM.match(path.read_text(encoding="utf-8"))
    if not m:
        return {}, []
    fm = yaml.safe_load(m.group(1))
    if not isinstance(fm, dict):
        return {}, []
    ents = {}
    for e in (fm.get("entities") or []):
        if isinstance(e, dict) and e.get("id"):
            ctype = e.get("type", "concept")
            ents[e["id"]] = {
                "entity_type": TYPE_MAP.get(ctype, ctype),
                "label": e.get("canonical") or e["id"],
            }
    edges = []
    for ed in (fm.get("edges") or []):
        if not isinstance(ed, dict) or not ed.get("type"):
            continue
        mapped = EDGE_MAP.get(ed["type"])
        if not mapped:
            continue
        etype, flip = mapped
        src, tgt = ed.get("from"), ed.get("to")
        if not src or not tgt:
            continue
        if flip:
            src, tgt = tgt, src
        edges.append({"source_id": src, "target_id": tgt, "edge_type": etype,
                      "evidence": (ed.get("evidence") or "")[:480], "confidence": 1.0})
    return ents, edges


def main(argv):
    dirs = argv[1:] or ["examples/good-dogs/corpus", "examples/good-dogs/enrichment"]
    notes = []
    for d in dirs:
        notes += sorted(Path(d).rglob("*.md"))

    entities: dict[str, dict] = {}
    edges: list[dict] = []
    for n in notes:
        ents, eds = parse_note(n)
        for eid, e in ents.items():
            entities.setdefault(eid, e)   # first definition wins (deterministic)
        edges.extend(eds)

    # Create placeholder nodes for any edge endpoint that was referenced but never
    # defined in an entities: block (so no edge dangles). Reported, not silent.
    referenced = {x for ed in edges for x in (ed["source_id"], ed["target_id"])}
    missing = referenced - set(entities)
    for mid in missing:
        entities[mid] = {"entity_type": "concept", "label": mid}

    g_entities = [{"id": k, "entity_type": v["entity_type"], "label": v["label"]}
                  for k, v in entities.items()]

    graph_dir = None  # build_graph reads config.GRAPH_DIR when None
    ont = Ontology("examples/good-dogs/ONTOLOGY-gold.md")
    counts = build_graph({"documents": [], "entities": g_entities, "edges": edges,
                          "mentions": []}, graph_dir=graph_dir, ontology=ont)

    # Export the clean gold findings for the viz + case study.
    out = Path("examples/good-dogs/findings-gold")
    out.mkdir(parents=True, exist_ok=True)
    with (out / "entities.jsonl").open("w", encoding="utf-8") as fh:
        for e in g_entities:
            fh.write(json.dumps(e) + "\n")
    with (out / "edges.jsonl").open("w", encoding="utf-8") as fh:
        for ed in edges:
            fh.write(json.dumps(ed) + "\n")

    print(f"notes parsed:        {len(notes)}")
    print(f"gold entities:       {len(g_entities)}  ({len(missing)} placeholder)")
    print(f"gold edges:          {len(edges)}")
    print(f"graph built:         {counts}")
    print(f"findings-gold/ written ({len(g_entities)} entities, {len(edges)} edges)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
