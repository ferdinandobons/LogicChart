"""Cross-flow and project-level detectors.

These compare sibling flows (inconsistent case handling, enum exhaustiveness,
outcome inconsistency, logging asymmetry, gated auth divergence) or need the
project-level constant table (dead_guard). They reference no analyzer instance
state, so they live here as free functions; `cross_flow_findings` is the single
entry point `ProjectAnalyzer._combine` calls, mirroring `single_flow_findings`.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from logicchart.analysis.common import (
    FALLBACK_LABELS,
    NEGATIVE_OPERATORS,
    YES,
)
from logicchart.model import (
    Evidence,
    Finding,
    FindingKind,
    Flow,
    FlowNode,
    NodeKind,
    Severity,
)
from logicchart.util import stable_id


def cross_flow_findings(
    flows: list[Flow],
    enums: dict[str, dict[str, list[str]]],
    constants_by_path: dict[str, dict[str, bool]],
    *,
    gated: bool,
) -> list[Finding]:
    """All cross-flow / project-level findings (the six detectors)."""
    findings: list[Finding] = []
    findings.extend(_find_inconsistent_decisions(flows, enums))
    findings.extend(_enum_exhaustiveness(flows, enums))
    findings.extend(_outcome_inconsistency(flows))
    findings.extend(_logging_asymmetry(flows))
    findings.extend(_dead_guard(flows, constants_by_path))
    if gated:
        findings.extend(_auth_divergence(flows))
    return findings


def _find_inconsistent_decisions(
    flows: list[Flow], enums: dict[str, dict[str, list[str]]]
) -> list[Finding]:
    # Quorum-aware cross-flow value coverage. Comparison is per flow (not per
    # decision node) and bucketed by (language, subject, value_namespace) so
    # only flows branching on the *same* subject and enum/union are compared -
    # keeping the same enum reused on different subjects apart, and scoping the
    # explicit-default suppression to the relevant subject. A flow is flagged
    # for a value a strict majority of its siblings handle but it omits.
    # Namespaces with a declared enum are left to _enum_exhaustiveness (a
    # stronger declared-set check), so the two never double-flag the same gap.
    buckets: dict[tuple[str, str, str], dict[str, _Coverage]] = {}
    for flow in flows:
        if flow.metadata.get("test"):
            continue
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            subject = str(node.metadata.get("subject", ""))
            namespace = str(node.metadata.get("value_namespace", ""))
            values = {str(item) for item in node.metadata.get("values", []) if str(item)}
            if not subject or not namespace or not values or not _is_positive_dispatch(node):
                continue
            if enums.get(flow.language, {}).get(namespace):
                continue
            coverages = buckets.setdefault((flow.language, subject, namespace), {})
            existing = coverages.get(flow.id)
            if existing is None:
                coverages[flow.id] = _Coverage(flow, node, set(values))
            else:
                existing.handled |= values

    findings: list[Finding] = []
    for (_language, subject, namespace), coverages in buckets.items():
        siblings = len(coverages)
        if siblings < _MIN_QUORUM_SIBLINGS:
            continue
        counts: Counter[str] = Counter()
        for coverage in coverages.values():
            counts.update(coverage.handled)
        quorum = siblings // 2 + 1  # strict majority, so a single outlier can't set quorum
        expected = {value for value, count in counts.items() if count >= quorum}
        for coverage in coverages.values():
            if _has_subject_default(coverage.flow, subject, namespace):
                continue
            missing = sorted(expected - coverage.handled)
            if missing:
                findings.append(
                    _inconsistent_finding(coverage, subject, namespace, missing, quorum, siblings)
                )
    return findings


def _enum_exhaustiveness(
    flows: list[Flow], enums: dict[str, dict[str, list[str]]]
) -> list[Finding]:
    # A flow that dispatches on a declared enum - handling at least two of its
    # members - but omits other declared members with no explicit default is
    # likely non-exhaustive. This uses the declared closed set, so unlike the
    # quorum check it needs no sibling flows.
    findings: list[Finding] = []
    for flow in flows:
        if flow.metadata.get("test"):
            continue
        coverage: dict[tuple[str, str], _Coverage] = {}
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            subject = str(node.metadata.get("subject", ""))
            namespace = str(node.metadata.get("value_namespace", ""))
            values = {str(item) for item in node.metadata.get("values", []) if str(item)}
            if not subject or not values or not _is_positive_dispatch(node):
                continue
            if not enums.get(flow.language, {}).get(namespace):
                continue
            existing = coverage.get((subject, namespace))
            if existing is None:
                coverage[(subject, namespace)] = _Coverage(flow, node, set(values))
            else:
                existing.handled |= values

        for (subject, namespace), cov in coverage.items():
            declared = enums[flow.language][namespace]
            declared_set = set(declared)
            if len(cov.handled & declared_set) < 2:
                continue
            if _has_subject_default(flow, subject, namespace):
                continue
            missing = sorted(declared_set - cov.handled)
            if missing:
                findings.append(_enum_finding(cov, subject, namespace, missing, declared))
    return findings


def _outcome_inconsistency(flows: list[Flow]) -> list[Finding]:
    # The same positive `subject == value` condition handled with materially
    # different outcomes across flows (e.g. raise 403 here, raise 404 there). A
    # strict majority sets the expected outcome, so a lone difference is flagged
    # against agreement, not guessed.
    by_condition: dict[tuple[str, str, str], list[tuple[Flow, FlowNode, str]]] = {}
    for flow in flows:
        if flow.metadata.get("test"):
            continue
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION or not _is_positive_dispatch(node):
                continue
            subject = str(node.metadata.get("subject", ""))
            values = [str(item) for item in node.metadata.get("values", []) if str(item)]
            signature = _outcome_signature(flow, node)
            if subject and len(values) == 1 and signature:
                key = (flow.language, subject, values[0])
                by_condition.setdefault(key, []).append((flow, node, signature))

    findings: list[Finding] = []
    for (_language, subject, value), entries in by_condition.items():
        if len(entries) < _MIN_QUORUM_SIBLINGS:
            continue
        ((common, count),) = Counter(sig for _, _, sig in entries).most_common(1)
        if count * 2 <= len(entries):
            continue  # no strict-majority expected outcome
        for flow, node, signature in entries:
            if not _outcomes_compatible(signature, common):
                findings.append(_outcome_finding(flow, node, subject, value, signature, common))
    return findings


def _logging_asymmetry(flows: list[Flow]) -> list[Finding]:
    # Scoped to error paths: flows sharing the exact same guard where a sibling
    # logs/alerts AND rejects (raises) while this one handles it silently. The
    # raise requirement keeps ubiquitous trivial guards from conflating unrelated
    # flows, matching the spec's "observability asymmetry on error paths".
    by_condition: dict[tuple[str, str], list[tuple[Flow, FlowNode, bool, bool]]] = {}
    for flow in flows:
        if flow.metadata.get("test"):
            continue
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION:
                continue
            condition = str(node.metadata.get("condition", ""))
            if not condition or node.metadata.get("domain") == "error":
                continue
            logs = _branch_logs(flow, node)
            raises = _outcome_signature(flow, node).startswith("raise")
            by_condition.setdefault((flow.language, condition), []).append(
                (flow, node, logs, raises)
            )

    findings: list[Finding] = []
    for (_language, condition), entries in by_condition.items():
        if len(entries) < 2:
            continue
        has_error_logger = any(logs and raises for *_, logs, raises in entries)
        has_silent = any(not logs for *_, logs, _ in entries)
        if has_error_logger and has_silent:
            for flow, node, logs, _ in entries:
                if not logs:
                    findings.append(_logging_finding(flow, node, condition))
    return findings


def _auth_divergence(flows: list[Flow]) -> list[Finding]:
    # GATED (opt-in via gated_detectors). Entry points in the same file where
    # some perform an authorization check and a sibling does not. Middleware or
    # DI can authorize invisibly, so this is a review candidate, not a bug.
    by_file: dict[str, list[Flow]] = {}
    for flow in flows:
        if flow.is_entrypoint and not flow.metadata.get("test"):
            by_file.setdefault(flow.location.path, []).append(flow)
    findings: list[Finding] = []
    for group in by_file.values():
        if len(group) < 2 or not any(f.metadata.get("performs_auth_check") for f in group):
            continue
        findings.extend(
            _auth_finding(flow) for flow in group if not flow.metadata.get("performs_auth_check")
        )
    return findings


def _dead_guard(flows: list[Flow], constants_by_path: dict[str, dict[str, bool]]) -> list[Finding]:
    # A truthiness guard on a module-level boolean constant: the branch is always
    # taken or never taken. INFERRED - the constant could be reassigned elsewhere.
    findings: list[Finding] = []
    for flow in flows:
        if flow.metadata.get("test"):
            continue
        constants = constants_by_path.get(flow.location.path, {})
        if not constants:
            continue
        shadowed = set(flow.metadata.get("shadows_constants", []))
        for node in flow.nodes:
            if node.kind is not NodeKind.DECISION or node.metadata.get("operator"):
                continue
            subject = str(node.metadata.get("subject", ""))
            if subject not in constants or subject in shadowed:
                continue
            value = constants[subject]
            always = (not value) if node.metadata.get("negation") else value
            findings.append(_dead_guard_finding(flow, node, subject, always))
    return findings


# Cross-flow quorum needs a real majority context: with fewer siblings, a single
# differing flow could not form a meaningful majority.
_MIN_QUORUM_SIBLINGS = 3


def _is_positive_dispatch(node: FlowNode) -> bool:
    return not node.metadata.get("negation") and (
        node.metadata.get("operator") not in NEGATIVE_OPERATORS
    )


def _edges_by_source(flow: Flow) -> dict[str, list[tuple[str, str]]]:
    out: dict[str, list[tuple[str, str]]] = {}
    for edge in flow.edges:
        out.setdefault(edge.source, []).append((edge.label, edge.target))
    return out


# Exception classes whose first positional argument is conventionally an HTTP status.
_HTTP_ERROR_CLASSES = {"httpexception", "apierror", "httperror", "responseerror", "apiexception"}


def _outcome_signature(flow: Flow, node: FlowNode) -> str:
    """How the positive ("Yes") branch of a decision terminates.

    Walks through intervening calls/actions (e.g. a log before the raise) to the
    first error or terminal node, so an effect-before-raise reads as the raise it
    leads to. A raise is keyed on its exception type plus a status code only when
    the code is unambiguous - never a bare integer argument.
    """
    nodes = {item.id: item for item in flow.nodes}
    out = _edges_by_source(flow)
    cursor = next((target for label, target in out.get(node.id, []) if label == YES), None)
    seen: set[str] = set()
    while cursor is not None and cursor not in seen:
        seen.add(cursor)
        current = nodes.get(cursor)
        if current is None:
            return ""
        if current.kind is NodeKind.ERROR:
            return _raise_signature(current.label)
        if current.kind is NodeKind.TERMINAL:
            return "return"
        if current.kind is NodeKind.DECISION:
            return ""  # a nested branch - no single outcome to summarize
        successors = out.get(cursor, [])
        cursor = successors[0][1] if len(successors) == 1 else None
    return ""


def _raise_signature(label: str) -> str:
    match = re.search(r"\bRaise\s+([A-Za-z_][\w.]*)", label)
    exception = (match.group(1) if match else "error").rsplit(".", 1)[-1]
    keyword = re.search(r"(?:status_code|status|code)\s*=\s*(\d{3})", label)
    code = keyword.group(1) if keyword else None
    if code is None:
        # Symbolic status constants (status.HTTP_403_FORBIDDEN) are the canonical
        # FastAPI/Starlette spelling - normalize to the numeric code so they compare
        # equal to the literal form and a symbolic 403-vs-404 still diverges.
        symbolic = re.search(r"\bHTTP_(\d{3})", label)
        code = symbolic.group(1) if symbolic else None
    if code is None and exception.lower() in _HTTP_ERROR_CLASSES:
        positional = re.search(r"\(\s*(\d{3})\b", label)
        code = positional.group(1) if positional else None
    return f"raise:{exception}" + (f":{code}" if code else "")


def _outcomes_compatible(actual: str, expected: str) -> bool:
    """Whether two outcome signatures describe the same outcome.

    A coded raise (``raise:HTTPException:403``) is compatible with the same
    exception carrying no code (``raise:HTTPException``): that is a literal-vs-
    symbolic status spelling, not a real divergence. Two differing codes on the
    same exception, or a different exception/terminal, remain a divergence.
    """
    if actual == expected:
        return True
    actual_exc, actual_code = _raise_exception_and_code(actual)
    expected_exc, expected_code = _raise_exception_and_code(expected)
    if actual_exc != expected_exc:
        return False
    return actual_code is None or expected_code is None or actual_code == expected_code


def _raise_exception_and_code(signature: str) -> tuple[str, str | None]:
    if not signature.startswith("raise:"):
        return signature, None
    exception, _, code = signature[len("raise:") :].partition(":")
    return f"raise:{exception}", (code or None)


def _branch_logs(flow: Flow, node: FlowNode) -> bool:
    """Whether the positive ("Yes") branch reaches a logging call before it ends."""
    nodes = {item.id: item for item in flow.nodes}
    out = _edges_by_source(flow)
    start = next((target for label, target in out.get(node.id, []) if label == YES), None)
    if start is None:
        return False
    seen: set[str] = set()
    stack = [start]
    while stack:
        current_id = stack.pop()
        if current_id in seen:
            continue
        seen.add(current_id)
        current = nodes.get(current_id)
        if current is None:
            continue
        if "log" in current.metadata.get("effects", []):
            return True
        if current.kind in (NodeKind.TERMINAL, NodeKind.ERROR):
            continue
        if current.kind is NodeKind.DECISION and current_id != start:
            continue  # do not cross into an unrelated nested decision
        stack.extend(target for _, target in out.get(current_id, []))
    return False


@dataclass(slots=True)
class _Coverage:
    """One flow's coverage of a (subject, value namespace), for cross-flow comparison."""

    flow: Flow
    node: FlowNode
    handled: set[str]


