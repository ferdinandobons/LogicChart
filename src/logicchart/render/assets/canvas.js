
    // Codebase canvas (Phase 2). Owns the two top levels of the viewer:
    //   L0 = one super-node per scope, edges = aggregated cross-scope calls.
    //   L1 = the whole codebase map plus one expanded scope's files/flows in place.
    // Selecting a flow (here or from the tree) still defers to shell.js's
    // renderFlow via LC.selectFlow -- that is the L2 renderer (Phase 3 inlines it).
    //
    // OWNERSHIP SEAM: shell.js owns the SVG element, the shared `view` object, and
    // the pan/zoom/wheel handlers (generic over `view`). It exposes those as LC.svg,
    // LC.setView, LC.updateViewBox, LC.getView, LC.renderFlow and flips LC.mode to
    // "flow" right before renderFlow. canvas.js sets LC.mode = "canvas" and is the
    // SINGLE writer of the SVG for L0/L1 -- every entry (initial load, hashchange,
    // breadcrumb, expand/collapse) funnels through renderCanvas().
    //
    // LAZY INVARIANT: renderL0 builds only `scopes.length` super-node groups + the
    // scope_edges paths -- O(scopes), never O(flows). Expanding a scope keeps those
    // super-nodes visible and draws ONLY the active scope's file groups in an attached
    // detail area; unrelated scopes remain collapsed context nodes. Collapsing
    // replaceChildren() back to L0.
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
      const FILE_PAD = 24;

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
      // L1 also tracks which file chips are expanded; a file's flow nodes (and their
      // intra-file/visible call edges) are materialized only while its path is in this
      // set, so a scope with hundreds of flows never dumps everything onto the canvas.
      const canvasState = {
        level: 0,
        expandedScope: null,
        selectedPath: null,
        selectedFlowId: null,
        expandedFiles: new Set(),
        // L2: the flow id whose decision flowchart is unfolded IN PLACE inside L1, or
        // null. At most one at a time -- expanding another collapses the previous. The
        // sub-graph is in the DOM only while this is set; collapse removes it.
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
          <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">
            <path class="arrow" d="M0,0 L8,4 L0,8 z"></path>
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
          '.flow-node[data-flow-id="' + CSS.escape(id) + '"]'
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

      function findingCountForPath(path) {
        let count = 0;
        byId.forEach(flow => {
          const p = flow.location && flow.location.path;
          if (p && (p === path || p.startsWith(path + "/"))) {
            count += (findingsByFlow.get(flow.id) || []).length;
          }
        });
        return count;
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

      // Wrapped-grid column count, shared by L0 super-nodes and L1 file boxes.
      function gridCols(count, cellW) {
        const containerW = (canvasEl && canvasEl.clientWidth) || 1000;
        const fitting = Math.max(1, Math.floor(containerW / (cellW + GAP_X)));
        return clamp(1, Math.round(Math.sqrt(count) * 1.3), fitting);
      }

      // --- L0 layout: scopes as a wrapped grid of super-nodes ----------------------

      function layoutL0(names) {
        const cached = layoutCache.get("L0");
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
            nodePos.set(name, {
              x: cx,
              y: cy,
              w: SCOPE_W,
              h: superNodeHeight((scopeFlows[name] || []).length),
              count: (scopeFlows[name] || []).length,
            });
          });
          layoutCache.set("L0", { nodePos });
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
        layout.fileBoxes.forEach(box => {
          box.x += dx;
          box.y += dy;
        });
        layout.flowPos.forEach(pos => {
          pos.x += dx;
          pos.y += dy;
        });
        if (layout.inlineAnchor) {
          layout.inlineAnchor.x += dx;
          layout.inlineAnchor.y += dy;
          layout.inlineAnchor.bounds = offsetBounds(layout.inlineAnchor.bounds, dx, dy);
          layout.inlineBounds = layout.inlineAnchor.bounds;
        } else if (layout.inlineBounds) {
          layout.inlineBounds = offsetBounds(layout.inlineBounds, dx, dy);
        }
        layout.bounds = offsetBounds(layout.bounds, dx, dy);
        return layout;
      }

      // --- L1 detail layout: one expanded scope's files in a grouped grid ----------

      // L1 layout. Each FILE in the expanded scope is a collapsed header chip by
      // default (file name + flow count); a file's flow nodes are laid out ONLY when
      // its path is in `canvasState.expandedFiles`. This keeps L1 lazy at scale: a
      // scope with hundreds of flows shows one chip per file, never every flow node.
      // The layout depends on the expanded-file set, so it is recomputed per render
      // (cheap: only expanded files materialize their flows) rather than cached by
      // scope alone.
      function layoutL1(scope) {
        // Expanded scope's flows, grouped by file. Files become chips; flows inside an
        // expanded file are materialized, the rest are not. The caller offsets this local
        // detail layout into the global codebase map.
        const visibleFlows = (scopeFlows[scope] || [])
          .map(id => byId.get(id))
          .filter(Boolean);
        const byPath = new Map();
        visibleFlows.forEach(flow => {
          const list = byPath.get(flow.location.path) || [];
          list.push(flow);
          byPath.set(flow.location.path, list);
        });
        const paths = [...byPath.keys()].sort((a, b) => a.localeCompare(b));

        // Pre-size each file box. A collapsed chip is header-only; an expanded box
        // grows to fit its flows in an inner grid.
        const HEADER_H = 22;
        const COLLAPSED_W = FILE_PAD * 2 + FLOW_W; // chip wide enough for the label.
        const COLLAPSED_H = FILE_PAD * 2 + HEADER_H;
        const boxes = paths.map(path => {
          const flowsInFile = sortFlows(byPath.get(path));
          const expanded = canvasState.expandedFiles.has(path);
          if (!expanded) {
            return { path, flows: flowsInFile, expanded: false, innerCols: 0, w: COLLAPSED_W, h: COLLAPSED_H };
          }
          const innerCols = Math.max(1, Math.floor(Math.sqrt(flowsInFile.length)));
          const innerRows = Math.ceil(flowsInFile.length / innerCols);
          const w = FILE_PAD * 2 + innerCols * FLOW_W + (innerCols - 1) * GAP_X;
          const h =
            FILE_PAD * 2 + HEADER_H + innerRows * FLOW_H + (innerRows - 1) * GAP_Y;
          return { path, flows: flowsInFile, expanded: true, innerCols, w, h };
        });

        // The inline-expanded flow (L2) lives in a file that must itself be expanded so
        // the flow node is present to anchor under. expandFlowInline guarantees that, but
        // guard here too: only reserve a band when the flow is actually a visible member.
        const expandedFlow = canvasState.expandedFlow
          ? byId.get(canvasState.expandedFlow)
          : null;
        // Reserve a band only for a flow that is a visible member AND actually has
        // decision nodes -- an empty flow draws nothing, so it needs no space.
        const expandedFlowPath =
          expandedFlow &&
          byPath.has(expandedFlow.location.path) &&
          expandedFlow.nodes &&
          expandedFlow.nodes.length
            ? expandedFlow.location.path
            : null;
        // Measured size of the decision sub-graph, so the row it sits under is pushed down
        // by exactly its height (no overlap with the next row), general over flow size.
        const subMeasure =
          expandedFlowPath && LC.measureFlow ? LC.measureFlow(expandedFlow) : null;
        const reservedH = subMeasure
          ? subMeasure.height + DECISION_PAD * 2
          : 0;
        const reservedW = subMeasure ? subMeasure.width + DECISION_PAD * 2 : 0;

        // Outer wrapped grid of file boxes; row height = tallest box in the row. When a
        // file in a row hosts the inline-expanded flow, the band BELOW that row is grown
        // by the sub-graph height so following rows are pushed down, never overlapped.
        const fileBoxes = new Map();
        const flowPos = new Map();
        // The inline sub-graph anchor (world center of its top), filled once the hosting
        // flow node is placed. renderL1 draws the sub-graph there.
        let inlineAnchor = null;
        const outerContainerW = (canvasEl && canvasEl.clientWidth) || 1000;
        // File-box wrap threshold stays the CONTAINER width -- a wide inline sub-graph must
        // NOT widen it, or the L1 file grid re-wraps every time a flow is expanded. The
        // sub-graph reserves its own horizontal room LOCALLY (its band's bounds extend past
        // the host row when reservedW is wide; the canvas pans to it), not globally here.
        const rowLimit = outerContainerW;
        let cursorX = 0;
        let rowTop = 0;
        let rowMaxH = 0;
        let rowStart = 0;
        let rowIndex = 0;
        let rowHasExpandedFlow = false;
        const rowMaxHeights = []; // finalized tallest box per row, for the inline anchor.
        boxes.forEach((box, i) => {
          if (i > rowStart && cursorX + box.w > rowLimit) {
            // wrap to a new row; if the finished row hosted the inline flow, add its band.
            rowMaxHeights[rowIndex] = rowMaxH;
            rowTop += rowMaxH + GAP_Y + (rowHasExpandedFlow ? reservedH : 0);
            cursorX = 0;
            rowMaxH = 0;
            rowStart = i;
            rowIndex += 1;
            rowHasExpandedFlow = false;
          }
          box.x = cursorX;
          box.y = rowTop;
          box.row = rowIndex;
          fileBoxes.set(box.path, box);
          // Only an expanded file places its flows in its inner grid; collapsed chips
          // contribute NO flow positions, so their flow nodes never enter the DOM.
          if (box.expanded) {
            box.flows.forEach((flow, fi) => {
              const col = fi % box.innerCols;
              const row = Math.floor(fi / box.innerCols);
              const cx = box.x + FILE_PAD + col * (FLOW_W + GAP_X) + FLOW_W / 2;
              const cy =
                box.y + FILE_PAD + HEADER_H + row * (FLOW_H + GAP_Y) + FLOW_H / 2;
              flowPos.set(flow.id, { x: cx, y: cy, w: FLOW_W, h: FLOW_H });
            });
          }
          if (box.path === expandedFlowPath) rowHasExpandedFlow = true;
          cursorX += box.w + GAP_X;
          rowMaxH = Math.max(rowMaxH, box.h);
        });
        rowMaxHeights[rowIndex] = rowMaxH; // finalize the last row.

        // Anchor the inline sub-graph centered horizontally on its flow node, just below
        // the bottom of the WHOLE host row (its tallest box) -- not just the host box --
        // so it can never overlap a taller same-row sibling chip. The band that follows
        // the host row was already grown by reservedH, so the next row clears it too.
        if (expandedFlowPath && flowPos.has(canvasState.expandedFlow) && subMeasure) {
          const hostBox = fileBoxes.get(expandedFlowPath);
          const node = flowPos.get(canvasState.expandedFlow);
          const rowBottom = hostBox.y + (rowMaxHeights[hostBox.row] || hostBox.h);
          // origin = where layoutFlow's (0,0) maps to: center it on the node, top of band.
          inlineAnchor = {
            x: node.x - (subMeasure.minX + subMeasure.maxX) / 2,
            y: rowBottom + DECISION_PAD - subMeasure.minY,
            flowId: canvasState.expandedFlow,
            bounds: {
              minX: node.x - reservedW / 2,
              maxX: node.x + reservedW / 2,
              minY: rowBottom,
              maxY: rowBottom + reservedH,
            },
          };
        }

        // The visible flow set is exactly the flows of EXPANDED files -- the only ones
        // with a position, the only ones drawn, and the only edge endpoints.
        const visibleIds = new Set(flowPos.keys());
        const allNodes = [...flowPos.values()];
        // Account for file-box extents too, so the viewBox includes box chrome.
        boxes.forEach(box => {
          allNodes.push({ x: box.x + box.w / 2, y: box.y + box.h / 2, w: box.w, h: box.h });
        });
        // NOTE: the reserved inline sub-graph band is deliberately EXCLUDED from `bounds`.
        // A large flow's band is ~thousands of world-px tall; folding it into the fit would
        // zoom the SHARED canvas viewBox out to contain it, shrinking every L1 file box /
        // sibling flow to an illegible scale. renderL1 fits only this
        // non-inline L1 content (and only on a fresh L1, never on expand) so the surrounding
        // context stays at a readable scale; the inline sub-graph draws at 1x and the user
        // pans to it. `inlineBounds` is exposed separately for the off-screen-nudge check.

        return {
          fileBoxes,
          flowPos,
          visibleIds,
          inlineAnchor,
          // Inline band bounds kept SEPARATE from `bounds` (which excludes it). renderL1
          // uses these only to keep the host flow node on-screen, never to refit the band.
          inlineBounds: inlineAnchor ? inlineAnchor.bounds : null,
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
          "scope-node" +
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
        rect.setAttribute("rx", "16");
        group.appendChild(rect);

        const nameLines = wrapLabel(name, 18, 2);
        // Recover the full scope name on hover when wrapLabel dropped overflow.
        if (isTruncated(name, 18, 2)) addTitle(group, name);
        nameLines.forEach((line, index) => {
          const text = svgEl("text");
          text.setAttribute("class", "scope-name");
          text.setAttribute("text-anchor", "middle");
          text.setAttribute(
            "y",
            String((index - (nameLines.length - 1) / 2) * 20 - 8)
          );
          text.textContent = line;
          group.appendChild(text);
        });
        const meta = svgEl("text");
        meta.setAttribute("class", "scope-meta");
        meta.setAttribute("text-anchor", "middle");
        meta.setAttribute("y", String(pos.h / 2 - (stats.review ? 28 : 14)));
        const langText = `${stats.languages} lang${stats.languages === 1 ? "" : "s"}`;
        meta.textContent = `${count} flow${count === 1 ? "" : "s"} · ${langText}`;
        group.appendChild(meta);
        if (stats.review) {
          const review = svgEl("text");
          review.setAttribute("class", "scope-review");
          review.setAttribute("text-anchor", "middle");
          review.setAttribute("y", String(pos.h / 2 - 11));
          review.textContent = `${stats.review} review`;
          group.appendChild(review);
        }

        const activate = () => expandScope(name);
        group.addEventListener("click", activate);
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          }
        });
        return group;
      }

      // A file is rendered as an expandable header chip. Collapsed by default it shows
      // only the file name + flow count; expanding (click / Enter / Space) materializes
      // its flow nodes, collapsing removes them. The header is the toggle target and
      // carries button semantics + aria-expanded so it is keyboard-accessible.
      function makeFileBox(path, box) {
        const count = box.flows.length;
        const reviewCount = findingCountForPath(path);
        const group = svgEl("g");
        group.setAttribute(
          "class",
          "file-box" +
            (box.expanded ? " expanded" : "") +
            (pathTouchesActive(path) ? " active-area" : "") +
            (reviewCount ? " has-finding" : "")
        );
        group.setAttribute("data-path", path);
        group.setAttribute("transform", `translate(${box.x} ${box.y})`);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-expanded", box.expanded ? "true" : "false");
        const labelText = shortPathLabel(path);
        group.setAttribute(
          "aria-label",
          `file ${labelText}: ${count} flow${count === 1 ? "" : "s"}, ${box.expanded ? "expanded" : "collapsed"}`
        );

        const rect = svgEl("rect");
        rect.setAttribute("class", "file-frame");
        rect.setAttribute("x", "0");
        rect.setAttribute("y", "0");
        rect.setAttribute("width", String(box.w));
        rect.setAttribute("height", String(box.h));
        rect.setAttribute("rx", "14");
        group.appendChild(rect);

        // Disclosure caret (rotates via CSS when expanded). Its position is baked into
        // the path data -- not an inline transform attribute -- because the CSS rotate
        // (transform-box: fill-box) would otherwise override an attribute transform.
        const cx = FILE_PAD - 12;
        const cy = FILE_PAD;
        const caret = svgEl("path");
        caret.setAttribute("class", "file-caret");
        caret.setAttribute("d", `M${cx},${cy - 4} L${cx + 5},${cy} L${cx},${cy + 4}`);
        group.appendChild(caret);

        const label = svgEl("text");
        label.setAttribute("class", "file-label");
        label.setAttribute("x", String(FILE_PAD));
        label.setAttribute("y", String(FILE_PAD + 4));
        // Show a context-bearing label so repeated names like route.ts stay legible.
        label.textContent = labelText;
        const full = svgEl("title");
        full.textContent = `${path} (${count} flow${count === 1 ? "" : "s"}${reviewCount ? `, ${reviewCount} review` : ""})`;
        label.appendChild(full);
        group.appendChild(label);

        // Flow-count chip on the header, so a collapsed file still advertises its size.
        const meta = svgEl("text");
        meta.setAttribute("class", "file-count");
        meta.setAttribute("x", String(box.w - FILE_PAD));
        meta.setAttribute("y", String(FILE_PAD + 4));
        meta.setAttribute("text-anchor", "end");
        meta.textContent = `${count}`;
        group.appendChild(meta);

        if (reviewCount) {
          const review = svgEl("circle");
          review.setAttribute("class", "file-review-dot");
          review.setAttribute("cx", String(box.w - 8));
          review.setAttribute("cy", String(8));
          review.setAttribute("r", "4");
          const reviewTitle = svgEl("title");
          reviewTitle.textContent = `${reviewCount} review finding${reviewCount === 1 ? "" : "s"}`;
          review.appendChild(reviewTitle);
          group.appendChild(review);
        }

        const toggle = () => toggleFile(path);
        group.addEventListener("click", toggle);
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            toggle();
          }
        });
        return group;
      }

      function makeFlowNode(flow, pos) {
        const group = svgEl("g");
        const isEntry = !!flow.is_entrypoint;
        const isExpanded = flow.id === canvasState.expandedFlow;
        group.setAttribute(
          "class",
          "node flow-node " +
            (isEntry ? "entry" : "action") +
            (findingFlowIds.has(flow.id) ? " has-finding" : "") +
            (flow.id === canvasState.selectedFlowId ? " selected" : "") +
            (pathTouchesActive(flow.location && flow.location.path) ? " active-area" : "") +
            (isExpanded ? " flow-open" : "")
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
          `flow: ${flow.name}, ${isExpanded ? "expanded" : "collapsed"}`
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
        meta.textContent = `${pathInActiveScope(flow.location.path)}:${flow.location.start_line}`;
        group.appendChild(meta);

        // Click / Enter / Space toggles the flow's decision sub-graph IN PLACE (L2).
        // Expanding an already-open flow collapses it; expanding another collapses the
        // previous (single inline flow for v1). Selection + breadcrumb follow the toggle.
        const toggle = () => toggleFlow(flow.id);
        group.addEventListener("click", toggle);
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
        // L1 by default; an inline-expanded flow puts a decision flowchart on the canvas,
        // so the level reads L2 (the decisions are L2 in the spec) without leaving L1.
        setCanvasLevel(canvasState.expandedFlow ? "2" : "1");
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
        if (activeScopeNode && detail.fileBoxes.size) {
          const centerX = (detail.bounds.minX + detail.bounds.maxX) / 2;
          const topY = detail.bounds.minY;
          const startY = activeScopeNode.y + activeScopeNode.h / 2;
          const link = svgEl("path");
          link.setAttribute("class", "scope-expansion-link");
          link.setAttribute(
            "d",
            `M ${activeScopeNode.x} ${startY} C ${activeScopeNode.x} ${startY + 34}, ${centerX} ${topY - 34}, ${centerX} ${topY}`
          );
          svg.appendChild(link);
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

        // Intra-scope call edges among the VISIBLE set only, deduped by min|max id.
        // Cross-scope calls remain represented by the aggregate scope edges above.
        const edgeLayer = svgEl("g");
        const drawn = new Set();
        let fanIndex = 0;
        detail.visibleIds.forEach(id => {
          const flow = byId.get(id);
          if (!flow) return;
          (flow.calls || []).forEach(target => {
            if (!detail.visibleIds.has(target)) return; // skip cross-scope / unresolved.
            const a = detail.flowPos.get(id);
            const b = detail.flowPos.get(target);
            if (!a || !b) return;
            const key = id < target ? id + "|" + target : target + "|" + id;
            if (drawn.has(key)) return;
            drawn.add(key);
            const curve = ((fanIndex++ % 5) - 2) * 14; // small per-edge fan-out.
            edgeLayer.appendChild(edgePath(straightEdge(a, b, curve), null));
          });
        });
        svg.appendChild(edgeLayer);

        // File boxes + the expanded scope's visible flow nodes. Other scopes are still in
        // the DOM as collapsed super-nodes, but their files/flows remain lazy.
        const fileLayer = svgEl("g");
        detail.fileBoxes.forEach((box, path) => {
          fileLayer.appendChild(makeFileBox(path, box));
        });
        svg.appendChild(fileLayer);

        const nodeLayer = svgEl("g");
        detail.visibleIds.forEach(id => {
          const flow = byId.get(id);
          const pos = detail.flowPos.get(id);
          if (flow && pos) nodeLayer.appendChild(makeFlowNode(flow, pos));
        });
        svg.appendChild(nodeLayer);

        // Inline L2: unfold the expanded flow's decision flowchart in place, anchored
        // under its flow node in the reserved band. Lazy: the sub-graph enters the DOM
        // ONLY here, only while expandedFlow is set; collapse re-renders without it.
        renderInlineFlow(detail);

        // Fit the viewBox to the NON-INLINE L1 content only, and ONLY when no flow is
        // inline-expanded. While a flow is expanded we must NOT refit: folding the (often
        // huge) decision band into the fit would shrink every file box / sibling flow /
        // sibling flow to an illegible scale. Instead the inline sub-graph renders at 1x
        // and we keep the user's current zoom/pan, nudging only enough to keep the host
        // flow node on-screen (the user pans to reach a tall/wide sub-graph).
        if (canvasState.expandedFlow) {
          const hostNode = detail.flowPos.get(canvasState.expandedFlow);
          ensureNodeVisible(hostNode);
        } else {
          fitBounds(layout.bounds);
        }
        renderBreadcrumb(canvasState);
      }

      // Draw the expanded flow's decisions in place using shell.js's reusable decision
      // renderer (LC.drawFlowGraph), anchored at layout.inlineAnchor. A faint connector
      // ties the flow node to its sub-graph. The drawn sub-graph is bound as the active
      // inspect/highlight target so clicking a decision node still calls inspectNode and
      // the bidirectional highlight + finding ring keep working, exactly as full screen.
      function renderInlineFlow(layout) {
        const anchor = layout.inlineAnchor;
        if (!anchor || !LC.drawFlowGraph) return;
        const flow = byId.get(anchor.flowId);
        if (!flow || !flow.nodes || !flow.nodes.length) return;

        const wrap = svgEl("g");
        wrap.setAttribute("class", "inline-flow");
        wrap.setAttribute("data-inline-flow", flow.id);
        // Stable id so the host flow node's aria-controls can reference this region.
        wrap.setAttribute("id", inlineWrapId(flow.id));

        // Soft backing panel behind the sub-graph so it reads as a unit within L1.
        const b = anchor.bounds;
        const panel = svgEl("rect");
        panel.setAttribute("class", "inline-flow-panel");
        panel.setAttribute("x", String(b.minX));
        panel.setAttribute("y", String(b.minY));
        panel.setAttribute("width", String(b.maxX - b.minX));
        panel.setAttribute("height", String(b.maxY - b.minY));
        panel.setAttribute("rx", "18");
        wrap.appendChild(panel);

        // Connector from the flow node down into its decision panel.
        const node = layout.flowPos.get(flow.id);
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
        });
        wrap.appendChild(render.layer);
        // Insert the inline sub-graph immediately AFTER the host flow node's <g>, so Tab
        // order is host node -> its decisions -> next sibling flow (appending to the SVG
        // would instead walk every sibling flow node before reaching the decisions).
        const hostNode = svg.querySelector(
          '.flow-node[data-flow-id="' + CSS.escape(flow.id) + '"]'
        );
        if (hostNode) hostNode.after(wrap);
        else svg.appendChild(wrap);

        // Bind the sub-graph as the active inspect/highlight target. Do NOT prime the
        // inspector here -- this runs on EVERY re-render, so calling inspectFlow would wipe
        // a clicked decision node's detail back to the flow summary. expandFlowInline primes
        // it once, when the flow is first opened.
        if (LC.setCurrentRender) LC.setCurrentRender(render);
      }

      // --- Single dispatch entry ---------------------------------------------------

      function renderCanvas() {
        LC.mode = "canvas";
        if (canvasState.level === 0) renderL0();
        else renderL1(canvasState.expandedScope);
      }

      // --- Mutators ----------------------------------------------------------------

      // Enter L1 for `name`. File chips start collapsed; entering a DIFFERENT scope
      // resets the expanded-file set AND any inline-expanded flow (both are scoped to the
      // scope being left, so they cannot carry over).
      function setScope(name) {
        if (canvasState.expandedScope !== name) {
          canvasState.expandedFiles.clear();
          clearInlineFlow();
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
        renderCanvas();
      }

      function collapseToL0() {
        canvasState.level = 0;
        canvasState.expandedScope = null;
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        canvasState.expandedFiles.clear();
        clearInlineFlow();
        setLevelHeader("Analyze a project to begin", "No flow selected");
        location.hash = "";
        // Back at L0 (the whole codebase): clear the selection so the panels show the
        // codebase-wide findings list and the source hint.
        if (LC.select) {
          LC.select({ scope: null, flowId: null, nodeId: null, findingId: null, path: null });
        }
        renderCanvas();
      }

      // Expand/collapse one file chip at L1, materializing or removing its flow nodes.
      // Collapsing the file that hosts the inline-expanded flow also collapses the flow
      // (its sub-graph would otherwise be orphaned with no node to anchor under).
      function toggleFile(path) {
        if (canvasState.expandedFiles.has(path)) {
          canvasState.expandedFiles.delete(path);
          const open = canvasState.expandedFlow
            ? byId.get(canvasState.expandedFlow)
            : null;
          if (open && open.location.path === path) clearInlineFlow();
        } else {
          canvasState.expandedFiles.add(path);
        }
        selectFile(path);
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
      }

      function focusPath(path, updateHash) {
        const scope = scopeOfPath(path);
        if (!scope) return false;
        if (path === scope) {
          expandScope(scope, updateHash);
          return true;
        }
        setScope(scope);
        clearInlineFlow();
        canvasState.expandedFiles.clear();
        if (filePaths.has(path)) canvasState.expandedFiles.add(path);
        selectFile(path);
        if (updateHash !== false) replaceHash("path=" + encodeURIComponent(path));
        renderCanvas();
        return true;
      }

      // Toggle the inline decision sub-graph for `id`. Expanding ensures the host scope +
      // file are open so the flow node exists to anchor under; expanding a different flow
      // replaces the previous (single inline flow for v1). Re-renders L1 in place.
      function toggleFlow(id) {
        if (canvasState.expandedFlow === id) {
          collapseInlineFlow(true);
          return;
        }
        expandFlowInline(id);
      }

      // Open `id`'s decisions inline within L1. Reveals its scope + file first (so the
      // node is materialized), pins selection, sets the #flow= hash for deep-linkability,
      // updates the header, primes the inspector ONCE, re-renders, and re-focuses the host
      // flow node (renderCanvas replaced the SVG, so its <g> -- and the focus on it -- was
      // destroyed). A flow with no decision nodes is NOT expandable: it would reserve no
      // band and draw nothing, so we just select + inspect it without entering inline mode.
      function expandFlowInline(id) {
        const flow = byId.get(id);
        if (!flow) return;
        const scope = scopeOfFlow(flow);
        if (scope && Object.prototype.hasOwnProperty.call(scopeFlows, scope)) {
          if (canvasState.expandedScope !== scope) canvasState.expandedFiles.clear();
          canvasState.expandedScope = scope;
        }
        canvasState.level = 1;
        canvasState.expandedFiles.add(flow.location.path);
        canvasState.selectedPath = flow.location.path;
        canvasState.selectedFlowId = id;
        LC.mode = "canvas"; // inline L2 stays on the canvas; never flips to "flow".
        // Keep the header in sync even when a flow node is clicked directly on the canvas
        // (shell.js's selectFlow sets it for tree clicks, but a direct node click routes
        // here without going through selectFlow).
        setFlowHeader(flow);
        const expandable = !!(flow.nodes && flow.nodes.length);
        if (expandable) {
          canvasState.expandedFlow = id;
          location.hash = "flow=" + encodeURIComponent(id);
        } else {
          // No decisions: clear any prior inline flow, select-only, no band, no flow-open.
          clearInlineFlow();
          location.hash = canvasState.expandedScope
            ? "scope=" + encodeURIComponent(canvasState.expandedScope)
            : "";
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

      // Clear the inline-flow STATE only (no render). Drops the active inspect/highlight
      // binding since the decision nodes are about to leave the DOM. Returns whether
      // anything was open, so callers can decide whether to re-render.
      function clearInlineFlow() {
        if (!canvasState.expandedFlow) return false;
        canvasState.expandedFlow = null;
        if (LC.setCurrentRender) LC.setCurrentRender(null);
        return true;
      }

      // Collapse the inline sub-graph, restoring the plain L1 layout. When `updateHash`,
      // rewinds the hash to the scope so back/refresh land on L1, not L2. Restores focus to
      // the now-collapsed host flow node (it is still in the DOM as a plain flow node) so an
      // Esc/Enter collapse does not drop the keyboard to <body>.
      function collapseInlineFlow(updateHash) {
        const hostId = canvasState.expandedFlow;
        const hostFlow = hostId ? byId.get(hostId) : null;
        if (!clearInlineFlow()) return;
        if (updateHash) {
          replaceHash(canvasState.expandedScope
            ? "scope=" + encodeURIComponent(canvasState.expandedScope)
            : "");
        }
        const fileToSelect = hostFlow && hostFlow.location && hostFlow.location.path
          ? hostFlow.location.path
          : null;
        if (fileToSelect) {
          selectFile(fileToSelect);
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

      function crumbButton(text, onClick, current) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "crumb" + (current ? " current" : "");
        if (current) button.setAttribute("aria-current", "page");
        button.textContent = text;
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
      //   L1 + inline flow (L2)    -> codebase / scope / file / flow
      //   standalone full-screen   -> codebase / scope / flow (no file; legacy fallback)
      // `inFlow` is the legacy full-screen renderFlow mode; inline L2 stays "canvas" and
      // is detected via state.expandedFlow instead.
      function renderBreadcrumb(state) {
        if (!breadcrumbEl) return;
        breadcrumbEl.replaceChildren();
        const inFlow = LC.mode === "flow";
        const inlineFlow = state.expandedFlow ? byId.get(state.expandedFlow) : null;
        const atRoot = state.level === 0 && !inFlow;
        breadcrumbEl.appendChild(crumbButton("codebase", collapseToL0, atRoot));

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
                  clearInlineFlow();
                  setScope(scope);
                  location.hash = "scope=" + encodeURIComponent(scope);
                  renderCanvas();
                }
              },
              scopeCurrent
            )
          );
        }

        // Inline L2: file crumb (collapses the inline flow, keeps the file open) + flow
        // crumb (current). The file crumb collapses the decisions but leaves the file's
        // sibling flows on the canvas, matching the spec's codebase/scope/file/flow path.
        if (inlineFlow) {
          const path = inlineFlow.location.path;
          breadcrumbEl.appendChild(crumbSeparator());
          const fileCrumb = crumbButton(shortPathLabel(path), () => collapseInlineFlow(true), false);
          fileCrumb.title = path;
          breadcrumbEl.appendChild(fileCrumb);
          breadcrumbEl.appendChild(crumbSeparator());
          breadcrumbEl.appendChild(crumbButton(inlineFlow.name, null, true));
          return;
        }

        if (state.level === 1 && state.selectedPath) {
          breadcrumbEl.appendChild(crumbSeparator());
          const fileCrumb = crumbButton(shortPathLabel(state.selectedPath), null, true);
          fileCrumb.title = state.selectedPath;
          breadcrumbEl.appendChild(fileCrumb);
          return;
        }

        // Legacy standalone full-screen flow crumb (only when renderFlow took the SVG).
        if (inFlow && state.selectedFlowId) {
          const flow = byId.get(state.selectedFlowId);
          if (flow) {
            breadcrumbEl.appendChild(crumbSeparator());
            breadcrumbEl.appendChild(crumbButton(flow.name, null, true));
          }
        }
      }

      // --- Hash dispatch surface (shell.js routeFromHash calls these) --------------

      LC.showL0 = function () {
        canvasState.level = 0;
        canvasState.expandedScope = null;
        canvasState.selectedFlowId = null;
        canvasState.selectedPath = null;
        canvasState.expandedFiles.clear();
        clearInlineFlow();
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
      // Reveals the flow's scope + file and unfolds its decisions in place within L1.
      LC.expandFlowInline = expandFlowInline;
      // Tree-driven focus. Unlike LC.showScope / LC.showPath (used by hash dispatch), these
      // follow the normal user action path and update the hash.
      LC.focusScope = expandScope;
      LC.focusPath = focusPath;
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
            // Switching the pinned scope drops stale file expansions from any prior one.
            if (canvasState.expandedScope !== scope) canvasState.expandedFiles.clear();
            canvasState.expandedScope = scope;
            canvasState.level = 1;
          }
        }
        renderBreadcrumb(canvasState);
      };
      LC.resetCanvas = function () {
        // resetView in canvas mode: re-fit + redraw the current level. When a flow is
        // inline-expanded, also drop its hand-placed decision positions so the sub-graph
        // returns to its automatic layout (mirrors the full-screen reset).
        if (canvasState.expandedFlow && LC.clearFlowPositions) {
          LC.clearFlowPositions(canvasState.expandedFlow);
        }
        renderCanvas();
      };

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
        if (canvasState.expandedFlow) {
          collapseInlineFlow(true);
        } else if (canvasState.level === 1) {
          collapseToL0();
        }
      });
    })();
