# SPEC — "Good Dogs": the public-facing flagship sample investigation

**Status:** SPEC (build deferred — operator said "spec only for now") ·
**Audience:** public repo sample · **Privacy:** fully public, **zero PII** by
construction (entities are breeds, public researchers/officials, agencies,
studies, bylaws — all from public sources).

> **Correction to an earlier draft of this spec:** an earlier version invented a
> fictional "Maple Hollow / find the good boy" corpus. That was wrong — there is
> already a real, reused **good-dog-corpus**. This spec is rewritten against the
> actual corpus.

---

## 1. What the corpus actually is

**Source:** `~/Projects/second-brain-hybrid-graph/examples/good-dog-corpus`
(canonical home; also used by `multipass-sme-cde-expansion` and others as a shared
demo corpus). **It is not yet copied into investigation-graph** — build step 1 is
to vendor it in (see §6).

**36 markdown notes across six domains**, drawn from public dog-related sources:

| Domain | Notes | Examples |
|--------|-------|----------|
| `veterinary_research` | 8 | FDA DCM investigation, leptospirosis consensus, GDV mortality |
| `behavioral_research` | 6 | Schenkel 1947, Mech alpha-status self-correction, AVSAB dominance position |
| `nutrition_safety` | 6 | melamine recall (2007), Hill's vitamin-D recall (2019), grain-free signal |
| `municipal_policy` | 6 | Denver/Montreal/Calgary BSL, Ontario DOLA, court challenges |
| `community_journalism` | 5 | Aurora pit-bull-ban repeal, shelter adoption pace, recall reporting |
| `breed_standards` | 5 | AKC/UKC/FCI/RKC breed definitions |

Each note has **typed frontmatter** (`mentions_entities:` lists entities already
tagged by type, `authored_by`, `source_url`, `source_date`, `license`) — so the
graph has strong structured anchors, not just free text.

**It ships with its own ontology** (`ontology.yaml` + a design-rationale
`ONTOLOGY.md`): 8 entity types and 12 edge types, hand-designed against an SME
evaluation framework. We **reuse that ontology**, we do not invent one.

---

## 2. Mission — the friendly hook over a real demonstration

"**Find the good dogs and the good dog people**" is the inviting framing; the
substance is what makes the graph earn its keep:

- **The good dogs** = the `breed` entities (German Shepherd, American Pit Bull
  Terrier, Golden Retriever, …) — the spine everything else hangs off.
- **The good dog people (and institutions)** = the `person` + `organization`
  entities: researchers, vets, journalists, council members, kennel clubs,
  universities, regulators (FDA, AVSAB, AKC) — the humans/bodies behind the
  knowledge.
- **The investigation** = how knowledge *about* dogs connects across six domains:
  a behavioral finding that drives a municipal bylaw; a recall that ripples from
  FDA notice to vet research to local reporting.

This is the same shape as a real investigation (identity, affiliation, network,
contradiction, timeline, gaps) — but the subject is wholesome and public, which is
exactly why it's the right public flagship.

---

## 3. Investigative questions (the corpus already seeds these)

The corpus was *designed* against SME eval categories; each maps to a crisp
"good-dogs" investigation beat the case study walks through:

| Beat | Question | What the graph shows | Corpus seed |
|------|----------|----------------------|-------------|
| **Identity / alias** | Is "GSD" the same good dog as "Alsatian" and "German Shepherd Dog"? | entity resolution collapses 3 surface forms to 1 `breed` (merge-review) | `alias_of` (GSD; APBT≠AmStaff is the trap) |
| **Network / multi-hop** | Which good dog *person* links a behavioral study to a city's breed law? | a `person`→`affiliated_with`→`org`→`authored`→`publication`→`subject_of`→`concept(BSL)` path | Aurora pit-bull repeal ties breed+BSL+people+policy |
| **Contradiction** | Where do the good dog people *disagree*? | a `contradicts` edge kept as a contradiction, **not averaged away** | grain-free → DCM (2018 signal vs 2022 reassessment) |
| **Temporal / supersession** | How did "good dog" consensus *change*? | a `supersedes` chain on a real time axis | dominance theory → positive reinforcement (1970s→AVSAB 2009) |
| **Structural gap** | What's the good dog everyone talks about but no record explains? | a high-mention entity with a missing connecting document | breeds referenced across domains with no direct link |

Answering these *is* the case study. Every answer cites the note(s) that support
it; contradictions and human-grounded edges are flagged, never asserted as
machine-certain.

---

## 4. Ontology — reuse the corpus's, translate to our format

The corpus's `ontology.yaml` is the source of truth: **8 entity types** (`breed`,
`person`, `organization`, `publication`, `concept`, `product`, `event`,
`location`) and **12 edge types** (`mentions`, `alias_of`, `supersedes`,
`contradicts`, `cites`, `authored_by`, `affiliated_with`, `regulates`,
`subject_of`, `member_of`, `grouped_under`, `located_in`), each with an
**evidence rule** (lexical / registry / explicit-marker / claim-pair / byline /
…) and several requiring **human grounding** (`contradicts`, `subject_of`).

