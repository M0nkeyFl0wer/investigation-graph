# Investigative Ontology v1.0

This file defines every entity type and edge type the knowledge graph accepts.
Edit it for your beat. The system validates all entities against this file at
write time — types not listed here are rejected and logged.

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
| person | An individual — named or described by role | "Jane Smith" | "The unnamed whistleblower" | "Smith & Associates" → organization |
| organization | A company, government body, NGO, political party, or group | "Acme Corp" | "The informal advisory group" | "The CEO" → person |
| document | A source document, filing, record, or publication | "Court filing #2024-1234" | "Handwritten note found in office" | "The filing deadline" → event |
| transaction | A financial transfer, contract, payment, or exchange of value | "$50,000 payment on 2024-03-15" | "In-kind donation of office space" | "The finance committee" → organization |
| location | A physical place, address, jurisdiction, or region | "123 Main St, Suite 400" | "The parking lot behind City Hall" | "City Hall" → organization (the institution, not the building) |
| event | A dated occurrence, meeting, filing, vote, or incident | "Board meeting 2024-01-20" | "Undated dinner referenced in emails" | "Monthly board meetings" → use multiple event entities |
| asset | Property, vehicle, account, financial instrument, or valuable | "Parcel 44-201" | "Cryptocurrency wallet 0x3f..." | "The property management company" → organization |
| claim | A factual assertion from a source, quote, or statement | "No money was exchanged" (press release) | Implied claim from document absence | "The press release" → document |
| domain | A registered internet domain or website (identity = the FQDN) | "fedfiling.com" | "a parked/defunct domain referenced in a filing" | "the hosting company" → organization; "the web page's content" → document |

## Edge Types

| Type | From → To | Description | Investigative Signal |
|------|-----------|-------------|---------------------|
| EMPLOYED_BY | person → organization | Current or former employment | Maps career paths, institutional affiliations |
| BOARD_MEMBER_OF | person → organization | Board, advisory, or governance role | Power structure, decision authority |
| FUNDED_BY | organization → organization/person | Financial support, investment, grants | Money flows, dependency |
| OWNS | person/organization → asset/organization | Ownership, beneficial or direct | Asset tracing, corporate structure |
| PAID_TO | transaction → person/organization | Payment recipient | Follow the money |
| CONTRACTED_WITH | organization → organization | Service or vendor contract | Procurement, conflicts of interest |
| AUTHORED | person → document | Document authorship or signature | Attribution, responsibility |
| MENTIONED_IN | any → document | Entity appears in this document | Provenance, sourcing |
| LOCATED_AT | any → location | Physical or registered location | Geographic connections |
| ATTENDED | person → event | Presence at event, meeting, hearing | Access, relationships |
| OCCURRED_ON | event/transaction → *(date as property)* | Temporal ordering | Timeline construction |
| CONTRADICTS | claim → claim | Two claims from different sources conflict | Inconsistencies, potential deception |
| SUPPORTS | claim → claim | One claim corroborates another | Evidence strength, corroboration |
| OPERATED_BY | organization → person | De-facto operational control of an entity, distinct from formal ownership/employment | Who actually runs a shell whose ownership is obscured (e.g. behind trusts) |
| REGISTERED_AGENT_OF | person/organization → organization | Statutory registered agent named on a corporate filing | Links a named human/firm to a shell company via the corporate registry |
| IMPERSONATES | organization/domain → organization | Poses as or mimics another (often official) entity | Core of imposter/scam schemes; maps the deception target |
| MEMBER_OF | person → organization | Membership in a group/band/club (distinct from formal employment) | Affiliations, pre-history, shared-group networks |
| FAMILY_OF | person → person | Kinship (spouse/sibling/parent/child — specify in a `relation` property) | Beneficial ownership via family; trusted-circle networks |
| OPERATES_DOMAIN | organization → domain | An entity runs/controls this website/domain | Ties a company to its web presence and to sibling sites |
| SIBLING_OF | domain → domain | Two domains are run by the same operator (e.g. shared analytics/Ads IDs) | Maps a single operator's family of interchangeable sites |
| CO_HOSTED_WITH | domain → domain | Two domains resolve to the same hosting IP / tenant (weaker than SIBLING_OF — infra adjacency, not proven common operator) | Surfaces hosting-layer leads; render as a lead, not a same-operator claim |
| ASSOCIATED_WITH | any → any | Unspecified relationship | **Use sparingly** — prefer a typed edge |

## Extending This Ontology

Add rows to the tables above. Keep it simple:

- Only add a type when you've seen 3+ instances that don't fit existing types
- Every edge type should have a clear investigative purpose
- "ASSOCIATED_WITH" is the catch-all — if you're using it a lot, you need more specific edge types
- The exotypical column is important: it shows what does NOT belong to this type, which prevents misclassification

After editing, run `python scripts/validate_ontology.py` to check for formatting errors.

## Beat-Specific Extensions

See `docs/examples/` for ontology extensions:
- `campaign-finance.md` — Donation, PAC, Filing, Disclosure
- `real-estate.md` — Property, Permit, Zoning_Decision, Appraisal
- `corporate.md` — Subsidiary, Beneficial_Owner, SEC_Filing, Executive_Compensation
