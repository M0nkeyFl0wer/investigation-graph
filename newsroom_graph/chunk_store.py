"""
DuckDB chunk store — the *base* of the DuckDB(base) + LadybugDB(graph) hybrid.

DuckDB is the source of truth for chunk text, embeddings, and full-text search.
LadybugDB (see ``graph.py``) holds the entity/edge graph and references chunks
and documents by id. There is **no substrate choice**: the graph is always this
hybrid (see ``SPEC.md``). The earlier multi-substrate (sqlite/postgres) code was
removed — accessibility for non-experts means one well-trodden path, not a knob.

This is a faithful port of the proven pattern in
``second-brain-hybrid-graph/second_brain/chunk_store.py``, adapted to this
project's config and commented for an operator who is not a database engineer.

Why each design choice (all hard-won — see the ``duckdb-rag`` and ``ladybug``
skills):

- **Fixed-width ``FLOAT[dim]`` embeddings**, dimension from ``config.EMBEDDING_DIM``.
  Only fixed-width vectors are HNSW-indexable; a variable ``FLOAT[]`` is not.
- **Parquet COPY** for bulk inserts — orders of magnitude faster than per-row
  INSERT, and the one bulk-load idiom shared with LadybugDB.
- **BM25 full-text search** via the ``fts`` extension. FTS does NOT auto-update
  on INSERT, so we rebuild the index after every batch with ``overwrite=1``.
- **In-memory HNSW built at boot**, not persisted. Persistent HNSW is flagged
  experimental in DuckDB and can corrupt on crash-during-write; for the corpus
  sizes a single investigator handles, an in-memory build is sub-second.
- **Two handles for reads**: a persistent read-only handle for BM25, and an
  in-memory handle for HNSW (built from the on-disk embeddings). They are fused
  with Reciprocal Rank Fusion (RRF) in Python — no weight tuning needed.
- **DELETE + INSERT to re-embed** a chunk. HNSW-indexed columns block UPDATE,
  so changing an embedding means delete-then-insert, never SET.
- **Deterministic UUID5 chunk ids** from ``source_uri`` + position, so the same
  chunk always gets the same id and re-ingestion is idempotent.

Concurrency: DuckDB allows exactly one writer process. This store opens a fresh
read-write handle per write call and closes it immediately, so it never holds a
write lock open across reads. A single CLI process therefore ingests (write),
then searches (read) without contention. Do not interleave a live read-only
handle with a write in the same process — DuckDB refuses ("Can't open with
different config").
"""

import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

from . import config

# RRF smoothing constant (Cormack 2009). Higher = flatter fusion between BM25 and
# vector ranks; lower favours each method's top hits. Sourced from config so an
# operator can tune it in one place.
RRF_K = getattr(config, "RRF_K", 60)


def _ensure_ext(conn: duckdb.DuckDBPyConnection, name: str) -> None:
    """INSTALL (first run, needs network once) then LOAD a DuckDB extension.

    Tolerant: if the extension is already present, INSTALL is a fast no-op; if
    install fails (offline), we still try LOAD so a pre-installed extension works.
    Keeping this auto-install means a non-expert user never sees a raw
    'INSTALL vss' error.
    """
    try:
        conn.execute(f"INSTALL {name};")
    except Exception:
        pass
    conn.execute(f"LOAD {name};")


def chunk_id_from_uri(uri: str, position: int) -> str:
    """Deterministic UUID5 chunk id from a source URI + chunk position.

    The same (document, position) always yields the same id, so re-ingesting a
    document overwrites its chunks rather than duplicating them.
    """
    # Fixed namespace UUID (the RFC-4122 example namespace) — any constant works,
    # it just has to be stable across runs.
    namespace = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    return str(uuid.uuid5(namespace, f"{uri}:{position}"))


