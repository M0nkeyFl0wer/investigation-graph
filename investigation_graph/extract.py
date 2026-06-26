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
        # Circuit breaker: per-chunk LLM extraction (P0.1) means many calls per
        # run. If Ollama is down/saturated, one timeout per chunk × N chunks ×
        # M docs would take forever. Once an LLM call hard-fails, we stop calling
        # it for the rest of this run and fall back to deterministic + spaCy only
        # (so an ingest degrades fast instead of hanging). Reset per Extractor.
        self._llm_disabled = False

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
        if config.PRIVACY_MODE in ("local", "hybrid", "remote") and not self._llm_disabled:
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
                if p3 is None:
                    # Hard failure (timeout/connection) — trip the circuit breaker
                    # so we don't pay a timeout on every remaining chunk + doc.
                    self._llm_disabled = True
                    logger.warning("LLM extraction disabled for the rest of this "
                                   "run after a failure; continuing with "
                                   "deterministic + spaCy entities only.")
                    break
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
            # host=None falls back to the default local Ollama; a non-empty
            # EXTRACT_ENDPOINT routes extraction to a remote GPU box (via tunnel).
            client = ollama.Client(host=config.EXTRACT_ENDPOINT or None,
                                   timeout=config.EXTRACT_TIMEOUT)
            response = client.chat(
                model=config.LOCAL_EXTRACTION_MODEL,
                messages=[{"role": "user", "content": prompt}],
                format="json",
            )
            result = json.loads(response["message"]["content"])
        except Exception as e:
            # Return None (not {}) to signal a HARD failure (timeout/connection)
            # so the caller can trip the circuit breaker. An empty-but-successful
            # call still returns {"entities": [], "edges": []} below.
            logger.warning("LLM extraction failed: %s", e)
            return None

        # Convert LLM output to our format. LLMs occasionally emit malformed JSON
        # even under format="json" — e.g. a bare string inside the entities array
        # ("entities": ["German Shepherd", ...]) or a non-list value. Defend
        # against it: a single bad chunk must NOT crash a whole multi-doc ingest.
        raw_entities = result.get("entities", [])
        raw_edges = result.get("edges", [])
        if not isinstance(raw_entities, list):
            raw_entities = []
        if not isinstance(raw_edges, list):
            raw_edges = []

        entities = []
        for e in raw_entities:
            if not isinstance(e, dict):
                continue  # skip bare strings / malformed elements
            etype = e.get("type", "").lower()
            label = e.get("label", "")
            if not label or not self.ontology.validate_entity_type(etype):
                continue
            entities.append(self._make_entity(
                label, etype, e.get("description", ""),
                0.6, source_url, f"llm_{config.LOCAL_EXTRACTION_MODEL}", now))

        edges = []
        for e in raw_edges:
            if not isinstance(e, dict):
                continue  # skip bare strings / malformed elements
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

    # ------------------------------------------------------------------
    # Pairwise + constrained-decoding extraction (the "smarter local" path)
    # ------------------------------------------------------------------
    #
    # WHY a different method instead of the whole-chunk free-generation above:
    # asking a small/mid local model to free-generate a JSON list of *all* the
    # relationships in a chunk is the hard version of the task — it has to
    # simultaneously decide which entities exist, which pairs relate, the type
    # of each, and emit valid JSON, all in one shot. Small models fabricate
    # edges on co-occurrence ("A and B both appear" -> invent a link) and miss
    # negations ("did NOT pay" -> still emit PAID), which wrecks precision on
    # exactly the no-relation / negation traps an investigative graph must not
    # hallucinate.
    #
    # extract_pairwise reframes it as PER-PAIR CLASSIFICATION, which small models
    # do far better:
    #   (a) find the entities in the text (spaCy NER + deterministic money/date),
    #   (b) for each candidate entity PAIR inside a sliding character window,
    #   (c) ask one focused question — "is there a relationship between A and B
    #       *stated in this text*, which ontology type, and quote the exact span"
    #   (d) force the answer through CONSTRAINED DECODING: the model's output is
    #       grammar-constrained to a JSON schema whose `type` field is an enum of
    #       only the allowed edge types plus the sentinel NO_RELATION. The model
    #       literally cannot emit an invalid type or malformed JSON, and it is
    #       given an explicit "no relation" escape hatch so negation/co-occurrence
    #       traps have a correct token to choose instead of being forced to invent.

    def extract_pairwise(self, text: str, source_url: str = "", doc_id: str = "",
                         allowed_edge_types: list[str] | None = None,
                         window_chars: int = 240,
                         model: str | None = None) -> dict:
        """Entity-pair + constrained-decoding relationship extractor.

        Returns the SAME shape as ``extract_from_text``:
        ``{"entities": [...], "edges": [...]}``.

        Args:
            text: the prose to extract from (a sentence or a chunk).
            source_url / doc_id: provenance, carried onto entities/edges.
            allowed_edge_types: the closed vocabulary the model may choose from.
                Defaults to this Extractor's ontology edge types. The eval passes
                its OWN target vocabulary here so the constrained-decoding enum and
                the scoring vocabulary line up (exact-triple scoring is unforgiving
                about edge-type spelling). NO_RELATION is always appended as the
                sentinel "these two are not related here" answer.
            window_chars: only pairs whose mentions fall within this many chars of
                each other are queried — distant entities in a long chunk are
                almost never directly related and querying them wastes calls and
                invites false positives.
            model: Ollama model id; defaults to config.LOCAL_EXTRACTION_MODEL.

        Raises:
            on a hard model failure (unreachable / timeout / contention) the
            underlying ollama exception propagates so the CALLER can decide to
            report DEGRADED rather than silently scoring a half-run. We do NOT
            swallow it into an empty result here — an empty result would look like
            a real (terrible) score, which is worse than an honest "couldn't run".
        """
        import ollama

        now = int(time.time())
        model = model or config.LOCAL_EXTRACTION_MODEL

        # The closed edge vocabulary the model may pick from. Default to the
        # ontology; the eval overrides with its scoring vocabulary.
        if allowed_edge_types is None:
            allowed_edge_types = list(self.ontology.edge_type_names)
        # Normalize, de-dupe, and always offer the explicit "no relation" escape.
        vocab = []
        for t in allowed_edge_types:
            tu = (t or "").upper().strip()
            if tu and tu not in vocab:
                vocab.append(tu)
        SENTINEL = "NO_RELATION"
        enum_types = vocab + [SENTINEL]

        # ---- (a) find entities in this text -----------------------------------
        # Reuse the deterministic + spaCy phases so pairwise sees the same
        # entities the rest of the pipeline does. We record each entity's
        # character offset(s) in the text so we can apply the proximity window.
        ents = self._phase1_deterministic(text, source_url, now) \
            + self._phase2_spacy(text, source_url, now)

        # De-dupe by id but keep first occurrence, and find each label's position.
        by_id: dict[str, dict] = {}
        for e in ents:
            by_id.setdefault(e["id"], e)
        entities = list(by_id.values())

        def _first_pos(label: str) -> int:
            # Character offset of the entity mention (lowercased search), or a
            # large sentinel if not literally present (e.g. normalized spaCy text).
            idx = text.lower().find(label.lower())
            return idx if idx >= 0 else 10**9

        for e in entities:
            e["_pos"] = _first_pos(e["label"])

        # ---- constrained-decoding JSON schema ---------------------------------
        # This is the grammar the model is forced to satisfy. `related` is a bool,
        # `type` is constrained to the closed enum (valid ontology types OR the
        # NO_RELATION sentinel), `evidence` is the verbatim span. A grammar-locked
        # output cannot be malformed JSON and cannot name a type outside the enum.
        schema = {
            "type": "object",
            "properties": {
                "related": {"type": "boolean"},
                "type": {"type": "string", "enum": enum_types},
                "evidence": {"type": "string"},
            },
            "required": ["related", "type", "evidence"],
        }

        # Human-readable type menu for the prompt (the schema enforces it; the
        # prompt explains what each type means so the model picks the right one).
        type_menu_lines = []
        for name in vocab:
            # Pull a description from the ontology when available; otherwise the
            # bare name (the eval's vocabulary may differ from ontology spelling).
            et = self.ontology.edge_types.get(name)
            desc = et.description if et else ""
            type_menu_lines.append(f"  - {name}: {desc}".rstrip())
        type_menu = "\n".join(type_menu_lines)

        client = ollama.Client(host=config.EXTRACT_ENDPOINT or None,
                               timeout=config.EXTRACT_TIMEOUT)

        edges = []
        seen_pairs = set()
        # ---- (b) iterate candidate entity pairs within the window -------------
        for i in range(len(entities)):
            for j in range(len(entities)):
                if i == j:
                    continue
                a, b = entities[i], entities[j]
                # Skip identical labels and out-of-window pairs.
                if a["label"].lower().strip() == b["label"].lower().strip():
                    continue
                if abs(a["_pos"] - b["_pos"]) > window_chars:
                    continue
                # Directed pair; don't ask the same ordered pair twice.
                key = (a["id"], b["id"])
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)

                # ---- (c) the focused per-pair question -----------------------
                prompt = (
                    "You are checking ONE possible relationship in a piece of text.\n"
                    f'Text: "{text.strip()}"\n\n'
                    f'Question: Does the text STATE a direct relationship FROM '
                    f'"{a["label"]}" TO "{b["label"]}"?\n\n'
                    "Rules:\n"
                    "- Only answer yes if the relationship is explicitly stated in "
                    "THIS text, in this direction (subject -> object).\n"
                    "- Negations ('did NOT pay', 'no payment was made') mean NOT "
                    "related.\n"
                    "- Mere co-occurrence ('both attended', 'and') is NOT a "
                    "relationship.\n"
                    "- If unrelated, set related=false and type=\"NO_RELATION\".\n\n"
                    "Choose the type from EXACTLY this list (or NO_RELATION):\n"
                    f"{type_menu}\n"
                    f"  - {SENTINEL}: the text states no such relationship.\n\n"
                    "Quote the exact span of text that states the relationship in "
                    "'evidence' (empty string if NO_RELATION)."
                )

                # ---- (d) constrained-decoding call ---------------------------
                # format=<schema> grammar-constrains the decode. Any hard failure
                # (timeout/connection) raises out of this method to the caller.
                response = client.chat(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    format=schema,
                    options={"temperature": 0},  # deterministic classification
                )
                try:
                    ans = json.loads(response["message"]["content"])
                except (json.JSONDecodeError, KeyError, TypeError):
                    # The grammar should prevent this; if a model still emits junk,
                    # treat THIS pair as "no relation" rather than crashing the run.
                    continue

                rel = bool(ans.get("related"))
                etype = (ans.get("type") or "").upper().strip()
                if not rel or etype == SENTINEL or etype not in vocab:
                    continue  # honest skip — the model said "not related here"

                edges.append({
                    "source_id": a["id"],
                    "target_id": b["id"],
                    "edge_type": etype,
                    "weight": 1.0,
                    "confidence": 0.65,
                    # Verbatim justification span (capped), same audit contract as
                    # the whole-chunk path.
                    "evidence": (ans.get("evidence", "") or "").strip()[:500],
                    "source_url": source_url,
                    "provenance": f"pairwise_{model}",
                    "created_at": now,
                })

        # Strip the internal _pos helper before returning the public shape.
        for e in entities:
            e.pop("_pos", None)

        return {"entities": entities, "edges": edges}

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