def _has_subject_default(flow: Flow, subject: str, namespace: str) -> bool:
    """Whether the flow has a real else/default on decisions for (subject, namespace).

    An elif continuation also emits a non-implicit "No" branch, so a branch counts
    as a default only when its edge target is NOT another same-subject decision -
    i.e. a genuine else/default body, not the next link in an if/elif chain.
    """
    nodes = {node.id: node for node in flow.nodes}

    def on_subject(node_id: str) -> bool:
        node = nodes.get(node_id)
        return (
            node is not None
            and node.kind is NodeKind.DECISION
            and node.metadata.get("subject") == subject
            and node.metadata.get("value_namespace") == namespace
        )

    sources = {node.id for node in flow.nodes if on_subject(node.id)}
    for edge in flow.edges:
        if edge.source not in sources or edge.label not in FALLBACK_LABELS:
            continue
        branch = next(
            (
                entry
                for entry in nodes[edge.source].metadata.get("branches", [])
                if entry.get("label") == edge.label
            ),
            None,
        )
        if branch is not None and not branch.get("implicit") and not on_subject(edge.target):
            return True
    return False


def _inconsistent_finding(
    coverage: _Coverage,
    subject: str,
    namespace: str,
    missing: list[str],
    quorum: int,
    siblings: int,
) -> Finding:
    return Finding(
        id=stable_id(coverage.flow.id, coverage.node.id, "inconsistent-case"),
        kind=FindingKind.INCONSISTENT_CASE_HANDLING,
        severity=Severity.WARNING,
        message=(f"Most sibling flows handle {subject} values omitted here: {', '.join(missing)}"),
        evidence=Evidence.POTENTIAL_GAP,
        flow_id=coverage.flow.id,
        node_id=coverage.node.id,
        location=coverage.node.location,
        detail=(
            "Heuristic cross-flow comparison: a value handled by a majority of sibling "
            "flows branching on this subject is absent here, with no explicit default."
        ),
        metadata={
            "category": "cross_flow",
            "subject": subject,
            "value_namespace": namespace,
            "missing": missing,
            "confidence": round(quorum / siblings, 2),
            "quorum": {"required": quorum, "siblings": siblings},
        },
    )


