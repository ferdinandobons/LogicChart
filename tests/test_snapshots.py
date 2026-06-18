from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import Flow, FlowNode, NodeKind, ProjectModel, SourceLocation
from logicchart.render.snapshot import (
    render_finding_snapshot,
    render_flow_snapshot,
    render_impact_snapshot,
    unsupported_snapshot_format,
)


def test_flow_snapshot_renders_decision_flow_svg(tmp_path: Path) -> None:
    source = tmp_path / "app.py"
    source.write_text(
        "def handle(user):\n"
        "    if user.role == '<admin>':\n"
        "        return allow()\n"
        "    return deny()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    flow = next(item for item in model.flows if item.name == "handle")
    decision = next(node for node in flow.nodes if node.kind.value == "decision")

    snapshot = render_flow_snapshot(model, flow.id, highlight_node_ids={decision.id})

    assert snapshot["format"] == "svg"
    assert snapshot["flow_id"] == flow.id
    assert decision.id in snapshot["highlighted_node_ids"]
    svg = snapshot["svg"]
    assert svg.startswith("<svg ")
    assert "kind-decision highlight" in svg
    assert "&lt;admin&gt;" in svg
    assert "<admin>" not in svg


def test_finding_snapshot_highlights_finding_node(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def dispatch(order):\n"
        "    if order.status == Status.OPEN:\n"
        "        return 'open'\n"
        "    elif order.status == Status.CLOSED:\n"
        "        return 'closed'\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    finding = model.findings[0]

    snapshot = render_finding_snapshot(model, finding.id)

    assert snapshot["finding_id"] == finding.id
    assert snapshot["flow_id"] == finding.flow_id
    assert snapshot["highlighted_node_ids"] == [finding.node_id]
    assert snapshot["diagnostic_category"] == "single_flow"
    assert snapshot["evidence_item_count"] >= 4
    assert "highlight" in snapshot["svg"]
    assert "Finding context" in snapshot["svg"]
    assert "Evidence: POTENTIAL_GAP" in snapshot["svg"]
    assert "Evidence chain:" in snapshot["svg"]
    assert "implicit fallback" in snapshot["svg"]


def test_flow_snapshot_budget_omits_nodes_but_keeps_highlight() -> None:
    nodes = [
        FlowNode(
            id=f"n{index}",
            kind=NodeKind.ACTION,
            label=f"node {index}",
            location=SourceLocation(path="app.py", start_line=index + 1, end_line=index + 1),
        )
        for index in range(10)
    ]
    flow = Flow(
        id="big-flow",
        name="big flow",
        symbol="big_flow",
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=True,
        location=SourceLocation(path="app.py", start_line=1, end_line=1),
        nodes=nodes,
    )
    model = ProjectModel(
        schema_version="1.1",
        generated_at="2026-06-18T00:00:00+00:00",
        root=".",
        flows=[flow],
    )

    snapshot = render_flow_snapshot(
        model,
        flow.id,
        highlight_node_ids={"n9"},
        max_nodes=4,
    )

    assert snapshot["rendered_node_count"] == 4
    assert snapshot["omitted_node_count"] == 6
    assert "node 9" in snapshot["svg"]
    assert "6 additional nodes omitted" in snapshot["svg"]


def test_impact_snapshot_renders_empty_state() -> None:
    snapshot = render_impact_snapshot(
        changed_files=["docs/readme.md"],
        direct=[],
        transitive=[],
        findings=[],
    )

    assert snapshot["format"] == "svg"
    assert snapshot["direct_flow_ids"] == []
    assert "No modeled flows are affected" in snapshot["svg"]


def test_impact_snapshot_budget_reports_omitted_flows() -> None:
    flows = [
        Flow(
            id=f"flow-{index}",
            name=f"flow {index}",
            symbol=f"flow_{index}",
            language="python",
            framework="generic",
            entry_kind="function",
            is_entrypoint=True,
            location=SourceLocation(path=f"app{index}.py", start_line=1, end_line=1),
        )
        for index in range(4)
    ]

    snapshot = render_impact_snapshot(
        changed_files=["app.py"],
        direct=flows[:2],
        transitive=flows[2:],
        findings=[],
        max_flows=1,
    )

    assert snapshot["rendered_direct_flow_ids"] == ["flow-0"]
    assert snapshot["rendered_transitive_flow_ids"] == ["flow-2"]
    assert snapshot["omitted_direct_flow_count"] == 1
    assert snapshot["omitted_transitive_flow_count"] == 1
    assert "1 direct and 1 caller flows omitted" in snapshot["svg"]


def test_snapshot_target_errors_are_structured() -> None:
    model = ProjectModel(
        schema_version="1.1",
        generated_at="2026-06-18T00:00:00+00:00",
        root=".",
    )

    flow_error = render_flow_snapshot(model, "missing-flow")
    finding_error = render_finding_snapshot(model, "missing-finding")

    assert flow_error["error"] == "Unknown flow: missing-flow"
    assert flow_error["error_code"] == "snapshot_flow_not_found"
    assert flow_error["target_type"] == "flow"
    assert flow_error["recoverable"] is True
    assert finding_error["error"] == "Unknown finding: missing-finding"
    assert finding_error["error_code"] == "snapshot_finding_not_found"
    assert finding_error["target_type"] == "finding"
    assert finding_error["recoverable"] is True


def test_unsupported_snapshot_format_reports_supported_formats() -> None:
    payload = unsupported_snapshot_format("png")

    assert payload["error"] == "Unsupported snapshot format: png"
    assert payload["error_code"] == "unsupported_snapshot_format"
    assert payload["requested_format"] == "png"
    assert payload["supported_formats"] == ["svg"]
    assert payload["recoverable"] is True
