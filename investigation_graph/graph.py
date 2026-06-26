"""
The LadybugDB graph — a rebuilt *projection* of the DuckDB source of truth.

DuckDB (``chunk_store.py``) holds the records (documents, chunks, entities,
edges). This module turns the entity/edge records into the typed graph that
powers path search and topology. Writes go through kg-common's ``GraphWriter``,
so we inherit its correctness machinery for free: type + grade-locality
validation, the single-writer pidfile lock, and — critically — the RELATES_TO
**corruption guard**.

Why "projection, not incremental store" (verified at
``kg-common/kg_common/write/ladybug.py:603-645``): on this LadybugDB build, an
incremental edge write into a *populated* RELATES_TO table permutes a column's
values across unrelated rows on the next checkpoint. ``GraphWriter.add_edge``
therefore refuses incremental edge writes once the table holds rows. The only
safe pattern is **reconstruct-and-swap**: build the whole edge set into a fresh,
empty table in one uninterrupted pass, then checkpoint once. So the graph is
disposable — ``build_graph()`` wipes it and rebuilds it from the full DuckDB
record set every time. Adding documents means appending records to DuckDB and
rebuilding (fast at single-investigator scale). See ``SPEC.md`` §2.1.

Embeddings and full-text search are NOT here — they live on DuckDB chunks (one
embedding model, one place). The graph stores structure: who connects to whom,
typed and evidence-bearing.
"""
import logging
import shutil
from pathlib import Path

from kg_common.write import GraphWriter

from . import config
from .ontology import Ontology

logger = logging.getLogger(__name__)

# ============================================================================
# PROVENANCE ENFORCEMENT — STRUCTURAL, not a string heuristic.
#
# History (why this is structural now): two prior builds enforced provenance by
# inspecting the SHAPE of the source string — first a denylist of banned words,
# then "positive validation" that collapsed into a denylist one layer down
# ("has >=1 letter and isn't one of ~30 placeholder words"). Both leaked, because
# any check that asks "does this STRING look like a source" is satisfiable by a
# string that looks like one and points to nothing: "no source", a bare
# "http://", a single "x", the Greek-omicron homoglyph "unknοwn", and — the
# killer — a perfectly well-formed but never-ingested URL ("http://sec.gov/
# filing/999") or a plausible phantom doc-id ("doc999"). A string check can NEVER
# catch the phantom case, because the phantom IS well-formed.
#
# So we stop checking the shape of a string and check a FACT: does this edge's
# source POINT TO a document that was actually INGESTED? That is the real libel
# defense — not "the edge claims a source" but "the edge points to a thing in
# evidence a journalist can open and read."
#
# THE CONTRACT (structural):
#   An edge is sourced iff
#     edge.source_url  ∈ { url / path of an ingested document },  OR
#     edge.provenance  ∈ { id of an ingested document }.
#   Everything else is refused. There is no notion of "looks like a source" here.
#   A phantom url and a phantom doc-id both fail for the SAME reason a literal
#   "x" fails: none of them is a member of the ingested-document set. No
#   denylist, no scheme check, no length/letter heuristic — pure set membership.
#
# Two write paths, two ways to obtain the ingested-document set:
#   * build_graph    — the set is built from the ``records["documents"]`` payload
#                      it is handed (the docs being ingested in this rebuild).
#   * Graph.add_edge — there is no records payload, so the set is the documents
#                      ALREADY IN THE GRAPH, queried back out of the store.
# ============================================================================


def _valid_sources_from_documents(documents) -> tuple[set, set]:
    """Build the structural valid-source sets from a list of document records.

    Returns ``(doc_locators, doc_ids)`` where:
      * ``doc_locators`` = every ``url`` and every ``path`` across the documents
        (the things an edge's ``source_url`` may match — a document's locator),
      * ``doc_ids``      = every document ``id`` (the things an edge's
        ``provenance`` may match — a document's identity).

    These are the ONLY values an edge may cite. Membership in these sets is the
    whole check; nothing about the *shape* of any string is consulted. We add
    both ``url`` and ``path`` because a document record may carry either or both
    as its locator (the artifact contract uses ``path``; some sources also carry
    a ``url``), and an edge's ``source_url`` legitimately matches whichever the
    document was ingested with. Empty/None locators are NOT added, so an edge can
    never resolve to a document by matching a blank locator against a blank field.
    """
    doc_locators: set = set()
    doc_ids: set = set()
    for doc in documents or ():
        # A document's identity — what an edge's ``provenance`` resolves against.
        did = doc.get("id")
        if did is not None and did != "":
            doc_ids.add(did)
        # A document's locator(s) — what an edge's ``source_url`` resolves against.
        for key in ("url", "path"):
            loc = doc.get(key)
            if loc is not None and loc != "":
                doc_locators.add(loc)
    return doc_locators, doc_ids


