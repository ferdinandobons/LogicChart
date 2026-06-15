"""Stage 5 cross-flow detectors: enum-vs-declared exhaustiveness."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer

_ENUM = (
    "from enum import Enum\n\n"
    "class Result(str, Enum):\n    A = 'a'\n    B = 'b'\n    C = 'c'\n    D = 'd'\n"
)


def _kinds_for(model: object, flow_name: str) -> set[str]:
    flow = next(f for f in model.flows if f.name == flow_name)  # type: ignore[attr-defined]
    return {f.kind for f in model.findings if f.flow_id == flow.id}  # type: ignore[attr-defined]


def test_enum_exhaustiveness_flags_omitted_declared_member(tmp_path: Path) -> None:
    (tmp_path / "domain.py").write_text(_ENUM, encoding="utf-8")
    (tmp_path / "svc.py").write_text(
        "def handle(result):\n"
        "    if result == Result.A:\n        return 1\n"
        "    elif result == Result.B:\n        return 2\n"
        "    elif result == Result.C:\n        return 3\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handle = next(f for f in model.flows if f.name == "handle")
    flagged = [
        f for f in model.findings if f.kind == "enum_exhaustiveness" and f.flow_id == handle.id
    ]
    assert flagged
    assert "Result.D" in flagged[0].metadata["missing"]
    assert flagged[0].metadata["value_namespace"] == "Result"


def test_enum_exhaustiveness_silent_with_explicit_else(tmp_path: Path) -> None:
    (tmp_path / "domain.py").write_text(_ENUM, encoding="utf-8")
    (tmp_path / "svc.py").write_text(
        "def handle(result):\n"
        "    if result == Result.A:\n        return 1\n"
        "    elif result == Result.B:\n        return 2\n"
        "    else:\n        return 0\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert "enum_exhaustiveness" not in _kinds_for(model, "handle")


def test_enum_exhaustiveness_silent_on_single_guard(tmp_path: Path) -> None:
    # Handling a single member is a guard, not an exhaustive dispatch.
    (tmp_path / "domain.py").write_text(_ENUM, encoding="utf-8")
    (tmp_path / "svc.py").write_text(
        "def handle(result):\n    if result == Result.A:\n        raise Error()\n    return ok()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert "enum_exhaustiveness" not in _kinds_for(model, "handle")


def test_enum_exhaustiveness_silent_without_declared_enum(tmp_path: Path) -> None:
    # No declared enum for Result -> the declared-set detector does not apply.
    (tmp_path / "svc.py").write_text(
        "def handle(result):\n"
        "    if result == Result.A:\n        return 1\n"
        "    elif result == Result.B:\n        return 2\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert "enum_exhaustiveness" not in _kinds_for(model, "handle")
