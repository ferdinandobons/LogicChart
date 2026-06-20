from __future__ import annotations

import hashlib
import html
import json
import re
import shlex
import sys
from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import asdict
from itertools import pairwise
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

from logicchart.analysis import ProjectAnalyzer
from logicchart.annotation_preview import AnnotationPreviewOptions, build_annotation_preview
from logicchart.annotations import (
    ANNOTATIONS_SCHEMA_VERSION,
    AnnotationLoadResult,
    annotations_path,
    load_annotations,
    model_hash,
    validate_annotations_payload,
)
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.model import Flow, FlowEdge, FlowNode, NodeKind, ProjectModel
from logicchart.quality import model_quality
from logicchart.query import (
    find_decisions,
    flow_navigation,
    flow_summary,
    git_changed_files,
    impact_model,
    model_summary,
    query_model,
    where_is_state_handled,
)
from logicchart.render.snapshot import (
    SNAPSHOT_FORMATS,
    render_flow_snapshot,
    render_impact_snapshot,
    render_subgraph_snapshot,
    unsupported_snapshot_format,
)
from logicchart.util import metadata_scope_names
from logicchart.validation import validate_logicchart

# Rough tokens per returned list item, used to honor an agent's token_budget cap.
_TOKENS_PER_ITEM = 60
_DEFAULT_CONTEXT_VISUAL_BYTE_BUDGET = 120_000

# Errors raised while loading the on-disk model (missing file, corrupt/garbled JSON,
# unexpected schema). Surfaced to the agent as a clean {"error": ...} instead of a raw
# traceback, so a stale or never-built model is recoverable advice, not a crash.
_LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError)

MCP_INSTRUCTIONS = """Use LogicChart as an agent-first code-logic understanding layer.
Prefer agent_context for ordinary user questions before broad file-by-file search. Use
domain_map when the user asks about statuses, roles, permissions, or other state-like
logic.
After substantial code edits, call update_logicchart and validate_artifacts, then commit
the synchronized logic-flow.json and logic-flow.md artifacts when they changed. Use
update_logicchart(full=true) when artifacts are missing, stale, or analyzer behavior
changed and cached file models should be ignored. Use preview_annotation_targets and
write_annotations for local agent-authored labels and summaries without provider keys."""


