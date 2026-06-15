from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from logicchart.analysis.common import (
    MATCH,
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
from logicchart.model import (
    Evidence,
    FileAnalysis,
    Finding,
    Flow,
    NodeKind,
    SourceLocation,
)
from logicchart.util import compact_text, file_sha256, relpath, stable_id

FASTAPI_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
CLI_DECORATORS = {"command", "callback"}
HANDLER_PREFIXES = ("handle_", "on_", "process_")


class PythonAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig) -> None:
        self.root = root
        self.config = config

    def analyze(self, path: Path) -> FileAnalysis:
        source = path.read_text(encoding="utf-8")
        relative = relpath(path, self.root)
        tree = ast.parse(source, filename=relative)
        module_name = _module_name(relative)
        flows: list[Flow] = []
        findings: list[Finding] = []

        for definition, owner in _definitions(tree):
            flow = self._analyze_definition(
                definition=definition,
                owner=owner,
                source=source,
                relative=relative,
                module_name=module_name,
                findings=findings,
            )
            flows.append(flow)

        is_package = Path(relative).name == "__init__.py"
        import_map = _import_map(tree, module_name, is_package)
        for flow in flows:
            attach_qualified_calls(flow, import_map, module_name)
            tag_call_effects(flow)

        return FileAnalysis(
            path=relative,
            language="python",
            sha256=file_sha256(path),
            enums=_harvest_enums(tree),
            constants=_harvest_constants(tree),
            flows=flows,
            findings=findings,
        )

    def _analyze_definition(
        self,
        definition: ast.FunctionDef | ast.AsyncFunctionDef,
        owner: str,
        source: str,
        relative: str,
        module_name: str,
        findings: list[Finding],
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
            findings,
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
        findings.extend(single_flow_findings(flow))
        return flow

    def _walk_statements(
        self,
        statements: list[ast.stmt],
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: str,
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
                        _source_segment(source, dead),
                    )
                )
                break
            if isinstance(statement, ast.If):
                endpoints = self._walk_if(statement, endpoints, builder, findings, source, relative)
            elif isinstance(statement, ast.Match):
                endpoints = self._walk_match(
                    statement, endpoints, builder, findings, source, relative
                )
            elif isinstance(statement, ast.Try):
                endpoints = self._walk_try(
                    statement, endpoints, builder, findings, source, relative
                )
            elif isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                label = _loop_label(statement)
                node = builder.add_node(
                    NodeKind.ACTION,
                    label,
                    _location(relative, statement),
                    endpoints,
                    detail=_source_segment(source, statement),
                    evidence=Evidence.INFERRED,
                )
                endpoints = [PendingEdge(node.id)]
            elif isinstance(statement, ast.Return):
                value = _safe_unparse(statement.value) if statement.value else ""
                calls = [
                    _call_name(item.func)
                    for item in ast.walk(statement)
                    if isinstance(item, ast.Call)
                ]
                calls = [item for item in calls if item]
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

    def _walk_if(
        self,
        statement: ast.If,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: str,
        relative: str,
    ) -> list[PendingEdge]:
        condition = _safe_unparse(statement.test)
        branch_source = " ".join(_source_segment(source, item) for item in statement.body)
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
            branch("Yes", _branch_outcome(statement.body)),
            branch(
                "No",
                _branch_outcome(statement.orelse) if statement.orelse else "falls_through",
                implicit=not statement.orelse,
            ),
        ]
        yes_endpoints = self._walk_statements(
            statement.body,
            [PendingEdge(node.id, "Yes")],
            builder,
            findings,
            source,
            relative,
        )
        if statement.orelse:
            no_endpoints = self._walk_statements(
                statement.orelse,
                [PendingEdge(node.id, "No")],
                builder,
                findings,
                source,
                relative,
            )
        else:
            no_endpoints = [PendingEdge(node.id, "No")]
        return yes_endpoints + no_endpoints

    def _walk_match(
        self,
        statement: ast.Match,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: str,
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
            is_default = pattern == "_"
            has_default = has_default or is_default
            if not is_default:
                values.append(pattern)
            branches.append(branch(pattern, _branch_outcome(case.body)))
            endpoints.extend(
                self._walk_statements(
                    case.body,
                    [PendingEdge(node.id, pattern)],
                    builder,
                    findings,
                    source,
                    relative,
                )
            )
        node.metadata["values"] = sorted(set(values))
        node.metadata["value_namespace"] = value_namespace(sorted(set(values)))
        if not has_default:
            branches.append(branch("_", "falls_through", implicit=True))
            # An unmatched value falls through to whatever follows the match.
            endpoints.append(PendingEdge(node.id, "_"))
        node.metadata["branches"] = branches
        return endpoints

    def _walk_try(
        self,
        statement: ast.Try,
        incoming: list[PendingEdge],
        builder: FlowBuilder,
        findings: list[Finding],
        source: str,
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
        branches: list[dict[str, Any]] = [branch("Success", _branch_outcome(statement.body))]
        endpoints = self._walk_statements(
            statement.body,
            [PendingEdge(node.id, "Success")],
            builder,
            findings,
            source,
            relative,
        )
        for handler in statement.handlers:
            error_name = _safe_unparse(handler.type) if handler.type else "Any error"
            branches.append(branch(error_name, _branch_outcome(handler.body)))
            endpoints.extend(
                self._walk_statements(
                    handler.body,
                    [PendingEdge(node.id, error_name)],
                    builder,
                    findings,
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
                statement.finalbody, finally_incoming, builder, findings, source, relative
            )
            if body_terminated:
                # The try/handlers already returned/raised; once finally runs that
                # terminator resumes, so anything after the try is unreachable.
                endpoints = []
        return endpoints


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
    calls = [_call_name(item.func) for item in ast.walk(statement) if isinstance(item, ast.Call)]
    calls = [item for item in calls if item]
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


def _source_segment(source: str, node: ast.AST) -> str:
    return compact_text(ast.get_source_segment(source, node) or _safe_unparse(node), 500)


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


def _loop_label(statement: ast.For | ast.AsyncFor | ast.While) -> str:
    if isinstance(statement, ast.While):
        return f"Repeat while {_safe_unparse(statement.test)}"
    return f"Process each {_safe_unparse(statement.target)}"


_ENUM_BASES = {"Enum", "IntEnum", "StrEnum", "IntFlag", "Flag", "ReprEnum"}


def _harvest_enums(tree: ast.Module) -> dict[str, list[str]]:
    """Map each Enum class to its members (``X.MEMBER``) — the value universe."""
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
    """Module-level boolean constants (``FLAG = False``) — the smallest data-flow fact
    a guard's always-true/false check needs."""
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


def _import_map(tree: ast.Module, module_name: str, is_package: bool) -> dict[str, str]:
    """Map each imported alias to a ``module:symbol`` (or ``module:``) binding.

    ``from m import f`` -> ``f`` => ``m:f`` (binds a symbol); ``import m as a`` ->
    ``a`` => ``m:`` (binds a module). Relative imports resolve against the current
    module's package, accounting for ``__init__.py`` being its own package.
    """
    mapping: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    mapping[alias.asname] = f"{alias.name}:"
                elif "." not in alias.name:
                    mapping[alias.name] = f"{alias.name}:"
        elif isinstance(node, ast.ImportFrom):
            base = _relative_base(node.module, node.level, module_name, is_package)
            for alias in node.names:
                bound = alias.asname or alias.name
                mapping[bound] = f"{base}:{alias.name}" if base else alias.name
    return mapping


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
        return "empty"
    for stmt in meaningful:
        if isinstance(stmt, ast.Return):
            return "returns"
        if isinstance(stmt, ast.Raise):
            return "raises"
        if isinstance(stmt, ast.Continue):
            return "continues"
        if isinstance(stmt, ast.Break):
            # break exits the enclosing loop/switch; control resumes after it.
            return "falls_through"
        if isinstance(stmt, ast.If) and stmt.orelse:
            then_outcome = _branch_outcome(stmt.body)
            else_outcome = _branch_outcome(stmt.orelse)
            if _terminates(then_outcome) and _terminates(else_outcome):
                return then_outcome if then_outcome == else_outcome else "returns"
    return "falls_through"


def _terminates(outcome: str) -> bool:
    return outcome in {"returns", "raises", "continues"}


def _is_noop(stmt: ast.stmt) -> bool:
    if isinstance(stmt, ast.Pass):
        return True
    # Docstrings, bare string literals, and `...` placeholders carry no behavior.
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
