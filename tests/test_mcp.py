from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from codedebrief.analysis.project import ProjectAnalyzer
from codedebrief.artifacts import write_artifacts
from codedebrief.config import CodeDebriefConfig
from codedebrief.mcp_server import (
    MCP_INSTRUCTIONS,
    _agent_action_terms,
    _agent_context_effective_token_budget,
    _context_navigation_pack,
    _context_visual_pack,
    _domain_logic_map,
    _McpModelStore,
    _model_load_error,
    _selection_context_payload,
    _unknown_target_error,
    _update_workflow_payload,
    _validation_payload,
    _workflow_slice_payload,
    flow_in_agent_scope,
)
from codedebrief.model import (
    FileRecord,
    Flow,
    FlowEdge,
    FlowNode,
    NodeKind,
    ProjectModel,
    SourceLocation,
)
from codedebrief.query import impact_model

PUBLIC_MCP_TOOLS = {
    "agent_context",
    "expand_slice",
    "workflow_path",
    "snapshot_slice",
    "explain_flow",
    "explain_node",
    "explain_edge",
    "validate_artifacts",
    "update_codedebrief",
}


def test_flow_in_agent_scope_normalizes_legacy_string_scope() -> None:
    flow = SimpleNamespace(metadata={"scope": "frontend"})

    assert flow_in_agent_scope(flow, "frontend")
    assert not flow_in_agent_scope(flow, "front")


def test_agent_action_terms_include_common_italian_aliases() -> None:
    assert _agent_action_terms("spiega il caricamento e salvataggio certificati") == {
        "save",
        "upload",
    }


def test_agent_context_token_budget_auto_scales_only_default_broad_requests(
    tmp_path: Path,
) -> None:
    model = ProjectModel.empty(tmp_path)
    model.files = [
        FileRecord(path=f"src/file_{index}.py", language="python", sha256="0")
        for index in range(1000)
    ]

    assert (
        _agent_context_effective_token_budget(
            model,
            900,
            has_explicit_context=False,
        )
        == 1500
    )
    assert (
        _agent_context_effective_token_budget(
            model,
            900,
            has_explicit_context=True,
        )
        == 900
    )
    assert (
        _agent_context_effective_token_budget(
            model,
            480,
            has_explicit_context=False,
        )
        == 480
    )
    assert (
        _agent_context_effective_token_budget(
            model,
            0,
            has_explicit_context=False,
        )
        == 0
    )


def test_mcp_model_store_reuses_model_until_artifact_changes(tmp_path: Path) -> None:
    first_model = ProjectModel.empty(tmp_path)
    first_model.flows = [
        Flow(
            id="flow-one",
            name="one",
            symbol="app:one",
            language="python",
            framework="generic",
            entry_kind="function",
            is_entrypoint=True,
            location=SourceLocation(path="app.py", start_line=1, end_line=2),
        )
    ]
    write_artifacts(tmp_path, first_model, include_html=False)
    store = _McpModelStore(tmp_path, CodeDebriefConfig())

    loaded_once, error = store.try_load()
    assert error is None
    loaded_twice, error = store.try_load()
    assert error is None
    assert loaded_twice is loaded_once

    second_model = ProjectModel.empty(tmp_path)
    second_model.flows = [
        Flow(
            id="flow-two-with-longer-id",
            name="two with longer label",
            symbol="app:two_with_longer_label",
            language="python",
            framework="generic",
            entry_kind="function",
            is_entrypoint=True,
            location=SourceLocation(path="app.py", start_line=3, end_line=4),
        )
    ]
    write_artifacts(tmp_path, second_model, include_html=False)

    loaded_after_change, error = store.try_load()
    assert error is None
    assert loaded_after_change is not loaded_once
    assert loaded_after_change is not None
    assert [flow.id for flow in loaded_after_change.flows] == ["flow-two-with-longer-id"]


