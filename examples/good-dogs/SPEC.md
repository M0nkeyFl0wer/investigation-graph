# SPEC — "Good Dogs": the public-facing flagship sample investigation

**Status:** SPEC (for review before build) · **Audience:** public repo sample ·
**Privacy:** fully public, **zero PII** by construction (every entity is fictional
or a dog).

> **Why this exists.** Our only public-safe graph today is the fictional Harbor
> City graft case (`examples/sample-investigation/`, the "good doggo" baseline).
> Fed Filing — our richest worked case — is private (real people, instructor
> course material). We want a *second* public sample that shows off the
> full method (capture → extract → ground → build → analyze) **and** the data-viz
> template, on a subject that is delightful, shareable, and carries no privacy
> risk. So: **a graph that finds the good dogs and the good dog people.**
>
> Same rigor as a real investigation — every claim sourced to a corpus document,
> confidence-tagged, inferences kept dashed, each step documented — but the
> "investigation" is wholesome. It teaches the discipline without any of the
> ethical weight, which makes it the ideal thing to put in front of newcomers.

---

## 1. Mission (the playful triage)

A neighborhood (fictional **Maple Hollow**) has a lively dog community. From a pile
of ordinary documents — adoption papers, a dog-park sign-in sheet, a "best in
show" writeup, vet newsletters, a lost-and-found post — answer:

1. **Who are the good dogs?** Which dogs are documented as well-behaved / awarded /
   beloved — and on what evidence?
2. **Who are the good dog people?** Owners, volunteers, trainers, the vet — the
   humans who make the community work.
3. **What connects them?** Which dogs and people are linked through parks, the
   shelter, a shared trainer, littermates, friendships — and **where are the gaps**
   (the dog everyone mentions but no record explains; the trainer who is the only
   bridge between two packs)?

These are deliberately the same *shapes* of question a real investigation asks
(identity, affiliation, network, structural holes) — just answered about dogs.

**Output:** a public `CASE-STUDY.md` + the interactive viz, framed as a teaching
demo: "here is how the graph turns a folder of documents into a network, and how
to read it honestly."

---

## 2. Corpus design (the heart of the spec)

The corpus is **purpose-built and fictional** (no real animals, people, or
addresses), engineered like Harbor City so the graph has both **connections** and
**gaps** to find. ~7 short documents in mixed formats (the pipeline reads
txt/md/html/PDF), with **deliberately shared entities** so edges emerge across
documents and one or two entities are referenced but never explained (the gaps).

| # | Document (fictional) | Format | What it seeds | Planted connections / gaps |
|---|----------------------|--------|---------------|----------------------------|
| 1 | *Maple Hollow Gazette* — "Best in Show 2025" writeup | md | dogs, owners, the award, the park | names the winner + 2 runners-up; mentions a trainer |
| 2 | Happy Tails Shelter — adoption records | html | dogs ↔ adopters, adoption dates | links several dogs to their people; one dog adopted by two docs' people |
| 3 | Riverbend Dog Park — weekly sign-in sheet | txt | dogs, owners, the park, dates | the "pack" cliques (community detection); recurring regulars |
| 4 | Paws & Train — class roster | md | dogs ↔ trainer | the trainer is the **bridge** between two otherwise-separate packs |
| 5 | Maple Hollow Vet — newsletter "patients of the month" | html | dogs, the vet, health notes | corroborates some dogs; introduces one dog **no other doc mentions** (gap) |
| 6 | Lost & Found community post | txt | a dog + a finder | a **claim** ("good boy returned a wallet") to validate / flag |
| 7 | Littermate registry excerpt | md | LITTERMATE_OF edges | family structure; one littermate is referenced but absent (gap) |

**Goodness, honestly.** "Good dog" is never just asserted — it is *derived* and
**confidence-tagged** exactly like a real finding:
- **VERIFIED** good dog = an award/title in a primary doc (the show writeup).
- **CORROBORATED** = praised in ≥2 independent docs (park + vet).
- **CAPTURED** = a single mention.
- **INFERRED** (dashed) = "probably a good dog" from indirect signal (e.g., a
  therapy-visit note) — shown as inference, never as fact.
- The wallet-returning "good boy" is a **claim** from one source → flagged for
  validation, mirroring the verify-before-publish discipline.

This is the trick that makes a silly subject a *real* teaching tool: it
demonstrates source tiers, corroboration, and the honesty-of-uncertainty grammar
without any privacy stakes.

---

## 3. Ontology (beat extension — validate before adding)

Reuse the base ontology where it fits; propose a small, OntoClean-validated
extension for the dog beat (run `taxonomy-validation` before editing `ONTOLOGY.md`):

**Entity types:** `person` (owner/volunteer/trainer/vet), `organization`
(shelter, dog park, training school, vet clinic, kennel club), `location` (park,
neighborhood), `event` (adoption, show, class), `award` (title/ribbon), `claim`
(the good-boy assertion), and **`dog`** (the one genuinely new type — a named
animal; archetypical "Biscuit", exotypical "the dog park" → organization).