class ChunkStore:
    """DuckDB-backed chunk store with BM25 + HNSW hybrid retrieval.

    Usage:
        # Writer (single process at a time)
        store = ChunkStore()           # path + dim come from config
        store.init_schema()            # idempotent
        store.write_chunks(chunks)     # bulk Parquet COPY

        # Reader (after writes are closed)
        hits = store.search_hybrid("payments to contractors", query_embedding)
    """

    def __init__(
        self,
        db_path: str | Path | None = None,
        read_only: bool = False,
        embedding_dim: int | None = None,
    ):
        # Default location lives beside the graph database, under data/.
        self.db_path = Path(db_path) if db_path else (config._PROJECT_ROOT / "data" / "chunks.duckdb")
        self.read_only = read_only
        # Dimension is parameterized (never hardcoded in DDL) so switching the
        # embedding model — e.g. nomic-embed-text (768) to qwen3-embedding (4096)
        # — is a config change, not a schema rewrite.
        self.embedding_dim = int(embedding_dim if embedding_dim is not None else config.EMBEDDING_DIM)
        if self.embedding_dim <= 0:
            raise ValueError("embedding_dim must be positive")
        # Lazily-opened handles (see module docstring for the two-handle pattern).
        self._ro: Optional[duckdb.DuckDBPyConnection] = None   # persistent read-only (BM25)
        self._mem: Optional[duckdb.DuckDBPyConnection] = None   # in-memory (HNSW)

    # =========================================================================
    # Connection handles
    # =========================================================================

    def _open_ro(self) -> duckdb.DuckDBPyConnection:
        """Open (once) the persistent read-only handle used for BM25 queries."""
        if self._ro is None:
            self._ro = duckdb.connect(str(self.db_path), read_only=True)
            try:
                _ensure_ext(self._ro, "fts")
            except Exception:
                # fts not available; FTS queries will no-op until the writer has
                # installed/built the index.
                pass
        return self._ro

    def _open_mem(self) -> duckdb.DuckDBPyConnection:
        """Open (once) an in-memory handle holding an HNSW index over embeddings.

        Embeddings are pulled through the already-open read-only handle as Arrow
        and materialized in memory. We deliberately do NOT ``ATTACH`` the file:
        the persistent ``_ro`` handle already holds it open, and DuckDB forbids a
        second connection ATTACHing a file another holds open as its main DB.
        """
        if self._mem is None:
            mem = duckdb.connect(":memory:")
            _ensure_ext(mem, "vss")
            ro = self._open_ro()
            # Pull only rows that actually have an embedding.
            vec_arrow = ro.execute(
                "SELECT id, embedding FROM chunk WHERE embedding IS NOT NULL"
            ).arrow()
            mem.register("chunk_vec_src", vec_arrow)
            mem.execute("CREATE TABLE chunk_vec AS SELECT * FROM chunk_vec_src;")
            mem.unregister("chunk_vec_src")
            # Build the HNSW index in memory (sub-second at investigator scale).
            mem.execute(
                """
                CREATE INDEX chunk_emb_hnsw ON chunk_vec
                USING HNSW (embedding)
                WITH (metric = 'cosine', ef_construction = 200, M = 32);
                """
            )
            self._mem = mem
        return self._mem

    def _open_rw(self) -> duckdb.DuckDBPyConnection:
        """Open a fresh read-write handle. Caller MUST close it (see write methods)."""
        conn = duckdb.connect(str(self.db_path), read_only=False)
        try:
            _ensure_ext(conn, "vss")
        except Exception:
            pass
        return conn

    # =========================================================================
    # Schema
    # =========================================================================

    def init_schema(self) -> None:
        """Create the chunk table, its indexes, and the BM25 FTS index.

        Idempotent — safe to call on every run. Embedding lives on the chunk row
        itself (one table, not a side table) so a chunk and its vector move
        together.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        rw = self._open_rw()
        try:
            try:
                _ensure_ext(rw, "fts")
            except Exception:
                pass

            # Note the f-string only interpolates the integer dimension — never
            # user input — so there is no injection surface here.
            rw.execute(
                f"""
                CREATE TABLE IF NOT EXISTS chunk (
                    id            VARCHAR PRIMARY KEY,   -- deterministic UUID5
                    doc_id        VARCHAR NOT NULL,      -- FK to a Document in the graph
                    source_uri    VARCHAR NOT NULL,      -- where the operator can re-find it
                    title         VARCHAR,
                    body          VARCHAR NOT NULL,      -- the chunk text (for FTS + display)
                    chunk_index   INTEGER NOT NULL,      -- position within the document
                    entity_ids    VARCHAR,               -- JSON array of linked entity ids
                    embedding     FLOAT[{self.embedding_dim}],  -- fixed-width => HNSW-able
                    sensitivity   VARCHAR DEFAULT 'public',     -- public|confirm_before_use|confidential
                    created_at    TIMESTAMP DEFAULT current_timestamp,
                    source_mtime  TIMESTAMP,             -- mtime of the source file at ingest
                    embedded_at   TIMESTAMP              -- when the embedding was computed
                );
                """
            )

            # Hot-path indexes: join chunks to a document; filter by sensitivity (ACL).
            rw.execute("CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id);")
            rw.execute("CREATE INDEX IF NOT EXISTS idx_chunk_sensitivity ON chunk(sensitivity);")

            # BM25 full-text index over body + title. Rebuilt after each batch
            # (FTS does not auto-update on INSERT); overwrite=1 makes it idempotent.
            self._build_fts(rw)
        finally:
            rw.close()

    @staticmethod
    def _build_fts(conn: duckdb.DuckDBPyConnection) -> None:
        """(Re)build the BM25 FTS index. Must run after every batch of inserts."""
        conn.execute(
            """
            PRAGMA create_fts_index(
                'chunk', 'id',
                'body', 'title',
                stemmer = 'porter',
                stopwords = 'english',
                overwrite = 1
            );
            """
        )

    # =========================================================================
    # Writes (bulk Parquet COPY)
    # =========================================================================

    def write_chunks(self, chunks: list[dict[str, Any]]) -> int:
        """Bulk-write chunks via a Parquet COPY, then rebuild the FTS index.

        Each chunk dict requires: id, doc_id, source_uri, body, chunk_index.
        Optional: title, embedding, entity_ids (list), sensitivity, source_mtime,
        embedded_at. Returns the number of chunks written.
        """
        if not chunks:
            return 0

        rw = self._open_rw()
        try:
            now = datetime.now(timezone.utc)
            rows = [
                {
                    "id": c["id"],
                    "doc_id": c["doc_id"],
                    "source_uri": c["source_uri"],
                    "title": c.get("title"),
                    "body": c["body"],
                    "chunk_index": c["chunk_index"],
                    "entity_ids": json.dumps(c.get("entity_ids", [])),
                    "embedding": c.get("embedding"),
                    "sensitivity": c.get("sensitivity", "public"),
                    "created_at": now,
                    "source_mtime": c.get("source_mtime"),
                    # Stamp embedded_at when an embedding is present so stats can
                    # report embedding coverage accurately.
                    "embedded_at": c.get("embedded_at")
                    or (now if c.get("embedding") is not None else None),
                }
                for c in chunks
            ]
            self._copy_rows(rw, rows)
            self._build_fts(rw)
            return len(chunks)
        finally:
            rw.close()

    def upsert_chunk(self, chunk: dict[str, Any]) -> None:
        """Insert or replace a single chunk (delete-then-insert).

        HNSW blocks UPDATE on the embedding column, so re-embedding a chunk means
        removing the old row and inserting the new one. FTS is rebuilt after.
        """
        rw = self._open_rw()
        try:
            rw.execute("DELETE FROM chunk WHERE id = ?", [chunk["id"]])
            now = datetime.now(timezone.utc)
            row = {
                "id": chunk["id"],
                "doc_id": chunk["doc_id"],
                "source_uri": chunk["source_uri"],
                "title": chunk.get("title"),
                "body": chunk["body"],
                "chunk_index": chunk["chunk_index"],
                "entity_ids": json.dumps(chunk.get("entity_ids", [])),
                "embedding": chunk.get("embedding"),
                "sensitivity": chunk.get("sensitivity", "public"),
                "created_at": now,
                "source_mtime": chunk.get("source_mtime"),
                "embedded_at": chunk.get("embedded_at")
                or (now if chunk.get("embedding") is not None else None),
            }
            self._copy_rows(rw, [row])
            self._build_fts(rw)
        finally:
            rw.close()

    def delete_chunks_by_doc_id(self, doc_id: str) -> int:
        """Delete all chunks for a document (used when re-ingesting it)."""
        rw = self._open_rw()
        try:
            count = rw.execute(
                "SELECT count(*) FROM chunk WHERE doc_id = ?", [doc_id]
            ).fetchone()[0]
            rw.execute("DELETE FROM chunk WHERE doc_id = ?", [doc_id])
            return count
        finally:
            rw.close()

    @staticmethod
    def _copy_rows(rw: duckdb.DuckDBPyConnection, rows: list[dict[str, Any]]) -> None:
        """Write rows to the chunk table via a temporary Parquet file + COPY.

        ``INSERT INTO chunk BY NAME SELECT * FROM read_parquet(...)`` matches
        columns by name, so the row dict order does not matter.
        """
        import tempfile

        import pyarrow as pa
        import pyarrow.parquet as pq

        table = pa.Table.from_pylist(rows)
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as f:
            pq.write_table(table, f.name)
            rw.execute("INSERT INTO chunk BY NAME SELECT * FROM read_parquet(?)", [f.name])
            Path(f.name).unlink()

    def set_entity_ids(self, links: dict[str, list[str]]) -> int:
        """Overwrite the entity_ids JSON for the given chunks (chunk_id -> ids).

        Safe as a plain UPDATE: entity_ids is NOT the HNSW-indexed column (the
        disk table carries no persistent HNSW — it is rebuilt in memory), so the
        delete-then-insert dance does not apply here.
        """
        if not links:
            return 0
        rw = self._open_rw()
        try:
            rw.executemany(
                "UPDATE chunk SET entity_ids = ? WHERE id = ?",
                [[json.dumps(sorted(set(ids))), cid] for cid, ids in links.items()],
            )
            return len(links)
        finally:
            rw.close()

    # =========================================================================
    # Reads (BM25 + HNSW + RRF)
    # =========================================================================

    def search_fts(self, query: str, limit: int = 12,
                   sensitivity_filter: Optional[list[str]] = None) -> list[dict[str, Any]]:
        """Keyword (BM25) search via the persistent read-only handle."""
        filters = sensitivity_filter or ["public"]
        ro = self._open_ro()
        filter_sql = ", ".join("?" for _ in filters)
        rows = ro.execute(
            f"""
            SELECT id, rank FROM (
                SELECT chunk.id,
                       fts_main_chunk.match_bm25(id, ?) AS score,
                       ROW_NUMBER() OVER (ORDER BY fts_main_chunk.match_bm25(id, ?) DESC) AS rank
                FROM chunk
                WHERE sensitivity IN ({filter_sql})
            ) t
            WHERE score IS NOT NULL
            ORDER BY rank
            LIMIT ?;
            """,
            [query, query, *filters, limit],
        ).fetchall()
        return [{"id": r[0], "rank": r[1]} for r in rows]

    def search_vector(self, query_embedding: list[float], limit: int = 12) -> list[dict[str, Any]]:
        """Semantic (ANN) search over the in-memory HNSW index.

        The query vector is CAST to ``FLOAT[dim]`` in SQL — a bare Python list
        binds as ``DOUBLE[]`` and ``array_cosine_distance`` has no FLOAT/DOUBLE
        overload, so the cast is mandatory.
        """
        mem = self._open_mem()
        cast = f"CAST(? AS FLOAT[{self.embedding_dim}])"
        rows = mem.execute(
            f"""
            SELECT id, ROW_NUMBER() OVER (ORDER BY array_cosine_distance(embedding, {cast})) AS rank
            FROM chunk_vec
            ORDER BY array_cosine_distance(embedding, {cast})
            LIMIT ?;
            """,
            [query_embedding, query_embedding, limit],
        ).fetchall()
        return [{"id": r[0], "rank": r[1]} for r in rows]

    def search_hybrid(
        self,
        query: str,
        query_embedding: Optional[list[float]] = None,
        sensitivity_filter: Optional[list[str]] = None,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Hybrid retrieval: BM25 + HNSW fused with RRF.

        With no embedding, falls back to BM25 only. Returns chunk dicts with an
        ``rrf_score``, highest first.
        """
        candidates = getattr(config, "VECTOR_CANDIDATES", 50)
        bm25 = {r["id"]: r["rank"] for r in
                self.search_fts(query, limit=candidates, sensitivity_filter=sensitivity_filter)}

        if query_embedding is None:
            # Keyword-only path.
            ids = list(bm25.keys())[:limit]
            return self._hydrate(ids, {cid: 1.0 / (RRF_K + rank) for cid, rank in bm25.items()})

        ann = {r["id"]: r["rank"] for r in self.search_vector(query_embedding, limit=candidates)}

        # Reciprocal Rank Fusion: sum 1/(k+rank) across the lists a chunk appears in.
        rrf: dict[str, float] = {}
        for cid in set(bm25) | set(ann):
            score = 0.0
            if cid in bm25:
                score += 1.0 / (RRF_K + bm25[cid])
            if cid in ann:
                score += 1.0 / (RRF_K + ann[cid])
            rrf[cid] = score

        top_ids = [cid for cid, _ in sorted(rrf.items(), key=lambda kv: kv[1], reverse=True)[:limit]]
        return self._hydrate(top_ids, rrf)

    def _hydrate(self, ids: list[str], score_map: dict[str, float]) -> list[dict[str, Any]]:
        """Fetch full chunk rows for the given ids (order preserved) + attach scores."""
        if not ids:
            return []
        ro = self._open_ro()
        placeholders = ", ".join("?" for _ in ids)
        rows = ro.execute(
            f"""
            SELECT id, doc_id, source_uri, title, body, entity_ids
            FROM chunk WHERE id IN ({placeholders})
            """,
            ids,
        ).fetchall()
        by_id = {r[0]: r for r in rows}
        out = []
        for cid in ids:
            if cid not in by_id:
                continue
            r = by_id[cid]
            out.append({
                "id": r[0],
                "doc_id": r[1],
                "source_uri": r[2],
                "title": r[3],
                "body": r[4],
                "entity_ids": json.loads(r[5]) if r[5] else [],
                "rrf_score": score_map.get(cid, 0.0),
            })
        return out

    def fetch_chunks_for_docs(self, doc_ids: list[str]) -> list[dict[str, Any]]:
        """Return [{id, doc_id, body}] for the given documents (read-only).

        Used by entity<->chunk linking to find which chunks a document's
        entities could be mentioned in. Uses a short-lived read handle.
        """
        if not doc_ids:
            return []
        conn = duckdb.connect(str(self.db_path), read_only=True)
        try:
            placeholders = ", ".join("?" for _ in doc_ids)
            rows = conn.execute(
                f"SELECT id, doc_id, body FROM chunk WHERE doc_id IN ({placeholders})",
                list(doc_ids),
            ).fetchall()
            return [{"id": r[0], "doc_id": r[1], "body": r[2]} for r in rows]
        finally:
            conn.close()

    def get_chunk_by_id(self, chunk_id: str) -> Optional[dict[str, Any]]:
        """Fetch a single chunk by id (read-only)."""
        ro = self._open_ro()
        row = ro.execute(
            """
            SELECT id, doc_id, source_uri, title, body, chunk_index, entity_ids,
                   sensitivity, embedded_at
            FROM chunk WHERE id = ?
            """,
            [chunk_id],
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0], "doc_id": row[1], "source_uri": row[2], "title": row[3],
            "body": row[4], "chunk_index": row[5],
            "entity_ids": json.loads(row[6]) if row[6] else [],
            "sensitivity": row[7], "embedded_at": row[8],
        }

    # =========================================================================
    # Stats / lifecycle
    # =========================================================================

    def chunk_count(self) -> int:
        """Total number of chunks (read-only)."""
        ro = self._open_ro()
        return ro.execute("SELECT count(*) FROM chunk").fetchone()[0]

    def get_stats(self) -> dict[str, Any]:
        """Health snapshot: totals, embedding coverage, sensitivity breakdown."""
        ro = self._open_ro()
        total = ro.execute("SELECT count(*) FROM chunk").fetchone()[0]
        embedded = ro.execute(
            "SELECT count(*) FROM chunk WHERE embedded_at IS NOT NULL"
        ).fetchone()[0]
        sensitivity = dict(
            ro.execute("SELECT sensitivity, count(*) FROM chunk GROUP BY sensitivity").fetchall()
        )
        return {
            "total_chunks": total,
            "embedded_chunks": embedded,
            "unembedded_chunks": total - embedded,
            "sensitivity_counts": sensitivity,
            "db_path": str(self.db_path),
        }

    def backup(self, backup_path: Optional[str] = None) -> Path:
        """Back up the single DuckDB file with a plain copy (no WAL drama)."""
        if backup_path:
            dest = Path(backup_path)
        else:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
            dest = self.db_path.with_suffix(f".duckdb.bak.{stamp}")
        shutil.copy2(self.db_path, dest)
        return dest

    def close(self) -> None:
        """Close the read handles. Write handles are already closed per call."""
        if self._ro is not None:
            self._ro.close()
            self._ro = None
        if self._mem is not None:
            self._mem.close()
            self._mem = None


def get_chunk_store(db_path: str | Path | None = None) -> ChunkStore:
    """Factory: return an initialized DuckDB chunk store (schema ensured)."""
    store = ChunkStore(db_path)
    store.init_schema()
    return store
