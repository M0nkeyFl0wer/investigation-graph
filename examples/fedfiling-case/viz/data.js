/* data.js — the single JSONL data adapter for both views.
 *
 * Loads the REAL curated findings + provenance manifest at runtime (read-only)
 * and joins them into one in-memory model that both View A (D3 timeline) and
 * View B (Cytoscape murder board) consume. No data ever leaves the browser.
 *
 * Source of truth (all relative to examples/fedfiling-case/, the serve root):
 *   report-private/findings/entities.jsonl      (23 entities)
 *   report-private/findings/edges.jsonl         (28 edges)
 *   report-private/investigation-log.jsonl      (CASE-lane steps)
 *   evidence/manifest.jsonl + evidence-private/manifest.jsonl  (chain of custody)
 *
 * The viz lives in viz/ and is served from the case dir, so these resolve as
 * ../report-private/... and ../evidence/... from index.html.
 */

const DATA = (() => {
  const BASE = "..";
  const PATHS = {
    entities: `${BASE}/report-private/findings/entities.jsonl`,
    edges: `${BASE}/report-private/findings/edges.jsonl`,
    log: `${BASE}/report-private/investigation-log.jsonl`,
    manifests: [
      `${BASE}/evidence/manifest.jsonl`,
      `${BASE}/evidence-private/manifest.jsonl`,
    ],
  };

  /* ---- shared visual grammar constants (ONTOLOGY -> visual encoding) ---- */

  // Edge colour = source_tier. Single-hue value ramp, dark = stronger authority
  // (registry/gov-primary) -> lightest grey = aggregator-secondary. Colourblind-safe.
  // Keyed by the tier *family* a tier string falls into.
  const TIER_RAMP = [
    { test: (t) => /registry-primary|gov-primary/.test(t), color: "#1a1a1a", rank: 5, label: "registry / gov primary" },
    { test: (t) => /registry-dns/.test(t),                 color: "#374151", rank: 4, label: "registry DNS" },
    { test: (t) => /primary-email|journalism/.test(t),     color: "#6b6f76", rank: 3, label: "primary-email / journalism" },
    { test: (t) => /company-site|vendor-site|encyclopedia/.test(t), color: "#9aa0a6", rank: 2, label: "company-site / encyclopedia" },
    { test: (t) => /aggregator-secondary/.test(t),         color: "#c4c8cd", rank: 1, label: "aggregator-secondary" },
  ];
  function tier(t) {
    t = t || "";
    for (const band of TIER_RAMP) if (band.test(t)) return band;
    return { color: "#c4c8cd", rank: 1, label: t || "unknown" };
  }

  // Edge line-style = inference level. dashed = INFERRED / inferential:true.
  function lineStyle(edge) {
    if (edge.status === "INFERRED" || edge.inferential === true || edge.status === "UNVERIFIED") return "dashed";
    if (edge.status === "CORROBORATED") return "solid"; // lighter weight handled via conf
    return "solid"; // VERIFIED / CAPTURED
  }

  // Confidence -> opacity + weight. conf is 0.4..0.95.
  function confOpacity(conf) { return 0.35 + 0.6 * (conf == null ? 0.6 : conf); }
  function confWidth(conf)   { return 1.2 + 4.0 * (conf == null ? 0.6 : conf); }

  // Node glyph = entity_type. trust = organization w/ double border; SAM.gov shield.
  function nodeKind(ent) {
    const isTrust = /trust/i.test(ent.id) || /trust/i.test(ent.label || "");
    const isGov = ent.id === "samgov" || /gov-primary/.test(ent.source_tier || "");
    return {
      type: ent.type,
      isTrust,
      isGov: ent.id === "samgov" ? true : isGov && ent.type === "organization",
      isGap: isGapEntity(ent),
    };
  }

  // GAP entities: the real unknowns. UNSUPPORTED/needs_review confidence.
  function isGapEntity(ent) {
    return ent.confidence === "UNSUPPORTED" || ent.quality_flag === "needs_review";
  }

  /* ---- evidential-distance ring assignment (View B concentric) ---- */
  // ring 1 (innermost, highest authority) = the nucleus + directly documented
  //   controllers/agents on the registry record.
  // ring 2 = corroborated operators / hub addresses / domains.
  // ring 3 (outermost) = inferred operators, GAP nodes, biographical cluster.
  const RING = {
    "fed-filing-llc": 4, "humberto-hernandez": 4, // nucleus
    "hanna-avenue-trust": 3, "paris-street-trust": 3, "dana-foit": 3, "samgov": 3,
    "fedfiling-com": 3, "federalfiling-com": 3, "federalfiling-us": 3,
    "valor-media-group": 2, "addr-2407-courtney": 2, "liadan-enterprises": 2,
    "addr-701-howard": 2, "addr-4809-ehrlich": 2, "the-spam-email": 2,
    "jonathan-mullen": 2, "samgov-impersonation": 2,
    "adrian-gobea": 1, "david-holland": 1, "usa-filing": 1,
    "no-mercy": 1, "ariel-hernandez": 1, "marty-cintron": 1, "brandbox": 1,
  };
  function ringScore(id) { return RING[id] != null ? RING[id] : 1; }

  // biographical / non-scam cluster recedes (light grey, toggle).
  const BIOGRAPHICAL = new Set([
    "no-mercy", "ariel-hernandez", "marty-cintron", "brandbox",
  ]);

  /* ---- loader ---- */
  async function fetchJsonl(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`fetch ${path}: ${res.status}`);
    const text = await res.text();
    return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => JSON.parse(l));
  }

  async function load() {
    const [entities, edges, log] = await Promise.all([
      fetchJsonl(PATHS.entities),
      fetchJsonl(PATHS.edges),
      fetchJsonl(PATHS.log),
    ]);

    // manifest: key by artifact_id AND capture_group so an edge's
    // evidence_artifact (which is a capture_group in this case) resolves.
    const manifest = new Map();          // artifact_id -> record
    const byGroup = new Map();           // capture_group -> [records]
    for (const p of PATHS.manifests) {
      let recs = [];
      try { recs = await fetchJsonl(p); } catch (e) { /* private manifest may be absent */ }
      for (const r of recs) {
        manifest.set(r.artifact_id, r);
        const g = r.capture_group || r.artifact_id;
        if (!byGroup.has(g)) byGroup.set(g, []);
        byGroup.get(g).push(r);
      }
    }

    // resolve an evidence_artifact ref -> the best provenance record.
    // prefer screenshot, then html, then pdf, then anything; fall back to direct id.
    function resolveProvenance(ref) {
      if (!ref) return null;
      if (manifest.has(ref)) return manifest.get(ref);
      const group = byGroup.get(ref);
      if (group && group.length) {
        const order = { screenshot: 0, html: 1, pdf: 2 };
        const sorted = [...group].sort(
          (a, b) => (order[a.kind] ?? 9) - (order[b.kind] ?? 9)
        );
        return sorted[0];
      }
      return null;
    }

    const entById = new Map(entities.map((e) => [e.id, e]));

    // degree (node size in View B)
    const degree = new Map();
    for (const e of edges) {
      degree.set(e.from, (degree.get(e.from) || 0) + 1);
      degree.set(e.to, (degree.get(e.to) || 0) + 1);
    }

    return {
      entities, edges, log, entById, degree,
      resolveProvenance, manifest,
      grammar: { tier, lineStyle, confOpacity, confWidth, nodeKind, ringScore, isGapEntity },
      BIOGRAPHICAL, TIER_RAMP, PATHS,
    };
  }

  return { load };
})();
