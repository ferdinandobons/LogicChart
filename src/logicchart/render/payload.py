from __future__ import annotations

from pathlib import Path
from typing import Any

from logicchart.model import FileRecord, Flow, ProjectModel


def build_payload(model: ProjectModel, source_root: Path | None = None) -> dict[str, Any]:
    data = model.to_dict()
    if source_root is not None:
        data["root"] = str(source_root)
    data["tree"] = build_tree(model.files, model.flows)
    scopes = build_scope_index(model.flows)
    data["scopes"] = scopes
    data["languages"] = build_language_index(model.flows)
    data["scope_edges"] = build_scope_edges(model.flows, scopes)
    # Embed the actual source lines the viewer's source panel needs to show real code
    # offline. Each file's lines are embedded ONCE in ``data["source_files"]`` and each
    # flow gets a lightweight reference into it (the only new data; mutates ``data``).
    data["source_files"] = attach_source_snippets(data["flows"], source_root)
    return data


# Per-flow cap on embedded source. A flow over a huge function (e.g. a 1000-line handler)
# must not embed every line: keep at most this many HEAD lines and mark the tail elided, so
# the page stays small and the panel can show an "N more lines" marker. Bounds the payload
# regardless of function size while keeping the head (where the entry/decisions live) intact.
MAX_SNIPPET_LINES = 200


def attach_source_snippets(
    flows: list[dict[str, Any]], source_root: Path | None
) -> dict[str, dict[str, Any]]:
    """Attach a lightweight source reference to each flow and return the shared file store.

    For every flow, ``flow["source"]`` becomes either ``None`` (no source available) or a
    reference ``{"path", "start_line", "end_line", "elided"?}`` into the returned
    ``source_files`` map. ``source_files[path] = {"start_line": int, "lines": [str, ...]}``
    embeds, ONCE per file, the union of the (capped) line ranges every non-test flow needs
    in that file -- so a file with many flows is embedded a single time, not once per flow.

    Bounding (two layers, both general over function/file size):

    * **Per-flow cap.** A flow spanning more than :data:`MAX_SNIPPET_LINES` lines keeps only
      its first ``MAX_SNIPPET_LINES`` lines; its reference carries ``"elided": True`` and the
      ``end_line`` is the original (uncapped) end so the panel can show how many lines were
      dropped. The file store only ever embeds the capped (head) range.
    * **File-level de-dup.** Each file's lines are read and stored once, covering the union
      of the capped ranges its flows need -- never the same lines twice, never whole trees.

    Self-contained (no fetch), language-agnostic (line slices work for any supported
    language), and deliberately tolerant so it stays general for any codebase: a flow whose
    file is missing, outside ``source_root``, binary, or otherwise unreadable gets
    ``flow["source"] = None`` and never raises. Each file is read at most once.

    ``flows`` is the JSON-serializable dict form (post ``model.to_dict()``); the reference is
    added to each dict so it rides along in the embedded payload.
    """
    if source_root is None:
        for flow in flows:
            flow["source"] = None
        return {}

    root = source_root
    # path -> list[str] of the file's lines (newline-stripped), or None when unreadable.
    file_cache: dict[str, list[str] | None] = {}

    def lines_for(path: str) -> list[str] | None:
        if path in file_cache:
            return file_cache[path]
        result: list[str] | None
        try:
            # Resolve under the source root and guard against path escapes (a flow whose
            # location.path is absolute or climbs out of the tree gets no snippet).
            target = (root / path).resolve()
            root_resolved = root.resolve()
            if root_resolved != target and root_resolved not in target.parents:
                result = None
            else:
                result = target.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError, ValueError):
            result = None
        file_cache[path] = result
        return result

    # First pass: resolve each flow's (clamped, capped) reference and remember the line
    # range each file must cover. ``needed[path]`` = (min start, max end) over its flows'
    # clamped+capped ranges, so the file is embedded once across the union.
    needed: dict[str, tuple[int, int]] = {}
    for flow in flows:
        location = flow.get("location") or {}
        path = location.get("path")
        start = location.get("start_line")
        end = location.get("end_line")
        if not path or not isinstance(start, int) or not isinstance(end, int):
            flow["source"] = None
            continue
        file_lines = lines_for(path)
        if file_lines is None:
            flow["source"] = None
            continue
        # Lines are 1-based and inclusive; clamp to the file so an out-of-range end never
        # over-reads and a degenerate range still yields whatever overlaps the file.
        lo = max(1, start)
        hi = min(len(file_lines), end)
        if hi < lo:
            flow["source"] = None
            continue
        # Per-flow cap: keep at most MAX_SNIPPET_LINES head lines; mark the rest elided.
        capped_hi = min(hi, lo + MAX_SNIPPET_LINES - 1)
        elided = capped_hi < hi
        ref: dict[str, Any] = {"path": path, "start_line": lo, "end_line": hi}
        if elided:
            ref["elided"] = True
        flow["source"] = ref
        # The file store only needs the capped (embedded) range for each flow.
        prev = needed.get(path)
        if prev is None:
            needed[path] = (lo, capped_hi)
        else:
            needed[path] = (min(prev[0], lo), max(prev[1], capped_hi))

    # Second pass: embed each file once, covering the union of the capped ranges. The flow
    # references slice their own (capped) window out of this on the client.
    source_files: dict[str, dict[str, Any]] = {}
    for path, (lo, hi) in needed.items():
        file_lines = lines_for(path)
        if file_lines is None:
            continue
        source_files[path] = {"start_line": lo, "lines": file_lines[lo - 1 : hi]}
    return source_files


