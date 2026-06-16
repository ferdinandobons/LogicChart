
    // Directory tree for the left rail. Reads the nested {name, path, type, children,
    // flow_ids} tree the payload builds (payload.tree) and the LC surface shell.js
    // exposes (selectFlow / sortFlows / byId). Folders are collapsible rows; file leaves
    // expand to list their flows, each clickable to select that flow in the canvas -
    // exactly as the old flat flow list did.
    //
    // Accessibility: the container is a WAI-ARIA tree (role="tree"); every dir/file/flow
    // row is a role="treeitem" with aria-level and (when expandable) aria-expanded, and
    // each row's children sit in a role="group". Keyboard follows the tree pattern with a
    // roving tabindex (exactly one row is tabbable at a time).
    (function () {
      const LC = window.LC || {};
      const model = LC.model || {};
      const fullTree = model.tree;
      const byId = LC.byId || new Map();
      const treeEl = document.getElementById("tree");
      const langFilterEl = document.getElementById("langFilter");
      const searchEl = document.getElementById("globalSearch");
      if (!treeEl || !fullTree) return;

      const sortFlows = LC.sortFlows || (list => [...list]);
      // The languages dropdown only appears for polyglot repos (>1 language), mirroring
      // the old rail's visibility rule. "" means "All languages".
      const languages = Array.isArray(model.languages) ? model.languages : [];
      const scopeNames = new Set(Object.keys(model.scopes || {}));
      const findings = LC.findings || model.findings || [];
      const findingsByFlow = new Map();
      findings.forEach(finding => {
        if (!finding.flow_id) return;
        const list = findingsByFlow.get(finding.flow_id) || [];
        list.push(finding);
        findingsByFlow.set(finding.flow_id, list);
      });
      let activeLang = "";
      let activeQuery = "";

      // Per-render lookup maps, rebuilt every time the tree is (re)rendered so a language
      // change cleanly replaces them.
      let dirRows = new Map(); // path -> dir <button>
      let fileRows = new Map(); // path -> file <button>
      let flowRows = new Map(); // flowId -> flow <button>
      let childContainers = new Map(); // path -> children <div>
      let lastActiveFlowId = LC.activeFlowId ? LC.activeFlowId() : null;
      let suppressScopeFocus = false;

      function svgFolderIcon(open) {
        const ns = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(ns, "svg");
        svg.setAttribute("viewBox", "0 0 16 16");
        svg.setAttribute("class", "tree-caret" + (open ? " open" : ""));
        svg.setAttribute("aria-hidden", "true");
        const path = document.createElementNS(ns, "path");
        path.setAttribute("d", "M6 4l4 4-4 4");
        svg.appendChild(path);
        return svg;
      }

      function makeRow(className, depth) {
        const row = document.createElement("button");
        row.type = "button";
        row.className = className;
        row.style.setProperty("--depth", String(depth));
        row.setAttribute("role", "treeitem");
        row.setAttribute("aria-level", String(depth + 1));
        // Roving tabindex: every row starts untabbable; one is promoted after render.
        row.tabIndex = -1;
        return row;
      }

      function flowRole(flow) {
        return flow.is_entrypoint ? "ENTRY" : "SUBFLOW";
      }

      function treePathLabel(node) {
        if (!node || node.type !== "file") return node ? node.name : "";
        const segments = String(node.path || "").split("/").filter(Boolean);
        if (segments.length <= 2) return segments.join("/") || node.name;
        const generic = /^(index|route|page|layout|handler|main)\.[^.]+$/i.test(node.name);
        return generic ? segments.slice(-2).join("/") : node.name;
      }

      // Resolve a file node's flow ids to flows, pruned to the active language.
      function flowsForFile(file) {
        const flows = (file.flow_ids || []).map(id => byId.get(id)).filter(Boolean);
        const byLanguage = activeLang ? flows.filter(f => f.language === activeLang) : flows;
        const visible = activeQuery ? byLanguage.filter(flowMatchesQuery) : byLanguage;
        return sortFlows(visible);
      }

      function flowMatchesQuery(flow) {
        if (!activeQuery) return true;
        const findingsText = (findingsByFlow.get(flow.id) || [])
          .map(finding => `${finding.kind || ""} ${finding.message || ""} ${finding.evidence || ""}`)
          .join(" ");
        const scope = flow.metadata && Array.isArray(flow.metadata.scope)
          ? flow.metadata.scope.join(" ")
          : "";
        const haystack = [
          flow.name,
          flow.symbol,
          flow.language,
          flow.framework,
          flow.entry_kind,
          scope,
          flow.location && flow.location.path,
          findingsText,
        ].join(" ").toLowerCase();
        return activeQuery.split(/\s+/).every(term => haystack.includes(term));
      }

      // Whether a node has at least one flow that survives the active-language filter.
      // A dir survives if any descendant file does.
      function nodeHasVisibleFlows(node) {
        if (node.type === "file") return flowsForFile(node).length > 0;
        return (node.children || []).some(nodeHasVisibleFlows);
      }

      // Render a file's flows as indented rows beneath it.
      function renderFlows(file, container, depth) {
        const flows = flowsForFile(file);
        flows.forEach(flow => {
          const row = makeRow("tree-flow", depth);
          row.setAttribute("data-flow-id", flow.id);
          row.setAttribute("data-path", file.path);
          const name = document.createElement("strong");
          name.textContent = flow.name;
          const badges = document.createElement("span");
          badges.className = "tree-flow-badges";
          const role = document.createElement("span");
          role.className = "tree-flow-badge role-" + flowRole(flow).toLowerCase();
          role.textContent = flowRole(flow);
          const kind = document.createElement("span");
          kind.className = "tree-flow-badge";
          kind.textContent = flow.entry_kind || "flow";
          badges.append(role, kind);
          row.append(name, badges);
          row.addEventListener("click", () => {
            if (LC.selectFlow) LC.selectFlow(flow.id);
          });
          flowRows.set(flow.id, row);
          container.appendChild(row);
        });
        if (!flows.length) {
          const empty = makeRow("tree-flow tree-empty", depth);
          empty.disabled = true;
          empty.textContent = "No flows";
          container.appendChild(empty);
        }
      }

      function renderNode(node, parent, depth) {
        // Skip subtrees with nothing to show under the active language filter.
        if (!nodeHasVisibleFlows(node)) return;

        const isDir = node.type === "dir";
        const row = makeRow(isDir ? "tree-dir" : "tree-file", depth);
        row.setAttribute("data-path", node.path);
        row.setAttribute("aria-expanded", "false");
        const caret = svgFolderIcon(false);
        const label = document.createElement("span");
        label.className = "tree-label";
        label.textContent = treePathLabel(node);
        if (!isDir && label.textContent !== node.path) label.title = node.path;
        row.append(caret, label);

        if (!isDir) {
          const count = flowsForFile(node).length;
          if (count) {
            const badge = document.createElement("span");
            badge.className = "tree-count";
            badge.textContent = String(count);
            row.appendChild(badge);
          }
        }

        const children = document.createElement("div");
        children.className = "tree-children";
        children.setAttribute("role", "group");
        children.hidden = true;
        childContainers.set(node.path, children);

        row.addEventListener("click", () => toggle(node, row, children, depth));
        if (isDir) dirRows.set(node.path, row);
        else fileRows.set(node.path, row);
        parent.append(row, children);
      }

      // Lazily build a node's children the first time it is opened, then toggle.
      function toggle(node, row, children, depth) {
        const open = children.hidden;
        if (open && !children.dataset.built) {
          if (node.type === "dir") {
            node.children.forEach(child => renderNode(child, children, depth + 1));
          } else {
            renderFlows(node, children, depth + 1);
          }
          children.dataset.built = "1";
        }
        children.hidden = !open;
        row.setAttribute("aria-expanded", String(open));
        const caret = row.querySelector(".tree-caret");
        if (caret) caret.classList.toggle("open", open);
        // Opening any tree path focuses the same area on the canvas. Top-level scopes use
        // the scope route; nested folders/files use the path route so the canvas can
        // highlight that sub-area while keeping the global map visible.
        if (open && !suppressScopeFocus) {
          if (LC.focusPath) {
            LC.focusPath(node.path);
          } else if (node.type === "dir" && scopeNames.has(node.path) && LC.focusScope) {
            LC.focusScope(node.path);
          }
        }
      }

      function cssEscape(value) {
        return window.CSS && CSS.escape ? CSS.escape(value) : value.replace(/["\\]/g, "\\$&");
      }

      // The dir/file row for a path (never a flow row, which shares its file's path).
      function structureRow(path) {
        return treeEl.querySelector(
          `.tree-dir[data-path="${cssEscape(path)}"], .tree-file[data-path="${cssEscape(path)}"]`
        );
      }

      // Open every ancestor folder + the file of a path so its flow row is visible.
      function revealPath(path) {
        const segments = path.split("/");
        let prefix = "";
        segments.forEach(segment => {
          prefix = prefix ? `${prefix}/${segment}` : segment;
          const children = childContainers.get(prefix);
          const row = structureRow(prefix);
          if (children && row && children.hidden) {
            suppressScopeFocus = true;
            try {
              row.click();
            } finally {
              suppressScopeFocus = false;
            }
          }
        });
      }

      function highlightActive(flowId) {
        flowRows.forEach((row, id) => row.classList.toggle("active", id === flowId));
        dirRows.forEach(row => row.classList.remove("active-folder"));
        fileRows.forEach(row => row.classList.remove("active-file"));
        const flow = byId.get(flowId);
        if (flow) {
          const fileRow = fileRows.get(flow.location.path);
          if (fileRow) fileRow.classList.add("active-file");
        }
      }

      function highlightPath(path) {
        flowRows.forEach(row => row.classList.remove("active"));
        dirRows.forEach(row => row.classList.remove("active-folder"));
        fileRows.forEach(row => row.classList.remove("active-file"));
        if (!path) return;
        revealPath(path);
        const row = structureRow(path);
        if (row) {
          row.classList.toggle("active-folder", row.classList.contains("tree-dir"));
          row.classList.toggle("active-file", row.classList.contains("tree-file"));
        }
      }

      function setLanguageFilterAvailability(sel) {
        if (!langFilterEl || languages.length <= 1) return;
        const locked = !!(sel && sel.flowId);
        langFilterEl.disabled = locked;
        langFilterEl.title = locked
          ? "Return to the codebase or scope level to change language"
          : "";
      }

      function clearCanvasSelectionForLanguageFilter() {
        const sel = LC.selection || {};
        if (!(sel.flowId || sel.nodeId || sel.path || sel.scope)) return;
        lastActiveFlowId = null;
        highlightActive(null);
        if (LC.showL0) {
          LC.showL0();
        } else if (LC.select) {
          LC.select({ scope: null, path: null, flowId: null, nodeId: null, findingId: null });
        }
      }

      function resetLanguageFilterForFlow(flow) {
        if (!langFilterEl || !flow || !activeLang || flow.language === activeLang) return;
        activeLang = "";
        langFilterEl.value = "";
        render();
      }

      // --- Roving tabindex + keyboard navigation (WAI-ARIA tree pattern) --------------

      // Every currently rendered + visible (no hidden ancestor) row, in DOM order.
      function visibleRows() {
        return [...treeEl.querySelectorAll(".tree-dir, .tree-file, .tree-flow")].filter(
          row => row.offsetParent !== null
        );
      }

      // Promote exactly one row to tabindex=0; the rest are -1.
      function setRovingTarget(row) {
        treeEl.querySelectorAll('[role="treeitem"]').forEach(r => {
          r.tabIndex = r === row ? 0 : -1;
        });
      }

      // After any (re)render or expand/collapse, keep a single tabbable row. Prefer the
      // active flow's row, else the active file, else the first visible row.
      function refreshRovingTarget() {
        const rows = visibleRows();
        if (!rows.length) return;
        let target =
          (lastActiveFlowId && flowRows.get(lastActiveFlowId)) ||
          treeEl.querySelector(".tree-dir.active-folder") ||
          treeEl.querySelector(".tree-file.active-file");
        if (!target || target.offsetParent === null) target = rows[0];
        setRovingTarget(target);
      }

      function isExpandable(row) {
        return row.hasAttribute("aria-expanded") && !row.classList.contains("tree-empty");
      }

      function isExpanded(row) {
        return row.getAttribute("aria-expanded") === "true";
      }

      // The children container a dir/file row controls (its next sibling).
      function rowChildren(row) {
        const next = row.nextElementSibling;
        return next && next.classList.contains("tree-children") ? next : null;
      }

      // The parent treeitem row of a given row, or null at the top level.
      function parentRow(row) {
        const group = row.parentElement;
        if (!group || !group.classList.contains("tree-children")) return null;
        const prev = group.previousElementSibling;
        return prev && prev.getAttribute("role") === "treeitem" ? prev : null;
      }

      function focusRow(row) {
        if (!row) return;
        setRovingTarget(row);
        row.focus();
      }

      function moveFocus(current, delta) {
        const rows = visibleRows();
        const i = rows.indexOf(current);
        if (i === -1) return;
        const next = rows[i + delta];
        if (next) focusRow(next);
      }

      function onKeydown(event) {
        const row = event.target.closest('[role="treeitem"]');
        if (!row || !treeEl.contains(row)) return;
        switch (event.key) {
          case "ArrowDown":
            event.preventDefault();
            moveFocus(row, 1);
            break;
          case "ArrowUp":
            event.preventDefault();
            moveFocus(row, -1);
            break;
          case "ArrowRight": {
            event.preventDefault();
            if (isExpandable(row)) {
              if (!isExpanded(row)) {
                row.click(); // expand
              } else {
                const children = rowChildren(row);
                const first = children && children.querySelector('[role="treeitem"]');
                if (first) focusRow(first);
              }
            }
            break;
          }
          case "ArrowLeft": {
            event.preventDefault();
            if (isExpandable(row) && isExpanded(row)) {
              row.click(); // collapse
            } else {
              const parent = parentRow(row);
              if (parent) focusRow(parent);
            }
            break;
          }
          case "Home": {
            event.preventDefault();
            const rows = visibleRows();
            if (rows.length) focusRow(rows[0]);
            break;
          }
          case "End": {
            event.preventDefault();
            const rows = visibleRows();
            if (rows.length) focusRow(rows[rows.length - 1]);
            break;
          }
          case "Enter":
          case " ":
            event.preventDefault();
            row.click();
            break;
          default:
            return;
        }
      }

      treeEl.addEventListener("keydown", onKeydown);
      // A pointer click on a row makes it the roving target, so the next Tab in / arrow
      // key starts from where the user clicked. Capture phase so this runs regardless of
      // the row's own click handler (which expands/collapses or selects a flow).
      treeEl.addEventListener(
        "click",
        event => {
          const row = event.target.closest('[role="treeitem"]');
          if (row) setRovingTarget(row);
        },
        true
      );

      // --- (Re)render -----------------------------------------------------------------

      function render() {
        treeEl.replaceChildren();
        dirRows = new Map();
        fileRows = new Map();
        flowRows = new Map();
        childContainers = new Map();
        (fullTree.children || []).forEach(child => renderNode(child, treeEl, 0));
        if (!treeEl.children.length) {
          const empty = document.createElement("div");
          empty.className = "tree-empty-state";
          empty.textContent = "No matching flows";
          treeEl.appendChild(empty);
        }

        // Re-reveal + re-highlight whatever flow is active so a language switch keeps the
        // canvas selection reflected when the active flow survives the filter.
        const activeId = lastActiveFlowId;
        if (activeId) {
          const flow = byId.get(activeId);
          if (flow && (!activeLang || flow.language === activeLang)) {
            revealPath(flow.location.path);
            highlightActive(activeId);
          }
        }
        refreshRovingTarget();
      }

      // --- Language filter ------------------------------------------------------------

      function setupLanguageFilter() {
        if (!langFilterEl) return;
        // Only offer the control for polyglot repos (mirror the old visibility rule).
        if (languages.length <= 1) {
          langFilterEl.style.display = "none";
          return;
        }
        langFilterEl.replaceChildren();
        const all = document.createElement("option");
        all.value = "";
        all.textContent = "All languages";
        langFilterEl.appendChild(all);
        languages.forEach(lang => {
          const option = document.createElement("option");
          option.value = lang;
          option.textContent = lang;
          langFilterEl.appendChild(option);
        });
        langFilterEl.style.display = "";
        langFilterEl.addEventListener("change", () => {
          activeLang = langFilterEl.value;
          render();
          clearCanvasSelectionForLanguageFilter();
        });
      }

      function setupSearch() {
        if (!searchEl) return;
        searchEl.addEventListener("input", () => {
          activeQuery = searchEl.value.trim().toLowerCase();
          render();
          clearCanvasSelectionForLanguageFilter();
        });
      }

      setupSearch();
      setupLanguageFilter();
      render();

      LC.onFlowSelected = function (flow) {
        if (!flow) return;
        resetLanguageFilterForFlow(flow);
        lastActiveFlowId = flow.id;
        revealPath(flow.location.path);
        highlightActive(flow.id);
        refreshRovingTarget();
      };

      // Bidirectional highlight: a selection made on ANY surface (a canvas block, a source
      // line, a finding row) reveals + highlights the owning file/flow row here, in the one
      // shared accent. Block clicks publish a flowId without going through onFlowSelected,
      // so subscribe to the store directly. revealPath + highlightActive are the same calls
      // onFlowSelected uses, so the tree's accent never drifts from the rest of the app.
      if (LC.onSelection) {
        LC.onSelection(function (sel) {
          setLanguageFilterAvailability(sel);
          const flowId = sel.flowId;
          if (!flowId) {
            lastActiveFlowId = null;
            highlightPath(sel.path);
            refreshRovingTarget();
            return;
          }
          if (flowId === lastActiveFlowId) return; // already reflected.
          const flow = byId.get(flowId);
          if (!flow) return;
          resetLanguageFilterForFlow(flow);
          lastActiveFlowId = flowId;
          revealPath(flow.location.path);
          highlightActive(flowId);
          refreshRovingTarget();
        });
      }
    })();
