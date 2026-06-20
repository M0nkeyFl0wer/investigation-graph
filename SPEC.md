# SPEC — Investigation Knowledge Graph (investigation-graph)

> A guided, local, hybrid-graph toolkit for an investigator or researcher who
> **could not stand one up themselves**. Manual document ingestion, a
> DuckDB + LadybugDB hybrid graph, and safety machinery (entity resolution,
> grounding, grade-locality) baked into the core — because "accessible" plus
> libel risk means correctness cannot live behind an optional flag.

Status: **in active build** (see `TODO.md` for the live checklist).
Repo: `github.com/M0nkeyFl0wer/investigation-graph` (branch `main`).

---

## 1. What we are building

A local-first pipeline that takes documents an investigator already has
(court filings, corporate records, leaked material, public records), builds a
typed, source-traceable knowledge graph, and surfaces **what is missing** —
structural gaps that become investigative leads. It runs entirely on the
user's machine in the default configuration; no data leaves the laptop.

The product is shaped as a **stage harness** the user is walked through:

```
scope → ingest → extract → ground → use
```

| Stage | What happens | Owner of correctness |
|-------|--------------|----------------------|
| **scope**   | Confirm/adapt the ontology for the beat; pick the corpus directory; set privacy mode. | Ontology (typed, graded) |
| **ingest**  | Read manual documents → chunk → embed → write to the **DuckDB** chunk store; register documents in the graph. | One artifact contract |
| **extract** | Three-phase extraction (deterministic → spaCy NER → local LLM) emits candidate entities and edges **as artifact-contract records**. | Provider pool |
| **ground**  | Entity resolution (dedup), grounding gate (evidence must appear in source), grade-locality validation. Only survivors are written. | ER + grounding + grade-locality |
| **use**     | Hybrid search, typed-path search, topology/gap analysis, daily briefing. | Retrieval + measure |

The wizard that *drives* the user through these stages is a **later step**
(WS3), modelled on the spec-kit-assistant harness. The core ships first as
clean, well-commented CLI steps that the wizard will later orchestrate.

---

## 2. Architecture — the hybrid

**Always a hybrid graph. No substrate choice is exposed to the user.**

```
            documents (manual)
                  │
                  ▼
        ┌───────────────────────┐
        │  DuckDB  (the base)   │   data/chunks.duckdb
        │  chunks + embeddings  │   • FLOAT[dim] fixed-width vectors (HNSW-able)
        │  + BM25 FTS           │   • BM25 via fts extension, rebuilt per batch
        │  SOURCE OF TRUTH for  │   • HNSW built in-memory at boot (persistent
        │  text & retrieval     │     HNSW is experimental — avoid on disk)
        └───────────┬───────────┘   • hybrid retrieval = BM25 + ANN + RRF
                    │ entity_ids / doc_ids link rows ↔ nodes
                    ▼
        ┌───────────────────────┐
        │ LadybugDB (the graph) │   data/graph.lbug
        │ entities, typed edges │   • bulk-loaded via Parquet COPY
        │ MENTIONED_IN, CHUNK_OF│   • edge writes go through kg-common
        │ THE RELATIONSHIPS     │     GraphWriter (corruption-guarded)
        └───────────────────────┘
```

- **DuckDB is the source of truth** for chunk text, embeddings, and full-text
  search; LadybugDB holds the entity/edge graph. The reference implementation
  of this exact pattern is `second-brain-hybrid-graph/second_brain/chunk_store.py`
  (two-handle RRF: read-only persistent handle for BM25, in-memory handle for
  HNSW; DELETE+INSERT for re-embed because HNSW blocks UPDATE; deterministic
  UUID5 chunk ids; Parquet COPY for bulk load). We follow it.
- **Parquet is the bulk-load transport** into both substrates (DuckDB
  `read_parquet`, LadybugDB `COPY FROM`). It is not a user-facing concept.
- **Embedding model is single and fixed per graph** (default
  `nomic-embed-text`, 768-d). Mixing models corrupts retrieval — see the
  `kg-ingestion` skill. Dimension is parameterized, never hardcoded in DDL.

### 2.1 The graph is a rebuilt projection, not an incremental store

