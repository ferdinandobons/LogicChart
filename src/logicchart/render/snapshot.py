from __future__ import annotations

import math
from dataclasses import dataclass
from html import escape
from typing import Any

from logicchart.model import Flow, FlowNode, NodeKind, ProjectModel

SNAPSHOT_FORMATS = ("svg",)
MAX_FLOW_NODES = 44
MAX_SUBGRAPH_FLOWS = 8


@dataclass(slots=True)
class _RenderedSubgraphFlow:
    flow: Flow
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


SNAPSHOT_WIDTH = 720
FLOW_NODE_WIDTH = 340


def unsupported_snapshot_format(requested: str) -> dict[str, Any]:
    return {
        "error": f"Unsupported snapshot format: {requested}",
        "error_code": "unsupported_snapshot_format",
        "requested_format": requested,
        "supported_formats": list(SNAPSHOT_FORMATS),
        "recoverable": True,
        "guardrail": ("This reports an unsupported visual export format for LogicChart snapshots."),
    }


def _subgraph_empty_error() -> dict[str, Any]:
    return {
        "error": "Subgraph snapshot requires at least one flow_id.",
        "error_code": "snapshot_subgraph_empty",
        "target_type": "subgraph",
        "recoverable": True,
        "guardrail": "This reports an empty visual snapshot request.",
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


def render_subgraph_snapshot(
    model: ProjectModel,
    *,
    flow_ids: list[str] | None = None,
    max_flows: int | None = None,
    max_nodes: int | None = None,
) -> dict[str, Any]:
    """Render a deterministic SVG for an explicit flow subgraph."""
    requested_flow_ids = _unique(flow_ids or [])
    if not requested_flow_ids:
        return _subgraph_empty_error()

    flows_by_id = {flow.id: flow for flow in model.flows}
    unresolved_targets: list[dict[str, str]] = []
    selected_flow_ids: list[str] = []
    highlighted_node_ids: set[str] = set()

    for flow_id in requested_flow_ids:
        if flow_id in flows_by_id:
            selected_flow_ids.append(flow_id)
        else:
            unresolved_targets.append({"type": "flow", "value": flow_id, "reason": "not_found"})

    selected_flows = [
        flows_by_id[flow_id] for flow_id in selected_flow_ids if flow_id in flows_by_id
    ]
    flow_limit = _effective_limit(max_flows, MAX_SUBGRAPH_FLOWS)
    rendered_flows = selected_flows[:flow_limit]
    rendered: list[_RenderedSubgraphFlow] = []
    for flow in rendered_flows:
        rendered.append(
            _RenderedSubgraphFlow(
                flow=flow,
                highlighted=set(),
                nodes=_select_flow_nodes(flow, set(), max_nodes),
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
        "unresolved_targets": unresolved_targets,
        "flow_ids": [flow.id for flow in selected_flows],
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


def _unresolved_target_label(item: Any) -> str:
    if isinstance(item, dict):
        target_type = item.get("type")
        value = item.get("value")
        if target_type is not None and value is not None:
            return f"{target_type}:{value}"
        return _compact(str(item), 80)
    return str(item)


def _subgraph_layout(
    rendered: list[_RenderedSubgraphFlow],
    unresolved_targets: list[dict[str, str]],
) -> dict[str, Any]:
    width = SNAPSHOT_WIDTH
    header_height = 116 + (24 if unresolved_targets else 0)
    section_gap = 28
    section_header_height = 70
    node_width = FLOW_NODE_WIDTH
    node_height = 76
    row_gap = 34
    x = (width - node_width) // 2
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
        "direction": "top_to_bottom_stacked_flows",
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
        "orientation": "vertical",
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
) -> str:
    x, y = position
    classes = ["node", f"kind-{node.kind.value}"]
    if highlighted:
        classes.append("highlight")
    shape = _node_shape(node.kind, x, y, width, height, " ".join(classes))
    label_lines = _wrap(node.label, 34, 2)
    meta = f"{node.location.path}:{node.location.start_line}"
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


def _style() -> str:
    return """
<style>
  .background { fill: #f8fafc; }
  .title { fill: #0f172a; font: 700 20px system-ui, sans-serif; }
  .subtitle { fill: #334155; font: 13px system-ui, sans-serif; }
  .meta { fill: #64748b; font: 11px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .column { fill: #334155; font: 700 13px system-ui, sans-serif; }
  .subgraph-section { fill: #ffffff; stroke: #cbd5e1; stroke-width: 1.2; }
  .node { fill: #ffffff; stroke: #94a3b8; stroke-width: 1.4; }
  .kind-decision { fill: #fff7ed; stroke: #f97316; }
  .kind-call { fill: #ecfeff; stroke: #0891b2; }
  .kind-error { fill: #fef2f2; stroke: #ef4444; }
  .highlight { stroke: #2563eb; stroke-width: 3; filter: drop-shadow(0 2px 5px #bfdbfe); }
  .edge { fill: none; stroke: #64748b; stroke-width: 1.2; marker-end: url(#arrow); }
  .edge-label { fill: #475569; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
  .node-label { fill: #0f172a; font: 700 12px system-ui, sans-serif; }
  .node-meta { fill: #64748b; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; }
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
