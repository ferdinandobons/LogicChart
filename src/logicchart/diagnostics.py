from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from logicchart.analysis.common import EMPTY, FALLS_THROUGH, NO, RAISES, RETURNS, SUCCESS
from logicchart.model import Evidence, Finding, FindingKind, Flow, FlowNode, NodeKind

DIAGNOSTIC_RELATED_LIMIT = 12


@dataclass(frozen=True, slots=True)
class FindingRule:
    """Stable public contract for one finding detector."""

    rule_id: str
    category: str
    title: str
    purpose: str
    preconditions: tuple[str, ...]
    evidence_rationale: str
    caveats: tuple[str, ...]
    metadata_fields: tuple[str, ...]
    review_prompt: str
    suggested_next_actions: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("preconditions", "caveats", "metadata_fields", "suggested_next_actions"):
            data[key] = list(data[key])
        return data


FINDING_RULES: dict[str, FindingRule] = {
    FindingKind.MISSING_BRANCH.value: FindingRule(
        rule_id=FindingKind.MISSING_BRANCH.value,
        category="single_flow",
        title="Missing explicit fallback",
        purpose="Find state-like decisions that omit an explicit else/default path.",
        preconditions=(
            "The node is a decision over a state-like subject, domain, or value namespace.",
            "The decision has at least one implicit fallback branch.",
        ),
        evidence_rationale=(
            "Review-only because an omitted fallback can be intentional for closed or "
            "externally constrained states."
        ),
        caveats=(
            "A framework, validator, or earlier guard can make the implicit path unreachable.",
            "A data-driven dispatch may be exhaustive outside the visible source snippet.",
        ),
        metadata_fields=("category",),
        review_prompt="Should this decision define an explicit else/default for unhandled states?",
        suggested_next_actions=(
            "Inspect the selected decision node and source range.",
            "Add an explicit else/default when the omitted path is real.",
            "Suppress or document the finding when an upstream invariant proves exhaustiveness.",
        ),
    ),
    FindingKind.DEAD_CODE.value: FindingRule(
        rule_id=FindingKind.DEAD_CODE.value,
        category="single_flow",
        title="Unreachable code",
        purpose="Find statements after all currently modeled paths return or raise.",
        preconditions=(
            "The analyzer observed a point where all predecessor paths already exit.",
            "A later statement remains in the same flow after that exit point.",
        ),
        evidence_rationale="Inferred from deterministic control-flow reachability.",
        caveats=(
            "Dynamic exceptions, decorators, or language-specific control effects may be "
            "invisible.",
        ),
        metadata_fields=("category",),
        review_prompt=(
            "Can the unreachable statement be removed, or should an earlier branch stop exiting?"
        ),
        suggested_next_actions=(
            "Inspect the previous return/raise paths.",
            "Remove dead code when it is accidental.",
            "Refactor the branch when the later code should still run.",
        ),
    ),
    FindingKind.BROAD_EXCEPT_SWALLOW.value: FindingRule(
        rule_id=FindingKind.BROAD_EXCEPT_SWALLOW.value,
        category="single_flow",
        title="Swallowed exception",
        purpose="Find exception handlers that hide failures by doing nothing or only logging.",
        preconditions=(
            "The decision is an error/exception branch.",
            "The handler neither re-raises nor returns an explicit error path.",
        ),
        evidence_rationale="Inferred from deterministic branch outcome and call-effect metadata.",
        caveats=(
            "A custom logging helper may persist or escalate outside LogicChart's current "
            "effect model.",
        ),
        metadata_fields=("category",),
        review_prompt=(
            "Should this handler re-raise, return an error result, or explicitly document "
            "suppression?"
        ),
        suggested_next_actions=(
            "Inspect the handler body.",
            "Return or raise an explicit failure path when callers need to know.",
            "Document intentional suppression when the failure is safely absorbed.",
        ),
    ),
    FindingKind.NO_OP_BRANCH.value: FindingRule(
        rule_id=FindingKind.NO_OP_BRANCH.value,
        category="single_flow",
        title="Empty branch",
        purpose="Find explicit branches whose body performs no modeled work.",
        preconditions=(
            "The branch is explicit rather than an implicit fallback.",
            "The branch outcome is empty and is not an error handler or dispatch case.",
        ),
        evidence_rationale="Inferred from deterministic branch body analysis.",
        caveats=("A placeholder branch may be intentional during development.",),
        metadata_fields=("category",),
        review_prompt="Is this branch intentionally empty, or is it missing behavior?",
        suggested_next_actions=(
            "Inspect the selected branch.",
            "Add the missing behavior or remove the dead branch.",
            "Leave an explicit comment when the no-op is intentional.",
        ),
    ),
    FindingKind.ASYMMETRIC_RETURN.value: FindingRule(
        rule_id=FindingKind.ASYMMETRIC_RETURN.value,
        category="single_flow",
        title="Asymmetric dispatch return",
        purpose="Find dispatch cases where most branches exit but at least one falls through.",
        preconditions=(
            "The decision is a switch/match-style dispatch.",
            "Most explicit cases return or raise.",
            "At least one explicit case falls through after doing work.",
        ),
        evidence_rationale="Inferred from deterministic branch outcome comparison.",
        caveats=("A fall-through branch may intentionally continue shared tail logic.",),
        metadata_fields=("category",),
        review_prompt="Should the fall-through case return/raise like its sibling cases?",
        suggested_next_actions=(
            "Inspect the fall-through case and shared tail.",
            "Add an explicit return or raise when the fall-through is accidental.",
            "Document intentional fall-through when shared tail logic is required.",
        ),
    ),
    FindingKind.DEAD_GUARD.value: FindingRule(
        rule_id=FindingKind.DEAD_GUARD.value,
        category="single_flow",
        title="Constant guard",
        purpose="Find guards on module-level boolean constants that are always true or false.",
        preconditions=(
            "The guard subject resolves to a module-level boolean constant.",
            "The subject is not shadowed inside the flow.",
        ),
        evidence_rationale=(
            "Inferred because the constant could still be reassigned dynamically elsewhere."
        ),
        caveats=("Runtime mutation or configuration injection can change the value.",),
        metadata_fields=("category", "constant", "always"),
        review_prompt="Is this constant guard still needed, or should the dead branch be removed?",
        suggested_next_actions=(
            "Inspect the constant definition and selected guard.",
            "Remove unreachable branch logic when the constant is fixed.",
            "Avoid flagging by making runtime configuration explicit when it is mutable.",
        ),
    ),
    FindingKind.INCONSISTENT_CASE_HANDLING.value: FindingRule(
        rule_id=FindingKind.INCONSISTENT_CASE_HANDLING.value,
        category="cross_flow",
        title="Inconsistent sibling case handling",
        purpose="Find sibling flows that omit values handled by a strict majority.",
        preconditions=(
            "At least three sibling flows branch on the same language, subject, and value "
            "namespace.",
            "A strict majority handles the missing value.",
            "The flagged flow has no explicit default for that subject and namespace.",
        ),
        evidence_rationale=(
            "Review-only because quorum detects an inconsistency pattern, not a declared contract."
        ),
        caveats=(
            "The flagged flow may intentionally support a narrower state set.",
            "Sibling grouping is deterministic but still heuristic.",
        ),
        metadata_fields=(
            "category",
            "subject",
            "value_namespace",
            "missing",
            "confidence",
            "quorum",
        ),
        review_prompt="Should this flow handle the values that its sibling flows usually cover?",
        suggested_next_actions=(
            "Compare the selected flow with the sibling flows in the same value namespace.",
            "Add missing cases or an explicit default when the omission is accidental.",
            "Document the narrower contract when the omission is intentional.",
        ),
    ),
    FindingKind.ENUM_EXHAUSTIVENESS.value: FindingRule(
        rule_id=FindingKind.ENUM_EXHAUSTIVENESS.value,
        category="cross_flow",
        title="Non-exhaustive declared enum dispatch",
        purpose="Find dispatches that omit declared enum or union members without a default.",
        preconditions=(
            "The analyzer extracted a declared closed set for the value namespace.",
            "One dispatch handles multiple declared members.",
            "The dispatch omits at least one declared member and has no explicit default.",
        ),
        evidence_rationale=(
            "Inferred from deterministic declared-set extraction and branch coverage."
        ),
        caveats=(
            "The declared set can include values that are impossible in this narrower flow.",
            "A framework or validator may reject omitted values before this function runs.",
        ),
        metadata_fields=("category", "subject", "value_namespace", "missing", "declared"),
        review_prompt=(
            "Should this dispatch handle every declared member or add an explicit default?"
        ),
        suggested_next_actions=(
            "Inspect the selected dispatch and declared value set.",
            "Add missing cases for real states.",
            "Add an explicit default or suppression when upstream validation proves the subset.",
        ),
    ),
    FindingKind.OUTCOME_INCONSISTENCY.value: FindingRule(
        rule_id=FindingKind.OUTCOME_INCONSISTENCY.value,
        category="cross_flow",
        title="Inconsistent sibling outcome",
        purpose="Find equivalent conditions that resolve to different material outcomes.",
        preconditions=(
            "At least three sibling flows contain the same positive subject/value condition.",
            "A strict majority resolves that condition to one outcome.",
            "The flagged flow resolves the same condition differently.",
        ),
        evidence_rationale="Inferred from deterministic condition and terminal outcome comparison.",
        caveats=(
            "Different routes may intentionally return different errors for the same state.",
            "Outcome signatures are compact and may not capture every domain-specific distinction.",
        ),
        metadata_fields=("category", "subject", "value", "outcome", "expected"),
        review_prompt="Is this different outcome intentional for the same condition?",
        suggested_next_actions=(
            "Compare the selected flow with sibling outcomes for the same condition.",
            "Align the outcome when consistency is required.",
            "Document the intentional divergence when the route contract differs.",
        ),
    ),
    FindingKind.LOGGING_ASYMMETRY.value: FindingRule(
        rule_id=FindingKind.LOGGING_ASYMMETRY.value,
        category="cross_flow",
        title="Logging asymmetry",
        purpose="Find shared error-path guards logged by one sibling flow but silent in another.",
        preconditions=(
            "Sibling flows share the same guard condition.",
            "At least one sibling logs or alerts and then raises.",
            "The flagged flow handles the same guard silently.",
        ),
        evidence_rationale="Inferred from deterministic guard, call-effect, and outcome metadata.",
        caveats=("Logging may happen in middleware or a callee not resolved in the graph.",),
        metadata_fields=("category", "condition"),
        review_prompt="Should this guard log or alert like its sibling error path?",
        suggested_next_actions=(
            "Inspect the selected guard and sibling error path.",
            "Add logging or alerting when observability is required.",
            "Document intentional silence when noise reduction is deliberate.",
        ),
    ),
    FindingKind.AUTH_DIVERGENCE.value: FindingRule(
        rule_id=FindingKind.AUTH_DIVERGENCE.value,
        category="cross_flow",
        title="Authorization divergence",
        purpose="Find sibling entrypoints where one skips an authorization check others perform.",
        preconditions=(
            "The gated detector is enabled.",
            "Sibling entrypoints live in the same file.",
            "At least one sibling performs an authorization check.",
            "The flagged entrypoint has no visible authorization check.",
        ),
        evidence_rationale=(
            "Review-only because middleware, dependency injection, or route configuration can "
            "authorize invisibly."
        ),
        caveats=("Middleware or decorators may enforce authorization outside the function body.",),
        metadata_fields=("category", "rule"),
        review_prompt="Is authorization enforced for this entrypoint outside the visible flow?",
        suggested_next_actions=(
            "Inspect route middleware, dependencies, and decorators.",
            "Add an explicit authorization check if none exists.",
            "Suppress or document the finding when external enforcement is confirmed.",
        ),
    ),
}


