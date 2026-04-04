# open-newsroom-graph

A privacy-first knowledge graph toolkit for investigative journalists. Ingest documents, extract entities and relationships, build a searchable graph, and find structural gaps that suggest leads. Runs entirely on your laptop.

**No cloud required. No accounts. No data leaves your machine.**

## What This Does

You have a pile of documents — court filings, corporate registrations, leaked emails, public records. You need to find connections and, more importantly, find what's *missing*.

This toolkit:

1. **Ingests** your documents (PDF, text, markdown, HTML)
2. **Extracts** people, organizations, transactions, and the relationships between them
3. **Builds** a searchable knowledge graph on your machine
4. **Analyzes** the graph structure to find gaps, contradictions, and surprising connections
5. **Briefs** you daily with a markdown summary of what the graph found

## Quick Start

### Prerequisites

- Python 3.10 or later
- [Ollama](https://ollama.com) installed (handles all AI locally)
- Basic comfort with the command line

### Setup (15 minutes)

```bash
# Clone the repo
git clone https://github.com/M0nkeyFl0wer/open-newsroom-graph.git
cd open-newsroom-graph

# Run setup (installs Python packages + downloads local AI models)
bash setup.sh

# Verify everything works
python -m newsroom_graph.check
```

The setup script installs: KuzuDB (graph database), sqlite-vec (semantic search), spaCy (language processing), NetworkX (graph analysis), and pulls the Ollama models for local embedding and extraction.

### Ingest Your First Documents

```bash
# Drop documents into the ingest folder
cp /path/to/your/documents/*.pdf ingest/

# Run ingestion
python scripts/ingest_folder.py

# See what was extracted
python scripts/search_cli.py --query "show all entities" --limit 20
```

### Search the Graph

```bash
# Keyword search
python scripts/search_cli.py --query "Acme Corp"

# Find connections between two entities
python scripts/search_cli.py --path "Jane Smith" "Harbor Development LLC"

# Semantic search (finds related content even without exact keyword matches)
python scripts/search_cli.py --query "payments to contractors" --mode semantic
```

### Run Analysis

```bash
# Find gaps, contradictions, and structural insights
python scripts/run_analysis.py

# Output: analysis-report.md in your working directory
```

### Daily Briefing

```bash
# Generate today's briefing
python scripts/daily_briefing.py

# Output: briefings/2026-04-03.md
# Also copies to your Obsidian vault if configured
```

## The Seven Stages

### 1. Ontology — What matters
Edit `ONTOLOGY.md` to define entity types and relationship types for your beat. Ships with a general investigative ontology. The system rejects entities that don't match your ontology — no junk accumulates.

### 2. Embeddings — Semantic understanding
Documents are converted to numerical vectors using a local AI model (Ollama + nomic-embed-text). These power semantic search — finding documents by meaning, not just keywords. All local, nothing leaves your machine.

### 3. Search and Fetch — Growing the graph
Drop documents in the ingest folder. The pipeline extracts entities in three passes: structural (dates, proper nouns), NLP (spaCy named entity recognition), and LLM (relationship extraction via local Ollama model). Each entity traces back to its source document.

### 4. Assessment and Ingestion — Quality control
Every entity is validated against the ontology. Duplicates are flagged. Confidence scores track extraction quality. The rejection log tells you what the pipeline struggles with — useful signal for extending your ontology.

### 5. Pruning and Path — Keeping it clean
Unlinked entities get flagged for review. Path search finds typed chains of connection between entities — not just "these are related" but "X was employed by A, A contracted with B, B is owned by Y." Each hop cites a source document.

### 6. Topology — Finding what's missing
Graph analysis finds structural gaps: communities that should connect but don't, entities that bridge otherwise separate networks, contradictions between sources. The math is deterministic — no AI guessing, just structure.

### 7. Daily Briefing — What the graph found
A markdown file summarizing: new entities, contradictions found, structural gaps (as investigative leads), and entities with surprising structural importance. Readable in Obsidian, any text editor, or the terminal.

## Privacy

**Default: fully local.** All AI runs via Ollama on your machine. No API keys. No cloud. No data transmission.

**Optional: remote extraction.** For non-sensitive documents where you want higher quality entity extraction, you can configure a remote LLM with zero-data-retention. See `docs/privacy-guide.md` for details. The graph, embeddings, and analysis always stay local regardless.

**Newsroom mode.** Run on a shared server for your team. See `docs/sharing-guide.md`. Multiple journalists ingest documents, everyone searches the same graph. Like a shared research library that knows what's connected — and what isn't.

## Configuration

Edit `newsroom_graph/config.py`:

```python
# Privacy mode: "local" (default), "hybrid", or "remote"
PRIVACY_MODE = "local"

# Obsidian vault path (for daily briefing delivery)
OBSIDIAN_VAULT = ""  # e.g., "~/obsidian-vault/investigations"

# Analysis schedule
AUTO_ANALYSIS = False  # Set True to run analysis after every ingestion
```

## Extending the Ontology

See `docs/extending-ontology.md` and the examples in `docs/examples/`:
- Campaign finance investigations
- Real estate and property investigations
- Corporate accountability investigations

## The Stack

All open source. All installable with pip (except Ollama).

| Tool | Purpose | Install |
|------|---------|---------|
| [KuzuDB](https://kuzudb.com) | Graph database | `pip install kuzu` |
| [sqlite-vec](https://github.com/asg017/sqlite-vec) | Vector search | `pip install sqlite-vec` |
| [spaCy](https://spacy.io) | NLP extraction | `pip install spacy` |
| [NetworkX](https://networkx.org) | Graph analysis | `pip install networkx` |
| [Ripser](https://ripser.scikit-tda.org) | Persistent homology | `pip install ripser` |
| [Ollama](https://ollama.com) | Local AI models | [ollama.com/download](https://ollama.com/download) |
| [Obsidian](https://obsidian.md) | Reading/writing (optional) | [obsidian.md](https://obsidian.md) |

## Contributing

Issues and PRs welcome. Keep it simple — this is a tool for journalists, not a framework for developers.

## License

MIT

## Contact

Built by [Ben West](https://benwest.blog). Reach out at [benwest.bsky.social](https://bsky.app/profile/benwest.bsky.social) if you want help setting it up for your newsroom.
