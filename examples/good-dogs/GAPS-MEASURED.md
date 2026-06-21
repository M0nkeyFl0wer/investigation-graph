# GAPS — measured (build of 2026-06-21)

Companion to `GAPS.md`, which said: *"don't quote the numbers as fact until a
build confirms them — they're hypotheses."* This file replaces the hypotheses
with **measured counts** from the first real build (36 notes → `qwen2.5:14b`
extraction on seshat → DuckDB+LadybugDB → `run_analysis.py`).

## The graph as built

| Metric | Value |
|--------|-------|
| Entities (after 967 duplicate merges) | **684** |
| Typed edges | **208** |
| Connected entities (degree > 0) | **168** |
| Isolated entities (degree 0) | **516** (75%) |
| Connected components | 549 · largest = **69** |
| Communities (Louvain) | 552 |
| Structural gaps (low-cross-edge community pairs) | **20** |
| Bridges (fragile single-entity links) | **122** |
| Persistent H1 (topological holes) | 1 |

**Entity types:** document 189 · event 176 · concept 113 · organization 82 ·
person 46 · product 31 · location 26 · breed 21.

**Edge types:** ABOUT 39 · ALIAS_OF 38 · AFFILIATED_WITH 33 · AUTHORED 30 ·
CITES 18 · REGULATES 18 · SUPERSEDES 11 · GROUPED_UNDER 7 · CONTRADICTS 7 ·
LOCATED_AT 6 · MEMBER_OF 1.

**Cross-domain hubs** (high betweenness on low-degree nodes — the "nifty reveal"):
SAFER (0.178), DCM (0.14), German Shepherd Dog (0.115), Freeman et al. (0.087),
JVIM (0.087). These are exactly the breed/concept entities that tie
research ↔ policy ↔ journalism together.

## Hypotheses vs measured (GAPS.md §1–§2)

| GAPS.md hypothesis | Verdict | Measured |
|--------------------|---------|----------|
| `cites` under-instantiated (<3 = gap) | **REFUTED** | 18 — healthy |
| `regulates` under-instantiated | **REFUTED** | 18 — healthy |
| `grouped_under` under-instantiated | **PARTIAL** | 7 edges over 21 breeds — a real but partial taxonomic spine |
| "only 2 contradictions — thin showcase" | **REFUTED** | 7 found (see caveat) |
| Temporal `supersedes` chains have holes | **HEALTHY** | 11 — the dominance→positive-reinforcement and recall chains landed |
| Orphans / thin single-mention nodes | **CONFIRMED — dominant** | 516 isolated (75%) |
| `MEMBER_OF` (not hypothesized) | **NEW gap** | 1 — genuinely under-instantiated |

**Contradiction caveat (honest):** of the 7 `CONTRADICTS` edges, the gold seeded
pairs landed — the grain-free/DCM pair (Freeman 2022 ↔ the 2018 announcement) and
the training pair (Vieira de Castro/PLOS ONE ↔ Mech 1999). A *trio* among the
brucellosis sources (USDA APHIS ↔ CDC ↔ Cosford 2018) is LLM-proposed and
**warrants human grounding** — which is exactly what the corpus ontology says
`contradicts` requires (`requires_human_grounding: true`). The graph surfacing a
contradiction *to be checked* is the feature, not a bug.

## What this says about the corpus

The relationship structure is strong (every seeded showcase instantiated), but the
graph is **fragmented**: 75% of extracted entities are single-mention orphans and
the largest connected component is only 69 nodes. Two things follow:

1. **For the viz / case study:** show the **connected core** (168 entities / 208
   edges) — the orphan long tail is real OSINT noise (every date, every minor
   proper noun the LLM lifted), not signal. Reducing it is itself one of the
   measured gaps (orphan reduction).
2. **For the loop demo:** the 20 structural gaps + 122 bridges are the leads.

## The gap we close in the loop demo (CASE-STUDY.md §final)

**Chosen: a pit-bull research ↔ municipal-policy bridge.** The behavioral cluster
(community 120: SAFER behavioral-assessment, American Staffordshire Terrier, bite
studies) and the municipal-policy cluster (Denver/Calgary/Montreal/Ontario BSL
bylaws) both turn on the same breed but have **no connecting document** between the
science and the law — a textbook structural gap (one of the 20). The good-dog
OSINT to close it: a public source that the BSL debate and the behavioral research
both reference (e.g. the AVMA literature review on breed and bite risk, or a
journalism piece tying a specific bylaw to the study it leaned on). Add the note →
re-ingest → show the bridge close, confidence-tagged and sourced.

Secondary candidate (cheaper, also valid): close the **`grouped_under`** spine by
adding the AKC/UKC breed-group listings so the 21 breeds attach to their groups.

*Per GAPS.md §4: 1–2 closed gaps illustrate the loop better than ten.*
