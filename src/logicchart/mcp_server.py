from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from shlex import quote
from typing import Any

from logicchart.analysis import ProjectAnalyzer
from logicchart.annotations import load_annotations
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.diagnostics import diagnostic_for_finding, finding_rule_contracts
from logicchart.llm_enrich import EnrichmentOptions, build_enrichment_preview
from logicchart.model import ProjectModel
from logicchart.quality import model_quality
from logicchart.query import (
    explain_finding,
    find_decisions,
    finding_context,
    flow_navigation,
    git_changed_files,
    impact_model,
    model_summary,
    query_model,
    where_is_state_handled,
)
from logicchart.render.snapshot import (
    SNAPSHOT_FORMATS,
    render_finding_snapshot,
    render_flow_snapshot,
    render_impact_snapshot,
    render_subgraph_snapshot,
    unsupported_snapshot_format,
)
from logicchart.validation import validate_logicchart

# Rough tokens per returned list item, used to honor an agent's token_budget cap.
_TOKENS_PER_ITEM = 60
_DEFAULT_CONTEXT_VISUAL_BYTE_BUDGET = 120_000

# Errors raised while loading the on-disk model (missing file, corrupt/garbled JSON,
# unexpected schema). Surfaced to the agent as a clean {"error": ...} instead of a raw
# traceback, so a stale or never-built model is recoverable advice, not a crash.
_LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError)

MCP_INSTRUCTIONS = """Use LogicChart as a CLI-first, MCP-enhanced code reasoning tool.
Prefer context_pack, query_logic, review_queue, and analyze_impact for bounded orientation
before broad file-by-file search. Use get_finding_context and get_finding_snapshot before
treating a logical error as actionable. After substantial code edits, call update_logicchart
and validate_artifacts, then commit the synchronized logic-flow.json and logic-flow.md
artifacts when they changed. Use update_logicchart(full=true) when artifacts are missing,
stale, or analyzer behavior changed and cached file models should be ignored. Treat
VERIFIED as syntax-backed, INFERRED as deterministic heuristic, and POTENTIAL_GAP as a
review candidate, not a confirmed bug. Use preview_enrichment to inspect the bounded
optional LLM payload locally before any explicit provider send through the CLI."""


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
    finding_ids: list[str] | None,
    dependency_paths: list[str] | None,
) -> list[str]:
    has_targets = bool(flow_ids or symbols or finding_ids or dependency_paths)
    if changed_files is not None:
        return changed_files
    return [] if has_targets else git_changed_files(project_root)


