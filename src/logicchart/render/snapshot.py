from __future__ import annotations

from html import escape
from typing import Any

from logicchart.diagnostics import diagnostic_for_finding
from logicchart.model import Finding, Flow, FlowNode, NodeKind, ProjectModel

SNAPSHOT_FORMATS = ("svg",)
MAX_FLOW_NODES = 44


def unsupported_snapshot_format(requested: str) -> dict[str, Any]:
    return {
        "error": f"Unsupported snapshot format: {requested}",
        "error_code": "unsupported_snapshot_format",
        "requested_format": requested,
        "supported_formats": list(SNAPSHOT_FORMATS),
        "recoverable": True,
        "guardrail": (
            "This reports an unsupported visual export format; it is not a source-code "
            "logical finding."
        ),
    }


def render_flow_snapshot(
    model: ProjectModel,
    flow_id: str,
    *,
    highlight_node_ids: set[str] | None = None,
    title: str | None = None,
    max_nodes: int | None = None,
) -> dict[str, Any]:
    flow = next((item for item in model.flows if item.id == flow_id), None)
    if flow is None:
        return _snapshot_request_error("flow", flow_id)
    findings = [item for item in model.findings if item.flow_id == flow.id]
    highlighted = highlight_node_ids or set()
    rendered_nodes = _select_flow_nodes(flow, highlighted, max_nodes)
    svg = _flow_svg(flow, findings, highlighted, rendered_nodes=rendered_nodes, title=title)
    return {
        "format": "svg",
        "flow_id": flow.id,
        "title": title or flow.name,
        "svg": svg,
        "highlighted_node_ids": sorted(highlight_node_ids or []),
        "node_count": len(flow.nodes),
        "rendered_node_count": len(rendered_nodes),
        "omitted_node_count": max(0, len(flow.nodes) - len(rendered_nodes)),
    }


def render_finding_snapshot(
    model: ProjectModel, finding_id: str, *, max_nodes: int | None = None
) -> dict[str, Any]:
    finding = next((item for item in model.findings if item.id == finding_id), None)
    if finding is None:
        return _snapshot_request_error("finding", finding_id)
    flow = next((item for item in model.flows if item.id == finding.flow_id), None)
    if flow is None:
        return _snapshot_request_error("flow", finding.flow_id, finding_id=finding_id)
    node = next((item for item in flow.nodes if item.id == finding.node_id), None)
    highlighted = {finding.node_id} if finding.node_id else set()
    rendered_nodes = _select_flow_nodes(flow, highlighted, max_nodes)
    diagnostic = _diagnostic_for_snapshot(model, finding, flow, node)
    title = f"{finding.kind}: {finding.message}"
    svg = _flow_svg(
        flow,
        [item for item in model.findings if item.flow_id == flow.id],
        highlighted,
        rendered_nodes=rendered_nodes,
        title=title,
        finding=finding,
        diagnostic=diagnostic,
    )
    return {
        "format": "svg",
        "flow_id": flow.id,
        "title": title,
        "svg": svg,
        "highlighted_node_ids": sorted(highlighted),
        "node_count": len(flow.nodes),
        "rendered_node_count": len(rendered_nodes),
        "omitted_node_count": max(0, len(flow.nodes) - len(rendered_nodes)),
        "finding_id": finding.id,
        "diagnostic_category": diagnostic.get("category"),
        "evidence_item_count": len(diagnostic.get("evidence_chain", [])),
    }


def _snapshot_request_error(
    target_type: str,
    target_id: str,
    *,
    finding_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": f"Unknown {target_type}: {target_id}",
        "error_code": f"snapshot_{target_type}_not_found",
        "target_type": target_type,
        "target_id": target_id,
        "recoverable": True,
        "guardrail": (
            "This reports an invalid snapshot target from the generated model; it is not "
            "a source-code logical finding."
        ),
    }
    if finding_id is not None:
        payload["finding_id"] = finding_id
    return payload


