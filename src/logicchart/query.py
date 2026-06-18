from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logicchart.diagnostics import diagnostic_for_finding, finding_rule_contracts_by_kind
from logicchart.model import Finding, FindingKind, Flow, NodeKind, ProjectModel
from logicchart.quality import model_quality

# Per-bucket relevance weights. Named constants instead of inline magic numbers so the
# ranking model is auditable and the tests can assert exact scores.
IDENTITY_WEIGHT = 6
NODE_WEIGHT = 3
FINDING_WEIGHT = 4
STRUCTURE_WEIGHT = 5
METADATA_WEIGHT = 2
# Tie-breaker only: nudges an entrypoint above an otherwise-equal non-entrypoint. Added
# only when the term-overlap score is already > 0, so it never manufactures a match.
ENTRYPOINT_BONUS = 1


@dataclass(slots=True)
class QueryMatch:
    flow: Flow
    score: int
    reasons: list[str]

    def to_dict(self, include_source: bool = True) -> dict[str, Any]:
        """The single serialization shared by the CLI ``--json`` path and the MCP
        ``query_logic`` tool, so both surfaces emit an identical JSON shape."""
        payload: dict[str, Any] = {
            "flow_id": self.flow.id,
            "name": self.flow.name,
            "language": self.flow.language,
            "entry_kind": self.flow.entry_kind,
            "framework": self.flow.framework,
            "scope": self.flow.metadata.get("scope", []),
            "score": self.score,
            "reasons": self.reasons,
        }
        if include_source:
            payload["source"] = f"{self.flow.location.path}:{self.flow.location.start_line}"
        return payload


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


def query_model(
    model: ProjectModel,
    question: str,
    limit: int = 10,
    scope: str | None = None,
    language: str | None = None,
    finding_kind: str | None = None,
) -> list[QueryMatch]:
    terms = _terms(question)
    if not terms:
        # A blank or punctuation-only question has nothing to rank against. Returning []
        # (rather than every entrypoint) makes the CLI print "No matching logic flows
        # found." instead of garbage filler.
        return []
    # Dedup query terms before scoring so repeating a word ("user user user") cannot
    # inflate a flow's rank. dict.fromkeys preserves order for stable reason text.
    unique_terms = list(dict.fromkeys(terms))

    matches: list[QueryMatch] = []
    findings_by_flow: dict[str, list[Finding]] = {}
    for finding in model.findings:
        findings_by_flow.setdefault(finding.flow_id, []).append(finding)

    for flow in model.flows:
        if not flow_in_scope(flow, scope):
            continue
        if language is not None and flow.language != language:
            continue
        # Match on tokens, not substrings: "order" must not match inside "reordering".
        name_tokens = _tokenize(f"{flow.name} {flow.symbol}")
        node_tokens = _tokenize(" ".join(node.label for node in flow.nodes))
        structure_tokens = _tokenize(
            " ".join(
                [
                    flow.location.path,
                    flow.language,
                    " ".join(str(item) for item in flow.metadata.get("scope", [])),
                ]
            )
        )
        metadata_tokens = _flow_metadata_tokens(flow)
        flow_findings = [
            finding
            for finding in findings_by_flow.get(flow.id, [])
            if finding_kind is None or finding.kind == finding_kind
        ]
        if finding_kind is not None and not flow_findings:
            continue
        finding_tokens = _tokenize(
            " ".join(
                f"{finding.kind} {finding.evidence.value} {finding.severity.value} "
                f"{finding.message} {_metadata_text(_query_metadata(finding.metadata))}"
                for finding in flow_findings
            )
        )
        score = 0
        reasons: list[str] = []
        for term in unique_terms:
            if term in name_tokens:
                score += IDENTITY_WEIGHT
                reasons.append(f"`{term}` matches the flow identity")
            if term in node_tokens:
                score += NODE_WEIGHT
                reasons.append(f"`{term}` appears in a decision or action")
            if term in structure_tokens:
                score += STRUCTURE_WEIGHT
                reasons.append(f"`{term}` matches flow structure")
            if term in metadata_tokens:
                score += METADATA_WEIGHT
                reasons.append(f"`{term}` appears in decision metadata")
            if term in finding_tokens:
                score += FINDING_WEIGHT
                reasons.append(f"`{term}` appears in a review finding")
        # The entrypoint bonus is a tie-breaker among real matches, never a match on its
        # own: only add it once the term-overlap score is already positive.
        if score:
            if flow.is_entrypoint:
                score += ENTRYPOINT_BONUS
            matches.append(QueryMatch(flow, score, list(dict.fromkeys(reasons))))
    # Deterministic order: score desc, then name, then unique id, so equal score+name is
    # stable regardless of flow insertion order.
    matches.sort(key=lambda item: (-item.score, item.flow.name, item.flow.id))
    if limit and limit > 0:
        matches = matches[:limit]
    return matches