**Edge types** (each with a clear investigative purpose, mirroring the real beats):
| Edge | From → To | Why it matters |
|------|-----------|----------------|
| `OWNS` (reuse) | person → dog | who belongs to whom |
| `ADOPTED_FROM` | dog → organization | origin story; shelter ties |
| `WALKS_AT` | dog/person → location | the park cliques (communities) |
| `TRAINED_BY` | dog → person | the bridge trainer |
| `WON` | dog → award | the VERIFIED good-dog signal |
| `MEMBER_OF` (reuse) | dog/person → organization | club/class affiliation |
| `FRIEND_OF` | dog → dog | the social graph (use sparingly) |
| `LITTERMATE_OF` | dog → dog | family structure |
| `TREATED_BY` | dog → person/org (vet) | corroboration source |

`ASSOCIATED_WITH` stays the capped catch-all. No `dog`-specific edge gets added
without 3+ real instances in the corpus (the project's "earn the type" rule).

---

## 4. Process (the same five stages, documented + validated)

Run and **document each step** in an investigation log (same JSONL shape as the
real cases), so the case study can show the path:

1. **Scope** — confirm the ontology + corpus.
2. **Ingest** — chunk + embed the 7 docs → DuckDB.
3. **Extract** — three-phase typed entities + evidence-bearing edges (each edge
   quotes the corpus sentence that states it — the same `evidence` discipline).
4. **Ground** — drop unsupported items, resolve duplicate dog/person names
   (the merge-review demonstrates entity resolution: "Biscuit" vs "Biscuit the
   beagle"), assign confidence tiers.
5. **Build** — reconstruct-and-swap the graph; then `run_analysis.py`.

**Validation:** every "good dog" / "good dog person" claim in the final write-up
cites the corpus document that supports it; inferred goodness is labelled INFERRED.
Because the corpus is fictional and public, **no minimization gate is needed** —
but we still run the provenance + ledger gates to prove the chain-of-evidence
discipline holds even here.

---

## 5. The nifty data-viz (reuse the de-branded template)

De-brand the Fed Filing viz (currently private) into a generic, reusable
`viz/` template and apply it here — this is the "same template for other public
sample work" the operator asked for. Two linked, offline views:

- **View B — "The Pack Board"** (Cytoscape): the dog/person/place network.
  - node glyph = entity type (a paw glyph for `dog`); node size = degree.
  - **community detection** colors the dog-park packs; the **bridge trainer** pops
    as the high-betweenness connector between packs (the "nifty" structural
    reveal).
  - the **gap dog** (mentioned, unexplained) renders as the GAP node — the same
    "the hole is the finding" lesson, but charming instead of alarming.
  - edge style = inference (dashed = inferred goodness), color = source tier.
- **View A — Timeline**: adoptions + shows over time (a real calendar axis here,
  since the events are genuinely dated — no work-order decoupling needed, which
  also sidesteps the lie-factor caveat from the Fed Filing timeline review).
- Click any node/edge → provenance panel: which corpus document, which verbatim
  sentence, what confidence. (No SHA-256 capture layer needed for fictional docs;
  provenance = the corpus file + line.)

**Apply the Fed Filing viz review fixes from the start:** flex layout (no
hardcoded topbar offset), legend that doesn't occlude data, legend↔render parity
(every glyph in the legend is actually drawn).

---

## 6. Deliverables & layout

```
examples/good-dogs/
  SPEC.md                 ← this file
  corpus/                 ← the 7 fictional source documents (PUBLIC, tracked)
  ONTOLOGY-good-dogs.md   ← the beat extension (or fold into root ONTOLOGY.md)
  CASE-STUDY.md           ← the public worked write-up (tracked)
  investigation-log.jsonl ← the documented steps (tracked — it's fictional)
  findings/               ← entities.jsonl + edges.jsonl (tracked)
  viz/                    ← the de-branded reusable template, themed for dogs
```

Everything tracked and public (it's fiction). Linked from the README as the
**public flagship** (replacing the Fed Filing link we just removed).

---

## 7. Open decisions to confirm before build

1. **Corpus source.** This spec builds a **purpose-built fictional** Maple Hollow
   corpus (recommended — total control, zero PII, designed-in gaps). Alternative:
   mine an *existing* corpus you have in mind for dog content — if so, point me at
   it and I'll adapt. (The phrase "existing corpus" in your note — did you mean a
   specific dataset, or "the existing pipeline/sample machinery"? Defaulting to
   purpose-built unless you say otherwise.)
2. **Tone.** Wholesome-and-earnest (gentle parody of an investigation) vs.
   deadpan-noir ("the case of the very good boy"). Defaulting to wholesome with a
   light wink.
3. **Scope tonight.** Spec only (this), or proceed to author the corpus + run the
   pipeline + build the viz? It's all zero-risk fiction, so I can build it end to
   end on your nod.
```