def render_impact_snapshot(
    *,
    changed_files: list[str],
    direct: list[Flow],
    transitive: list[Flow],
    findings: list[Finding],
    max_flows: int | None = None,
    target_flow_ids: list[str] | None = None,
    target_symbols: list[str] | None = None,
    target_finding_ids: list[str] | None = None,
    unresolved_targets: list[Any] | None = None,
    impact_reasons: dict[str, list[str]] | None = None,
    subgraph_flow_ids: list[str] | None = None,
    subgraph_finding_ids: list[str] | None = None,
) -> dict[str, Any]:
    rendered_direct = _select_impact_flows(direct, max_flows)
    rendered_transitive = _select_impact_flows(transitive, max_flows)
    svg = _impact_svg(
        changed_files,
        direct,
        transitive,
        findings,
        rendered_direct=rendered_direct,
        rendered_transitive=rendered_transitive,
        unresolved_targets=unresolved_targets or [],
    )
    return {
        "format": "svg",
        "changed_files": changed_files,
        "target_flow_ids": target_flow_ids or [],
        "target_symbols": target_symbols or [],
        "target_finding_ids": target_finding_ids or [],
        "unresolved_targets": unresolved_targets or [],
        "impact_reasons": impact_reasons or {},
        "subgraph_flow_ids": subgraph_flow_ids or [],
        "subgraph_finding_ids": subgraph_finding_ids or [],
        "direct_flow_ids": [flow.id for flow in direct],
        "transitive_flow_ids": [flow.id for flow in transitive],
        "rendered_direct_flow_ids": [flow.id for flow in rendered_direct],
        "rendered_transitive_flow_ids": [flow.id for flow in rendered_transitive],
        "omitted_direct_flow_count": max(0, len(direct) - len(rendered_direct)),
        "omitted_transitive_flow_count": max(0, len(transitive) - len(rendered_transitive)),
        "finding_ids": [finding.id for finding in findings],
        "svg": svg,
    }


def _flow_svg(
    flow: Flow,
    findings: list[Finding],
    highlight_node_ids: set[str],
    *,
    rendered_nodes: list[FlowNode],
    title: str | None,
    finding: Finding | None = None,
    diagnostic: dict[str, Any] | None = None,
) -> str:
    nodes = rendered_nodes
    omitted = max(0, len(flow.nodes) - len(nodes))
    width = 920
    header_height = 108
    row_gap = 34
    node_width = 340
    node_height = 76
    x = 290
    positions = {
        node.id: (x, header_height + index * (node_height + row_gap))
        for index, node in enumerate(nodes)
    }
    graph_height = header_height + max(1, len(nodes)) * (node_height + row_gap) + 86
    panel = _finding_panel(finding, diagnostic) if finding and diagnostic else None
    height = max(graph_height, (panel["height"] + 132) if panel else graph_height)
    parts = [
        _svg_open(width, height, title or flow.name),
        _style(),
        f'<rect class="background" x="0" y="0" width="{width}" height="{height}" />',
        _text(28, 34, title or flow.name, "title"),
        _text(
            28,
            58,
            f"{flow.entry_kind} - {flow.language} - "
            f"{flow.location.path}:{flow.location.start_line}",
            "subtitle",
        ),
        _text(
            28,
            82,
            f"{len(flow.nodes)} nodes - {len(flow.edges)} edges - {len(findings)} findings",
            "meta",
        ),
    ]
    for edge in flow.edges:
        if edge.source not in positions or edge.target not in positions:
            continue
        parts.append(
            _edge(edge.source, edge.target, positions, node_width, node_height, edge.label)
        )
    for node in nodes:
        node_findings = [finding for finding in findings if finding.node_id == node.id]
        parts.append(
            _flow_node(
                node,
                positions[node.id],
                node_width,
                node_height,
                highlighted=node.id in highlight_node_ids,
                finding_count=len(node_findings),
            )
        )
    if omitted:
        parts.append(
            _text(
                28,
                height - 34,
                f"{omitted} additional nodes omitted from this compact snapshot.",
                "meta",
            )
        )
    if panel:
        parts.append(str(panel["svg"]))
    parts.append("</svg>")
    return "\n".join(parts)


