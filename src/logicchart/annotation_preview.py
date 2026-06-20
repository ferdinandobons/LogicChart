from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logicchart.annotations import ANNOTATIONS_SCHEMA_VERSION, annotations_path, model_hash
from logicchart.config import LogicChartConfig
from logicchart.model import Flow, FlowNode, ProjectModel
from logicchart.util import metadata_scope_names

_DEFAULT_MAX_FLOWS = 12
_DEFAULT_MAX_NODES_PER_FLOW = 18


@dataclass(frozen=True)
class AnnotationPreviewOptions:
    scope: str | None = None
    flow_ids: tuple[str, ...] = ()
    max_flows: int = _DEFAULT_MAX_FLOWS
    max_nodes_per_flow: int = _DEFAULT_MAX_NODES_PER_FLOW


def build_annotation_preview(
    root: Path,
    model: ProjectModel,
    config: LogicChartConfig,
    options: AnnotationPreviewOptions,
) -> dict[str, Any]:
    selected_flows = _select_flows(model, options)
    request = _build_annotation_request(model, selected_flows, options)

    return {
        "provider_call_made": False,
        "send_required": False,
        "model_hash": model_hash(model),
        "output": str(annotations_path(root, config)),
        "targets": {
            "scope": options.scope,
            "flow_ids": [flow.id for flow in selected_flows],
            "omitted_flow_count": max(
                0,
                len(_candidate_flows(model, options)) - len(selected_flows),
            ),
        },
        "request": request,
        "guardrails": [
            "Preview mode is local-only and never calls a provider.",
            (
                "Annotations can label or summarize existing ids only; "
                "they cannot change flow structure."
            ),
            (
                "Agent-authored annotations must validate as logic-annotations.json "
                "before they are written."
            ),
        ],
    }


def _build_annotation_request(
    model: ProjectModel,
    flows: list[Flow],
    options: AnnotationPreviewOptions,
) -> dict[str, Any]:
    return {
        "task": "Return LogicChart annotation sidecar JSON only.",
        "schema": {
            "schema_version": ANNOTATIONS_SCHEMA_VERSION,
            "model_hash": model_hash(model),
            "allowed_buckets": {
                "flows": ["label", "description", "summary"],
                "nodes": ["label", "description"],
                "scopes": ["label", "description", "summary"],
            },
            "limits": {"label": 120, "text": 2000},
        },
        "instructions": [
            "Use only ids present in this request.",
            "Do not create, delete, or rename flow nodes.",
            "Keep labels short and specific to the code behavior.",
            "Use annotations to improve comprehension; do not frame them as defect reports.",
            "Return a JSON object matching logic-annotations schema_version 1.0.",
        ],
        "selection": {
            "scope": options.scope,
            "max_flows": options.max_flows,
            "max_nodes_per_flow": options.max_nodes_per_flow,
        },
        "scopes": _request_scopes(model, flows),
        "flows": [_flow_payload(flow, options.max_nodes_per_flow) for flow in flows],
    }


def _select_flows(model: ProjectModel, options: AnnotationPreviewOptions) -> list[Flow]:
    return _candidate_flows(model, options)[: max(0, options.max_flows)]


def _candidate_flows(model: ProjectModel, options: AnnotationPreviewOptions) -> list[Flow]:
    flows = model.flows
    if options.scope:
        flows = [flow for flow in flows if options.scope in _flow_scopes(flow)]
    if options.flow_ids:
        wanted = set(options.flow_ids)
        flows = [
            flow
            for flow in flows
            if flow.id in wanted or flow.symbol in wanted or flow.name in wanted
        ]
    return sorted(
        flows,
        key=lambda flow: (
            not flow.is_entrypoint,
            flow.location.path,
            flow.name,
            flow.id,
        ),
    )


def _request_scopes(model: ProjectModel, flows: list[Flow]) -> dict[str, Any]:
    requested = {scope for flow in flows for scope in _flow_scopes(flow)}
    scopes = model.metadata.get("scopes", {})
    if not isinstance(scopes, dict):
        return {}
    return {scope: scopes.get(scope, {}) for scope in sorted(requested)}


def _flow_payload(flow: Flow, max_nodes: int) -> dict[str, Any]:
    nodes = flow.nodes[: max(0, max_nodes)]
    return {
        "id": flow.id,
        "name": flow.name,
        "symbol": flow.symbol,
        "language": flow.language,
        "entry_kind": flow.entry_kind,
        "is_entrypoint": flow.is_entrypoint,
        "source": _source_payload(flow.location),
        "calls": flow.calls[:20],
        "called_by": flow.called_by[:20],
        "scopes": _flow_scopes(flow),
        "nodes": [_node_payload(node) for node in nodes],
        "omitted_node_count": max(0, len(flow.nodes) - len(nodes)),
    }


def _node_payload(node: FlowNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": node.kind.value,
        "label": node.label,
        "evidence": node.evidence.value,
        "source": _source_payload(node.location),
    }


def _source_payload(location: Any) -> dict[str, Any]:
    return {
        "path": location.path,
        "start_line": location.start_line,
        "end_line": location.end_line,
    }


def _flow_scopes(flow: Flow) -> list[str]:
    return sorted(metadata_scope_names(flow.metadata))
