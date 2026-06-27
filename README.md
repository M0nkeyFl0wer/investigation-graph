# investigation-graph

A privacy-first knowledge graph toolkit for **investigative journalists, OSINT investigators, and researchers**. Load structured records and documents, resolve who's who across datasets, and surface the structural gaps that point to leads — a source-traced graph you can navigate. Relationship extraction from prose is a **human-verified assist** (we measured it — see below), not the spine. Runs on your laptop.

**No cloud required. No accounts. No data leaves your machine.**

> **⚠️ Status — not yet installable from a fresh clone.** The `kg-common` substrate
> this depends on goes public alongside this repo; until then `pip install` from a
> clean checkout won't resolve it. For now, read this as the *approach* and the
> worked example (`examples/good-dogs/`), not a runnable install.

<a href="https://ladybugdb.com"><img src="https://ladybugdb.com/img/logo.svg" alt="LadybugDB" height="50"></a>&nbsp;&nbsp;&nbsp;
<a href="https://networkx.org"><img src="https://networkx.org/documentation/stable/_static/networkx_logo.svg" alt="NetworkX" height="50"></a>&nbsp;&nbsp;&nbsp;
<a href="https://ollama.com"><img src="https://ollama.com/public/ollama.png" alt="Ollama" height="50"></a>