def _impact_svg(
    changed_files: list[str],
    direct: list[Flow],
    transitive: list[Flow],
    findings: list[Finding],
    *,
    rendered_direct: list[Flow],
    rendered_transitive: list[Flow],
    unresolved_targets: list[Any],
) -> str:
    width = 920
    row_height = 84
    row_gap = 22
    rows = max(1, max(len(rendered_direct), len(rendered_transitive)))
    target_offset = 24 if unresolved_targets else 0
    height = 156 + target_offset + rows * (row_height + row_gap) + 80
    omitted_direct = max(0, len(direct) - len(rendered_direct))
    omitted_transitive = max(0, len(transitive) - len(rendered_transitive))
    parts = [
        _svg_open(width, height, "LogicChart impact snapshot"),
        _style(),
        f'<rect class="background" x="0" y="0" width="{width}" height="{height}" />',
        _text(28, 34, "Impact snapshot", "title"),
        _text(
            28,
            58,
            f"{len(changed_files)} changed files - {len(direct)} direct - "
            f"{len(transitive)} caller impact - {len(findings)} findings",
            "subtitle",
        ),
        _text(28, 84, _compact(", ".join(changed_files), 125), "meta"),
    ]
    if unresolved_targets:
        unresolved_label = ", ".join(_unresolved_target_label(item) for item in unresolved_targets)
        parts.append(
            _text(
                28,
                108,
                _compact(f"Unresolved targets: {unresolved_label}", 125),
                "meta",
            )
        )
    parts.extend(
        [
            _text(80, 126 + target_offset, "Direct impact", "column"),
            _text(530, 126 + target_offset, "Caller impact", "column"),
        ]
    )
    for index, flow in enumerate(rendered_direct):
        parts.append(
            _impact_box(
                flow,
                52,
                150 + target_offset + index * (row_height + row_gap),
                row_height,
            )
        )
    for index, flow in enumerate(rendered_transitive):
        parts.append(
            _impact_box(
                flow,
                502,
                150 + target_offset + index * (row_height + row_gap),
                row_height,
            )
        )
    if not direct and not transitive:
        message = (
            "No modeled flows matched the requested targets."
            if unresolved_targets
            else "No modeled flows are affected by these files."
        )
        parts.append(_text(52, 184 + target_offset, message, "meta"))
    if omitted_direct or omitted_transitive:
        parts.append(
            _text(
                52,
                height - 34,
                f"{omitted_direct} direct and {omitted_transitive} caller flows omitted.",
                "meta",
            )
        )
    parts.append("</svg>")
    return "\n".join(parts)


def _unresolved_target_label(item: Any) -> str:
    if isinstance(item, dict):
        target_type = item.get("type")
        value = item.get("value")
        if target_type is not None and value is not None:
            return f"{target_type}:{value}"
        return _compact(str(item), 80)
    return str(item)


def _select_flow_nodes(
    flow: Flow,
    highlight_node_ids: set[str],
    max_nodes: int | None,
) -> list[FlowNode]:
    limit = _effective_limit(max_nodes, MAX_FLOW_NODES)
    selected = flow.nodes[:limit]
    selected_ids = {node.id for node in selected}
    for node in flow.nodes:
        if node.id not in highlight_node_ids or node.id in selected_ids:
            continue
        if len(selected) < limit:
            selected.append(node)
        elif selected:
            selected[-1] = node
        selected_ids = {item.id for item in selected}
    return [node for node in flow.nodes if node.id in selected_ids]


def _select_impact_flows(flows: list[Flow], max_flows: int | None) -> list[Flow]:
    if max_flows is None:
        return flows
    return flows[: _effective_limit(max_flows, len(flows))]


def _effective_limit(value: int | None, default: int) -> int:
    if value is None:
        return default
    return max(1, min(default, value))


def _flow_node(
    node: FlowNode,
    position: tuple[int, int],
    width: int,
    height: int,
    *,
    highlighted: bool,
    finding_count: int,
) -> str:
    x, y = position
    classes = ["node", f"kind-{node.kind.value}"]
    if highlighted:
        classes.append("highlight")
    if finding_count:
        classes.append("has-finding")
    shape = _node_shape(node.kind, x, y, width, height, " ".join(classes))
    label_lines = _wrap(node.label, 34, 2)
    meta = f"{node.location.path}:{node.location.start_line}"
    if finding_count:
        meta += f" - {finding_count} finding{'s' if finding_count != 1 else ''}"
    text_lines = [
        _text(x + width / 2, y + 28, line, "node-label", anchor="middle") for line in label_lines
    ]
    text_lines.append(_text(x + width / 2, y + height - 18, meta, "node-meta", anchor="middle"))
    return "\n".join([shape, *text_lines])