def run_mcp(root: Path, config: LogicChartConfig | None = None) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "MCP support is not installed. Run `uv tool install '.[mcp]'` "
            "(or `uv sync --extra mcp` for development)."
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
                    "findings": sum(item.flow_id == flow.id for item in model.findings),
                }
                for flow in model.flows
                if flow.is_entrypoint or not entrypoints_only
            ],
            token_budget,
        )

    @server.tool()
    def get_flow(flow_id: str, token_budget: int = 0) -> dict[str, Any]:
        """Return one complete flow, including nodes, edges, callers, and findings."""
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
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        return {
            "flow": flow_dict,
            "findings": _cap(
                [
                    _finding_dict(item, model, annotation_payload)
                    for item in model.findings
                    if item.flow_id == flow.id
                ],
                token_budget,
            ),
        }

    @server.tool()
    def get_flow_navigation(flow_id: str, token_budget: int = 0) -> dict[str, Any]:
        """Return an agent navigation pack for one flow: relations, decisions, findings."""
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
        finding_kind: str | None = None,
        finding_severity: str | None = None,
        finding_evidence: str | None = None,
        source_path: str | None = None,
        symbol: str | None = None,
        domain: str | None = None,
        value: str | None = None,
        token_budget: int = 0,
    ) -> list[dict[str, Any]]:
        """Find flows relevant to a behavior, decision, state, or codebase question.

        ``scope`` restricts to a named macro-part so the result matches the CLI's
        ``query --scope`` ranking. ``token_budget`` only ever shrinks the list below
        ``limit``; it never expands it (query_model has already truncated to ``limit``).
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
            finding_kind=finding_kind,
            finding_severity=finding_severity,
            finding_evidence=finding_evidence,
            source_path=source_path,
            symbol=symbol,
            domain=domain,
            value=value,
        )
        return _cap([match.to_dict() for match in matches], token_budget)

    @server.tool()
    def get_findings(flow_id: str | None = None, token_budget: int = 0) -> list[dict[str, Any]]:
        """List findings with structured diagnostics, confidence, and next actions."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        return _cap(
            [
                _finding_dict(item, model, annotation_payload)
                for item in model.findings
                if flow_id is None or item.flow_id == flow_id
            ],
            token_budget,
        )

    @server.tool()
    def finding_rules(kind: str | None = None, token_budget: int = 0) -> list[dict[str, Any]]:
        """Return stable detector contracts: purpose, preconditions, caveats, remediation."""
        return _cap(finding_rule_contracts(kind), token_budget)

    @server.tool()
    def get_finding_snapshot(
        finding_id: str, format: str = "svg", token_budget: int = 0
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot centered on one finding."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_finding_snapshot(
            model,
            finding_id,
            max_nodes=_snapshot_node_budget(token_budget),
        )

    @server.tool()
    def get_subgraph_snapshot(
        flow_ids: list[str] | None = None,
        finding_ids: list[str] | None = None,
        format: str = "svg",
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for explicit flows/findings."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_subgraph_snapshot(
            model,
            flow_ids=flow_ids,
            finding_ids=finding_ids,
            max_flows=_snapshot_flow_budget(token_budget),
            max_nodes=_snapshot_node_budget(token_budget),
        )

    @server.tool()
    def logicchart_summary() -> dict[str, Any]:
        """An orientation snapshot: flow/entrypoint counts and findings by kind/severity."""
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
        finding_ids: list[str] | None = None,
        max_flows: int = 8,
        max_nodes_per_flow: int = 12,
        max_findings: int = 12,
        env_file: str | None = None,
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Preview the optional LLM enrichment payload without calling a provider.

        The result mirrors ``logicchart enrich`` and always reports
        ``provider_call_made: false``. Provider sends remain an explicit CLI action with
        ``logicchart enrich --send`` after the preview has been reviewed.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        options = _enrichment_options(
            scope=scope,
            flow_ids=flow_ids,
            finding_ids=finding_ids,
            max_flows=max_flows,
            max_nodes_per_flow=max_nodes_per_flow,
            max_findings=max_findings,
            token_budget=token_budget,
        )
        preview = build_enrichment_preview(
            project_root,
            model,
            active_config,
            options,
            env_file=env_file,
        )
        return _enrichment_preview_payload(
            preview,
            scope=scope,
            flow_ids=flow_ids or [],
            finding_ids=finding_ids or [],
            max_flows=options.max_flows,
            max_nodes_per_flow=options.max_nodes_per_flow,
            max_findings=options.max_findings,
            env_file=env_file,
            token_budget=token_budget,
        )

    @server.tool()
    def analysis_quality(token_budget: int = 0) -> dict[str, Any]:
        """Analyzer-quality metrics with attention signals and agent follow-up tools."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        quality = model.metadata.get("quality")
        if not isinstance(quality, dict):
            quality = model_quality(model)
        return _quality_report(quality, token_budget)

    @server.tool()
    def explain_finding_chain(finding_id: str, token_budget: int = 0) -> dict[str, Any]:
        """The deterministic evidence chain behind one finding (decision, condition, branches).

        Returns one small record; token_budget is accepted only to match the uniform
        query/list tool contract.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        result = explain_finding(model, finding_id, annotation_payload)
        if result is None:
            return _unknown_target_error("finding", finding_id)
        result["next_tools"] = {
            "finding_context": {
                "tool": "get_finding_context",
                "arguments": {"finding_id": finding_id, "token_budget": token_budget},
            },
            "visual_snapshot": {
                "tool": "get_finding_snapshot",
                "arguments": {"finding_id": finding_id, "format": "svg"},
            },
        }
        return result

    @server.tool()
    def get_finding_context(finding_id: str, token_budget: int = 0) -> dict[str, Any]:
        """Return a bounded deterministic subgraph around one logical finding."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        result = finding_context(model, finding_id, token_budget, annotation_payload)
        return result if result is not None else _unknown_target_error("finding", finding_id)

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
        """Structured search over decision nodes (by domain/subject/missing-fallback)."""
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
    def analyze_impact(
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        finding_ids: list[str] | None = None,
        dependency_paths: list[str] | None = None,
        token_budget: int = 0,
    ) -> dict[str, Any]:
        """Find direct and transitive decision flows affected by files or explicit targets.

        ``scope`` restricts to a named macro-part, matching the CLI's ``impact --scope``.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        changes = _impact_changed_files(
            project_root, changed_files, flow_ids, symbols, finding_ids, dependency_paths
        )
        result = impact_model(
            model,
            changes,
            scope,
            flow_ids=flow_ids,
            symbols=symbols,
            finding_ids=finding_ids,
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
            "target_finding_ids": result.target_finding_ids,
            "target_dependency_paths": result.target_dependency_paths,
            "unresolved_targets": result.unresolved_targets,
            "impact_reasons": result.impact_reasons,
            "direct": _cap(direct, token_budget),
            "transitive": _cap(transitive, token_budget),
            "findings": _cap(
                [_finding_dict(item, model) for item in result.findings], token_budget
            ),
            "subgraph_flow_ids": result.subgraph_flow_ids,
            "subgraph_finding_ids": result.subgraph_finding_ids,
        }

    @server.tool()
    def get_impact_snapshot(
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        finding_ids: list[str] | None = None,
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
            project_root, changed_files, flow_ids, symbols, finding_ids, dependency_paths
        )
        result = impact_model(
            model,
            changes,
            scope,
            flow_ids=flow_ids,
            symbols=symbols,
            finding_ids=finding_ids,
            dependency_paths=dependency_paths,
        )
        return render_impact_snapshot(
            changed_files=result.changed_files,
            direct=result.directly_impacted,
            transitive=result.transitively_impacted,
            findings=result.findings,
            max_flows=_snapshot_flow_budget(token_budget),
            target_flow_ids=result.target_flow_ids,
            target_symbols=result.target_symbols,
            target_finding_ids=result.target_finding_ids,
            target_dependency_paths=result.target_dependency_paths,
            unresolved_targets=result.unresolved_targets,
            impact_reasons=result.impact_reasons,
            subgraph_flow_ids=result.subgraph_flow_ids,
            subgraph_finding_ids=result.subgraph_finding_ids,
        )

    @server.tool()
    def review_queue(
        scope: str | None = None,
        evidence: str | None = None,
        severity: str | None = None,
        token_budget: int = 0,
    ) -> list[dict[str, Any]]:
        """Prioritized findings for an agent to review before or after editing."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        flows = {flow.id: flow for flow in model.flows if flow_in_agent_scope(flow, scope)}
        rows = []
        for finding in model.findings:
            if finding.flow_id not in flows:
                continue
            if evidence is not None and finding.evidence.value != evidence:
                continue
            if severity is not None and finding.severity.value != severity:
                continue
            flow = flows[finding.flow_id]
            rows.append(
                {
                    **_finding_dict(finding, model, annotation_payload),
                    "flow": _flow_summary(flow),
                    "priority": _finding_priority(finding),
                }
            )
        rows.sort(key=lambda item: (item["priority"], item["location"]["path"], item["message"]))
        return _cap(rows, token_budget)

    @server.tool()
    def context_pack(
        question: str | None = None,
        changed_files: list[str] | None = None,
        scope: str | None = None,
        flow_ids: list[str] | None = None,
        symbols: list[str] | None = None,
        finding_ids: list[str] | None = None,
        dependency_paths: list[str] | None = None,
        language: str | None = None,
        source_path: str | None = None,
        domain: str | None = None,
        value: str | None = None,
        finding_kind: str | None = None,
        finding_severity: str | None = None,
        finding_evidence: str | None = None,
        include_visual: bool = False,
        token_budget: int = 600,
        visual_byte_budget: int = _DEFAULT_CONTEXT_VISUAL_BYTE_BUDGET,
    ) -> dict[str, Any]:
        """Compact orientation pack: summary, relevant flows, impact, review, visuals.

        ``flow_ids``, ``symbols``, ``finding_ids``, and ``dependency_paths`` mirror
        ``analyze_impact`` so an agent can build a context pack around an exact flow,
        symbol, diagnostic, or source subtree without pretending a file changed.
        Query filters mirror ``query_logic`` so agents can request a bounded pack for
        source, state-domain, language, or finding evidence slices without lexical terms.
        ``visual_byte_budget`` caps inline SVG bytes when ``include_visual`` is true;
        omitted snapshots remain available through the returned ``next_tools``.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        changes = _impact_changed_files(
            project_root, changed_files, flow_ids, symbols, finding_ids, dependency_paths
        )
        impact = impact_model(
            model,
            changes,
            scope,
            flow_ids=flow_ids,
            symbols=symbols,
            finding_ids=finding_ids,
            dependency_paths=dependency_paths,
        )
        query_filters = {
            key: val
            for key, val in {
                "language": language,
                "source_path": source_path,
                "domain": domain,
                "value": value,
                "finding_kind": finding_kind,
                "finding_severity": finding_severity,
                "finding_evidence": finding_evidence,
            }.items()
            if val is not None
        }
        matches = query_model(
            model,
            question or " ".join(changes),
            limit=8,
            scope=scope,
            language=language,
            source_path=source_path,
            domain=domain,
            value=value,
            finding_kind=finding_kind,
            finding_severity=finding_severity,
            finding_evidence=finding_evidence,
        )
        review_flow_ids = {flow.id for flow in impact.all_flows} | {
            match.flow.id for match in matches
        }
        has_specific_context = bool(
            (question and question.strip())
            or changes
            or flow_ids
            or symbols
            or finding_ids
            or dependency_paths
            or query_filters
        )
        scoped_flow_ids = {flow.id for flow in model.flows if flow_in_agent_scope(flow, scope)}
        review_findings = [
            finding
            for finding in model.findings
            if finding.flow_id in scoped_flow_ids
            and (
                finding.flow_id in review_flow_ids
                or (not review_flow_ids and not has_specific_context)
            )
            and _finding_matches_agent_filters(
                finding,
                kind=finding_kind,
                severity=finding_severity,
                evidence=finding_evidence,
            )
        ]
        review_findings.sort(
            key=lambda item: (_finding_priority(item), item.location.path, item.message)
        )
        annotations = load_annotations(project_root, model, active_config)
        annotation_payload = annotations.annotations if annotations.ok else None
        review_rows = [
            _finding_dict(finding, model, annotation_payload) for finding in review_findings
        ]
        return {
            "summary": model_summary(model),
            "query_filters": query_filters,
            "query": _cap([match.to_dict() for match in matches], token_budget),
            "impact": {
                "changed_files": impact.changed_files,
                "target_flow_ids": impact.target_flow_ids,
                "target_symbols": impact.target_symbols,
                "target_finding_ids": impact.target_finding_ids,
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
                "subgraph_finding_ids": impact.subgraph_finding_ids,
            },
            "navigation": _context_navigation_pack(
                model,
                impact=impact,
                matches=matches,
                annotations=annotation_payload,
                token_budget=token_budget,
            ),
            "review": _cap(review_rows, token_budget),
            "visual_context": _context_visual_pack(
                model,
                impact=impact,
                matches=matches,
                review_findings=review_findings,
                scope=scope,
                include_visual=include_visual,
                token_budget=token_budget,
                visual_byte_budget=visual_byte_budget,
            ),
        }

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
            "findings": len(result.model.findings),
            "artifacts": [
                str(json_path),
                str(markdown_path),
                str(html_path) if html_path else "",
            ],
            **_update_workflow_payload(json_path, markdown_path, html_path),
        }

    server.run(transport="stdio")