Build task: translate this YAML into investigation-graph's `ONTOLOGY.md` table
format (validate with `taxonomy-validation` to confirm the translation preserves
the OntoClean discipline — the corpus already split `member_of` vs `grouped_under`
on identity grounds, a good model). **No new types invented.** This also proves a
nice point for the repo: investigation-graph can adopt an externally-authored,
discipline-checked ontology wholesale.

---

## 5. Process — the five stages, documented + validated

Run the standard pipeline on the vendored corpus and **log every step** (same
`investigation-log.jsonl` shape the cases use), so the write-up shows the path:

1. **Scope** — adopt the translated ontology; point ingest at the corpus vault.
2. **Ingest** — chunk + embed 36 notes → DuckDB (frontmatter `mentions_entities`
   gives high-precision deterministic anchors alongside spaCy/LLM extraction).
3. **Extract** — typed entities + evidence-bearing edges; `alias_of` comes from
   the registry (not free LLM extraction), per the evidence rule.
4. **Ground** — resolve aliases (GSD/Alsatian → one breed; **keep APBT≠AmStaff**),
   preserve the seeded `contradicts` pair, assign confidence; the **merge-review**
   artifact shows the alias collapse for human confirmation.
5. **Build** — reconstruct-and-swap; then `run_analysis.py` for communities,
   bridges, and gaps.

**Validation:** every claim in the case study cites a corpus note; the
contradiction is shown as a contradiction; human-grounding-required edges
(`contradicts`, `subject_of`) are labelled as such. Fictional? No — but public and
non-sensitive, so **no minimization gate is needed**; we still run the provenance +
ledger gates to show the chain-of-evidence discipline holds.

---

## 6. The data-viz (de-branded reusable template)

De-brand the (now-private) Fed Filing viz into a generic `viz/` template — the
"same template for other public sample work" — and theme it for dogs. Two linked,
offline views:

- **View B — the knowledge network** (Cytoscape):
  - node glyph = entity type (breed / person / org / publication / concept / …),
    size = degree.
  - **community detection** colors the six domains; the **nifty reveal** is the
    *cross-domain bridges* — a `breed` or `concept` (e.g. BSL, German Shepherd)
    that connects research ↔ policy ↔ journalism, which flat search misses.
  - the **`contradicts` edge** gets a distinct style (the grain-free/DCM pair) —
    the "the graph records disagreement instead of averaging it" lesson, visible.
  - the **gap** entity renders as the GAP node — charming, not alarming.
  - edge style = evidence strength / human-grounded vs lexical; color = … (reuse
    the tier ramp idea, re-keyed to the corpus's evidence-rule types).
- **View A — timeline** (D3): the `supersedes` chains and recall timelines on a
  **real calendar axis** (events are genuinely dated — no work-order decoupling,
  which sidesteps the lie-factor caveat from the Fed Filing timeline review).
- Click any node/edge → provenance panel: which note, which frontmatter/sentence,
  which evidence rule, confidence. (Provenance = the corpus file + line; no SHA-256
  capture layer needed for public published sources.)

**Carry over the Fed Filing viz review fixes from the start:** flex layout (no
hardcoded topbar offset), legend that does not occlude data, legend↔render parity.

**Prior art:** `~/Projects/multipass-sme-cde-expansion/tools/good-dog-graph-pipeline/`
already builds a graph from this corpus (`good-dog-ontology-build.yaml`, demo,
workflows). Review it before building so we align with the established pattern
rather than fork it.

---

## 7. Deliverables & layout

```
examples/good-dogs/
  SPEC.md                 ← this file
  corpus/                 ← VENDORED copy of good-dog-corpus/vault (36 notes, PUBLIC)
  ONTOLOGY.md             ← the corpus ontology translated to our table format
  CASE-STUDY.md           ← the public worked write-up (the five beats, sourced)
  investigation-log.jsonl ← documented steps
  findings/               ← entities.jsonl + edges.jsonl
  viz/                    ← de-branded reusable template, themed for dogs
```

All tracked and public. Linked from the README as the **public flagship**
(filling the slot we just removed when Fed Filing went private). The Harbor City
sample stays as the tiny quick-start; Good Dogs becomes the richer showcase.

---

## 8. Open decisions to confirm before build

1. **Vendoring.** Copy the corpus into `examples/good-dogs/corpus/` (recommended —
   self-contained, matches how you reuse it elsewhere) vs. git submodule vs.
   read it from its canonical path. *Default: copy in.*
2. **Ontology home.** Translate the corpus ontology into a sample-local
   `examples/good-dogs/ONTOLOGY.md`, or promote it to the repo-root `ONTOLOGY.md`?
   *Default: sample-local, to keep the root ontology investigation-generic.*
3. **Align with prior art.** Reuse / adapt the `multipass` good-dog-graph-pipeline
   build, or build fresh against investigation-graph's `ingest_folder.py`?
   *Default: build on `ingest_folder.py` (our stack), borrowing the ontology-build
   YAML as reference.*
4. **Extraction compute.** Local Ollama vs the seshat tunnel (same choice as the
   cases). *Default: local first; corpus is small.*

Build is **deferred** per your "spec only for now." On your nod I'll execute §5–§7.