def impact_model(
    model: ProjectModel, changed_files: list[str], scope: str | None = None
) -> ImpactResult:
    normalized = {_normalize_path(item) for item in changed_files}
    flows = [flow for flow in model.flows if flow_in_scope(flow, scope)]
    direct = [flow for flow in flows if _normalize_path(flow.location.path) in normalized]
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

    transitive = [flow for flow in transitive if flow_in_scope(flow, scope)]
    impacted_ids = {flow.id for flow in direct} | {flow.id for flow in transitive}
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
    rules = model.metadata.get("finding_rules") or finding_rule_contracts_by_kind()
    quality = model.metadata.get("quality") or model_quality(model)
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
        "finding_rules": {
            "total": len(rules),
            "by_category": dict(
                Counter(str(item.get("category", "project")) for item in rules.values())
            ),
        },
        "enums": {
            language: sorted(members)
            for language, members in model.metadata.get("enums", {}).items()
        },
        "scopes": model.metadata.get("scopes", {}),
        "quality": quality,
    }


def flow_in_scope(flow: Flow, scope: str | None) -> bool:
    """Whether a flow belongs to the requested macro-part (None = no filter)."""
    return scope is None or scope in flow.metadata.get("scope", [])


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
    diagnostic = finding.metadata.get("diagnostic")
    if not isinstance(diagnostic, dict):
        diagnostic = diagnostic_for_finding(finding, flow=flow, node=node)
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
        "diagnostic": diagnostic,
    }


def where_is_state_handled(
    model: ProjectModel, domain: str, value: str | None = None
) -> list[dict[str, Any]]:
    """Every flow that branches on a domain/value-namespace, with the values it covers."""
    results: list[dict[str, Any]] = []
    if not domain:
        # An empty domain is not a wildcard: it would match empty metadata and return
        # every decision node.
        return results
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
        if item.kind
        in {
            FindingKind.MISSING_BRANCH,
            FindingKind.ENUM_EXHAUSTIVENESS,
            FindingKind.INCONSISTENT_CASE_HANDLING,
        }
    }
    results: list[dict[str, Any]] = []
    for flow in model.flows:
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            if domain is not None and node.metadata.get("domain") != domain:
                continue
            # Equality match on subject, consistent with where_is_state_handled's exact
            # domain/value matching (was a substring test, so "status" matched
            # "order_status").
            if subject is not None and str(node.metadata.get("subject", "")) != subject:
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
    # \w is unicode-aware in py3, so "café" / "日本語" survive tokenization instead of
    # being dropped or split by the ASCII-only [a-zA-Z0-9_] class.
    return [
        token
        for token in re.findall(r"\w+", question.lower())
        if len(token) > 1 and token not in stopwords
    ]


def _tokenize(text: str) -> set[str]:
    """The field-side tokenizer that mirrors ``_terms`` (unicode \\w words, lowercased),
    so query terms are matched against whole tokens rather than substrings."""
    return set(re.findall(r"\w+", text.lower()))


def _flow_metadata_tokens(flow: Flow) -> set[str]:
    values: list[str] = []
    for node in flow.nodes:
        values.extend(
            str(node.metadata.get(key, ""))
            for key in ("domain", "subject", "value_namespace", "operator")
        )
        values.extend(str(item) for item in node.metadata.get("values", []))
        values.extend(str(item) for item in node.metadata.get("effects", []))
        for branch in node.metadata.get("branches", []):
            if isinstance(branch, dict):
                values.extend(str(branch.get(key, "")) for key in ("label", "outcome"))
    return _tokenize(" ".join(values))


def _metadata_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(f"{key} {_metadata_text(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return " ".join(_metadata_text(item) for item in value)
    return str(value)


def _query_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key != "diagnostic"}


def _normalize_path(value: str) -> str:
    # Strip only a leading "./" prefix - not the {'.', '/'} char set, which would
    # corrupt dot-prefixed paths like ".github/workflows/ci.yml".
    value = value.replace("\\", "/")
    return value[2:] if value.startswith("./") else value
