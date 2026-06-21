from __future__ import annotations

import json
import re
from pathlib import Path

from logicchart.model import ProjectModel
from logicchart.render.payload import build_payload

# A literal ``</script`` anywhere inside an inlined ``<script>`` body terminates the script
# element early in the HTML parser, corrupting the page (it does not matter that it sits in
# a JS string or comment). Neutralize ONLY that exact sequence -- ``<\/script`` is identical
# to ``</script`` inside any JS string/regex/comment, so this is behavior-preserving, and it
# leaves other ``</...`` markup (e.g. ``</filter>`` inside an innerHTML template) untouched.
_SCRIPT_CLOSE = re.compile(r"</(script)", re.IGNORECASE)


def _asset(name: str) -> str:
    return (Path(__file__).parent / "assets" / name).read_text(encoding="utf-8")


def _inline_js(name: str) -> str:
    return _SCRIPT_CLOSE.sub(r"<\\/\1", _asset(name))


def _optional_inline_js(name: str) -> str:
    path = Path(__file__).parent / "assets" / name
    if not path.exists():
        return ""
    return _SCRIPT_CLOSE.sub(r"<\\/\1", path.read_text(encoding="utf-8"))


def render_html(model: ProjectModel, source_root: Path | None = None) -> str:
    payload_data = build_payload(model, source_root)
    payload = json.dumps(payload_data, ensure_ascii=False).replace("</", "<\\/")
    css = _asset("styles.css")
    js = _inline_js("shell.js")
    tree_js = _inline_js("tree.js")
    panels_js = _inline_js("panels.js")
    viewer_runtime_js = _optional_inline_js("generated/logicchart-viewer-runtime.iife.js")
    return (
        _HTML_TEMPLATE.replace("__STYLES__", css)
        .replace("__SHELL_JS__", js)
        .replace("__TREE_JS__", tree_js)
        .replace("__PANELS_JS__", panels_js)
        .replace("__VIEWER_RUNTIME_JS__", viewer_runtime_js)
        .replace("__LOGICCHART_DATA__", payload)
    )


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>LogicChart</title>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 26 40'%3E%3Ccircle cx='13' cy='7.5' r='5.5' fill='%232f63ef'/%3E%3Cline x1='13' y1='17.5' x2='13' y2='21' stroke='%237458dc' stroke-width='3' stroke-linecap='round'/%3E%3Cpolygon points='13,25 19.5,31 13,37 6.5,31' fill='%23df9a12'/%3E%3C/svg%3E">
  <style>__STYLES__</style>
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
        <div><h1>LogicChart</h1></div>
      </div>
      <div class="flow-heading">
        <div class="eyebrow" id="flowKind">No flow selected</div>
        <h2 id="flowTitle">Analyze a project to begin</h2>
      </div>
      <div class="metrics">
        <div class="metric"><strong id="flowCount">0</strong> <span>flows</span></div>
        <div class="metric"><strong id="entryCount">0</strong> <span>entries</span></div>
      </div>
    </header>

    <aside class="left-rail" id="leftRail">
      <div class="rail-inner">
        <div class="rail-head codebase-head">
          <div class="rail-head-row">
            <h2 class="rail-title">Codebase</h2>
          </div>
          <input class="filter" id="globalSearch" type="search" placeholder="Find path, symbol, or flow" aria-label="Find path, symbol, or flow">
          <select class="filter compact-filter" id="langFilter" aria-label="Filter by language" style="display:none"></select>
        </div>
        <div class="tree" id="tree" role="tree" aria-label="Directory tree"></div>
        <div class="legend">
          <span>Action</span><span class="decision">Decision</span>
          <span class="call">Subflow</span><span class="outcome">Outcome</span>
        </div>
      </div>
      <div class="rail-resizer rail-resizer-left" id="leftRailResizer" role="separator" tabindex="0" aria-label="Resize codebase sidebar" aria-orientation="vertical" aria-valuemin="240" aria-valuemax="560" aria-valuenow="312" title="Resize codebase sidebar"></div>
    </aside>

    <main>
      <nav id="breadcrumb" class="breadcrumb" aria-label="Canvas level"></nav>
      <div class="canvas-toolbar" aria-label="Canvas controls">
        <div class="tool-group" aria-label="Panels">
          <button class="tool" id="menuButton" title="Toggle codebase tree" aria-label="Toggle codebase tree">&#9776;</button>
          <button class="tool detail-tool" id="detailButton" title="Show source and details" aria-label="Toggle source and details" aria-pressed="false">i</button>
        </div>
        <div class="tool-group" aria-label="Graph viewport">
          <button class="tool reset-tool command-tool" id="resetView" title="Collapse all expanded sections and return to the codebase root" aria-label="Collapse all expanded sections and return to the codebase root">RESET</button>
          <button class="tool expand-tool command-tool" id="expandView" title="Expand all scopes and flows in the current graph" aria-label="Expand all scopes and flows in the current graph">EXPAND</button>
          <button class="tool" id="fitView" title="Fit current flowchart" aria-label="Fit current flowchart">&#8982;</button>
          <button class="tool" id="zoomOut" title="Zoom out" aria-label="Zoom out">&minus;</button>
          <button class="tool" id="zoomIn" title="Zoom in" aria-label="Zoom in">+</button>
        </div>
        <div class="tool-group" aria-label="Output">
          <button class="tool export-tool" id="exportPng" title="Export current flowchart as PNG" aria-label="Export current flowchart as PNG">PNG</button>
          <button class="tool export-tool" id="exportJpg" title="Export current flowchart as JPG" aria-label="Export current flowchart as JPG">JPG</button>
          <button class="tool" id="fullscreenToggle" data-action="fullscreen" title="Full screen (Esc to exit)" aria-label="Toggle full-screen canvas" aria-pressed="false">&#9974;</button>
        </div>
      </div>
      <div id="typedViewerHost" class="typed-viewer-host" hidden aria-label="Framework-backed flowchart"></div>
      <div class="empty" id="emptyState"><p>No matching flow was found.</p></div>
    </main>

    <aside class="right-rail" id="rightRail">
      <div class="rail-resizer rail-resizer-right" id="rightRailResizer" role="separator" tabindex="0" aria-label="Resize details sidebar" aria-orientation="vertical" aria-valuemin="280" aria-valuemax="640" aria-valuenow="336" title="Resize details sidebar"></div>
      <div class="rail-inner">
        <div class="detail-drawer-head">
          <span>Details</span>
          <div class="panel-stack-tools" aria-label="Details sections">
            <button class="panel-stack-control" id="detailsCollapseAll" type="button" title="Collapse all detail sections" aria-label="Collapse all detail sections">-</button>
            <button class="panel-stack-control" id="detailsExpandAll" type="button" title="Expand all detail sections" aria-label="Expand all detail sections">+</button>
          </div>
          <button class="panel-close" id="detailsClose" type="button" title="Hide source and details" aria-label="Hide source and details">&times;</button>
        </div>
        <section class="panel panel-quality" id="qualityPanel" aria-label="Analysis health" data-collapsible-panel data-panel-state="quality">
          <div class="panel-head" data-panel-heading>
            <button class="panel-collapse-toggle" id="qualityPanelToggle" type="button" data-panel-toggle aria-expanded="true" aria-controls="quality" title="Collapse Analysis health" aria-label="Collapse Analysis health"><span class="panel-chevron" aria-hidden="true"></span></button>
            <h2 class="rail-title">Analysis health</h2>
            <span class="panel-count" id="qualityCount" aria-hidden="true"></span>
          </div>
          <div class="panel-body quality-scroll" id="quality" role="region" aria-label="Analysis health metrics"></div>
        </section>
        <section class="panel panel-source" id="sourcePanel" aria-label="Source" data-collapsible-panel data-panel-state="source">
          <div class="panel-head" data-panel-heading>
            <button class="panel-collapse-toggle" id="sourcePanelToggle" type="button" data-panel-toggle aria-expanded="true" aria-controls="source" title="Collapse Source" aria-label="Collapse Source"><span class="panel-chevron" aria-hidden="true"></span></button>
            <h2 class="rail-title">Source</h2>
            <span class="panel-file" id="sourceFile"></span>
          </div>
          <div class="panel-body source-scroll" id="source" role="region" aria-label="Source code">
            <p class="panel-empty">Select a flow or node to view its source.</p>
          </div>
        </section>
      </div>
    </aside>
  </div>

  <!-- Visually-hidden polite live region: panels.js announces source/detail changes
       on each selection so screen-reader users are notified when the panels re-render. -->
  <div id="panelStatus" class="sr-only" role="status" aria-live="polite"></div>

  <script id="logicchart-data" type="application/json">__LOGICCHART_DATA__</script>
  <script>__SHELL_JS__</script>
  <script>__TREE_JS__</script>
  <script>__PANELS_JS__</script>
  <script>__VIEWER_RUNTIME_JS__</script>
  <script>
    (function () {
      const runtime = window.LogicChartViewer;
      const host = document.getElementById("typedViewerHost");
      const data = document.getElementById("logicchart-data");
      if (!runtime || !host || !data || !runtime.mountStandaloneLogicChartViewer) {
        document.body.dataset.runtime = "unavailable";
        return;
      }
      document.body.dataset.runtime = "react";
      host.hidden = false;
      try {
        const payload = JSON.parse(data.textContent || "{}");
        window.logicchartTypedViewer = runtime.mountStandaloneLogicChartViewer(host, payload);
        if (window.LC && window.LC.syncShellFromHash) window.LC.syncShellFromHash();
      } catch (error) {
        host.hidden = true;
        document.body.dataset.runtime = "unavailable";
        console.error("Unable to start React viewer runtime", error);
      }
    })();
  </script>
</body>
</html>
"""
