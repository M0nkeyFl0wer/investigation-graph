# Case Study — Mapping a SAM.gov Imposter Network from a Single Spam Email

*A worked, reproducible investigation built with **investigation-graph**.*

> **What this is.** A public-records methodology demonstration. Starting from one
> unsolicited "renew your SAM registration" email, we use the investigation-graph
> stack — evidentiary capture → typed-entity/relationship extraction → grounding →
> a knowledge graph — to reconstruct the operator network behind the sender. It is
> the project's flagship example: it shows the *method*, not a new accusation.
>
> **What this is not.** Not a criminal allegation. The conduct documented here is,
> as the source training exercise framed it, "not illegal, but not remotely
> ethical" — a paid middleman inserting itself into a **free** government process.
> Every claim below is sourced to a captured primary record and tagged with a
> confidence level. Inferences are labelled as inferences. We assert no wrongdoing
> beyond what public records show, and we name individuals **only** through public
> *business* records (state corporate filings, a company's own website, a
> regulator advisory) — never home addresses, family, or personal identifiers.
>
> **Standard.** Modeled on the Berkeley Protocol on Digital Open Source
> Investigations: every finding is sourced; integrity is preserved with a SHA‑256
> evidence manifest; the method is reproducible; and minimization is applied to
> this public version. LLM‑assisted, **human‑verified**, primary‑source‑grounded.

---

## 1. The starting point

A small business received this email (the recipient's own details are redacted;
it is the *target* of the spam, not a participant):

> **From:** David Holland <david.holland@fedfiling.com> — "Account Executive"
> **Subject:** *…SAM Renewal…*
> *"Your registration … is nearing its expiration date. To maintain uninterrupted
> access … and prevent any disruptions in your ability to conduct business with the
> federal government or receive funds, it is imperative that you promptly renew …"*
> **Call now:** (877) 886‑9960 · **Address block:** 701 S Howard Ave, Tampa, FL 33606
> *"Federal Filing is an Independent firm."*

The triage questions (from the exercise brief):

1. Who is **David Holland** — a real person, or a disposable persona?
2. What is the company, and **who owns / operates / profits from it**?
3. How does the scheme actually work?

A single document, three relationship-shaped questions — exactly the shape a graph
answers better than a folder of notes.

---

## 2. How the investigation was built

investigation-graph runs a five-stage local pipeline (`scope → ingest → extract →
ground → build`; see `../../SPEC.md`). For this case the stages map to:

| Stage | What happened here |
|-------|--------------------|
| **Capture** | Each primary source (the email, state corporate filings, the company sites, the regulator advisory, DNS/RDAP records) was captured to disk and **SHA‑256‑hashed** into an evidence manifest (`evidence/manifest.jsonl`). A claim is not evidence until its primary source is captured and re-hashable. |
| **Extract** | Entities and **typed, evidence-bearing edges** were drawn from the captured text. Every edge carries the verbatim source span that justifies it. |
| **Ground** | Each candidate was checked against its source, entity duplicates (aliases) resolved, and a confidence tier assigned. |
| **Build** | The survivors were projected into a knowledge graph via **reconstruct‑and‑swap** (the whole graph is rebuilt from the vetted record set, so adding sources never corrupts existing data). |

The result is a companion knowledge graph of **23 entities and 28 relationships**.
Every node and edge is provenance-linked (it names the evidence artifact that backs
it) and **confidence-tagged**:

| | VERIFIED | CORROBORATED | CAPTURED | INFERRED / UNVERIFIED |
|---|---|---|---|---|
| **Entities (23)** | 15 | 3 | 4 | 1 (unsupported persona) |
| **Edges (28)** | 22 | — | 1 | 5 (3 inferred + 2 unverified) |

The **5 inferential edges are rendered dashed** in the companion visualization and
are never presented as fact. That discipline is the point: an investigative graph
is only as trustworthy as its weakest unlabelled edge.

