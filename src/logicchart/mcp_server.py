from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from logicchart.analysis import ProjectAnalyzer
from logicchart.artifacts import load_model, write_artifacts
from logicchart.diff import diff_models
from logicchart.model import ProjectModel
from logicchart.query import (
    explain_finding,
    find_decisions,
    impact_model,
    model_summary,
    query_model,
    where_is_state_handled,
)
from logicchart.util import read_json

# Rough tokens per returned list item, used to honor an agent's token_budget cap.
_TOKENS_PER_ITEM = 60


def _cap(items: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return items
    return items[: max(1, token_budget // _TOKENS_PER_ITEM)]


def run_mcp(root: Path) -> None:
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError(
            "MCP support is not installed. Run `pip install 'logicchart[mcp]'`."
        ) from error

    project_root = root.resolve()
    server = FastMCP("LogicChart", json_response=True)

    @server.tool()
    def list_flows(entrypoints_only: bool = True, token_budget: int = 0) -> list[dict[str, Any]]:
        """List known decision flows in the current project."""
        model = load_model(project_root)
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
    def get_flow(flow_id: str) -> dict[str, Any]:
        """Return one complete flow, including nodes, edges, callers, and findings."""
        model = load_model(project_root)
        flow = next((item for item in model.flows if item.id == flow_id), None)
        if flow is None:
            return {"error": f"Unknown flow: {flow_id}"}
        return {
            "flow": _flow_dict(flow),
            "findings": [_finding_dict(item) for item in model.findings if item.flow_id == flow.id],
        }

    @server.tool()
    def query_logic(question: str, limit: int = 10) -> list[dict[str, Any]]:
        """Find flows relevant to a behavior, decision, state, or codebase question."""
        model = load_model(project_root)
        return [
            {
                "flow_id": match.flow.id,
                "name": match.flow.name,
                "score": match.score,
                "reasons": match.reasons,
                "source": (f"{match.flow.location.path}:{match.flow.location.start_line}"),
            }
            for match in query_model(model, question, limit)
        ]

    @server.tool()
    def get_findings(flow_id: str | None = None, token_budget: int = 0) -> list[dict[str, Any]]:
        """List potential gaps and inconsistent case handling."""
        model = load_model(project_root)
        return _cap(
            [
                _finding_dict(item)
                for item in model.findings
                if flow_id is None or item.flow_id == flow_id
            ],
            token_budget,
        )

    @server.tool()
    def logicchart_summary() -> dict[str, Any]:
        """An orientation snapshot: flow/entrypoint counts and findings by kind/severity."""
        return model_summary(load_model(project_root))

    @server.tool()
    def explain_finding_chain(finding_id: str) -> dict[str, Any]:
        """The deterministic evidence chain behind one finding (decision, condition, branches)."""
        result = explain_finding(load_model(project_root), finding_id)
        return result if result is not None else {"error": f"Unknown finding: {finding_id}"}

    @server.tool()
    def where_state_handled(
        domain: str, value: str | None = None, token_budget: int = 0
    ) -> list[dict[str, Any]]:
        """Every flow that branches on a domain/value-namespace, with the values it covers."""
        return _cap(where_is_state_handled(load_model(project_root), domain, value), token_budget)

    @server.tool()
    def find_decision_nodes(
        domain: str | None = None,
        subject: str | None = None,
        missing_fallback: bool = False,
        token_budget: int = 0,
    ) -> list[dict[str, Any]]:
        """Structured search over decision nodes (by domain/subject/missing-fallback)."""
        decisions = find_decisions(
            load_model(project_root),
            domain=domain,
            subject=subject,
            missing_fallback=missing_fallback,
        )
        return _cap(decisions, token_budget)

    @server.tool()
    def diff_findings(base_path: str) -> dict[str, Any]:
        """Compare the current model against a baseline logic-flow.json (the CI primitive)."""
        base = ProjectModel.from_dict(read_json(Path(base_path)))
        diff = diff_models(base, load_model(project_root))
        return {
            "introduced": [_finding_dict(item) for item in diff.introduced],
            "resolved": [_finding_dict(item) for item in diff.resolved],
            "persisting": len(diff.persisting),
        }

    @server.tool()
    def analyze_impact(changed_files: list[str]) -> dict[str, Any]:
        """Find direct and transitive decision flows affected by changed source files."""
        result = impact_model(load_model(project_root), changed_files)
        return {
            "changed_files": result.changed_files,
            "direct": [_flow_summary(item) for item in result.directly_impacted],
            "transitive": [_flow_summary(item) for item in result.transitively_impacted],
            "findings": [_finding_dict(item) for item in result.findings],
        }

    @server.tool()
    def update_logicchart(full: bool = False) -> dict[str, Any]:
        """Refresh LogicChart after source changes and write JSON, Markdown, and HTML."""
        result = ProjectAnalyzer(project_root).analyze(full=full)
        json_path, markdown_path, html_path = write_artifacts(project_root, result.model)
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
    }


def _flow_dict(flow: Any) -> dict[str, Any]:
    return asdict(flow)


def _finding_dict(finding: Any) -> dict[str, Any]:
    return asdict(finding)
