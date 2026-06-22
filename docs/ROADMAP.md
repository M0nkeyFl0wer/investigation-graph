# Roadmap — fixes from the OSINT + LadybugDB critiques

Scoped TODO for every issue surfaced in the investigator-lens and
LadybugDB-lead-dev critiques (2026-06-19). Priority: **P0** = correctness
investigators can be misled by; **P1** = quality/scale/safety; **P2** = larger
capability (visual ingestion, incrementality, UX). Each item names the relevant
skill to consult before coding.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

**Done (2026-06-19/20):** P0.1 (per-chunk extraction), P0.2 (edge evidence), P0.3
(OCR), P1.1 (ER embedding tier), P1.2 (whole-word grounding), P1.3 (merge review),
P1.4 (`find_path` id-anchored + explicit limit), P1.5 (WAL/sidecar cleanup),
P1.6 (pin `real_ladybug==0.15.3`), P1.8 (path scores labeled model-estimated),
**P2.1 scaffold** (`media/` processor interface + DocumentProcessor). Plus: LLM
circuit breaker; **a real re-ingest crash fixed** (single-file graph); the §4
**corruption-claim correction** (SPEC §2.1). 24/24 tests.
**Next:** P1.7 (incremental — optional, revisit at scale), **P2.1 implementation**
(ColQwen visual retrieval + VLM — needs GPU/controlled compute + the kg-common
promotion decision).

---

## P0 — correctness (silently misleading today)

### P0.1 — Relationship extraction reads only the first 4,000 chars  ⭐ biggest
- **Problem:** `extract.py:161` feeds `text[:4000]` to the LLM, so relationships
  on page 2+ of any real document never appear. Looks processed; isn't.
- **Fix:** extract **per chunk**, not per truncated document. Loop the same
  chunks we already embed (1000/200), run LLM extraction on each, union results.
  This *also* fixes P0.2 (each entity/edge then carries its real source chunk →
  true provenance + tighter grounding). Cap total LLM calls per doc for runaway
  safety; log when a doc is large.
- **Skill:** `kg-ingestion` (chunk-provenance contract, one-model hygiene).
- **Where:** `investigation_graph/extract.py`, `scripts/ingest_folder.py`.

### P0.2 — Edges carry no evidence quote
- **Problem:** LLM edges are built without an `evidence` field (`extract.py`
  ~195-204); the graph's `evidence` column is empty, breaking the "auditable"
  promise. Grounding co-occurrence can't see the justifying sentence either.
- **Fix:** have the extraction prompt return a short `evidence` span per edge;
  store it on the edge. With P0.1 (per-chunk), attribute the edge to its chunk id
  so grounding checks the *real* span, not whole-doc containment.
- **Skill:** `kg-ingestion` (evidence-bearing edges), `taxonomy-validation`.
- **Where:** `extract.py`, `pipeline.py` (pass evidence through), `graph.py`.

### P0.3 — No OCR / scanned-doc + image support
- **Problem:** `pdftotext` yields nothing on scanned PDFs/photos/screenshots —
  most of a real OSINT corpus. No image ingestion at all.
- **Fix (first cut):** OCR fallback when `pdftotext` returns ~empty
  (`ocrmypdf`/Tesseract; Surya for layout). Detect image files and route them.
  Full visual understanding is the P2 epic (see `proposals/visual-ingestion.md`).
- **Skill:** `kg-ingestion`.
- **Where:** `scripts/ingest_folder.py` `read_document`, new `media` path.

---

## P1 — quality, scale, safety

### P1.1 — Entity resolution has no semantic tier wired in
- **Problem:** `pipeline.ground_and_resolve` calls `resolve_or_create_semantic`
  with exact+fuzzy only (no embeddings passed), so aliases that aren't
  fuzzy-close don't merge. `config.DEDUP_THRESHOLD` is defined but unused.
- **Fix:** pass per-entity embeddings (cheap — embed `label: description`) so the
  cosine tier engages; wire `DEDUP_THRESHOLD` to the resolver `threshold`.
- **Skill:** `kg-ingestion` (entity resolution), kg-common `write/dedup`.

