# Fed Filing — investigation visualization (two views)

Two linked, offline, provenance-first views of the curated Fed Filing knowledge
graph. Both render from the **real** findings (23 entities / 28 edges) and share
one visual grammar, one provenance side-panel, and cross-view highlight.

- **View B — center-out "murder board"** (Cytoscape.js, concentric layout).
  Nucleus = `FED FILING, LLC` + `Humberto (Gabriel) Hernandez`; concentric rings =
  *evidential distance* (inner = documented controllers on the registry record;
  outer = inferred operators + the biographical No Mercy cluster). Node size =
  degree (the Valor / 2407 Courtney Meadows hubs bulge).
- **View A — dual-track branching timeline** (D3 v7). A **LIFE** lane on a shared
  calendar axis (1971 born → 1995 No Mercy → 2019 Fed Filing LLC + domains) over a
  **CASE** lane that lays the `investigation-log.jsonl` pivots out by **work order**
  (numbered badges ①…⑮, branch stubs carrying each step's result/status) — because
  every pivot happened within ~2 days of 2026-06, calendar position would pile them
  in one column; work-order spacing is the honest reconciliation (the axis decoupling
  is labelled on the chart).

## How to run

The viz **reads the private findings at runtime** from `../report-private/` and the
provenance manifests from `../evidence/` + `../evidence-private/`, so serve from the
**case directory** (one level up from `viz/`), not from `viz/`:

```bash
cd examples/fedfiling-case          # NOT examples/fedfiling-case/viz
python -m http.server 8043
# open http://127.0.0.1:8043/viz/index.html
```

Toggle the two views with the **B / A** tabs. Filters (View B): *biographical
context*, *inferred only*, *primary-source only*, and a *small-multiples* dropdown
that scopes to one investigative question (Who owns it? / Who runs it? / impersonation
/ addresses / Who is Hernandez?). Click any node, edge, or timeline step for its
**chain of custody**.

## Offline / privacy-first

- All libraries are **vendored locally** in `vendor/` (D3 v7 — ISC; Cytoscape.js —
  MIT, with `concentric` built into core). There are **no runtime CDN requests** —
  verified: every request during load goes only to the local server.
- The data never leaves the browser. The only external URLs anywhere are the
  `source_url` chain-of-custody links in the provenance panel, which are *data* the
  analyst opens manually, not load-time dependencies.

## Visual grammar (identical in both views — drives every encoding from the ontology)

| Channel | Encodes | Mapping |
|---|---|---|
| node glyph | `entity_type` | person = circle · organization = rounded-rect · domain/location/document glyphs · **trust = double border** · SAM.gov = filled gov mark |
| node ring (View B) | evidential distance | inner = proven control → outer = inferred / biographical |
| node size (View B) | degree | hubs bulge |
| edge line style | inference | **solid** = VERIFIED/CAPTURED · **dashed** = INFERRED / `inferential:true` |
| edge colour | `source_tier` | dark (registry/gov-primary) → light grey (aggregator-secondary) |
| edge opacity + width | `conf` (0.4–0.95) | faint+thin = tentative · opaque+crisp = strong |
| GAP / unsupported | unknowns | hollow hatched red-dashed node (e.g. the David Holland burner persona) |
| edge label | `edge_type` | OWNS, OPERATED_BY, IMPERSONATES, … |

The three named **inferential** edges (`OPERATED_BY → Hernandez`, `OPERATED_BY →
Gobea`, `EMPLOYED_BY ← Holland`) render dashed and faint — they must never read as
documented. (5 edges are dashed in total: the 3 INFERRED + 2 UNVERIFIED secondary
Valor links.)

## Data sources (read-only — the viz never modifies them)

- `../report-private/findings/entities.jsonl` (23) — `{id,type,label,props,confidence,source_tier,provenance[]}`
- `../report-private/findings/edges.jsonl` (28) — `{type,from,to,conf,status,evidence_artifact,evidence_fact,source_tier,inferential?}`
- `../report-private/investigation-log.jsonl` — the CASE-lane steps
- `../evidence/manifest.jsonl` + `../evidence-private/manifest.jsonl` — provenance
  (`evidence_artifact` resolves via `capture_group` → `sha256` / `source_url` /
  `captured_at_utc` / `kind`)

`data.js` is the single adapter that loads + joins all of the above.

## Files

```
viz/
  index.html   shell: view toggle, legend, provenance panel
  data.js      JSONL adapter + the shared visual-grammar constants
  app.js       View B (Cytoscape) + View A (D3) + panel + cross-view highlight
  style.css    greyscale Tufte styling (ink for data, not decoration)
  vendor/      d3.v7.min.js, cytoscape.min.js (vendored, offline)
  _verify/     CDP screenshot harness + output (gitignored — renders private PII)
```

## Verification

`_verify/capture.py` drives the osint-browser over CDP to screenshot both views and
assert the counts. The osint-browser runs in a container, so it can't reach the
host's `127.0.0.1`; serve the viz from a sibling container on the browser's docker
network and point the harness at that address:

```bash
docker run -d --name viz-verify-srv --network osint-browser_default \
  -v "$PWD":/srv:ro -w /srv python:3.12-slim \
  python -m http.server 8043 --bind 0.0.0.0
SRV=$(docker inspect viz-verify-srv --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')

PYTHONPATH=/home/m0nk/Projects/investigation-graph-fedfiling \
  /home/m0nk/Projects/investigation-graph/.venv/bin/python \
  viz/_verify/capture.py "http://$SRV:8043/viz/index.html"
```

Last run: 23 entities / 28 edges, 23 cy-nodes / 28 cy-edges, 5 dashed edges (the 3
named inferential among them), zero external network requests.
```
