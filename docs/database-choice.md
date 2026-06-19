# The Database: a DuckDB + LadybugDB Hybrid

You don't choose a database. The toolkit always uses the same two-part store, so
there's one well-trodden path and nothing to misconfigure. This note explains
what the two parts are and why — useful if you're curious or extending the tool.

---

## The two parts

```
            your documents
                  │
                  ▼
   ┌──────────────────────────┐
   │  DuckDB  (the base)      │   data/chunks.duckdb  — a single file
   │  • document text chunks  │
   │  • embeddings (vectors)  │   keyword (BM25) + semantic (vector) search
   │  • full-text search      │   live here; this is the source of truth
   │  • the record set        │   (documents, entities, edges)
   └───────────┬──────────────┘
               │ rebuilt into ▼
   ┌──────────────────────────┐
   │ LadybugDB (the graph)    │   data/graph.lbug  — a directory
   │ • entities (people, orgs)│
   │ • typed relationships    │   path-finding and topology (gaps, bridges,
   │ • provenance edges       │   communities) run here
   └──────────────────────────┘
```

- **DuckDB is the source of truth.** Every chunk, embedding, and extracted
  record lives here. It's one file — back it up with a plain copy.
- **The graph is a rebuilt projection.** Each ingest rebuilds `graph.lbug` from
  the DuckDB records. You never edit the graph directly; it's derived. (This also
  sidesteps a LadybugDB edge-write corruption mode — see `../SPEC.md` §2.1.)

## Why this pairing

- **DuckDB** gives fast, reliable hybrid retrieval out of the box: BM25
  full-text + HNSW vector search, fused with Reciprocal Rank Fusion. One
  embedded file, no server.
- **LadybugDB** is a real graph database (Cypher queries, typed edges). The
  investigative payoff — "how is X connected to Y", "what's structurally
  missing" — is graph-shaped, and that's what it's good at.

Using both means each does what it's best at, and the whole investigation is two
files/directories under `data/` that you can encrypt, copy, or move as a unit.

## Backup

```bash
# The entire investigation state:
tar czf investigation-$(date +%Y%m%d).tar.gz data/ ONTOLOGY.md
```

## Embedding model

One model, fixed per graph (default `nomic-embed-text`, 768-dim — runs locally
via Ollama). Mixing embedding models corrupts retrieval, so the dimension is set
once in `investigation_graph/config.py` (`EMBEDDING_DIM`) and used everywhere. To
switch models, change the model + dimension together and re-ingest.

## Extending

The store lives in `investigation_graph/chunk_store.py` (DuckDB) and
`investigation_graph/graph.py` (the LadybugDB projection). Both build on the shared
`kg-common` library, which supplies the corruption-guarded graph writer, the
ontology contract, entity resolution, and the grounding gate.
