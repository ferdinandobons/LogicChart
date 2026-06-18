import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.artifacts import load_model, write_artifacts
from logicchart.cli import main as cli_main
from logicchart.mcp_server import MCP_INSTRUCTIONS


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
                    "explain_finding_chain",
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
                    "query_logic",
                    "explain_finding_chain",
                    "finding_rules",
                    "analyze_impact",
                    "review_queue",
                    "context_pack",
                ):
                    properties = schema_by_name[budget_tool].get("properties", {})
                    assert "token_budget" in properties, budget_tool

                response = await session.call_tool(
                    "query_logic",
                    {"question": "admin authorization", "limit": 5},
                )
                assert not response.isError
                assert "authorize" in str(response.content)

                summary = await session.call_tool("logicchart_summary", {})
                assert not summary.isError
                assert "flows" in str(summary.content)
                assert "finding_rules" in str(summary.content)
                assert "quality" in str(summary.content)
                assert "language_capabilities" in str(summary.content)

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

                context = await session.call_tool(
                    "context_pack",
                    {"question": "admin authorization", "changed_files": ["app.py"]},
                )
                assert not context.isError
                assert "impact" in str(context.content)

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
