# Roadmap — fixes from the OSINT + LadybugDB critiques

Scoped TODO for every issue surfaced in the investigator-lens and
LadybugDB-lead-dev critiques (2026-06-19). Priority: **P0** = correctness
investigators can be misled by; **P1** = quality/scale/safety; **P2** = larger
capability (visual ingestion, incrementality, UX). Each item names the relevant
skill to consult before coding.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done

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

### P1.7 — Full graph rebuild every ingest = scaling cliff  (LadybugDB lens)
- **Problem:** re-ingesting one doc re-writes the whole corpus (safe, but O(corpus)).
- **Fix (later):** design `build_graph` to diff DuckDB records vs the graph and
  rebuild only when the REL set changed; adopt incremental REL writes once
  kg-common/LadybugDB ship the fixed path. **Skill:** `ladybug-surgery`.

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
- **PUB.3 — incremental REL write** once the LadybugDB corruption is fixed
  upstream (unblocks P1.7).
- **PUB.4 — edge `evidence` as a first-class, validated field** in the writer
  (supports P0.2 across consumers).
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

Commit in small chunks; comment all code; consult the named skill before each.
