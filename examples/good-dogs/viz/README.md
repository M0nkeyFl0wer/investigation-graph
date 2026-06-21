# Good Dogs — offline knowledge-graph visualization

A fully offline, two-view visualization of the **Good Dogs** public knowledge
graph: the good dogs (breeds), the good dog people and institutions
(researchers, vets, journalists, councils, kennel clubs, regulators), and how
knowledge *about* dogs connects across six domains.

Built on the gold graph in `../findings-gold/` — 176 entities, 255
relationships, all from public sources, zero PII.

## How to open

It's fully self-contained. Either:

- **Double-click `index.html`** — it works straight off disk (`file://`); the
  graph is inlined in `data.js`, and every library is vendored under `vendor/`.
  No network access is made at any point.
- **Or serve it statically** (nicer for some browsers' file:// rules):

  ```bash
  cd examples/good-dogs/viz
  python3 -m http.server 8080
  # then open http://localhost:8080/
  ```

## What you're looking at

**The network** (Cytoscape) — node *shape* is the entity type (breeds get a
double ring; concepts are diamonds; studies are rectangles), node *colour* is
one of the six knowledge domains, and node *size* is its degree. The payoff is
the **cross-domain bridges** — a breed or concept that ties research to policy
to journalism, which a flat keyword search never surfaces.

- **`research → policy gap` switch** — the loop demo. "Open" hides the 2014 AVMA
  literature review; flip it to "closed" and the AVMA review appears in teal,
  closing the path *behavioural research → AVMA review → breed-specific
  legislation*.
- **`trace the disagreements`** — isolates the `CONTRADICTS` edges (drawn in a
  distinct dashed red): the grain-free/DCM reframing, dominance vs
  positive-reinforcement, open vs closed stud books. The graph **records the
  disagreement instead of averaging it away.**
- **domain dropdown** — focus a single domain and its immediate neighbours.

**The timeline** (D3) — the same dated studies, recalls, bylaws, and events on a
**real calendar axis**. Arcs above the spine are the `SUPERSEDES` chains (solid:
dominance theory → positive reinforcement; the Hill's vitamin-D recall
lifecycle; the BSL repeals) and `CONTRADICTS` chains (dashed red).

Click any node, edge, or timeline dot to open the **evidence panel** — its
label, type, domain, relationships, and for edges the verbatim evidence quote +
confidence.

## Regenerating the data

`data.js` is generated from the gold graph. After the gold `entities.jsonl` /
`edges.jsonl` change, regenerate it:

```bash
python3 examples/good-dogs/viz/gen_data.py
```

The generator (stdlib only) inlines the graph, assigns each entity to one of the
six domains by keyword signature, extracts calendar years from labels/ids, and
tags the AVMA bridge node + its six edges for the before/after toggle. It prints
a summary of counts you can diff against expectations.

## Headless self-check

The page exposes `window.__selfCheck()` returning node/edge counts, the
contradicts and bridge-edge counts, the dated-entity count, the rendered dashed
contradiction count, and any captured `jsErrors`. Used by the verification
harness; handy in the browser console too.

## Notes

- **Offline by construction**: no `src="http..."`, no `fetch()`, no CDN, no
  telemetry. Verify with `grep -R 'http' index.html app.js data.js` (the only
  hits are inside the minified vendor libs' license/XML-namespace strings, which
  are never dereferenced).
- The source of truth is the **gold graph** (`../findings-gold/`). This viz is a
  read-only view of it.
