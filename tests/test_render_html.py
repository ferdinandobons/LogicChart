"""Viewer-shell smoke tests.

The HTML viewer is assembled from a template plus extracted assets
(``render/assets/styles.css`` and ``render/assets/shell.js``) and a JSON payload
built by :func:`build_payload`. These tests pin the seams so a future split of
the assets cannot silently drop the style block, the data hook, or the official
React chart runtime.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.render.html import render_html
from logicchart.render.payload import build_payload


def _model(tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def handle(account):\n    if account.active:\n        return ok()\n    return denied()\n",
        encoding="utf-8",
    )
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def test_render_html_emits_shell(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # Style block survived the asset extraction.
    assert "<style>" in html
    # The JSON payload hook the shell script reads from is present.
    assert "logicchart-data" in html
    # The official chart host the viewer draws into is wired up.
    assert 'id="typedViewerHost"' in html
    # The header stays compact and avoids decorative product-tagline copy.
    assert "Decision flow index" not in html


def test_build_payload_has_flows(tmp_path: Path) -> None:
    payload = build_payload(_model(tmp_path), tmp_path)
    assert isinstance(payload, dict)
    assert payload["flows"]


def test_render_html_emits_directory_tree(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The directory tree container the left rail renders into is wired up.
    assert 'id="tree"' in html
    # Codebase search and language filter are wired above the tree.
    assert 'id="langFilter"' in html
    assert 'id="globalSearch"' in html
    assert "Find path, symbol, or flow" in html
    # tree.js is actually inlined into the page (a function unique to it). Asserting a
    # runtime-only DOM attribute like data-flow-id would pass vacuously just because the
    # script source mentions it, so we pin a structural marker instead.
    assert "refreshRovingTarget" in html
    assert "flowMatchesQuery" in html
    assert "setupReviewFilter" not in html

    # The embedded JSON payload carries a non-empty directory tree (file leaves with
    # flow ids), not just the literal key. Parse the data <script> and check it.
    match = re.search(
        r'<script id="logicchart-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))
    tree = payload["tree"]
    assert tree["type"] == "dir"
    assert tree["children"], "expected at least one file/dir node in the tree"

    def _has_flow_leaf(node: dict) -> bool:
        if node["type"] == "file" and node["flow_ids"]:
            return True
        return any(_has_flow_leaf(child) for child in node["children"])

    assert _has_flow_leaf(tree), "expected a file leaf carrying flow ids"


def test_render_html_has_no_leftover_placeholders(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    for placeholder in (
        "__STYLES__",
        "__SHELL_JS__",
        "__TREE_JS__",
        "__PANELS_JS__",
        "__LOGICCHART_DATA__",
    ):
        assert placeholder not in html


def test_render_html_emits_official_react_flowchart(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The breadcrumb container the chart level path renders into is wired up.
    assert 'id="breadcrumb"' in html
    # The old static renderer is not present or inlined.
    assert 'id="canvas"' not in html
    assert "renderL0" not in html
    assert "expandFlowInline" not in html
    # The payload carries the aggregated cross-scope edge list the L0 view draws.
    match = re.search(
        r'<script id="logicchart-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))
    assert isinstance(payload["scope_edges"], list)
    # The primary canvas is flow-first: scopes expand into a universal progressive
    # entrypoint/call graph, not file boxes tuned to a particular repository shape.
    assert "mountStandaloneLogicChartViewer" in html
    assert "routeFlowIds" in html


def test_render_html_includes_semantic_flow_kind_styles(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    assert ".flow-node.flow-kind-route" in html
    assert ".flow-node.flow-kind-function" in html
    assert ".flow-node.flow-kind-component" in html
    assert ".flow-node.flow-kind-service" in html
    assert ".typed-viewer-host .flow-node.flow-open .shape" in html
    assert ".typed-viewer-host .flow-node.flow-open.selected .shape" in html
    assert ".scope-node .shape" in html
    assert "--scope-hue" in html
    assert '[data-theme="dark"] .typed-viewer-host .scope-node .shape' in html
    assert "openedFlowIds" in html
    assert "openedScopeIds" in html
    assert "progressive-row-label" in html
    assert "unlocked calls" in html
    assert "flow-source-tag" in html
    assert "flow-expand-pill" in html
    assert "expandCallTarget" in html
    assert "resetView()" in html
    assert "omitEntryNode" in html
    assert "movable" in html
    assert "routeFlowIds" in html
    assert "selectedConnection" in html
    assert "progressive-call-edge" in html
    assert "progressive-call-hit" in html
    assert "progressive-call-label" in html
    assert "scope-entry-link" in html
    assert "scope-entry" in html
    assert "rowWidthForLayer" in html
    assert "scope-expansion-link" not in html
    assert "edge-source" in html
    assert "selected-link" in html
    assert "edge-focus" in html
    assert "focus-hidden" in html
    assert "arrowFocus" in html
    assert "edge-hit" in html
    assert "edge-hit-segment" in html
    assert "edgeId" in html
    assert "manualNodePositions" in html
    assert "cssEscape(" in html
    assert ".scope-node" in html
    assert "movable" in html
    assert "hsl(var(--scope-hue" in html
    assert ".scope-node .scope-name" not in html
    assert "active-parent" in html
    assert "exportCurrentCanvas" in html
    assert "logicchart-flowchart" in html
    assert 'id="fitView"' in html
    assert "Fit current flowchart" in html
    assert "typed.fitView" in html
    assert 'id="expandView"' in html
    assert ">EXPAND</button>" in html
    assert "typed.expandAll" in html
    assert "logicchart-expand-progress" in html
    assert 'class="tool-group"' in html
    assert 'class="tool reset-tool command-tool"' in html
    assert 'class="tool expand-tool command-tool"' in html
    assert ">RESET</button>" in html
    assert "Export current flowchart as PNG" in html
    assert "Export current flowchart as JPG" in html
    assert "themeToggle" not in html
    assert "logicchart-overview" not in html
    assert "inline-flow-panel" not in html
    assert "makeFileBox" not in html
    assert "expandedFiles" not in html


def test_render_html_wires_framework_decision_expansion(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The framework runtime owns progressive expansion. Pin these seams so the generated
    # viewer cannot regress into the deleted static canvas path.
    assert "mountStandaloneLogicChartViewer" in html
    assert "selectFlow(flow.id)" in html
    assert "selectScope" in html
    assert "syncShellFromHash" in html
    assert "expandFlowInline" not in html


def test_render_html_emits_quality_and_source_panels(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The right rail is for model quality and source inspection.
    assert 'id="source"' in html
    assert 'id="quality"' in html
    assert 'id="errors"' not in html
    assert "data-collapsible-panel" in html
    assert 'id="qualityPanelToggle"' in html
    assert 'id="sourcePanelToggle"' in html
    assert 'id="errorsPanelToggle"' not in html
    assert 'id="detailsCollapseAll"' in html
    assert 'id="detailsExpandAll"' in html
    assert 'aria-controls="quality"' in html
    assert 'aria-controls="source"' in html
    assert 'aria-controls="errors"' not in html
    # panels.js is actually inlined: structural markers unique to quality/source rendering.
    assert "renderSource" in html
    assert "renderQuality" in html
    assert "renderErrors" not in html
    assert "appendDiagnosticChart" not in html
    assert "diagnosticChartItems" not in html
    assert "diagnostic-grid" not in html
    assert "diagnostic-chart" not in html
    assert "Diagnostic subgraph" not in html
    assert "Focused diagnostic subgraph" not in html
    assert "data-diagnostic-chart-node" not in html
    assert "diagnostic-related" not in html
    # The full-screen toggle on the canvas toolbar (aria-pressed, data-action hook).
    assert 'data-action="fullscreen"' in html
    assert 'id="detailButton"' in html
    assert 'id="detailsClose"' in html
    assert "aria-pressed" in html
    assert "setRightRailOpen(false);" in html
    # The shared selection store the four surfaces publish/subscribe through.
    assert "LC.select" in html

    # The visually-hidden aria-live region the panels announce selection changes into.
    assert 'id="panelStatus"' in html
    assert 'aria-live="polite"' in html

    # The embedded payload carries the shared source-file store, and each flow holds a
    # lightweight reference into it (not its own copy). We can only assert the payload
    # here (no DOM), so check the reference + store rode along.
    match = re.search(
        r'<script id="logicchart-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))
    flow = payload["flows"][0]
    ref = flow["source"]
    assert ref is not None
    assert ref["path"] in payload["source_files"], "flow source must reference the file store"
    store = payload["source_files"][ref["path"]]
    assert store["lines"], "expected embedded source lines in the file store"
    # The code-line class panels.js stamps on each rendered snippet line is present in
    # the inlined stylesheet/script (the hook the DOM verification asserts at runtime).
    assert "code-line" in html


def test_render_html_wires_state_aware_viewer_controls(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # File/path selections must drive the same shared selection store as flow/node clicks,
    # otherwise opening a file can leave the Source panel showing a stale sibling file.
    assert "syncShellFromHash" in html
    assert 'key === "path"' in html

    # Breadcrumb and file chips should use a context-bearing path label, not only the
    # basename (many frameworks have repeated names like route.ts).
    assert "flowSourceLabel(" in html
    assert "treePathLabel(" in html

    # Flow rows in the tree should render metadata as compact chips, not stacked text that
    # breaks differently for every entry kind/framework.
    assert "tree-flow-badges" in html
    assert "tree-flow-title" in html
    assert "tree-flow-source" in html
    assert "flowDisplayName(" in html
    assert "flowRoleClass(" in html
    assert "humanizeIdentifier(" in html

    # The Source panel is meaningful only when a file/flow is selected; scope/root views
    # keep the details rail focused on model quality instead of placeholder source content.
    assert "sourcePanel.hidden = !flow" in html

    # Project-quality metrics are surfaced in the details rail from generated metadata,
    # giving large-codebase exploration a visible analyzer coverage and precision snapshot.
    assert 'id="qualityPanel"' in html
    assert "model.metadata.quality" in html
    assert "qualityMetric(" in html
    assert "Call resolution" in html
    assert "Skipped files" in html
    assert "Parse warnings" in html
    assert "Language attention" in html
    assert ".quality-metrics" in html

    # Full-screen canvas hides rails, so the rail menu must not remain as a no-op control.
    assert "body[data-fullscreen] #menuButton" in html

    # Narrow-view study mode keeps the canvas primary: source/details are a stateful
    # details drawer, and the canvas level is mirrored onto the body for responsive styling.
    assert "setRightRailOpen(" in html
    assert "data-detail-open" in html
    assert "data-nav-open" in html
    assert "dataset.canvasLevel" in html
    assert "translateY(100%)" in html

    # Language filtering is tree-local; changing it while a deep canvas selection is active
    # must clear the deep selection instead of leaving tree/canvas on different worlds.
    assert "clearCanvasSelectionForLanguageFilter" in html
    assert "sel.scope || (sel.path ? sel.path.split" in html

    # Opening a tree directory/file should focus that area on the integrated canvas,
    # including nested folders via the path hash route.
    assert "highlightPath" in html
    assert 'key === "path"' in html
    assert "active-folder" in html
    # Revealing the active flow in the tree is programmatic; it must not fire the same
    # path-focus side effect as an intentional user click, or #flow deep links collapse
    # back to #path while the inline decision graph is open.
    assert "suppressScopeFocus" in html

    # Large-codebase scan aids: progressive route expansion and
    # tree empty state for search/filter misses should stay wired into the viewer.
    assert "contextFlowIds" in html
    assert "entryFlowIds" in html
    assert "No matching flows" in html

    # Desktop rails are not static columns: each sidebar has an accessible drag separator,
    # persistent width state, keyboard resizing, and a canvas-layout refresh hook.
    assert 'id="leftRailResizer"' in html
    assert 'id="rightRailResizer"' in html
    assert 'role="separator"' in html
    assert "logicchart-left-rail-width" in html
    assert "logicchart-right-rail-width" in html
    assert "initCollapsiblePanels" in html
    assert "logicchart-panel-collapsed-" in html
    assert "data-panel-heading" in html
    assert 'id="qualityPanelToggle"' in html
    assert 'id="sourcePanelToggle"' in html
    assert 'id="errorsPanelToggle"' not in html
    assert 'aria-controls="quality"' in html
    assert 'aria-controls="source"' in html
    assert 'aria-controls="errors"' not in html
    assert 'target.closest("button, a, input, select, textarea")' in html
    assert 'heading.setAttribute("role", "button")' in html
    assert 'heading.setAttribute("tabindex", "0")' in html
    assert 'heading.setAttribute("aria-expanded"' in html
    assert 'heading.addEventListener("keydown"' in html
    assert 'event.key !== "Enter" && event.key !== " "' in html
    assert "setAllPanelsCollapsed" in html
    assert "detailsCollapseAll.addEventListener" in html
    assert ".panel-collapse-toggle" in html
    assert ".panel-stack-control" in html
    assert ".panel[data-collapsed]" in html
    assert ".panel-head[data-panel-heading]:focus-visible" in html
    assert (
        ".tree-dir.active-folder, .tree-file.active-file {\n      background: var(--active);"
        in html
    )
    assert ".tree-flow.active::before {\n      background: var(--blue);" in html
    assert ".panel-stack-control {\n      display: grid;" in html
    assert "background: var(--panel);\n      color: var(--ink);" in html
    assert "background: var(--active);\n      color: var(--blue);" in html
    assert "resizeRailFromKeyboard" in html
    assert "scheduleCanvasLayoutRefresh" in html
    assert "data-nav-closed" in html
    assert "body[data-nav-closed] .shell" in html
    assert "data-detail-closed" in html
    assert "@media (min-width: 701px) and (max-width: 1050px)" in html
    assert "body[data-detail-open] .canvas-toolbar" in html
    assert "right: calc(min(var(--right-rail-width), calc(100vw - 72px)) + 14px)" in html
    assert "Collapse all expanded sections and return to the codebase root" in html
    assert "Expand all scopes and flows in the current graph" in html
    assert "Open ${flowDisplayName(flow)} in the progressive flowchart" in html
    assert "Select source line" in html
    assert "selectedSourceRange" in html
    assert "sel.flowId === flow.id" in html

    # Canvas component polish: edge labels are readable pills and decision blocks carry a
    # compact semantic kind badge, so dense flowcharts retain their visual grammar.
    assert "edge-label-bg" in html
    assert "edgePathLayer" in html
    assert "edgeLabelLayer" in html
    assert "branch-exit-chip" in html
    assert "horizontalLabelX" in html
    assert "flowLayers(" in html
    assert "FLOW_LAYER_Y" in html
    assert "FLOW_SIBLING_X" in html
    assert "node-kind-badge" in html
    assert "safeDecodeHashValue" in html
    assert "manualPositions.clear()" in html
    assert "openDetails" in html
    assert (
        "LC.select(selectionForFlow(flow));\n"
        "          if (LC.openDetails) LC.openDetails();" in html
    )
    assert ".edge-hit, .edge-hit-segment, .edge-label-wrap" in html
    assert "bindEdgeActivationParts" in html
    assert "setEdgeHitGeometry(hit, geometry, activate" in html
    assert "selectedConnection" in html
    assert "flow-call" in html


def test_render_html_wires_framework_viewer_runtime(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The framework-backed progressive canvas is the official HTML runtime. The old static
    # chart is not a selectable runtime anymore.
    assert 'id="typedViewerHost"' in html
    assert 'data-runtime = "react"' not in html
    assert 'dataset.runtime = "react"' in html
    assert 'params.get("runtime") === "static"' not in html
    assert 'dataset.runtime = "static"' not in html
    assert 'dataset.runtime = "unavailable"' in html
    assert "mountStandaloneLogicChartViewer" in html
    assert "logicchartTypedViewer" in html
    assert "legacyCanvas" not in html
