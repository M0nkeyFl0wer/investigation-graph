<!-- DRAFT — for the maintainer's edit. Public-facing copy in the project's voice.
The investigation, the named hubs, the numbers, and the loop are all real and
reproducible (see "Reproduce"); the wording is raw material, not finished copy. -->

# Good Dogs & Good Dog People

### An investigation: *follow the evidence, not the fear — who's actually looking out for dogs?*

Over and over, the same thing happens to dogs. A fear takes hold — a scary diet, a
"dangerous" breed, a dominance you're supposed to assert — and it drives marketing,
or panic, or law. And then a handful of people quietly follow the **evidence** and
pull the world back toward what's true. This is an investigation into those people
and those dogs, built from 36 public documents, using a knowledge graph to find the
story a folder of PDFs would hide.

**It's also a demonstration.** Everything below is a public record, summarized and
connected; nothing here is a new accusation. The point is to show what
`investigation-graph` does on a subject where the stakes are real but no one gets
hurt: turn documents into a typed, evidence-bearing map, and read the *shape* of
that map for the story.

## Bottom line — three takeaways

1. **The graph records disagreement instead of averaging it away.** Where fear met
   evidence — grain-free diets, breed bans, "alpha" dominance — both claims sit in
   the graph as an explicit `CONTRADICTS` or `SUPERSEDES` edge, sourced on both
   sides. You can *see* the correction happen.
2. **The "good dog people" are not an opinion — they're the structure.** The
   people and institutions who followed the evidence are literally the graph's
   load-bearing hubs (highest betweenness): the FDA, the AVMA, Lisa Freeman,
   the AVSAB, L. David Mech, the Calgary model. Remove them and the map falls apart.
3. **A graph tells you what's *missing*.** It found a real hole — the behavioral
   science and the breed-ban law never connected — and one sourced document closed
   it. That's the difference between a search box and an investigation.

## The cast (and how the graph names them)

The graph wasn't told who matters; betweenness centrality surfaced them — the nodes
the most paths run through:

**Good dog people — the evidence-followers:**
- **Dr. Lisa Freeman** (Tufts) — coined "BEG" and chased the grain-free/DCM signal
  honestly, all the way to the 2022 study that complicated her own earlier alarm.
- **L. David Mech** — the wolf biologist whose 1999 work *retired the "alpha wolf"*
  idea he'd helped popularize decades earlier. A good dog person corrects himself.
- **The AVSAB** and the **AVMA** — the veterinary bodies that put the dominance myth
  and breed-specific legislation, respectively, on the wrong side of the evidence.
- **The FDA** (the single biggest hub, degree 18) — the recall watchdog threaded
  through melamine (2007), Hill's vitamin-D (2019), and the salmonella recalls.
- **The Calgary model** — the responsible-ownership framework that became the
  evidence-based answer to breed bans.

**Good dogs — the maligned, vindicated:** the **American Pit Bull Terrier** /
**American Staffordshire Terrier** (banned on fear, exonerated on data) and the
**German Shepherd Dog** (a high-betweenness bridge across research, standards, and
policy).

## The three fears, and who corrected them

### 1. The grain-free panic
**Fear:** boutique "BEG" (boutique, exotic-ingredient, grain-free) diets marketed
as healthier; a 2018 alarm linking them to dilated cardiomyopathy (DCM).
**Evidence:** Freeman and the FDA investigate; the 2022 *JVIM* prospective study
complicates the simple grain-free→DCM story.
**In the graph:** a `CONTRADICTS` edge between the 2018 alarm and the 2022
reassessment — the disagreement preserved, not blended into a mush.

### 2. The breed panic
**Fear:** pit bulls cast as inherently dangerous; breed bans enacted (Denver 1989,
Ontario 2005, Montreal 2016).
**Evidence:** the AVMA's 2014 review finds breed doesn't predict bites and that
visual breed ID is unreliable; the Calgary model shows responsible-ownership rules
work better; courts and voters move (Colorado Dog Fanciers, Montreal 2018, Denver
2020, Aurora 2024).
**In the graph:** a fear→evidence→repeal arc you can trace — and the climax of this
case study (below).

### 3. The dominance myth
**Fear:** "be the alpha," dominance-based training rooted in 1947 captive-wolf
observation.
**Evidence:** Mech's own recantation; the 2008 AVSAB position statement; modern
welfare research on aversive methods.
**In the graph:** a `SUPERSEDES` chain from dominance theory to positive
reinforcement — the consensus shift, dated and sourced.