def _is_test_flow(flow: Flow) -> bool:
    """Whether a flow is a test flow, mirroring the old left rail's ``!flow.metadata.test``."""
    return bool(flow.metadata.get("test"))


def build_tree(files: list[FileRecord], flows: list[Flow]) -> dict[str, Any]:
    """Fold file paths into a nested dir/file tree.

    Each node has the shape ``{name, path, type, children, flow_ids}``. ``flow_ids``
    is populated on file leaves with the ids of flows whose ``location.path`` is that
    file; directories always carry ``[]``. A flow whose file is missing from ``files``
    still gets a leaf so no flow is dropped from the tree. Children are ordered
    deterministically: directories before files, each group sorted by name.

    Test flows are excluded (the old left rail hid them via ``!flow.metadata.test``);
    a file with only test flows is dropped entirely, and a directory that ends up
    with no surviving descendants is dropped too, so counts are not inflated.
    """
    # Only non-test flows are eligible. Map each file path to the surviving flow ids.
    non_test = [flow for flow in flows if not _is_test_flow(flow)]
    by_id = {flow.id: flow for flow in non_test}

    flows_for_path: dict[str, list[str]] = {}
    for record in files:
        # Keep the file's flow ids, but only the non-test ones.
        kept = [fid for fid in record.flow_ids if fid in by_id]
        if kept:
            flows_for_path[record.path] = kept
    for flow in non_test:
        path = flow.location.path
        ids = flows_for_path.setdefault(path, [])
        if flow.id not in ids:
            ids.append(flow.id)

    root = _new_node("", "", "dir")
    for path in flows_for_path:
        _insert_path(root, path, flows_for_path[path])
    _prune_empty(root)
    _sort_children(root)
    return root


def build_language_index(flows: list[Flow]) -> list[str]:
    """Sorted list of distinct ``flow.language`` across non-test flows.

    Powers the viewer's language dropdown for polyglot repos. Test flows are excluded
    so a language that only appears in tests does not surface a filter option for it.
    """
    languages = {flow.language for flow in flows if not _is_test_flow(flow) and flow.language}
    return sorted(languages)


def build_scope_index(flows: list[Flow]) -> dict[str, list[str]]:
    """Group flow ids by scope.

    Uses ``flow.metadata["scope"]`` (a list) when present; otherwise infers the
    scope as the top-level directory segment of ``flow.location.path`` (so it works
    with no ``[logicchart.scopes]`` declared). Never hard-codes scope names.

    Test flows are excluded with the same predicate ``build_tree`` /
    ``build_language_index`` / ``build_scope_edges`` use, so L0 scope counts and the
    L1 nodes agree with the directory tree's non-test universe. A scope that would
    contain only test flows (e.g. an inferred ``tests`` scope) is dropped entirely,
    rather than surfacing a super-node the tree hides.
    """
    index: dict[str, list[str]] = {}
    for flow in flows:
        if _is_test_flow(flow):
            continue
        scopes = flow.metadata.get("scope")
        if not scopes:
            scopes = [_top_level_segment(flow.location.path)]
        for scope in scopes:
            index.setdefault(scope, []).append(flow.id)
    return index


