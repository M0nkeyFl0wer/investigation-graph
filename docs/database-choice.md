# Choosing Your Database Substrate

This guide helps you pick the right database for your needs. The graph (relationships between entities) always lives in LadybugDB, but you have choices for where to store document chunks and embeddings.

---

## Quick Decision

| You want... | Choose |
|-------------|--------|
| Simple, reliable, just works | **SQLite** |
| More power, future flexibility | **DuckDB** |
| Multiple people sharing | **Postgres** |
| Prototyping, very small data | **Ladybug only** |

---

## Option Comparison

### SQLite — The Simple Choice

**Best for:** Single user, retrieval-focused, want things to just work

| Pros | Cons |
|------|------|
| FTS5 is extremely reliable | Not designed for complex analytics |
| sqlite-vec handles vectors well | Less flexibility for future needs |
| No extra setup required | |
| One file, easy to backup | |

**Setup:** Just works. No server needed.

---

### DuckDB — The Flexible Choice

**Best for:** Want analytical power, comfortable with slight technical complexity

| Pros | Cons |
|------|------|
| ATTACH from Cypher — seamless graph integration | Vector search (HNSW) needs experimental flag |
| Excellent for bulk operations | Slightly more complex |
| COPY FROM Parquet is extremely fast | Some features still maturing |

**Setup:** Requires enabling experimental features for vector search.

---

### Postgres — The Team Choice

**Best for:** Multiple users, larger investigations, need concurrent access

| Pros | Cons |
|------|------|
| Most powerful search (tsvector + pgvector) | Requires server setup |
| Handles concurrent reads/writes well | More maintenance |
| Mature tooling (scheduled jobs, monitoring) | Not "copy folder and go" |

**Setup:** Requires installing and configuring PostgreSQL.

---

### Ladybug Only — The Legacy Choice

**Best for:** Prototyping, very small datasets (<100 documents)

| Pros | Cons |
|------|------|
| Simplest setup | Limited FTS and vector search |
| Everything in one place | Not recommended for production |

**Note:** Not recommended for new projects. Choose SQLite, DuckDB, or Postgres instead.

---

## How to Change

Edit `newsroom_graph/config.py`:

```python
# Change this line:
CHUNK_SUBSTRATE = "sqlite"  # or "duckdb", "postgres", "ladybug"
```

If you switch substrates later, you'll need to re-run ingestion to populate the new chunk store. The graph data (entities and relationships) will be preserved.

---

## Need Help?

If you're not sure, start with **SQLite**. You can always switch to DuckDB or Postgres later if your needs change. The retrieval improvements (hybrid search combining keyword and vector) will make a big difference regardless of which you pick.