### P1.2 — Grounding is whole-text substring containment
- **Problem:** short/common labels ("City", "the Authority") ground + co-occur
  spuriously. (Largely mitigated by P0.1 per-chunk attribution.)
- **Fix:** require min label length / token overlap, not bare substring; prefer
  the chunk the entity was *extracted from* (P0.1) over any-chunk containment.
- **Skill:** `kg-ingestion`.

### P1.3 — No merge review / human-in-the-loop  (libel vector)
- **Problem:** ER auto-merges with no review/split; a wrong merge fuses two real
  people. Confidence isn't surfaced at merge time.
- **Fix:** emit a `merges.jsonl` review artifact (what merged, score, evidence);
  a `--review-merges` mode that lists/【un]confirms; never auto-merge below a high
  threshold without recording it. Surface merge count + low-confidence merges in
  the ingest report.
- **Skill:** `kg-ingestion`, kg-common `pipeline/review_gate`.

### P1.4 — `find_path` scale + silent truncation  (LadybugDB lens)
- **Problem:** `WHERE a.label CONTAINS $src` = O(n) label scan (no index);
  `RELATES_TO*1..4` over a single denormalized REL table scans every hop;
  `LIMIT 5` truncates silently.
- **Fix:** add a label lookup index/structure; resolve endpoints to ids first,
  then path between ids; make the limit explicit + report when truncated. Revisit
  per-type REL tables (needs kg-common ABC change — see PUB.2).
- **Skill:** `ladybug` (schema/index, Cypher), `kg-debug` (traversal).

### P1.5 — WAL-quarantine on graph open  (LadybugDB lens)
- **Problem:** a killed builder leaves a poisoned `.wal` that SEGVs every
  subsequent open on this build. Non-experts will Ctrl-C a slow ingest.
- **Fix:** wrap `Graph` open in a WAL preflight/quarantine (pidfile marker; if
  marker+`.wal` present on open, move the WAL aside). kg-common has the pattern.
- **Skill:** `ladybug` (crash recovery), `ladybug-surgery` (safe mutation).

### P1.6 — Pin `real_ladybug` to the validated version
- **Problem:** `>=0.15.0` floats across builds with *different* corruption
  surfaces (repro was 0.17.1). 
- **Fix:** pin to the exact version reconstruct-and-swap was validated against;
  document why. **Skill:** `ladybug`.

### P1.7 — Full graph rebuild every ingest = O(corpus)  (LadybugDB lens)
- **Problem:** re-ingesting one doc re-writes the whole corpus. The rebuild is a
  *conservative choice*, not a corruption necessity — the "incremental writes
  corrupt" claim was **disproven standalone on 2026-06-19** (30 trials, 0
  collateral; see SPEC §2.1). So incremental edge writes are *likely safe*.
- **Fix (later, only if scale demands):** `build_graph` diffs DuckDB records vs
  the graph and writes incrementally instead of rebuilding — **but first**
  re-measure corruption with exact per-edge intended-state tracking on a copy
  (the discipline that caught the original mis-measurement). **Skill:**
  `ladybug-surgery`, verification.md §4.

### P1.8 — Path "confidence" is false precision
- **Problem:** product of 3B-model edge confidences presented as a score.
- **Fix:** label it "uncertainty (model-estimated)", or derive from corroboration
  (independent paths / multiple source docs) rather than raw LLM confidence.

---

## P2 — capability

### P2.1 — Visual ingestion subsystem  ⭐ (OSINT is visual)
- See **[`docs/proposals/visual-ingestion.md`](proposals/visual-ingestion.md)** —
  Docling (digital) → OCR (scanned) → ColQwen/ColPali visual retrieval
  (visually-rich, region-grounded) → VLM captioning (photos), behind a `media/`
  processor interface in **kg-common**, with an optional controlled GPU backend
  (bigger local card, a self-hosted GPU box, or a privacy-respecting GPU VPS).
- **Skill:** `kg-ingestion`, `duckdb-rag` (multi-vector store).

### P2.2 — Timeline / temporal view
- Schema has bi-temporal edges but no user-facing "what did we know on date X" /
  timeline output. Add a temporal query + briefing section.

