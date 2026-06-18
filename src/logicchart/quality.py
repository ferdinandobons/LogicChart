from __future__ import annotations

from collections import Counter
from typing import Any

from logicchart.model import Finding, Flow, FlowNode, NodeKind, ProjectModel

GENERIC_LABELS = {
    "call",
    "return",
    "raise",
    "action",
    "branch",
    "condition",
    "unknown",
}
LOW_CONFIDENCE = {"low", "none"}
HUGE_FLOW_NODE_THRESHOLD = 60
DENSE_EDGE_RATIO_THRESHOLD = 2.6


def model_quality(model: ProjectModel) -> dict[str, Any]:
    """Deterministic analyzer-quality metrics derived from one persisted model."""
    non_test_flows = [flow for flow in model.flows if not flow.metadata.get("test")]
    call_nodes = [node for flow in model.flows for node in flow.nodes if node.kind is NodeKind.CALL]
    resolved = [node for node in call_nodes if node.metadata.get("target_flow")]
    ambiguous = [node for node in call_nodes if len(node.metadata.get("call_candidates", [])) > 1]
    unresolved = [
        node
        for node in call_nodes
        if not node.metadata.get("target_flow") and not node.metadata.get("call_candidates")
    ]
    low_confidence = [
        node
        for node in call_nodes
        if str(node.metadata.get("link_confidence", "")).lower() in LOW_CONFIDENCE
    ]
    node_count = sum(len(flow.nodes) for flow in model.flows)
    edge_count = sum(len(flow.edges) for flow in model.flows)
    generic_labels = _generic_label_nodes(model.flows)
    source_locations = _source_location_nodes(model.flows)
    findings = model.findings
    huge_flows = [
        {
            "flow_id": flow.id,
            "name": flow.name,
            "nodes": len(flow.nodes),
            "source": f"{flow.location.path}:{flow.location.start_line}",
        }
        for flow in non_test_flows
        if len(flow.nodes) >= HUGE_FLOW_NODE_THRESHOLD
    ]
    edge_ratio = round(edge_count / node_count, 2) if node_count else 0.0
    return {
        "files": {
            "total": len(model.files),
            "by_language": dict(Counter(record.language for record in model.files)),
            "empty": sum(1 for record in model.files if not record.flow_ids),
        },
        "flows": {
            "total": len(model.flows),
            "non_test": len(non_test_flows),
            "entrypoints": sum(flow.is_entrypoint for flow in non_test_flows),
            "by_language": dict(Counter(flow.language for flow in non_test_flows)),
            "by_entry_kind": dict(Counter(flow.entry_kind for flow in non_test_flows)),
            "per_file": _flow_distribution(model.flows),
            "huge": huge_flows[:20],
        },
        "calls": {
            "total": len(call_nodes),
            "resolved": len(resolved),
            "unresolved": len(unresolved),
            "ambiguous": len(ambiguous),
            "low_confidence": len(low_confidence),
            "resolution_rate": _ratio(len(resolved), len(call_nodes)),
        },
        "findings": _finding_quality(findings),
        "labels": {
            "generic_nodes": len(generic_labels),
            "generic_ratio": _ratio(len(generic_labels), node_count),
            "sample": generic_labels[:20],
        },
        "source_locations": {
            "nodes_with_source": len(source_locations),
            "coverage": _ratio(len(source_locations), node_count),
        },
        "graph": {
            "nodes": node_count,
            "edges": edge_count,
            "edge_to_node_ratio": edge_ratio,
            "dense_graph_warning": edge_ratio >= DENSE_EDGE_RATIO_THRESHOLD,
        },
    }


def render_quality(quality: dict[str, Any]) -> str:
    files = quality["files"]
    flows = quality["flows"]
    calls = quality["calls"]
    labels = quality["labels"]
    source = quality["source_locations"]
    graph = quality["graph"]
    findings = quality["findings"]
    lines = [
        "Analysis quality:",
        f"- Files: {files['total']} ({_format_counts(files['by_language'])})",
        f"- Flows: {flows['total']} total, {flows['entrypoints']} entrypoints "
        f"({_format_counts(flows['by_language'])})",
        f"- Calls: {calls['resolved']}/{calls['total']} resolved "
        f"({calls['resolution_rate']:.0%}); {calls['unresolved']} unresolved, "
        f"{calls['ambiguous']} ambiguous, {calls['low_confidence']} low-confidence",
        f"- Findings: {findings['total']} total ({_format_counts(findings['by_evidence'])})",
        f"- Labels: {labels['generic_nodes']} generic nodes ({labels['generic_ratio']:.0%})",
        f"- Source coverage: {source['nodes_with_source']} nodes ({source['coverage']:.0%})",
        f"- Graph density: {graph['edges']} edges / {graph['nodes']} nodes "
        f"({graph['edge_to_node_ratio']})",
    ]
    if flows["huge"]:
        lines.append("- Huge flows:")
        lines.extend(
            f"  - {item['name']} ({item['nodes']} nodes, {item['source']})"
            for item in flows["huge"][:5]
        )
    if labels["sample"]:
        lines.append("- Generic label samples:")
        lines.extend(f"  - {item['label']} ({item['source']})" for item in labels["sample"][:5])
    if graph["dense_graph_warning"]:
        lines.append("- Warning: graph edge density is high; inspect layout and call resolution.")
    return "\n".join(lines)


def _finding_quality(findings: list[Finding]) -> dict[str, Any]:
    return {
        "total": len(findings),
        "by_kind": dict(Counter(finding.kind for finding in findings)),
        "by_severity": dict(Counter(finding.severity.value for finding in findings)),
        "by_evidence": dict(Counter(finding.evidence.value for finding in findings)),
    }


def _flow_distribution(flows: list[Flow]) -> dict[str, Any]:
    counts = Counter(flow.location.path for flow in flows)
    values = sorted(counts.values())
    if not values:
        return {"min": 0, "max": 0, "avg": 0.0}
    return {
        "min": values[0],
        "max": values[-1],
        "avg": round(sum(values) / len(values), 2),
    }


def _generic_label_nodes(flows: list[Flow]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for flow in flows:
        for node in flow.nodes:
            if not _generic_label(node):
                continue
            rows.append(
                {
                    "flow_id": flow.id,
                    "node_id": node.id,
                    "label": node.label,
                    "source": f"{node.location.path}:{node.location.start_line}",
                }
            )
    return rows


def _generic_label(node: FlowNode) -> bool:
    label = " ".join(node.label.lower().split())
    if label in GENERIC_LABELS:
        return True
    if node.kind is NodeKind.CALL and label.startswith("call "):
        return len(label.split()) <= 2
    return node.kind is NodeKind.ACTION and label in {"do work", "handle", "process"}


def _source_location_nodes(flows: list[Flow]) -> list[FlowNode]:
    return [
        node
        for flow in flows
        for node in flow.nodes
        if node.location.path and node.location.start_line > 0 and node.location.end_line > 0
    ]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "none"
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items()))
