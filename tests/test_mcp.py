import asyncio
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.artifacts import write_artifacts


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

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "logicchart.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"list_flows", "get_flow", "query_logic", "update_logicchart"} <= names
                assert {
                    "logicchart_summary",
                    "explain_finding_chain",
                    "where_state_handled",
                    "find_decision_nodes",
                    "diff_findings",
                } <= names

                response = await session.call_tool(
                    "query_logic",
                    {"question": "admin authorization", "limit": 5},
                )
                assert not response.isError
                assert "authorize" in str(response.content)

                summary = await session.call_tool("logicchart_summary", {})
                assert not summary.isError
                assert "flows" in str(summary.content)

                state = await session.call_tool("where_state_handled", {"domain": "role"})
                assert not state.isError
                assert "authorize" in str(state.content)

    asyncio.run(exercise_server())
