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

- **Branch:** `align/kg-common-hybrid` (pushed; off `main` @ `df40eaf`)
- **Done & committed:** WS0 (SPEC+TODO) · WS2.0 (kg-common+duckdb deps, imports
  verified) · WS2.1 substrate (`chunk_store.py` DuckDB hybrid, smoke-verified) ·
  WS2.2 ontology (kg-common `Ontology` subclass + grade-locality, verified).
- **Done (kg-common, branch `ws1/sanitize-public`, NOT pushed, repo still
  private):** WS1 skills+core sanitized; WS1b `scripts/build_public_export.py`
  fail-closed export (136 files, 0 leaks, 469 tests pass). Worktree
  `../kg-common-ws1-sanitize` left for review.
- **Next:** WS2.1b — make `graph.py` a rebuilt **projection** of DuckDB
  (`Graph(GraphWriter)`, reconstruct-and-swap edges; see SPEC §2.1). Then WS2.3
  (artifact contract + scope→ingest→extract→ground→use), WS2.4 (good-dog +
  tests + doc reconcile).
- **Key constraint (verified):** GraphWriter refuses incremental edge writes
  into a populated `RELATES_TO` (corruption guard). Graph is always rebuilt from
  DuckDB; never mutated incrementally. SPEC §2.1.
- **Open decisions (user, gate flip-public only — not WS2):** (1) public
  kg-common README rewrite (task #8); (2) when to flip kg-common public.
- **Sibling agents:** active Claude in `kg-common` main checkout — do WS1/WS1b
  work only in the worktree.
- **Commit rules:** no AI attribution; explicit `git add` paths; ruff gate is
  real (fix, don't bypass, your own code); push uses `--no-verify` until WS2.4
  lands tests (pre-push has no tests yet — known, not a regression).
</content>
