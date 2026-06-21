# Good Dogs — Sample Ontology v1.0

This is the **sample-local** ontology for the "Good Dogs & Good Dog People"
investigation. The ingest pipeline loads it via `ONTOLOGY_PATH=examples/good-dogs/ONTOLOGY.md`
so the dog-domain run does **not** disturb the investigation-generic root
`ONTOLOGY.md`. The system validates every extracted entity/edge against this file
at write time — types not listed here are rejected and logged.

It is a faithful translation of the public **good-dog-corpus** ontology
(`corpus-source/ontology.yaml`, hand-designed v0.2) into investigation-graph's
table format. The corpus's design narrative lives in `corpus-source/ONTOLOGY.md`;
this file is the operational schema our parser reads.

**Translation decisions (corpus YAML → our tables):**

- `publication` → **document**. The corpus's "study/article/bylaw/recall notice"
  is exactly our `document`. We use the native name; the loader already aliases
  `publication → document`.
- `breed`, `concept`, `product` → **kept as first-class new types**. These have no
  generic-ontology equivalent and they carry the demo (breeds drive alias
  resolution; concepts get superseded; products get recalled/regulated).
- `mentions` (doc → entity) is **omitted as an edge** — the writer creates the
  structural `MENTIONED_IN` (entity → its source document) automatically during
  ingest, so declaring it here would double-count.
- `authored_by` (publication → person) is expressed as native **AUTHORED**
  (person → document) — same relation, our direction convention.
- `located_in` → native **LOCATED_AT**. `subject_of` → **ABOUT**. The rest keep
  their corpus names, uppercased.
- `CONTRADICTS` is declared **document → document** here (the corpus seeds
  contradictions between *publications*, e.g. the 2018 vs 2022 grain-free/DCM
  finding), not the generic `claim → claim`.

## Quality Fields

The system tracks quality metadata on entities and edges:

| Field | Where | Description |
|-------|-------|-------------|
| `extraction_source` | Entity, Edge | How this was extracted: `deterministic`, `nlp`, `llm`, `human` |
| `trust_penalty` | Entity | LLM-extracted items get -0.1, human gets 0.0 |
| `quality_flag` | Entity | `verified`, `needs_review`, `junk` |
| `evidence` | Edge | Quoted source text justifying the relationship |
| `valid_from` | Edge | When this edge became true (timestamp) |
| `valid_until` | Edge | When it stopped being true (0 = still valid) |

## Entity Types

| Type | Description | Archetypical | Atypical | Exotypical (NOT this type) |
|------|-------------|-------------|----------|---------------------------|
| breed | A recognized dog breed or breed group (identity = registry-canonical name) | "German Shepherd Dog" | "Herding Group" (a breed *grouping*, modelled as a breed) | "American Staffordshire Terrier" is NOT "American Pit Bull Terrier" — two registered breeds, never merge |
| person | A named individual: researcher, vet, trainer, journalist, council member | "Dr. Lisa Freeman" | "the unnamed shelter volunteer" | "Tufts Cummings School" → organization |
| organization | A kennel club, university, vet hospital, municipality, manufacturer, or regulator | "American Kennel Club" | "the city council (as a body)" | "the AKC president" → person |
| document | A study, article, bylaw, recall notice, position statement — anything authored (corpus `publication`) | "2018 FDA DCM investigation update" | "an undated breed-standard page" | "the recall event itself" → event |
| concept | An idea, methodology, or policy that gets superseded, regulated, or traversed | "dominance theory"; "positive reinforcement"; "breed-specific legislation" | "the BEG-diet hypothesis" | "the council vote enacting BSL" → event |
| product | A specific commercial product, brand, or SKU | "Hill's Science Diet"; "Acana grain-free" | "a recalled lot number" | "Hill's Pet Nutrition (the company)" → organization |
| event | A dated occurrence: recall announcement, council vote, study publication, attack incident | "Montreal BSL repeal, 2018" | "an undated incident referenced in a bylaw" | "monthly council meetings" → use multiple event entities |
| location | A city, park, shelter, or jurisdiction | "Denver, Colorado"; "Calgary" | "the off-leash park behind the rec centre" | "City Hall (the institution)" → organization |

## Edge Types

| Type | From → To | Description | Investigative Signal |
|------|-----------|-------------|---------------------|
| AUTHORED | person → document | Authorship or byline (corpus `authored_by`, our direction) | Attribution; whose findings these are |
| AFFILIATED_WITH | person → organization | Current affiliation (no time bounds) | Conflicts of interest; institutional clusters |
| MEMBER_OF | person → organization | Membership in a group/body (distinct from employment) | Committee/panel networks |
| GROUPED_UNDER | breed → breed | A breed belongs to a broader breed group (SKOS broader) | The taxonomic spine; gives the otherwise-flat breed set an is-a backbone |
| ALIAS_OF | breed/person/organization/document → breed/person/organization/document | Two surface forms naming the SAME canonical entity. Intended *same-type* (a breed aliases a breed, not a person); grade-locality can't bind "same type as source", so the entity resolver enforces that — the domain/range here just lists the types aliases legitimately apply to | Entity resolution; the GSD/Alsatian and APBT-conflation tests |
| SUPERSEDES | document → document | A newer finding/policy/recommendation replaces an older one | Temporal consensus shifts (dominance theory → positive reinforcement) |
| CONTRADICTS | document → document | Two documents make incompatible claims about the same subject | Inconsistencies; the grain-free/DCM 2018↔2022 debate |
| CITES | document → document | Explicit reference from one document to another | Evidence lineage; which studies a policy leans on |
| REGULATES | organization → product/concept | A regulatory body holds jurisdiction over the entity | Who has authority (FDA over pet food; a municipality over BSL) |
| ABOUT | document → event/concept | The document's PRIMARY subject (corpus `subject_of`, stronger than a mention) | Topic anchoring; separates the core source on X from passing references |
| LOCATED_AT | organization/event → location | Physical or jurisdictional location | Geographic clustering of policy/incidents |

## Extending This Ontology

This sample mirrors the discipline of the root ontology:

- Only add a type when you've seen 3+ instances that don't fit existing types.
- Every edge type should have a clear investigative purpose.
- The exotypical column is load-bearing: it states what does NOT belong, which is
  what prevents the APBT/AmStaff and Hill's-company/Hill's-product collapses.

After editing, run `python scripts/validate_ontology.py` (point it at this file)
to check for formatting errors, then re-validate the taxonomy.
