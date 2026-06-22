"""Deterministic, non-LLM ingestion processors (P2.4 / interop brief G1).

Today everything is forced through chunk→embed→LLM-extract. But some sources are
already structured — a table row *is* a typed edge — and must never touch an LLM.
These processors read structured sources and emit ontology-typed entities/edges in
the same artifact-contract shape the LLM extractor produces, so they flow through
the existing ground → resolve → grade-locality pipeline unchanged.
"""
from investigation_graph.processors.tabular import (
    MappingSpec,
    SpecError,
    TabularProcessor,
    ingest_table,
    maybe_ingest_tabular,
)

__all__ = [
    "MappingSpec",
    "SpecError",
    "TabularProcessor",
    "ingest_table",
    "maybe_ingest_tabular",
]
