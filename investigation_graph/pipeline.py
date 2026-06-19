"""
The ground stage — where extracted candidates earn their place in the graph.

This is the correctness heart of the pipeline and the reason a journalist can
trust the result. Extraction (``extract.py``) is permissive on purpose; this
module is where two of the three baked-in safety gates fire (the third,
grade-locality, fires downstream in ``GraphWriter`` during ``build_graph``):

1. **Grounding gate** (`kg_common.write.grounding.ground`) — an entity is kept
   only if its surface form actually occurs in a source chunk, and an edge only
   if its two endpoints co-occur in a shared chunk. A hallucinated entity (the
   LLM invented a name that's in no document) or a fabricated link (two real
   people the model "connected" who never appear together) is **quarantined**,
   not published. For an investigative tool, a fabricated connection is a libel
   risk — so this is not optional.

2. **Entity resolution** (`kg_common.write.dedup.resolve_or_create_semantic`) —
   "Jane Smith", "J. Smith" and a second "Jane Smith" extracted from a different
   document collapse to one node instead of three. Without this, the graph
   invents false distinctions (or misses real connections) — the exact failure
   the README's ethics section warns about. Cascade: exact name → fuzzy
   (rapidfuzz) → embedding (optional) → LLM adjudication (optional).

The artifact contract: this stage consumes ``chunks`` / ``entities`` / ``edges``
(the same record kinds the rest of the pipeline speaks) and returns build-ready
``entities`` / ``edges`` plus a report. No plugin framework — one record shape,
the one the manual ingest path already produces.
"""
import logging
import re

from kg_common.write.dedup import ResolutionIndex, resolve_or_create_semantic
from kg_common.write.grounding import ground

from . import config

logger = logging.getLogger(__name__)


def _norm(s: str) -> str:
    """Lowercase + collapse whitespace — the haystack/needle form for the
    containment check, matching kg-common's grounding normalizer."""
    return " ".join((s or "").lower().split())


def _label_in_text(label_norm: str, text_norm: str) -> bool:
    """Whole-word containment for grounding (P1.2).

    The label must occur bounded by non-word characters, not as a raw substring —
    so a short/common label ("city", "the authority") no longer grounds to any
    chunk that merely contains those letters (e.g. "city" inside "capacity").
    Labels under 2 chars never ground. This tightens the gate against
    plausible-but-wrong attribution; it doesn't loosen anything.
    """
    if len(label_norm) < 2:
        return False
    return re.search(rf"(?<!\w){re.escape(label_norm)}(?!\w)", text_norm) is not None