def _edge_resolves(edge: dict, doc_locators: set, doc_ids: set) -> bool:
    """True iff this edge's source resolves to an ingested document (set membership).

    Structural test, no string shape: the edge is sourced iff its ``source_url``
    is the locator of an ingested document OR its ``provenance`` is the id of one.
    A missing field is simply not a member of the (locator/id) set, so a sourceless
    edge fails for the same reason a phantom one does — it is not IN the evidence.

    We require the cited value to be non-empty before testing membership, so that
    an edge with ``source_url=""`` cannot accidentally resolve should a malformed
    document ever leak an empty locator into the set (belt-and-suspenders with the
    empty-filtering in ``_valid_sources_from_documents``).
    """
    source_url = edge.get("source_url")
    if source_url is not None and source_url != "" and source_url in doc_locators:
        return True
    provenance = edge.get("provenance")
    if provenance is not None and provenance != "" and provenance in doc_ids:
        return True
    return False


def _import_ladybug():
    """Dual-import: source builds expose ``ladybug``; PyPI ships ``real_ladybug``."""
    try:
        import ladybug as lb  # noqa: F401
        return lb
    except ImportError:
        import real_ladybug as lb
        return lb


class Graph:
    """Read/write handle on the LadybugDB graph projection.

    Two modes:
      - read_only=True  → a plain read connection (NO writer lock). Use this for
        search, analysis, and briefings; many can run at once and none collide
        with a build.
      - read_only=False → wraps a kg-common ``GraphWriter`` (takes the
        single-writer pidfile lock, ensures schema from the ontology). Use for
        incremental writes inside a build.

    For a full rebuild from DuckDB records, prefer the module-level
    ``build_graph()`` — it does the corruption-safe reconstruct-and-swap.
    """

    def __init__(self, graph_dir: Path | None = None, ontology: Ontology | None = None,
                 read_only: bool = False):
        self.graph_dir = Path(graph_dir) if graph_dir else config.GRAPH_DIR
        self.ontology = ontology or Ontology()
        self.read_only = read_only
        self._writer: GraphWriter | None = None
        self._db = None
        self._conn = None

        if read_only:
            # Plain read connection — does not acquire the writer pidfile lock.
            self.graph_dir.parent.mkdir(parents=True, exist_ok=True)
            lb = _import_ladybug()
            self._db = lb.Database(str(self.graph_dir), read_only=True)
            self._conn = lb.Connection(self._db)
        else:
            # GraphWriter opens read-write, ensures schema, takes the lock.
            self._writer = GraphWriter(self.graph_dir, self.ontology)
            self._conn = self._writer._conn  # reads during a write session

    # =========================================================================
    # Writes (delegate to GraphWriter; refuse in read-only mode)
    # =========================================================================

    def _require_writer(self) -> GraphWriter:
        if self._writer is None:
            raise RuntimeError("Graph opened read_only; writes are not allowed.")
        return self._writer

    def add_document(self, doc_id: str, **extras) -> bool:
        """Register a source document node."""
        return self._require_writer().add_document(doc_id, **extras)

    def add_entity(self, entity_id: str, entity_type: str, label: str, **extras) -> bool:
        """Add an entity. GraphWriter validates the type + runs the dedup gate."""
        return self._require_writer().add_entity(entity_id, entity_type, label, **extras)

    def _graph_valid_sources(self) -> tuple[set, set]:
        """Read the structural valid-source set back out of the GRAPH itself.

        This is the second write path's analogue of the ``records["documents"]``
        payload that ``build_graph`` is handed: here there is no payload, so the
        ingested-document set is *the documents that are already nodes in this
        graph*. We query them and project the same two sets the structural check
        needs — document locators (``path``) and document ids.

        NOTE on the locator column: the Document node schema (see
        ``Ontology.document_field_schema``) stores ``id`` and ``path`` — there is
        no ``url`` column, so a document's stored locator is its ``path``. An edge
        added here therefore resolves by ``source_url == d.path`` or
        ``provenance == d.id``. (A ``url`` passed to ``add_document`` is not in
        the schema and is not persisted, so it cannot be a stored locator.) This
        is exactly the structural contract on the live store, not a string check.
        """
        rows = self.query("MATCH (d:Document) RETURN d.id AS id, d.path AS path")
        # Reuse the same set-builder as build_graph so both paths agree on what
        # "a valid source" means; rows expose ``path`` as the document locator.
        return _valid_sources_from_documents(rows)

    def add_edge(self, source_id: str, target_id: str, edge_type: str, **extras) -> bool:
        """Add a typed edge. GraphWriter validates type + grade-locality and
        enforces the corruption guard (only safe during a fresh bulk build).

        PROVENANCE ENFORCEMENT (STRUCTURAL, enforced HERE — the SECOND write path
        into the graph; the first is ``build_graph``). The guarantee must hold for
        BOTH paths, so the same fact is checked here: does this edge's source
        resolve to a document that is ACTUALLY IN THIS GRAPH? There is no records
        payload on this path, so the ingested-document set is read back out of the
        store (``_graph_valid_sources``). The edge passes iff its ``source_url`` is
        the locator (``path``) of a document node OR its ``provenance`` is the id
        of one. A phantom url ("http://sec.gov/filing/999"), a phantom doc-id, a
        missing source, and every string-junk value all fail for the SAME reason —
        none is a member of the graph's document set. No shape check, no denylist.

        Refused edges never reach the writer, so kg-common can never silently
        relabel a sourceless edge as provenance="unknown"/source_url="" and store
        it. ``extras`` carries the provenance/source_url keyword arguments the
        caller supplied.
        """
        doc_locators, doc_ids = self._graph_valid_sources()
        if not _edge_resolves(extras, doc_locators, doc_ids):
            logger.warning(
                "PROVENANCE GATE: refused edge %s (%s → %s) via Graph.add_edge — "
                "its source does not resolve to any document in the graph (got "
                "provenance=%r, source_url=%r). An edge may enter only if it "
                "points to an actually-ingested document a journalist can open.",
                edge_type, source_id, target_id,
                extras.get("provenance"), extras.get("source_url"),
            )
            return False
        return self._require_writer().add_edge(source_id, target_id, edge_type, **extras)

    def add_mention(self, entity_id: str, doc_id: str, mention_count: int = 1) -> bool:
        """Add an entity→document provenance edge (MENTIONED_IN)."""
        return self._require_writer().add_mention(entity_id, doc_id, mention_count)

    # =========================================================================
    # Reads (work in both modes via the shared connection)
    # =========================================================================

    def query(self, cypher: str, parameters: dict | None = None) -> list[dict]:
        """Run a Cypher read query, returning a list of column→value dicts."""
        result = self._conn.execute(cypher, parameters=parameters or {})
        cols = result.get_column_names()
        rows = []
        while result.has_next():
            rows.append(dict(zip(cols, result.get_next())))
        return rows

    def entity_count(self) -> int:
        r = self.query("MATCH (e:Entity) RETURN count(e) AS n")
        return r[0]["n"] if r else 0

    def edge_count(self) -> int:
        r = self.query("MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS n")
        return r[0]["n"] if r else 0

    def document_count(self) -> int:
        r = self.query("MATCH (d:Document) RETURN count(d) AS n")
        return r[0]["n"] if r else 0

    def find_path(self, source_label: str, target_label: str, max_hops: int = 4,
                  limit: int = 25, endpoint_cap: int = 25) -> list:
        """Find typed paths between two entities matched by label substring (P1.4).

        Two-step for performance + honesty:

        1. Resolve the source/target *labels* to entity **ids** first. The path
           traversal then anchors on ``id IN $set`` — and ``id`` is the PRIMARY
           KEY, so it's indexed — instead of doing a ``CONTAINS`` label scan at
           every hop of the variable-length expansion.
        2. Enumerate paths between the resolved id sets, fetching one more than
           ``limit`` so we can tell the caller when results were **truncated**
           (the old code silently capped at 5).

        Returns paths sorted by confidence (product of edge confidences — note:
        this is model-estimated, not ground truth; see ROADMAP P1.8). ``max_hops``
        is interpolated as an int literal (LadybugDB can't parameterize the
        variable-length bound) — never user input.
        """
        hops = int(max_hops)
        cap = int(endpoint_cap)  # int literal in LIMIT (LadybugDB can't param it)
        # 1. Resolve endpoints to ids (two cheap single-property scans).
        srcs = self.query(
            f"MATCH (a:Entity) WHERE a.label CONTAINS $q RETURN a.id AS id LIMIT {cap}",
            {"q": source_label})
        tgts = self.query(
            f"MATCH (b:Entity) WHERE b.label CONTAINS $q RETURN b.id AS id LIMIT {cap}",
            {"q": target_label})
        if not srcs or not tgts:
            return []
        src_ids = [r["id"] for r in srcs]
        tgt_ids = [r["id"] for r in tgts]

        # 2. Paths between the indexed id anchors; +1 to detect truncation.
        raw = self.query(
            f"""
            MATCH p = (a:Entity)-[r:RELATES_TO*1..{hops}]->(b:Entity)
            WHERE a.id IN $src AND b.id IN $tgt
            RETURN nodes(p) AS path_nodes, rels(p) AS path_rels
            LIMIT {int(limit) + 1}
            """,
            {"src": src_ids, "tgt": tgt_ids},
        )
        if len(raw) > limit:
            logger.warning("find_path: more than %d paths between %r and %r; "
                           "showing %d (raise limit to see more).",
                           limit, source_label, target_label, limit)
            raw = raw[:limit]

        results = []
        for row in raw:
            labels = [n["label"] for n in row["path_nodes"]]
            etypes = [r["edge_type"] for r in row["path_rels"]]
            conf = 1.0
            for r in row["path_rels"]:
                conf *= r.get("confidence", 1.0)
            results.append({
                "node_labels": labels,
                "edge_types": etypes,
                "path_confidence": round(conf, 4),
            })
        return sorted(results, key=lambda p: -p["path_confidence"])

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def flush(self) -> None:
        """Flush the write buffer (write mode only). Do NOT call mid-edge-load:
        a checkpoint between edge writes re-opens the corruption window."""
        if self._writer is not None:
            self._writer.flush()
            self._conn = self._writer._conn  # flush rebinds the connection

    def close(self) -> None:
        """Release the writer lock (write mode) or the read connection."""
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._conn = None
        self._db = None