def _cap(items: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return items
    return items[: max(1, token_budget // _TOKENS_PER_ITEM)]


def _snapshot_node_budget(token_budget: int) -> int | None:
    if token_budget <= 0:
        return None
    return max(4, token_budget // 80)


def _snapshot_flow_budget(token_budget: int) -> int | None:
    if token_budget <= 0:
        return None
    return max(1, token_budget // 120)


def _impact_changed_files(
    project_root: Path,
    changed_files: list[str] | None,
    flow_ids: list[str] | None,
    symbols: list[str] | None,
    dependency_paths: list[str] | None,
) -> list[str]:
    has_targets = bool(flow_ids or symbols or dependency_paths)
    if changed_files is not None:
        return changed_files
    return [] if has_targets else git_changed_files(project_root)


def run_mcp(root: Path, config: LogicChartConfig | None = None) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "MCP support is not importable. Reinstall LogicChart with `uv tool install .` "
            "or run `uv sync --extra dev` for development."
        ) from error

    project_root = root.resolve()
    active_config = config or LogicChartConfig.load(project_root)
    server = FastMCP("LogicChart", instructions=MCP_INSTRUCTIONS, json_response=True)

    @server.tool()
    def list_flows(entrypoints_only: bool = True, token_budget: int = 0) -> list[dict[str, Any]]:
        """List known decision flows in the current project."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        return _cap(
            [
                {
                    "id": flow.id,
                    "name": flow.name,
                    "symbol": flow.symbol,
                    "entry_kind": flow.entry_kind,
                    "framework": flow.framework,
                    "source": f"{flow.location.path}:{flow.location.start_line}",
                }
                for flow in model.flows
                if flow.is_entrypoint or not entrypoints_only
            ],
            token_budget,
        )

    @server.tool()
    def get_flow(flow_id: str, token_budget: int = 0) -> dict[str, Any]:
        """Return one complete flow, including nodes, edges, callers, and callees."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        flow = next((item for item in model.flows if item.id == flow_id), None)
        if flow is None:
            return _unknown_target_error("flow", flow_id)
        flow_dict = _flow_dict(flow)
        # Honor the budget by trimming the largest list-shaped fields of the graph, then
        # keep the subgraph internally consistent: drop any edge whose source or target
        # node was capped away, so the result is never a dangling-edge graph.
        flow_dict["nodes"] = _cap(flow_dict.get("nodes", []), token_budget)
        kept_node_ids = {node["id"] for node in flow_dict["nodes"]}
        flow_dict["edges"] = _cap(
            [
                edge
                for edge in flow_dict.get("edges", [])
                if edge["source"] in kept_node_ids and edge["target"] in kept_node_ids
            ],
            token_budget,
        )
        return {"flow": flow_dict}

    @server.tool()
    def get_flow_navigation(flow_id: str, token_budget: int = 0) -> dict[str, Any]:
        """Return an agent navigation pack for one flow: relations and decisions."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        return flow_navigation(model, flow_id, token_budget, annotation_payload)

    @server.tool()
    def get_flow_snapshot(
        flow_id: str, format: str = "svg", token_budget: int = 0
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for one flow."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_flow_snapshot(
            model,
            flow_id,
            max_nodes=_snapshot_node_budget(token_budget),
        )

    @server.tool()
    def query_logic(
        question: str,
        limit: int = 10,
        scope: str | None = None,
        language: str | None = None,
        source_path: str | None = None,
        symbol: str | None = None,
        domain: str | None = None,
        value: str | None = None,
        token_budget: int = 0,
    ) -> list[dict[str, Any]]:
        """Find flows relevant to a behavior, decision, state, or codebase question.

        ``scope`` restricts to a named macro-part so the result matches deterministic
        query ranking. ``token_budget`` only ever shrinks the list below ``limit``; it
        never expands it (query_model has already truncated to ``limit``).
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        matches = query_model(
            model,
            question,
            limit,
            scope,
            language=language,
            source_path=source_path,
            symbol=symbol,
            domain=domain,
            value=value,
        )
        return _cap([match.to_dict() for match in matches], token_budget)

    @server.tool()
    def get_subgraph_snapshot(
        flow_ids: list[str] | None = None,
        format: str = "svg",
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for explicit flows."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_subgraph_snapshot(
            model,
            flow_ids=flow_ids,
            max_flows=_snapshot_flow_budget(token_budget),
            max_nodes=_snapshot_node_budget(token_budget),
        )

    @server.tool()
    def logicchart_summary() -> dict[str, Any]:
        """An orientation snapshot: flow, entrypoint, language, and quality counts."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        summary = model_summary(model)
        summary["annotations"] = load_annotations(project_root, model, active_config).to_dict()
        return summary

    @server.tool()
    def preview_enrichment(
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        max_flows: int = 8,
        max_nodes_per_flow: int = 12,
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Preview local annotation targets without calling a provider.

        The result is local-only and always reports ``provider_call_made: false``. The
        agent-first workflow should use this to inspect candidate annotation targets, then
        write validated agent-authored annotations through LogicChart annotation tools.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        options = _enrichment_options(
            scope=scope,
            flow_ids=flow_ids,
            max_flows=max_flows,
            max_nodes_per_flow=max_nodes_per_flow,
            token_budget=token_budget,
        )
        preview = build_annotation_preview(
            project_root,
            model,
            active_config,
            options,
        )
        return _enrichment_preview_payload(
            preview,
            token_budget=token_budget,
        )

    @server.tool()
    def preview_annotation_targets(
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        max_flows: int = 8,
        max_nodes_per_flow: int = 12,
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Preview local annotation targets without provider setup or network calls."""
        preview = cast(
            dict[str, Any],
            preview_enrichment(
                scope=scope,
                flow_ids=flow_ids,
                max_flows=max_flows,
                max_nodes_per_flow=max_nodes_per_flow,
                token_budget=token_budget,
            ),
        )
        if "error" in preview:
            return preview
        preview["tool"] = "preview_annotation_targets"
        preview["send_required"] = False
        preview["schema_version"] = ANNOTATIONS_SCHEMA_VERSION
        preview["allowed_fields"] = _annotation_allowed_fields()
        preview["guardrail"] = (
            "This tool only previews local targets. Use write_annotations for "
            "agent_generated text, and keep annotation content separate from "
            "deterministic LogicChart facts."
        )
        preview["next_tools"]["write_annotations"] = {
            "tool": "write_annotations",
            "arguments": {
                "replace_existing": False,
                "generated_by": {
                    "kind": "agent_generated",
                    "logicchart_workflow": "agent_authored_annotations",
                },
            },
        }
        return preview

    @server.tool()
    def annotation_status(include_annotations: bool = False) -> dict[str, Any]:
        """Return annotation sidecar status, counts, and validation guardrails."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return _annotation_status_payload(project_root, model, active_config, include_annotations)

    @server.tool()
    def validate_annotations(include_annotations: bool = False) -> dict[str, Any]:
        """Validate the optional annotation sidecar against the current model."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        payload = _annotation_status_payload(
            project_root,
            model,
            active_config,
            include_annotations,
        )
        payload["tool"] = "validate_annotations"
        payload["next_tools"] = {
            **payload.get("next_tools", {}),
            "validate_artifacts": {
                "tool": "validate_artifacts",
                "arguments": {"check_sync": True, "include_quality": True},
            },
        }
        return payload

    @server.tool()
    def write_annotations(
        annotations: dict[str, Any] | None = None,
        flows: dict[str, dict[str, str]] | None = None,
        nodes: dict[str, dict[str, str]] | None = None,
        scopes: dict[str, dict[str, str]] | None = None,
        generated_by: dict[str, Any] | None = None,
        replace_existing: bool = False,
    ) -> dict[str, Any]:
        """Write validated agent-authored annotations to logic-annotations.json."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return _write_annotations_payload(
            project_root,
            model,
            active_config,
            annotations=annotations,
            flows=flows,
            nodes=nodes,
            scopes=scopes,
            generated_by=generated_by,
            replace_existing=replace_existing,
        )

    @server.tool()
    def clear_annotations(confirm: bool = False) -> dict[str, Any]:
        """Remove logic-annotations.json only when confirm=true is supplied."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        path = annotations_path(project_root, active_config)
        if not confirm:
            return {
                "ok": False,
                "error": "clear_annotations requires confirm=true.",
                "error_code": "annotation_clear_confirmation_required",
                "path": str(path),
                "guardrail": (
                    "Clearing annotations removes optional agent-generated text only; it "
                    "does not change deterministic LogicChart artifacts."
                ),
            }
        if path.exists():
            path.unlink()
        payload = _annotation_status_payload(project_root, model, active_config, False)
        payload["tool"] = "clear_annotations"
        payload["cleared"] = True
        return payload

    @server.tool()
    def analysis_quality(token_budget: int = 0) -> dict[str, Any]:
        """Analyzer-quality metrics for model coverage, parsing, calls, and labels."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        quality = model.metadata.get("quality")
        if not isinstance(quality, dict):
            quality = model_quality(model)
        return _quality_report(quality, token_budget)

    @server.tool()
    def where_state_handled(
        domain: str, value: str | None = None, token_budget: int = 0
    ) -> list[dict[str, Any]]:
        """Every flow that branches on a domain/value-namespace, with the values it covers."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        return _cap(where_is_state_handled(model, domain, value), token_budget)

    @server.tool()
    def find_decision_nodes(
        domain: str | None = None,
        subject: str | None = None,
        missing_fallback: bool = False,
        token_budget: int = 0,
    ) -> list[dict[str, Any]]:
        """Structured search over decision nodes (by domain/subject/implicit fallback)."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        decisions = find_decisions(
            model,
            domain=domain,
            subject=subject,
            missing_fallback=missing_fallback,
        )
        return _cap(decisions, token_budget)

    @server.tool()
    def domain_map(
        domain: str | None = None,
        value: str | None = None,
        scope: str | None = None,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Aggregate domain/state handling across decisions and flows."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return _domain_logic_map(
            model,
            domain=domain,
            value=value,
            scope=scope,
            token_budget=token_budget,
        )

    @server.tool()
    def analyze_impact(
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        dependency_paths: list[str] | None = None,
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Find direct and transitive decision flows affected by files or explicit targets.

        ``scope`` restricts to a named macro-part, matching the model scope filter.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        changes = _impact_changed_files(
            project_root, changed_files, flow_ids, symbols, dependency_paths
        )
        result = impact_model(
            model,
            changes,
            scope,
            flow_ids=flow_ids,
            symbols=symbols,
            dependency_paths=dependency_paths,
        )
        direct = [
            _impact_flow_summary(item, result.impact_reasons) for item in result.directly_impacted
        ]
        transitive = [
            _impact_flow_summary(item, result.impact_reasons)
            for item in result.transitively_impacted
        ]
        return {
            "changed_files": result.changed_files,
            "target_flow_ids": result.target_flow_ids,
            "target_symbols": result.target_symbols,
            "target_dependency_paths": result.target_dependency_paths,
            "unresolved_targets": result.unresolved_targets,
            "impact_reasons": result.impact_reasons,
            "direct": _cap(direct, token_budget),
            "transitive": _cap(transitive, token_budget),
            "subgraph_flow_ids": result.subgraph_flow_ids,
        }

    @server.tool()
    def get_impact_snapshot(
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        dependency_paths: list[str] | None = None,
        format: str = "svg",
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for direct and caller impact."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        changes = _impact_changed_files(
            project_root, changed_files, flow_ids, symbols, dependency_paths
        )
        result = impact_model(
            model,
            changes,
            scope,
            flow_ids=flow_ids,
            symbols=symbols,
            dependency_paths=dependency_paths,
        )
        return render_impact_snapshot(
            changed_files=result.changed_files,
            direct=result.directly_impacted,
            transitive=result.transitively_impacted,
            max_flows=_snapshot_flow_budget(token_budget),
            target_flow_ids=result.target_flow_ids,
            target_symbols=result.target_symbols,
            target_dependency_paths=result.target_dependency_paths,
            unresolved_targets=result.unresolved_targets,
            impact_reasons=result.impact_reasons,
            subgraph_flow_ids=result.subgraph_flow_ids,
        )

    @server.tool()
    def context_pack(
        question: str | None = None,
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        dependency_paths: list[str] | None = None,
        language: str | None = None,
        source_path: str | None = None,
        domain: str | None = None,
        value: str | None = None,
        include_visual: bool = False,
        token_budget: int = 600,
        visual_byte_budget: int = _DEFAULT_CONTEXT_VISUAL_BYTE_BUDGET,
    ) -> dict[str, Any]:
        """Compact orientation pack: summary, relevant flows, impact, navigation, visuals.

        ``flow_ids``, ``symbols``, and ``dependency_paths`` mirror
        ``analyze_impact`` so an agent can build a context pack around an exact flow,
        symbol, or source subtree without pretending a file changed.
        Query filters mirror ``query_logic`` so agents can request a bounded pack for
        source, state-domain, or language slices without lexical terms.
        ``visual_byte_budget`` caps inline SVG bytes when ``include_visual`` is true;
        omitted snapshots remain available through the returned ``next_tools``.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return _context_pack_payload(
            project_root,
            active_config,
            model,
            question=question,
            changed_files=changed_files,
            scope=scope,
            flow_ids=flow_ids,
            symbols=symbols,
            dependency_paths=dependency_paths,
            language=language,
            source_path=source_path,
            domain=domain,
            value=value,
            include_visual=include_visual,
            token_budget=token_budget,
            visual_byte_budget=visual_byte_budget,
        )

    @server.tool()
    def agent_context(
        question: str | None = None,
        changed_files: list[str] | None = None,
        selected_code: str | None = None,
        current_file: str | None = None,
        flow_id: str | None = None,
        symbol: str | None = None,
        dependency_path: str | None = None,
        domain: str | None = None,
        value: str | None = None,
        scope: str | None = None,
        include_visual: bool = False,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Primary agent entrypoint for code-logic questions and change impact.

        Accepts the context a coding agent naturally has: user question, changed files,
        selected code/current file, or focused flow/symbol/dependency targets.
        Returns one bounded workflow_slice plus compatible query, impact, navigation,
        source-range, guardrail, and optional visual snapshot context.
        """
        effective_question = _agent_context_question(question, selected_code)
        source_path = current_file.strip() if current_file and current_file.strip() else None
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        domain_scope, _scope_query_hint = _agent_scope_filter(model, scope)
        pack = _context_pack_payload(
            project_root,
            active_config,
            model,
            question=effective_question,
            changed_files=changed_files,
            scope=scope,
            flow_ids=_single_item_list(flow_id),
            symbols=_single_item_list(symbol),
            dependency_paths=_single_item_list(dependency_path),
            source_path=source_path,
            domain=domain,
            value=value,
            include_visual=include_visual,
            token_budget=token_budget,
        )
        domain_payload = _domain_logic_map(
            model,
            domain=domain,
            value=value,
            scope=domain_scope,
            token_budget=token_budget,
        )
        workflow_slice = _workflow_slice_payload(
            model,
            pack,
            question=effective_question,
            inputs={
                "question": question,
                "changed_files": changed_files or [],
                "current_file": source_path,
                "flow_id": flow_id,
                "symbol": symbol,
                "dependency_path": dependency_path,
                "domain": domain,
                "value": value,
                "scope": scope,
                "include_visual": include_visual,
                "token_budget": token_budget,
            },
            domain_map_payload=domain_payload,
            token_budget=token_budget,
        )
        recommended_next_tools = _agent_context_next_tools(pack, token_budget)
        recommended_next_tools["workflow_slice"] = workflow_slice["next_tools"]
        return {
            "tool": "agent_context",
            "guardrail": (
                "Use this as source-grounded context for explanation or edits. Do not "
                "invent workflow steps, branches, constants, limits, or error codes outside "
                "the returned LogicChart payload; keep agent-generated annotation text "
                "separate from deterministic facts."
            ),
            "inputs": {
                "question": question,
                "changed_files": changed_files or [],
                "current_file": source_path,
                "selected_code_excerpt": _selected_code_excerpt(selected_code),
                "flow_id": flow_id,
                "symbol": symbol,
                "dependency_path": dependency_path,
                "domain": domain,
                "value": value,
                "scope": scope,
                "include_visual": include_visual,
                "token_budget": token_budget,
            },
            "workflow_slice": workflow_slice,
            "context": pack,
            "domain_map": domain_payload,
            "recommended_next_tools": recommended_next_tools,
        }

    @server.tool()
    def expand_slice(
        slice_id: str | None = None,
        flow_ids: list[str] | None = None,
        direction: str = "neighbors",
        depth: int = 1,
        include_visual: bool = False,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Widen or deepen a workflow slice from stable flow handles."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        expansion = _expand_workflow_slice_targets(
            model,
            flow_ids=flow_ids,
            direction=direction,
            depth=depth,
            token_budget=token_budget,
        )
        if expansion["error_code"]:
            return _slice_target_error(
                "expand_slice",
                expansion["error_code"],
                expansion["message"],
                slice_id=slice_id,
                flow_ids=flow_ids,
            )
        pack = _context_pack_payload(
            project_root,
            active_config,
            model,
            question=f"expand workflow slice {direction}",
            flow_ids=expansion["flow_ids"],
            include_visual=include_visual,
            token_budget=token_budget,
        )
        domain_payload = _domain_logic_map(
            model,
            domain=None,
            value=None,
            scope=None,
            token_budget=token_budget,
        )
        workflow_slice = _workflow_slice_payload(
            model,
            pack,
            question=f"expand workflow slice {direction}",
            inputs={
                "slice_id": slice_id,
                "flow_ids": flow_ids or [],
                "direction": direction,
                "depth": depth,
                "include_visual": include_visual,
                "token_budget": token_budget,
            },
            domain_map_payload=domain_payload,
            token_budget=token_budget,
        )
        return {
            "tool": "expand_slice",
            "base_slice_id": slice_id,
            "direction": expansion["direction"],
            "depth": expansion["depth"],
            "expansion": expansion,
            "workflow_slice": workflow_slice,
        }

    @server.tool()
    def workflow_path(
        source: str,
        target: str,
        scope: str | None = None,
        include_visual: bool = False,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Trace a deterministic workflow path between two flows, symbols, or concepts."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        source_seed = _resolve_workflow_path_seed(model, source, scope, token_budget)
        target_seed = _resolve_workflow_path_seed(model, target, scope, token_budget)
        if not source_seed["flow_ids"] or not target_seed["flow_ids"]:
            return _workflow_path_error(source, target, source_seed, target_seed, token_budget)
        path = _find_workflow_path(model, source_seed["flow_ids"], target_seed["flow_ids"])
        selected_flow_ids = path["flow_ids"] or _unique_preserve_order(
            [*source_seed["flow_ids"][:2], *target_seed["flow_ids"][:2]]
        )
        pack = _context_pack_payload(
            project_root,
            active_config,
            model,
            question=f"{source} -> {target}",
            scope=scope,
            flow_ids=selected_flow_ids,
            include_visual=include_visual,
            token_budget=token_budget,
        )
        domain_payload = _domain_logic_map(
            model,
            domain=None,
            value=None,
            scope=scope,
            token_budget=token_budget,
        )
        workflow_slice = _workflow_slice_payload(
            model,
            pack,
            question=f"{source} -> {target}",
            inputs={
                "source": source,
                "target": target,
                "scope": scope,
                "include_visual": include_visual,
                "token_budget": token_budget,
            },
            domain_map_payload=domain_payload,
            token_budget=token_budget,
        )
        return {
            "tool": "workflow_path",
            "source": source_seed,
            "target": target_seed,
            "path": path,
            "workflow_slice": workflow_slice,
            "guardrail": (
                "A missing path means no static call path was modeled in the current "
                "artifact; it does not prove runtime disconnection."
            ),
        }

    @server.tool()
    def snapshot_slice(
        slice_id: str | None = None,
        flow_ids: list[str] | None = None,
        format: str = "svg",
        include_svg: bool = True,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Render a deterministic visual snapshot for a workflow slice."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        normalized_flow_ids = _known_flow_ids(model, flow_ids)
        if not normalized_flow_ids:
            return _slice_target_error(
                "snapshot_slice",
                "slice_targets_missing",
                "snapshot_slice requires at least one known flow_id.",
                slice_id=slice_id,
                flow_ids=flow_ids,
            )
        snapshot = render_subgraph_snapshot(
            model,
            flow_ids=normalized_flow_ids,
            max_flows=_snapshot_flow_budget(token_budget),
            max_nodes=_snapshot_node_budget(token_budget),
        )
        artifact = _write_snapshot_artifact(
            project_root,
            snapshot,
            slice_id=slice_id,
            flow_ids=normalized_flow_ids,
        )
        snapshot_payload = dict(snapshot)
        if not include_svg and "svg" in snapshot_payload:
            snapshot_payload["svg_omitted"] = True
            snapshot_payload["svg_omitted_reason"] = "include_svg=false"
            snapshot_payload["svg_byte_size"] = _snapshot_svg_byte_size(snapshot)
            snapshot_payload.pop("svg", None)
        return {
            "tool": "snapshot_slice",
            "slice_id": slice_id,
            "format": format,
            "flow_ids": normalized_flow_ids,
            "snapshot": snapshot_payload,
            "artifact": artifact,
            "viewer_targets": _workflow_viewer_targets(
                model,
                normalized_flow_ids,
            ),
            "guardrail": (
                "Snapshots are deterministic visual context for the selected slice. "
                "Omission counts must be preserved when explaining large slices. "
                "If the client cannot render inline SVG or Mermaid, open the returned "
                "artifact html_path/svg_path instead of rebuilding the diagram."
            ),
        }

    @server.tool()
    def explain_flow(flow_id: str, token_budget: int = 900) -> dict[str, Any]:
        """Explain one flow with source anchors, decisions, calls, and next tools."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        flow = _flow_by_id(model, flow_id)
        if flow is None:
            return _unknown_target_error("flow", flow_id)
        return _focused_flow_explanation(model, flow, token_budget)

    @server.tool()
    def explain_node(
        node_id: str,
        flow_id: str | None = None,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Explain one flowchart node with local edge and source context."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        resolved = _resolve_node(model, node_id, flow_id)
        if resolved is None:
            return _unknown_target_error("node", node_id)
        flow, node = resolved
        return _focused_node_explanation(model, flow, node, token_budget)

    @server.tool()
    def explain_edge(
        edge_id: str,
        flow_id: str | None = None,
        token_budget: int = 900,
    ) -> dict[str, Any]:
        """Explain one flowchart edge or modeled call edge with source context."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        resolved = _resolve_edge(model, edge_id, flow_id)
        if resolved is None:
            return _unknown_target_error("edge", edge_id)
        flow, edge = resolved
        return _focused_edge_explanation(model, flow, edge, token_budget)

    @server.tool()
    def validate_artifacts(
        check_sync: bool = False,
        include_quality: bool = False,
        max_skipped_files: int | None = None,
        max_parse_warnings: int | None = None,
        min_call_resolution: float | None = None,
        max_generic_label_ratio: float | None = None,
    ) -> dict[str, Any]:
        """Validate the generated model and optionally check source sync."""
        thresholds: dict[str, float | int] = {}
        if max_skipped_files is not None:
            thresholds["max_skipped_files"] = max_skipped_files
        if max_parse_warnings is not None:
            thresholds["max_parse_warnings"] = max_parse_warnings
        if min_call_resolution is not None:
            thresholds["min_call_resolution"] = min_call_resolution
        if max_generic_label_ratio is not None:
            thresholds["max_generic_label_ratio"] = max_generic_label_ratio
        report = validate_logicchart(
            project_root,
            config=active_config,
            check_sync=check_sync,
            include_quality=include_quality,
            quality_thresholds=thresholds,
        )
        return _validation_payload(report.to_dict())

    @server.tool()
    def update_logicchart(full: bool = False) -> dict[str, Any]:
        """Refresh LogicChart after source changes and write JSON, Markdown, and HTML."""
        result = ProjectAnalyzer(project_root, active_config).analyze(full=full)
        json_path, markdown_path, html_path = write_artifacts(
            project_root,
            result.model,
            config=active_config,
        )
        return {
            "changed_files": result.changed_files,
            "deleted_files": result.deleted_files,
            "cache_hits": result.cache_hits,
            "flows": len(result.model.flows),
            "artifacts": [
                str(json_path),
                str(markdown_path),
                str(html_path) if html_path else "",
            ],
            **_update_workflow_payload(json_path, markdown_path, html_path),
        }

    server.run(transport="stdio")


def _impact_flow_summary(flow: Any, impact_reasons: dict[str, list[str]]) -> dict[str, Any]:
    return {
        **flow_summary(flow),
        "reasons": impact_reasons.get(flow.id, []),
    }


def _flow_dict(flow: Any) -> dict[str, Any]:
    return asdict(flow)


def _context_pack_payload(
    root: Path,
    config: LogicChartConfig,
    model: ProjectModel,
    *,
    question: str | None = None,
    changed_files: list[str] | None = None,
    scope: str | None = None,
    flow_ids: list[str] | None = None,
    symbols: list[str] | None = None,
    dependency_paths: list[str] | None = None,
    language: str | None = None,
    source_path: str | None = None,
    domain: str | None = None,
    value: str | None = None,
    include_visual: bool = False,
    token_budget: int = 600,
    visual_byte_budget: int = _DEFAULT_CONTEXT_VISUAL_BYTE_BUDGET,
) -> dict[str, Any]:
    scope_filter, scope_query_hint = _agent_scope_filter(model, scope)
    effective_question = _question_with_scope_hint(question, scope_query_hint)
    changes = _impact_changed_files(root, changed_files, flow_ids, symbols, dependency_paths)
    impact = impact_model(
        model,
        changes,
        scope_filter,
        flow_ids=flow_ids,
        symbols=symbols,
        dependency_paths=dependency_paths,
    )
    query_filters = {
        key: val
        for key, val in {
            "language": language,
            "source_path": source_path,
            "domain": domain,
            "value": value,
        }.items()
        if val is not None
    }
    if scope_filter is not None:
        query_filters["scope"] = scope_filter
    if scope_query_hint is not None:
        query_filters["scope_query_hint"] = scope_query_hint
    matches_by_id = {
        match.flow.id: match
        for match in query_model(
            model,
            effective_question or " ".join(changes),
            limit=80,
            scope=scope_filter,
            language=language,
            source_path=source_path,
            domain=domain,
            value=value,
        )
    }
    for action_term in sorted(_agent_action_terms(effective_question)):
        for match in query_model(
            model,
            action_term,
            limit=12,
            scope=scope_filter,
            language=language,
            source_path=source_path,
            domain=domain,
            value=value,
        ):
            matches_by_id.setdefault(match.flow.id, match)
    matches = _agent_order_matches(list(matches_by_id.values()), effective_question)[:8]
    annotations = load_annotations(root, model, config)
    annotation_payload = annotations.annotations if annotations.ok else None
    return {
        "summary": model_summary(model),
        "query_filters": query_filters,
        "query": _cap([match.to_dict() for match in matches], token_budget),
        "impact": {
            "changed_files": impact.changed_files,
            "target_flow_ids": impact.target_flow_ids,
            "target_symbols": impact.target_symbols,
            "target_dependency_paths": impact.target_dependency_paths,
            "unresolved_targets": impact.unresolved_targets,
            "impact_reasons": impact.impact_reasons,
            "direct": _cap(
                [
                    _impact_flow_summary(item, impact.impact_reasons)
                    for item in impact.directly_impacted
                ],
                token_budget,
            ),
            "transitive": _cap(
                [
                    _impact_flow_summary(item, impact.impact_reasons)
                    for item in impact.transitively_impacted
                ],
                token_budget,
            ),
            "subgraph_flow_ids": impact.subgraph_flow_ids,
        },
        "navigation": _context_navigation_pack(
            model,
            impact=impact,
            matches=matches,
            annotations=annotation_payload,
            token_budget=token_budget,
        ),
        "visual_context": _context_visual_pack(
            model,
            impact=impact,
            matches=matches,
            scope=scope_filter,
            include_visual=include_visual,
            token_budget=token_budget,
            visual_byte_budget=visual_byte_budget,
        ),
    }


def _workflow_slice_payload(
    model: ProjectModel,
    pack: dict[str, Any],
    *,
    question: str | None,
    inputs: dict[str, Any],
    domain_map_payload: dict[str, Any],
    token_budget: int,
) -> dict[str, Any]:
    primary_flow_ids = _workflow_primary_flow_ids(pack)
    selected_flow_ids = _workflow_selected_flow_ids(pack)
    if not primary_flow_ids:
        primary_flow_ids = selected_flow_ids[: _slice_primary_budget(token_budget)]
    supporting_flow_ids = [
        flow_id for flow_id in selected_flow_ids if flow_id not in set(primary_flow_ids)
    ][: _slice_supporting_budget(token_budget)]
    visible_flow_ids = _unique_preserve_order([*primary_flow_ids, *supporting_flow_ids])
    slice_id = _workflow_slice_id(model, inputs, visible_flow_ids)
    primary_flows = _workflow_flow_rows(model, primary_flow_ids)
    supporting_flows = _workflow_flow_rows(model, supporting_flow_ids)
    ordered_steps = _workflow_ordered_steps(model, primary_flow_ids, token_budget)
    decisions = _workflow_decisions(model, visible_flow_ids, token_budget)
    viewer_targets = _workflow_viewer_targets(model, visible_flow_ids)
    canonical_visual = _workflow_canonical_visual(
        model,
        visible_flow_ids,
        token_budget,
    )
    next_tools = _workflow_slice_next_tools(
        primary_flow_ids,
        supporting_flow_ids,
        token_budget,
    )
    return {
        "schema_version": "workflow_slice.v1",
        "id": slice_id,
        "model_hash": model_hash(model),
        "intent": {
            "question": question,
            "task_type": _workflow_task_type(question, inputs),
            "include_visual": bool(inputs.get("include_visual")),
            "token_budget": token_budget,
        },
        "handle": {
            "slice_id": slice_id,
            "model_hash": model_hash(model),
            "flow_ids": visible_flow_ids,
            "scope": inputs.get("scope"),
            "question": question,
        },
        "selection": _workflow_selection(pack, inputs, primary_flow_ids, supporting_flow_ids),
        "presentation": _workflow_presentation_contract(
            primary_flows=primary_flows,
            supporting_flows=supporting_flows,
            ordered_steps=ordered_steps,
            decisions=decisions,
            viewer_targets=viewer_targets,
            canonical_visual=canonical_visual,
            next_tools=next_tools,
        ),
        "primary_flows": primary_flows,
        "supporting_flows": supporting_flows,
        "ordered_steps": ordered_steps,
        "decisions": decisions,
        "calls": _workflow_calls(model, visible_flow_ids, token_budget),
        "domain_logic": _workflow_domain_logic(domain_map_payload, visible_flow_ids, token_budget),
        "source_ranges": _workflow_source_ranges(model, visible_flow_ids, pack, token_budget),
        "visuals": _workflow_visuals(pack),
        "viewer_targets": viewer_targets,
        "omissions": _workflow_omissions(pack, selected_flow_ids, visible_flow_ids, token_budget),
        "next_actions": _workflow_next_actions(primary_flow_ids, supporting_flow_ids),
        "next_tools": next_tools,
        "guardrail": (
            "workflow_slice is deterministic, local, and source-grounded. Agent-generated "
            "annotations must remain separate from deterministic LogicChart facts."
        ),
    }


def _workflow_slice_id(
    model: ProjectModel,
    inputs: dict[str, Any],
    flow_ids: list[str],
) -> str:
    payload = {
        "model_hash": model_hash(model),
        "inputs": inputs,
        "flow_ids": flow_ids,
    }
    raw = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return f"slice-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]}"


def _workflow_presentation_contract(
    *,
    primary_flows: list[dict[str, Any]],
    supporting_flows: list[dict[str, Any]],
    ordered_steps: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    viewer_targets: dict[str, Any],
    canonical_visual: dict[str, Any],
    next_tools: dict[str, Any],
) -> dict[str, Any]:
    primary_names = [str(flow.get("name")) for flow in primary_flows if flow.get("name")]
    title = "Workflow slice"
    if primary_names:
        title = f"Workflow slice: {', '.join(primary_names[:2])}"
    return {
        "schema_version": "workflow_slice.presentation.v1",
        "title": title,
        "counts": {
            "primary_flows": len(primary_flows),
            "supporting_flows": len(supporting_flows),
            "ordered_steps": len(ordered_steps),
            "decisions": len(decisions),
            "viewer_targets": viewer_targets.get("target_count", 0),
            "canonical_visual_nodes": canonical_visual.get("node_count", 0),
            "canonical_visual_edges": canonical_visual.get("edge_count", 0),
        },
        "default_sections": [
            {"label": "Slice Identity", "source_fields": ["id", "model_hash", "handle"]},
            {
                "label": "Canonical Visual",
                "source_fields": ["presentation.canonical_visual"],
            },
            {"label": "Primary Flows", "source_fields": ["primary_flows"]},
            {"label": "Supporting Flows", "source_fields": ["supporting_flows"]},
            {"label": "Ordered Steps", "source_fields": ["ordered_steps"]},
            {"label": "Decision Nodes", "source_fields": ["decisions"]},
            {"label": "Visual Targets", "source_fields": ["viewer_targets", "next_tools"]},
        ],
        "agent_guidance": [
            "When the user asks to show a workflow_slice or workflow, render "
            "presentation.canonical_visual.diagram as-is before prose.",
            "The agent may choose the visible depth and branches by asking for a "
            "narrower or expanded slice, but block contents must stay grounded in "
            "this payload.",
            "Tell the user the shown diagram is a bounded summary of the selected "
            "logic and can be expanded.",
            "End visual answers with concise follow-up choices: simplify labels in "
            "the user's language, expand omitted nodes or branches, or explore a "
            "related area.",
            "A separate human-friendly translation may rewrite labels in the user's "
            "language only from returned node, edge, source, and decision fields.",
            "Use ordered_steps as the canonical walkthrough and keep source anchors visible.",
            "Keep flow_id and node_id values visible so the slice can be expanded.",
            "Do not invent steps, constants, limits, error codes, or branches outside "
            "this payload.",
            "Show raw JSON or YAML only when the user explicitly asks for raw output.",
        ],
        "depth_policy": {
            "summary": (
                "This is a bounded workflow_slice selected for the request. Use the "
                "slice handle and recommended_next_tools to deepen, widen, or trace "
                "specific paths instead of manually inventing omitted branches."
            ),
            "agent_role": (
                "Choose the amount of detail to display for the user's question, but "
                "derive each displayed block from canonical_visual, ordered_steps, "
                "decisions, source_ranges, or focused explain_* tool results."
            ),
        },
        "display_policy": {
            "source_extraction": (
                "Use LogicChart as the deterministic source for the workflow requested "
                "by the user. Inspect the returned workflow_slice first; if relevant "
                "nodes, branches, callers, callees, or paths are missing, use "
                "recommended_next_tools before answering."
            ),
            "first_response": (
                "Show the clearest useful subset of the selected workflow. The agent "
                "may omit low-signal implementation nodes from the first visible graph, "
                "but it must preserve all displayed facts exactly from the selected "
                "workflow_slice or focused follow-up tool payloads."
            ),
            "closing_options": [
                "Offer a language-friendly rewrite of the graph labels in the user's language.",
                "Offer to expand the diagram with omitted nodes, branches, or adjacent flows.",
                "Offer to explore another related area or deepen a specific path.",
            ],
        },
        "label_policy": {
            "canonical": (
                "For stable output, render canonical_visual.diagram exactly and keep "
                "diagram_hash when useful."
            ),
            "human_friendly": (
                "A human-friendly translation may replace technical labels with "
                "clearer wording in the language used by the user, only as a separate "
                "presentation layer. Preserve ids or source anchors and do not add "
                "facts absent from the workflow_slice payload."
            ),
        },
        "media_policy": {
            "svg_snapshot": (
                "Prefer snapshot_slice when the client can render inline SVG, SVG/HTML "
                "visualization widgets, or local image artifacts; it is the closest static "
                "visual to the modeled graph. In terminal clients with no SVG widget, call "
                "snapshot_slice with include_svg=false and open the returned artifact "
                "html_path/svg_path."
            ),
            "mermaid_fallback": (
                "Use canonical_visual.diagram as the top-to-bottom universal text "
                "fallback when images are unavailable or the user wants copyable output; "
                "do not treat a code block as a rendered graph in clients that only show "
                "plain text."
            ),
            "manual_viewer": (
                "Keep logicchart view as the interactive manual UI; do not replace it "
                "with a static Mermaid or screenshot-only experience."
            ),
        },
        "visual_guidance": (
            "If the user asks to visualize the slice, call snapshot_slice with "
            "handle.flow_ids. If the client has an SVG/HTML "
            "visualization widget, render snapshot.svg through that widget. If inline SVG "
            "is unavailable in the client, call snapshot_slice with include_svg=false and "
            "provide the returned artifact html_path/svg_path or open_command before any "
            "text fallback. If no local artifact can be opened, render "
            "presentation.canonical_visual.diagram exactly; do not synthesize a new Mermaid "
            "diagram. Explain that the diagram is a bounded summary and can be expanded. "
            "End with options to simplify labels in the user's language, expand the graph "
            "with omitted details, or explore a related area. Open viewer_targets with "
            "logicchart view for manual inspection."
        ),
        "canonical_visual": canonical_visual,
        "recommended_next_tools": {
            key: value
            for key, value in next_tools.items()
            if key in {"expand_slice", "snapshot_slice", "workflow_path"}
        },
    }


def _workflow_canonical_visual(
    model: ProjectModel,
    flow_ids: list[str],
    token_budget: int,
) -> dict[str, Any]:
    flows = [cast(Flow, flow) for flow in _flows_by_ids(model, flow_ids)]
    node_budget = max(12, _slice_item_budget(token_budget))
    lines = ["flowchart TD", '  subgraph workflow_slice["workflow_slice"]', "    direction TB"]
    rendered_nodes: set[str] = set()
    flow_node_ids: dict[str, list[str]] = {}
    rendered_flow_ids: list[str] = []
    omitted_nodes = 0
    omitted_edges = 0
    edge_count = 0
    layout_constraint_count = 0

    if not flows:
        lines.append('    empty["No modeled flows selected for this workflow_slice"]')

    for flow in flows:
        flow_node_ids[flow.id] = []
        if len(rendered_nodes) >= node_budget:
            omitted_nodes += len(flow.nodes)
            continue
        rendered_flow_ids.append(flow.id)
        lines.append(
            f"    subgraph {_workflow_mermaid_id(f'flow:{flow.id}')}"
            f'["{_workflow_mermaid_label(flow.name)}"]'
        )
        lines.append("      direction TB")
        if not flow.nodes:
            summary_id = _workflow_mermaid_id(f"{flow.id}:summary")
            lines.append(f'      {summary_id}["{_workflow_mermaid_label(flow.name)}"]')
            flow_node_ids[flow.id].append(summary_id)
        for node in flow.nodes:
            if len(rendered_nodes) >= node_budget:
                omitted_nodes += 1
                continue
            node_id = _workflow_mermaid_id(node.id)
            lines.append(f"      {_workflow_mermaid_node(node, node_id)}")
            rendered_nodes.add(node.id)
            flow_node_ids[flow.id].append(node_id)
        for edge in flow.edges:
            if edge.source in rendered_nodes and edge.target in rendered_nodes:
                lines.append(f"      {_workflow_mermaid_edge(edge)}")
                edge_count += 1
            else:
                omitted_edges += 1
        lines.append("    end")

    flows_by_id = {flow.id: flow for flow in flows}
    for flow in flows:
        source_nodes = flow_node_ids.get(flow.id, [])
        if not source_nodes:
            continue
        for target_id in flow.calls:
            target = flows_by_id.get(target_id)
            target_nodes = flow_node_ids.get(target_id, [])
            if target is None or not target_nodes:
                omitted_edges += 1
                continue
            lines.append(
                f"  {source_nodes[-1]} -->"
                f'|"{_workflow_mermaid_label(f"calls {target.name}", 64)}"| {target_nodes[0]}'
            )
            edge_count += 1

    for previous_flow_id, next_flow_id in pairwise(rendered_flow_ids):
        previous_nodes = flow_node_ids.get(previous_flow_id, [])
        next_nodes = flow_node_ids.get(next_flow_id, [])
        if not previous_nodes or not next_nodes:
            continue
        lines.append(f"    {previous_nodes[-1]} ~~~ {next_nodes[0]}")
        layout_constraint_count += 1

    lines.append("  end")
    diagram = "\n".join(lines)
    return {
        "schema_version": "workflow_slice.canonical_visual.v1",
        "format": "mermaid",
        "diagram": diagram,
        "diagram_hash": hashlib.sha256(diagram.encode("utf-8")).hexdigest()[:16],
        "source": "logic-flow graph nodes and edges",
        "source_fields": [
            "primary_flows",
            "supporting_flows",
            "ordered_steps",
            "decisions",
            "source_ranges",
        ],
        "flow_ids": rendered_flow_ids,
        "node_count": len(rendered_nodes),
        "edge_count": edge_count,
        "layout": {
            "direction": "top_to_bottom",
            "flow_direction": "top_to_bottom",
            "flow_grouping": "vertical_parent_subgraph",
            "constraint_count": layout_constraint_count,
            "constraint_edge": "invisible_mermaid_link",
        },
        "omissions": {
            "node_budget": node_budget,
            "omitted_node_count": omitted_nodes,
            "omitted_edge_count": omitted_edges,
        },
        "guardrail": (
            "Render this diagram as-is when a text Mermaid fallback is needed. It is "
            "derived from deterministic graph nodes and edges; do not add inferred "
            "limits, error codes, branches, or service steps that are absent from the "
            "workflow_slice payload. Invisible Mermaid links are layout constraints only. "
            "Use a separate human-friendly view in the user's language if labels need "
            "translation."
        ),
    }


def _workflow_mermaid_node(node: FlowNode, node_id: str) -> str:
    label = _workflow_mermaid_label(node.label)
    if node.kind is NodeKind.DECISION:
        return f'{node_id}{{"{label}"}}'
    if node.kind is NodeKind.CALL:
        return f'{node_id}[["{label}"]]'
    if node.kind is NodeKind.ERROR:
        return f'{node_id}{{{{"{label}"}}}}'
    if node.kind in {NodeKind.ENTRY, NodeKind.TERMINAL}:
        return f'{node_id}(["{label}"])'
    return f'{node_id}["{label}"]'


def _workflow_mermaid_edge(edge: FlowEdge) -> str:
    source = _workflow_mermaid_id(edge.source)
    target = _workflow_mermaid_id(edge.target)
    label = f'|"{_workflow_mermaid_label(edge.label, 64)}"|' if edge.label else ""
    return f"{source} -->{label} {target}"


def _workflow_mermaid_id(value: str) -> str:
    return "m" + "".join(character if character.isalnum() else "_" for character in value)


def _workflow_mermaid_label(value: str, limit: int = 96) -> str:
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) > limit:
        normalized = normalized[: max(0, limit - 3)].rstrip() + "..."
    return (
        normalized.replace("&", "&amp;")
        .replace("\\", "\\\\")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "/")
    )


def _workflow_primary_flow_ids(pack: dict[str, Any]) -> list[str]:
    impact = pack.get("impact")
    direct = _list_dicts(impact.get("direct")) if isinstance(impact, dict) else []
    if direct:
        return _unique_preserve_order(str(item["id"]) for item in direct if item.get("id"))
    query = _list_dicts(pack.get("query"))
    return _unique_preserve_order(str(item["flow_id"]) for item in query if item.get("flow_id"))[:1]


def _workflow_selected_flow_ids(pack: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    impact = pack.get("impact")
    if isinstance(impact, dict):
        for key in ("direct", "transitive"):
            ids.extend(str(item["id"]) for item in _list_dicts(impact.get(key)) if item.get("id"))
        ids.extend(_string_list(impact.get("subgraph_flow_ids")))
    ids.extend(
        str(item["flow_id"]) for item in _list_dicts(pack.get("query")) if item.get("flow_id")
    )
    navigation = pack.get("navigation")
    if isinstance(navigation, dict):
        for item in _list_dicts(navigation.get("flows")):
            flow = item.get("flow")
            if isinstance(flow, dict) and flow.get("id"):
                ids.append(str(flow["id"]))
    return _unique_preserve_order(ids)


def _workflow_selection(
    pack: dict[str, Any],
    inputs: dict[str, Any],
    primary_flow_ids: list[str],
    supporting_flow_ids: list[str],
) -> dict[str, Any]:
    query = _list_dicts(pack.get("query"))
    reasons = []
    for item in query[:5]:
        reasons.append(
            {
                "flow_id": item.get("flow_id"),
                "score": item.get("score"),
                "reasons": item.get("reasons", []),
            }
        )
    return {
        "inputs": inputs,
        "query_filters": pack.get("query_filters", {}),
        "primary_flow_ids": primary_flow_ids,
        "supporting_flow_ids": supporting_flow_ids,
        "selection_reasons": reasons,
        "impact_reasons": (pack.get("impact") or {}).get("impact_reasons", {})
        if isinstance(pack.get("impact"), dict)
        else {},
    }


def _workflow_flow_rows(model: ProjectModel, flow_ids: list[str]) -> list[dict[str, Any]]:
    flows = {flow.id: flow for flow in model.flows}
    rows = []
    for flow_id in flow_ids:
        flow = flows.get(flow_id)
        if flow is None:
            continue
        rows.append(
            {
                **flow_summary(flow),
                "symbol": flow.symbol,
                "is_entrypoint": flow.is_entrypoint,
                "nodes": len(flow.nodes),
                "edges": len(flow.edges),
                "decisions": sum(node.kind is NodeKind.DECISION for node in flow.nodes),
                "calls": len(flow.calls),
                "callers": len(flow.called_by),
                "tests": list(flow.tests),
            }
        )
    return rows


def _workflow_ordered_steps(
    model: ProjectModel,
    flow_ids: list[str],
    token_budget: int,
) -> list[dict[str, Any]]:
    limit = _slice_item_budget(token_budget)
    steps: list[dict[str, Any]] = []
    for flow in _flows_by_ids(model, flow_ids):
        for index, node in enumerate(flow.nodes, start=1):
            steps.append(
                {
                    "flow_id": flow.id,
                    "flow": flow.name,
                    "step_index": index,
                    "node_id": node.id,
                    "kind": _enum_value(node.kind),
                    "label": node.label,
                    "source": _source_anchor(node.location),
                    "evidence": _enum_value(node.evidence),
                    **_node_decision_context(node),
                }
            )
            if len(steps) >= limit:
                return steps
    return steps


def _workflow_decisions(
    model: ProjectModel,
    flow_ids: list[str],
    token_budget: int,
) -> list[dict[str, Any]]:
    decisions: list[dict[str, Any]] = []
    for flow in _flows_by_ids(model, flow_ids):
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            decisions.append(
                {
                    "flow_id": flow.id,
                    "flow": flow.name,
                    "node_id": node.id,
                    "label": node.label,
                    "source": _source_anchor(node.location),
                    "evidence": _enum_value(node.evidence),
                    **_node_decision_context(node),
                }
            )
    return decisions[: _slice_item_budget(token_budget)]


def _workflow_calls(
    model: ProjectModel,
    flow_ids: list[str],
    token_budget: int,
) -> list[dict[str, Any]]:
    flows = {flow.id: flow for flow in model.flows}
    calls: list[dict[str, Any]] = []
    for flow in _flows_by_ids(model, flow_ids):
        for target_id in flow.calls:
            target = flows.get(target_id)
            calls.append(
                {
                    "source_flow_id": flow.id,
                    "source_flow": flow.name,
                    "target_flow_id": target_id,
                    "target_flow": target.name if target else None,
                    "resolved": target is not None,
                    "confidence": "resolved" if target else "unresolved",
                    "source": _source_anchor(flow.location),
                }
            )
        for caller_id in flow.called_by:
            caller = flows.get(caller_id)
            calls.append(
                {
                    "source_flow_id": caller_id,
                    "source_flow": caller.name if caller else None,
                    "target_flow_id": flow.id,
                    "target_flow": flow.name,
                    "resolved": caller is not None,
                    "confidence": "resolved" if caller else "unresolved",
                    "source": _source_anchor(caller.location if caller else flow.location),
                    "relationship": "caller",
                }
            )
    return calls[: _slice_item_budget(token_budget)]


def _workflow_domain_logic(
    domain_map_payload: dict[str, Any],
    flow_ids: list[str],
    token_budget: int,
) -> dict[str, Any]:
    concepts = _list_dicts(domain_map_payload.get("concepts"))
    selected = set(flow_ids)
    if selected:
        concepts = [
            concept
            for concept in concepts
            if selected.intersection(_string_list(concept.get("subgraph_flow_ids")))
        ]
    return {
        "concepts": concepts[: max(1, min(5, _slice_item_budget(token_budget)))],
        "omitted_concept_count": max(
            0, len(concepts) - max(1, min(5, _slice_item_budget(token_budget)))
        ),
        "source": "domain_map",
        "guardrail": domain_map_payload.get("guardrail"),
    }


def _workflow_source_ranges(
    model: ProjectModel,
    flow_ids: list[str],
    pack: dict[str, Any],
    token_budget: int,
) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()

    def add(location: Any, *, flow_id: str | None = None, node_id: str | None = None) -> None:
        if not hasattr(location, "path"):
            return
        key = (str(location.path), int(location.start_line), int(location.end_line))
        if key in seen:
            return
        seen.add(key)
        ranges.append(
            {
                "path": location.path,
                "start_line": location.start_line,
                "end_line": location.end_line,
                "flow_id": flow_id,
                "node_id": node_id,
            }
        )

    for flow in _flows_by_ids(model, flow_ids):
        add(flow.location, flow_id=flow.id)
        for node in flow.nodes:
            add(node.location, flow_id=flow.id, node_id=node.id)
    return ranges[: _slice_item_budget(token_budget)]


def _workflow_visuals(pack: dict[str, Any]) -> dict[str, Any]:
    visual = pack.get("visual_context")
    if not isinstance(visual, dict):
        return {"include_visual": False, "next_tools": {}}
    inline_keys = [
        key for key in ("impact_snapshot", "subgraph_snapshot", "flow_snapshots") if key in visual
    ]
    return {
        "include_visual": visual.get("include_visual", False),
        "inline_payloads": inline_keys,
        "format": visual.get("format", "svg"),
        "snapshot_budget": visual.get("snapshot_budget", {}),
        "next_tools": visual.get("next_tools", {}),
        "omitted_visual_snapshot_count": visual.get("omitted_visual_snapshot_count", 0),
        "omitted_visual_snapshot_reasons": visual.get("omitted_visual_snapshot_reasons", {}),
    }


def _workflow_viewer_targets(
    model: ProjectModel,
    flow_ids: list[str],
) -> dict[str, Any]:
    flow_targets = [
        {
            "type": "flow",
            "flow_id": flow.id,
            "name": flow.name,
            "hash_fragment": _viewer_flow_hash(flow.id),
            "source": _source_anchor(flow.location),
        }
        for flow in _flows_by_ids(model, flow_ids)
    ]
    return {
        "command": "logicchart view",
        "route": "flow-hash",
        "targets": flow_targets,
        "target_count": len(flow_targets),
        "guardrail": (
            "Use logicchart view for manual inspection, then append a hash_fragment to "
            "the generated viewer URL or local HTML file. These links open visual context; "
            "they do not replace the deterministic workflow_slice payload."
        ),
    }


def _viewer_flow_hash(flow_id: str) -> str:
    return f"#flow={quote(flow_id, safe='')}"


def _workflow_omissions(
    pack: dict[str, Any],
    selected_flow_ids: list[str],
    visible_flow_ids: list[str],
    token_budget: int,
) -> dict[str, Any]:
    navigation_value = pack.get("navigation")
    navigation: dict[str, Any] = navigation_value if isinstance(navigation_value, dict) else {}
    visual_value = pack.get("visual_context")
    visual: dict[str, Any] = visual_value if isinstance(visual_value, dict) else {}
    impact_value = pack.get("impact")
    impact: dict[str, Any] = impact_value if isinstance(impact_value, dict) else {}
    return {
        "token_budget": token_budget,
        "omitted_selected_flow_count": max(0, len(selected_flow_ids) - len(visible_flow_ids)),
        "omitted_flow_navigation_count": navigation.get("omitted_flow_navigation_count", 0),
        "omitted_flow_snapshot_count": visual.get("omitted_flow_snapshot_count", 0),
        "omitted_visual_snapshot_count": visual.get("omitted_visual_snapshot_count", 0),
        "unresolved_targets": impact.get("unresolved_targets", []),
    }


def _workflow_next_actions(
    primary_flow_ids: list[str],
    supporting_flow_ids: list[str],
) -> list[str]:
    actions = [
        "Use ordered_steps and source_ranges when answering the user.",
        "Use decision metadata and source anchors rather than inventing missing branches.",
    ]
    if supporting_flow_ids:
        actions.append("Inspect supporting_flows when caller/callee context changes the answer.")
    if primary_flow_ids:
        actions.append("Use snapshot_slice when visual flowchart context would clarify the answer.")
    return actions


def _workflow_slice_next_tools(
    primary_flow_ids: list[str],
    supporting_flow_ids: list[str],
    token_budget: int,
) -> dict[str, Any]:
    flow_ids = _unique_preserve_order([*primary_flow_ids, *supporting_flow_ids])
    tools: dict[str, Any] = {
        "expand_slice": {
            "tool": "expand_slice",
            "arguments": {
                "flow_ids": flow_ids,
                "direction": "neighbors",
                "depth": 1,
                "token_budget": token_budget,
            },
        },
        "snapshot_slice": {
            "tool": "snapshot_slice",
            "arguments": {
                "flow_ids": flow_ids,
                "format": "svg",
                "include_svg": True,
                "token_budget": token_budget,
            },
        },
    }
    if primary_flow_ids:
        tools["explain_primary_flow"] = {
            "tool": "explain_flow",
            "arguments": {"flow_id": primary_flow_ids[0], "token_budget": token_budget},
        }
    if len(flow_ids) >= 2:
        tools["workflow_path"] = {
            "tool": "workflow_path",
            "arguments": {
                "source": flow_ids[0],
                "target": flow_ids[-1],
                "token_budget": token_budget,
            },
        }
    return tools


def _workflow_task_type(question: str | None, inputs: dict[str, Any]) -> str:
    text = (question or "").lower()
    if inputs.get("changed_files"):
        return "change_impact"
    if inputs.get("domain") or inputs.get("value"):
        return "inspect_domain_logic"
    if any(term in text for term in ("impact", "break", "affected", "modifica", "rompe")):
        return "change_impact"
    if any(term in text for term in ("test", "coverage", "verifica")):
        return "prepare_tests"
    if any(term in text for term in ("where", "handled", "status", "state", "role")):
        return "inspect_state_handling"
    if any(term in text for term in ("path", "trace", "from", "to", "percorso")):
        return "trace_behavior"
    return "explain_behavior"


def _node_decision_context(node: Any) -> dict[str, Any]:
    if node.kind is not NodeKind.DECISION:
        return {}
    return {
        "condition": node.metadata.get("condition"),
        "domain": node.metadata.get("domain"),
        "subject": node.metadata.get("subject"),
        "operator": node.metadata.get("operator"),
        "values": node.metadata.get("values", []),
        "branches": node.metadata.get("branches", []),
    }


def _expand_workflow_slice_targets(
    model: ProjectModel,
    *,
    flow_ids: list[str] | None,
    direction: str,
    depth: int,
    token_budget: int,
) -> dict[str, Any]:
    normalized_direction = direction if direction in _slice_expansion_directions() else "neighbors"
    known_seed_flows = _known_flow_ids(model, flow_ids)
    known_seed_flows = _unique_preserve_order(known_seed_flows)
    unknown_flow_ids = [item for item in flow_ids or [] if item not in set(known_seed_flows)]
    if not known_seed_flows:
        return {
            "error_code": "slice_targets_missing",
            "message": "expand_slice requires at least one known flow_id.",
            "flow_ids": [],
            "unknown_flow_ids": unknown_flow_ids,
        }
    expanded = set(known_seed_flows)
    frontier = set(known_seed_flows)
    for _ in range(max(0, min(depth, 4))):
        next_frontier = set()
        for flow_id in frontier:
            next_frontier.update(_slice_neighbor_flow_ids(model, flow_id, normalized_direction))
        next_frontier.difference_update(expanded)
        expanded.update(next_frontier)
        frontier = next_frontier
        if not frontier:
            break
    budget = _slice_flow_budget(token_budget)
    ordered = _order_expanded_flow_ids(model, known_seed_flows, expanded)[:budget]
    return {
        "error_code": None,
        "message": None,
        "seed_flow_ids": known_seed_flows,
        "flow_ids": ordered,
        "direction": normalized_direction,
        "depth": max(0, min(depth, 4)),
        "unknown_flow_ids": unknown_flow_ids,
        "omitted_expanded_flow_count": max(0, len(expanded) - len(ordered)),
    }


def _slice_neighbor_flow_ids(model: ProjectModel, flow_id: str, direction: str) -> set[str]:
    flow = _flow_by_id(model, flow_id)
    if flow is None:
        return set()
    neighbors: set[str] = set()
    if direction in {"neighbors", "callees", "all"}:
        neighbors.update(flow.calls)
    if direction in {"neighbors", "callers", "all"}:
        neighbors.update(flow.called_by)
    if direction in {"neighbors", "tests", "all"}:
        neighbors.update(flow.tests)
    if direction in {"domain", "all"}:
        domains = _flow_domain_keys(flow)
        if domains:
            for candidate in model.flows:
                if candidate.id != flow.id and domains.intersection(_flow_domain_keys(candidate)):
                    neighbors.add(candidate.id)
    known = {item.id for item in model.flows}
    return {item for item in neighbors if item in known}


def _flow_domain_keys(flow: Any) -> set[str]:
    keys: set[str] = set()
    for node in getattr(flow, "nodes", []):
        if node.kind is NodeKind.DECISION:
            keys.update(_domain_keys(node.metadata))
    return keys


def _slice_expansion_directions() -> set[str]:
    return {"neighbors", "callers", "callees", "tests", "domain", "all"}


def _resolve_workflow_path_seed(
    model: ProjectModel,
    text: str,
    scope: str | None,
    token_budget: int,
) -> dict[str, Any]:
    normalized = text.strip()
    exact = _flow_by_id(model, normalized)
    if exact is not None and flow_in_agent_scope(exact, scope):
        return {
            "query": text,
            "flow_ids": [exact.id],
            "matches": [{**flow_summary(exact), "reason": "exact_flow_id"}],
        }
    exact_matches = [
        flow
        for flow in model.flows
        if flow_in_agent_scope(flow, scope)
        and (flow.symbol == normalized or flow.name == normalized)
    ]
    if exact_matches:
        return {
            "query": text,
            "flow_ids": [flow.id for flow in exact_matches[: _slice_flow_budget(token_budget)]],
            "matches": [
                {**flow_summary(flow), "reason": "exact_symbol_or_name"}
                for flow in exact_matches[: _slice_flow_budget(token_budget)]
            ],
        }
    matches = query_model(model, normalized, limit=5, scope=scope)
    rows = [match for match in matches if flow_in_agent_scope(match.flow, scope)]
    return {
        "query": text,
        "flow_ids": [match.flow.id for match in rows],
        "matches": [
            {
                **flow_summary(match.flow),
                "score": match.score,
                "reasons": match.reasons,
            }
            for match in rows
        ],
    }


def _find_workflow_path(
    model: ProjectModel,
    source_flow_ids: list[str],
    target_flow_ids: list[str],
) -> dict[str, Any]:
    targets = set(target_flow_ids)
    graph = _workflow_call_graph(model)
    queue: deque[tuple[str, list[str]]] = deque(
        (source_id, [source_id]) for source_id in source_flow_ids
    )
    visited = set(source_flow_ids)
    while queue:
        current, path = queue.popleft()
        if current in targets:
            return {
                "found": True,
                "flow_ids": path,
                "edges": _workflow_path_edges(model, path),
                "omitted_reason": None,
            }
        for neighbor in graph.get(current, []):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            queue.append((neighbor, [*path, neighbor]))
    return {
        "found": False,
        "flow_ids": [],
        "edges": [],
        "omitted_reason": "no_static_call_path_in_model",
    }


def _workflow_call_graph(model: ProjectModel) -> dict[str, list[str]]:
    graph: dict[str, set[str]] = {flow.id: set() for flow in model.flows}
    known = set(graph)
    for flow in model.flows:
        for target in flow.calls:
            if target in known:
                graph[flow.id].add(target)
                graph[target].add(flow.id)
        for caller in flow.called_by:
            if caller in known:
                graph[flow.id].add(caller)
                graph[caller].add(flow.id)
    return {key: sorted(value) for key, value in graph.items()}


def _workflow_path_edges(model: ProjectModel, path: list[str]) -> list[dict[str, Any]]:
    flows = {flow.id: flow for flow in model.flows}
    edges = []
    for source_id, target_id in pairwise(path):
        source = flows.get(source_id)
        target = flows.get(target_id)
        if source is None or target is None:
            continue
        direction = "calls" if target_id in source.calls else "called_by"
        edges.append(
            {
                "source_flow_id": source_id,
                "target_flow_id": target_id,
                "relationship": direction,
                "source": _source_anchor(source.location),
            }
        )
    return edges


def _workflow_path_error(
    source: str,
    target: str,
    source_seed: dict[str, Any],
    target_seed: dict[str, Any],
    token_budget: int,
) -> dict[str, Any]:
    return {
        "tool": "workflow_path",
        "error": "Could not resolve both workflow path endpoints.",
        "error_code": "workflow_path_endpoint_not_found",
        "source": source_seed,
        "target": target_seed,
        "recoverable": True,
        "guardrail": (
            "Endpoint resolution uses deterministic model query matches. Missing matches "
            "mean the current artifact lacks a modeled flow for the endpoint."
        ),
        "next_tools": {
            "query_source": {
                "tool": "query_logic",
                "arguments": {"question": source, "token_budget": token_budget},
            },
            "query_target": {
                "tool": "query_logic",
                "arguments": {"question": target, "token_budget": token_budget},
            },
        },
    }


def _focused_flow_explanation(model: ProjectModel, flow: Any, token_budget: int) -> dict[str, Any]:
    return {
        "tool": "explain_flow",
        "flow": _workflow_flow_rows(model, [flow.id])[0],
        "ordered_steps": _workflow_ordered_steps(model, [flow.id], token_budget),
        "decisions": _workflow_decisions(model, [flow.id], token_budget),
        "calls": _workflow_calls(model, [flow.id], token_budget),
        "source_ranges": _workflow_source_ranges(
            model,
            [flow.id],
            {},
            token_budget,
        ),
        "next_tools": {
            "snapshot_slice": {
                "tool": "snapshot_slice",
                "arguments": {
                    "flow_ids": [flow.id],
                    "format": "svg",
                    "include_svg": True,
                    "token_budget": token_budget,
                },
            },
            "expand_slice": {
                "tool": "expand_slice",
                "arguments": {"flow_ids": [flow.id], "direction": "neighbors"},
            },
        },
    }


def _focused_node_explanation(
    model: ProjectModel,
    flow: Any,
    node: Any,
    token_budget: int,
) -> dict[str, Any]:
    incoming = [edge for edge in flow.edges if edge.target == node.id]
    outgoing = [edge for edge in flow.edges if edge.source == node.id]
    return {
        "tool": "explain_node",
        "flow": flow_summary(flow),
        "node": {
            "id": node.id,
            "kind": _enum_value(node.kind),
            "label": node.label,
            "detail": node.detail,
            "source": _source_anchor(node.location),
            "evidence": _enum_value(node.evidence),
            "metadata": node.metadata,
        },
        "decision": _node_decision_context(node),
        "incoming_edges": [
            _edge_payload(edge) for edge in incoming[: _slice_item_budget(token_budget)]
        ],
        "outgoing_edges": [
            _edge_payload(edge) for edge in outgoing[: _slice_item_budget(token_budget)]
        ],
        "next_tools": {
            "explain_flow": {
                "tool": "explain_flow",
                "arguments": {"flow_id": flow.id, "token_budget": token_budget},
            },
            "snapshot_slice": {
                "tool": "snapshot_slice",
                "arguments": {
                    "flow_ids": [flow.id],
                    "format": "svg",
                    "include_svg": True,
                    "token_budget": token_budget,
                },
            },
        },
    }


def _focused_edge_explanation(
    model: ProjectModel,
    flow: Any,
    edge: Any,
    token_budget: int,
) -> dict[str, Any]:
    source_node = next((node for node in flow.nodes if node.id == edge.source), None)
    target_node = next((node for node in flow.nodes if node.id == edge.target), None)
    return {
        "tool": "explain_edge",
        "flow": flow_summary(flow),
        "edge": _edge_payload(edge),
        "source_node": _node_payload(source_node) if source_node is not None else None,
        "target_node": _node_payload(target_node) if target_node is not None else None,
        "source_ranges": [
            item
            for item in (
                _source_range_payload(source_node.location, flow.id, source_node.id)
                if source_node is not None
                else None,
                _source_range_payload(target_node.location, flow.id, target_node.id)
                if target_node is not None
                else None,
            )
            if item is not None
        ],
        "next_tools": {
            "explain_flow": {
                "tool": "explain_flow",
                "arguments": {"flow_id": flow.id, "token_budget": token_budget},
            },
            "snapshot_slice": {
                "tool": "snapshot_slice",
                "arguments": {
                    "flow_ids": [flow.id],
                    "format": "svg",
                    "include_svg": True,
                    "token_budget": token_budget,
                },
            },
        },
    }


def _slice_target_error(
    tool: str,
    error_code: str,
    message: str,
    *,
    slice_id: str | None,
    flow_ids: list[str] | None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "ok": False,
        "error": message,
        "error_code": error_code,
        "slice_id": slice_id,
        "flow_ids": flow_ids or [],
        "recoverable": True,
        "guardrail": (
            "Slice tools operate only on ids in the current local model. Re-run "
            "agent_context if the artifact changed or ids are unavailable."
        ),
        "next_tools": {
            "agent_context": {
                "tool": "agent_context",
                "arguments": {"token_budget": 900},
            },
            "list_flows": {
                "tool": "list_flows",
                "arguments": {"entrypoints_only": False, "token_budget": 900},
            },
        },
    }


def _known_flow_ids(model: ProjectModel, flow_ids: list[str] | None) -> list[str]:
    known = {flow.id for flow in model.flows}
    return _unique_preserve_order(flow_id for flow_id in flow_ids or [] if flow_id in known)


def _flows_by_ids(model: ProjectModel, flow_ids: list[str]) -> list[Any]:
    flows = {flow.id: flow for flow in model.flows}
    return [flows[flow_id] for flow_id in flow_ids if flow_id in flows]


def _flow_by_id(model: ProjectModel, flow_id: str) -> Any | None:
    return next((flow for flow in model.flows if flow.id == flow_id), None)


def _resolve_node(model: ProjectModel, node_id: str, flow_id: str | None) -> tuple[Any, Any] | None:
    flows = _flows_by_ids(model, [flow_id]) if flow_id else model.flows
    for flow in flows:
        for node in flow.nodes:
            if node.id == node_id:
                return flow, node
    return None


def _resolve_edge(model: ProjectModel, edge_id: str, flow_id: str | None) -> tuple[Any, Any] | None:
    flows = _flows_by_ids(model, [flow_id]) if flow_id else model.flows
    for flow in flows:
        for edge in flow.edges:
            if edge.id == edge_id:
                return flow, edge
    return None


def _order_expanded_flow_ids(
    model: ProjectModel,
    seed_flow_ids: list[str],
    expanded: set[str],
) -> list[str]:
    seed = _unique_preserve_order(seed_flow_ids)
    by_id = {flow.id: flow for flow in model.flows}
    rest = sorted(
        (flow_id for flow_id in expanded if flow_id not in set(seed)),
        key=lambda flow_id: (
            by_id[flow_id].location.path if flow_id in by_id else "",
            by_id[flow_id].name if flow_id in by_id else flow_id,
            flow_id,
        ),
    )
    return [*seed, *rest]


def _slice_primary_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 3
    return max(1, min(4, token_budget // 300))


def _slice_supporting_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 6
    return max(1, min(8, token_budget // 180))


def _slice_flow_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 20
    return max(1, min(24, token_budget // 80))


def _slice_item_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 40
    return max(4, min(40, token_budget // 40))


def _source_anchor(location: Any) -> dict[str, Any]:
    return {
        "path": location.path,
        "start_line": location.start_line,
        "end_line": location.end_line,
    }


def _source_range_payload(location: Any, flow_id: str, node_id: str) -> dict[str, Any]:
    return {
        **_source_anchor(location),
        "flow_id": flow_id,
        "node_id": node_id,
    }


def _node_payload(node: Any) -> dict[str, Any]:
    return {
        "id": node.id,
        "kind": _enum_value(node.kind),
        "label": node.label,
        "source": _source_anchor(node.location),
        "evidence": _enum_value(node.evidence),
    }


def _edge_payload(edge: Any) -> dict[str, Any]:
    return {
        "id": edge.id,
        "source": edge.source,
        "target": edge.target,
        "label": edge.label,
        "evidence": _enum_value(edge.evidence),
    }


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique_preserve_order(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value is None:
            continue
        item = str(value)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _context_visual_pack(
    model: ProjectModel,
    *,
    impact: Any,
    matches: list[Any],
    scope: str | None,
    include_visual: bool,
    token_budget: int,
    visual_byte_budget: int,
) -> dict[str, Any]:
    flow_candidates = _context_visual_flows(impact, matches)
    flow_limit = _context_visual_item_budget(token_budget)
    visual_byte_limit = max(0, visual_byte_budget)
    flow_tool_args = [
        {
            "tool": "get_flow_snapshot",
            "arguments": {
                "flow_id": flow.id,
                "format": "svg",
                "token_budget": token_budget,
            },
        }
        for flow in flow_candidates[:flow_limit]
    ]
    subgraph_flow_ids = [flow.id for flow in flow_candidates[:flow_limit]]
    impact_arguments: dict[str, Any] = {
        "changed_files": impact.changed_files,
        "format": "svg",
        "token_budget": token_budget,
    }
    if scope is not None:
        impact_arguments["scope"] = scope
    if impact.target_flow_ids:
        impact_arguments["flow_ids"] = impact.target_flow_ids
    if impact.target_symbols:
        impact_arguments["symbols"] = impact.target_symbols
    if impact.target_dependency_paths:
        impact_arguments["dependency_paths"] = impact.target_dependency_paths
    payload: dict[str, Any] = {
        "include_visual": include_visual,
        "format": "svg",
        "snapshot_budget": {
            "flow_snapshots": flow_limit,
            "node_budget": _snapshot_node_budget(token_budget),
            "flow_budget": _snapshot_flow_budget(token_budget),
            "visual_byte_budget": visual_byte_limit,
            "used_visual_bytes": 0,
        },
        "next_tools": {
            "impact_snapshot": {
                "tool": "get_impact_snapshot",
                "arguments": impact_arguments,
            },
            "flow_snapshots": flow_tool_args,
            "subgraph_snapshot": {
                "tool": "get_subgraph_snapshot",
                "arguments": {
                    "flow_ids": subgraph_flow_ids,
                    "format": "svg",
                    "token_budget": token_budget,
                },
            },
        },
        "omitted_flow_snapshot_count": max(0, len(flow_candidates) - flow_limit),
        "omitted_visual_snapshot_count": 0,
        "omitted_visual_snapshot_reasons": {},
    }
    if not include_visual:
        return payload
    used_visual_bytes = 0
    omitted_visual_reasons: dict[str, int] = {}

    def include_snapshot(snapshot: dict[str, Any]) -> bool:
        nonlocal used_visual_bytes
        size = _snapshot_svg_byte_size(snapshot)
        if used_visual_bytes + size > visual_byte_limit:
            omitted_visual_reasons["visual_byte_budget"] = (
                omitted_visual_reasons.get("visual_byte_budget", 0) + 1
            )
            return False
        used_visual_bytes += size
        return True

    impact_snapshot = render_impact_snapshot(
        changed_files=impact.changed_files,
        direct=impact.directly_impacted,
        transitive=impact.transitively_impacted,
        max_flows=_snapshot_flow_budget(token_budget),
        target_flow_ids=impact.target_flow_ids,
        target_symbols=impact.target_symbols,
        target_dependency_paths=impact.target_dependency_paths,
        unresolved_targets=impact.unresolved_targets,
        impact_reasons=impact.impact_reasons,
        subgraph_flow_ids=impact.subgraph_flow_ids,
    )
    if include_snapshot(impact_snapshot):
        payload["impact_snapshot"] = impact_snapshot
    else:
        payload["impact_snapshot_omitted_reason"] = "visual_byte_budget"

    if subgraph_flow_ids:
        subgraph_snapshot = render_subgraph_snapshot(
            model,
            flow_ids=subgraph_flow_ids,
            max_flows=_snapshot_flow_budget(token_budget),
            max_nodes=_snapshot_node_budget(token_budget),
        )
        if include_snapshot(subgraph_snapshot):
            payload["subgraph_snapshot"] = subgraph_snapshot
        else:
            payload["subgraph_snapshot_omitted_reason"] = "visual_byte_budget"

    flow_snapshots = []
    for flow in flow_candidates[:flow_limit]:
        snapshot = render_flow_snapshot(
            model, flow.id, max_nodes=_snapshot_node_budget(token_budget)
        )
        if include_snapshot(snapshot):
            flow_snapshots.append(snapshot)
        else:
            payload["omitted_flow_snapshot_count"] += 1
    payload["flow_snapshots"] = flow_snapshots
    payload["snapshot_budget"]["used_visual_bytes"] = used_visual_bytes
    payload["omitted_visual_snapshot_count"] = sum(omitted_visual_reasons.values())
    payload["omitted_visual_snapshot_reasons"] = omitted_visual_reasons
    return payload


def _context_visual_flows(impact: Any, matches: list[Any]) -> list[Any]:
    flows: dict[str, Any] = {}
    for flow in [*impact.directly_impacted, *impact.transitively_impacted]:
        flows.setdefault(flow.id, flow)
    for match in matches:
        flows.setdefault(match.flow.id, match.flow)
    return list(flows.values())


def _agent_order_matches(matches: list[Any], question: str | None) -> list[Any]:
    """Prefer application flows before tests in agent packs.

    Tests are valuable evidence, but when an LLM explains "how X works" it should start
    from implementation flows and use test flows as secondary confirmation.
    """
    action_terms = _agent_action_terms(question)
    return sorted(
        matches,
        key=lambda match: (
            bool(match.flow.metadata.get("test")),
            -_agent_action_hits(match, action_terms),
            -match.score,
            match.flow.name,
            match.flow.id,
        ),
    )


def _agent_action_hits(match: Any, action_terms: set[str]) -> int:
    if not action_terms:
        return 0
    reason_text = " ".join(str(reason) for reason in match.reasons)
    return sum(1 for term in action_terms if f"`{term}`" in reason_text)


def _agent_action_terms(question: str | None) -> set[str]:
    if not question:
        return set()
    action_vocab = {
        "approve",
        "auth",
        "authenticate",
        "authorize",
        "cancel",
        "checkout",
        "complete",
        "create",
        "delete",
        "download",
        "export",
        "import",
        "login",
        "pay",
        "process",
        "save",
        "send",
        "start",
        "submit",
        "update",
        "upload",
        "validate",
    }
    aliases = {
        "aggiorna": "update",
        "aggiornamento": "update",
        "autenticazione": "authenticate",
        "autorizzazione": "authorize",
        "cancella": "delete",
        "cancellazione": "delete",
        "carica": "upload",
        "caricamento": "upload",
        "crea": "create",
        "creazione": "create",
        "elimina": "delete",
        "esporta": "export",
        "esportazione": "export",
        "importa": "import",
        "importazione": "import",
        "invio": "send",
        "pagamento": "pay",
        "salva": "save",
        "salvataggio": "save",
        "validazione": "validate",
    }
    terms: set[str] = set()
    for token in re.findall(r"\w+", question.lower()):
        if token in action_vocab:
            terms.add(token)
        if token in aliases:
            terms.add(aliases[token])
    return terms


def _snapshot_svg_byte_size(snapshot: dict[str, Any]) -> int:
    svg = snapshot.get("svg", "")
    if not isinstance(svg, str):
        return 0
    return len(svg.encode("utf-8"))


def _write_snapshot_artifact(
    project_root: Path,
    snapshot: dict[str, Any],
    *,
    slice_id: str | None,
    flow_ids: list[str],
) -> dict[str, Any]:
    svg = snapshot.get("svg")
    if not isinstance(svg, str) or not svg.startswith("<svg"):
        return {
            "written": False,
            "reason": "snapshot_svg_unavailable",
        }
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()[:16]
    stem = _snapshot_artifact_stem(slice_id, flow_ids, digest)
    snapshot_dir = project_root / ".logicchart" / "snapshots"
    svg_path = snapshot_dir / f"{stem}.svg"
    html_path = snapshot_dir / f"{stem}.html"
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        svg_path.write_text(svg, encoding="utf-8")
        html_path.write_text(_snapshot_artifact_html(svg, stem), encoding="utf-8")
    except OSError as exc:
        return {
            "written": False,
            "reason": "write_failed",
            "error": str(exc),
        }
    relative_svg = svg_path.relative_to(project_root).as_posix()
    relative_html = html_path.relative_to(project_root).as_posix()
    return {
        "written": True,
        "schema_version": "snapshot_artifact.v1",
        "format": "svg",
        "digest": digest,
        "directory": str(snapshot_dir),
        "svg_path": str(svg_path),
        "html_path": str(html_path),
        "relative_svg_path": relative_svg,
        "relative_html_path": relative_html,
        "open_command": _open_file_command(html_path),
        "markdown_image": f"![LogicChart snapshot]({svg_path})",
        "guardrail": (
            "Use this local artifact when the chat client cannot render inline SVG or "
            "Mermaid. The file is generated under .logicchart/ and is local-only."
        ),
    }


def _snapshot_artifact_stem(
    slice_id: str | None,
    flow_ids: list[str],
    digest: str,
) -> str:
    label = slice_id or "-".join(flow_ids[:2]) or "slice"
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label).strip(".-")
    if not safe:
        safe = "slice"
    return f"snapshot-{safe[:64]}-{digest}"


def _snapshot_artifact_html(svg: str, title: str) -> str:
    escaped_title = html.escape(title)
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            "  <title>LogicChart snapshot</title>",
            "  <style>",
            "    body { margin: 0; background: #101216; color: #f5f7fb; font-family: "
            "Inter, ui-sans-serif, system-ui, sans-serif; }",
            "    header { padding: 12px 16px; border-bottom: 1px solid #2b3038; }",
            "    main { padding: 16px; overflow: auto; }",
            "    svg { max-width: none; height: auto; background: #151820; }",
            "  </style>",
            "</head>",
            "<body>",
            f"  <header>LogicChart snapshot: {escaped_title}</header>",
            "  <main>",
            svg,
            "  </main>",
            "</body>",
            "</html>",
        ]
    )


def _open_file_command(path: Path) -> str:
    quoted = shlex.quote(str(path))
    if sys.platform == "darwin":
        return f"open {quoted}"
    if sys.platform.startswith("win"):
        return f"start {quoted}"
    return f"xdg-open {quoted}"


def _single_item_list(value: str | None) -> list[str] | None:
    if value is None or not value.strip():
        return None
    return [value.strip()]


def _agent_scope_filter(model: ProjectModel, scope: str | None) -> tuple[str | None, str | None]:
    """Resolve agent-provided scope into (strict_scope_filter, free_text_query_hint).

    Coding agents often pass natural language such as "certificate upload" in ``scope``.
    LogicChart scopes are configured macro-parts like "frontend" or "backend"; unknown
    scope text should help ranking, not filter every flow out.
    """
    if scope is None or not scope.strip():
        return None, None
    normalized = scope.strip()
    if normalized in _known_scope_names(model):
        return normalized, None
    return None, normalized


def _known_scope_names(model: ProjectModel) -> set[str]:
    names: set[str] = set()
    scopes = model.metadata.get("scopes", {})
    if isinstance(scopes, Mapping):
        names.update(str(name) for name in scopes)
    for flow in model.flows:
        names.update(metadata_scope_names(flow.metadata))
    return names


def _question_with_scope_hint(question: str | None, scope_query_hint: str | None) -> str | None:
    if scope_query_hint is None:
        return question
    if question and question.strip():
        return f"{question.strip()} {scope_query_hint}"
    return scope_query_hint


def _selected_code_excerpt(selected_code: str | None, limit: int = 1200) -> str | None:
    if selected_code is None:
        return None
    stripped = selected_code.strip()
    if not stripped:
        return None
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def _agent_context_question(question: str | None, selected_code: str | None) -> str | None:
    if question and question.strip():
        return question.strip()
    excerpt = _selected_code_excerpt(selected_code, limit=400)
    if excerpt:
        return f"selected code: {excerpt}"
    return question


def _agent_context_next_tools(pack: dict[str, Any], token_budget: int) -> dict[str, Any]:
    visual_context = pack.get("visual_context")
    visual_tools = visual_context.get("next_tools", {}) if isinstance(visual_context, dict) else {}
    next_tools: dict[str, Any] = {
        "validate_artifacts": {
            "tool": "validate_artifacts",
            "arguments": {"check_sync": True, "include_quality": True},
        },
    }
    if visual_tools:
        next_tools["visual_context"] = visual_tools
    impact = pack.get("impact")
    if isinstance(impact, dict):
        flow_ids = _string_list(impact.get("subgraph_flow_ids"))
        if flow_ids:
            next_tools["subgraph_snapshot"] = {
                "tool": "get_subgraph_snapshot",
                "arguments": {
                    "flow_ids": flow_ids,
                    "format": "svg",
                    "token_budget": token_budget,
                },
            }
    return next_tools


def _domain_logic_map(
    model: ProjectModel,
    *,
    domain: str | None,
    value: str | None,
    scope: str | None,
    token_budget: int,
) -> dict[str, Any]:
    normalized_domain = domain.strip() if domain and domain.strip() else None
    normalized_value = value.strip() if value and value.strip() else None
    concepts: dict[str, dict[str, Any]] = {}

    for flow in model.flows:
        if not flow_in_agent_scope(flow, scope):
            continue
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            keys = _domain_keys(node.metadata)
            if normalized_domain is not None:
                keys = [key for key in keys if key == normalized_domain]
            if not keys:
                continue
            values = _metadata_string_values(node.metadata.get("values"))
            for key in keys:
                concept = concepts.setdefault(key, _empty_domain_concept(key))
                concept["subjects"].update(_metadata_string_values(node.metadata.get("subject")))
                concept["value_namespaces"].update(
                    _metadata_string_values(node.metadata.get("value_namespace"))
                )
                concept["handled_values"].update(values)
                concept["flow_ids"].add(flow.id)
                concept["node_ids"].add(node.id)
                concept["decision_nodes"].append(
                    {
                        "flow_id": flow.id,
                        "flow": flow.name,
                        "node_id": node.id,
                        "subject": node.metadata.get("subject"),
                        "value_namespace": node.metadata.get("value_namespace"),
                        "values": values,
                        "source": f"{node.location.path}:{node.location.start_line}",
                        "source_range": _source_anchor(node.location),
                    }
                )

    if normalized_value is not None:
        concepts = {
            key: concept
            for key, concept in concepts.items()
            if _metadata_value_matches(normalized_value, concept["handled_values"])
        }
    concept_rows = [_domain_concept_payload(item, token_budget) for item in concepts.values()]
    concept_rows.sort(
        key=lambda item: (
            -item["decision_count"],
            item["domain"],
        )
    )
    if token_budget > 0:
        concept_limit = max(1, token_budget // 300)
        omitted = max(0, len(concept_rows) - concept_limit)
        concept_rows = concept_rows[:concept_limit]
    else:
        omitted = 0
    return {
        "tool": "domain_map",
        "guardrail": (
            "Domain maps are deterministic summaries of decision metadata. They show "
            "where values and state-like concepts are handled in modeled flows; they "
            "do not infer missing cases or defects."
        ),
        "filters": {
            "domain": normalized_domain,
            "value": normalized_value,
            "scope": scope,
            "token_budget": token_budget,
        },
        "concepts": concept_rows,
        "omitted_concept_count": omitted,
        "next_tools": {
            "agent_context": {
                "tool": "agent_context",
                "arguments": {
                    "domain": normalized_domain,
                    "value": normalized_value,
                    "scope": scope,
                    "token_budget": token_budget,
                },
            },
            "find_decision_nodes": {
                "tool": "find_decision_nodes",
                "arguments": {"domain": normalized_domain, "token_budget": token_budget},
            },
        },
    }


def _empty_domain_concept(domain: str) -> dict[str, Any]:
    return {
        "domain": domain,
        "subjects": set(),
        "value_namespaces": set(),
        "handled_values": set(),
        "flow_ids": set(),
        "node_ids": set(),
        "decision_nodes": [],
    }


def _domain_concept_payload(concept: dict[str, Any], token_budget: int) -> dict[str, Any]:
    per_section_limit = max(1, token_budget // 240) if token_budget > 0 else 20
    flow_ids = sorted(concept["flow_ids"])
    visible_flow_ids = flow_ids[:per_section_limit] if token_budget > 0 else flow_ids
    return {
        "domain": concept["domain"],
        "subjects": sorted(concept["subjects"]),
        "value_namespaces": sorted(concept["value_namespaces"]),
        "handled_values": sorted(concept["handled_values"]),
        "decision_count": len(concept["decision_nodes"]),
        "flow_count": len(concept["flow_ids"]),
        "decision_nodes": concept["decision_nodes"][:per_section_limit],
        "omitted_decision_count": max(0, len(concept["decision_nodes"]) - per_section_limit),
        "omitted_subgraph_flow_count": max(0, len(flow_ids) - len(visible_flow_ids)),
        "subgraph_flow_ids": visible_flow_ids,
        "next_tools": {
            "context_pack": {
                "tool": "context_pack",
                "arguments": {"domain": concept["domain"]},
            },
            "subgraph_snapshot": {
                "tool": "get_subgraph_snapshot",
                "arguments": {
                    "flow_ids": visible_flow_ids,
                    "format": "svg",
                },
            },
        },
    }


def _domain_keys(metadata: dict[str, Any]) -> list[str]:
    keys = [
        *_metadata_string_values(metadata.get("domain")),
        *_metadata_string_values(metadata.get("value_namespace")),
    ]
    return list(dict.fromkeys(key for key in keys if key))


def _metadata_string_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _metadata_value_matches(target: str, values: Iterable[str]) -> bool:
    normalized_target = _normalized_domain_value(target)
    for value in values:
        normalized_value = _normalized_domain_value(value)
        if normalized_value == normalized_target:
            return True
        suffix = str(value).rsplit(".", maxsplit=1)[-1]
        if _normalized_domain_value(suffix) == normalized_target:
            return True
    return False


def _normalized_domain_value(value: str) -> str:
    return value.strip().strip("\"'").lower()


def _context_navigation_pack(
    model: ProjectModel,
    *,
    impact: Any,
    matches: list[Any],
    annotations: dict[str, Any] | None,
    token_budget: int,
) -> dict[str, Any]:
    flow_candidates = _context_visual_flows(impact, matches)
    flow_limit = _context_navigation_item_budget(token_budget)
    per_flow_budget = _context_navigation_token_budget(token_budget, flow_limit)
    selected = flow_candidates[:flow_limit]
    return {
        "flow_budget": flow_limit,
        "per_flow_token_budget": per_flow_budget,
        "flows": [
            flow_navigation(model, flow.id, per_flow_budget, annotations) for flow in selected
        ],
        "next_tools": {
            "flow_navigation": [
                {
                    "tool": "get_flow_navigation",
                    "arguments": {
                        "flow_id": flow.id,
                        "token_budget": per_flow_budget,
                    },
                }
                for flow in selected
            ]
        },
        "omitted_flow_navigation_count": max(0, len(flow_candidates) - flow_limit),
    }


def _context_navigation_item_budget(token_budget: int) -> int:
    return _context_item_budget(token_budget)


def _context_navigation_token_budget(token_budget: int, flow_limit: int) -> int:
    if token_budget <= 0:
        return 0
    return max(60, token_budget // max(1, flow_limit))


def _context_visual_item_budget(token_budget: int) -> int:
    return _context_item_budget(token_budget)


def _context_item_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 2
    return max(1, min(3, token_budget // 300))


def _enrichment_options(
    *,
    scope: str | None,
    flow_ids: list[str] | None,
    max_flows: int,
    max_nodes_per_flow: int,
    token_budget: int,
) -> AnnotationPreviewOptions:
    flow_limit = max(0, max_flows)
    node_limit = max(0, max_nodes_per_flow)
    if token_budget > 0:
        flow_limit = min(flow_limit, max(1, token_budget // 240))
        node_limit = min(node_limit, max(4, token_budget // 100))
    return AnnotationPreviewOptions(
        scope=scope,
        flow_ids=tuple(flow_ids or ()),
        max_flows=flow_limit,
        max_nodes_per_flow=node_limit,
    )


def _enrichment_preview_payload(
    preview: dict[str, Any],
    *,
    token_budget: int,
) -> dict[str, Any]:
    targets = preview.get("targets", {})
    selected_flow_ids = _string_list(targets.get("flow_ids"))
    next_tools: dict[str, Any] = {}
    if selected_flow_ids:
        next_tools["subgraph_snapshot"] = {
            "tool": "get_subgraph_snapshot",
            "arguments": {
                "flow_ids": selected_flow_ids,
                "format": "svg",
                "token_budget": token_budget,
            },
        }
    if selected_flow_ids:
        next_tools["flow_navigation"] = [
            {
                "tool": "get_flow_navigation",
                "arguments": {"flow_id": flow_id, "token_budget": token_budget},
            }
            for flow_id in selected_flow_ids[:3]
        ]
    return {
        **preview,
        "guardrail": (
            "This MCP tool is local preview only and never calls a provider. Use the "
            "selected ids as candidate targets for agent-authored annotations, keeping "
            "generated text separate from deterministic facts."
        ),
        "next_tools": next_tools,
        "next_actions": [
            "Inspect selected flow and node ids before writing annotations.",
            "Use generated text only as agent_generated annotation content.",
            "Run logicchart validate after annotation sidecar changes.",
        ],
    }


def _annotation_allowed_fields() -> dict[str, list[str]]:
    return {
        "flows": ["label", "description", "summary"],
        "nodes": ["label", "description"],
        "scopes": ["label", "description", "summary"],
    }


def _annotation_status_payload(
    root: Path,
    model: ProjectModel,
    config: LogicChartConfig,
    include_annotations: bool,
) -> dict[str, Any]:
    loaded = load_annotations(root, model, config)
    payload = {
        "tool": "annotation_status",
        "guardrail": (
            "Annotations are optional agent-generated presentation text. They do not "
            "change deterministic flows, decisions, calls, source anchors, or validation facts."
        ),
        **loaded.to_dict(),
        "schema_version": ANNOTATIONS_SCHEMA_VERSION,
        "allowed_fields": _annotation_allowed_fields(),
        "next_tools": {
            "preview_annotation_targets": {
                "tool": "preview_annotation_targets",
                "arguments": {},
            },
            "write_annotations": {
                "tool": "write_annotations",
                "arguments": {"replace_existing": False},
            },
        },
    }
    if include_annotations and loaded.annotations is not None:
        payload["annotations"] = loaded.annotations
    return payload


def _write_annotations_payload(
    root: Path,
    model: ProjectModel,
    config: LogicChartConfig,
    *,
    annotations: dict[str, Any] | None,
    flows: dict[str, dict[str, str]] | None,
    nodes: dict[str, dict[str, str]] | None,
    scopes: dict[str, dict[str, str]] | None,
    generated_by: dict[str, Any] | None,
    replace_existing: bool,
) -> dict[str, Any]:
    bucket_inputs: dict[str, dict[str, dict[str, str]] | None] = {
        "flows": flows,
        "nodes": nodes,
        "scopes": scopes,
    }
    has_bucket_inputs = any(value is not None for value in bucket_inputs.values())
    if annotations is not None and has_bucket_inputs:
        return _annotation_write_error(
            root,
            model,
            config,
            "annotation_write_ambiguous_payload",
            "Use either a full annotations object or bucket arguments, not both.",
        )

    loaded = load_annotations(root, model, config)
    if loaded.status != "absent" and not loaded.ok and not replace_existing:
        return _annotation_write_error(
            root,
            model,
            config,
            "annotation_existing_sidecar_invalid",
            (
                "Existing annotations are invalid or stale; pass replace_existing=true "
                "to replace them."
            ),
            errors=loaded.errors,
            status=loaded.to_dict(),
        )

    candidate = _annotation_candidate_payload(
        model,
        loaded.annotations if loaded.ok else None,
        annotations=annotations,
        bucket_inputs=bucket_inputs,
        generated_by=generated_by,
        replace_existing=replace_existing,
    )
    provenance_errors = _validate_annotation_write_provenance(candidate)
    if provenance_errors:
        return _annotation_write_error(
            root,
            model,
            config,
            "annotation_provenance_invalid",
            "MCP annotation writes must use agent_generated provenance.",
            errors=provenance_errors,
        )
    path = annotations_path(root, config)
    result = AnnotationLoadResult(path=str(path), expected_model_hash=model_hash(model))
    normalized = validate_annotations_payload(candidate, model, result)
    if normalized is None or not result.ok:
        return _annotation_write_error(
            root,
            model,
            config,
            "annotation_validation_failed",
            "Annotation payload did not validate against the current model.",
            errors=result.errors,
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    status = _annotation_status_payload(root, model, config, include_annotations=False)
    status["tool"] = "write_annotations"
    status["written"] = True
    status["replace_existing"] = replace_existing
    return status


def _annotation_candidate_payload(
    model: ProjectModel,
    existing: dict[str, Any] | None,
    *,
    annotations: dict[str, Any] | None,
    bucket_inputs: dict[str, dict[str, dict[str, str]] | None],
    generated_by: dict[str, Any] | None,
    replace_existing: bool,
) -> dict[str, Any]:
    if annotations is not None:
        candidate = dict(annotations)
    else:
        candidate = {
            bucket: dict((existing or {}).get(bucket, {}))
            for bucket in ("flows", "nodes", "scopes")
        }
        if replace_existing:
            candidate = {bucket: {} for bucket in ("flows", "nodes", "scopes")}
        for bucket, entries in bucket_inputs.items():
            if entries is not None:
                bucket_payload = candidate.setdefault(bucket, {})
                if not isinstance(bucket_payload, dict):
                    candidate[bucket] = entries
                    continue
                for target_id, fields in entries.items():
                    existing_fields = bucket_payload.get(target_id, {})
                    if isinstance(existing_fields, dict):
                        merged_fields = dict(existing_fields)
                        merged_fields.update(fields)
                        bucket_payload[target_id] = merged_fields
                    else:
                        bucket_payload[target_id] = fields

    candidate["schema_version"] = ANNOTATIONS_SCHEMA_VERSION
    candidate["model_hash"] = model_hash(model)
    if generated_by is not None:
        candidate["generated_by"] = generated_by
    elif "generated_by" not in candidate:
        candidate["generated_by"] = {
            "kind": "agent_generated",
            "logicchart_workflow": "agent_authored_annotations",
            "tool": "write_annotations",
        }
    return candidate


def _validate_annotation_write_provenance(candidate: dict[str, Any]) -> list[str]:
    generated_by = candidate.get("generated_by")
    if not isinstance(generated_by, dict):
        return ["generated_by must be an object with kind='agent_generated'."]
    if generated_by.get("kind") != "agent_generated":
        return ["generated_by.kind must be 'agent_generated' for write_annotations."]
    return []


def _annotation_write_error(
    root: Path,
    model: ProjectModel,
    config: LogicChartConfig,
    error_code: str,
    message: str,
    *,
    errors: list[str] | None = None,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "ok": False,
        "error": message,
        "error_code": error_code,
        "path": str(annotations_path(root, config)),
        "expected_model_hash": model_hash(model),
        "guardrail": (
            "Rejecting annotation writes protects deterministic LogicChart facts from "
            "unknown ids, stale models, oversized text, or malformed generated content."
        ),
        "errors": errors or [],
        "next_tools": {
            "preview_annotation_targets": {
                "tool": "preview_annotation_targets",
                "arguments": {},
            },
            "annotation_status": {
                "tool": "annotation_status",
                "arguments": {"include_annotations": False},
            },
        },
    }
    if status is not None:
        payload["status"] = status
    return payload


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _quality_report(quality: dict[str, Any], token_budget: int) -> dict[str, Any]:
    return {
        "quality": _bounded_quality(quality, token_budget),
        "attention": _quality_attention_items(quality, token_budget),
        "guardrail": (
            "Quality attention signals identify analyzer limits such as skipped files, "
            "parse warnings, unresolved calls, generic labels, or dense graphs. They "
            "describe model coverage, not application defects."
        ),
        "next_tools": {
            "validate_quality": {
                "tool": "validate_artifacts",
                "arguments": {"include_quality": True},
            },
        },
    }


def _bounded_quality(quality: dict[str, Any], token_budget: int) -> dict[str, Any]:
    if token_budget <= 0:
        return quality
    item_limit = _quality_item_budget(token_budget)
    bounded = dict(quality)

    languages = quality.get("languages")
    if isinstance(languages, dict):
        attention = _list_dicts(languages.get("attention"))[:item_limit]
        depth = languages.get("depth")
        depth_rows = depth if isinstance(depth, dict) else {}
        attention_order = [str(item.get("language", "")) for item in attention]
        ordered_languages = [
            *[language for language in attention_order if language in depth_rows],
            *sorted(language for language in depth_rows if language not in attention_order),
        ][:item_limit]
        bounded["languages"] = {
            "attention": attention,
            "depth": {language: depth_rows[language] for language in ordered_languages},
            "omitted_language_count": max(0, len(depth_rows) - len(ordered_languages)),
        }

    files = quality.get("files")
    if isinstance(files, dict):
        bounded_files = dict(files)
        skipped = files.get("skipped")
        if isinstance(skipped, dict):
            bounded_files["skipped"] = {
                **skipped,
                "sample": _list_dicts(skipped.get("sample"))[:item_limit],
            }
        parse_errors = files.get("parse_errors")
        if isinstance(parse_errors, dict):
            bounded_files["parse_errors"] = {
                **parse_errors,
                "sample": _list_dicts(parse_errors.get("sample"))[:item_limit],
            }
        bounded["files"] = bounded_files

    flows = quality.get("flows")
    if isinstance(flows, dict):
        bounded["flows"] = {**flows, "huge": _list_dicts(flows.get("huge"))[:item_limit]}

    labels = quality.get("labels")
    if isinstance(labels, dict):
        bounded["labels"] = {
            **labels,
            "sample": _list_dicts(labels.get("sample"))[:item_limit],
        }

    return bounded


def _quality_attention_items(quality: dict[str, Any], token_budget: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    files = quality.get("files")
    calls = quality.get("calls")
    labels = quality.get("labels")
    graph = quality.get("graph")
    languages = quality.get("languages")

    skipped = files.get("skipped") if isinstance(files, dict) else None
    skipped_total = skipped.get("total", 0) if isinstance(skipped, dict) else 0
    if skipped_total:
        items.append(
            {
                "type": "skipped_files",
                "signals": ["skipped_files"],
                "count": skipped_total,
                "next_tools": {
                    "validate_quality": {
                        "tool": "validate_artifacts",
                        "arguments": {"include_quality": True},
                    }
                },
            }
        )

    parse_errors = files.get("parse_errors") if isinstance(files, dict) else None
    parse_error_total = parse_errors.get("total", 0) if isinstance(parse_errors, dict) else 0
    if parse_error_total:
        items.append(
            {
                "type": "parse_warnings",
                "signals": ["parse_errors"],
                "count": parse_error_total,
                "next_tools": {
                    "validate_parse_warnings": {
                        "tool": "validate_artifacts",
                        "arguments": {"include_quality": True, "max_parse_warnings": 0},
                    }
                },
            }
        )

    if isinstance(calls, dict) and (calls.get("unresolved", 0) or calls.get("ambiguous", 0)):
        items.append(
            {
                "type": "call_resolution",
                "signals": ["unresolved_calls", "ambiguous_calls"],
                "resolution_rate": calls.get("resolution_rate", 0),
                "next_tools": {
                    "query_calls": {
                        "tool": "query_logic",
                        "arguments": {"question": "unresolved calls", "token_budget": token_budget},
                    }
                },
            }
        )

    if isinstance(labels, dict) and labels.get("generic_nodes", 0):
        items.append(
            {
                "type": "generic_labels",
                "signals": ["generic_labels"],
                "generic_ratio": labels.get("generic_ratio", 0),
                "next_tools": {
                    "query_generic_labels": {
                        "tool": "query_logic",
                        "arguments": {"question": "generic labels", "token_budget": token_budget},
                    }
                },
            }
        )

    if isinstance(graph, dict) and graph.get("dense_graph_warning"):
        items.append(
            {
                "type": "graph_density",
                "signals": ["dense_graph"],
                "edge_to_node_ratio": graph.get("edge_to_node_ratio", 0),
            }
        )

    if isinstance(languages, dict):
        for item in _list_dicts(languages.get("attention")):
            language = str(item.get("language", ""))
            items.append(
                {
                    "type": "language",
                    "language": language,
                    "signals": item.get("signals", []),
                    "next_tools": {
                        "query_language": {
                            "tool": "query_logic",
                            "arguments": {
                                "question": language,
                                "language": language,
                                "token_budget": token_budget,
                            },
                        }
                    },
                }
            )

    return _cap(items, token_budget)


def _validation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    next_tools: dict[str, dict[str, Any]] = {
        "analysis_quality": {
            "tool": "analysis_quality",
            "arguments": {"token_budget": 600},
        },
    }
    if not payload.get("ok"):
        next_tools = {
            "update_model": {
                "tool": "update_logicchart",
                "arguments": {"full": True},
            },
            **next_tools,
        }
    return {
        **payload,
        "guardrail": (
            "Artifact validation checks generated model freshness, schema, annotations, "
            "and optional analyzer-quality thresholds."
        ),
        "next_tools": next_tools,
        "next_cli": _validation_next_cli(bool(payload.get("ok"))),
    }


def _validation_next_cli(ok: bool) -> list[str]:
    if ok:
        return [
            "logicchart validate --quality --json",
            "logicchart view",
        ]
    return [
        "logicchart update --full",
        "logicchart validate --check-sync --json",
    ]


def _update_workflow_payload(
    json_path: Path,
    markdown_path: Path,
    html_path: Path | None,
) -> dict[str, Any]:
    return {
        "guardrail": (
            "The model has been regenerated from local source files. Validate sync and "
            "quality before relying on MCP context or committing generated artifacts."
        ),
        "next_tools": {
            "validate_artifacts": {
                "tool": "validate_artifacts",
                "arguments": {"check_sync": True, "include_quality": True},
            },
            "analysis_quality": {
                "tool": "analysis_quality",
                "arguments": {"token_budget": 600},
            },
        },
        "next_artifacts": {
            "commit": [str(json_path), str(markdown_path)],
            "local_html": str(html_path) if html_path else None,
        },
        "next_cli": [
            "logicchart validate --check-sync --json",
            "logicchart validate --quality",
        ],
    }


def _list_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _quality_item_budget(token_budget: int) -> int:
    return max(1, min(8, token_budget // 120))


def _unknown_target_error(target_type: str, target_id: str) -> dict[str, Any]:
    next_tools: dict[str, dict[str, Any]] = {
        "list_flows": {
            "tool": "list_flows",
            "arguments": {"entrypoints_only": False, "token_budget": 600},
        },
        "query_logic": {
            "tool": "query_logic",
            "arguments": {"question": target_id, "token_budget": 600},
        },
    }
    return {
        "error": f"Unknown {target_type}: {target_id}",
        "error_code": f"{target_type}_not_found",
        "target_type": target_type,
        "target_id": target_id,
        "recoverable": True,
        "guardrail": (
            "This reports an invalid MCP target from the generated model. Re-run "
            "query_logic or list_flows to resolve a current flow/node handle."
        ),
        "next_tools": next_tools,
    }


def _try_load(
    project_root: Path,
    config: LogicChartConfig,
) -> tuple[ProjectModel | None, dict[str, Any] | None]:
    """Load the model, or return a clean error dict the tool can hand back.

    Every MCP tool reads the persisted model first; without this a missing or corrupt
    model would propagate a raw traceback to the calling agent.
    """
    try:
        return load_model(project_root, config), None
    except _LOAD_ERRORS as error:
        return None, _model_load_error(project_root, config, error)


def _model_load_error(
    project_root: Path,
    config: LogicChartConfig,
    error: BaseException,
) -> dict[str, Any]:
    json_path, markdown_path, html_path = output_paths(project_root, config)
    return {
        "error": "Could not load the LogicChart model.",
        "error_code": _model_load_error_code(error),
        "detail": str(error),
        "artifact": str(json_path),
        "related_artifacts": {
            "markdown": str(markdown_path),
            "html": str(html_path),
        },
        "recoverable": True,
        "guardrail": (
            "This reports missing or invalid generated artifacts. Run update_logicchart "
            "and validate_artifacts before relying on MCP context."
        ),
        "next_tools": {
            "update_model": {
                "tool": "update_logicchart",
                "arguments": {"full": True},
            },
            "validate_artifacts": {
                "tool": "validate_artifacts",
                "arguments": {"check_sync": True, "include_quality": True},
            },
        },
        "next_cli": [
            "logicchart update --full",
            "logicchart validate --check-sync --json",
        ],
    }


def _model_load_error_code(error: BaseException) -> str:
    if isinstance(error, FileNotFoundError):
        return "artifact_missing"
    if isinstance(error, PermissionError):
        return "artifact_unreadable"
    if isinstance(error, OSError):
        return "artifact_unreadable"
    detail = str(error)
    if isinstance(error, ValueError) and "invalid JSON" in detail:
        return "artifact_malformed_json"
    return "artifact_invalid"


def flow_in_agent_scope(flow: Any, scope: str | None) -> bool:
    return scope is None or scope in metadata_scope_names(flow.metadata)
