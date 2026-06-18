import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.annotations import annotations_path, model_hash
from logicchart.artifacts import load_model, write_artifacts
from logicchart.cli import main as cli_main
from logicchart.mcp_server import MCP_INSTRUCTIONS, _quality_report


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
                    "analysis_quality",
                    "explain_finding_chain",
                    "get_finding_context",
                    "finding_rules",
                    "get_flow_navigation",
                    "get_flow_snapshot",
                    "get_finding_snapshot",
                    "get_impact_snapshot",
                    "where_state_handled",
                    "find_decision_nodes",
                    "review_queue",
                    "context_pack",
                    "validate_artifacts",
                } <= names

                # Spec §5.2: every query/list tool exposes a token_budget cap.
                schema_by_name = {tool.name: tool.inputSchema for tool in tools.tools}
                for budget_tool in (
                    "get_flow",
                    "get_flow_navigation",
                    "get_flow_snapshot",
                    "get_finding_snapshot",
                    "get_impact_snapshot",
                    "query_logic",
                    "analysis_quality",
                    "explain_finding_chain",
                    "get_finding_context",
                    "finding_rules",
                    "analyze_impact",
                    "review_queue",
                    "context_pack",
                ):
                    properties = schema_by_name[budget_tool].get("properties", {})
                    assert "token_budget" in properties, budget_tool
                context_properties = schema_by_name["context_pack"].get("properties", {})
                assert {"flow_ids", "symbols", "finding_ids"} <= set(context_properties)

                response = await session.call_tool(
                    "query_logic",
                    {"question": "admin authorization", "limit": 5},
                )
                assert not response.isError
                assert "authorize" in str(response.content)
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
                assert flow.id in str(targeted_snapshot.content)

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
                    {"max_skipped_files": 0},
                )
                assert not validation_threshold.isError
                assert "quality" in str(validation_threshold.content)

                state = await session.call_tool("where_state_handled", {"domain": "role"})
                assert not state.isError
                assert "authorize" in str(state.content)

    asyncio.run(exercise_server())


def test_cli_json_and_mcp_query_logic_have_same_shape(tmp_path: Path, capsys: object) -> None:
    """The CLI `query --json` and the MCP `query_logic` tool share one serializer
    (QueryMatch.to_dict), so identical inputs yield identical JSON rows."""
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

    assert cli_main(["query", "admin authorize", "--path", str(tmp_path), "--json"]) == 0
    cli_rows = json.loads(capsys.readouterr().out)  # type: ignore[attr-defined]

    mcp_rows: list[dict[str, object]] = []

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

    asyncio.run(call_mcp())

    assert cli_rows == mcp_rows
    assert cli_rows
    for row in cli_rows:
        assert set(row) == {
            "flow_id",
            "name",
            "language",
            "entry_kind",
            "framework",
            "scope",
            "score",
            "reasons",
            "source",
        }


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
                assert "logicchart analyze --full" in payload["next_cli"]  # type: ignore[index]

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


def test_analysis_quality_report_bounds_language_attention() -> None:
    quality = {
        "files": {"skipped": {"total": 0, "sample": []}},
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
    assert [item["language"] for item in report["attention"]] == ["python", "typescript"]
    assert (
        report["attention"][0]["next_tools"]["query_language"]["arguments"]["language"] == "python"
    )


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
                assert "<svg" in visual["impact_snapshot"]["svg"]
                assert visual["flow_snapshots"]
                assert visual["finding_snapshots"]
                assert visual["flow_snapshots"][0]["rendered_node_count"] >= 1
                assert visual["finding_snapshots"][0]["finding_id"] == captured[0]["id"]
                assert visual["snapshot_budget"]["flow_snapshots"] == 1

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