*(Running underneath all three: the FDA recall trail — melamine → Hill's vitamin D
→ salmonella — the watchdog catching what marketing missed.)*

## The climax — the graph finds a hole, and we close it

This is the part a search box can't do.

**The tool named a gap.** Topology showed two clusters that obviously *should*
connect but didn't: the **behavioral-research** cluster (the SAFER aggression-
assessment work, the dominance literature) and the **breed-law** cluster (breed-
specific legislation and the Denver/Calgary/Montreal/Ontario bylaws). Both turn on
the same breeds — yet a shortest-path query between them returned **NO PATH**. The
science and the law sat in separate worlds.

**We did the good-dog OSINT.** What public document bridges them? The **AVMA's 2014
review, *The Role of Breed in Dog Bite Risk and Prevention*** — it weighs the
behavior-and-bite research *and* states the case against breed bans. Public, sourced
(avma.org). We added it as one note.

**The bridge closed:**

> **SAFER behavioral research → AVMA 2014 review → Breed-specific legislation**

`concept_safer_assessment ↔ concept_bsl` went from **NO PATH → length 2**, the two
clusters merged, and the connected core grew from **62 to 83** nodes. One sourced
document turned "the science says one thing, the law does another" from an
unprovable hunch into a navigable, evidence-bearing path. *That* is the
investigation the cute title promised: a good dog person (the AVMA, doing the
review) reconnecting the evidence to the policy that ignored it.

## A note on honesty — two graphs

We build the corpus two ways, and the gap between them is itself a lesson.

- The **gold graph** (the corpus's hand-curated annotations) is the clean map this
  story is told on: **175 entities / 234 edges, 16 components**.
- The **extraction graph** (our pipeline reading the raw prose with a local LLM) is
  the honest, messy reality: the relationships are all there, but ~760 entities
  fragment into **549 components / 516 single-mention orphans** because the model
  over-extracts and doesn't canonicalize ("pit bull," "pit bull-type dogs," "300
  pit bulls" become three nodes). **Extraction quality is the hard part of graph-
  RAG**, and that's why a curated ontology earns its keep. (Full topology of both:
  `GAPS-MEASURED.md`.)

## What's still open (honest gaps remain gaps)

Not every thread closes. The dominance cluster still doesn't reach every bylaw; the
breed-group taxonomy is thin; the recall trail could connect to more of the
nutrition science. The tool's job isn't to pretend otherwise — it's to make the
holes visible so you know where to look next.

## The visualization

`viz/` renders this on the gold graph, fully offline, in two linked views: a
**knowledge network** (the cast as hubs, the three fears as `CONTRADICTS`/
`SUPERSEDES` edges, a before/after switch for the AVMA bridge) and a **timeline**
(the corrections on a real 1947→2024 calendar axis). Click any node or edge for its
provenance — which document, which evidence, what confidence.

## Reproduce

```bash
# The clean gold graph the story is told on — BEFORE the bridge:
GRAPH_DIR=examples/good-dogs/data-gold/graph.lbug \
ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY-gold.md \
PYTHONPATH=. python scripts/build_graph_from_corpus_gold.py examples/good-dogs/corpus
#   run_analysis.py  →  behavioral <-> policy = NO PATH (the gap).

# Close the loop — add the one sourced document and rebuild:
GRAPH_DIR=examples/good-dogs/data-gold/graph.lbug \
ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY-gold.md \
PYTHONPATH=. python scripts/build_graph_from_corpus_gold.py \
  examples/good-dogs/corpus examples/good-dogs/enrichment
#   run_analysis.py  →  SAFER -> AVMA review -> BSL. The bridge is closed.

# The honest, messy extraction graph (our pipeline on raw prose) — needs Ollama:
INGEST_DIR=examples/good-dogs/corpus GRAPH_DIR=examples/good-dogs/data/graph.lbug \
CHUNK_DB=examples/good-dogs/data/chunks.duckdb ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY.md \
PYTHONPATH=. python scripts/ingest_folder.py
```

## Sources

Every corpus note cites its public source (FDA recalls, AKC/UKC/FCI breed
standards, municipal bylaws and court decisions, peer-reviewed studies, AVSAB/AVMA
statements, local journalism). The enrichment note cites the AVMA 2014 review and
the AVMA's public BSL-position page. Nothing here is a new allegation; everything is
a public record, summarized and connected.
