"""
The investigative ontology — now a kg-common ``Ontology`` subclass.

``ONTOLOGY.md`` stays the human-editable source of truth (edit it for your beat;
the boundary examples are genuinely good and we keep them). This module parses
that file and produces an object that conforms to the shared kg-common ontology
contract, so the kg-common ``GraphWriter`` enforces, for free:

- **type membership** — only declared entity/edge types are admitted;
- **grade-locality** — an edge's endpoints must satisfy its declared
  domain -> range (``EMPLOYED_BY`` only person -> organization, etc.). The old
  code checked only that the *type* existed, not that the endpoints were legal,
  so a nonsense ``transaction --EMPLOYED_BY--> claim`` slipped through. Now it is
  rejected;
- **alias normalization** — if the extractor says ``company`` we map it to
  ``organization`` instead of rejecting it.

The "From -> To" column in ONTOLOGY.md already encodes domain/range; we read it
directly. Conventions, matching the kg-common loader and the good-dog-corpus
YAML dialect:

- ``any`` (or ``*``) on either side means "unconstrained on that side";
- ``/`` unions alternatives (``organization/person`` -> either);
- ``OCCURRED_ON`` is dropped — a date is a *property*, not a node, so it is not a
  graph edge (the schema carries timestamps instead);
- ``MENTIONED_IN`` is structural (entity -> document), handled by the writer's
  own MENTIONED_IN relation, so it is excluded from the RELATES_TO vocabulary.
"""
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# The shared contract. Imported under an alias so we can still export a class
# named ``Ontology`` (existing callers do ``from .ontology import Ontology``).
from kg_common.ontology import Ontology as _KGOntology

logger = logging.getLogger(__name__)


@dataclass
class EntityType:
    """One entity type plus the boundary examples that sharpen extraction."""
    name: str
    description: str
    archetypical: str = ""   # clearly belongs
    atypical: str = ""       # edge case that still belongs
    exotypical: str = ""     # looks similar but does NOT belong (the key signal)


@dataclass
class EdgeType:
    """One relationship type and its parsed domain/range options."""
    name: str
    description: str
    from_types: list[str] = field(default_factory=list)  # canonical or ["*"]
    to_types: list[str] = field(default_factory=list)
    investigative_signal: str = ""


# Edge names that are NOT domain RELATES_TO relations: structural or property-like.
# Kept out of the RELATES_TO vocabulary so the extractor doesn't emit them as
# entity->entity edges.
_STRUCTURAL_EDGES = {"MENTIONED_IN"}        # handled by the writer's MENTIONED_IN rel
_PROPERTY_EDGES = {"OCCURRED_ON"}            # a date is a property, not an edge

# Conservative synonym maps — synonyms only, never direction-reversing ones
# (reversing an edge's direction silently is a correctness bug, so we don't).
_TYPE_ALIASES = {
    "company": "organization", "corporation": "organization", "ngo": "organization",
    "agency": "organization", "firm": "organization", "institution": "organization",
    "individual": "person", "people": "person",
    "place": "location", "address": "location", "jurisdiction": "location",
    "payment": "transaction", "transfer": "transaction",
    "property": "asset", "account": "asset",
    "filing": "document", "record": "document", "publication": "document",
    "statement": "claim", "assertion": "claim",
}
_EDGE_TYPE_ALIASES = {
    "WORKS_FOR": "EMPLOYED_BY", "EMPLOYEE_OF": "EMPLOYED_BY",
    "DIRECTOR_OF": "BOARD_MEMBER_OF", "ON_BOARD_OF": "BOARD_MEMBER_OF",
    "CONTRACTOR_OF": "CONTRACTED_WITH", "VENDOR_FOR": "CONTRACTED_WITH",
    "WROTE": "AUTHORED", "SIGNED": "AUTHORED",
    "RELATED_TO": "ASSOCIATED_WITH", "LINKED_TO": "ASSOCIATED_WITH",
}


