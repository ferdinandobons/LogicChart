from __future__ import annotations

import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logicchart.model import Flow, FlowNode, NodeKind, ProjectModel
from logicchart.util import metadata_scope_names

# Per-bucket relevance weights. Named constants instead of inline magic numbers so the
# ranking model is auditable and the tests can assert exact scores.
IDENTITY_WEIGHT = 6
NODE_WEIGHT = 3
STRUCTURE_WEIGHT = 5
METADATA_WEIGHT = 2
# Tie-breaker only: nudges an entrypoint above an otherwise-equal non-entrypoint. Added
# only when the term-overlap score is already > 0, so it never manufactures a match.
ENTRYPOINT_BONUS = 1
NAVIGATION_TOKENS_PER_ITEM = 60


@dataclass(slots=True)
class QueryMatch:
    flow: Flow
    score: int
    reasons: list[str]

    def to_dict(self, include_source: bool = True) -> dict[str, Any]:
        """The single serialization used by MCP query/context tools."""
        payload: dict[str, Any] = {
            "flow_id": self.flow.id,
            "name": self.flow.name,
            "language": self.flow.language,
            "entry_kind": self.flow.entry_kind,
            "framework": self.flow.framework,
            "scope": metadata_scope_names(self.flow.metadata),
            "score": self.score,
            "reasons": self.reasons,
            "subgraph_flow_ids": [self.flow.id],
            "next_tools": {
                "agent_context": {
                    "tool": "agent_context",
                    "arguments": {"flow_id": self.flow.id},
                },
                "snapshot_slice": {
                    "tool": "snapshot_slice",
                    "arguments": {
                        "flow_ids": [self.flow.id],
                        "format": "svg",
                        "include_svg": False,
                    },
                },
                "expand_slice": {
                    "tool": "expand_slice",
                    "arguments": {"flow_ids": [self.flow.id], "direction": "neighbors"},
                },
            },
        }
        if include_source:
            payload["source"] = f"{self.flow.location.path}:{self.flow.location.start_line}"
        return payload


@dataclass(slots=True)
class ImpactResult:
    changed_files: list[str]
    directly_impacted: list[Flow]
    transitively_impacted: list[Flow]
    impact_reasons: dict[str, list[str]] = field(default_factory=dict)
    target_flow_ids: list[str] = field(default_factory=list)
    target_symbols: list[str] = field(default_factory=list)
    target_dependency_paths: list[str] = field(default_factory=list)
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


