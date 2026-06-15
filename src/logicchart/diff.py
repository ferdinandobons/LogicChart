"""Model diffing — the CI primitive.

Compare two `logic-flow.json` models by stable finding id to report findings
introduced, resolved, and persisting, and render the result as GitHub Markdown
and SARIF. Because finding ids derive from structural anchors, a finding pins
across edits to its mutable details, so "introduced since base" is meaningful.
"""

from __future__ import annotations

from dataclasses import dataclass

from logicchart.model import Finding, ProjectModel

_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


@dataclass(slots=True)
class ModelDiff:
    introduced: list[Finding]
    resolved: list[Finding]
    persisting: list[Finding]

    @property
    def has_regressions(self) -> bool:
        return bool(self.introduced)


def diff_models(base: ProjectModel, head: ProjectModel) -> ModelDiff:
    base_by_id = {finding.id: finding for finding in base.findings}
    head_by_id = {finding.id: finding for finding in head.findings}
    introduced = [finding for fid, finding in head_by_id.items() if fid not in base_by_id]
    resolved = [finding for fid, finding in base_by_id.items() if fid not in head_by_id]
    persisting = [finding for fid, finding in head_by_id.items() if fid in base_by_id]
    return ModelDiff(
        introduced=sorted(introduced, key=_finding_sort_key),
        resolved=sorted(resolved, key=_finding_sort_key),
        persisting=sorted(persisting, key=_finding_sort_key),
    )


def render_diff_markdown(diff: ModelDiff) -> str:
    lines = ["## LogicChart diff", ""]
    lines.append(
        f"- **Introduced:** {len(diff.introduced)} · "
        f"**Resolved:** {len(diff.resolved)} · "
        f"**Persisting:** {len(diff.persisting)}"
    )
    if diff.introduced:
        lines += ["", "### Introduced findings", ""]
        lines += [_markdown_row(finding) for finding in diff.introduced]
    if diff.resolved:
        lines += ["", "### Resolved findings", ""]
        lines += [_markdown_row(finding) for finding in diff.resolved]
    return "\n".join(lines) + "\n"


def render_sarif(diff: ModelDiff) -> dict[str, object]:
    """A minimal SARIF 2.1.0 log of the introduced findings.

    Each result carries the stable finding id as a partial fingerprint, so a code
    scanner re-keys alerts on the structural id (the diff premise) rather than on
    location, and each rule declares its default severity level.
    """
    rules = {
        finding.kind: {
            "id": finding.kind,
            "name": finding.kind,
            "defaultConfiguration": {"level": _SARIF_LEVEL.get(finding.severity.value, "warning")},
        }
        for finding in diff.introduced
    }
    results = [
        {
            "ruleId": finding.kind,
            "level": _SARIF_LEVEL.get(finding.severity.value, "warning"),
            "message": {"text": finding.message},
            "partialFingerprints": {"logicchartFindingId/v1": finding.id},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": finding.location.path},
                        "region": {"startLine": finding.location.start_line},
                    }
                }
            ],
        }
        for finding in diff.introduced
    ]
    return {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "LogicChart",
                        "informationUri": "https://github.com/ferdinandobons/LogicChart",
                        "rules": list(rules.values()),
                    }
                },
                "results": results,
            }
        ],
    }


def _markdown_row(finding: Finding) -> str:
    location = f"{finding.location.path}:{finding.location.start_line}"
    return f"- **{finding.kind}** ({finding.evidence.value}) — {finding.message} `{location}`"


def _finding_sort_key(finding: Finding) -> tuple[str, str, int]:
    return (finding.kind, finding.location.path, finding.location.start_line)
