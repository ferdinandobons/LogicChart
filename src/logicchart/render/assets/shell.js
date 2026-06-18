
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

    // Shared surface other inlined scripts (tree.js, future panels) bind to. The left
    // rail is owned by tree.js now, so the app shell exposes flow selection here.
    const LC = (window.LC = window.LC || {});
    LC.model = model;
    LC.flows = flows;
    LC.byId = byId;
    // The generated HTML now has one official chart renderer: the typed React runtime.
    // The shell still owns shared selection, rails, tree, source, findings, and toolbar
    // buttons, but it no longer routes users into the retired static renderer.
    LC.mode = "react";

    // --- Shared selection store (Phase 4) ---------------------------------------
    // ONE selection model, ONE accent color. Every surface -- a canvas decision block,
    // a source line, a tree file/flow row, a logical-error row -- both PUBLISHES into
    // this store (via LC.select) and SUBSCRIBES to it (via LC.onSelection) so selecting
    // any one highlights the others. The store holds only ids; each surface maps ids to
    // its own DOM. shell.js drives the canvas highlight (its existing job); panels.js
    // renders the source + errors panels and the tree reflects the active file/flow.
    const selection = {
      path: null,
      flowId: null,
      nodeId: null,
      findingId: null,
      scope: null,
      edgeId: null,
      line: null,
      endLine: null,
    };
    const selectionSubscribers = [];
    // Re-entrancy guard: a subscriber that calls back into select() (e.g. a finding row
    // resolving its flow) must not recurse the notify loop; coalesce to one pass.
    let notifyingSelection = false;
    LC.selection = selection;
    LC.onSelection = function (fn) {
      if (typeof fn === "function") selectionSubscribers.push(fn);
    };
    // Merge a partial selection and notify every surface. Passing a key as `undefined`
    // leaves it untouched; pass `null` to explicitly clear it. Always carries the full
    // resolved selection object to subscribers.
    LC.select = function (partial) {
      partial = partial || {};
      const keys = ["path", "flowId", "nodeId", "findingId", "scope", "edgeId", "line", "endLine"];
      const explicitEdge = Object.prototype.hasOwnProperty.call(partial, "edgeId");
      const clearsEdge = !explicitEdge && keys.some(key =>
        key !== "edgeId" && Object.prototype.hasOwnProperty.call(partial, key)
      );
      keys.forEach(key => {
        if (Object.prototype.hasOwnProperty.call(partial, key) && partial[key] !== undefined) {
          selection[key] = partial[key];
        }
      });
      if (clearsEdge) selection.edgeId = null;
      if (notifyingSelection) return;
      notifyingSelection = true;
      try {
        selectionSubscribers.forEach(fn => {
          try { fn(selection); } catch (_) {}
        });
      } finally {
        notifyingSelection = false;
      }
    };

    const svg =
      document.getElementById("canvas") ||
      document.createElementNS("http://www.w3.org/2000/svg", "svg");
    const rightRail = document.getElementById("rightRail");
    const leftRail = document.getElementById("leftRail");
    const detailButton = document.getElementById("detailButton");
    const detailsClose = document.getElementById("detailsClose");
    const menuButton = document.getElementById("menuButton");
    const typedViewerHost = document.getElementById("typedViewerHost");
    const exportPngButton = document.getElementById("exportPng");
    const exportJpgButton = document.getElementById("exportJpg");
    const railWidths = { left: 312, right: 336 };
    const railConfig = {
      left: {
        css: "--left-rail-width",
        storage: "logicchart-left-rail-width",
        handle: document.getElementById("leftRailResizer"),
        min: 240,
        max: 560,
      },
      right: {
        css: "--right-rail-width",
        storage: "logicchart-right-rail-width",
        handle: document.getElementById("rightRailResizer"),
        min: 280,
        max: 640,
      },
    };
    let activeFlow = null;
    let view = { x: 0, y: 0, width: 1000, height: 800 };
    let drag = null;
    let railResize = null;
    let railRefreshFrame = 0;
    // Per-flow hand-placed node positions: flowId -> Map(nodeId -> {x, y}). Survives
    // navigating away and back within the session.
    const manualPositions = new Map();
    // Element references for the currently rendered flow, for selection highlighting.
    let currentRender = null;
    const FLOW_NODE_HALF_W = 145;
    const FLOW_RECT_HALF_H = 43;
    const FLOW_DECISION_HALF_H = 58;
    const FLOW_META_BOTTOM = 78;
    const FLOW_NODE_HALF_H = 92;
    const FLOW_LAYER_Y = 230;
    const FLOW_SIBLING_X = 360;
    const FLOW_MIN_X_GAP = 330;
    const EDGE_START_CLEARANCE = 30;
    const EDGE_END_CLEARANCE = 10;

    function setCanvasLevel(level) {
      const value = String(level);
      svg.setAttribute("data-level", value);
      document.body.dataset.canvasLevel = value;
    }

    function setLeftRailOpen(open) {
      leftRail.classList.toggle("open", !!open);
      document.body.toggleAttribute("data-nav-open", !!open);
      document.body.toggleAttribute("data-nav-closed", !open);
      syncRailControls();
      scheduleCanvasLayoutRefresh();
    }

    function setRightRailOpen(open) {
      rightRail.classList.toggle("open", !!open);
      document.body.toggleAttribute("data-detail-open", !!open);
      document.body.toggleAttribute("data-detail-closed", !open);
      if (detailButton) {
        detailButton.setAttribute("aria-pressed", open ? "true" : "false");
        detailButton.title = open ? "Hide source and findings" : "Show source and findings";
      }
      syncRailControls();
      scheduleCanvasLayoutRefresh();
    }

    function leftRailOpen() {
      if (window.innerWidth <= 700) return leftRail.classList.contains("open");
      return !document.body.hasAttribute("data-nav-closed");
    }

    function rightRailOpen() {
      if (window.innerWidth <= 1050) return rightRail.classList.contains("open");
      return !document.body.hasAttribute("data-detail-closed");
    }

    function syncRailControls() {
      const navOpen = leftRailOpen();
      const detailOpen = rightRailOpen();
      if (menuButton) {
        menuButton.setAttribute("aria-pressed", navOpen ? "true" : "false");
        menuButton.title = navOpen ? "Hide codebase tree" : "Show codebase tree";
      }
      if (detailButton) {
        detailButton.setAttribute("aria-pressed", detailOpen ? "true" : "false");
        detailButton.title = detailOpen ? "Hide source and findings" : "Show source and findings";
      }
    }

    function eventTargetIsTextInput(event) {
      const target = event.target;
      return !!(target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || ""));
    }

    function railViewportMax(side) {
      const cfg = railConfig[side];
      if (!cfg) return 0;
      if (window.innerWidth <= 1050) return cfg.max;
      const other = side === "left" ? railWidths.right : railWidths.left;
      const maxFromViewport = window.innerWidth - other - 460;
      return Math.max(cfg.min, Math.min(cfg.max, maxFromViewport));
    }

    function clampRailWidth(side, value) {
      const cfg = railConfig[side];
      if (!cfg) return 0;
      const max = railViewportMax(side);
      return Math.min(max, Math.max(cfg.min, Math.round(value)));
    }

    function applyRailWidth(side, value, persist) {
      const cfg = railConfig[side];
      if (!cfg) return;
      const width = clampRailWidth(side, value);
      railWidths[side] = width;
      document.documentElement.style.setProperty(cfg.css, `${width}px`);
      if (cfg.handle) {
        cfg.handle.setAttribute("aria-valuenow", String(width));
        cfg.handle.setAttribute("aria-valuemax", String(railViewportMax(side)));
      }
      if (persist) {
        try { localStorage.setItem(cfg.storage, String(width)); } catch (_) {}
      }
    }

    function loadStoredRailWidths() {
      Object.keys(railConfig).forEach(side => {
        const cfg = railConfig[side];
        let stored = null;
        try { stored = localStorage.getItem(cfg.storage); } catch (_) {}
        const parsed = stored === null ? NaN : Number(stored);
        applyRailWidth(side, Number.isFinite(parsed) ? parsed : railWidths[side], false);
      });
    }

    function scheduleCanvasLayoutRefresh() {
      if (railRefreshFrame) return;
      railRefreshFrame = requestAnimationFrame(() => {
        railRefreshFrame = 0;
        if (LC.refreshCanvasLayout) LC.refreshCanvasLayout();
        else if (LC.updateViewBox) LC.updateViewBox();
      });
    }

    function resizeRailFromPointer(event) {
      if (!railResize) return;
      const dx = event.clientX - railResize.startX;
      const next = railResize.startWidth + (railResize.side === "left" ? dx : -dx);
      applyRailWidth(railResize.side, next, true);
      scheduleCanvasLayoutRefresh();
      event.preventDefault();
    }

    function endRailResize() {
      if (!railResize) return;
      const cfg = railConfig[railResize.side];
      if (cfg && cfg.handle) cfg.handle.removeAttribute("aria-grabbed");
      railResize = null;
      document.body.removeAttribute("data-rail-resizing");
      window.removeEventListener("pointermove", resizeRailFromPointer);
      window.removeEventListener("pointerup", endRailResize);
      window.removeEventListener("pointercancel", endRailResize);
      scheduleCanvasLayoutRefresh();
    }

    function beginRailResize(side, event) {
      if (event.button !== 0) return;
      const cfg = railConfig[side];
      if (!cfg || !cfg.handle) return;
      railResize = { side, startX: event.clientX, startWidth: railWidths[side] };
      document.body.dataset.railResizing = side;
      cfg.handle.setAttribute("aria-grabbed", "true");
      window.addEventListener("pointermove", resizeRailFromPointer);
      window.addEventListener("pointerup", endRailResize);
      window.addEventListener("pointercancel", endRailResize);
      event.preventDefault();
    }

    function resizeRailFromKeyboard(side, event) {
      const cfg = railConfig[side];
      if (!cfg) return;
      let next = railWidths[side];
      if (event.key === "Home") next = cfg.min;
      else if (event.key === "End") next = railViewportMax(side);
      else if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
        const physical = event.key === "ArrowRight" ? 1 : -1;
        next += (side === "left" ? physical : -physical) * 24;
      } else {
        return;
      }
      applyRailWidth(side, next, true);
      scheduleCanvasLayoutRefresh();
      event.preventDefault();
    }

    function fitRailsToViewport() {
      applyRailWidth("left", railWidths.left, false);
      applyRailWidth("right", railWidths.right, false);
    }

    function initRailResizers() {
      Object.keys(railConfig).forEach(side => {
        const cfg = railConfig[side];
        if (!cfg.handle) return;
        cfg.handle.addEventListener("pointerdown", event => beginRailResize(side, event));
        cfg.handle.addEventListener("keydown", event => resizeRailFromKeyboard(side, event));
      });
      window.addEventListener("resize", () => {
        fitRailsToViewport();
        syncRailControls();
        scheduleCanvasLayoutRefresh();
      });
    }

    loadStoredRailWidths();
    initRailResizers();
    setRightRailOpen(false);
    syncRailControls();

    document.getElementById("flowCount").textContent = flows.length;
    document.getElementById("entryCount").textContent = flows.filter(item => item.is_entrypoint).length;
    document.getElementById("findingCount").textContent = findings.length;

    function headerFlowKind(flow) {
      return `${flow.entry_kind} · ${flow.language} · ${flow.framework}`;
    }

    function setHeaderFlow(flow) {
      activeFlow = flow || null;
      if (!flow) return;
      document.getElementById("flowTitle").textContent = flow.name;
      document.getElementById("flowKind").textContent = headerFlowKind(flow);
    }

    function setHeaderScope(scope) {
      activeFlow = null;
      document.getElementById("flowTitle").textContent = scope || "codebase";
      document.getElementById("flowKind").textContent = "scope";
    }

    function setHeaderRoot() {
      activeFlow = null;
      document.getElementById("flowTitle").textContent = "Codebase";
      document.getElementById("flowKind").textContent = "progressive flowchart";
    }

    function selectionForFlow(flow) {
      return {
        edgeId: null,
        endLine: flow.location?.end_line ?? flow.location?.start_line ?? null,
        findingId: null,
        flowId: flow.id,
        line: flow.location?.start_line ?? null,
        nodeId: null,
        path: flow.location?.path || null,
        scope: null,
      };
    }

    // Entry points first, then by name. Shared so the tree lists a file's flows in the
    // same order the old flat list used.
    LC.sortFlows = list =>
      [...list].sort(
        (a, b) => Number(b.is_entrypoint) - Number(a.is_entrypoint) || a.name.localeCompare(b.name)
      );

    // Updates the header + the active-flow bookkeeping shared by the tree and details.
    // Rendering belongs to the typed React runtime; the shell only delegates selection and
    // keeps the surrounding HTML controls synchronized.
    function selectFlow(flowId) {
      const flow = byId.get(flowId);
      if (!flow) return;
      setHeaderFlow(flow);
      const typed = activeTypedViewer();
      if (typed && typeof typed.selectFlow === "function") {
        typed.selectFlow(flow.id);
      } else {
        location.hash = "flow=" + encodeURIComponent(flow.id);
        LC.select(selectionForFlow(flow));
      }
      // On phones the tree is a drawer, so a selection should clear the canvas. On
      // desktop/tablet the tree is working context; keep it open unless the user closes it.
      if (window.innerWidth <= 700) setLeftRailOpen(false);
      // Let other inlined scripts (e.g. tree.js) reflect the active flow.
      if (window.LC.onFlowSelected) window.LC.onFlowSelected(flow);
    }

    function flowLayoutNodes(flow, opts) {
      opts = opts || {};
      return (flow.nodes || []).filter(node => !(opts.omitEntry && node.kind === "entry"));
    }

    function flowLayers(nodes, edges, incoming, outgoing, order) {
      const nodeById = new Map(nodes.map(node => [node.id, node]));
      const indegree = new Map(nodes.map(node => [node.id, 0]));
      const layerById = new Map(nodes.map(node => [node.id, 0]));
      edges.forEach(edge => {
        if (edge.source === edge.target) return;
        indegree.set(edge.target, (indegree.get(edge.target) || 0) + 1);
      });

      const queue = nodes
        .filter(node => (indegree.get(node.id) || 0) === 0)
        .sort((a, b) => order.get(a.id) - order.get(b.id));
      const visited = new Set();

      while (queue.length) {
        const node = queue.shift();
        if (!node || visited.has(node.id)) continue;
        visited.add(node.id);
        (outgoing.get(node.id) || []).forEach(edge => {
          const nextLayer = (layerById.get(node.id) || 0) + 1;
          layerById.set(edge.target, Math.max(layerById.get(edge.target) || 0, nextLayer));
          indegree.set(edge.target, (indegree.get(edge.target) || 0) - 1);
          if ((indegree.get(edge.target) || 0) === 0) {
            const target = nodeById.get(edge.target);
            if (target) queue.push(target);
          }
        });
        queue.sort((a, b) => order.get(a.id) - order.get(b.id));
      }

      // Cycles/backedges are valid in real control flow. Keep those nodes visible by
      // assigning a stable fallback layer from any already-known parents instead of assuming
      // the payload was topologically sorted.
      nodes.forEach(node => {
        if (visited.has(node.id)) return;
        const parentLayers = (incoming.get(node.id) || [])
          .map(edge => layerById.get(edge.source))
          .filter(value => Number.isFinite(value));
        if (parentLayers.length) {
          layerById.set(node.id, Math.max(layerById.get(node.id) || 0, Math.max(...parentLayers) + 1));
        }
      });

      return layerById;
    }

    function layoutFlow(flow, opts) {
      opts = opts || {};
      const nodes = flowLayoutNodes(flow, opts);
      const visibleIds = new Set(nodes.map(node => node.id));
      const order = new Map(nodes.map((node, index) => [node.id, index]));
      const incoming = new Map(nodes.map(node => [node.id, []]));
      const outgoing = new Map(nodes.map(node => [node.id, []]));
      const edges = (flow.edges || []).filter(edge =>
        visibleIds.has(edge.source) && visibleIds.has(edge.target)
      );
      edges.forEach(edge => incoming.get(edge.target)?.push(edge));
      edges.forEach(edge => outgoing.get(edge.source)?.push(edge));
      const layerById = flowLayers(nodes, edges, incoming, outgoing, order);
      const positions = new Map();
      const layerCounts = new Map();

      [...nodes]
        .sort((a, b) =>
          (layerById.get(a.id) || 0) - (layerById.get(b.id) || 0) ||
          order.get(a.id) - order.get(b.id)
        )
        .forEach(node => {
          const parents = (incoming.get(node.id) || []).filter(edge => positions.has(edge.source));
          const layer = layerById.get(node.id) || 0;
          let x = 0;
          if (parents.length) {
            const parentXs = parents.map(edge => positions.get(edge.source)?.x || 0);
            x = parentXs.reduce((sum, value) => sum + value, 0) / parentXs.length;
            if (parents.length === 1) {
              const parentEdge = parents[0];
              const siblings = outgoing.get(parentEdge.source) || [];
              if (siblings.length > 1) {
                const siblingIndex = siblings.findIndex(edge => edge.target === node.id);
                const centeredIndex = siblingIndex - (siblings.length - 1) / 2;
                x = (positions.get(parentEdge.source)?.x || 0) + centeredIndex * FLOW_SIBLING_X;
              } else {
                const branch = parentEdge.label?.toLowerCase();
                if (["yes", "success"].includes(branch)) x -= FLOW_SIBLING_X / 2;
                if (["no", "error"].includes(branch)) x += FLOW_SIBLING_X / 2;
              }
            }
          }
          const occupied = layerCounts.get(layer) || [];
          while (occupied.some(value => Math.abs(value - x) < FLOW_MIN_X_GAP)) x += FLOW_SIBLING_X;
          occupied.push(x);
          layerCounts.set(layer, occupied);
          positions.set(node.id, { x, y: layer * FLOW_LAYER_Y, layer, order: order.get(node.id) || 0 });
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
      if (!values.length) {
        return { positions, bounds: { minX: 0, maxX: 0, minY: 0, maxY: 0 }, nodes, edges };
      }
      const minX = Math.min(...values.map(item => item.x), 0);
      const maxX = Math.max(...values.map(item => item.x), 0);
      const minY = Math.min(...values.map(item => item.y), 0);
      const maxY = Math.max(...values.map(item => item.y), 0);
      return { positions, bounds: { minX, maxX, minY, maxY }, nodes, edges };
    }

    function nodeHalfHeight(kind) {
      return kind === "decision" ? FLOW_DECISION_HALF_H : FLOW_RECT_HALF_H;
    }

    function horizontalLabelX(startX, endX) {
      const dx = endX - startX;
      if (Math.abs(dx) < 24) return startX + 7;
      return startX + dx * 0.34;
    }

    // Single source for an edge's orthogonal path + label anchor, reused on first render
    // and live during a node drag so connected edges follow. The path is intentionally
    // flowchart-like: leave through a lower port, travel on a horizontal branch lane, then
    // enter the target from above.
    function edgeGeometry(start, end, startKind, endKind) {
      const startPortY = start.y + nodeHalfHeight(startKind);
      const endPortY = end.y - nodeHalfHeight(endKind);
      const verticalRoom = endPortY - startPortY;
      const branchY = verticalRoom > EDGE_START_CLEARANCE + EDGE_END_CLEARANCE + 20
        ? startPortY + EDGE_START_CLEARANCE
        : startPortY + verticalRoom / 2;
      const labelIsExitChip = startKind === "decision";
      const curveY = Math.max(90, Math.abs(endPortY - startPortY) * 0.55);
      return {
        d: `M ${start.x} ${startPortY} L ${start.x} ${branchY} L ${end.x} ${branchY} L ${end.x} ${endPortY}`,
        focusD: `M ${start.x} ${startPortY} C ${start.x} ${startPortY + curveY}, ${end.x} ${endPortY - curveY}, ${end.x} ${endPortY}`,
        points: [
          { x: start.x, y: startPortY },
          { x: start.x, y: branchY },
          { x: end.x, y: branchY },
          { x: end.x, y: endPortY },
        ],
        labelX: labelIsExitChip ? horizontalLabelX(start.x, end.x) : (start.x + end.x) / 2 + 7,
        labelY: branchY - 8,
        exitChip: labelIsExitChip,
      };
    }

    function bindEdgeActivationParts(group, activate) {
      if (!group || !activate) return;
      group.querySelectorAll("*").forEach(part => {
        part.addEventListener("click", activate);
      });
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

    function edgeLabel(text, geometry) {
      const value = String(text);
      const width = Math.max(30, value.length * 7 + 18);
      const group = svgEl("g");
      group.setAttribute("class", `edge-label-wrap${geometry.exitChip ? " branch-exit-chip" : ""}`);
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

    function nodeKindBadge(kind) {
      const labelText = kind === "terminal" ? "outcome" : String(kind || "node");
      const width = Math.max(48, labelText.length * 6 + 16);
      const group = svgEl("g");
      group.setAttribute("class", "node-kind-badge");
      group.setAttribute("transform", "translate(0 -30)");
      const bg = svgEl("rect");
      bg.setAttribute("x", String(-width / 2));
      bg.setAttribute("y", "-9");
      bg.setAttribute("width", String(width));
      bg.setAttribute("height", "18");
      bg.setAttribute("rx", "9");
      const text = svgEl("text");
      text.setAttribute("text-anchor", "middle");
      text.setAttribute("y", "4");
      text.textContent = labelText;
      group.append(bg, text);
      return group;
    }

    // Decision-flow defs (shadow filters + arrow marker). The visible chart is rendered
    // by the React runtime; these helpers remain for shared source/export compatibility.
    function flowDefs() {
      const defs = svgEl("defs");
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

    // Reusable decision-graph renderer retained for shared source/export compatibility.
    // It draws `flow`'s nodes/edges into a fresh <g> layer and returns it without touching
    // the SVG, the global `view`, or data-level.
    //
    // opts.originX/originY translate the whole sub-graph (layoutFlow is origin-relative;
    // the caller places it). opts.spine adds the decision spine (full-screen only). Drag
    // and the bidirectional highlight keep working in both modes: drag uses the shared
    // `view` scale (same SVG world units inline or full), and the returned record is set
    // as `currentRender` so inspectNode -> highlightNode lights up incident edges/nodes.
    function drawFlowGraph(flow, opts) {
      opts = opts || {};
      const originX = opts.originX || 0;
      const originY = opts.originY || 0;
      const { positions, bounds, nodes, edges } = layoutFlow(flow, opts);
      const layer = svgEl("g");
      if (opts.layerClass) layer.setAttribute("class", opts.layerClass);

      if (opts.spine) {
        const spine = svgEl("line");
        spine.setAttribute("class", "decision-spine");
        spine.setAttribute("x1", String(originX));
        spine.setAttribute("y1", String(originY - 20));
        spine.setAttribute("x2", String(originX));
        spine.setAttribute("y2", String(originY + bounds.maxY + 100));
        layer.appendChild(spine);
      }

      const at = id => {
        const p = positions.get(id);
        return p ? { x: p.x + originX, y: p.y + originY } : null;
      };
      const flowNodeById = new Map(nodes.map(node => [node.id, node]));
      const edgeRecordId = edge => edge.id || `${edge.source}->${edge.target}`;

      // Keep edge element references per node so dragging a block re-routes its edges live,
      // and a flat list so selecting a node can highlight its incident edges.
      const nodeEdges = new Map(nodes.map(node => [node.id, []]));
      const edgeRecords = [];
      const edgeLayer = svgEl("g");
      const edgePathLayer = svgEl("g");
      const edgeLabelLayer = svgEl("g");
      edges.forEach(edge => {
        const start = at(edge.source);
        const end = at(edge.target);
        if (!start || !end) return;
        const sourceNode = flowNodeById.get(edge.source);
        const targetNode = flowNodeById.get(edge.target);
        const geometry = edgeGeometry(start, end, sourceNode?.kind, targetNode?.kind);
        let hit = svgEl("g");
        let label = null;
        const activateEdge = event => {
          event.stopPropagation();
          if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
          if (LC.openDetails) LC.openDetails();
          LC.select({
            flowId: flow.id,
            path: flow.location.path,
            nodeId: null,
            findingId: null,
            edgeId: edgeRecordId(edge),
            line: flow.location.start_line || null,
            endLine: flow.location.end_line || flow.location.start_line || null,
          });
        };
        hit.setAttribute("class", "edge-hit");
        setEdgeHitGeometry(hit, geometry, activateEdge);
        hit.setAttribute("data-edge-id", edgeRecordId(edge));
        hit.setAttribute("data-source-node-id", edge.source);
        hit.setAttribute("data-target-node-id", edge.target);
        const path = svgEl("path");
        path.setAttribute("class", "edge");
        path.setAttribute("d", geometry.d);
        path.setAttribute("tabindex", "0");
        path.setAttribute("role", "button");
        path.setAttribute("aria-label", `link from ${sourceNode?.label || edge.source} to ${targetNode?.label || edge.target}`);
        path.setAttribute("data-edge-id", edgeRecordId(edge));
        path.setAttribute("data-source-node-id", edge.source);
        path.setAttribute("data-target-node-id", edge.target);
        edgePathLayer.appendChild(path);
        const focusPath = svgEl("path");
        focusPath.setAttribute("class", "edge-focus");
        focusPath.setAttribute("d", geometry.focusD || geometry.d);
        edgePathLayer.appendChild(focusPath);
        edgePathLayer.appendChild(hit);
        if (edge.label) {
          label = edgeLabel(edge.label, geometry);
          label.setAttribute("role", "button");
          label.setAttribute("tabindex", "0");
          label.setAttribute("data-edge-id", edgeRecordId(edge));
          label.setAttribute("data-source-node-id", edge.source);
          label.setAttribute("data-target-node-id", edge.target);
          label.setAttribute("aria-label", `link ${edge.label} from ${sourceNode?.label || edge.source} to ${targetNode?.label || edge.target}`);
          edgeLabelLayer.appendChild(label);
        }
        const record = { edge, flow, hit, path, focusPath, label, activateEdge };
        hit.addEventListener("click", activateEdge);
        path.addEventListener("click", activateEdge);
        path.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activateEdge(event);
          }
        });
        if (label) {
          label.addEventListener("click", activateEdge);
          bindEdgeActivationParts(label, activateEdge);
          label.addEventListener("keydown", event => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              activateEdge(event);
            }
          });
        }
        edgeRecords.push(record);
        nodeEdges.get(edge.source)?.push(record);
        nodeEdges.get(edge.target)?.push(record);
      });
      edgeLayer.append(edgePathLayer, edgeLabelLayer);
      layer.appendChild(edgeLayer);

      function rerouteFrom(nodeId) {
        (nodeEdges.get(nodeId) || []).forEach(({ edge, hit, path, focusPath, label, activateEdge }) => {
          const start = at(edge.source);
          const end = at(edge.target);
          if (!start || !end) return;
          const sourceNode = flowNodeById.get(edge.source);
          const targetNode = flowNodeById.get(edge.target);
          const geometry = edgeGeometry(start, end, sourceNode?.kind, targetNode?.kind);
          setEdgeHitGeometry(hit, geometry, activateEdge);
          path.setAttribute("d", geometry.d);
          if (focusPath) focusPath.setAttribute("d", geometry.focusD || geometry.d);
          if (label) label.setAttribute("transform", `translate(${geometry.labelX} ${geometry.labelY})`);
        });
      }

      const nodeLayer = svgEl("g");
      const nodeGroups = new Map();
      const nodeDraggable = opts.draggable !== false;
      nodes.forEach(node => {
        const position = positions.get(node.id);
        // Live world-space position of this node (origin-translated). Drag mutates it.
        const place = { x: position.x + originX, y: position.y + originY };
        const group = svgEl("g");
        nodeGroups.set(node.id, group);
        group.setAttribute(
          "class",
          `node ${node.kind}${nodeDraggable ? "" : " static"}${findingsByNode.has(node.id) ? " has-finding" : ""}`
        );
        group.setAttribute("transform", `translate(${place.x} ${place.y})`);
        group.setAttribute("tabindex", "0");
        group.setAttribute("role", "button");
        group.setAttribute("aria-label", `${node.kind}: ${node.label}`);
        function activateNode() {
          const targetFlow = node.kind === "call" && node.metadata
            ? node.metadata.target_flow
            : null;
          if (targetFlow && byId.has(targetFlow) && LC.expandCallTarget) {
            LC.expandCallTarget(flow.id, targetFlow, node.id);
          } else {
            inspectNode(flow, node);
          }
        }
        // Drag to rearrange the block in both full-screen and inline decision charts.
        // A renderer may explicitly pass draggable:false for a read-only preview.
        if (nodeDraggable) {
          let nodeDrag = null;
          const moveNodeDrag = event => {
            if (!nodeDrag) return;
            const dx = (event.clientX - nodeDrag.x) * nodeDrag.scaleX;
            const dy = (event.clientY - nodeDrag.y) * nodeDrag.scaleY;
            nodeDrag.moved = Math.max(nodeDrag.moved, Math.abs(dx) + Math.abs(dy));
            place.x = nodeDrag.ox + dx;
            place.y = nodeDrag.oy + dy;
            // positions is origin-relative; mirror the drag back so rerouteFrom (which
            // re-adds the origin) and any later override store both stay consistent.
            position.x = place.x - originX;
            position.y = place.y - originY;
            group.setAttribute("transform", `translate(${place.x} ${place.y})`);
            rerouteFrom(node.id);
          };
          const endNodeDrag = event => {
            if (!nodeDrag) return;
            group.classList.remove("dragging");
            window.removeEventListener("pointermove", moveNodeDrag);
            window.removeEventListener("pointerup", endNodeDrag);
            window.removeEventListener("pointercancel", endNodeDrag);
            try { group.releasePointerCapture(event.pointerId); } catch (_) {}
            if (nodeDrag.moved < 4 && event.type === "pointerup") {
              activateNode();
            } else {
              const store = manualPositions.get(flow.id) || new Map();
              store.set(node.id, { x: position.x, y: position.y });
              manualPositions.set(flow.id, store);
            }
            nodeDrag = null;
          };
          const startNodeDrag = event => {
            if (event.button !== 0) return;
            event.stopPropagation();
            if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
            nodeDrag = {
              x: event.clientX,
              y: event.clientY,
              ox: place.x,
              oy: place.y,
              scaleX: view.width / svg.clientWidth,
              scaleY: view.height / svg.clientHeight,
              moved: 0
            };
            group.classList.add("dragging");
            window.addEventListener("pointermove", moveNodeDrag);
            window.addEventListener("pointerup", endNodeDrag);
            window.addEventListener("pointercancel", endNodeDrag);
            group.setPointerCapture(event.pointerId);
          };
          group.addEventListener("pointerdown", startNodeDrag);
        } else {
          group.addEventListener("click", event => {
            event.stopPropagation();
            if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
            activateNode();
          });
        }
        group.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activateNode();
          }
        });
        const shape = nodeShape(node.kind);
        shape.setAttribute("class", "shape");
        group.appendChild(shape);
        group.appendChild(nodeKindBadge(node.kind));
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
        meta.setAttribute("y", String(node.kind === "decision" ? FLOW_META_BOTTOM : 62));
        meta.textContent = `${node.location.path}:${node.location.start_line}`;
        group.appendChild(meta);
        nodeLayer.appendChild(group);
      });
      layer.appendChild(nodeLayer);

      // World-space bounds of the drawn sub-graph, so the caller can reserve room / fit.
      const worldBounds = {
        minX: bounds.minX + originX - FLOW_NODE_HALF_W,
        maxX: bounds.maxX + originX + FLOW_NODE_HALF_W,
        minY: bounds.minY + originY - FLOW_NODE_HALF_H,
        maxY: bounds.maxY + originY + FLOW_NODE_HALF_H,
      };
      return { layer, nodeGroups, edgeRecords, bounds: worldBounds };
    }

    // Bind a freshly drawn decision graph as the active highlight target.
    function setCurrentRender(render) {
      currentRender = render ? { nodeGroups: render.nodeGroups, edgeRecords: render.edgeRecords } : null;
    }

    function renderFlow(flow) {
      svg.replaceChildren();
      // The L2 decision chart is canvas level 2; keep the level attribute correct so a
      // reader (or test) can tell which level is on screen (L0 scopes / L1 flows / L2).
      setCanvasLevel("2");
      if (!flow.nodes.length) {
        document.getElementById("emptyState").style.display = "grid";
        currentRender = null;
        return;
      }
      document.getElementById("emptyState").style.display = "none";

      svg.appendChild(flowDefs());
      const render = drawFlowGraph(flow, { spine: true });
      const bounds = render.bounds;
      const padding = 170;
      const top = Math.min(-90, bounds.minY - 70);
      view = {
        x: bounds.minX - padding,
        y: top,
        width: Math.max(760, bounds.maxX - bounds.minX + padding * 2),
        height: Math.max(600, bounds.maxY - top + 250)
      };
      updateViewBox();
      svg.appendChild(render.layer);
      currentRender = { nodeGroups: render.nodeGroups, edgeRecords: render.edgeRecords };
    }

    function clearHighlight() {
      if (!currentRender) return;
      currentRender.nodeGroups.forEach(group =>
        group.classList.remove("selected", "dimmed", "edge-source", "edge-target")
      );
      currentRender.edgeRecords.forEach(record => {
        if (record.hit) record.hit.classList.remove("selected-link", "dimmed");
        record.path.classList.remove("incident", "selected-link", "dimmed", "focus-hidden");
        if (record.focusPath) record.focusPath.classList.remove("selected-link");
        if (record.label) record.label.classList.remove("selected-link", "dimmed");
      });
    }

    function highlightEdge(targetRecord) {
      if (!currentRender) return;
      currentRender.edgeRecords.forEach(record => {
        const selected = record === targetRecord;
        if (record.hit) {
          record.hit.classList.toggle("selected-link", selected);
          record.hit.classList.toggle("dimmed", !selected);
        }
        record.path.classList.remove("selected-link", "incident");
        record.path.classList.toggle("focus-hidden", selected);
        record.path.classList.toggle("dimmed", !selected);
        if (record.focusPath) {
          record.focusPath.classList.toggle("selected-link", selected);
        }
        if (record.label) {
          record.label.classList.toggle("selected-link", selected);
          record.label.classList.toggle("dimmed", !selected);
        }
      });
      const endpoints = new Set([targetRecord.edge.source, targetRecord.edge.target]);
      currentRender.nodeGroups.forEach((group, id) => {
        group.classList.toggle("selected", endpoints.has(id));
        group.classList.toggle("dimmed", !endpoints.has(id));
        group.classList.toggle("edge-source", id === targetRecord.edge.source);
        group.classList.toggle("edge-target", id === targetRecord.edge.target);
      });
    }

    function highlightNode(nodeId) {
      if (!currentRender) return;
      const connected = new Set([nodeId]);
      currentRender.edgeRecords.forEach(record => {
        const incident = record.edge.source === nodeId || record.edge.target === nodeId;
        if (record.hit) {
          record.hit.classList.remove("selected-link");
          record.hit.classList.toggle("dimmed", !incident);
        }
        record.path.classList.remove("selected-link", "focus-hidden");
        if (record.focusPath) record.focusPath.classList.remove("selected-link");
        record.path.classList.toggle("incident", incident);
        record.path.classList.toggle("dimmed", !incident);
        if (record.label) {
          record.label.classList.remove("selected-link");
          record.label.classList.toggle("dimmed", !incident);
        }
        if (incident) { connected.add(record.edge.source); connected.add(record.edge.target); }
      });
      currentRender.nodeGroups.forEach((group, id) => {
        group.classList.toggle("selected", id === nodeId);
        group.classList.toggle("dimmed", !connected.has(id));
        group.classList.remove("edge-source", "edge-target");
      });
    }

    function decisionEdgeRecordFromElement(element) {
      if (!currentRender || !element || !element.closest) return null;
      if (element.closest(".progressive-call-hit, .progressive-call-edge, .progressive-call-label")) {
        return null;
      }
      const target = element.closest(".edge-hit, .edge, .edge-label-wrap");
      if (!target) return null;
      const id = target.getAttribute("data-edge-id");
      const source = target.getAttribute("data-source-node-id");
      const destination = target.getAttribute("data-target-node-id");
      return currentRender.edgeRecords.find(item => {
        const recordId = item.edge.id || `${item.edge.source}->${item.edge.target}`;
        return (id && recordId === id) ||
          (source && destination && item.edge.source === source && item.edge.target === destination);
      }) || null;
    }

    function activateDecisionEdgeRecord(event) {
      const record = decisionEdgeRecordFromElement(event.target);
      if (!record || !record.flow) return;
      event.preventDefault();
      event.stopPropagation();
      if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
      if (LC.openDetails) LC.openDetails();
      LC.select({
        flowId: record.flow.id,
        path: record.flow.location.path,
        nodeId: null,
        findingId: null,
        edgeId: record.edge.id || `${record.edge.source}->${record.edge.target}`,
        line: record.flow.location.start_line || null,
        endLine: record.flow.location.end_line || record.flow.location.start_line || null,
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

    // Inspecting a flow: clear the per-node canvas highlight (no single node is active)
    // and publish the flow selection so the Source + Logical-errors panels (panels.js)
    // and the tree reflect it. The right column is now Source/Errors (panels.js owns the
    // DOM); shell.js keeps only its canvas-highlight responsibility plus publishing the
    // shared selection. nodeId is cleared so the source panel shows the whole flow snippet.
    function inspectFlow(flow) {
      if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
      clearHighlight();
      setRightRailOpen(true);
      LC.select({
        flowId: flow.id,
        path: flow.location.path,
        nodeId: null,
        findingId: null,
        line: flow.location.start_line || null,
        endLine: flow.location.end_line || flow.location.start_line || null,
      });
    }

    // Inspecting a decision/call node: publish the node selection. The block highlight is
    // applied by the single shared-selection subscriber below (one accent path, not
    // duplicated here); the source panel highlights the node's source line(s) and the
    // errors panel lists the node's findings, both via the same store.
    function inspectNode(flow, node) {
      if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
      setRightRailOpen(true);
      LC.select({
        flowId: flow.id,
        nodeId: node.id,
        path: node.location.path,
        findingId: null,
        line: node.location.start_line || null,
        endLine: node.location.end_line || node.location.start_line || null,
      });
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

    function safeDecodeHashValue(value) {
      try {
        return decodeURIComponent(value);
      } catch (_) {
        return null;
      }
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

    function activeTypedViewer() {
      if (document.body.dataset.runtime !== "react") return null;
      const viewer = window.logicchartTypedViewer;
      return viewer && typeof viewer === "object" ? viewer : null;
    }

    function cssVar(name, fallback) {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      return value || fallback;
    }

    function canvasContentBounds() {
      const nodes = [...svg.children].filter(child => child.tagName.toLowerCase() !== "defs");
      if (!nodes.length) {
        return { x: view.x, y: view.y, width: view.width, height: view.height };
      }
      const hitboxes = [...svg.querySelectorAll(".edge-hit")];
      const previousDisplays = hitboxes.map(node => node.style.display);
      hitboxes.forEach(node => {
        node.style.display = "none";
      });
      let minX = Infinity;
      let minY = Infinity;
      let maxX = -Infinity;
      let maxY = -Infinity;
      try {
        nodes.forEach(node => {
          if (node.classList && node.classList.contains("edge-hit")) return;
          try {
            const box = node.getBBox();
            if (!box || !Number.isFinite(box.width) || !Number.isFinite(box.height)) return;
            minX = Math.min(minX, box.x);
            minY = Math.min(minY, box.y);
            maxX = Math.max(maxX, box.x + box.width);
            maxY = Math.max(maxY, box.y + box.height);
          } catch (_) {}
        });
      } finally {
        hitboxes.forEach((node, index) => {
          node.style.display = previousDisplays[index] || "";
        });
      }
      if (!Number.isFinite(minX) || !Number.isFinite(minY)) {
        return { x: view.x, y: view.y, width: view.width, height: view.height };
      }
      const padding = 90;
      return {
        x: minX - padding,
        y: minY - padding,
        width: Math.max(1, maxX - minX + padding * 2),
        height: Math.max(1, maxY - minY + padding * 2),
      };
    }

    function exportCurrentCanvas(format) {
      const typed = activeTypedViewer();
      if (typed && typeof typed.exportImage === "function") {
        typed.exportImage(format);
        return;
      }
      const bounds = canvasContentBounds();
      const preferredScale = 2;
      const maxPixelSide = 16384;
      const maxPixelArea = 96000000;
      const boundedWidth = Math.max(1, bounds.width);
      const boundedHeight = Math.max(1, bounds.height);
      const scale = Math.max(
        0.1,
        Math.min(
          preferredScale,
          maxPixelSide / Math.max(boundedWidth, boundedHeight),
          Math.sqrt(maxPixelArea / (boundedWidth * boundedHeight)),
        ),
      );
      const width = Math.max(1, Math.round(bounds.width * scale));
      const height = Math.max(1, Math.round(bounds.height * scale));
      const clone = svg.cloneNode(true);
      clone.setAttribute("xmlns", "http://www.w3.org/2000/svg");
      clone.setAttribute("width", String(width));
      clone.setAttribute("height", String(height));
      clone.setAttribute("viewBox", `${bounds.x} ${bounds.y} ${bounds.width} ${bounds.height}`);
      clone.setAttribute("data-theme", document.documentElement.dataset.theme || "dark");
      clone.querySelectorAll(".edge-hit").forEach(node => node.remove());

      const style = document.createElementNS("http://www.w3.org/2000/svg", "style");
      style.textContent = document.querySelector("style")?.textContent || "";
      clone.prepend(style);
      const background = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      background.setAttribute("x", String(bounds.x));
      background.setAttribute("y", String(bounds.y));
      background.setAttribute("width", String(bounds.width));
      background.setAttribute("height", String(bounds.height));
      background.setAttribute("fill", cssVar("--paper", "#ffffff"));
      clone.insertBefore(background, style.nextSibling);

      const serialized = new XMLSerializer().serializeToString(clone);
      const svgBlob = new Blob([serialized], { type: "image/svg+xml;charset=utf-8" });
      const imageUrl = URL.createObjectURL(svgBlob);
      const image = new Image();
      image.onload = () => {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          URL.revokeObjectURL(imageUrl);
          return;
        }
        ctx.fillStyle = cssVar("--paper", "#ffffff");
        ctx.fillRect(0, 0, width, height);
        ctx.drawImage(image, 0, 0, width, height);
        URL.revokeObjectURL(imageUrl);
        const mime = format === "jpg" ? "image/jpeg" : "image/png";
        canvas.toBlob(blob => {
          if (!blob) return;
          const link = document.createElement("a");
          const stamp = new Date().toISOString().replace(/[:.]/g, "-");
          link.download = `logicchart-flowchart-${stamp}.${format}`;
          link.href = URL.createObjectURL(blob);
          document.body.appendChild(link);
          link.click();
          link.remove();
          setTimeout(() => URL.revokeObjectURL(link.href), 1000);
        }, mime, format === "jpg" ? 0.92 : undefined);
      };
      image.onerror = () => URL.revokeObjectURL(imageUrl);
      image.src = imageUrl;
    }

    function zoom(factor) {
      const typed = activeTypedViewer();
      if (typed && typeof typed.zoom === "function") {
        typed.zoom(factor);
        return;
      }
      const nextWidth = view.width * factor;
      const nextHeight = view.height * factor;
      view.x += (view.width - nextWidth) / 2;
      view.y += (view.height - nextHeight) / 2;
      view.width = nextWidth;
      view.height = nextHeight;
      updateViewBox();
    }

    function fitView() {
      const typed = activeTypedViewer();
      if (typed && typeof typed.fitView === "function") {
        typed.fitView();
        return;
      }
      view = canvasContentBounds();
      updateViewBox();
    }

    function expandView() {
      const typed = activeTypedViewer();
      if (typed && typeof typed.expandAll === "function") {
        typed.expandAll();
      }
    }

    document.getElementById("resetView").addEventListener("click", () => {
      const typed = activeTypedViewer();
      if (typed && typeof typed.resetView === "function") {
        typed.resetView();
        return;
      }
      if (LC.mode === "flow") {
        if (!activeFlow) return;
        manualPositions.delete(activeFlow.id);  // discard hand-placed positions, re-layout
        renderFlow(activeFlow);
      }
    });
    document.getElementById("expandView").addEventListener("click", expandView);
    document.getElementById("fitView").addEventListener("click", fitView);
    document.getElementById("zoomOut").addEventListener("click", () => zoom(1.22));
    document.getElementById("zoomIn").addEventListener("click", () => zoom(.82));
    if (exportPngButton) {
      exportPngButton.addEventListener("click", () => exportCurrentCanvas("png"));
    }
    if (exportJpgButton) {
      exportJpgButton.addEventListener("click", () => exportCurrentCanvas("jpg"));
    }
    if (menuButton) {
      menuButton.addEventListener("click", () => setLeftRailOpen(!leftRailOpen()));
    }
    if (detailButton) {
      detailButton.addEventListener("click", () => setRightRailOpen(!rightRailOpen()));
    }
    if (detailsClose) {
      detailsClose.addEventListener("click", () => setRightRailOpen(false));
    }
    document.addEventListener("keydown", event => {
      if (event.key !== "Escape" || eventTargetIsTextInput(event)) return;
      if (rightRailOpen()) {
        setRightRailOpen(false);
        event.stopImmediatePropagation();
        return;
      }
      if (leftRailOpen()) {
        setLeftRailOpen(false);
        event.stopImmediatePropagation();
      }
    });

    svg.addEventListener("wheel", event => {
      event.preventDefault();
      zoom(event.deltaY > 0 ? 1.08 : .92);
    }, { passive: false });
    if (typedViewerHost) {
      typedViewerHost.addEventListener("wheel", event => {
        const typed = activeTypedViewer();
        if (!typed || typeof typed.zoom !== "function") return;
        event.preventDefault();
        typed.zoom(event.deltaY > 0 ? 1.08 : .92);
      }, { passive: false });
    }
    svg.addEventListener("pointerdown", activateDecisionEdgeRecord, true);
    svg.addEventListener("mousedown", activateDecisionEdgeRecord, true);
    svg.addEventListener("click", activateDecisionEdgeRecord, true);
    document.addEventListener("pointerdown", activateDecisionEdgeRecord, true);
    document.addEventListener("mousedown", activateDecisionEdgeRecord, true);
    document.addEventListener("click", activateDecisionEdgeRecord, true);
    svg.addEventListener("keydown", event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const record = decisionEdgeRecordFromElement(event.target);
      if (!record) return;
      event.preventDefault();
      activateDecisionEdgeRecord(event);
    }, true);
    document.addEventListener("keydown", event => {
      if (event.key !== "Enter" && event.key !== " ") return;
      const record = decisionEdgeRecordFromElement(event.target);
      if (!record) return;
      event.preventDefault();
      activateDecisionEdgeRecord(event);
    }, true);
    svg.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      // Pan only from the empty canvas background. If the press lands on an interactive
      // node group (scope, flow, decision block all carry role="button"), do not start a pan or
      // capture the pointer, so the node's own click handler fires (expand/toggle).
      if (event.target.closest('[role="button"], .edge-hit, .edge-hit-segment, .edge-label-wrap')) return;
      drag = { x: event.clientX, y: event.clientY, vx: view.x, vy: view.y, moved: 0 };
      svg.classList.add("dragging");
      svg.setPointerCapture(event.pointerId);
    });
    svg.addEventListener("pointermove", event => {
      if (!drag) return;
      const scaleX = view.width / svg.clientWidth;
      const scaleY = view.height / svg.clientHeight;
      drag.moved = Math.max(
        drag.moved,
        Math.abs(event.clientX - drag.x) + Math.abs(event.clientY - drag.y)
      );
      view.x = drag.vx - (event.clientX - drag.x) * scaleX;
      view.y = drag.vy - (event.clientY - drag.y) * scaleY;
      updateViewBox();
    });
    svg.addEventListener("pointerup", () => {
      if (drag && drag.moved < 4) {
        if (LC.clearProgressiveLinkHighlight) LC.clearProgressiveLinkHighlight();
        clearHighlight();
      }
      drag = null;
      svg.classList.remove("dragging");
    });

    document.documentElement.dataset.theme = "dark";

    // Expose flow/scope selection so the directory tree and details panel can drive the
    // official React chart without knowing about its implementation.
    LC.selectFlow = selectFlow;
    LC.selectScope = scope => {
      const typed = activeTypedViewer();
      setHeaderScope(scope);
      if (typed && typeof typed.selectScope === "function") {
        typed.selectScope(scope);
      } else {
        location.hash = "scope=" + encodeURIComponent(scope);
        LC.select({
          edgeId: null,
          endLine: null,
          findingId: null,
          flowId: null,
          line: null,
          nodeId: null,
          path: null,
          scope,
        });
      }
    };
    LC.resetGraph = () => {
      const typed = activeTypedViewer();
      if (typed && typeof typed.resetView === "function") typed.resetView();
      else {
        location.hash = "root";
        setHeaderRoot();
        LC.select({
          edgeId: null,
          endLine: null,
          findingId: null,
          flowId: null,
          line: null,
          nodeId: null,
          path: null,
          scope: null,
        });
      }
    };
    LC.activeFlowId = () => activeFlow?.id || null;

    // Viewport primitives retained for shared shell helpers.
    LC.renderFlow = renderFlow;
    LC.svg = svg;
    LC.openDetails = () => setRightRailOpen(true);
    LC.setCanvasLevel = setCanvasLevel;
    LC.setView = v => { view = v; updateViewBox(); };
    LC.updateViewBox = updateViewBox;
    LC.getView = () => view;
    // Shared decision-render helpers retained for source/export compatibility.
    LC.drawFlowGraph = drawFlowGraph;
    LC.flowDefs = flowDefs;
    LC.setCurrentRender = setCurrentRender;
    LC.inspectFlow = inspectFlow;
    LC.inspectNode = inspectNode;
    // Highlight surface panels.js reuses (one accent path, never duplicated): when a
    // finding/source row resolves to a node, light up that node on the active decision
    // graph exactly as a direct block click would, without rebuilding the inspector.
    LC.highlightNode = highlightNode;
    LC.clearHighlight = clearHighlight;
    // Findings the panels read: the flat list (filtered by flow at L2, by scope/subtree at
    // L0/L1) and the per-node index (a node's own findings). Exposed so panels.js does not
    // re-derive the same maps and drift from shell.js.
    LC.findings = findings;
    LC.findingsByNode = findingsByNode;
    // Resolve a node object by (flowId, nodeId) so a finding/source-line click can recover
    // the FlowNode without panels.js re-walking the model.
    LC.nodeById = (flowId, nodeId) => {
      const flow = byId.get(flowId);
      if (!flow || !nodeId) return null;
      return flow.nodes.find(n => n.id === nodeId) || null;
    };
    // Origin-relative bounds of a flow's decision layout. layoutFlow returns bounds over
    // node CENTERS only; inflate by the node half-extents so callers reserve the visual
    // footprint, not just center points.
    LC.measureFlow = (flow, opts) => {
      if (!flow || !flow.nodes || !flow.nodes.length) {
        return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0 };
      }
      const { bounds, nodes } = layoutFlow(flow, opts || {});
      if (!nodes.length) {
        return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0 };
      }
      const inflated = {
        minX: bounds.minX - FLOW_NODE_HALF_W,
        maxX: bounds.maxX + FLOW_NODE_HALF_W,
        minY: bounds.minY - FLOW_NODE_HALF_H,
        maxY: bounds.maxY + FLOW_NODE_HALF_H,
      };
      return {
        ...inflated,
        width: inflated.maxX - inflated.minX,
        height: inflated.maxY - inflated.minY,
      };
    };
    // Drop a flow's hand-placed decision-node positions, so the canvas reset (0) restores
    // the automatic layout of an inline-expanded sub-graph just like it does full screen.
    LC.clearFlowPositions = id => {
      if (id == null) manualPositions.clear();
      else manualPositions.delete(id);
    };

    // Reconcile the CANVAS block highlight from the shared selection. A node selected on
    // ANY surface (a source line, a finding row) lights up its block here, on whatever
    // decision graph is currently drawn -- the same single highlight path a direct block
    // click uses. Guarded by currentRender: when no decision graph is on screen (L0, or a
    // flow whose decisions are not expanded) there is no block to light, and that is fine
    // (the source/tree/finding highlights still apply via panels.js / tree.js). This keeps
    // ONE accent path for the block instead of duplicating highlightNode in panels.js.
    LC.onSelection(sel => {
      if (!currentRender) return;
      if (sel.edgeId) {
        const record = currentRender.edgeRecords.find(item =>
          (item.edge.id || `${item.edge.source}->${item.edge.target}`) === sel.edgeId
        );
        if (record) highlightEdge(record);
        else clearHighlight();
      } else if (sel.nodeId && currentRender.nodeGroups.has(sel.nodeId)) {
        highlightNode(sel.nodeId);
      } else if (!sel.nodeId) {
        clearHighlight();
      }
    });

    // Keep the HTML shell in sync with the hash the React runtime owns. This deliberately
    // does not render canvas content; it only updates header/tree/source state.
    function syncShellFromHash() {
      const raw = location.hash.slice(1);
      const eq = raw.indexOf("=");
      const scopes = model.scopes || {};
      if (eq !== -1) {
        const key = raw.slice(0, eq);
        const value = safeDecodeHashValue(raw.slice(eq + 1));
        if (value == null) { setHeaderRoot(); return; }
        if (key === "flow" && byId.has(value)) {
          const flow = byId.get(value);
          setHeaderFlow(flow);
          LC.select(selectionForFlow(flow));
          if (window.LC.onFlowSelected) window.LC.onFlowSelected(flow);
          return;
        }
        if (key === "scope" && Object.prototype.hasOwnProperty.call(scopes, value)) {
          setHeaderScope(value);
          LC.select({
            edgeId: null,
            endLine: null,
            findingId: null,
            flowId: null,
            line: null,
            nodeId: null,
            path: null,
            scope: value,
          });
          return;
        }
        if (key === "path" && value) {
          const scope = value.split("/").filter(Boolean)[0] || null;
          if (scope) setHeaderScope(scope);
          LC.select({
            edgeId: null,
            endLine: null,
            findingId: null,
            flowId: null,
            line: null,
            nodeId: null,
            path: value,
            scope,
          });
          return;
        }
        if (key === "edge") return;
        if (key === "node" && value === "codebase") {
          setHeaderRoot();
          LC.select({
            edgeId: null,
            endLine: null,
            findingId: null,
            flowId: null,
            line: null,
            nodeId: null,
            path: null,
            scope: null,
          });
          return;
        }
      } else if (raw) {
        const decoded = safeDecodeHashValue(raw);
        if (decoded == null) { setHeaderRoot(); return; }
        if (byId.has(decoded)) {
          const flow = byId.get(decoded);
          setHeaderFlow(flow);
          LC.select(selectionForFlow(flow));
          if (window.LC.onFlowSelected) window.LC.onFlowSelected(flow);
          return;
        }
        if (decoded === "root") {
          setHeaderRoot();
          LC.select({
            edgeId: null,
            endLine: null,
            findingId: null,
            flowId: null,
            line: null,
            nodeId: null,
            path: null,
            scope: null,
          });
        }
      }
      if (!raw) setHeaderRoot();
    }
    LC.syncShellFromHash = syncShellFromHash;
    window.addEventListener("hashchange", syncShellFromHash);
    syncShellFromHash();
