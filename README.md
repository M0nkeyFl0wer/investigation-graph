# open-newsroom-graph

A privacy-first knowledge graph toolkit for investigative journalists. Ingest documents, extract entities and relationships, build a searchable graph, and find structural gaps that suggest leads. Runs entirely on your laptop.

**No cloud required. No accounts. No data leaves your machine.**

<a href="https://ladybugdb.com"><img src="https://ladybugdb.com/img/logo.svg" alt="LadybugDB" height="50"></a>&nbsp;&nbsp;&nbsp;
<a href="https://networkx.org"><img src="https://networkx.org/documentation/stable/_static/networkx_logo.svg" alt="NetworkX" height="50"></a>&nbsp;&nbsp;&nbsp;
<a href="https://ollama.com"><img src="https://ollama.com/public/ollama.png" alt="Ollama" height="50"></a>

> **Research context:** Inspired by [*An Alternative Trajectory for Generative AI*](https://arxiv.org/abs/2603.14147) (Belova et al., Princeton, 2026), which proposes domain-specific superintelligence built on knowledge graphs and formal logic rather than monolithic LLMs. This toolkit applies that vision to investigative journalism: a local, specialized knowledge graph where every entity traces back to a source document, every connection is typed and auditable, and structural gaps — found through topology, not AI guessing — become investigative leads. *"Intelligence arises from manipulating relational symbolic structures, abstracting away low-level sensory details."*

## What This Does

You have a pile of documents — court filings, corporate registrations, leaked emails, public records. You need to find connections and, more importantly, find what's *missing*.

This toolkit:

1. **Ingests** your documents (PDF, text, markdown, HTML)
2. **Extracts** people, organizations, transactions, and the relationships between them
3. **Builds** a searchable knowledge graph on your machine
4. **Analyzes** the graph structure to find gaps, contradictions, and surprising connections
5. **Briefs** you daily with a markdown summary of what the graph found

---

## Quick Start

### Prerequisites

- **Python 3.10 or later** (check: `python3 --version`)
- **[Ollama](https://ollama.com)** installed and running (handles all AI locally)
- **Basic comfort with the command line** (everything runs via terminal)

### Setup

```bash
# Clone the repo
git clone https://github.com/M0nkeyFl0wer/investigative-journalism-kg.git
cd open-newsroom-graph

# Run setup (installs Python packages + downloads local AI models)
bash setup.sh

# Verify everything works
python -m newsroom_graph.check
```

You should see:

```
open-newsroom-graph system check
========================================
  LadybugDB: 0.15.3
  PyArrow: 23.0.1
  spaCy: 3.8.14
  spaCy model: en_core_web_sm OK
  NetworkX: 3.6.1
  Ripser: not installed (optional, pip install ripser)
  Ollama: OK (2 models)
  Embedding model: nomic-embed-text OK

Ontology: Ontology(8 entity types, 14 edge types)
  All checks passed.
```

If anything says NOT INSTALLED or MISSING, the check tells you exactly what to run.

### Ingest Your First Documents

```bash
# Drop documents into the ingest folder
cp /path/to/your/documents/*.pdf ingest/
cp /path/to/your/documents/*.txt ingest/

# Run ingestion
python scripts/ingest_folder.py
```

Output looks like:

```
Found 3 documents to ingest.

[1/3] harbor-city-expose.txt
  Extracted: 27 entities, 13 edges
  Embedded: 2 chunks
[2/3] property-records.md
  Extracted: 21 entities, 8 edges
  Embedded: 2 chunks
[3/3] financial-disclosure.html
  Extracted: 32 entities, 8 edges
  Embedded: 2 chunks

Bulk loading 80 entities...
  Loaded: 80
Computing entity embeddings...
Loading 29 edges...
  Loaded: 29

==================================================
Ingestion complete in 99.3s.
  Documents processed: 3
  Total entities:      80
  Total edges:         28
  Total documents:     3
```

### Search the Graph

```bash
# Keyword search — finds exact matches
python scripts/search_cli.py -q "Acme Corp"

# Semantic search — finds related content even without keyword match
python scripts/search_cli.py -q "payments to contractors" --mode semantic

# Hybrid search — combines keyword and semantic, best of both
python scripts/search_cli.py -q "financial fraud" --mode hybrid

# Find connections between two entities
python scripts/search_cli.py --path "Jane Smith" "Harbor Development LLC"

# Filter by entity type
python scripts/search_cli.py -q "Chen" --type person
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

Edit `ONTOLOGY.md` to define entity types and relationship types for your beat. Ships with a general investigative journalism ontology covering 8 entity types and 14 edge types.

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

Embeddings are stored directly in the graph database as `FLOAT[768]` columns. No separate vector database. One database for everything.

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

Three search modes:

| Mode | How it works | Best for |
|------|-------------|----------|
| `keyword` | Cypher `CONTAINS` match on entity labels | Finding specific entities by name |
| `semantic` | Cosine similarity between query embedding and entity embeddings | Finding related entities without knowing their name |
| `hybrid` | Reciprocal Rank Fusion (RRF) — ranks by position across both lists, no weight tuning needed | Best general-purpose search |

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

Everything runs on your machine. No network connections. No API keys. No accounts.

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
# In newsroom_graph/config.py
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

Two risks that automated extraction creates for investigative journalists:

**Identity ambiguity.** The pipeline will extract "John Smith", "J. Smith", and "John S. Smith" as three separate entities. It may also split "BP US" and "British Petroleum" into different organizations. Before publishing any finding based on graph connections, **manually verify that linked entities are actually the same person or organization.** Misattributing connections in an automated graph can falsely accuse individuals. The deduplication threshold in `config.py` (`DEDUP_THRESHOLD = 0.92`) catches some duplicates via embedding similarity, but it is not sufficient for names that are similar but refer to different people.

**Triangulation risk.** Combining multiple datasets (public records + leaked internal emails + confidential source interviews) creates a graph where the structural position of entities can inadvertently reveal confidential sources. If you publish a subset of the graph — even with names redacted — the unique pattern of connections around a source may be enough for an adversary to identify who leaked the information. Before sharing any graph visualization or export:

- Review whether the structural layout reveals source identity through unique relational positions
- Consider removing or generalizing edges that trace back to confidential sources
- Remember that even aggregate statistics (community membership, betweenness scores) can narrow down candidates

**The graph is an intelligence product.** Treat it with the same operational security as your source list.

---

## Configuration

All configuration lives in `newsroom_graph/config.py`:

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
| [LadybugDB](https://ladybugdb.com) | 0.15.3 | Graph database + vector storage | Embedded columnar graph DB. Cypher queries. Native `FLOAT[768]` vector columns with `array_cosine_similarity`. No server. One directory = one investigation. Continuation of KuzuDB. |
| [PyArrow](https://arrow.apache.org) | 23.0+ | Bulk data loading | LadybugDB's `COPY FROM` Parquet is 25x faster than iterative inserts. PyArrow writes the Parquet files. |
| [Pandas](https://pandas.pydata.org) | 3.0+ | Data manipulation | DataFrame operations for bulk entity preparation before Parquet export. |
| [spaCy](https://spacy.io) | 3.8+ | NLP extraction (Phase 2) | Named entity recognition. `en_core_web_sm` model — small, fast, good enough for people/orgs/locations. |
| [NetworkX](https://networkx.org) | 3.6+ | Graph analysis | Louvain communities, betweenness centrality, bridge detection, connected components. Runs on the extracted graph. |
| [Ripser](https://ripser.scikit-tda.org) | 0.6+ | Persistent homology (optional) | Finds topological holes — higher-order structural gaps that community detection misses. |
| [Ollama](https://ollama.com) | 0.3+ | Local AI models | Runs embedding + extraction models on your hardware. No API keys. No cloud. |
| [Obsidian](https://obsidian.md) | any | Reading/writing (optional) | If configured, daily briefings auto-copy to your Obsidian vault inbox. |

### Why LadybugDB instead of Neo4j/SQLite/etc?

- **Embedded**: No server process. The database is a directory on disk. Copy it, back it up, encrypt it.
- **Cypher**: Industry-standard graph query language. Transferable knowledge.
- **Native vectors**: `FLOAT[768]` columns with `array_cosine_similarity` — no separate vector database needed.
- **Bulk loading**: `COPY FROM` Parquet files is 25x faster than row-by-row inserts. Matters when ingesting 200+ documents.
- **Single database**: Graph + vectors + metadata in one place. One directory = one investigation.

### Why not a cloud graph database?

Your investigation data — leaked documents, source identities, financial records — should not be on someone else's server. This toolkit is designed so that **nothing leaves your machine** in the default configuration.

---

## Architecture

```
ONTOLOGY.md                    ← You edit this
    │
    ▼
newsroom_graph/ontology.py     ← Parses types, validates at write time
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

**All Cypher queries are pre-built and parameterized** in `newsroom_graph/queries.py`. No dynamic Cypher generation anywhere in the codebase. This means:

- No query injection
- No LLM hallucinating Cypher syntax
- Every query the system runs is auditable — read `queries.py` to see exactly what it does

### Database schema

```
Entity (Node Table)
├── id: STRING (primary key, SHA256 hash)
├── entity_type: STRING (validated against ONTOLOGY.md)
├── label: STRING
├── description: STRING
├── confidence: DOUBLE (0.0-1.0)
├── source_url: STRING (which document)
├── provenance: STRING (which extraction phase)
├── created_at: INT64 (unix timestamp)
├── updated_at: INT64
├── embedding: FLOAT[768] (nomic-embed-text vector)
└── layer: STRING (reserved for future semantic layering)

Document (Node Table)
├── id: STRING (primary key)
├── path: STRING
├── title: STRING
├── ingested_at: INT64
└── chunk_count: INT32

Chunk (Node Table)
├── id: STRING (primary key)
├── doc_id: STRING
├── text: STRING
├── chunk_index: INT32
├── created_at: INT64
└── embedding: FLOAT[768]

RELATES_TO (Edge Table: Entity → Entity)
├── edge_type: STRING (EMPLOYED_BY, FUNDED_BY, etc.)
├── weight: DOUBLE
├── confidence: DOUBLE
├── source_url: STRING
├── provenance: STRING
├── created_at: INT64
└── expired_at: INT64 (reserved for future soft-expiry)

MENTIONED_IN (Edge Table: Entity → Document)
CHUNK_OF (Edge Table: Chunk → Document)
```

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
cp -r /path/to/open-newsroom-graph/* .
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
from newsroom_graph.graph import Graph
from newsroom_graph.topology import export_skeleton_json
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

The configured model isn't pulled in Ollama. Check `newsroom_graph/config.py` for `LOCAL_EXTRACTION_MODEL` and pull it:

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
open-newsroom-graph/
├── ONTOLOGY.md                    # Entity and edge type definitions (you edit this)
├── README.md                      # This file
├── LICENSE                        # MIT
├── requirements.txt               # Python dependencies
├── setup.sh                       # One-command setup script
├── newsroom_graph/
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

Issues and PRs welcome. Keep it simple — this is a tool for journalists, not a framework for developers.

## License

MIT

## Contact

Built by [Ben West](https://benwest.blog). Reach out at [benwest.bsky.social](https://bsky.app/profile/benwest.bsky.social) if you want help setting it up for your newsroom.
