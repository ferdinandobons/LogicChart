"""Query and navigation helpers for source-grounded workflow comprehension."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import Flow, ProjectModel, SourceLocation
from logicchart.query import (
    flow_navigation,
    query_model,
)

_CHAIN = (
    "def a(s):\n"
    "    if s.status == X.A:\n        return 1\n"
    "    elif s.status == X.B:\n        return 2\n"
)


def _model(tmp_path: Path, body: str) -> ProjectModel:
    (tmp_path / "m.py").write_text(body, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _flow(flow_id: str, name: str, symbol: str) -> Flow:
    return Flow(
        id=flow_id,
        name=name,
        symbol=symbol,
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=False,
        location=SourceLocation(path="app.py", start_line=1, end_line=1),
    )


def test_analysis_generates_comprehension_metadata(tmp_path: Path) -> None:
    model = _model(tmp_path, _CHAIN)
    assert model.schema_version == "2.0"
    assert model.flows
    assert "quality" in model.metadata


def test_flow_navigation_resolves_target_without_name_ambiguity_regression(
    tmp_path: Path,
) -> None:
    model = ProjectModel.empty(tmp_path)
    model.flows = [
        _flow("target-id", "shared name", "pkg:target"),
        _flow("symbol-flow", "shared name", "pkg:symbol"),
        _flow("name-flow", "unique name", "pkg:name"),
    ]

    assert flow_navigation(model, "target-id")["flow"]["id"] == "target-id"
    assert flow_navigation(model, "pkg:symbol")["flow"]["id"] == "symbol-flow"
    assert flow_navigation(model, "unique name")["flow"]["id"] == "name-flow"

    ambiguous = flow_navigation(model, "shared name")

    assert ambiguous["error_code"] == "flow_target_ambiguous"
    assert [item["id"] for item in ambiguous["matches"]] == ["target-id", "symbol-flow"]


def test_query_matches_structure_and_metadata(tmp_path: Path) -> None:
    model = _model(
        tmp_path,
        "def get_profile(user):\n"
        "    user = repository.fetch(user.id)\n"
        "    if user.status == AccountStatus.ACTIVE:\n"
        "        return user\n"
        "    return None\n",
    )

    matches = query_model(model, "python accountstatus active profile", language="python")

    assert matches
    top = matches[0]
    assert top.flow.name == "get_profile"
    assert any("structure" in reason or "metadata" in reason for reason in top.reasons)
    payload = top.to_dict()
    assert payload["language"] == "python"
    assert payload["entry_kind"] == "function"