### P2.3 — Guided wizard (WS3)
- The scope→ingest→extract→ground→use harness as a guided CLI wizard (spec-kit
  pattern), then optional desktop wrapper.

### P2.4 — Structured / tabular ingestion  ⭐ (interop brief G1, do first)
- **Problem:** the highest-value OSINT data (flight logs, ledgers, registries,
  sanctions lists) is tabular. Today everything is forced through
  chunk→embed→LLM-extract — but a table row already *is* a typed edge and must
  never touch an LLM (cost, hallucination, and it's deterministic).
- **Fix:** a tabular processor in the **same shape as `kg_common.media`**
  (`BaseProcessor.accepts/process → ProcessorResult{text,structured,metadata}`,
  registered via `register_processor(..., first=True)`) for `.csv/.tsv/.xlsx`.
  Column→ontology mapping is driven by a small **per-file YAML mapping spec**
  (which columns are entities, which pair forms an edge, which are dates/amounts).
  The processor emits deterministic **entities/edges via the artifact contract**
  (`extraction_source="deterministic"`, real `source_url` = file + row anchor),
  appended into the ingest stage so they flow through **ground → resolve →
  grade-locality unchanged** — verified path: a new `processors/` module feeds the
  same entity/edge lists `extract.py` builds, then `ground_and_resolve` +
  `build_graph`. **No LLM call on the structured path.** Structured ER routes
  through the existing `resolve_or_create_semantic`; evaluate **Splink** (MIT,
  Fellegi-Sunter) on the **DuckDB base we already have** as a probabilistic
  linkage tier *behind the resolver interface* (→ PUB.5, the single resolver-tier
  seam), an optional `[dedup-structured]` extra — it does **not** replace the
  semantic tier.
- **Amounts carry currency (review):** a money column must capture **currency** (and
  ideally an FX-normalized value), not a bare number — otherwise P2.8 flow is
  meaningless across currencies. The `add_edge` properties dict already exists, so
  the mechanism is there; the YAML spec marks a column as `amount` **with a currency
  column or literal**. Dates normalized to ISO-8601.
- **Done when (measured):** a flight-log/ledger-style CSV produces typed edges with
  zero LLM calls, provenance intact — **and** a before/after on the sme-eval grader
  shows the deterministic path beats LLM-extraction on the same table (precision on
  the typed edges), not just "tests pass."
- **Tools:** stdlib `csv`; `pandas` (existing dep); `openpyxl` xlsx = **optional
  extra**. `splink` = optional extra.
- **Skill:** `kg-ingestion`, `duckdb-rag`.
- **Where:** new `investigation_graph/processors/tabular.py` + a YAML-spec loader,
  `scripts/ingest_folder.py`, `investigation_graph/pipeline.py`.

### P2.5 — FollowTheMoney / BODS interop crosswalk  (interop brief G2)
- **Problem:** our ontology is ~90% a renamed FtM. With no crosswalk we can't
  ingest **OpenSanctions** (FtM-native) or **Open Ownership** (BODS) as ready-made
  corpora, nor export to the journalist ecosystem (Aleph) — the highest-leverage
  interop piece, and the authority G3 needs.
- **Fix:** a concrete `to_ftm` / `from_ftm` mapping in *this repo's* `Ontology`
  subclass, behind a local adapter, against the **PUB.6** ABC hook (land the hook
  even if we supply the concrete mapping — the ABC is freezing pre-public).
  **Verify the crosswalk against the current `followthemoney` schema before
  finalizing — FtM evolves.** Round-trip a bundled sample (this repo → FtM JSON →
  back) with no loss on mappable types; import an OpenSanctions sample via
  `from_ftm`. The no-equivalent rows (`claim`, `CONTRADICTS`/`SUPPORTS`/
  `ASSOCIATED_WITH`, `ATTENDED`) are documented as an explicit boundary — **do not
  force-fit** them.
- **Preserve statement-level provenance (review):** `from_ftm` must keep FtM's
  per-statement provenance (each property/edge carries its own source dataset +
  collection), **not flatten an OpenSanctions import to one `source_url`** — the
  granular provenance is exactly the auditability this tool sells.
- **Tools:** `followthemoney` (OCCRP, MIT); `nomenklatura` for FtM-native statement
  dedup if useful. Both **optional extras**.
- **Skill:** `taxonomy-validation`.
- **Where:** new `investigation_graph/interop/ftm.py`, `investigation_graph/ontology.py`
  (subclass methods), a bundled sample corpus, tests. (Substrate hook = PUB.6.)

### P2.6 — External entity linking (distinct from internal dedup)  (interop brief G3)
- **Problem:** we resolve duplicates *within* a corpus but never link an entity
  *out* to an authority — the disambiguation + enrichment step, and the real guard
  for the "is this the same John Smith?" libel risk our own ethics section names.
- **Fix:** match resolved entities to an authority — **OpenSanctions** (FtM,
  offline snapshot = local-first default) and optionally **Wikidata** (online =
  opt-in, non-sensitive). On match, attach an authority id + confidence; **on no
  match, leave unlinked** (never invent one). Extends the kg-common ER primitives
  via the single resolution-tier seam (→ PUB.5), using **nomenklatura** (MIT,
  FtM-native — composes with `interop/ftm.py`; its `same/not-same/undecided`
  Judgement model is the P1.3 gate in FtM terms); consumer shim first. Offline path
  works with no network. (Tool eval: `docs/proposals/dedup-tools.md`.)
- **ASYMMETRIC RISK — harden before output (review):** a false-positive link to an
  OpenSanctions/PEP record is **publish-stopping defamation**, so "attach id +
  confidence, leave unmatched alone" is necessary but **not sufficient**. Require a
  **high match threshold AND human confirmation before any external match is
  *asserted* in output** — route candidate matches through the **P1.3 merge-review
  gate** (same human-in-the-loop the libel vector already uses), not just a stored
  confidence. Unconfirmed matches stay candidate-only, never surfaced as fact.
- **Licensing:** **OpenSanctions is free for journalism but commercial use needs a
  license + attribution** — log the current terms (verify at implementation) since
  this tool ships publicly. Wikidata = CC0.
- **Done when (measured, not just green):** before/after **precision/recall** of the
  linker on a labelled sample via the sme-eval grader — not "tests pass." A wrong
  link here is a libel event, so the bar is measured precision, with the human gate
  on assertion.
- **Skill:** `kg-ingestion`.
- **Where:** new `investigation_graph/interop/linking.py` (shim over the resolver),
  tests + an eval harness. Depends on P2.5 for the OpenSanctions/FtM ingestion path.

### P2.7 — Edge inference / logical closure  (interop brief G4)
- **Problem:** topology *detects missing* edges; nothing *derives implied* ones.
  Deterministic transitive closure over `OWNS`/`FUNDED_BY` reconstructs
  beneficial-ownership chains through shells; inverse closure is free.
- **Fix:** deterministic transitive + inverse closure in **networkx** (existing
  dep) over a **directed** projection (note: `topology.py:build_networkx_graph`
  returns an *undirected* `nx.Graph`, and `kg_common.measure.to_networkx` returns
  an `nx.MultiDiGraph` — use/derive a directed view). Tag every derived edge
  `provenance="inferred"` with the source chain as `evidence`; **never present
  inferred edges as extracted**; exclude them from extracted-only views/queries.
  **PSL is out of scope** (heavy/JVM, against the deterministic grain) — opt-in
  future only.
- **DON'T MANUFACTURE FALSE CONTROL (review — this is the dangerous gap):** naive
  transitive closure over `OWNS` invents control — *A owns 5% of B, B owns 5% of C*
  does **not** make A control C. Beneficial ownership is **multiplicative ownership
  percentages with a threshold** (~25% in UK PSC / EU AMLD regimes — make it
  **configurable**; BODS, which P2.5 brings in, already encodes interest levels, so
  prefer real percentages over edge-existence). The inferencer MUST: (a) chain only
  **type-compatible** edges (`OWNS∘OWNS`, never `OWNS∘EMPLOYED_BY`); (b) carry
  **per-hop confidence decay**; (c) **cap depth**; (d) route an inferred *control*
  edge through the **P1.3 merge-review gate**, not merely tag it — a tag keeps it
  out of extracted views but does **not** stop a false control claim reaching a
  draft.
- **Done when (measured):** before/after precision/recall of inferred control edges
  against a labelled ownership sample (sme-eval), plus a known-shell test where a
  sub-threshold chain produces **no** control edge.
- **Skill:** `kg-ingestion` (+ `networkx`).
- **Where:** new `investigation_graph/infer.py` (or a `kg_common.measure` submodule
  — PUB candidate if it generalizes), `queries.py` (an extracted-only filter), the
  P1.3 review path, tests.

### P2.8 — Money-flow tracing  (interop brief G5)
- **Problem:** we have betweenness/communities but no **amount-weighted flow** over
  transaction edges (funds in → shell chain → out). The ontology is built for it
  (`PAID_TO` = "follow the money").
- **Fix:** amount-weighted path / max-flow over `transaction` + `PAID_TO` /
  `FUNDED_BY` edges using **networkx** (existing dep). Expose a "trace funds from X"
  query in `queries.py` returning ordered chains with amounts + source edges.
  **Schema gap (logged in DEVIATIONS):** edges carry no `amount` field today —
  carry the amount **with its currency** as an edge property fed by P2.4
  tabular-ledger ingestion (and/or via the `transaction` entity). Flow over mixed
  currencies is meaningless without **FX normalization** — normalize to a base
  currency (or refuse to sum across currencies and report per-currency chains).
  Depends on P2.4 for amount-bearing edges.
- **Done when (measured):** the trace returns ordered fund chains with amounts +
  source edges on a known multi-hop ledger fixture, and does **not** silently sum
  across currencies.
- **Skill:** `networkx`.
- **Where:** `investigation_graph/topology.py` (a directed amount-weighted
  projection) or a `kg_common.measure` flow helper, `queries.py`, tests.

---

## PUB — kg-common (public substrate) updates to suggest/upstream

These belong in the shared library, not just this consumer (per `BOUNDARY.md`):

- **PUB.1 — `kg_common/media`** processor subsystem (`BaseProcessor` →
  `ProcessorResult{text, structured, metadata}`; Docling/OCR/visual processors).
  Greenfield (the seabrick handoff proposed it; not built). The visual epic
  (P2.1) should land here so every consumer benefits.
- **PUB.2 — typed REL tables option** in the Ontology ABC, so consumers can opt
  out of the single-`RELATES_TO`+`edge_type`-property anti-idiom (enables P1.4
  performance + reduces the blast radius the corruption guard must cover).
- **PUB.3 — relax the `add_edge` corruption guard** — the 2026-06-19 standalone
  repro falsified the "incremental REL write corrupts" claim (kg-common's own
  conclusion: keep as conservative defense, not a real bug). If re-measurement
  on real consumers confirms safety, the guard could become opt-in rather than
  default-refuse, unblocking P1.7 incremental writes across consumers.
- **PUB.4 — edge `evidence` as a first-class, validated field** in the writer
  (supports P0.2 across consumers).
- **PUB.5 — ONE general "resolution-tier" extension point on
  `write.dedup.resolve_or_create_semantic`.** Internal dedup, structured/
  probabilistic linkage, and external-authority linking are **all tiers in one
  cascade** — so add a *single* general tier seam (`tiers=` ordered list of tier
  callables, mirroring `adjudicate_fn`), **not** two bespoke callbacks. The resolver
  has no plugin point today; two one-off params on a freezing public API is two
  things to regret. Consumer-shim first; upstream once it generalizes to ≥2
  consumers. *(Collapsed from two PUB entries per review: one seam, not two.)*
  **Tool decisions (eval in `docs/proposals/dedup-tools.md`, 2026-06-22):**
  - **Internal-dedup tier → Splink** (MIT; UK MoJ). Runs natively on our DuckDB
    base, unsupervised (Fellegi-Sunter EM, no labelling loop), explainable. Optional
    `[dedup-structured]` extra, scoped to the **structured path (P2.4)** with a
    bundled default F-S spec — NOT the free-text cascade (it needs column
    comparisons + an EM pass, so it isn't zero-config like today's resolver).
  - **External-authority tier → nomenklatura** (MIT; OpenSanctions, FtM-native).
    Composes with the `interop/ftm.py` crosswalk; its `same/not-same/undecided`
    Judgement model *is* the P1.3 gate in FtM terms. Folds into `[interop]`, for
    **P2.6**.
  - **Zingg — REJECTED** (AGPL v3.0 copyleft into a publicly-shipping ER library +
    needs Spark, a substrate we avoid; Splink covers it at MIT).
  - **dedupe / followthemoney-compare — deferred** (MIT but redundant / no native
    label source / pins older FtM).
- **PUB.6 — FtM crosswalk hook on the `Ontology` ABC** — add `to_ftm()` /
  `from_ftm()` (or a SKOS-mapping slot) as ABC methods with `NotImplementedError`
  defaults, so every investigative consumer shares the FollowTheMoney/BODS
  contract. The ABC is freezing pre-public, so land the **hook** even though this
  repo (P2.5) supplies the concrete mapping. (The ABC is currently unversioned —
  note the compat surface.)
- Public-export note: any new `media` extras (docling, ocrmypdf, colpali-engine)
  must be **optional dependencies** so the dependency-light core stays light, and
  run through the sanitizer/export gate.

---

## Sequencing

1. **P0.1 + P0.2 together** (per-chunk extraction with evidence) — one change,
   biggest correctness win, also tightens grounding.
2. **P0.3** OCR fallback (unblocks scanned docs now; visual epic later).
3. **P1.1–P1.3** (ER semantic tier, grounding tighten, merge review).
4. **P1.4–P1.6** (LadybugDB hardening: find_path, WAL, pin).
5. **P2.1** visual subsystem (its own design doc + likely a kg-common epic).
6. **P1.7 / P1.8 / P2.2 / P2.3** as capacity allows.
7. **Interop & analysis brief (P2.4→P2.8, in order):** P2.4 structured ingestion
   first (it feeds the amount-bearing edges P2.8 needs and is self-contained) →
   P2.5 FtM crosswalk (authority for P2.6) → P2.6 external linking → P2.7 edge
   inference → P2.8 money-flow.
   **Status 2026-06-22 (branch `feat/interop-analysis-gaps`):** ✅ P2.4 (tabular
   ingestion), ✅ P2.7 (ownership-control inference), ✅ P2.8 (money-flow) — each
   done + graph-native + eval'd (`scripts/eval_tabular.py` / `eval_inference.py` /
   `eval_flow.py`, all P=R=1.00). A critical silent-drop of typed edge props was
   found + fixed (amount/currency/share_pct now first-class columns). ⏳ P2.5 (FtM)
   + P2.6 (external linking) remain — they need the user's nod (PUB.6 Ontology-ABC
   hook) and external-data licensing review (OpenSanctions). Substrate hooks PUB.5/PUB.6/PUB.7 are implemented
   **consumer-side first** behind a thin local interface, then proposed upstream in
   a **kg-common worktree** through the sanitizer/export gate — never on
   kg-common's public `main`, and not without the user's nod.

Commit in small chunks; comment all code; consult the named skill before each.

New deps from the interop brief (`openpyxl`, `followthemoney`, `nomenklatura`,
`splink`) are **optional extras only** — the required core stays dependency-light.
Every new node/edge carries `source_url` + `extraction_source`; inferred edges are
tagged `provenance="inferred"` and never shown as extracted; nothing bypasses
grounding / grade-locality / ER. See `DEVIATIONS.md` for brief-vs-repo deltas.

**Measurement is the definition of done, not "tests pass" (cross-cutting, per
review).** "Round-trips / green tests" proves it *runs*, not that it *helps* — and
this consumer's whole differentiator is the build-vs-grade split kg-common ships on.
So every interop entry's DoD includes a **before/after on the `sme-eval` grader**
(LadybugDB adapter consumes these graphs): precision/recall, not just pytest —
**especially P2.6 (external linking) and P2.7 (control inference), where being wrong
is a libel event, not a flaky test.** The human-review gate (P1.3) is on *assertion*
for both.
