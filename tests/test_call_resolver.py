"""Stage 3 import-aware call resolution with confidence and kept candidates."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import Flow, FlowNode, NodeKind


def _call_node(flow: Flow) -> FlowNode:
    return next(node for node in flow.nodes if node.kind is NodeKind.CALL)


def test_python_import_alias_resolves_with_high_confidence(tmp_path: Path) -> None:
    (tmp_path / "helpers.py").write_text("def load_account(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "routes.py").write_text(
        "from helpers import load_account as fetch\n\ndef handler(req):\n    return fetch(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handler = next(f for f in model.flows if f.name == "handler")
    target = next(f for f in model.flows if f.name == "load_account")
    call = _call_node(handler)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id
    assert target.id in handler.calls


def test_python_ambiguous_candidates_are_kept_not_dropped(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def process(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def process(y):\n    return y\n", encoding="utf-8")
    (tmp_path / "caller.py").write_text(
        "def run(obj):\n    return obj.process()\n", encoding="utf-8"
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    call = _call_node(run)

    assert call.metadata["link_confidence"] == "low"
    assert len(call.metadata["call_candidates"]) == 2
    # Ambiguous resolution does not commit to a single edge.
    assert "target_flow" not in call.metadata
    assert run.calls == []


def test_typescript_named_import_resolves_across_files(tmp_path: Path) -> None:
    (tmp_path / "users.ts").write_text(
        "export function loadUser(id: string) {\n  return id;\n}\n", encoding="utf-8"
    )
    (tmp_path / "route.ts").write_text(
        'import { loadUser } from "./users";\n\n'
        "export async function GET(req: Request) {\n  return loadUser(req);\n}\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    get = next(f for f in model.flows if f.name == "GET")
    target = next(f for f in model.flows if f.name == "loadUser")
    call = _call_node(get)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id


def test_module_function_not_confused_with_class_method(tmp_path: Path) -> None:
    # A package function `pkg.sub:helper` and a method `pkg:sub.helper` collapse to
    # the same dotted form; the boundary-preserving resolver must keep them apart.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text(
        "class sub:\n    def helper(self):\n        return 1\n", encoding="utf-8"
    )
    (pkg / "sub.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")
    (pkg / "caller.py").write_text(
        "from pkg.sub import helper\n\ndef run(req):\n    return helper(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    func = next(f for f in model.flows if f.symbol == "pkg.sub:helper")
    method = next(f for f in model.flows if f.symbol == "pkg:sub.helper")
    call = _call_node(run)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == func.id
    assert method.id not in run.calls


def test_relative_import_in_package_init_makes_no_false_edge(tmp_path: Path) -> None:
    # A decoy pkg/helper.py and the real pkg/sub/helper.py both define do_work;
    # pkg/sub/__init__.py imports `from . import helper`. The wrong-package decoy
    # must never become a committed high-confidence target.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helper.py").write_text("def do_work(x):\n    return x\n", encoding="utf-8")
    sub = pkg / "sub"
    sub.mkdir()
    (sub / "helper.py").write_text("def do_work(y):\n    return y\n", encoding="utf-8")
    (sub / "__init__.py").write_text(
        "from . import helper\n\ndef run(req):\n    return helper.do_work(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    decoy = next(f for f in model.flows if f.symbol == "pkg.helper:do_work")
    target = next(f for f in model.flows if f.symbol == "pkg.sub.helper:do_work")
    call = _call_node(run)

    # `from . import helper` binds the submodule, so `helper.do_work` resolves to the
    # real same-package target at high confidence - not the wrong-package decoy.
    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id
    assert call.metadata.get("target_flow") != decoy.id
    assert decoy.id not in run.calls


def test_submodule_import_binds_module_not_symbol(tmp_path: Path) -> None:
    # `from . import util` where util.py is a sibling submodule: a unique leaf name
    # must resolve at HIGH confidence (was medium short-name fallback before the fix).
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "util.py").write_text("def persist_unique(x):\n    return x\n", encoding="utf-8")
    (pkg / "core.py").write_text(
        "from . import util\n\ndef run(req):\n    return util.persist_unique(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    target = next(f for f in model.flows if f.symbol == "pkg.util:persist_unique")
    call = _call_node(run)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id
    assert target.id in run.calls


def test_dotted_import_without_alias_resolves(tmp_path: Path) -> None:
    # `import pkg.util` (dotted, no `as`): the longest-prefix resolver links
    # `pkg.util.persist_unique` to the module symbol.
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "util.py").write_text("def persist_unique(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "import pkg.util\n\ndef run(req):\n    return pkg.util.persist_unique(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    target = next(f for f in model.flows if f.symbol == "pkg.util:persist_unique")
    call = _call_node(run)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id


def test_relative_import_resolves_in_regular_module(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helpers.py").write_text("def fetch(x):\n    return x\n", encoding="utf-8")
    (pkg / "routes.py").write_text(
        "from .helpers import fetch\n\ndef handler(req):\n    return fetch(req)\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handler = next(f for f in model.flows if f.name == "handler")
    target = next(f for f in model.flows if f.symbol == "pkg.helpers:fetch")
    call = _call_node(handler)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id


def test_short_name_fallback_is_medium_confidence(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def run(obj):\n    return obj.helper()\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def helper(x):\n    return x\n", encoding="utf-8")

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    target = next(f for f in model.flows if f.name == "helper")
    call = _call_node(run)

    assert call.metadata["link_confidence"] == "medium"
    assert call.metadata["target_flow"] == target.id


def test_unresolvable_call_records_no_link(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def run(req):\n    return external_thing(req)\n", encoding="utf-8"
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    run = next(f for f in model.flows if f.name == "run")
    call = _call_node(run)

    assert "link_confidence" not in call.metadata
    assert run.calls == []


def test_typescript_default_import_resolves_via_marker(tmp_path: Path) -> None:
    (tmp_path / "widget.ts").write_text(
        "export default function renderWidget(props: unknown) {\n  return props;\n}\n",
        encoding="utf-8",
    )
    (tmp_path / "page.tsx").write_text(
        'import Widget from "./widget";\n\n'
        "export default function Page() {\n  return Widget(null);\n}\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    page = next(f for f in model.flows if f.name == "Page")
    target = next(f for f in model.flows if f.name == "renderWidget")
    call = _call_node(page)

    assert call.metadata["link_confidence"] == "high"
    assert call.metadata["target_flow"] == target.id
