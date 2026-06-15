"""Terraform / HCL analyzer.

Terraform is declarative, not control flow: it describes resources, modules, data
sources, variables, and outputs, wired by references (``aws_vpc.main.id``) and
``depends_on``. This analyzer maps each block to a flow and each reference to a call
edge, so the same IR carries a resource dependency graph - the model can then show the
whole infrastructure, a scope of it, or one resource's dependencies.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import tree_sitter_hcl
from tree_sitter import Language, Parser

from logicchart.analysis.common import FlowBuilder, PendingEdge, annotate_reachability
from logicchart.config import LogicChartConfig
from logicchart.model import Evidence, FileAnalysis, Flow, NodeKind, SourceLocation
from logicchart.util import file_sha256, relpath, stable_id

# Reference roots that are not edges to another block (meta-arguments and built-ins).
_META_ROOTS = {"each", "count", "self", "path", "terraform", "local", "locals"}
# Block types that become entry points (they create or compose infrastructure).
_ENTRYPOINT_BLOCKS = {"resource", "module"}


class TerraformAnalyzer:
    def __init__(self, root: Path, config: LogicChartConfig) -> None:
        self.root = root
        self.config = config
        self.parser = Parser(Language(tree_sitter_hcl.language()))

    def analyze(self, path: Path) -> FileAnalysis:
        source = path.read_bytes()
        relative = relpath(path, self.root)
        tree = self.parser.parse(source)
        module = _module_name(relative)
        flows = [
            flow
            for block in _blocks(tree.root_node)
            if (flow := self._block_flow(block, source, relative, module)) is not None
        ]
        return FileAnalysis(
            path=relative,
            language="terraform",
            sha256=file_sha256(path),
            flows=flows,
            findings=[],
        )

    def _block_flow(self, block: Any, source: bytes, relative: str, module: str) -> Flow | None:
        block_type = _text(block.children[0], source) if block.children else ""
        labels = [_text(s, source) for s in block.children if s.type == "string_lit"]
        identity = _block_identity(block_type, labels)
        if identity is None:
            return None
        block_symbol, entry_kind = identity
        symbol = f"{module}:{block_symbol}"
        location = _location(relative, block)
        flow = Flow(
            id=f"flow-{stable_id(symbol)}",
            name=block_symbol,
            symbol=symbol,
            language="terraform",
            framework="terraform",
            entry_kind=entry_kind,
            is_entrypoint=block_type in _ENTRYPOINT_BLOCKS,
            location=location,
            metadata={"test": False, "block_type": block_type},
        )
        builder = FlowBuilder(flow)
        entry = builder.add_node(
            NodeKind.ENTRY,
            f"{entry_kind}: {block_symbol}",
            location,
            [],
            metadata={"symbol": symbol},
        )
        for reference in _references(block, source):
            node = builder.add_node(
                NodeKind.CALL,
                f"Depends on {reference}",
                location,
                [PendingEdge(entry.id)],
                evidence=Evidence.VERIFIED,
                metadata={
                    "calls": [reference.split(".")[-1]],
                    "qualified_calls": [f"{module}:{reference}"],
                },
            )
            node.metadata.setdefault("effects", [])
        annotate_reachability(flow)
        return flow


def _block_identity(block_type: str, labels: list[str]) -> tuple[str, str] | None:
    if block_type == "resource" and len(labels) >= 2:
        return f"{labels[0]}.{labels[1]}", "resource"
    if block_type == "data" and len(labels) >= 2:
        return f"data.{labels[0]}.{labels[1]}", "data"
    if block_type == "module" and labels:
        return f"module.{labels[0]}", "module"
    if block_type == "variable" and labels:
        return f"var.{labels[0]}", "variable"
    if block_type == "output" and labels:
        return f"output.{labels[0]}", "output"
    if block_type == "provider" and labels:
        return f"provider.{labels[0]}", "provider"
    return None


def _references(block: Any, source: bytes) -> list[str]:
    references: dict[str, None] = {}
    for node in _descendants(block):
        if node.type != "expression":
            continue
        named = [child for child in node.children if child.is_named]
        if not named or named[0].type != "variable_expr":
            continue
        root = _text(named[0], source)
        attrs = [
            _text(next((g for g in child.children if g.is_named), None), source)
            for child in named[1:]
            if child.type == "get_attr"
        ]
        reference = _reference_symbol(root, attrs)
        if reference is not None:
            references[reference] = None
    return list(references)


def _reference_symbol(root: str, attrs: list[str]) -> str | None:
    if root in _META_ROOTS or not attrs:
        return None
    if root == "module":
        return f"module.{attrs[0]}"
    if root == "var":
        return f"var.{attrs[0]}"
    if root == "data" and len(attrs) >= 2:
        return f"data.{attrs[0]}.{attrs[1]}"
    if root == "output":
        return f"output.{attrs[0]}"
    # Otherwise the root is a resource type, e.g. aws_vpc.main.
    return f"{root}.{attrs[0]}"


def _blocks(root: Any) -> Iterable[Any]:
    body = next((c for c in root.children if c.type == "body"), None)
    if body is None:
        return ()
    return (child for child in body.children if child.type == "block")


def _descendants(node: Any) -> Iterable[Any]:
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(current.children)


def _text(node: Any | None, source: bytes) -> str:
    if node is None:
        return ""
    text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
    return text.strip().strip('"')


def _location(relative: str, node: Any) -> SourceLocation:
    return SourceLocation(relative, int(node.start_point.row) + 1, int(node.end_point.row) + 1)


def _module_name(relative: str) -> str:
    return Path(relative).parent.as_posix().replace("/", ".").strip(".")


def build_analyzer(root: Path, config: LogicChartConfig) -> TerraformAnalyzer:
    return TerraformAnalyzer(root, config)
