from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from logicchart.analysis.common import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    CONFIDENCE_NONE,
    DEFAULT_EXPORT_MARKER,
)
from logicchart.analysis.discovery import discover_source_files, language_for
from logicchart.analysis.python import PythonAnalyzer
from logicchart.analysis.typescript import TypeScriptAnalyzer
from logicchart.config import LogicChartConfig
from logicchart.model import (
    Evidence,
    FileAnalysis,
    FileRecord,
    Finding,
    Flow,
    FlowNode,
    NodeKind,
    ProjectModel,
    Severity,
)
from logicchart.util import file_sha256, read_json, relpath, stable_id, write_json

CACHE_VERSION = "2"


@dataclass(slots=True)
class AnalysisResult:
    model: ProjectModel
    changed_files: list[str]
    deleted_files: list[str]
    cache_hits: int


class ProjectAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig | None = None) -> None:
        self.root = root.resolve()
        self.config = config or LogicChartConfig.load(self.root)
        self.cache_dir = self.root / ".logicchart" / "cache"
        self.index_path = self.cache_dir / "index.json"
        self.previous_generated_at: str | None = None
        self.python = PythonAnalyzer(self.root, self.config)
        self.typescript = TypeScriptAnalyzer(self.root, self.config)

    def analyze(self, *, full: bool = False) -> AnalysisResult:
        files = discover_source_files(self.root, self.config)
        previous_index = {} if full else self._load_index()
        current_paths = {relpath(path, self.root) for path in files}
        deleted_files = sorted(set(previous_index) - current_paths)
        analyses: list[FileAnalysis] = []
        changed_files: list[str] = []
        cache_hits = 0
        new_index: dict[str, dict[str, str]] = {}

        for path in files:
            relative = relpath(path, self.root)
            digest = file_sha256(path)
            cache_file = self.cache_dir / f"{stable_id(relative, length=24)}.json"
            cached = previous_index.get(relative)
            if not full and cached and cached.get("sha256") == digest and cache_file.exists():
                analysis = FileAnalysis.from_dict(read_json(cache_file))
                cache_hits += 1
            else:
                analysis = self._analyze_file(path)
                write_json(cache_file, analysis.to_dict())
                changed_files.append(relative)
            analyses.append(analysis)
            new_index[relative] = {"sha256": digest, "cache": cache_file.name}

        model = self._combine(analyses)
        if not full and not changed_files and not deleted_files and self.previous_generated_at:
            model.generated_at = self.previous_generated_at
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        write_json(
            self.index_path,
            {
                "cache_version": CACHE_VERSION,
                "generated_at": model.generated_at,
                "files": new_index,
            },
        )
        return AnalysisResult(
            model=model,
            changed_files=changed_files,
            deleted_files=deleted_files,
            cache_hits=cache_hits,
        )

    def _analyze_file(self, path: Path) -> FileAnalysis:
        language = language_for(path)
        if language == "python":
            return self.python.analyze(path)
        return self.typescript.analyze(path)

    def _load_index(self) -> dict[str, dict[str, str]]:
        if not self.index_path.exists():
            return {}
        data = read_json(self.index_path)
        if data.get("cache_version") != CACHE_VERSION:
            return {}
        generated_at = data.get("generated_at")
        self.previous_generated_at = str(generated_at) if generated_at else None
        file_data = data.get("files", {})
        return {
            str(path): {"sha256": str(item["sha256"]), "cache": str(item["cache"])}
            for path, item in file_data.items()
        }

    def _combine(self, analyses: list[FileAnalysis]) -> ProjectModel:
        flows = [flow for analysis in analyses for flow in analysis.flows]
        findings = [finding for analysis in analyses for finding in analysis.findings]
        self._link_calls(flows)
        self._link_tests(flows)
        # Keyed by language so a Python enum and a same-named TS union stay distinct
        # value universes (they are different closed sets).
        enums: dict[str, dict[str, list[str]]] = {}
        for analysis in analyses:
            language_enums = enums.setdefault(analysis.language, {})
            for name, members in analysis.enums.items():
                known = language_enums.setdefault(name, [])
                known.extend(member for member in members if member not in known)
        constants_by_path = {analysis.path: analysis.constants for analysis in analyses}
        findings.extend(self._find_inconsistent_decisions(flows, enums))
        findings.extend(self._enum_exhaustiveness(flows, enums))
        findings.extend(self._outcome_inconsistency(flows))
        findings.extend(self._logging_asymmetry(flows))
        findings.extend(self._dead_guard(flows, constants_by_path))
        if self.config.gated_detectors:
            findings.extend(self._auth_divergence(flows))
        findings = _suppress_redundant_missing_branch(findings)
        findings = _deduplicate_findings(findings)
        files = [
            FileRecord(
                path=analysis.path,
                language=analysis.language,
                sha256=analysis.sha256,
                flow_ids=[flow.id for flow in analysis.flows],
            )
            for analysis in analyses
        ]
        return ProjectModel(
            schema_version="1.1",
            generated_at=datetime.now(timezone.utc).isoformat(),
            root=".",
            flows=sorted(flows, key=lambda item: (not item.is_entrypoint, item.symbol)),
            findings=sorted(findings, key=lambda item: (item.severity.value, item.message)),
            files=files,
            metadata={
                "languages": sorted({item.language for item in analyses}),
                "entrypoint_count": sum(flow.is_entrypoint for flow in flows),
                "flow_count": len(flows),
                "finding_count": len(findings),
                "enums": enums,
            },
        )

    def _link_calls(self, flows: list[Flow]) -> None:
        # Import-aware first (`qualified_calls` from the analyzers), short name as a
        # fallback. Ambiguous candidates are recorded, not dropped, and every link
        # carries a `link_confidence` so interprocedural detectors can weigh it.
        # Key on the flow symbol as-is (``module:qualified``) so a module-path
        # boundary can never collide with an attribute boundary. A default-export
        # flow also answers to the module's default marker.
        by_qualified: dict[str, list[Flow]] = {}
        by_name: dict[str, list[Flow]] = {}
        for flow in flows:
            by_qualified.setdefault(flow.symbol, []).append(flow)
            if flow.metadata.get("default_export"):
                module = flow.symbol.split(":", 1)[0]
                by_qualified.setdefault(f"{module}:{DEFAULT_EXPORT_MARKER}", []).append(flow)
            short = flow.symbol.split(":", 1)[-1].split(".")[-1]
            by_name.setdefault(short, []).append(flow)

        for flow in flows:
            for node in flow.nodes:
                if node.kind is not NodeKind.CALL:
                    continue
                candidates, confidence = self._resolve_call(flow, node, by_qualified, by_name)
                if not candidates:
                    continue
                node.metadata["link_confidence"] = confidence
                node.metadata["call_candidates"] = sorted(candidates)
                if len(candidates) == 1:
                    target = next(iter(candidates.values()))
                    node.metadata["target_flow"] = target.id
                    node.metadata["target_symbol"] = target.symbol
                    if target.id not in flow.calls:
                        flow.calls.append(target.id)
                    if flow.id not in target.called_by:
                        target.called_by.append(flow.id)

    @staticmethod
    def _resolve_call(
        flow: Flow,
        node: FlowNode,
        by_qualified: dict[str, list[Flow]],
        by_name: dict[str, list[Flow]],
    ) -> tuple[dict[str, Flow], str]:
        qualified: dict[str, Flow] = {}
        for name in node.metadata.get("qualified_calls", []):
            for candidate in by_qualified.get(str(name), []):
                if candidate.id != flow.id:
                    qualified[candidate.id] = candidate
        if qualified:
            return qualified, (CONFIDENCE_HIGH if len(qualified) == 1 else CONFIDENCE_LOW)

        short_name: dict[str, Flow] = {}
        for raw in node.metadata.get("calls", []):
            for candidate in by_name.get(str(raw).split(".")[-1], []):
                if candidate.id != flow.id:
                    short_name[candidate.id] = candidate
        if short_name:
            return short_name, (CONFIDENCE_MEDIUM if len(short_name) == 1 else CONFIDENCE_LOW)
        return {}, CONFIDENCE_NONE

    def _link_tests(self, flows: list[Flow]) -> None:
        by_id = {flow.id: flow for flow in flows}
        for flow in flows:
            if not flow.metadata.get("test"):
                continue
            for target_id in flow.calls:
                target = by_id.get(target_id)
                if target and flow.symbol not in target.tests:
                    target.tests.append(flow.symbol)

    def _find_inconsistent_decisions(
        self, flows: list[Flow], enums: dict[str, dict[str, list[str]]]
    ) -> list[Finding]:
        # Quorum-aware cross-flow value coverage. Comparison is per flow (not per
        # decision node) and bucketed by (language, subject, value_namespace) so
        # only flows branching on the *same* subject and enum/union are compared —
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
                        _inconsistent_finding(
                            coverage, subject, namespace, missing, quorum, siblings
                        )
                    )
        return findings

    def _enum_exhaustiveness(
        self, flows: list[Flow], enums: dict[str, dict[str, list[str]]]
    ) -> list[Finding]:
        # A flow that dispatches on a declared enum — handling at least two of its
        # members — but omits other declared members with no explicit default is
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

    def _outcome_inconsistency(self, flows: list[Flow]) -> list[Finding]:
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
                if signature != common:
                    findings.append(_outcome_finding(flow, node, subject, value, signature, common))
        return findings

    def _logging_asymmetry(self, flows: list[Flow]) -> list[Finding]:
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

    def _auth_divergence(self, flows: list[Flow]) -> list[Finding]:
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
                _auth_finding(flow)
                for flow in group
                if not flow.metadata.get("performs_auth_check")
            )
        return findings

    def _dead_guard(
        self, flows: list[Flow], constants_by_path: dict[str, dict[str, bool]]
    ) -> list[Finding]:
        # A truthiness guard on a module-level boolean constant: the branch is always
        # taken or never taken. INFERRED — the constant could be reassigned elsewhere.
        findings: list[Finding] = []
        for flow in flows:
            if flow.metadata.get("test"):
                continue
            constants = constants_by_path.get(flow.location.path, {})
            if not constants:
                continue
            for node in flow.nodes:
                if node.kind is not NodeKind.DECISION or node.metadata.get("operator"):
                    continue
                subject = str(node.metadata.get("subject", ""))
                if subject not in constants:
                    continue
                value = constants[subject]
                always = (not value) if node.metadata.get("negation") else value
                findings.append(_dead_guard_finding(flow, node, subject, always))
        return findings


