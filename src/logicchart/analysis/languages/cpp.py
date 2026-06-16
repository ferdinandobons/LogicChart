"""C++ language profile for the profile-driven tree-sitter analyzer."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import tree_sitter_cpp

from logicchart.analysis.languages._common import module_name, text
from logicchart.analysis.treesitter import (
    LanguageProfile,
    TreeSitterAnalyzer,
    TSDefinition,
)
from logicchart.config import LogicChartConfig


def _definitions(
    root: Any, source: bytes, relative: str, profile: LanguageProfile
) -> Iterable[TSDefinition]:
    yield from _walk(root, source, "")


def _walk(node: Any, source: bytes, owner: str) -> Iterable[TSDefinition]:
    if node.type in {"class_specifier", "struct_specifier", "namespace_definition"}:
        name = text(node.child_by_field_name("name"), source)
        next_owner = ".".join(part for part in (owner, name) if part)
        body = node.child_by_field_name("body")
        for child in body.children if body is not None else node.children:
            if child.is_named:
                yield from _walk(child, source, next_owner)
        return
    if node.type == "function_definition":
        name, explicit_owner = _qualified_function_name(
            node.child_by_field_name("declarator"), source
        )
        body = node.child_by_field_name("body")
        if name and body is not None:
            yield TSDefinition(name=name, node=node, body=body, owner=explicit_owner or owner)
        return
    for child in node.children:
        if child.is_named:
            yield from _walk(child, source, owner)


def _qualified_function_name(declarator: Any | None, source: bytes) -> tuple[str, str]:
    """Return (name, owner) from a possibly nested/qualified function declarator."""
    target = declarator
    while target is not None:
        inner = target.child_by_field_name("declarator")
        if inner is None:
            break
        target = inner
    identifiers = _identifier_texts(target, source)
    if not identifiers:
        identifiers = _identifier_texts(declarator, source)
    if not identifiers:
        return "", ""
    return identifiers[-1], ".".join(identifiers[:-1])


def _identifier_texts(node: Any | None, source: bytes) -> list[str]:
    if node is None:
        return []
    values: list[str] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if current.type in {"identifier", "field_identifier", "type_identifier", "destructor_name"}:
            values.append(text(current, source).lstrip("~"))
            continue
        stack.extend(reversed(current.children))
    return [value for value in values if value]


def _classify(
    definition: TSDefinition, relative: str, source: str, config: LogicChartConfig
) -> tuple[str, str, bool]:
    owner_prefix = f"{definition.owner}." if definition.owner else ""
    override = config.entrypoint_override(f"{relative}:{owner_prefix}{definition.name}")
    if definition.name == "main" and not definition.owner:
        return "cpp", "main", override if override is not None else True
    public = config.include_public_functions and not _has_static_storage(definition.node)
    return (
        "generic",
        "method" if definition.owner else "function",
        (override if override is not None else public),
    )


def _has_static_storage(node: Any) -> bool:
    return any(
        child.type == "storage_class_specifier" and child.text.decode() == "static"
        for child in node.children
    )


def _is_test(relative: str, name: str) -> bool:
    lowered = relative.lower()
    segments = lowered.split("/")
    filename = segments[-1]
    return (
        any(segment in {"test", "tests"} for segment in segments[:-1])
        or filename.startswith("test_")
        or filename.endswith(
            (
                "_test.cc",
                "_test.cpp",
                "_test.cxx",
                "_test.hh",
                "_test.hpp",
                "_test.hxx",
            )
        )
    )


CPP_PROFILE = LanguageProfile(
    language="cpp",
    grammar_loader=tree_sitter_cpp.language,
    function_types=frozenset({"function_definition"}),
    definitions=_definitions,
    classify=_classify,
    is_test=_is_test,
    module_name=module_name,
    block_types=frozenset({"compound_statement"}),
    switch_types=frozenset({"switch_statement"}),
    switch_value_field="condition",
    case_types=frozenset({"case_statement"}),
    default_when_no_value=True,
    case_fall_through=True,
    loop_types=frozenset(
        {"for_statement", "while_statement", "do_statement", "range_based_for_statement"}
    ),
    throw_types=frozenset({"throw_statement"}),
    call_types=frozenset({"call_expression"}),
    try_type="try_statement",
    catch_types=frozenset({"catch_clause"}),
    assignment_types=frozenset({"declaration"}),
)


def build_analyzer(root: Path, config: LogicChartConfig) -> TreeSitterAnalyzer:
    return TreeSitterAnalyzer(root, config, CPP_PROFILE)
