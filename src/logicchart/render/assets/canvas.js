
    // Codebase canvas. Owns the progressive flowchart surface:
    //   L0 = one super-node per scope, edges = aggregated cross-scope calls.
    //   L1 = the whole codebase map plus one expanded scope's entrypoint/call graph.
    //   L2 = a selected flow's decisions unfolded in place inside that same graph.
    // The filesystem is navigation/evidence only: paths appear as small source tags,
    // never as the primary canvas hierarchy.
    //
    // OWNERSHIP SEAM: shell.js owns the SVG element, the shared `view` object, and
    // the pan/zoom/wheel handlers (generic over `view`). It exposes those as LC.svg,
    // LC.setView, LC.updateViewBox, LC.getView, LC.renderFlow and flips LC.mode to
    // "flow" right before renderFlow. canvas.js sets LC.mode = "canvas" and is the
    // SINGLE writer of the SVG for L0/L1 -- every entry (initial load, hashchange,
    // breadcrumb, expand/collapse) funnels through renderCanvas().
    //
    // LAZY INVARIANT: renderL0 builds only `scopes.length` super-node groups + the
    // scope_edges paths -- O(scopes), never O(flows). Expanding a scope draws only its
    // main entrypoints plus the downstream calls explicitly unlocked by the user. It
    // never dumps every file or every function from a large codebase onto the canvas.
    (function () {
      const LC = window.LC;
      if (!LC || !LC.svg) return; // shell.js must have booted and exposed the seam.

      const model = LC.model || {};
      const byId = LC.byId || new Map();
      const svg = LC.svg;
      const sortFlows = LC.sortFlows || (list => [...list]);
      const findings = model.findings || [];
      // Flow ids carrying at least one finding -> the "has-finding" ring (reused CSS).
      const findingFlowIds = new Set(
        findings.map(item => item.flow_id).filter(Boolean)
      );
      const findingsByFlow = new Map();
      findings.forEach(item => {
        if (!item.flow_id) return;
        const list = findingsByFlow.get(item.flow_id) || [];
        list.push(item);
        findingsByFlow.set(item.flow_id, list);
      });

      // World units match the existing ~290px decision nodes so shell.js's pan/zoom
      // (which mutates the shared `view`) reuses exactly, no rescaling.
      const SCOPE_W = 220;
      const SCOPE_H_MIN = 96;
      const SCOPE_H_MAX = 200;
      const FLOW_W = 238;
      const FLOW_H = 68;
      const GAP_X = 70;
      const GAP_Y = 60;
      const FLOW_ROW_GAP = 150;
      const FLOW_LAYER_GAP = 360;
      const FLOW_CHIP_Y = 27;
      const FLOW_META_Y = 45;
      const DETAIL_PAD = 60;

      const canvasEl = document.getElementById("canvas");
      const breadcrumbEl = document.getElementById("breadcrumb");
      const emptyState = document.getElementById("emptyState");
      // The shared empty-state <p> is reused by renderFlow too, so remember its default
      // copy and restore it whenever we are not showing the L0 "no scopes" message --
      // otherwise a no-scopes repo would leave "No scopes" stuck on later empty flows.
      const emptyMessageEl = emptyState ? emptyState.querySelector("p") : null;
      const defaultEmptyMessage = emptyMessageEl ? emptyMessageEl.textContent : "";
      function setEmptyMessage(text) {
        if (emptyMessageEl) emptyMessageEl.textContent = text;
      }

      // --- State (single explicit object; no hidden DOM state) ---------------------
      // L1 tracks an unlocked route of flows. The first layer is the active scope's
      // entrypoints; each route flow reveals only its direct call targets as the next
      // layer. This keeps the canvas universal and progressive across different codebases:
      // no backend/frontend/file assumptions, only entrypoints, calls, decisions, outcomes.
      const canvasState = {
        level: 0,
        expandedScope: null,
        selectedPath: null,
        selectedFlowId: null,
        selectedRouteEdge: null,
        routeFlowIds: [],
        // L2: all flow ids whose decision flowcharts are unfolded IN PLACE inside L1.
        // `expandedFlow` is only the active/last-selected one for hash, focus, and reset.
        expandedFlowIds: new Set(),
        expandedFlow: null,
      };
      // Decision-node node geometry (matches shell.js's L2 chart: 290x86 rects, 145-radius
      // diamonds). Used only to reserve the inline band; the real nodes come from shell.js.
      const DECISION_PAD = 90; // breathing room around the reserved inline sub-graph.
      // Stable DOM id for the inline sub-graph wrap of a given flow, so the host flow node
      // can aria-controls= it (announcing the expanded region it owns). Sanitize the flow id
      // to a valid token; the id only needs to be stable + unique per flow within the page.
      function inlineWrapId(flowId) {
        return "inline-flow-" + String(flowId).replace(/[^A-Za-z0-9_-]/g, "_");
      }
      // Cache the scope-grid geometry; file/detail layouts stay per-render because they
      // depend on expanded files and the selected inline flow.
      const layoutCache = new Map();
      // User-adjusted positions for canvas blocks. The automatic layout gives the first
      // readable flowchart; drag lets users refine spacing on the codebase they inspect.
      const manualScopePositions = new Map();
      const manualFlowPositions = new Map();
      let currentRouteEdgeRecords = new Map();

      function layoutWidthBucket() {
        const width = (canvasEl && canvasEl.clientWidth) || 1000;
        return Math.max(1, Math.round(width / 80));
      }

      // --- Data precompute (cached on LC) ------------------------------------------

      // scope -> [flowId]. Provided by payload (inferred top-level dirs when no
      // [logicchart.scopes]); ALWAYS present, covers 0/1/many. Used directly for
      // membership + super-node sizing so canvas grouping == tree grouping.
      const scopeFlows = model.scopes || {};

      // [{from, to, count}] cross-scope aggregate. Prefer payload.scope_edges; fall
      // back to a pure-data JS derivation so canvas.js works before/without the Python
      // change. Both attribute a multi-scope flow's calls to EACH membership.
      function deriveScopeEdges() {
        const flowScope = new Map(); // flowId -> [scope]
        Object.keys(scopeFlows).forEach(scope => {
          (scopeFlows[scope] || []).forEach(id => {
            const list = flowScope.get(id) || [];
            list.push(scope);
            flowScope.set(id, list);
          });
        });
        const counts = new Map(); // "from\0to" -> count
        flowScope.forEach((srcScopes, flowId) => {
          const flow = byId.get(flowId);
          if (!flow) return;
          (flow.calls || []).forEach(target => {
            if (!byId.has(target)) return; // guard: unresolved/external target.
            const dstScopes = flowScope.get(target) || [];
            srcScopes.forEach(src => {
              dstScopes.forEach(dst => {
                if (src === dst) return; // drop self-scope calls at L0.
                const key = src + "\0" + dst;
                counts.set(key, (counts.get(key) || 0) + 1);
              });
            });
          });
        });
        const edges = [];
        counts.forEach((count, key) => {
          const parts = key.split("\0");
          edges.push({ from: parts[0], to: parts[1], count });
        });
        return edges;
      }

      const scopeEdges = Array.isArray(model.scope_edges)
        ? model.scope_edges
        : deriveScopeEdges();

      const filePaths = new Set();
      byId.forEach(flow => {
        const path = flow.location && flow.location.path;
        if (path) filePaths.add(path);
      });

      // flowId -> [scope], derived from the payload's scope index (the same membership
      // the canvas groups by, which already excludes test flows). Lets a flow opened
      // from the tree or a #flow= deep link recover its scope crumb.
      const scopeOfFlowIndex = new Map();
      Object.keys(scopeFlows)
        .sort()
        .forEach(scope => {
          (scopeFlows[scope] || []).forEach(id => {
            const list = scopeOfFlowIndex.get(id) || [];
            list.push(scope);
            scopeOfFlowIndex.set(id, list);
          });
        });

      // The scope a flow belongs to for breadcrumb purposes. Prefer the payload index;
      // fall back to flow.metadata.scope, then to the inferred top-level dir (mirroring
      // build_scope_index) so a flow always resolves to a deterministic FIRST scope.
      function scopeOfFlow(flow) {
        if (!flow) return null;
        const fromIndex = scopeOfFlowIndex.get(flow.id);
        if (fromIndex && fromIndex.length) return fromIndex[0];
        const declared = flow.metadata && flow.metadata.scope;
        if (Array.isArray(declared) && declared.length) {
          return [...declared].sort()[0];
        }
        const path = (flow.location && flow.location.path) || "";
        const parts = path.split("/").filter(Boolean);
        return parts.length ? parts[0] : path || null;
      }

      function scopeOfPath(path) {
        const value = String(path || "");
        if (!value) return null;
        if (Object.prototype.hasOwnProperty.call(scopeFlows, value)) return value;
        const names = Object.keys(scopeFlows).sort();
        const prefixScope = names.find(scope => value === scope || value.startsWith(scope + "/"));
        if (prefixScope) return prefixScope;

        // Declared scopes can have logical names that do not mirror filesystem prefixes.
        // For folder/file deep links, recover the strongest owning scope from flows under
        // that path instead of assuming `scopeName/child` is always the path shape.
        const candidates = new Map();
        byId.forEach(flow => {
          const flowPath = flow.location && flow.location.path;
          if (!flowPath || !(flowPath === value || flowPath.startsWith(value + "/"))) {
            return;
          }
          const scopes = scopeOfFlowIndex.get(flow.id) || [scopeOfFlow(flow)].filter(Boolean);
          scopes.forEach(scope => {
            if (Object.prototype.hasOwnProperty.call(scopeFlows, scope)) {
              candidates.set(scope, (candidates.get(scope) || 0) + 1);
            }
          });
        });
        return (
          [...candidates.entries()].sort(
            (a, b) => b[1] - a[1] || a[0].localeCompare(b[0])
          )[0]?.[0] || null
        );
      }

      // --- Geometry helpers --------------------------------------------------------

      function clamp(min, value, max) {
        return Math.max(min, Math.min(max, value));
      }

      function svgEl(tag) {
        return document.createElementNS("http://www.w3.org/2000/svg", tag);
      }

      function cssEscape(value) {
        const text = String(value);
        if (window.CSS && typeof window.CSS.escape === "function") {
          return window.CSS.escape(text);
        }
        return text
          .replace(/\\/g, "\\\\")
          .replace(/"/g, "\\\"")
          .replace(/\n/g, "\\A ")
          .replace(/\r/g, "\\D ");
      }

      function setCanvasLevel(level) {
        if (LC.setCanvasLevel) LC.setCanvasLevel(level);
        else {
          const value = String(level);
          canvasEl.setAttribute("data-level", value);
          document.body.dataset.canvasLevel = value;
        }
      }

      function superNodeHeight(count) {
        return clamp(SCOPE_H_MIN, SCOPE_H_MIN + 6 * Math.sqrt(count), SCOPE_H_MAX);
      }

      function splitLongToken(token, width) {
        let rest = String(token);
        const chunks = [];
        while (rest.length > width) {
          const windowText = rest.slice(0, width);
          let cut = -1;
          [".", "::", "/", "_", "-"].forEach(delimiter => {
            const index = windowText.lastIndexOf(delimiter);
            if (index > cut) cut = index + delimiter.length;
          });
          if (cut < Math.floor(width * 0.45)) cut = width;
          chunks.push(rest.slice(0, cut));
          rest = rest.slice(cut);
        }
        if (rest) chunks.push(rest);
        return chunks;
      }

      function labelLines(value, width) {
        const words = String(value)
          .split(/\s+/)
          .flatMap(word =>
            word.length > width ? splitLongToken(word, width) : [word]
          );
        const lines = [];
        let current = "";
        words.forEach(word => {
          if (!current || (current + " " + word).length <= width) {
            current = current ? current + " " + word : word;
          } else {
            lines.push(current);
            current = word;
          }
        });
        if (current) lines.push(current);
        return lines;
      }

      // Wrap a label to at most `max` lines of roughly `width` chars (mirrors shell.js).
      function wrapLabel(value, width, max) {
        const lines = labelLines(value, width);
        return lines.slice(0, max);
      }

      // True when wrapLabel dropped content: more lines than `max`, so the rendered
      // label is missing the overflow. Lets callers attach a <title> to recover it.
      function isTruncated(value, width, max) {
        const lines = labelLines(value, width);
        return lines.length > max;
      }

      // Attach a hover/long-press tooltip with the full text to an SVG element.
      function addTitle(target, text) {
        const title = svgEl("title");
        title.textContent = text;
        target.appendChild(title);
      }

      // Lightly-curved cubic between node CENTERS, clipped to each node's border using
      // its known {w,h}; arrow sits on the rect edge, not the center. `curveOffset`
      // pushes the control points perpendicular to the segment so parallel edges fan
      // out. General over node size + orientation (unlike shell.js's edgeGeometry,
      // which hardcodes the +43/-43 flow-node half-height and a top-to-bottom S-curve).
      function straightEdge(a, b, curveOffset) {
        curveOffset = curveOffset || 0;
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len = Math.hypot(dx, dy) || 1;
        const ux = dx / len;
        const uy = dy / len;

        // Clip the endpoints to each node's rectangular border along the segment.
        const start = clipToRect(a, ux, uy);
        const end = clipToRect(b, -ux, -uy);

        // Perpendicular offset for the control points (so overlapping lines separate).
        const px = -uy * curveOffset;
        const py = ux * curveOffset;
        const c1x = start.x + dx * 0.3 + px;
        const c1y = start.y + dy * 0.3 + py;
        const c2x = start.x + dx * 0.7 + px;
        const c2y = start.y + dy * 0.7 + py;
        return {
          d: `M ${start.x} ${start.y} C ${c1x} ${c1y}, ${c2x} ${c2y}, ${end.x} ${end.y}`,
          labelX: (start.x + end.x) / 2 + px,
          labelY: (start.y + end.y) / 2 + py,
        };
      }

      // Point on `node`'s rect border in direction (ux,uy) from its center.
      function clipToRect(node, ux, uy) {
        const hw = (node.w || FLOW_W) / 2;
        const hh = (node.h || FLOW_H) / 2;
        // Scale to hit the nearer of the vertical/horizontal edges.
        const tx = ux !== 0 ? hw / Math.abs(ux) : Infinity;
        const ty = uy !== 0 ? hh / Math.abs(uy) : Infinity;
        const t = Math.min(tx, ty);
        return { x: node.x + ux * t, y: node.y + uy * t };
      }

      function defsBlock() {
        const defs = svgEl("defs");
        // Neutral black shadow (not the old hardcoded navy #1e2e4e, which read as a
        // blue tint in light mode); low opacity keeps it subtle in both themes.
        defs.innerHTML = `
          <filter id="nodeShadow" x="-30%" y="-30%" width="160%" height="180%">
            <feDropShadow dx="0" dy="8" stdDeviation="8" flood-color="#000" flood-opacity=".10"/>
          </filter>
          <filter id="nodeLift" x="-45%" y="-45%" width="190%" height="210%">
            <feDropShadow dx="0" dy="16" stdDeviation="14" flood-color="#000" flood-opacity=".22"/>
          </filter>
          <marker id="arrow" markerWidth="6.5" markerHeight="6.5" refX="5.7" refY="3.25" viewBox="0 0 6.5 6.5" orient="auto">
            <path class="arrow" d="M0,0 L6.5,3.25 L0,6.5 z"></path>
          </marker>
          <marker id="arrowFocus" markerWidth="6.5" markerHeight="6.5" refX="5.7" refY="3.25" viewBox="0 0 6.5 6.5" orient="auto">
            <path class="arrow-focus" d="M0,0 L6.5,3.25 L0,6.5 z"></path>
          </marker>`;
        return defs;
      }

      // ViewBox fit over a {minX,maxX,minY,maxY} bounds, same math renderFlow uses.
      function fitBounds(bounds) {
        const padding = 120;
        LC.setView({
          x: bounds.minX - padding,
          y: bounds.minY - padding,
          width: Math.max(760, bounds.maxX - bounds.minX + padding * 2),
          height: Math.max(560, bounds.maxY - bounds.minY + padding * 2),
        });
      }

      // Keep the host flow node on-screen when a flow is inline-expanded, WITHOUT changing
      // the zoom (no refit): the surrounding L1 context must stay at its readable scale.
      // Pans the shared `view` by the minimum amount so the node's rect is inside the
      // viewport; if it is already visible, leaves the view untouched (no jump). The user
      // pans/zooms to reach a taller-than-viewport sub-graph -- this only guarantees the
      // anchor node itself does not end up off the edge after a re-render.
      function ensureNodeVisible(node) {
        if (!node || !LC.getView || !LC.setView) return;
        const view = LC.getView();
        if (!view || !view.width || !view.height) return;
        const margin = 60;
        const hw = (node.w || FLOW_W) / 2;
        const hh = (node.h || FLOW_H) / 2;
        const left = node.x - hw - margin;
        const right = node.x + hw + margin;
        const top = node.y - hh - margin;
        const bottom = node.y + hh + margin;
        let x = view.x;
        let y = view.y;
        if (left < x) x = left;
        else if (right > x + view.width) x = right - view.width;
        if (top < y) y = top;
        else if (bottom > y + view.height) y = bottom - view.height;
        if (x !== view.x || y !== view.y) {
          LC.setView({ x, y, width: view.width, height: view.height });
        }
      }

      // Re-focus a host flow node by id after a renderCanvas (which replaceChildren()s the
      // SVG, destroying the previously-focused <g> and dropping focus to <body>). Keeps the
      // keyboard position on the flow the user just toggled. Safe no-op if the node is not
      // in the DOM (e.g. its file collapsed). CSS.escape guards ids with odd characters.
      function focusFlowNode(id) {
        if (!id) return;
        const node = svg.querySelector(
          '.flow-node[data-flow-id="' + cssEscape(id) + '"]'
        );
        if (node && typeof node.focus === "function") node.focus();
      }

      // Update the page header (#flowTitle / #flowKind) for a flow. shell.js's selectFlow
      // sets these for tree clicks, but a flow node clicked directly on the canvas routes
      // through expandFlowInline without going through selectFlow, so mirror it here.
      function setFlowHeader(flow) {
        if (!flow) return;
        setLevelHeader(
          flow.name,
          `${flow.entry_kind} · ${flow.language} · ${flow.framework}`
        );
      }

      function setLevelHeader(title, kind) {
        const titleEl = document.getElementById("flowTitle");
        const kindEl = document.getElementById("flowKind");
        if (titleEl) titleEl.textContent = title;
        if (kindEl) kindEl.textContent = kind;
      }

      function pathInActiveScope(path) {
        const value = String(path || "");
        const scope = canvasState.expandedScope;
        if (!scope) return value;
        const prefix = scope + "/";
        return value.startsWith(prefix) ? value.slice(prefix.length) : value;
      }

      function shortPathLabel(path) {
        const segments = pathInActiveScope(path).split("/").filter(Boolean);
        if (segments.length <= 2) return segments.join("/") || String(path || "");
        return segments.slice(-2).join("/");
      }

      function flowCountForPath(path) {
        let count = 0;
        byId.forEach(flow => {
          const p = flow.location && flow.location.path;
          if (p && (p === path || p.startsWith(path + "/"))) count += 1;
        });
        return count;
      }

      function pathKind(path) {
        return filePaths.has(path) ? "file" : "folder";
      }

      function pathContains(parent, child) {
        return !!(
          parent &&
          child &&
          (child === parent || String(child).startsWith(String(parent) + "/"))
        );
      }

      function pathTouchesActive(path) {
        const selected = canvasState.selectedPath;
        return !!(
          selected &&
          (pathContains(selected, path) || pathContains(path, selected))
        );
      }

      function scopeStats(name) {
        const ids = scopeFlows[name] || [];
        const languages = new Set();
        let review = 0;
        ids.forEach(id => {
          const flow = byId.get(id);
          if (flow && flow.language) languages.add(flow.language);
          review += (findingsByFlow.get(id) || []).length;
        });
        return { languages: languages.size, review };
      }

      // Wrapped-grid column count for L0 super-nodes.
      function gridCols(count, cellW) {
        const containerW = (canvasEl && canvasEl.clientWidth) || 1000;
        const fitting = Math.max(1, Math.floor(containerW / (cellW + GAP_X)));
        return clamp(1, Math.round(Math.sqrt(count) * 1.3), fitting);
      }

      // --- L0 layout: scopes as a wrapped grid of super-nodes ----------------------

      function layoutL0(names) {
        const cacheKey = "L0:" + layoutWidthBucket() + ":" + names.join("|");
        const cached = layoutCache.get(cacheKey);
        let nodePos;
        if (cached) {
          nodePos = cached.nodePos;
        } else {
          nodePos = new Map();
          const cols = gridCols(names.length, SCOPE_W);
          const heights = names.map(name => superNodeHeight((scopeFlows[name] || []).length));
          const rowH = Math.max(SCOPE_H_MIN, ...heights);
          names.forEach((name, i) => {
            const col = i % cols;
            const row = Math.floor(i / cols);
            const cx = col * (SCOPE_W + GAP_X) + SCOPE_W / 2;
            const cy = row * (rowH + GAP_Y) + rowH / 2;
            const manual = manualScopePositions.get(name);
            nodePos.set(name, {
              x: manual ? manual.x : cx,
              y: manual ? manual.y : cy,
              w: SCOPE_W,
              h: superNodeHeight((scopeFlows[name] || []).length),
              count: (scopeFlows[name] || []).length,
            });
          });
          layoutCache.set(cacheKey, { nodePos });
        }
        return { nodePos, bounds: boundsOf([...nodePos.values()]) };
      }

      function boundsOf(nodes) {
        if (!nodes.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
        let minX = Infinity;
        let maxX = -Infinity;
        let minY = Infinity;
        let maxY = -Infinity;
        nodes.forEach(n => {
          minX = Math.min(minX, n.x - (n.w || FLOW_W) / 2);
          maxX = Math.max(maxX, n.x + (n.w || FLOW_W) / 2);
          minY = Math.min(minY, n.y - (n.h || FLOW_H) / 2);
          maxY = Math.max(maxY, n.y + (n.h || FLOW_H) / 2);
        });
        return { minX, maxX, minY, maxY };
      }

      function offsetBounds(bounds, dx, dy) {
        return {
          minX: bounds.minX + dx,
          maxX: bounds.maxX + dx,
          minY: bounds.minY + dy,
          maxY: bounds.maxY + dy,
        };
      }

      function mergeBounds(boundsList) {
        const valid = boundsList.filter(Boolean);
        if (!valid.length) return { minX: 0, maxX: 0, minY: 0, maxY: 0 };
        return {
          minX: Math.min(...valid.map(bounds => bounds.minX)),
          maxX: Math.max(...valid.map(bounds => bounds.maxX)),
          minY: Math.min(...valid.map(bounds => bounds.minY)),
          maxY: Math.max(...valid.map(bounds => bounds.maxY)),
        };
      }

      function offsetLayout(layout, dx, dy) {
        layout.flowPos.forEach(pos => {
          pos.x += dx;
          pos.y += dy;
          pos.layoutOffsetX = (pos.layoutOffsetX || 0) + dx;
          pos.layoutOffsetY = (pos.layoutOffsetY || 0) + dy;
        });
        layout.flowRows.forEach(row => {
          row.x += dx;
          row.y += dy;
        });
        layout.inlineAnchors.forEach(anchor => {
          anchor.x += dx;
          anchor.y += dy;
          anchor.bounds = offsetBounds(anchor.bounds, dx, dy);
        });
        if (layout.inlineBounds) layout.inlineBounds = offsetBounds(layout.inlineBounds, dx, dy);
        layout.bounds = offsetBounds(layout.bounds, dx, dy);
        return layout;
      }

      // --- L1 detail layout: progressive entrypoint/call graph ---------------------

      function flowInScope(flow, scope) {
        return (scopeOfFlowIndex.get(flow.id) || [scopeOfFlow(flow)])
          .filter(Boolean)
          .includes(scope);
      }

      function nonTestScopeFlows(scope) {
        return (scopeFlows[scope] || [])
          .map(id => byId.get(id))
          .filter(Boolean);
      }

      function directCallTargets(flow) {
        return (flow.calls || [])
          .map(id => byId.get(id))
          .filter(Boolean);
      }

      function entryFlowsForScope(scope) {
        const flows = nonTestScopeFlows(scope);
        const ids = new Set(flows.map(flow => flow.id));
        const entries = flows.filter(flow => flow.is_entrypoint);
        const rootEntries = entries.filter(flow =>
          !(flow.called_by || []).some(source => ids.has(source))
        );
        if (rootEntries.length) return sortFlows(rootEntries);
        if (entries.length) return sortFlows(entries);
        const roots = flows.filter(flow =>
          !(flow.called_by || []).some(source => ids.has(source))
        );
        return sortFlows(roots.length ? roots : flows);
      }

      function pathMatchesFocus(flow) {
        const path = flow.location && flow.location.path;
        const selected = canvasState.selectedPath;
        return !!(
          selected &&
          path &&
          (pathContains(selected, path) || pathContains(path, selected))
        );
      }

      function focusedPathFlows(scope) {
        if (canvasState.selectedFlowId || canvasState.routeFlowIds.length) return [];
        if (!canvasState.selectedPath) return [];
        return sortFlows(
          nonTestScopeFlows(scope).filter(pathMatchesFocus)
        );
      }

      function routeContains(id) {
        return canvasState.routeFlowIds.includes(id);
      }

      function normalizeRoute(scope) {
        const seen = new Set();
        canvasState.routeFlowIds = canvasState.routeFlowIds.filter(id => {
          const flow = byId.get(id);
          if (!flow || seen.has(id)) return false;
          seen.add(id);
          return !scope || flowInScope(flow, scope) || routeContains(id);
        });
        if (
          canvasState.expandedFlow &&
          !canvasState.routeFlowIds.includes(canvasState.expandedFlow)
        ) {
          canvasState.routeFlowIds.push(canvasState.expandedFlow);
        }
        canvasState.expandedFlowIds.forEach(id => {
          if (!canvasState.routeFlowIds.includes(id)) {
            canvasState.routeFlowIds.push(id);
          }
        });
      }

      function appendUnique(list, flow) {
        if (!flow || list.some(item => item.id === flow.id)) return;
        list.push(flow);
      }

      function buildProgressiveLayers(scope) {
        normalizeRoute(scope);
        const root = entryFlowsForScope(scope);
        focusedPathFlows(scope).forEach(flow => appendUnique(root, flow));
        const firstRouteFlow = canvasState.routeFlowIds[0]
          ? byId.get(canvasState.routeFlowIds[0])
          : null;
        appendUnique(root, firstRouteFlow);

        const layers = [sortFlows(root)];
        const seen = new Set(layers[0].map(flow => flow.id));
        const route = canvasState.routeFlowIds
          .map(id => byId.get(id))
          .filter(Boolean);

        route.forEach(flow => {
          if (!seen.has(flow.id)) {
            layers.push([flow]);
            seen.add(flow.id);
          }
          const targets = directCallTargets(flow).filter(target => !seen.has(target.id));
          if (targets.length) {
            const sorted = sortFlows(targets);
            sorted.forEach(target => seen.add(target.id));
            layers.push(sorted);
          }
        });

        return layers.filter(layer => layer.length);
      }

      function rowLabelFor(index) {
        if (index === 0) return "entrypoints";
        return `unlocked calls ${index}`;
      }

      function rowWidth(count) {
        return Math.max(FLOW_W, count * FLOW_W + Math.max(0, count - 1) * GAP_X);
      }

      function rowWidthForLayer(layer, reserveWidths) {
        const reserved = layer.reduce(
          (sum, flow) => sum + (reserveWidths.get(flow.id) || FLOW_W),
          0
        );
        return Math.max(FLOW_W, reserved + Math.max(0, layer.length - 1) * GAP_X);
      }

      function layoutL1(scope) {
        const layers = buildProgressiveLayers(scope);
        const flowPos = new Map();
        const flowRows = [];
        const visibleIds = new Set();
        const allNodes = [];
        const routeEdges = [];
        const expandedMeasures = new Map();
        const reserveWidths = new Map();
        layers.forEach(layer => {
          layer.forEach(flow => {
            const measure =
              canvasState.expandedFlowIds.has(flow.id) &&
              flow.nodes &&
              flow.nodes.length &&
              LC.measureFlow
                ? LC.measureFlow(flow, { omitEntry: true })
                : null;
            if (measure) expandedMeasures.set(flow.id, measure);
            reserveWidths.set(
              flow.id,
              Math.max(FLOW_W, measure ? measure.width + DECISION_PAD * 2 : FLOW_W)
            );
          });
        });
        const maxWidth = Math.max(
          ...layers.map(layer => rowWidthForLayer(layer, reserveWidths)),
          FLOW_W
        );
        const inlineAnchors = [];

        let y = 0;
        layers.forEach((layer, layerIndex) => {
          const width = rowWidthForLayer(layer, reserveWidths);
          let cursorX = (maxWidth - width) / 2;
          flowRows.push({
            x: maxWidth / 2,
            y,
            w: Math.max(width, FLOW_W),
            h: FLOW_H + FLOW_CHIP_Y * 2,
            label: rowLabelFor(layerIndex),
          });

          layer.forEach((flow, index) => {
            const reserveW = reserveWidths.get(flow.id) || FLOW_W;
            const x = cursorX + reserveW / 2;
            cursorX += reserveW + GAP_X;
            const pos = { x, y, w: FLOW_W, h: FLOW_H, layer: layerIndex };
            const manual = manualFlowPositions.get(flow.id);
            if (manual) {
              pos.x = manual.x;
              pos.y = manual.y;
            }
            flowPos.set(flow.id, pos);
            visibleIds.add(flow.id);
            allNodes.push(pos);
          });

          const expandedInRow = layer
            .filter(flow => expandedMeasures.has(flow.id))
            .map(flow => ({
              flow,
              measure: expandedMeasures.get(flow.id),
            }))
            .filter(item => item.measure);

          if (expandedInRow.length) {
            let rowExtra = 0;
            let bandTop = y + FLOW_H / 2 + FLOW_CHIP_Y;
            expandedInRow.forEach((item, index) => {
              if (index > 0) {
                bandTop += FLOW_ROW_GAP;
                rowExtra += FLOW_ROW_GAP;
              }
              const node = flowPos.get(item.flow.id);
              const reservedW = item.measure.width + DECISION_PAD * 2;
              const reservedH = item.measure.height + DECISION_PAD * 2;
              const anchor = {
                x: node.x - (item.measure.minX + item.measure.maxX) / 2,
                y: bandTop + DECISION_PAD - item.measure.minY,
                flowId: item.flow.id,
                bounds: {
                  minX: node.x - reservedW / 2,
                  maxX: node.x + reservedW / 2,
                  minY: bandTop,
                  maxY: bandTop + reservedH,
                },
              };
              inlineAnchors.push(anchor);
              allNodes.push({
                x: (anchor.bounds.minX + anchor.bounds.maxX) / 2,
                y: (anchor.bounds.minY + anchor.bounds.maxY) / 2,
                w: anchor.bounds.maxX - anchor.bounds.minX,
                h: anchor.bounds.maxY - anchor.bounds.minY,
              });
              bandTop += reservedH;
              rowExtra += reservedH;
            });
            y += FLOW_H + FLOW_ROW_GAP + rowExtra;
          } else {
            y += FLOW_H + FLOW_LAYER_GAP;
          }
        });

        visibleIds.forEach(id => {
          const flow = byId.get(id);
          const from = flowPos.get(id);
          if (!flow || !from) return;
          directCallTargets(flow).forEach(target => {
            const to = flowPos.get(target.id);
            if (!to) return;
            routeEdges.push({ source: id, target: target.id, from, to, label: "calls" });
          });
        });

        return {
          flowRows,
          flowPos,
          visibleIds,
          routeEdges,
          inlineAnchors,
          entryFlowIds: layers[0] ? layers[0].map(flow => flow.id) : [],
          inlineBounds: inlineAnchors.length
            ? mergeBounds(inlineAnchors.map(anchor => anchor.bounds))
            : null,
          bounds: boundsOf(allNodes),
        };
      }

      function layoutExpandedCodebase(scope) {
        const names = Object.keys(scopeFlows).sort();
        const l0 = layoutL0(names);
        const detail = layoutL1(scope);
        const scopeNode = l0.nodePos.get(scope);
        if (scopeNode) {
          const detailCenter = (detail.bounds.minX + detail.bounds.maxX) / 2;
          const detailTop = detail.bounds.minY;
          const dx = scopeNode.x - detailCenter;
          const targetTop = Math.max(
            scopeNode.y + scopeNode.h / 2 + GAP_Y + 35,
            l0.bounds.maxY + GAP_Y
          );
          const dy = targetTop - detailTop;
          offsetLayout(detail, dx, dy);
        }
        return {
          names,
          nodePos: l0.nodePos,
          scopeBounds: l0.bounds,
          detail,
          bounds: mergeBounds([l0.bounds, detail.bounds]),
        };
      }

      // --- Node builders -----------------------------------------------------------

      function makeSuperNode(name, count, pos, opts) {
        opts = opts || {};
        const stats = scopeStats(name);
        const group = svgEl("g");
        group.setAttribute(
          "class",
          "node entry scope-node movable" +
            (opts.expanded ? " expanded" : "") +
            (opts.dimmed ? " dimmed" : "") +
            (stats.review ? " has-finding" : "")
        );
        group.setAttribute("data-scope", name);
        group.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-label", `scope ${name}: ${count} flows`);

        const rect = svgEl("rect");
        rect.setAttribute("class", "shape");
        rect.setAttribute("x", String(-pos.w / 2));
        rect.setAttribute("y", String(-pos.h / 2));
        rect.setAttribute("width", String(pos.w));
        rect.setAttribute("height", String(pos.h));
        rect.setAttribute("rx", "32");
        group.appendChild(rect);

        const nameLines = wrapLabel(name, 18, 2);
        // Recover the full scope name on hover when wrapLabel dropped overflow.
        if (isTruncated(name, 18, 2)) addTitle(group, name);
        nameLines.forEach((line, index) => {
          const text = svgEl("text");
          text.setAttribute("text-anchor", "middle");
          text.setAttribute(
            "y",
            String((index - (nameLines.length - 1) / 2) * 20 - 8)
          );
          text.textContent = line;
          group.appendChild(text);
        });
        const meta = svgEl("text");
        meta.setAttribute("class", "meta");
        meta.setAttribute("text-anchor", "middle");
        meta.setAttribute("y", String(pos.h / 2 - (stats.review ? 28 : 14)));
        const langText = `${stats.languages} lang${stats.languages === 1 ? "" : "s"}`;
        meta.textContent = `${count} flow${count === 1 ? "" : "s"} · ${langText}`;
        group.appendChild(meta);
        if (stats.review) {
          const review = svgEl("text");
          review.setAttribute("class", "meta");
          review.setAttribute("text-anchor", "middle");
          review.setAttribute("y", String(pos.h / 2 - 11));
          review.textContent = `${stats.review} review`;
          group.appendChild(review);
        }

        const activate = () => expandScope(name);
        let scopeDrag = null;
        group.addEventListener("pointerdown", event => {
          if (event.button !== 0) return;
          event.stopPropagation();
          clearProgressiveLinkHighlight();
          const currentView = LC.getView ? LC.getView() : null;
          scopeDrag = {
            x: event.clientX,
            y: event.clientY,
            ox: pos.x,
            oy: pos.y,
            moved: 0,
            scaleX: currentView && svg.clientWidth ? currentView.width / svg.clientWidth : 1,
            scaleY: currentView && svg.clientHeight ? currentView.height / svg.clientHeight : 1,
          };
          group.classList.add("dragging");
          group.setPointerCapture(event.pointerId);
        });
        group.addEventListener("pointermove", event => {
          if (!scopeDrag) return;
          const dx = (event.clientX - scopeDrag.x) * scopeDrag.scaleX;
          const dy = (event.clientY - scopeDrag.y) * scopeDrag.scaleY;
          scopeDrag.moved = Math.max(scopeDrag.moved, Math.abs(dx) + Math.abs(dy));
          pos.x = scopeDrag.ox + dx;
          pos.y = scopeDrag.oy + dy;
          group.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
        });
        const finishScopeDrag = event => {
          if (!scopeDrag) return;
          group.classList.remove("dragging");
          try { group.releasePointerCapture(event.pointerId); } catch (_) {}
          if (scopeDrag.moved < 4 && event.type === "pointerup") {
            activate();
          } else {
            manualScopePositions.set(name, { x: pos.x, y: pos.y });
            layoutCache.clear();
            renderCanvas();
          }
          scopeDrag = null;
        };
        group.addEventListener("pointerup", finishScopeDrag);
        group.addEventListener("pointercancel", finishScopeDrag);
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          }
        });
        return group;
      }

      function makeFlowNode(flow, pos) {
        const group = svgEl("g");
        const isEntry = !!flow.is_entrypoint;
        const isExpanded = canvasState.expandedFlowIds.has(flow.id);
        const isRoute = routeContains(flow.id);
        const callCount = directCallTargets(flow).length;
        const decisionCount = (flow.nodes || []).filter(node => node.kind === "decision").length;
        const sourceLabel = `${pathInActiveScope(flow.location.path)}:${flow.location.start_line}`;
        group.setAttribute(
          "class",
          "node flow-node " +
            (isEntry ? "entry" : "action subflow") +
            (findingFlowIds.has(flow.id) ? " has-finding" : "") +
            (flow.id === canvasState.selectedFlowId ? " selected" : "") +
            (pathTouchesActive(flow.location && flow.location.path) ? " active-area" : "") +
            (isRoute ? " route-flow" : "") +
            (isExpanded ? " flow-open" : "") +
            " movable"
        );
        group.setAttribute("data-flow-id", flow.id);
        group.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        // The node toggles its inline decision sub-graph, so expose expanded state and,
        // while expanded, point aria-controls at the sub-graph wrap it owns.
        group.setAttribute("aria-expanded", isExpanded ? "true" : "false");
        if (isExpanded) group.setAttribute("aria-controls", inlineWrapId(flow.id));
        group.setAttribute(
          "aria-label",
          `flow: ${flow.name}, ${decisionCount} decisions, ${callCount} downstream calls, ${isExpanded ? "expanded" : "collapsed"}`
        );

        const rect = svgEl("rect");
        rect.setAttribute("class", "shape");
        rect.setAttribute("x", String(-FLOW_W / 2));
        rect.setAttribute("y", String(-FLOW_H / 2));
        rect.setAttribute("width", String(FLOW_W));
        rect.setAttribute("height", String(FLOW_H));
        rect.setAttribute("rx", isEntry ? "32" : "12");
        group.appendChild(rect);

        const lines = wrapLabel(flow.name, 28, 2);
        // Recover the full flow name on hover when wrapLabel dropped overflow.
        if (isTruncated(flow.name, 28, 2)) addTitle(group, flow.name);
        lines.forEach((line, index) => {
          const text = svgEl("text");
          text.setAttribute("text-anchor", "middle");
          text.setAttribute("y", String((index - (lines.length - 1) / 2) * 16 - 4));
          text.textContent = line;
          group.appendChild(text);
        });
        const meta = svgEl("text");
        meta.setAttribute("class", "meta");
        meta.setAttribute("text-anchor", "middle");
        meta.setAttribute("y", String(FLOW_H / 2 - 7));
        meta.textContent = `${flow.entry_kind || "flow"} · ${flow.language || "unknown"}`;
        group.appendChild(meta);

        const source = svgEl("text");
        source.setAttribute("class", "flow-source-tag");
        source.setAttribute("text-anchor", "middle");
        source.setAttribute("y", String(FLOW_H / 2 + 21));
        source.textContent = sourceLabel;
        const sourceTitle = svgEl("title");
        sourceTitle.textContent = sourceLabel;
        source.appendChild(sourceTitle);
        group.appendChild(source);

        if (callCount || decisionCount) {
          const badgeText = callCount
            ? `+ ${callCount} downstream`
            : `${decisionCount} decision${decisionCount === 1 ? "" : "s"}`;
          const badgeWidth = Math.max(80, badgeText.length * 6 + 20);
          const badge = svgEl("g");
          badge.setAttribute("class", "flow-expand-pill");
          badge.setAttribute(
            "transform",
            `translate(${FLOW_W / 2 - badgeWidth / 2 - 8} ${-FLOW_H / 2 - 14})`
          );
          const badgeBg = svgEl("rect");
          badgeBg.setAttribute("x", String(-badgeWidth / 2));
          badgeBg.setAttribute("y", "-10");
          badgeBg.setAttribute("width", String(badgeWidth));
          badgeBg.setAttribute("height", "20");
          badgeBg.setAttribute("rx", "10");
          const badgeLabel = svgEl("text");
          badgeLabel.setAttribute("text-anchor", "middle");
          badgeLabel.setAttribute("y", "4");
          badgeLabel.textContent = badgeText;
          badge.append(badgeBg, badgeLabel);
          group.appendChild(badge);
        }

        // Click / Enter / Space unlocks this flow in the route and, when it has decisions,
        // unfolds the decision sub-graph in place. Pointer drag moves the block freely;
        // a short press below the movement threshold remains a click.
        const toggle = () => toggleFlow(flow.id);
        let flowDrag = null;
        group.addEventListener("pointerdown", event => {
          if (event.button !== 0) return;
          event.stopPropagation();
          clearProgressiveLinkHighlight();
          const currentView = LC.getView ? LC.getView() : null;
          flowDrag = {
            x: event.clientX,
            y: event.clientY,
            ox: pos.x,
            oy: pos.y,
            moved: 0,
            scaleX: currentView && svg.clientWidth ? currentView.width / svg.clientWidth : 1,
            scaleY: currentView && svg.clientHeight ? currentView.height / svg.clientHeight : 1,
          };
          group.classList.add("dragging");
          group.setPointerCapture(event.pointerId);
        });
        group.addEventListener("pointermove", event => {
          if (!flowDrag) return;
          const dx = (event.clientX - flowDrag.x) * flowDrag.scaleX;
          const dy = (event.clientY - flowDrag.y) * flowDrag.scaleY;
          flowDrag.moved = Math.max(flowDrag.moved, Math.abs(dx) + Math.abs(dy));
          pos.x = flowDrag.ox + dx;
          pos.y = flowDrag.oy + dy;
          group.setAttribute("transform", `translate(${pos.x} ${pos.y})`);
          rerouteFlowNodeEdges(flow.id);
        });
        const finishDrag = event => {
          if (!flowDrag) return;
          group.classList.remove("dragging");
          try { group.releasePointerCapture(event.pointerId); } catch (_) {}
          if (flowDrag.moved < 4 && event.type === "pointerup") {
            toggle();
          } else {
            manualFlowPositions.set(flow.id, {
              x: pos.x - (pos.layoutOffsetX || 0),
              y: pos.y - (pos.layoutOffsetY || 0),
            });
            renderCanvas();
            focusFlowNode(flow.id);
          }
          flowDrag = null;
        };
        group.addEventListener("pointerup", finishDrag);
        group.addEventListener("pointercancel", finishDrag);
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        });
        return group;
      }

      function edgePath(geometry, count) {
        const path = svgEl("path");
        path.setAttribute("class", "edge");
        path.setAttribute("d", geometry.d);
        if (count != null) {
          path.setAttribute("stroke-width", String(clamp(1, Math.log2(count + 1), 6)));
        }
        return path;
      }

      function edgeFocusPath(geometry) {
        const path = svgEl("path");
        path.setAttribute("class", "edge-focus");
        path.setAttribute("d", geometry.focusD || geometry.d);
        return path;
      }

      function bindEdgeActivationParts(group, activate) {
        if (!group || !activate) return;
        group.querySelectorAll("*").forEach(part => {
          part.addEventListener("click", activate);
        });
      }

      function edgeHitPath(geometry, activate) {
        const hit = svgEl("g");
        hit.setAttribute("class", "edge-hit");
        setEdgeHitGeometry(hit, geometry, activate);
        return hit;
      }

      function setEdgeHitGeometry(hit, geometry, activate) {
        hit.replaceChildren();
        const points = geometry.points || [];
        const pad = 10;
        for (let index = 0; index < points.length - 1; index += 1) {
          const a = points[index];
          const b = points[index + 1];
          const rect = svgEl("rect");
          rect.setAttribute("class", "edge-hit-segment");
          rect.setAttribute("x", String(Math.min(a.x, b.x) - pad));
          rect.setAttribute("y", String(Math.min(a.y, b.y) - pad));
          rect.setAttribute("width", String(Math.max(Math.abs(a.x - b.x), 1) + pad * 2));
          rect.setAttribute("height", String(Math.max(Math.abs(a.y - b.y), 1) + pad * 2));
          rect.setAttribute("rx", "10");
          if (activate) rect.addEventListener("click", activate);
          hit.appendChild(rect);
        }
      }

      function clearProgressiveLinkHighlight(options) {
        if (!options || !options.preserveSelection) {
          canvasState.selectedRouteEdge = null;
        }
        svg.querySelectorAll(".node.edge-source, .node.edge-target").forEach(node => {
          node.classList.remove("edge-source", "edge-target");
        });
        svg.querySelectorAll(".node.dimmed").forEach(node => {
          node.classList.remove("dimmed");
        });
        svg.querySelectorAll(".edge.selected-link, .edge-hit.selected-link").forEach(edge => {
          edge.classList.remove("selected-link");
        });
        svg.querySelectorAll(".edge.dimmed, .edge.focus-hidden, .edge-hit.dimmed").forEach(edge => {
          edge.classList.remove("dimmed", "focus-hidden");
        });
        svg.querySelectorAll(".edge-focus.selected-link").forEach(edge => {
          edge.classList.remove("selected-link");
        });
        svg.querySelectorAll(".edge-label-wrap.selected-link, .edge-label-wrap.dimmed").forEach(label => {
          label.classList.remove("selected-link", "dimmed");
        });
      }

      function applyProgressiveLinkClasses(edge, path, label, hit, focusPath) {
        if (!edge || !path) return;
        clearProgressiveLinkHighlight({ preserveSelection: true });
        path.classList.add("focus-hidden");
        if (hit) hit.classList.add("selected-link");
        if (focusPath) focusPath.classList.add("selected-link");
        if (label) label.classList.add("selected-link");
        const related = new Set([edge.source, edge.target]);
        svg.querySelectorAll(".node").forEach(node => {
          const id = node.getAttribute("data-flow-id");
          node.classList.toggle("dimmed", !related.has(id));
        });
        svg.querySelectorAll(".edge").forEach(item => {
          item.classList.toggle("dimmed", item !== path);
        });
        svg.querySelectorAll(".edge-hit").forEach(item => {
          item.classList.toggle("dimmed", item !== hit);
        });
        svg.querySelectorAll(".edge-label-wrap").forEach(item => {
          item.classList.toggle("dimmed", item !== label);
        });
        const sourceNode = svg.querySelector(
          '.flow-node[data-flow-id="' + cssEscape(edge.source) + '"]'
        );
        const targetNode = svg.querySelector(
          '.flow-node[data-flow-id="' + cssEscape(edge.target) + '"]'
        );
        if (sourceNode) sourceNode.classList.add("edge-source");
        if (targetNode) targetNode.classList.add("edge-target");
      }

      function selectProgressiveLink(edge, path, label, hit, focusPath) {
        if (!edge || !path) return;
        canvasState.selectedRouteEdge = { kind: "progressive-call", source: edge.source, target: edge.target };
        applyProgressiveLinkClasses(edge, path, label, hit, focusPath);
        if (LC.clearHighlight) LC.clearHighlight();
        if (LC.openDetails) LC.openDetails();
        const flow = byId.get(edge.source);
        if (flow && LC.select) {
          LC.select({
            scope: canvasState.expandedScope,
            path: flow.location.path,
            flowId: flow.id,
            nodeId: null,
            findingId: null,
            edgeId: null,
          });
        }
      }

      function applyScopeEntryLinkClasses(edge, path, hit, focusPath) {
        if (!edge || !path) return;
        clearProgressiveLinkHighlight({ preserveSelection: true });
        path.classList.add("focus-hidden");
        if (hit) hit.classList.add("selected-link");
        if (focusPath) focusPath.classList.add("selected-link");
        svg.querySelectorAll(".node").forEach(node => {
          const flowId = node.getAttribute("data-flow-id");
          const scopeName = node.getAttribute("data-scope");
          node.classList.toggle(
            "dimmed",
            !(scopeName === edge.scope || flowId === edge.target)
          );
        });
        svg.querySelectorAll(".edge").forEach(item => {
          item.classList.toggle("dimmed", item !== path);
        });
        svg.querySelectorAll(".edge-hit").forEach(item => {
          item.classList.toggle("dimmed", item !== hit);
        });
        svg.querySelectorAll(".edge-label-wrap").forEach(item => {
          item.classList.add("dimmed");
        });
        const scopeNode = svg.querySelector(
          '.scope-node[data-scope="' + cssEscape(edge.scope) + '"]'
        );
        const targetNode = svg.querySelector(
          '.flow-node[data-flow-id="' + cssEscape(edge.target) + '"]'
        );
        if (scopeNode) scopeNode.classList.add("edge-source");
        if (targetNode) targetNode.classList.add("edge-target");
      }

      function selectScopeEntryLink(edge, path, hit, focusPath) {
        if (!edge || !path) return;
        canvasState.selectedRouteEdge = {
          kind: "scope-entry",
          scope: edge.scope,
          target: edge.target,
        };
        applyScopeEntryLinkClasses(edge, path, hit, focusPath);
        if (LC.clearHighlight) LC.clearHighlight();
        if (LC.openDetails) LC.openDetails();
        const flow = byId.get(edge.target);
        if (flow && LC.select) {
          LC.select({
            scope: edge.scope,
            path: flow.location.path,
            flowId: flow.id,
            nodeId: null,
            findingId: null,
            edgeId: null,
          });
        }
      }

      function restoreSelectedProgressiveLink() {
        const selected = canvasState.selectedRouteEdge;
        if (!selected) return;
        if (selected.kind === "scope-entry") {
          const sourceSelector = '[data-source-scope="' + cssEscape(selected.scope) + '"]';
          const targetSelector = '[data-target-flow-id="' + cssEscape(selected.target) + '"]';
          const path = svg.querySelector(".scope-entry-link" + sourceSelector + targetSelector);
          if (!path) return;
          const hit = svg.querySelector(".scope-entry-hit" + sourceSelector + targetSelector);
          const focusPath = svg.querySelector(".scope-entry-focus" + sourceSelector + targetSelector);
          applyScopeEntryLinkClasses(
            { scope: selected.scope, target: selected.target },
            path,
            hit,
            focusPath
          );
          return;
        }
        const sourceSelector = '[data-source-flow-id="' + cssEscape(selected.source) + '"]';
        const targetSelector = '[data-target-flow-id="' + cssEscape(selected.target) + '"]';
        const label = svg.querySelector(".progressive-call-label" + sourceSelector + targetSelector);
        const path = svg.querySelector(".progressive-call-edge" + sourceSelector + targetSelector);
        if (!label || !path) return;
        const hit = svg.querySelector(".progressive-call-hit" + sourceSelector + targetSelector);
        const focusPath = svg.querySelector(".progressive-call-focus" + sourceSelector + targetSelector);
        applyProgressiveLinkClasses(
          { source: selected.source, target: selected.target },
          path,
          label,
          hit,
          focusPath
        );
      }

      function rememberRouteEdge(flowId, record) {
        const records = currentRouteEdgeRecords.get(flowId) || [];
        records.push(record);
        currentRouteEdgeRecords.set(flowId, records);
      }

      function routeEdgeRecordFromElement(element) {
        if (!element || !element.closest) return null;
        const target = element.closest(
          ".progressive-call-hit, .progressive-call-edge, .progressive-call-label"
        );
        if (!target) return null;
        const source = target.getAttribute("data-source-flow-id");
        const destination = target.getAttribute("data-target-flow-id");
        if (!source || !destination) return null;
        const records = currentRouteEdgeRecords.get(source) || [];
        const record = records.find(item =>
          item.edge.source === source && item.edge.target === destination
        );
        if (record) return record;
        const sourceSelector = '[data-source-flow-id="' + cssEscape(source) + '"]';
        const targetSelector = '[data-target-flow-id="' + cssEscape(destination) + '"]';
        return {
          edge: { source, target: destination },
          hit: svg.querySelector(".progressive-call-hit" + sourceSelector + targetSelector),
          path: svg.querySelector(".progressive-call-edge" + sourceSelector + targetSelector),
          focusPath: svg.querySelector(".progressive-call-focus" + sourceSelector + targetSelector),
          label: svg.querySelector(".progressive-call-label" + sourceSelector + targetSelector),
        };
      }

      function scopeEntryRecordFromElement(element) {
        if (!element || !element.closest) return null;
        const target = element.closest(".scope-entry-hit, .scope-entry-link");
        if (!target) return null;
        const scope = target.getAttribute("data-source-scope");
        const flowId = target.getAttribute("data-target-flow-id");
        if (!scope || !flowId) return null;
        const sourceSelector = '[data-source-scope="' + cssEscape(scope) + '"]';
        const targetSelector = '[data-target-flow-id="' + cssEscape(flowId) + '"]';
        return {
          kind: "scope-entry",
          edge: { scope, target: flowId },
          hit: svg.querySelector(".scope-entry-hit" + sourceSelector + targetSelector),
          path: svg.querySelector(".scope-entry-link" + sourceSelector + targetSelector),
          focusPath: svg.querySelector(".scope-entry-focus" + sourceSelector + targetSelector),
        };
      }

      function activateRouteEdgeRecord(event) {
        const record = scopeEntryRecordFromElement(event.target) ||
          routeEdgeRecordFromElement(event.target);
        if (!record) return;
        event.preventDefault();
        event.stopPropagation();
        if (record.kind === "scope-entry") {
          selectScopeEntryLink(record.edge, record.path, record.hit, record.focusPath);
          return;
        }
        selectProgressiveLink(record.edge, record.path, record.label, record.hit, record.focusPath);
      }

      function rerouteFlowNodeEdges(flowId) {
        (currentRouteEdgeRecords.get(flowId) || []).forEach(record => {
          const geometry = progressiveEdgeGeometry(record.edge.from, record.edge.to);
          if (record.hit) setEdgeHitGeometry(record.hit, geometry, record.activate);
          record.path.setAttribute("d", geometry.d);
          if (record.focusPath) record.focusPath.setAttribute("d", geometry.focusD || geometry.d);
          if (record.label) {
            record.label.setAttribute("transform", `translate(${geometry.labelX} ${geometry.labelY})`);
          }
        });
      }

      function edgeLabel(text, geometry) {
        const value = String(text);
        const width = Math.max(30, value.length * 7 + 18);
        const group = svgEl("g");
        group.setAttribute("class", "edge-label-wrap");
        group.setAttribute("transform", `translate(${geometry.labelX} ${geometry.labelY})`);
        const bg = svgEl("rect");
        bg.setAttribute("class", "edge-label-bg");
        bg.setAttribute("x", String(-width / 2));
        bg.setAttribute("y", "-12");
        bg.setAttribute("width", String(width));
        bg.setAttribute("height", "20");
        bg.setAttribute("rx", "10");
        const label = svgEl("text");
        label.setAttribute("class", "edge-label");
        label.setAttribute("text-anchor", "middle");
        label.setAttribute("y", "4");
        label.textContent = value;
        group.append(bg, label);
        return group;
      }

      function progressiveEdgeGeometry(a, b) {
        const startY = a.y + FLOW_H / 2;
        const endY = b.y - FLOW_H / 2;
        const midY = startY + Math.max(56, (endY - startY) * 0.42);
        const curveY = Math.max(90, Math.abs(endY - startY) * 0.55);
        return {
          d: `M ${a.x} ${startY} L ${a.x} ${midY} L ${b.x} ${midY} L ${b.x} ${endY}`,
          focusD: `M ${a.x} ${startY} C ${a.x} ${startY + curveY}, ${b.x} ${endY - curveY}, ${b.x} ${endY}`,
          points: [
            { x: a.x, y: startY },
            { x: a.x, y: midY },
            { x: b.x, y: midY },
            { x: b.x, y: endY },
          ],
          labelX: a.x + (b.x - a.x) * 0.36,
          labelY: midY - 9,
        };
      }

      function scopeEntryGeometry(scopeNode, flowPos, index, total) {
        const startY = scopeNode.y + scopeNode.h / 2;
        const endY = flowPos.y - FLOW_H / 2;
        const available = Math.max(80, endY - startY);
        const fanoutOffset = (index - (total - 1) / 2) * 10;
        const startX = scopeNode.x + fanoutOffset;
        const laneY = startY + clamp(42, available * 0.42, Math.max(42, available - 46));
        const curveY = Math.max(70, available * 0.55);
        return {
          d: `M ${startX} ${startY} L ${startX} ${laneY} L ${flowPos.x} ${laneY} L ${flowPos.x} ${endY}`,
          focusD: `M ${startX} ${startY} C ${startX} ${startY + curveY}, ${flowPos.x} ${endY - curveY}, ${flowPos.x} ${endY}`,
          points: [
            { x: startX, y: startY },
            { x: startX, y: laneY },
            { x: flowPos.x, y: laneY },
            { x: flowPos.x, y: endY },
          ],
        };
      }

      // --- Renderers ---------------------------------------------------------------

      function renderL0() {
        const names = Object.keys(scopeFlows).sort();
        setCanvasLevel("0");

        if (names.length === 0) {
          svg.replaceChildren();
          if (emptyState) {
            emptyState.style.display = "grid";
            setEmptyMessage("No scopes");
          }
          renderBreadcrumb(canvasState);
          return;
        }
        if (names.length === 1) {
          // Skip the trivial single-scope L0 and go straight into it.
          expandScope(names[0]);
          return;
        }
        // Restore the default copy in case a prior no-scopes render left "No scopes".
        setEmptyMessage(defaultEmptyMessage);
        if (emptyState) emptyState.style.display = "none";

        const { nodePos, bounds } = layoutL0(names);
        svg.replaceChildren();
        svg.appendChild(defsBlock());

        // Aggregated cross-scope edges (from != to). EMPTY-EDGE GUARD: when sparse,
        // simply draw none -- the wrapped grid is already a clean, non-degenerate layout.
        const edgeLayer = svgEl("g");
        scopeEdges.forEach(edge => {
          if (edge.from === edge.to) return;
          const a = nodePos.get(edge.from);
          const b = nodePos.get(edge.to);
          if (!a || !b) return;
          const geometry = straightEdge(a, b, 0);
          edgeLayer.appendChild(edgePath(geometry, edge.count));
          edgeLayer.appendChild(edgeLabel(edge.count, geometry));
        });
        svg.appendChild(edgeLayer);

        const nodeLayer = svgEl("g");
        names.forEach(name => {
          const pos = nodePos.get(name);
          nodeLayer.appendChild(
            makeSuperNode(name, (scopeFlows[name] || []).length, pos, {})
          );
        });
        svg.appendChild(nodeLayer);

        fitBounds(bounds);
        renderBreadcrumb(canvasState);
      }

      function renderL1(scope) {
        if (!scope || !Object.prototype.hasOwnProperty.call(scopeFlows, scope)) {
          canvasState.level = 0;
          renderL0();
          return;
        }
        // L1 by default; any inline-expanded flow puts decision flowcharts on the canvas,
        // so the level reads L2 without leaving the progressive L1 surface.
        setCanvasLevel(canvasState.expandedFlowIds.size ? "2" : "1");
        setEmptyMessage(defaultEmptyMessage);
        if (emptyState) emptyState.style.display = "none";

        const layout = layoutExpandedCodebase(scope);
        const detail = layout.detail;
        svg.replaceChildren();
        svg.appendChild(defsBlock());

        // Keep the global codebase map in view while one scope is expanded. Scope edges
        // stay aggregate-level context; detailed intra-scope edges are drawn inside the
        // active detail area below.
        const scopeEdgeLayer = svgEl("g");
        scopeEdges.forEach(edge => {
          if (edge.from === edge.to) return;
          const a = layout.nodePos.get(edge.from);
          const b = layout.nodePos.get(edge.to);
          if (!a || !b) return;
          const geometry = straightEdge(a, b, 0);
          const path = edgePath(geometry, edge.count);
          if (edge.from !== scope && edge.to !== scope) {
            path.classList.add("dimmed-edge");
          }
          scopeEdgeLayer.appendChild(path);
          scopeEdgeLayer.appendChild(edgeLabel(edge.count, geometry));
        });
        svg.appendChild(scopeEdgeLayer);

        const activeScopeNode = layout.nodePos.get(scope);
        if (activeScopeNode && detail.entryFlowIds.length) {
          const scopeEntryLayer = svgEl("g");
          detail.entryFlowIds.forEach((flowId, index) => {
            const pos = detail.flowPos.get(flowId);
            if (!pos) return;
            const geometry = scopeEntryGeometry(
              activeScopeNode,
              pos,
              index,
              detail.entryFlowIds.length
            );
            const linkEdge = { scope, target: flowId };
            let hit = null;
            let path = null;
            let focusPath = null;
            const activate = event => {
              event.stopPropagation();
              selectScopeEntryLink(linkEdge, path, hit, focusPath);
            };
            hit = edgeHitPath(geometry, activate);
            hit.classList.add("scope-entry-hit");
            path = edgePath(geometry, null);
            path.classList.add("scope-entry-link");
            focusPath = edgeFocusPath(geometry);
            focusPath.classList.add("scope-entry-focus");
            [hit, path, focusPath].forEach(item => {
              item.setAttribute("data-source-scope", scope);
              item.setAttribute("data-target-flow-id", flowId);
            });
            path.setAttribute("tabindex", "0");
            path.setAttribute("role", "button");
            path.setAttribute(
              "aria-label",
              `entry link from ${scope} to ${byId.get(flowId)?.name || flowId}`
            );
            hit.addEventListener("click", activate);
            path.addEventListener("click", activate);
            path.addEventListener("keydown", event => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activate(event);
              }
            });
            scopeEntryLayer.appendChild(path);
            scopeEntryLayer.appendChild(focusPath);
            scopeEntryLayer.appendChild(hit);
          });
          svg.appendChild(scopeEntryLayer);
        }

        const scopeNodeLayer = svgEl("g");
        layout.names.forEach(name => {
          const pos = layout.nodePos.get(name);
          scopeNodeLayer.appendChild(
            makeSuperNode(name, (scopeFlows[name] || []).length, pos, {
              expanded: name === scope,
              dimmed: name !== scope,
            })
          );
        });
        svg.appendChild(scopeNodeLayer);

        const rowLayer = svgEl("g");
        detail.flowRows.forEach(row => {
          const line = svgEl("line");
          line.setAttribute("class", "progressive-row-rule");
          line.setAttribute("x1", String(row.x - row.w / 2 - DETAIL_PAD));
          line.setAttribute("x2", String(row.x + row.w / 2 + DETAIL_PAD));
          line.setAttribute("y1", String(row.y - FLOW_META_Y));
          line.setAttribute("y2", String(row.y - FLOW_META_Y));
          const label = svgEl("text");
          label.setAttribute("class", "progressive-row-label");
          label.setAttribute("x", String(row.x - row.w / 2 - DETAIL_PAD));
          label.setAttribute("y", String(row.y - FLOW_META_Y - 10));
          label.textContent = row.label;
          rowLayer.append(line, label);
        });
        svg.appendChild(rowLayer);

        // Progressive call edges among the visible entrypoint/call-route nodes. These are
        // not file edges: every visible relation is a universal "this flow calls that
        // flow" connection, regardless of language, framework, or folder layout.
        const edgeLayer = svgEl("g");
        currentRouteEdgeRecords = new Map();
        const drawn = new Set();
        detail.routeEdges.forEach(edge => {
          const key = edge.source + "|" + edge.target;
          if (drawn.has(key)) return;
          drawn.add(key);
          const geometry = progressiveEdgeGeometry(edge.from, edge.to);
          let hit = null;
          let path = null;
          let focusPath = null;
          let label = null;
          const labelText = `call link from ${byId.get(edge.source)?.name || edge.source} to ${byId.get(edge.target)?.name || edge.target}`;
          const activate = event => {
            event.stopPropagation();
            selectProgressiveLink(edge, path, label, hit, focusPath);
          };
          hit = edgeHitPath(geometry, activate);
          hit.classList.add("progressive-call-hit");
          path = edgePath(geometry, null);
          path.classList.add("progressive-call-edge");
          focusPath = edgeFocusPath(geometry);
          focusPath.classList.add("progressive-call-focus");
          hit.setAttribute("data-source-flow-id", edge.source);
          hit.setAttribute("data-target-flow-id", edge.target);
          focusPath.setAttribute("data-source-flow-id", edge.source);
          focusPath.setAttribute("data-target-flow-id", edge.target);
          path.setAttribute("tabindex", "0");
          path.setAttribute("role", "button");
          path.setAttribute("aria-label", labelText);
          path.setAttribute("data-source-flow-id", edge.source);
          path.setAttribute("data-target-flow-id", edge.target);
          label = edgeLabel(edge.label, geometry);
          label.classList.add("progressive-call-label");
          label.setAttribute("data-source-flow-id", edge.source);
          label.setAttribute("data-target-flow-id", edge.target);
          label.setAttribute("role", "button");
          label.setAttribute("tabindex", "0");
          label.setAttribute("aria-label", labelText);
          hit.addEventListener("click", activate);
          path.addEventListener("click", activate);
          path.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              activate(event);
            }
          });
          label.addEventListener("click", activate);
          bindEdgeActivationParts(label, activate);
          label.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              activate(event);
            }
          });
          const record = { edge, hit, path, focusPath, label, activate };
          rememberRouteEdge(edge.source, record);
          rememberRouteEdge(edge.target, record);
          edgeLayer.appendChild(path);
          edgeLayer.appendChild(focusPath);
          edgeLayer.appendChild(hit);
          edgeLayer.appendChild(label);
        });
        svg.appendChild(edgeLayer);

        // The active scope's visible flow nodes. Other scopes stay collapsed context
        // nodes, and downstream flows appear only after a user unlocks them via calls.
        const nodeLayer = svgEl("g");
        detail.visibleIds.forEach(id => {
          const flow = byId.get(id);
          const pos = detail.flowPos.get(id);
          if (flow && pos) nodeLayer.appendChild(makeFlowNode(flow, pos));
        });
        svg.appendChild(nodeLayer);

        // Inline L2: unfold the expanded flow's decision flowchart in place, anchored
        // under its flow node in the reserved band. Lazy: the sub-graph enters the DOM
        // ONLY here, only while at least one flow is expanded; collapse/reset re-renders
        // without the related inline sections.
        renderInlineFlow(detail);
        restoreSelectedProgressiveLink();

        // Fit the viewBox to the NON-INLINE L1 content only, and ONLY when no flow is
        // inline-expanded. While a flow is expanded we must NOT refit: folding the (often
        // huge) decision band into the fit would shrink every sibling flow to an
        // illegible scale. Instead the inline sub-graph renders at 1x
        // and we keep the user's current zoom/pan, nudging only enough to keep the host
        // flow node on-screen (the user pans to reach a tall/wide sub-graph).
        if (canvasState.expandedFlowIds.size) {
          const hostNode = detail.flowPos.get(canvasState.expandedFlow);
          ensureNodeVisible(hostNode);
        } else {
          fitBounds(layout.bounds);
        }
        renderBreadcrumb(canvasState);
      }

      // Draw every expanded flow's decisions in place using shell.js's reusable decision
      // renderer (LC.drawFlowGraph). Each sub-graph stays mounted until explicitly
      // collapsed/reset, so expanding a downstream call does not close its parent.
      function renderInlineFlow(layout) {
        if (!LC.drawFlowGraph) return;
        (layout.inlineAnchors || []).forEach(anchor => {
          const flow = byId.get(anchor.flowId);
          if (!flow || !flow.nodes || !flow.nodes.length) return;

          const wrap = svgEl("g");
          wrap.setAttribute("class", "inline-flow");
          wrap.setAttribute("data-inline-flow", flow.id);
          // Stable id so the host flow node's aria-controls can reference this region.
          wrap.setAttribute("id", inlineWrapId(flow.id));

          // Connector from the flow node down into its decision panel.
          const node = layout.flowPos.get(flow.id);
          const b = anchor.bounds;
          if (node) {
            const link = svgEl("path");
            link.setAttribute("class", "inline-flow-link");
            link.setAttribute(
              "d",
              `M ${node.x} ${node.y + FLOW_H / 2} L ${node.x} ${b.minY}`
            );
            wrap.appendChild(link);
          }

          const render = LC.drawFlowGraph(flow, {
            originX: anchor.x,
            originY: anchor.y,
            layerClass: "inline-flow-graph",
            omitEntry: true,
            draggable: true,
          });
          wrap.addEventListener("pointerdown", () => {
            canvasState.expandedFlow = flow.id;
            if (LC.setCurrentRender) LC.setCurrentRender(render);
          }, true);
          wrap.appendChild(render.layer);
          const hostNode = svg.querySelector(
            '.flow-node[data-flow-id="' + cssEscape(flow.id) + '"]'
          );
          if (hostNode) hostNode.after(wrap);
          else svg.appendChild(wrap);

          if (flow.id === canvasState.expandedFlow && LC.setCurrentRender) {
            LC.setCurrentRender(render);
          }
        });
      }

      // --- Single dispatch entry ---------------------------------------------------

      function renderCanvas() {
        LC.mode = "canvas";
        if (canvasState.level === 0) renderL0();
        else renderL1(canvasState.expandedScope);
      }

      // --- Mutators ----------------------------------------------------------------

      // Enter L1 for `name`. Switching scope drops the unlocked route because route
      // membership is contextual to the scope/map the user was exploring.
      function setScope(name) {
        if (canvasState.expandedScope !== name) {
          clearRoute();
        }
        canvasState.level = 1;
        canvasState.expandedScope = name;
      }

      function expandScope(name, updateHash) {
        if (!Object.prototype.hasOwnProperty.call(scopeFlows, name)) return;
        setScope(name);
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        setLevelHeader(
          name,
          `${(scopeFlows[name] || []).length} flow${(scopeFlows[name] || []).length === 1 ? "" : "s"} · scope`
        );
        if (updateHash !== false) location.hash = "scope=" + encodeURIComponent(name);
        // Publish the scope so the logical-errors panel scopes to this L1 subtree's
        // findings. Clear any prior flow/node so the panels reflect the level, not a
        // stale selection from a deeper view.
        if (LC.select) {
          LC.select({ scope: name, flowId: null, nodeId: null, findingId: null, path: null });
        }
        if (LC.openDetails) LC.openDetails();
        renderCanvas();
      }

      function collapseToL0() {
        canvasState.level = 0;
        canvasState.expandedScope = null;
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        clearRoute();
        setLevelHeader("Analyze a project to begin", "No flow selected");
        location.hash = "";
        // Back at L0 (the whole codebase): clear the selection so the panels show the
        // codebase-wide findings list and the source hint.
        if (LC.select) {
          LC.select({ scope: null, flowId: null, nodeId: null, findingId: null, path: null });
        }
        renderCanvas();
      }

      function replaceHash(hash) {
        if (window.history && window.history.replaceState) {
          const base = location.pathname + location.search;
          window.history.replaceState(null, "", hash ? base + "#" + hash : base);
        } else {
          location.hash = hash || "";
        }
      }

      function selectFile(path) {
        const count = flowCountForPath(path);
        const kind = pathKind(path);
        canvasState.selectedPath = path;
        canvasState.selectedFlowId = null;
        setLevelHeader(
          shortPathLabel(path),
          `${count} flow${count === 1 ? "" : "s"} · ${kind}`
        );
        if (LC.select) {
          LC.select({
            scope: canvasState.expandedScope,
            path,
            flowId: null,
            nodeId: null,
            findingId: null,
          });
        }
        if (LC.openDetails) LC.openDetails();
      }

      function focusPath(path, updateHash) {
        const scope = scopeOfPath(path);
        if (!scope) return false;
        if (path === scope) {
          expandScope(scope, updateHash);
          return true;
        }
        setScope(scope);
        clearRoute();
        selectFile(path);
        if (updateHash !== false) replaceHash("path=" + encodeURIComponent(path));
        renderCanvas();
        return true;
      }

      function activateRouteFlow(id) {
        const index = canvasState.routeFlowIds.indexOf(id);
        if (index === -1) {
          canvasState.routeFlowIds.push(id);
        } else {
          canvasState.routeFlowIds = canvasState.routeFlowIds.slice(0, index + 1);
        }
      }

      function clearRoute() {
        canvasState.routeFlowIds = [];
        clearAllInlineFlows();
      }

      // Toggle the inline decision sub-graph for `id`. Expanding unlocks this flow in the
      // visible route and reveals its direct calls as the next row of the same flowchart.
      function toggleFlow(id) {
        if (canvasState.expandedFlowIds.has(id)) {
          collapseInlineFlow(true, id);
          return;
        }
        expandFlowInline(id);
      }

      // Open `id`'s decisions inline within L1. The flow is added to the route first, so
      // its direct call targets become visible even when the flow itself has no decisions.
      function expandFlowInline(id) {
        clearProgressiveLinkHighlight();
        const flow = byId.get(id);
        if (!flow) return;
        const scope = scopeOfFlow(flow);
        if (scope && Object.prototype.hasOwnProperty.call(scopeFlows, scope)) {
          if (canvasState.expandedScope !== scope) clearRoute();
          canvasState.expandedScope = scope;
        }
        canvasState.level = 1;
        activateRouteFlow(id);
        canvasState.selectedPath = flow.location.path;
        canvasState.selectedFlowId = id;
        LC.mode = "canvas"; // inline L2 stays on the canvas; never flips to "flow".
        // Keep the header in sync even when a flow node is clicked directly on the canvas
        // (shell.js's selectFlow sets it for tree clicks, but a direct node click routes
        // here without going through selectFlow).
        setFlowHeader(flow);
        const expandable = !!(
          flow.nodes &&
          flow.nodes.some(node => node.kind !== "entry")
        );
        if (expandable) {
          canvasState.expandedFlowIds.add(id);
          canvasState.expandedFlow = id;
          location.hash = "flow=" + encodeURIComponent(id);
        } else {
          // No decisions: select/unlock only, no decision band.
          canvasState.expandedFlow = null;
          if (LC.setCurrentRender) LC.setCurrentRender(null);
          location.hash = "flow=" + encodeURIComponent(id);
        }
        // Prime the inspector with the flow summary ONCE, here on open -- NOT in
        // renderInlineFlow (which runs on every re-render and would wipe a clicked node's
        // detail back to the summary).
        if (LC.inspectFlow) LC.inspectFlow(flow);
        renderCanvas();
        // renderCanvas() replaceChildren()'d the SVG; restore focus to the host node so the
        // keyboard does not fall through to <body> after an Enter/Space toggle.
        focusFlowNode(id);
      }

      function clearAllInlineFlows() {
        clearProgressiveLinkHighlight();
        if (!canvasState.expandedFlowIds.size && !canvasState.expandedFlow) return false;
        canvasState.expandedFlowIds.clear();
        canvasState.expandedFlow = null;
        if (LC.setCurrentRender) LC.setCurrentRender(null);
        return true;
      }

      // Clear one inline-flow STATE only (no render). Returns whether a section closed.
      function clearInlineFlow(id) {
        const targetId = id || canvasState.expandedFlow;
        if (!targetId || !canvasState.expandedFlowIds.has(targetId)) return false;
        canvasState.expandedFlowIds.delete(targetId);
        if (canvasState.expandedFlow === targetId) {
          canvasState.expandedFlow = canvasState.expandedFlowIds.size
            ? [...canvasState.expandedFlowIds][canvasState.expandedFlowIds.size - 1]
            : null;
          if (LC.setCurrentRender) LC.setCurrentRender(null);
        }
        return true;
      }

      // Collapse one inline sub-graph. When `updateHash`, rewinds the hash to the active
      // scope or remaining active flow. Other expanded sections remain mounted.
      function collapseInlineFlow(updateHash, id) {
        const hostId =
          id ||
          canvasState.expandedFlow ||
          [...canvasState.expandedFlowIds][canvasState.expandedFlowIds.size - 1];
        const hostFlow = hostId ? byId.get(hostId) : null;
        if (!clearInlineFlow(hostId)) return;
        if (updateHash) {
          replaceHash(canvasState.expandedFlow
            ? "flow=" + encodeURIComponent(canvasState.expandedFlow)
            : canvasState.expandedScope
              ? "scope=" + encodeURIComponent(canvasState.expandedScope)
              : "");
        }
        if (hostFlow) {
          canvasState.selectedFlowId = hostFlow.id;
          setFlowHeader(hostFlow);
          if (LC.select) {
            LC.select({
              scope: canvasState.expandedScope,
              path: hostFlow.location.path,
              flowId: hostFlow.id,
              nodeId: null,
              findingId: null,
            });
          }
        } else if (canvasState.expandedScope) {
          canvasState.selectedPath = null;
          setLevelHeader(
            canvasState.expandedScope,
            `${(scopeFlows[canvasState.expandedScope] || []).length} flow${(scopeFlows[canvasState.expandedScope] || []).length === 1 ? "" : "s"} · scope`
          );
        }
        renderCanvas();
        focusFlowNode(hostId);
      }

      // --- Breadcrumb --------------------------------------------------------------

      function crumbButton(text, onClick, current, title) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "crumb" + (current ? " current" : "");
        if (current) button.setAttribute("aria-current", "page");
        button.textContent = text;
        button.title = title || (current ? `Current level: ${text}` : `Go to ${text}`);
        if (onClick) button.addEventListener("click", onClick);
        return button;
      }

      function crumbSeparator() {
        const sep = document.createElement("span");
        sep.className = "crumb-sep";
        sep.setAttribute("aria-hidden", "true");
        sep.textContent = "/";
        return sep;
      }

      // Breadcrumb levels:
      //   L0                       -> codebase
      //   L1                       -> codebase / scope
      //   L1 + inline flow (L2)    -> codebase / scope / flow
      //   path focus               -> codebase / scope / source path
      // `inFlow` is the legacy full-screen renderFlow mode; inline L2 stays "canvas" and
      // is detected via state.expandedFlow instead.
      function renderBreadcrumb(state) {
        if (!breadcrumbEl) return;
        breadcrumbEl.replaceChildren();
        const inFlow = LC.mode === "flow";
        const inlineFlow = state.expandedFlow ? byId.get(state.expandedFlow) : null;
        const atRoot = state.level === 0 && !inFlow;
        breadcrumbEl.appendChild(
          crumbButton("codebase", collapseToL0, atRoot, "Reset to the codebase overview")
        );

        if (state.level === 1 && state.expandedScope) {
          breadcrumbEl.appendChild(crumbSeparator());
          const scope = state.expandedScope;
          // The scope crumb is "current" at plain L1 (no inline flow, not full-screen);
          // clicking it from a deeper level returns here and collapses the inline flow.
          const scopeCurrent = state.level === 1 && !inFlow && !inlineFlow;
          breadcrumbEl.appendChild(
            crumbButton(
              scope,
              () => {
                if (inFlow || inlineFlow || canvasState.level !== 1) {
                  clearRoute();
                  setScope(scope);
                  location.hash = "scope=" + encodeURIComponent(scope);
                  renderCanvas();
                }
              },
              scopeCurrent,
              scopeCurrent ? `Current scope: ${scope}` : `Return to scope ${scope}`
            )
          );
        }

        // Inline L2: the flow crumb is current. Source path stays secondary evidence in
        // the node tag and Source panel, not a primary canvas hierarchy level.
        if (inlineFlow) {
          breadcrumbEl.appendChild(crumbSeparator());
          breadcrumbEl.appendChild(
            crumbButton(inlineFlow.name, null, true, `Current expanded flow: ${inlineFlow.name}`)
          );
          return;
        }

        if (state.level === 1 && state.selectedPath) {
          breadcrumbEl.appendChild(crumbSeparator());
          const fileCrumb = crumbButton(
            shortPathLabel(state.selectedPath),
            null,
            true,
            `Current source focus: ${state.selectedPath}`
          );
          fileCrumb.title = state.selectedPath;
          breadcrumbEl.appendChild(fileCrumb);
          return;
        }

        // Legacy standalone full-screen flow crumb (only when renderFlow took the SVG).
        if (inFlow && state.selectedFlowId) {
          const flow = byId.get(state.selectedFlowId);
          if (flow) {
            breadcrumbEl.appendChild(crumbSeparator());
            breadcrumbEl.appendChild(
              crumbButton(flow.name, null, true, `Current flow: ${flow.name}`)
            );
          }
        }
      }

      // --- Hash dispatch surface (shell.js routeFromHash calls these) --------------

      LC.showL0 = function () {
        canvasState.level = 0;
        canvasState.expandedScope = null;
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        clearRoute();
        setLevelHeader("Analyze a project to begin", "No flow selected");
        if (LC.select) {
          LC.select({ scope: null, flowId: null, nodeId: null, findingId: null, path: null });
        }
        renderCanvas();
      };
      LC.showScope = function (name) {
        if (!Object.prototype.hasOwnProperty.call(scopeFlows, name)) {
          LC.showL0();
          return;
        }
        setScope(name);
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        setLevelHeader(
          name,
          `${(scopeFlows[name] || []).length} flow${(scopeFlows[name] || []).length === 1 ? "" : "s"} · scope`
        );
        if (LC.select) {
          LC.select({ scope: name, flowId: null, nodeId: null, findingId: null, path: null });
        }
        renderCanvas();
      };
      LC.showPath = function (path) {
        if (!focusPath(path, false)) LC.showL0();
      };
      // Inline-L2 entry shell.js's selectFlow delegates to (tree click, #flow= deep link).
      // Reveals the flow's scope and unfolds its decisions in place within L1.
      LC.expandFlowInline = expandFlowInline;
      LC.expandCallTarget = function (sourceFlowId, targetFlowId) {
        const source = byId.get(sourceFlowId);
        const target = byId.get(targetFlowId);
        if (!source || !target) return;
        const sourceIndex = canvasState.routeFlowIds.indexOf(sourceFlowId);
        if (sourceIndex === -1) {
          canvasState.routeFlowIds.push(sourceFlowId);
        } else {
          canvasState.routeFlowIds = canvasState.routeFlowIds.slice(0, sourceIndex + 1);
        }
        expandFlowInline(targetFlowId);
      };
      // Tree-driven focus. Unlike LC.showScope / LC.showPath (used by hash dispatch), these
      // follow the normal user action path and update the hash.
      LC.focusScope = expandScope;
      LC.focusPath = focusPath;
      LC.clearProgressiveLinkHighlight = clearProgressiveLinkHighlight;
      LC.clearCanvasFocus = function () {
        clearProgressiveLinkHighlight();
        if (LC.clearHighlight) LC.clearHighlight();
        svg.querySelectorAll(".flow-node.selected").forEach(node => {
          node.classList.remove("selected");
        });
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        if (LC.select) {
          LC.select({
            scope: canvasState.expandedScope,
            path: null,
            flowId: null,
            nodeId: null,
            findingId: null,
            edgeId: null,
          });
        }
        renderBreadcrumb(canvasState);
      };
      LC.refreshCanvasLayout = function () {
        layoutCache.clear();
        if (LC.mode === "canvas") renderCanvas();
      };
      // When shell.js enters flow mode (renderFlow), refresh the breadcrumb so it
      // gains the flow crumb. A flow opened from the tree or a #flow= deep link may
      // have no scope set yet, so derive the flow's scope (first membership, mirroring
      // build_scope_index) and pin it as the expanded scope -- otherwise the crumb
      // would read `codebase / <flow>` with the scope hop missing.
      LC.onCanvasFlow = function (flow) {
        canvasState.selectedFlowId = flow ? flow.id : null;
        if (flow) {
          const scope = scopeOfFlow(flow);
          if (scope && Object.prototype.hasOwnProperty.call(scopeFlows, scope)) {
            if (canvasState.expandedScope !== scope) clearRoute();
            canvasState.expandedScope = scope;
            canvasState.level = 1;
          }
        }
        renderBreadcrumb(canvasState);
      };
      LC.resetCanvas = function () {
        // Reset in canvas mode: close the progressive route/inline sections and re-fit
        // the current scope/root. This is the user's explicit "start over" control.
        layoutCache.clear();
        if (LC.clearFlowPositions) LC.clearFlowPositions();
        manualScopePositions.clear();
        manualFlowPositions.clear();
        clearRoute();
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        if (canvasState.expandedScope && LC.select) {
          LC.select({
            scope: canvasState.expandedScope,
            path: null,
            flowId: null,
            nodeId: null,
            findingId: null,
          });
        }
        if (canvasState.expandedScope) {
          replaceHash("scope=" + encodeURIComponent(canvasState.expandedScope));
        }
        renderCanvas();
      };

      svg.addEventListener("pointerdown", activateRouteEdgeRecord, true);
      svg.addEventListener("mousedown", activateRouteEdgeRecord, true);
      svg.addEventListener("click", activateRouteEdgeRecord, true);
      document.addEventListener("pointerdown", activateRouteEdgeRecord, true);
      document.addEventListener("mousedown", activateRouteEdgeRecord, true);
      document.addEventListener("click", activateRouteEdgeRecord, true);
      svg.addEventListener("keydown", event => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const record = routeEdgeRecordFromElement(event.target);
        if (!record) return;
        event.preventDefault();
        activateRouteEdgeRecord(event);
      }, true);
      document.addEventListener("keydown", event => {
        if (event.key !== "Enter" && event.key !== " ") return;
        const record = routeEdgeRecordFromElement(event.target);
        if (!record) return;
        event.preventDefault();
        activateRouteEdgeRecord(event);
      }, true);

      // Esc collapses the deepest open level: an inline flow first (back to plain L1),
      // else an expanded scope (back to L0). Ignored while typing in a form control. When
      // the in-page full-screen FALLBACK is active, panels.js OWNS the Esc (it exits the
      // fallback), so defer here -- otherwise one keypress both exits full screen AND
      // collapses a level. The real Fullscreen API path is handled by the browser, not here.
      document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        const target = event.target;
        if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || "")) return;
        if (LC.fullscreenFallbackActive && LC.fullscreenFallbackActive()) return;
        if (canvasState.expandedFlowIds.size) {
          collapseInlineFlow(true);
        } else if (canvasState.routeFlowIds.length) {
          clearRoute();
          if (canvasState.expandedScope) {
            replaceHash("scope=" + encodeURIComponent(canvasState.expandedScope));
          }
          renderCanvas();
        } else if (canvasState.level === 1) {
          collapseToL0();
        }
      });
    })();
