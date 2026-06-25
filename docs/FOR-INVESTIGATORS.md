# investigation-graph for investigators — the *why* and *how*

This is the field guide. The [README](../README.md) tells you *what* the tool is
and how to install it; this tells you *why* you'd use it on a real case and *how*
to work with it without fooling yourself.

Written for journalists, OSINT investigators, and researchers — anyone who ends
up with a pile of documents and the question *"what connects these, and what am
I missing?"*

---

## Why a graph, not a folder of PDFs

You already have search. Search answers *"where is the word 'Meridian'?"* It does
not answer:

- *Who connects Robert Chen to Meridian Holdings, and through how many hops?*
- *Which two clusters of entities **should** be connected but aren't — i.e.,
  where's the document I haven't found yet?*
- *Who is structurally central but barely mentioned* — the quiet fixer who
  appears once but sits on the only path between two networks?

Those are **relationship** and **structure** questions. A knowledge graph makes
them first-class: people, orgs, money, places, and events become nodes; the
relationships become typed, source-tagged edges. Once your documents are a graph,
the *shape* of the case becomes visible — and the **holes in the shape are
leads**.

The core bet of this tool (after the Princeton "domain-specific KG over monolithic
LLM" argument): **structure you can audit beats an AI that confidently summarizes.**

---

## This isn't theoretical — it's how the big investigations were done

Knowledge graphs are the standard tool behind the most consequential document-leak
investigations of the last decade. This toolkit puts the same *method* on your
laptop, at a scale one person can run.

- **The Panama / Paradise Papers (ICIJ).** The International Consortium of
  Investigative Journalists loaded a **2.9 TB, ~11.9-million-record** leak into a
  graph database (Neo4j) to trace offshore shell companies, their officers, and
  beneficial owners across jurisdictions. The work won a **Pulitzer**. ICIJ's own
  framing: *"relationships are all important… understanding relationships at huge
  scale is where graph techniques excel."* They later baked graph-building into
  [Datashare](https://www.icij.org/inside-icij/2024/02/datashares-new-plug-in-helps-investigative-journalists-connect-the-dots-with-graphs/),
  their free leak-analysis platform. ([ICIJ × Neo4j](https://neo4j.com/customer-stories/icij/) ·
  [Paradise Papers](https://www.prnewswire.com/news-releases/the-international-consortium-of-investigative-journalists-uses-neo4js-native-graph-platform-to-unlock-explosive-13-million-files-paradise-papers-leak-300555204.html) ·
  [open Panama Papers graph dataset](https://github.com/neo4j-graph-examples/icij-panama-papers))
- **The Azerbaijani Laundromat.** A money-laundering scheme that moved hundreds of
  billions through **~500 shell companies**, surfaced from **~17,000 leaked
  documents** — wire transfers and fabricated invoices. The investigative move was
  exactly ours: **resolve entities** (the same company/person under many spellings)
  and **connect them by typed relationships** so the structure of the scheme
  becomes visible. ([Paco Nathan on entity resolution for anti-fraud graphs](https://odsc.medium.com/paco-nathan-on-entity-resolution-graphs-and-the-future-of-anti-fraud-ai-8766b80b7e85))
- **Entity resolution is the backbone.** Practitioners like **Paco Nathan**
  (Senzing) make the case that *entity-resolved* graphs are what make downstream
  anti-fraud / intelligence work possible — because "J. Smith", "John Smith", and
  "Smith Holdings Ltd." have to collapse to the right nodes before any pattern is
  real. That's why this tool bakes entity resolution and a grounding gate into the
  core, not as add-ons.

**What's different here:** those teams had data engineers, a Neo4j cluster, and
months. This toolkit gives a solo investigator the same primitives —
source-traced entities, typed relationships, entity resolution, gap/topology
analysis — **locally, privately, on one machine.** You won't process 2.9 TB on a
laptop, but the *method* is identical, and most real cases (a scam operator, a
procurement conflict, a local corruption story) are far smaller than the Panama
Papers and well within reach.

---

## The mental model

- **Entities** — the things: `person`, `organization`, `transaction`, `asset`,
  `location`, `event`, `document`, `claim`. Every entity records *which document*
  it came from.
- **Edges** — typed relationships: `EMPLOYED_BY`, `FUNDED_BY`, `OWNS`, `PAID_TO`,
  `CONTRACTED_WITH`, `BOARD_MEMBER_OF`, … An edge is only allowed between sensible
  types (a person can be `EMPLOYED_BY` an organization; an organization can't be
  `EMPLOYED_BY` a person). That rule is enforced, so the graph stays legible.
- **The corpus lives in two places** you never have to think about: text +
  search in DuckDB, the relationship graph in LadybugDB. One folder
  (`data/`) = your whole investigation. Copy it, encrypt it, move it.

---

## The workflow, and what *you* do at each stage

The tool runs five stages. Your job is different at each one.

| Stage | The tool does | **You do** |
|-------|---------------|------------|
| **scope** | loads the ontology (entity/edge types) | Decide your beat. Edit `ONTOLOGY.md` if your case needs types it doesn't ship with (permits, vessels, shell companies…). |
| **ingest** | chunks + embeds your documents | Drop documents in `ingest/`. Garbage in, garbage out — give it the real material. |
| **extract** | pulls entities + relationships (regex → spaCy → local LLM) | Nothing yet — but know the LLM is small and reads only the **start** of long docs (see limits). |
| **ground** | **drops** entities/edges not supported by the text, **merges** duplicate names | Nothing — this is the tool refusing to invent. Read the "Quarantined" line: it tells you how much it threw out. |
| **use** | search, path-finding, gap/bridge analysis, briefings | **This is where you work.** |

```bash
python scripts/ingest_folder.py        # scope → ingest → extract → ground → build
python scripts/run_analysis.py         # gaps, bridges, surprising connectors
python scripts/search_cli.py -q "payments to contractors"
python scripts/search_cli.py --path "Chen" "Meridian"
python scripts/daily_briefing.py       # what changed / what needs attention
```

---

## How to read the output (where the leads are)

- **Structural gaps** = *your next FOIA/records request.* Two dense clusters with
  zero edges between them means your documents cover two related areas you haven't
  connected. The gap question is literally "go find the document that links
  these."
- **Bridges** = *fragile, load-bearing connections.* A single edge holding two
  networks together is both a finding and a thing to corroborate before you rely
  on it.
- **Surprising connections** (high betweenness, low degree) = *the quiet
  connector.* Someone mentioned once who sits on the only path between two groups
  is exactly who you call next.
- **The "Quarantined" count** = *the tool's honesty.* It's how many extracted
  claims didn't survive verification against the source text. A high number means
  noisy documents or a weak extraction pass — not connections to trust.

---

## The discipline (read this twice)

This is a **lead generator and a structure-finder, not a source of findings.**
Before anything goes in a story or a report:

1. **Verify every connection against the original document yourself.** The graph
   says *"this edge exists"*; you confirm *"the document actually says this."*
2. **Check identity before you accuse.** The tool merges "Jane Smith" and "J.
   Smith" when it's confident — and it can be wrong. Two different people fused
   into one node is how an automated graph libels someone. Confirm that linked
   entities are the same human/org.
3. **Mind what the extraction missed.** The local model reads only the first
   ~4,000 characters of each document for *relationships* (entities get more). On
   a long filing, connections buried on page 12 won't appear. Split long
   documents, or treat the graph as "leads from the tops of documents."
4. **Triangulation can out a source.** Even with names redacted, the unique
   *pattern* of connections around a confidential source can identify them.
   Before sharing any export or visualization, ask whether the structure itself
   reveals who talked.

---

## OPSEC

- **Default is fully local.** No cloud, no accounts, no telemetry. Extraction and
  embeddings run on your machine via Ollama. For sensitive sources, keep it that
  way (don't switch on hybrid/remote mode for confidential material).
- **The graph is an intelligence product.** Treat `data/` with the same care as
  your source list — full-disk encryption at minimum; encrypted volume for
  sensitive cases.
- **Sharing:** the whole case is `data/` + `ONTOLOGY.md`. Share deliberately, over
  encrypted transfer, and review what the structure reveals first.

---

## Honest limitations (so you use it right)

- **Grounding checks co-occurrence, not the relationship.** The ground gate drops
  entities not in your text and edges between entities that never appear together —
  but if two real entities *are* named in the same passage, an edge the model
  invented between them (a wrong `PAID_TO`, a fabricated `OWNS`) will pass. The gate
  proves they were mentioned together; it does **not** prove the link. This is the
  one place to be most careful: read the stored source sentence for every edge
  before you rely on it.
- **Long documents:** relationship extraction sees the first ~4,000 chars per doc
  today. Split big PDFs into sections before ingesting if relationships matter.
- **Scanned PDFs / images:** not read. `pdftotext` extracts digital text only —
  scanned filings, photos of documents, and screenshots won't enter the graph
  until you OCR them first.
- **Edge evidence:** every edge stores the exact source sentence that justified it
  (a verbatim span, plus the document and confidence), so you can read the model's
  evidence directly. It can still be wrong — the model can misread a sentence — so
  re-check the full source before quoting a connection.
- **Extraction model:** the default is a small (3B) local model. It misses and
  mislabels on dense legal/financial prose. Bigger local models (set in
  `config.py`) help; verification is still on you.
- **Single user, terminal-based** today. A guided wizard is planned.

None of these are reasons not to use it — they're reasons to use it *as a map of
where to look*, not as the evidence itself.

---

## A worked example

The bundled `examples/sample-investigation/` is a fictional Harbor City graft case
— a commissioner, a developer, a redevelopment authority, a contract approved
despite a conflict. Run it end to end:

```bash
mkdir -p ingest && cp examples/sample-investigation/* ingest/
python scripts/ingest_folder.py
python scripts/run_analysis.py        # see the gap + the bridges
python scripts/search_cli.py --path "Chen" "Meridian"
```

Watch what the analysis surfaces: the bridge between the Planning Commission and
the developer's advisors, the redevelopment authority sitting between the parcel's
old and new owners. That's the shape of the story — now go confirm it in the
documents.