def _flow_summary(flow: Any) -> dict[str, Any]:
    return {
        "id": flow.id,
        "name": flow.name,
        "source": f"{flow.location.path}:{flow.location.start_line}",
        "entry_kind": flow.entry_kind,
        "language": flow.language,
        "scope": flow.metadata.get("scope", []),
    }


def _impact_flow_summary(flow: Any, impact_reasons: dict[str, list[str]]) -> dict[str, Any]:
    return {
        **_flow_summary(flow),
        "reasons": impact_reasons.get(flow.id, []),
    }


def _flow_dict(flow: Any) -> dict[str, Any]:
    return asdict(flow)


def _context_visual_pack(
    model: ProjectModel,
    *,
    impact: Any,
    matches: list[Any],
    review_findings: list[Any],
    scope: str | None,
    include_visual: bool,
    token_budget: int,
    visual_byte_budget: int,
) -> dict[str, Any]:
    flow_candidates = _context_visual_flows(impact, matches)
    finding_candidates = review_findings
    flow_limit = _context_visual_item_budget(token_budget)
    finding_limit = _context_visual_item_budget(token_budget)
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
    finding_tool_args = [
        {
            "tool": "get_finding_snapshot",
            "arguments": {
                "finding_id": finding.id,
                "format": "svg",
                "token_budget": token_budget,
            },
        }
        for finding in finding_candidates[:finding_limit]
    ]
    subgraph_flow_ids = [flow.id for flow in flow_candidates[:flow_limit]]
    subgraph_finding_ids = [finding.id for finding in finding_candidates[:finding_limit]]
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
    if impact.target_finding_ids:
        impact_arguments["finding_ids"] = impact.target_finding_ids
    if impact.target_dependency_paths:
        impact_arguments["dependency_paths"] = impact.target_dependency_paths
    payload: dict[str, Any] = {
        "include_visual": include_visual,
        "format": "svg",
        "snapshot_budget": {
            "flow_snapshots": flow_limit,
            "finding_snapshots": finding_limit,
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
            "finding_snapshots": finding_tool_args,
            "subgraph_snapshot": {
                "tool": "get_subgraph_snapshot",
                "arguments": {
                    "flow_ids": subgraph_flow_ids,
                    "finding_ids": subgraph_finding_ids,
                    "format": "svg",
                    "token_budget": token_budget,
                },
            },
        },
        "omitted_flow_snapshot_count": max(0, len(flow_candidates) - flow_limit),
        "omitted_finding_snapshot_count": max(0, len(finding_candidates) - finding_limit),
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
        findings=impact.findings,
        max_flows=_snapshot_flow_budget(token_budget),
        target_flow_ids=impact.target_flow_ids,
        target_symbols=impact.target_symbols,
        target_finding_ids=impact.target_finding_ids,
        target_dependency_paths=impact.target_dependency_paths,
        unresolved_targets=impact.unresolved_targets,
        impact_reasons=impact.impact_reasons,
        subgraph_flow_ids=impact.subgraph_flow_ids,
        subgraph_finding_ids=impact.subgraph_finding_ids,
    )
    if include_snapshot(impact_snapshot):
        payload["impact_snapshot"] = impact_snapshot
    else:
        payload["impact_snapshot_omitted_reason"] = "visual_byte_budget"

    if subgraph_flow_ids or subgraph_finding_ids:
        subgraph_snapshot = render_subgraph_snapshot(
            model,
            flow_ids=subgraph_flow_ids,
            finding_ids=subgraph_finding_ids,
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

    finding_snapshots = []
    for finding in finding_candidates[:finding_limit]:
        snapshot = render_finding_snapshot(
            model, finding.id, max_nodes=_snapshot_node_budget(token_budget)
        )
        if include_snapshot(snapshot):
            finding_snapshots.append(snapshot)
        else:
            payload["omitted_finding_snapshot_count"] += 1
    payload["finding_snapshots"] = finding_snapshots
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


def _snapshot_svg_byte_size(snapshot: dict[str, Any]) -> int:
    svg = snapshot.get("svg", "")
    if not isinstance(svg, str):
        return 0
    return len(svg.encode("utf-8"))


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
    if token_budget <= 0:
        return 2
    return max(1, min(3, token_budget // 300))


def _context_navigation_token_budget(token_budget: int, flow_limit: int) -> int:
    if token_budget <= 0:
        return 0
    return max(60, token_budget // max(1, flow_limit))


def _context_visual_item_budget(token_budget: int) -> int:
    if token_budget <= 0:
        return 2
    return max(1, min(3, token_budget // 300))


def _enrichment_options(
    *,
    scope: str | None,
    flow_ids: list[str] | None,
    finding_ids: list[str] | None,
    max_flows: int,
    max_nodes_per_flow: int,
    max_findings: int,
    token_budget: int,
) -> EnrichmentOptions:
    flow_limit = max(0, max_flows)
    node_limit = max(0, max_nodes_per_flow)
    finding_limit = max(0, max_findings)
    if token_budget > 0:
        flow_limit = min(flow_limit, max(1, token_budget // 240))
        node_limit = min(node_limit, max(4, token_budget // 100))
        finding_limit = min(finding_limit, max(1, token_budget // 180))
    return EnrichmentOptions(
        scope=scope,
        flow_ids=tuple(flow_ids or ()),
        finding_ids=tuple(finding_ids or ()),
        max_flows=flow_limit,
        max_nodes_per_flow=node_limit,
        max_findings=finding_limit,
    )


def _enrichment_preview_payload(
    preview: dict[str, Any],
    *,
    scope: str | None,
    flow_ids: list[str],
    finding_ids: list[str],
    max_flows: int,
    max_nodes_per_flow: int,
    max_findings: int,
    env_file: str | None,
    token_budget: int,
) -> dict[str, Any]:
    targets = preview.get("targets", {})
    selected_flow_ids = _string_list(targets.get("flow_ids"))
    selected_finding_ids = _string_list(targets.get("finding_ids"))
    next_tools: dict[str, Any] = {
        "review_queue": {
            "tool": "review_queue",
            "arguments": {"token_budget": token_budget or 600},
        },
        "get_findings": {
            "tool": "get_findings",
            "arguments": {"token_budget": token_budget or 600},
        },
    }
    if selected_flow_ids or selected_finding_ids:
        next_tools["subgraph_snapshot"] = {
            "tool": "get_subgraph_snapshot",
            "arguments": {
                "flow_ids": selected_flow_ids,
                "finding_ids": selected_finding_ids,
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
            "This MCP tool is local preview only and never calls a provider. Review the "
            "request payload and use the CLI `logicchart enrich --send` only after the "
            "external-send boundary is approved for the selected codebase."
        ),
        "next_tools": next_tools,
        "next_cli": _enrichment_next_cli(
            scope=scope,
            flow_ids=flow_ids,
            finding_ids=finding_ids,
            max_flows=max_flows,
            max_nodes_per_flow=max_nodes_per_flow,
            max_findings=max_findings,
            env_file=env_file,
        ),
    }


def _enrichment_next_cli(
    *,
    scope: str | None,
    flow_ids: list[str],
    finding_ids: list[str],
    max_flows: int,
    max_nodes_per_flow: int,
    max_findings: int,
    env_file: str | None,
) -> list[str]:
    base = ["logicchart", "enrich"]
    if scope is not None:
        base.extend(["--scope", scope])
    for flow_id in flow_ids:
        base.extend(["--flow", flow_id])
    for finding_id in finding_ids:
        base.extend(["--finding", finding_id])
    base.extend(["--max-flows", str(max_flows)])
    base.extend(["--max-nodes-per-flow", str(max_nodes_per_flow)])
    base.extend(["--max-findings", str(max_findings)])
    if env_file is not None:
        base.extend(["--env-file", env_file])
    preview = [*base, "--json"]
    send = [*base, "--send"]
    return [
        _shell_join(preview),
        "logicchart llm setup --help",
        f"{_shell_join(send)}  # after reviewing preview and approving provider send",
    ]


def _shell_join(parts: list[str]) -> str:
    return " ".join(quote(part) for part in parts)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _quality_report(quality: dict[str, Any], token_budget: int) -> dict[str, Any]:
    return {
        "quality": _bounded_quality(quality, token_budget),
        "attention": _quality_attention_items(quality, token_budget),
        "guardrail": (
            "Quality attention signals identify analyzer limits and review targets; "
            "they are not confirmed logical bugs by themselves."
        ),
        "next_tools": {
            "validate_quality": {
                "tool": "validate_artifacts",
                "arguments": {"include_quality": True},
            },
            "review_queue": {
                "tool": "review_queue",
                "arguments": {"token_budget": token_budget},
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
        "review_queue": {
            "tool": "review_queue",
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
            "and optional analyzer-quality thresholds; it does not confirm or dismiss "
            "logical findings."
        ),
        "next_tools": next_tools,
        "next_cli": _validation_next_cli(bool(payload.get("ok"))),
    }


def _validation_next_cli(ok: bool) -> list[str]:
    if ok:
        return [
            "logicchart validate --quality --json",
            "logicchart query <question>",
            "logicchart explain <finding-id>",
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
            "review_queue": {
                "tool": "review_queue",
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


def _finding_dict(
    finding: Any,
    model: ProjectModel | None = None,
    annotations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = asdict(finding)
    metadata = data.setdefault("metadata", {})
    if not isinstance(metadata.get("diagnostic"), dict):
        flow = None
        node = None
        if model is not None:
            flow = next((item for item in model.flows if item.id == finding.flow_id), None)
            if flow is not None and finding.node_id:
                node = next((item for item in flow.nodes if item.id == finding.node_id), None)
        metadata["diagnostic"] = diagnostic_for_finding(
            finding,
            flow=flow,
            node=node,
            model=model,
        )
    annotation = _finding_annotation(finding, annotations)
    if annotation:
        data["annotation"] = annotation
    data["next_tools"] = _finding_next_tools(finding)
    return data


def _finding_annotation(finding: Any, annotations: dict[str, Any] | None) -> dict[str, str] | None:
    if not annotations:
        return None
    finding_annotations = annotations.get("findings", {})
    if not isinstance(finding_annotations, dict):
        return None
    annotation = finding_annotations.get(finding.id)
    return annotation if isinstance(annotation, dict) and annotation else None


def _finding_next_tools(finding: Any) -> dict[str, dict[str, Any]]:
    return {
        "finding_context": {
            "tool": "get_finding_context",
            "arguments": {"finding_id": finding.id},
        },
        "visual_snapshot": {
            "tool": "get_finding_snapshot",
            "arguments": {"finding_id": finding.id, "format": "svg"},
        },
        "subgraph_snapshot": {
            "tool": "get_subgraph_snapshot",
            "arguments": {
                "flow_ids": [finding.flow_id],
                "finding_ids": [finding.id],
                "format": "svg",
            },
        },
        "flow_navigation": {
            "tool": "get_flow_navigation",
            "arguments": {"flow_id": finding.flow_id},
        },
    }


def _unknown_target_error(target_type: str, target_id: str) -> dict[str, Any]:
    next_tools: dict[str, dict[str, Any]]
    if target_type == "flow":
        next_tools = {
            "list_flows": {
                "tool": "list_flows",
                "arguments": {"entrypoints_only": False, "token_budget": 600},
            },
            "query_logic": {
                "tool": "query_logic",
                "arguments": {"question": target_id, "token_budget": 600},
            },
        }
    else:
        next_tools = {
            "review_queue": {
                "tool": "review_queue",
                "arguments": {"token_budget": 600},
            },
            "get_findings": {
                "tool": "get_findings",
                "arguments": {"token_budget": 600},
            },
        }
    return {
        "error": f"Unknown {target_type}: {target_id}",
        "error_code": f"{target_type}_not_found",
        "target_type": target_type,
        "target_id": target_id,
        "recoverable": True,
        "guardrail": (
            "This reports an invalid MCP target from the generated model; it is not a "
            "source-code logical finding."
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
            "This reports missing or invalid generated artifacts; it is not a "
            "source-code logical finding."
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
    return scope is None or scope in flow.metadata.get("scope", [])


def _finding_matches_agent_filters(
    finding: Any,
    *,
    kind: str | None,
    severity: str | None,
    evidence: str | None,
) -> bool:
    if kind is not None and finding.kind != kind:
        return False
    if severity is not None and finding.severity.value != severity:
        return False
    return evidence is None or finding.evidence.value == evidence


def _finding_priority(finding: Any) -> int:
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    evidence_rank = {"VERIFIED": 0, "INFERRED": 1, "POTENTIAL_GAP": 2}
    return severity_rank.get(finding.severity.value, 3) * 10 + evidence_rank.get(
        finding.evidence.value,
        3,
    )
