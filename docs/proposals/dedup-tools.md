# Proposal — entity-resolution / dedup tools, evaluated behind the PUB.5 seam

**Status:** research + recommendation / no code written. Decision-ready.
**Scope:** a prior agent flagged four ER/dedup tools as candidates for this OSINT
KG stack. Only Splink (loosely, in P2.4) and nomenklatura (a mention, in P2.5)
made the plan. This evaluates **all four** against our real constraints and says,
per tool, **ADOPT / CONSIDER / REJECT**, and exactly **how** each plugs in.

**The frame that decides everything:** every tool here must enter as **one tier
behind the single PUB.5 resolution-tier seam**, never as a replacement for the
hardwired semantic tier. PUB.5 (`docs/ROADMAP.md`) collapses internal dedup,
structured/probabilistic linkage, and external-authority linking into **one
ordered list of tier callables** on `resolve_or_create_semantic` — *not* two
bespoke callbacks. We are consumer-shim-first: the seam lives locally in this
repo until it generalizes to ≥2 consumers, then it's proposed upstream through
the sanitizer/export gate (never on kg-common's public `main` without the nod).

**Two ER needs that must not be conflated** (SPEC §5, ROADMAP P2.4 vs P2.6):

- **(a) INTERNAL dedup** — merge name variants *within* one corpus. The tabular
  case (P2.4). `tests/test_tabular_robustness.py::test_name_variants_are_NOT_
  merged_by_exact_fuzzy_alone` is the documented baseline: exact + fuzzy alone
  leaves `Brightpath Advisors` and `Brightpath Advisors LLC` as two orgs. This is
  the gap a probabilistic tier fills.
- **(b) EXTERNAL linking** — match a *resolved* internal entity OUT to an
  authority (OpenSanctions / Wikidata, P2.6 / G3). Libel-sensitive: a
  false-positive PEP/sanctions link is publish-stopping defamation, so it routes
  through the **P1.3 human-review gate before assertion**, not just a stored
  confidence.

**The gating constraints (read these first — they decide the verdicts):**

1. **Optional extras only.** New deps go in `[project.optional-dependencies]`;
   the core stays dependency-light. The core today is `networkx / ollama / duckdb
   / kg-common[media]` (see `pyproject.toml`).
2. **Local-first / no network by default.** OSINT privacy — the default config
   leaks nothing off the laptop (SPEC §1, §6).
3. **License matters — kg-common is about to go PUBLIC.** A copyleft (AGPL) dep
   in a publicly-shipped *library* is a real problem; permissive (MIT/BSD/Apache)
   is fine.
4. **FtM-native composes.** We already adopted `followthemoney` 4.9.2 for the G2
   crosswalk (`investigation_graph/interop/ftm.py`, `interop` extra). Tools that
   speak FtM compose with what's there.
5. **DuckDB base already exists.** `data/chunks.duckdb` holds chunks / embeddings
   / FTS (SPEC §2). A tool that runs *natively on DuckDB* is a near-zero-substrate
   add; a tool that drags in Spark/JVM is not.

**Current seam status (verified):** PUB.5 is **not yet implemented**.
`pipeline.ground_and_resolve` (`investigation_graph/pipeline.py:146`) calls
`resolve_or_create_semantic(...)` with only `embedding / threshold /
fuzzy_threshold` — no tier list. So everything below is "what to build into the
seam," and the seam itself is the first thing to land (a thin local shim).

---

## The seam each tool plugs into (the tier-callable contract)

PUB.5 adds **one** parameter to `resolve_or_create_semantic` — an ordered list of
tier callables, run *after* exact/fuzzy/embedding and *before* (or folding into)
`adjudicate_fn`. A tier sees the candidate and the batch's `ResolutionIndex` and
returns a canonical id to merge into, or `None` to fall through. Proposed shape:

```python
# A resolution tier: candidate → existing-id-to-merge-into, or None.
ResolutionTier = Callable[
    [
        str,                    # candidate label (surface form)
        str,                    # entity_type (cross-type rule still holds)
        ResolutionIndex,        # the batch universe already built this run
        Optional[list[float]],  # candidate embedding, if any
    ],
    Optional[str],              # canonical entity_id to merge into, or None
]

def resolve_or_create_semantic(
    candidate_id, name, entity_type, index, *,
    embedding=None, threshold=0.85, fuzzy_threshold=0.92,
    adjudicate_band=0.05, adjudicate_fn=None, create_fn=None,
    tiers: list[ResolutionTier] | None = None,   # ← the ONE new seam
) -> str: ...
```

Two structural points the cascade already enforces and every tier inherits:

- **Cross-type never merges** (`person` never folds into `organization`) — at
  *every* tier, including any new one.
- **Internal dedup is order-stable, single-pass, greedy** (the module's KNOWN
  LIMITATION). A probabilistic tier that scores *pairs* fits this only if it
  returns a single best canonical id per candidate; cluster-level tools (Splink,
  dedupe) therefore run as a **batch pre-pass** that produces a cluster→canonical
  map, and the tier is a cheap lookup into that map (it does not re-score live).

External linking is the *same seam, different tier*: it returns an **authority
id** as a property to attach, not an internal merge — and unconfirmed matches
stay candidate-only (P2.6 review gate). Same mechanism, asymmetric risk handling.

---

## Tool 1 — Splink (MoJ)

| | |
|---|---|
| **License** | **MIT** — fine for a public library. ✅ |
| **Repo / version** | `moj-analytical-services/splink`, **4.0.16** (Mar 2026); v5 in dev. |
| **ER need** | **INTERNAL dedup** (the probabilistic/structured tier). Not for external authority linking. |
| **Method** | Fellegi-Sunter via **EM** (unsupervised — *no labelled training data required*), with explainable match-weight waterfalls. Cite Linacre et al., IJPDS 2022, doi:10.23889/ijpds.v7i3.1794. |
| **Scale** | ~1M records/laptop/minute on DuckDB; scaled to 100M+ (MoJ Data First, US DHA) by swapping the backend to Spark/Athena — *backend is pluggable, our default stays DuckDB*. |
| **Offline on our DuckDB base?** | **Yes — natively.** DuckDB is Splink 4's default/packaged backend; other backends are opt-in `splink[spark]` etc. No network. Runs directly on the substrate we already have. |

**Verdict: ADOPT** as the **structured-linkage internal-dedup tier** behind PUB.5,
as the optional **`[dedup-structured]`** extra (`splink>=4,<5`). This is exactly
the P2.4 plan, now concrete.

**Why it's the right internal-dedup tool here:**
- It runs **on DuckDB**, the substrate we already stand up — closest thing to a
  zero-new-substrate probabilistic linker in the ecosystem.
- MIT — no public-shipping friction.
- It *closes the documented gap*: `Brightpath Advisors` vs `…Advisors LLC`,
  which exact+fuzzy provably misses (the robustness test), is the F-S
  partial-match sweet spot.
- **Explainability is a feature, not a footnote** — the match-weight waterfall is
  auditable evidence for *why* two rows merged, which is exactly the
  "auditable" promise the tool sells and what a libel-review needs.

**The honest trade-off — Splink is not zero-config, our current resolver is.**
`resolve_or_create_semantic` is config-free: import and call. Splink needs **a
model**: column comparisons, blocking rules, and an EM training pass (cheap, but
it *is* a step, and it benefits from a sane prior on `m`/`u` probabilities). The
resolution:
- Splink is a **tier you opt into for the structured/tabular path** (P2.4), where
  rows have clean typed columns to compare (name, address, date, id) and a model
  is worth training. It is **not** the default for the free-text LLM-extraction
  path, which keeps the zero-config exact→fuzzy→embedding cascade.
- Ship a **bundled default model spec** (a small JSON Splink settings file keyed
  to the tabular ontology columns) so the common case is still close to
  zero-config; advanced users override it. The EM pass runs once per batch as the
  pre-pass described above, producing the cluster→canonical map the tier reads.
- Keep it an **extra**: the core never imports Splink; only the structured tier
  does, gated like `rapidfuzz`/`ollama` (absence drops the tier, never errors).

**Integration sketch (the pre-pass + the tier lookup):**

```python
# investigation_graph/resolve/splink_tier.py  — only imported if [dedup-structured]
def build_splink_clusters(rows, settings, duckdb_con) -> dict[str, str]:
    """Batch pre-pass: train F-S via EM on the structured rows over our existing
    DuckDB connection, predict pairwise, cluster, return {row_id: canonical_id}.
    No network. Runs on data/chunks.duckdb. Returns a plain dict the tier reads."""
    import splink  # gated; absence => structured tier simply not registered
    ...

def make_splink_tier(cluster_map: dict[str, str]) -> ResolutionTier:
    def tier(name, entity_type, index, embedding):
        # cheap lookup into the precomputed cluster map; respects cross-type via
        # index (the canonical's type must match), returns id or None to fall through
        ...
    return tier
```

---

## Tool 2 — dedupe (dedupeio)

| | |
|---|---|
| **License** | **MIT** — fine for a public library. ✅ |
| **ER need** | **INTERNAL dedup**, CSV-scale, **single-analyst active-learning** flavour. |
| **Method** | Fellegi-Sunter + **active learning** (human labels the tricky pairs via CLI) + agglomerative clustering. |
| **Scale** | CSV-scale / single laptop. No DuckDB backend; pulls its own ML stack (numpy/scikit-style, affine-gap, blocking). Not a 100M-record tool. |
| **Offline on our DuckDB base?** | Offline yes; **not on DuckDB** — it operates on in-memory record dicts, a parallel substrate to the one we already have. |

**Verdict: CONSIDER** (don't adopt now). Same ER need as Splink (internal dedup),
**but Splink dominates it on our constraints**: Splink runs on the DuckDB base we
already have, scales far past CSV, and is *also* unsupervised (no labelling
loop). Adopting both means two probabilistic internal-dedup tiers doing the same
job on different substrates — needless surface on a freezing public seam.

**When dedupe would earn its place:** dedupe's *differentiator* is the **active-
learning labelling loop** — a human teaching the matcher on genuinely ambiguous
pairs. We **already have a human-in-the-loop**: the P1.3 merge-review gate
(`merges.jsonl`). The clean move, if we want learning-from-labels later, is to
**feed P1.3 accept/reject decisions back as labels** — but into **Splink's** model
(or `adjudicate_fn`), not to bolt on a second engine. So: keep dedupe as a
*reference* for the active-learning UX, revisit only if (a) we want a labelling
loop *and* (b) Splink's unsupervised EM proves insufficient on real corpora. Until
both are true, REJECT-by-deferral.

---

## Tool 3 — Zingg (zinggAI)

| | |
|---|---|
| **License** | **AGPL v3.0 — copyleft.** ❌ The trap (see below). |
| **ER need** | INTERNAL dedup / master-data-management at Spark scale. |
| **Method** | Spark + ML, ML-driven blocking comparing ~0.05–1% of pairs. |
| **Scale** | Large (Spark/Databricks/Snowflake). |
| **Offline on our DuckDB base?** | **No.** Requires a **Spark runtime** — a heavyweight JVM substrate we do not have and explicitly avoid (SPEC §6: no server deployment, local-first). It does not touch our DuckDB base. |

**Verdict: REJECT.** Two independent disqualifiers, either one sufficient:

1. **The AGPL licensing trap — call it out explicitly.** AGPL v3 is strong
   copyleft *with the network clause*: it triggers source-disclosure obligations
   not just on distribution but on **conveying the software's functionality over
   a network**. kg-common is **about to ship publicly as a library**, and this
   consumer is meant to be shareable. Taking an AGPL dependency into a tier of a
   publicly-shipping ER library risks the AGPL terms reaching across the seam to
   anything that links the library or exposes it as a service — exactly the
   ambiguity you do not want baked into a frozen public substrate. Even as an
   "optional extra," it normalizes an AGPL path through the core ER contract.
   **Permissive (MIT) Splink gives us the same internal-dedup capability with
   none of this.** There is no scenario in this stack where Zingg's marginal
   capability is worth importing AGPL into a public ER library.
2. **Substrate mismatch.** It needs Spark; we are deliberately DuckDB + single-
   investigator-local. Adopting Zingg would violate SPEC §6 (no
   server/multi-user, local-first) regardless of the license.

If a *future, different* consumer genuinely needs 100M+-record MDM at Spark
scale, the answer is **still Splink** (swap its backend to Spark — MIT,
already-modelled), not Zingg.

---

## Tool 4 — followthemoney-compare (OCCRP) + nomenklatura (OpenSanctions)

Treat these as the **FtM-native pair** — they speak the same data model our G2
crosswalk already adopted.

### nomenklatura (opensanctions)

| | |
|---|---|
| **License** | **MIT** — fine for a public library. ✅ |
| **ER need** | **Both, FtM-native** — statement-level dedup *and* the resolver/judgement substrate for external linking, with **canonical IDs**. |
| **Method** | A **Resolver**: a graph of *Judgements* (same / not-same / undecided) over entity IDs, with connected-components to pick the best ID per cluster. Depends only on FtM. |
| **Offline / DuckDB?** | Offline; FtM-native (operates on FtM statements/proxies, not our DuckDB rows directly — but our `interop/ftm.py` already produces FtM proxies, so it composes through that bridge). |

**Verdict: ADOPT** for the **external-linking path (P2.6)** as the **`[interop]` /
authority-linking tier**, FtM-native, MIT. This is the right tool to **match a
resolved entity OUT to OpenSanctions** and carry an **authority id + judgement**,
*because*:
- It is **MIT** and **FtM-native** — it composes directly with
  `investigation_graph/interop/ftm.py` (`to_ftm` gives it proxies; its canonical
  IDs come back as authority ids to attach).
- Its **Judgement model IS the P1.3 human gate, in FtM terms** — `same /
  not-same / undecided` is precisely the accept/reject/defer the libel-sensitive
  external-link review needs. We don't bolt a review UX onto a stored confidence;
  we reuse nomenklatura's resolver as the decision ledger, surfaced through P1.3.
- **No-match → leave unlinked** falls out naturally (undecided judgement, never
  asserted). Unconfirmed matches stay candidate-only.

**Caveat to honour at implementation:** P2.6's licensing note —
**OpenSanctions data is free for journalism but commercial use needs a license +
attribution**; nomenklatura the *code* is MIT, the *data* is the gated bit. Log
current terms at implementation. (Wikidata = CC0, opt-in/online/non-sensitive.)

### followthemoney-compare

| | |
|---|---|
| **License** | **MIT** — fine. ✅ |
| **Version / maint.** | 0.4.3; small repo, low activity. Core deps light (numpy/pandas/ftm/fuzzywuzzy/mmh3); the **model-training deps (pymc3, scikit-learn) are a `[dev]` extra**. |
| **ER need** | The **scoring model inside Aleph XREF** — count-min-sketch TF-IDF token weighting + a logistic/Bayesian (GLM Bernoulli via pymc3 MCMC) pair-scorer. |
| **Method** | Trains on **accept/reject profile decisions exported from an Aleph instance.** |
| **Offline / DuckDB?** | Offline; FtM-native; **not on our DuckDB base** (operates on FtM proxies + its own sketch structures). |

**Verdict: CONSIDER, lean REJECT-for-now.** It's MIT and FtM-native (good), but:
- Its **training signal is Aleph XREF profile decisions** — we don't run Aleph,
  so we'd be adopting a model with **no native source of training labels**. Our
  label source is P1.3, whose decisions are *not* in Aleph's profile format.
- It **overlaps both adopted tools**: as a *pair-scorer* it competes with Splink
  (internal) and as an *FtM matcher* it competes with nomenklatura's resolver
  (external) — without dominating either on our constraints.
- **Version-compat risk:** `followthemoney-compare` 0.4.3 pins older FtM; our
  crosswalk is verified against **4.9.2** (`FTM_VERSION_VERIFIED`). Pulling it in
  risks an FtM version pull-back across the `interop` extra. Verify before any
  adoption.
- It also carries the **`pymc3` weight** (a heavy MCMC/Theano-lineage stack) for
  the model-fit path — against the dependency-light grain even as an extra.

So: **not now.** It becomes interesting only if we later want a *learned FtM
pair-scorer* and can feed it labels — at which point compare its value against
just training Splink. Keep as a documented option, don't wire it.

---

## SYNTHESIS — the recommended ER architecture

**One seam (PUB.5), three substrate-aligned tiers, two ER needs cleanly split:**

```
                 resolve_or_create_semantic(... , tiers=[...])   ← the ONE seam
                 │
  exact ─→ fuzzy ─→ embedding ─→ [TIER LIST] ─→ adjudicate_fn ─→ create
 (always)(rapidfuzz)(cosine)        │              (LLM, ambiguous band)
                                    │
        ┌───────────────────────────┴───────────────────────────┐
        │ INTERNAL dedup tier                EXTERNAL linking tier │
        │ ── Splink (MIT) ──                 ── nomenklatura (MIT) │
        │ F-S/EM on the DuckDB base          FtM resolver / judgements
        │ extra: [dedup-structured]          extra: [interop] (+OpenSanctions
        │ used on the P2.4 structured path     data, gated license)
        │ cluster pre-pass → map lookup      authority-id attach, NOT a merge
        │ returns internal canonical id      → P1.3 gate BEFORE assertion
        └────────────────────────────────────────────────────────┘
```

- **Internal dedup → Splink.** MIT; runs natively on our existing DuckDB base;
  unsupervised EM (no labelling loop); explainable match weights; closes the
  documented exact+fuzzy gap. Optional extra `[dedup-structured]`, used on the
  structured/tabular path, not the zero-config free-text path.
- **External linking → nomenklatura.** MIT; FtM-native (composes with
  `interop/ftm.py`); its Judgement model *is* the P1.3 human gate in FtM terms;
  authority id attached only on human-confirmed match, unmatched left alone.
  Optional extra (folds into `[interop]`); OpenSanctions *data* license logged at
  implementation.
- **dedupe → CONSIDER/defer.** Redundant with Splink on our constraints; its only
  edge (active learning) is better served by feeding P1.3 labels into Splink.
- **followthemoney-compare → CONSIDER/defer.** MIT + FtM-native but no native
  label source (needs Aleph), overlaps both adopted tools, FtM-version + pymc3
  weight. Revisit only as a learned FtM pair-scorer with a label pipeline.
- **Zingg → REJECT.** AGPL copyleft into a public ER library (the trap) **and**
  Spark substrate we don't run. Splink covers the capability at MIT.

**Everything is consumer-shim-first.** Land the PUB.5 `tiers=` seam locally in
this repo (a thin `investigation_graph/resolve/` shim wrapping
`resolve_or_create_semantic`), wire Splink and nomenklatura as tiers there, prove
it against the sme-eval grader (precision/recall — *measurement is the DoD, not
"tests pass"*, ROADMAP cross-cutting note), and only then propose the seam
upstream to kg-common through the sanitizer/export gate once it has ≥2 consumers.

### The AGPL/Zingg trap, restated for the record

kg-common ships **publicly as a library**. AGPL v3's network-use clause makes it
hazardous to route an ER *contract* through an AGPL dependency, because the
copyleft can reach across the library boundary to consumers — even if the dep is
"optional." Every capability Zingg offers, MIT-licensed Splink offers on a
substrate we already run. **Do not import AGPL into the public ER seam.** This is
the one licensing landmine in the set; the other three tools are all MIT.

### What needs the user's decision

1. **OpenSanctions data licensing** (P2.6) — code is MIT, the *data* is "free for
   journalism, license + attribution for commercial." This tool ships publicly →
   confirm intended use and log current terms before wiring nomenklatura's
   authority matching. (Wikidata stays CC0/opt-in.)
2. **Splink default model spec** — adopting Splink trades our zero-config resolver
   for a (small, bundled) F-S model on the structured path. Confirm we're happy
   shipping a default Splink settings file for the tabular ontology columns so the
   common case stays near-zero-config, with advanced override.
3. **Order of work** — recommend landing the **PUB.5 `tiers=` seam (local shim)
   first**, then Splink (P2.4 internal), then nomenklatura (P2.6 external, which
   already depends on P2.5 FtM ingestion). P2.6 is the libel-sensitive one and
   needs the P1.3-gate wiring before any external match is asserted.

---

## Sources

- Splink — github.com/moj-analytical-services/splink (MIT, v4.0.16, DuckDB
  default backend); Linacre et al., IJPDS 2022, doi:10.23889/ijpds.v7i3.1794.
- dedupe — github.com/dedupeio/dedupe, pypi.org/project/dedupe (MIT, active
  learning + agglomerative clustering).
- Zingg — github.com/zinggAI/zingg (AGPL v3.0, Spark runtime).
- followthemoney-compare — github.com/alephdata/followthemoney-compare (MIT,
  count-min-sketch TF-IDF + pymc3 GLM, trains on Aleph XREF decisions).
- nomenklatura — github.com/opensanctions/nomenklatura (MIT, FtM Resolver /
  Judgements / connected-components canonical IDs).
- OpenSanctions deduplication writeup — opensanctions.org/articles/2021-11-11-deduplication/.
