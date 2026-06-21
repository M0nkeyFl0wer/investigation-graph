<!-- DRAFT — for the maintainer's edit. This is public-facing copy in the project's
voice; the numbers and the loop are real and reproducible (see "Reproduce" below),
but the wording is raw material, not finished copy. -->

# Good Dogs & Good Dog People — a worked knowledge-graph investigation

A wholesome, zero-PII demonstration of what `investigation-graph` does: take a
folder of public documents, turn it into a typed, evidence-bearing knowledge
graph, and then use the **shape** of that graph to tell you where to look next.
The subject is dogs — veterinary science, behavior research, pet-food safety,
breed standards, municipal policy, and the local journalism that covers all four —
because the most compelling way to show a tool is on something everyone can follow
and no one gets hurt by.

This case study is a **public-records methodology demonstration**, not a new
claim about anyone. Every fact traces to a public source in the corpus.

## The corpus

`corpus/` holds **36 public notes across 6 domains** — veterinary research (8),
behavioral research (6), nutrition & safety (6), municipal policy (6), community
journalism (5), and breed standards (5). Each note is a fair-use summary of a
real, attributable public source (FDA recalls, AKC/UKC breed standards, municipal
bylaws, peer-reviewed studies, AVSAB position statements, local news), with a
hand-curated frontmatter block of typed entities and relationships.

## Two graphs, on purpose

We build the corpus two ways, and the difference is itself a lesson.

**1. The extraction graph — what the tool finds in raw prose.** We strip the
frontmatter and run our pipeline end-to-end (chunk → embed → three-phase
extraction → grounding → graph) over the *prose only*. The result is honest and
messy: **~760 entities / ~210 edges**, but **549 connected components and 516
single-mention orphans**. A local LLM reading prose produces redundant,
un-canonicalized entities — `"pit bull"`, `"pit bull-type dogs"`, `"300 pit
bulls"`, and `"pit bull characteristics"` all land as *separate* nodes. The typed
relationships we want are all there (7 `CONTRADICTS`, 11 `SUPERSEDES`, 38
`ALIAS_OF`), but the graph is fragmented. **This is the realistic baseline** — and
the grounding gate that quarantines ~20% of edges is doing its job.

**2. The gold graph — the corpus's curated design.** The corpus also ships
hand-authored annotations (the frontmatter entity/edge blocks) whose IDs
interconnect across notes by construction. Built from those, the same 36 notes
become **175 entities / 234 edges in just 16 components, with 7 orphans** and a
62-node connected core. This is the clean graph the corpus was *designed* to
materialize, and it's the one we visualize and investigate below.

The gap between the two graphs is the real-world story: **extraction quality is
the hard part of graph-RAG**, and a curated ontology + annotations is what turns a
fragmented scrape into a navigable map. (See `GAPS-MEASURED.md` for the full
topology of both.)

## What the graph already knows — five investigative moves

The corpus was designed to exercise the questions a knowledge graph answers better
than a folder of PDFs:

- **Contradiction (the graph records disagreement instead of averaging it).** The
  grain-free / DCM debate is in the graph as a `CONTRADICTS` edge: the 2018
  "diet-associated DCM" alarm vs. the 2022 Freeman *JVIM* prospective reassessment.
  So is the training-science shift: the 1970s dominance/"alpha" model vs. the 2008
  AVSAB position statement and later aversive-training welfare research.
- **Temporal supersession.** `SUPERSEDES` chains carry the dominance-theory →
  positive-reinforcement consensus shift and the staged pet-food recall timelines.
- **Alias resolution.** `ALIAS_OF` links the German Shepherd Dog / Alsatian / GSD
  surface forms — and the corpus deliberately keeps the American Pit Bull Terrier
  and the American Staffordshire Terrier *distinct* (a trap for systems that
  collapse them).
- **Multi-hop.** A researcher → their institution → a study → the policy that
  leaned on it: paths flat search can't make.
- **Cross-domain bridges.** The breeds and concepts that hold the six domains
  together — German Shepherd Dog, DCM, breed-specific legislation — surface as
  high-betweenness nodes: the connective tissue that a topic-by-topic read misses.

