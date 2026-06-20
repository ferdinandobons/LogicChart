from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logicchart.model import (
    Evidence,
    Flow,
    FlowEdge,
    FlowNode,
    NodeKind,
    SourceLocation,
)
from logicchart.util import compact_text, relpath

FUNCTIONAL_TERMS = {
    "active",
    "admin",
    "allow",
    "auth",
    "authorized",
    "blocked",
    "cancel",
    "complete",
    "deleted",
    "deny",
    "disabled",
    "enabled",
    "error",
    "exists",
    "failed",
    "invalid",
    "missing",
    "mode",
    "none",
    "owner",
    "paid",
    "permission",
    "ready",
    "role",
    "state",
    "status",
    "suspended",
    "type",
    "valid",
}

BOUNDARY_CALL_TERMS = {
    "authorize",
    "commit",
    "create",
    "delete",
    "dispatch",
    "execute",
    "fetch",
    "insert",
    "publish",
    "redirect",
    "request",
    "save",
    "send",
    "update",
    "validate",
    "write",
}


@dataclass(slots=True)
class PendingEdge:
    node_id: str
    label: str = ""


class FlowBuilder:
    def __init__(self, flow: Flow) -> None:
        self.flow = flow
        self._node_number = 0
        self._edge_number = 0

    def add_node(
        self,
        kind: NodeKind,
        label: str,
        location: SourceLocation,
        incoming: list[PendingEdge],
        *,
        evidence: Evidence = Evidence.VERIFIED,
        detail: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> FlowNode:
        self._node_number += 1
        node = FlowNode(
            id=f"{self.flow.id}:n{self._node_number}",
            kind=kind,
            label=compact_text(label, 120),
            location=location,
            evidence=evidence,
            detail=compact_text(detail, 500),
            metadata=metadata or {},
        )
        self.flow.nodes.append(node)
        for endpoint in incoming:
            self.add_edge(endpoint.node_id, node.id, endpoint.label)
        return node

    def add_edge(
        self,
        source: str,
        target: str,
        label: str = "",
        evidence: Evidence = Evidence.VERIFIED,
    ) -> FlowEdge:
        self._edge_number += 1
        edge = FlowEdge(
            id=f"{self.flow.id}:e{self._edge_number}",
            source=source,
            target=target,
            label=label,
            evidence=evidence,
        )
        self.flow.edges.append(edge)
        return edge


def require_tree_sitter_parse_ok(root_node: Any, relative: str, language: str) -> None:
    """Raise a clean SyntaxError when a tree-sitter parse contains error nodes.

    Tree-sitter can produce a partial tree for malformed source. That is useful for
    editors, but LogicChart's canonical model should not present a partial flow as if it
    were trustworthy. The project analyzer catches SyntaxError and records the file as a
    skipped-file quality signal instead.
    """
    parse_error = tree_sitter_parse_error(root_node, relative, language)
    if parse_error is None:
        return
    raise SyntaxError(parse_error["reason"])


def tree_sitter_parse_error(root_node: Any, relative: str, language: str) -> dict[str, Any] | None:
    if not bool(getattr(root_node, "has_error", False)):
        return None
    error_node = _first_tree_sitter_error(root_node) or root_node
    point = getattr(error_node, "start_point", None)
    line = int(getattr(point, "row", 0)) + 1
    kind = str(getattr(error_node, "type", "ERROR"))
    return {
        "language": language,
        "path": relative,
        "line": line,
        "kind": kind,
        "reason": f"{language} parse error in {relative}:{line} near {kind}",
    }


def _first_tree_sitter_error(node: Any) -> Any | None:
    if str(getattr(node, "type", "")) == "ERROR":
        return node
    for child in getattr(node, "children", []) or []:
        if bool(getattr(child, "has_error", False)):
            found = _first_tree_sitter_error(child)
            return found or child
    return None


def is_functional_condition(condition: str, branch_text: str = "") -> bool:
    lowered = f"{condition} {branch_text}".lower()
    tokens = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", lowered))
    if tokens & FUNCTIONAL_TERMS:
        return True
    # Control-flow outcomes mark a branch as functional, including a bare `return`.
    if re.search(r"\b(return|raise|throw|redirect)\b", lowered):
        return True
    return any(term in lowered for term in BOUNDARY_CALL_TERMS)


# Canonical per-branch terminal behavior, recorded on a decision node's `branches`
# metadata and validated by branch().
RETURNS = "returns"
RAISES = "raises"
FALLS_THROUGH = "falls_through"
EMPTY = "empty"
CONTINUES = "continues"
BRANCH_OUTCOMES = frozenset({RETURNS, RAISES, FALLS_THROUGH, EMPTY, CONTINUES})

# Structural branch *labels* the walkers emit on decision edges.
YES = "Yes"
NO = "No"
SUCCESS = "Success"
DEFAULT = "default"
WILDCARD = "_"
# Labels that mark a genuine else/default branch (vs the positive case).
FALLBACK_LABELS = frozenset({NO, DEFAULT, WILDCARD})

# Value-dispatch decision constructs, stored in a decision node's `operator`.
MATCH = "match"
SWITCH = "switch"
DISPATCH_OPERATORS = frozenset({MATCH, SWITCH})

# Negative comparison operators stored in a decision node's `operator`. A negative
# comparison (status != X / status not in {...} / x is not Y) is a guard that allows the
# rest, not a positive value-dispatch over those members.
OP_NE = "!="
OP_IS_NOT = "is not"
OP_NOT_IN = "not in"
NEGATIVE_OPERATORS = frozenset({OP_NE, OP_NOT_IN, OP_IS_NOT})

DOMAIN_TERMS = ("status", "state", "role", "type", "kind", "mode", "permission")
_IDENTITY_OPERATORS = r"==|!=|\bis not\b|\bnot in\b|\bis\b|\bin\b"


def domain_from_subject(subject: str) -> str:
    """The functional domain a decision subject touches (status/role/...), or ""."""
    lowered = subject.lower()
    return next((term for term in DOMAIN_TERMS if term in lowered), "")


def branch(label: str, outcome: str, *, implicit: bool = False) -> dict[str, Any]:
    """One decision-branch record for a node's `branches` metadata."""
    assert outcome in BRANCH_OUTCOMES, f"unknown branch outcome: {outcome!r}"
    return {"label": label, "outcome": outcome, "implicit": implicit}


def decision_identity(
    *,
    condition: str,
    subject: str,
    operator: str,
    domain: str = "",
    values: list[str] | None = None,
    negation: bool = False,
    namespace: str | None = None,
) -> dict[str, Any]:
    """Assemble the canonical decision-node metadata key set.

    Single constructor so every decision node - if/elif, match, switch, try - carries
    the same shape (condition/domain/values plus the identity fields).
    """
    sorted_values = sorted(set(values or []))
    resolved_namespace = namespace if namespace is not None else value_namespace(sorted_values)
    return {
        "condition": condition,
        "domain": domain,
        "values": sorted_values,
        "subject": subject,
        "operator": operator,
        "negation": negation,
        "value_namespace": resolved_namespace,
    }


_VALUE_OPERATORS = r"==|!=|\bis not\b|\bnot in\b|\bin\b|\bis\b"
# Tuple, list, set literal, dotted identifier, or quoted string after a comparison.
_VALUE_LITERAL = r"\([^)]*\)|\[[^\]]*\]|\{[^}]*\}|[A-Za-z_][\w.]*|['\"][^'\"]+['\"]"
_VALUE_PATTERN = re.compile(rf"(?:{_VALUE_OPERATORS})\s*(?:{_VALUE_LITERAL})")
_LEADING_OPERATOR = re.compile(rf"^(?:{_VALUE_OPERATORS})\s*")
_VALUE_STRIP = " '\"[](){}"


def decision_metadata(condition: str) -> dict[str, Any]:
    compact = compact_text(condition, 240)
    lowered = compact.lower()
    domain = next((term for term in DOMAIN_TERMS if re.search(rf"\b{term}\b", lowered)), "")

    values: list[str] = []
    for value in _VALUE_PATTERN.findall(compact):
        for token in re.split(r"[,|]", _LEADING_OPERATOR.sub("", value)):
            cleaned = token.strip(_VALUE_STRIP)
            if cleaned:
                values.append(cleaned)
    subject, operator, negation = parse_subject_operator(compact)
    return decision_identity(
        condition=compact,
        subject=subject,
        operator=operator,
        domain=domain,
        values=values,
        negation=negation,
    )


def parse_subject_operator(condition: str) -> tuple[str, str, bool]:
    """Decompose a decision condition into (subject, operator, negation).

    Comparison conditions yield the normalized dotted left-hand side and one of
    ==/!=/is/is not/in/not in. Bare truthiness checks (``not user.active``,
    ``!ctx.ok``) yield an empty operator with the negation flag set.
    """
    text = condition.strip()
    match = re.match(
        rf"^\s*(?P<neg>not\s+|!)?\s*(?P<lhs>.+?)\s*(?P<op>{_IDENTITY_OPERATORS})\s*(?P<rhs>.+)$",
        text,
    )
    if match:
        operator = re.sub(r"\s+", " ", match.group("op").strip())
        return match.group("lhs").strip(), operator, bool(match.group("neg"))

    negation = bool(re.match(r"\s*(not\s+|!)", text))
    subject = re.sub(r"^\s*(not\s+|!)\s*", "", text)
    return subject.strip(), "", negation


def value_namespace(values: list[str]) -> str:
    """The shared dotted enum prefix of compared values (``Foo.BAR`` -> ``Foo``).

    Returns the single common namespace when every dotted value agrees, else "".
    """
    prefixes = {value.rsplit(".", 1)[0] for value in values if "." in value}
    return next(iter(prefixes)) if len(prefixes) == 1 else ""


# Marker for a module's default export, so a default import resolves to whichever
# flow carries `default_export` rather than guessing its name. `#` cannot appear in
# an identifier, so it never collides with a real symbol.
DEFAULT_EXPORT_MARKER = "#default"

# Confidence tiers recorded on a resolved call's `link_confidence`.
CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_NONE = "none"
LINK_CONFIDENCES = frozenset({CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW, CONFIDENCE_NONE})


def resolve_qualified(raw: str, import_map: dict[str, str], current_module: str) -> str:
    """Resolve a call name to a ``module:symbol`` reference via the import map.

    Import-map values carry the boundary: ``module:symbol`` binds a symbol
    (``from m import f``), ``module:`` binds a module (so the next attribute is the
    symbol). An unmapped head is assumed local to the current module. Preserving the
    ``:`` keeps a module path from being confused with attribute access on a value.

    The longest dotted prefix wins, so a multi-segment module binding (``import
    pkg.util`` -> ``pkg.util:``) resolves ``pkg.util.persist`` to ``pkg.util:persist``
    rather than stopping at the first segment.
    """
    parts = raw.split(".")
    for size in range(len(parts), 0, -1):
        base = import_map.get(".".join(parts[:size]))
        if base is None:
            continue
        rest = ".".join(parts[size:])
        if not rest:
            return base
        return f"{base}{rest}" if base.endswith(":") else f"{base}.{rest}"
    return f"{current_module}:{raw}"


def attach_qualified_calls(flow: Flow, import_map: dict[str, str], current_module: str) -> None:
    """Record `qualified_calls` (``module:symbol`` references) on every call node.

    Each raw call name is resolved through the import map; unmapped heads fall back
    to a current-module reference (expected to miss for external calls, hit for local).
    """
    for node in flow.nodes:
        if node.kind is not NodeKind.CALL:
            continue
        raw_calls = [str(item) for item in node.metadata.get("calls", [])]
        node.metadata["qualified_calls"] = [
            resolve_qualified(raw, import_map, current_module) for raw in raw_calls
        ]


def dependency_paths_from_import_map(
    import_map: dict[str, str],
    root: Path,
    *,
    module_suffixes: tuple[str, ...],
    package_files: tuple[str, ...] = (),
    package_directories: bool = False,
    include_path: Callable[[str], bool] = lambda relative: True,
) -> list[str]:
    """Resolve import-map modules to first-party source paths under ``root``.

    Import maps may contain external packages. A dependency is emitted only when a
    candidate file exists inside the analyzed folder, keeping impact edges local-first and
    deterministic.
    """
    dependencies: list[str] = []
    seen: set[str] = set()
    for module in _import_map_modules(import_map):
        module_path = module.replace(".", "/")
        candidates = [
            *(f"{module_path}{suffix}" for suffix in module_suffixes),
            *(f"{module_path}/{filename}" for filename in package_files),
        ]
        for candidate in candidates:
            path = root / candidate
            if not path.is_file():
                continue
            relative = relpath(path, root)
            if not include_path(relative):
                continue
            if relative not in seen:
                dependencies.append(relative)
                seen.add(relative)
            break
        else:
            if not package_directories:
                continue
            package_dir = root / module_path
            if not package_dir.is_dir():
                continue
            for suffix in module_suffixes:
                for path in sorted(package_dir.glob(f"*{suffix}")):
                    if not path.is_file():
                        continue
                    relative = relpath(path, root)
                    if not include_path(relative):
                        continue
                    if relative not in seen:
                        dependencies.append(relative)
                        seen.add(relative)
    return dependencies


def _import_map_modules(import_map: dict[str, str]) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()
    for value in import_map.values():
        module = str(value).split(":", 1)[0]
        if not module or module in seen:
            continue
        modules.append(module)
        seen.add(module)
    return modules


def annotate_reachability(flow: Flow) -> None:
    """Record `reachable_from_entry` / `reaches_terminal` on every node.

    Deterministic graph reachability: a forward walk from entry nodes and a
    reverse walk from terminal/error nodes. Surfaced for navigation and explanation.
    """
    outgoing: dict[str, list[str]] = {node.id: [] for node in flow.nodes}
    incoming: dict[str, list[str]] = {node.id: [] for node in flow.nodes}
    for edge in flow.edges:
        if edge.source in outgoing and edge.target in incoming:
            outgoing[edge.source].append(edge.target)
            incoming[edge.target].append(edge.source)

    entries = [node.id for node in flow.nodes if node.kind is NodeKind.ENTRY]
    exits = [node.id for node in flow.nodes if node.kind in (NodeKind.TERMINAL, NodeKind.ERROR)]
    from_entry = _reach(entries, outgoing)
    to_terminal = _reach(exits, incoming)
    for node in flow.nodes:
        node.metadata["reachable_from_entry"] = node.id in from_entry
        node.metadata["reaches_terminal"] = node.id in to_terminal


def _reach(seeds: list[str], adjacency: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set(seeds)
    stack = list(seeds)
    while stack:
        current = stack.pop()
        for neighbor in adjacency.get(current, ()):
            if neighbor not in seen:
                seen.add(neighbor)
                stack.append(neighbor)
    return seen


def call_is_boundary(name: str) -> bool:
    lowered = name.lower()
    return any(term in lowered for term in BOUNDARY_CALL_TERMS)


# Side-effect categories inferred from a call's leaf name. Used as explanatory metadata
# for calls and branch behavior.
EFFECT_LEXICON: dict[str, tuple[str, ...]] = {
    "auth_check": (
        "require_role",
        "require_admin",
        "require_permission",
        "check_permission",
        "ensure_authenticated",
        "ensure_admin",
        "get_current_user",
        "authorize",
        "authenticate",
        "verify_token",
        "has_permission",
        "is_authorized",
    ),
    "db_write": ("save", "insert", "update", "delete", "create", "commit", "persist", "upsert"),
    "db_read": ("fetch", "find", "load", "query", "select", "lookup"),
    "network": ("send", "publish", "dispatch", "notify", "emit", "request"),
    "log": ("log", "warn", "warning", "capture_exception", "alert"),
}


# Receiver names that mark a call as logging regardless of the level method
# (so `logger.info` / `log.error` / `self.logging.warning` all count as a log).
_LOGGER_RECEIVERS = {"log", "logger", "logging"}


def _to_snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def effect_tags(call_names: Iterable[str]) -> list[str]:
    """The side-effect categories a set of call names implies (word-boundary match)."""
    effects: set[str] = set()
    for name in call_names:
        parts = str(name).split(".")
        padded = f"_{_to_snake(parts[-1])}_"
        for effect, terms in EFFECT_LEXICON.items():
            if any(f"_{term}_" in padded for term in terms):
                effects.add(effect)
        if any(part.lower() in _LOGGER_RECEIVERS for part in parts[:-1]):
            effects.add("log")
    return sorted(effects)


def tag_call_effects(flow: Flow) -> None:
    """Tag call nodes with `effects` and set the flow's `performs_auth_check`."""
    performs_auth = False
    for node in flow.nodes:
        if node.kind is not NodeKind.CALL:
            continue
        effects = effect_tags(str(item) for item in node.metadata.get("calls", []))
        if effects:
            node.metadata["effects"] = effects
        performs_auth = performs_auth or "auth_check" in effects
    flow.metadata["performs_auth_check"] = performs_auth
