
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
    // Ownership seam: which renderer owns the SVG right now. "canvas" (L0/L1, owned by
    // canvas.js) or "flow" (L2 decision chart, owned by renderFlow here). EVERY entry
    // into the SVG sets this so the two renderers never write behind each other's back.
    LC.mode = "canvas";

    // --- Shared selection store (Phase 4) ---------------------------------------
    // ONE selection model, ONE accent color. Every surface -- a canvas decision block,
    // a source line, a tree file/flow row, a logical-error row -- both PUBLISHES into
    // this store (via LC.select) and SUBSCRIBES to it (via LC.onSelection) so selecting
    // any one highlights the others. The store holds only ids; each surface maps ids to
    // its own DOM. shell.js drives the canvas highlight (its existing job); panels.js
    // renders the source + errors panels and the tree reflects the active file/flow.
    const selection = { path: null, flowId: null, nodeId: null, findingId: null, scope: null };
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
      ["path", "flowId", "nodeId", "findingId", "scope"].forEach(key => {
        if (Object.prototype.hasOwnProperty.call(partial, key) && partial[key] !== undefined) {
          selection[key] = partial[key];
        }
      });
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

    const svg = document.getElementById("canvas");
    const rightRail = document.getElementById("rightRail");
    const leftRail = document.getElementById("leftRail");
    const detailButton = document.getElementById("detailButton");
    const detailsClose = document.getElementById("detailsClose");
    const menuButton = document.getElementById("menuButton");
    const themeToggleBtn = document.getElementById("themeToggle");
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
    syncRailControls();

    document.getElementById("flowCount").textContent = flows.length;
    document.getElementById("entryCount").textContent = flows.filter(item => item.is_entrypoint).length;
    document.getElementById("findingCount").textContent = findings.length;

    // Entry points first, then by name. Shared so the tree lists a file's flows in the
    // same order the old flat list used.
    LC.sortFlows = list =>
      [...list].sort(
        (a, b) => Number(b.is_entrypoint) - Number(a.is_entrypoint) || a.name.localeCompare(b.name)
      );

    // Updates the header + the active-flow bookkeeping shared by the tree and breadcrumb.
    // Selection RENDERS via canvas.js's inline-L2 expander (LC.expandFlowInline) when it
    // is registered -- the flow's decisions unfold IN PLACE inside the L1 canvas, keeping
    // the surrounding files/flows visible. Only when no inline expander is available (a
    // bare deep link before canvas.js boots, or a degraded shell) does it fall back to the
    // full-screen renderFlow, so #flow= and tree clicks never dead-end.
    function selectFlow(flowId) {
      const flow = byId.get(flowId);
      if (!flow) return;
      activeFlow = flow;
      document.getElementById("flowTitle").textContent = flow.name;
      document.getElementById("flowKind").textContent =
        `${flow.entry_kind} · ${flow.language} · ${flow.framework}`;
      if (window.LC.expandFlowInline) {
        // canvas.js owns the SVG (mode stays "canvas"); it sets the hash, draws the
        // inline sub-graph, refreshes the breadcrumb, and calls inspectFlow itself.
        window.LC.expandFlowInline(flow.id);
      } else {
        location.hash = "flow=" + encodeURIComponent(flow.id);
        LC.mode = "flow"; // single dispatch into the standalone full-screen L2 renderer.
        renderFlow(flow);
        inspectFlow(flow);
        if (window.LC.onCanvasFlow) window.LC.onCanvasFlow(flow);
      }
      // On phones the tree is a drawer, so a selection should clear the canvas. On
      // desktop/tablet the tree is working context; keep it open unless the user closes it.
      if (window.innerWidth <= 700) setLeftRailOpen(false);
      // Let other inlined scripts (e.g. tree.js) reflect the active flow.
      if (window.LC.onFlowSelected) window.LC.onFlowSelected(flow);
    }

    function layoutFlow(flow) {
      const order = new Map(flow.nodes.map((node, index) => [node.id, index]));
      const incoming = new Map(flow.nodes.map(node => [node.id, []]));
      const outgoing = new Map(flow.nodes.map(node => [node.id, []]));
      flow.edges.forEach(edge => incoming.get(edge.target)?.push(edge));
      flow.edges.forEach(edge => outgoing.get(edge.source)?.push(edge));
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
        positions.set(node.id, { x, y: layer * FLOW_LAYER_Y, layer, order: index });
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
      return {
        d: `M ${start.x} ${startPortY} L ${start.x} ${branchY} L ${end.x} ${branchY} L ${end.x} ${endPortY}`,
        labelX: labelIsExitChip ? horizontalLabelX(start.x, end.x) : (start.x + end.x) / 2 + 7,
        labelY: branchY - 8,
        exitChip: labelIsExitChip,
      };
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

    // Decision-flow defs (shadow filters + arrow marker). canvas.js draws its own copy
    // for L0/L1, but the inline-L2 sub-graph reuses these ids, so renderFlow and the
    // inline path both ensure a <defs> is present in whatever SVG they draw into.
    function flowDefs() {
      const defs = svgEl("defs");
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

    // Reusable decision-graph renderer. Draws `flow`'s nodes/edges (the L2 chart) into a
    // fresh <g> layer and RETURNS it WITHOUT touching the SVG, the global `view`, or
    // data-level -- so the same code powers both the full-screen renderFlow and the
    // inline-L2 sub-graph canvas.js anchors under an expanded flow node.
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
      const { positions, bounds } = layoutFlow(flow);
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
      const flowNodeById = new Map(flow.nodes.map(node => [node.id, node]));

      // Keep edge element references per node so dragging a block re-routes its edges live,
      // and a flat list so selecting a node can highlight its incident edges.
      const nodeEdges = new Map(flow.nodes.map(node => [node.id, []]));
      const edgeRecords = [];
      const edgeLayer = svgEl("g");
      const edgePathLayer = svgEl("g");
      const edgeLabelLayer = svgEl("g");
      flow.edges.forEach(edge => {
        const start = at(edge.source);
        const end = at(edge.target);
        if (!start || !end) return;
        const sourceNode = flowNodeById.get(edge.source);
        const targetNode = flowNodeById.get(edge.target);
        const geometry = edgeGeometry(start, end, sourceNode?.kind, targetNode?.kind);
        const path = svgEl("path");
        path.setAttribute("class", "edge");
        path.setAttribute("d", geometry.d);
        edgePathLayer.appendChild(path);
        let label = null;
        if (edge.label) {
          label = edgeLabel(edge.label, geometry);
          edgeLabelLayer.appendChild(label);
        }
        const record = { edge, path, label };
        edgeRecords.push(record);
        nodeEdges.get(edge.source)?.push(record);
        nodeEdges.get(edge.target)?.push(record);
      });
      edgeLayer.append(edgePathLayer, edgeLabelLayer);
      layer.appendChild(edgeLayer);

      function rerouteFrom(nodeId) {
        (nodeEdges.get(nodeId) || []).forEach(({ edge, path, label }) => {
          const start = at(edge.source);
          const end = at(edge.target);
          if (!start || !end) return;
          const sourceNode = flowNodeById.get(edge.source);
          const targetNode = flowNodeById.get(edge.target);
          const geometry = edgeGeometry(start, end, sourceNode?.kind, targetNode?.kind);
          path.setAttribute("d", geometry.d);
          if (label) label.setAttribute("transform", `translate(${geometry.labelX} ${geometry.labelY})`);
        });
      }

      const nodeLayer = svgEl("g");
      const nodeGroups = new Map();
      flow.nodes.forEach(node => {
        const position = positions.get(node.id);
        // Live world-space position of this node (origin-translated). Drag mutates it.
        const place = { x: position.x + originX, y: position.y + originY };
        const group = svgEl("g");
        nodeGroups.set(node.id, group);
        group.setAttribute("class", `node ${node.kind}${findingsByNode.has(node.id) ? " has-finding" : ""}`);
        group.setAttribute("transform", `translate(${place.x} ${place.y})`);
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
            ox: place.x,
            oy: place.y,
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
          place.x = nodeDrag.ox + dx;
          place.y = nodeDrag.oy + dy;
          // positions is origin-relative; mirror the drag back so rerouteFrom (which
          // re-adds the origin) and any later override store both stay consistent.
          position.x = place.x - originX;
          position.y = place.y - originY;
          group.setAttribute("transform", `translate(${place.x} ${place.y})`);
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

    // Bind a freshly drawn decision graph as the active highlight target. Inline-L2
    // (canvas.js) calls this after placing the sub-graph so a click on a decision node
    // routes through the same inspectNode -> highlightNode path as the full-screen view.
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

    // Inspecting a flow: clear the per-node canvas highlight (no single node is active)
    // and publish the flow selection so the Source + Logical-errors panels (panels.js)
    // and the tree reflect it. The right column is now Source/Errors (panels.js owns the
    // DOM); shell.js keeps only its canvas-highlight responsibility plus publishing the
    // shared selection. nodeId is cleared so the source panel shows the whole flow snippet.
    function inspectFlow(flow) {
      clearHighlight();
      LC.select({ flowId: flow.id, path: flow.location.path, nodeId: null, findingId: null });
    }

    // Inspecting a decision/call node: publish the node selection. The block highlight is
    // applied by the single shared-selection subscriber below (one accent path, not
    // duplicated here); the source panel highlights the node's source line(s) and the
    // errors panel lists the node's findings, both via the same store.
    function inspectNode(flow, node) {
      setRightRailOpen(true);
      LC.select({ flowId: flow.id, nodeId: node.id, path: node.location.path, findingId: null });
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

    document.getElementById("zoomIn").addEventListener("click", () => zoom(.82));
    document.getElementById("zoomOut").addEventListener("click", () => zoom(1.22));
    document.getElementById("resetView").addEventListener("click", () => {
      // Mode-aware: flow mode re-lays out the active flow; canvas mode drops the
      // current view's drag overrides and re-fits via canvas.js.
      if (LC.mode === "flow") {
        if (!activeFlow) return;
        manualPositions.delete(activeFlow.id);  // discard hand-placed positions, re-layout
        renderFlow(activeFlow);
      } else if (LC.resetCanvas) {
        LC.resetCanvas();
      }
    });
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
    svg.addEventListener("pointerdown", event => {
      if (event.button !== 0) return;
      // Pan only from the empty canvas background. If the press lands on an interactive
      // node group (scope/file/flow all carry role="button"), do not start a pan or
      // capture the pointer, so the node's own click handler fires (expand/toggle).
      if (event.target.closest('[role="button"]')) return;
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

    // Expose flow selection so the directory tree (tree.js, a later <script>) can
    // drive the canvas. tree.js renders the left rail and reads LC.activeFlowId() to
    // mark the active row.
    LC.selectFlow = selectFlow;
    LC.activeFlowId = () => activeFlow?.id || null;

    // Viewport primitives canvas.js reuses WITHOUT redefining. The pan/zoom/wheel
    // handlers above mutate this shared `view` object and call updateViewBox, so they
    // work for BOTH renderers untouched (generic over `view`).
    LC.renderFlow = renderFlow;
    LC.svg = svg;
    LC.setCanvasLevel = setCanvasLevel;
    LC.setView = v => { view = v; updateViewBox(); };
    LC.updateViewBox = updateViewBox;
    LC.getView = () => view;
    // Inline-L2 seam: canvas.js draws a flow's decisions in place (inside the L1 canvas)
    // by reusing the very same decision renderer. drawFlowGraph returns a detached <g>
    // (no SVG/view side effects); flowDefs supplies the shared filter/marker ids;
    // setCurrentRender binds the sub-graph as the active inspect/highlight target.
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
    // Half-extents of a drawn decision node plus badges/source labels, so measureFlow
    // can inflate center-only bounds to the visual box the rendered nodes occupy.
    // Origin-relative bounds of a flow's decision layout, so canvas.js can RESERVE the
    // band an inline-expanded sub-graph will occupy BEFORE drawing it (layout then draw),
    // keeping siblings from overlapping. Same layoutFlow the renderer uses, so the
    // reserved box matches the drawn one (manual drag overrides included). layoutFlow
    // returns bounds over node CENTERS only; inflate by the node half-extents so the
    // reserved band/panel actually contains the rendered nodes (a single-node flow then
    // measures 290x116, not 0x0) -- callers add their own DECISION_PAD breathing room.
    LC.measureFlow = flow => {
      if (!flow || !flow.nodes || !flow.nodes.length) {
        return { minX: 0, maxX: 0, minY: 0, maxY: 0, width: 0, height: 0 };
      }
      const { bounds } = layoutFlow(flow);
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
    LC.clearFlowPositions = id => { manualPositions.delete(id); };

    // Reconcile the CANVAS block highlight from the shared selection. A node selected on
    // ANY surface (a source line, a finding row) lights up its block here, on whatever
    // decision graph is currently drawn -- the same single highlight path a direct block
    // click uses. Guarded by currentRender: when no decision graph is on screen (L0, or a
    // flow whose decisions are not expanded) there is no block to light, and that is fine
    // (the source/tree/finding highlights still apply via panels.js / tree.js). This keeps
    // ONE accent path for the block instead of duplicating highlightNode in panels.js.
    LC.onSelection(sel => {
      if (!currentRender) return;
      if (sel.nodeId && currentRender.nodeGroups.has(sel.nodeId)) {
        highlightNode(sel.nodeId);
      } else if (!sel.nodeId) {
        clearHighlight();
      }
    });

    // Single hash router. Parsed once on load and on every hashchange; dispatches to
    // the right owner so a deep link / refresh / back-button restores the level.
    //   #flow=<id>   -> selectFlow (mode flow, L2)
    //   #scope=<name> (name in model.scopes) -> canvas L1 for that scope
    //   #path=<path>  -> canvas L1 with that folder/file area selected
    //   bare #<id> with byId.has(decoded) -> treated as #flow=<id> (back-compat)
    //   empty / unrecognized -> canvas L0
    function routeFromHash() {
      const raw = location.hash.slice(1);
      const eq = raw.indexOf("=");
      const scopes = model.scopes || {};
      if (eq !== -1) {
        const key = raw.slice(0, eq);
        const value = decodeURIComponent(raw.slice(eq + 1));
        if (key === "flow" && byId.has(value)) { selectFlow(value); return; }
        if (key === "scope" && Object.prototype.hasOwnProperty.call(scopes, value)) {
          if (LC.showScope) LC.showScope(value);
          return;
        }
        if (key === "path" && value) {
          if (LC.showPath) LC.showPath(value);
          return;
        }
      } else if (raw) {
        const decoded = decodeURIComponent(raw);
        if (byId.has(decoded)) { selectFlow(decoded); return; }
      }
      if (LC.showL0) LC.showL0();
    }
    LC.routeFromHash = routeFromHash;

    // Boot: defer the first route until canvas.js has registered showL0/showScope.
    // canvas.js is the very next <script>, so a microtask is enough; guard anyway.
    function boot() {
      if (!LC.showL0) { setTimeout(boot, 0); return; }
      routeFromHash();
      window.addEventListener("hashchange", routeFromHash);
    }
    boot();
