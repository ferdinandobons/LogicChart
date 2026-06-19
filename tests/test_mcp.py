import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.annotations import annotations_path, model_hash
from logicchart.artifacts import load_model, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.llm_enrich import build_enrichment_preview
from logicchart.mcp_server import (
    MCP_INSTRUCTIONS,
    _context_navigation_pack,
    _context_visual_pack,
    _domain_logic_map,
    _enrichment_options,
    _enrichment_preview_payload,
    _finding_dict,
    _model_load_error,
    _quality_report,
    _unknown_target_error,
    _update_workflow_payload,
    _validation_payload,
)
from logicchart.query import impact_model, query_model


def test_mcp_finding_dict_includes_optional_annotation(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        """
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    DELETED = "deleted"


def handle(status):
    match status:
        case Status.OPEN:
            return "open"
        case Status.CLOSED:
            return "closed"
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    finding = model.findings[0]
    row = _finding_dict(
        finding,
        model,
        {"findings": {finding.id: {"summary": "Missing deleted branch."}}},
    )

    assert row["annotation"]["summary"] == "Missing deleted branch."
    assert row["metadata"]["diagnostic"]["rule_id"] == finding.kind
    assert row["next_tools"]["finding_context"]["tool"] == "get_finding_context"


def test_mcp_lists_and_queries_flows(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        """
def authorize(user):
    if user.role == "admin":
        return True
    return False
""",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    flow = result.model.flows[0]
    annotations_path(tmp_path).write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model_hash": model_hash(result.model),
                "flows": {flow.id: {"label": "Annotated authorization"}},
            }
        ),
        encoding="utf-8",
    )

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                assert init.instructions == MCP_INSTRUCTIONS
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"list_flows", "get_flow", "query_logic", "update_logicchart"} <= names
                assert {
                    "logicchart_summary",
                    "agent_context",
                    "analysis_quality",
                    "explain_finding_chain",
                    "get_finding_context",
                    "finding_rules",
                    "get_flow_navigation",
                    "get_flow_snapshot",
                    "get_finding_snapshot",
                    "get_subgraph_snapshot",
                    "get_impact_snapshot",
                    "preview_enrichment",
                    "preview_annotation_targets",
                    "annotation_status",
                    "validate_annotations",
                    "write_annotations",
                    "clear_annotations",
                    "domain_map",
                    "where_state_handled",
                    "find_decision_nodes",
                    "review_queue",
                    "context_pack",
                    "validate_artifacts",
                } <= names

                # Spec §5.2: every query/list tool exposes a token_budget cap.
                schema_by_name = {tool.name: tool.inputSchema for tool in tools.tools}
                update_properties = schema_by_name["update_logicchart"].get("properties", {})
                assert "full" in update_properties
                validation_properties = schema_by_name["validate_artifacts"].get("properties", {})
                assert "max_parse_warnings" in validation_properties
                for budget_tool in (
                    "get_flow",
                    "get_flow_navigation",
                    "get_flow_snapshot",
                    "get_finding_snapshot",
                    "get_subgraph_snapshot",
                    "get_impact_snapshot",
                    "query_logic",
                    "analysis_quality",
                    "explain_finding_chain",
                    "get_finding_context",
                    "finding_rules",
                    "analyze_impact",
                    "preview_enrichment",
                    "preview_annotation_targets",
                    "domain_map",
                    "review_queue",
                    "context_pack",
                    "agent_context",
                ):
                    properties = schema_by_name[budget_tool].get("properties", {})
                    assert "token_budget" in properties, budget_tool
                agent_context_properties = schema_by_name["agent_context"].get("properties", {})
                assert {
                    "question",
                    "changed_files",
                    "selected_code",
                    "current_file",
                    "flow_id",
                    "symbol",
                    "finding_id",
                    "dependency_path",
                    "domain",
                    "value",
                    "include_visual",
                } <= set(agent_context_properties)
                context_properties = schema_by_name["context_pack"].get("properties", {})
                assert {"flow_ids", "symbols", "finding_ids", "dependency_paths"} <= set(
                    context_properties
                )
                assert {
                    "language",
                    "source_path",
                    "domain",
                    "value",
                    "finding_kind",
                    "finding_severity",
                    "finding_evidence",
                } <= set(context_properties)
                assert "visual_byte_budget" in context_properties
                for impact_tool in ("analyze_impact", "get_impact_snapshot"):
                    impact_properties = schema_by_name[impact_tool].get("properties", {})
                    assert "dependency_paths" in impact_properties
                query_properties = schema_by_name["query_logic"].get("properties", {})
                assert {"finding_kind", "finding_severity", "finding_evidence"} <= set(
                    query_properties
                )
                enrichment_properties = schema_by_name["preview_enrichment"].get("properties", {})
                assert {"flow_ids", "finding_ids", "max_nodes_per_flow"} <= set(
                    enrichment_properties
                )
                annotation_target_properties = schema_by_name["preview_annotation_targets"].get(
                    "properties", {}
                )
                assert {"flow_ids", "finding_ids", "max_nodes_per_flow"} <= set(
                    annotation_target_properties
                )
                write_annotation_properties = schema_by_name["write_annotations"].get(
                    "properties", {}
                )
                assert {"flows", "nodes", "findings", "scopes", "replace_existing"} <= set(
                    write_annotation_properties
                )

                response = await session.call_tool(
                    "query_logic",
                    {"question": "admin authorization", "limit": 5},
                )
                assert not response.isError
                assert "authorize" in str(response.content)
                agent_context = await session.call_tool(
                    "agent_context",
                    {
                        "question": "how does admin authorization work?",
                        "current_file": "app.py",
                        "selected_code": "if user.role == 'admin': return True",
                        "include_visual": True,
                        "token_budget": 480,
                    },
                )
                assert not agent_context.isError
                agent_context_payload = agent_context.structuredContent  # type: ignore[assignment]
                assert agent_context_payload["tool"] == "agent_context"  # type: ignore[index]
                assert "confirmed bugs" in agent_context_payload["guardrail"]  # type: ignore[index]
                assert (  # type: ignore[index]
                    agent_context_payload["inputs"]["current_file"] == "app.py"
                )
                context = agent_context_payload["context"]  # type: ignore[index]
                assert context["query"][0]["flow_id"] == flow.id
                assert "visual_context" in context
                assert (  # type: ignore[index]
                    agent_context_payload["recommended_next_tools"]["validate_artifacts"]["tool"]
                    == "validate_artifacts"
                )
                filtered_response = await session.call_tool(
                    "query_logic",
                    {"question": "", "symbol": flow.symbol, "source_path": "app.py"},
                )
                assert not filtered_response.isError
                filtered_rows = filtered_response.structuredContent["result"]  # type: ignore[index]
                assert [row["flow_id"] for row in filtered_rows] == [flow.id]

                summary = await session.call_tool("logicchart_summary", {})
                assert not summary.isError
                assert "flows" in str(summary.content)
                assert "finding_rules" in str(summary.content)
                assert "quality" in str(summary.content)
                assert "language_capabilities" in str(summary.content)
                assert "Annotated authorization" not in str(summary.content)
                assert "annotations" in str(summary.content)
                assert summary.structuredContent["annotations"]["counts"]["flows"] == 1  # type: ignore[index]

                enrichment = await session.call_tool(
                    "preview_enrichment",
                    {"flow_ids": [flow.id], "token_budget": 240},
                )
                assert not enrichment.isError
                enrichment_payload = enrichment.structuredContent  # type: ignore[assignment]
                assert enrichment_payload["provider_call_made"] is False  # type: ignore[index]
                assert enrichment_payload["send_required"] is True  # type: ignore[index]
                assert enrichment_payload["targets"]["flow_ids"] == [flow.id]  # type: ignore[index]
                assert enrichment_payload["request"]["flows"][0]["id"] == flow.id  # type: ignore[index]
                assert "LOGICCHART_LLM_API_KEY" not in str(enrichment.content)
                assert "agent-authored annotations" in enrichment_payload["guardrail"]  # type: ignore[index]
                assert (  # type: ignore[index]
                    enrichment_payload["next_tools"]["subgraph_snapshot"]["tool"]
                    == "get_subgraph_snapshot"
                )
                assert "next_cli" not in enrichment_payload
                assert "logicchart validate" in enrichment_payload["next_actions"][2]  # type: ignore[index]

                preview_targets = await session.call_tool(
                    "preview_annotation_targets",
                    {"flow_ids": [flow.id], "token_budget": 240},
                )
                assert not preview_targets.isError
                preview_targets_payload = preview_targets.structuredContent  # type: ignore[assignment]
                assert preview_targets_payload["tool"] == "preview_annotation_targets"  # type: ignore[index]
                assert preview_targets_payload["send_required"] is False  # type: ignore[index]
                assert preview_targets_payload["allowed_fields"]["flows"] == [  # type: ignore[index]
                    "label",
                    "description",
                    "summary",
                ]
                assert (  # type: ignore[index]
                    preview_targets_payload["next_tools"]["write_annotations"]["tool"]
                    == "write_annotations"
                )

                annotation_status = await session.call_tool(
                    "annotation_status",
                    {"include_annotations": True},
                )
                assert not annotation_status.isError
                annotation_status_payload = annotation_status.structuredContent  # type: ignore[assignment]
                assert annotation_status_payload["status"] == "loaded"  # type: ignore[index]
                assert annotation_status_payload["counts"]["flows"] == 1  # type: ignore[index]
                assert annotation_status_payload["annotations"]["flows"][flow.id]["label"] == (  # type: ignore[index]
                    "Annotated authorization"
                )

                invalid_annotation_write = await session.call_tool(
                    "write_annotations",
                    {"flows": {"missing-flow": {"label": "Unknown flow"}}},
                )
                assert not invalid_annotation_write.isError
                invalid_write_payload = invalid_annotation_write.structuredContent  # type: ignore[assignment]
                assert invalid_write_payload["ok"] is False  # type: ignore[index]
                assert (  # type: ignore[index]
                    invalid_write_payload["error_code"] == "annotation_validation_failed"
                )
                assert "missing-flow" in "; ".join(invalid_write_payload["errors"])  # type: ignore[index]

                annotation_write = await session.call_tool(
                    "write_annotations",
                    {
                        "flows": {
                            flow.id: {
                                "summary": "Agent-authored summary for authorization.",
                            }
                        },
                        "generated_by": {
                            "kind": "agent_generated",
                            "agent": "test-agent",
                        },
                    },
                )
                assert not annotation_write.isError
                annotation_write_payload = annotation_write.structuredContent  # type: ignore[assignment]
                assert annotation_write_payload["ok"] is True  # type: ignore[index]
                assert annotation_write_payload["tool"] == "write_annotations"  # type: ignore[index]
                assert annotation_write_payload["counts"]["flows"] == 1  # type: ignore[index]
                validate_annotation_sidecar = await session.call_tool(
                    "validate_annotations",
                    {"include_annotations": True},
                )
                assert not validate_annotation_sidecar.isError
                validate_annotation_payload = validate_annotation_sidecar.structuredContent  # type: ignore[assignment]
                assert validate_annotation_payload["ok"] is True  # type: ignore[index]
                assert (  # type: ignore[index]
                    validate_annotation_payload["annotations"]["flows"][flow.id]["summary"]
                    == "Agent-authored summary for authorization."
                )
                assert (  # type: ignore[index]
                    validate_annotation_payload["next_tools"]["validate_artifacts"]["tool"]
                    == "validate_artifacts"
                )

                quality = await session.call_tool("analysis_quality", {"token_budget": 240})
                assert not quality.isError
                quality_payload = quality.structuredContent  # type: ignore[assignment]
                assert "quality" in quality_payload
                assert "guardrail" in quality_payload
                assert (
                    quality_payload["next_tools"]["validate_quality"]["tool"]  # type: ignore[index]
                    == "validate_artifacts"
                )
                quality_metrics = quality_payload["quality"]  # type: ignore[index]
                assert "python" in quality_metrics["languages"]["depth"]  # type: ignore[index]
                assert (
                    quality_metrics["languages"]["depth"]["python"]["capability"]["frontend"]  # type: ignore[index]
                    == "python_ast"
                )
                assert isinstance(quality_payload["attention"], list)  # type: ignore[index]

                rules = await session.call_tool("finding_rules", {"kind": "missing_branch"})
                assert not rules.isError
                assert "Missing explicit fallback" in str(rules.content)
                rule_payload = rules.structuredContent["result"][0]  # type: ignore[index]
                assert "true_positive_example" in rule_payload
                assert "intentional_suppression_example" in rule_payload
                missing_finding = await session.call_tool(
                    "explain_finding_chain",
                    {"finding_id": "missing-finding"},
                )
                assert not missing_finding.isError
                missing_finding_payload = missing_finding.structuredContent  # type: ignore[assignment]
                assert missing_finding_payload["error_code"] == "finding_not_found"  # type: ignore[index]
                assert (  # type: ignore[index]
                    missing_finding_payload["next_tools"]["review_queue"]["tool"] == "review_queue"
                )
                missing_finding_context = await session.call_tool(
                    "get_finding_context",
                    {"finding_id": "missing-finding"},
                )
                assert not missing_finding_context.isError
                assert (  # type: ignore[index]
                    missing_finding_context.structuredContent["error_code"] == "finding_not_found"
                )
                missing_finding_snapshot = await session.call_tool(
                    "get_finding_snapshot",
                    {"finding_id": "missing-finding"},
                )
                assert not missing_finding_snapshot.isError
                assert (  # type: ignore[index]
                    missing_finding_snapshot.structuredContent["error_code"]
                    == "snapshot_finding_not_found"
                )

                navigation = await session.call_tool(
                    "get_flow_navigation",
                    {"flow_id": flow.id},
                )
                assert not navigation.isError
                assert "decision_nodes" in str(navigation.content)
                assert "visual_snapshot" in str(navigation.content)
                assert "Annotated authorization" in str(navigation.content)

                flow_snapshot = await session.call_tool(
                    "get_flow_snapshot",
                    {"flow_id": flow.id},
                )
                assert not flow_snapshot.isError
                assert "<svg" in str(flow_snapshot.content)
                subgraph_snapshot = await session.call_tool(
                    "get_subgraph_snapshot",
                    {"flow_ids": [flow.id], "token_budget": 120},
                )
                assert not subgraph_snapshot.isError
                subgraph_payload = subgraph_snapshot.structuredContent  # type: ignore[assignment]
                assert subgraph_payload["rendered_flow_ids"] == [flow.id]  # type: ignore[index]
                assert (
                    subgraph_payload["layout"]["engine"]  # type: ignore[index]
                    == "static-subgraph-snapshot-v1"
                )
                assert "Subgraph snapshot" in str(subgraph_snapshot.content)
                missing_flow = await session.call_tool("get_flow", {"flow_id": "missing-flow"})
                assert not missing_flow.isError
                missing_flow_payload = missing_flow.structuredContent  # type: ignore[assignment]
                assert missing_flow_payload["error_code"] == "flow_not_found"  # type: ignore[index]
                assert missing_flow_payload["target_id"] == "missing-flow"  # type: ignore[index]
                assert (  # type: ignore[index]
                    missing_flow_payload["next_tools"]["list_flows"]["tool"] == "list_flows"
                )
                missing_navigation = await session.call_tool(
                    "get_flow_navigation",
                    {"flow_id": "missing-flow"},
                )
                assert not missing_navigation.isError
                missing_navigation_payload = missing_navigation.structuredContent  # type: ignore[assignment]
                assert missing_navigation_payload["error_code"] == "flow_not_found"  # type: ignore[index]
                assert (  # type: ignore[index]
                    missing_navigation_payload["next_tools"]["query_logic"]["tool"] == "query_logic"
                )
                missing_flow_snapshot = await session.call_tool(
                    "get_flow_snapshot",
                    {"flow_id": "missing-flow"},
                )
                assert not missing_flow_snapshot.isError
                missing_flow_snapshot_payload = missing_flow_snapshot.structuredContent  # type: ignore[assignment]
                assert (  # type: ignore[index]
                    missing_flow_snapshot_payload["error_code"] == "snapshot_flow_not_found"
                )
                missing_subgraph_snapshot = await session.call_tool(
                    "get_subgraph_snapshot",
                    {"flow_ids": ["missing-flow"]},
                )
                assert not missing_subgraph_snapshot.isError
                missing_subgraph_payload = missing_subgraph_snapshot.structuredContent  # type: ignore[assignment]
                assert missing_subgraph_payload["unresolved_targets"] == [  # type: ignore[index]
                    {"type": "flow", "value": "missing-flow", "reason": "not_found"}
                ]

                impact_snapshot = await session.call_tool(
                    "get_impact_snapshot",
                    {"changed_files": ["app.py"]},
                )
                assert not impact_snapshot.isError
                assert "Impact snapshot" in str(impact_snapshot.content)
                targeted_impact = await session.call_tool(
                    "analyze_impact",
                    {"flow_ids": [flow.id], "token_budget": 120},
                )
                assert not targeted_impact.isError
                targeted_payload = targeted_impact.structuredContent  # type: ignore[assignment]
                assert targeted_payload["changed_files"] == []  # type: ignore[index]
                assert targeted_payload["target_flow_ids"] == [flow.id]  # type: ignore[index]
                assert targeted_payload["impact_reasons"] == {  # type: ignore[index]
                    flow.id: [f"explicit flow target `{flow.id}`"]
                }
                assert targeted_payload["direct"][0]["reasons"] == [  # type: ignore[index]
                    f"explicit flow target `{flow.id}`"
                ]
                assert flow.id in targeted_payload["subgraph_flow_ids"]  # type: ignore[index]
                targeted_snapshot = await session.call_tool(
                    "get_impact_snapshot",
                    {"flow_ids": [flow.id], "token_budget": 120},
                )
                assert not targeted_snapshot.isError
                targeted_snapshot_payload = targeted_snapshot.structuredContent  # type: ignore[assignment]
                assert flow.id in str(targeted_snapshot.content)
                assert targeted_snapshot_payload["target_flow_ids"] == [flow.id]  # type: ignore[index]
                assert targeted_snapshot_payload["unresolved_targets"] == []  # type: ignore[index]
                dependency_impact = await session.call_tool(
                    "analyze_impact",
                    {"dependency_paths": ["./app.py"], "token_budget": 120},
                )
                assert not dependency_impact.isError
                dependency_payload = dependency_impact.structuredContent  # type: ignore[assignment]
                assert dependency_payload["changed_files"] == []  # type: ignore[index]
                assert dependency_payload["target_dependency_paths"] == ["app.py"]  # type: ignore[index]
                assert dependency_payload["impact_reasons"] == {  # type: ignore[index]
                    flow.id: ["dependency path target `app.py`"]
                }
                dependency_snapshot = await session.call_tool(
                    "get_impact_snapshot",
                    {"dependency_paths": ["./app.py"], "token_budget": 120},
                )
                assert not dependency_snapshot.isError
                dependency_snapshot_payload = dependency_snapshot.structuredContent  # type: ignore[assignment]
                assert dependency_snapshot_payload["target_dependency_paths"] == [  # type: ignore[index]
                    "app.py"
                ]
                missing_target_snapshot = await session.call_tool(
                    "get_impact_snapshot",
                    {"flow_ids": ["missing-flow"], "token_budget": 120},
                )
                assert not missing_target_snapshot.isError
                missing_target_payload = missing_target_snapshot.structuredContent  # type: ignore[assignment]
                assert missing_target_payload["target_flow_ids"] == [  # type: ignore[index]
                    "missing-flow"
                ]
                assert missing_target_payload["unresolved_targets"] == [  # type: ignore[index]
                    {"type": "flow", "value": "missing-flow", "reason": "not_found"}
                ]
                assert "Unresolved targets: flow:missing-flow" in str(
                    missing_target_snapshot.content
                )

                context = await session.call_tool(
                    "context_pack",
                    {"question": "admin authorization", "changed_files": ["app.py"]},
                )
                assert not context.isError
                assert "impact" in str(context.content)
                context_payload = context.structuredContent  # type: ignore[assignment]
                assert context_payload["visual_context"]["include_visual"] is False  # type: ignore[index]
                assert (
                    context_payload["visual_context"]["next_tools"]["impact_snapshot"]["tool"]  # type: ignore[index]
                    == "get_impact_snapshot"
                )
                context_navigation = context_payload["navigation"]  # type: ignore[index]
                assert context_navigation["flow_budget"] >= 1
                assert context_navigation["flows"][0]["flow"]["id"] == flow.id
                assert context_navigation["flows"][0]["annotations"]["flow"] == {
                    "label": "Annotated authorization",
                    "summary": "Agent-authored summary for authorization.",
                }
                assert (
                    context_navigation["next_tools"]["flow_navigation"][0]["tool"]
                    == "get_flow_navigation"
                )
                targeted_context = await session.call_tool(
                    "context_pack",
                    {"flow_ids": [flow.id], "token_budget": 120},
                )
                assert not targeted_context.isError
                targeted_context_payload = targeted_context.structuredContent  # type: ignore[assignment]
                targeted_impact = targeted_context_payload["impact"]  # type: ignore[index]
                assert targeted_impact["changed_files"] == []
                assert targeted_impact["target_flow_ids"] == [flow.id]
                assert targeted_impact["impact_reasons"] == {
                    flow.id: [f"explicit flow target `{flow.id}`"]
                }
                assert targeted_impact["direct"][0]["reasons"] == [
                    f"explicit flow target `{flow.id}`"
                ]
                assert flow.id in targeted_impact["subgraph_flow_ids"]
                impact_next_args = targeted_context_payload["visual_context"]["next_tools"][  # type: ignore[index]
                    "impact_snapshot"
                ]["arguments"]
                assert impact_next_args["flow_ids"] == [flow.id]
                subgraph_next_args = targeted_context_payload["visual_context"]["next_tools"][  # type: ignore[index]
                    "subgraph_snapshot"
                ]["arguments"]
                assert subgraph_next_args["flow_ids"] == [flow.id]
                targeted_navigation = targeted_context_payload["navigation"]  # type: ignore[index]
                assert targeted_navigation["flow_budget"] == 1
                assert targeted_navigation["per_flow_token_budget"] == 120
                assert targeted_navigation["flows"][0]["flow"]["id"] == flow.id
                assert (
                    targeted_navigation["flows"][0]["next_tools"]["complete_flow"]["tool"]
                    == "get_flow"
                )
                dependency_context = await session.call_tool(
                    "context_pack",
                    {"dependency_paths": ["./app.py"], "token_budget": 120},
                )
                assert not dependency_context.isError
                dependency_context_payload = dependency_context.structuredContent  # type: ignore[assignment]
                dependency_impact_payload = dependency_context_payload["impact"]  # type: ignore[index]
                assert dependency_impact_payload["target_dependency_paths"] == ["app.py"]
                dependency_next_args = dependency_context_payload["visual_context"][  # type: ignore[index]
                    "next_tools"
                ]["impact_snapshot"]["arguments"]
                assert dependency_next_args["dependency_paths"] == ["app.py"]

                validation = await session.call_tool("validate_artifacts", {})
                assert not validation.isError
                assert "ok" in str(validation.content)
                validation_quality = await session.call_tool(
                    "validate_artifacts",
                    {"include_quality": True},
                )
                assert not validation_quality.isError
                assert "quality" in str(validation_quality.content)
                validation_threshold = await session.call_tool(
                    "validate_artifacts",
                    {"max_skipped_files": 0, "max_parse_warnings": 0},
                )
                assert not validation_threshold.isError
                assert "quality" in str(validation_threshold.content)
                role_domain = await session.call_tool(
                    "domain_map",
                    {"domain": "role", "value": "admin", "token_budget": 360},
                )
                assert not role_domain.isError
                role_domain_payload = role_domain.structuredContent  # type: ignore[assignment]
                assert role_domain_payload["tool"] == "domain_map"  # type: ignore[index]
                role_concept = role_domain_payload["concepts"][0]  # type: ignore[index]
                assert role_concept["domain"] == "role"
                assert role_concept["handled_values"] == ["admin"]
                assert role_concept["subgraph_flow_ids"] == [flow.id]
                assert (  # type: ignore[index]
                    role_concept["next_tools"]["subgraph_snapshot"]["tool"]
                    == "get_subgraph_snapshot"
                )
                role_context = await session.call_tool(
                    "agent_context",
                    {
                        "question": "where is admin role handled?",
                        "domain": "role",
                        "value": "admin",
                        "token_budget": 360,
                    },
                )
                assert not role_context.isError
                role_context_payload = role_context.structuredContent  # type: ignore[assignment]
                assert role_context_payload["domain_map"]["concepts"][0]["domain"] == "role"  # type: ignore[index]
                clear_without_confirm = await session.call_tool("clear_annotations", {})
                assert not clear_without_confirm.isError
                assert (  # type: ignore[index]
                    clear_without_confirm.structuredContent["error_code"]
                    == "annotation_clear_confirmation_required"
                )
                clear_annotations = await session.call_tool(
                    "clear_annotations",
                    {"confirm": True},
                )
                assert not clear_annotations.isError
                clear_payload = clear_annotations.structuredContent  # type: ignore[assignment]
                assert clear_payload["status"] == "absent"  # type: ignore[index]
                assert clear_payload["cleared"] is True  # type: ignore[index]

                state = await session.call_tool("where_state_handled", {"domain": "role"})
                assert not state.isError
                assert "authorize" in str(state.content)

    asyncio.run(exercise_server())


def test_query_model_and_mcp_query_logic_have_same_shape(tmp_path: Path) -> None:
    """MCP query_logic uses the same QueryMatch serializer as the deterministic model."""
    source = tmp_path / "app.py"
    source.write_text(
        "def authorize(user):\n"
        "    if user.role == 'admin':\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)

    (tmp_path / "orders.py").write_text(
        "def route(order):\n"
        "    if order.status == 'draft':\n"
        "        return draft(order)\n"
        "    elif order.status == 'paid':\n"
        "        return paid(order)\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    assert result.model.findings
    expected_rows = [match.to_dict() for match in query_model(result.model, "admin authorize")]
    expected_finding_rows = [
        match.to_dict()
        for match in query_model(
            result.model,
            "",
            finding_kind="missing_branch",
            finding_severity="warning",
            finding_evidence="POTENTIAL_GAP",
        )
    ]

    mcp_rows: list[dict[str, object]] = []
    mcp_finding_rows: list[dict[str, object]] = []
    mcp_context_payloads: list[dict[str, object]] = []

    async def call_mcp() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool("query_logic", {"question": "admin authorize"})
                assert not response.isError
                # A list-returning tool puts the full list under structuredContent.result
                # (each content block is one item serialized on its own).
                payload = response.structuredContent["result"]  # type: ignore[index]
                mcp_rows.extend(payload)
                finding_response = await session.call_tool(
                    "query_logic",
                    {
                        "question": "",
                        "finding_kind": "missing_branch",
                        "finding_severity": "warning",
                        "finding_evidence": "POTENTIAL_GAP",
                    },
                )
                assert not finding_response.isError
                finding_payload = finding_response.structuredContent["result"]  # type: ignore[index]
                mcp_finding_rows.extend(finding_payload)
                context_response = await session.call_tool(
                    "context_pack",
                    {
                        "question": "",
                        "finding_kind": "missing_branch",
                        "finding_severity": "warning",
                        "finding_evidence": "POTENTIAL_GAP",
                        "token_budget": 240,
                    },
                )
                assert not context_response.isError
                mcp_context_payloads.append(context_response.structuredContent)  # type: ignore[arg-type]

    asyncio.run(call_mcp())

    assert expected_rows == mcp_rows
    assert expected_rows
    assert expected_finding_rows == mcp_finding_rows
    assert expected_finding_rows
    assert any(
        "finding evidence matches `POTENTIAL_GAP`" in row["reasons"]
        for row in expected_finding_rows
    )
    assert len(mcp_context_payloads) == 1
    context_payload = mcp_context_payloads[0]
    assert context_payload["query_filters"] == {
        "finding_kind": "missing_branch",
        "finding_severity": "warning",
        "finding_evidence": "POTENTIAL_GAP",
    }
    assert context_payload["query"] == expected_finding_rows
    assert context_payload["review"]
    assert {
        (row["kind"], row["severity"], row["evidence"]) for row in context_payload["review"]
    } == {("missing_branch", "warning", "POTENTIAL_GAP")}
    for row in expected_rows:
        assert set(row) == {
            "flow_id",
            "name",
            "language",
            "entry_kind",
            "framework",
            "scope",
            "score",
            "reasons",
            "finding_count",
            "finding_ids",
            "finding_kinds",
            "finding_severities",
            "finding_evidence",
            "omitted_finding_count",
            "subgraph_flow_ids",
            "subgraph_finding_ids",
            "next_tools",
            "source",
        }
        assert row["next_tools"]["flow_navigation"]["tool"] == "get_flow_navigation"
        assert row["next_tools"]["context_pack"]["tool"] == "context_pack"
        assert row["next_tools"]["subgraph_snapshot"]["tool"] == "get_subgraph_snapshot"
        assert row["subgraph_flow_ids"] == [row["flow_id"]]
    for row in expected_finding_rows:
        assert row["finding_count"] == 1
        assert row["finding_ids"]
        assert row["finding_kinds"] == ["missing_branch"]
        assert row["finding_severities"] == ["warning"]
        assert row["finding_evidence"] == ["POTENTIAL_GAP"]
        assert row["subgraph_finding_ids"] == row["finding_ids"]
        assert (
            row["next_tools"]["subgraph_snapshot"]["arguments"]["finding_ids"] == row["finding_ids"]
        )


def test_domain_map_does_not_attach_findings_to_unrelated_same_flow_domain(
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        """
def route(user, order):
    if user.role == "admin":
        audit(user)
    if order.status == "draft":
        return draft(order)
    elif order.status == "paid":
        return paid(order)
    return fallback(order)
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    payload = _domain_logic_map(
        model,
        domain=None,
        value=None,
        scope=None,
        token_budget=0,
    )

    concepts = {row["domain"]: row for row in payload["concepts"]}
    assert concepts["status"]["finding_count"] == 1
    assert [item["kind"] for item in concepts["status"]["findings"]] == ["missing_branch"]
    assert concepts["role"]["finding_count"] == 0
    assert concepts["role"]["findings"] == []


def test_domain_map_keeps_enum_exhaustiveness_findings_on_matching_domain(
    tmp_path: Path,
) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        """
from enum import Enum


class Status(Enum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"


def route(status):
    if status == Status.DRAFT:
        return draft()
    elif status == Status.OPEN:
        return open_order()
    return fallback()
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    payload = _domain_logic_map(
        model,
        domain="Status",
        value=None,
        scope=None,
        token_budget=0,
    )

    assert len(payload["concepts"]) == 1
    concept = payload["concepts"][0]
    assert concept["domain"] == "Status"
    assert concept["missing_values"] == ["Status.PAID"]
    assert [item["kind"] for item in concept["findings"]] == ["enum_exhaustiveness"]


def test_mcp_model_load_errors_are_structured_and_actionable(tmp_path: Path) -> None:
    async def call_with_missing_artifact() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                summary = await session.call_tool("logicchart_summary", {})
                assert not summary.isError
                payload = summary.structuredContent  # type: ignore[assignment]
                assert payload["error_code"] == "artifact_missing"  # type: ignore[index]
                assert payload["recoverable"] is True  # type: ignore[index]
                assert "logical finding" in payload["guardrail"]  # type: ignore[index]
                assert (  # type: ignore[index]
                    payload["next_tools"]["update_model"]["tool"] == "update_logicchart"
                )
                assert "logicchart update --full" in payload["next_cli"]  # type: ignore[index]

                flows = await session.call_tool("list_flows", {})
                assert not flows.isError
                rows = flows.structuredContent["result"]  # type: ignore[index]
                assert rows[0]["error_code"] == "artifact_missing"
                assert rows[0]["artifact"].endswith("logicchart-out/logic-flow.json")

    asyncio.run(call_with_missing_artifact())

    artifact = tmp_path / "logicchart-out" / "logic-flow.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("{", encoding="utf-8")

    async def call_with_malformed_artifact() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                summary = await session.call_tool("logicchart_summary", {})
                assert not summary.isError
                payload = summary.structuredContent  # type: ignore[assignment]
                assert payload["error_code"] == "artifact_malformed_json"  # type: ignore[index]
                assert "invalid JSON" in payload["detail"]  # type: ignore[index]

                validation = await session.call_tool("validate_artifacts", {})
                assert not validation.isError
                validation_payload = validation.structuredContent  # type: ignore[assignment]
                assert validation_payload["ok"] is False  # type: ignore[index]
                assert "Malformed JSON" in validation_payload["errors"][0]  # type: ignore[index]

    asyncio.run(call_with_malformed_artifact())


def test_mcp_update_validate_sequence_after_source_change(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def primary(flag):\n    if flag:\n        return 'yes'\n    return 'no'\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    source.write_text(
        "def primary(flag):\n"
        "    if flag:\n"
        "        return 'yes'\n"
        "    return 'no'\n\n"
        "def secondary(value):\n"
        "    if value == 'open':\n"
        "        return primary(True)\n"
        "    return primary(False)\n",
        encoding="utf-8",
    )

    async def exercise_update_validate() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                stale = await session.call_tool("validate_artifacts", {"check_sync": True})
                assert not stale.isError
                stale_payload = stale.structuredContent  # type: ignore[assignment]
                assert stale_payload["ok"] is False  # type: ignore[index]
                assert "stale" in stale_payload["errors"][0]  # type: ignore[index]
                assert (  # type: ignore[index]
                    stale_payload["next_tools"]["update_model"]["tool"] == "update_logicchart"
                )
                assert "logicchart update --full" in stale_payload["next_cli"]  # type: ignore[index]

                update = await session.call_tool("update_logicchart", {"full": True})
                assert not update.isError
                update_payload = update.structuredContent  # type: ignore[assignment]
                assert "app.py" in update_payload["changed_files"]  # type: ignore[index]
                assert update_payload["flows"] >= 2  # type: ignore[index]
                assert (  # type: ignore[index]
                    update_payload["next_tools"]["validate_artifacts"]["arguments"]
                    == {"check_sync": True, "include_quality": True}
                )
                assert update_payload["next_artifacts"]["commit"][0].endswith(  # type: ignore[index]
                    "logic-flow.json"
                )

                fresh = await session.call_tool(
                    "validate_artifacts",
                    {"check_sync": True, "include_quality": True},
                )
                assert not fresh.isError
                fresh_payload = fresh.structuredContent  # type: ignore[assignment]
                assert fresh_payload["ok"] is True  # type: ignore[index]
                assert "quality" in fresh_payload
                assert (  # type: ignore[index]
                    fresh_payload["next_tools"]["analysis_quality"]["tool"] == "analysis_quality"
                )

                query = await session.call_tool("query_logic", {"question": "secondary"})
                assert not query.isError
                assert "secondary" in str(query.content)

    asyncio.run(exercise_update_validate())


def test_analysis_quality_report_bounds_language_attention() -> None:
    quality = {
        "files": {
            "skipped": {"total": 0, "sample": []},
            "parse_errors": {
                "total": 2,
                "sample": [
                    {"path": "partial.ts", "language": "typescript", "line": 4},
                    {"path": "partial.go", "language": "go", "line": 9},
                ],
            },
        },
        "flows": {"huge": []},
        "calls": {"unresolved": 0, "ambiguous": 0},
        "labels": {"generic_nodes": 0, "sample": []},
        "graph": {},
        "languages": {
            "attention": [
                {"language": "python", "signals": ["low_call_resolution"]},
                {"language": "typescript", "signals": ["generic_labels"]},
            ],
            "depth": {
                "python": {"files": 3, "flows": 8},
                "typescript": {"files": 4, "flows": 9},
            },
        },
    }

    report = _quality_report(quality, token_budget=120)

    assert report["guardrail"].startswith("Quality attention signals")
    assert report["next_tools"]["validate_quality"]["tool"] == "validate_artifacts"
    languages = report["quality"]["languages"]
    assert list(languages["depth"]) == ["python"]
    assert languages["attention"] == [{"language": "python", "signals": ["low_call_resolution"]}]
    assert languages["omitted_language_count"] == 1
    assert report["quality"]["files"]["parse_errors"]["sample"] == [
        {"path": "partial.ts", "language": "typescript", "line": 4}
    ]
    assert report["attention"][0]["type"] == "parse_warnings"
    assert (
        report["attention"][0]["next_tools"]["validate_parse_warnings"]["arguments"][
            "max_parse_warnings"
        ]
        == 0
    )
    assert [item.get("language") for item in report["attention"][1:]] == [
        "python",
    ]
    assert (
        report["attention"][1]["next_tools"]["query_language"]["arguments"]["language"] == "python"
    )


def test_mcp_enrichment_preview_payload_contract(tmp_path: Path) -> None:
    source = tmp_path / "orders.py"
    source.write_text(
        "def route(order):\n"
        "    if order.status == 'draft':\n"
        "        return draft(order)\n"
        "    elif order.status == 'paid':\n"
        "        return paid(order)\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    config = LogicChartConfig.load(tmp_path)
    finding = result.model.findings[0]
    options = _enrichment_options(
        scope=None,
        flow_ids=None,
        finding_ids=[finding.id],
        max_flows=8,
        max_nodes_per_flow=12,
        max_findings=12,
        token_budget=240,
    )
    preview = build_enrichment_preview(tmp_path, result.model, config, options)

    payload = _enrichment_preview_payload(
        preview,
        token_budget=240,
    )

    assert payload["provider_call_made"] is False
    assert payload["request"]["selection"]["max_flows"] == 1
    assert payload["request"]["selection"]["max_nodes_per_flow"] == 4
    assert payload["targets"]["flow_ids"] == [finding.flow_id]
    assert payload["targets"]["finding_ids"] == [finding.id]
    assert payload["next_tools"]["review_queue"]["tool"] == "review_queue"
    assert payload["next_tools"]["subgraph_snapshot"]["arguments"]["finding_ids"] == [finding.id]
    assert "next_cli" not in payload
    assert "logicchart validate" in payload["next_actions"][2]
    assert "agent-authored annotations" in payload["guardrail"]


def test_mcp_context_visual_pack_direct_contracts(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def dispatch(order):\n"
        "    if order.status == Status.OPEN:\n"
        "        return 'open'\n"
        "    elif order.status == Status.CLOSED:\n"
        "        return 'closed'\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    model = result.model
    finding = model.findings[0]
    flow = next(item for item in model.flows if item.id == finding.flow_id)
    impact = impact_model(model, [], flow_ids=[flow.id])

    payload = _context_visual_pack(
        model,
        impact=impact,
        matches=[],
        review_findings=[finding],
        scope=None,
        include_visual=True,
        token_budget=120,
        visual_byte_budget=200_000,
    )

    assert payload["include_visual"] is True
    assert payload["next_tools"]["impact_snapshot"]["arguments"]["flow_ids"] == [flow.id]
    assert payload["next_tools"]["subgraph_snapshot"]["arguments"] == {
        "flow_ids": [flow.id],
        "finding_ids": [finding.id],
        "format": "svg",
        "token_budget": 120,
    }
    assert payload["impact_snapshot"]["format"] == "svg"
    assert payload["impact_snapshot"]["layout_quality"]["status"] == "complete"
    assert payload["subgraph_snapshot"]["layout"]["engine"] == "static-subgraph-snapshot-v1"
    assert payload["subgraph_snapshot"]["layout_quality"]["status"] == "compact"
    assert payload["subgraph_snapshot"]["layout_quality"]["counts"]["omitted_node_count"] >= 1
    assert payload["subgraph_snapshot"]["rendered_flow_ids"] == [flow.id]
    assert payload["subgraph_snapshot"]["finding_ids"] == [finding.id]
    assert payload["flow_snapshots"][0]["flow_id"] == flow.id
    assert payload["flow_snapshots"][0]["layout_quality"]["status"] == "compact"
    assert payload["flow_snapshots"][0]["layout_quality"]["counts"]["omitted_node_count"] >= 1
    assert payload["finding_snapshots"][0]["finding_id"] == finding.id
    assert payload["finding_snapshots"][0]["layout_quality"]["counts"]["rendered_node_count"] >= 1
    assert payload["snapshot_budget"]["used_visual_bytes"] > 0

    capped = _context_visual_pack(
        model,
        impact=impact,
        matches=[],
        review_findings=[finding],
        scope=None,
        include_visual=True,
        token_budget=120,
        visual_byte_budget=1,
    )

    assert "impact_snapshot" not in capped
    assert capped["impact_snapshot_omitted_reason"] == "visual_byte_budget"
    assert "subgraph_snapshot" not in capped
    assert capped["subgraph_snapshot_omitted_reason"] == "visual_byte_budget"
    assert capped["flow_snapshots"] == []
    assert capped["finding_snapshots"] == []
    assert capped["omitted_visual_snapshot_reasons"] == {
        "visual_byte_budget": capped["omitted_visual_snapshot_count"]
    }


def test_mcp_context_navigation_pack_direct_contracts(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def dispatch(order):\n"
        "    if order.status == 'open':\n"
        "        return handle_open(order)\n"
        "    return handle_default(order)\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    model = result.model
    flow = next(item for item in model.flows if item.name == "dispatch")
    impact = impact_model(model, [], flow_ids=[flow.id])

    payload = _context_navigation_pack(
        model,
        impact=impact,
        matches=[],
        annotations=None,
        token_budget=120,
    )

    assert payload["flow_budget"] == 1
    assert payload["per_flow_token_budget"] == 120
    assert payload["flows"][0]["flow"]["id"] == flow.id
    assert payload["flows"][0]["next_tools"]["complete_flow"]["tool"] == "get_flow"
    assert payload["next_tools"]["flow_navigation"] == [
        {
            "tool": "get_flow_navigation",
            "arguments": {"flow_id": flow.id, "token_budget": 120},
        }
    ]
    assert payload["omitted_flow_navigation_count"] == 0


def test_mcp_recovery_payload_helpers_are_actionable(tmp_path: Path) -> None:
    config = LogicChartConfig()

    missing = _model_load_error(tmp_path, config, FileNotFoundError("missing artifact"))
    assert missing["error_code"] == "artifact_missing"
    assert missing["recoverable"] is True
    assert missing["artifact"].endswith("logicchart-out/logic-flow.json")
    assert missing["next_tools"]["update_model"]["tool"] == "update_logicchart"
    assert "logicchart update --full" in missing["next_cli"]

    malformed = _model_load_error(tmp_path, config, ValueError("invalid JSON in artifact"))
    assert malformed["error_code"] == "artifact_malformed_json"

    unknown_flow = _unknown_target_error("flow", "missing-flow")
    assert unknown_flow["error_code"] == "flow_not_found"
    assert unknown_flow["next_tools"]["list_flows"]["tool"] == "list_flows"
    assert unknown_flow["next_tools"]["query_logic"]["arguments"]["question"] == "missing-flow"

    unknown_finding = _unknown_target_error("finding", "missing-finding")
    assert unknown_finding["error_code"] == "finding_not_found"
    assert unknown_finding["next_tools"]["review_queue"]["tool"] == "review_queue"

    stale = _validation_payload({"ok": False, "errors": ["stale"], "warnings": []})
    assert stale["next_tools"]["update_model"]["tool"] == "update_logicchart"
    assert stale["next_cli"] == [
        "logicchart update --full",
        "logicchart validate --check-sync --json",
    ]

    fresh = _validation_payload({"ok": True, "errors": [], "warnings": []})
    assert "update_model" not in fresh["next_tools"]
    assert "logicchart view" in fresh["next_cli"]

    workflow = _update_workflow_payload(
        tmp_path / "logicchart-out" / "logic-flow.json",
        tmp_path / "logicchart-out" / "logic-flow.md",
        None,
    )
    assert workflow["next_tools"]["validate_artifacts"]["arguments"] == {
        "check_sync": True,
        "include_quality": True,
    }
    assert workflow["next_artifacts"]["local_html"] is None
    assert workflow["next_artifacts"]["commit"][0].endswith("logic-flow.json")


def test_mcp_review_queue_prioritizes_findings(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def dispatch(order):\n"
        "    if order.status == Status.OPEN:\n"
        "        return 'open'\n"
        "    elif order.status == Status.CLOSED:\n"
        "        return 'closed'\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)

    captured: list[dict[str, object]] = []

    async def call_review_queue() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool("review_queue", {"token_budget": 120})
                assert not response.isError
                captured.extend(response.structuredContent["result"])  # type: ignore[index]
                snapshot = await session.call_tool(
                    "get_finding_snapshot",
                    {"finding_id": captured[0]["id"]},
                )
                assert not snapshot.isError
                assert "<svg" in str(snapshot.content)
                subgraph_snapshot = await session.call_tool(
                    "get_subgraph_snapshot",
                    {"finding_ids": [captured[0]["id"]], "token_budget": 160},
                )
                assert not subgraph_snapshot.isError
                subgraph_payload = subgraph_snapshot.structuredContent  # type: ignore[assignment]
                assert subgraph_payload["finding_ids"] == [captured[0]["id"]]  # type: ignore[index]
                assert subgraph_payload["highlighted_node_ids"]  # type: ignore[index]
                context = await session.call_tool(
                    "get_finding_context",
                    {"finding_id": captured[0]["id"], "token_budget": 160},
                )
                assert not context.isError
                payload = context.structuredContent  # type: ignore[assignment]
                assert payload["finding"]["id"] == captured[0]["id"]  # type: ignore[index]
                assert payload["evidence_guardrail"]["tier"] == "POTENTIAL_GAP"  # type: ignore[index]
                assert payload["focus_flow"]["name"] == "dispatch"  # type: ignore[index]
                assert payload["related_nodes"]  # type: ignore[index]
                assert (
                    payload["next_tools"]["visual_snapshot"]["tool"]  # type: ignore[index]
                    == "get_finding_snapshot"
                )
                assert (
                    payload["next_tools"]["subgraph_snapshot"]["tool"]  # type: ignore[index]
                    == "get_subgraph_snapshot"
                )
                explanation = await session.call_tool(
                    "explain_finding_chain",
                    {"finding_id": captured[0]["id"], "token_budget": 160},
                )
                assert not explanation.isError
                assert "get_finding_context" in str(explanation.content)
                visual_context = await session.call_tool(
                    "context_pack",
                    {
                        "question": "dispatch status",
                        "changed_files": ["app.py"],
                        "include_visual": True,
                        "token_budget": 120,
                    },
                )
                assert not visual_context.isError
                visual_payload = visual_context.structuredContent  # type: ignore[assignment]
                visual = visual_payload["visual_context"]  # type: ignore[index]
                assert visual["include_visual"] is True
                assert visual["impact_snapshot"]["format"] == "svg"
                assert "unresolved_targets" in visual["impact_snapshot"]
                assert "<svg" in visual["impact_snapshot"]["svg"]
                assert visual["subgraph_snapshot"]["format"] == "svg"
                assert visual["subgraph_snapshot"]["finding_ids"] == [captured[0]["id"]]
                assert "<svg" in visual["subgraph_snapshot"]["svg"]
                assert visual["flow_snapshots"]
                assert visual["finding_snapshots"]
                assert visual["flow_snapshots"][0]["rendered_node_count"] >= 1
                assert visual["finding_snapshots"][0]["finding_id"] == captured[0]["id"]
                assert visual["snapshot_budget"]["flow_snapshots"] == 1
                assert visual["snapshot_budget"]["used_visual_bytes"] > 0
                capped_visual_context = await session.call_tool(
                    "context_pack",
                    {
                        "question": "dispatch status",
                        "changed_files": ["app.py"],
                        "include_visual": True,
                        "token_budget": 120,
                        "visual_byte_budget": 1,
                    },
                )
                assert not capped_visual_context.isError
                capped_payload = capped_visual_context.structuredContent  # type: ignore[assignment]
                capped_visual = capped_payload["visual_context"]  # type: ignore[index]
                assert capped_visual["include_visual"] is True
                assert capped_visual["snapshot_budget"]["visual_byte_budget"] == 1
                assert capped_visual["snapshot_budget"]["used_visual_bytes"] == 0
                assert "impact_snapshot" not in capped_visual
                assert capped_visual["impact_snapshot_omitted_reason"] == "visual_byte_budget"
                assert "subgraph_snapshot" not in capped_visual
                assert capped_visual["subgraph_snapshot_omitted_reason"] == "visual_byte_budget"
                assert capped_visual["flow_snapshots"] == []
                assert capped_visual["finding_snapshots"] == []
                assert capped_visual["omitted_visual_snapshot_count"] >= 3
                assert capped_visual["omitted_visual_snapshot_reasons"] == {
                    "visual_byte_budget": capped_visual["omitted_visual_snapshot_count"]
                }
                assert (
                    capped_visual["next_tools"]["impact_snapshot"]["tool"]  # type: ignore[index]
                    == "get_impact_snapshot"
                )
                assert (
                    capped_visual["next_tools"]["subgraph_snapshot"]["tool"]  # type: ignore[index]
                    == "get_subgraph_snapshot"
                )

    asyncio.run(call_review_queue())

    assert captured
    assert captured[0]["kind"] == "missing_branch"
    assert "flow" in captured[0]
    diagnostic = captured[0]["metadata"]["diagnostic"]
    assert diagnostic["rule_id"] == "missing_branch"
    assert diagnostic["review_prompt"]
    assert diagnostic["suggested_next_actions"]


def test_get_flow_subgraph_is_internally_consistent(tmp_path: Path) -> None:
    """Capping nodes by token_budget must also drop edges whose endpoints were removed,
    so get_flow never returns a dangling-edge subgraph."""
    source = tmp_path / "app.py"
    source.write_text(
        "def authorize(user):\n"
        "    if user.role == 'admin':\n"
        "        return allow()\n"
        "    elif user.role == 'staff':\n"
        "        return review()\n"
        "    return deny()\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    flow = next(f for f in load_model(tmp_path).flows if f.name == "authorize")

    captured: dict[str, object] = {}

    async def call_get_flow() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(
                    "get_flow", {"flow_id": flow.id, "token_budget": 90}
                )
                assert not response.isError
                # A dict-returning tool exposes the object directly via structuredContent.
                captured.update(response.structuredContent)  # type: ignore[arg-type]

    asyncio.run(call_get_flow())

    flow_dict = captured["flow"]
    node_ids = {node["id"] for node in flow_dict["nodes"]}  # type: ignore[index]
    # Budget was small enough to drop some nodes...
    assert len(node_ids) < len(flow.nodes)
    # ...and every surviving edge still connects two surviving nodes.
    for edge in flow_dict["edges"]:  # type: ignore[index]
        assert edge["source"] in node_ids
        assert edge["target"] in node_ids