def query_model(
    model: ProjectModel,
    question: str,
    limit: int = 10,
    scope: str | None = None,
    language: str | None = None,
    source_path: str | None = None,
    symbol: str | None = None,
    domain: str | None = None,
    value: str | None = None,
) -> list[QueryMatch]:
    terms = _terms(question)
    has_structured_filter = any(
        item is not None
        for item in (
            scope,
            language,
            source_path,
            symbol,
            domain,
            value,
        )
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
                    " ".join(metadata_scope_names(flow.metadata)),
                ]
            )
        )
        metadata_tokens = _flow_metadata_tokens(flow)
        score = 0
        reasons: list[str] = []
        for term in unique_terms:
            if _term_matches(term, name_tokens):
                score += IDENTITY_WEIGHT
                reasons.append(f"`{term}` matches the flow identity")
            if _term_matches(term, node_tokens):
                score += NODE_WEIGHT
                reasons.append(f"`{term}` appears in a decision or action")
            if _term_matches(term, structure_tokens):
                score += STRUCTURE_WEIGHT
                reasons.append(f"`{term}` matches flow structure")
            if _term_matches(term, metadata_tokens):
                score += METADATA_WEIGHT
                reasons.append(f"`{term}` appears in decision metadata")
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
    dependency_paths: list[str] | None = None,
) -> ImpactResult:
    normalized = {_normalize_path(item) for item in changed_files}
    flows = [flow for flow in model.flows if flow_in_scope(flow, scope)]
    direct = [flow for flow in flows if _normalize_path(flow.location.path) in normalized]
    by_id = {flow.id: flow for flow in model.flows}
    scoped_ids = {flow.id for flow in flows}
    target_flow_ids = _unique(flow_ids or [])
    target_symbols = _unique(symbols or [])
    target_dependency_paths = _unique(_normalize_path(item) for item in dependency_paths or [])
    unresolved_targets: list[dict[str, str]] = []
    direct_by_id: dict[str, Flow] = {}
    impact_reasons: dict[str, list[str]] = {}

    def add_reason(flow: Flow, reason: str) -> None:
        reasons = impact_reasons.setdefault(flow.id, [])
        if reason not in reasons:
            reasons.append(reason)

    for flow in direct:
        direct_by_id[flow.id] = flow
        add_reason(flow, f"source file changed `{_normalize_path(flow.location.path)}`")

    for file_record in model.files:
        dependency_matches = sorted(
            dependency
            for dependency in {_normalize_path(item) for item in file_record.dependencies}
            if dependency in normalized
        )
        if not dependency_matches:
            continue
        for flow_id in file_record.flow_ids:
            dependent_flow = by_id.get(flow_id)
            if dependent_flow is None or dependent_flow.id not in scoped_ids:
                continue
            direct_by_id[dependent_flow.id] = dependent_flow
            for dependency in dependency_matches:
                add_reason(dependent_flow, f"depends on changed file `{dependency}`")

    def add_flow(flow: Flow, target_type: str, value: str, reason: str) -> None:
        if flow.id not in scoped_ids:
            unresolved_targets.append(
                {"type": target_type, "value": value, "reason": "scope_filtered"}
            )
            return
        direct_by_id[flow.id] = flow
        add_reason(flow, reason)

    for flow_id in target_flow_ids:
        target_flow = by_id.get(flow_id)
        if target_flow is None:
            unresolved_targets.append({"type": "flow", "value": flow_id, "reason": "not_found"})
            continue
        add_flow(target_flow, "flow", flow_id, f"explicit flow target `{flow_id}`")

    for symbol in target_symbols:
        matches = [flow for flow in model.flows if symbol in (flow.symbol, flow.name)]
        if not matches:
            unresolved_targets.append({"type": "symbol", "value": symbol, "reason": "not_found"})
            continue
        for flow in matches:
            add_flow(flow, "symbol", symbol, f"explicit symbol/name target `{symbol}`")

    for dependency_path in target_dependency_paths:
        matches = [
            flow
            for flow in model.flows
            if _path_matches_dependency(_normalize_path(flow.location.path), dependency_path)
        ]
        if not matches:
            unresolved_targets.append(
                {"type": "dependency_path", "value": dependency_path, "reason": "not_found"}
            )
            continue
        scoped_matches = [flow for flow in matches if flow.id in scoped_ids]
        if not scoped_matches:
            unresolved_targets.append(
                {
                    "type": "dependency_path",
                    "value": dependency_path,
                    "reason": "scope_filtered",
                }
            )
            continue
        for flow in scoped_matches:
            direct_by_id[flow.id] = flow
            add_reason(flow, f"dependency path target `{dependency_path}`")

    direct = list(direct_by_id.values())
    impacted_ids = set(direct_by_id)
    queue: deque[str] = deque(impacted_ids)
    transitive: list[Flow] = []
    while queue:
        current = by_id.get(queue.popleft())
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
                add_reason(caller, f"calls impacted flow `{current.name}`")

    transitive = [flow for flow in transitive if flow_in_scope(flow, scope)]
    impacted_ids = {flow.id for flow in direct} | {flow.id for flow in transitive}
    scoped_impact_reasons = {
        flow_id: reasons
        for flow_id, reasons in sorted(impact_reasons.items())
        if flow_id in impacted_ids
    }
    return ImpactResult(
        changed_files=sorted(normalized),
        directly_impacted=sorted(direct, key=lambda item: item.name),
        transitively_impacted=sorted(transitive, key=lambda item: item.name),
        impact_reasons=scoped_impact_reasons,
        target_flow_ids=target_flow_ids,
        target_symbols=target_symbols,
        target_dependency_paths=target_dependency_paths,
        unresolved_targets=unresolved_targets,
    )


def flow_navigation(
    model: ProjectModel,
    target: str,
    token_budget: int = 0,
) -> dict[str, Any]:
    """A bounded navigation pack for one flow, shared by CLI and MCP."""
    flow, error = _resolve_flow_target(model, target)
    if error is not None:
        return error
    assert flow is not None
    by_id = {item.id: item for item in model.flows}
    scope = metadata_scope_names(flow.metadata)
    primary_scope = scope[0] if scope else None
    return {
        "flow": {
            **flow_summary(flow),
            "symbol": flow.symbol,
            "is_entrypoint": flow.is_entrypoint,
            "nodes": len(flow.nodes),
            "edges": len(flow.edges),
            "decisions": sum(node.kind is NodeKind.DECISION for node in flow.nodes),
            "calls": len(flow.calls),
            "callers": len(flow.called_by),
            "tests": flow.tests,
        },
        "called_flows": _navigation_cap(_related_flow_summaries(flow.calls, by_id), token_budget),
        "caller_flows": _navigation_cap(
            _related_flow_summaries(flow.called_by, by_id), token_budget
        ),
        "unresolved_call_ids": [target_id for target_id in flow.calls if target_id not in by_id],
        "decision_nodes": _navigation_cap(
            [_decision_navigation(node) for node in flow.nodes if node.kind is NodeKind.DECISION],
            token_budget,
        ),
        "next_tools": {
            "agent_context": {
                "tool": "agent_context",
                "arguments": {
                    "flow_id": flow.id,
                    "question": flow.name,
                    **({"scope": primary_scope} if primary_scope else {}),
                },
            },
            "snapshot_slice": {
                "tool": "snapshot_slice",
                "arguments": {
                    "flow_ids": [flow.id],
                    "format": "svg",
                    "include_svg": False,
                },
            },
            "expand_slice": {
                "tool": "expand_slice",
                "arguments": {"flow_ids": [flow.id], "direction": "neighbors"},
            },
        },
    }


