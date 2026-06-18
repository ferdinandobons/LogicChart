from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logicchart.diagnostics import diagnostic_for_finding, finding_rule_contracts_by_kind
from logicchart.model import Finding, FindingKind, Flow, FlowNode, NodeKind, ProjectModel
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
FINDING_CONTEXT_TOKENS_PER_ITEM = 80


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
    target_flow_ids: list[str] = field(default_factory=list)
    target_symbols: list[str] = field(default_factory=list)
    target_finding_ids: list[str] = field(default_factory=list)
    unresolved_targets: list[dict[str, str]] = field(default_factory=list)

    @property
    def all_flows(self) -> list[Flow]:
        seen: dict[str, Flow] = {}
        for flow in self.directly_impacted + self.transitively_impacted:
            seen[flow.id] = flow
        return list(seen.values())

    @property
    def subgraph_flow_ids(self) -> list[str]:
        return [flow.id for flow in self.all_flows]

    @property
    def subgraph_finding_ids(self) -> list[str]:
        return [finding.id for finding in self.findings]


def query_model(
    model: ProjectModel,
    question: str,
    limit: int = 10,
    scope: str | None = None,
    language: str | None = None,
    finding_kind: str | None = None,
    source_path: str | None = None,
    symbol: str | None = None,
    domain: str | None = None,
    value: str | None = None,
) -> list[QueryMatch]:
    terms = _terms(question)
    has_structured_filter = any(
        item is not None
        for item in (scope, language, finding_kind, source_path, symbol, domain, value)
    )
    if not terms and not has_structured_filter:
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
        filter_reasons = _structured_query_filter_reasons(
            flow,
            source_path=source_path,
            symbol=symbol,
            domain=domain,
            value=value,
        )
        if filter_reasons is None:
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
        if finding_kind is not None and flow_findings:
            filter_reasons.append(f"flow has `{finding_kind}` findings")
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
        if filter_reasons:
            score += STRUCTURE_WEIGHT * len(filter_reasons)
            reasons.extend(filter_reasons)
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
    model: ProjectModel,
    changed_files: list[str],
    scope: str | None = None,
    *,
    flow_ids: list[str] | None = None,
    symbols: list[str] | None = None,
    finding_ids: list[str] | None = None,
) -> ImpactResult:
    normalized = {_normalize_path(item) for item in changed_files}
    flows = [flow for flow in model.flows if flow_in_scope(flow, scope)]
    direct = [flow for flow in flows if _normalize_path(flow.location.path) in normalized]
    by_id = {flow.id: flow for flow in model.flows}
    scoped_ids = {flow.id for flow in flows}
    target_flow_ids = _unique(flow_ids or [])
    target_symbols = _unique(symbols or [])
    target_finding_ids = _unique(finding_ids or [])
    unresolved_targets: list[dict[str, str]] = []
    direct_by_id = {flow.id: flow for flow in direct}

    def add_flow(flow: Flow, target_type: str, value: str) -> None:
        if flow.id not in scoped_ids:
            unresolved_targets.append(
                {"type": target_type, "value": value, "reason": "scope_filtered"}
            )
            return
        direct_by_id[flow.id] = flow

    for flow_id in target_flow_ids:
        flow = by_id.get(flow_id)
        if flow is None:
            unresolved_targets.append({"type": "flow", "value": flow_id, "reason": "not_found"})
            continue
        add_flow(flow, "flow", flow_id)

    for symbol in target_symbols:
        matches = [flow for flow in model.flows if flow.symbol == symbol or flow.name == symbol]
        if not matches:
            unresolved_targets.append({"type": "symbol", "value": symbol, "reason": "not_found"})
            continue
        for flow in matches:
            add_flow(flow, "symbol", symbol)

    findings_by_id = {finding.id: finding for finding in model.findings}
    for finding_id in target_finding_ids:
        finding = findings_by_id.get(finding_id)
        if finding is None:
            unresolved_targets.append(
                {"type": "finding", "value": finding_id, "reason": "not_found"}
            )
            continue
        flow = by_id.get(finding.flow_id)
        if flow is None:
            unresolved_targets.append(
                {"type": "finding", "value": finding_id, "reason": "flow_not_found"}
            )
            continue
        add_flow(flow, "finding", finding_id)

    direct = list(direct_by_id.values())
    impacted_ids = set(direct_by_id)
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
        target_flow_ids=target_flow_ids,
        target_symbols=target_symbols,
        target_finding_ids=target_finding_ids,
        unresolved_targets=unresolved_targets,
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
    target_count = (
        len(result.target_flow_ids) + len(result.target_symbols) + len(result.target_finding_ids)
    )
    lines = [
        f"Changed files: {len(result.changed_files)}",
        f"Explicit targets: {target_count}",
        f"Directly impacted flows: {len(result.directly_impacted)}",
        f"Transitively impacted flows: {len(result.transitively_impacted)}",
        f"Related review findings: {len(result.findings)}",
    ]
    if result.target_flow_ids or result.target_symbols or result.target_finding_ids:
        lines.append("\nTargets:")
        if result.target_flow_ids:
            lines.append(f"- flows: {', '.join(result.target_flow_ids)}")
        if result.target_symbols:
            lines.append(f"- symbols: {', '.join(result.target_symbols)}")
        if result.target_finding_ids:
            lines.append(f"- findings: {', '.join(result.target_finding_ids)}")
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
    if result.unresolved_targets:
        lines.append("\nUnresolved targets:")
        lines.extend(
            f"- {item['type']} {item['value']}: {item['reason']}"
            for item in result.unresolved_targets
        )
    return "\n".join(lines)


