"""Markdown report: injection escaping and the signal/noise split (review fixes)."""

from __future__ import annotations

from logicchart.model import (
    Evidence,
    Finding,
    ProjectModel,
    Severity,
    SourceLocation,
)
from logicchart.render.markdown import render_markdown


def _finding(kind: str, evidence: Evidence, message: str) -> Finding:
    return Finding(
        id=f"id-{kind}-{evidence.value}",
        kind=kind,
        severity=Severity.WARNING,
        message=message,
        evidence=evidence,
        flow_id="f",
        location=SourceLocation("app.py", 3, 3),
    )


def _model(findings: list[Finding]) -> ProjectModel:
    return ProjectModel(
        schema_version="1.1", generated_at="x", root=".", flows=[], findings=findings
    )


def test_finding_message_link_injection_is_neutralized() -> None:
    evil = "see [click](https://evil.example) and `code` and <b>x</b>"
    out = render_markdown(_model([_finding("dead_code", Evidence.INFERRED, evil)]))
    # The attacker substring must not survive as a live Markdown link / code / HTML.
    assert "[click](https://evil.example)" not in out
    assert r"\[click\]" in out
    assert "<b>x</b>" not in out


def test_potential_gap_is_grouped_under_collapsible_section() -> None:
    findings = [
        _finding("dead_code", Evidence.INFERRED, "an inferred fact"),
        _finding("missing_branch", Evidence.POTENTIAL_GAP, "a review candidate"),
    ]
    out = render_markdown(_model(findings))
    main, _, review = out.partition("<details>")
    # The verified/inferred finding is in the main section, the gap under <details>.
    assert "an inferred fact" in main
    assert "a review candidate" not in main
    assert "a review candidate" in review
    assert "POTENTIAL_GAP" in review


def test_include_gaps_expands_the_review_section() -> None:
    findings = [_finding("missing_branch", Evidence.POTENTIAL_GAP, "a review candidate")]
    folded = render_markdown(_model(findings), include_gaps=False)
    expanded = render_markdown(_model(findings), include_gaps=True)
    assert "<details>" in folded
    assert "<details open>" in expanded


def test_evidence_level_is_rendered_inline() -> None:
    out = render_markdown(_model([_finding("dead_code", Evidence.INFERRED, "x")]))
    assert "INFERRED" in out
