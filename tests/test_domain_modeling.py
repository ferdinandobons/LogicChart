"""Domain metadata remains navigable without a public review queue."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer

_ENUM = (
    "from enum import Enum\n\n"
    "class Result(str, Enum):\n    A = 'a'\n    B = 'b'\n    C = 'c'\n    D = 'd'\n"
)


def test_enum_dispatch_keeps_domain_metadata_without_findings(tmp_path: Path) -> None:
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
    decisions = [node for node in handle.nodes if node.metadata.get("value_namespace") == "Result"]
    values = {value for node in decisions for value in node.metadata["values"]}

    assert {"Result.A", "Result.B", "Result.C"} <= values
    assert model.findings == []


def test_cross_flow_siblings_remain_navigable_without_review_queue(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def refund(order):\n"
        "    if order.amount <= 0:\n"
        "        log_warning('bad')\n        raise ApiError(422)\n"
        "    do_refund(order)\n\n\n"
        "def capture(order):\n"
        "    if order.amount <= 0:\n        return\n"
        "    do_capture(order)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    refund = next(flow for flow in model.flows if flow.name == "refund")
    capture = next(flow for flow in model.flows if flow.name == "capture")

    assert refund.nodes
    assert capture.nodes
    assert model.findings == []