def _wipe_graph(graph_dir: Path) -> None:
    """Remove a LadybugDB graph + its sidecars before a rebuild.

    real_ladybug 0.15.3 stores the graph as a single FILE (``g.lbug``), while
    other builds use a directory. ``shutil.rmtree`` only handles a directory, so
    a naive wipe crashed on the second ingest (the re-ingest path) when the graph
    was a file. This handles either shape, and also clears sidecars
    (``g.lbug.wal`` / ``.shadow`` / ``.lock`` / ``.tmp``): that lets the rebuild
    start clean AND quarantines any WAL a crashed builder left behind — a
    poisoned WAL would otherwise SEGV the next open (P1.5).
    """
    p = Path(graph_dir)
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists() or p.is_symlink():
        p.unlink(missing_ok=True)
    for sidecar in p.parent.glob(p.name + ".*"):
        if sidecar.is_dir():
            shutil.rmtree(sidecar, ignore_errors=True)
        else:
            sidecar.unlink(missing_ok=True)


def build_graph(records: dict, graph_dir: Path | None = None,
                ontology: Ontology | None = None) -> dict:
    """Rebuild the whole graph projection from DuckDB records (reconstruct-and-swap).

    ``records`` is the artifact-contract payload:
        {
          "documents": [ {id, ...extras} ],
          "entities":  [ {id, entity_type, label, ...extras} ],
          "edges":     [ {source_id, target_id, edge_type, ...extras} ],
          "mentions":  [ {entity_id, doc_id, mention_count} ],   # optional
        }

    The graph directory is WIPED and rebuilt: documents + entities first, then
    every edge in one uninterrupted pass into the freshly-empty RELATES_TO
    table, then a single checkpoint at close. Because the table starts empty and
    is never checkpointed mid-load, the LadybugDB edge-corruption window never
    opens — this is the guard-sanctioned reconstruct-and-swap. We pass
    ``allow_inplace_edge_writes=True`` because that precondition (single-process
    bulk load into a freshly emptied table) is exactly satisfied here.

    Returns counts: {documents, entities, edges, mentions}.
    """
    graph_dir = Path(graph_dir) if graph_dir else config.GRAPH_DIR
    ontology = ontology or Ontology()

    # Wipe — the graph is a disposable projection of the DuckDB source of truth.
    _wipe_graph(graph_dir)

    documents = records.get("documents", [])
    entities = records.get("entities", [])
    edges = records.get("edges", [])
    mentions = records.get("mentions", [])

    # STRUCTURAL provenance set, built from the documents being ingested in THIS
    # rebuild. An edge may enter only if it resolves into these sets (source_url
    # ∈ document locators, OR provenance ∈ document ids). Built ONCE up front so
    # the edge loop is a cheap set-membership test per edge — no string shape is
    # ever inspected (see the module header for why string heuristics leaked).
    doc_locators, doc_ids = _valid_sources_from_documents(documents)

    # allow_inplace_edge_writes=True is SAFE here only: fresh empty table, single
    # bulk pass, one checkpoint at close (see module + SPEC §2.1).
    writer = GraphWriter(graph_dir, ontology, allow_inplace_edge_writes=True)
    counts = {"documents": 0, "entities": 0, "edges": 0, "mentions": 0}
    # Copy each record before popping keys — never mutate the caller's records
    # (so build_graph is re-callable / idempotent on the same input).
    try:
        for d in documents:
            d = dict(d)
            did = d.pop("id")
            if writer.add_document(did, **d):
                counts["documents"] += 1

        for e in entities:
            e = dict(e)
            eid, etype, label = e.pop("id"), e.pop("entity_type"), e.pop("label")
            if writer.add_entity(eid, etype, label, **e):
                counts["entities"] += 1

        # All edges in ONE pass — no flush/checkpoint between them.
        for ed in edges:
            ed = dict(ed)
            src, tgt, etype = ed.pop("source_id"), ed.pop("target_id"), ed.pop("edge_type")

            # PROVENANCE GATE (STRUCTURAL, enforced HERE at the real write path,
            # not in a bypassable helper): every edge entering the graph must
            # resolve to a document that was actually ingested in THIS rebuild —
            # source_url ∈ doc_locators OR provenance ∈ doc_ids. kg-common's schema
            # would otherwise silently relabel a sourceless edge as
            # provenance="unknown"/source_url="" and store it; we refuse it. A
            # phantom url/doc-id and a sourceless edge all fail identically: they
            # are not MEMBERS of the ingested-document set. This is checked against
            # the leftover ``ed`` extras (still holds provenance/source_url after
            # the three pops above). No string shape is consulted.
            if not _edge_resolves(ed, doc_locators, doc_ids):
                counts.setdefault("edges_rejected", 0)
                counts["edges_rejected"] += 1
                logger.warning(
                    "PROVENANCE GATE: refused edge %s (%s → %s) — its source does "
                    "not resolve to any ingested document (got provenance=%r, "
                    "source_url=%r). An edge may enter only if it points to an "
                    "actually-ingested document a journalist can open.",
                    etype, src, tgt, ed.get("provenance"), ed.get("source_url"),
                )
                continue

            if writer.add_edge(src, tgt, etype, **ed):
                counts["edges"] += 1

        for m in mentions:
            if writer.add_mention(m["entity_id"], m["doc_id"], m.get("mention_count", 1)):
                counts["mentions"] += 1
    finally:
        writer.close()  # single checkpoint here

    logger.info("Rebuilt graph at %s: %s", graph_dir, counts)
    return counts