def _enum_finding(
    coverage: _Coverage, subject: str, namespace: str, missing: list[str], declared: list[str]
) -> Finding:
    return Finding(
        id=stable_id(coverage.flow.id, coverage.node.id, "enum-exhaustiveness"),
        kind=FindingKind.ENUM_EXHAUSTIVENESS,
        severity=Severity.WARNING,
        message=f"Declared {namespace} members not handled for {subject}: {', '.join(missing)}",
        evidence=Evidence.INFERRED,
        flow_id=coverage.flow.id,
        node_id=coverage.node.id,
        location=coverage.node.location,
        detail=(
            "The flow dispatches on this enum (handling several members) but omits "
            "declared members of it, with no explicit default."
        ),
        metadata={
            "category": "cross_flow",
            "subject": subject,
            "value_namespace": namespace,
            "missing": missing,
            "declared": list(declared),
        },
    )


def _outcome_finding(
    flow: Flow, node: FlowNode, subject: str, value: str, signature: str, expected: str
) -> Finding:
    return Finding(
        id=stable_id(flow.id, node.id, "outcome-inconsistency"),
        kind=FindingKind.OUTCOME_INCONSISTENCY,
        severity=Severity.WARNING,
        message=f"{subject} == {value} resolves to {signature} here, but {expected} elsewhere",
        evidence=Evidence.INFERRED,
        flow_id=flow.id,
        node_id=node.id,
        location=node.location,
        detail=(
            "Most sibling flows resolve this exact condition with a different outcome; "
            "review whether the divergence is intentional."
        ),
        metadata={
            "category": "cross_flow",
            "subject": subject,
            "value": value,
            "outcome": signature,
            "expected": expected,
        },
    )


