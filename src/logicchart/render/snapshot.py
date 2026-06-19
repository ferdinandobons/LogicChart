from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Any

from logicchart.diagnostics import diagnostic_for_finding
from logicchart.model import Finding, Flow, FlowNode, NodeKind, ProjectModel

SNAPSHOT_FORMATS = ("svg",)
MAX_FLOW_NODES = 44
MAX_SUBGRAPH_FLOWS = 8


@dataclass(slots=True)
class _RenderedSubgraphFlow:
    flow: Flow
    findings: list[Finding]
    highlighted: set[str]
    nodes: list[FlowNode]


@dataclass(frozen=True, slots=True)
class _LayoutBox:
    id: str
    x: float
    y: float
    width: float
    height: float
    kind: str

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height


@dataclass(frozen=True, slots=True)
class _LayoutEdge:
    source: str
    target: str
    label: str


DIAGNOSTIC_PANEL_X = 646
DIAGNOSTIC_PANEL_Y = 116
DIAGNOSTIC_PANEL_WIDTH = 246


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
    layout = _flow_layout(
        flow,
        findings,
        highlighted,
        rendered_nodes=rendered_nodes,
    )
    svg = _flow_svg(
        flow,
        findings,
        highlighted,
        rendered_nodes=rendered_nodes,
        title=title,
        layout=layout,
    )
    return {
        "format": "svg",
        "flow_id": flow.id,
        "title": title or flow.name,
        "svg": svg,
        "highlighted_node_ids": sorted(highlight_node_ids or []),
        "node_count": len(flow.nodes),
        "rendered_node_count": len(rendered_nodes),
        "omitted_node_count": max(0, len(flow.nodes) - len(rendered_nodes)),
        "layout": _flow_layout_payload(flow, rendered_nodes, layout),
        "layout_quality": _flow_layout_quality(flow, rendered_nodes, layout),
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
    flow_findings = [item for item in model.findings if item.flow_id == flow.id]
    layout = _flow_layout(
        flow,
        flow_findings,
        highlighted,
        rendered_nodes=rendered_nodes,
        finding=finding,
        diagnostic=diagnostic,
    )
    svg = _flow_svg(
        flow,
        flow_findings,
        highlighted,
        rendered_nodes=rendered_nodes,
        title=title,
        finding=finding,
        diagnostic=diagnostic,
        layout=layout,
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
        "layout": _flow_layout_payload(flow, rendered_nodes, layout),
        "layout_quality": _flow_layout_quality(flow, rendered_nodes, layout),
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


def _subgraph_empty_error() -> dict[str, Any]:
    return {
        "error": "Subgraph snapshot requires at least one flow_id or finding_id.",
        "error_code": "snapshot_subgraph_empty",
        "target_type": "subgraph",
        "recoverable": True,
        "guardrail": (
            "This reports an empty visual snapshot request; it is not a source-code "
            "logical finding."
        ),
    }


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result


def _node_finding_counts(findings: list[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        if finding.node_id:
            counts[finding.node_id] = counts.get(finding.node_id, 0) + 1
    return counts


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
    target_dependency_paths: list[str] | None = None,
    unresolved_targets: list[Any] | None = None,
    impact_reasons: dict[str, list[str]] | None = None,
    subgraph_flow_ids: list[str] | None = None,
    subgraph_finding_ids: list[str] | None = None,
) -> dict[str, Any]:
    rendered_direct = _select_impact_flows(direct, max_flows)
    rendered_transitive = _select_impact_flows(transitive, max_flows)
    target_labels = _impact_target_labels(
        target_flow_ids=target_flow_ids or [],
        target_symbols=target_symbols or [],
        target_finding_ids=target_finding_ids or [],
        target_dependency_paths=target_dependency_paths or [],
    )
    layout = _impact_layout(
        changed_files,
        direct,
        transitive,
        findings,
        rendered_direct=rendered_direct,
        rendered_transitive=rendered_transitive,
        target_labels=target_labels,
        unresolved_targets=unresolved_targets or [],
    )
    svg = _impact_svg(
        changed_files,
        direct,
        transitive,
        findings,
        rendered_direct=rendered_direct,
        rendered_transitive=rendered_transitive,
        target_labels=target_labels,
        unresolved_targets=unresolved_targets or [],
        layout=layout,
    )
    return {
        "format": "svg",
        "changed_files": changed_files,
        "target_flow_ids": target_flow_ids or [],
        "target_symbols": target_symbols or [],
        "target_finding_ids": target_finding_ids or [],
        "target_dependency_paths": target_dependency_paths or [],
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
        "layout": _impact_layout_payload(
            direct,
            transitive,
            rendered_direct,
            rendered_transitive,
            layout,
        ),
        "layout_quality": _impact_layout_quality(
            direct,
            transitive,
            rendered_direct,
            rendered_transitive,
            layout,
        ),
        "svg": svg,
    }


def render_subgraph_snapshot(
    model: ProjectModel,
    *,
    flow_ids: list[str] | None = None,
    finding_ids: list[str] | None = None,
    max_flows: int | None = None,
    max_nodes: int | None = None,
) -> dict[str, Any]:
    """Render a deterministic SVG for an explicit flow/finding subgraph."""
    requested_flow_ids = _unique(flow_ids or [])
    requested_finding_ids = _unique(finding_ids or [])
    if not requested_flow_ids and not requested_finding_ids:
        return _subgraph_empty_error()

    flows_by_id = {flow.id: flow for flow in model.flows}
    findings_by_id = {finding.id: finding for finding in model.findings}
    unresolved_targets: list[dict[str, str]] = []
    selected_flow_ids: list[str] = []
    selected_finding_ids: list[str] = []
    highlighted_node_ids: set[str] = set()

    for flow_id in requested_flow_ids:
        if flow_id in flows_by_id:
            selected_flow_ids.append(flow_id)
        else:
            unresolved_targets.append({"type": "flow", "value": flow_id, "reason": "not_found"})

    for finding_id in requested_finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            unresolved_targets.append(
                {"type": "finding", "value": finding_id, "reason": "not_found"}
            )
            continue
        selected_finding_ids.append(finding.id)
        if finding.node_id:
            highlighted_node_ids.add(finding.node_id)
        if finding.flow_id not in selected_flow_ids:
            selected_flow_ids.append(finding.flow_id)

    selected_flows = [
        flows_by_id[flow_id] for flow_id in selected_flow_ids if flow_id in flows_by_id
    ]
    flow_limit = _effective_limit(max_flows, MAX_SUBGRAPH_FLOWS)
    rendered_flows = selected_flows[:flow_limit]
    findings_by_flow: dict[str, list[Finding]] = {}
    highlighted_by_flow: dict[str, set[str]] = {}
    selected_finding_id_set = set(selected_finding_ids)
    for finding in model.findings:
        findings_by_flow.setdefault(finding.flow_id, []).append(finding)
        if finding.id in selected_finding_id_set and finding.node_id:
            highlighted_by_flow.setdefault(finding.flow_id, set()).add(finding.node_id)

    rendered: list[_RenderedSubgraphFlow] = []
    for flow in rendered_flows:
        highlighted = highlighted_by_flow.get(flow.id, set())
        rendered.append(
            _RenderedSubgraphFlow(
                flow=flow,
                findings=findings_by_flow.get(flow.id, []),
                highlighted=highlighted,
                nodes=_select_flow_nodes(flow, highlighted, max_nodes),
            )
        )
    layout = _subgraph_layout(rendered, unresolved_targets)
    svg = _subgraph_svg(
        rendered,
        unresolved_targets=unresolved_targets,
        layout=layout,
        selected_flow_count=len(selected_flows),
    )
    rendered_node_count = sum(len(item.nodes) for item in rendered)
    node_count = sum(len(flow.nodes) for flow in selected_flows)
    return {
        "format": "svg",
        "title": "Subgraph snapshot",
        "requested_flow_ids": requested_flow_ids,
        "requested_finding_ids": requested_finding_ids,
        "unresolved_targets": unresolved_targets,
        "flow_ids": [flow.id for flow in selected_flows],
        "finding_ids": selected_finding_ids,
        "rendered_flow_ids": [flow.id for flow in rendered_flows],
        "omitted_flow_count": max(0, len(selected_flows) - len(rendered_flows)),
        "highlighted_node_ids": sorted(highlighted_node_ids),
        "node_count": node_count,
        "rendered_node_count": rendered_node_count,
        "omitted_node_count": max(0, node_count - rendered_node_count),
        "layout": _subgraph_layout_payload(selected_flows, rendered, layout),
        "layout_quality": _subgraph_layout_quality(
            selected_flows,
            rendered,
            layout,
            unresolved_targets,
        ),
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
    layout: dict[str, Any] | None = None,
) -> str:
    nodes = rendered_nodes
    omitted = max(0, len(flow.nodes) - len(nodes))
    layout = layout or _flow_layout(flow, findings, highlight_node_ids, rendered_nodes=nodes)
    width = int(layout["width"])
    height = int(layout["height"])
    node_width = int(layout["node_width"])
    node_height = int(layout["node_height"])
    positions = layout["positions"]
    panel = _finding_panel(finding, diagnostic) if finding and diagnostic else None
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
    node_finding_counts = _node_finding_counts(findings)
    for edge in flow.edges:
        if edge.source not in positions or edge.target not in positions:
            continue
        parts.append(
            _edge(edge.source, edge.target, positions, node_width, node_height, edge.label)
        )
    for node in nodes:
        parts.append(
            _flow_node(
                node,
                positions[node.id],
                node_width,
                node_height,
                highlighted=node.id in highlight_node_ids,
                finding_count=node_finding_counts.get(node.id, 0),
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


def _subgraph_svg(
    rendered: list[_RenderedSubgraphFlow],
    *,
    unresolved_targets: list[dict[str, str]],
    layout: dict[str, Any],
    selected_flow_count: int,
) -> str:
    width = int(layout["width"])
    height = int(layout["height"])
    node_width = int(layout["node_width"])
    node_height = int(layout["node_height"])
    positions = layout["positions"]
    parts = [
        _svg_open(width, height, "LogicChart subgraph snapshot"),
        _style(),
        f'<rect class="background" x="0" y="0" width="{width}" height="{height}" />',
        _text(28, 34, "Subgraph snapshot", "title"),
        _text(
            28,
            58,
            f"{selected_flow_count} flows - {layout['selected_node_count']} nodes - "
            f"{len(unresolved_targets)} unresolved targets",
            "subtitle",
        ),
    ]
    if unresolved_targets:
        unresolved_label = ", ".join(_unresolved_target_label(item) for item in unresolved_targets)
        parts.append(
            _text(28, 84, _compact(f"Unresolved targets: {unresolved_label}", 125), "meta")
        )
    if not rendered:
        parts.append(_text(52, 132, "No valid flows matched the requested subgraph.", "meta"))
        parts.append("</svg>")
        return "\n".join(parts)

    for section, item in zip(layout["sections"], rendered, strict=True):
        flow = item.flow
        findings = item.findings
        nodes = item.nodes
        highlighted = item.highlighted
        section_y = int(section["y"])
        parts.extend(
            [
                f'<rect class="subgraph-section" x="28" y="{section_y}" '
                f'width="{width - 56}" height="{section["height"]}" rx="14" />',
                _text(52, section_y + 28, flow.name, "column"),
                _text(
                    52,
                    section_y + 50,
                    _compact(
                        f"{flow.entry_kind} - {flow.language} - "
                        f"{flow.location.path}:{flow.location.start_line}",
                        100,
                    ),
                    "meta",
                ),
            ]
        )
        flow_positions = {node.id: positions[node.id] for node in nodes if node.id in positions}
        node_finding_counts = _node_finding_counts(findings)
        for edge in flow.edges:
            if edge.source not in flow_positions or edge.target not in flow_positions:
                continue
            parts.append(
                _edge(edge.source, edge.target, flow_positions, node_width, node_height, edge.label)
            )
        for node in nodes:
            parts.append(
                _flow_node(
                    node,
                    positions[node.id],
                    node_width,
                    node_height,
                    highlighted=node.id in highlighted,
                    finding_count=node_finding_counts.get(node.id, 0),
                )
            )
        omitted = max(0, len(flow.nodes) - len(nodes))
        if omitted:
            parts.append(
                _text(
                    52,
                    section_y + int(section["height"]) - 18,
                    f"{omitted} additional nodes omitted from this compact flow.",
                    "meta",
                )
            )
    omitted_flows = max(0, selected_flow_count - len(rendered))
    if omitted_flows:
        parts.append(_text(28, height - 34, f"{omitted_flows} additional flows omitted.", "meta"))
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
    target_labels: list[str],
    unresolved_targets: list[Any],
    layout: dict[str, Any] | None = None,
) -> str:
    layout = layout or _impact_layout(
        changed_files,
        direct,
        transitive,
        findings,
        rendered_direct=rendered_direct,
        rendered_transitive=rendered_transitive,
        target_labels=target_labels,
        unresolved_targets=unresolved_targets,
    )
    width = int(layout["width"])
    height = int(layout["height"])
    row_height = int(layout["row_height"])
    row_gap = int(layout["row_gap"])
    target_offset = int(layout["target_offset"])
    omitted_direct = max(0, len(direct) - len(rendered_direct))
    omitted_transitive = max(0, len(transitive) - len(rendered_transitive))
    meta_lines: list[str] = []
    if changed_files:
        meta_lines.append(_compact(f"Changed files: {', '.join(changed_files)}", 125))
    if target_labels:
        meta_lines.append(_compact(f"Targets: {', '.join(target_labels)}", 125))
    if unresolved_targets:
        unresolved_label = ", ".join(_unresolved_target_label(item) for item in unresolved_targets)
        meta_lines.append(_compact(f"Unresolved targets: {unresolved_label}", 125))
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
    ]
    parts.extend(_text(28, 84 + index * 24, line, "meta") for index, line in enumerate(meta_lines))
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


def _impact_target_labels(
    *,
    target_flow_ids: list[str],
    target_symbols: list[str],
    target_finding_ids: list[str],
    target_dependency_paths: list[str],
) -> list[str]:
    labels: list[str] = []
    labels.extend(f"flow:{item}" for item in target_flow_ids)
    labels.extend(f"symbol:{item}" for item in target_symbols)
    labels.extend(f"finding:{item}" for item in target_finding_ids)
    labels.extend(f"path:{item}" for item in target_dependency_paths)
    return labels


def _flow_layout(
    flow: Flow,
    findings: list[Finding],
    highlight_node_ids: set[str],
    *,
    rendered_nodes: list[FlowNode],
    finding: Finding | None = None,
    diagnostic: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width = 920
    header_height = 108
    row_gap = 34
    node_width = 340
    node_height = 76
    x = 290
    positions = {
        node.id: (x, header_height + index * (node_height + row_gap))
        for index, node in enumerate(rendered_nodes)
    }
    graph_height = header_height + max(1, len(rendered_nodes)) * (node_height + row_gap) + 86
    panel_height = _finding_panel_height(finding, diagnostic) if finding and diagnostic else 0
    height = max(graph_height, panel_height + 132 if panel_height else graph_height)
    rendered_edge_count = sum(
        edge.source in positions and edge.target in positions for edge in flow.edges
    )
    return {
        "engine": "static-flow-snapshot-v1",
        "direction": "top_to_bottom",
        "width": width,
        "height": height,
        "header_height": header_height,
        "row_gap": row_gap,
        "node_width": node_width,
        "node_height": node_height,
        "x": x,
        "graph_height": graph_height,
        "panel_height": panel_height,
        "positions": positions,
        "rendered_edge_count": rendered_edge_count,
        "omitted_edge_count": max(0, len(flow.edges) - rendered_edge_count),
        "highlighted_node_count": len(highlight_node_ids),
        "finding_count": len(findings),
    }


def _flow_layout_payload(
    flow: Flow,
    rendered_nodes: list[FlowNode],
    layout: dict[str, Any],
) -> dict[str, Any]:
    positions: dict[str, tuple[int, int]] = layout["positions"]
    return {
        "engine": layout["engine"],
        "direction": layout["direction"],
        "canvas": {"width": layout["width"], "height": layout["height"]},
        "node": {
            "width": layout["node_width"],
            "height": layout["node_height"],
            "row_gap": layout["row_gap"],
        },
        "bounds": {
            "x": layout["x"],
            "y": layout["header_height"],
            "width": layout["node_width"],
            "height": max(1, layout["graph_height"] - layout["header_height"]),
        },
        "rendered_edge_count": layout["rendered_edge_count"],
        "omitted_edge_count": layout["omitted_edge_count"],
        "compact": len(rendered_nodes) < len(flow.nodes),
        "node_positions": [
            {
                "id": node.id,
                "x": positions[node.id][0],
                "y": positions[node.id][1],
                "width": layout["node_width"],
                "height": layout["node_height"],
            }
            for node in rendered_nodes
        ],
    }


def _flow_layout_quality(
    flow: Flow,
    rendered_nodes: list[FlowNode],
    layout: dict[str, Any],
) -> dict[str, Any]:
    omitted_nodes = max(0, len(flow.nodes) - len(rendered_nodes))
    omitted_edges = int(layout["omitted_edge_count"])
    rendered_node_ids = {node.id for node in rendered_nodes}
    clarity = _layout_clarity(
        _flow_layout_boxes(rendered_nodes, layout),
        canvas_width=float(layout["width"]),
        canvas_height=float(layout["height"]),
        edges=[
            _LayoutEdge(edge.source, edge.target, edge.label)
            for edge in flow.edges
            if edge.source in rendered_node_ids and edge.target in rendered_node_ids
        ],
    )
    return _snapshot_layout_quality(
        compact=omitted_nodes > 0 or omitted_edges > 0,
        counts={
            "node_count": len(flow.nodes),
            "rendered_node_count": len(rendered_nodes),
            "omitted_node_count": omitted_nodes,
            "edge_count": len(flow.edges),
            "rendered_edge_count": int(layout["rendered_edge_count"]),
            "omitted_edge_count": omitted_edges,
        },
        clarity=clarity,
    )


def _impact_layout(
    changed_files: list[str],
    direct: list[Flow],
    transitive: list[Flow],
    findings: list[Finding],
    *,
    rendered_direct: list[Flow],
    rendered_transitive: list[Flow],
    target_labels: list[str],
    unresolved_targets: list[Any],
) -> dict[str, Any]:
    width = 920
    row_height = 84
    row_gap = 22
    rows = max(1, max(len(rendered_direct), len(rendered_transitive)))
    meta_line_count = (
        int(bool(changed_files)) + int(bool(target_labels)) + int(bool(unresolved_targets))
    )
    target_offset = max(0, meta_line_count - 1) * 24
    height = 156 + target_offset + rows * (row_height + row_gap) + 80
    return {
        "engine": "static-impact-snapshot-v1",
        "direction": "left_to_right_columns",
        "width": width,
        "height": height,
        "row_height": row_height,
        "row_gap": row_gap,
        "rows": rows,
        "target_offset": target_offset,
        "direct_column": {"x": 52, "y": 150 + target_offset, "width": 366},
        "transitive_column": {"x": 502, "y": 150 + target_offset, "width": 366},
        "changed_file_count": len(changed_files),
        "target_count": len(target_labels),
        "finding_count": len(findings),
        "unresolved_target_count": len(unresolved_targets),
    }


def _impact_layout_payload(
    direct: list[Flow],
    transitive: list[Flow],
    rendered_direct: list[Flow],
    rendered_transitive: list[Flow],
    layout: dict[str, Any],
) -> dict[str, Any]:
    return {
        "engine": layout["engine"],
        "direction": layout["direction"],
        "canvas": {"width": layout["width"], "height": layout["height"]},
        "row": {"height": layout["row_height"], "gap": layout["row_gap"]},
        "target_count": layout["target_count"],
        "columns": [
            {
                "id": "direct",
                "label": "Direct impact",
                **layout["direct_column"],
                "rendered_flow_count": len(rendered_direct),
                "omitted_flow_count": max(0, len(direct) - len(rendered_direct)),
            },
            {
                "id": "caller",
                "label": "Caller impact",
                **layout["transitive_column"],
                "rendered_flow_count": len(rendered_transitive),
                "omitted_flow_count": max(0, len(transitive) - len(rendered_transitive)),
            },
        ],
        "compact": len(rendered_direct) < len(direct) or len(rendered_transitive) < len(transitive),
    }


def _impact_layout_quality(
    direct: list[Flow],
    transitive: list[Flow],
    rendered_direct: list[Flow],
    rendered_transitive: list[Flow],
    layout: dict[str, Any],
) -> dict[str, Any]:
    omitted_direct = max(0, len(direct) - len(rendered_direct))
    omitted_transitive = max(0, len(transitive) - len(rendered_transitive))
    return _snapshot_layout_quality(
        compact=omitted_direct > 0 or omitted_transitive > 0,
        counts={
            "direct_flow_count": len(direct),
            "rendered_direct_flow_count": len(rendered_direct),
            "omitted_direct_flow_count": omitted_direct,
            "transitive_flow_count": len(transitive),
            "rendered_transitive_flow_count": len(rendered_transitive),
            "omitted_transitive_flow_count": omitted_transitive,
            "finding_count": int(layout["finding_count"]),
            "unresolved_target_count": int(layout["unresolved_target_count"]),
        },
        clarity=_layout_clarity(
            _impact_layout_boxes(rendered_direct, rendered_transitive, layout),
            canvas_width=float(layout["width"]),
            canvas_height=float(layout["height"]),
        ),
    )


def _subgraph_layout(
    rendered: list[_RenderedSubgraphFlow],
    unresolved_targets: list[dict[str, str]],
) -> dict[str, Any]:
    width = 1060
    header_height = 116 + (24 if unresolved_targets else 0)
    section_gap = 28
    section_header_height = 70
    node_width = 340
    node_height = 76
    row_gap = 34
    x = 360
    y = header_height
    sections: list[dict[str, Any]] = []
    positions: dict[str, tuple[int, int]] = {}
    rendered_edge_count = 0
    total_edge_count = 0
    selected_node_count = 0
    rendered_node_count = 0

    for item in rendered:
        flow = item.flow
        nodes = item.nodes
        node_rows = max(1, len(nodes))
        section_height = section_header_height + node_rows * (node_height + row_gap) + 24
        node_start_y = y + section_header_height
        for index, node in enumerate(nodes):
            positions[node.id] = (x, node_start_y + index * (node_height + row_gap))
        edge_count = sum(
            edge.source in positions and edge.target in positions for edge in flow.edges
        )
        sections.append(
            {
                "flow_id": flow.id,
                "x": 28,
                "y": y,
                "width": width - 56,
                "height": section_height,
                "node_start_y": node_start_y,
                "rendered_node_count": len(nodes),
                "omitted_node_count": max(0, len(flow.nodes) - len(nodes)),
                "rendered_edge_count": edge_count,
                "omitted_edge_count": max(0, len(flow.edges) - edge_count),
            }
        )
        selected_node_count += len(flow.nodes)
        rendered_node_count += len(nodes)
        total_edge_count += len(flow.edges)
        rendered_edge_count += edge_count
        y += section_height + section_gap

    if not rendered:
        y = header_height + 86
    height = y + 44
    return {
        "engine": "static-subgraph-snapshot-v1",
        "direction": "stacked_flows",
        "width": width,
        "height": height,
        "header_height": header_height,
        "section_gap": section_gap,
        "section_header_height": section_header_height,
        "node_width": node_width,
        "node_height": node_height,
        "row_gap": row_gap,
        "x": x,
        "positions": positions,
        "sections": sections,
        "selected_node_count": selected_node_count,
        "rendered_node_count": rendered_node_count,
        "rendered_edge_count": rendered_edge_count,
        "omitted_edge_count": max(0, total_edge_count - rendered_edge_count),
        "unresolved_target_count": len(unresolved_targets),
    }


def _subgraph_layout_payload(
    selected_flows: list[Flow],
    rendered: list[_RenderedSubgraphFlow],
    layout: dict[str, Any],
) -> dict[str, Any]:
    positions: dict[str, tuple[int, int]] = layout["positions"]
    rendered_nodes = [node for item in rendered for node in item.nodes]
    return {
        "engine": layout["engine"],
        "direction": layout["direction"],
        "canvas": {"width": layout["width"], "height": layout["height"]},
        "node": {
            "width": layout["node_width"],
            "height": layout["node_height"],
            "row_gap": layout["row_gap"],
        },
        "sections": [
            {
                "flow_id": section["flow_id"],
                "x": section["x"],
                "y": section["y"],
                "width": section["width"],
                "height": section["height"],
                "rendered_node_count": section["rendered_node_count"],
                "omitted_node_count": section["omitted_node_count"],
                "rendered_edge_count": section["rendered_edge_count"],
                "omitted_edge_count": section["omitted_edge_count"],
            }
            for section in layout["sections"]
        ],
        "rendered_edge_count": layout["rendered_edge_count"],
        "omitted_edge_count": layout["omitted_edge_count"],
        "compact": (
            len(rendered) < len(selected_flows)
            or any(section["omitted_node_count"] for section in layout["sections"])
        ),
        "node_positions": [
            {
                "id": node.id,
                "x": positions[node.id][0],
                "y": positions[node.id][1],
                "width": layout["node_width"],
                "height": layout["node_height"],
            }
            for node in rendered_nodes
        ],
    }


def _subgraph_layout_quality(
    selected_flows: list[Flow],
    rendered: list[_RenderedSubgraphFlow],
    layout: dict[str, Any],
    unresolved_targets: list[dict[str, str]],
) -> dict[str, Any]:
    omitted_flows = max(0, len(selected_flows) - len(rendered))
    omitted_nodes = sum(int(section["omitted_node_count"]) for section in layout["sections"])
    omitted_edges = int(layout["omitted_edge_count"])
    clarity = _layout_clarity(
        _subgraph_layout_boxes(rendered, layout),
        canvas_width=float(layout["width"]),
        canvas_height=float(layout["height"]),
        edges=_subgraph_layout_edges(rendered),
    )
    return _snapshot_layout_quality(
        compact=omitted_flows > 0 or omitted_nodes > 0 or omitted_edges > 0,
        counts={
            "flow_count": len(selected_flows),
            "rendered_flow_count": len(rendered),
            "omitted_flow_count": omitted_flows,
            "node_count": int(layout["selected_node_count"]),
            "rendered_node_count": int(layout["rendered_node_count"]),
            "omitted_node_count": omitted_nodes,
            "rendered_edge_count": int(layout["rendered_edge_count"]),
            "omitted_edge_count": omitted_edges,
            "unresolved_target_count": len(unresolved_targets),
        },
        clarity=clarity,
    )


def _snapshot_layout_quality(
    *,
    compact: bool,
    counts: dict[str, int],
    clarity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "status": "compact" if compact else "complete",
        "complete": not compact,
        "counts": counts,
        "clarity": clarity,
        "guardrail": (
            "Layout quality describes the rendered snapshot only. Compact snapshots may omit "
            "model nodes, edges, or flows; request a higher token_budget or the follow-up "
            "snapshot tool when omitted counts are non-zero."
        ),
    }


def _flow_layout_boxes(rendered_nodes: list[FlowNode], layout: dict[str, Any]) -> list[_LayoutBox]:
    positions: dict[str, tuple[int, int]] = layout["positions"]
    boxes = [
        _LayoutBox(
            id=node.id,
            x=float(positions[node.id][0]),
            y=float(positions[node.id][1]),
            width=float(layout["node_width"]),
            height=float(layout["node_height"]),
            kind="node",
        )
        for node in rendered_nodes
        if node.id in positions
    ]
    panel_height = int(layout.get("panel_height") or 0)
    if panel_height:
        boxes.append(
            _LayoutBox(
                id="diagnostic-panel",
                x=DIAGNOSTIC_PANEL_X,
                y=DIAGNOSTIC_PANEL_Y,
                width=DIAGNOSTIC_PANEL_WIDTH,
                height=float(panel_height),
                kind="diagnostic_panel",
            )
        )
    return boxes


def _impact_layout_boxes(
    rendered_direct: list[Flow],
    rendered_transitive: list[Flow],
    layout: dict[str, Any],
) -> list[_LayoutBox]:
    row_height = float(layout["row_height"])
    row_gap = float(layout["row_gap"])
    boxes: list[_LayoutBox] = []
    for column_id, flows, column in (
        ("direct", rendered_direct, layout["direct_column"]),
        ("caller", rendered_transitive, layout["transitive_column"]),
    ):
        for index, flow in enumerate(flows):
            boxes.append(
                _LayoutBox(
                    id=f"{column_id}:{flow.id}",
                    x=float(column["x"]),
                    y=float(column["y"]) + index * (row_height + row_gap),
                    width=float(column["width"]),
                    height=row_height,
                    kind="flow",
                )
            )
    return boxes


def _subgraph_layout_boxes(
    rendered: list[_RenderedSubgraphFlow],
    layout: dict[str, Any],
) -> list[_LayoutBox]:
    positions: dict[str, tuple[int, int]] = layout["positions"]
    boxes: list[_LayoutBox] = []
    for item in rendered:
        for node in item.nodes:
            if node.id not in positions:
                continue
            boxes.append(
                _LayoutBox(
                    id=node.id,
                    x=float(positions[node.id][0]),
                    y=float(positions[node.id][1]),
                    width=float(layout["node_width"]),
                    height=float(layout["node_height"]),
                    kind="node",
                )
            )
    return boxes


def _subgraph_layout_edges(rendered: list[_RenderedSubgraphFlow]) -> list[_LayoutEdge]:
    edges: list[_LayoutEdge] = []
    for item in rendered:
        node_ids = {node.id for node in item.nodes}
        edges.extend(
            _LayoutEdge(edge.source, edge.target, edge.label)
            for edge in item.flow.edges
            if edge.source in node_ids and edge.target in node_ids
        )
    return edges


def _layout_clarity(
    boxes: list[_LayoutBox],
    *,
    canvas_width: float,
    canvas_height: float,
    edges: list[_LayoutEdge] | None = None,
) -> dict[str, Any]:
    box_overlaps = _box_overlaps(boxes)
    edge_hits = _edge_obstacle_hits(edges or [], boxes)
    overflow = _canvas_overflow_boxes(boxes, canvas_width, canvas_height)
    finite = (
        math.isfinite(canvas_width)
        and math.isfinite(canvas_height)
        and all(
            math.isfinite(value) for box in boxes for value in (box.x, box.y, box.width, box.height)
        )
    )
    clear = finite and not box_overlaps and not edge_hits and not overflow
    return {
        "status": "clear" if clear else "needs_review",
        "clear": clear,
        "counts": {
            "box_count": len(boxes),
            "box_overlap_count": len(box_overlaps),
            "edge_obstacle_hit_count": len(edge_hits),
            "canvas_overflow_count": len(overflow),
            "non_finite_geometry_count": 0 if finite else 1,
        },
        "minimum_box_gap": _minimum_box_gap(boxes),
        "samples": {
            "box_overlaps": box_overlaps[:5],
            "edge_obstacle_hits": edge_hits[:5],
            "canvas_overflow": overflow[:5],
        },
    }


def _box_overlaps(boxes: list[_LayoutBox]) -> list[dict[str, str]]:
    overlaps: list[dict[str, str]] = []
    for left_index, left in enumerate(boxes):
        for right in boxes[left_index + 1 :]:
            if _boxes_overlap(left, right):
                overlaps.append({"first": left.id, "second": right.id})
    return overlaps


def _edge_obstacle_hits(
    edges: list[_LayoutEdge],
    boxes: list[_LayoutBox],
) -> list[dict[str, str]]:
    boxes_by_id = {box.id: box for box in boxes}
    hits: list[dict[str, str]] = []
    for edge in edges:
        source = boxes_by_id.get(edge.source)
        target = boxes_by_id.get(edge.target)
        if source is None or target is None:
            continue
        corridor = _edge_corridor(source, target)
        for box in boxes:
            if box.id in {edge.source, edge.target}:
                continue
            if _boxes_overlap(corridor, box):
                hits.append(
                    {
                        "edge": f"{edge.source}->{edge.target}",
                        "obstacle": box.id,
                    }
                )
    return hits


def _edge_corridor(source: _LayoutBox, target: _LayoutBox) -> _LayoutBox:
    x1 = source.x + source.width / 2
    y1 = source.bottom
    x2 = target.x + target.width / 2
    y2 = target.y
    left = min(x1, x2) - 6
    top = min(y1, y2)
    return _LayoutBox(
        id=f"{source.id}->{target.id}",
        x=left,
        y=top,
        width=abs(x2 - x1) + 12,
        height=abs(y2 - y1),
        kind="edge_corridor",
    )


def _canvas_overflow_boxes(
    boxes: list[_LayoutBox],
    canvas_width: float,
    canvas_height: float,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for box in boxes:
        sides: list[str] = []
        if box.x < 0:
            sides.append("left")
        if box.y < 0:
            sides.append("top")
        if box.right > canvas_width:
            sides.append("right")
        if box.bottom > canvas_height:
            sides.append("bottom")
        if sides:
            result.append({"box": box.id, "sides": ",".join(sides)})
    return result


def _minimum_box_gap(boxes: list[_LayoutBox]) -> float | None:
    if len(boxes) < 2:
        return None
    gap: float | None = None
    for left_index, left in enumerate(boxes):
        for right in boxes[left_index + 1 :]:
            distance = _box_gap(left, right)
            gap = distance if gap is None else min(gap, distance)
    return round(gap, 2) if gap is not None else None


def _box_gap(left: _LayoutBox, right: _LayoutBox) -> float:
    if _boxes_overlap(left, right):
        return 0.0
    dx = max(left.x - right.right, right.x - left.right, 0.0)
    dy = max(left.y - right.bottom, right.y - left.bottom, 0.0)
    return math.sqrt(dx * dx + dy * dy)


def _boxes_overlap(left: _LayoutBox, right: _LayoutBox) -> bool:
    return (
        left.x < right.right
        and left.right > right.x
        and left.y < right.bottom
        and left.bottom > right.y
    )


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
    x = DIAGNOSTIC_PANEL_X
    y = DIAGNOSTIC_PANEL_Y
    width = DIAGNOSTIC_PANEL_WIDTH
    lines = _finding_panel_lines(finding, diagnostic)
    row_height = 17
    height = _finding_panel_height(finding, diagnostic)
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


def _finding_panel_height(finding: Finding, diagnostic: dict[str, Any]) -> int:
    return 44 + len(_finding_panel_lines(finding, diagnostic)) * 17


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
  .subgraph-section { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1.2; }
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