def _split_options(raw: str) -> list[str]:
    """Parse one side of a 'From -> To' cell into canonical type options.

    Handles '/' unions and the 'any'/'*' wildcard. Returns ['*'] for wildcard.
    """
    raw = raw.strip().lower()
    if not raw or raw in ("any", "*"):
        return ["*"]
    return [p.strip() for p in raw.split("/") if p.strip()]


class Ontology(_KGOntology):
    """Investigative-journalism ontology, loaded from ONTOLOGY.md.

    Conforms to kg_common.ontology.Ontology: the GraphWriter consumes
    NODE_TYPES / EDGE_TYPES / EDGE_DOMAIN_RANGE / aliases / field schemas and
    grades every write against them. Labels, PKs and rel-table names already
    match the kg-common defaults (Entity/id, RELATES_TO, MENTIONED_IN, CHUNK_OF),
    so we inherit those unchanged.
    """

    VERSION = "1.0"
    TYPE_ALIASES = _TYPE_ALIASES
    EDGE_TYPE_ALIASES = _EDGE_TYPE_ALIASES

    def __init__(self, ontology_path: str | None = None):
        if ontology_path is None:
            # Default to the env-selected ontology (a beat/sample sets ONTOLOGY_PATH
            # to its own file), falling back to the investigation-generic root.
            ontology_path = os.environ.get(
                "ONTOLOGY_PATH",
                str(Path(__file__).resolve().parent.parent / "ONTOLOGY.md"))
        self.path = Path(ontology_path)
        # Rich metadata (kept for prompts + validate_ontology reporting).
        self.entity_types: dict[str, EntityType] = {}
        self.edge_types: dict[str, EdgeType] = {}
        self._rejection_counts: dict[str, int] = {}
        self._parse()
        # Populate the kg-common contract as INSTANCE attributes (they shadow the
        # empty class-level frozensets the ABC declares).
        self.NODE_TYPES = frozenset(self.entity_types.keys())
        self.EDGE_TYPES = frozenset(self.edge_types.keys())
        self.EDGE_DOMAIN_RANGE = self._build_domain_range()

    # ------------------------------------------------------------------
    # Parsing ONTOLOGY.md
    # ------------------------------------------------------------------

    def _parse(self):
        if not self.path.exists():
            raise FileNotFoundError(f"Ontology file not found: {self.path}")

        section = None
        for line in self.path.read_text().split("\n"):
            if "## Entity Types" in line:
                section = "entities"
                continue
            if "## Edge Types" in line:
                section = "edges"
                continue
            if line.startswith("## "):
                section = None
                continue
            # Skip non-table lines and the header/separator rows.
            if not line.startswith("|") or line.startswith("|---") or line.startswith("| Type"):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]

            if section == "entities" and len(cells) >= 2:
                name = cells[0].lower().strip()
                self.entity_types[name] = EntityType(
                    name=name,
                    description=cells[1],
                    archetypical=cells[2] if len(cells) > 2 else "",
                    atypical=cells[3] if len(cells) > 3 else "",
                    exotypical=cells[4] if len(cells) > 4 else "",
                )
            elif section == "edges" and len(cells) >= 3:
                name = cells[0].upper().strip()
                # Drop property-like and structural edges from the relation vocab.
                if name in _PROPERTY_EDGES:
                    logger.debug("Skipping property-edge %s (date is a property)", name)
                    continue
                if name in _STRUCTURAL_EDGES:
                    logger.debug("Skipping structural edge %s (handled by writer)", name)
                    continue
                from_to = cells[1]
                # Reject malformed cells (e.g. a parenthetical '(date as property)').
                if "(" in from_to or "→" not in from_to and "->" not in from_to:
                    logger.warning("Skipping edge %s: unparseable domain/range %r", name, from_to)
                    continue
                left, right = re.split(r"\s*(?:→|->)\s*", from_to, maxsplit=1)
                self.edge_types[name] = EdgeType(
                    name=name,
                    description=cells[2],
                    from_types=_split_options(left),
                    to_types=_split_options(right),
                    investigative_signal=cells[3] if len(cells) > 3 else "",
                )

    def _build_domain_range(self) -> dict[str, list[tuple[str, str]]]:
        """Cartesian-expand each edge's from/to options into (src, tgt) pairs.

        kg-common's validate_grade treats '*' in either slot as a wildcard, so a
        fully-unconstrained edge becomes [('*','*')] which accepts anything.
        """
        dr: dict[str, list[tuple[str, str]]] = {}
        for name, e in self.edge_types.items():
            dr[name] = [(s, t) for s in e.from_types for t in e.to_types]
        return dr

    # ------------------------------------------------------------------
    # Validation surface (back-compat with existing callers + rejection log)
    # ------------------------------------------------------------------

    def validate_entity_type(self, entity_type: str) -> bool:
        """True iff the type (after alias normalization) is declared.

        Tracks rejections so ingestion can report which types the corpus wanted
        that the ontology lacks — the signal for when to extend ONTOLOGY.md.
        """
        norm = self.normalize_node_type(entity_type)
        if norm is not None:
            return True
        self._rejection_counts[(entity_type or "").lower().strip()] = (
            self._rejection_counts.get((entity_type or "").lower().strip(), 0) + 1
        )
        return False

    def validate_edge_type(self, edge_type: str) -> bool:
        """True iff the edge type (after alias canonicalization) is declared."""
        return self.canonical_edge_type((edge_type or "").upper().strip()) in self.EDGE_TYPES

    def get_rejection_counts(self) -> dict[str, int]:
        """Rejected entity types, most frequent first — ontology-expansion signal."""
        return dict(sorted(self._rejection_counts.items(), key=lambda kv: -kv[1]))

    # ------------------------------------------------------------------
    # Extraction prompts — keep the rich boundary examples (the good part)
    # ------------------------------------------------------------------

    def extraction_prompt_fragment(self) -> str:
        """Override the ABC's bare type list with the boundary-example version."""
        return self.get_extraction_prompt_context()

    def get_extraction_prompt_context(self) -> str:
        lines = ["Classify entities using ONLY these types:\n"]
        for name, et in self.entity_types.items():
            line = f"- **{name}**: {et.description}"
            if et.exotypical:
                line += f"\n  NOT this type: {et.exotypical}"
            lines.append(line)
        lines.append("\nIf an entity doesn't clearly fit any type, skip it. Do NOT invent types.")
        return "\n".join(lines)

    def get_edge_prompt_context(self) -> str:
        lines = ["Use ONLY these relationship types:\n"]
        for name, e in self.edge_types.items():
            frm = "/".join(e.from_types)
            to = "/".join(e.to_types)
            lines.append(f"- **{name}** ({frm} -> {to}): {e.description}")
        lines.append("\nPrefer specific types. Use ASSOCIATED_WITH only as a last resort.")
        return "\n".join(lines)

    @property
    def entity_type_names(self) -> list[str]:
        return list(self.entity_types.keys())

    @property
    def edge_type_names(self) -> list[str]:
        return list(self.edge_types.keys())

    # ------------------------------------------------------------------
    # Schema — onng's richer columns on top of the kg-common defaults
    # ------------------------------------------------------------------

    def entity_field_schema(self):
        """kg-common entity defaults + this project's provenance/quality columns."""
        schema = super().entity_field_schema()
        schema.update({
            "source_url": ("STRING", ""),            # which document
            "extraction_source": ("STRING", "unknown"),  # deterministic|nlp|llm|human
            "trust_penalty": ("DOUBLE", 0.0),        # LLM gets -0.1, human 0.0
            "quality_flag": ("STRING", ""),          # verified|needs_review|junk
            "last_reviewed": ("INT64", 0),
            "layer": ("STRING", "domain"),           # reserved for semantic layering
        })
        return schema

    def edge_field_schema(self):
        """kg-common edge defaults (incl. the bi-temporal trio) + extraction_source."""
        schema = super().edge_field_schema()
        schema.update({
            "extraction_source": ("STRING", "unknown"),
        })
        return schema

    def document_field_schema(self):
        """Document columns this project uses."""
        schema = super().document_field_schema()
        schema.update({
            "chunk_count": ("INT64", 0),
        })
        return schema

    def __repr__(self):
        return f"Ontology({len(self.entity_types)} entity types, {len(self.edge_types)} edge types)"