> **Research context:** Inspired by [*An Alternative Trajectory for Generative AI*](https://arxiv.org/abs/2603.14147) (Belova et al., Princeton, 2026), which proposes domain-specific superintelligence built on knowledge graphs and formal logic rather than monolithic LLMs. This toolkit applies that vision to investigative work — journalism, OSINT, and research: a local, specialized knowledge graph where every entity traces back to a source document, every connection is typed and auditable, and structural gaps — found through topology, not AI guessing — become investigative leads. *"Intelligence arises from manipulating relational symbolic structures, abstracting away low-level sensory details."*

## What This Does

You have a pile of documents — court filings, corporate registrations, leaked emails, public records. You need to find connections and, more importantly, find what's *missing*.

This toolkit:

1. **Ingests** your documents (PDF, text, markdown, HTML)
2. **Extracts** people, organizations, transactions, and the relationships between them
3. **Builds** a searchable knowledge graph on your machine
4. **Analyzes** the graph structure to find gaps, contradictions, and surprising connections
5. **Briefs** you daily with a markdown summary of what the graph found

### Why an investigator would use this

Search answers *"where's the word 'Meridian'?"* It doesn't answer *"who connects
Chen to Meridian, and what document am I missing that should link these two
clusters?"* Those are **relationship and structure** questions — and the
**holes in the structure are leads**. This tool turns a pile of documents into a
typed, source-traced graph so you can see the shape of a case, find the quiet
connectors, and spot the gap that points to the next records request.

It's deliberately a **lead-generator and structure-finder, not a source of
findings** — every connection is yours to verify against the original document
before you publish. The safety machinery exists because an automated graph that
invents a connection is a libel risk: it *quarantines* any entity whose name
isn't in your documents and any edge between two entities that never appear
together, so a hallucinated name — or a link between people never mentioned in
the same place — is dropped, not published. What it does **not** do is verify
that a relationship between two entities that *do* co-occur is real, so every edge
stores its source sentence and confirming it against the document is your job.

> **📖 Read [`docs/FOR-INVESTIGATORS.md`](docs/FOR-INVESTIGATORS.md) — the field
> guide.** Why a graph beats a folder of PDFs, how to work each stage, how to
> read gaps/bridges as leads, the verification discipline, OPSEC, and the honest
> limitations. Start there if you're an investigator, not a developer.

---

## How this fits real investigative practice

Edges get into the graph two ways, with very different reliability — being clear
about which is which is the whole point.

**1. Structured sources — the reliable path (local, no model).** Corporate
registries, court filings, CSVs, and [FollowTheMoney](https://followthemoney.tech)
/ [OpenSanctions](https://opensanctions.org) / [ICIJ Offshore Leaks](https://offshoreleaks.icij.org)
data carry their relationships *in the data* (`OWNS`, `DIRECTOR_OF`, `FUNDS`). The
tool loads those as typed, sourced edges and resolves duplicate entities across
datasets. This is how the large investigations (Panama/Pandora Papers) are
actually built — **structured data + entity resolution + a navigable graph**, not
a model reading prose. It runs entirely locally and is the most trustworthy mode.
For heavy-duty entity resolution it composes with dedicated tools (Splink,
nomenklatura, Senzing) rather than reinventing them.

**2. Unstructured text — the assistive path (model-dependent).** For emails, PDFs,
and news, entities come from spaCy locally, but high-quality *relationship*
extraction needs a capable model — and **we measured how good it actually is** on
indirect, real-document-style prose (exact-triple F1, verified gold): **≈ 0.38 on a
laptop model, ≈ 0.62 even with a frontier model.** So prose extraction misses or
mis-types a large share of real relationships at *every* tier — it is a
**human-verified lead generator, not a source of findings**, never auto-asserted.
**Verify every prose-derived edge against the source document before you rely on it
— this is a primary operating instruction, not a disclaimer.** You pick the model
by your data's sensitivity:
- **Public / already-published data → a cloud model is fine** (no source to protect — most OSINT).
- **Source-sensitive data → a model you host** (your GPU, a private VPS, or a zero-retention enterprise API), accepting that a laptop-only model gives weaker edges.

Everything else — entities, embeddings/semantic search, and the topology that
surfaces the gaps — runs locally either way. **The privacy guarantee is precise:
the default local pipeline makes no network calls; relationship extraction over
prose is the one stage where you trade model strength against where your data
goes, and you choose.**

> ⚠️ **Status:** the structured path's pieces (tabular/CSV ingest, the
> FollowTheMoney crosswalk, the entity-resolution tiers) exist but are not yet the
> default `ingest_folder` flow — wiring that is the current priority (see
> `docs/ROADMAP.md`). Today the wired-in default is the prose/LLM path.

---

## Quick Start

### Prerequisites

- **Python 3.10 or later** (check: `python3 --version`)
- **[Ollama](https://ollama.com)** installed and running (handles all AI locally)
- **Basic comfort with the command line** (everything runs via terminal)

### Setup

```bash
# Clone the repo
git clone https://github.com/M0nkeyFl0wer/investigation-graph.git
cd investigation-graph

# Run setup (installs Python packages — including the kg-common substrate — and
# downloads the local AI models)
bash setup.sh

# Verify everything works
python -m investigation_graph.check
```

You should see:

```
investigation-graph system check
========================================
  LadybugDB: 0.15.3
  PyArrow: 23.0.1
  spaCy: 3.8.14
  spaCy model: en_core_web_sm OK
  NetworkX: 3.6.1
  Ripser: OK
  DuckDB: 1.5.4
  kg-common: 0.0.1

  Ollama: OK (5 models)
  Embedding model (nomic-embed-text, 768d): OK

Ontology: Ontology(8 entity types, 12 edge types)
  All checks passed.
```

If anything says NOT INSTALLED or MISSING, the check tells you exactly what to run.

### Ingest Your First Documents

Try the bundled sample investigation first (a small fictional Harbor City graft
case — the one this README's examples walk through):

```bash
mkdir -p ingest
cp examples/sample-investigation/* ingest/
python scripts/ingest_folder.py
```

For a **richer, fully worked example**, see the **[Good Dogs case study](examples/good-dogs/CASE-STUDY.md)**
— a wholesome, public-records walk-through (veterinary science, breed standards,
and municipal policy) that builds the graph, finds a structural gap with topology,
closes it with one sourced document, and visualizes the result. It's the flagship
demonstration of the whole loop.

Then swap in your own documents:

```bash
# Drop documents into the ingest folder (PDF, text, markdown, HTML)
cp /path/to/your/documents/* ingest/

# Re-run ingestion (idempotent — re-processes each document cleanly)
python scripts/ingest_folder.py
```

Output looks like:

```
Scope: Ontology(8 entity types, 12 edge types)
Corpus: 3 document(s) in ingest/  →  DuckDB chunks.duckdb

[1/3] harbor-city-expose.txt
  2 chunks (2 embedded), 24 entities, 6 edges → DuckDB
[2/3] property-records.md
  2 chunks (2 embedded), 20 entities, 4 edges → DuckDB
[3/3] financial-disclosure.html
  2 chunks (2 embedded), 30 entities, 5 edges → DuckDB

Grounding 74 entities / 15 edges against 6 chunks...

========================================================
Ingestion complete in 61.4s.
  Documents:            3
  Chunks in DuckDB:     6
  Entities (graph):     41  (merged 12 duplicates)
  Edges (graph):        9
  Quarantined:          21 entities (28%), 6 edges (40%) — failed the grounding gate
```

Each document is chunked and embedded into DuckDB, then extracted; the **ground**
stage drops entities/edges that aren't supported by the source text and merges
duplicate names before the graph is built. The "Quarantined" line is the gate
doing its job — extracted claims that didn't survive verification never enter the
graph. (Edge counts come from the local LLM; with Ollama unavailable you'll still
get the deterministic + spaCy entities and a keyword-searchable corpus.)

### Search the Graph

```bash
# Content search over document chunks (default mode = hybrid: fts + semantic)
python scripts/search_cli.py -q "Acme Corp"

# Keyword-only (BM25) over document text
python scripts/search_cli.py -q "payments to contractors" --mode fts

# Semantic (by meaning) over document text
python scripts/search_cli.py -q "financial fraud" --mode semantic

# Graph: typed relationship chain between two entities
python scripts/search_cli.py --path "Jane Smith" "Harbor Development LLC"

# Graph: find an entity node by name
python scripts/search_cli.py --entity "Chen"
```

**Path search** shows the chain of relationships:

```
Found 3 paths:

  Path 1 (confidence: 0.36):
    Chen --[EMPLOYED_BY]--> Brightpath Advisors --[FUNDED_BY]--> Meridian Holdings LLC

  Path 2 (confidence: 0.22):
    Chen --[EMPLOYED_BY]--> Brightpath Advisors --[FUNDED_BY]--> Harbor City
    Redevelopment Authority --[OCCURRED_ON]--> Meridian Holdings LLC
```

Each hop has a confidence score. The path confidence is the product of all hops — lower confidence means more uncertain connections.

### Run Analysis

```bash
python scripts/run_analysis.py
```

Output:

```
TOPOLOGY REPORT
============================================================
  Entities:              80
  Edges:                 28
  Connected components:  57
  Largest component:     11 nodes
  Communities (Louvain): 58

STRUCTURAL GAPS: 3
------------------------------------------------------------
  [HIGH] Brightpath Advisors ↔ Harbor City Redevelopment Authority
         7 entities ↔ 7 entities | cross-edges: 0
         → How do Brightpath Advisors and Harbor City Redevelopment
           Authority relate? Your knowledge about these is not yet connected.

SURPRISING CONNECTIONS: 6
------------------------------------------------------------
  Robert Chen (person)
    Betweenness: 0.5111 | Degree: 4
    → Structurally important despite low frequency
```

**Structural gaps** are the investigative leads — communities of entities that should plausibly connect but don't in your data. That's where the missing documents are.

**Surprising connections** are entities with high betweenness centrality (they bridge otherwise separate networks) but low degree (they don't appear in many documents). These are the quiet connectors.

### Daily Briefing

```bash
python scripts/daily_briefing.py
```

Generates `briefings/2026-04-04.md` — a markdown summary including:
- New entities added in the last 24 hours
- Contradictions found between sources
- Structural gaps (as investigative questions)
- Surprising connectors
- Unlinked entities needing attention

If you configure an Obsidian vault path, the briefing automatically copies there.

### Ontology Health

```bash
python scripts/validate_ontology.py
```

Shows how well your ontology matches reality:

```
  ICR (type coverage): 0.75 — warning (some declared types have no data)
  CI (class imbalance): 0.34 — warning (dominant: organization at 27/80)
  IPR (edge coverage): 0.57 — warning

  Type distribution:
    organization       27 ( 33.8%) ████████████████
    transaction        25 ( 31.2%) ███████████████
    event              16 ( 20.0%) ██████████
    person              9 ( 11.2%) █████

  Unpopulated types: asset, claim
```

- **ICR** (Instantiated Class Ratio): What fraction of your declared types have actual data. Below 0.8 means some types are dead schema.
- **CI** (Class Imbalance): If one type dominates (above 0.5), your extraction is probably miscategorizing entities.
- **IPR** (Instantiated Property Ratio): Same as ICR but for edge types.

---

## The Seven Stages

### 1. Ontology — What matters

Edit `ONTOLOGY.md` to define entity types and relationship types for your beat or case. Ships with a general investigative ontology (journalism / OSINT / research) covering 8 entity types and 12 edge types.

The system **rejects entities that don't match your ontology** at write time — no junk accumulates. Rejections are counted and reported, so you know when to expand the ontology.

Each type includes boundary examples:

| Column | Purpose |
|--------|---------|
| Archetypical | Clearly belongs to this type |
| Atypical | Edge case that still belongs |
| Exotypical | Looks similar but does NOT belong — shows which type it DOES belong to |

The exotypical examples prevent the most common extraction error: everything getting dumped into a catch-all type.

### 2. Embeddings — Semantic understanding

Documents are chunked (1000 characters with 200-character overlap) and converted to 768-dimensional vectors using a local AI model (Ollama + nomic-embed-text). These power semantic search — finding documents by meaning, not just keywords.

Chunks, embeddings, and full-text (BM25) search live in **DuckDB** (a single file, `data/chunks.duckdb`) — the base of the hybrid. The entity/edge **graph** lives in LadybugDB and is rebuilt from those records. See [`docs/database-choice.md`](docs/database-choice.md) for why the two-part store, and `SPEC.md` for the architecture. If Ollama is unavailable, ingestion still completes — chunks are stored unembedded (keyword search keeps working) and semantic search simply skips them.

### 3. Extraction — Three-phase entity extraction

Every document goes through three extraction phases:

**Phase 1 — Deterministic** (instant, free, always runs):
- Regex patterns for dates, dollar amounts, email addresses
- Structural extraction from document formatting
- Confidence: 0.85-0.90 (high — these are pattern matches)

**Phase 2 — spaCy NER** (fast, local, no GPU needed):
- Named entity recognition: people, organizations, locations
- Maps spaCy labels to your ontology types (PERSON → person, ORG → organization, etc.)
- Confidence: 0.70 (good — NER is well-established)

**Phase 3 — LLM** (slower, local via Ollama):
- Relationship extraction: who is connected to whom, and how
- Type refinement: corrects Phase 2 misclassifications using ontology context
- Produces typed edges (EMPLOYED_BY, FUNDED_BY, CONTRACTED_WITH, etc.)
- Confidence: 0.60 (lower — LLM extraction needs human review)
- Constrained by ontology: the LLM prompt includes all types and boundary examples

Each entity records its `provenance` (which phase extracted it) and `source_url` (which document it came from). Nothing enters the graph without a paper trail.

### 4. Quality Control — Ontology validation

Every entity is validated against `ONTOLOGY.md` before it enters the graph. If the extraction pipeline produces an entity typed as "weapon" but your ontology doesn't include "weapon", it's rejected and the rejection is counted.

After ingestion, you see:

```
Ontology rejections (types not in ONTOLOGY.md):
  weapon: 3 rejections
  vehicle: 2 rejections
  Tip: Consider adding frequently rejected types to ONTOLOGY.md
```

This tells you when your ontology needs expanding — the data is telling you what types it contains.

### 5. Search and Path — Following the connections

Two search surfaces. **Content search** (`-q`) runs over the document chunks in
DuckDB — find passages by keyword or meaning; **graph lookups** (`--entity` /
`--path`) run over the entity/edge graph. The `--mode` flag applies to content
search only:

| Content mode (`--mode`) | How it works | Best for |
|------|-------------|----------|
| `fts` | BM25 full-text over chunk text | Passages containing specific words |
| `semantic` | Cosine similarity between the query embedding and **chunk** embeddings | Passages by meaning, without the exact words |
| `hybrid` (default) | Reciprocal Rank Fusion of `fts` + `semantic` — no weight tuning | Best general-purpose passage search |

Graph lookups are separate flags, not modes: `--entity NAME` finds entity nodes
whose label contains NAME (Cypher `CONTAINS`); `--path FROM TO` finds typed
relationship chains. (Entities carry no embeddings — semantic search is over
chunks, not nodes.)

**Path search** finds typed chains between entities. Not just "these are related" but:

```
Jane Smith --[EMPLOYED_BY]--> Acme Corp --[CONTRACTED_WITH]--> Harbor Dev LLC
```

Each path has a confidence score (product of edge confidences). Multiple paths between the same entities often mean stronger connections.

### 6. Topology — Finding what's missing

Graph analysis runs deterministic algorithms — no AI, just math on the graph structure:

| Algorithm | What it finds | Why it matters |
|-----------|--------------|----------------|
| Connected components | Separate clusters in the graph | Shows which investigations are isolated |
| Louvain communities | Dense subgroups | Natural topic clusters |
| Betweenness centrality | Entities that bridge communities | Quiet connectors — people/orgs that link otherwise separate networks |
| Bridge detection | Single-point-of-failure edges | Fragile connections that would break if removed |
| Gap detection | Community pairs with low cross-edges | **The leads** — what your investigation is missing |
| Persistent homology | Topological holes in the graph | Higher-order structural gaps (requires Ripser) |

**The gaps are the story.** Two large communities with zero cross-edges means your documents cover two related areas that you haven't connected yet. The gap question tells you what to look for next.

### 7. Daily Briefing — What the graph found

A markdown file generated from graph structure alone. Sections:

- **New entities**: What was added in the last 24 hours
- **Contradictions**: `CONTRADICTS` edges between claims from different sources
- **Structural gaps**: Community pairs with low connectivity (as investigative questions)
- **Surprising connections**: High betweenness on low-degree entities
- **Unlinked entities**: Entities older than 7 days with no connections (need attention or removal)

Readable in Obsidian, any text editor, or the terminal. Optionally auto-copies to your Obsidian vault inbox.

---

## Privacy

### Local Mode (default)

The default pipeline runs on your machine and makes **no network calls** — no API
keys, no accounts. The one exception you opt into deliberately: relationship
extraction over prose can be routed to a hosted model (see *How this fits real
investigative practice* above for when that's appropriate), and the optional
`capture/` tool fetches URLs you explicitly give it. Left at defaults, nothing
leaves your machine.

| Component | Where it runs |
|-----------|--------------|
| Document text | Stays on disk |
| Entity extraction | Ollama on your CPU/GPU |
| Embeddings | Ollama on your CPU/GPU |
| Knowledge graph | LadybugDB directory on disk |
| Vector search | LadybugDB native (same database) |
| Analysis | Python (NetworkX) on your CPU |
| Daily briefings | Written to disk |

**When to use:** Sensitive sources, leaked documents, anything you can't risk being transmitted.

### Hybrid Mode

Embeddings stay local. Entity extraction can optionally use a remote LLM with zero-data-retention (ZDR) for non-sensitive documents. Better extraction quality on complex documents.

```python
# In investigation_graph/config.py
PRIVACY_MODE = "hybrid"
REMOTE_API_BASE = "https://api.anthropic.com/v1"
REMOTE_MODEL = "claude-haiku-4-5-20251001"
# Set NEWSROOM_API_KEY as environment variable — never hardcode
```

**When to use:** Mix of public records (non-sensitive) and confidential material (sensitive). The graph, embeddings, and analysis always stay local regardless.

### Remote Mode

Everything via remote API. Not recommended for sensitive material.

**When to use:** Bulk processing of purely public datasets where speed and quality matter more than confidentiality.

See `docs/privacy-guide.md` for detailed comparison and provider recommendations.

### Ethics: Identity Ambiguity and Source Protection

Two risks that automated extraction creates for anyone publishing findings — journalists, OSINT investigators, and researchers alike:

**Identity ambiguity.** The pipeline will extract "John Smith", "J. Smith", and "John S. Smith" as three separate entities. It may also split "BP US" and "British Petroleum" into different organizations. Before publishing any finding based on graph connections, **manually verify that linked entities are actually the same person or organization.** Misattributing connections in an automated graph can falsely accuse individuals. The deduplication threshold in `config.py` (`DEDUP_THRESHOLD = 0.92`) catches some duplicates via embedding similarity, but it is not sufficient for names that are similar but refer to different people.

**Triangulation risk.** Combining multiple datasets (public records + leaked internal emails + confidential source interviews) creates a graph where the structural position of entities can inadvertently reveal confidential sources. If you publish a subset of the graph — even with names redacted — the unique pattern of connections around a source may be enough for an adversary to identify who leaked the information. Before sharing any graph visualization or export:

- Review whether the structural layout reveals source identity through unique relational positions
- Consider removing or generalizing edges that trace back to confidential sources
- Remember that even aggregate statistics (community membership, betweenness scores) can narrow down candidates

**The graph is an intelligence product.** Treat it with the same operational security as your source list.

---

## Configuration

All configuration lives in `investigation_graph/config.py`:

### Paths

```python
GRAPH_DIR = Path("data/graph.lbug")    # Where the graph database lives
INGEST_DIR = Path("ingest")             # Where documents go for ingestion
BRIEFING_DIR = Path("briefings")        # Where daily briefings are written
OBSIDIAN_VAULT = ""                     # Optional: Obsidian vault for briefing delivery
```

### Models

```python
EMBEDDING_MODEL = "nomic-embed-text"    # Local embedding model (768 dimensions)
EMBEDDING_DIM = 768                     # Must match model output dimension
LOCAL_EXTRACTION_MODEL = "llama3.2:3b"  # Local LLM for entity/relationship extraction
```

The default extraction model (`llama3.2:3b`) is small and fast. For better extraction quality at the cost of speed, try `mistral`, `llama3:8b`, or `gemma2`.

### Extraction Tuning

```python
MIN_CONFIDENCE = 0.5       # Minimum confidence to keep an entity (0.0-1.0)
MAX_ENTITIES_PER_DOC = 200 # Safety limit per document
DEDUP_THRESHOLD = 0.92     # Cosine similarity above this = likely duplicate
```

### Analysis Tuning

```python
AUTO_ANALYSIS = False        # Run analysis after every ingestion
PRUNE_AGE_DAYS = 7           # Flag unlinked entities older than this
MIN_COMMUNITY_SIZE = 5       # Minimum community size for gap analysis
MAX_CROSS_EDGES_FOR_GAP = 3  # Below this = flagged as gap
TOP_BETWEENNESS = 10         # How many high-betweenness entities to report
```

### Daily Briefing Sections

```python
BRIEFING_SECTIONS = [
    "new_entities",           # Entities added in last 24h
    "contradictions",         # CONTRADICTS edges found
    "structural_gaps",        # Community pairs with low cross-connection
    "surprising_connections", # High betweenness on low-frequency entities
    "unlinked_entities",      # Entities needing attention
]
```

Remove a section name to exclude it from briefings.

---

## Extending the Ontology

Edit `ONTOLOGY.md` to add entity types and edge types for your beat.

**Rule of thumb:** Only add a type when you've seen 3+ instances that don't fit existing types. Check the rejection log after ingestion — it tells you what types your documents need.

### Adding an Entity Type

Add a row to the Entity Types table in `ONTOLOGY.md`:

```markdown
| permit | A government permit, license, or approval | "Building permit #2024-087" | "Informal verbal approval" | "The permit office" → organization |
```

The last three columns (archetypical, atypical, exotypical) improve extraction accuracy. The exotypical column is especially important — it shows the LLM what does NOT belong to this type.

### Adding an Edge Type

Add a row to the Edge Types table:

```markdown
| ISSUED_BY | permit → organization | Government body that issued the permit | Regulatory authority, approval chain |
```

Every edge type should have a clear investigative purpose. If you can't explain why a relationship matters to the investigation, don't add it.

### Validating Changes

```bash
python scripts/validate_ontology.py
```

This checks:
- All types are syntactically valid
- The graph health metrics (ICR/CI/IPR) with the updated ontology
- Which types are populated and which are empty

---

## The Stack

All open source. All installable with pip (except Ollama).

| Tool | Version | Purpose | Why this one |
|------|---------|---------|-------------|
| [DuckDB](https://duckdb.org) | 1.0+ | Chunks + embeddings + FTS (the base) | Single-file columnar DB. BM25 full-text + HNSW vector search fused with RRF. Source of truth for chunk text, embeddings, and the record set. |
| [LadybugDB](https://ladybugdb.com) | 0.15.3 | Graph database (the projection) | Embedded graph DB, Cypher queries, typed edges. Rebuilt from the DuckDB records each ingest. No server. Continuation of KuzuDB. |
| [kg-common](https://github.com/M0nkeyFl0wer/kg-common) | pinned | Shared KG substrate | GraphWriter (safe bulk-write path), the Ontology contract (grade-locality), entity resolution, and the grounding gate — imported, not reinvented. |
| [PyArrow](https://arrow.apache.org) | 15.0+ | Bulk data loading | `COPY FROM` Parquet is far faster than row-by-row inserts; PyArrow writes the Parquet files for both DuckDB and LadybugDB. |
| [Pandas](https://pandas.pydata.org) | 3.0+ | Data manipulation | DataFrame operations for bulk entity preparation before Parquet export. |
| [spaCy](https://spacy.io) | 3.8+ | NLP extraction (Phase 2) | Named entity recognition. `en_core_web_sm` model — small, fast, good enough for people/orgs/locations. |
| [NetworkX](https://networkx.org) | 3.6+ | Graph analysis | Louvain communities, betweenness centrality, bridge detection, connected components. Runs on the extracted graph. |
| [Ripser](https://ripser.scikit-tda.org) | 0.6+ | Persistent homology (optional) | Finds topological holes — higher-order structural gaps that community detection misses. |
| [Ollama](https://ollama.com) | 0.3+ | Local AI models | Runs embedding + extraction models on your hardware. No API keys. No cloud. |
| [Obsidian](https://obsidian.md) | any | Reading/writing (optional) | If configured, daily briefings auto-copy to your Obsidian vault inbox. |

### Why DuckDB + LadybugDB (and no choice to make)?

You don't pick a database — it's always this hybrid, so there's nothing to misconfigure:

- **DuckDB does retrieval**: BM25 full-text + HNSW vector search out of the box, fused with Reciprocal Rank Fusion. One file, no server, easy to back up.
- **LadybugDB does structure**: a real graph DB (Cypher, typed edges) for the investigative payoff — paths, gaps, bridges, communities.
- **The graph is a rebuilt projection** of the DuckDB records, not an incrementally-mutated store. Every ingest rebuilds it in one clean pass, so re-ingestion is idempotent — the same records always produce the same graph, with no in-place edge mutation to drift or get out of sync (see `SPEC.md` §2.1).
- **Embedded**: both are files/dirs under `data/` — copy, back up, or encrypt the whole investigation as a unit.

### Why not a cloud graph database?

Your investigation data — leaked documents, source identities, financial records — should not be on someone else's server. This toolkit is designed so that **nothing leaves your machine** in the default configuration.

---

## Architecture

```
ONTOLOGY.md                    ← You edit this
    │
    ▼
investigation_graph/ontology.py     ← Parses types, validates at write time
    │
    ▼
ingest/ ──► extract.py         ← Three-phase extraction
    │         │
    │         ├─ Phase 1: Deterministic (regex)
    │         ├─ Phase 2: spaCy NER
    │         └─ Phase 3: LLM (Ollama)
    │                │
    │                ▼
    │         embed.py              ← Ollama nomic-embed-text
    │                │
    │                ▼
    └────────► graph.py             ← LadybugDB: entities + edges + vectors
                     │
                     ▼
              queries.py            ← All Cypher centralized here
                     │
         ┌───────────┼───────────┐
         ▼           ▼           ▼
    search_cli   topology.py   briefing.py
    (keyword/    (Louvain,     (daily
     semantic/    gaps,         markdown
     hybrid/      bridges,      summary)
     path)        homology)
```

### Data flow

1. Documents land in `ingest/`
2. `ingest_folder.py` reads each document, runs three-phase extraction
3. Entities are validated against ONTOLOGY.md — rejected types are logged
4. Valid entities bulk-load via Parquet into LadybugDB
5. Each entity gets a 768-dim embedding computed by Ollama and stored in the graph
6. Edges (relationships) are written via parameterized Cypher
7. Search, analysis, and briefings all query the same graph

### Query safety

**All Cypher queries are pre-built and parameterized** in `investigation_graph/queries.py`. No dynamic Cypher generation anywhere in the codebase. This means:

- No query injection
- No LLM hallucinating Cypher syntax
- Every query the system runs is auditable — read `queries.py` to see exactly what it does

### Database schema

**DuckDB (`data/chunks.duckdb`) — the source of truth.**

```
chunk        id, doc_id, source_uri, title, body, chunk_index,
             entity_ids, embedding FLOAT[N], sensitivity, embedded_at   (+ BM25 FTS index)
document     id, path, title, ingested_at        ← the full record set, so the
entity       id, doc_id, entity_type, label, ...   graph can be rebuilt from here
edge         doc_id, source_id, target_id, edge_type, evidence, ...
```

**LadybugDB (`data/graph.lbug`) — the rebuilt projection.** Schema comes from
the kg-common `Ontology` (so it stays consistent with the writer's validation):

```
Entity (Node)      id (PK), entity_type, label, description, confidence,
                   source_url, provenance, extraction_source, quality_flag, ...
Document (Node)    id (PK), path, title, ingested_at
RELATES_TO (Edge)  edge_type, weight, confidence, evidence, provenance,
                   valid_at_ms, invalid_at_ms, expired_at_ms   (bi-temporal trio)
MENTIONED_IN (Edge: Entity → Document)
CHUNK_OF (Edge: Chunk → Document)
```

Entities carry no embedding column — semantic search runs over the DuckDB
chunks, not over graph nodes (one embedding model, one place). Edge writes go
through kg-common's `GraphWriter`; the graph is rebuilt in a single
reconstruct-and-swap pass per ingest, so re-ingestion is idempotent and never
mutates edges in place.

### Integration with AI assistants (MCP / Claude Code)

If you connect this graph to an AI assistant via MCP (Model Context Protocol) or similar tool-use framework, use **progressive disclosure** to avoid context bloat:

- **Don't** dump the full schema, ontology, and query library into the system prompt upfront. This wastes tokens and degrades reasoning.
- **Do** provide high-level tool descriptions initially ("search the knowledge graph", "find paths between entities", "run topology analysis").
- **Only when the assistant decides to query the graph** should it fetch the specific schema (entity types, edge types) and query patterns it needs.

In practice: expose `search_cli.py` and `run_analysis.py` as tools with short descriptions. Let the assistant call them with natural language queries. The assistant doesn't need to know Cypher or the full ONTOLOGY.md unless it's constructing custom queries — and `queries.py` means it shouldn't need to.

---

## Recipes

### Start a new investigation

```bash
mkdir my-investigation && cd my-investigation
cp -r /path/to/investigation-graph/* .
bash setup.sh
# Edit ONTOLOGY.md for your beat
mkdir ingest && cp /path/to/documents/* ingest/
python scripts/ingest_folder.py
python scripts/run_analysis.py
```

### Add documents to an existing investigation

```bash
# Drop new documents in ingest/
cp new-documents/*.pdf ingest/

# Re-run ingestion (only processes new files — existing graph is preserved)
python scripts/ingest_folder.py
```

### Find the money trail

```bash
# Search for transactions
python scripts/search_cli.py -q "$" --type transaction

# Find paths between a person and a company
python scripts/search_cli.py --path "Robert Chen" "Meridian Holdings"

# Semantic search for financial activity
python scripts/search_cli.py -q "payments consulting fees" --mode semantic
```

### Check for contradictions

```bash
# Run analysis — contradictions section shows conflicting claims
python scripts/run_analysis.py | grep -A5 "CONTRADICTIONS"
```

### Trim the hairball for visualization

When your graph has thousands of edges, direct visualization is unusable — a "hairball" of overlapping lines where nothing is readable. The skeleton extractor removes edges in order of decreasing betweenness centrality, keeping only the structural backbone:

```python
# In a Python script or REPL
from investigation_graph.graph import Graph
from investigation_graph.topology import export_skeleton_json
import json

graph = Graph()
skeleton = export_skeleton_json(graph, max_edges=200)
print(f"Reduced {skeleton['original_edges']} edges to {skeleton['skeleton_edges']} "
      f"({skeleton['reduction']:.0%} reduction)")

# Export for D3, vis-network, Gephi, etc.
with open("skeleton.json", "w") as f:
    json.dump(skeleton, f, indent=2)
```

The skeleton preserves all nodes and the highest-betweenness edges — the structural bridges that define your investigation's shape. Low-weight, redundant edges are removed first.

### Query the graph at a point in time

Investigations span months. Witnesses change stories, early facts get disproven. The graph stores `created_at` timestamps on all edges and reserves `expired_at` for soft-expiry (marking relationships as superseded without deleting them).

```python
# What did the graph look like on October 1st?
# (only edges created before that date, excluding expired ones)
import time
from datetime import datetime

cutoff = int(datetime(2024, 10, 1).timestamp())
graph = Graph()
results = graph.query("""
    MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
    WHERE r.created_at <= $cutoff AND r.expired_at = 0
    RETURN a.label, r.edge_type, b.label, r.created_at
    ORDER BY r.created_at DESC LIMIT 20
""", parameters={"cutoff": cutoff})
```

To mark a relationship as superseded (e.g., a witness recanted):

```python
# Soft-expire the old claim, add the new one
now = int(time.time())
graph.query("""
    MATCH (a:Entity {label: $claim})-[r:RELATES_TO]->(b:Entity)
    SET r.expired_at = $now
""", parameters={"claim": "No payments were made", "now": now})
```

The old relationship remains in the graph for the audit trail. Current queries filter on `expired_at = 0`; historical queries drop the filter.

### Export the graph for sharing

```bash
# The graph lives at data/graph.lbug — copy it to share with colleagues
# (encrypted transfer only for sensitive investigations)
cp -r data/graph.lbug /encrypted-usb/investigation-backup/
```

### Back up your investigation

```bash
# The entire investigation state is in data/ and briefings/
tar czf investigation-backup-$(date +%Y%m%d).tar.gz data/ briefings/ ONTOLOGY.md
```

---

## Troubleshooting

### "Ollama: NOT RUNNING"

Start Ollama: `ollama serve` (runs in background). Then pull models:

```bash
ollama pull nomic-embed-text
ollama pull llama3.2:3b
```

### "spaCy model: MISSING"

```bash
source .venv/bin/activate
python -m spacy download en_core_web_sm
```

### "LLM extraction failed: model not found"

The configured model isn't pulled in Ollama. Check `investigation_graph/config.py` for `LOCAL_EXTRACTION_MODEL` and pull it:

```bash
ollama pull llama3.2:3b
```

### Ingestion is slow

Most time is spent on LLM extraction (Phase 3). Options:
- Use a smaller model: set `LOCAL_EXTRACTION_MODEL = "llama3.2:1b"` in config.py
- Skip Phase 3 entirely for bulk imports and re-run later
- If you have a GPU, Ollama will use it automatically

### Too many entities of one type

Check `validate_ontology.py` output. If CI (class imbalance) is above 0.5, one type is catching everything. Fix by:
1. Adding better exotypical examples to ONTOLOGY.md for the dominant type
2. Adding new types that the dominant type is absorbing

### PDF ingestion doesn't work

Install `pdftotext`:

```bash
# Ubuntu/Debian
sudo apt install poppler-utils

# macOS
brew install poppler
```

---

## File Reference

```
investigation-graph/
├── ONTOLOGY.md                    # Entity and edge type definitions (you edit this)
├── README.md                      # This file
├── LICENSE                        # MIT
├── requirements.txt               # Python dependencies
├── setup.sh                       # One-command setup script
├── investigation_graph/
│   ├── __init__.py                # Package init (version 0.1.0)
│   ├── config.py                  # All configuration (paths, models, thresholds)
│   ├── ontology.py                # ONTOLOGY.md parser + write-time validator
│   ├── graph.py                   # LadybugDB wrapper (schema, CRUD, vector search, bulk load)
│   ├── embed.py                   # Ollama embedding wrapper (single + batch)
│   ├── extract.py                 # Three-phase extraction pipeline
│   ├── topology.py                # NetworkX graph analysis
│   ├── briefing.py                # Daily briefing markdown generator
│   ├── queries.py                 # All Cypher query patterns (centralized)
│   └── check.py                   # Dependency verification
├── scripts/
│   ├── ingest_folder.py           # Main entry point: documents → graph
│   ├── search_cli.py              # Search: keyword, semantic, hybrid, path
│   ├── run_analysis.py            # Topology analysis with report output
│   ├── daily_briefing.py          # Generate daily briefing markdown
│   └── validate_ontology.py       # Ontology health check (ICR/CI/IPR)
├── docs/
│   └── privacy-guide.md           # Detailed privacy mode comparison
├── data/                          # Graph database (gitignored)
├── ingest/                        # Drop documents here (gitignored)
└── briefings/                     # Generated briefings (gitignored)
```

---

## Contributing

Issues and PRs welcome. Keep it simple — this is a tool for investigators and researchers, not a framework for developers.

## License

**Code** — MIT (see `LICENSE`). The ingestion pipeline, resolution cascade, and
the FollowTheMoney crosswalk are MIT and free to reuse.

**Data** — MIT does *not* cover external datasets you pull through the tool. In
particular, **OpenSanctions data is CC BY-NC 4.0** (with a journalism exemption).
This project ships *code only* and bundles no sanctions data; if you enable
external-entity linking you supply your own OpenSanctions snapshot under its own
license. Don't infer that the root MIT file makes any data you pull through the
tool permissive — it doesn't.

## Contact

Built by [Ben West](https://benwest.blog). Reach out at [benwest.bsky.social](https://bsky.app/profile/benwest.bsky.social) if you want help setting it up for your newsroom, team, or investigation.
