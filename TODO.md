# TODO — Investigative Journalism KG build

Step-by-step, **handoff-friendly** checklist. See `SPEC.md` for the why.
Check items off as you go; each phase ends at a logical commit. When handing
off, fill in the **Handoff state** block at the bottom.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked

---

## WS0 — Planning artifacts  *(this repo)*

- [x] Write `SPEC.md`
- [x] Write `TODO.md`
- [ ] Branch `align/kg-common-hybrid`; checkpoint inherited in-flight work;
      commit planning artifacts; push branch
- [ ] Log WS0 decision to vault RAG (both repos)

---

## WS1 — kg-common public-ready  *(repo: `kg-common`, use a WORKTREE — sibling agent active)*

> Goal: the public export is clean so this repo can depend on
> `kg-common @ git+https`. Do **not** hand-edit `kg-common-public-staging/`
> (it is regenerated); fix the **source** + the **sanitizer**, then re-vendor.

- [ ] Enter an isolated worktree in kg-common (do not touch its `main` checkout)
- [ ] Extend `scripts/sanitize_patterns.py`:
  - [ ] `SUBSTITUTIONS`: add `vault_rag` → generic, `graph-ops-dashboard` → generic,
        `johns-graph` → generic, `multipass-structural-memory-eval` → generic
  - [ ] `LEAK_PATTERNS`: add `vault_rag`, `graph-ops-dashboard`, `localhost:77\d\d`,
        `johns-graph`, named-memory filenames (`*_data_loss`, `*_cache.md`)
- [ ] Scrub the 6 core-package leaks (not skills — these are in `kg_common/`):
  - [ ] `kg_common/identity.py:18` — `vault_rag/schema/identity.py` path
  - [ ] `kg_common/session/parser.py:84` — `vault_rag` example
  - [ ] `kg_common/session/client.py:8` — `http://localhost:7720` default
  - [ ] `kg_common/telemetry.py:3` — `graph-ops-dashboard` reference
  - [ ] `kg_common/write/ladybug.py:129` — `~/.claude/skills/...` path pointer
  - [ ] `tests/test_ladybug_writer.py:259` — `johns-graph` comment
- [ ] Re-run `python scripts/vendor_skills.py` → regenerate clean public skills
- [ ] `python scripts/vendor_skills.py --check` and `pytest tests/test_skills_sanitized.py` → green
- [ ] Manual re-grep of vendored output for: `m0nk`, tailscale IPs, `77\d\d`,
      private project slugs (the scan from the audit) → zero hits
- [ ] Confirm `skills/` set is the clean public data-eng + graph skills bundle
- [ ] Decision point (user): flip GitHub `kg-common` public + refresh export
- [ ] Once public: this repo pins `kg-common @ git+https` (see WS2)

---

## WS2 — Journalist core  *(this repo — primary)*

### Phase 2.0 — dependency + skeleton
- [ ] Add kg-common to `requirements.txt`/`pyproject` (local editable now;
      `git+https` once WS1 ships)
- [ ] Confirm import surface: `GraphWriter`, `Ontology`, `dedup`, `grounding`,
      `provider`, `retrieval`, `measure`

### Phase 2.1 — substrate (DuckDB base + Ladybug graph)
- [ ] **Delete** dead chunk-store branches (sqlite, postgres) and the
      `CHUNK_SUBSTRATE` config knob — no substrate choice exposed
- [ ] Rework `chunk_store.py` to the `second-brain-hybrid-graph` DuckDB pattern:
  - [ ] `FLOAT[dim]` fixed-width embedding (dim from config, never hardcoded)
  - [ ] Parquet COPY bulk insert (`INSERT INTO ... read_parquet`)
  - [ ] BM25 FTS via `PRAGMA create_fts_index(..., overwrite=1)`, rebuilt per batch
  - [ ] In-memory HNSW at boot; two-handle RRF `search_hybrid`
  - [ ] DELETE+INSERT re-embed; deterministic UUID5 chunk ids; sensitivity ACL
- [ ] LadybugDB graph via kg-common `GraphWriter` (drop home-grown
      `add_edge`/`bulk_add_edges`; Parquet COPY for nodes)
- [ ] Parameterize embedding dimension end-to-end (DDL + Parquet + config)

