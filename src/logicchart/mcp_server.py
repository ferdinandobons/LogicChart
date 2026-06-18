from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from logicchart.analysis import ProjectAnalyzer
from logicchart.artifacts import load_model, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.diagnostics import diagnostic_for_finding, finding_rule_contracts
from logicchart.model import ProjectModel
from logicchart.query import (
    explain_finding,
    find_decisions,
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
    unsupported_snapshot_format,
)
from logicchart.validation import validate_logicchart

# Rough tokens per returned list item, used to honor an agent's token_budget cap.
_TOKENS_PER_ITEM = 60

# Errors raised while loading the on-disk model (missing file, corrupt/garbled JSON,
# unexpected schema). Surfaced to the agent as a clean {"error": ...} instead of a raw
# traceback, so a stale or never-built model is recoverable advice, not a crash.
_LOAD_ERRORS = (OSError, ValueError, KeyError, TypeError)

MCP_INSTRUCTIONS = """Use LogicChart as a CLI-first, MCP-enhanced code reasoning tool.
Prefer context_pack, query_logic, review_queue, and analyze_impact for bounded orientation
before broad file-by-file search. After substantial code edits, call update_logicchart and
validate_artifacts, then commit the synchronized logic-flow.json and logic-flow.md artifacts
when they changed. Treat VERIFIED as syntax-backed, INFERRED as deterministic heuristic, and
POTENTIAL_GAP as a review candidate, not a confirmed bug."""


def _cap(items: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return items
    return items[: max(1, token_budget // _TOKENS_PER_ITEM)]


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
            return {"error": f"Unknown flow: {flow_id}"}
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
        return {
            "flow": flow_dict,
            "findings": _cap(
                [_finding_dict(item, model) for item in model.findings if item.flow_id == flow.id],
                token_budget,
            ),
        }

    @server.tool()
    def get_flow_snapshot(flow_id: str, format: str = "svg") -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for one flow."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_flow_snapshot(model, flow_id)

    @server.tool()
    def query_logic(
        question: str,
        limit: int = 10,
        scope: str | None = None,
        language: str | None = None,
        finding_kind: str | None = None,
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
        )
        return _cap([match.to_dict() for match in matches], token_budget)

    @server.tool()
    def get_findings(flow_id: str | None = None, token_budget: int = 0) -> list[dict[str, Any]]:
        """List findings with structured diagnostics, confidence, and next actions."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return [error]
        assert model is not None
        return _cap(
            [
                _finding_dict(item, model)
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
    def get_finding_snapshot(finding_id: str, format: str = "svg") -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot centered on one finding."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return render_finding_snapshot(model, finding_id)

    @server.tool()
    def logicchart_summary() -> dict[str, Any]:
        """An orientation snapshot: flow/entrypoint counts and findings by kind/severity."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        return model_summary(model)

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
        result = explain_finding(model, finding_id)
        return result if result is not None else {"error": f"Unknown finding: {finding_id}"}

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
        changed_files: list[str], scope: str | None = None, token_budget: int = 0
    ) -> dict[str, Any]:
        """Find direct and transitive decision flows affected by changed source files.

        ``scope`` restricts to a named macro-part, matching the CLI's ``impact --scope``.
        """
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        result = impact_model(model, changed_files, scope)
        direct = [_flow_summary(item) for item in result.directly_impacted]
        transitive = [_flow_summary(item) for item in result.transitively_impacted]
        return {
            "changed_files": result.changed_files,
            "direct": _cap(direct, token_budget),
            "transitive": _cap(transitive, token_budget),
            "findings": _cap(
                [_finding_dict(item, model) for item in result.findings], token_budget
            ),
        }

    @server.tool()
    def get_impact_snapshot(
        changed_files: list[str],
        scope: str | None = None,
        format: str = "svg",
    ) -> dict[str, Any]:
        """Return a deterministic visual SVG snapshot for direct and caller impact."""
        if format not in SNAPSHOT_FORMATS:
            return unsupported_snapshot_format(format)
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        result = impact_model(model, changed_files, scope)
        return render_impact_snapshot(
            changed_files=result.changed_files,
            direct=result.directly_impacted,
            transitive=result.transitively_impacted,
            findings=result.findings,
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
                    **_finding_dict(finding, model),
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
        token_budget: int = 600,
    ) -> dict[str, Any]:
        """Compact orientation pack: summary, relevant flows, impact, and review queue."""
        model, error = _try_load(project_root, active_config)
        if error is not None:
            return error
        assert model is not None
        changes = changed_files if changed_files is not None else git_changed_files(project_root)
        impact = impact_model(model, changes, scope)
        matches = query_model(model, question or " ".join(changes), limit=8, scope=scope)
        review_flow_ids = {flow.id for flow in impact.all_flows} | {
            match.flow.id for match in matches
        }
        review_rows = [
            _finding_dict(finding, model)
            for finding in model.findings
            if not review_flow_ids or finding.flow_id in review_flow_ids
        ]
        return {
            "summary": model_summary(model),
            "query": _cap([match.to_dict() for match in matches], token_budget),
            "impact": {
                "changed_files": impact.changed_files,
                "direct": _cap(
                    [_flow_summary(item) for item in impact.directly_impacted],
                    token_budget,
                ),
                "transitive": _cap(
                    [_flow_summary(item) for item in impact.transitively_impacted],
                    token_budget,
                ),
            },
            "review": _cap(review_rows, token_budget),
        }

    @server.tool()
    def validate_artifacts(
        check_sync: bool = False, include_quality: bool = False
    ) -> dict[str, Any]:
        """Validate the generated model and optionally check source sync."""
        return validate_logicchart(
            project_root,
            config=active_config,
            check_sync=check_sync,
            include_quality=include_quality,
        ).to_dict()

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


def _flow_dict(flow: Any) -> dict[str, Any]:
    return asdict(flow)


def _finding_dict(finding: Any, model: ProjectModel | None = None) -> dict[str, Any]:
    data = asdict(finding)
    metadata = data.setdefault("metadata", {})
    if not isinstance(metadata.get("diagnostic"), dict):
        flow = None
        node = None
        if model is not None:
            flow = next((item for item in model.flows if item.id == finding.flow_id), None)
            if flow is not None and finding.node_id:
                node = next((item for item in flow.nodes if item.id == finding.node_id), None)
        metadata["diagnostic"] = diagnostic_for_finding(finding, flow=flow, node=node)
    return data


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
        return None, {
            "error": f"Could not load the LogicChart model: {error}. "
            "Run `logicchart analyze --full` (or the update_logicchart tool) first."
        }


def flow_in_agent_scope(flow: Any, scope: str | None) -> bool:
    return scope is None or scope in flow.metadata.get("scope", [])


def _finding_priority(finding: Any) -> int:
    severity_rank = {"error": 0, "warning": 1, "info": 2}
    evidence_rank = {"VERIFIED": 0, "INFERRED": 1, "POTENTIAL_GAP": 2}
    return severity_rank.get(finding.severity.value, 3) * 10 + evidence_rank.get(
        finding.evidence.value,
        3,
    )
