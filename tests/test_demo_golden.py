"""Golden-master precision SLA, measured on examples/demo.

The demo is a dense polyglot frontend/backend codebase (11 languages across two
macro-parts). The SLA pins the published-artifact noise budget: across the whole
codebase LogicChart surfaces exactly two intentional enum-exhaustiveness review
signals and nothing else. A second test proves same-language cross-flow detection
still fires.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import Evidence

DEMO = Path(__file__).resolve().parent.parent / "examples" / "demo"

_SOURCE_ROOTS = ("backend", "frontend", "logicchart.toml")
# Every language the polyglot demo is meant to exercise end to end.
_EXPECTED_LANGUAGES = {
    "python",
    "typescript",
    "javascript",
    "go",
    "java",
    "csharp",
    "php",
    "c",
    "cpp",
    "rust",
    "ruby",
}
_EXPECTED_SCOPES = {"backend", "frontend"}


def _analyze_copy(source: Path, tmp_path: Path) -> ProjectAnalyzer:
    """Analyze a copy so the committed fixture's cache/output stay pristine."""
    for item in _SOURCE_ROOTS:
        src = source / item
        dst = tmp_path / item
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)
    return ProjectAnalyzer(tmp_path)


def test_demo_is_polyglot_and_scoped(tmp_path: Path) -> None:
    model = _analyze_copy(DEMO, tmp_path).analyze(full=True).model

    languages = {flow.language for flow in model.flows}
    assert languages >= _EXPECTED_LANGUAGES

    scopes = {scope for flow in model.flows for scope in (flow.metadata.get("scope") or [])}
    assert scopes >= _EXPECTED_SCOPES


def test_demo_precision_sla(tmp_path: Path) -> None:
    model = _analyze_copy(DEMO, tmp_path).analyze(full=True).model
    findings = model.findings

    # Exactly two findings across the whole polyglot codebase: the frontend
    # intentionally leaves some enum states unhandled in two route switches.
    assert len(findings) == 2
    assert {finding.kind for finding in findings} == {"enum_exhaustiveness"}
    assert {finding.evidence for finding in findings} == {Evidence.INFERRED}

    missing_by_subject = {
        finding.metadata["subject"]: set(finding.metadata["missing"]) for finding in findings
    }
    assert missing_by_subject == {
        "order.state": {
            "OrderState.BACKORDERED",
            "OrderState.CHARGEBACK",
            "OrderState.RETURNED",
        },
        "user.status": {
            "UserStatus.ARCHIVED",
            "UserStatus.DELETED",
            "UserStatus.LOCKED",
        },
    }
    assert all(
        next(flow for flow in model.flows if flow.id == finding.flow_id).language == "typescript"
        for finding in findings
    )

    # No cross-flow false positive survives, and no review-only noise either.
    assert not any(f.kind == "inconsistent_case_handling" for f in findings)
    assert not any(f.evidence is Evidence.POTENTIAL_GAP for f in findings)


def test_demo_rust_match_is_not_a_false_positive(tmp_path: Path) -> None:
    # The Rust router's exhaustive `match` must not be flagged as a missing fallback.
    model = _analyze_copy(DEMO, tmp_path).analyze(full=True).model
    rust_flows = {flow.id for flow in model.flows if flow.language == "rust"}
    assert rust_flows  # the backend router was discovered
    assert not any(f.flow_id in rust_flows for f in model.findings)


def test_quorum_cross_flow_flags_the_minority_omission(tmp_path: Path) -> None:
    # Three sibling flows handle Status.DELETED; the fourth omits it. A strict
    # majority handling a value it lacks makes the minority flow a review candidate.
    full = """
def handle_{n}(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return blocked()
    if account.status == Status.DELETED:
        return gone()
"""
    body = full.format(n="a") + full.format(n="b") + full.format(n="c")
    body += """
def handle_partial(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return blocked()
"""
    (tmp_path / "service.py").write_text(body, encoding="utf-8")

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    partial = next(f for f in model.flows if f.name == "handle_partial")
    flagged = [
        f
        for f in model.findings
        if f.kind == "inconsistent_case_handling" and f.flow_id == partial.id
    ]

    assert any("DELETED" in f.message for f in flagged)
    # The mutable detail lives in metadata; the id is structural and stable.
    finding = next(f for f in flagged if "DELETED" in f.message)
    assert finding.metadata["value_namespace"] == "Status"
    assert "Status.DELETED" in finding.metadata["missing"]
    assert finding.metadata["quorum"]["siblings"] == 4
    # The three complete siblings are not flagged.
    assert not any(
        f.kind == "inconsistent_case_handling" and f.flow_id != partial.id for f in model.findings
    )
