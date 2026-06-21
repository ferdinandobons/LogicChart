"""Match-statement dispatch modeling: guarded wildcards and OR patterns."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel

_ENUM = (
    "from enum import Enum\n\n\n"
    "class Status(Enum):\n"
    "    A = 'a'\n"
    "    B = 'b'\n"
    "    C = 'c'\n"
    "    D = 'd'\n\n\n"
)


def _analyze(tmp_path: Path, body: str) -> ProjectModel:
    (tmp_path / "mod.py").write_text(_ENUM + body, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _match_meta(model: ProjectModel, flow_name: str) -> dict:
    flow = next(f for f in model.flows if f.name == flow_name)
    node = next(n for n in flow.nodes if n.kind is NodeKind.DECISION)
    return node.metadata


def test_guarded_wildcard_is_modeled(tmp_path: Path) -> None:
    body = (
        "def handle(status):\n"
        "    match status:\n"
        "        case Status.A:\n"
        "            return 1\n"
        "        case Status.B:\n"
        "            return 2\n"
        "        case _ if status.special:\n"
        "            return 3\n"
    )
    model = _analyze(tmp_path, body)
    meta = _match_meta(model, "handle")
    assert {"Status.A", "Status.B"} <= set(meta["values"])


def test_guarded_wildcard_leaves_trailing_return_live(tmp_path: Path) -> None:
    body = (
        "def handle(status):\n"
        "    match status:\n"
        "        case Status.A:\n"
        "            return 1\n"
        "        case _ if status.special:\n"
        "            return 2\n"
        "    return 'fallthrough'\n"
    )
    model = _analyze(tmp_path, body)
    flow = next(f for f in model.flows if f.name == "handle")
    assert any(node.label == "Return 'fallthrough'" for node in flow.nodes)


def test_or_pattern_members_are_split(tmp_path: Path) -> None:
    body = (
        "def handle(status):\n"
        "    match status:\n"
        "        case Status.A:\n"
        "            return 1\n"
        "        case Status.B | Status.C:\n"
        "            return 2\n"
    )
    model = _analyze(tmp_path, body)
    meta = _match_meta(model, "handle")
    assert meta["value_namespace"] == "Status"
    assert {"Status.A", "Status.B", "Status.C"} <= set(meta["values"])


def test_real_default_stays_explicit(tmp_path: Path) -> None:
    body = (
        "def handle(status):\n"
        "    match status:\n"
        "        case Status.A:\n"
        "            return 1\n"
        "        case Status.B:\n"
        "            return 2\n"
        "        case _:\n"
        "            return 0\n"
    )
    model = _analyze(tmp_path, body)
    meta = _match_meta(model, "handle")
    assert any(branch["label"] == "_" and not branch["implicit"] for branch in meta["branches"])
