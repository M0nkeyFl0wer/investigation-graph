# DEVIATIONS

Deviations between the **interop & analysis-gaps brief** and the real repo/substrate,
found during Phase-0 recon (read against the live code, not the brief's signatures).
Each is a place the plan adapts to ground truth. Update as implementation proceeds.

## Doc-location / brief-assumption deltas

- **`docs/BOUNDARY.md` does not exist in this repo.** The brief says to read it here;
  it actually lives in **kg-common**. The project↔substrate boundary *is* documented
  in this repo, in **`SPEC.md §3`** (the concern/API table: Ontology, GraphWriter,
  entity resolution, grounding, grade-locality, provider pool, retrieval, measure).
  Plan reads SPEC §3 as the boundary doc.
- **ROADMAP is `docs/ROADMAP.md`, not root `ROADMAP.md`.** Plan entries appended there.
- **`DEVIATIONS.md` did not exist** — created by this Phase-0 (this file).

## Substrate-interface deltas (verified by reading kg-common-media)

- **The resolver has no plugin point for new tiers.**
  `write/dedup.resolve_or_create_semantic` is a hardwired cascade
  (exact→fuzzy→embedding→`adjudicate_fn`). The brief's "route structured ER through
  the resolver interface" has no clean existing seam; the `adjudicate_fn` *callback*
  is the only extension model. → P2.4/P2.6 add an `external_match_fn`-style callback
  (PUB.5/PUB.7), consumer-side first. We do **not** fork the resolver.
- **No `amount`/value field on edges in the current schema.** `measure`/ontology edge
  fields carry `edge_type`, `evidence`, `confidence`, temporal stamps — no monetary
  amount. G5 (P2.8 money-flow) therefore depends on P2.4 tabular ingestion to attach
  an `amount` edge property; surfaced here as a schema gap, not assumed present.
- **Directedness mismatch.** `investigation_graph/topology.py:build_networkx_graph`
  returns an **undirected** `nx.Graph`; `kg_common.measure.to_networkx` returns an
  `nx.MultiDiGraph`. Transitive closure (P2.7) and money-flow (P2.8) need a
  **directed** view — we derive one rather than reuse the undirected projection.
- **`measure/centrality.py` and `measure/coverage.py` are empty Phase-6 stubs.**
  `measure/` *does* ship `to_networkx`, `er_quality` (B-Cubed), `bridge`,
  `hard_case_buffer`. No flow/closure helper exists → P2.7/P2.8 add one (instance
  `infer.py` first; PUB candidate if it generalizes).
- **The Ontology base is an overridable base class, not a hard ABC, and is
  unversioned** (`VERSION` lives on subclasses). PUB.6 adds `to_ftm`/`from_ftm` as
  base methods with `NotImplementedError` defaults so existing subclasses don't break.

## Crosswalk boundary (per the brief's own G2 table — recorded, not forced)

- `claim`, `CONTRADICTS`, `SUPPORTS`, `ASSOCIATED_WITH`, `ATTENDED` have **no clean
  FtM equivalent** and stay project-specific. The crosswalk documents these as an
  explicit boundary; it does not invent FtM targets for them.

## Process / environment

- **kg_common is installed editable from the `kg-common-media` worktree**
  (`feat/media-subsystem`), not a pinned release. Any PUB.x change is made in a
  kg-common **worktree**, routed through the sanitizer/export gate, and **never** on
  kg-common's public `main` or hand-edited into `kg-common-public-staging/` — and not
  without the user's explicit go-ahead.
- **Working branch:** this Phase-0 plan is committed on a dedicated
  `feat/interop-analysis-gaps` branch (off `case/fedfiling-build`, which carries the
  unrelated good-dogs/fed-filing sample work), to keep the interop work separable.

## Open questions to confirm before the relevant phase

- (P2.4) Splink as the structured-linkage tier — confirm it earns its weight on the
  DuckDB base vs. the existing resolver before committing the optional extra.
- (P2.5) Re-verify the FtM crosswalk against the *current* `followthemoney` schema at
  implementation time — FtM evolves.
- (Any PUB.x) Get the user's explicit nod before merging any kg-common API change to
  its `main` or flipping kg-common public.
