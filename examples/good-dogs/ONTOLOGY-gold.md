# Good Dogs — Gold-Annotation Ontology (permissive render)

This ontology is used **only** to build the *gold* graph — the one assembled from
the good-dog-corpus's own hand-curated frontmatter `entities:`/`edges:` blocks
(`scripts/build_graph_from_corpus_gold.py`), as opposed to the noisy graph our LLM
extractor produces from the raw prose.

The gold annotations are **canonical by construction** (the corpus was designed so
its entity IDs interconnect), so this ontology deliberately uses **wildcard
domain/range** (`any → any`) on every edge: it preserves the corpus's designed
graph faithfully rather than re-litigating grade-locality on data that is already
clean. The strict, investigation-generic constraints live in the sibling
`ONTOLOGY.md` (used for the extraction graph).

## Entity Types

| Type | Description | Archetypical | Atypical | Exotypical (NOT this type) |
|------|-------------|-------------|----------|---------------------------|
| breed | A recognized dog breed or breed group | "American Pit Bull Terrier" | "AmStaff" | "the AKC" → organization |
| person | A named individual | "Dr. Lisa Freeman" | "L. David Mech" | "Tufts" → organization |
| organization | A body, registry, university, municipality, or regulator | "City of Denver" | "AVSAB" | "the mayor" → person |
| document | A study, article, bylaw, statute, or recall notice (corpus `publication`) | "Mech 1999" | "Denver Ordinance 404 (1989)" | "the council vote" → event |
| concept | An idea, methodology, or policy | "Breed-specific legislation" | "dominance theory" | "the repeal vote" → event |
| product | A commercial product, brand, or SKU | "Hill's Science Diet" | "a recalled lot" | "Hill's (the company)" → organization |
| event | A dated occurrence | "Denver ban repeal (2020)" | "AKC recognizes the breed (1936)" | "the ordinance text" → document |
| location | A city, region, or jurisdiction | "Denver, CO" | "Ontario, Canada" | "City Hall" → organization |

## Edge Types

| Type | From → To | Description | Investigative Signal |
|------|-----------|-------------|---------------------|
| AUTHORED | any → any | Authorship (corpus `authored_by`, direction normalized) | Attribution |
| AFFILIATED_WITH | any → any | Person↔institution affiliation | Institutional clusters |
| MEMBER_OF | any → any | Membership in a body | Committee/panel networks |
| ABOUT | any → any | Primary subject (corpus `subject_of`) | Topic anchoring |
| MENTIONS | any → any | A document references an entity | The connective tissue between documents and the things they discuss |
| CITES | any → any | Document references another document | Evidence lineage |
| CONTRADICTS | any → any | Incompatible claims | The grain-free/DCM and dominance debates |
| SUPERSEDES | any → any | Newer replaces older | Consensus shifts |
| REGULATES | any → any | Regulatory jurisdiction | Who has authority |
| ALIAS_OF | any → any | Same canonical entity, different surface form | Entity resolution |
| GROUPED_UNDER | any → any | Breed → breed group | Taxonomic spine |
| LOCATED_AT | any → any | Spatial scoping (corpus `located_in`) | Geographic clustering |

## Note

Wildcard ranges are appropriate **only** because this graph is built from curated,
canonical annotations. Do not point the LLM extractor at this file — for extraction
the strict `ONTOLOGY.md` is what catches mis-typed and phantom edges.