> **Correction (2026-06-19).** An earlier version of this section asserted, as
> established fact, that *any* incremental edge write into a populated
> `RELATES_TO` table corrupts unrelated rows. **That claim is not substantiated.**
> A standalone, single-process, exact-per-edge-intended-state repro on pristine
> DBs (ladybug 0.17.1) ran **30 trials across 6 mechanisms — including the exact
> `MERGE … ON MATCH SET` op — with zero collateral corruption**
> (`kg-common/docs/issue-drafts/2026-06-19-ladybug-incremental-rel-write-corruption/`).
> The original 2026-06-16 report was **most likely a mis-measured dedup-merge
> effect** (a legitimate edge re-point read as corruption). It is **not a fileable
> engine bug**, and incremental edge writes are *probably* safe.

So why does this project still rebuild the graph rather than mutate it? **As cheap,
conservative defense** — which is exactly what kg-common's own post-mortem
concluded (keep the `add_edge` guard + reconstruct-and-swap). A production anomaly
*was* observed once; the cause is unconfirmed (one un-ruled-out hypothesis is
HNSW/FTS indexes on the graph — which this project deliberately does *not* put on
the graph). The rebuild costs us nothing at single-investigator scale and removes
a class of risk we can't yet fully characterize. It is a **choice, not a forced
necessity.**

The design, then:

- **DuckDB is the source of truth for entities and edges too**, not just chunks.
  Extraction + grounding write the surviving `entity`/`edge` records to DuckDB.
- **The LadybugDB graph is a disposable materialized view**, rebuilt from the
  DuckDB record set on each build: fresh graph dir → schema from
  `ontology.schema_ddl()` → bulk-load all entities → load all edges in one pass
  → checkpoint → close. (`GraphWriter` still refuses incremental edge writes by
  default — the conservative guard — so we bulk-load with
  `_allow_inplace_edge_writes=True` into the freshly-emptied table.)
- Adding documents = append records to DuckDB, then rebuild the graph.

**Revisit at scale (see ROADMAP P1.7):** the full rebuild is O(corpus); if a large
corpus makes it costly, incremental edge writes are the likely-safe alternative —
but only after re-measuring corruption with exact per-edge intended-state tracking
on a copy first (the discipline that caught the original mis-measurement).

---

## 3. Dependency on kg-common (the standardized substrate)