## The payoff — the co-evolutionary loop

A knowledge graph's best trick isn't answering a question you already have; it's
**exposing the holes in its own structure as leads.** Here is that loop, run end
to end on the gold graph.

**1. Build and run topology.** `run_analysis.py` reports communities, bridges, and
structural gaps.

**2. The tool names a gap.** Two clusters that obviously *should* connect, don't:
the **behavioral-research** cluster (the SAFER aggression-assessment work, the
dominance-theory literature, Bollen & Horowitz 2012) and the **municipal-policy**
cluster (the breed-specific-legislation concept and the Denver / Calgary / Montreal
/ Ontario bylaws). Both turn on the same breeds — yet a shortest-path query between
them returns **NO PATH** (verified across every behavioral×policy pair). The
science and the law sit in separate components.

**3. Do targeted public-records OSINT to fill it.** What public document bridges
the behavior science and the breed bans? The **AVMA's 2014 literature review,
*The Role of Breed in Dog Bite Risk and Prevention*** — it weighs the bite-and-
behavior research *and* states the veterinary case against breed-specific
legislation ("breed-specific bans are a simplistic answer to a far more complex
social problem"; visual breed identification is unreliable; ownership factors
matter more than breed). Sourced to avma.org. We add it as one note in
`enrichment/`, annotated to cite the SAFER-validity study and to be *about* breed-
specific legislation.

**4. Re-ingest and watch the bridge close.** With the one note added, the path
appears:

> **SAFER (behavioral research) → AVMA 2014 review → Breed-specific legislation**

`concept_safer_assessment ↔ concept_bsl` goes from **NO PATH → length 2**, the
behavioral and policy clusters merge, and the largest connected component grows
from **62 to 83** nodes. One sourced document, and a question that flat search
would never have surfaced now has a navigable, evidence-bearing answer.

**5. Be honest about what's still open.** Not every gap is worth closing, and some
remain by design — the dominance-theory cluster still doesn't reach every bylaw,
the breed-group taxonomic spine is thin (`GROUPED_UNDER` is sparse), and the
extraction graph's orphan tail is real. Honest gaps stay gaps; the tool just makes
them visible.

## The visualization

`viz/` renders the gold graph in two linked, fully-offline views: a **knowledge
network** (communities colored by domain, cross-domain bridges and the
`CONTRADICTS` edges called out, a before/after toggle for the AVMA bridge) and a
**timeline** (the supersession and recall chains on a real calendar axis). Click
any node or edge for its provenance — which note, which evidence, what confidence.

## Reproduce

```bash
# 1. Extraction graph (the honest, messy baseline) — strips frontmatter, runs the
#    full pipeline. Needs Ollama (local or a remote endpoint via EXTRACT_ENDPOINT).
INGEST_DIR=examples/good-dogs/corpus \
GRAPH_DIR=examples/good-dogs/data/graph.lbug \
CHUNK_DB=examples/good-dogs/data/chunks.duckdb \
ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY.md \
PYTHONPATH=. python scripts/ingest_folder.py

# 2. Gold graph (the clean, curated graph) — before the enrichment:
GRAPH_DIR=examples/good-dogs/data-gold/graph.lbug \
ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY-gold.md \
PYTHONPATH=. python scripts/build_graph_from_corpus_gold.py examples/good-dogs/corpus
#    ...then run_analysis.py and note: behavioral <-> policy = NO PATH.

# 3. Close the loop — add the enrichment note and rebuild:
GRAPH_DIR=examples/good-dogs/data-gold/graph.lbug \
ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY-gold.md \
PYTHONPATH=. python scripts/build_graph_from_corpus_gold.py \
  examples/good-dogs/corpus examples/good-dogs/enrichment
#    ...run_analysis.py again: SAFER -> AVMA review -> BSL, the bridge is closed.
```

## Sources

The corpus notes each cite their public source. The enrichment note cites the AVMA
2014 review (`avma.org/.../dog_bite_risk_and_prevention_bgnd.pdf`) and the AVMA's
public BSL-position page. Nothing here is a new allegation; everything is a public
record, summarized and connected.