def test_selection_context_treats_unknown_scope_as_query_hint(tmp_path: Path) -> None:
    model = ProjectModel.empty(tmp_path)
    upload_flow = Flow(
        id="upload-flow",
        name="UnifiedUploadBox",
        symbol="frontend.components:UnifiedUploadBox",
        language="typescript",
        framework="react",
        entry_kind="component",
        is_entrypoint=True,
        location=SourceLocation(
            path="frontend/certificati/UnifiedUploadBox.tsx",
            start_line=1,
            end_line=20,
        ),
        nodes=[
            FlowNode(
                id="upload-node",
                kind=NodeKind.ACTION,
                label="PUT uploaded PDF to presigned S3 URL",
                location=SourceLocation(
                    path="frontend/certificati/UnifiedUploadBox.tsx",
                    start_line=12,
                    end_line=13,
                ),
            )
        ],
    )
    model.flows = [
        upload_flow,
        Flow(
            id="upload-test",
            name="TestUploadUrls.test_success",
            symbol="tests.test_ocr:TestUploadUrls.test_success",
            language="python",
            framework="pytest",
            entry_kind="test",
            is_entrypoint=True,
            location=SourceLocation(
                path="backend-api/tests/e2e/test_ocr_endpoints.py",
                start_line=1,
                end_line=10,
            ),
            metadata={"test": True},
            nodes=[
                FlowNode(
                    id="upload-test-node",
                    kind=NodeKind.ACTION,
                    label="upload endpoint accepts certificate PDF",
                    location=SourceLocation(
                        path="backend-api/tests/e2e/test_ocr_endpoints.py",
                        start_line=4,
                        end_line=5,
                    ),
                )
            ],
        ),
        Flow(
            id="profile-flow",
            name="ProfilePanel",
            symbol="frontend.components:ProfilePanel",
            language="typescript",
            framework="react",
            entry_kind="component",
            is_entrypoint=True,
            location=SourceLocation(path="frontend/ProfilePanel.tsx", start_line=1, end_line=10),
        ),
    ]
    model.metadata["scopes"] = {"frontend": 2}

    payload = _selection_context_payload(
        tmp_path,
        CodeDebriefConfig(),
        model,
        question="spiegami come funziona",
        scope="certificate upload",
        token_budget=600,
    )

    assert payload["query_filters"]["scope_query_hint"] == "certificate upload"
    assert "scope" not in payload["query_filters"]
    assert payload["query"][0]["flow_id"] == "upload-flow"
    assert "upload-test" in {row["flow_id"] for row in payload["query"]}
    assert payload["navigation"]["flows"][0]["flow"]["id"] == "upload-flow"


