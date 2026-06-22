"""
Pre-built, parameterized Cypher query patterns.
Every query the system runs is defined here. No dynamic Cypher generation.
This means: (1) no query hallucination, (2) every query is auditable,
(3) journalists can see exactly what the system does.
"""

QUERIES = {
    # Entity search
    "entity_by_label": """
        MATCH (e:Entity)
        WHERE e.label CONTAINS $query
        RETURN e.id AS id, e.label AS label, e.entity_type AS type,
               e.confidence AS confidence, e.source_url AS source
        ORDER BY e.confidence DESC LIMIT $limit
    """,

    "entity_by_type": """
        MATCH (e:Entity {entity_type: $etype})
        RETURN e.id AS id, e.label AS label, e.confidence AS confidence,
               e.source_url AS source
        ORDER BY e.label LIMIT $limit
    """,

    "entity_by_label_and_type": """
        MATCH (e:Entity)
        WHERE e.label CONTAINS $query AND e.entity_type = $etype
        RETURN e.id AS id, e.label AS label, e.entity_type AS type,
               e.confidence AS confidence, e.source_url AS source
        ORDER BY e.confidence DESC LIMIT $limit
    """,

    # NOTE: entity-level vector search was removed — embeddings live on DuckDB
    # chunks now (one model, one place), so semantic search runs over chunks via
    # ChunkStore, not over Entity nodes. See SPEC §2.

    # Topology support
    "all_entities_for_topology": """
        MATCH (e:Entity)
        RETURN e.id AS id, e.entity_type AS type, e.label AS label,
               e.confidence AS confidence
    """,

    "all_edges_for_topology": """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        RETURN a.id AS src, b.id AS tgt, r.edge_type AS type,
               r.weight AS weight, r.confidence AS confidence
    """,

    # Extracted-only view (P2.7): edges actually found in sources, EXCLUDING
    # inferred/derived edges. This is the default view for anything that must not
    # treat a derived control edge as an observed fact.
    "extracted_edges": """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        WHERE r.provenance IS NULL OR r.provenance <> 'inferred'
        RETURN a.label AS src, r.edge_type AS type, b.label AS tgt,
               r.provenance AS provenance, r.confidence AS confidence
    """,

    # The complement: only inferred/derived edges (for the review surface). The
    # effective % rides in the evidence string (it's not a top-level edge column).
    "inferred_edges": """
        MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity)
        WHERE r.provenance = 'inferred'
        RETURN a.label AS src, r.edge_type AS type, b.label AS tgt,
               r.confidence AS confidence, r.evidence AS evidence
    """,

    # Contradiction detection
    "contradictions": """
        MATCH (a:Entity)-[r:RELATES_TO {edge_type: 'CONTRADICTS'}]->(b:Entity)
        RETURN a.label AS claim_a, b.label AS claim_b,
               a.source_url AS source_a, b.source_url AS source_b,
               r.created_at AS found_at
        ORDER BY r.created_at DESC LIMIT $limit
    """,

    # New entities (for daily briefing)
    "new_entities_since": """
        MATCH (e:Entity) WHERE e.created_at > $since
        RETURN e.entity_type AS type, count(e) AS cnt
        ORDER BY cnt DESC
    """,

    # Unlinked entities (for pruning/briefing)
    "unlinked_entities": """
        MATCH (e:Entity)
        WHERE NOT (e)-[:RELATES_TO]-()
          AND NOT (e)-[:MENTIONED_IN]-()
          AND e.created_at < $before
        RETURN e.label AS label, e.entity_type AS type
        LIMIT $limit
    """,

    # Ontology health
    "type_distribution": """
        MATCH (e:Entity)
        RETURN e.entity_type AS type, count(e) AS cnt
        ORDER BY cnt DESC
    """,

    "edge_type_distribution": """
        MATCH ()-[r:RELATES_TO]->()
        RETURN r.edge_type AS type, count(r) AS cnt
        ORDER BY cnt DESC
    """,

    # Counts
    "entity_count": "MATCH (e:Entity) RETURN count(e) AS cnt",
    "edge_count": "MATCH ()-[r:RELATES_TO]->() RETURN count(r) AS cnt",
    "document_count": "MATCH (d:Document) RETURN count(d) AS cnt",

    # Quality gates
    "llm_extracted_entities": """
        MATCH (e:Entity)
        WHERE e.extraction_source = 'llm'
        RETURN e.id AS id, e.label AS label, e.entity_type AS type,
               e.trust_penalty AS trust_penalty
        LIMIT $limit
    """,

    "low_confidence_entities": """
        MATCH (e:Entity)
        WHERE e.confidence < 0.6
        RETURN e.id AS id, e.label AS label, e.entity_type AS type,
               e.confidence AS confidence, e.last_reviewed AS last_reviewed
        LIMIT $limit
    """,

    "needs_review_entities": """
        MATCH (e:Entity)
        WHERE e.quality_flag = 'needs_review'
        RETURN e.id AS id, e.label AS label, e.entity_type AS type,
               e.created_at AS created_at
        LIMIT $limit
    """,

    "junk_entities": """
        MATCH (e:Entity)
        WHERE e.entity_type = 'concept'
          AND (e.label CONTAINS 'Session' OR e.label CONTAINS 'Commit'
               OR e.label CONTAINS 'File' OR e.label MATCHES '.*\\d{4}-\\d{2}-\\d{2}.*')
        RETURN e.id AS id, e.label AS label
        LIMIT $limit
    """,

    "entity_type_distribution": """
        MATCH (e:Entity)
        RETURN e.entity_type AS type, count(e) AS cnt
        ORDER BY cnt DESC
    """,

    "llm_extracted_edges": """
        MATCH ()-[r:RELATES_TO]->()
        WHERE r.extraction_source = 'llm'
        RETURN count(r) AS cnt
    """,

    # Graph health
    "orphaned_entities": """
        MATCH (e:Entity)
        WHERE NOT (e)-[:RELATES_TO]-() AND NOT (e)-[:MENTIONED_IN]-()
        RETURN e.id AS id, e.label AS label, e.entity_type AS type
        LIMIT $limit
    """,
}
