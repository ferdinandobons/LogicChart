from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.diagnostics import finding_rule_contracts_by_kind
from logicchart.model import Evidence, FindingKind
from logicchart.query import explain_finding, query_model

_FIXTURE = """
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    DELETED = "deleted"


def handle(status):
    match status:
        case Status.OPEN:
            return "open"
        case Status.CLOSED:
            return "closed"
"""


def test_findings_carry_normalized_diagnostics(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(_FIXTURE, encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    assert model.findings
    assert "finding_rules" in model.metadata
    for finding in model.findings:
        diagnostic = finding.metadata.get("diagnostic")
        assert isinstance(diagnostic, dict)
        assert diagnostic["rule_id"] == finding.kind
        assert diagnostic["severity"] == finding.severity.value
        assert diagnostic["evidence"] == finding.evidence.value
        assert diagnostic["scope"]["flow_id"] == finding.flow_id
        assert diagnostic["scope"]["related_flow_ids"] == [finding.flow_id]
        assert diagnostic["review_prompt"]
        assert diagnostic["suggested_next_actions"]
        assert diagnostic["evidence_chain"]

    enum_finding = next(
        finding for finding in model.findings if finding.kind == FindingKind.ENUM_EXHAUSTIVENESS
    )
    diagnostic = enum_finding.metadata["diagnostic"]
    assert diagnostic["category"] == "cross_flow"
    assert diagnostic["missing"]
    assert diagnostic["expected"]["handle_declared_values"]
    assert diagnostic["confidence"]["basis"] == "deterministic heuristic"
    assert enum_finding.evidence is Evidence.INFERRED


def test_cross_flow_diagnostics_include_related_decision_scope(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        """
def handle_a(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()


def handle_b(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()


def handle_c(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()


def handle_partial(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    partial = next(flow for flow in model.flows if flow.name == "handle_partial")
    finding = next(
        item
        for item in model.findings
        if item.kind == FindingKind.INCONSISTENT_CASE_HANDLING and item.flow_id == partial.id
    )

    diagnostic = finding.metadata["diagnostic"]
    scope = diagnostic["scope"]
    assert scope["related_flow_ids"][0] == partial.id
    assert len(scope["related_flow_ids"]) > 1
    assert finding.node_id in scope["related_node_ids"]
    related = next(
        item for item in diagnostic["evidence_chain"] if item["type"] == "related_decisions"
    )
    assert len(related["nodes"]) <= 12
    assert any("handles_missing_value" in node["reasons"] for node in related["nodes"])
    assert all("location" in node for node in related["nodes"])


def test_single_flow_diagnostics_include_detector_specific_evidence(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(
        """
FEATURE_ENABLED = False


def route(user):
    if user.role == "admin":
        return admin()
    elif user.role == "staff":
        return staff()


def feature():
    if FEATURE_ENABLED:
        return enabled()
    return disabled()
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    missing = next(item for item in model.findings if item.kind == FindingKind.MISSING_BRANCH)
    missing_chain = missing.metadata["diagnostic"]["evidence_chain"]
    fallback = next(item for item in missing_chain if item["type"] == "implicit_fallback")
    assert fallback["subject"] == "user.role"
    assert fallback["handled_values"] == ["admin", "staff"]
    assert fallback["fallback_present"] is False
    assert fallback["implicit_branches"]

    dead_guard = next(item for item in model.findings if item.kind == FindingKind.DEAD_GUARD)
    guard_chain = dead_guard.metadata["diagnostic"]["evidence_chain"]
    constant_guard = next(item for item in guard_chain if item["type"] == "constant_guard")
    assert constant_guard["constant"] == "FEATURE_ENABLED"
    assert constant_guard["guard_always"] is False
    assert constant_guard["unreachable_branch_label"] == "Yes"
    assert constant_guard["branches"]


def test_every_finding_kind_has_a_rule_contract() -> None:
    rules = finding_rule_contracts_by_kind()
    assert set(rules) == {kind.value for kind in FindingKind}
    for kind, rule in rules.items():
        assert rule["rule_id"] == kind
        assert rule["purpose"]
        assert rule["preconditions"]
        assert rule["evidence_rationale"]
        assert rule["review_prompt"]
        assert rule["suggested_next_actions"]


def test_explain_finding_returns_diagnostic_contract(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(_FIXTURE, encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    finding = model.findings[0]

    explanation = explain_finding(model, finding.id)

    assert explanation is not None
    assert explanation["id"] == finding.id
    assert explanation["diagnostic"]["rule_id"] == finding.kind
    assert explanation["diagnostic"]["scope"]["source"].startswith("service.py:")


def test_query_ignores_generated_diagnostic_prose(tmp_path: Path) -> None:
    (tmp_path / "service.py").write_text(_FIXTURE, encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    matches = query_model(model, "suggested next actions", limit=10)

    assert matches == []
