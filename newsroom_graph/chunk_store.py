"""
Chunk storage abstraction layer.
Supports SQLite, DuckDB, Postgres, or legacy Ladybug-only mode.

Each substrate has different strengths:
- SQLite    : Simple, reliable FTS5 + sqlite-vec. Best for single-user retrieval.
- DuckDB    : Analytical power + Cypher ATTACH. Best for flexibility.
- Postgres  : Server-based, concurrent. Best for teams.
- Ladybug   : Legacy, all in graph. Good for prototyping.
"""
import logging

from . import config

logger = logging.getLogger(__name__)


class ChunkStore:
    """Abstraction layer for chunk storage across different substrates."""

    def __init__(self, substrate: str = None):
        self.substrate = substrate or config.CHUNK_SUBSTRATE
        self._conn = None
        self._open()

    def _open(self):
        """Open the appropriate chunk store based on substrate selection."""
        if self.substrate == "sqlite":
            self._open_sqlite()
        elif self.substrate == "duckdb":
            self._open_duckdb()
        elif self.substrate == "postgres":
            self._open_postgres()
        elif self.substrate == "ladybug":
            logger.info("Using Ladybug-only mode (no chunk substrate)")
            return
        else:
            raise ValueError(f"Unknown substrate: {self.substrate}")

    def _open_sqlite(self):
        """Open SQLite chunk store with FTS5 and vec support."""
        import sqlite3

        db_path = config._PROJECT_ROOT / "data" / "chunks.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row

        self._init_sqlite_schema()
        logger.info(f"Opened SQLite chunk store: {db_path}")

    def _init_sqlite_schema(self):
        """Initialize SQLite schema with FTS5 and virtual table for vectors."""
        cur = self._conn.cursor()

        # Main chunk table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunk (
                id TEXT PRIMARY KEY,
                doc_id TEXT NOT NULL,
                doc_path TEXT,
                title TEXT,
                body TEXT NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                entity_ids TEXT,  -- JSON array of entity IDs
                sensitivity TEXT DEFAULT 'public',
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                source_mtime INTEGER
            )
        """)

        # FTS5 virtual table for full-text search
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
                id, title, body,
                content='chunk',
                content_rowid='rowid'
            )
        """)

        # Trigger to keep FTS in sync
        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
                INSERT INTO chunk_fts(rowid, id, title, body)
                VALUES (new.rowid, new.id, new.title, new.body);
            END
        """)

        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
                INSERT INTO chunk_fts(chunk_fts, rowid, id, title, body)
                VALUES ('delete', old.rowid, old.id, old.title, old.body);
            END
        """)

        cur.execute("""
            CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
                INSERT INTO chunk_fts(chunk_fts, rowid, id, title, body)
                VALUES ('delete', old.rowid, old.id, old.title, old.body);
                INSERT INTO chunk_fts(rowid, id, title, body)
                VALUES (new.rowid, new.id, new.title, new.body);
            END
        """)

        # Vector storage (using BLOB for embeddings)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunk_embedding (
                chunk_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                embedded_at INTEGER DEFAULT (strftime('%s', 'now'))
            )
        """)

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_entity ON chunk(entity_ids)")

        self._conn.commit()

    def _open_duckdb(self):
        """Open DuckDB chunk store."""
        import duckdb

        db_path = config._PROJECT_ROOT / "data" / "chunks.duckdb"
        db_path.parent.mkdir(parents=True, exist_ok=True)

        # Enable experimental features for vector search
        self._conn = duckdb.connect(str(db_path))
        self._conn.execute("SET hnsw_enable_experimental_persistence = true")

        self._init_duckdb_schema()
        logger.info(f"Opened DuckDB chunk store: {db_path}")

    def _init_duckdb_schema(self):
        """Initialize DuckDB schema with FTS and vector support."""
        cur = self._conn.cursor()

        # Main chunk table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunk (
                id VARCHAR PRIMARY KEY,
                doc_id VARCHAR NOT NULL,
                doc_path VARCHAR,
                title VARCHAR,
                body VARCHAR NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                entity_ids VARCHAR[],  -- DuckDB array
                sensitivity VARCHAR DEFAULT 'public',
                created_at TIMESTAMP DEFAULT current_timestamp,
                source_mtime TIMESTAMP
            )
        """)

        # FTS will be added via PRAGMA after inserts (can't create at init)
        # HNSW index is experimental - we'll handle this in the embed module
        # For now, store embeddings as FLOAT[]

        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunk_embedding (
                chunk_id VARCHAR PRIMARY KEY,
                embedding FLOAT[],  -- Array type for vectors
                embedded_at TIMESTAMP DEFAULT current_timestamp
            )
        """)

    def _open_postgres(self):
        """Open Postgres chunk store."""
        import os
        import psycopg2

        password = os.environ.get("NEWSROOM_POSTGRES_PASSWORD", "")

        self._conn = psycopg2.connect(
            host=config.POSTGRES_HOST,
            port=config.POSTGRES_PORT,
            dbname=config.POSTGRES_DB,
            user=config.POSTGRES_USER,
            password=password
        )
        self._conn.autocommit = True
        self._init_postgres_schema()
        logger.info(f"Opened Postgres chunk store: {config.POSTGRES_HOST}:{config.POSTGRES_PORT}/{config.POSTGRES_DB}")

    def _init_postgres_schema(self):
        """Initialize Postgres schema with tsvector and pgvector."""
        cur = self._conn.cursor()

        # Enable extensions
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        cur.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

        # Main chunk table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunk (
                id VARCHAR PRIMARY KEY,
                doc_id VARCHAR NOT NULL,
                doc_path VARCHAR,
                title VARCHAR,
                body TEXT NOT NULL,
                chunk_index INTEGER DEFAULT 0,
                entity_ids TEXT[],  -- Postgres array
                sensitivity VARCHAR DEFAULT 'public',
                created_at TIMESTAMPTZ DEFAULT now(),
                source_mtime TIMESTAMPTZ
            )
        """)

        # Generated tsvector for FTS
        cur.execute("""
            ALTER TABLE chunk ADD COLUMN IF NOT EXISTS tsv tsvector
            GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(body, '')), 'C')
            ) STORED
        """)

        # Embedding column (use halfvec for high-dim support)
        dim = config.EMBEDDING_DIM
        cur.execute(f"""
            ALTER TABLE chunk ADD COLUMN IF NOT EXISTS embedding halfvec({dim})
        """)

        # Indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_doc ON chunk(doc_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_fts ON chunk USING GIN(tsv)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chunk_entity ON chunk USING GIN(entity_ids)")

        # HNSW index (after embeddings are added)
        # cur.execute("""
        #     CREATE INDEX IF NOT EXISTS idx_chunk_emb_hnsw ON chunk
        #     USING hnsw (embedding halfvec_cosine_ops) WITH (m=16, ef_construction=64)
        # """)

    # =========================================================================
    # CRUD Operations
    # =========================================================================

    def add_chunk(self, chunk_id: str, doc_id: str, body: str,
                  title: str = "", doc_path: str = "",
                  chunk_index: int = 0, entity_ids: list = None,
                  sensitivity: str = "public") -> bool:
        """Add a single chunk to the store."""
        if self.substrate == "ladybug":
            return True  # No-op in ladybug-only mode

        if self.substrate == "sqlite":
            return self._add_chunk_sqlite(chunk_id, doc_id, body, title, doc_path, chunk_index, entity_ids, sensitivity)
        elif self.substrate == "duckdb":
            return self._add_chunk_duckdb(chunk_id, doc_id, body, title, doc_path, chunk_index, entity_ids, sensitivity)
        elif self.substrate == "postgres":
            return self._add_chunk_postgres(chunk_id, doc_id, body, title, doc_path, chunk_index, entity_ids, sensitivity)

    def _add_chunk_sqlite(self, chunk_id: str, doc_id: str, body: str,
                          title: str, doc_path: str, chunk_index: int,
                          entity_ids: list, sensitivity: str) -> bool:
        import json
        cur = self._conn.cursor()
        entity_json = json.dumps(entity_ids or [])
        cur.execute("""
            INSERT OR REPLACE INTO chunk (id, doc_id, doc_path, title, body, chunk_index, entity_ids, sensitivity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (chunk_id, doc_id, doc_path, title, body, chunk_index, entity_json, sensitivity))
        self._conn.commit()
        return True

    def _add_chunk_duckdb(self, chunk_id: str, doc_id: str, body: str,
                          title: str, doc_path: str, chunk_index: int,
                          entity_ids: list, sensitivity: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO chunk (id, doc_id, doc_path, title, body, chunk_index, entity_ids, sensitivity)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (chunk_id, doc_id, doc_path, title, body, chunk_index, entity_ids or [], sensitivity))
        self._conn.commit()  # Ensure write is persisted
        return True

    def _add_chunk_postgres(self, chunk_id: str, doc_id: str, body: str,
                            title: str, doc_path: str, chunk_index: int,
                            entity_ids: list, sensitivity: str) -> bool:
        cur = self._conn.cursor()
        cur.execute("""
            INSERT INTO chunk (id, doc_id, doc_path, title, body, chunk_index, entity_ids, sensitivity)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                doc_path = EXCLUDED.doc_path,
                title = EXCLUDED.title,
                body = EXCLUDED.body,
                entity_ids = EXCLUDED.entity_ids
        """, (chunk_id, doc_id, doc_path, title, body, chunk_index, entity_ids, sensitivity))
        return True

    def add_embedding(self, chunk_id: str, embedding: list) -> bool:
        """Add an embedding vector for a chunk."""
        if self.substrate == "ladybug":
            return True

        if self.substrate == "sqlite":
            return self._add_embedding_sqlite(chunk_id, embedding)
        elif self.substrate == "duckdb":
            return self._add_embedding_duckdb(chunk_id, embedding)
        elif self.substrate == "postgres":
            return self._add_embedding_postgres(chunk_id, embedding)

    def _add_embedding_sqlite(self, chunk_id: str, embedding: list) -> bool:
        import struct
        cur = self._conn.cursor()
        # Store as binary blob
        emb_bytes = struct.pack(f"{len(embedding)}f", *embedding)
        cur.execute("""
            INSERT OR REPLACE INTO chunk_embedding (chunk_id, embedding)
            VALUES (?, ?)
        """, (chunk_id, emb_bytes))
        self._conn.commit()
        return True

    def _add_embedding_duckdb(self, chunk_id: str, embedding: list) -> bool:
        cur = self._conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO chunk_embedding (chunk_id, embedding)
            VALUES (?, ?)
        """, (chunk_id, embedding))
        self._conn.commit()
        return True

    def _add_embedding_postgres(self, chunk_id: str, embedding: list) -> bool:
        cur = self._conn.cursor()
        # Convert to halfvec format
        emb_str = "[" + ",".join(str(x) for x in embedding) + "]"
        cur.execute("""
            INSERT INTO chunk_embedding (chunk_id, embedding)
            VALUES (%s, %s::halfvec)
            ON CONFLICT (chunk_id) DO UPDATE SET embedding = EXCLUDED.embedding
        """, (chunk_id, emb_str))
        return True

    # =========================================================================
    # Search Operations
    # =========================================================================

    def search_fts(self, query: str, limit: int = 12) -> list:
        """Full-text search using keyword matching."""
        if self.substrate == "ladybug":
            return []

        if self.substrate == "sqlite":
            return self._search_fts_sqlite(query, limit)
        elif self.substrate == "duckdb":
            return self._search_fts_duckdb(query, limit)
        elif self.substrate == "postgres":
            return self._search_fts_postgres(query, limit)

    def _search_fts_sqlite(self, query: str, limit: int) -> list:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT c.id, c.doc_id, c.title, c.body, f.rank
            FROM chunk_fts f
            JOIN chunk c ON f.id = c.id
            WHERE chunk_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit))
        return [dict(row) for row in cur.fetchall()]

    def _search_fts_duckdb(self, query: str, limit: int) -> list:
        """DuckDB full-text search.

        Note: DuckDB FTS requires running PRAGMA create_fts_index after
        bulk data loads. Without the index, this falls back to LIKE.
        For production, call rebuild_fts() after ingestion completes.
        """
        cur = self._conn.cursor()

        # Check if FTS index exists, if not use LIKE fallback
        try:
            cur.execute("SELECT count(*) FROM duckdb_functions() WHERE function_name = 'match_bm25'")
            if cur.fetchone()[0] > 0:
                # Try BM25 if FTS extension is available
                cur.execute("""
                    SELECT id, doc_id, title, body
                    FROM chunk
                    WHERE body ILIKE ? OR title ILIKE ?
                    LIMIT ?
                """, (f"%{query}%", f"%{query}%", limit))
                return [{"id": r[0], "doc_id": r[1], "title": r[2], "body": r[3]} for r in cur.fetchall()]
        except Exception:
            pass

        # Fallback to LIKE
        cur.execute("""
            SELECT id, doc_id, title, body
            FROM chunk
            WHERE body LIKE ? OR title LIKE ?
            LIMIT ?
        """, (f"%{query}%", f"%{query}%", limit))
        return [{"id": r[0], "doc_id": r[1], "title": r[2], "body": r[3]} for r in cur.fetchall()]

    def rebuild_fts(self) -> None:
        """Rebuild FTS index after bulk loads. Call after ingestion completes."""
        if self.substrate != "duckdb":
            return

        try:
            # Drop existing FTS index if it exists
            self._conn.execute("DROP TABLE IF EXISTS chunk_fts")
        except Exception:
            pass

        # Note: DuckDB FTS requires the fts extension and explicit index creation
        # This is a placeholder - the actual implementation depends on DuckDB version
        logger.info("DuckDB FTS index rebuild requested (requires extension setup)")

    def _search_fts_postgres(self, query: str, limit: int) -> list:
        cur = self._conn.cursor()
        cur.execute("""
            SELECT id, doc_id, title, body,
                   ts_rank_cd(tsv, websearch_to_tsquery(%s)) AS rank
            FROM chunk
            WHERE tsv @@ websearch_to_tsquery(%s)
            ORDER BY rank DESC
            LIMIT %s
        """, (query, query, limit))
        return [{"id": r[0], "doc_id": r[1], "title": r[2], "body": r[3], "rank": r[4]} for r in cur.fetchall()]

    def _search_vector_duckdb(self, query_embedding: list, limit: int) -> list:
        """DuckDB vector search.

        Note: DuckDB HNSW requires experimental persistence and full index
        rebuild after data loads. This implementation uses brute-force
        cosine similarity as fallback. For production, either:
        1. Enable experimental HNSW and rebuild index after loads, or
        2. Store embeddings in SQLite for better vector support.
        """
        import math

        cur = self._conn.cursor()
        cur.execute("SELECT chunk_id, embedding FROM chunk_embedding")

        results = []
        for row in cur.fetchall():
            chunk_id, emb = row
            if emb is None:
                continue

            # Compute cosine similarity
            if len(emb) != len(query_embedding):
                continue

            dot = sum(a * b for a, b in zip(query_embedding, emb))
            norm1 = math.sqrt(sum(x * x for x in query_embedding))
            norm2 = math.sqrt(sum(x * x for x in emb))

            if norm1 > 0 and norm2 > 0:
                score = dot / (norm1 * norm2)
                results.append((chunk_id, score))

        results.sort(key=lambda x: -x[1])
        return [{"chunk_id": r[0], "score": r[1]} for r in results[:limit]]

    def search_vector(self, query_embedding: list, limit: int = 12) -> list:
        """Semantic search using vector similarity."""
        if self.substrate == "ladybug":
            return []

        if self.substrate == "sqlite":
            return self._search_vector_sqlite(query_embedding, limit)
        elif self.substrate == "duckdb":
            return self._search_vector_duckdb(query_embedding, limit)
        elif self.substrate == "postgres":
            return self._search_vector_postgres(query_embedding, limit)

    def _search_vector_sqlite(self, query_embedding: list, limit: int) -> list:
        import struct
        import math

        cur = self._conn.cursor()
        cur.execute("SELECT chunk_id, embedding FROM chunk_embedding")
        results = []
        for row in cur.fetchall():
            chunk_id, emb_bytes = row
            emb = struct.unpack(f"{len(emb_bytes)//4}f", emb_bytes)
            # Cosine similarity
            dot = sum(a * b for a, b in zip(query_embedding, emb))
            norm1 = math.sqrt(sum(x * x for x in query_embedding))
            norm2 = math.sqrt(sum(x * x for x in emb))
            if norm1 > 0 and norm2 > 0:
                score = dot / (norm1 * norm2)
                results.append((chunk_id, score))

        results.sort(key=lambda x: -x[1])
        return [{"chunk_id": r[0], "score": r[1]} for r in results[:limit]]

    def _search_vector_postgres(self, query_embedding: list, limit: int) -> list:
        cur = self._conn.cursor()
        emb_str = "[" + ",".join(str(x) for x in query_embedding) + "]"
        cur.execute("""
            SELECT c.id, c.doc_id, c.title, c.body,
                   (c.embedding <=> %s::halfvec) AS distance
            FROM chunk c
            JOIN chunk_embedding e ON c.id = e.chunk_id
            ORDER BY distance
            LIMIT %s
        """, (emb_str, limit))
        return [{"id": r[0], "doc_id": r[1], "title": r[2], "body": r[3], "distance": r[4]} for r in cur.fetchall()]

    def search_hybrid(self, query: str, query_embedding: list,
                      fts_weight: float = 0.5, limit: int = 12) -> list:
        """
        Hybrid search combining FTS and vector search using RRF.
        """
        fts_results = self.search_fts(query, limit=config.VECTOR_CANDIDATES)
        vec_results = self.search_vector(query_embedding, limit=config.VECTOR_CANDIDATES)

        # RRF fusion
        rrf_scores = {}
        k = config.RRF_K

        for rank, result in enumerate(fts_results, 1):
            chunk_id = result.get("id") or result.get("chunk_id")
            if chunk_id:
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + (1.0 / (k + rank))

        for rank, result in enumerate(vec_results, 1):
            chunk_id = result.get("chunk_id")
            if chunk_id:
                rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + (1.0 / (k + rank))

        # Sort by RRF score and fetch details
        sorted_ids = sorted(rrf_scores.items(), key=lambda x: -x[1])[:limit]

        results = []
        for chunk_id, rrf_score in sorted_ids:
            if self.substrate == "sqlite":
                cur = self._conn.cursor()
                cur.execute("SELECT id, doc_id, title, body FROM chunk WHERE id = ?", (chunk_id,))
                row = cur.fetchone()
                if row:
                    results.append({
                        "id": row[0],
                        "doc_id": row[1],
                        "title": row[2],
                        "body": row[3],
                        "rrf_score": rrf_score
                    })
            elif self.substrate == "postgres":
                cur = self._conn.cursor()
                cur.execute("SELECT id, doc_id, title, body FROM chunk WHERE id = %s", (chunk_id,))
                row = cur.fetchone()
                if row:
                    results.append({
                        "id": row[0],
                        "doc_id": row[1],
                        "title": row[2],
                        "body": row[3],
                        "rrf_score": rrf_score
                    })

        return results

    # =========================================================================
    # Utility
    # =========================================================================

    def chunk_count(self) -> int:
        """Get total chunk count."""
        if self.substrate == "ladybug":
            return 0

        cur = self._conn.cursor()
        if self.substrate == "sqlite":
            cur.execute("SELECT COUNT(*) FROM chunk")
        elif self.substrate in ("duckdb", "postgres"):
            cur.execute("SELECT COUNT(*) FROM chunk")
        return cur.fetchone()[0]

    def close(self):
        """Close the chunk store."""
        if self._conn:
            self._conn.close()
            self._conn = None


def get_chunk_store(substrate: str = None) -> ChunkStore:
    """Factory function to get the appropriate chunk store."""
    return ChunkStore(substrate or config.CHUNK_SUBSTRATE)