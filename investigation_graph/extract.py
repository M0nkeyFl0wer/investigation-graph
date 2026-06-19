"""
Three-phase entity and relationship extraction.
Phase 1: Deterministic (structure, regex, dates) — fast, free, always runs
Phase 2: NLP (spaCy NER) — local, fast, catches named entities
Phase 3: LLM (Ollama or remote) — semantic, identifies relationships and types

Every entity validates against ONTOLOGY.md at extraction time.
Rejected types are counted for ontology improvement feedback.
"""
import logging
import re
import json
import hashlib
import time
import spacy

from . import config
from .chunking import chunk_text
from .ontology import Ontology

logger = logging.getLogger(__name__)


def generate_entity_id(label: str, entity_type: str, source_url: str) -> str:
    """Canonical ID function. ONE function, used everywhere."""
    normalized = f"{entity_type}:{label.lower().strip()}:{source_url}"
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class Extractor:
    """Three-phase extraction pipeline."""

    def __init__(self, ontology: Ontology):
        self.ontology = ontology
        self.nlp = spacy.load("en_core_web_sm")

    def extract_from_text(self, text: str, source_url: str = "",
                          doc_id: str = "") -> dict:
        """
        Run all three extraction phases on a text.
        Returns: {"entities": [...], "edges": [...]}
        """
        entities = []
        edges = []
        now = int(time.time())

        # Phase 1: Deterministic extraction
        p1_entities = self._phase1_deterministic(text, source_url, now)
        entities.extend(p1_entities)

        # Phase 2: spaCy NER
        p2_entities = self._phase2_spacy(text, source_url, now)
        entities.extend(p2_entities)

        # Phase 3: LLM extraction (relationships + type refinement) — PER CHUNK.
        # This used to run on text[:4000] (the first ~4k chars only), so any
        # relationship past the top of a real document was silently missed. We
        # now run the LLM over EVERY chunk — the same 1000/200 windows ingestion
        # embeds — and union the results, so a long filing's later-page
        # connections are actually extracted. A per-document cap bounds cost on
        # very large files (raise MAX_LLM_CHUNKS_PER_DOC to cover more).
        if config.PRIVACY_MODE in ("local", "hybrid", "remote"):
            chunks = chunk_text(text)
            cap = getattr(config, "MAX_LLM_CHUNKS_PER_DOC", 40)
            if len(chunks) > cap:
                logger.info("Doc has %d chunks; LLM extraction capped at %d.",
                            len(chunks), cap)
            extract_fn = (self._phase3_llm_local if config.PRIVACY_MODE == "local"
                          else self._phase3_llm_remote)
            for chunk in chunks[:cap]:
                # Pass entities seen so far so cross-chunk edge endpoints resolve.
                p3 = extract_fn(chunk, source_url, entities, now)
                entities.extend(p3.get("entities", []))
                edges.extend(p3.get("edges", []))

        # Deduplicate by ID
        seen_ids = set()
        unique_entities = []
        for e in entities:
            if e["id"] not in seen_ids:
                seen_ids.add(e["id"])
                unique_entities.append(e)

        return {"entities": unique_entities, "edges": edges}

    def _phase1_deterministic(self, text: str, source_url: str,
                              now: int) -> list:
        """Extract entities from structure: dates, dollar amounts."""
        entities = []

        # Dates (ISO and natural format)
        date_pattern = r'\b(\d{4}-\d{2}-\d{2}|\w+ \d{1,2},? \d{4})\b'
        for match in re.finditer(date_pattern, text):
            label = match.group(0)
            entities.append(self._make_entity(
                label, "event", f"Date reference: {label}",
                0.9, source_url, "deterministic", now))

        # Dollar amounts → transactions
        money_pattern = r'\$[\d,]+(?:\.\d{2})?'
        for match in re.finditer(money_pattern, text):
            label = match.group(0)
            entities.append(self._make_entity(
                label, "transaction", f"Financial amount: {label}",
                0.85, source_url, "deterministic", now))

        return entities

    def _phase2_spacy(self, text: str, source_url: str, now: int) -> list:
        """Extract named entities using spaCy NER."""
        doc = self.nlp(text[:100000])
        entities = []

        spacy_to_ontology = {
            "PERSON": "person",
            "ORG": "organization",
            "GPE": "location",
            "LOC": "location",
            "FAC": "location",
            "MONEY": "transaction",
            "DATE": "event",
            "EVENT": "event",
        }

        seen_labels = set()
        for ent in doc.ents:
            ontology_type = spacy_to_ontology.get(ent.label_)
            if not ontology_type:
                continue
            if not self.ontology.validate_entity_type(ontology_type):
                continue

            label = ent.text.strip()
            if label in seen_labels or len(label) < 2:
                continue
            seen_labels.add(label)

            entities.append(self._make_entity(
                label, ontology_type, "",
                0.7, source_url, "spacy_ner", now))

        return entities

    def _phase3_llm_local(self, text: str, source_url: str,
                          existing_entities: list, now: int) -> dict:
        """LLM extraction via local Ollama model, over ONE chunk of text.

        Called once per chunk by extract_from_text (see P0.1). Each edge carries
        an ``evidence`` span — the verbatim text that states the relationship —
        so a connection is auditable (P0.2): the graph can show *why* two entities
        are linked, not just that they are.
        """
        import ollama

        type_guidance = self.ontology.get_extraction_prompt_context()
        edge_guidance = self.ontology.get_edge_prompt_context()
        existing_labels = [e["label"] for e in existing_entities[:30]]

        prompt = f"""Analyze this text and extract entities and relationships.

{type_guidance}

{edge_guidance}

Already extracted entities: {', '.join(existing_labels) if existing_labels else 'none yet'}

Respond ONLY with valid JSON. No preamble, no markdown.
Format:
{{
  "entities": [
    {{"label": "...", "type": "...", "description": "..."}}
  ],
  "edges": [
    {{"source": "entity label", "target": "entity label", "type": "EDGE_TYPE",
      "evidence": "short verbatim quote from the text that states this relationship"}}
  ]
}}

Text to analyze:
{text}"""

        try:
            # Timed client: a cold/saturated Ollama raises on timeout instead of
            # hanging the whole ingest. The except below turns any failure into a
            # skipped extraction for this doc (deterministic + spaCy phases stand).
            client = ollama.Client(timeout=config.EXTRACT_TIMEOUT)
            response = client.chat(
                model=config.LOCAL_EXTRACTION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            result = json.loads(response["message"]["content"])
        except Exception as e:
            logger.warning("LLM extraction failed (skipping doc's LLM phase): %s", e)
            return {"entities": [], "edges": []}

        # Convert LLM output to our format
        entities = []
        for e in result.get("entities", []):
            etype = e.get("type", "").lower()
            label = e.get("label", "")
            if not label or not self.ontology.validate_entity_type(etype):
                continue
            entities.append(self._make_entity(
                label, etype, e.get("description", ""),
                0.6, source_url, f"llm_{config.LOCAL_EXTRACTION_MODEL}", now))

        edges = []
        for e in result.get("edges", []):
            etype = e.get("type", "").upper()
            if not self.ontology.validate_edge_type(etype):
                continue
            src_label = e.get("source", "")
            tgt_label = e.get("target", "")
            src_id = self._find_entity_id(src_label, entities + existing_entities)
            tgt_id = self._find_entity_id(tgt_label, entities + existing_entities)
            if src_id and tgt_id:
                edges.append({
                    "source_id": src_id,
                    "target_id": tgt_id,
                    "edge_type": etype,
                    "weight": 1.0,
                    "confidence": 0.6,
                    # The verbatim span justifying the edge (capped) — the audit
                    # trail an investigator needs before quoting a connection.
                    "evidence": (e.get("evidence", "") or "").strip()[:500],
                    "source_url": source_url,
                    "provenance": f"llm_{config.LOCAL_EXTRACTION_MODEL}",
                    "created_at": now,
                })

        return {"entities": entities, "edges": edges}

    def _phase3_llm_remote(self, text: str, source_url: str,
                           existing_entities: list, now: int) -> dict:
        """LLM extraction via remote API (hybrid/remote mode)."""
        logger.info("Remote extraction not yet configured, falling back to local")
        return self._phase3_llm_local(text, source_url, existing_entities, now)

    def _make_entity(self, label: str, entity_type: str, description: str,
                     confidence: float, source_url: str, provenance: str,
                     now: int) -> dict:
        """Build a standard entity dict."""
        return {
            "id": generate_entity_id(label, entity_type, source_url),
            "entity_type": entity_type,
            "label": label,
            "description": description,
            "confidence": confidence,
            "source_url": source_url,
            "provenance": provenance,
            "created_at": now,
            "updated_at": now,
        }

    def _find_entity_id(self, label: str, entities: list) -> str | None:
        """Find entity ID by label match."""
        label_lower = label.lower().strip()
        for e in entities:
            if e["label"].lower().strip() == label_lower:
                return e["id"]
        # Fuzzy fallback: substring match
        for e in entities:
            if label_lower in e["label"].lower() or e["label"].lower() in label_lower:
                return e["id"]
        return None
