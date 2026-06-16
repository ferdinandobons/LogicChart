
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
    const scopeFilterEl = document.getElementById("scopeFilter");
    const langFilterEl = document.getElementById("langFilter");
    const detailsEl = document.getElementById("details");
    const rightRail = document.getElementById("rightRail");
    const leftRail = document.getElementById("leftRail");
    const themeToggleBtn = document.getElementById("themeToggle");
    let activeFlow = null;
    let view = { x: 0, y: 0, width: 1000, height: 800 };
    let drag = null;
    // Per-flow hand-placed node positions: flowId -> Map(nodeId -> {x, y}). Survives
    // navigating away and back within the session.
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

    function populateFilters() {
      const scopes = new Set();
      const languages = new Set();
      flows.forEach(flow => {
        (flow.metadata.scope || []).forEach(scope => scopes.add(scope));
        if (flow.language) languages.add(flow.language);
      });
      fillSelect(scopeFilterEl, "All scopes", [...scopes].sort());
      fillSelect(langFilterEl, "All languages", [...languages].sort());
      // Hide a filter that offers no real choice (a single scope/language).
      scopeFilterEl.style.display = scopes.size > 1 ? "" : "none";
      langFilterEl.style.display = languages.size > 1 ? "" : "none";
    }

    function fillSelect(select, allLabel, values) {
      select.replaceChildren();
      const all = document.createElement("option");
      all.value = "";
      all.textContent = allLabel;
      select.appendChild(all);
      values.forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
    }

    function renderList(filter = "") {
      const needle = filter.trim().toLowerCase();
      const scope = scopeFilterEl.value;
      const language = langFilterEl.value;
      listEl.replaceChildren();
      sortedFlows()
        .filter(flow => !flow.metadata.test)
        .filter(flow => !scope || (flow.metadata.scope || []).includes(scope))
        .filter(flow => !language || flow.language === language)
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

    // Single source for an edge's curved path + label anchor, reused on first render and
    // live during a node drag so connected edges follow.
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

    const applyFilters = () => renderList(searchEl.value);
    searchEl.addEventListener("input", applyFilters);
    scopeFilterEl.addEventListener("change", applyFilters);
    langFilterEl.addEventListener("change", applyFilters);
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

    populateFilters();
    renderList();
    const requested = decodeURIComponent(location.hash.slice(1));
    const initial = byId.get(requested) || flows.find(item => item.is_entrypoint) || flows[0];
    if (initial) selectFlow(initial.id);
  