def _node_shape(kind: NodeKind, x: int, y: int, width: int, height: int, classes: str) -> str:
    if kind is NodeKind.DECISION:
        points = [
            (x + width / 2, y),
            (x + width, y + height / 2),
            (x + width / 2, y + height),
            (x, y + height / 2),
        ]
        return '<polygon class="{}" points="{}" />'.format(
            classes,
            " ".join(f"{px},{py}" for px, py in points),
        )
    if kind in {NodeKind.ENTRY, NodeKind.TERMINAL}:
        return (
            f'<rect class="{classes}" x="{x}" y="{y}" width="{width}" height="{height}" '
            f'rx="{height / 2}" />'
        )
    return f'<rect class="{classes}" x="{x}" y="{y}" width="{width}" height="{height}" rx="10" />'


def _edge(
    source_id: str,
    target_id: str,
    positions: dict[str, tuple[int, int]],
    node_width: int,
    node_height: int,
    label: str,
) -> str:
    sx, sy = positions[source_id]
    tx, ty = positions[target_id]
    x1 = sx + node_width / 2
    y1 = sy + node_height
    x2 = tx + node_width / 2
    y2 = ty
    mid_y = (y1 + y2) / 2
    path = f'<path class="edge" d="M {x1} {y1} C {x1} {mid_y}, {x2} {mid_y}, {x2} {y2}" />'
    if not label:
        return path
    return "\n".join(
        [
            path,
            _text((x1 + x2) / 2 + 10, mid_y - 4, _compact(label, 28), "edge-label"),
        ]
    )


def _impact_box(flow: Flow, x: int, y: int, height: int) -> str:
    width = 366
    lines = [
        f'<rect class="impact-node" x="{x}" y="{y}" width="{width}" height="{height}" rx="10" />',
        _text(x + 16, y + 28, _compact(flow.name, 42), "node-label"),
        _text(
            x + 16,
            y + 52,
            f"{flow.entry_kind} - {flow.language}",
            "node-meta",
        ),
        _text(x + 16, y + 72, _compact(flow.location.path, 52), "node-meta"),
    ]
    return "\n".join(lines)


def _finding_panel(finding: Finding, diagnostic: dict[str, Any]) -> dict[str, Any]:
    x = 646
    y = 116
    width = 246
    lines = _finding_panel_lines(finding, diagnostic)
    row_height = 17
    height = 44 + len(lines) * row_height
    parts = [
        f'<rect class="diagnostic-panel" x="{x}" y="{y}" width="{width}" '
        f'height="{height}" rx="12" />',
        _text(x + 14, y + 24, "Finding context", "panel-title"),
    ]
    cursor = y + 48
    for line in lines:
        parts.append(_text(x + 14, cursor, line, "panel-text"))
        cursor += row_height
    return {"height": height, "svg": "\n".join(parts)}


def _finding_panel_lines(finding: Finding, diagnostic: dict[str, Any]) -> list[str]:
    lines = [
        f"Evidence: {_enum_text(finding.evidence)}",
        f"Severity: {_enum_text(finding.severity)}",
    ]
    confidence = diagnostic.get("confidence")
    if isinstance(confidence, dict):
        lines.append(
            "Confidence: "
            + _compact(
                f"{confidence.get('score', 'n/a')} {confidence.get('basis', '')}",
                34,
            )
        )
    missing = diagnostic.get("missing")
    if missing:
        lines.append(f"Missing: {_compact(_value_summary(missing), 36)}")
    expected = diagnostic.get("expected")
    if expected:
        lines.append(f"Expected: {_compact(_value_summary(expected), 34)}")
    actual = diagnostic.get("actual")
    if actual:
        lines.append(f"Actual: {_compact(_value_summary(actual), 36)}")
    review = diagnostic.get("review_prompt")
    if review:
        lines.extend(f"Review: {line}" for line in _wrap(str(review), 34, 2))
    evidence = _evidence_lines(diagnostic.get("evidence_chain", []))
    if evidence:
        lines.append("Evidence chain:")
        lines.extend(evidence)
    return lines[:18]


