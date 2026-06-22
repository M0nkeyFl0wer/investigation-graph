"""
Deterministic tabular ingestion (P2.4 / interop brief G1).

A table row already **is** a typed edge — flight logs, ledgers, registries, and
sanctions lists are the highest-value OSINT data, and forcing them through an LLM
is wasteful, non-deterministic, and a hallucination risk. This module reads a
``.csv``/``.tsv`` (xlsx later, as an optional extra) together with a per-file
**YAML mapping spec**, and emits ontology-typed entities + edges in the SAME
artifact-contract dict shape the LLM extractor produces (see
``extract.py:_make_entity``). They then flow through the existing
ground → resolve → grade-locality pipeline with no special-casing.

No LLM, no inference: every entity and edge is named **explicitly** by the spec,
carries ``extraction_source="deterministic"`` (confidence 0.9 — the deterministic
tier), and cites its source row as ``evidence``.

Mapping spec (YAML), validated against the ontology **at load** (fail loud, not
silently at write):

    entities:
      - column: owner            # CSV column holding the entity's label
        type: organization       # a literal ontology type ...
      - column: asset
        type_column: asset_type  # ... or a column naming the type per row
    edges:
      - source: owner            # must reference an entity column above
        type: OWNS               # an ontology edge type
        target: asset
        properties:              # optional extra edge properties
          share_pct: share_pct   #   edge_property_name: csv_column
        amount: amount           # optional money column ...
        currency: currency       # ... REQUIRED with amount (never a bare number)
        date: as_of              # optional ISO date column -> valid_from

Design notes / failure modes guarded (per the kg-ingestion skill):
- **Types validated up front.** Literal entity/edge types are checked against the
  ontology, and literal-typed edges are grade-checked, when the spec loads — so a
  bad mapping fails loud instead of every row rejecting at write.
- **No delimited round-trip of free text.** We emit Python dicts straight into the
  artifact contract; evidence/labels never go back through CSV/TSV (the skill's
  "delimited COPY desyncs free-text rows" lesson).
- **Edges only from an explicit triple.** An edge exists only because the spec
  named ``(source_col, edge_type, target_col)`` — never inferred from co-occurrence.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from investigation_graph.extract import generate_entity_id
from investigation_graph.ontology import Ontology

# Confidence for the deterministic tier (matches the skill's 0.9 deterministic /
# 0.7 NLP / 0.5 LLM convention and extract.py's deterministic phase).
_DETERMINISTIC_CONFIDENCE = 0.9
_PROVENANCE = "tabular"
_EXTRACTION_SOURCE = "deterministic"
_EVIDENCE_CAP = 500  # match the edge evidence cap used elsewhere


class SpecError(ValueError):
    """A mapping spec that is malformed or inconsistent with the ontology.

    Raised at load time so a bad mapping fails before any row is processed."""


@dataclass
class _EntityMap:
    column: str
    type: str | None = None          # literal ontology type, OR ...
    type_column: str | None = None   # ... a column naming the type per row


@dataclass
class _EdgeMap:
    source: str                      # an entity column
    type: str                        # an ontology edge type
    target: str                      # an entity column
    properties: dict[str, str] = field(default_factory=dict)  # edge_prop -> column
    amount: str | None = None        # money column
    currency: str | None = None      # currency column (required with amount)
    date: str | None = None          # ISO date column -> valid_from


@dataclass
class MappingSpec:
    """A validated column→ontology mapping for one tabular source."""
    entities: list[_EntityMap]
    edges: list[_EdgeMap]
    _by_column: dict[str, _EntityMap] = field(default_factory=dict)

    @classmethod
    def from_yaml(cls, path: str | Path, ontology: Ontology | None = None) -> "MappingSpec":
        """Parse + validate a mapping spec against the ontology. Fails loud."""
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise SpecError(f"{path}: spec must be a YAML mapping (got {type(raw).__name__})")
        ent_maps = [_parse_entity_map(e, path) for e in (raw.get("entities") or [])]
        edge_maps = [_parse_edge_map(e, path) for e in (raw.get("edges") or [])]
        if not ent_maps:
            raise SpecError(f"{path}: spec declares no entities")
        spec = cls(entities=ent_maps, edges=edge_maps,
                   _by_column={e.column: e for e in ent_maps})
        spec._validate(ontology or Ontology(), path)
        return spec

    def _validate(self, ont: Ontology, path: str | Path) -> None:
        # Entity types: a literal type must be a real node type (column-typed is
        # validated per row, since the value isn't known until read).
        for e in self.entities:
            if e.type and not ont.validate_entity_type(e.type):
                raise SpecError(f"{path}: entity column '{e.column}' maps to unknown "
                                f"type '{e.type}'")
        # Edge types + endpoints + grade-locality (where both ends are literal-typed).
        for ed in self.edges:
            if not ont.validate_edge_type(ed.type):
                raise SpecError(f"{path}: edge '{ed.source}->{ed.target}' uses unknown "
                                f"edge type '{ed.type}'")
            for side in (ed.source, ed.target):
                if side not in self._by_column:
                    raise SpecError(f"{path}: edge endpoint '{side}' is not a declared "
                                    f"entity column")
            if ed.amount and not ed.currency:
                # Review requirement: a money column must carry currency, or
                # downstream money-flow (P2.8) is meaningless across currencies.
                raise SpecError(f"{path}: edge '{ed.source}->{ed.target}' has amount "
                                f"'{ed.amount}' but no currency column")
            src_t = self._by_column[ed.source].type
            tgt_t = self._by_column[ed.target].type
            if src_t and tgt_t and not ont.validate_grade(ed.type, src_t, tgt_t):
                raise SpecError(f"{path}: edge '{ed.type}' cannot connect "
                                f"{src_t} -> {tgt_t} (grade-locality)")


def _parse_entity_map(d: Any, path) -> _EntityMap:
    if not isinstance(d, dict) or "column" not in d:
        raise SpecError(f"{path}: each entity needs a 'column' (got {d!r})")
    if bool(d.get("type")) == bool(d.get("type_column")):
        raise SpecError(f"{path}: entity '{d.get('column')}' needs exactly one of "
                        f"'type' or 'type_column'")
    return _EntityMap(column=d["column"], type=d.get("type"),
                      type_column=d.get("type_column"))


def _parse_edge_map(d: Any, path) -> _EdgeMap:
    for k in ("source", "type", "target"):
        if not isinstance(d, dict) or k not in d:
            raise SpecError(f"{path}: each edge needs 'source', 'type', 'target' "
                            f"(got {d!r})")
    return _EdgeMap(source=d["source"], type=d["type"], target=d["target"],
                    properties=dict(d.get("properties") or {}),
                    amount=d.get("amount"), currency=d.get("currency"),
                    date=d.get("date"))


def _delimiter(path: Path) -> str:
    return "\t" if path.suffix.lower() == ".tsv" else ","


def ingest_table(path: str | Path, spec: MappingSpec, *,
                 ontology: Ontology | None = None) -> dict:
    """Read a CSV/TSV through its mapping spec → artifact-contract entities/edges.

    Returns ``{"entities": [...], "edges": [...], "skipped": [...]}``. Entities use
    the FILE as ``source_url`` (so the same label across rows is one node, deduped
    by id); edges cite the specific row in ``evidence``. Row-level type/grade
    violations (only possible when a type comes from a column) are collected in
    ``skipped`` rather than crashing the whole file — a data error, not a spec error.
    """
    path = Path(path)
    ont = ontology or Ontology()
    source_url = str(path)
    entities: dict[str, dict] = {}   # id -> entity (dedup within the file)
    edges: list[dict] = []
    skipped: list[dict] = []

    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter=_delimiter(path))
        for i, row in enumerate(reader, start=1):
            # Resolve each entity column to (label, type), validating column-typed
            # values per row. A blank cell means "no entity here for this row".
            row_entities: dict[str, dict] = {}
            for em in spec.entities:
                label = (row.get(em.column) or "").strip()
                if not label:
                    continue
                etype = em.type or (row.get(em.type_column) or "").strip()
                if not ont.validate_entity_type(etype):
                    skipped.append({"row": i, "reason": "bad_entity_type",
                                    "column": em.column, "type": etype})
                    continue
                eid = generate_entity_id(label, etype, source_url)
                ent = {
                    "id": eid, "entity_type": etype, "label": label,
                    "description": "", "confidence": _DETERMINISTIC_CONFIDENCE,
                    "source_url": source_url, "provenance": _PROVENANCE,
                    "extraction_source": _EXTRACTION_SOURCE,
                }
                entities.setdefault(eid, ent)
                row_entities[em.column] = ent

            # Edges: only the explicit triples the spec names, grade-checked per row.
            for ed in spec.edges:
                se, te = row_entities.get(ed.source), row_entities.get(ed.target)
                if not se or not te:
                    continue  # one endpoint blank this row — no edge
                if not ont.validate_grade(ed.type, se["entity_type"], te["entity_type"]):
                    skipped.append({"row": i, "reason": "grade_violation",
                                    "edge": ed.type,
                                    "from": se["entity_type"], "to": te["entity_type"]})
                    continue
                edge = {
                    "source_id": se["id"], "target_id": te["id"], "edge_type": ed.type,
                    "confidence": _DETERMINISTIC_CONFIDENCE,
                    "source_url": source_url, "provenance": _PROVENANCE,
                    "extraction_source": _EXTRACTION_SOURCE,
                    "evidence": _row_evidence(i, row, ed)[:_EVIDENCE_CAP],
                }
                for prop, col in ed.properties.items():
                    if row.get(col) not in (None, ""):
                        edge[prop] = row[col]
                if ed.amount and row.get(ed.amount) not in (None, ""):
                    edge["amount"] = row[ed.amount]
                    edge["currency"] = row.get(ed.currency, "")
                if ed.date and row.get(ed.date) not in (None, ""):
                    edge["valid_from"] = row[ed.date]
                edges.append(edge)

    return {"entities": list(entities.values()), "edges": edges, "skipped": skipped}


def _row_evidence(i: int, row: dict, ed: _EdgeMap) -> str:
    """A compact, human-readable citation of the source row for this edge."""
    bits = [f"{ed.source}={row.get(ed.source, '')}",
            f"{ed.target}={row.get(ed.target, '')}"]
    if ed.amount and row.get(ed.amount):
        bits.append(f"{ed.amount}={row.get(ed.amount)} {row.get(ed.currency, '')}".strip())
    if ed.date and row.get(ed.date):
        bits.append(f"{ed.date}={row.get(ed.date)}")
    return f"row {i}: " + ", ".join(bits)


# --- media-subsystem-shaped processor ---------------------------------------
# Mirrors kg_common.media.BaseProcessor so a structured source can be discovered
# the same way documents are. The deterministic entities/edges live in
# ProcessorResult.structured; the ingest wiring reads them from there. A table
# with no sibling "<stem>.map.yaml" degrades gracefully to an empty result.
try:
    from kg_common.media import BaseProcessor, ProcessorResult
except Exception:  # pragma: no cover - media is an optional surface in some installs
    BaseProcessor = object  # type: ignore
    ProcessorResult = None  # type: ignore

_TABULAR_SUFFIXES = {".csv", ".tsv"}


class TabularProcessor(BaseProcessor):  # type: ignore[misc]
    """Reads a CSV/TSV + its sibling ``<stem>.map.yaml`` into deterministic
    entities/edges (in ``ProcessorResult.structured``). Graceful on a missing spec."""

    def __init__(self, ontology: Ontology | None = None):
        self._ontology = ontology

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in _TABULAR_SUFFIXES

    def process(self, path: Path):  # -> ProcessorResult
        spec_path = path.with_suffix("").with_suffix(".map.yaml")
        if not spec_path.exists():
            spec_path = path.parent / (path.stem + ".map.yaml")
        if ProcessorResult is None:  # pragma: no cover
            raise RuntimeError("kg_common.media.ProcessorResult unavailable")
        if not spec_path.exists():
            # No mapping = nothing we can type deterministically. Degrade, don't raise.
            return ProcessorResult(metadata={"kind": "tabular", "mapped": False,
                                             "reason": "no .map.yaml spec"})
        spec = MappingSpec.from_yaml(spec_path, self._ontology)
        out = ingest_table(path, spec, ontology=self._ontology)
        return ProcessorResult(
            text="",
            structured={"entities": out["entities"], "edges": out["edges"]},
            metadata={"kind": "tabular", "mapped": True,
                      "spec": str(spec_path), "skipped": out["skipped"]},
        )