def render_finding_explanation(explanation: dict[str, Any]) -> str:
    diagnostic = explanation.get("diagnostic") or {}
    confidence = diagnostic.get("confidence") or {}
    scope = diagnostic.get("scope") or {}
    decision = explanation.get("decision") or {}
    lines = [
        f"Finding: {explanation['id']}",
        f"Kind: {explanation['kind']}",
        f"Evidence: {explanation['evidence']} ({confidence.get('basis', 'unknown basis')})",
        f"Severity: {explanation['severity']}",
        f"Location: {explanation['location']}",
        f"Flow: {explanation.get('flow') or '(unknown)'}",
        f"Message: {explanation['message']}",
    ]
    if explanation.get("detail"):
        lines.append(f"Detail: {explanation['detail']}")
    if decision:
        lines.append("\nDecision:")
        lines.append(f"- label: {decision.get('label') or '(unknown)'}")
        if decision.get("subject"):
            lines.append(f"- subject: {decision['subject']}")
        if decision.get("condition"):
            lines.append(f"- condition: {decision['condition']}")
        branches = decision.get("branches") or []
        if branches:
            lines.append(f"- branches: {_compact_list(branches)}")
    if diagnostic:
        lines.append("\nDiagnostic:")
        lines.append(f"- rule: {diagnostic.get('rule_id', explanation['kind'])}")
        lines.append(f"- category: {diagnostic.get('category', 'unknown')}")
        lines.append(f"- source: {scope.get('source', explanation['location'])}")
        if diagnostic.get("missing"):
            lines.append(f"- missing: {_compact_list(diagnostic['missing'])}")
        if diagnostic.get("expected"):
            lines.append(f"- expected: {_metadata_text(diagnostic['expected'])}")
        if diagnostic.get("actual"):
            lines.append(f"- actual: {_metadata_text(diagnostic['actual'])}")
        if diagnostic.get("review_prompt"):
            lines.append(f"- review: {diagnostic['review_prompt']}")
    actions = diagnostic.get("suggested_next_actions") or []
    if actions:
        lines.append("\nSuggested next actions:")
        lines.extend(f"- {action}" for action in actions[:4])
    chain = diagnostic.get("evidence_chain") or []
    if chain:
        lines.append("\nEvidence chain:")
        for item in chain[:6]:
            item_type = str(item.get("type", "evidence"))
            location = (
                item.get("source")
                or _location_text(item.get("location"))
                or scope.get("source")
                or explanation["location"]
            )
            summary = _evidence_summary(item)
            lines.append(f"- {item_type} @ {location}: {summary}")
        omitted = len(chain) - 6
        if omitted > 0:
            lines.append(f"- {omitted} additional evidence item(s) omitted")
    lines.append("\nGuardrail:")
    lines.append(f"- {evidence_guardrail(explanation['evidence'])}")
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
        "language_capabilities": model.metadata.get("language_capabilities", {}),
        "enums": {
            language: sorted(members)
            for language, members in model.metadata.get("enums", {}).items()
        },
        "scopes": model.metadata.get("scopes", {}),
        "quality": quality,
    }