> **Source tiering.** Authority does not propagate upward. A state registry filing
> (Sunbiz) outranks a regulator advisory (TINA), which outranks a company's own
> page, which outranks a data aggregator. A secondary source never inherits primary
> authority, and the graph records which tier each claim rests on.

---

## 3. The investigative path

Each hop below was reproduced with a **captured, hashed** primary source — not
copied from prior notes.

```
the spam email  ──AUTHORED──▶  "David Holland"  ──EMPLOYED_BY (claimed)──▶  Fed Filing
      │                                                    │
 @fedfiling.com domain                          Sunbiz: "FED FILING, LLC" (L19000306788)
      │                                                    │
 shared GA4/GTM/Ads IDs                         registered agent: Dana Foit
      ▼                                                    │
 fedfiling.com = federalfiling.com           same registered-agent address as…
        = federalfiling.us  (one operator)              │
      │                                          Valor Media Group LLC ◀── the hub
 IMPERSONATES ▼                                  Liadan Enterprises LLC (Foit)
   SAM.gov (free)                               Jonathan Mullen (Valor manager)
```

### 3.1 The sender is a likely **burner persona**

"David Holland" appears **nowhere** outside the email itself: not on the company's
own staff listings, and breach-data lookups returned **no instance** of the
address. The precise, defensible claim is *"no captured evidence maps
david.holland@fedfiling.com to a real person"* — **not** "proven fake." The company
sends the same kind of email under several interchangeable "Account Executive"
names, which is consistent with disposable sender identities.

In the graph this shows up **structurally**: the David Holland node is a
near‑orphan — it has only an (as‑claimed) authorship edge to the email and a
**dashed, inferred** employment edge to the company. A node that the rest of the
network never corroborates is itself the finding.

*(Confidence: persona entity = UNSUPPORTED / needs‑review; the employment edge =
INFERRED, dashed.)*

### 3.2 The company, and an ownership-obscuring layer

Florida's corporate registry (Sunbiz) shows **FED FILING, LLC**, document
**L19000306788**, **ACTIVE**, organized December 2019. Its **registered agent is
Dana Foit**. Its principal address has moved over time (the email's *701 S Howard
Ave, Tampa* block to a later *4809 Ehrlich Rd, Ste 105, Tampa* on the 2026 annual
report).

The notable public-record finding: the LLC's **authorized persons are not named
individuals but two revocable trusts** (names withheld in this public version).
Holding the company through trusts rather than people is the layer that obscures
*who profits* — and it is exactly the kind of detail a "who's behind this" reader
would miss but a graph makes prominent.

*(Confidence: VERIFIED — registry‑primary.)*

### 3.3 The operators behind the persona

- **Humberto ("Gabriel") Hernandez — CEO.** Identified via the company's own blog
  (a post bylined "Gabriel" with a photo → reverse-image → Hernandez) and
  **confirmed** by the regulator advisory, in which Hernandez self-identifies as
  Federal Filing's CEO/founder. An independent public encyclopedia record provides
  a strong identity anchor confirming he is an established public figure — i.e., a
  real operator, the opposite of the David Holland persona. *(VERIFIED — journalism;
  the reverse-image hop itself is documented as draft-only and not over-claimed.)*
- **Dana Foit — registered agent / manager.** Registered agent of FED FILING, LLC,
  and **CEO + registered agent of Liadan Enterprises LLC** (Sunbiz L23000443885).
  *(VERIFIED — registry‑primary.)*
- **Adrian Gobea** appears on the company's pages as a contact and describes
  himself as co‑founder on a podcast; "co‑founder" was **not** corroborated in any
  captured record, so it stays **draft-only / inferred**. *(Downgraded — not
  published as fact.)*

**Crucially, the operator→company control link is INFERRED, not documented.** The
Sunbiz entity record names only the two trusts and the registered agent — neither
Hernandez nor Gobea appears on it. So the edges `Fed Filing OPERATED_BY Hernandez`
and `…OPERATED_BY Gobea` are drawn **dashed**: the public statements say they run
it; the corporate record does not (yet) prove the chain. Publishing that gap, as a
gap, is the honest result.

