from __future__ import annotations

import posixpath
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tree_sitter_typescript
from tree_sitter import Language, Parser

from logicchart.analysis.common import (
    CONTINUES,
    DEFAULT,
    DEFAULT_EXPORT_MARKER,
    EMPTY,
    FALLS_THROUGH,
    NO,
    RAISES,
    RETURNS,
    SUCCESS,
    SWITCH,
    YES,
    FlowBuilder,
    PendingEdge,
    annotate_reachability,
    attach_qualified_calls,
    branch,
    call_is_boundary,
    decision_identity,
    decision_metadata,
    domain_from_subject,
    is_functional_condition,
    tag_call_effects,
    value_namespace,
)
from logicchart.analysis.detectors import dead_code_finding, single_flow_findings
from logicchart.config import LogicChartConfig
from logicchart.model import Evidence, FileAnalysis, Finding, Flow, NodeKind, SourceLocation
from logicchart.util import compact_text, file_sha256, relpath, stable_id

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
LOOP_TYPES = {"for_statement", "for_in_statement", "while_statement", "do_statement"}
FUNCTION_TYPES = {"function_declaration", "generator_function_declaration"}
CALLABLE_VALUE_TYPES = {"arrow_function", "function_expression", "generator_function"}


@dataclass(slots=True)
class TypeScriptDefinition:
    name: str
    node: Any
    body: Any
    owner: str
    exported: bool
    default_export: bool


class TypeScriptAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig) -> None:
        self.root = root
        self.config = config

    def analyze(self, path: Path) -> FileAnalysis:
        source_bytes = path.read_bytes()
        source = source_bytes.decode("utf-8")
        relative = relpath(path, self.root)
        language = "tsx" if path.suffix == ".tsx" else "typescript"
        grammar = (
            tree_sitter_typescript.language_tsx()
            if language == "tsx"
            else tree_sitter_typescript.language_typescript()
        )
        parser = Parser(Language(grammar))
        tree = parser.parse(source_bytes)
        findings: list[Finding] = []
        flows = [
            self._analyze_definition(item, source_bytes, source, relative, findings)
            for item in _definitions(tree.root_node, source_bytes, relative)
        ]
        import_map = _import_map(tree.root_node, source_bytes, relative)
        module_name = _module_name(relative)
        for flow in flows:
            attach_qualified_calls(flow, import_map, module_name)
        return FileAnalysis(
            path=relative,
            language="typescript",
            sha256=file_sha256(path),
            enums=_harvest_enums(tree.root_node, source_bytes),
            flows=flows,
            findings=findings,
        )

    def _analyze_definition(
        self,
        definition: TypeScriptDefinition,
        source_bytes: bytes,
        source: str,
        relative: str,
        findings: list[Finding],
    ) -> Flow:
        qualified_name = (
            f"{definition.owner}.{definition.name}" if definition.owner else definition.name
        )
        symbol = f"{_module_name(relative)}:{qualified_name}"
        framework, entry_kind, is_entrypoint = _classify_entrypoint(
            definition, relative, source, self.config
        )
        is_test = _is_test(relative, definition.name)
        if is_test:
            is_entrypoint = False
            entry_kind = "test"

        location = _location(relative, definition.node)
        flow = Flow(
            id=f"flow-{stable_id(symbol)}",
            name=qualified_name,
            symbol=symbol,
            language="typescript",
            framework=framework,
            entry_kind=entry_kind,
            is_entrypoint=is_entrypoint,
            location=location,
            metadata={
                "exported": definition.exported,
                "default_export": definition.default_export,
                "test": is_test,
            },
        )
        builder = FlowBuilder(flow)
        entry = builder.add_node(
            NodeKind.ENTRY,
            _entry_label(flow),
            location,
            [],
            metadata={"symbol": symbol},
        )
        statements = list(_named_children(definition.body))
        outgoing = self._walk_statements(
            statements,
            [PendingEdge(entry.id)],
            builder,
            findings,
            source_bytes,
            relative,
        )
        if outgoing:
            builder.add_node(
                NodeKind.TERMINAL,
                "Complete",
                location,
                outgoing,
                evidence=Evidence.INFERRED,
            )
        annotate_reachability(flow)
        # Tag effects before single-flow detection so detectors that reason about
        # call effects (e.g. a log-only exception handler) see them.
        tag_call_effects(flow)
        findings.extend(single_flow_findings(flow))
        return flow

    def _walk_statements(
        self,
        statements: list[Any],
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        endpoints = incoming
        for index, statement in enumerate(statements):
            if not endpoints:
                dead = statements[index]
                findings.append(
                    dead_code_finding(
                        builder.flow,
                        _location(relative, dead),
                        _text(dead, source),
                    )
                )
                break
            node_type = statement.type
            if node_type == "if_statement":
                endpoints = self._walk_if(statement, endpoints, builder, findings, source, relative)
            elif node_type == "switch_statement":
                endpoints = self._walk_switch(
                    statement, endpoints, builder, findings, source, relative
                )
            elif node_type == "try_statement":
                endpoints = self._walk_try(
                    statement, endpoints, builder, findings, source, relative
                )
            elif node_type in LOOP_TYPES:
                node = builder.add_node(
                    NodeKind.ACTION,
                    _loop_label(statement, source),
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                    evidence=Evidence.INFERRED,
                )
                endpoints = [PendingEdge(node.id)]
            elif node_type == "return_statement":
                value = _text(statement, source).removeprefix("return").rstrip(";").strip()
                calls = [
                    _call_name(item, source)
                    for item in _descendants(statement)
                    if item.type == "call_expression"
                ]
                calls = [item for item in calls if item]
                if calls:
                    call_node = builder.add_node(
                        NodeKind.CALL,
                        f"Call {calls[0]}()",
                        _location(relative, statement),
                        endpoints,
                        detail=_text(statement, source),
                        metadata={"calls": calls},
                    )
                    endpoints = [PendingEdge(call_node.id)]
                builder.add_node(
                    NodeKind.TERMINAL,
                    f"Return {value}".strip(),
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                )
                endpoints = []
            elif node_type == "throw_statement":
                value = _text(statement, source).removeprefix("throw").rstrip(";").strip()
                builder.add_node(
                    NodeKind.ERROR,
                    f"Throw {value}".strip(),
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                )
                endpoints = []
            elif node_type in {"function_declaration", "class_declaration"}:
                continue
            else:
                kind, label, calls = _statement_summary(statement, source)
                node = builder.add_node(
                    kind,
                    label,
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                    metadata={"calls": calls} if calls else {},
                )
                endpoints = [PendingEdge(node.id)]
        return endpoints

    def _walk_if(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        condition_node = statement.child_by_field_name("condition")
        consequence = statement.child_by_field_name("consequence")
        alternative = statement.child_by_field_name("alternative")
        condition = _strip_parentheses(_text(condition_node, source))
        branch_text = _text(consequence, source)

        if not is_functional_condition(condition, branch_text):
            node = builder.add_node(
                NodeKind.ACTION,
                f"Handle internal condition: {condition}",
                _location(relative, statement),
                incoming,
                evidence=Evidence.INFERRED,
                detail=_text(statement, source),
            )
            return [PendingEdge(node.id)]

        node = builder.add_node(
            NodeKind.DECISION,
            condition,
            _location(relative, condition_node or statement),
            incoming,
            detail=condition,
            metadata=decision_metadata(condition),
        )
        node.metadata["branches"] = [
            branch(YES, _branch_outcome(_statement_children(consequence))),
            branch(
                NO,
                (
                    _branch_outcome(_statement_children(alternative))
                    if alternative is not None
                    else FALLS_THROUGH
                ),
                implicit=alternative is None,
            ),
        ]
        yes_endpoints = self._walk_statements(
            _statement_children(consequence),
            [PendingEdge(node.id, YES)],
            builder,
            findings,
            source,
            relative,
        )
        if alternative is not None:
            no_endpoints = self._walk_statements(
                _statement_children(alternative),
                [PendingEdge(node.id, NO)],
                builder,
                findings,
                source,
                relative,
            )
        else:
            no_endpoints = [PendingEdge(node.id, NO)]
        return yes_endpoints + no_endpoints

    def _walk_switch(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        value_node = statement.child_by_field_name("value")
        subject = _strip_parentheses(_text(value_node, source))
        node = builder.add_node(
            NodeKind.DECISION,
            f"Switch on {subject}",
            _location(relative, statement),
            incoming,
            metadata=decision_identity(
                condition=subject,
                subject=subject,
                operator=SWITCH,
                domain=domain_from_subject(subject),
                namespace="",
            ),
        )
        body = statement.child_by_field_name("body")
        endpoints: list[PendingEdge] = []
        values: list[str] = []
        has_default = False
        branches: list[dict[str, Any]] = []
        for case in _named_children(body):
            value_node = case.child_by_field_name("value")
            if case.type == "switch_default":
                label = DEFAULT
                has_default = True
            elif case.type == "switch_case":
                label = _text(value_node, source) or "case"
                values.append(label)
            else:
                continue
            children = [
                child
                for child in _named_children(case)
                if value_node is None
                or (
                    child.start_byte != value_node.start_byte
                    or child.end_byte != value_node.end_byte
                )
            ]
            branches.append(branch(label, _branch_outcome(children)))
            endpoints.extend(
                self._walk_statements(
                    children,
                    [PendingEdge(node.id, label)],
                    builder,
                    findings,
                    source,
                    relative,
                )
            )
        node.metadata["values"] = sorted(set(values))
        node.metadata["value_namespace"] = value_namespace(sorted(set(values)))
        if not has_default:
            branches.append(branch(DEFAULT, FALLS_THROUGH, implicit=True))
            # An unmatched value falls through to whatever follows the switch.
            endpoints.append(PendingEdge(node.id, DEFAULT))
        node.metadata["branches"] = branches
        return endpoints

    def _walk_try(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        body = statement.child_by_field_name("body")
        handler = statement.child_by_field_name("handler")
        finalizer = statement.child_by_field_name("finalizer")
        node = builder.add_node(
            NodeKind.DECISION,
            "Operation succeeds?",
            _location(relative, statement),
            incoming,
            evidence=Evidence.INFERRED,
            detail=_text(statement, source),
            metadata=decision_identity(
                condition="exception boundary",
                subject="exception",
                operator="",
                domain="error",
                namespace="",
            ),
        )
        branches: list[dict[str, Any]] = [
            branch(SUCCESS, _branch_outcome(_statement_children(body)))
        ]
        endpoints = self._walk_statements(
            _statement_children(body),
            [PendingEdge(node.id, SUCCESS)],
            builder,
            findings,
            source,
            relative,
        )
        if handler is not None:
            branches.append(branch("Error", _branch_outcome(_statement_children(handler))))
            endpoints.extend(
                self._walk_statements(
                    _statement_children(handler),
                    [PendingEdge(node.id, "Error")],
                    builder,
                    findings,
                    source,
                    relative,
                )
            )
        node.metadata["branches"] = branches
        if finalizer is not None:
            # A finally block always runs, even when the body/handler returned.
            body_terminated = not endpoints
            finally_incoming = endpoints or [PendingEdge(node.id, "finally")]
            endpoints = self._walk_statements(
                _statement_children(finalizer),
                finally_incoming,
                builder,
                findings,
                source,
                relative,
            )
            if body_terminated:
                # The try/handler already returned/raised; once finally runs that
                # terminator resumes, so anything after the try is unreachable.
                endpoints = []
        return endpoints


def _definitions(root: Any, source: bytes, relative: str) -> Iterable[TypeScriptDefinition]:
    yield from _walk_definitions(root, source, relative, owner="", exported=False, default=False)


def _walk_definitions(
    node: Any,
    source: bytes,
    relative: str,
    owner: str,
    exported: bool,
    default: bool,
) -> Iterable[TypeScriptDefinition]:
    node_text = _text(node, source)
    if node.type == "export_statement":
        exported = True
        default = bool(re.match(r"\s*export\s+default\b", node_text))

    if node.type == "class_declaration":
        name_node = node.child_by_field_name("name")
        class_name = _text(name_node, source) or owner
        body = node.child_by_field_name("body")
        for child in _named_children(body):
            yield from _walk_definitions(
                child, source, relative, owner=class_name, exported=exported, default=default
            )
        return

    if node.type in FUNCTION_TYPES:
        name_node = node.child_by_field_name("name")
        name = _text(name_node, source)
        if not name and default:
            name = _default_export_name(relative)
        body = node.child_by_field_name("body")
        if name and body is not None:
            yield TypeScriptDefinition(name, node, body, owner, exported, default)
        return

    if node.type == "method_definition":
        name = _text(node.child_by_field_name("name"), source)
        body = node.child_by_field_name("body")
        if name and body is not None:
            yield TypeScriptDefinition(name, node, body, owner, exported, default)
        return

    if node.type == "variable_declarator":
        value = node.child_by_field_name("value")
        name = _text(node.child_by_field_name("name"), source)
        if value is not None and value.type in CALLABLE_VALUE_TYPES and name:
            body = value.child_by_field_name("body")
            if body is not None:
                yield TypeScriptDefinition(name, node, body, owner, exported, default)
        return

    for child in _named_children(node):
        yield from _walk_definitions(child, source, relative, owner, exported, default)


def _classify_entrypoint(
    definition: TypeScriptDefinition,
    relative: str,
    source: str,
    config: LogicChartConfig,
) -> tuple[str, str, bool]:
    owner_prefix = f"{definition.owner}." if definition.owner else ""
    symbol_hint = f"{relative}:{owner_prefix}{definition.name}"
    override = config.entrypoint_override(symbol_hint)
    normalized = "/" + relative.replace("\\", "/")

    if (
        definition.name in HTTP_METHODS
        and definition.exported
        and (normalized.endswith("/route.ts") or normalized.endswith("/route.tsx"))
    ):
        return "nextjs", "route", override if override is not None else True
    if definition.name == "middleware" and definition.exported:
        return "nextjs", "middleware", override if override is not None else True
    if ('"use server"' in source or "'use server'" in source) and definition.exported:
        return "nextjs", "server_action", override if override is not None else True
    if relative.endswith(("/page.tsx", "/layout.tsx")) and (
        definition.default_export or definition.exported
    ):
        return "nextjs", "component", override if override is not None else True
    if re.match(r"^(on|handle)[A-Z_]", definition.name):
        return "react", "event_handler", override if override is not None else True
    if definition.name.startswith("use") and len(definition.name) > 3:
        return "react", "hook", override if override is not None else definition.exported
    if relative.endswith(".tsx") and definition.name[:1].isupper():
        return "react", "component", override if override is not None else definition.exported
    if definition.owner:
        return "generic", "method", override if override is not None else False
    public = config.include_public_functions and definition.exported
    return "generic", "function", override if override is not None else public


def _statement_summary(statement: Any, source: bytes) -> tuple[NodeKind, str, list[str]]:
    calls = [
        _call_name(item, source)
        for item in _descendants(statement)
        if item.type == "call_expression"
    ]
    calls = [item for item in calls if item]
    boundary = next((item for item in calls if call_is_boundary(item)), "")
    if boundary:
        return NodeKind.CALL, f"Call {boundary}()", calls
    if calls:
        return NodeKind.CALL, f"Call {calls[0]}()", calls
    text = _text(statement, source).rstrip(";")
    if statement.type in {"lexical_declaration", "variable_declaration"}:
        names = [
            _text(item.child_by_field_name("name"), source)
            for item in _descendants(statement)
            if item.type == "variable_declarator"
        ]
        label = f"Set {', '.join(item for item in names if item)}"
        return NodeKind.ACTION, label or compact_text(text, 90), []
    return NodeKind.ACTION, compact_text(text, 90), []


def _call_name(call: Any, source: bytes) -> str:
    function = call.child_by_field_name("function")
    return _text(function, source)


def _statement_children(node: Any | None) -> list[Any]:
    if node is None:
        return []
    if node.type in {"statement_block", "switch_body"}:
        return list(_named_children(node))
    if node.type == "else_clause":
        children = list(_named_children(node))
        return _statement_children(children[-1]) if children else []
    if node.type == "catch_clause":
        body = node.child_by_field_name("body")
        return _statement_children(body)
    if node.type == "finally_clause":
        children = list(_named_children(node))
        return _statement_children(children[-1]) if children else []
    return [node]


def _named_children(node: Any | None) -> Iterable[Any]:
    if node is None:
        return []
    return (child for child in node.children if child.is_named)


def _descendants(node: Any) -> Iterable[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        if current is not node and current.type in FUNCTION_TYPES | CALLABLE_VALUE_TYPES:
            continue
        stack.extend(reversed(current.children))


def _text(node: Any | None, source: bytes) -> str:
    if node is None:
        return ""
    return compact_text(source[node.start_byte : node.end_byte].decode("utf-8"), 500)


def _location(relative: str, node: Any) -> SourceLocation:
    return SourceLocation(
        relative,
        int(node.start_point.row) + 1,
        int(node.end_point.row) + 1,
    )


def _loop_label(statement: Any, source: bytes) -> str:
    text = _text(statement, source)
    header = text.split("{", 1)[0].strip()
    return compact_text(f"Repeat: {header}", 100)


def _entry_label(flow: Flow) -> str:
    labels = {
        "route": "Route",
        "middleware": "Middleware",
        "server_action": "Server action",
        "component": "Component",
        "hook": "Hook",
        "event_handler": "Event",
        "test": "Test",
    }
    prefix = labels.get(flow.entry_kind)
    return f"{prefix}: {flow.name}" if prefix else flow.name


def _module_name(relative: str) -> str:
    for suffix in (".tsx", ".ts"):
        if relative.endswith(suffix):
            relative = relative[: -len(suffix)]
    return relative.replace("/", ".")


def _default_export_name(relative: str) -> str:
    stem = Path(relative).stem
    return stem[:1].upper() + stem[1:] if stem else "DefaultExport"


def _import_map(root: Any, source: bytes, relative: str) -> dict[str, str]:
    """Map each imported binding to a fully-qualified target module symbol.

    Resolves relative module specifiers against the importing file; bare/external
    specifiers (e.g. ``react``) are skipped so only first-party calls resolve.
    """
    mapping: dict[str, str] = {}
    for node in root.children:
        if node.type != "import_statement":
            continue
        source_node = node.child_by_field_name("source")
        if source_node is None:
            continue
        module = _resolve_module(_text(source_node, source).strip("'\"`"), relative)
        if module is None:
            continue
        clause = next((child for child in node.children if child.type == "import_clause"), None)
        if clause is None:
            continue
        for child in clause.children:
            if child.type == "identifier":  # default import -> resolve via marker
                mapping[_text(child, source)] = f"{module}:{DEFAULT_EXPORT_MARKER}"
            elif child.type == "namespace_import":  # import * as ns -> binds the module
                alias = next((c for c in child.children if c.type == "identifier"), None)
                if alias is not None:
                    mapping[_text(alias, source)] = f"{module}:"
            elif child.type == "named_imports":
                for spec in child.children:
                    if spec.type != "import_specifier":
                        continue
                    name = _text(spec.child_by_field_name("name"), source)
                    alias_node = spec.child_by_field_name("alias")
                    bound = _text(alias_node, source) if alias_node is not None else name
                    if name:
                        mapping[bound] = f"{module}:{name}"
    return mapping


def _resolve_module(specifier: str, relative: str) -> str | None:
    if not specifier.startswith("."):
        return None
    target = posixpath.normpath(posixpath.join(posixpath.dirname(relative), specifier))
    target = re.sub(r"\.(tsx?|jsx?)$", "", target)
    return target.replace("/", ".")


def _harvest_enums(root: Any, source: bytes) -> dict[str, list[str]]:
    """Map each TS enum / string-literal union to its members - the value universe."""
    enums: dict[str, list[str]] = {}
    for top in root.children:
        nodes = list(_named_children(top)) if top.type == "export_statement" else [top]
        for node in nodes:
            if node.type == "enum_declaration":
                name = _text(node.child_by_field_name("name"), source)
                members = [
                    f"{name}.{_text(child.child_by_field_name('name') or child, source)}"
                    for child in _named_children(node.child_by_field_name("body"))
                    if child.type in {"enum_assignment", "property_identifier"}
                ]
                if name and members:
                    enums[name] = members
            elif node.type == "type_alias_declaration":
                name = _text(node.child_by_field_name("name"), source)
                members = _union_string_members(node.child_by_field_name("value"), source)
                if name and members:
                    enums[name] = members
    return enums


def _union_string_members(value: Any, source: bytes) -> list[str]:
    """String members of a union type, flattening nested and parenthesized unions."""
    if value is None:
        return []
    if value.type in {"union_type", "parenthesized_type"}:
        members: list[str] = []
        for child in _named_children(value):
            members.extend(_union_string_members(child, source))
        return members
    if value.type == "literal_type":
        inner = next(iter(_named_children(value)), None)
        if inner is not None and inner.type == "string":
            return [_text(inner, source).strip("'\"`")]
    return []


def _is_test(relative: str, name: str) -> bool:
    path = Path(relative)
    return (
        name.startswith(("test", "it", "should"))
        or "__tests__" in path.parts
        or ".test." in path.name
        or ".spec." in path.name
    )


_INERT_STATEMENTS = {"empty_statement", "comment"}


def _branch_outcome(statements: list[Any]) -> str:
    """Classify how control leaves a branch body: one of common.BRANCH_OUTCOMES."""
    meaningful = [stmt for stmt in statements if stmt.type not in _INERT_STATEMENTS]
    if not meaningful:
        return EMPTY
    for stmt in meaningful:
        if stmt.type == "return_statement":
            return RETURNS
        if stmt.type == "throw_statement":
            return RAISES
        if stmt.type == "continue_statement":
            return CONTINUES
        if stmt.type == "break_statement":
            # break exits the enclosing loop/switch; control resumes after it.
            return FALLS_THROUGH
        if stmt.type == "if_statement":
            alternative = stmt.child_by_field_name("alternative")
            if alternative is not None:
                then_outcome = _branch_outcome(
                    _statement_children(stmt.child_by_field_name("consequence"))
                )
                else_outcome = _branch_outcome(_statement_children(alternative))
                if _terminates(then_outcome) and _terminates(else_outcome):
                    return then_outcome if then_outcome == else_outcome else RETURNS
    return FALLS_THROUGH


def _terminates(outcome: str) -> bool:
    return outcome in {RETURNS, RAISES, CONTINUES}


def _strip_parentheses(value: str) -> str:
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    return value