This repo is a **research-tool / oracle-type consumer** of `kg-common`. It must
**not reinvent** what kg-common provides (per kg-common `docs/BOUNDARY.md`,
re-implementation is a bug — correctness fixes won't flow in). We import:

| Concern | kg-common API | Replaces (today's home-grown) |
|---------|---------------|-------------------------------|
| Typed, graded ontology | `kg_common.ontology.Ontology` (ABC subclass) | `investigation_graph/ontology.py` (markdown regex) |
| Corruption-guarded writes | `kg_common.write.GraphWriter` | `investigation_graph/graph.py` `add_edge`/`bulk_add_edges` |
| Entity resolution | `kg_common.write.dedup.resolve_or_create_semantic` | *(absent today)* |
| Grounding gate | `kg_common.write.grounding.ground` | *(absent today)* |
| Grade-locality | `Ontology.validate_edge` + `EDGE_DOMAIN_RANGE` | type-only check |
| Provider pool | `kg_common.provider` (Ollama/Anthropic) | `investigation_graph/embed.py` |
| Retrieval primitives | `kg_common.retrieval` (PathRAG) | `investigation_graph/queries.py` paths |
| Measurement | `kg_common.measure` (centrality/bridge/coverage) | `investigation_graph/topology.py` |

**Distribution:** kg-common is private + not on PyPI today. A sanitized public
export exists (`~/Projects/kg-common-public-staging`) and the export tooling
lives in `kg-common/scripts/{sanitize_patterns,vendor_skills}.py` with a
leak-check test (`tests/test_skills_sanitized.py`). Once kg-common is flipped
public, this repo pins `kg-common @ git+https://github.com/M0nkeyFl0wer/kg-common.git`
(the pattern `second-brain-hybrid-graph` already uses). Until then: local
editable (`pip install -e ../kg-common`). **External shareability is gated on
WS1.**

---

## 4. The one artifact contract (no plugin framework)

Per the Simplicity Gate: **do not build plugin sockets for collectors that do
not exist.** The core enforces exactly **one ingestion artifact contract** —
the record shape the manual path needs anyway, and the same shape
`kg_common.write.grounding.ground()` already consumes:

```
record = { "kind": "document" | "chunk" | "entity" | "edge", ... }
```

- `document` — id, path/source_uri, title, ingested_at
- `chunk`    — id, doc_id, source_uri, body, chunk_index, embedding, sensitivity
- `entity`   — id, entity_type, label, evidence chunk ids, provenance, confidence
- `edge`     — source_id, target_id, edge_type, evidence, confidence, provenance

Ingestion and extraction **emit** this contract; `ground()` **judges** it;
`GraphWriter` **loads** the survivors. Any future collector (an OSINT scraper,
a different importer) is just "a thing that emits these records" — it conforms
to the contract; it is not a plugin the core has to know about.

---

## 5. Correctness machinery — baked in, not optional

Accessible tool + libel risk ⇒ safety cannot be a flag a hurried user turns
off. The following are **always on**:

1. **Entity resolution** — `resolve_or_create_semantic` (exact → fuzzy →
   embedding → optional LLM adjudication). Prevents "J. Smith" / "John Smith"
   fragmenting into separate nodes and producing false (or missed) connections.
2. **Grounding gate** — `ground()`. An extracted entity must appear in its
   cited source chunk; an edge's endpoints must co-occur. Hallucinated edges
   are quarantined, not published.
3. **Grade-locality** — `Ontology.validate_edge` against `EDGE_DOMAIN_RANGE`.
   `EMPLOYED_BY` must go person→organization; malformed edges are rejected.
4. **Edge-write corruption guard** — `GraphWriter` refuses incremental writes
   into a populated `RELATES_TO` table (the LadybugDB failure mode that
   silently destroys valid edges); bulk reconstruct-and-swap instead.
5. **Bi-temporal edges** — `valid_at_ms` / `invalid_at_ms` / `expired_at_ms`;
   contradictions invalidate prior edges rather than deleting history.

The ethics guidance already in `README.md` (identity ambiguity, triangulation
risk) is the *human* half of this; the machinery above is the *automated* half.

---

## 6. Scope boundaries (non-goals for v1)

- ❌ No user-facing substrate choice (always DuckDB + LadybugDB).
- ❌ No collector / plugin framework (one artifact contract instead).
- ❌ No cloud/remote default (local-first; hybrid/remote are opt-in for
  non-sensitive corpora only).
- ❌ No multi-user / server deployment.
- ❌ No guided wizard yet (WS3, later — modelled on spec-kit-assistant).

---

## 7. Workstreams

| WS | Goal | Repo | Gating |
|----|------|------|--------|
| **WS0** | Planning artifacts (this SPEC + `TODO.md`) | this | — |
| **WS1** | kg-common public-ready: extend sanitizer, re-vendor clean **public skills** (library/ladybug/ladybug-rag/ladybug-surgery/duckdb-rag/kg-ingestion/taxonomy-validation/networkx/ripser/pre-push), scrub 6 core leaks, flip public | `kg-common` (worktree — sibling agent active) | gates external `git+https` dep |
| **WS2** | Journalist core: refactor onto kg-common + DuckDB/Ladybug hybrid; delete dead substrate branches; wire the 5 stages; bake in correctness; bundle `good-dog-corpus`; smoke tests | this | gates ship |
| **WS3** | Guided wizard on the spec-kit harness | this | later |

WS1 and WS2 run **in parallel** (different repos, no collision). WS2 builds
against the local kg-common checkout; publish (WS1) unblocks external sharing.

---

## 8. Example corpus

`multipass-structural-memory-eval-ladybug/sme/corpora/good-dog-corpus` (608K:
`sources/`, `vault/`, its own `ONTOLOGY.md` + `ontology.yaml` + `questions.yaml`
eval set). Bundled as the worked example for onboarding and smoke tests.

---

## 9. Conventions

- **Commits:** small, logical, **no AI attribution** (project `CLAUDE.md` rule).
  Explicit file paths in `git add` (never `-A`/`.`) — multi-agent discipline.
- **Comments:** all code is commented as written (operator-readable).
- **Skills consulted as we go:** `library-skills`, `ladybug`, `ladybug-rag`,
  `ladybug-surgery`, `duckdb-rag`, `kg-ingestion`, `taxonomy-validation`,
  `networkx`, `ripser`, `pre-push`.
- **Logging:** session decisions logged to the vault RAG
  (`log_session_decision`) per repo; cross-repo crossings (WS1) logged on both
  sides (repo-pivot discipline).
</content>
</invoke>