### 3.4 The network hub

The connective tissue a graph surfaces better than prose: **FED FILING, LLC's
registered agent, Valor Media Group LLC, and Liadan Enterprises LLC all share a
single registered-agent address in Tampa** (withheld here). On the **primary**
Valor Media Group LLC record (Sunbiz L25000078389), the documented officers are
**Jonathan Mullen (manager) and Dana Foit (registered agent)**.

A secondary aggregator had listed Hernandez and Gobea as Valor managers; the
**primary record does not** — so we **corrected** that claim down to
secondary‑only/unverified rather than repeat it. The documented hub is Foit + Mullen
at the shared address; the broader operator tie to Valor remains unproven. (This is
a deliberate correction of the source draft, recorded as such.)

*(Confidence: shared‑address + Valor/Liadan officers = VERIFIED registry‑primary;
the Hernandez/Gobea→Valor links = UNVERIFIED, dashed.)*

### 3.5 The scheme: impersonating a free government service

SAM.gov (the federal System for Award Management) registration is **free** — a U.S.
Department of Justice resource states plainly "there is no cost to register with
SAM.gov." Federal Filing's emails and sites mimic that process for a fee. The
regulator advisory (Truth in Advertising) states the operation "deceptively
disguises itself as SAM.gov," and quotes the CEO acknowledging "customers thinking
we are SAM." Documented pricing for the otherwise-free service: **$399 / $699 / $899
renewals and $998 for a new registration** per the advisory, with the operator's
own site showing tiers up to roughly **$2,598**.

In the graph this is two `IMPERSONATES` edges (the company and its domain → SAM.gov),
the relationship that names the harm. *(VERIFIED — gov‑primary + journalism +
the primary email.)*

### 3.6 One operator, three domains — found via shared analytics

The strongest *new* infrastructure finding came not from WHOIS but from **shared
tracking IDs**. `fedfiling.com`, `federalfiling.com`, and **`federalfiling.us`** all
embed the **same Google Analytics ID (`G‑QSMLVZP8KB`), the same Google Tag Manager
container (`GTM‑PZN28DB`), and the same Google Ads account (`189792758`)** — and
`federalfiling.us` resolves to the same AWS IP as `federalfiling.com`. Different
registrars and hosting (GoDaddy/AWS vs. Cloudflare) hid the link; the analytics
fingerprint exposes it. The `.us` domain was discovered by pivoting on the tag
container and **was not in the source draft** at all. *(VERIFIED — three
`OPERATES_DOMAIN` edges.)*

**A negative finding, kept honest:** the regulator named "USA Filing"
(`samfiling.com`) as a sibling SAM imposter. We tested it the same way and found
**no shared tracking IDs** with Fed Filing — only a registrar family in common. So
USA Filing stays **unlinked** at the analytics layer; we do **not** assert a common
operator. A method that only ever "confirms" connections is not a method.

---

## 4. What the graph added over a written report

A linear report can state these facts. The graph makes three things *fall out* of
the structure:

1. **The burner persona as topology.** "David Holland" is a near-orphan node whose
   only outward edges are claimed/inferred. The absence of corroborating edges *is*
   the signal — visible at a glance, not buried in a paragraph.
2. **The hub no single document names.** The shared registered-agent address ties
   three otherwise-separate LLCs together. No one source says "these are connected";
   the **bridge** between them is an emergent property of the typed `LOCATED_AT` /
   `REGISTERED_AGENT_OF` edges.
3. **Verified spine vs. inferred reach, at a glance.** The solid edges form a
   registry-grounded spine (who is the agent, who owns what, what impersonates
   what); the dashed edges show exactly where the documented record stops and
   inference begins. The graph refuses to let an inference masquerade as a fact.