def finding_rule_contracts(kind: str | None = None) -> list[dict[str, Any]]:
    """Return public detector contracts, optionally restricted to one finding kind."""
    if kind is not None:
        rule = FINDING_RULES.get(_kind_value(kind))
        return [rule.to_dict()] if rule is not None else []
    return [FINDING_RULES[key].to_dict() for key in sorted(FINDING_RULES)]


def finding_rule_contracts_by_kind() -> dict[str, dict[str, Any]]:
    return {key: FINDING_RULES[key].to_dict() for key in sorted(FINDING_RULES)}


def enrich_model_diagnostics(model: Any) -> None:
    """Attach normalized diagnostics and a shared rule registry to a ProjectModel."""
    model.metadata["finding_rules"] = finding_rule_contracts_by_kind()
    flows_by_id = {flow.id: flow for flow in model.flows}
    nodes_by_key = {
        (flow.id, node.id): node for flow in model.flows for node in getattr(flow, "nodes", [])
    }
    for finding in model.findings:
        flow = flows_by_id.get(finding.flow_id)
        node = nodes_by_key.get((finding.flow_id, finding.node_id))
        finding.metadata["diagnostic"] = diagnostic_for_finding(
            finding,
            flow=flow,
            node=node,
            model=model,
        )


def diagnostic_for_finding(
    finding: Finding,
    *,
    flow: Flow | None = None,
    node: FlowNode | None = None,
    model: Any | None = None,
) -> dict[str, Any]:
    kind = _kind_value(finding.kind)
    rule = FINDING_RULES.get(kind, _fallback_rule(kind))
    metadata = _metadata_without_diagnostic(finding.metadata)
    category = str(metadata.get("category") or rule.category)
    related_decisions = _related_decisions(finding, flow, node, metadata, model)
    return {
        "rule_id": rule.rule_id,
        "category": category,
        "severity": _enum_value(finding.severity),
        "evidence": _enum_value(finding.evidence),
        "confidence": _confidence(finding),
        "scope": _scope(finding, flow, node, category, related_decisions),
        "inputs": _inputs(metadata, node),
        "evidence_chain": _evidence_chain(finding, flow, node, metadata, related_decisions),
        "expected": _expected(metadata, node),
        "actual": _actual(metadata, node),
        "missing": _as_list(metadata.get("missing")),
        "review_prompt": rule.review_prompt,
        "suggested_next_actions": list(rule.suggested_next_actions),
    }