def build_scope_edges(flows: list[Flow], scope_index: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Aggregate cross-scope calls into ``[{from, to, count}]`` edges.

    For each non-test flow ``f`` and each resolved call target ``t`` (a flow id in the
    model), attribute the call to *every* (srcScope, dstScope) pair drawn from ``f``'s
    and ``t``'s scope memberships. A flow may belong to several scopes
    (``metadata["scope"]`` is a list), so its cross-scope calls are double-counted under
    each membership -- the documented convention that matches ``build_scope_index``,
    which already places a flow under every listed scope. Same-scope pairs (and calls
    to unresolved/external ids not in the model) are dropped: L0 shows only cross-scope
    structure. Keeping these edges in the payload makes the viewer deterministic and
    avoids deriving cross-scope topology in the browser.
    """
    by_id = {flow.id: flow for flow in flows}
    # flow id -> its scope memberships, recomputed the same way build_scope_index does.
    flow_scopes: dict[str, list[str]] = {}
    for scope, ids in scope_index.items():
        for flow_id in ids:
            flow_scopes.setdefault(flow_id, []).append(scope)

    counts: dict[tuple[str, str], int] = {}
    for flow in flows:
        if _is_test_flow(flow):
            continue
        src_scopes = flow_scopes.get(flow.id, [])
        if not src_scopes:
            continue
        for target in flow.calls:
            target_flow = by_id.get(target)
            # Mirror renderFlow's `if (!start || !end) return;` -- skip unresolved or
            # external call targets, and never count a call into a test flow.
            if target_flow is None or _is_test_flow(target_flow):
                continue
            dst_scopes = flow_scopes.get(target, [])
            for src in src_scopes:
                for dst in dst_scopes:
                    if src != dst:
                        counts[(src, dst)] = counts.get((src, dst), 0) + 1

    return [
        {"from": src, "to": dst, "count": count} for (src, dst), count in sorted(counts.items())
    ]


def _top_level_segment(path: str) -> str:
    """The first path segment, or the file's own name for a root-level file."""
    parts = [part for part in path.split("/") if part]
    return parts[0] if parts else path


def _new_node(name: str, path: str, node_type: str) -> dict[str, Any]:
    return {"name": name, "path": path, "type": node_type, "children": [], "flow_ids": []}


def _insert_path(root: dict[str, Any], path: str, flow_ids: list[str]) -> None:
    segments = [part for part in path.split("/") if part]
    if not segments:
        return
    node = root
    prefix = ""
    for index, segment in enumerate(segments):
        prefix = f"{prefix}/{segment}" if prefix else segment
        is_leaf = index == len(segments) - 1
        child = next((c for c in node["children"] if c["name"] == segment), None)
        if child is None:
            child = _new_node(segment, prefix, "file" if is_leaf else "dir")
            node["children"].append(child)
        node = child
    # `node` is now the leaf; attach flow ids without duplicating.
    for flow_id in flow_ids:
        if flow_id not in node["flow_ids"]:
            node["flow_ids"].append(flow_id)


def _prune_empty(node: dict[str, Any]) -> None:
    """Drop file leaves with no flow ids and directories with no surviving descendants.

    Recurses depth-first so a directory whose children all get pruned is itself dropped.
    The root is never removed by this (callers keep it), only its empty subtrees.
    """
    kept: list[dict[str, Any]] = []
    for child in node["children"]:
        if child["type"] == "dir":
            _prune_empty(child)
            if child["children"]:
                kept.append(child)
        elif child["flow_ids"]:
            kept.append(child)
    node["children"] = kept


def _sort_children(node: dict[str, Any]) -> None:
    node["children"].sort(key=lambda c: (c["type"] != "dir", c["name"]))
    for child in node["children"]:
        _sort_children(child)
