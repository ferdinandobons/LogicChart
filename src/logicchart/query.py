from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logicchart.model import Finding, Flow, NodeKind, ProjectModel


@dataclass(slots=True)
class QueryMatch:
    flow: Flow
    score: int
    reasons: list[str]


@dataclass(slots=True)
class ImpactResult:
    changed_files: list[str]
    directly_impacted: list[Flow]
    transitively_impacted: list[Flow]
    findings: list[Finding]

    @property
    def all_flows(self) -> list[Flow]:
        seen: dict[str, Flow] = {}
        for flow in self.directly_impacted + self.transitively_impacted:
            seen[flow.id] = flow
        return list(seen.values())


def query_model(model: ProjectModel, question: str, limit: int = 10) -> list[QueryMatch]:
    terms = _terms(question)
    matches: list[QueryMatch] = []
    findings_by_flow: dict[str, list[Finding]] = {}
    for finding in model.findings:
        findings_by_flow.setdefault(finding.flow_id, []).append(finding)

    for flow in model.flows:
        score = 0
        reasons: list[str] = []
        name_text = f"{flow.name} {flow.symbol} {flow.entry_kind} {flow.framework}".lower()
        node_text = " ".join(node.label for node in flow.nodes).lower()
        finding_text = " ".join(
            finding.message for finding in findings_by_flow.get(flow.id, [])
        ).lower()
        for term in terms:
            if term in name_text:
                score += 6
                reasons.append(f"`{term}` matches the flow identity")
            if term in node_text:
                score += 3
                reasons.append(f"`{term}` appears in a decision or action")
            if term in finding_text:
                score += 4
                reasons.append(f"`{term}` appears in a review finding")
        if flow.is_entrypoint:
            score += 1
        if score:
            matches.append(QueryMatch(flow, score, list(dict.fromkeys(reasons))))
    return sorted(matches, key=lambda item: (-item.score, item.flow.name))[:limit]


def impact_model(model: ProjectModel, changed_files: list[str]) -> ImpactResult:
    normalized = {_normalize_path(item) for item in changed_files}
    direct = [flow for flow in model.flows if _normalize_path(flow.location.path) in normalized]
    by_id = {flow.id: flow for flow in model.flows}
    impacted_ids = {flow.id for flow in direct}
    queue = list(impacted_ids)
    transitive: list[Flow] = []
    while queue:
        current = by_id.get(queue.pop(0))
        if current is None:
            continue
        for caller_id in current.called_by:
            if caller_id in impacted_ids:
                continue
            impacted_ids.add(caller_id)
            queue.append(caller_id)
            caller = by_id.get(caller_id)
            if caller:
                transitive.append(caller)

    findings = [item for item in model.findings if item.flow_id in impacted_ids]
    return ImpactResult(
        changed_files=sorted(normalized),
        directly_impacted=sorted(direct, key=lambda item: item.name),
        transitively_impacted=sorted(transitive, key=lambda item: item.name),
        findings=findings,
    )


def render_query(matches: list[QueryMatch]) -> str:
    if not matches:
        return "No matching logic flows found."
    lines = []
    for index, match in enumerate(matches, 1):
        flow = match.flow
        lines.append(
            f"{index}. {flow.name} [{flow.entry_kind}] "
            f"{flow.location.path}:{flow.location.start_line}"
        )
        lines.append(f"   score={match.score} · " + "; ".join(match.reasons[:3]))
    return "\n".join(lines)


def render_impact(result: ImpactResult) -> str:
    lines = [
        f"Changed files: {len(result.changed_files)}",
        f"Directly impacted flows: {len(result.directly_impacted)}",
        f"Transitively impacted flows: {len(result.transitively_impacted)}",
        f"Related review findings: {len(result.findings)}",
    ]
    if result.directly_impacted:
        lines.append("\nDirect impact:")
        lines.extend(
            f"- {flow.name} ({flow.location.path}:{flow.location.start_line})"
            for flow in result.directly_impacted
        )
    if result.transitively_impacted:
        lines.append("\nCaller impact:")
        lines.extend(
            f"- {flow.name} ({flow.location.path}:{flow.location.start_line})"
            for flow in result.transitively_impacted
        )
    if result.findings:
        lines.append("\nReview before changing:")
        lines.extend(f"- {finding.message}" for finding in result.findings)
    return "\n".join(lines)


