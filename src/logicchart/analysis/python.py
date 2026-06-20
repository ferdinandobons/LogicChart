from __future__ import annotations

import ast
import copy
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, cast

from logicchart.analysis.common import (
    CONTINUES,
    EMPTY,
    FALLS_THROUGH,
    MATCH,
    NO,
    RAISES,
    RETURNS,
    SUCCESS,
    WILDCARD,
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
from logicchart.analysis.discovery import discover_source_files
from logicchart.config import LogicChartConfig
from logicchart.model import (
    Evidence,
    FileAnalysis,
    Flow,
    NodeKind,
    SourceLocation,
)
from logicchart.util import compact_text, file_sha256, relpath, stable_id

FASTAPI_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
CLI_DECORATORS = {"command", "callback"}
HANDLER_PREFIXES = ("handle_", "on_", "process_")


class _SourceText:
    def __init__(self, text: str) -> None:
        self.text = text
        self.lines = text.splitlines(keepends=True)

    def segment(self, node: ast.AST) -> str:
        start_line = getattr(node, "lineno", None)
        end_line = getattr(node, "end_lineno", None)
        start_col = getattr(node, "col_offset", None)
        end_col = getattr(node, "end_col_offset", None)
        if (
            not isinstance(start_line, int)
            or not isinstance(end_line, int)
            or not isinstance(start_col, int)
            or not isinstance(end_col, int)
            or start_line < 1
            or end_line < start_line
            or start_line > len(self.lines)
        ):
            return ""

        end_line = min(end_line, len(self.lines))
        selected = self.lines[start_line - 1 : end_line]
        if not selected:
            return ""
        if start_line == end_line:
            return _slice_line_utf8(selected[0], start_col, end_col)

        first = _slice_line_utf8(selected[0], start_col, None)
        middle = selected[1:-1]
        last = _slice_line_utf8(selected[-1], 0, end_col)
        return "".join([first, *middle, last])


class PythonAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig) -> None:
        self.root = root
        self.config = config
        self._module_paths: dict[str, str] | None = None

    def analyze(self, path: Path) -> FileAnalysis:
        # utf-8-sig transparently strips a leading BOM (a valid file an editor saved as
        # UTF-8-with-BOM), so it parses instead of choking on a stray ﻿ token.
        source = _SourceText(path.read_text(encoding="utf-8-sig"))
        relative = relpath(path, self.root)
        tree = ast.parse(source.text, filename=relative)
        module_name = _module_name(relative)
        constants = _harvest_constants(tree)
        constant_names = set(constants)
        flows: list[Flow] = []
        for definition, owner in _definitions(tree):
            flow = self._analyze_definition(
                definition=definition,
                owner=owner,
                source=source,
                relative=relative,
                module_name=module_name,
            )
            # A constant shadowed locally is runtime-dependent, so dead_guard must not
            # claim its guard is always true/false.
            shadowed = _assigned_names(definition) & constant_names
            if shadowed:
                flow.metadata["shadows_constants"] = sorted(shadowed)
            flows.append(flow)

        is_package = Path(relative).name == "__init__.py"
        module_paths = self._python_module_paths()
        import_map = _import_map(
            tree,
            module_name,
            is_package,
            lambda base, name: _is_submodule(module_paths, base, name),
        )
        dependencies = [
            item
            for item in _dependency_paths_from_modules(import_map, module_paths)
            if item != relative
        ]
        for flow in flows:
            attach_qualified_calls(flow, import_map, module_name)

        return FileAnalysis(
            path=relative,
            language="python",
            sha256=file_sha256(path),
            enums=_harvest_enums(tree),
            constants=constants,
            dependencies=dependencies,
            flows=flows,
        )

    def _python_module_paths(self) -> dict[str, str]:
        if self._module_paths is not None:
            return self._module_paths
        module_paths: dict[str, str] = {}
        for path in discover_source_files(self.root, self.config):
            if path.suffix.lower() != ".py":
                continue
            relative = relpath(path, self.root)
            module_paths.setdefault(_module_name(relative), relative)
        self._module_paths = module_paths
        return module_paths

    def _analyze_definition(
        self,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
        owner: str,
        source: _SourceText,
        relative: str,
        module_name: str,
    ) -> Flow:
        qualified_name = f"{owner}.{definition.name}" if owner else definition.name
        symbol = f"{module_name}:{qualified_name}"
        framework, entry_kind, is_entrypoint = _classify_entrypoint(
            definition, relative, owner, self.config
        )
        is_test = _is_test(relative, definition.name)
        if is_test:
            is_entrypoint = False
            entry_kind = "test"

        location = _location(relative, definition)
        flow = Flow(
            id=f"flow-{stable_id(symbol)}",
            name=qualified_name,
            symbol=symbol,
            language="python",
            framework=framework,
            entry_kind=entry_kind,
            is_entrypoint=is_entrypoint,
            location=location,
            metadata={
                "async": isinstance(definition, ast.AsyncFunctionDef),
                "test": is_test,
                "decorators": [_safe_unparse(item) for item in definition.decorator_list],
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
        outgoing = self._walk_statements(
            definition.body,
            [PendingEdge(entry.id)],
            builder,
            source,
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
        # Tag call effects for downstream navigation and explanation metadata.
        tag_call_effects(flow)
        return flow

    def _walk_statements(
        self,
        statements: list[ast.stmt],
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: _SourceText,
        relative: str,
    ) -> list[PendingEdge]:
        endpoints = incoming
        for statement in statements:
            if not endpoints:
                break
            if isinstance(statement, ast.If):
                endpoints = self._walk_if(statement, endpoints, builder, source, relative)
            elif isinstance(statement, ast.Match):
                endpoints = self._walk_match(statement, endpoints, builder, source, relative)
            elif isinstance(statement, ast.Try):
                endpoints = self._walk_try(statement, endpoints, builder, source, relative)
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                endpoints = self._walk_loop(statement, endpoints, builder, source, relative)
            elif isinstance(statement, ast.Return):
                value = _safe_unparse(statement.value) if statement.value else ""
                calls = _call_names(statement)
                if calls:
                    call_node = builder.add_node(
                        NodeKind.CALL,
                        f"Call {calls[0]}()",
                        _location(relative, statement),
                        endpoints,
                        detail=_source_segment(source, statement),
                        metadata={"calls": calls},
                    )
                    endpoints = [PendingEdge(call_node.id)]
                node = builder.add_node(
                    NodeKind.TERMINAL,
                    f"Return {value}".strip(),
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                )
                endpoints = []
            elif isinstance(statement, ast.Raise):
                value = _safe_unparse(statement.exc) if statement.exc else "error"
                builder.add_node(
                    NodeKind.ERROR,
                    f"Raise {value}",
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                )
                endpoints = []
            elif isinstance(statement, ast.Break):
                node = builder.add_node(
                    NodeKind.ACTION,
                    "Break loop",
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                    metadata={"loop_control": "break"},
                )
                endpoints = [PendingEdge(node.id)]
            elif isinstance(statement, ast.Continue):
                builder.add_node(
                    NodeKind.ACTION,
                    "Continue loop",
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                    metadata={"loop_control": "continue"},
                )
                endpoints = []
            else:
                kind, label, calls = _statement_summary(statement)
                node = builder.add_node(
                    kind,
                    label,
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                    metadata={"calls": calls} if calls else {},
                )
                endpoints = [PendingEdge(node.id)]
        return endpoints

    def _walk_loop(
        self,
        statement: ast.For | ast.AsyncFor | ast.While,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: _SourceText,
        relative: str,
    ) -> list[PendingEdge]:
        node = builder.add_node(
            NodeKind.ACTION,
            _loop_label(statement),
            _location(relative, statement),
            incoming,
            detail=_source_segment(source, statement),
            evidence=Evidence.INFERRED,
            metadata={
                "loop": True,
                "body_outcome": _branch_outcome(statement.body),
                "else_outcome": (
                    _branch_outcome(statement.orelse) if statement.orelse else FALLS_THROUGH
                ),
                "has_else": bool(statement.orelse),
            },
        )
        body_endpoints = self._walk_statements(
            statement.body,
            [PendingEdge(node.id, "Iteration")],
            builder,
            source,
            relative,
        )
        done_endpoints = [PendingEdge(node.id, "Done")]
        if statement.orelse:
            return self._walk_statements(
                statement.orelse,
                done_endpoints + body_endpoints,
                builder,
                source,
                relative,
            )
        return done_endpoints + body_endpoints

    def _walk_if(
        self,
        statement: ast.If,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: _SourceText,
        relative: str,
    ) -> list[PendingEdge]:
        condition = _safe_unparse(statement.test)
        branch_source = _branch_behavior_source(statement.body)
        functional = is_functional_condition(condition, branch_source)
        if not functional:
            node = builder.add_node(
                NodeKind.ACTION,
                f"Handle internal condition: {condition}",
                _location(relative, statement),
                incoming,
                evidence=Evidence.INFERRED,
                detail=_source_segment(source, statement),
            )
            return [PendingEdge(node.id)]

        node = builder.add_node(
            NodeKind.DECISION,
            condition,
            _location(relative, statement.test),
            incoming,
            detail=_source_segment(source, statement.test),
            metadata=decision_metadata(condition),
        )
        node.metadata["branches"] = [
            branch(YES, _branch_outcome(statement.body)),
            branch(
                NO,
                _branch_outcome(statement.orelse) if statement.orelse else FALLS_THROUGH,
                implicit=not statement.orelse,
            ),
        ]
        yes_endpoints = self._walk_statements(
            statement.body,
            [PendingEdge(node.id, YES)],
            builder,
            source,
            relative,
        )
        if statement.orelse:
            no_endpoints = self._walk_statements(
                statement.orelse,
                [PendingEdge(node.id, NO)],
                builder,
                source,
                relative,
            )
        else:
            no_endpoints = [PendingEdge(node.id, NO)]
        return yes_endpoints + no_endpoints

    def _walk_match(
        self,
        statement: ast.Match,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: _SourceText,
        relative: str,
    ) -> list[PendingEdge]:
        subject = _safe_unparse(statement.subject)
        node = builder.add_node(
            NodeKind.DECISION,
            f"Match {subject}",
            _location(relative, statement),
            incoming,
            metadata=decision_identity(
                condition=subject,
                subject=subject,
                operator=MATCH,
                domain=domain_from_subject(subject),
                namespace="",
            ),
        )
        endpoints: list[PendingEdge] = []
        has_default = False
        values: list[str] = []
        branches: list[dict[str, Any]] = []
        for case in statement.cases:
            pattern = _safe_unparse(case.pattern)
            # A guarded wildcard `case _ if cond:` only matches when the guard holds, so
            # it is NOT an exhaustive default - fall-through and missing enum members must
            # still be surfaced.
            is_default = pattern == WILDCARD and case.guard is None
            has_default = has_default or is_default
            label = f"{pattern} if {_safe_unparse(case.guard)}" if case.guard else pattern
            if not is_default and pattern != WILDCARD:
                # Split OR-patterns (`case A | B:`) into their individual members so
                # value_namespace and enum exhaustiveness see the real values.
                values.extend(_match_values(case.pattern))
            branches.append(branch(label, _branch_outcome(case.body)))
            endpoints.extend(
                self._walk_statements(
                    case.body,
                    [PendingEdge(node.id, label)],
                    builder,
                    source,
                    relative,
                )
            )
        node.metadata["values"] = sorted(set(values))
        node.metadata["value_namespace"] = value_namespace(sorted(set(values)))
        if not has_default:
            branches.append(branch(WILDCARD, FALLS_THROUGH, implicit=True))
            # An unmatched value falls through to whatever follows the match.
            endpoints.append(PendingEdge(node.id, WILDCARD))
        node.metadata["branches"] = branches
        return endpoints

    def _walk_try(
        self,
        statement: ast.Try,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        source: _SourceText,
        relative: str,
    ) -> list[PendingEdge]:
        node = builder.add_node(
            NodeKind.DECISION,
            "Operation succeeds?",
            _location(relative, statement),
            incoming,
            evidence=Evidence.INFERRED,
            detail=_source_segment(source, statement),
            metadata=decision_identity(
                condition="exception boundary",
                subject="exception",
                operator="",
                domain="error",
                namespace="",
            ),
        )
        success_outcome = _branch_outcome(statement.body)
        if success_outcome == FALLS_THROUGH and statement.orelse:
            success_outcome = _branch_outcome(statement.orelse)
        branches: list[dict[str, Any]] = [branch(SUCCESS, success_outcome)]
        body_endpoints = self._walk_statements(
            statement.body,
            [PendingEdge(node.id, SUCCESS)],
            builder,
            source,
            relative,
        )
        if statement.orelse and body_endpoints:
            body_endpoints = self._walk_statements(
                statement.orelse,
                body_endpoints,
                builder,
                source,
                relative,
            )
        endpoints = body_endpoints
        for handler in statement.handlers:
            error_name = _safe_unparse(handler.type) if handler.type else "Any error"
            branches.append(branch(error_name, _branch_outcome(handler.body)))
            endpoints.extend(
                self._walk_statements(
                    handler.body,
                    [PendingEdge(node.id, error_name)],
                    builder,
                    source,
                    relative,
                )
            )
        node.metadata["branches"] = branches
        if statement.finalbody:
            # A finally block always runs, even when the body/handlers returned.
            body_terminated = not endpoints
            finally_incoming = endpoints or [PendingEdge(node.id, "finally")]
            endpoints = self._walk_statements(
                statement.finalbody, finally_incoming, builder, source, relative
            )
            if body_terminated:
                # The try/handlers already returned/raised; the terminator resumes after
                # finally, so anything past the try is unreachable.
                endpoints = []
        return endpoints


def _assigned_names(definition: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Names bound inside a function: assignment targets, loop/with vars, and params.

    A name in Store context (or a parameter) shadows a module-level constant of the same
    name, making a guard on it runtime-dependent rather than statically dead.
    """
    visitor = _AssignedNameVisitor()
    visitor.names.update(_argument_names(definition.args))
    for statement in definition.body:
        visitor.visit(statement)
    return visitor.names


def _match_values(pattern: ast.pattern) -> list[str]:
    """The dispatched value(s) of a match case, flattening OR-patterns to members."""
    if isinstance(pattern, ast.MatchOr):
        members: list[str] = []
        for alternative in pattern.patterns:
            members.extend(_match_values(alternative))
        return members
    return [_safe_unparse(pattern)]


def _definitions(
    tree: ast.Module,
) -> Iterable[tuple[ast.FunctionDef | ast.AsyncFunctionDef, str]]:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node, ""
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield member, node.name


def _classify_entrypoint(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
    relative: str,
    owner: str,
    config: LogicChartConfig,
) -> tuple[str, str, bool]:
    decorators = [_safe_unparse(item) for item in definition.decorator_list]
    symbol_hint = f"{relative}:{owner + '.' if owner else ''}{definition.name}"
    override = config.entrypoint_override(symbol_hint)

    for decorator in decorators:
        parts = decorator.split("(", 1)[0].split(".")
        method = parts[-1]
        if method in FASTAPI_METHODS:
            return "fastapi", "route", override if override is not None else True
        if method in CLI_DECORATORS:
            return "python-cli", "command", override if override is not None else True

    if definition.name.startswith(HANDLER_PREFIXES):
        return "generic", "event_handler", override if override is not None else True
    if owner:
        return "generic", "method", override if override is not None else False
    public = config.include_public_functions and not definition.name.startswith("_")
    return "generic", "function", override if override is not None else public


def _statement_summary(statement: ast.stmt) -> tuple[NodeKind, str, list[str]]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return NodeKind.ACTION, f"Define local function {statement.name}", []
    if isinstance(statement, ast.ClassDef):
        return NodeKind.ACTION, f"Define local class {statement.name}", []
    calls = _call_names(statement)
    boundary = next((item for item in calls if call_is_boundary(item)), "")
    if boundary:
        return NodeKind.CALL, f"Call {boundary}()", calls
    if calls:
        return NodeKind.CALL, f"Call {calls[0]}()", calls
    if isinstance(statement, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        targets: list[str] = []
        if isinstance(statement, ast.Assign):
            targets = [_safe_unparse(item) for item in statement.targets]
        else:
            targets = [_safe_unparse(statement.target)]
        return NodeKind.ACTION, f"Set {', '.join(targets)}", []
    if isinstance(statement, ast.Assert):
        return NodeKind.ACTION, f"Assert {_safe_unparse(statement.test)}", []
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return NodeKind.ACTION, "Load dependencies", []
    return NodeKind.ACTION, compact_text(_safe_unparse(statement), 90), []


def _entry_label(flow: Flow) -> str:
    if flow.entry_kind == "route":
        return f"Route: {flow.name}"
    if flow.entry_kind == "command":
        return f"Command: {flow.name}"
    if flow.entry_kind == "test":
        return f"Test: {flow.name}"
    return flow.name


def _location(relative: str, node: ast.AST) -> SourceLocation:
    start = int(getattr(node, "lineno", 1))
    end = int(getattr(node, "end_lineno", start))
    return SourceLocation(relative, start, end)


def _source_segment(source: _SourceText, node: ast.AST) -> str:
    return compact_text(source.segment(node) or _safe_unparse(node), 500)


def _slice_line_utf8(line: str, start: int, end: int | None) -> str:
    data = line.encode("utf-8")
    safe_start = max(0, min(start, len(data)))
    safe_end = len(data) if end is None else max(safe_start, min(end, len(data)))
    return data[safe_start:safe_end].decode("utf-8", "replace")


def _safe_unparse(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except (ValueError, TypeError):
        return node.__class__.__name__


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _call_names(node: ast.AST) -> list[str]:
    visitor = _CallNameVisitor()
    visitor.visit(node)
    return visitor.calls


class _CallNameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.calls: list[str] = []

    def visit_Call(self, node: ast.Call) -> None:
        name = _call_name(node.func)
        if name:
            self.calls.append(name)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return None

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return None

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


class _AssignedNameVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.names.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.names.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return None


def _argument_names(arguments: ast.arguments) -> set[str]:
    names: set[str] = set()
    for arg in (
        list(arguments.posonlyargs)
        + list(arguments.args)
        + list(arguments.kwonlyargs)
        + ([arguments.vararg] if arguments.vararg else [])
        + ([arguments.kwarg] if arguments.kwarg else [])
    ):
        names.add(arg.arg)
    return names


def _branch_behavior_source(stmts: list[ast.stmt]) -> str:
    return " ".join(
        _safe_unparse(_strip_nested_callable_bodies(statement))
        for statement in stmts
        if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    )


def _strip_nested_callable_bodies(statement: ast.stmt) -> ast.stmt:
    return cast(ast.stmt, _NestedCallableBodyStripper().visit(copy.deepcopy(statement)))


class _NestedCallableBodyStripper(ast.NodeTransformer):
    def visit_Lambda(self, node: ast.Lambda) -> ast.AST:
        return ast.copy_location(ast.Constant(value="lambda"), node)


def _loop_label(statement: ast.For | ast.AsyncFor | ast.While) -> str:
    if isinstance(statement, ast.While):
        return f"Repeat while {_safe_unparse(statement.test)}"
    return f"Process each {_safe_unparse(statement.target)}"


_ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "IntFlag", "Flag", "ReprEnum"}


def _harvest_enums(tree: ast.Module) -> dict[str, list[str]]:
    """Map each Enum class to its members (``X.MEMBER``) - the value universe."""
    enums: dict[str, list[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or not _is_enum_class(node):
            continue
        members: list[str] = []
        for statement in node.body:
            if isinstance(statement, ast.Assign):
                members.extend(
                    f"{node.name}.{target.id}"
                    for target in statement.targets
                    if isinstance(target, ast.Name) and _is_enum_member(target.id)
                )
            elif (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and _is_enum_member(statement.target.id)
            ):
                members.append(f"{node.name}.{statement.target.id}")
        if members:
            enums[node.name] = members
    return enums


def _is_enum_class(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if name in _ENUM_BASES or name.endswith("Enum"):
            return True
    return False


def _is_enum_member(name: str) -> bool:
    # Skip Enum directives and private attributes (e.g. _ignore_, __dunder__).
    return not name.startswith("_")


def _harvest_constants(tree: ast.Module) -> dict[str, bool]:
    """Module-level boolean constants (``FLAG = False``) - the data-flow fact a guard's
    always-true/false check needs."""
    constants: dict[str, bool] = {}
    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        elif isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Constant)
            and isinstance(value.value, bool)
        ):
            constants[target.id] = value.value
    return constants


def _module_name(relative: str) -> str:
    path = relative.removesuffix(".py").replace("/", ".")
    return path.removesuffix(".__init__")


def _import_map(
    tree: ast.Module,
    module_name: str,
    is_package: bool,
    is_submodule: Callable[[str, str], bool],
) -> dict[str, str]:
    """Map each imported alias to a ``module:symbol`` (or ``module:``) binding.

    ``from m import f`` => ``f`` -> ``m:f`` (binds a symbol); ``import m as a`` => ``a`` ->
    ``m:`` (binds a module). ``from pkg import sub`` where ``sub`` is a known first-party
    submodule binds the module (``pkg.sub:``), mirroring a TS namespace import, so the next
    attribute is read as the symbol. Relative imports resolve against the current module's
    package, accounting for ``__init__.py`` being its own package.
    """
    mapping: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    mapping[alias.asname] = f"{alias.name}:"
                else:
                    # `import pkg` / `import pkg.util` (no alias): the dotted name is itself
                    # a module; resolve_qualified longest-prefix-matches it.
                    mapping[alias.name] = f"{alias.name}:"
        elif isinstance(node, ast.ImportFrom):
            base = _relative_base(node.module, node.level, module_name, is_package)
            for alias in node.names:
                bound = alias.asname or alias.name
                if base and is_submodule(base, alias.name):
                    mapping[bound] = f"{base}.{alias.name}:"
                elif base:
                    mapping[bound] = f"{base}:{alias.name}"
                else:
                    mapping[bound] = alias.name
    return mapping


def _is_submodule(module_paths: dict[str, str], base: str, name: str) -> bool:
    """Whether ``base.name`` is a known first-party module in the discovered source set."""
    return f"{base}.{name}" in module_paths


def _dependency_paths_from_modules(
    import_map: dict[str, str], module_paths: dict[str, str]
) -> list[str]:
    dependencies: list[str] = []
    seen: set[str] = set()
    for binding in import_map.values():
        module, _, _ = binding.partition(":")
        relative = module_paths.get(module)
        if relative is None or relative in seen:
            continue
        dependencies.append(relative)
        seen.add(relative)
    return dependencies


def _relative_base(module: str | None, level: int, current_module: str, is_package: bool) -> str:
    if level == 0:
        return module or ""
    # An __init__ module *is* its own package, so a level-1 import stays put.
    drop = level - 1 if is_package else level
    parts = current_module.split(".")
    base_parts = parts[: len(parts) - drop] if drop <= len(parts) else []
    base = ".".join(base_parts)
    if module:
        return f"{base}.{module}" if base else module
    return base


def _is_test(relative: str, name: str) -> bool:
    parts = Path(relative).parts
    return name.startswith("test_") or "tests" in parts or Path(relative).name.startswith("test_")


def _branch_outcome(stmts: list[ast.stmt]) -> str:
    """Classify how control leaves a branch body: one of common.BRANCH_OUTCOMES."""
    meaningful = [stmt for stmt in stmts if not _is_noop(stmt)]
    if not meaningful:
        return EMPTY
    for stmt in meaningful:
        if isinstance(stmt, ast.Return):
            return RETURNS
        if isinstance(stmt, ast.Raise):
            return RAISES
        if isinstance(stmt, ast.Continue):
            return CONTINUES
        if isinstance(stmt, ast.Break):
            # break exits the enclosing loop/switch; control resumes after it.
            return FALLS_THROUGH
        if isinstance(stmt, ast.Try):
            try_outcome = _try_statement_outcome(stmt)
            if _terminates(try_outcome):
                return try_outcome
        if isinstance(stmt, ast.If) and stmt.orelse:
            then_outcome = _branch_outcome(stmt.body)
            else_outcome = _branch_outcome(stmt.orelse)
            if _terminates(then_outcome) and _terminates(else_outcome):
                return then_outcome if then_outcome == else_outcome else RETURNS
    return FALLS_THROUGH


def _try_statement_outcome(statement: ast.Try) -> str:
    final_outcome = _branch_outcome(statement.finalbody)
    if _terminates(final_outcome):
        return final_outcome

    success_outcome = _branch_outcome(statement.body)
    if success_outcome == FALLS_THROUGH and statement.orelse:
        success_outcome = _branch_outcome(statement.orelse)

    branch_outcomes = [
        success_outcome,
        *(_branch_outcome(handler.body) for handler in statement.handlers),
    ]
    if branch_outcomes and all(_terminates(outcome) for outcome in branch_outcomes):
        return (
            branch_outcomes[0]
            if all(outcome == branch_outcomes[0] for outcome in branch_outcomes)
            else RETURNS
        )
    return FALLS_THROUGH


def _terminates(outcome: str) -> bool:
    return outcome in {RETURNS, RAISES, CONTINUES}


def _is_noop(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    # Docstrings, bare string literals, and `...` placeholders carry no behavior.
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
