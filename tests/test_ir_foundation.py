"""Stage 1 IR foundation: branch outcomes, decision identity, reachability."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.common import (
    BRANCH_OUTCOMES,
    parse_subject_operator,
    value_namespace,
)
from logicchart.analysis.python import PythonAnalyzer
from logicchart.analysis.typescript import TypeScriptAnalyzer
from logicchart.config import LogicChartConfig
from logicchart.model import FlowNode, NodeKind


def _py_decision(tmp_path: Path, body: str) -> FlowNode:
    source = tmp_path / "module.py"
    source.write_text(body, encoding="utf-8")
    flow = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source).flows[0]
    return next(node for node in flow.nodes if node.kind is NodeKind.DECISION)


def _branches(node: FlowNode) -> dict[str, dict[str, object]]:
    return {branch["label"]: branch for branch in node.metadata["branches"]}


def test_python_branch_outcome_raises_and_implicit_fallthrough(tmp_path: Path) -> None:
    node = _py_decision(
        tmp_path,
        """
def handle(account):
    if account.status == Status.SUSPENDED:
        raise Error()
    return account
""",
    )
    branches = _branches(node)
    assert branches["Yes"]["outcome"] == "raises"
    assert branches["No"]["outcome"] == "falls_through"
    assert branches["No"]["implicit"] is True


def test_python_branch_outcome_returns_and_empty_else(tmp_path: Path) -> None:
    node = _py_decision(
        tmp_path,
        """
def handle(x):
    if x.status == State.A:
        return 1
    else:
        pass
    return 0
""",
    )
    branches = _branches(node)
    assert branches["Yes"]["outcome"] == "returns"
    assert branches["No"]["outcome"] == "empty"
    assert branches["No"]["implicit"] is False


def test_python_decision_identity(tmp_path: Path) -> None:
    node = _py_decision(
        tmp_path,
        """
def handle(account):
    if account.status == Status.SUSPENDED:
        raise Error()
""",
    )
    assert node.metadata["subject"] == "account.status"
    assert node.metadata["operator"] == "=="
    assert node.metadata["negation"] is False
    assert node.metadata["value_namespace"] == "Status"


def test_python_decision_identity_negation(tmp_path: Path) -> None:
    node = _py_decision(
        tmp_path,
        """
def handle(user):
    if not user.is_active:
        return redirect()
""",
    )
    assert node.metadata["negation"] is True
    assert node.metadata["subject"] == "user.is_active"
    assert node.metadata["operator"] == ""


def test_reachability_flags_present_and_true(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text(
        """
def handle(x):
    if x.status == State.A:
        return 1
    return 0
""",
        encoding="utf-8",
    )
    flow = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source).flows[0]
    assert flow.nodes
    for node in flow.nodes:
        assert node.metadata["reachable_from_entry"] is True
        assert node.metadata["reaches_terminal"] is True


def test_typescript_switch_branch_outcomes(tmp_path: Path) -> None:
    route = tmp_path / "app" / "api" / "orders"
    route.mkdir(parents=True)
    source = route / "route.ts"
    source.write_text(
        """
export async function POST(request: Request) {
  switch (order.status) {
    case OrderStatus.PAID:
      return ok();
    case OrderStatus.CANCELLED:
      throw new Error("no");
  }
}
""",
        encoding="utf-8",
    )
    flow = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source).flows[0]
    node = next(n for n in flow.nodes if n.kind is NodeKind.DECISION)
    branches = _branches(node)

    assert node.metadata["value_namespace"] == "OrderStatus"
    assert any(b["outcome"] == "returns" for k, b in branches.items() if "PAID" in k)
    assert any(b["outcome"] == "raises" for k, b in branches.items() if "CANCELLED" in k)
    assert branches["default"]["implicit"] is True


def test_typescript_break_case_is_falls_through(tmp_path: Path) -> None:
    route = tmp_path / "app" / "api" / "z"
    route.mkdir(parents=True)
    source = route / "route.ts"
    source.write_text(
        """
export async function POST(request: Request) {
  switch (order.status) {
    case OrderStatus.PAID:
      recordPaid();
      break;
    default:
      return ok();
  }
}
""",
        encoding="utf-8",
    )
    flow = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source).flows[0]
    node = next(n for n in flow.nodes if n.kind is NodeKind.DECISION)
    branches = _branches(node)

    # A case that works then breaks exits the switch - it does not terminate.
    paid = next(b for label, b in branches.items() if "PAID" in label)
    assert paid["outcome"] == "falls_through"
    assert all(b["outcome"] in BRANCH_OUTCOMES for b in node.metadata["branches"])


def test_parse_subject_operator_unit() -> None:
    assert parse_subject_operator("account.role != required") == ("account.role", "!=", False)
    assert parse_subject_operator("user is None") == ("user", "is", False)
    assert parse_subject_operator("user is not None") == ("user", "is not", False)
    assert parse_subject_operator("x in {A, B}") == ("x", "in", False)
    assert parse_subject_operator("not ctx.ok") == ("ctx.ok", "", True)


def test_value_namespace_unit() -> None:
    assert value_namespace(["Status.A", "Status.B"]) == "Status"
    assert value_namespace(["Status.A", "Role.X"]) == ""
    assert value_namespace(["plain"]) == ""
