
    // Right-column panels (Phase 4): Source (top) + Logical errors (bottom), plus the
    // canvas full-screen toggle. Both panels SUBSCRIBE to the shared selection store
    // (shell.js's LC.select / LC.onSelection) and PUBLISH back into it, so selecting any
    // one of {a canvas decision block, a source line, a tree file/flow, a finding row}
    // highlights the others in the one shared accent. No duplicated highlight/inspect
    // logic: block highlighting stays in shell.js (driven off the store), the tree
    // reflects via tree.js's store subscription, and these panels own only their own DOM.
    //
    // SECURITY: every character of source text and every finding string is inserted as a
    // TEXT NODE (textContent / createTextNode), NEVER innerHTML -- the snippet lines are
    // source-derived and must not be interpreted as markup. `<`, `>`, `&`, `"` in code
    // render literally.
    (function () {
      const LC = window.LC;
      if (!LC) return;

      const model = LC.model || {};
      const byId = LC.byId || new Map();
      const flows = LC.flows || [];
      const findings = LC.findings || model.findings || [];
      const findingsByNode = LC.findingsByNode || new Map();
      const scopeFlows = model.scopes || {};
      // File-level source store: path -> {start_line, lines}. Each file's lines are
      // embedded ONCE here (payload.attach_source_snippets), and a flow's `source` is a
      // lightweight {path, start_line, end_line, elided?} reference that slices its own
      // window out of this. Resolving through the store is what de-dups a file shared by
      // many flows -- we never re-embed or re-slice the whole file per flow.
      const sourceFiles = model.source_files || {};

      // At most this many findings are rendered in the errors panel for a broad (L0 /
      // empty / scope) selection, with an "N more" affordance after; a node selection is
      // exact and always shown in full. Keeps the panel from rendering an unbounded list
      // (a large codebase has thousands of findings) -- general over finding count.
      const MAX_FINDING_ROWS = 50;

      const sourcePanel = document.getElementById("sourcePanel");
      const sourceBody = document.getElementById("source");
      const sourceFileEl = document.getElementById("sourceFile");
      const errorsBody = document.getElementById("errors");
      const errorsCountEl = document.getElementById("errorsCount");
      const reviewQueueBtn = document.getElementById("reviewQueueToggle");
      const liveRegion = document.getElementById("panelStatus");
      let reviewQueueMode = false;

      // aria-live announcer: screen readers are not notified when the panels rebuild on a
      // selection change. Each panel records its own status ("source: file:line", "<n>
      // findings"); onSelection then writes ONE combined message into the visually-hidden
      // polite live region -- so the two panels do not overwrite each other's announcement.
      let sourceStatus = "";
      let errorsStatus = "";
      function flushAnnounce() {
        if (!liveRegion) return;
        const parts = [];
        if (sourceStatus) parts.push(sourceStatus);
        if (errorsStatus) parts.push(errorsStatus);
        liveRegion.textContent = parts.join(", ");
      }

      // --- small DOM helpers (text-node only) -------------------------------------

      function el(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text; // text node, never markup.
        return node;
      }

      function clear(node) {
        if (node) node.replaceChildren();
      }

      // Focus restoration across a panel re-render. Activating a finding row or a code line
      // re-renders the panel (replaceChildren destroys the focused element, dropping focus
      // to <body>). When an activation originates INSIDE a panel, we record the stable id of
      // the activated item here, then restore focus to the equivalent row/line AFTER the
      // whole selection cascade settles. Deferring matters: a code-line click can trigger
      // a chart selection focus update; restoring synchronously during render would be
      // immediately overwritten by that.
      // Scheduling the restore last (a microtask after the cascade) lets the panel keep
      // focus. Cleared once consumed so a later unrelated selection does not steal focus.
      let pendingFocus = null;
      // Run a callback after the current synchronous selection cascade. Falls back to a
      // direct call if neither timer is available (degraded shell).
      function afterCascade(fn) {
        if (typeof queueMicrotask === "function") queueMicrotask(fn);
        else if (typeof setTimeout === "function") setTimeout(fn, 0);
        else fn();
      }
      // Restore focus to the panel element carrying the pending stable id, if it is still in
      // the DOM. data-line for the source panel, data-finding-id for the errors panel.
      function restorePendingFocus() {
        if (!pendingFocus) return;
        const sel =
          pendingFocus.panel === "source"
            ? '.code-line[data-line="' + cssAttr(pendingFocus.id) + '"]'
            : '.finding-row[data-finding-id="' + cssAttr(pendingFocus.id) + '"]';
        const body = pendingFocus.panel === "source" ? sourceBody : errorsBody;
        const target = body && body.querySelector ? body.querySelector(sel) : null;
        if (target && typeof target.focus === "function") target.focus();
        pendingFocus = null;
      }
      // Escape a value for use inside an [attr="..."] selector (ids/line numbers are simple,
      // but a finding id could contain quotes/backslashes).
      function cssAttr(value) {
        return String(value).replace(/(["\\])/g, "\\$1");
      }

      // --- selection -> findings ---------------------------------------------------

      // The set of flow ids whose findings are "relevant" to the current selection:
      //   node selected  -> that node's findings only (handled separately, exact).
      //   flow selected  -> that one flow.
      //   scope selected -> every flow in the scope (L1 subtree).
      //   path selected  -> every flow whose file path is under that path (tree dir/file).
      //   nothing        -> all flows (L0: the whole codebase's findings).
      // General over any codebase: scopes/paths come straight from the payload, no
      // hard-coded names.
      function relevantFlowIds(sel) {
        if (sel.flowId && byId.has(sel.flowId)) return new Set([sel.flowId]);
        if (sel.path) {
          // A path selection ALWAYS scopes, even when it matches no flows: returning the
          // (possibly empty) set keeps the panels showing "this file/dir's findings" rather
          // than falling through to the whole-codebase list. An empty set => no findings.
          const prefix = sel.path;
          const ids = new Set();
          flows.forEach(flow => {
            const p = (flow.location && flow.location.path) || "";
            if (p === prefix || p.startsWith(prefix + "/")) ids.add(flow.id);
          });
          return ids;
        }
        if (sel.scope && Object.prototype.hasOwnProperty.call(scopeFlows, sel.scope)) {
          return new Set(scopeFlows[sel.scope] || []);
        }
        return null; // null => "all findings" (no scoping).
      }

      // Findings to list for a selection. A selected node narrows to that node's findings;
      // otherwise the relevant flow set's findings, deduped and stable-ordered.
      function findingsForSelection(sel) {
        if (reviewQueueMode) return prioritizedFindings(findings.slice());
        if (sel.nodeId) {
          return (findingsByNode.get(sel.nodeId) || []).slice();
        }
        const ids = relevantFlowIds(sel);
        if (ids === null) return findings.slice();
        return findings.filter(f => ids.has(f.flow_id));
      }

      function findingPriority(finding) {
        const severity = { error: 0, warning: 1, info: 2 };
        const evidence = { VERIFIED: 0, INFERRED: 1, POTENTIAL_GAP: 2 };
        return (severity[finding.severity] ?? 3) * 10 + (evidence[finding.evidence] ?? 3);
      }

      function prioritizedFindings(list) {
        return list.sort((a, b) =>
          findingPriority(a) - findingPriority(b) ||
          String(a.location && a.location.path || "").localeCompare(String(b.location && b.location.path || "")) ||
          String(a.message || "").localeCompare(String(b.message || ""))
        );
      }

      // --- Logical-errors panel ----------------------------------------------------

      // Evidence tier label exactly as the model emits it (VERIFIED / INFERRED /
      // POTENTIAL_GAP). Falls back to the raw value for forward-compatibility with any
      // future tier, so the panel never hard-codes the closed set.
      function tierClass(evidence) {
        return "tier-" + String(evidence || "").toLowerCase().replace(/[^a-z0-9]+/g, "-");
      }

      function findingRow(finding) {
        // A finding row is an activatable listitem. It must NOT be a <button role="listitem">
        // (a button is not a valid listitem child of role="list"); use a div with
        // role="listitem", made keyboard-activatable via tabindex + an Enter/Space handler.
        const row = el("div", "finding-row finding " + (finding.severity || ""));
        row.setAttribute("role", "listitem");
        row.setAttribute("tabindex", "0");
        row.setAttribute("data-finding-id", finding.id);
        if (finding.flow_id) row.setAttribute("data-flow-id", finding.flow_id);
        if (finding.node_id) row.setAttribute("data-node-id", finding.node_id);

        const head = el("div", "finding-head");
        const tier = el("span", "tier-badge " + tierClass(finding.evidence), finding.evidence || "");
        const kind = el("span", "finding-kind", finding.kind || "");
        head.append(tier, kind);
        row.appendChild(head);

        row.appendChild(el("div", "finding-message", finding.message || ""));
        // Source coordinate of the finding, so a row stands alone without the panels.
        if (finding.location && finding.location.path) {
          row.appendChild(
            el(
              "div",
              "finding-loc",
              finding.location.path + ":" + finding.location.start_line
            )
          );
        }
        row.title = finding.detail || `Open finding ${finding.kind || "review item"} in the flowchart`;

        // Activating a finding selects its flow + node (bidirectional: lights the block,
        // the source line, and the tree file). selectFlow opens the flow inline so its
        // decision block exists to highlight; then publish the node + finding so the block
        // highlight + source line land. selectFlow's notify completes first (not
        // re-entrant), so this second select() re-notifies cleanly. The activation came
        // from THIS panel, so record the finding id to restore focus after the re-render.
        function activate() {
          pendingFocus = { panel: "errors", id: finding.id };
          if (finding.flow_id && LC.selectFlow) {
            LC.selectFlow(finding.flow_id);
          }
          LC.select({
            flowId: finding.flow_id || null,
            nodeId: finding.node_id || null,
            path: (finding.location && finding.location.path) || null,
            findingId: finding.id,
            line: (finding.location && finding.location.start_line) || null,
            endLine:
              (finding.location && (finding.location.end_line || finding.location.start_line)) || null,
          });
        }
        row.addEventListener("click", activate);
        row.addEventListener("keydown", event => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            activate();
          }
        });
        return row;
      }

      // Compact counts-by-tier/kind summary for a broad (empty / L0 / scope) selection, so
      // the panel never renders an unbounded finding list at the top level. Returns a
      // <div> with one count line per evidence tier plus the total.
      function findingSummary(list) {
        const byTier = new Map();
        list.forEach(f => {
          const tier = String(f.evidence || "other");
          byTier.set(tier, (byTier.get(tier) || 0) + 1);
        });
        const wrap = el("div", "errors-summary");
        wrap.appendChild(
          el("p", "panel-empty", list.length + " finding" + (list.length === 1 ? "" : "s") + " across the current view.")
        );
        [...byTier.keys()].sort().forEach(tier => {
          const line = el("div", "summary-line");
          line.appendChild(el("span", "tier-badge " + tierClass(tier), tier));
          line.appendChild(el("span", "summary-count", String(byTier.get(tier))));
          wrap.appendChild(line);
        });
        wrap.appendChild(
          el("p", "panel-empty", "Select a flow or node to list its findings.")
        );
        return wrap;
      }

      function renderErrors(sel) {
        if (!errorsBody) return;
        const list = findingsForSelection(sel);
        clear(errorsBody);
        if (errorsCountEl) errorsCountEl.textContent = list.length ? String(list.length) : "";
        errorsStatus = list.length
          ? list.length + " finding" + (list.length === 1 ? "" : "s")
          : "no findings";
        if (!list.length) {
          errorsBody.appendChild(
            el("p", "panel-empty", "No findings for the current selection.")
          );
          return;
        }
        // A node selection is exact -- show all of its (few) findings. A broad selection
        // (nothing / L0 / a scope / a path) can match thousands; show a compact summary
        // instead of an unbounded list, so the panel stays bounded at the top level.
        if (reviewQueueMode && list.length > MAX_FINDING_ROWS) {
          list.slice(0, MAX_FINDING_ROWS).forEach(finding => {
            errorsBody.appendChild(findingRow(finding));
          });
          errorsBody.appendChild(
            el("p", "panel-empty", String(list.length - MAX_FINDING_ROWS) + " more findings not shown.")
          );
          return;
        }
        const exact = !!sel.nodeId;
        if (!exact && list.length > MAX_FINDING_ROWS) {
          errorsBody.appendChild(findingSummary(list));
          return;
        }
        list.forEach(finding => {
          const row = findingRow(finding);
          if (
            (sel.findingId && finding.id === sel.findingId) ||
            (sel.nodeId && finding.node_id === sel.nodeId)
          ) {
            row.classList.add("selected");
          }
          errorsBody.appendChild(row);
        });
        // Focus is restored once after the whole cascade settles (see onSelection), not here.
      }

      // --- Source panel ------------------------------------------------------------

      // The flow whose snippet the source panel shows for a selection: the selected flow,
      // else (a bare scope/path selection) the first flow under it, so a file click still
      // shows code. null when nothing resolves.
      function sourceFlowFor(sel) {
        if (sel.flowId && byId.has(sel.flowId)) return byId.get(sel.flowId);
        if (!sel.path) return null;
        const ids = relevantFlowIds(sel);
        if (ids && ids.size) {
          // Deterministic: the lowest-line flow in the smallest path, good enough as a
          // representative; the user normally selects a flow before reading source.
          let best = null;
          ids.forEach(id => {
            const flow = byId.get(id);
            if (!flow) return;
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
        return null;
      }

      // Resolve a flow's own source lines from the SHARED file store. flow.source is a
      // lightweight {path, start_line, end_line, elided?} reference; the file is embedded
      // ONCE in sourceFiles[path] (deduped across every flow sharing it), so we slice this
      // flow's window out of that one copy. Returns {start_line, lines, elided, total} for
      // the flow's window, or null when the source is unavailable.
      function resolveFlowSource(flow) {
        const ref = flow && flow.source;
        if (!ref || !ref.path) return null;
        const file = sourceFiles[ref.path];
        if (!file || !Array.isArray(file.lines)) return null;
        const from = ref.start_line;
        if (from == null) return null;
        const to = ref.end_line != null ? ref.end_line : from;
        // The store covers a union range starting at file.start_line; slice this flow's
        // window out of it. The embedded (capped) window may be shorter than from..to when
        // the flow's tail was elided, so the slice naturally stops at the embedded end.
        const offset = from - file.start_line;
        if (offset < 0) return null;
        const lines = file.lines.slice(offset, offset + (to - from + 1));
        if (!lines.length) return null;
        return {
          start_line: from,
          lines: lines,
          // elided => the flow spans more lines than were embedded; total is the full
          // (uncapped) count so the panel can show how many lines were dropped.
          elided: !!ref.elided,
          total: to - from + 1,
        };
      }

      // Map each source line to the node that should be selected when that line is clicked,
      // preferring the NARROWEST-span node covering it. The entry node (and any whole-flow
      // node) spans the ENTIRE flow, so a naive first-node-wins maps every line to it and a
      // code click always selects the entry block. Instead: skip any node whose span equals
      // the flow's own span (the entry/whole-flow node), and when two nodes cover a line keep
      // the one with the smaller (end_line - start_line) -- so the `if` line lands on the
      // decision and a `return` line on that terminal. General over node order and nesting.
      function buildLineToNode(flow) {
        const loc = flow.location || {};
        const flowSpan =
          loc.start_line != null && loc.end_line != null
            ? loc.end_line - loc.start_line
            : null;
        const lineToNode = new Map(); // line -> {id, span}
        (flow.nodes || []).forEach(node => {
          const nloc = node.location || {};
          const from = nloc.start_line;
          if (from == null) return;
          const to = nloc.end_line != null ? nloc.end_line : from;
          const span = to - from;
          // Skip the entry/whole-flow node: it covers everything, so it is never the
          // "block on this line". A node whose span >= the flow's span is that node.
          if (flowSpan != null && span >= flowSpan) return;
          for (let ln = from; ln <= to; ln++) {
            const cur = lineToNode.get(ln);
            if (!cur || span < cur.span) lineToNode.set(ln, { id: node.id, span: span });
          }
        });
        return lineToNode;
      }

      // Resolve the source range that should read as selected. A node selection wins and
      // marks the exact logic block. A plain flow selection still marks the flow span, so
      // clicking a top-level block or an edge target visibly lands on a concrete piece of
      // code rather than merely opening the surrounding file.
      function selectedSourceRange(flow, sel) {
        if (sel.nodeId) {
          const node = LC.nodeById ? LC.nodeById(flow.id, sel.nodeId) : null;
          if (node && node.location) {
            const from = node.location.start_line;
            return {
              from: from,
              to: node.location.end_line != null ? node.location.end_line : from,
            };
          }
        }
        if (
          sel.line != null &&
          (!sel.path || !flow.location || !flow.location.path || sel.path === flow.location.path)
        ) {
          return {
            from: sel.line,
            to: sel.endLine != null ? sel.endLine : sel.line,
          };
        }
        if (sel.flowId === flow.id && flow.location && flow.location.start_line != null) {
          const from = flow.location.start_line;
          return {
            from: from,
            to: flow.location.end_line != null ? flow.location.end_line : from,
          };
        }
        return null;
      }

      // Render the flow's snippet with gutter line numbers. When a flow or node is
      // selected, the covered line range is marked + scrolled into view. The snippet spans
      // exactly the flow's own range, so node lines fall inside it.
      function renderSource(sel) {
        if (!sourceBody) return;
        const flow = sourceFlowFor(sel);
        clear(sourceBody);
        if (sourceFileEl) sourceFileEl.textContent = "";
        if (sourcePanel) sourcePanel.hidden = !flow;

        if (!flow) {
          sourceBody.appendChild(
            el("p", "panel-empty", "Select a flow or node to view its source.")
          );
          sourceStatus = "no source selected";
          return;
        }
        if (sourceFileEl) {
          sourceFileEl.textContent = flow.location.path + ":" + flow.location.start_line;
          sourceFileEl.title = flow.location.path;
        }
        sourceStatus = "source: " + flow.location.path + ":" + flow.location.start_line;

        const snippet = resolveFlowSource(flow);
        if (!snippet || !snippet.lines.length) {
          // Source unavailable (missing/binary file, or no snippet embedded) -- tolerated,
          // never a crash. Show a clear note rather than empty space.
          sourceBody.appendChild(
            el("p", "panel-empty", "Source unavailable for this file.")
          );
          return;
        }

        const lineToNode = buildLineToNode(flow);

        const selectedRange = selectedSourceRange(flow, sel);
        const hiFrom = selectedRange ? selectedRange.from : null;
        const hiTo = selectedRange ? selectedRange.to : null;

        const pre = el("div", "code-block");
        pre.setAttribute("role", "presentation");
        let firstHi = null;
        snippet.lines.forEach((text, i) => {
          const lineNo = snippet.start_line + i;
          const entry = lineToNode.get(lineNo);
          const nodeId = entry ? entry.id : null;
          // A div (not a <button>) so the line sits cleanly inside the code block; made
          // keyboard-activatable via role=button + tabindex + the Enter/Space handler below.
          const lineEl = el("div", "code-line" + (nodeId ? " has-node" : ""));
          lineEl.setAttribute("data-line", String(lineNo));
          if (nodeId) {
            lineEl.setAttribute("role", "button");
            lineEl.setAttribute("tabindex", "0");
            lineEl.setAttribute("data-node-id", nodeId);
            lineEl.title = `Select logic block on line ${lineNo}`;
          }
          const isHi = hiFrom != null && lineNo >= hiFrom && lineNo <= hiTo;
          if (isHi) {
            lineEl.classList.add("selected");
            if (!firstHi) firstHi = lineEl;
          }

          const gutter = el("span", "code-gutter", String(lineNo));
          gutter.setAttribute("aria-hidden", "true");
          // The code text is the ONE place untrusted source enters the DOM: textContent
          // only. A line containing markup or a closing script tag renders as literal
          // characters -- never parsed, never executed.
          const code = el("span", "code-text", text.length ? text : " ");

          lineEl.append(gutter, code);

          if (nodeId) {
            const activateLine = () => {
              // Selecting a source line selects its block: publish the node so shell.js
              // lights the canvas block, the tree marks the file, and this panel marks the
              // line -- all from the one store. Record the line so focus returns to the
              // equivalent line after the re-render this triggers (else it drops to <body>).
              pendingFocus = { panel: "source", id: lineNo };
              if (LC.selectFlow) LC.selectFlow(flow.id);
              LC.select({
                flowId: flow.id,
                nodeId: nodeId,
                path: flow.location.path,
                findingId: null,
                line: lineNo,
                endLine: lineNo,
              });
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

        // When the flow's tail was elided (a very long function), say how many lines were
        // dropped rather than silently showing a truncated snippet.
        if (snippet.elided) {
          const dropped = snippet.total - snippet.lines.length;
          sourceBody.appendChild(
            el("p", "code-elided", dropped + " more line" + (dropped === 1 ? "" : "s") + " not shown")
          );
        }
        // Focus is restored once after the whole cascade settles (see onSelection), not here.

        // Bring the highlighted block's first line into view within the scroll area
        // (not the page): a large snippet scrolls, it never overflows the panel.
        if (firstHi && typeof firstHi.scrollIntoView === "function") {
          firstHi.scrollIntoView({ block: "nearest" });
        }
      }

      // --- Subscribe both panels to the shared store -------------------------------

      function onSelection(sel) {
        renderSource(sel);
        renderErrors(sel);
        // One combined announcement per selection (source + findings), so neither panel's
        // status clobbers the other's in the single shared live region.
        flushAnnounce();
        // Restore focus to the panel item the user just activated AFTER the whole cascade
        // settles, so chart focus updates do not immediately overwrite it.
        if (pendingFocus) afterCascade(restorePendingFocus);
      }
      if (LC.onSelection) LC.onSelection(onSelection);
      // Prime once with the initial (empty) selection so the panels show their hints.
      onSelection(LC.selection || {});

      if (reviewQueueBtn) {
        reviewQueueBtn.addEventListener("click", () => {
          reviewQueueMode = !reviewQueueMode;
          reviewQueueBtn.setAttribute("aria-pressed", reviewQueueMode ? "true" : "false");
          reviewQueueBtn.classList.toggle("active", reviewQueueMode);
          onSelection(LC.selection || {});
        });
      }

      // --- Full-screen canvas (Phase 4.5) -----------------------------------------
      // Maximizes the canvas and hides the side panels. Uses the browser Fullscreen API
      // when available; otherwise a CSS "maximize in page" fallback via a
      // body[data-fullscreen] class. Esc and the toggle both exit; the selection store is
      // never touched, so the panels are correct the moment the layout returns.
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
      // The in-page CSS fallback is intentional state we own (true only when we chose the
      // class fallback). The real Fullscreen API state is read live from fsElement(). The
      // body[data-fullscreen] attribute is a DERIVED CSS flag set by reflectFsState -- it
      // is NEVER read back as state, so the two mechanisms can never feed back into a loop
      // (an API exit clears the attribute instead of latching it on).
      let fallbackActive = false;
      function isMaximized() {
        return fallbackActive || fsElement() === mainEl;
      }
      // Expose the in-page fallback state so other shell handlers can defer to panels.js:
      // while the CSS fallback is maximized, panels.js owns Esc and exits the fallback.
      // The real Fullscreen API path is handled by the browser, so this flag is only ever
      // true for the fallback.
      LC.fullscreenFallbackActive = () => fallbackActive;

      function reflectFsState() {
        const on = isMaximized();
        if (fsToggle) {
          fsToggle.setAttribute("aria-pressed", on ? "true" : "false");
          fsToggle.title = on ? "Exit full screen (Esc)" : "Full screen (Esc to exit)";
        }
        // Derived CSS flag: drives the in-page maximize + panel hiding for BOTH the class
        // fallback and the real API (so :fullscreen and [data-fullscreen] share one rule).
        // Leaving fullscreen by any means (our toggle, F11, platform Esc -> fullscreenchange)
        // clears it and restores the layout.
        if (on) body.setAttribute("data-fullscreen", "");
        else body.removeAttribute("data-fullscreen");
        // The viewBox depends on the SVG's pixel size, which just changed; re-apply it so
        // the drawing fills the new area without a manual pan/zoom.
        if (LC.updateViewBox) LC.updateViewBox();
      }

      function requestFs() {
        if (!mainEl) return Promise.resolve();
        const req =
          mainEl.requestFullscreen ||
          mainEl.webkitRequestFullscreen ||
          mainEl.msRequestFullscreen;
        try {
          const r = req.call(mainEl);
          return r && typeof r.then === "function" ? r : Promise.resolve();
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
            const r = exit.call(document);
            return r && typeof r.then === "function" ? r : Promise.resolve();
          } catch (_) {}
        }
        return Promise.resolve();
      }

      function enterMaximize() {
        if (fsApiSupported) {
          // Try the real API; if it rejects (e.g. no user-activation), fall back to the
          // in-page class so the toggle always does something.
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
        // Clear the fallback intent first, then drop the real fullscreen if we are in it.
        // reflectFsState (called now and again on fullscreenchange) recomputes from the
        // live API state + this flag, never from the derived CSS attribute.
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

      LC.toggleFullscreen = toggleFullscreen;

      if (fsToggle) {
        fsToggle.addEventListener("click", toggleFullscreen);
      }
      // Keep aria-pressed + layout correct when fullscreen changes outside our toggle.
      ["fullscreenchange", "webkitfullscreenchange"].forEach(evt => {
        document.addEventListener(evt, reflectFsState);
      });
      // Esc exits the in-page maximize fallback (the real Fullscreen API handles its own
      // Esc, which fires fullscreenchange -> reflectFsState). Ignored while typing.
      document.addEventListener("keydown", event => {
        if (event.key !== "Escape") return;
        const t = event.target;
        if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || "")) return;
        if (fallbackActive) {
          exitMaximize();
        }
      });
    })();