def evidence_guardrail(evidence: str) -> str:
    if evidence == "VERIFIED":
        return "syntax-backed fact"
    if evidence == "INFERRED":
        return "deterministic heuristic; inspect before treating as a confirmed bug"
    return "review candidate; never treat as a confirmed bug without inspection"


def _compact_list(value: Any, limit: int = 6) -> str:
    items = _list_value(value)
    shown = items[:limit]
    text = ", ".join(_metadata_text(item) for item in shown)
    omitted = len(items) - len(shown)
    return f"{text} (+{omitted} more)" if omitted > 0 else text


def _evidence_summary(item: dict[str, Any]) -> str:
    if "nodes" in item and isinstance(item["nodes"], list):
        return f"{len(item['nodes'])} related node(s)"
    if "values" in item:
        return f"values: {_compact_list(item['values'])}"
    if "branches" in item:
        return f"branches: {_compact_list(item['branches'])}"
    payload = {
        key: value
        for key, value in item.items()
        if key not in {"type", "location", "source"} and value not in (None, "", [], {})
    }
    return _metadata_text(payload) if payload else "see source range"


def _location_text(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    path = value.get("path")
    line = value.get("start_line")
    if not path or line is None:
        return None
    return f"{path}:{line}"


def flow_in_scope(flow: Flow, scope: str | None) -> bool:
    """Whether a flow belongs to the requested macro-part (None = no filter)."""
    return scope is None or scope in flow.metadata.get("scope", [])


def _structured_query_filter_reasons(
    flow: Flow,
    *,
    source_path: str | None,
    symbol: str | None,
    domain: str | None,
    value: str | None,
) -> list[str] | None:
    reasons: list[str] = []
    if source_path is not None:
        needle = _normalize_path(source_path)
        haystack = _normalize_path(flow.location.path)
        if needle not in haystack:
            return None
        reasons.append(f"source path matches `{needle}`")
    if symbol is not None:
        if symbol not in {flow.symbol, flow.name, flow.id}:
            return None
        reasons.append(f"symbol/name matches `{symbol}`")
    if domain is not None or value is not None:
        decision = _flow_has_decision_filter(flow, domain=domain, value=value)
        if decision is None:
            return None
        if domain is not None:
            reasons.append(f"decision domain matches `{domain}`")
        if value is not None:
            reasons.append(f"decision value matches `{value}`")
    return reasons


def _flow_has_decision_filter(
    flow: Flow, *, domain: str | None, value: str | None
) -> FlowNode | None:
    for node in flow.nodes:
        if node.kind is not NodeKind.DECISION:
            continue
        domains = {
            str(node.metadata.get("domain", "")),
            str(node.metadata.get("value_namespace", "")),
        }
        if domain is not None and domain not in domains:
            continue
        if value is not None and value not in _decision_values(node):
            continue
        return node
    return None


def _decision_values(node: FlowNode) -> set[str]:
    values = {str(item) for item in node.metadata.get("values", [])}
    for branch in node.metadata.get("branches", []):
        if isinstance(branch, dict):
            values.add(str(branch.get("label", "")))
    return values


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
        diagnostic = diagnostic_for_finding(finding, flow=flow, node=node, model=model)
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


def finding_context(
    model: ProjectModel, finding_id: str, token_budget: int = 0
) -> dict[str, Any] | None:
    """A bounded deterministic subgraph around one finding for agents and MCP clients."""
    finding = next((item for item in model.findings if item.id == finding_id), None)
    if finding is None:
        return None
    flow = next((item for item in model.flows if item.id == finding.flow_id), None)
    node = None
    if flow is not None and finding.node_id:
        node = next((item for item in flow.nodes if item.id == finding.node_id), None)
    diagnostic = finding.metadata.get("diagnostic")
    if not isinstance(diagnostic, dict):
        diagnostic = diagnostic_for_finding(finding, flow=flow, node=node, model=model)
    related_flows = _finding_related_flows(model, finding, flow)
    related_nodes = _finding_related_nodes(related_flows, finding, diagnostic)
    related_flow_ids = {item.id for item, _roles in related_flows}
    related_findings = [
        _finding_context_finding(candidate)
        for candidate in model.findings
        if candidate.id != finding.id
        and candidate.flow_id in related_flow_ids
        and _finding_matches_context(candidate, finding)
    ]
    return {
        "finding": _finding_context_finding(finding),
        "evidence_guardrail": _evidence_guardrail(finding),
        "diagnostic_summary": {
            "rule_id": diagnostic.get("rule_id"),
            "category": diagnostic.get("category"),
            "confidence": diagnostic.get("confidence"),
            "missing": diagnostic.get("missing"),
            "expected": diagnostic.get("expected"),
            "actual": diagnostic.get("actual"),
            "review_prompt": diagnostic.get("review_prompt"),
        },
        "focus_flow": _context_flow_summary(flow, ["finding_flow"], model) if flow else None,
        "focus_node": _context_node_summary(flow, node, ["finding_node"]) if node else None,
        "related_flows": _context_cap(
            [
                _context_flow_summary(related_flow, roles, model)
                for related_flow, roles in related_flows
                if related_flow.id != finding.flow_id
            ],
            token_budget,
        ),
        "related_nodes": _context_cap(related_nodes, token_budget),
        "related_findings": _context_cap(related_findings, token_budget),
        "evidence_chain": diagnostic.get("evidence_chain", []),
        "suggested_next_actions": diagnostic.get("suggested_next_actions", []),
        "next_tools": {
            "visual_snapshot": {
                "tool": "get_finding_snapshot",
                "arguments": {"finding_id": finding.id, "format": "svg"},
            },
            "impact": {
                "tool": "analyze_impact",
                "arguments": {"finding_ids": [finding.id]},
            },
            "flow_navigation": {
                "tool": "get_flow_navigation",
                "arguments": {"flow_id": finding.flow_id},
            },
            "complete_flow": {"tool": "get_flow", "arguments": {"flow_id": finding.flow_id}},
        },
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


def _finding_related_flows(
    model: ProjectModel, finding: Finding, focus_flow: Flow | None
) -> list[tuple[Flow, list[str]]]:
    metadata = _query_metadata(finding.metadata)
    roles_by_flow: dict[str, set[str]] = {}
    flows_by_id = {flow.id: flow for flow in model.flows}

    def add(flow_id: str | None, role: str) -> None:
        if flow_id is None or flow_id not in flows_by_id:
            return
        roles_by_flow.setdefault(flow_id, set()).add(role)

    add(finding.flow_id, "finding_flow")
    if focus_flow is not None:
        for flow_id in focus_flow.calls:
            add(flow_id, "called_by_finding_flow")
        for flow_id in focus_flow.called_by:
            add(flow_id, "caller_of_finding_flow")

    subject = _metadata_string(metadata.get("subject"))
    namespace = _metadata_string(metadata.get("value_namespace"))
    condition = _metadata_string(metadata.get("condition"))
    missing_values = {str(item) for item in _list_value(metadata.get("missing"))}
    expected_value = _metadata_string(metadata.get("expected"))
    outcome_value = _metadata_string(metadata.get("outcome"))

    for flow in model.flows:
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            if subject and node.metadata.get("subject") == subject:
                if namespace and node.metadata.get("value_namespace") == namespace:
                    add(flow.id, "same_subject_namespace")
                elif not namespace:
                    add(flow.id, "same_subject")
            if condition and node.metadata.get("condition") == condition:
                add(flow.id, "same_condition")
            handled_values = {str(item) for item in node.metadata.get("values", [])}
            if missing_values and missing_values & handled_values:
                add(flow.id, "handles_missing_value")
            branches = node.metadata.get("branches", [])
            if isinstance(branches, list) and (expected_value or outcome_value):
                branch_text = _metadata_text(branches)
                if expected_value and expected_value in branch_text:
                    add(flow.id, "matches_expected_outcome")
                if outcome_value and outcome_value in branch_text:
                    add(flow.id, "matches_actual_outcome")

    return [
        (flows_by_id[flow_id], sorted(roles))
        for flow_id, roles in sorted(
            roles_by_flow.items(),
            key=lambda item: (
                0 if item[0] == finding.flow_id else 1,
                flows_by_id[item[0]].name,
                item[0],
            ),
        )
    ]


def _finding_related_nodes(
    related_flows: list[tuple[Flow, list[str]]],
    finding: Finding,
    diagnostic: dict[str, Any],
) -> list[dict[str, Any]]:
    metadata = _query_metadata(finding.metadata)
    subject = _metadata_string(metadata.get("subject"))
    namespace = _metadata_string(metadata.get("value_namespace"))
    condition = _metadata_string(metadata.get("condition"))
    missing_values = {str(item) for item in _list_value(metadata.get("missing"))}
    evidence_node_ids = set(_list_value(diagnostic.get("scope", {}).get("related_node_ids")))
    if finding.node_id:
        evidence_node_ids.add(finding.node_id)
    rows: list[dict[str, Any]] = []
    for flow, flow_roles in related_flows:
        for node in flow.nodes:
            reasons: list[str] = []
            if node.id in evidence_node_ids:
                reasons.append("finding_evidence")
            if (
                node.kind is NodeKind.DECISION
                and subject
                and node.metadata.get("subject") == subject
            ):
                if namespace and node.metadata.get("value_namespace") == namespace:
                    reasons.append("same_subject_namespace")
                elif not namespace:
                    reasons.append("same_subject")
            if (
                node.kind is NodeKind.DECISION
                and condition
                and node.metadata.get("condition") == condition
            ):
                reasons.append("same_condition")
            handled_values = {str(item) for item in node.metadata.get("values", [])}
            if missing_values and missing_values & handled_values:
                reasons.append("handles_missing_value")
            if not reasons:
                continue
            rows.append(_context_node_summary(flow, node, sorted(set(reasons)), flow_roles))
    return sorted(
        rows,
        key=lambda item: (
            0 if item["flow_id"] == finding.flow_id else 1,
            item["flow_name"],
            item["node_id"],
        ),
    )


def _finding_matches_context(candidate: Finding, finding: Finding) -> bool:
    candidate_metadata = _query_metadata(candidate.metadata)
    metadata = _query_metadata(finding.metadata)
    if candidate.kind == finding.kind:
        return True
    for key in ("subject", "value_namespace", "condition", "rule"):
        if metadata.get(key) is not None and candidate_metadata.get(key) == metadata.get(key):
            return True
    missing = {str(item) for item in _list_value(metadata.get("missing"))}
    candidate_missing = {str(item) for item in _list_value(candidate_metadata.get("missing"))}
    return bool(missing and missing & candidate_missing)


def _finding_context_finding(finding: Finding) -> dict[str, Any]:
    return {
        "id": finding.id,
        "kind": _enum_text(finding.kind),
        "severity": _enum_text(finding.severity),
        "evidence": _enum_text(finding.evidence),
        "message": finding.message,
        "flow_id": finding.flow_id,
        "node_id": finding.node_id,
        "source": f"{finding.location.path}:{finding.location.start_line}",
    }


def _context_flow_summary(flow: Flow, roles: list[str], model: ProjectModel) -> dict[str, Any]:
    return {
        "id": flow.id,
        "name": flow.name,
        "roles": roles,
        "language": flow.language,
        "entry_kind": flow.entry_kind,
        "source": f"{flow.location.path}:{flow.location.start_line}",
        "scope": flow.metadata.get("scope", []),
        "nodes": len(flow.nodes),
        "decisions": sum(node.kind is NodeKind.DECISION for node in flow.nodes),
        "calls": len(flow.calls),
        "callers": len(flow.called_by),
        "findings": sum(item.flow_id == flow.id for item in model.findings),
    }


def _context_node_summary(
    flow: Flow | None,
    node: Any,
    reasons: list[str],
    flow_roles: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "flow_id": flow.id if flow is not None else None,
        "flow_name": flow.name if flow is not None else None,
        "flow_roles": flow_roles or [],
        "node_id": node.id,
        "label": node.label,
        "kind": _enum_text(node.kind),
        "reasons": reasons,
        "source": f"{node.location.path}:{node.location.start_line}",
        "condition": node.metadata.get("condition"),
        "subject": node.metadata.get("subject"),
        "value_namespace": node.metadata.get("value_namespace"),
        "values": node.metadata.get("values", []),
        "branches": node.metadata.get("branches", []),
    }


def _evidence_guardrail(finding: Finding) -> dict[str, str]:
    if finding.evidence.value == "VERIFIED":
        meaning = "syntax-backed fact"
    elif finding.evidence.value == "INFERRED":
        meaning = "deterministic heuristic; inspect before treating as a bug"
    else:
        meaning = "review candidate; never treat as a confirmed bug without inspection"
    return {"tier": finding.evidence.value, "meaning": meaning}


def _context_cap(items: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return items
    return items[: max(1, token_budget // FINDING_CONTEXT_TOKENS_PER_ITEM)]


def _metadata_string(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else _metadata_text(value)


def _list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _enum_text(value: Any) -> str:
    return value.value if hasattr(value, "value") else str(value)


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


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in values if item))


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
