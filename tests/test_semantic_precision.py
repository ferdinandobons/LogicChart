"""Precision regressions kept as code-logic modeling tests."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.common import decision_metadata
from logicchart.analysis.project import ProjectAnalyzer


def test_set_literal_values_are_extracted() -> None:
    meta = decision_metadata("status in {Status.A, Status.B}")
    assert set(meta["values"]) == {"Status.A", "Status.B"}
    assert meta["value_namespace"] == "Status"


def test_is_not_none_does_not_capture_bogus_value() -> None:
    meta = decision_metadata("user is not None")
    assert meta["operator"] == "is not"
    assert "not" not in meta["values"]
    assert meta["values"] == ["None"]


def test_set_membership_predicate_models_decision(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "from enum import Enum\n\n"
        "class Status(Enum):\n"
        "    A = 'a'\n"
        "    B = 'b'\n"
        "    C = 'c'\n"
        "    D = 'd'\n\n\n"
        "def handle(status):\n"
        "    if status in {Status.A, Status.B, Status.C}:\n"
        "        return 1\n"
        "    return 0\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handle = next(flow for flow in model.flows if flow.name == "handle")
    decision = next(node for node in handle.nodes if "status in" in node.label)

    assert {"Status.A", "Status.B", "Status.C"} <= set(decision.metadata["values"])


def test_constant_guard_remains_modeled(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "ENABLE = False\n\n\ndef run():\n    if ENABLE:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(flow for flow in model.flows if flow.name == "run")

    assert any(node.label == "ENABLE" for node in run.nodes)


def test_log_only_handler_remains_modeled(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text(
        "import logging\n\nlogger = logging.getLogger(__name__)\n\n\n"
        "def run():\n"
        "    try:\n"
        "        risky()\n"
        "    except Exception as e:\n"
        "        logger.error(e)\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(flow for flow in model.flows if flow.name == "run")

    assert any(node.metadata.get("domain") == "error" for node in run.nodes)