def rule_for_kind(kind: str | FindingKind) -> dict[str, Any] | None:
    rule = FINDING_RULES.get(_kind_value(kind))
    return rule.to_dict() if rule is not None else None


def _fallback_rule(kind: str) -> FindingRule:
    return FindingRule(
        rule_id=kind,
        category="project",
        title=kind.replace("_", " ").title(),
        purpose="Explain a finding emitted by a detector that is not yet in the registry.",
        preconditions=(),
        evidence_rationale="Uses the finding's emitted evidence tier.",
        caveats=("The detector contract has not been formalized yet.",),
        metadata_fields=(),
        review_prompt="Review the selected finding and source evidence.",
        suggested_next_actions=("Inspect the selected flow and source range.",),
    )


def _scope(
    finding: Finding,
    flow: Flow | None,
    node: FlowNode | None,
    category: str,
    related_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    location = finding.location
    related_flow_ids = _unique([finding.flow_id, *(item["flow_id"] for item in related_decisions)])
    related_node_ids = _unique(
        [
            *([finding.node_id] if finding.node_id else []),
            *(item["node_id"] for item in related_decisions),
        ]
    )
    return {
        "category": category,
        "flow_id": finding.flow_id,
        "flow_name": flow.name if flow is not None else None,
        "node_id": finding.node_id,
        "node_label": node.label if node is not None else None,
        "source": f"{location.path}:{location.start_line}",
        "path": location.path,
        "line": location.start_line,
        "end_line": location.end_line,
        "language": flow.language if flow is not None else None,
        "entry_kind": flow.entry_kind if flow is not None else None,
        "scopes": list(flow.metadata.get("scope", [])) if flow is not None else [],
        "related_flow_ids": related_flow_ids,
        "related_node_ids": related_node_ids,
    }


def _inputs(metadata: dict[str, Any], node: FlowNode | None) -> dict[str, Any]:
    result = {key: value for key, value in metadata.items() if key != "category"}
    if node is not None:
        result["decision"] = {
            "condition": node.metadata.get("condition"),
            "subject": node.metadata.get("subject"),
            "operator": node.metadata.get("operator"),
            "values": node.metadata.get("values", []),
            "branches": node.metadata.get("branches", []),
        }
    return result


def _evidence_chain(
    finding: Finding,
    flow: Flow | None,
    node: FlowNode | None,
    metadata: dict[str, Any],
    related_decisions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = [
        {
            "type": "finding",
            "message": finding.message,
            "detail": finding.detail,
            "source": f"{finding.location.path}:{finding.location.start_line}",
            "location": _location_dict(finding.location),
        }
    ]
    if flow is not None:
        chain.append(
            {
                "type": "flow",
                "flow_id": flow.id,
                "name": flow.name,
                "language": flow.language,
                "entry_kind": flow.entry_kind,
                "source": f"{flow.location.path}:{flow.location.start_line}",
                "location": _location_dict(flow.location),
            }
        )
    if node is not None:
        chain.append(
            {
                "type": _enum_value(node.kind),
                "node_id": node.id,
                "label": node.label,
                "condition": node.metadata.get("condition"),
                "subject": node.metadata.get("subject"),
                "values": node.metadata.get("values", []),
                "branches": node.metadata.get("branches", []),
                "source": f"{node.location.path}:{node.location.start_line}",
                "location": _location_dict(node.location),
            }
        )
        chain.extend(_detector_evidence(finding, flow, node, metadata))
    if metadata.get("declared"):
        chain.append(
            {
                "type": "declared_values",
                "value_namespace": metadata.get("value_namespace"),
                "values": _as_list(metadata.get("declared")),
            }
        )
    if metadata.get("quorum"):
        chain.append({"type": "sibling_quorum", "quorum": metadata["quorum"]})
    if metadata.get("missing"):
        chain.append({"type": "missing_values", "values": _as_list(metadata.get("missing"))})
    if related_decisions:
        chain.append({"type": "related_decisions", "nodes": related_decisions})
    return chain


def _detector_evidence(
    finding: Finding,
    flow: Flow | None,
    node: FlowNode,
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    kind = _kind_value(finding.kind)
    if kind == FindingKind.MISSING_BRANCH.value:
        return [_implicit_fallback_evidence(flow, node)]
    if kind == FindingKind.DEAD_GUARD.value:
        return [_constant_guard_evidence(node, metadata)]
    if kind == FindingKind.BROAD_EXCEPT_SWALLOW.value:
        return [_handler_outcome_evidence(node)]
    if kind == FindingKind.NO_OP_BRANCH.value:
        return [_empty_branch_evidence(node)]
    if kind == FindingKind.ASYMMETRIC_RETURN.value:
        return [_dispatch_outcome_evidence(node)]
    return []


def _implicit_fallback_evidence(flow: Flow | None, node: FlowNode) -> dict[str, Any]:
    decisions = _same_subject_decision_chain(flow, node)
    branches = [
        {**branch, "decision_node_id": decision.id}
        for decision in decisions
        for branch in _branch_summaries(decision)
    ]
    implicit = [branch for branch in branches if branch["implicit"]]
    explicit = [branch for branch in branches if not branch["implicit"]]
    handled_values = _unique(
        [
            str(value)
            for decision in decisions
            for value in _as_list(decision.metadata.get("values")) or []
        ]
    )
    return {
        "type": "implicit_fallback",
        "condition": node.metadata.get("condition"),
        "subject": node.metadata.get("subject"),
        "domain": node.metadata.get("domain"),
        "value_namespace": node.metadata.get("value_namespace"),
        "operator": node.metadata.get("operator"),
        "handled_values": handled_values,
        "decision_node_ids": [decision.id for decision in decisions],
        "explicit_branches": explicit,
        "implicit_branches": implicit,
        "fallback_present": False,
    }


def _constant_guard_evidence(node: FlowNode, metadata: dict[str, Any]) -> dict[str, Any]:
    always = metadata.get("always")
    return {
        "type": "constant_guard",
        "constant": metadata.get("constant"),
        "condition": node.metadata.get("condition"),
        "guard_always": always,
        "unreachable_branch_label": "No" if always is True else "Yes" if always is False else None,
        "branches": _branch_summaries(node),
    }


def _handler_outcome_evidence(node: FlowNode) -> dict[str, Any]:
    handlers = [
        branch
        for branch in _branch_summaries(node)
        if not branch["implicit"] and branch["label"] != SUCCESS
    ]
    return {
        "type": "handler_outcomes",
        "condition": node.metadata.get("condition"),
        "handlers": handlers,
        "swallowing_outcomes": [EMPTY, FALLS_THROUGH],
    }


def _empty_branch_evidence(node: FlowNode) -> dict[str, Any]:
    empty = [branch for branch in _branch_summaries(node) if branch["outcome"] == EMPTY]
    return {
        "type": "empty_branches",
        "condition": node.metadata.get("condition"),
        "branches": empty,
    }


def _dispatch_outcome_evidence(node: FlowNode) -> dict[str, Any]:
    branches = _branch_summaries(node)
    exiting = [branch for branch in branches if branch["outcome"] in {RETURNS, RAISES}]
    fallthrough = [branch for branch in branches if branch["outcome"] == FALLS_THROUGH]
    return {
        "type": "dispatch_outcomes",
        "operator": node.metadata.get("operator"),
        "subject": node.metadata.get("subject"),
        "exiting_branches": exiting,
        "fallthrough_branches": fallthrough,
        "exit_majority": len(exiting) > len(fallthrough),
    }


def _branch_summaries(node: FlowNode) -> list[dict[str, Any]]:
    branches = node.metadata.get("branches", [])
    if not isinstance(branches, list):
        return []
    result = []
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        result.append(
            {
                "label": branch.get("label"),
                "outcome": branch.get("outcome"),
                "implicit": bool(branch.get("implicit")),
            }
        )
    return result


def _same_subject_decision_chain(flow: Flow | None, node: FlowNode) -> list[FlowNode]:
    if flow is None:
        return [node]
    decisions = {
        candidate.id: candidate
        for candidate in flow.nodes
        if candidate.kind is NodeKind.DECISION
        and candidate.metadata.get("subject") == node.metadata.get("subject")
    }
    if node.id not in decisions:
        return [node]
    no_edges = {
        edge.source: edge.target
        for edge in flow.edges
        if edge.label == NO and edge.source in decisions and edge.target in decisions
    }
    chain = [node]
    seen = {node.id}
    cursor = node.id
    while cursor in no_edges:
        cursor = no_edges[cursor]
        if cursor in seen:
            break
        seen.add(cursor)
        chain.append(decisions[cursor])
    return chain


def _related_decisions(
    finding: Finding,
    flow: Flow | None,
    node: FlowNode | None,
    metadata: dict[str, Any],
    model: Any | None,
) -> list[dict[str, Any]]:
    if model is None:
        return []
    if metadata.get("category") != "cross_flow":
        return []
    subject = metadata.get("subject") or (node.metadata.get("subject") if node else None)
    namespace = metadata.get("value_namespace") or (
        node.metadata.get("value_namespace") if node else None
    )
    condition = metadata.get("condition") or (node.metadata.get("condition") if node else None)
    missing_values = {str(item) for item in (_as_list(metadata.get("missing")) or [])}
    if not any((subject, namespace, condition, missing_values)):
        return []
    rows: list[dict[str, Any]] = []
    for candidate_flow in getattr(model, "flows", []):
        for candidate_node in getattr(candidate_flow, "nodes", []):
            if candidate_flow.id == finding.flow_id and candidate_node.id == finding.node_id:
                continue
            if candidate_node.kind is not NodeKind.DECISION:
                continue
            reasons = _related_decision_reasons(
                candidate_node,
                subject=subject,
                namespace=namespace,
                condition=condition,
                missing_values=missing_values,
            )
            if not reasons:
                continue
            rows.append(
                {
                    "flow_id": candidate_flow.id,
                    "flow_name": candidate_flow.name,
                    "node_id": candidate_node.id,
                    "label": candidate_node.label,
                    "reasons": reasons,
                    "source": (
                        f"{candidate_node.location.path}:{candidate_node.location.start_line}"
                    ),
                    "location": _location_dict(candidate_node.location),
                }
            )
    rows.sort(key=lambda item: (item["flow_name"], item["flow_id"], item["node_id"]))
    return rows[:DIAGNOSTIC_RELATED_LIMIT]


def _related_decision_reasons(
    node: FlowNode,
    *,
    subject: Any,
    namespace: Any,
    condition: Any,
    missing_values: set[str],
) -> list[str]:
    metadata = node.metadata
    reasons: list[str] = []
    if subject and metadata.get("subject") == subject:
        if namespace and metadata.get("value_namespace") == namespace:
            reasons.append("same_subject_namespace")
        elif not namespace:
            reasons.append("same_subject")
    if condition and metadata.get("condition") == condition:
        reasons.append("same_condition")
    if missing_values and missing_values & _handled_values(node):
        reasons.append("handles_missing_value")
    return _unique(reasons)


def _handled_values(node: FlowNode) -> set[str]:
    values = {str(item) for item in node.metadata.get("values", [])}
    for branch in node.metadata.get("branches", []):
        if isinstance(branch, dict) and branch.get("label") is not None:
            values.add(str(branch["label"]))
    return values


def _expected(metadata: dict[str, Any], node: FlowNode | None) -> Any:
    if "expected" in metadata:
        return metadata["expected"]
    missing = _as_list(metadata.get("missing"))
    declared = _as_list(metadata.get("declared"))
    if missing and declared:
        return {"handle_declared_values": declared}
    if missing and metadata.get("quorum"):
        return {"handle_quorum_values": missing, "quorum": metadata.get("quorum")}
    if metadata.get("always") is not None:
        return {"reachable_guard": True}
    if node is not None and node.metadata.get("branches"):
        return {"explicit_review_of_branches": True}
    return None


def _actual(metadata: dict[str, Any], node: FlowNode | None) -> Any:
    if "outcome" in metadata:
        return metadata["outcome"]
    if metadata.get("always") is not None:
        return {"guard_always": metadata["always"]}
    if node is None:
        return None
    return {
        "condition": node.metadata.get("condition"),
        "handled_values": node.metadata.get("values", []),
        "branches": node.metadata.get("branches", []),
    }


def _confidence(finding: Finding) -> dict[str, Any]:
    metadata = _metadata_without_diagnostic(finding.metadata)
    raw = metadata.get("confidence")
    if isinstance(raw, int | float):
        return {
            "score": max(0.0, min(1.0, round(float(raw), 2))),
            "basis": "detector_metadata",
        }
    evidence = finding.evidence
    if evidence is Evidence.VERIFIED:
        return {"score": 1.0, "basis": "syntax-backed evidence"}
    if evidence is Evidence.INFERRED:
        return {"score": 0.7, "basis": "deterministic heuristic"}
    if evidence is Evidence.POTENTIAL_GAP:
        return {"score": 0.4, "basis": "review candidate, not a confirmed bug"}
    return {"score": None, "basis": "unknown evidence tier"}


def _location_dict(location: Any) -> dict[str, Any]:
    return {
        "path": location.path,
        "start_line": location.start_line,
        "end_line": location.end_line,
    }


def _unique(values: list[Any]) -> list[Any]:
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _metadata_without_diagnostic(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key != "diagnostic"}


def _as_list(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    if isinstance(value, tuple | set):
        return list(value)
    return [value]


def _kind_value(kind: str | FindingKind) -> str:
    return kind.value if isinstance(kind, FindingKind) else str(kind)


def _enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value
