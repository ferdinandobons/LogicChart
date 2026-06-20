import ast
from pathlib import Path

import pytest

from logicchart.analysis.python import (
    PythonAnalyzer,
    _dependency_paths_from_modules,
    _import_map,
)
from logicchart.config import LogicChartConfig
from logicchart.model import NodeKind


def test_fastapi_route_builds_functional_decisions(tmp_path: Path) -> None:
    source = tmp_path / "api.py"
    source.write_text(
        """
from fastapi import FastAPI, HTTPException

app = FastAPI()

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    user = await load_user(user_id)
    if user.status == UserStatus.SUSPENDED:
        raise HTTPException(403)
    if user is None:
        return {"error": "missing"}
    return user
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)

    assert len(analysis.flows) == 1
    flow = analysis.flows[0]
    assert flow.is_entrypoint
    assert flow.framework == "fastapi"
    assert flow.entry_kind == "route"
    assert any(node.kind is NodeKind.DECISION for node in flow.nodes)
    assert any(node.kind is NodeKind.ERROR for node in flow.nodes)


def test_import_map_uses_module_index_without_filesystem_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tree = ast.parse("from pkg import util\nfrom pkg import missing\n")

    def fail_is_file(self: Path) -> bool:
        raise AssertionError("import mapping must not probe the filesystem per import")

    monkeypatch.setattr(Path, "is_file", fail_is_file)

    mapping = _import_map(
        tree,
        "pkg.service",
        False,
        lambda base, name: f"{base}.{name}" in {"pkg.util"},
    )

    assert mapping["util"] == "pkg.util:"
    assert mapping["missing"] == "pkg:missing"
    assert _dependency_paths_from_modules(
        mapping,
        {"pkg": "pkg/__init__.py", "pkg.util": "pkg/util.py"},
    ) == ["pkg/util.py", "pkg/__init__.py"]


def test_python_internal_call_is_recorded(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def load_user(user_id: str):
    return repository.fetch(user_id)

def get_profile(user_id: str):
    user = load_user(user_id)
    return user.profile
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    profile = next(flow for flow in analysis.flows if flow.name == "get_profile")

    call_node = next(node for node in profile.nodes if node.kind is NodeKind.CALL)
    assert "load_user" in call_node.metadata["calls"]


def test_python_source_snippets_do_not_resplit_large_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "large_service.py"
    source.write_text(
        "\n".join(["# filler"] * 5000)
        + """

def process(order):
    if order.status:
        return handle(order)
    return reject(order)
""",
        encoding="utf-8",
    )

    def fail_get_source_segment(source: str, node: ast.AST) -> str:
        raise AssertionError("PythonAnalyzer must not call ast.get_source_segment")

    monkeypatch.setattr(ast, "get_source_segment", fail_get_source_segment)

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = analysis.flows[0]

    assert any(node.detail == "order.status" for node in flow.nodes)
    assert any(node.detail == "return handle(order)" for node in flow.nodes)


def test_local_function_body_does_not_pollute_outer_flow(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(order):
    def helper():
        if order.status == OrderStatus.OPEN:
            return persist(order)
        return reject(order)
    return ok(order)
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = {node.label for node in flow.nodes}

    assert "Define local function helper" in labels
    assert "Call ok()" in labels
    assert "order.status == OrderStatus.OPEN" not in labels
    assert "Call persist()" not in labels
    assert "Call reject()" not in labels

    call_names = {
        call
        for node in flow.nodes
        for call in node.metadata.get("calls", [])
        if isinstance(call, str)
    }
    assert call_names == {"ok"}


def test_local_function_body_does_not_make_parent_if_functional(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(flag):
    if flag:
        def helper():
            return persist()
    return done()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = {node.label for node in flow.nodes}

    assert "Handle internal condition: flag" in labels
    assert "flag" not in labels
    assert "Call persist()" not in labels
    assert "Call done()" in labels


def test_local_lambda_body_does_not_make_parent_if_functional(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(flag, order):
    if flag:
        callback = lambda: validate(order)
    return done()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = {node.label for node in flow.nodes}

    assert "Handle internal condition: flag" in labels
    assert "flag" not in labels
    assert "Call validate()" not in labels
    assert "Call done()" in labels


def test_local_function_assignment_does_not_shadow_parent_constants(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
FLAG = False

def process():
    def helper():
        FLAG = True
        return FLAG
    return ready()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")

    assert "shadows_constants" not in flow.metadata


def test_try_else_body_is_modeled_on_success_path(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(order):
    try:
        validate(order)
    except ValidationError:
        return reject(order)
    else:
        persist(order)
    return ok(order)
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = [node.label for node in flow.nodes]

    assert "Call validate()" in labels
    assert "Call persist()" in labels
    assert "Call ok()" in labels
    assert "Return ok(order)" in labels
    assert "Return reject(order)" in labels

    by_label = {node.label: node.id for node in flow.nodes}
    assert any(
        edge.source == by_label["Call validate()"] and edge.target == by_label["Call persist()"]
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call persist()"] and edge.target == by_label["Call ok()"]
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call ok()"] and edge.target == by_label["Return ok(order)"]
        for edge in flow.edges
    )


def test_try_else_is_skipped_when_body_returns(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(order):
    try:
        return ok(order)
    except ValidationError:
        return reject(order)
    else:
        persist(order)
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")

    assert "Call persist()" not in {node.label for node in flow.nodes}


def test_loop_body_decision_is_modeled_before_post_loop(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(orders):
    for order in orders:
        if order.status == OrderStatus.OPEN:
            approve(order)
    return done()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = [node.label for node in flow.nodes]

    assert "Process each order" in labels
    assert "order.status == OrderStatus.OPEN" in labels
    assert "Call approve()" in labels
    assert "Call done()" in labels
    assert "Return done()" in labels

    by_label = {node.label: node.id for node in flow.nodes}
    assert any(
        edge.source == by_label["Process each order"]
        and edge.target == by_label["order.status == OrderStatus.OPEN"]
        and edge.label == "Iteration"
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Process each order"]
        and edge.target == by_label["Call done()"]
        and edge.label == "Done"
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call approve()"] and edge.target == by_label["Call done()"]
        for edge in flow.edges
    )


def test_loop_else_body_is_modeled_on_natural_completion(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(items):
    for item in items:
        inspect(item)
    else:
        finalize()
    return done()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = [node.label for node in flow.nodes]

    assert "Process each item" in labels
    assert "Call inspect()" in labels
    assert "Call finalize()" in labels
    assert "Call done()" in labels

    by_label = {node.label: node.id for node in flow.nodes}
    assert any(
        edge.source == by_label["Process each item"]
        and edge.target == by_label["Call inspect()"]
        and edge.label == "Iteration"
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Process each item"]
        and edge.target == by_label["Call finalize()"]
        and edge.label == "Done"
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call inspect()"] and edge.target == by_label["Call finalize()"]
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call finalize()"] and edge.target == by_label["Call done()"]
        for edge in flow.edges
    )


def test_loop_continue_does_not_flow_to_post_loop(tmp_path: Path) -> None:
    source = tmp_path / "service.py"
    source.write_text(
        """
def process(items):
    for item in items:
        if item.status == Status.SKIP:
            continue
        handle(item)
    return done()
""",
        encoding="utf-8",
    )

    analysis = PythonAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "process")
    labels = [node.label for node in flow.nodes]

    assert "Continue loop" in labels
    assert "Call handle()" in labels
    assert "Call done()" in labels

    by_label = {node.label: node.id for node in flow.nodes}
    assert (
        any(
            edge.source == by_label["Continue loop"] and edge.target == by_label["Call done()"]
            for edge in flow.edges
        )
        is False
    )
    assert any(
        edge.source == by_label["Call handle()"] and edge.target == by_label["Call done()"]
        for edge in flow.edges
    )