def _logging_finding(flow: Flow, node: FlowNode, condition: str) -> Finding:
    return Finding(
        id=stable_id(flow.id, node.id, "logging-asymmetry"),
        kind=FindingKind.LOGGING_ASYMMETRY,
        severity=Severity.INFO,
        message=f"Guard '{condition}' is logged in a sibling flow but silent here",
        evidence=Evidence.INFERRED,
        flow_id=flow.id,
        node_id=node.id,
        location=node.location,
        detail=(
            "A sibling flow logs or alerts on the same guard while this one proceeds "
            "silently - an observability gap on a shared condition."
        ),
        metadata={"category": "cross_flow", "condition": condition},
    )


def _auth_finding(flow: Flow) -> Finding:
    entry = flow.nodes[0] if flow.nodes else None
    return Finding(
        id=stable_id(flow.id, "auth-divergence"),
        kind=FindingKind.AUTH_DIVERGENCE,
        severity=Severity.WARNING,
        message=f"{flow.name} skips the authorization check its sibling entry points perform",
        evidence=Evidence.POTENTIAL_GAP,
        flow_id=flow.id,
        node_id=entry.id if entry else None,
        location=flow.location,
        detail=(
            "Gated heuristic: sibling entry points in this file perform an authorization "
            "check while this one does not. Middleware or DI may authorize it invisibly - review."
        ),
        metadata={"category": "cross_flow", "rule": "auth_divergence"},
    )


def _dead_guard_finding(flow: Flow, node: FlowNode, subject: str, always: bool) -> Finding:
    return Finding(
        id=stable_id(flow.id, node.id, "dead-guard"),
        kind=FindingKind.DEAD_GUARD,
        severity=Severity.WARNING,
        message=f"Guard on the constant {subject} is always {always}",
        evidence=Evidence.INFERRED,
        flow_id=flow.id,
        node_id=node.id,
        location=node.location,
        detail=(
            "The condition is a module-level boolean constant, so one branch is dead. "
            "Confirm the constant is not reassigned elsewhere."
        ),
        metadata={"category": "single_flow", "constant": subject, "always": always},
    )
