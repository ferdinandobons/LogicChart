# LogicChart viewer

The LogicChart viewer is an offline, generated UI for studying large codebases as one
progressive decision flowchart.

The default artifact is still `logic-flow.html`: a single local HTML file with embedded
CSS, JavaScript, payload data, and the framework runtime. It can be opened through
`logicchart view`, committed as a generated artifact when useful, or regenerated with
`logicchart view --render-only`.

## Product shape

The canvas should read as one navigable flowchart:

1. The first row is the codebase scope map (`backend`, `frontend`, `edge`, or any configured
   macro-part).
2. Selecting a scope reveals the entrypoints in that scope without closing previously
   opened scopes, so multiple codebase areas can stay visible in the same canvas.
3. Selecting an entrypoint expands that flow in place, including its decisions, outcomes,
   and direct call targets.
4. Selecting an internal flow reconstructs the visible caller chain from the scope entrypoint
   instead of placing that flow as a detached island.
5. Selecting a connection highlights the source node, target node, and connection while
   dimming unrelated blocks.
6. Selecting empty canvas space clears connection focus and returns the scope view to its
   normal contrast.

The renderer must remain shape-agnostic. It should never special-case names such as
`backend`, `frontend`, or `edge`; those are ordinary scope values from the generated model.

## Runtime path

There is one official viewer path:

| Runtime | How to open it | Responsibility |
| --- | --- | --- |
| React runtime | `logic-flow.html` | Default progressive canvas, scope nodes, scope-entry links, flow detail charts, viewport zoom/pan/reset, graph-bounds-aware raster export |

The React runtime is built from `frontend/` into
`src/logicchart/render/assets/generated/logicchart-viewer-runtime.iife.js` and then embedded
by `src/logicchart/render/html.py`. Generated HTML should always mount the React runtime;
the retired static canvas is no longer shipped as a selectable runtime because it split
behavior between two chart implementations.

The shell and React runtime deliberately share the same generated payload. The shell still
drives the side panels and tree selection; the React runtime synchronizes through hashes
such as:

```text
#scope=frontend
#flow=<flow-id>
#root
#node=codebase
#edge=<encoded scope-entry connection>
```

## Layout rules

The viewer layout should preserve these invariants:

- Top-level scope nodes use the same node styling family as entrypoints and flows.
- Scope colors come from deterministic per-payload hues, not hard-coded names, and the CSS
  adapts their fill/stroke for light and dark themes.
- A scope connects to every visible entrypoint below it.
- Previously opened scopes remain expanded when another scope is selected.
- Selecting the codebase root uses `#node=codebase` and highlights connected scopes without
  expanding an arbitrary fallback scope.
- Reset clears opened scopes, opened flows, manual positions, and viewport state, then
  returns to `#root`, the collapsed codebase map.
- Expand all opens every non-test scope and flow from the generated payload; it must be
  payload-driven rather than tuned to demo scope names or file paths.
- Expanded scope sections follow the root-map rows, so large codebases pack into readable
  vertical bands instead of one unbounded horizontal strip.
- Fit re-centers the current visible flowchart without closing expanded scopes, expanded
  flows, or manual block positions.
- The codebase rail should stay operational: path/symbol/finding search, review-only
  triage, and optional language filtering when the payload is polyglot.
- Expanded flow detail charts reserve their visual band before later rows are placed.
- Every visible flow node is reachable from the codebase root through root-scope,
  scope-entry, or flow-call edges.
- Hidden hit paths exist for pointer targeting but must never render visible boxes.
- Pan and zoom are viewport operations; they must not mutate model layout.
- Viewport operations must remain finite and recoverable: invalid zoom inputs are ignored,
  free pan is unbounded, and Reset returns to the collapsed baseline view.
- Wheel and trackpad zoom must stay anchored to the cursor in the active runtime.
- The minimap is an aggregate navigator, not a second tiny node renderer: it shows the
  graph bounds and current viewport, scrolls to pan the canvas, double-clicks to fit, and
  keeps the viewport visible even when free pan moves outside the graph bounds.
- The left tree may normalize display labels for scanning, such as HTTP-method routes or
  camelCase symbols, but tooltips and source panels must preserve the original symbol and
  source location.
- Large entrypoint rows wrap instead of forcing unbounded horizontal overflow.

The frontend tests expose reusable layout checks through `viewerLayoutBoxes`,
`overlappingLayoutBoxes`, `viewerLayoutEdgeObstacleHits`, and
`viewerLayoutQualityReport`. Use the quality report when a change needs one machine-readable
answer for whether the layout is clear: no block overlaps, no routed edge/box collisions,
no detached visible flow nodes, finite canvas bounds, and coherent node/edge counts. Add
new overlap, reachability, or routing cases when changing spacing, node sizes, row
wrapping, manual positioning, call-chain expansion, or inline detail measurements.

## Development workflow

Install the frontend workspace once:

```bash
npm install
```

For viewer changes, run:

```bash
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart update
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart view examples/demo --render-only --no-open
```

Before declaring a viewer change done, also run:

```bash
node --check src/logicchart/render/assets/generated/logicchart-viewer-runtime.iife.js
node --check src/logicchart/render/assets/shell.js
node --check src/logicchart/render/assets/tree.js
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run pytest tests/test_render_html.py
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run pytest
```

Browser checks should use a regenerated demo artifact and a cache-buster URL:

```text
http://localhost:<port>/examples/demo/logicchart-out/logic-flow.html?v=<stamp>#scope=frontend
```

High-value browser checks:

- Scope view stays on `#scope=frontend` and does not open a flow by default.
- Scope node count, entrypoint node count, and scope-entry edge count match the payload.
- Opening a second scope keeps the first scope's entrypoints visible and connected.
- Reset returns to `#root` with only the codebase and top-level scope nodes visible.
- Clicking a scope-entry connection selects exactly one link, one source, and one target,
  while unrelated nodes/links dim.
- Clicking blank canvas clears connection focus.
- Clicking an entrypoint from the canvas and from the tree opens the same flow detail.
- The source panel shows the selected flow's file and line range.
- Wheel zoom, canvas pan, minimap drag/scroll pan, fit, reset, PNG export, and JPG export
  route through the active runtime.
- PNG/JPG export resolution follows the graph bounds rather than the current viewport, with
  browser-safe caps for very large charts.
- SVG hit paths remain invisible in screenshots and exports.

## Documentation discipline

Keep `README.md`, `CONTRIBUTING.md`, this file, and the generated agent instructions in
sync whenever the viewer workflow changes. When runtime ownership changes, update the
default URL examples and make sure no retired runtime path remains documented.