def _evidence_lines(chain: Any) -> list[str]:
    if not isinstance(chain, list):
        return []
    useful = [
        item
        for item in chain
        if isinstance(item, dict) and item.get("type") not in {"finding", "flow"}
    ]
    return [_compact(f"- {_evidence_summary(item)}", 36) for item in useful[:6]]


def _evidence_summary(item: dict[str, Any]) -> str:
    item_type = str(item.get("type", "evidence"))
    if item_type == "implicit_fallback":
        values = _value_summary(item.get("handled_values"))
        return f"implicit fallback after {values}"
    if item_type == "constant_guard":
        return f"{item.get('constant')} always {item.get('guard_always')}"
    if item_type == "handler_outcomes":
        return "handler outcome can swallow error"
    if item_type == "empty_branches":
        return "empty branch performs no modeled work"
    if item_type == "dispatch_outcomes":
        return "dispatch fallthrough differs from exits"
    if item_type == "related_decisions":
        nodes = item.get("nodes")
        count = len(nodes) if isinstance(nodes, list) else 0
        return f"{count} related decision nodes"
    if item.get("source"):
        return f"{item_type} at {item.get('source')}"
    return item_type.replace("_", " ")


def _diagnostic_for_snapshot(
    model: ProjectModel,
    finding: Finding,
    flow: Flow,
    node: FlowNode | None,
) -> dict[str, Any]:
    diagnostic = finding.metadata.get("diagnostic")
    if isinstance(diagnostic, dict):
        return diagnostic
    return diagnostic_for_finding(finding, flow=flow, node=node, model=model)


def _value_summary(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        return ", ".join(f"{key}={_value_summary(item)}" for key, item in value.items())
    if isinstance(value, list | tuple | set):
        return ", ".join(str(item) for item in value)
    return str(value)


def _enum_text(value: Any) -> str:
    return str(getattr(value, "value", value))


def _style() -> str:
    return """
<style>
  .background { fill: #f8fafc; }
  .title { fill: #0f172a; font: 700 20px system-ui, sans-serif; }
  .subtitle { fill: #334155; font: 13px system-ui, sans-serif; }
  .meta { fill: #64748b; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .column { fill: #334155; font: 700 13px system-ui, sans-serif; }
  .node, .impact-node { fill: #ffffff; stroke: #94a3b8; stroke-width: 1.4; }
  .kind-decision { fill: #fff7ed; stroke: #f97316; }
  .kind-call { fill: #ecfeff; stroke: #0891b2; }
  .kind-error { fill: #fef2f2; stroke: #ef4444; }
  .has-finding { stroke-width: 2; }
  .highlight { stroke: #2563eb; stroke-width: 3; filter: drop-shadow(0 2px 5px #bfdbfe); }
  .edge { fill: none; stroke: #64748b; stroke-width: 1.2; marker-end: url(#arrow); }
  .edge-label { fill: #475569; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .node-label { fill: #0f172a; font: 700 12px system-ui, sans-serif; }
  .node-meta { fill: #64748b; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .diagnostic-panel { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1.2; }
  .panel-title { fill: #0f172a; font: 700 13px system-ui, sans-serif; }
  .panel-text { fill: #334155; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
</style>
<defs>
  <marker id="arrow" markerWidth="8" markerHeight="8" refX="7" refY="3.5" orient="auto">
    <polygon points="0 0, 8 3.5, 0 7" fill="#64748b" />
  </marker>
</defs>
""".strip()


def _svg_open(width: int, height: int, label: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(label)}">'
    )


def _text(
    x: float,
    y: float,
    value: str,
    class_name: str,
    *,
    anchor: str = "start",
) -> str:
    return (
        f'<text class="{class_name}" x="{x}" y="{y}" text-anchor="{anchor}">{escape(value)}</text>'
    )


def _wrap(value: str, width: int, max_lines: int) -> list[str]:
    words = value.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(" ".join(words)) > len(" ".join(lines)):
        lines[-1] = _compact(lines[-1], max(4, width - 1))
    return lines


def _compact(value: str, width: int) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= width else collapsed[: max(0, width - 3)] + "..."