A companion offline visualization of this graph (two linked views — a "murder
board" and an investigative timeline) lives in [`viz/`](viz/README.md). It renders
the verified spine solid and the inferred reach dashed, and every edge is clickable
back to its evidence artifact. The viz is an **operator-side** tool: it reads the
working findings + evidence manifest at runtime, so it runs against your local case
data (which, in this public repository, is kept private). See `viz/README.md` to
run it on your own corpus.

---

## 5. Ethics, limits, and what we did *not* claim

This case study is deliberately conservative:

- **No victim counts.** We say "reported complaints," never "victims." The Better
  Business Bureau Tampa profile showed the company **Not Rated** with **zero**
  complaints recorded at research time, and the regulator cited a single consumer
  complaint. There is **no verifiable aggregate**, so we publish none.
- **No conflation.** A "Federal Filing" in Knoxville, TN is a **different** legal-
  forms company, not the Tampa SAM imposter; we kept them separate.
- **Dropped, unverifiable figures.** A "$499" figure that circulated in the source
  notes appeared in **zero** captured sources, so it was dropped in favor of the
  prices we could document.
- **Minimization applied.** Operators are named only via public business records.
  Home addresses, family members, dates of birth, the trust street names, the
  shared registered-agent street address, and the trainer's private course
  materials are **excluded** from this public version and enforced by an automated
  minimization gate (`scripts/eval_gates.py minimization`).
- **Inferences stay inferences.** The operator→company control chain and the
  persona's employment are unproven and labelled so.

The full, unminimized working report and the raw captured artifacts (which contain
third‑party personal information) are kept **private** and out of this repository.

---

## 6. Reproduce it

The investigation data is committed so the method is auditable end to end:

- **Evidence manifest** — `evidence/manifest.jsonl`: every public source with its
  URL, capture time, and SHA‑256. Re-fetch a source and re-hash it to verify
  nothing changed.
- **Source list** — `sources.json`: the public URLs behind each artifact id.
- **The graph seed** — the vetted, confidence-tagged entities and edges that the
  companion knowledge graph is built from (kept with the private working notes, as
  they carry the inferential edges and operator detail).
- **The stack** — ingest your own corpus and rebuild the graph:

  ```bash
  # from the repo root, with the local pipeline configured (see SPEC.md)
  python scripts/ingest_folder.py     # capture → extract → ground → build
  python scripts/run_analysis.py      # communities, bridges, structural gaps
  python scripts/search_cli.py -q "who operates fed filing"
  ```

- **The visualization** — `examples/fedfiling-case/viz/` (offline; see its README).

---

## 7. Public sources

All sources are public records or public reporting. Captured copies are hashed in
`evidence/manifest.jsonl`.

| What it grounds | Source |
|---|---|
| The scheme; CEO self-identification; "disguises itself as SAM.gov" | Truth in Advertising — *Federal Filing government-imposter scam* (truthinadvertising.org) |
| The named sibling imposter (USA Filing / samfiling.com) | Truth in Advertising — *USA Filing government-imposter scam* |
| SAM.gov registration is free (the impersonation basis) | U.S. DOJ Office of Justice Programs — *System for Award Management* |
| Company entity, registered agent, trust authorized-persons, addresses | Florida Division of Corporations (Sunbiz) — FED FILING, LLC (L19000306788) |
| The network hub (officers, shared agent address) | Sunbiz — Valor Media Group LLC (L25000078389); Liadan Enterprises LLC (L23000443885) |
| Same-operator domains; the `.us` third domain | Direct site capture + RDAP/DNS — fedfiling.com, federalfiling.com, federalfiling.us |
| Harm context (Not Rated; reported complaints) | Better Business Bureau — Fed Filing LLC, Tampa profile |
| CEO identity anchor (established public figure) | Public encyclopedia record |

---

*Built with [investigation-graph](../../README.md) — a local, privacy-first
knowledge-graph toolkit for investigative journalists, OSINT researchers, and
anyone who needs to turn a pile of documents into a defensible, sourced network.*
