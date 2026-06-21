    // Right-column panels: analyzer quality and source/details. Both panels subscribe to
    // the shared codeDebrief selection store so canvas, tree, and source stay synchronized.
    //
    // SECURITY: source text is inserted only with textContent/createTextNode. Source code
    // is never interpreted as markup.
    (function () {
      const codeDebrief = window.CodeDebrief;
      if (!codeDebrief) return;

      const model = codeDebrief.model || {};
      const byId = codeDebrief.byId || new Map();
      const flows = codeDebrief.flows || [];
      const scopeFlows = model.scopes || {};
      const quality = (model.metadata && model.metadata.quality) || null;
      const sourceFiles = model.source_files || {};

      const sourcePanel = document.getElementById("sourcePanel");
      const sourceBody = document.getElementById("source");
      const sourceFileEl = document.getElementById("sourceFile");
      const qualityPanel = document.getElementById("qualityPanel");
      const qualityBody = document.getElementById("quality");
      const qualityCountEl = document.getElementById("qualityCount");
      const liveRegion = document.getElementById("panelStatus");

      let sourceStatus = "";
      let pendingFocus = null;

      function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
      }

      function clear(node) {
        if (node) node.replaceChildren();
      }

      function metricValue(value) {
        if (value == null || value === "") return "0";
        if (typeof value === "number") return String(value);
        return String(value);
      }

      function ratioPercent(value) {
        return typeof value === "number" ? Math.round(value * 100) + "%" : "0%";
      }

      function qualityMetric(label, value, tone) {
        const item = el("div", "quality-metric" + (tone ? " " + tone : ""));
        item.append(el("span", "quality-label", label), el("strong", "", metricValue(value)));
        return item;
      }

      function qualitySignal(label, value, tone) {
        const row = el("div", "quality-signal" + (tone ? " " + tone : ""));
        row.append(el("span", "quality-label", label), el("span", "quality-value", metricValue(value)));
        return row;
      }

      function countPairs(counts, limit) {
        if (!counts || typeof counts !== "object") return [];
        return Object.keys(counts)
          .map(key => [key, counts[key]])
          .filter(([, value]) => Number(value) > 0)
          .sort((a, b) => Number(b[1]) - Number(a[1]) || String(a[0]).localeCompare(String(b[0])))
          .slice(0, limit);
      }

      function renderQuality() {
        if (!qualityPanel || !qualityBody) return;
        clear(qualityBody);
        if (!quality || typeof quality !== "object") {
          qualityPanel.hidden = true;
          return;
        }
        qualityPanel.hidden = false;
        const files = quality.files || {};
        const flowQuality = quality.flows || {};
        const calls = quality.calls || {};
        const labels = quality.labels || {};
        const source = quality.source_locations || {};
        const graph = quality.graph || {};
        const languagesQuality = quality.languages || {};
        const skipped = (files.skipped && typeof files.skipped === "object") ? files.skipped : { total: 0 };
        const parseErrors = (files.parse_errors && typeof files.parse_errors === "object")
          ? files.parse_errors
          : { total: 0 };

        if (qualityCountEl) qualityCountEl.textContent = ratioPercent(source.coverage);

        const metrics = el("div", "quality-metrics");
        metrics.append(
          qualityMetric("Files", files.total),
          qualityMetric("Flows", flowQuality.total),
          qualityMetric("Entrypoints", flowQuality.entrypoints),
          qualityMetric("Source", ratioPercent(source.coverage))
        );
        qualityBody.appendChild(metrics);

        const signals = el("div", "quality-signals");
        const unresolved = Number(calls.unresolved || 0);
        const ambiguous = Number(calls.ambiguous || 0);
        const generic = Number(labels.generic_nodes || 0);
        const skippedTotal = Number(skipped.total || 0);
        const parseWarnings = Number(parseErrors.total || 0);
        const huge = Array.isArray(flowQuality.huge) ? flowQuality.huge.length : 0;
        const languageAttention = Array.isArray(languagesQuality.attention)
          ? languagesQuality.attention.length
          : 0;
        signals.append(
          qualitySignal("Call resolution", ratioPercent(calls.resolution_rate), unresolved || ambiguous ? "attention" : ""),
          qualitySignal("Skipped files", skippedTotal, skippedTotal ? "attention" : ""),
          qualitySignal("Parse warnings", parseWarnings, parseWarnings ? "attention" : ""),
          qualitySignal("Unresolved calls", unresolved, unresolved ? "attention" : ""),
          qualitySignal("Ambiguous calls", ambiguous, ambiguous ? "attention" : ""),
          qualitySignal("Generic labels", generic + " · " + ratioPercent(labels.generic_ratio), generic ? "attention" : ""),
          qualitySignal("Language attention", languageAttention, languageAttention ? "attention" : ""),
          qualitySignal("Graph density", graph.edge_to_node_ratio, graph.dense_graph_warning ? "attention" : "")
        );
        if (huge) signals.append(qualitySignal("Huge flows", huge, "attention"));
        qualityBody.appendChild(signals);

        const languages = countPairs(flowQuality.by_language || files.by_language, 8);
        if (languages.length) {
          const chips = el("div", "quality-chips");
          languages.forEach(([language, count]) => {
            chips.appendChild(el("span", "quality-chip", language + " " + count));
          });
          qualityBody.appendChild(chips);
        }
      }

      function flushAnnounce() {
        if (liveRegion) liveRegion.textContent = sourceStatus;
      }

      function afterCascade(fn) {
        if (typeof queueMicrotask === "function") queueMicrotask(fn);
        else if (typeof setTimeout === "function") setTimeout(fn, 0);
        else fn();
      }

      function afterFlowOpen(fn) {
        afterCascade(() => {
          if (typeof setTimeout === "function") setTimeout(fn, 0);
          else fn();
        });
      }

      function cssAttr(value) {
        return String(value).replace(/(["\\])/g, "\\$1");
      }

      function restorePendingFocus() {
        if (!pendingFocus || !sourceBody) return;
        const target = sourceBody.querySelector('.code-line[data-line="' + cssAttr(pendingFocus.id) + '"]');
        if (target && typeof target.focus === "function") target.focus();
        pendingFocus = null;
      }

      function relevantFlowIds(sel) {
        if (sel.flowId && byId.has(sel.flowId)) return new Set([sel.flowId]);
        if (sel.path) {
          const prefix = sel.path;
          const ids = new Set();
          flows.forEach(flow => {
            const path = (flow.location && flow.location.path) || "";
            if (path === prefix || path.startsWith(prefix + "/")) ids.add(flow.id);
          });
          return ids;
        }
        if (sel.scope && Object.prototype.hasOwnProperty.call(scopeFlows, sel.scope)) {
          return new Set(scopeFlows[sel.scope] || []);
        }
        return null;
      }

      function sourceFlowFor(sel) {
        if (sel.flowId && byId.has(sel.flowId)) return byId.get(sel.flowId);
        if (!sel.path) return null;
        const ids = relevantFlowIds(sel);
        if (!ids || !ids.size) return null;
        let best = null;
        ids.forEach(id => {
          const flow = byId.get(id);
          if (!flow || !flow.location) return;
          if (
            !best ||
            flow.location.path < best.location.path ||
            (flow.location.path === best.location.path &&
              flow.location.start_line < best.location.start_line)
          ) {
            best = flow;
          }
        });
        return best;
      }

      function resolveFlowSource(flow) {
        const ref = flow && flow.source;
        if (!ref || !ref.path) return null;
        const file = sourceFiles[ref.path];
        if (!file || !Array.isArray(file.lines)) return null;
        const from = ref.start_line;
        if (from == null) return null;
        const to = ref.end_line != null ? ref.end_line : from;
        const offset = from - file.start_line;
        if (offset < 0) return null;
        const lines = file.lines.slice(offset, offset + (to - from + 1));
        if (!lines.length) return null;
        return {
          elided: !!ref.elided,
          lines: lines,
          start_line: from,
          total: to - from + 1,
        };
      }

      function buildLineToNode(flow) {
        const loc = flow.location || {};
        const flowSpan =
          loc.start_line != null && loc.end_line != null
            ? loc.end_line - loc.start_line
            : null;
        const lineToNode = new Map();
        (flow.nodes || []).forEach(node => {
          const nloc = node.location || {};
          const from = nloc.start_line;
          if (from == null) return;
          const to = nloc.end_line != null ? nloc.end_line : from;
          const span = to - from;
          if (flowSpan != null && span >= flowSpan) return;
          for (let line = from; line <= to; line++) {
            const current = lineToNode.get(line);
            if (!current || span < current.span) lineToNode.set(line, { id: node.id, span: span });
          }
        });
        return lineToNode;
      }

      function selectedSourceRange(flow, sel) {
        if (sel.nodeId) {
          const node = codeDebrief.nodeById ? codeDebrief.nodeById(flow.id, sel.nodeId) : null;
          if (node && node.location) {
            const from = node.location.start_line;
            return { from: from, to: node.location.end_line != null ? node.location.end_line : from };
          }
        }
        if (
          sel.line != null &&
          (!sel.path || !flow.location || !flow.location.path || sel.path === flow.location.path)
        ) {
          return { from: sel.line, to: sel.endLine != null ? sel.endLine : sel.line };
        }
        if (sel.flowId === flow.id && flow.location && flow.location.start_line != null) {
          const from = flow.location.start_line;
          return { from: from, to: flow.location.end_line != null ? flow.location.end_line : from };
        }
        return null;
      }

      function renderSource(sel) {
        if (!sourceBody) return;
        const flow = sourceFlowFor(sel || {});
        clear(sourceBody);
        if (sourceFileEl) sourceFileEl.textContent = "";
        if (sourcePanel) sourcePanel.hidden = !flow;
        if (qualityPanel) qualityPanel.classList.toggle("panel-quality-expanded", !flow);

        if (!flow) {
          sourceBody.appendChild(el("p", "panel-empty", "Select a flow or node to view its source."));
          sourceStatus = "no source selected";
          return;
        }

        const snippet = resolveFlowSource(flow);
        const location = flow.location || {};
        const fileLabel = location.path
          ? location.path + (location.start_line ? ":" + location.start_line : "")
          : flow.name || flow.id;
        if (sourceFileEl) sourceFileEl.textContent = fileLabel;

        if (!snippet) {
          sourceBody.appendChild(el("p", "panel-empty", "Source lines are not embedded for this flow."));
          sourceStatus = "source unavailable";
          return;
        }

        sourceStatus = "source " + fileLabel;
        const pre = el("pre", "code-lines");
        const lineToNode = buildLineToNode(flow);
        const selected = selectedSourceRange(flow, sel || {});
        let firstHighlight = null;

        snippet.lines.forEach((text, index) => {
          const lineNo = snippet.start_line + index;
          const lineEl = el("div", "code-line");
          lineEl.setAttribute("data-line", String(lineNo));
          const node = lineToNode.get(lineNo);
          const nodeId = node && node.id;
          if (nodeId) {
            lineEl.setAttribute("data-node-id", nodeId);
            lineEl.tabIndex = 0;
            lineEl.setAttribute("role", "button");
            lineEl.setAttribute("aria-label", "Select source line " + lineNo);
          }
          if (selected && lineNo >= selected.from && lineNo <= selected.to) {
            lineEl.classList.add("selected");
            if (!firstHighlight) firstHighlight = lineEl;
          }

          const gutter = el("span", "code-gutter", String(lineNo));
          gutter.setAttribute("aria-hidden", "true");
          lineEl.append(gutter, el("span", "code-text", text.length ? text : " "));

          if (nodeId) {
            const activateLine = () => {
              pendingFocus = { id: lineNo };
              const publishLineSelection = () => codeDebrief.select({
                endLine: lineNo,
                flowId: flow.id,
                line: lineNo,
                nodeId: nodeId,
                path: flow.location.path,
              });
              if (codeDebrief.selectFlow) {
                codeDebrief.selectFlow(flow.id);
                afterFlowOpen(publishLineSelection);
              } else {
                publishLineSelection();
              }
            };
            lineEl.addEventListener("click", activateLine);
            lineEl.addEventListener("keydown", event => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                activateLine();
              }
            });
          }
          pre.appendChild(lineEl);
        });
        sourceBody.appendChild(pre);

        if (snippet.elided) {
          const dropped = snippet.total - snippet.lines.length;
          sourceBody.appendChild(
            el("p", "code-elided", dropped + " more line" + (dropped === 1 ? "" : "s") + " not shown")
          );
        }
        if (firstHighlight && typeof firstHighlight.scrollIntoView === "function") {
          firstHighlight.scrollIntoView({ block: "nearest" });
        }
      }

      renderQuality();

      function onSelection(sel) {
        renderSource(sel || {});
        flushAnnounce();
        if (pendingFocus) afterCascade(restorePendingFocus);
      }
      if (codeDebrief.onSelection) codeDebrief.onSelection(onSelection);
      onSelection(codeDebrief.selection || {});

      const fsToggle = document.getElementById("fullscreenToggle");
      const mainEl = document.querySelector("main");
      const body = document.body;
      const fsApiSupported = !!(
        mainEl &&
        (mainEl.requestFullscreen ||
          mainEl.webkitRequestFullscreen ||
          mainEl.msRequestFullscreen)
      );

      function fsElement() {
        return document.fullscreenElement || document.webkitFullscreenElement || null;
      }
      let fallbackActive = false;
      function isMaximized() {
        return fallbackActive || fsElement() === mainEl;
      }
      codeDebrief.fullscreenFallbackActive = () => fallbackActive;

      function reflectFsState() {
        const on = isMaximized();
        if (fsToggle) {
          fsToggle.setAttribute("aria-pressed", on ? "true" : "false");
          fsToggle.title = on ? "Exit full screen (Esc)" : "Full screen (Esc to exit)";
        }
        if (on) body.setAttribute("data-fullscreen", "");
        else body.removeAttribute("data-fullscreen");
        if (codeDebrief.updateViewBox) codeDebrief.updateViewBox();
      }

      function requestFs() {
        if (!mainEl) return Promise.resolve();
        const req =
          mainEl.requestFullscreen ||
          mainEl.webkitRequestFullscreen ||
          mainEl.msRequestFullscreen;
        try {
          const result = req.call(mainEl);
          return result && typeof result.then === "function" ? result : Promise.resolve();
        } catch (_) {
          return Promise.reject();
        }
      }

      function exitFs() {
        const exit =
          document.exitFullscreen ||
          document.webkitExitFullscreen ||
          document.msExitFullscreen;
        if (exit) {
          try {
            const result = exit.call(document);
            return result && typeof result.then === "function" ? result : Promise.resolve();
          } catch (_) {}
        }
        return Promise.resolve();
      }

      function enterMaximize() {
        if (fsApiSupported) {
          requestFs().then(reflectFsState, () => {
            fallbackActive = true;
            reflectFsState();
          });
        } else {
          fallbackActive = true;
          reflectFsState();
        }
      }

      function exitMaximize() {
        fallbackActive = false;
        if (fsElement() === mainEl) {
          exitFs().then(reflectFsState, reflectFsState);
        } else {
          reflectFsState();
        }
      }

      function toggleFullscreen() {
        if (isMaximized()) exitMaximize();
        else enterMaximize();
      }

      codeDebrief.toggleFullscreen = toggleFullscreen;

      if (fsToggle) fsToggle.addEventListener("click", toggleFullscreen);
      ["fullscreenchange", "webkitfullscreenchange"].forEach(eventName => {
        document.addEventListener(eventName, reflectFsState);
      });
      document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        const target = event.target;
        if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName || "")) return;
        if (fallbackActive) exitMaximize();
      });
    })();