# Cross-flow quorum needs a real majority context: with fewer siblings, a single
# differing flow could not form a meaningful majority.
_MIN_QUORUM_SIBLINGS = 3
_FALLBACK_LABELS = {"No", "default", "_"}
# A negative comparison (status not in {...}) is a guard that allows the rest, not
# a positive value-dispatch, so it must not be read as "handling" those members.
_NEGATIVE_OPERATORS = {"!=", "not in", "is not"}


def _is_positive_dispatch(node: FlowNode) -> bool:
    return not node.metadata.get("negation") and (
        node.metadata.get("operator") not in _NEGATIVE_OPERATORS
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
    the code is unambiguous — never a bare integer argument.
    """
    nodes = {item.id: item for item in flow.nodes}
    out = _edges_by_source(flow)
    cursor = next((target for label, target in out.get(node.id, []) if label == "Yes"), None)
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
            return ""  # a nested branch — no single outcome to summarize
        successors = out.get(cursor, [])
        cursor = successors[0][1] if len(successors) == 1 else None
    return ""


def _raise_signature(label: str) -> str:
    match = re.search(r"\bRaise\s+([A-Za-z_][\w.]*)", label)
    exception = (match.group(1) if match else "error").rsplit(".", 1)[-1]
    keyword = re.search(r"(?:status_code|status|code)\s*=\s*(\d{3})", label)
    code = keyword.group(1) if keyword else None
    if code is None and exception.lower() in _HTTP_ERROR_CLASSES:
        positional = re.search(r"\(\s*(\d{3})\b", label)
        code = positional.group(1) if positional else None
    return f"raise:{exception}" + (f":{code}" if code else "")


def _branch_logs(flow: Flow, node: FlowNode) -> bool:
    """Whether the positive ("Yes") branch reaches a logging call before it ends."""
    nodes = {item.id: item for item in flow.nodes}
    out = _edges_by_source(flow)
    start = next((target for label, target in out.get(node.id, []) if label == "Yes"), None)
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
    as a default only when its edge target is NOT another same-subject decision —
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
        if edge.source not in sources or edge.label not in _FALLBACK_LABELS:
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
        kind="inconsistent_case_handling",
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
        kind="enum_exhaustiveness",
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
        kind="outcome_inconsistency",
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
        kind="logging_asymmetry",
        severity=Severity.INFO,
        message=f"Guard '{condition}' is logged in a sibling flow but silent here",
        evidence=Evidence.INFERRED,
        flow_id=flow.id,
        node_id=node.id,
        location=node.location,
        detail=(
            "A sibling flow logs or alerts on the same guard while this one proceeds "
            "silently — an observability gap on a shared condition."
        ),
        metadata={"category": "cross_flow", "condition": condition},
    )


def _auth_finding(flow: Flow) -> Finding:
    entry = flow.nodes[0] if flow.nodes else None
    return Finding(
        id=stable_id(flow.id, "auth-divergence"),
        kind="auth_divergence",
        severity=Severity.WARNING,
        message=f"{flow.name} skips the authorization check its sibling entry points perform",
        evidence=Evidence.POTENTIAL_GAP,
        flow_id=flow.id,
        node_id=entry.id if entry else None,
        location=flow.location,
        detail=(
            "Gated heuristic: sibling entry points in this file perform an authorization "
            "check while this one does not. Middleware or DI may authorize it invisibly — review."
        ),
        metadata={"category": "cross_flow", "rule": "auth_divergence"},
    )


def _suppress_redundant_missing_branch(findings: list[Finding]) -> list[Finding]:
    """Drop missing_branch where enum_exhaustiveness already names the missing members.

    Both fire on a state-like dispatch with no fallback; the declared-set finding is
    strictly more actionable, so keep it and suppress the generic one on that node.
    """
    enum_nodes = {
        (item.flow_id, item.node_id) for item in findings if item.kind == "enum_exhaustiveness"
    }
    return [
        item
        for item in findings
        if not (item.kind == "missing_branch" and (item.flow_id, item.node_id) in enum_nodes)
    ]


def _dead_guard_finding(flow: Flow, node: FlowNode, subject: str, always: bool) -> Finding:
    return Finding(
        id=stable_id(flow.id, node.id, "dead-guard"),
        kind="dead_guard",
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


def _deduplicate_findings(findings: list[Finding]) -> list[Finding]:
    return list({item.id: item for item in findings}.values())
