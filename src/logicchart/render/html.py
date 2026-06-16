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


def render_html(model: ProjectModel, source_root: Path | None = None) -> str:
    payload = json.dumps(build_payload(model, source_root), ensure_ascii=False).replace(
        "</", "<\\/"
    )
    css = _asset("styles.css")
    js = _inline_js("shell.js")
    canvas_js = _inline_js("canvas.js")
    tree_js = _inline_js("tree.js")
    panels_js = _inline_js("panels.js")
    return (
        _HTML_TEMPLATE.replace("__STYLES__", css)
        .replace("__SHELL_JS__", js)
        .replace("__CANVAS_JS__", canvas_js)
        .replace("__TREE_JS__", tree_js)
        .replace("__PANELS_JS__", panels_js)
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
          <h2 class="rail-title">Codebase</h2>
          <input class="filter" id="globalSearch" type="search" placeholder="Search flows" aria-label="Search flows">
          <select class="filter" id="langFilter" aria-label="Filter by language" style="display:none"></select>
        </div>
        <div class="tree" id="tree" role="tree" aria-label="Directory tree"></div>
        <div class="legend">
          <span>Action</span><span class="decision">Decision</span>
          <span class="call">Subflow</span><span class="outcome">Outcome</span>
          <span class="gap">Review</span>
        </div>
      </div>
    </aside>

    <main>
      <nav id="breadcrumb" class="breadcrumb" aria-label="Canvas level"></nav>
      <div class="canvas-toolbar" aria-label="Canvas controls">
        <button class="tool" id="menuButton" title="Toggle codebase tree" aria-label="Toggle codebase tree">&#9776;</button>
        <button class="tool detail-tool" id="detailButton" title="Show source and findings" aria-label="Toggle source and findings" aria-pressed="false">i</button>
        <button class="tool" id="zoomOut" title="Zoom out">&minus;</button>
        <button class="tool" id="resetView" title="Reset view &amp; layout">0</button>
        <button class="tool" id="zoomIn" title="Zoom in">+</button>
        <button class="tool" id="fullscreenToggle" data-action="fullscreen" title="Full screen (Esc to exit)" aria-label="Toggle full-screen canvas" aria-pressed="false">&#9974;</button>
      </div>
      <svg id="canvas" role="img" aria-label="Codebase canvas" data-level="0"></svg>
      <div class="empty" id="emptyState"><p>No matching flow was found.</p></div>
    </main>

    <aside class="right-rail" id="rightRail">
      <div class="rail-inner">
        <div class="detail-drawer-head">
          <span>Details</span>
          <button class="panel-close" id="detailsClose" type="button" title="Hide source and findings" aria-label="Hide source and findings">&times;</button>
        </div>
        <section class="panel panel-source" id="sourcePanel" aria-label="Source">
          <div class="panel-head">
            <h2 class="rail-title">Source</h2>
            <span class="panel-file" id="sourceFile"></span>
          </div>
          <div class="panel-body source-scroll" id="source" role="region" aria-label="Source code">
            <p class="panel-empty">Select a flow or node to view its source.</p>
          </div>
        </section>
        <section class="panel panel-errors" id="errorsPanel" aria-label="Logical errors">
          <div class="panel-head">
            <h2 class="rail-title">Logical errors</h2>
            <button class="panel-action" id="reviewQueueToggle" type="button" aria-pressed="false" title="Show prioritized review queue">Queue</button>
            <span class="panel-count" id="errorsCount" aria-hidden="true"></span>
          </div>
          <div class="panel-body errors-scroll" id="errors" role="list" aria-label="Findings for the current selection">
            <p class="panel-empty">No findings for the current selection.</p>
          </div>
        </section>
      </div>
    </aside>
  </div>

  <!-- Visually-hidden polite live region: panels.js announces the source/findings change
       on each selection so screen-reader users are notified when the panels re-render. -->
  <div id="panelStatus" class="sr-only" role="status" aria-live="polite"></div>

  <script id="logicchart-data" type="application/json">__LOGICCHART_DATA__</script>
  <script>__SHELL_JS__</script>
  <script>__CANVAS_JS__</script>
  <script>__TREE_JS__</script>
  <script>__PANELS_JS__</script>
</body>
</html>
"""
