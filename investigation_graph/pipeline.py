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
from .dedup import make_cluster_tier, norm_dedupe, norm_name
from .lossless_merge import plan_lossless_merge
from .resolution import resolve_with_tiers
from .semantic_gate import is_stance_bearing_type

logger = logging.getLogger(__name__)

# A record is AUTHORITATIVE STRUCTURED data — a row in a registry filing /
# structured import, NOT an LLM guess over prose — when the structured-ingest path
# tags it with the STABLE marker ``extraction_source == "structured"``. For these
# the assertion IS the row: the entity and edge exist because a structured source
# declared them, so they must not be discarded merely because their surface form
# does not happen to co-occur in narrative prose (the prose co-occurrence heuristic
# is the right gate for hallucination-prone LLM output, the wrong gate for an
# authoritative tabular/registry fact).
#
# IMPORTANT — key on the STABLE marker, never on the human-facing ``provenance``:
# ``provenance``/``source_url`` are descriptive (often a per-record URL like
# ``https://registry.example.gov/filing#co7``) and VARY from feed to feed and even
# from row to row. Keying the rescue on a literal provenance value (the prior build
# hardcoded ``"structured_import"``) silently dropped every real registry feed whose
# provenance string differed. ``extraction_source`` is the contract the ingest path
# sets independently of what the provenance text happens to be, so ANY registry feed
# — whatever its provenance — is covered.
_STRUCTURED_EXTRACTION_SOURCE = "structured"


def _is_authoritative_structured(record: dict) -> bool:
    """True if a record came from an authoritative structured import.

    Detected via the stable ``extraction_source == "structured"`` marker the
    structured-ingest path sets, NOT via any provenance string (which varies per
    feed / per row). Such records are trustworthy by origin (a registry declared
    them); the prose co-occurrence grounding heuristic — built to catch an LLM
    inventing names that appear in no document — should not silently drop them. We
    still corroborate them against the corpus's normalized-name clusters below, so a
    genuinely unsupported structured ghost (in no chunk AND with no grounded
    cluster-mate) is still quarantined."""
    return record.get("extraction_source") == _STRUCTURED_EXTRACTION_SOURCE


