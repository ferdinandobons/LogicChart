"""Viewer-shell smoke tests.

The HTML viewer is assembled from a template plus extracted assets
(``render/assets/styles.css`` and ``render/assets/shell.js``) and a JSON payload
built by :func:`build_payload`. These tests pin the seams so a future split of
the assets cannot silently drop the style block, the data hook, or the canvas.
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
    # The main canvas the viewer draws into is wired up.
    assert 'id="canvas"' in html


def test_build_payload_has_flows(tmp_path: Path) -> None:
    payload = build_payload(_model(tmp_path), tmp_path)
    assert isinstance(payload, dict)
    assert payload["flows"]


def test_render_html_emits_directory_tree(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The directory tree container the left rail renders into is wired up.
    assert 'id="tree"' in html
    # The language dropdown above the tree is present (hidden until >1 language).
    assert 'id="langFilter"' in html
    # Search-driven navigation is wired into the same tree surface.
    assert 'id="globalSearch"' in html
    # tree.js is actually inlined into the page (a function unique to it). Asserting a
    # runtime-only DOM attribute like data-flow-id would pass vacuously just because the
    # script source mentions it, so we pin a structural marker instead.
    assert "refreshRovingTarget" in html
    assert "flowMatchesQuery" in html

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
        "__CANVAS_JS__",
        "__TREE_JS__",
        "__PANELS_JS__",
        "__LOGICCHART_DATA__",
    ):
        assert placeholder not in html


def test_render_html_emits_codebase_canvas(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The canvas carries a level attribute (L0 by default); the codebase-canvas smoke test
    # asserts the level seam exists so the two-level canvas cannot silently regress.
    assert "data-level" in html
    # The breadcrumb container the canvas level path renders into is wired up.
    assert 'id="breadcrumb"' in html
    # canvas.js is actually inlined: a structural marker unique to it (the renderL0
    # entry) plus the data-scope attribute literal it stamps on every super-node.
    assert "renderL0" in html
    assert "data-scope" in html
    # The payload carries the aggregated cross-scope edge list the L0 view draws.
    match = re.search(
        r'<script id="logicchart-data" type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1).replace("<\\/", "</"))
    assert isinstance(payload["scope_edges"], list)
    # A focused scope remains inside the global codebase map: sibling scopes stay visible
    # as dimmed context nodes while the active scope expands into a progressive route.
    assert "layoutExpandedCodebase" in html
    assert "dimmed" in html
    assert "focusScope" in html
    # The primary canvas is flow-first: scopes expand into a universal progressive
    # entrypoint/call graph, not file boxes tuned to a particular repository shape.
    assert "buildProgressiveLayers" in html
    assert "routeFlowIds" in html


def test_render_html_includes_semantic_flow_kind_styles(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    assert ".flow-node.flow-kind-route" in html
    assert ".flow-node.flow-kind-function" in html
    assert ".flow-node.flow-kind-component" in html
    assert ".flow-node.flow-kind-service" in html
    assert ".scope-node .shape" in html
    assert "--scope-hue" in html
    assert '[data-theme="dark"] .typed-viewer-host .scope-node .shape' in html
    assert "expandedFlowIds" in html
    assert "progressive-row-label" in html
    assert "unlocked calls" in html
    assert "flow-source-tag" in html
    assert "flow-expand-pill" in html
    assert "expandCallTarget" in html
    assert "clearAllInlineFlows" in html
    assert "omitEntry" in html
    assert "draggable: true" in html
    assert "flowLayoutNodes" in html
    assert "selectProgressiveLink" in html
    assert "progressive-call-edge" in html
    assert "progressive-call-hit" in html
    assert "progressive-call-label" in html
    assert "scope-entry-link" in html
    assert "scopeEntryGeometry" in html
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
    assert "manualScopePositions" in html
    assert "manualFlowPositions" in html
    assert "cssEscape(" in html
    assert 'typeof window.CSS.escape === "function"' in html
    assert '"node entry scope-node movable"' in html
    assert "hsl(var(--scope-hue" in html
    assert ".scope-node .scope-name" not in html
    assert "active-parent" in html
    assert "exportCurrentCanvas" in html
    assert "logicchart-flowchart" in html
    assert 'id="fitView"' in html
    assert "Fit current flowchart" in html
    assert "typed.fitView" in html
    assert 'class="tool-group"' in html
    assert 'class="tool reset-tool"' in html
    assert ">Reset</button>" in html
    assert "Export current flowchart as PNG" in html
    assert "Export current flowchart as JPG" in html
    assert "themeToggle" not in html
    assert "inline-flow-panel" not in html
    assert "makeFileBox" not in html
    assert "expandedFiles" not in html


def test_render_html_wires_inline_decision_expansion(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # Phase 3 (L2): a flow node unfolds its decision flowchart in place inside the L1
    # canvas. Pin the seam so the inline expander cannot silently regress:
    #   - canvas.js exposes the inline entry shell.js's selectFlow delegates to,
    #   - it draws a dedicated inline sub-graph layer,
    #   - shell.js exposes the reusable decision renderer the inline path reuses.
    assert "expandFlowInline" in html
    assert "inline-flow" in html
    assert "drawFlowGraph" in html
    # The reusable measure helper that reserves the inline band (so siblings never overlap).
    assert "measureFlow" in html


def test_render_html_emits_source_and_errors_panels(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # Phase 4: the right column splits into a Source panel (top) and a Logical-errors
    # panel (bottom). Pin both container ids so the split cannot silently regress.
    assert 'id="source"' in html
    assert 'id="errors"' in html
    assert 'id="reviewQueueToggle"' in html
    # panels.js is actually inlined: a structural marker unique to it (the function that
    # subscribes both panels to the shared selection store).
    assert "renderSource" in html
    assert "renderErrors" in html
    assert "prioritizedFindings" in html
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
    assert "selectFile(" in html
    assert "setLevelHeader(" in html

    # Breadcrumb and file chips should use a context-bearing path label, not only the
    # basename (many frameworks have repeated names like route.ts).
    assert "shortPathLabel(" in html
    assert "treePathLabel(" in html

    # Flow rows in the tree should render metadata as compact chips, not stacked text that
    # breaks differently for every entry kind/framework.
    assert "tree-flow-badges" in html

    # The Source panel is meaningful only when a file/flow is selected; scope/root views
    # should let Logical errors use the right rail without a placeholder source panel.
    assert "sourcePanel.hidden = !flow" in html

    # Selecting a decision node should visually select its finding row even when the user
    # did not click the finding row itself.
    assert "finding.node_id === sel.nodeId" in html

    # Full-screen canvas hides rails, so the rail menu must not remain as a no-op control.
    assert "body[data-fullscreen] #menuButton" in html

    # Narrow-view study mode keeps the canvas primary: source/findings are a stateful
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
    assert "focusPath" in html
    assert 'key === "path"' in html
    assert "active-folder" in html
    # Revealing the active flow in the tree is programmatic; it must not fire the same
    # path-focus side effect as an intentional user click, or #flow deep links collapse
    # back to #path while the inline decision graph is open.
    assert "suppressScopeFocus" in html

    # Large-codebase scan aids: scope finding density, progressive route expansion, and
    # tree empty state for search/filter misses should stay wired into the static viewer.
    assert "scopeStats(" in html
    assert "directCallTargets(" in html
    assert "entryFlowsForScope(" in html
    assert "No matching flows" in html

    # Desktop rails are not static columns: each sidebar has an accessible drag separator,
    # persistent width state, keyboard resizing, and a canvas-layout refresh hook.
    assert 'id="leftRailResizer"' in html
    assert 'id="rightRailResizer"' in html
    assert 'role="separator"' in html
    assert "logicchart-left-rail-width" in html
    assert "logicchart-right-rail-width" in html
    assert "resizeRailFromKeyboard" in html
    assert "refreshCanvasLayout" in html
    assert "data-nav-closed" in html
    assert "body[data-nav-closed] .shell" in html
    assert "data-detail-closed" in html
    assert "Reset expanded sections and fit current scope" in html
    assert "Open ${flow.name} in the progressive flowchart" in html
    assert "Select logic block on line" in html
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
    assert "clearCanvasFocus" in html
    assert "openDetails" in html
    assert ".edge-hit, .edge-hit-segment, .edge-label-wrap" in html
    assert "bindEdgeActivationParts" in html
    assert "setEdgeHitGeometry(hit, geometry, activate" in html
    assert "routeEdgeRecordFromElement" in html
    assert "decisionEdgeRecordFromElement" in html


def test_render_html_wires_framework_viewer_runtime(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # The framework-backed progressive canvas is now the default HTML runtime. The legacy
    # static canvas remains available as an explicit fallback for debugging and bundle
    # failures, but ordinary generated viewers should open on the typed frontend.
    assert 'id="typedViewerHost"' in html
    assert 'data-runtime = "react"' not in html
    assert 'dataset.runtime = "react"' in html
    assert 'params.get("runtime") === "static"' in html
    assert 'dataset.runtime = "static"' in html
    assert "mountStandaloneLogicChartViewer" in html
    assert "logicchartTypedViewer" in html
    # After the React viewer mounts successfully, the hidden legacy SVG must not keep a
    # second copy of the flow nodes in the DOM. Keeping it empty avoids duplicate canvas
    # query/hit state while preserving the static fallback when React cannot start.
    assert 'legacyCanvas.textContent = ""' in html
    assert 'legacyCanvas.setAttribute("aria-hidden", "true")' in html
    assert 'legacyCanvas.setAttribute("data-runtime-inactive", "true")' in html