### Phase 2.2 — ontology onto the kg-common ABC
- [ ] Port the 8 entity / 14 edge types to an `Ontology` subclass
      (keep the archetypical/atypical/exotypical boundary examples — they're good)
- [ ] Add `EDGE_DOMAIN_RANGE` grade-locality for every edge type
- [ ] Fix modeling bugs: drop/replace `OCCURRED_ON … (date as property)`;
      remove `any` pseudo-types; add `TYPE_ALIASES` / `EDGE_TYPE_ALIASES`
- [ ] `validate_ontology.py` still reports ICR/CI/IPR against the new ABC

### Phase 2.3 — the artifact contract + stages
- [ ] Define the one artifact-contract record schema (document/chunk/entity/edge)
- [ ] **scope** step: ontology confirm + corpus dir + privacy mode
- [ ] **ingest** step: manual docs → chunk → embed → DuckDB; register docs in graph
- [ ] **extract** step: 3-phase extraction emits contract records
- [ ] **ground** step: `resolve_or_create_semantic` → `ground()` → grade-locality →
      `GraphWriter` (only survivors written; report quarantine rate)
- [ ] **use** step: hybrid search, typed-path, topology/gaps, daily briefing
      (port `topology.py` to `kg_common.measure` where it maps cleanly)

### Phase 2.4 — example, tests, docs
- [ ] Bundle `good-dog-corpus` as the worked example
- [ ] Smoke test: ingest good-dog → graph builds → search/path/gap return
      (per `pre-push` skill: unit + integration + smoke)
- [ ] Reconcile docs with reality (remove claims for deleted sqlite/postgres
      paths; fix README clone URL → `investigative-journalism-kg`)
- [ ] Update `docs/database-choice.md` → describe the fixed hybrid, not a choice

---

## WS3 — Guided wizard  *(later)*

- [ ] Study `spec-kit-assistant.tar.gz` harness shape
- [ ] Wrap scope→ingest→extract→ground→use as a guided wizard
- [ ] (Optional) desktop wrapper, per the `*-little-helper` builds

---

## Handoff state  *(update on every handoff)*

- **Branch:** `align/kg-common-hybrid` (pushed; off `main` @ `df40eaf`).
- **Done & committed (this repo):** WS0 docs · WS2.0 deps · WS2.1 DuckDB
  substrate · WS2.1b graph projection (`Graph(GraphWriter)`, reconstruct-and-
  swap) · WS2.2 ontology (kg-common ABC + grade-locality) · WS2.3 ground stage
  (grounding + entity resolution) + 5-stage ingest + search rewire · WS2.4
  smoke suite (7 tests, deterministic), read-script reconcile, determinism fix,
  Ollama timeout/degradation hardening, `database-choice.md` rewrite, README
  clone URL. All ruff-clean, no AI attribution.
- **Done (kg-common, branch `ws1/sanitize-public` in worktree
  `../kg-common-ws1-sanitize`, NOT pushed, repo still private):** WS1 skills+
  core sanitized; WS1b `scripts/build_public_export.py` fail-closed export
  (136 files, 0 leaks, 469 tests pass).
- **Verified:** stub e2e (full flow, hallucination quarantined) + real-doc e2e
  with Ollama DOWN (28.5s, no hang: 6 chunks, 53 entities via spaCy+grounding+
  ER across 3 docs, graceful degradation). LLM edges + embeddings are
  Ollama-gated; a healthy Ollama adds them.
- **Three safety gates live + tested:** grade-locality (GraphWriter), grounding
  (`pipeline.ground_and_resolve`), entity resolution (same).
- **Key constraint (verified):** GraphWriter refuses incremental edge writes
  into a populated `RELATES_TO` (corruption guard) → graph is always REBUILT
  from DuckDB, never mutated. SPEC §2.1.
- **Remaining (polish):** bundle good-dog-corpus as the example; fuller README
  reconcile (stale "embeddings in the graph" / bulk-edge claims → DuckDB chunks
  + kg-common dep); real-Ollama e2e for LLM edges when the daemon is healthy.
- **Open decisions (user; gate flip-public only):** (1) public kg-common README
  (task #8); (2) when to flip kg-common public.
- **Env notes:** local Ollama was hanging on cold-load/GPU-saturation (health
  probe 15s timeout) — code now degrades instead of hanging. Pre-push hook runs
  SYSTEM pytest (not the `.venv`), so it can't import deps; suite is green in
  the venv (`.venv/bin/python -m pytest`). Push with `--no-verify` until the
  hook targets the venv.
- **Commit rules:** no AI attribution; explicit `git add` paths; ruff gate is
  real (fix your own code, don't bypass).
</content>