def _cluster_key(entity: dict) -> tuple[str, str]:
    """Type-aware normalized-name cluster key for an entity.

    Two entities share a key iff they are the same type AND share a legal-suffix-
    stripped, de-punctuated, lowercased name ("Acme 7" / "Acme 7 LLC" -> same;
    "Acme 7" / "Acme 70" -> different; "Jordan Lee 0" / "Jordan Lee 7" ->
    different). This is the SAME normalization the adopted structured-dedup tier
    uses (investigation_graph.dedup.norm_name), so grounding-rescue and resolution
    agree on what a duplicate group is."""
    return (entity.get("entity_type", ""), norm_name(entity.get("label", "")))


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
    alias_merge: bool = True,
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

    # ── 1b. Authoritative-structured grounding rescue ─────────────────────────
    # A structured row IS an authoritative edge/entity — it exists because a
    # registry filing declared it, not because an LLM guessed it from prose. The
    # prose co-occurrence gate is the right defense against hallucinated LLM names
    # but the WRONG gate for an authoritative structured fact, which legitimately
    # may never appear verbatim in narrative text (e.g. the bare name "Acme 0" is
    # in the filing prose but its legal-suffix variant "Acme 0 LLC" is only ever
    # the *target* of an ownership row, so it co-occurs in no chunk).
    #
    # We rescue such an entity from quarantine ONLY when its normalized-name
    # cluster (same type + legal-suffix-stripped name) has at least one member
    # that DID ground in prose. That keeps the rescue corroborated by the corpus:
    # a suffix variant of a name the filing actually mentions is trustworthy, but
    # a planted poison entity that is in no chunk AND in a cluster with no grounded
    # member (a lone ghost) is still quarantined and its edge still dropped. This
    # is the general structured-import rule, not a per-name exception.
    structured_clusters_with_support: set[tuple[str, str]] = set()
    for e in entities:
        if e["id"] in grounded_entity_ids:
            structured_clusters_with_support.add(_cluster_key(e))

    rescued_ids: set[str] = set()
    for e in entities:
        if e["id"] in grounded_entity_ids:
            continue  # already grounded in prose
        if not _is_authoritative_structured(e):
            continue  # only authoritative structured records are rescuable
        if _cluster_key(e) in structured_clusters_with_support:
            rescued_ids.add(e["id"])
    grounded_entity_ids |= rescued_ids
    # Preserve INPUT order (not set-iteration order) so entity resolution is
    # deterministic: the first-seen surface form becomes the canonical node every
    # run. Iterating the id set directly would let PYTHONHASHSEED decide which
    # duplicate wins — unacceptable for a tool whose output must be reproducible.
    grounded_entities = [e for e in entities if e["id"] in grounded_entity_ids]
    grounded_edges = [r["_orig"] for r in report.grounded if r.get("kind") == "edge"]

    # Rescue authoritative-structured edges the prose co-occurrence gate dropped.
    # For an authoritative structured edge the ROW is the assertion of the
    # relationship, so we do not also demand its two endpoints co-occur in narrative
    # prose (a registry "A OWNS B" row is authoritative even if no sentence names A
    # and B together). The only requirement we keep is the structural one: BOTH
    # endpoints must be grounded/rescued entities — so the planted poison edge to a
    # ghost endpoint (in no chunk, no grounded cluster-mate) still gets dropped,
    # because its target never becomes a grounded entity. We de-dup against edges
    # already in grounded_edges by object identity so nothing is double-counted.
    already = {id(e) for e in grounded_edges}
    for ed in edges:
        if id(ed) in already:
            continue
        if not _is_authoritative_structured(ed):
            continue  # LLM-guessed edges still owe prose co-occurrence
        if ed["source_id"] in grounded_entity_ids and ed["target_id"] in grounded_entity_ids:
            grounded_edges.append(ed)

    # ── 2. Entity resolution ──────────────────────────────────────────────
    # Collapse duplicate surface forms to one canonical node. resolve_or_create
    # auto-registers new ids in the index; a returned id != the candidate means
    # a merge, so we drop the duplicate and re-point its edges to the canonical.
    index = ResolutionIndex()
    id_map: dict[str, str] = {}
    canonical: dict[str, dict] = {}
    merge_records: list[dict] = []

    # ── 2a. Structured-dedup tier (PUB.5) for authoritative-structured batches ──
    # The exact+fuzzy cascade has two failures on authoritative structured input:
    #   (1) it MISSES legal-suffix variants — "Acme 7" / "Acme 7 LLC" are not
    #       fuzzy-close enough (token_sort_ratio < 0.92), so they survive as two
    #       nodes and fragment the graph; and
    #   (2) on densely numbered names it OVER-merges — rapidfuzz scores "Acme 10"
    #       ≈ "Acme 0" above 0.92 (one inserted char), wrongly fusing distinct
    #       companies, which both fragments the ownership chain AND collapses real
    #       edges into self-loops.
    # The deterministic normalized-name tier (legal-suffix stripping + de-punct,
    # type-aware — investigation_graph.dedup) fixes BOTH: it merges the suffix
    # variants (same normalized name) while keeping "Acme 0" ≠ "Acme 10" and the 8
    # distinct "Jordan Lee N" people separate (different normalized names). Because
    # that deterministic clustering is the authority for structured data, we ALSO
    # disable the noisy fuzzy tier on this path (it would re-introduce failure (2));
    # the exact and embedding tiers stay engaged. Non-structured (LLM/prose) batches
    # are untouched — they keep the original exact+fuzzy(+embedding) cascade, so the
    # tabular-baseline and prose tests are unaffected.
    structured_entities = [e for e in grounded_entities if _is_authoritative_structured(e)]
    use_structured_tier = bool(structured_entities)
    structured_tier = None
    if use_structured_tier:
        # Cluster ALL grounded entities by (type, normalized-name). The tier merges
        # each candidate onto an already-registered cluster-mate; entities not in a
        # multi-member cluster simply create themselves (no-op merge).
        cluster_map = norm_dedupe([
            {"unique_id": e["id"], "name": e.get("label", ""),
             "entity_type": e.get("entity_type", "")}
            for e in grounded_entities
        ])
        structured_tier = make_cluster_tier(cluster_map)

    for e in grounded_entities:
        # Stance-bearing types (a claim / policy_position) are EXCLUDED from the
        # cosine tier: opposing stances embed as near-identical ("Support …" vs
        # "Oppose …" ~0.97), so an embedding merge would invert a position — a
        # libel-grade error for an investigative tool. We withhold the embedding
        # for those types so only the precise exact/fuzzy tiers can merge them.
        # (Excludes the cosine tier ONLY; exact/fuzzy resolution is unaffected.)
        # See investigation_graph/semantic_gate.py for the why + the measured case.
        candidate_embedding = (
            None
            if is_stance_bearing_type(e.get("entity_type", ""))
            else embeddings.get(e["id"])
        )
        if use_structured_tier:
            # Structured path: exact + (deterministic normalized-name) tier +
            # embedding, fuzzy disabled (fuzzy_threshold > 1 can never fire). The
            # normalized-name tier runs only on a full miss of exact/embedding, so
            # the cheap deterministic tiers still come first.
            canon = resolve_with_tiers(
                e["id"], e.get("label", ""), e.get("entity_type", ""),
                index,
                tiers=(structured_tier,),
                embedding=candidate_embedding,
                threshold=threshold,
                fuzzy_threshold=1.01,        # disable the over-merging fuzzy tier
            )
        else:
            canon = resolve_or_create_semantic(
                e["id"], e.get("label", ""), e.get("entity_type", ""),
                index,
                embedding=candidate_embedding,   # engages the cosine tier (P1.1)
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
    #
    # A naive re-point + keep-first dedup SILENTLY DROPS data: after two duplicate
    # endpoints fold to one canonical id, two formerly-distinct edges can land on
    # the same (source_id, target_id, edge_type) triple. If those edges carry
    # DIFFERENT data-bearing props — e.g. per-name-spelling campaign-finance
    # aggregates {amount_total, contribution_count, dates} — keeping the first and
    # discarding the rest loses real money (a sibling project lost a donor $6,650
    # this way). plan_lossless_merge re-points + de-dups losslessly: it sums
    # additive aggregates, unions date lists, and routes genuinely-conflicting
    # collisions (currency mismatch, contradictory share_pct) to human review
    # instead of dropping them. See investigation_graph/lossless_merge.py.
    edge_plan = plan_lossless_merge(grounded_edges, id_map)
    resolved_edges = edge_plan.write_edges()
    lossy_edge_clusters = list(edge_plan.review_clusters)

    # ── 2b. Alias-driven merge (use the extractor's ALIAS_OF judgments) ────
    # Similarity-only resolution leaves recurring entities fragmented across
    # documents — "GSD" / "German Shepherd Dog" / "Alsatian" survive as three
    # nodes because their strings/embeddings aren't close enough. But the
    # extractor ALSO emitted explicit ALIAS_OF edges meaning "same canonical
    # entity". Use them as a high-precision merge signal: union the endpoints of
    # each SAME-TYPE ALIAS_OF edge, collapse each group to one node (the longest
    # surface form), and re-point edges. Same-type only — never fuse a breed with
    # a person (the wrong-merge / libel risk). This is what connects the
    # otherwise-islanded document clusters into a navigable graph.
    if alias_merge:
        parent: dict[str, str] = {}

        def _find(x: str) -> str:
            parent.setdefault(x, x)
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:          # path compression
                parent[x], x = root, parent[x]
            return root

        def _union(a: str, b: str) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[rb] = ra

        for ed in resolved_edges:
            if ed.get("edge_type") != "ALIAS_OF":
                continue
            s, t = ed["source_id"], ed["target_id"]
            es, et = canonical.get(s), canonical.get(t)
            if es and et and es.get("entity_type") == et.get("entity_type"):
                _union(s, t)

        # Group the canonical nodes; pick each group's keeper = longest label
        # (tie-break by id, so the choice is deterministic across runs).
        groups: dict[str, list[str]] = {}
        for cid in canonical:
            groups.setdefault(_find(cid), []).append(cid)
        alias_map: dict[str, str] = {}
        for members in groups.values():
            keeper = max(members, key=lambda i: (len(canonical[i].get("label", "")), i))
            for m in members:
                alias_map[m] = keeper
                if m != keeper:
                    merge_records.append({
                        "kept_id": keeper,
                        "kept_label": canonical[keeper].get("label", ""),
                        "merged_id": m,
                        "merged_label": canonical[m].get("label", ""),
                        "entity_type": canonical[m].get("entity_type", ""),
                        "via_alias": True,
                    })

        # Keep only group keepers; re-point every edge through the alias map and
        # drop self-loops (incl. the ALIAS_OF edges we just merged along). The
        # alias merge can create the SAME edge collision as the resolution merge
        # above (two alias members each carrying a distinct aggregate edge to the
        # same target), so it gets the same lossless guard — re-aggregate additive
        # collisions, route real conflicts to review, never silently drop.
        canonical = {cid: e for cid, e in canonical.items() if alias_map.get(cid) == cid}
        alias_plan = plan_lossless_merge(resolved_edges, alias_map)
        resolved_edges = alias_plan.write_edges()
        lossy_edge_clusters.extend(alias_plan.review_clusters)

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
        # Edge collisions a merge created that could NOT be losslessly collapsed
        # (e.g. mismatched currency, contradictory share_pct). These are NEVER
        # dropped — they are surfaced here for the same human review the entity
        # merges get, so conflicting aggregates are a decision, not a silent loss.
        "lossy_edge_clusters": [
            {"key": list(c.key), "reason": c.reason, "edges": c.edges}
            for c in lossy_edge_clusters
        ],
    }
    logger.info("ground+resolve: %s", report_dict)

    return {"entities": list(canonical.values()), "edges": resolved_edges}, report_dict