def test_workflow_slice_anchors_natural_query_to_one_primary_flow(tmp_path: Path) -> None:
    upload_flow = Flow(
        id="upload-flow",
        name="OCRService.create_upload_urls",
        symbol="backend.ocr:OCRService.create_upload_urls",
        language="python",
        framework="fastapi",
        entry_kind="function",
        is_entrypoint=False,
        location=SourceLocation(path="backend/ocr/service.py", start_line=80, end_line=140),
        nodes=[
            FlowNode(
                id="upload-start",
                kind=NodeKind.ACTION,
                label="Create pending OCR upload job",
                location=SourceLocation(path="backend/ocr/service.py", start_line=84, end_line=84),
            ),
            FlowNode(
                id="upload-decision",
                kind=NodeKind.DECISION,
                label="DeadlineType is valid",
                location=SourceLocation(path="backend/ocr/service.py", start_line=90, end_line=90),
            ),
        ],
        edges=[
            FlowEdge(
                id="upload-edge",
                source="upload-start",
                target="upload-decision",
                label="Next",
            )
        ],
        calls=["start-flow"],
    )
    start_flow = Flow(
        id="start-flow",
        name="OCRService.start_processing",
        symbol="backend.ocr:OCRService.start_processing",
        language="python",
        framework="fastapi",
        entry_kind="function",
        is_entrypoint=False,
        location=SourceLocation(path="backend/ocr/service.py", start_line=189, end_line=260),
        nodes=[
            FlowNode(
                id="start-node",
                kind=NodeKind.ACTION,
                label="Start OCR processing for uploaded certificates",
                location=SourceLocation(
                    path="backend/ocr/service.py",
                    start_line=192,
                    end_line=192,
                ),
            )
        ],
    )
    model = ProjectModel.empty(tmp_path)
    model.flows = [upload_flow, start_flow]
    pack = _selection_context_payload(
        tmp_path,
        CodeDebriefConfig(),
        model,
        question="OCR upload certificati",
        token_budget=600,
    )

    workflow_slice = _workflow_slice_payload(
        model,
        pack,
        question="OCR upload certificati",
        inputs={
            "question": "OCR upload certificati",
            "changed_files": [],
            "current_file": None,
            "flow_id": None,
            "symbol": None,
            "dependency_path": None,
            "domain": None,
            "value": None,
            "scope": None,
            "include_visual": False,
            "token_budget": 600,
        },
        domain_logic_payload=_domain_logic_map(
            model,
            domain=None,
            value=None,
            scope=None,
            token_budget=600,
        ),
        token_budget=600,
    )

    assert [flow["id"] for flow in workflow_slice["primary_flows"]] == ["upload-flow"]
    assert "start-flow" in {flow["id"] for flow in workflow_slice["supporting_flows"]}
    assert workflow_slice["presentation"]["schema_version"] == "workflow_slice.presentation.v1"
    assert "bounded summary" in " ".join(workflow_slice["presentation"]["agent_guidance"])
    assert "high-level written flow" in " ".join(workflow_slice["presentation"]["agent_guidance"])
    assert "High-Level Flow" in {
        section["label"] for section in workflow_slice["presentation"]["default_sections"]
    }
    written_flow_policy = workflow_slice["presentation"]["display_policy"]["written_flow"]
    assert written_flow_policy["placement"] == "After the visual and before follow-up choices."
    assert "ordered_steps" in written_flow_policy["source_fields"]
    assert "same simplified wording" in written_flow_policy["language_friendly_rewrite"]
    assert "language-friendly rewrite" in " ".join(
        workflow_slice["presentation"]["display_policy"]["closing_options"]
    )
    assert "human-friendly" in workflow_slice["presentation"]["label_policy"]["human_friendly"]
    assert "high-level written flow" in workflow_slice["presentation"]["visual_guidance"]

    canonical_visual = workflow_slice["presentation"]["canonical_visual"]
    assert canonical_visual["schema_version"] == "workflow_slice.canonical_visual.v1"
    assert canonical_visual["format"] == "mermaid"
    assert canonical_visual["diagram"].startswith("flowchart TD\n")
    assert 'subgraph workflow_slice["workflow_slice"]' in canonical_visual["diagram"]
    assert "direction TB" in canonical_visual["diagram"]
    assert "OCRService.create_upload_urls" in canonical_visual["diagram"]
    assert "Create pending OCR upload job" in canonical_visual["diagram"]
    assert "DeadlineType is valid" in canonical_visual["diagram"]
    assert '-->|"Next"|' in canonical_visual["diagram"]
    assert "calls OCRService.start_processing" in canonical_visual["diagram"]
    assert canonical_visual["diagram_hash"]
    assert canonical_visual["layout"]["direction"] == "top_to_bottom"
    assert canonical_visual["layout"]["flow_grouping"] == "vertical_parent_subgraph"
    assert "human-friendly view" in canonical_visual["guardrail"]


