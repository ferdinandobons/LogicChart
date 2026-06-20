"""A profile-driven tree-sitter analyzer.

Most languages share the same control-flow shape (functions, ``if``, ``switch``/
``match``, loops, ``return``, ``throw``/``raise``, ``try``/``catch``, calls). This module
runs that common walk once, parameterized by a :class:`LanguageProfile` that names the
grammar node types and supplies small per-language extractors. A new control-flow
language becomes a profile (see ``analysis/languages/``), not a bespoke analyzer.

It produces the same IR (flows, nodes, edges, ``branches``, decision identity, effects,
qualified calls) as the dedicated Python/TypeScript analyzers, so linking, rendering, and
agent navigation stay consistent.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tree_sitter import Language, Parser

from logicchart.analysis.common import (
    CONTINUES,
    EMPTY,
    FALLS_THROUGH,
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
    dependency_paths_from_import_map,
    domain_from_subject,
    is_functional_condition,
    require_tree_sitter_parse_ok,
    tag_call_effects,
    tree_sitter_parse_error,
    value_namespace,
)
from logicchart.analysis.common import DEFAULT as DEFAULT_LABEL
from logicchart.analysis.common import NO as NO_LABEL
from logicchart.config import LogicChartConfig
from logicchart.model import Evidence, FileAnalysis, Flow, NodeKind, SourceLocation
from logicchart.util import compact_text, file_sha256, relpath, stable_id


@dataclass(slots=True)
class TSDefinition:
    """One function/method to turn into a flow."""

    name: str
    node: Any
    body: Any
    owner: str = ""


@dataclass(frozen=True, slots=True)
class LanguageProfile:
    """The grammar vocabulary + extractors that make a language analyzable.

    Defaults describe a typical C-family grammar; a profile overrides only what differs.
    Callables keep the per-language bits (which functions are entry points, what a test
    file looks like, how imports resolve) out of the generic walk.
    """

    language: str
    grammar_loader: Callable[[], Any]
    function_types: frozenset[str]
    definitions: Callable[[Any, bytes, str, LanguageProfile], Iterable[TSDefinition]]
    classify: Callable[[TSDefinition, str, str, LogicChartConfig], tuple[str, str, bool]]
    is_test: Callable[[str, str], bool]
    module_name: Callable[[str], str]
    import_map: Callable[[Any, bytes, str], dict[str, str]] = lambda root, src, rel: {}
    dependency_module_suffixes: tuple[str, ...] = ()
    dependency_package_files: tuple[str, ...] = ()
    dependency_package_directories: bool = False
    dependency_path_filter: Callable[[str], bool] = lambda relative: True
    entry_label: Callable[[Flow], str] | None = None
    harvest_enums: Callable[[Any, bytes], dict[str, list[str]]] | None = None
    # Node-type vocabulary (C-family defaults).
    block_types: frozenset[str] = frozenset({"block"})
    if_type: str = "if_statement"
    condition_field: str = "condition"
    consequence_field: str = "consequence"
    alternative_field: str = "alternative"
    # Else-branch node types when the else is a child rather than a field (Ruby).
    alternative_types: frozenset[str] = frozenset()
    switch_types: frozenset[str] = frozenset()
    switch_value_field: str = "value"
    switch_body_field: str | None = "body"
    case_types: frozenset[str] = frozenset()
    case_value_field: str = "value"
    default_types: frozenset[str] = frozenset()
    # A case with no value is the default (C: `default:` is a valueless case_statement).
    default_when_no_value: bool = False
    # Case values that mean "match anything" (a match `_` arm acts as the default).
    wildcard_values: frozenset[str] = frozenset()
    # The switch/match is compiler-exhaustive (e.g. Rust `match`): no explicit default does
    # not mean an unhandled case, so it must not be flagged as a missing fallback.
    exhaustive_switch: bool = False
    # C-style fall-through: a case whose body does not break/return/raise/continue runs on
    # into the next case (C/PHP/TS/JS/Java colon labels). Go/Ruby/Rust/Python implicitly
    # terminate each case, so an empty body must NOT chain into the next case there.
    case_fall_through: bool = False
    loop_types: frozenset[str] = frozenset()
    return_type: str = "return_statement"
    return_keyword: str = "return"
    throw_types: frozenset[str] = frozenset()
    throw_keyword: str = "throw"
    continue_types: frozenset[str] = frozenset({"continue_statement"})
    break_types: frozenset[str] = frozenset({"break_statement"})
    call_types: frozenset[str] = frozenset({"call_expression"})
    call_function_field: str = "function"
    call_name: Callable[[Any, bytes], str] | None = None
    try_type: str | None = None
    try_body_field: str = "body"
    catch_types: frozenset[str] = frozenset()
    catch_body_field: str = "body"
    finally_types: frozenset[str] = frozenset()
    # Override case extraction for grammars that don't fit the simple "case nodes with a
    # value field" shape (e.g. Java's switch_block groups).
    switch_cases: Callable[[Any, bytes, LanguageProfile], list[CaseInfo]] | None = None
    assignment_types: frozenset[str] = frozenset()
    assignment_target_field: str = "left"
    nested_def_types: frozenset[str] = field(default_factory=frozenset)
    inert_types: frozenset[str] = frozenset({"comment"})
    # Wrapper statements unwrapped to their inner expression before dispatch (e.g. Rust
    # wraps an if/match used as a statement in an expression_statement).
    unwrap_types: frozenset[str] = frozenset()


@dataclass(slots=True)
class CaseInfo:
    """One switch/case branch: its label, dispatched values, and body statements."""

    label: str
    is_default: bool
    values: list[str]
    body: list[Any]


class TreeSitterAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig, profile: LanguageProfile) -> None:
        self.root = root
        self.config = config
        self.profile = profile
        self.parser = Parser(Language(profile.grammar_loader()))

    def analyze(self, path: Path) -> FileAnalysis:
        # Strip a leading UTF-8 BOM so a file an editor saved as UTF-8-with-BOM parses;
        # the byte offsets the walk reports stay correct because the BOM is dropped
        # before parsing (it is never part of a real token).
        source = path.read_bytes().removeprefix(b"\xef\xbb\xbf")
        relative = relpath(path, self.root)
        tree = self.parser.parse(source)
        parse_error = tree_sitter_parse_error(tree.root_node, relative, self.profile.language)
        definitions = list(self.profile.definitions(tree.root_node, source, relative, self.profile))
        if parse_error is not None and not definitions:
            require_tree_sitter_parse_ok(tree.root_node, relative, self.profile.language)
        flows = [self._analyze_definition(item, source, relative) for item in definitions]
        if parse_error is not None:
            for flow in flows:
                flow.metadata["parse_error"] = parse_error
        import_map = self.profile.import_map(tree.root_node, source, relative)
        module_name = self.profile.module_name(relative)
        dependencies = [
            item
            for item in dependency_paths_from_import_map(
                import_map,
                self.root,
                module_suffixes=self.profile.dependency_module_suffixes,
                package_files=self.profile.dependency_package_files,
                package_directories=self.profile.dependency_package_directories,
                include_path=self.profile.dependency_path_filter,
            )
            if item != relative
        ]
        for flow in flows:
            attach_qualified_calls(flow, import_map, module_name)
            tag_call_effects(flow)
        harvest = self.profile.harvest_enums
        enums = harvest(tree.root_node, source) if harvest else {}
        return FileAnalysis(
            path=relative,
            language=self.profile.language,
            sha256=file_sha256(path),
            enums=enums,
            dependencies=dependencies,
            flows=flows,
        )

    def _analyze_definition(self, definition: TSDefinition, source: bytes, relative: str) -> Flow:
        owner_prefix = f"{definition.owner}." if definition.owner else ""
        qualified_name = f"{owner_prefix}{definition.name}"
        symbol = f"{self.profile.module_name(relative)}:{qualified_name}"
        framework, entry_kind, is_entrypoint = self.profile.classify(
            definition, relative, source.decode("utf-8", "replace"), self.config
        )
        is_test = self.profile.is_test(relative, definition.name)
        if is_test:
            is_entrypoint = False
            entry_kind = "test"

        location = _location(relative, definition.node)
        flow = Flow(
            id=f"flow-{stable_id(symbol)}",
            name=qualified_name,
            symbol=symbol,
            language=self.profile.language,
            framework=framework,
            entry_kind=entry_kind,
            is_entrypoint=is_entrypoint,
            location=location,
            metadata={"test": is_test},
        )
        builder = FlowBuilder(flow)
        entry = builder.add_node(
            NodeKind.ENTRY, self._entry_label(flow), location, [], metadata={"symbol": symbol}
        )
        outgoing = self._walk_statements(
            self._statement_children(definition.body),
            [PendingEdge(entry.id)],
            builder,
            source,
            relative,
        )
        if outgoing:
            builder.add_node(
                NodeKind.TERMINAL, "Complete", location, outgoing, evidence=Evidence.INFERRED
            )
        annotate_reachability(flow)
        tag_call_effects(flow)
        return flow

    def _entry_label(self, flow: Flow) -> str:
        if self.profile.entry_label is not None:
            return self.profile.entry_label(flow)
        return flow.name

    def _walk_statements(
        self,
        statements: list[Any],
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        profile = self.profile
        endpoints = incoming
        for raw in statements:
            if not endpoints:
                break
            statement = raw
            if statement.type in profile.unwrap_types:
                inner = next((c for c in statement.children if c.is_named), None)
                if inner is not None:
                    statement = inner
            node_type = statement.type
            if node_type == profile.if_type:
                endpoints = self._walk_if(statement, endpoints, builder, source, relative)
            elif node_type in profile.switch_types:
                endpoints = self._walk_switch(statement, endpoints, builder, source, relative)
            elif profile.try_type is not None and node_type == profile.try_type:
                endpoints = self._walk_try(statement, endpoints, builder, source, relative)
            elif node_type in profile.loop_types:
                endpoints = self._walk_loop(statement, endpoints, builder, source, relative)
            elif node_type == profile.return_type:
                endpoints = self._walk_return(statement, endpoints, builder, source, relative)
            elif node_type in profile.throw_types:
                value = _text(statement, source).removeprefix(profile.throw_keyword).strip(" ;")
                builder.add_node(
                    NodeKind.ERROR,
                    f"Raise {value}".strip(),
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                )
                endpoints = []
            elif node_type in profile.break_types:
                node = builder.add_node(
                    NodeKind.ACTION,
                    "Break loop",
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                    metadata={"loop_control": "break"},
                )
                endpoints = [PendingEdge(node.id)]
            elif node_type in profile.continue_types:
                builder.add_node(
                    NodeKind.ACTION,
                    "Continue loop",
                    _location(relative, statement),
                    endpoints,
                    detail=_text(statement, source),
                    metadata={"loop_control": "continue"},
                )
                endpoints = []
            elif node_type in profile.function_types or node_type in profile.nested_def_types:
                continue
            else:
                kind, label, calls = self._statement_summary(statement, source)
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

    def _walk_return(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        value = _text(statement, source).removeprefix(self.profile.return_keyword).strip(" ;")
        calls = self._calls_in(statement, source)
        endpoints = incoming
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
        return []

    def _walk_loop(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        body = self._loop_body(statement)
        body_statements = self._statement_children(body)
        node = builder.add_node(
            NodeKind.ACTION,
            _loop_label(statement, source),
            _location(relative, statement),
            incoming,
            detail=_text(statement, source),
            evidence=Evidence.INFERRED,
            metadata={
                "loop": True,
                "body_outcome": self._branch_outcome(body_statements),
                "has_else": False,
            },
        )
        body_endpoints = self._walk_statements(
            body_statements,
            [PendingEdge(node.id, "Iteration")],
            builder,
            source,
            relative,
        )
        return [PendingEdge(node.id, "Done"), *body_endpoints]

    def _walk_if(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        profile = self.profile
        condition_node = statement.child_by_field_name(profile.condition_field)
        consequence = statement.child_by_field_name(profile.consequence_field)
        alternative = statement.child_by_field_name(profile.alternative_field)
        if alternative is None and profile.alternative_types:
            # Languages where the else branch is a child node, not a field (Ruby).
            alternative = next(
                (c for c in _named_children(statement) if c.type in profile.alternative_types), None
            )
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
            branch(YES, self._branch_outcome(self._statement_children(consequence))),
            branch(
                NO_LABEL,
                self._branch_outcome(self._statement_children(alternative))
                if alternative is not None
                else FALLS_THROUGH,
                implicit=alternative is None,
            ),
        ]
        yes_endpoints = self._walk_statements(
            self._statement_children(consequence),
            [PendingEdge(node.id, YES)],
            builder,
            source,
            relative,
        )
        if alternative is not None:
            no_endpoints = self._walk_statements(
                self._statement_children(alternative),
                [PendingEdge(node.id, NO_LABEL)],
                builder,
                source,
                relative,
            )
        else:
            no_endpoints = [PendingEdge(node.id, NO_LABEL)]
        return yes_endpoints + no_endpoints

    def _walk_switch(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        profile = self.profile
        value_node = statement.child_by_field_name(profile.switch_value_field)
        subject = _strip_parentheses(_text(value_node, source)) or "value"
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
        cases = (
            profile.switch_cases(statement, source, profile)
            if profile.switch_cases
            else (self._default_cases(statement, source))
        )
        endpoints: list[PendingEdge] = []
        values: list[str] = []
        has_default = False
        branches: list[dict[str, Any]] = []
        # C-style fall-through: when a case body neither breaks nor returns/raises and is
        # NOT the last case, its endpoints chain into the NEXT case's body rather than
        # onto the post-switch join. Without this, `case A: case B: return X` would dangle
        # A's endpoint onto "Complete", fabricating a path the real switch never takes.
        carried: list[PendingEdge] = []
        for index, case in enumerate(cases):
            if case.is_default:
                label = DEFAULT_LABEL
                has_default = True
            else:
                label = case.label
                values.extend(case.values)
            branches.append(branch(label, self._branch_outcome(case.body)))
            case_endpoints = self._walk_statements(
                case.body,
                [PendingEdge(node.id, label), *carried],
                builder,
                source,
                relative,
            )
            carried = []
            if (
                profile.case_fall_through
                and index + 1 < len(cases)
                and self._case_falls_through(case.body)
            ):
                carried = case_endpoints
            else:
                endpoints.extend(case_endpoints)
        node.metadata["values"] = sorted(set(values))
        node.metadata["value_namespace"] = value_namespace(sorted(set(values)))
        if not has_default and not profile.exhaustive_switch:
            branches.append(branch(DEFAULT_LABEL, FALLS_THROUGH, implicit=True))
            endpoints.append(PendingEdge(node.id, DEFAULT_LABEL))
        node.metadata["branches"] = branches
        return endpoints

    def _default_cases(self, statement: Any, source: bytes) -> list[CaseInfo]:
        profile = self.profile
        container = (
            statement.child_by_field_name(profile.switch_body_field)
            if profile.switch_body_field
            else statement
        )
        cases: list[CaseInfo] = []
        for case in _named_children(container):
            case_value = case.child_by_field_name(profile.case_value_field)
            body = self._case_body(case, case_value)
            label = _text(case_value, source)
            is_default = (
                case.type in profile.default_types
                or (profile.default_when_no_value and case_value is None)
                or label in profile.wildcard_values
            )
            if is_default:
                cases.append(CaseInfo(DEFAULT_LABEL, True, [], body))
            elif case.type in profile.case_types:
                # A multi-value case (`case A, B:` in Go) groups several values under one
                # label; split them so each counts toward enum coverage individually.
                values = _split_case_values(case_value, label, source)
                cases.append(CaseInfo(label or "case", False, values, body))
        return cases

    def _case_body(self, case: Any, case_value: Any) -> list[Any]:
        children = [
            child
            for child in _named_children(case)
            if case_value is None
            or child.start_byte != case_value.start_byte
            or child.end_byte != case_value.end_byte
        ]
        flattened: list[Any] = []
        for child in children:
            if child.type in self.profile.block_types:
                flattened.extend(_named_children(child))
            else:
                flattened.append(child)
        return flattened

    def _walk_try(
        self,
        statement: Any,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: bytes,
        relative: str,
    ) -> list[PendingEdge]:
        profile = self.profile
        body = statement.child_by_field_name(profile.try_body_field)
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
            branch(SUCCESS, self._branch_outcome(self._statement_children(body)))
        ]
        endpoints = self._walk_statements(
            self._statement_children(body),
            [PendingEdge(node.id, SUCCESS)],
            builder,
            source,
            relative,
        )
        for catch in (c for c in _named_children(statement) if c.type in profile.catch_types):
            catch_body = self._statement_children(self._block_of(catch))
            branches.append(branch("Error", self._branch_outcome(catch_body)))
            endpoints.extend(
                self._walk_statements(
                    catch_body, [PendingEdge(node.id, "Error")], builder, source, relative
                )
            )
        node.metadata["branches"] = branches
        finals = [c for c in _named_children(statement) if c.type in profile.finally_types]
        if finals:
            final_body = self._statement_children(self._block_of(finals[0]))
            body_terminated = not endpoints
            finally_incoming = endpoints or [PendingEdge(node.id, "finally")]
            endpoints = self._walk_statements(
                final_body, finally_incoming, builder, source, relative
            )
            if body_terminated:
                endpoints = []
        return endpoints

    def _block_of(self, node: Any) -> Any:
        body = node.child_by_field_name(self.profile.catch_body_field)
        if body is not None:
            return body
        for child in _named_children(node):
            if child.type in self.profile.block_types:
                return child
        return node

    def _case_falls_through(self, statements: list[Any]) -> bool:
        """Whether a C-style switch case runs on into the next case.

        A case falls through unless it explicitly leaves the switch: a break exits to
        the post-switch join, and a return/raise/continue leaves the function or loop.
        An empty case (`case A: case B: ...`) and a case that simply runs off its end
        both fall through. We require the *terminator to be reached on the straight-line
        body*, so a break/return nested only inside an `if` does not count as an
        unconditional exit (control can still fall through the else side).
        """
        profile = self.profile
        for statement in statements:
            if statement.type in profile.inert_types:
                continue
            if (
                statement.type == profile.return_type
                or statement.type in profile.throw_types
                or statement.type in profile.continue_types
                or statement.type in profile.break_types
            ):
                return False
            if (
                profile.try_type is not None
                and statement.type == profile.try_type
                and not self._try_case_falls_through(statement)
            ):
                return False
            if statement.type == profile.if_type:
                alternative = statement.child_by_field_name(profile.alternative_field)
                if alternative is not None:
                    then_falls_through = self._case_falls_through(
                        self._statement_children(
                            statement.child_by_field_name(profile.consequence_field)
                        )
                    )
                    else_falls_through = self._case_falls_through(
                        self._statement_children(alternative)
                    )
                    if not then_falls_through and not else_falls_through:
                        return False
        return True

    def _try_case_falls_through(self, statement: Any) -> bool:
        profile = self.profile
        finals = [c for c in _named_children(statement) if c.type in profile.finally_types]
        if finals and not self._case_falls_through(
            self._statement_children(self._block_of(finals[0]))
        ):
            return False

        body = statement.child_by_field_name(profile.try_body_field)
        body_falls_through = self._case_falls_through(self._statement_children(body))
        catches = [c for c in _named_children(statement) if c.type in profile.catch_types]
        if not catches:
            return body_falls_through
        return body_falls_through or any(
            self._case_falls_through(self._statement_children(self._block_of(catch)))
            for catch in catches
        )

    def _branch_outcome(self, statements: list[Any]) -> str:
        profile = self.profile
        meaningful = [s for s in statements if s.type not in profile.inert_types]
        if not meaningful:
            return EMPTY
        for statement in meaningful:
            if statement.type == profile.return_type:
                return RETURNS
            if statement.type in profile.throw_types:
                return RAISES
            if statement.type in profile.continue_types:
                return CONTINUES
            if statement.type in profile.break_types:
                return FALLS_THROUGH
            if profile.try_type is not None and statement.type == profile.try_type:
                try_outcome = self._try_statement_outcome(statement)
                if _terminates(try_outcome):
                    return try_outcome
            if statement.type == profile.if_type:
                alternative = statement.child_by_field_name(profile.alternative_field)
                if alternative is not None:
                    then_outcome = self._branch_outcome(
                        self._statement_children(
                            statement.child_by_field_name(profile.consequence_field)
                        )
                    )
                    else_outcome = self._branch_outcome(self._statement_children(alternative))
                    if _terminates(then_outcome) and _terminates(else_outcome):
                        return then_outcome if then_outcome == else_outcome else RETURNS
        return FALLS_THROUGH

    def _try_statement_outcome(self, statement: Any) -> str:
        profile = self.profile
        finals = [c for c in _named_children(statement) if c.type in profile.finally_types]
        if finals:
            final_outcome = self._branch_outcome(
                self._statement_children(self._block_of(finals[0]))
            )
            if _terminates(final_outcome):
                return final_outcome

        body = statement.child_by_field_name(profile.try_body_field)
        outcomes = [self._branch_outcome(self._statement_children(body))]
        outcomes.extend(
            self._branch_outcome(self._statement_children(self._block_of(catch)))
            for catch in _named_children(statement)
            if catch.type in profile.catch_types
        )
        if outcomes and all(_terminates(outcome) for outcome in outcomes):
            return outcomes[0] if all(outcome == outcomes[0] for outcome in outcomes) else RETURNS
        return FALLS_THROUGH

    def _statement_summary(self, statement: Any, source: bytes) -> tuple[NodeKind, str, list[str]]:
        calls = self._calls_in(statement, source)
        boundary = next((item for item in calls if call_is_boundary(item)), "")
        if boundary:
            return NodeKind.CALL, f"Call {boundary}()", calls
        if calls:
            return NodeKind.CALL, f"Call {calls[0]}()", calls
        if statement.type in self.profile.assignment_types:
            target = _text(
                statement.child_by_field_name(self.profile.assignment_target_field), source
            )
            if target:
                return NodeKind.ACTION, f"Set {target}", []
        return NodeKind.ACTION, compact_text(_text(statement, source).rstrip(";"), 90), []

    def _calls_in(self, statement: Any, source: bytes) -> list[str]:
        field_name = self.profile.call_function_field
        extract = self.profile.call_name or (lambda call, src: _call_name(call, src, field_name))
        names = [
            extract(item, source)
            for item in self._descendants(statement)
            if item.type in self.profile.call_types
        ]
        return [name for name in names if name]

    def _descendants(self, node: Any) -> Iterable[Any]:
        breakers = self.profile.function_types | self.profile.nested_def_types
        stack = [node]
        while stack:
            current = stack.pop()
            yield current
            if current is not node and current.type in breakers:
                continue
            stack.extend(reversed(current.children))

    def _statement_children(self, node: Any | None) -> list[Any]:
        if node is None:
            return []
        profile = self.profile
        if node.type in profile.block_types:
            return list(_named_children(node))
        # A control-flow statement used directly as a branch body (an `else if`, where the
        # alternative IS the nested if) must be dispatched by the walker, not flattened to
        # one of its blocks - else the middle branch is silently dropped.
        dispatchable = (
            {profile.if_type, profile.return_type}
            | profile.switch_types
            | profile.loop_types
            | profile.throw_types
        )
        if profile.try_type is not None:
            dispatchable.add(profile.try_type)
        if node.type in dispatchable:
            return [node]
        # A wrapper clause (else clause, then clause): descend into the block it holds.
        blocks = [c for c in _named_children(node) if c.type in profile.block_types]
        if blocks:
            return list(_named_children(blocks[-1]))
        return [node]

    def _loop_body(self, statement: Any) -> Any | None:
        body = statement.child_by_field_name("body")
        if body is not None:
            return body
        blocks = [
            child for child in _named_children(statement) if child.type in self.profile.block_types
        ]
        if blocks:
            return blocks[-1]
        named = list(_named_children(statement))
        return named[-1] if named else None


def _named_children(node: Any | None) -> Iterable[Any]:
    if node is None:
        return []
    return (child for child in node.children if child.is_named)


def _text(node: Any | None, source: bytes) -> str:
    if node is None:
        return ""
    return compact_text(source[node.start_byte : node.end_byte].decode("utf-8", "replace"), 500)


def _location(relative: str, node: Any) -> SourceLocation:
    return SourceLocation(relative, int(node.start_point.row) + 1, int(node.end_point.row) + 1)


def _loop_label(statement: Any, source: bytes) -> str:
    header = _text(statement, source).split("{", 1)[0].strip()
    return compact_text(f"Repeat: {header}", 100)


def _call_name(call: Any, source: bytes, function_field: str) -> str:
    return _text(call.child_by_field_name(function_field), source)


def _strip_parentheses(value: str) -> str:
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    return value


def _split_case_values(case_value: Any, label: str, source: bytes) -> list[str]:
    """The individual values of a (possibly multi-value) case label.

    A grammar that groups several values under one case (Go `case A, B:` parses to an
    `expression_list` whose named children are the values) is split into its members.
    Falls back to a top-level comma split of the label text (commas inside (), [], {}
    are not boundaries, so a call/tuple value stays whole). A single-value case yields
    just its label.
    """
    if case_value is None:
        return []
    members = [_text(child, source).strip() for child in case_value.children if child.is_named]
    grammar_split = [text for text in members if text]
    if len(grammar_split) >= 2:
        return grammar_split
    return [piece for piece in _split_top_level(label) if piece] or ([label] if label else [])


def _split_top_level(text: str) -> list[str]:
    """Split on top-level commas, ignoring commas nested in (), [], or {}."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in text:
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if char == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    parts.append("".join(current).strip())
    return parts


def _terminates(outcome: str) -> bool:
    return outcome in {RETURNS, RAISES, CONTINUES}
