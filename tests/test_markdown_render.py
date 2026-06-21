"""Markdown report escaping for source-grounded flow documentation."""

from __future__ import annotations

from codedebrief.model import (
    Flow,
    FlowEdge,
    FlowNode,
    NodeKind,
    ProjectModel,
    SourceLocation,
)
from codedebrief.render.markdown import render_markdown


def _flow(
    *,
    flow_id: str = "f",
    name: str = "handle",
    path: str = "app.py",
    node_label: str = "return ok",
) -> Flow:
    return Flow(
        id=flow_id,
        name=name,
        symbol=f"m:{name}",
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=True,
        location=SourceLocation(path, 1, 3),
        nodes=[
            FlowNode(
                id="n1",
                kind=NodeKind.ENTRY,
                label="Start",
                location=SourceLocation(path, 1, 1),
            ),
            FlowNode(
                id="n2",
                kind=NodeKind.ACTION,
                label=node_label,
                location=SourceLocation(path, 2, 2),
            ),
        ],
        edges=[FlowEdge(id="e1", source="n1", target="n2", label="next")],
    )


def _model(flow: Flow) -> ProjectModel:
    return ProjectModel(
        schema_version="2.0",
        generated_at="x",
        root=".",
        flows=[flow],
    )


def test_markdown_renders_flow_report() -> None:
    out = render_markdown(_model(_flow()))

    assert "# CodeDebrief Decision Flows" in out
    assert "## Project Map" in out
    assert "## Entry Point Flows" in out
    assert "flowchart TD" in out
    assert "flowchart LR" not in out


def test_mermaid_node_label_injection_is_neutralized() -> None:
    evil = 'see "quote" and <b>x</b>\nnext'
    out = render_markdown(_model(_flow(node_label=evil)))

    assert "<b>x</b>" not in out
    assert "&lt;b&gt;x&lt;/b&gt;" in out
    assert "&quot;quote&quot;" in out
    assert "next" in out


def test_source_path_with_metacharacters_cannot_break_the_reference() -> None:
    # A source-derived file path with a backtick, a `)`, and angle brackets must not be
    # able to close the inline code span or the link destination.
    evil_path = "a`b)c<d>e.py"
    out = render_markdown(_model(_flow(path=evil_path)))
    reference = next(line for line in out.splitlines() if "e.py:1" in line)

    assert "`a`b)" not in reference
    assert "a'b)c" in reference
    assert "](../a`b)c" not in reference
    assert "%29" in reference
    assert "%3C" in reference and "%3E" in reference
    assert "](../a%60b%29c%3Cd%3Ee.py#L1)" in reference


def test_flow_name_with_metacharacters_is_escaped_in_the_heading() -> None:
    out = render_markdown(_model(_flow(name="weird`name](http://evil)<b>")))
    heading = next(line for line in out.splitlines() if line.startswith("### "))

    assert "](http://evil)" not in heading
    assert "<b>" not in heading
    assert r"\]\(http://evil\)" in heading


def test_generated_at_and_root_cannot_break_the_header() -> None:
    flow = _flow()
    model = ProjectModel(
        schema_version="2.0",
        generated_at="x`bad",
        root="root`bad",
        flows=[flow],
    )
    out = render_markdown(model)

    assert "`x`bad`" not in out
    assert "`x'bad`" in out
    assert "`root'bad`" in out