def test_mcp_public_surface_and_workflow_tools(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        """
def authorize(user):
    if user.role == "admin":
        return allow(user)
    return deny(user)
""",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    flow = result.model.flows[0]
    assert flow.nodes
    assert flow.edges

    async def exercise_server() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codedebrief.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                init = await session.initialize()
                assert init.instructions == MCP_INSTRUCTIONS
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert names == PUBLIC_MCP_TOOLS

                schema_by_name = {tool.name: tool.inputSchema for tool in tools.tools}
                for budget_tool in (
                    "agent_context",
                    "expand_slice",
                    "workflow_path",
                    "snapshot_slice",
                    "explain_flow",
                    "explain_node",
                    "explain_edge",
                ):
                    assert "token_budget" in schema_by_name[budget_tool].get("properties", {})
                assert "include_svg" in schema_by_name["snapshot_slice"].get("properties", {})
                assert "full" in schema_by_name["update_codedebrief"].get("properties", {})
                assert "max_parse_warnings" in schema_by_name["validate_artifacts"].get(
                    "properties", {}
                )

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
                agent_context_payload = agent_context.structuredContent
                assert agent_context_payload["tool"] == "agent_context"  # type: ignore[index]
                assert "source-grounded" in agent_context_payload["guardrail"]  # type: ignore[index]
                assert agent_context_payload["inputs"]["current_file"] == "app.py"  # type: ignore[index]
                context = agent_context_payload["context"]  # type: ignore[index]
                assert context["query"][0]["flow_id"] == flow.id
                assert "visual_context" in context
                workflow_slice = agent_context_payload["workflow_slice"]  # type: ignore[index]
                assert workflow_slice["schema_version"] == "workflow_slice.v1"
                assert workflow_slice["id"].startswith("slice-")
                assert workflow_slice["handle"]["flow_ids"] == [flow.id]
                assert workflow_slice["primary_flows"][0]["id"] == flow.id
                assert workflow_slice["ordered_steps"]
                assert workflow_slice["source_ranges"]
                assert workflow_slice["viewer_targets"]["command"] == "codedebrief view"
                assert workflow_slice["next_tools"]["expand_slice"]["tool"] == "expand_slice"
                assert (
                    workflow_slice["next_tools"]["snapshot_slice"]["arguments"]["include_svg"]
                    is False
                )
                canonical_visual = workflow_slice["presentation"]["canonical_visual"]
                assert canonical_visual["format"] == "mermaid"
                assert canonical_visual["diagram"].startswith("flowchart TD\n")
                assert canonical_visual["layout"]["direction"] == "top_to_bottom"

                expanded_slice = await session.call_tool(
                    "expand_slice",
                    {
                        "slice_id": workflow_slice["id"],
                        "flow_ids": workflow_slice["handle"]["flow_ids"],
                        "direction": "neighbors",
                        "token_budget": 480,
                    },
                )
                assert not expanded_slice.isError
                assert expanded_slice.structuredContent["tool"] == "expand_slice"  # type: ignore[index]

                slice_snapshot = await session.call_tool(
                    "snapshot_slice",
                    {
                        "slice_id": workflow_slice["id"],
                        "flow_ids": workflow_slice["handle"]["flow_ids"],
                        "token_budget": 480,
                    },
                )
                assert not slice_snapshot.isError
                artifact = slice_snapshot.structuredContent["artifact"]  # type: ignore[index]
                assert artifact["written"] is True
                assert artifact["schema_version"] == "snapshot_artifact.v1"
                assert artifact["format"] == "svg"
                assert artifact["preferred_format"] == "mermaid"
                assert artifact["formats"] == ["mermaid", "svg"]
                assert Path(artifact["mermaid_path"]).exists()
                assert Path(artifact["svg_path"]).exists()
                assert Path(artifact["html_path"]).exists()

                light_slice_snapshot = await session.call_tool(
                    "snapshot_slice",
                    {
                        "slice_id": workflow_slice["id"],
                        "flow_ids": workflow_slice["handle"]["flow_ids"],
                        "include_svg": False,
                        "token_budget": 480,
                    },
                )
                assert not light_slice_snapshot.isError
                light_payload = light_slice_snapshot.structuredContent
                assert "svg" not in light_payload["snapshot"]  # type: ignore[index]
                assert light_payload["artifact"]["formats"] == ["mermaid"]  # type: ignore[index]
                assert "svg_path" not in light_payload["artifact"]  # type: ignore[index]

                path_response = await session.call_tool(
                    "workflow_path",
                    {"source": flow.id, "target": flow.id, "token_budget": 480},
                )
                assert not path_response.isError
                assert path_response.structuredContent["path"]["found"] is True  # type: ignore[index]

                flow_explanation = await session.call_tool(
                    "explain_flow",
                    {"flow_id": flow.id, "token_budget": 480},
                )
                assert not flow_explanation.isError
                assert flow_explanation.structuredContent["flow"]["id"] == flow.id  # type: ignore[index]

                node_explanation = await session.call_tool(
                    "explain_node",
                    {"flow_id": flow.id, "node_id": flow.nodes[0].id, "token_budget": 480},
                )
                assert not node_explanation.isError
                assert node_explanation.structuredContent["node"]["id"] == flow.nodes[0].id  # type: ignore[index]

                edge_explanation = await session.call_tool(
                    "explain_edge",
                    {"flow_id": flow.id, "edge_id": flow.edges[0].id, "token_budget": 480},
                )
                assert not edge_explanation.isError
                assert edge_explanation.structuredContent["edge"]["id"] == flow.edges[0].id  # type: ignore[index]

                validation = await session.call_tool("validate_artifacts", {})
                assert not validation.isError
                assert validation.structuredContent["ok"] is True  # type: ignore[index]

    asyncio.run(exercise_server())


def test_domain_logic_reports_independent_decision_domains(tmp_path: Path) -> None:
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
    assert payload["tool"] == "domain_logic"
    assert concepts["status"]["handled_values"] == ["draft", "paid"]
    assert concepts["role"]["handled_values"] == ["admin"]
    assert "missing_values" not in concepts["status"]
    assert concepts["role"]["next_tools"]["snapshot_slice"]["tool"] == "snapshot_slice"


def test_domain_logic_reports_enum_handled_values_without_inferring_missing_cases(
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
    assert concept["handled_values"] == ["Status.DRAFT", "Status.OPEN"]
    assert concept["decision_nodes"][0]["source_range"]["path"] == "app.py"
    assert "missing_values" not in concept

    missing_value_payload = _domain_logic_map(
        model,
        domain="Status",
        value="paid",
        scope=None,
        token_budget=0,
    )
    assert missing_value_payload["concepts"] == []


def test_domain_logic_caps_snapshot_targets_with_token_budget(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "\n\n".join(
            [
                f"""
def route_{index}(user):
    if user.role == "admin":
        return allow(user)
    return deny(user)
"""
                for index in range(8)
            ]
        ),
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    payload = _domain_logic_map(
        model,
        domain="role",
        value=None,
        scope=None,
        token_budget=240,
    )

    concept = payload["concepts"][0]
    assert concept["flow_count"] == 8
    assert len(concept["decision_nodes"]) == 1
    assert len(concept["subgraph_flow_ids"]) == 1
    assert concept["omitted_subgraph_flow_count"] == 7
    assert (
        concept["next_tools"]["snapshot_slice"]["arguments"]["flow_ids"]
        == concept["subgraph_flow_ids"]
    )


def test_mcp_model_load_errors_are_structured_and_actionable(tmp_path: Path) -> None:
    async def call_with_missing_artifact() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codedebrief.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                context = await session.call_tool("agent_context", {"question": "anything"})
                assert not context.isError
                payload = context.structuredContent
                assert payload["error_code"] == "artifact_missing"  # type: ignore[index]
                assert payload["recoverable"] is True  # type: ignore[index]
                assert "generated artifacts" in payload["guardrail"]  # type: ignore[index]
                assert payload["next_tools"]["update_model"]["tool"] == "update_codedebrief"  # type: ignore[index]
                assert "codedebrief update --full" in payload["next_cli"]  # type: ignore[index]

    asyncio.run(call_with_missing_artifact())

    error_log = tmp_path / "codedebrief-out" / "codedebrief.errors.jsonl"
    assert error_log.exists()
    assert '"code": "artifact_missing"' in error_log.read_text(encoding="utf-8")

    artifact = tmp_path / "codedebrief-out" / "codedebrief.json"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text("{", encoding="utf-8")

    async def call_with_malformed_artifact() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "codedebrief.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                context = await session.call_tool("agent_context", {"question": "anything"})
                assert not context.isError
                payload = context.structuredContent
                assert payload["error_code"] == "artifact_malformed_json"  # type: ignore[index]
                assert "invalid JSON" in payload["detail"]  # type: ignore[index]

                validation = await session.call_tool("validate_artifacts", {})
                assert not validation.isError
                validation_payload = validation.structuredContent
                assert validation_payload["ok"] is False  # type: ignore[index]
                assert "Malformed JSON" in validation_payload["errors"][0]  # type: ignore[index]

    asyncio.run(call_with_malformed_artifact())


def test_mcp_update_validate_sequence_after_source_change(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def primary(flag):\n    if flag:\n        return 'yes'\n    return 'no'\n",
        encoding="utf-8",
    )
    helper = tmp_path / "helper.py"
    helper.write_text("def unchanged():\n    return 'stable'\n", encoding="utf-8")
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
            args=["-m", "codedebrief.cli", "mcp", str(tmp_path)],
        )
        async with stdio_client(parameters) as streams:
            read_stream, write_stream = streams
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                stale = await session.call_tool("validate_artifacts", {"check_sync": True})
                assert not stale.isError
                stale_payload = stale.structuredContent
                assert stale_payload["ok"] is False  # type: ignore[index]
                assert "stale" in stale_payload["errors"][0]  # type: ignore[index]
                assert stale_payload["next_tools"]["update_model"]["tool"] == "update_codedebrief"  # type: ignore[index]

                update = await session.call_tool("update_codedebrief", {})
                assert not update.isError
                update_payload = update.structuredContent
                assert "app.py" in update_payload["changed_files"]  # type: ignore[index]
                assert "helper.py" not in update_payload["changed_files"]  # type: ignore[index]
                assert update_payload["cache_hits"] >= 1  # type: ignore[index]
                assert update_payload["flows"] >= 2  # type: ignore[index]
                assert update_payload["next_tools"]["validate_artifacts"]["arguments"] == {  # type: ignore[index]
                    "check_sync": True,
                    "include_quality": True,
                }

                fresh = await session.call_tool(
                    "validate_artifacts",
                    {"check_sync": True, "include_quality": True},
                )
                assert not fresh.isError
                fresh_payload = fresh.structuredContent
                assert fresh_payload["ok"] is True  # type: ignore[index]
                assert "quality" in fresh_payload
                assert fresh_payload["next_tools"] == {}

                context = await session.call_tool(
                    "agent_context",
                    {"question": "secondary", "token_budget": 240},
                )
                assert not context.isError
                assert "secondary" in str(context.content)

    asyncio.run(exercise_update_validate())


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
    flow = next(item for item in model.flows if item.name == "dispatch")
    impact = impact_model(model, [], flow_ids=[flow.id])

    payload = _context_visual_pack(
        model,
        impact=impact,
        matches=[],
        scope=None,
        include_visual=True,
        token_budget=120,
        visual_byte_budget=200_000,
    )

    assert payload["include_visual"] is True
    assert payload["next_tools"]["snapshot_slice"]["arguments"] == {
        "flow_ids": [flow.id],
        "format": "svg",
        "include_svg": False,
        "token_budget": 120,
    }
    assert payload["subgraph_snapshot"]["layout"]["engine"] == "static-subgraph-snapshot-v1"
    assert payload["subgraph_snapshot"]["rendered_flow_ids"] == [flow.id]
    assert payload["snapshot_budget"]["used_visual_bytes"] > 0

    capped = _context_visual_pack(
        model,
        impact=impact,
        matches=[],
        scope=None,
        include_visual=True,
        token_budget=120,
        visual_byte_budget=1,
    )

    assert "subgraph_snapshot" not in capped
    assert capped["subgraph_snapshot_omitted_reason"] == "visual_byte_budget"
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
        token_budget=120,
    )

    assert payload["flow_budget"] == 1
    assert payload["per_flow_token_budget"] == 120
    assert payload["flows"][0]["flow"]["id"] == flow.id
    assert payload["flows"][0]["next_tools"]["agent_context"]["tool"] == "agent_context"
    assert payload["next_tools"]["agent_context"] == [
        {
            "tool": "agent_context",
            "arguments": {"flow_id": flow.id, "token_budget": 120},
        }
    ]
    assert payload["omitted_flow_navigation_count"] == 0


def test_mcp_recovery_payload_helpers_are_actionable(tmp_path: Path) -> None:
    config = CodeDebriefConfig()

    missing = _model_load_error(tmp_path, config, FileNotFoundError("missing artifact"))
    assert missing["error_code"] == "artifact_missing"
    assert missing["recoverable"] is True
    assert missing["artifact"].endswith("codedebrief-out/codedebrief.json")
    assert missing["next_tools"]["update_model"]["tool"] == "update_codedebrief"
    assert "codedebrief update --full" in missing["next_cli"]

    malformed = _model_load_error(tmp_path, config, ValueError("invalid JSON in artifact"))
    assert malformed["error_code"] == "artifact_malformed_json"

    unknown_flow = _unknown_target_error("flow", "missing-flow")
    assert unknown_flow["error_code"] == "flow_not_found"
    assert unknown_flow["next_tools"]["agent_context"]["tool"] == "agent_context"
    assert unknown_flow["next_tools"]["agent_context"]["arguments"]["question"] == "missing-flow"

    stale = _validation_payload({"ok": False, "errors": ["stale"], "warnings": []})
    assert stale["next_tools"]["update_model"]["tool"] == "update_codedebrief"
    assert stale["next_cli"] == [
        "codedebrief update --full",
        "codedebrief validate --check-sync --json",
    ]

    fresh = _validation_payload({"ok": True, "errors": [], "warnings": []})
    assert "update_model" not in fresh["next_tools"]
    assert fresh["next_cli"] == [
        "codedebrief validate --quality --json",
        "codedebrief view",
    ]

    update_payload = _update_workflow_payload(
        tmp_path / "codedebrief-out" / "codedebrief.json",
        tmp_path / "codedebrief-out" / "codedebrief.md",
        None,
    )
    assert update_payload["next_tools"]["validate_artifacts"]["tool"] == "validate_artifacts"
    assert update_payload["next_artifacts"]["commit"] == [
        str(tmp_path / "codedebrief-out" / "codedebrief.json"),
        str(tmp_path / "codedebrief-out" / "codedebrief.md"),
        str(tmp_path / "codedebrief-out" / "codedebrief.hash.json"),
    ]
