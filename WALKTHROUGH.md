# Hands-on walkthrough — run the toolkit end to end

Two parts: **A) explore a real prebuilt graph** (no model, zero risk) so you learn
what "right" looks like, then **B) run a full ingest yourself** so you see every
stage — including where it's honest (grounding) and where it degrades silently
(LLM contention). Every step lists what you should SEE if it worked, so a wrong
answer is visible *as* wrong rather than passing for success.

## Setup (one time, per terminal)

```bash
cd ~/Projects/investigation-graph-fedfiling          # the current code (frontier worktree)
PY=~/Projects/investigation-graph/.venv/bin/python   # venv lives in the main checkout; this worktree has none
```
The code is imported from the directory you stand in; `$PY` only supplies the
dependencies. (This split is also why a *fresh clone* can't run it yet — the
install gap tracked in `docs/ROADMAP.md`.)

**Pre-flight — confirm the borrowed venv matches this branch's imports:**
```bash
$PY -c "import investigation_graph; print('ok')"
```
If this doesn't print `ok`, **stop** — the main checkout's venv has drifted from
the frontier branch's imports. That's the known install gap, not a mistake you
made; reinstall deps before going further. Don't debug the commands below.

---

## Part A — Explore a real graph (no model, instant)

A prebuilt "good dogs" investigation graph is bundled in the repo (666 entities,
185 edges, from 36 real documents). Point the tools at it:

```bash
GD=examples/good-dogs/data
```

### A1 — Structure and leads
```bash
GRAPH_DIR=$GD/graph.lbug CHUNK_DB=$GD/chunks.duckdb $PY scripts/run_analysis.py
```
- **What it does:** topology (no AI) over the graph → a report.
- **You should see:** `Running topology analysis on 666 entities, 185 edges`, then a
  TOPOLOGY REPORT and **`STRUCTURAL GAPS: 28`** (roughly), each a pair of clusters
  with `cross-edges: 0` and a generated question (e.g. *"How do Salmonella Kiambu
  and the FDA relate?"*).
- **Pass-line:** ~28 HIGH/MEDIUM gaps with investigative questions. If you see
  `STRUCTURAL GAPS: 0` or a crash, something's wrong — that's not an empty answer,
  it's a broken run.

### A2 — Find an entity (graph)
```bash
GRAPH_DIR=$GD/graph.lbug CHUNK_DB=$GD/chunks.duckdb $PY scripts/search_cli.py --entity "FDA"
```
- **You should see:** `Found 12 entit(y/ies):` — typed nodes like `[document] FDA
  consumer guidance (confidence 0.60)`. Pass-line: ~12 FDA-named nodes. Empty = wrong.

### A3 — Search document text (DuckDB chunks)
```bash
GRAPH_DIR=$GD/graph.lbug CHUNK_DB=$GD/chunks.duckdb $PY scripts/search_cli.py -q "salmonella recall" --mode fts
```
- **You should see:** `Found 12 passage(s):` — real excerpts with a `source:` path.
  Pass-line: several passages from the salmonella-recall doc.
- **Understand the distinction:** `-q ... --mode {fts,semantic,hybrid}` searches the
  document **chunks**; `--entity` / `--path` search the **graph**. Two surfaces.

### A4 — Trace a path (graph)
```bash
GRAPH_DIR=$GD/graph.lbug CHUNK_DB=$GD/chunks.duckdb $PY scripts/search_cli.py --path "FDA" "Salmonella Kiambu"
```
- **Expect often:** `No paths found.` — and that's the honest point: if there's no
  edge chain, the tool won't invent one. A missing path between things you *expect*
  to connect is itself a lead (that's what A1's gaps formalize). A path *is* shown
  for entity pairs that are genuinely edge-connected.

---

## Part B — Run a full ingest yourself

You'll ingest a small corpus into a **scratch** location, so you never touch the
good-dogs data or your real `data/`.

### B0 — Verify the model BEFORE you spend a slow run on it
```bash
$PY -c "
import ollama
try:
    ollama.Client(timeout=20).generate(model='llama3.2:3b', prompt='say ok', options={'num_predict':3})
    print('MODEL RESPONSIVE — Part B should produce edges')
except Exception as e:
    print('MODEL CONTENDED/ABSENT — Part B will produce few/no edges; fix before proceeding (%s)' % type(e).__name__)
"
```
Edges come **only** from the local LLM. If this prints CONTENDED/ABSENT, a full
ingest will burn minutes and produce entities but ~0 edges — fix it (wait for the
GPU to free, or set a smaller `EXTRACT_MODEL`) before B2. This is the precondition,
not a post-mortem.

### B1 — Point at a small corpus + scratch output
```bash
export INGEST_DIR=examples/sample-investigation     # a few small demo docs (or your own folder)
export GRAPH_DIR=/tmp/ig-test/graph.lbug
export CHUNK_DB=/tmp/ig-test/chunks.duckdb
export EXTRACT_TIMEOUT=45                            # bound each LLM call
mkdir -p /tmp/ig-test
```

### B1.5 — Plant a poison doc and watch grounding CATCH it (the proof)
Watching `Quarantined: 0` scroll by teaches nothing — you can't tell "gate works,
nothing to catch" from "gate broken." So witness it fire on a known-bad input.
This deterministic demo (no model) feeds grounding one real entity, one fabricated
entity, and a fabricated edge between them:
```bash
$PY -c "
from investigation_graph.pipeline import ground_and_resolve
chunks=[{'id':'c1','text':'Acme Corp paid a contractor in March 2024.'}]
entities=[{'id':'real','entity_type':'organization','label':'Acme Corp'},
          {'id':'ghost','entity_type':'person','label':'Zebediah Quagmire'}]
edges=[{'source_id':'real','target_id':'ghost','edge_type':'PAID_TO'}]
out, rep = ground_and_resolve(chunks, entities, edges)
print('kept entities    :', sorted(e['id'] for e in out['entities']))
print('quarantined count:', rep['entities_quarantined'])
print('edges kept       :', len(out['edges']), '(the fabricated PAID_TO is gone — its endpoint was quarantined)')
"
```
- **You should see:** `kept ['real']`, `quarantined count: 1`, `edges kept: 0`. The
  fabricated person ("Zebediah Quagmire" — in no chunk) is dropped, and the edge to
  it dies with it. **That is the libel-safety gate working, on a thing you planted.**
  In a real LLM run, the same gate catches whatever the model hallucinates.

### B2 — Ingest, and watch two lines
```bash
$PY scripts/ingest_folder.py
```
Each doc: **chunk → extract** (regex dates/money → spaCy names → LLM relationships)
**→ ground → resolve → build**. Watch:
- **`Quarantined: N entities, M edges`** — how much it *refused* (the honesty line).
- **The final entity/edge counts.** If `0 edges` and B0 said CONTENDED, that's the
  LLM, not your documents. Re-run when the GPU is idle.

### B3 — Analyze + search YOUR graph (env already exported)
```bash
$PY scripts/run_analysis.py
$PY scripts/search_cli.py --entity "Chen"
```

### B4 — Clean up
```bash
rm -rf /tmp/ig-test
unset INGEST_DIR GRAPH_DIR CHUNK_DB EXTRACT_TIMEOUT
```

---

**Do Part A completely first** (calibrate your eye on a known-good graph), then Part
B with eyes on the model probe, the planted-poison quarantine, and the edge count —
that sequence shows you exactly where the tool is trustworthy and where it degrades.
