from __future__ import annotations

import json
from pathlib import Path

from logicchart.model import ProjectModel


def render_html(model: ProjectModel, source_root: Path | None = None) -> str:
    data = model.to_dict()
    if source_root is not None:
        data["root"] = str(source_root)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return _HTML_TEMPLATE.replace("__LOGICCHART_DATA__", payload)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LogicChart</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 40'%3E%3Ccircle cx='13' cy='7.5' r='5.5' fill='%232f63ef'/%3E%3Cline x1='13' y1='17.5' x2='13' y2='21' stroke='%237458dc' stroke-width='3' stroke-linecap='round'/%3E%3Cpolygon points='13,25 19.5,31 13,37 6.5,31' fill='%23df9a12'/%3E%3C/svg%3E">
  <style>
    :root {
      --paper: #eef2fa;
      --grid: rgba(40, 86, 180, 0.05);
      --panel: #ffffff;
      --panel-2: #f7f9fe;
      --header: rgba(255, 255, 255, 0.82);
      --ink: #16233a;
      --muted: #67768f;
      --line: #d6deec;
      --line-strong: #c2cdde;
      --blue: #2f63ef;
      --cyan: #07a8c4;
      --amber: #df9a12;
      --coral: #e0524f;
      --violet: #7458dc;
      --hover: #e9eefb;
      --active: #dfe8fb;
      --chip: #e9effe;
      --tool: rgba(255, 255, 255, 0.92);
      --finding-bg: #fff7e6;
      --finding-error-bg: #ffefef;
      --node-fill: #ffffff;
      --fill-entry: #e7eeff;
      --fill-decision: #fdf2d6;
      --fill-call: #efe9ff;
      --fill-terminal: #e0f6f1;
      --fill-error: #ffe9e9;
      --edge: #9aa7be;
      --radius: 12px;
      --radius-sm: 9px;
      --shadow: 0 20px 55px rgba(24, 40, 76, 0.16);
      color-scheme: light;
    }
    [data-theme="dark"] {
      --paper: #0c1320;
      --grid: rgba(120, 160, 255, 0.05);
      --panel: #141d30;
      --panel-2: #111a2b;
      --header: rgba(17, 26, 43, 0.82);
      --ink: #e7eefb;
      --muted: #8a9aba;
      --line: #263347;
      --line-strong: #34435c;
      --blue: #5e8cff;
      --cyan: #2bd3ee;
      --amber: #f3b63f;
      --coral: #ff6b6b;
      --violet: #a98bf6;
      --hover: #1b2740;
      --active: #21305a;
      --chip: #1d2b4d;
      --tool: rgba(20, 29, 48, 0.92);
      --finding-bg: #2a2412;
      --finding-error-bg: #2e1a1d;
      --node-fill: #18223a;
      --fill-entry: #1a2748;
      --fill-decision: #2c2614;
      --fill-call: #221b3e;
      --fill-terminal: #12302d;
      --fill-error: #311a1e;
      --edge: #58688a;
      --shadow: 0 22px 60px rgba(0, 0, 0, 0.55);
      color-scheme: dark;
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; }
    body {
      color: var(--ink);
      background:
        linear-gradient(var(--grid) 1px, transparent 1px),
        linear-gradient(90deg, var(--grid) 1px, transparent 1px),
        var(--paper);
      background-size: 26px 26px;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      overflow: hidden;
      transition: background-color .25s ease, color .25s ease;
    }
    button, input { font: inherit; }
    button { color: inherit; }
    .shell {
      display: grid;
      grid-template-columns: 312px minmax(0, 1fr) 336px;
      grid-template-rows: 78px minmax(0, 1fr);
      height: 100%;
    }
    header {
      grid-column: 1 / -1;
      display: flex;
      align-items: center;
      gap: 24px;
      padding: 0 22px;
      background: var(--header);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(16px);
      z-index: 3;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 13px;
      min-width: 270px;
    }
    .brand-mark {
      flex: none;
      display: grid;
      place-items: center;
    }
    /* The mark is a mini decision flow: an entry node (circle) linked to a decision
       (diamond), in the same blue/amber the chart uses for those node kinds. */
    .brand-mark svg { height: 34px; width: auto; display: block; overflow: visible; }
    .logo-node { fill: var(--blue); }
    .logo-link { stroke: var(--violet); stroke-width: 3; stroke-linecap: round; }
    .logo-decision { fill: var(--amber); }
    .brand h1 {
      font-family: Georgia, "Times New Roman", serif;
      font-size: 23px;
      letter-spacing: -0.4px;
      margin: 0;
    }
    .brand small {
      display: block;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
    }
    .flow-heading { min-width: 0; flex: 1; }
    .flow-heading .eyebrow {
      color: var(--blue);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.1em;
      text-transform: uppercase;
    }
    .flow-heading h2 {
      margin: 4px 0 0;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 20px;
    }
    .metrics { display: flex; gap: 8px; }
    .metric {
      padding: 9px 13px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--panel);
      min-width: 74px;
      box-shadow: 0 1px 2px rgba(24, 40, 76, 0.05);
    }
    .metric strong { display: block; font-size: 17px; }
    .metric span {
      color: var(--muted);
      font-size: 10px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }
    .theme-toggle {
      margin-left: auto;
      width: 40px;
      height: 40px;
      border: 1px solid var(--line);
      border-radius: 50%;
      background: var(--panel);
      cursor: pointer;
      font-size: 17px;
      line-height: 1;
      display: grid;
      place-items: center;
      transition: border-color .15s ease, transform .15s ease;
    }
    .theme-toggle:hover { border-color: var(--blue); transform: translateY(-1px); }
    aside {
      min-height: 0;
      background: var(--panel-2);
    }
    .left-rail { border-right: 1px solid var(--line); }
    .right-rail { border-left: 1px solid var(--line); }
    .rail-inner {
      height: 100%;
      display: flex;
      flex-direction: column;
      min-height: 0;
    }
    .rail-head { padding: 20px; border-bottom: 1px solid var(--line); }
    .rail-title {
      margin: 0 0 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: var(--muted);
    }
    .search {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--paper);
      color: var(--ink);
      padding: 10px 12px;
      outline: none;
      transition: border-color .15s ease, box-shadow .15s ease;
    }
    .search:focus { border-color: var(--blue); box-shadow: 0 0 0 3px rgba(47, 99, 239, .16); }
    .flow-list, .detail-scroll { overflow: auto; min-height: 0; }
    .flow-list { padding: 10px; }
    .flow-item {
      width: 100%;
      display: grid;
      grid-template-columns: 5px 1fr;
      gap: 11px;
      text-align: left;
      border: 0;
      border-radius: var(--radius-sm);
      background: transparent;
      padding: 11px 11px;
      cursor: pointer;
      transition: background-color .12s ease;
    }
    .flow-item:hover, .flow-item:focus-visible { background: var(--hover); outline: none; }
    .flow-item.active { background: var(--active); }
    .flow-item .bar { background: var(--line-strong); border-radius: 3px; min-height: 42px; }
    .flow-item.active .bar { background: var(--blue); }
    .flow-item strong { display: block; font-size: 13px; line-height: 1.25; }
    .flow-item span {
      display: block;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      margin-top: 5px;
    }
    main { position: relative; min-width: 0; min-height: 0; overflow: hidden; }
    .canvas-toolbar {
      position: absolute;
      top: 16px;
      right: 16px;
      z-index: 2;
      display: flex;
      gap: 6px;
    }
    .tool {
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--tool);
      color: var(--ink);
      min-width: 40px;
      height: 40px;
      cursor: pointer;
      backdrop-filter: blur(8px);
      box-shadow: 0 8px 18px rgba(24, 40, 76, .12);
      transition: border-color .15s ease, transform .15s ease;
    }
    .tool:hover, .tool:focus-visible { border-color: var(--blue); outline: none; transform: translateY(-1px); }
    #canvas { width: 100%; height: 100%; cursor: grab; }
    #canvas.dragging { cursor: grabbing; }
    .empty {
      position: absolute;
      inset: 0;
      display: none;
      place-items: center;
      text-align: center;
      color: var(--muted);
    }
    .detail-scroll { padding: 20px; }
    .detail-kind {
      display: inline-block;
      padding: 5px 9px;
      border-radius: 999px;
      color: var(--blue);
      background: var(--chip);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      font-weight: 700;
      letter-spacing: .08em;
      text-transform: uppercase;
    }
    .detail-scroll h3 {
      margin: 16px 0 8px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 22px;
      line-height: 1.15;
    }
    .detail-scroll p { color: var(--muted); line-height: 1.55; font-size: 13px; }
    .source-link, .subflow-link {
      display: block;
      width: 100%;
      margin: 14px 0;
      padding: 11px 12px;
      border: 1px solid var(--line);
      border-radius: var(--radius-sm);
      background: var(--paper);
      color: var(--ink);
      text-decoration: none;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 11px;
      overflow-wrap: anywhere;
      cursor: pointer;
      transition: border-color .15s ease;
    }
    .source-link:hover, .subflow-link:hover { border-color: var(--blue); }
    .section-label {
      margin: 24px 0 10px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      letter-spacing: .1em;
      text-transform: uppercase;
    }
    .finding {
      border-left: 4px solid var(--amber);
      border-radius: 8px;
      background: var(--finding-bg);
      padding: 11px 12px;
      margin-bottom: 9px;
      font-size: 12px;
      line-height: 1.45;
    }
    .finding.error { border-color: var(--coral); background: var(--finding-error-bg); }
    .legend {
      margin-top: auto;
      border-top: 1px solid var(--line);
      padding: 14px 20px;
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      color: var(--muted);
      font-size: 10px;
    }
    .legend span { display: flex; align-items: center; }
    .legend span::before {
      content: "";
      width: 9px;
      height: 9px;
      border-radius: 3px;
      display: inline-block;
      margin-right: 8px;
      background: var(--blue);
    }
    .legend .decision::before { background: var(--amber); transform: rotate(45deg); }
    .legend .call::before { background: var(--violet); }
    .legend .outcome::before { background: var(--cyan); border-radius: 50%; }
    .legend .gap::before { background: var(--coral); border-radius: 50%; }
    .node { cursor: grab; }
    .node.dragging { cursor: grabbing; }
    .node .shape {
      fill: var(--node-fill);
      stroke: var(--blue);
      stroke-width: 2;
      filter: url(#nodeShadow);
      transition: filter .14s ease, stroke-width .14s ease, opacity .18s ease;
    }
    .node.entry .shape { fill: var(--fill-entry); stroke: var(--blue); }
    .node.decision .shape { fill: var(--fill-decision); stroke: var(--amber); }
    .node.call .shape { fill: var(--fill-call); stroke: var(--violet); }
    .node.terminal .shape { fill: var(--fill-terminal); stroke: var(--cyan); }
    .node.error .shape { fill: var(--fill-error); stroke: var(--coral); }
    .node.has-finding .shape { stroke: var(--coral); stroke-width: 3; }
    .node:hover .shape, .node:focus-visible .shape { filter: url(#nodeLift); stroke-width: 2.6; }
    .node:focus-visible { outline: none; }
    .node.dragging .shape { filter: url(#nodeLift); }
    .node.selected .shape { stroke-width: 3.4; filter: url(#nodeLift); }
    .node.dimmed { opacity: .26; }
    .node text {
      fill: var(--ink);
      font-size: 13px;
      font-weight: 650;
      pointer-events: none;
    }
    .node .meta {
      fill: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 9px;
      font-weight: 500;
      letter-spacing: .05em;
      text-transform: uppercase;
    }
    .arrow { fill: var(--edge); transition: fill .18s ease; }
    .edge { fill: none; stroke: var(--edge); stroke-width: 2; marker-end: url(#arrow); transition: stroke .18s ease, opacity .18s ease; }
    .edge.incident { stroke: var(--blue); stroke-width: 2.6; }
    .edge.dimmed { opacity: .18; }
    .edge-label {
      fill: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      font-weight: 700;
      paint-order: stroke;
      stroke: var(--paper);
      stroke-width: 6px;
      transition: opacity .18s ease;
    }
    .edge-label.dimmed { opacity: .18; }
    .decision-spine { stroke: var(--cyan); opacity: .16; stroke-width: 5; stroke-dasharray: 3 10; }
    @media (max-width: 1050px) {
      .shell { grid-template-columns: 262px minmax(0,1fr); }
      .right-rail {
        position: fixed;
        right: 0;
        top: 78px;
        bottom: 0;
        width: 322px;
        z-index: 5;
        box-shadow: var(--shadow);
        transform: translateX(100%);
        transition: transform .2s ease;
      }
      .right-rail.open { transform: translateX(0); }
      .metrics { display: none; }
    }
    @media (max-width: 700px) {
      .shell { grid-template-columns: 1fr; }
      header { padding: 0 14px; }
      .brand { min-width: 0; }
      .brand small, .flow-heading { display: none; }
      .left-rail {
        position: fixed;
        left: 0;
        top: 78px;
        bottom: 0;
        width: 286px;
        z-index: 5;
        box-shadow: var(--shadow);
        transform: translateX(-100%);
      }
      .left-rail.open { transform: translateX(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { scroll-behavior: auto !important; transition: none !important; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header>
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 26 40" xmlns="http://www.w3.org/2000/svg">
            <circle class="logo-node" cx="13" cy="7.5" r="5.5"></circle>
            <line class="logo-link" x1="13" y1="17.5" x2="13" y2="21"></line>
            <polygon class="logo-decision" points="13,25 19.5,31 13,37 6.5,31"></polygon>
          </svg>
        </div>
        <div><h1>LogicChart</h1><small>Decision flow index</small></div>
      </div>
      <div class="flow-heading">
        <div class="eyebrow" id="flowKind">No flow selected</div>
        <h2 id="flowTitle">Analyze a project to begin</h2>
      </div>
      <div class="metrics">
        <div class="metric"><strong id="flowCount">0</strong><span>flows</span></div>
        <div class="metric"><strong id="entryCount">0</strong><span>entries</span></div>
        <div class="metric"><strong id="findingCount">0</strong><span>review</span></div>
      </div>
      <button class="theme-toggle" id="themeToggle" title="Toggle theme" aria-label="Toggle light/dark theme">&#9789;</button>
    </header>

    <aside class="left-rail" id="leftRail">
      <div class="rail-inner">
        <div class="rail-head">
          <h2 class="rail-title">Entry points and subflows</h2>
          <input class="search" id="flowSearch" type="search" placeholder="Filter flows..." aria-label="Filter flows">
        </div>
        <div class="flow-list" id="flowList"></div>
        <div class="legend">
          <span>Action</span><span class="decision">Decision</span>
          <span class="call">Subflow</span><span class="outcome">Outcome</span>
          <span class="gap">Review</span>
        </div>
      </div>
    </aside>

    <main>
      <div class="canvas-toolbar" aria-label="Canvas controls">
        <button class="tool" id="menuButton" title="Toggle flow list">&#9776;</button>
        <button class="tool" id="zoomOut" title="Zoom out">&minus;</button>
        <button class="tool" id="resetView" title="Reset view &amp; layout">0</button>
        <button class="tool" id="zoomIn" title="Zoom in">+</button>
      </div>
      <svg id="canvas" role="img" aria-label="Decision flowchart"></svg>
      <div class="empty" id="emptyState"><p>No matching flow was found.</p></div>
    </main>

    <aside class="right-rail" id="rightRail">
      <div class="rail-inner">
        <div class="rail-head"><h2 class="rail-title">Inspector</h2></div>
        <div class="detail-scroll" id="details">
          <p>Select a node to inspect its source, evidence, and related findings.</p>
          <p>Tip: drag any block to rearrange the diagram by hand. Reset (0) restores the
          automatic layout.</p>
        </div>
      </div>
    </aside>
  </div>

  <script id="logicchart-data" type="application/json">__LOGICCHART_DATA__</script>
  <script>
    const model = JSON.parse(document.getElementById("logicchart-data").textContent);
    const flows = model.flows || [];
    const findings = model.findings || [];
    const byId = new Map(flows.map(flow => [flow.id, flow]));
    const findingsByNode = new Map();
    findings.forEach(item => {
      if (!item.node_id) return;
      const list = findingsByNode.get(item.node_id) || [];
      list.push(item);
      findingsByNode.set(item.node_id, list);
    });

    const svg = document.getElementById("canvas");
    const listEl = document.getElementById("flowList");
    const searchEl = document.getElementById("flowSearch");
    const detailsEl = document.getElementById("details");
    const rightRail = document.getElementById("rightRail");
    const leftRail = document.getElementById("leftRail");
    const themeToggleBtn = document.getElementById("themeToggle");
    let activeFlow = null;
    let view = { x: 0, y: 0, width: 1000, height: 800 };
    let drag = null;
    // Per-flow manual node positions: flowId -> Map(nodeId -> {x, y}). Lets the user
    // hand-arrange blocks; survives navigating away and back within the session.
    const manualPositions = new Map();
    // Element references for the currently rendered flow, for selection highlighting.
    let currentRender = null;

    document.getElementById("flowCount").textContent = flows.length;
    document.getElementById("entryCount").textContent = flows.filter(item => item.is_entrypoint).length;
    document.getElementById("findingCount").textContent = findings.length;

    function sortedFlows() {
      return [...flows].sort((a, b) =>
        Number(b.is_entrypoint) - Number(a.is_entrypoint) || a.name.localeCompare(b.name)
      );
    }

    function renderList(filter = "") {
      const needle = filter.trim().toLowerCase();
      listEl.replaceChildren();
      sortedFlows()
        .filter(flow => !flow.metadata.test)
        .filter(flow => `${flow.name} ${flow.symbol} ${flow.entry_kind}`.toLowerCase().includes(needle))
        .forEach(flow => {
          const button = document.createElement("button");
          button.className = "flow-item" + (activeFlow?.id === flow.id ? " active" : "");
          button.innerHTML = `<span class="bar"></span><span><strong></strong><span></span></span>`;
          button.querySelector("strong").textContent = flow.name;
          button.querySelector("span span").textContent =
            `${flow.is_entrypoint ? "ENTRY" : "SUBFLOW"} · ${flow.entry_kind}`;
          button.addEventListener("click", () => selectFlow(flow.id));
          listEl.appendChild(button);
        });
    }

    function selectFlow(flowId) {
      const flow = byId.get(flowId);
      if (!flow) return;
      activeFlow = flow;
      location.hash = encodeURIComponent(flow.id);
      document.getElementById("flowTitle").textContent = flow.name;
      document.getElementById("flowKind").textContent =
        `${flow.entry_kind} · ${flow.language} · ${flow.framework}`;
      renderList(searchEl.value);
      renderFlow(flow);
      inspectFlow(flow);
      leftRail.classList.remove("open");
    }

    function layoutFlow(flow) {
      const order = new Map(flow.nodes.map((node, index) => [node.id, index]));
      const incoming = new Map(flow.nodes.map(node => [node.id, []]));
      flow.edges.forEach(edge => incoming.get(edge.target)?.push(edge));
      const positions = new Map();
      const layerCounts = new Map();

      flow.nodes.forEach((node, index) => {
        const parents = incoming.get(node.id) || [];
        let layer = 0;
        let x = 0;
        if (parents.length) {
          layer = Math.max(...parents.map(edge => (positions.get(edge.source)?.layer || 0) + 1));
          const parentXs = parents.map(edge => positions.get(edge.source)?.x || 0);
          x = parentXs.reduce((sum, value) => sum + value, 0) / parentXs.length;
          const branch = parents[0]?.label?.toLowerCase();
          if (["yes", "success"].includes(branch)) x -= 165;
          if (["no", "error"].includes(branch)) x += 165;
        }
        const occupied = layerCounts.get(layer) || [];
        while (occupied.some(value => Math.abs(value - x) < 210)) x += 230;
        occupied.push(x);
        layerCounts.set(layer, occupied);
        positions.set(node.id, { x, y: layer * 150, layer, order: index });
      });

      // Apply any hand-placed overrides for this flow before measuring bounds.
      const overrides = manualPositions.get(flow.id);
      if (overrides) {
        overrides.forEach((point, nodeId) => {
          const position = positions.get(nodeId);
          if (position) { position.x = point.x; position.y = point.y; position.moved = true; }
        });
      }

      const values = [...positions.values()];
      const minX = Math.min(...values.map(item => item.x), 0);
      const maxX = Math.max(...values.map(item => item.x), 0);
      const minY = Math.min(...values.map(item => item.y), 0);
      const maxY = Math.max(...values.map(item => item.y), 0);
      return { positions, bounds: { minX, maxX, minY, maxY } };
    }

    // One source for an edge's curved path + label anchor, reused on first render and
    // live while a node is dragged so connected edges follow.
    function edgeGeometry(start, end) {
      const startY = start.y + 43;
      const endY = end.y - 43;
      const middleY = (startY + endY) / 2;
      return {
        d: `M ${start.x} ${startY} C ${start.x} ${middleY}, ${end.x} ${middleY}, ${end.x} ${endY}`,
        labelX: (start.x + end.x) / 2 + 7,
        labelY: middleY - 6,
      };
    }

    function renderFlow(flow) {
      svg.replaceChildren();
      if (!flow.nodes.length) {
        document.getElementById("emptyState").style.display = "grid";
        return;
      }
      document.getElementById("emptyState").style.display = "none";
      const { positions, bounds } = layoutFlow(flow);
      const padding = 170;
      const top = Math.min(-90, bounds.minY - 70);
      view = {
        x: bounds.minX - padding,
        y: top,
        width: Math.max(760, bounds.maxX - bounds.minX + padding * 2),
        height: Math.max(600, bounds.maxY - top + 250)
      };
      updateViewBox();

      const defs = svgEl("defs");
      defs.innerHTML = `
        <filter id="nodeShadow" x="-30%" y="-30%" width="160%" height="180%">
          <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#1e2e4e" flood-opacity=".10"/>
        </filter>
        <filter id="nodeLift" x="-45%" y="-45%" width="190%" height="210%">
          <feDropShadow dx="0" dy="16" stdDeviation="14" flood-color="#1e2e4e" flood-opacity=".24"/>
        </filter>
        <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
          <path class="arrow" d="M0,0 L8,4 L0,8 z"></path>
        </marker>`;
      svg.appendChild(defs);

      const spine = svgEl("line");
      spine.setAttribute("class", "decision-spine");
      spine.setAttribute("x1", "0");
      spine.setAttribute("y1", "-20");
      spine.setAttribute("x2", "0");
      spine.setAttribute("y2", String(bounds.maxY + 100));
      svg.appendChild(spine);

      // Keep edge element references per node so dragging a block re-routes its edges live,
      // and a flat list so selecting a node can highlight its incident edges.
      const nodeEdges = new Map(flow.nodes.map(node => [node.id, []]));
      const edgeRecords = [];
      const edgeLayer = svgEl("g");
      flow.edges.forEach(edge => {
        const start = positions.get(edge.source);
        const end = positions.get(edge.target);
        if (!start || !end) return;
        const geometry = edgeGeometry(start, end);
        const path = svgEl("path");
        path.setAttribute("class", "edge");
        path.setAttribute("d", geometry.d);
        edgeLayer.appendChild(path);
        let label = null;
        if (edge.label) {
          label = svgEl("text");
          label.setAttribute("class", "edge-label");
          label.setAttribute("x", String(geometry.labelX));
          label.setAttribute("y", String(geometry.labelY));
          label.textContent = edge.label;
          edgeLayer.appendChild(label);
        }
        const record = { edge, path, label };
        edgeRecords.push(record);
        nodeEdges.get(edge.source)?.push(record);
        nodeEdges.get(edge.target)?.push(record);
      });
      svg.appendChild(edgeLayer);

      function rerouteFrom(nodeId) {
        (nodeEdges.get(nodeId) || []).forEach(({ edge, path, label }) => {
          const start = positions.get(edge.source);
          const end = positions.get(edge.target);
          if (!start || !end) return;
          const geometry = edgeGeometry(start, end);
          path.setAttribute("d", geometry.d);
          if (label) {
            label.setAttribute("x", String(geometry.labelX));
            label.setAttribute("y", String(geometry.labelY));
          }
        });
      }

      const nodeLayer = svgEl("g");
      const nodeGroups = new Map();
      flow.nodes.forEach(node => {
        const position = positions.get(node.id);
        const group = svgEl("g");
        nodeGroups.set(node.id, group);
        group.setAttribute("class", `node ${node.kind}${findingsByNode.has(node.id) ? " has-finding" : ""}`);
        group.setAttribute("transform", `translate(${position.x} ${position.y})`);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-label", `${node.kind}: ${node.label}`);
        // Drag to rearrange the block; a plain click (no real movement) opens the inspector.
        let nodeDrag = null;
        group.addEventListener("pointerdown", event => {
          if (event.button !== 0) return;
          event.stopPropagation();
          nodeDrag = {
            x: event.clientX,
            y: event.clientY,
            ox: position.x,
            oy: position.y,
            scaleX: view.width / svg.clientWidth,
            scaleY: view.height / svg.clientHeight,
            moved: 0
          };
          group.classList.add("dragging");
          group.setPointerCapture(event.pointerId);
        });
        group.addEventListener("pointermove", event => {
          if (!nodeDrag) return;
          const dx = (event.clientX - nodeDrag.x) * nodeDrag.scaleX;
          const dy = (event.clientY - nodeDrag.y) * nodeDrag.scaleY;
          nodeDrag.moved = Math.max(nodeDrag.moved, Math.abs(dx) + Math.abs(dy));
          position.x = nodeDrag.ox + dx;
          position.y = nodeDrag.oy + dy;
          group.setAttribute("transform", `translate(${position.x} ${position.y})`);
          rerouteFrom(node.id);
        });
        const endNodeDrag = event => {
          if (!nodeDrag) return;
          group.classList.remove("dragging");
          try { group.releasePointerCapture(event.pointerId); } catch (_) {}
          if (nodeDrag.moved < 4) {
            inspectNode(flow, node);
          } else {
            const store = manualPositions.get(flow.id) || new Map();
            store.set(node.id, { x: position.x, y: position.y });
            manualPositions.set(flow.id, store);
          }
          nodeDrag = null;
        };
        group.addEventListener("pointerup", endNodeDrag);
        group.addEventListener("pointercancel", endNodeDrag);
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") { event.preventDefault(); inspectNode(flow, node); }
        });
        const shape = nodeShape(node.kind);
        shape.setAttribute("class", "shape");
        group.appendChild(shape);
        const lines = wrapLabel(node.label, node.kind === "decision" ? 25 : 31);
        lines.forEach((line, index) => {
          const text = svgEl("text");
          text.setAttribute("text-anchor", "middle");
          text.setAttribute("y", String((index - (lines.length - 1) / 2) * 17 + 1));
          text.textContent = line;
          group.appendChild(text);
        });
        const meta = svgEl("text");
        meta.setAttribute("class", "meta");
        meta.setAttribute("text-anchor", "middle");
        meta.setAttribute("y", "62");
        meta.textContent = `${node.location.path}:${node.location.start_line}`;
        group.appendChild(meta);
        nodeLayer.appendChild(group);
      });
      svg.appendChild(nodeLayer);
      currentRender = { nodeGroups, edgeRecords };
    }

    function clearHighlight() {
      if (!currentRender) return;
      currentRender.nodeGroups.forEach(group => group.classList.remove("selected", "dimmed"));
      currentRender.edgeRecords.forEach(record => {
        record.path.classList.remove("incident", "dimmed");
        if (record.label) record.label.classList.remove("dimmed");
      });
    }

    function highlightNode(nodeId) {
      if (!currentRender) return;
      const connected = new Set([nodeId]);
      currentRender.edgeRecords.forEach(record => {
        const incident = record.edge.source === nodeId || record.edge.target === nodeId;
        record.path.classList.toggle("incident", incident);
        record.path.classList.toggle("dimmed", !incident);
        if (record.label) record.label.classList.toggle("dimmed", !incident);
        if (incident) { connected.add(record.edge.source); connected.add(record.edge.target); }
      });
      currentRender.nodeGroups.forEach((group, id) => {
        group.classList.toggle("selected", id === nodeId);
        group.classList.toggle("dimmed", !connected.has(id));
      });
    }

    function nodeShape(kind) {
      if (kind === "decision") {
        const polygon = svgEl("polygon");
        polygon.setAttribute("points", "0,-58 145,0 0,58 -145,0");
        return polygon;
      }
      const rect = svgEl("rect");
      rect.setAttribute("x", "-145");
      rect.setAttribute("y", "-43");
      rect.setAttribute("width", "290");
      rect.setAttribute("height", "86");
      rect.setAttribute("rx", kind === "entry" || kind === "terminal" ? "43" : kind === "call" ? "5" : "12");
      return rect;
    }

    function inspectFlow(flow) {
      clearHighlight();
      detailsEl.replaceChildren();
      const badge = element("span", "detail-kind", flow.is_entrypoint ? "Entry point" : "Subflow");
      const title = element("h3", "", flow.name);
      const description = element("p", "", `${flow.symbol} · ${flow.nodes.length} nodes · ${flow.edges.length} paths`);
      detailsEl.append(badge, title, description, sourceLink(flow.location));
      const related = findings.filter(item => item.flow_id === flow.id);
      if (related.length) {
        detailsEl.append(element("div", "section-label", "Review points"));
        related.forEach(item => detailsEl.append(findingCard(item)));
      }
      if (flow.tests?.length) {
        detailsEl.append(element("div", "section-label", "Referenced by tests"));
        flow.tests.forEach(test => detailsEl.append(element("p", "", test)));
      }
    }

    function inspectNode(flow, node) {
      rightRail.classList.add("open");
      highlightNode(node.id);
      detailsEl.replaceChildren();
      detailsEl.append(
        element("span", "detail-kind", `${node.kind} · ${node.evidence}`),
        element("h3", "", node.label)
      );
      if (node.detail) detailsEl.append(element("p", "", node.detail));
      detailsEl.append(sourceLink(node.location));
      const nodeFindings = findingsByNode.get(node.id) || [];
      if (nodeFindings.length) {
        detailsEl.append(element("div", "section-label", "Review points"));
        nodeFindings.forEach(item => detailsEl.append(findingCard(item)));
      }
      if (node.metadata?.target_flow && byId.has(node.metadata.target_flow)) {
        const target = byId.get(node.metadata.target_flow);
        const link = element("button", "subflow-link", `Open subflow → ${target.name}`);
        link.addEventListener("click", () => selectFlow(target.id));
        detailsEl.append(element("div", "section-label", "Internal call"), link);
      }
      if (node.metadata?.condition) {
        detailsEl.append(element("div", "section-label", "Decision evidence"));
        detailsEl.append(element("p", "", node.metadata.condition));
      }
    }

    function findingCard(item) {
      const card = element("div", `finding ${item.severity}`, item.message);
      if (item.detail) card.title = item.detail;
      return card;
    }

    function sourceLink(location) {
      const link = element("a", "source-link", `${location.path}:${location.start_line}`);
      const absolute = `${model.root}/${location.path}`.replaceAll("//", "/");
      link.href = `vscode://file/${absolute}:${location.start_line}`;
      link.title = "Open source in VS Code";
      return link;
    }

    function element(tag, className, text) {
      const item = document.createElement(tag);
      if (className) item.className = className;
      item.textContent = text;
      return item;
    }

    function svgEl(tag) {
      return document.createElementNS("http://www.w3.org/2000/svg", tag);
    }

    function wrapLabel(value, width) {
      const words = value.split(/\s+/);
      const lines = [];
      let current = "";
      words.forEach(word => {
        if (!current || `${current} ${word}`.length <= width) current = current ? `${current} ${word}` : word;
        else { lines.push(current); current = word; }
      });
      if (current) lines.push(current);
      return lines.slice(0, 3);
    }

    function updateViewBox() {
      svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
    }

    function zoom(factor) {
      const nextWidth = view.width * factor;
      const nextHeight = view.height * factor;
      view.x += (view.width - nextWidth) / 2;
      view.y += (view.height - nextHeight) / 2;
      view.width = nextWidth;
      view.height = nextHeight;
      updateViewBox();
    }

    searchEl.addEventListener("input", event => renderList(event.target.value));
    document.getElementById("zoomIn").addEventListener("click", () => zoom(.82));
    document.getElementById("zoomOut").addEventListener("click", () => zoom(1.22));
    document.getElementById("resetView").addEventListener("click", () => {
      if (!activeFlow) return;
      manualPositions.delete(activeFlow.id);  // discard hand-placed positions, re-layout
      renderFlow(activeFlow);
    });
    document.getElementById("menuButton").addEventListener("click", () => leftRail.classList.toggle("open"));

    svg.addEventListener("wheel", event => {
      event.preventDefault();
      zoom(event.deltaY > 0 ? 1.08 : .92);
    }, { passive: false });
    svg.addEventListener("pointerdown", event => {
      drag = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y };
      svg.classList.add("dragging");
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", event => {
      if (!drag) return;
      const scaleX = view.width / svg.clientWidth;
      const scaleY = view.height / svg.clientHeight;
      view.x = drag.vx - (event.clientX - drag.x) * scaleX;
      view.y = drag.vy - (event.clientY - drag.y) * scaleY;
      updateViewBox();
    });
    svg.addEventListener("pointerup", () => { drag = null; svg.classList.remove("dragging"); });

    const THEME_KEY = "logicchart-theme";
    function applyTheme(theme) {
      document.documentElement.dataset.theme = theme;
      themeToggleBtn.textContent = theme === "dark" ? "☀" : "☾";  // sun / moon
      themeToggleBtn.title = theme === "dark" ? "Switch to light theme" : "Switch to dark theme";
      try { localStorage.setItem(THEME_KEY, theme); } catch (_) {}
    }
    let storedTheme = null;
    try { storedTheme = localStorage.getItem(THEME_KEY); } catch (_) {}
    const prefersDark = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    applyTheme(storedTheme || (prefersDark ? "dark" : "light"));
    themeToggleBtn.addEventListener("click", () =>
      applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark")
    );

    renderList();
    const requested = decodeURIComponent(location.hash.slice(1));
    const initial = byId.get(requested) || flows.find(item => item.is_entrypoint) || flows[0];
    if (initial) selectFlow(initial.id);
  </script>
</body>
</html>
"""