def ground_and_resolve(
    chunks: list[dict],
    entities: list[dict],
    edges: list[dict],
    *,
    min_edge_overlap: int = 1,
    fuzzy_threshold: float = 0.92,
    embeddings: dict | None = None,
    threshold: float | None = None,
) -> tuple[dict, dict]:
    """Run grounding + entity resolution over extracted candidates.

    Args:
        chunks:   [{"id", "text", ...}]  — the source text the gate checks against.
        entities: [{"id", "entity_type", "label", ...}]  — extraction output.
        edges:    [{"source_id", "target_id", "edge_type", ...}]
        min_edge_overlap: shared chunks an edge's endpoints must co-occur in.
        fuzzy_threshold:  rapidfuzz merge line for entity resolution.
        embeddings: optional {entity_id: vector}. When given, the resolver's
            cosine tier engages (P1.1) — merges aliases that aren't fuzzy-close
            (e.g. "IBM" / "International Business Machines"). Absent → exact+fuzzy
            only (no Ollama needed). Vectors must be one model/dimension.
        threshold: cosine merge line for the embedding tier; defaults to
            ``config.DEDUP_THRESHOLD``.

    Returns:
        (build_records, report)
        - build_records = {"entities": [...], "edges": [...]} — survivors, with
          edges re-pointed to canonical entity ids. Feed straight to
          ``graph.build_graph`` (add the documents/mentions there).
        - report = grounding + resolution stats, incl. a ``merges`` list of every
          (kept, merged) pair for human review (P1.3 — a wrong merge fuses two
          real people, the libel vector, so every merge is recorded).
    """
    embeddings = embeddings or {}
    threshold = config.DEDUP_THRESHOLD if threshold is None else threshold
    # ── 1. Grounding ──────────────────────────────────────────────────────
    # Attribute each entity to the chunk(s) whose text contains its label. An
    # entity in no chunk gets no pointer and is quarantined as ungrounded; this
    # is exactly how a hallucinated name fails the gate. (Whole-doc extraction
    # today; per-chunk extraction would carry the pointer natively — a future
    # refinement, noted in SPEC.) We COPY each record and add only the keys the
    # gate reads, so the originals are untouched.
    norm_chunks = {c["id"]: _norm(c.get("text", "")) for c in chunks}

    recs: list[dict] = [{"kind": "chunk", "id": c["id"], "text": c.get("text", "")}
                        for c in chunks]

    for e in entities:
        label_norm = _norm(e.get("label", ""))
        # Chunks where this entity's surface form occurs as a whole word (P1.2).
        src_chunks = [cid for cid, t in norm_chunks.items() if _label_in_text(label_norm, t)]
        rec = {"kind": "entity", "id": e["id"], "name": e.get("label", "")}
        if src_chunks:
            rec["source_chunk_id"] = src_chunks  # ground() accepts a list
        recs.append(rec)

    for ed in edges:
        recs.append({
            "kind": "edge",
            "source": ed["source_id"],
            "target": ed["target_id"],
            # carry the original so we can recover it from report.grounded
            "_orig": ed,
        })

    report = ground(recs, min_edge_overlap=min_edge_overlap)

    grounded_entity_ids = {r["id"] for r in report.grounded if r.get("kind") == "entity"}
    # Preserve INPUT order (not set-iteration order) so entity resolution is
    # deterministic: the first-seen surface form becomes the canonical node every
    # run. Iterating the id set directly would let PYTHONHASHSEED decide which
    # duplicate wins — unacceptable for a tool whose output must be reproducible.
    grounded_entities = [e for e in entities if e["id"] in grounded_entity_ids]
    grounded_edges = [r["_orig"] for r in report.grounded if r.get("kind") == "edge"]

    # ── 2. Entity resolution ──────────────────────────────────────────────
    # Collapse duplicate surface forms to one canonical node. resolve_or_create
    # auto-registers new ids in the index; a returned id != the candidate means
    # a merge, so we drop the duplicate and re-point its edges to the canonical.
    index = ResolutionIndex()
    id_map: dict[str, str] = {}
    canonical: dict[str, dict] = {}
    merge_records: list[dict] = []
    for e in grounded_entities:
        canon = resolve_or_create_semantic(
            e["id"], e.get("label", ""), e.get("entity_type", ""),
            index,
            embedding=embeddings.get(e["id"]),   # engages the cosine tier (P1.1)
            threshold=threshold,
            fuzzy_threshold=fuzzy_threshold,
        )
        id_map[e["id"]] = canon
        if canon == e["id"]:
            canonical[canon] = e          # first sighting — keep it
        else:
            # Duplicate folds into the canonical. Record the pair for human
            # review (P1.3): a wrong merge fuses two real entities.
            kept = canonical.get(canon, {})
            merge_records.append({
                "kept_id": canon,
                "kept_label": kept.get("label", ""),
                "merged_id": e["id"],
                "merged_label": e.get("label", ""),
                "entity_type": e.get("entity_type", ""),
                "via_embedding": e["id"] in embeddings,
            })

    # Re-point edges to canonical ids; drop self-loops created by a merge.
    resolved_edges = []
    for ed in grounded_edges:
        src = id_map.get(ed["source_id"], ed["source_id"])
        tgt = id_map.get(ed["target_id"], ed["target_id"])
        if src == tgt:
            continue
        ed = {**ed, "source_id": src, "target_id": tgt}
        resolved_edges.append(ed)

    report_dict = {
        "entities_in": len(entities),
        "edges_in": len(edges),
        "entities_grounded": len(grounded_entities),
        "edges_grounded": len(grounded_edges),
        "entities_quarantined": len(report.ungrounded_entities),
        "edges_quarantined": len(report.unsupported_edges),
        "entities_merged": len(merge_records),
        "entities_out": len(canonical),
        "edges_out": len(resolved_edges),
        "quarantine_rate": report.quarantine_rate(),
        "merges": merge_records,   # (kept, merged) pairs for review (P1.3)
    }
    logger.info("ground+resolve: %s", report_dict)

    return {"entities": list(canonical.values()), "edges": resolved_edges}, report_dict
