# Sample investigation — "Harbor City"

A tiny, fictional graft case used as the worked example throughout the main
README. Three documents that deliberately share entities (a commissioner, a
developer, a redevelopment authority, a contract) so the graph has connections —
and gaps — to find.

| File | What it is |
|------|------------|
| `harbor-city-expose.txt` | A news exposé about a contract approved despite a conflict of interest |
| `property-records.md` | Property/ownership records for the parcel in question |
| `financial-disclosure.html` | A commissioner's annual financial disclosure |

## Try it

```bash
mkdir -p ingest
cp examples/sample-investigation/* ingest/
python scripts/ingest_folder.py      # ingest → extract → ground → build
python scripts/run_analysis.py       # gaps, bridges, surprising connectors
python scripts/search_cli.py -q "payments to contractors"
python scripts/search_cli.py --path "Chen" "Meridian"
```

Everything is fictional — safe to share and re-run. These are public-records-style
documents, not sensitive material; use them to learn the workflow before pointing
the tool at a real investigation.
