# GAPS — where the good-dog-corpus needs more research

**Status:** SPEC (companion to `SPEC.md`) · **Purpose:** identify coverage gaps in
the corpus and turn *filling them* into a demonstration of the tool — "good-dog
OSINT" that shows the graph telling you **where to research next**.

> **The big idea.** A knowledge graph's best trick isn't answering questions — it's
> exposing the *holes in the structure* as leads (the Princeton topology-
> verification framing; the EvoSkills co-evolutionary loop: topology gaps feed back
> into the next round of enrichment). So the public flagship shouldn't just *be* a
> finished graph — it should **demonstrate the loop**: build → find gaps → do
> targeted public-records OSINT to fill them → re-ingest → watch a bridge close.
> That loop, on a wholesome subject, is the most compelling thing we can show.

---

## 1. How to find the gaps (use the tool + the SME framework)

Two complementary gap-finders, both already in the stack:

**A. Topology (the tool itself).** `run_analysis.py` surfaces:
- **structural gaps** — community pairs with low cross-edges (domains that *should*
  connect but don't yet): e.g. a `behavioral_research` finding and a
  `municipal_policy` bylaw about the same breed with no path between them.
- **bridges** — single entities holding two clusters together (fragile knowledge:
  one note away from disconnection).
- **orphans / thin nodes** — entities mentioned once, with no corroboration.

**B. The SME ontology coverage map** (`good-dog-corpus/ontology.yaml`
§`sme_category_coverage`). It declares which categories the corpus *intends* to
exercise. The gap is the delta between *declared* and *instantiated*:
- categories with seeds present: 1 (factual), 2c (multi-hop), 3 (contradiction),
  4 (alias), 6 (temporal), 8 (ontology-coherence), 10 (phantom-edges).
- categories **not** in the map (candidate eval gaps): aggregation/quantitative,
  comparison, negation/absence, causal chains — under-tested today.
- **edge types declared but likely under-instantiated** (verify after a build —
  count instances): `cites`, `regulates`, `grouped_under`. An edge type with <3
  real instances is a declared-but-unexercised gap.

The build's first job is to **measure** these (don't quote the numbers below as
fact until a build confirms them — they're hypotheses from reading the corpus).

---

## 2. Hypothesized content gaps + the OSINT that fills them

Each row is a gap, the public source to mine (the "good-dog OSINT"), and the
SME category / topology hole it closes. All sources are public records.

| Gap (hypothesis) | Good-dog OSINT to fill it | Closes |
|------------------|---------------------------|--------|
| **Breed-group taxonomy thin** — `grouped_under` (breed→group) is new in v0.2; few breed-group notes, so the taxonomic spine is sparse | AKC/UKC/FCI group listings (Herding, Terrier, Sporting…) → `breed`+`grouped_under` | ontology-coherence; multi-hop via group |
| **Product/brand coverage thin** — the DCM/recall story names brands the corpus doesn't model | FDA CVM recall database + the 2019 FDA DCM brand-name list (public) → `product` entities + `regulates`/`subject_of` | factual retrieval; aggregation |
| **Incomplete research→policy bridges** — a bylaw exists but the specific study it relies on isn't in-corpus | municipal ordinance texts (Denver/Calgary/Ontario already present) + the cited studies → `cites`/`subject_of` edges | multi-hop; structural-gap closure |
| **Temporal chains have holes** — dominance→positive-reinforcement chain jumps 2009→today | AVSAB / AAHA later position statements; modern training-welfare reviews → `supersedes` links | temporal |
| **Only 2 contradictions seeded** — thin for a contradiction showcase | raw-diet safety debate (FDA vs raw-feeding advocacy studies); BSL-efficacy studies that disagree → `contradicts` pairs | contradiction |
| **Geographic concentration** — policy notes skew US/Canada | UK Dangerous Dogs Act, EU breed rules (public statute text) → `located_in` breadth | comparison; multi-hop |
| **Few `person` corroboration paths** — some researchers appear once | author disambiguation via DOI/ORCID + institutional pages → `affiliated_with`/`authored_by` | multi-hop; orphan reduction |

---

## 3. The demonstration (this is the public-facing payoff)

Frame the case study's final act as the **co-evolutionary loop**, end to end:

1. Build the graph from the 36 notes; run topology.
2. The tool **names a gap** (e.g. "the German Shepherd breed connects to a
   behavioral study and to a Calgary bylaw, but no document links the study to the
   bylaw — a missing bridge").
3. Do **targeted public-records OSINT** to find the connecting source (the
   ordinance's cited evidence, or a journalism piece tying them).
4. Add the note, **re-ingest**, and show the **bridge close** — with the new edge
   confidence-tagged and sourced.
5. Note what's *still* open (honest gaps remain gaps).

This turns the sample from a static demo into a living illustration of *why* a
graph beats a folder of PDFs: it doesn't just store what you know — it shows you
what to go find.

---

## 4. Scope note

Build deferred ("spec only for now"). Step order when it resumes: vendor corpus →
translate ontology → build → **`run_analysis.py` to confirm which gaps above are
real (replace hypotheses with measured counts)** → pick 1–2 gaps → do the OSINT →
re-ingest → write the loop into `CASE-STUDY.md`. Keep it small: 1–2 closed gaps
illustrate the loop better than ten.
