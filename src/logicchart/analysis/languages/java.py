"""Java language profile for the profile-driven tree-sitter analyzer."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import tree_sitter_java

from logicchart.analysis.common import DEFAULT as DEFAULT_LABEL
from logicchart.analysis.treesitter import (
    CaseInfo,
    LanguageProfile,
    TreeSitterAnalyzer,
    TSDefinition,
)
from logicchart.config import LogicChartConfig

_CONTAINERS = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
}
_METHODS = {"method_declaration", "constructor_declaration"}
_ROUTE_ANNOTATIONS = (
    "@GetMapping",
    "@PostMapping",
    "@PutMapping",
    "@DeleteMapping",
    "@PatchMapping",
    "@RequestMapping",
)


def _text(node: Any | None, source: bytes) -> str:
    if node is None:
        return ""
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _named(node: Any | None) -> Iterable[Any]:
    if node is None:
        return ()
    return (child for child in node.children if child.is_named)


def _definitions(
    root: Any, source: bytes, relative: str, profile: LanguageProfile
) -> Iterable[TSDefinition]:
    yield from _walk(root, source, owner="")


def _walk(node: Any, source: bytes, owner: str) -> Iterable[TSDefinition]:
    if node.type in _CONTAINERS:
        name = _text(node.child_by_field_name("name"), source) or owner
        for child in _named(node.child_by_field_name("body")):
            yield from _walk(child, source, name)
        return
    if node.type in _METHODS:
        name = _text(node.child_by_field_name("name"), source)
        body = node.child_by_field_name("body")
        if name and body is not None:
            yield TSDefinition(name=name, node=node, body=body, owner=owner)
        return
    for child in _named(node):
        yield from _walk(child, source, owner)


def _modifiers(node: Any, source: bytes) -> str:
    for child in node.children:
        if child.type == "modifiers":
            return _text(child, source)
    return ""


def _classify(
    definition: TSDefinition, relative: str, source: str, config: LogicChartConfig
) -> tuple[str, str, bool]:
    override = config.entrypoint_override(f"{relative}:{definition.owner}.{definition.name}")
    modifiers = _modifiers(definition.node, source.encode("utf-8"))
    if definition.name == "main" and "static" in modifiers:
        return "java", "main", override if override is not None else True
    if any(annotation in modifiers for annotation in _ROUTE_ANNOTATIONS):
        return "spring", "route", override if override is not None else True
    public = config.include_public_functions and "public" in modifiers
    return "generic", "method", override if override is not None else public


def _is_test(relative: str, name: str) -> bool:
    return (
        "/test/" in relative
        or relative.endswith(("Test.java", "Tests.java", "IT.java"))
        or name.startswith("test")
    )


def _module_name(relative: str) -> str:
    return Path(relative).parent.as_posix().replace("/", ".").strip(".")


def _switch_cases(switch_node: Any, source: bytes, profile: LanguageProfile) -> list[CaseInfo]:
    body = switch_node.child_by_field_name("body")
    cases: list[CaseInfo] = []
    for group in _named(body):
        if group.type != "switch_block_statement_group":
            continue
        labels = [c for c in _named(group) if c.type == "switch_label"]
        statements = [c for c in _named(group) if c.type != "switch_label"]
        values: list[str] = []
        is_default = False
        for label in labels:
            value = next(iter(_named(label)), None)
            if value is None:
                is_default = True
            else:
                values.append(_text(value, source))
        if is_default and not values:
            cases.append(CaseInfo(DEFAULT_LABEL, True, [], statements))
        else:
            cases.append(CaseInfo(", ".join(values) or "case", False, values, statements))
    return cases


def _call_name(call: Any, source: bytes) -> str:
    if call.type == "method_invocation":
        return _text(call.child_by_field_name("name"), source)
    if call.type == "object_creation_expression":
        return _text(call.child_by_field_name("type"), source)
    return ""


JAVA_PROFILE = LanguageProfile(
    language="java",
    grammar_loader=tree_sitter_java.language,
    function_types=frozenset(_METHODS),
    definitions=_definitions,
    classify=_classify,
    is_test=_is_test,
    module_name=_module_name,
    switch_types=frozenset({"switch_expression"}),
    switch_value_field="condition",
    switch_cases=_switch_cases,
    loop_types=frozenset(
        {"for_statement", "enhanced_for_statement", "while_statement", "do_statement"}
    ),
    throw_types=frozenset({"throw_statement"}),
    call_types=frozenset({"method_invocation", "object_creation_expression"}),
    call_name=_call_name,
    try_type="try_statement",
    catch_types=frozenset({"catch_clause"}),
    finally_types=frozenset({"finally_clause"}),
    assignment_types=frozenset({"local_variable_declaration", "assignment_expression"}),
    nested_def_types=frozenset({"lambda_expression"}),
)


def build_analyzer(root: Path, config: LogicChartConfig) -> TreeSitterAnalyzer:
    return TreeSitterAnalyzer(root, config, JAVA_PROFILE)
