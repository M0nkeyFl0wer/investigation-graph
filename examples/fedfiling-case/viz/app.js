/* app.js — shared shell + View B (Cytoscape) + View A (D3 timeline).
 * One data adapter, one grammar, one provenance panel, cross-view highlight. */

(async function () {
  const M = await DATA.load();
  const G = M.grammar;
  window.__M = M; // expose for the verification harness / debugging

  document.getElementById("counts").textContent =
    `${M.entities.length} entities · ${M.edges.length} edges`;

  /* ---------- shared provenance panel (chain of custody) ---------- */
  const panel = document.getElementById("panel");
  const panelBody = document.getElementById("panel-body");
  document.getElementById("panel-close").onclick = () => panel.classList.add("hidden");

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }

  function showEntityProvenance(ent) {
    const k = G.nodeKind(ent);
    const provRefs = ent.provenance || [];
    const recs = provRefs.map((r) => ({ ref: r, rec: M.resolveProvenance(r) }));
    const t = G.tier(ent.source_tier);
    let html = `<h3>${esc(ent.label)}</h3>`;
    html += `<p class="sub">${esc(ent.type)}${k.isTrust ? " · trust" : ""}${k.isGov ? " · government" : ""}`;
    html += k.isGap ? ` · <span class="badge gap">GAP / unknown</span>` : "";
    html += `</p>`;
    if (ent.note) html += `<div class="fact">${esc(ent.note)}</div>`;
    html += `<div class="kv"><span class="k">confidence</span><span class="v">${esc(ent.confidence)}</span></div>`;
    html += `<div class="kv"><span class="k">source tier</span><span class="v">`
          + `<span class="sw" style="display:inline-block;width:14px;height:9px;background:${t.color};border:1px solid #0002"></span> ${esc(ent.source_tier)} (${esc(t.label)})</span></div>`;
    if (ent.props && Object.keys(ent.props).length) {
      html += `<div class="kv"><span class="k">properties</span><span class="v">`;
      for (const [pk, pv] of Object.entries(ent.props)) html += `<div><b>${esc(pk)}:</b> ${esc(pv)}</div>`;
      html += `</span></div>`;
    }
    html += provenanceRecordsHtml(recs);
    panelBody.innerHTML = html;
    panel.classList.remove("hidden");
  }

  function showEdgeProvenance(e) {
    const t = G.tier(e.source_tier);
    const inferred = e.status === "INFERRED" || e.inferential === true || e.status === "UNVERIFIED";
    const from = M.entById.get(e.from), to = M.entById.get(e.to);
    let html = `<h3>${esc(e.type)}</h3>`;
    html += `<p class="sub">${esc(from ? from.label : e.from)} &rarr; ${esc(to ? to.label : e.to)}</p>`;
    html += inferred
      ? `<p><span class="badge inf">INFERRED — not on the corporate record</span></p>`
      : `<p><span class="badge ver">${esc(e.status)} — documented</span></p>`;
    html += `<div class="kv"><span class="k">evidence_fact (verbatim)</span></div>`;
    html += `<div class="fact">${esc(e.evidence_fact)}</div>`;
    html += `<div class="kv"><span class="k">confidence</span><span class="v">${e.conf}</span></div>`;
    html += `<div class="kv"><span class="k">source tier</span><span class="v">`
          + `<span class="sw" style="display:inline-block;width:14px;height:9px;background:${t.color};border:1px solid #0002"></span> ${esc(e.source_tier)} (${esc(t.label)})</span></div>`;
    html += `<div class="kv"><span class="k">evidence_claim_ok</span><span class="v">${esc(e.evidence_claim_ok)}</span></div>`;
    if (e.note) html += `<div class="kv"><span class="k">note</span><span class="v">${esc(e.note)}</span></div>`;
    const rec = M.resolveProvenance(e.evidence_artifact);
    html += provenanceRecordsHtml([{ ref: e.evidence_artifact, rec }]);
    panelBody.innerHTML = html;
    panel.classList.remove("hidden");
  }

  function provenanceRecordsHtml(recs) {
    if (!recs.length) return "";
    let html = `<div class="kv"><span class="k">chain of custody — artifact(s)</span></div>`;
    for (const { ref, rec } of recs) {
      html += `<div style="margin:0.45rem 0;border-top:1px solid var(--line);padding-top:0.4rem">`;
      html += `<div class="mono"><b>artifact_id:</b> ${esc(ref)}</div>`;
      if (!rec) { html += `<div class="miss">no manifest record resolves this id</div></div>`; continue; }
      html += `<div class="mono"><b>sha256:</b> ${esc(rec.sha256)}</div>`;
      html += `<div class="mono"><b>captured:</b> ${esc(rec.captured_at_utc)}</div>`;
      html += `<div class="mono"><b>kind:</b> ${esc(rec.kind)}</div>`;
      if (rec.source_url)
        html += `<div class="mono"><b>source:</b> <a href="${esc(rec.source_url)}" target="_blank" rel="noopener">${esc(rec.source_url)}</a></div>`;
      html += `</div>`;
    }
    return html;
  }

  /* ---------- legend tier ramp ---------- */
  const ramp = document.getElementById("tier-ramp");
  for (const band of M.TIER_RAMP) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="sw" style="background:${band.color}"></span> ${band.label}`;
    ramp.appendChild(li);
  }
  document.getElementById("legend-toggle").onclick = () =>
    document.getElementById("legend").classList.toggle("collapsed");

  /* ---------- tooltip ---------- */
  const tooltip = document.createElement("div");
  tooltip.id = "tooltip";
  document.body.appendChild(tooltip);
  function showTip(html, x, y) {
    tooltip.innerHTML = html; tooltip.classList.add("show");
    tooltip.style.left = Math.min(x + 12, window.innerWidth - 290) + "px";
    tooltip.style.top = (y + 12) + "px";
  }
  function hideTip() { tooltip.classList.remove("show"); }

  /* ---------- cross-view highlight ---------- */
  let highlighted = null;
  function highlightEntity(id) {
    highlighted = id;
    if (cy) {
      cy.elements().removeClass("xv-hl");
      if (id) cy.getElementById(id).addClass("xv-hl");
    }
    d3.selectAll(".tl-node").classed("tl-hl", false)
      .filter((d) => d && d.id === id).classed("tl-hl", true);
  }

  /* ================= VIEW B — Cytoscape murder board ================= */
  let cy = null;

  function entityToNode(ent) {
    const k = G.nodeKind(ent);
    const t = G.tier(ent.source_tier);
    return {
      data: {
        id: ent.id, label: ent.label, etype: ent.type,
        isTrust: k.isTrust, isGov: k.isGov, isGap: k.isGap,
        tierColor: t.color, tierRank: t.rank,
        ring: G.ringScore(ent.id),
        degree: M.degree.get(ent.id) || 1,
        bio: M.BIOGRAPHICAL.has(ent.id),
        ent,
      },
    };
  }

  function edgeToCyEdge(e, i) {
    const t = G.tier(e.source_tier);
    const dashed = G.lineStyle(e) === "dashed";
    return {
      data: {
        id: `e${i}`, source: e.from, target: e.to,
        label: e.type, etype: e.type,
        dashed, tierColor: t.color,
        opacity: G.confOpacity(e.conf), width: G.confWidth(e.conf),
        conf: e.conf, status: e.status,
        bio: M.BIOGRAPHICAL.has(e.from) || M.BIOGRAPHICAL.has(e.to),
        question: edgeQuestion(e),
        edge: e,
      },
    };
  }

  // map each edge to one or more "investigative question" facets (small multiples).
  function edgeQuestion(e) {
    const q = new Set();
    if (e.type === "OWNS") q.add("owns");
    if (e.type === "OPERATED_BY" || e.type === "REGISTERED_AGENT_OF" || e.type === "OPERATES_DOMAIN" || e.type === "EMPLOYED_BY" || e.type === "AUTHORED") q.add("operates");
    if (e.type === "IMPERSONATES") q.add("impersonates");
    if (e.type === "LOCATED_AT") q.add("located");
    if (e.type === "MEMBER_OF" || e.type === "FAMILY_OF") q.add("identity");
    return [...q];
  }

  const glyphShape = {
    person: "ellipse", organization: "round-rectangle", domain: "ellipse",
    location: "round-tag", document: "round-rectangle", event: "diamond",
    transaction: "diamond", asset: "hexagon", claim: "octagon",
  };

  function buildCy() {
    const nodes = M.entities.map(entityToNode);
    const edges = M.edges.map(edgeToCyEdge);
    cy = cytoscape({
      container: document.getElementById("cy"),
      elements: { nodes, edges },
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            "shape": (n) => n.data("isGov") ? "round-diamond" : (glyphShape[n.data("etype")] || "ellipse"),
            "background-color": "#ffffff",
            "background-opacity": 1,
            "border-width": (n) => n.data("isTrust") ? 4 : 2,
            "border-color": (n) => n.data("isGap") ? "var(--gap)" : (n.data("bio") ? "#c4c8cd" : "#1a1a1a"),
            "border-style": (n) => n.data("isGap") ? "dashed" : (n.data("isTrust") ? "double" : "solid"),
            "label": "data(label)",
            "font-size": 9,
            "color": (n) => n.data("bio") ? "#9aa0a6" : "#1a1a1a",
            "text-wrap": "wrap", "text-max-width": 92,
            "text-valign": "bottom", "text-margin-y": 3,
            "width": (n) => 16 + 5 * Math.sqrt(n.data("degree")),
            "height": (n) => 16 + 5 * Math.sqrt(n.data("degree")),
            "opacity": (n) => n.data("bio") ? 0.55 : 1,
          },
        },
        { selector: "node[?isGov]", style: { "background-color": "#1a1a1a", "color": "#1a1a1a" } },
        {
          selector: "node[?isGap]",
          style: {
            "background-fill": "linear-gradient", "background-opacity": 0.2,
            "border-color": "#b00020", "border-style": "dashed",
            "shape": "ellipse",
          },
        },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "line-color": "data(tierColor)",
            "line-style": (e) => e.data("dashed") ? "dashed" : "solid",
            "width": "data(width)",
            "opacity": "data(opacity)",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "data(tierColor)",
            "arrow-scale": 0.8,
            "label": "data(label)",
            "font-size": 7, "color": "#6b6f76",
            "text-rotation": "autorotate",
            "text-background-color": "#faf9f7", "text-background-opacity": 0.85,
            "text-background-padding": 1,
          },
        },
        { selector: "edge[?bio]", style: { "opacity": 0.3, "line-color": "#c4c8cd", "target-arrow-color": "#c4c8cd" } },
        { selector: ".faded", style: { "opacity": 0.07, "text-opacity": 0 } },
        { selector: "node.faded", style: { "opacity": 0.07, "text-opacity": 0 } },
        { selector: ".xv-hl", style: { "border-color": "#1d4ed8", "line-color": "#1d4ed8",
            "target-arrow-color": "#1d4ed8", "border-width": 5, "opacity": 1, "z-index": 99 } },
        { selector: "node:selected", style: { "border-color": "#1d4ed8", "border-width": 5 } },
      ],
      layout: concentricLayout(),
    });

    cy.on("tap", "node", (evt) => {
      const ent = evt.target.data("ent");
      showEntityProvenance(ent);
      highlightEntity(ent.id);
    });
    cy.on("tap", "edge", (evt) => showEdgeProvenance(evt.target.data("edge")));
    cy.on("tap", (evt) => { if (evt.target === cy) { panel.classList.add("hidden"); highlightEntity(null); } });
    cy.on("mouseover", "edge", (evt) => {
      const e = evt.target.data("edge");
      showTip(`<span class="tt-type">${esc(e.type)} · ${esc(e.status)} · conf ${e.conf}</span><br>${esc(e.evidence_fact)}`,
        evt.renderedPosition.x, evt.renderedPosition.y);
    });
    cy.on("mouseover", "node", (evt) => {
      const n = evt.target.data("ent");
      showTip(`<span class="tt-type">${esc(n.type)}</span><br>${esc(n.label)}`, evt.renderedPosition.x, evt.renderedPosition.y);
    });
    cy.on("mouseout", "node edge", hideTip);
  }

  function concentricLayout() {
    return {
      name: "concentric",
      concentric: (n) => n.data("ring"),     // higher = closer to centre
      levelWidth: () => 1,
      minNodeSpacing: 38,
      spacingFactor: 1.05,
      avoidOverlap: true,
      animate: false,
      fit: true, padding: 50,
      startAngle: (3 / 2) * Math.PI,
    };
  }

  /* ---- View B filters / small multiples ---- */
  function applyCyFilters() {
    if (!cy) return;
    const bio = document.getElementById("t-bio").checked;
    const infOnly = document.getElementById("t-inf").checked;
    const primaryOnly = document.getElementById("t-primary").checked;
    const question = document.getElementById("t-question").value;

    cy.batch(() => {
      cy.elements().removeClass("faded");
      cy.edges().forEach((ed) => {
        const e = ed.data("edge");
        let hide = false;
        if (!bio && ed.data("bio")) hide = true;
        if (infOnly && !(e.status === "INFERRED" || e.inferential === true || e.status === "UNVERIFIED")) hide = true;
        if (primaryOnly && !/registry-primary|gov-primary|registry-dns/.test(e.source_tier)) hide = true;
        if (question !== "all" && !ed.data("question").includes(question)) hide = true;
        if (hide) ed.addClass("faded");
      });
      // fade nodes with no visible edge (except the nucleus)
      cy.nodes().forEach((n) => {
        if (!bio && n.data("bio")) { n.addClass("faded"); return; }
        const keep = ["fed-filing-llc", "humberto-hernandez"].includes(n.id());
        const hasVisible = n.connectedEdges().some((e) => !e.hasClass("faded"));
        if (!keep && !hasVisible) n.addClass("faded");
      });
    });
  }
  ["t-bio", "t-inf", "t-primary"].forEach((id) =>
    document.getElementById(id).addEventListener("change", applyCyFilters));
  document.getElementById("t-question").addEventListener("change", applyCyFilters);
  // bio toggle also re-renders the timeline (shared across both views)
  document.getElementById("t-bio").addEventListener("change", () => {
    if (document.getElementById("view-a").classList.contains("active")) buildTimeline();
  });

  /* ================= VIEW A — D3 dual-track branching timeline ================= */
  // Parse a year out of an entity's date-ish props.
  function entityYear(ent) {
    const p = ent.props || {};
    const cands = [p.filed, p.registered, p.dob, p.era, p.wayback_since];
    for (const c of cands) {
      const m = String(c || "").match(/\b(19|20)\d{2}\b/);
      if (m) return +m[0];
    }
    return null;
  }

  // LIFE-lane events: dated, registry/biographical chronology.
  function lifeEvents() {
    const evts = [];
    for (const ent of M.entities) {
      const y = entityYear(ent);
      if (y == null) continue;
      evts.push({
        id: ent.id, ent, year: y,
        date: new Date(`${y}-01-01`),
        label: ent.label, type: ent.type,
        bio: M.BIOGRAPHICAL.has(ent.id),
        tier: G.tier(ent.source_tier),
      });
    }
    evts.sort((a, b) => a.year - b.year);
    // vertical-dodge collisions: markers within a 2-year window stack upward so
    // labels don't overlap (the 2019-2020 Fed Filing + 3 domains cluster).
    let prevYear = -999, stack = 0;
    for (const e of evts) {
      stack = (e.year - prevYear <= 2) ? stack + 1 : 0;
      e.dodge = stack;
      prevYear = e.year;
    }
    return evts;
  }

  // CASE-lane: investigation-log steps placed at calendar position of ts,
  // ordered by step number (work order ≠ calendar order).
  function caseSteps() {
    return M.log.map((s) => ({
      ...s,
      date: new Date(s.ts),
      hasArtifacts: (s.artifacts || []).length > 0,
    }));
  }

  function buildTimeline() {
    const container = d3.select("#timeline");
    container.selectAll("*").remove();
    const life = lifeEvents();
    const steps = caseSteps();

    const margin = { top: 40, right: 60, bottom: 40, left: 90 };
    const width = Math.max(1100, document.getElementById("timeline").clientWidth - 4);
    const height = document.getElementById("timeline").clientHeight - 4;
    const innerH = height - margin.top - margin.bottom;

    // time domain: range-frame from earliest datum to now.
    const minYear = d3.min(life, (d) => d.year);
    const t0 = new Date(`${minYear}-01-01`);
    const t1 = new Date("2026-09-01");
    const x = d3.scaleTime().domain([t0, t1]).range([margin.left, width - margin.right]);

    const svg = container.append("svg")
      .attr("width", width).attr("height", height)
      .style("display", "block");

    const root = svg.append("g");

    // zoomable inner group (x-rescale only)
    const zoomG = root.append("g");

    const laneLifeY = margin.top + innerH * 0.30;
    const laneCaseY = margin.top + innerH * 0.72;

    // lane labels
    svg.append("text").attr("class", "tl-lane-label").attr("x", 8).attr("y", laneLifeY - 8).text("LIFE");
    svg.append("text").attr("class", "tl-lane-label").attr("x", 8).attr("y", laneCaseY - 8).text("CASE");
    svg.append("text").attr("class", "tl-section").attr("x", 8).attr("y", laneLifeY + 8).text("calendar");
    svg.append("text").attr("class", "tl-section").attr("x", 8).attr("y", laneCaseY + 8).text("work order");
    // annotate the deliberate axis decoupling (lie-factor honesty)
    svg.append("text").attr("class", "tl-section")
      .attr("x", width - margin.right).attr("y", laneCaseY - 44).attr("text-anchor", "end")
      .style("font-style", "italic")
      .text("CASE lane = order we worked it (all pivots 2026-06-20/21), not calendar →");

    // axis + decade grid
    const axisG = svg.append("g").attr("class", "tl-axis").attr("transform", `translate(0,${height - margin.bottom})`);
    const gridG = zoomG.append("g");
    const lifeG = zoomG.append("g");
    const caseG = zoomG.append("g");

    // spines (whisper)
    lifeG.append("line").attr("class", "tl-spine").attr("x1", margin.left).attr("x2", width - margin.right).attr("y1", laneLifeY).attr("y2", laneLifeY);
    caseG.append("line").attr("class", "tl-spine").attr("x1", margin.left).attr("x2", width - margin.right).attr("y1", laneCaseY).attr("y2", laneCaseY);

    function render(scale) {
      // decade grid
      const ticks = scale.ticks(d3.timeYear.every(scale.domain()[1].getFullYear() - scale.domain()[0].getFullYear() > 25 ? 5 : 1));
      const grid = gridG.selectAll("line.tl-tick-grid").data(ticks, (d) => +d);
      grid.enter().append("line").attr("class", "tl-tick-grid")
        .merge(grid)
        .attr("x1", (d) => scale(d)).attr("x2", (d) => scale(d))
        .attr("y1", margin.top - 6).attr("y2", height - margin.bottom);
      grid.exit().remove();

      axisG.call(d3.axisBottom(scale).ticks(8).tickFormat(d3.timeFormat("%Y")));
      axisG.selectAll(".tick text").attr("class", null);

      // ---- LIFE markers ----
      const lm = lifeG.selectAll("g.life-node").data(life, (d) => d.id);
      const lmEnter = lm.enter().append("g").attr("class", "life-node tl-node")
        .on("click", (ev, d) => { showEntityProvenance(d.ent); highlightEntity(d.id); })
        .on("mouseover", (ev, d) => showTip(`<span class="tt-type">${esc(d.type)} · ${d.year}</span><br>${esc(d.label)}`, ev.clientX, ev.clientY))
        .on("mouseout", hideTip);
      lmEnter.append("line").attr("class", "tl-leader");
      appendGlyph(lmEnter);
      lmEnter.append("text").attr("class", "tl-label");
      const lmAll = lmEnter.merge(lm)
        .classed("dim", (d) => d.bio && !document.getElementById("t-bio").checked)
        .attr("transform", (d) => `translate(${scale(d.date)},${laneLifeY - d.dodge * 30})`)
        .attr("data-id", (d) => d.id);
      // leader line back down to the spine for dodged markers
      lmAll.select("line.tl-leader")
        .attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", (d) => d.dodge * 30)
        .attr("stroke", "#d8d5d0").attr("stroke-width", 0.75);
      lmAll.select("text.tl-label")
        .attr("x", 0).attr("y", -12).attr("text-anchor", "middle")
        .text((d) => `${d.year} ${shortLabel(d.label, 26)}`)
        .style("fill", (d) => d.bio ? "#9aa0a6" : "#1a1a1a");
      styleGlyph(lmAll);

      // ---- CASE steps ----
      // Work-order x scale: ALL pivots happened within ~2 days (2026-06-20/21),
      // so a calendar position would pile them in one pixel column. The design
      // (§A.1) renders the CASE lane by WORK ORDER instead — the investigation
      // started at the 2026 email and worked backward. Each step keeps its real
      // timestamp on its badge/tooltip; x = the order we worked it.
      const ordered = [...steps].sort((a, b) => a.step - b.step);
      const cx = d3.scalePoint()
        .domain(ordered.map((s) => s.step))
        .range([margin.left + 20, width - margin.right - 20]).padding(0.5);

      const linkData = ordered.slice(1).map((s, i) => ({ a: ordered[i], b: s }));
      const links = caseG.selectAll("path.tl-step-link").data(linkData, (d) => d.b.step);
      links.enter().append("path").attr("class", "tl-step-link")
        .attr("fill", "none").attr("stroke", "#9aa0a6").attr("stroke-width", 1).attr("marker-end", "url(#wo-arrow)")
        .merge(links)
        .attr("d", (d) => {
          const x1 = cx(d.a.step), x2 = cx(d.b.step);
          const my = laneCaseY - 16;
          return `M${x1},${laneCaseY} C${x1},${my} ${x2},${my} ${x2},${laneCaseY}`;
        });
      links.exit().remove();

      const cm = caseG.selectAll("g.case-node").data(ordered, (d) => d.step);
      const cmEnter = cm.enter().append("g").attr("class", "case-node tl-node")
        .on("click", (ev, d) => showStepProvenance(d))
        .on("mouseover", (ev, d) => showTip(`<span class="tt-type">step ${d.step} · ${esc(d.phase)} · ${esc(d.ts)}</span><br>${esc(d.action)}<br><i>${esc(d.result)}</i>`, ev.clientX, ev.clientY))
        .on("mouseout", hideTip);
      cmEnter.append("circle").attr("r", 9);
      cmEnter.append("text").attr("class", "tl-step-badge").attr("text-anchor", "middle").attr("dy", 3);
      cmEnter.append("line").attr("class", "tl-branch");      // branch stub
      cmEnter.append("text").attr("class", "tl-label tl-branch-phase");
      cmEnter.append("text").attr("class", "tl-label tl-branch-label");
      // alternate branch stubs up/down so labels don't collide
      const cmAll = cmEnter.merge(cm)
        .classed("dim", (d) => d.status === "" )
        .attr("transform", (d) => `translate(${cx(d.step)},${laneCaseY})`);
      cmAll.select("circle")
        .attr("fill", (d) => d.status ? "#1a1a1a" : "#9aa0a6")
        .attr("stroke", "#fff").attr("stroke-width", 1.5);
      cmAll.select("text.tl-step-badge").text((d) => d.step);
      cmAll.select("text.tl-branch-phase")
        .attr("x", 0).attr("y", (d, i) => i % 2 ? 26 : -18).attr("text-anchor", "middle")
        .style("font-size", "8px").style("font-weight", "600").style("fill", "#6b6f76")
        .text((d) => d.phase.replace(/^pivot:/, "→ "));
      cmAll.select("line.tl-branch")
        .attr("x1", 0).attr("x2", 0)
        .attr("y1", (d, i) => i % 2 ? 9 : -9)
        .attr("y2", (d, i) => i % 2 ? 30 : -30)
        .attr("stroke", (d) => d.status ? "#1a1a1a" : "#c4c8cd")
        .attr("stroke-width", 1)
        .attr("stroke-dasharray", (d) => d.status ? null : "3 2");
      cmAll.select("text.tl-branch-label")
        .attr("x", 0).attr("y", (d, i) => i % 2 ? 44 : -36).attr("text-anchor", "middle")
        .style("font-size", "8.5px").style("fill", "#444")
        .text((d) => shortLabel(d.result, 30));
    }

    // arrow marker for work order
    const defs = svg.append("defs");
    defs.append("marker").attr("id", "wo-arrow").attr("viewBox", "0 -4 8 8")
      .attr("refX", 7).attr("refY", 0).attr("markerWidth", 5).attr("markerHeight", 5).attr("orient", "auto")
      .append("path").attr("d", "M0,-3L7,0L0,3").attr("fill", "#9aa0a6");

    function appendGlyph(sel) {
      sel.append("path").attr("class", "tl-glyph");
    }
    function styleGlyph(sel) {
      sel.select("path.tl-glyph")
        .attr("d", (d) => glyphPath(d.type, d.id))
        .attr("fill", "#fff")
        .attr("stroke", (d) => d.bio ? "#c4c8cd" : "#1a1a1a")
        .attr("stroke-width", (d) => isTrustEnt(d) ? 3 : 1.6)
        .attr("opacity", (d) => d.bio ? 0.6 : 1);
    }
    function isTrustEnt(d) { return /trust/i.test(d.id); }

    render(x);

    // zoom (x only)
    const zoom = d3.zoom().scaleExtent([1, 40])
      .translateExtent([[0, 0], [width, height]])
      .extent([[margin.left, 0], [width - margin.right, height]])
      .on("zoom", (ev) => render(ev.transform.rescaleX(x)));
    svg.call(zoom);
  }

  function showStepProvenance(s) {
    let html = `<h3>Step ${s.step} &middot; ${esc(s.phase)}</h3>`;
    html += `<p class="sub">${esc(s.ts)} &middot; ${esc(s.method)}</p>`;
    if (s.status) html += `<p><span class="badge ver">${esc(s.status)}</span></p>`;
    html += `<div class="kv"><span class="k">action</span><span class="v">${esc(s.action)}</span></div>`;
    html += `<div class="kv"><span class="k">target</span><span class="v">${esc(s.target)}</span></div>`;
    html += `<div class="kv"><span class="k">result</span><span class="v">${esc(s.result)}</span></div>`;
    const arts = s.artifacts || [];
    if (arts.length) {
      const recs = arts.map((r) => ({ ref: r, rec: M.resolveProvenance(r) }));
      html += provenanceRecordsHtml(recs);
    } else {
      html += `<div class="kv"><span class="k">artifacts</span><span class="v miss">none recorded for this step</span></div>`;
    }
    panelBody.innerHTML = html;
    panel.classList.remove("hidden");
  }

  // SVG glyph paths per entity type (small, centred on 0,0).
  function glyphPath(type, id) {
    const r = 7;
    if (/trust/i.test(id)) return roundedRect(-9, -6, 18, 12, 2);      // org (double stroke applied)
    switch (type) {
      case "person": return circlePath(r);
      case "domain": return circlePath(r);                               // dotted handled elsewhere; keep simple
      case "organization": return roundedRect(-9, -6, 18, 12, 2);
      case "location": return pinPath();
      case "document": return roundedRect(-6, -8, 12, 16, 1);
      default: return circlePath(r);
    }
  }
  function circlePath(r) { return `M${-r},0 a${r},${r} 0 1,0 ${2 * r},0 a${r},${r} 0 1,0 ${-2 * r},0`; }
  function roundedRect(x, y, w, h, rr) {
    return `M${x + rr},${y} h${w - 2 * rr} a${rr},${rr} 0 0 1 ${rr},${rr} v${h - 2 * rr} a${rr},${rr} 0 0 1 ${-rr},${rr} h${-(w - 2 * rr)} a${rr},${rr} 0 0 1 ${-rr},${-rr} v${-(h - 2 * rr)} a${rr},${rr} 0 0 1 ${rr},${-rr} z`;
  }
  function pinPath() { return `M0,-9 C5,-9 7,-5 7,-2 C7,3 0,9 0,9 C0,9 -7,3 -7,-2 C-7,-5 -5,-9 0,-9 z`; }

  function shortLabel(s, n = 22) {
    s = String(s || ""); return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }

  /* ================= view toggle ================= */
  const tabB = document.getElementById("tab-b"), tabA = document.getElementById("tab-a");
  const viewB = document.getElementById("view-b"), viewA = document.getElementById("view-a");
  function setView(which) {
    const isB = which === "b";
    tabB.classList.toggle("active", isB); tabA.classList.toggle("active", !isB);
    tabB.setAttribute("aria-selected", isB); tabA.setAttribute("aria-selected", !isB);
    viewB.classList.toggle("active", isB); viewA.classList.toggle("active", !isB);
    panel.classList.add("hidden");
    // bio toggle is shared; the other filters are View-B-only
    document.getElementById("t-inf").parentElement.style.visibility = isB ? "visible" : "hidden";
    document.getElementById("t-primary").parentElement.style.visibility = isB ? "visible" : "hidden";
    document.getElementById("t-question").style.visibility = isB ? "visible" : "hidden";
    if (isB && cy) { cy.resize(); cy.fit(undefined, 50); }
    if (!isB) buildTimeline();
    if (highlighted) highlightEntity(highlighted);
  }
  tabB.onclick = () => setView("b");
  tabA.onclick = () => setView("a");

  /* ================= boot ================= */
  buildCy();
  window.cy = cy; // exposed for the verification harness
  applyCyFilters();
  window.addEventListener("resize", () => {
    if (viewB.classList.contains("active") && cy) cy.resize();
    if (viewA.classList.contains("active")) buildTimeline();
  });
  document.getElementById("loading").classList.add("done");

  // expose a self-check the verifier can read from the page console / DOM.
  window.__selfCheck = function () {
    const dashed = M.edges.filter((e) => G.lineStyle(e) === "dashed");
    const named = [
      M.edges.find((e) => e.type === "OPERATED_BY" && e.to === "humberto-hernandez"),
      M.edges.find((e) => e.type === "OPERATED_BY" && e.to === "adrian-gobea"),
      M.edges.find((e) => e.type === "EMPLOYED_BY" && e.from === "david-holland"),
    ];
    return {
      entities: M.entities.length,
      edges: M.edges.length,
      dashedCount: dashed.length,
      namedInferentialDashed: named.every((e) => e && G.lineStyle(e) === "dashed"),
      cyNodes: cy ? cy.nodes().length : 0,
      cyEdges: cy ? cy.edges().length : 0,
    };
  };
})();