def _resolve_flow_target(
    model: ProjectModel, target: str
) -> tuple[Flow | None, dict[str, Any] | None]:
    symbol_match: Flow | None = None
    name_matches: list[Flow] = []
    for flow in model.flows:
        if flow.id == target:
            return flow, None
        if symbol_match is None and flow.symbol == target:
            symbol_match = flow
        if flow.name == target:
            name_matches.append(flow)
    if symbol_match is not None:
        return symbol_match, None
    if len(name_matches) == 1:
        return name_matches[0], None
    if len(name_matches) > 1:
        return None, _flow_target_error(
            f"ambiguous flow target: {target}",
            "flow_target_ambiguous",
            target,
            matches=[flow_summary(flow) for flow in name_matches],
        )
    return None, _flow_target_error(f"flow not found: {target}", "flow_not_found", target)


def _flow_target_error(
    message: str,
    error_code: str,
    target: str,
    *,
    matches: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": message,
        "error_code": error_code,
        "target": target,
        "recoverable": True,
        "guardrail": (
            "This reports an invalid flow-navigation target from the generated model; "
            "re-run agent_context with a narrower question to locate a modeled flow."
        ),
        "next_tools": {
            "agent_context": {
                "tool": "agent_context",
                "arguments": {"question": target, "token_budget": 600},
            },
        },
    }
    if matches is not None:
        payload["matches"] = matches
    return payload


def _navigation_cap(items: list[dict[str, Any]], token_budget: int) -> list[dict[str, Any]]:
    if token_budget <= 0:
        return items
    return items[: max(1, token_budget // NAVIGATION_TOKENS_PER_ITEM)]


def flow_summary(flow: Flow) -> dict[str, Any]:
    return {
        "id": flow.id,
        "name": flow.name,
        "source": f"{flow.location.path}:{flow.location.start_line}",
        "entry_kind": flow.entry_kind,
        "language": flow.language,
        "scope": metadata_scope_names(flow.metadata),
    }


def _related_flow_summaries(flow_ids: list[str], by_id: dict[str, Flow]) -> list[dict[str, Any]]:
    return sorted(
        [flow_summary(by_id[flow_id]) for flow_id in flow_ids if flow_id in by_id],
        key=lambda item: (item["name"], item["id"]),
    )


def _decision_navigation(node: FlowNode) -> dict[str, Any]:
    return {
        "node_id": node.id,
        "label": node.label,
        "source": f"{node.location.path}:{node.location.start_line}",
        "condition": node.metadata.get("condition"),
        "domain": node.metadata.get("domain"),
        "subject": node.metadata.get("subject"),
        "operator": node.metadata.get("operator"),
        "values": node.metadata.get("values", []),
        "branches": node.metadata.get("branches", []),
    }


def flow_in_scope(flow: Flow, scope: str | None) -> bool:
    """Whether a flow belongs to the requested macro-part (None = no filter)."""
    return scope is None or scope in metadata_scope_names(flow.metadata)


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


def _unique(values: Iterable[str]) -> list[str]:
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
    return [token for token in _word_tokens(question) if len(token) > 1 and token not in stopwords]


def _tokenize(text: str) -> set[str]:
    """The field-side tokenizer that mirrors ``_terms`` (unicode \\w words, lowercased),
    so query terms are matched against whole tokens rather than substrings."""
    tokens: set[str] = set()
    for token in _word_tokens(text):
        tokens.update(_term_variants(token))
    return tokens


def _word_tokens(text: str) -> list[str]:
    # Split common code identifiers before lowercasing so a human query for "upload"
    # can match names such as UnifiedUploadBox or ocrService. \w is unicode-aware in
    # py3, so "café" / "日本語" still survive tokenization.
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
    tokens: list[str] = []
    for token in re.findall(r"\w+", spaced.lower()):
        tokens.extend(part for part in token.split("_") if part)
    return tokens


def _term_matches(term: str, tokens: set[str]) -> bool:
    return any(variant in tokens for variant in _term_variants(term))


def _term_variants(token: str) -> set[str]:
    variants = {token}
    if len(token) > 5 and token.endswith("ies"):
        variants.add(f"{token[:-3]}y")
    if len(token) > 4 and token.endswith("es"):
        variants.add(token[:-2])
    if len(token) > 3 and token.endswith("s"):
        variants.add(token[:-1])
    if len(token) >= 6 and token[-1] in {"a", "e", "i", "o"}:
        variants.add(token[:-1])
    return {variant for variant in variants if len(variant) > 1}


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


def _normalize_path(value: str) -> str:
    # Strip only a leading "./" prefix - not the {'.', '/'} char set, which would
    # corrupt dot-prefixed paths like ".github/workflows/ci.yml".
    value = value.replace("\\", "/")
    return value[2:] if value.startswith("./") else value


def _path_matches_dependency(source_path: str, dependency_path: str) -> bool:
    dependency = dependency_path.rstrip("/")
    if not dependency:
        return False
    return source_path == dependency or source_path.startswith(f"{dependency}/")
