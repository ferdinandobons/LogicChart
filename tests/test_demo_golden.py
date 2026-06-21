"""Golden-master comprehension SLA, measured on examples/demo.

The demo is a dense polyglot frontend/backend codebase (11 languages across two
macro-parts). The SLA pins that LogicChart models the flows as source-grounded
comprehension artifacts.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer

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


def test_demo_emits_comprehension_metadata(tmp_path: Path) -> None:
    model = _analyze_copy(DEMO, tmp_path).analyze(full=True).model
    assert model.schema_version == "2.0"
    assert "quality" in model.metadata


def test_demo_rust_match_is_not_a_false_positive(tmp_path: Path) -> None:
    model = _analyze_copy(DEMO, tmp_path).analyze(full=True).model
    rust_flows = {flow.id for flow in model.flows if flow.language == "rust"}
    assert rust_flows  # the backend router was discovered
    assert any(flow.nodes for flow in model.flows if flow.id in rust_flows)


def test_quorum_fixture_models_all_sibling_flows(tmp_path: Path) -> None:
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

    assert {flow.name for flow in model.flows} >= {
        "handle_a",
        "handle_b",
        "handle_c",
        "handle_partial",
    }