def model_summary(model: ProjectModel) -> dict[str, Any]:
    """An orientation snapshot: counts of flows, findings by kind/severity/evidence."""
    return {
        "flows": len(model.flows),
        "entrypoints": sum(flow.is_entrypoint for flow in model.flows),
        "languages": model.metadata.get("languages", []),
        "findings": {
            "total": len(model.findings),
            "by_kind": dict(Counter(item.kind for item in model.findings)),
            "by_severity": dict(Counter(item.severity.value for item in model.findings)),
            "by_evidence": dict(Counter(item.evidence.value for item in model.findings)),
        },
        "enums": {
            language: sorted(members)
            for language, members in model.metadata.get("enums", {}).items()
        },
    }


def explain_finding(model: ProjectModel, finding_id: str) -> dict[str, Any] | None:
    """The full deterministic evidence chain behind one finding."""
    finding = next((item for item in model.findings if item.id == finding_id), None)
    if finding is None:
        return None
    flow = next((item for item in model.flows if item.id == finding.flow_id), None)
    node = None
    if flow is not None and finding.node_id:
        node = next((item for item in flow.nodes if item.id == finding.node_id), None)
    decision = None
    if node is not None:
        decision = {
            "label": node.label,
            "condition": node.metadata.get("condition"),
            "subject": node.metadata.get("subject"),
            "branches": node.metadata.get("branches"),
        }
    return {
        "id": finding.id,
        "kind": finding.kind,
        "severity": finding.severity.value,
        "evidence": finding.evidence.value,
        "message": finding.message,
        "detail": finding.detail,
        "location": f"{finding.location.path}:{finding.location.start_line}",
        "flow": flow.name if flow else None,
        "decision": decision,
        "metadata": finding.metadata,
    }


def where_is_state_handled(
    model: ProjectModel, domain: str, value: str | None = None
) -> list[dict[str, Any]]:
    """Every flow that branches on a domain/value-namespace, with the values it covers."""
    results: list[dict[str, Any]] = []
    for flow in model.flows:
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            namespaces = {
                str(node.metadata.get("domain", "")),
                str(node.metadata.get("value_namespace", "")),
            }
            if domain not in namespaces:
                continue
            values = [str(item) for item in node.metadata.get("values", [])]
            if value is not None and value not in values:
                continue
            results.append(
                {
                    "flow": flow.name,
                    "subject": node.metadata.get("subject"),
                    "values": values,
                    "source": f"{node.location.path}:{node.location.start_line}",
                }
            )
    return results


def find_decisions(
    model: ProjectModel,
    *,
    domain: str | None = None,
    subject: str | None = None,
    missing_fallback: bool = False,
) -> list[dict[str, Any]]:
    """Structured search over decision nodes (by domain/subject/missing-fallback)."""
    gap_nodes = {
        item.node_id
        for item in model.findings
        if item.kind in {"missing_branch", "enum_exhaustiveness", "inconsistent_case_handling"}
    }
    results: list[dict[str, Any]] = []
    for flow in model.flows:
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            if domain is not None and node.metadata.get("domain") != domain:
                continue
            if subject is not None and subject not in str(node.metadata.get("subject", "")):
                continue
            has_gap = node.id in gap_nodes
            if missing_fallback and not has_gap:
                continue
            results.append(
                {
                    "flow": flow.name,
                    "subject": node.metadata.get("subject"),
                    "operator": node.metadata.get("operator"),
                    "values": node.metadata.get("values"),
                    "has_gap": has_gap,
                    "source": f"{node.location.path}:{node.location.start_line}",
                }
            )
    return results


def git_changed_files(root: Path) -> list[str]:
    import subprocess

    commands = [
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ]
    files: set[str] = set()
    for command in commands:
        result = subprocess.run(
            command,
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            files.update(line.strip() for line in result.stdout.splitlines() if line.strip())
    return sorted(files)


def _terms(question: str) -> list[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "does",
        "flow",
        "for",
        "from",
        "how",
        "in",
        "is",
        "of",
        "the",
        "to",
        "what",
        "where",
        "which",
    }
    return [
        token
        for token in re.findall(r"[a-zA-Z0-9_]+", question.lower())
        if len(token) > 1 and token not in stopwords
    ]


def _normalize_path(value: str) -> str:
    return value.replace("\\", "/").lstrip("./")
