/* app.js — Good Dogs knowledge-graph viz.
 *
 * One inlined data model (data.js, GOOD_DOGS_GRAPH), one shared visual grammar,
 * one evidence panel, two linked views:
 *   View B — the knowledge network (Cytoscape): node shape = entity type,
 *            node colour = knowledge domain, size = degree. CONTRADICTS edges
 *            get a distinct double-stroke red. A BEFORE/AFTER toggle reveals the
 *            AVMA review that bridges behavioural research and breed policy.
 *   View A — the timeline (D3): the same studies/events on a REAL calendar axis,
 *            with the SUPERSEDES chains drawn as arcs (dominance theory ->
 *            positive reinforcement; the Hill's vitamin-D recall lifecycle; the
 *            BSL repeals).
 *
 * Fully offline: GOOD_DOGS_GRAPH is inlined; no fetch, no CDN, no telemetry.
 */

(function () {
  "use strict";

  const jsErrors = [];
  window.addEventListener("error", (e) => jsErrors.push(String(e.message || e)));

  // data.js declares `const GOOD_DOGS_GRAPH` (a top-level lexical binding, which
  // is reachable by name here but is NOT a property of window).
  const G = GOOD_DOGS_GRAPH;
  const ENT = G.entities;
  const EDGES = G.edges;
  const entById = new Map(ENT.map((e) => [e.id, e]));

  /* ---------------- shared visual grammar ---------------- */

  // The six knowledge domains -> archival colours (must match style.css :root).
  const DOMAINS = [
    { id: "veterinary_research",  label: "Veterinary research",  color: "#6b8e5a" },
    { id: "behavioral_research",  label: "Behavioural research",  color: "#c08a3e" },
    { id: "nutrition_safety",     label: "Nutrition & safety",    color: "#b5562d" },
    { id: "municipal_policy",     label: "Municipal policy",      color: "#5b6a8f" },
    { id: "community_journalism", label: "Community journalism",  color: "#8a6d9c" },
    { id: "breed_standards",      label: "Breed standards",       color: "#a3863e" },
  ];
  const DOMAIN_BY_ID = new Map(DOMAINS.map((d) => [d.id, d]));
  function domainColor(id) { return (DOMAIN_BY_ID.get(id) || { color: "#8a8178" }).color; }
  function domainLabel(id) { return (DOMAIN_BY_ID.get(id) || { label: id }).label; }

  // Cytoscape node shape per entity type. The breed (the spine) gets a double
  // ring; concepts are diamonds; documents are rectangles; events teardrops.
  const SHAPE = {
    breed: "ellipse", person: "ellipse", organization: "round-rectangle",
    document: "round-rectangle", concept: "diamond", event: "round-tag",
    product: "hexagon", location: "round-tag",
  };

  // Confidence (0..1) -> edge opacity + width. Most gold edges are 1.0; the few
  // softer ones read lighter and thinner.
  function confOpacity(c) { return 0.35 + 0.6 * (c == null ? 0.8 : c); }
  function confWidth(c)   { return 1.2 + 3.4 * (c == null ? 0.8 : c); }

  const CONTRA = "#b5462f", BRIDGE = "#2f6f6a", INK = "#2b2622", HL = "#3a5a8c";

  // degree -> node size (View B)
  const degree = new Map();
  for (const e of EDGES) {
    degree.set(e.from, (degree.get(e.from) || 0) + 1);
    degree.set(e.to, (degree.get(e.to) || 0) + 1);
  }

  document.getElementById("counts").textContent =
    `${ENT.length} entities · ${EDGES.length} relationships`;

  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  }
  function shortLabel(s, n = 30) {
    s = String(s || "");
    // strip parenthetical citation tails for compact labels
    const clean = s.replace(/\s*\([^)]*\)\s*$/, "");
    const base = clean.length ? clean : s;
    return base.length > n ? base.slice(0, n - 1) + "…" : base;
  }

  /* ---------------- evidence panel ---------------- */
  const panel = document.getElementById("panel");
  const panelBody = document.getElementById("panel-body");
  document.getElementById("panel-close").onclick = () => panel.classList.add("hidden");

  function confBar(c) {
    if (c == null) return "";
    const pct = Math.round(c * 100);
    return `<div class="kv"><span class="k">confidence</span>`
      + `<div class="conf-bar"><span style="width:${pct}%"></span></div>`
      + `<span class="v" style="font-size:0.78rem;color:var(--muted)">${c.toFixed(2)}</span></div>`;
  }

  function showEntity(ent) {
    const d = DOMAIN_BY_ID.get(ent.domain);
    let html = `<h3>${esc(ent.label)}</h3>`;
    html += `<p class="sub">${esc(ent.type)}${ent.year ? " · " + ent.year : ""}`
      + `${ent.protagonist ? " · good dog person" : ""}`
      + `${ent.bridge ? " · the bridge" : ""}</p>`;
    // WHO'S WHO — the protagonist note: why this hub is an evidence-follower.
    if (ent.protagonist && ent.protagonistNote) {
      html += `<p><span class="badge hub">good dog person · a betweenness hub</span></p>`
        + `<div class="fact hub">${esc(ent.protagonistNote)}. The graph didn't `
        + `<i>decide</i> they matter &mdash; centrality surfaced them: the most paths run through them.</div>`;
    }
    html += `<div class="kv"><span class="k">knowledge domain</span><span class="v domchip">`
      + `<span class="dot" style="background:${d ? d.color : "#888"}"></span>${esc(domainLabel(ent.domain))}</span></div>`;
    html += `<div class="kv"><span class="k">connections</span><span class="v">${degree.get(ent.id) || 0} edge(s) in the graph</span></div>`;

    // list this entity's relationships, grouped, so a node click explains itself.
    const out = EDGES.filter((e) => e.from === ent.id);
    const inc = EDGES.filter((e) => e.to === ent.id);
    if (out.length || inc.length) {
      html += `<div class="kv"><span class="k">relationships</span><span class="v">`;
      for (const e of out) {
        const to = entById.get(e.to);
        html += `<div style="margin:2px 0">&rarr; <b>${esc(e.type)}</b> ${esc(to ? to.label : e.to)}</div>`;
      }
      for (const e of inc) {
        const fr = entById.get(e.from);
        html += `<div style="margin:2px 0;color:var(--muted)">&larr; ${esc(fr ? fr.label : e.from)} <b>${esc(e.type)}</b></div>`;
      }
      html += `</span></div>`;
    }
    if (ent.bridge) {
      html += `<p><span class="badge bridge">the science reaches the law</span></p>`
        + `<div class="fact">This 2014 AVMA literature review is the document the graph's own topology asked for: behavioural / bite-risk research on one side, breed-specific legislation on the other, and <i>no path</i> between them. Adding it closed the gap. Pick <b>the breed panic</b> and flip the switch to watch it connect.</div>`;
    }
    panelBody.innerHTML = html;
    panel.classList.remove("hidden");
  }

  function showEdge(e) {
    const from = entById.get(e.from), to = entById.get(e.to);
    const isContra = e.type === "CONTRADICTS";
    const isSuper = e.type === "SUPERSEDES";
    let html = `<h3>${esc(e.type)}</h3>`;
    html += `<p class="sub">${esc(from ? from.label : e.from)} &rarr; ${esc(to ? to.label : e.to)}</p>`;
    if (isContra)
      html += `<p><span class="badge contra">where fear met evidence</span></p>`;
    if (isSuper)
      html += `<p><span class="badge super">the correction, dated</span></p>`;
    if (e.bridge)
      html += `<p><span class="badge bridge">the science reaches the law</span></p>`;
    html += `<div class="kv"><span class="k">evidence</span></div>`;
    html += `<div class="fact${isContra ? " contra" : ""}">${esc(e.evidence) || "<i>no evidence note recorded</i>"}</div>`;
    html += confBar(e.confidence);
    if (isContra)
      html += `<p class="note">This is a disagreement, kept on purpose. The graph records that fear and evidence collided here &mdash; sourced on both sides &mdash; instead of averaging them into a false consensus.</p>`;
    panelBody.innerHTML = html;
    panel.classList.remove("hidden");
  }

  /* ---------------- legend (built from the same constants the views use) ---------------- */
  const domRamp = document.getElementById("domain-ramp");
  for (const d of DOMAINS) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="sw" style="background:${d.color}"></span> ${d.label}`;
    domRamp.appendChild(li);
  }
  document.getElementById("legend-toggle").onclick = () =>
    document.getElementById("legend").classList.toggle("collapsed");

  /* ---------------- tooltip ---------------- */
  const tooltip = document.createElement("div");
  tooltip.id = "tooltip";
  document.body.appendChild(tooltip);
  function showTip(html, x, y) {
    tooltip.innerHTML = html; tooltip.classList.add("show");
    tooltip.style.left = Math.min(x + 14, window.innerWidth - 312) + "px";
    tooltip.style.top = (y + 14) + "px";
  }
  function hideTip() { tooltip.classList.remove("show"); }

  /* ---------------- cross-view highlight ---------------- */
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

  /* ================= VIEW B — the knowledge network ================= */
  let cy = null;
  const story = document.getElementById("story");
  // which of the three fears is in focus ("all" = the whole map).
  let currentStory = "all";

  function buildCy() {
    const nodes = ENT.map((ent) => ({
      data: {
        id: ent.id, label: shortLabel(ent.label, 28), full: ent.label,
        etype: ent.type, domain: ent.domain, domColor: domainColor(ent.domain),
        degree: degree.get(ent.id) || 1, bridge: ent.bridge, ent,
        // NARRATIVE: protagonists carry an always-on label; story membership
        // drives the small-multiples dimming.
        protagonist: !!ent.protagonist,
        plabel: ent.protagonist ? shortLabel(ent.label, 30) : shortLabel(ent.label, 28),
      },
    }));
    const edges = EDGES.map((e) => ({
      data: {
        id: e.id, source: e.from, target: e.to, label: e.type, etype: e.type,
        contra: e.type === "CONTRADICTS", bridge: e.bridge,
        opacity: confOpacity(e.confidence), width: confWidth(e.confidence),
        edge: e,
      },
    }));

    cy = cytoscape({
      container: document.getElementById("cy"),
      elements: { nodes, edges },
      wheelSensitivity: 0.25,
      style: [
        {
          selector: "node",
          style: {
            "shape": (n) => SHAPE[n.data("etype")] || "ellipse",
            "background-color": "data(domColor)",
            "background-opacity": 0.92,
            "border-width": (n) => n.data("etype") === "breed" ? 3.5 : 1.6,
            "border-color": (n) => n.data("etype") === "breed" ? INK : "rgba(43,38,34,0.55)",
            "label": "data(label)",
            "font-family": "Avenir Next, Segoe UI, system-ui, sans-serif",
            "font-size": 8.5,
            "color": "#2b2622",
            "text-wrap": "wrap", "text-max-width": 96,
            "text-valign": "bottom", "text-margin-y": 3,
            "text-background-color": "#f4efe4", "text-background-opacity": 0.7,
            "text-background-padding": 1,
            "width": (n) => 15 + 6 * Math.sqrt(n.data("degree")),
            "height": (n) => 15 + 6 * Math.sqrt(n.data("degree")),
          },
        },
        // breed = the spine: a second ring (double-border feel)
        { selector: "node[etype = 'breed']", style: {
            "border-style": "double", "border-width": 5 } },
        // the AVMA bridge node, when shown, pulses teal
        { selector: "node[?bridge]", style: {
            "border-color": BRIDGE, "border-width": 4, "shape": "round-rectangle" } },
        // PROTAGONISTS — the "good dog people". Subtle ink halo + a label that is
        // always on (so the evidence-followers stay legible at a glance), and a
        // touch larger so the hubs read as hubs. No chartjunk: the halo is one
        // soft outline, the label sits on the same paper chip as every other.
        { selector: "node[?protagonist]", style: {
            "label": "data(plabel)",
            "font-size": 10, "font-weight": 600,
            "color": INK,
            "text-background-opacity": 0.92,
            "text-background-padding": 2,
            "z-index": 70,
            "underlay-color": HL, "underlay-opacity": 0.16,
            "underlay-padding": 7, "underlay-shape": "ellipse" } },
        {
          selector: "edge",
          style: {
            "curve-style": "bezier",
            "line-color": "rgba(93,86,78,0.55)",
            "width": "data(width)",
            "opacity": "data(opacity)",
            "target-arrow-shape": "triangle",
            "target-arrow-color": "rgba(93,86,78,0.55)",
            "arrow-scale": 0.7,
          },
        },
        // CONTRADICTS — the distinct style: forester's red, dashed, no arrow
        // (disagreement is mutual), drawn on top.
        { selector: "edge[?contra]", style: {
            "line-color": CONTRA, "line-style": "dashed",
            "target-arrow-color": CONTRA, "target-arrow-shape": "none",
            "source-arrow-shape": "none", "width": 2.4, "opacity": 0.95, "z-index": 50,
            "line-dash-pattern": [6, 3] } },
        // the AVMA bridge edges — inked teal, thicker, on top
        { selector: "edge[?bridge]", style: {
            "line-color": BRIDGE, "target-arrow-color": BRIDGE,
            "width": 3, "opacity": 0.96, "z-index": 60 } },
        // domain focus / loop fading
        { selector: ".faded", style: { "opacity": 0.06, "text-opacity": 0 } },
        { selector: "node.faded", style: { "opacity": 0.07, "text-opacity": 0 } },
        // STORY small-multiples: when one fear is selected, everything outside
        // that arc recedes to near-zero ink (Tufte: dim the non-data); the arc's
        // own nodes/edges stay full, and the climax edge already self-asserts.
        { selector: ".story-dim", style: { "opacity": 0.05, "text-opacity": 0 } },
        { selector: "node.story-dim", style: { "opacity": 0.06, "text-opacity": 0, "underlay-opacity": 0 } },
        // hidden = the "before" state for bridge elements
        { selector: ".gone", style: { "display": "none" } },
        // cross-view + selection highlight
        { selector: ".xv-hl", style: {
            "border-color": HL, "line-color": HL, "target-arrow-color": HL,
            "border-width": 5, "opacity": 1, "z-index": 99 } },
        { selector: "node:selected", style: { "border-color": HL, "border-width": 5 } },
        // emphasised bridge (the "after" highlight)
        { selector: ".bridge-hot", style: {
            "line-color": BRIDGE, "target-arrow-color": BRIDGE, "border-color": BRIDGE,
            "width": 4.5, "border-width": 5, "opacity": 1, "z-index": 80 } },
      ],
      layout: layoutByDomain(),
    });

    cy.on("tap", "node", (evt) => {
      const ent = evt.target.data("ent");
      showEntity(ent); highlightEntity(ent.id);
    });
    cy.on("tap", "edge", (evt) => showEdge(evt.target.data("edge")));
    cy.on("tap", (evt) => { if (evt.target === cy) { panel.classList.add("hidden"); highlightEntity(null); } });
    cy.on("mouseover", "node", (evt) => {
      const n = evt.target.data();
      showTip(`<span class="tt-type">${esc(n.etype)} · ${esc(domainLabel(n.domain))}</span><br>${esc(n.full)}`,
        evt.renderedPosition.x, evt.renderedPosition.y);
    });
    cy.on("mouseover", "edge", (evt) => {
      const e = evt.target.data("edge");
      const tail = e.evidence ? "<br>" + esc(shortLabel(e.evidence, 120)) : "";
      showTip(`<span class="tt-type">${esc(e.type)}${e.confidence != null ? " · conf " + e.confidence.toFixed(2) : ""}</span>${tail}`,
        evt.renderedPosition.x, evt.renderedPosition.y);
    });
    cy.on("mouseout", "node edge", hideTip);
  }

  // Physics layout: a cose-style force layout reads the community structure best
  // (domains clump, the cross-domain bridges stretch between clusters). Tuned so
  // the dense research/policy hubs hold together while the small disconnected
  // pairs (e.g. an alias_of pair) pack neatly rather than stringing out.
  function layoutByDomain() {
    return {
      name: "cose",
      animate: false,
      fit: true, padding: 50,
      componentSpacing: 60,        // pack disconnected components tightly
      nodeRepulsion: () => 5200,
      idealEdgeLength: () => 58,
      edgeElasticity: () => 90,
      gravity: 1.1,                // pull components toward centre
      gravityRange: 4.0,
      numIter: 1600,
      coolingFactor: 0.97,
      initialTemp: 240,
      nestingFactor: 1.0,
      nodeDimensionsIncludeLabels: true,
      randomize: true,
    };
  }

  /* ---- the BEFORE/AFTER loop-demo toggle ---- */
  const bridgeChk = document.getElementById("t-bridge");
  const loopState = document.getElementById("loop-state");

  function applyBridge() {
    if (!cy) return;
    const after = bridgeChk.checked;
    loopState.textContent = after ? "gap closed" : "gap open";
    document.getElementById("loop-wrap").classList.toggle("on", after);
    cy.batch(() => {
      cy.elements("[?bridge]").forEach((el) => {
        el.toggleClass("gone", !after);
        el.toggleClass("bridge-hot", after);
      });
    });
    // narrate it — only meaningful while the breed panic is the active arc.
    if (currentStory === "breed") {
      if (after) {
        story.className = "bridged";
        story.innerHTML = "<b>The science reaches the law.</b> SAFER behavioural "
          + "research &rarr; the 2014 AVMA review &rarr; breed-specific legislation. "
          + "The gap the graph found is closed.";
      } else {
        story.className = "";
        story.innerHTML = "The behavioural research and the breed law sit in separate "
          + "worlds &mdash; a shortest-path query returns <i>no&nbsp;path</i>. What document "
          + "bridges them? <span style='color:var(--bridge)'>Flip the switch.</span>";
      }
    }
  }
  bridgeChk.addEventListener("change", applyBridge);

  /* ---- domain focus + contradiction trace ---- */
  const domainSel = document.getElementById("t-domain");
  const contraChk = document.getElementById("t-contradict");

  function applyFilters() {
    if (!cy) return;
    const dom = domainSel.value;
    const traceContra = contraChk.checked;
    cy.batch(() => {
      cy.elements().removeClass("faded");
      if (traceContra) {
        // fade everything except CONTRADICTS edges and their endpoints
        const keep = cy.collection();
        cy.edges("[?contra]").forEach((ed) => {
          keep.merge(ed); keep.merge(ed.source()); keep.merge(ed.target());
        });
        cy.elements().not(keep).addClass("faded");
        return;
      }
      if (dom !== "all") {
        const inDom = cy.nodes().filter((n) => n.data("domain") === dom);
        const touch = inDom.connectedEdges();
        const keep = inDom.union(touch).union(touch.connectedNodes());
        cy.elements().not(keep).addClass("faded");
      }
    });
  }
  domainSel.addEventListener("change", applyFilters);
  contraChk.addEventListener("change", () => {
    if (contraChk.checked) domainSel.value = "all";
    applyFilters();
  });

  /* ---- THE THREE FEARS — the narrative spine (small multiples) ----
   *
   * Each fear is the SAME visual grammar (the network), in a comparable state:
   * its arc lit, the rest dimmed to non-data ink. The captions narrate the same
   * shape three times — fear -> evidence -> correction — so the eye can compare
   * across them. "All" restores the whole map. Selecting "breed" also reveals the
   * AVMA before/after bridge toggle (the climax of that arc).               */

  const STORY_META = {
    all: {
      label: "All",
      caption: "Three fears about dogs &mdash; a scary diet, a &lsquo;dangerous&rsquo; breed, "
        + "a dominance you must assert. Each one was pulled back to the evidence by a few "
        + "<b>good dog people</b> (always-labelled here). Pick a fear to follow one arc.",
    },
    grain_free: {
      label: "The grain-free panic",
      caption: "<b>Fear:</b> boutique grain-free &lsquo;BEG&rsquo; diets, and a 2018 alarm "
        + "linking them to heart disease (DCM). <b>Evidence:</b> Lisa Freeman and the FDA "
        + "investigate; the 2022 study complicates the simple story. The red line is the "
        + "climax &mdash; <b>where fear met evidence</b>, the 2018 alarm against the 2022 reassessment.",
    },
    breed: {
      label: "The breed panic",
      caption: "<b>Fear:</b> pit bulls cast as inherently dangerous; breed bans enacted. "
        + "<b>Evidence:</b> the AVMA&rsquo;s 2014 review finds breed doesn&rsquo;t predict bites, "
        + "and the Calgary model works better &mdash; so courts and voters repeal. "
        + "Flip the switch to watch <b>the science reach the law</b>.",
    },
    dominance: {
      label: "The dominance myth",
      caption: "<b>Fear:</b> &lsquo;be the alpha&rsquo; training, rooted in 1947 captive-wolf work "
        + "(Schenkel). <b>Evidence:</b> L. David Mech recants his own myth; the AVSAB&rsquo;s 2008 "
        + "statement supersedes it; modern welfare research follows. The arc is one long "
        + "<b>supersedes</b> chain &mdash; the consensus shift, dated and sourced.",
    },
  };

  const fearBtns = Array.from(document.querySelectorAll(".fear"));
  const spineCaption = document.getElementById("spine-caption");
  const loopWrap = document.getElementById("loop-wrap");

  function applyStory(key) {
    currentStory = key;
    // segmented-control selection state
    fearBtns.forEach((b) => {
      const on = b.dataset.story === key;
      b.classList.toggle("active", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    });
    document.getElementById("story-spine").dataset.story = key;

    // the AVMA before/after bridge lives INSIDE the breed panic only
    const breed = key === "breed";
    loopWrap.hidden = !breed;
    if (!breed) {                 // leaving breed: reset the bridge to "gap open"
      if (bridgeChk.checked) { bridgeChk.checked = false; applyBridge(); }
    }

    // dim everything outside the chosen arc (small-multiples non-data-ink)
    if (cy) {
      cy.batch(() => {
        cy.elements().removeClass("story-dim");
        if (key !== "all") {
          const inStory = (el) => {
            const src = el.isEdge() ? el.data("edge") : el.data("ent");
            const arr = (src && src.stories) || [];
            return arr.indexOf(key) !== -1;
          };
          cy.elements().forEach((el) => {
            if (!inStory(el)) el.addClass("story-dim");
          });
          // re-fit to the lit arc so it fills the frame (data density up)
          const lit = cy.elements().not(".story-dim").not(".gone");
          if (lit.nonempty()) cy.animate({ fit: { eles: lit, padding: 70 }, duration: 360 });
        } else {
          cy.animate({ fit: { eles: cy.elements().not(".gone"), padding: 55 }, duration: 360 });
        }
      });
    }

    // narrate the arc
    spineCaption.innerHTML = STORY_META[key].caption;

    // the bottom caption: only the breed arc uses the bridge-state narration;
    // for the others, echo a one-line take so the canvas isn't mute.
    if (breed) {
      applyBridge();
    } else if (key === "all") {
      story.className = "empty"; story.innerHTML = "";
    } else if (key === "grain_free") {
      story.className = ""; story.innerHTML = "Follow the red line: the 2018 alarm and the "
        + "2022 reassessment, kept side by side instead of blended away.";
    } else if (key === "dominance") {
      story.className = ""; story.innerHTML = "Follow the chain back: positive reinforcement "
        + "supersedes the &lsquo;alpha&rsquo; myth Mech himself helped retire.";
    }
  }

  fearBtns.forEach((b) => b.addEventListener("click", () => {
    // a fear focus and the domain/contra filters are mutually exclusive views
    if (b.dataset.story !== "all") {
      domainSel.value = "all"; contraChk.checked = false; applyFilters();
    }
    applyStory(b.dataset.story);
  }));

  // selecting a domain or the contradiction trace exits any story focus
  domainSel.addEventListener("change", () => { if (currentStory !== "all") applyStory("all"); });
  contraChk.addEventListener("change", () => { if (contraChk.checked && currentStory !== "all") applyStory("all"); });

  /* ================= VIEW A — the timeline (real calendar axis) ================= */
  // Only entities with a real year plot. SUPERSEDES + CONTRADICTS chains between
  // dated entities are drawn as arcs above the spine.
  function datedEntities() {
    return ENT.filter((e) => e.year != null)
      .map((e) => ({
        id: e.id, ent: e, year: e.year, type: e.type, domain: e.domain,
        label: e.label, date: new Date(`${e.year}-06-15`),
      }))
      .sort((a, b) => a.year - b.year);
  }

  function buildTimeline() {
    const container = d3.select("#timeline");
    container.selectAll("*").remove();
    const data = datedEntities();
    const datedIds = new Set(data.map((d) => d.id));
    const byId = new Map(data.map((d) => [d.id, d]));

    // chains we draw as arcs: SUPERSEDES (continuity) + CONTRADICTS (disagreement),
    // but only when BOTH endpoints are dated (so they sit on the calendar).
    const chains = EDGES
      .filter((e) => (e.type === "SUPERSEDES" || e.type === "CONTRADICTS")
                  && datedIds.has(e.from) && datedIds.has(e.to))
      .map((e) => ({ ...e, a: byId.get(e.from), b: byId.get(e.to) }));

    const margin = { top: 56, right: 64, bottom: 46, left: 64 };
    const host = document.getElementById("timeline");
    const width = Math.max(1080, host.clientWidth - 4);
    const height = Math.max(560, host.clientHeight - 4);
    const innerH = height - margin.top - margin.bottom;

    const minYear = d3.min(data, (d) => d.year);
    const maxYear = d3.max(data, (d) => d.year);
    const t0 = new Date(`${minYear - 2}-01-01`);
    const t1 = new Date(`${maxYear + 2}-01-01`);
    const x = d3.scaleTime().domain([t0, t1]).range([margin.left, width - margin.right]);

    const svg = container.append("svg")
      .attr("width", width).attr("height", height).style("display", "block");

    const spineY = margin.top + innerH * 0.62;

    // headings — the timeline's one-line framing.
    svg.append("text").attr("class", "tl-band-label").attr("x", margin.left).attr("y", 26)
      .text("The corrections, dated");
    svg.append("text").attr("class", "tl-band-sub").attr("x", margin.left).attr("y", 42)
      .text("each dot is a dated study, recall, bylaw, or event on a real 1947→2024 calendar · "
        + "arcs above: the correction supersedes (solid) or fear met evidence (dashed red)");

    // decade grid
    const gridG = svg.append("g");
    const span = maxYear - minYear;
    const ticks = x.ticks(d3.timeYear.every(span > 40 ? 5 : span > 18 ? 2 : 1));
    gridG.selectAll("line").data(ticks).enter().append("line")
      .attr("class", "tl-tick-grid")
      .attr("x1", (d) => x(d)).attr("x2", (d) => x(d))
      .attr("y1", margin.top - 6).attr("y2", height - margin.bottom);

    // axis
    svg.append("g").attr("class", "tl-axis")
      .attr("transform", `translate(0,${height - margin.bottom})`)
      .call(d3.axisBottom(x).ticks(10).tickFormat(d3.timeFormat("%Y")));

    // spine
    svg.append("line").attr("class", "tl-spine")
      .attr("x1", margin.left).attr("x2", width - margin.right)
      .attr("y1", spineY).attr("y2", spineY);

    // vertical-dodge: dated items within a 2-year window stack so labels clear.
    let prevYear = -999, stack = 0;
    for (const d of data) {
      stack = (d.year - prevYear <= 2) ? stack + 1 : 0;
      d.dodge = stack; prevYear = d.year;
    }

    // ---- chains (arcs above the spine) ----
    const arcG = svg.append("g");
    arcG.selectAll("path").data(chains).enter().append("path")
      .attr("class", (d) => "tl-super" + (d.type === "CONTRADICTS" ? " contra" : ""))
      .attr("d", (d) => {
        const x1 = x(d.a.date), x2 = x(d.b.date);
        const mid = (x1 + x2) / 2;
        const lift = Math.min(120, 34 + Math.abs(x2 - x1) * 0.28);
        return `M${x1},${spineY} Q${mid},${spineY - lift} ${x2},${spineY}`;
      })
      .attr("opacity", 0.85)
      .append("title").text((d) => `${d.type}: ${entById.get(d.from).label} → ${entById.get(d.to).label}`);

    // ---- dated markers ----
    const nodeG = svg.append("g");
    const node = nodeG.selectAll("g.tl-node").data(data, (d) => d.id)
      .enter().append("g").attr("class", "tl-node")
      .attr("transform", (d) => `translate(${x(d.date)},${spineY - d.dodge * 30})`)
      .on("click", (ev, d) => { showEntity(d.ent); highlightEntity(d.id); })
      .on("mouseover", (ev, d) => showTip(
        `<span class="tt-type">${esc(d.type)} · ${d.year} · ${esc(domainLabel(d.domain))}</span><br>${esc(d.label)}`,
        ev.clientX, ev.clientY))
      .on("mouseout", hideTip);

    // leader line back to spine for dodged markers
    node.append("line").attr("class", "tl-leader")
      .attr("x1", 0).attr("y1", 0).attr("x2", 0).attr("y2", (d) => d.dodge * 30);

    // glyph (shape echoes the network's entity-type shapes; fill = domain)
    node.append("path").attr("class", "tl-glyph")
      .attr("d", (d) => glyphPath(d.type))
      .attr("fill", (d) => domainColor(d.domain))
      .attr("fill-opacity", 0.92)
      .attr("stroke", INK).attr("stroke-width", 1.6);

    node.append("text").attr("class", "tl-year")
      .attr("y", -13).attr("text-anchor", "middle").text((d) => d.year);
    node.append("text").attr("class", "tl-label")
      .attr("y", 20).attr("text-anchor", "middle")
      .text((d) => shortLabel(d.label, 24));

    if (highlighted) highlightEntity(highlighted);
  }

  // small centred SVG glyph paths per entity type (mirror the network shapes)
  function glyphPath(type) {
    const r = 7;
    switch (type) {
      case "person":       return circle(r);
      case "breed":        return circle(r + 1);
      case "organization": return rrect(-8, -6, 16, 12, 2);
      case "document":     return rrect(-6, -8, 12, 16, 1);
      case "concept":      return diamond(8);
      case "event":        return teardrop();
      case "product":      return hexagon(8);
      case "location":     return teardrop();
      default:             return circle(r);
    }
  }
  function circle(r) { return `M${-r},0 a${r},${r} 0 1,0 ${2 * r},0 a${r},${r} 0 1,0 ${-2 * r},0`; }
  function rrect(x, y, w, h, rr) {
    return `M${x + rr},${y} h${w - 2 * rr} a${rr},${rr} 0 0 1 ${rr},${rr} v${h - 2 * rr} a${rr},${rr} 0 0 1 ${-rr},${rr} h${-(w - 2 * rr)} a${rr},${rr} 0 0 1 ${-rr},${-rr} v${-(h - 2 * rr)} a${rr},${rr} 0 0 1 ${rr},${-rr} z`;
  }
  function diamond(s) { return `M0,${-s} L${s},0 L0,${s} L${-s},0 Z`; }
  function teardrop() { return `M0,-9 C5,-9 7,-5 7,-2 C7,3 0,9 0,9 C0,9 -7,3 -7,-2 C-7,-5 -5,-9 0,-9 z`; }
  function hexagon(s) {
    const pts = [];
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 6 + i * Math.PI / 3;
      pts.push(`${(Math.cos(a) * s).toFixed(1)},${(Math.sin(a) * s).toFixed(1)}`);
    }
    return "M" + pts.join("L") + "Z";
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
    // the domain + contradict controls are View-B-only; the story spine + its
    // breed-only bridge toggle apply to both views' narrative (kept visible).
    domainSel.style.visibility = isB ? "visible" : "hidden";
    contraChk.parentElement.style.visibility = isB ? "visible" : "hidden";
    if (isB && cy) { cy.resize(); cy.fit(undefined, 55); }
    if (!isB) buildTimeline();
    if (highlighted) highlightEntity(highlighted);
  }
  tabB.onclick = () => setView("b");
  tabA.onclick = () => setView("a");

  /* ---- takeaways panel: dismissible, re-openable ---- */
  const takeaways = document.getElementById("takeaways");
  const takeawaysReopen = document.getElementById("takeaways-reopen");
  function dismissTakeaways() { takeaways.classList.add("gone"); takeawaysReopen.hidden = false; }
  document.getElementById("takeaways-close").onclick = dismissTakeaways;
  document.getElementById("takeaways-go").onclick = () => {
    dismissTakeaways();
    // nudge the viewer into the spine: open the grain-free arc first.
    const b = document.querySelector('.fear[data-story="grain_free"]');
    if (b) b.click();
  };
  takeawaysReopen.onclick = () => { takeaways.classList.remove("gone"); takeawaysReopen.hidden = true; };

  /* ================= boot ================= */
  buildCy();
  window.cy = cy;

  // seed the three-fears counters (text-as-data: each fear shows its node count)
  const M = (G.meta || {});
  const setN = (id, n) => { const el = document.getElementById(id); if (el && n != null) el.textContent = n; };
  setN("n-grain_free", M.storyGrainFree);
  setN("n-breed", M.storyBreed);
  setN("n-dominance", M.storyDominance);

  applyFilters();
  // hide the AVMA bridge by default (the "gap open" before-state); the breed
  // arc reveals + narrates it. applyBridge() also seeds .gone on the bridge edges.
  bridgeChk.checked = false;
  applyBridge();
  applyStory("all");   // sets the spine caption + initial (no-story) state
  window.addEventListener("resize", () => {
    if (viewB.classList.contains("active") && cy) cy.resize();
    if (viewA.classList.contains("active")) buildTimeline();
  });
  document.getElementById("loading").classList.add("done");

  /* ---- the headless self-check ---- */
  window.__selfCheck = function () {
    const contradicts = EDGES.filter((e) => e.type === "CONTRADICTS");
    const bridgeEdges = EDGES.filter((e) => e.bridge);
    const dashedRendered = cy ? cy.edges("[?contra]").length : 0;
    const inStory = (k) => ENT.filter((e) => (e.stories || []).indexOf(k) !== -1).length;
    return {
      nodes: ENT.length,
      edges: EDGES.length,
      contradicts: contradicts.length,
      supersedes: EDGES.filter((e) => e.type === "SUPERSEDES").length,
      bridgeEdges: bridgeEdges.length,
      datedEntities: ENT.filter((e) => e.year != null).length,
      domains: new Set(ENT.map((e) => e.domain)).size,
      cyNodes: cy ? cy.nodes().length : 0,
      cyEdges: cy ? cy.edges().length : 0,
      dashedContradictsRendered: dashedRendered,
      legendDomains: document.querySelectorAll("#domain-ramp li").length,
      // NARRATIVE: story-tag node counts + the protagonist count + that the
      // selector and always-on protagonist labels actually rendered.
      storyGrainFree: inStory("grain_free"),
      storyBreed: inStory("breed"),
      storyDominance: inStory("dominance"),
      protagonists: ENT.filter((e) => e.protagonist).length,
      protagonistsRendered: cy ? cy.nodes("[?protagonist]").length : 0,
      fearButtons: document.querySelectorAll(".fear").length,
      takeawaysFindings: document.querySelectorAll("#takeaways .findings li").length,
      currentStory: currentStory,
      jsErrors: jsErrors.slice(),
    };
  };
})();
