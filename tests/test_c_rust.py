"""C, C++, and Rust support via the profile-driven engine (Stage C)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.common import DEFAULT
from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel

_C = """int handle(int status) {
  if (status == 1) { return 0; }
  switch (status) { case 1: return 1; case 2: return 2; }
  return persist(status);
}
static int persist(int status) { return store(status); }
"""

_CPP = """class Router {
public:
  int handle(Status status) {
    if (status == Status::Active) { return 1; }
    switch (status) {
      case Status::Active: return 10;
      case Status::Suspended: return 20;
    }
    return fallback(status);
  }
};

static int fallback(Status status) { return 0; }
int main() { return Router().handle(Status::Active); }
"""

_RUST = """pub fn handle(s: Status) -> i32 {
  if s == Status::Active { return 1; }
  match s {
    Status::Active => 1,
    Status::Suspended => 2,
  }
}
fn persist(s: Status) -> i32 { store(s) }
"""


def _analyze(tmp_path: Path, name: str, content: str) -> ProjectModel:
    src = tmp_path / "src"
    src.mkdir()
    (src / name).write_text(content, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _flow(model: ProjectModel, name: str):
    return next(f for f in model.flows if f.name == name)


def test_c_if_switch_static_and_calls(tmp_path: Path) -> None:
    model = _analyze(tmp_path, "handler.c", _C)
    by_name = {f.name: f for f in model.flows}
    assert by_name["handle"].language == "c"
    # a static function is file-local, not an entry point
    assert by_name["handle"].is_entrypoint and not by_name["persist"].is_entrypoint
    handle = _flow(model, "handle")
    labels = {n.label for n in handle.nodes if n.kind is NodeKind.DECISION}
    assert "status == 1" in labels and "Switch on status" in labels
    assert "missing_branch" in {f.kind for f in model.findings if f.flow_id == handle.id}
    assert _flow(model, "persist").id in handle.calls


def test_cpp_class_methods_switch_static_and_main(tmp_path: Path) -> None:
    model = _analyze(tmp_path, "router.cpp", _CPP)
    by_name = {f.name: f for f in model.flows}
    assert {"Router.handle", "fallback", "main"} <= set(by_name)
    assert all(f.language == "cpp" for f in model.flows)
    assert by_name["Router.handle"].is_entrypoint
    assert by_name["Router.handle"].entry_kind == "method"
    assert not by_name["fallback"].is_entrypoint
    assert by_name["main"].is_entrypoint

    handle = _flow(model, "Router.handle")
    labels = {n.label for n in handle.nodes if n.kind is NodeKind.DECISION}
    assert "status == Status::Active" in labels
    assert "Switch on status" in labels
    assert "missing_branch" in {f.kind for f in model.findings if f.flow_id == handle.id}


def test_cpp_local_static_variable_does_not_hide_public_function(tmp_path: Path) -> None:
    model = _analyze(
        tmp_path,
        "counter.cpp",
        "int counter() { static int value = 0; return ++value; }\n",
    )

    flow = _flow(model, "counter")
    assert flow.is_entrypoint


def test_rust_if_match_and_visibility(tmp_path: Path) -> None:
    model = _analyze(tmp_path, "lib.rs", _RUST)
    by_name = {f.name: f for f in model.flows}
    assert by_name["handle"].language == "rust"
    assert by_name["handle"].is_entrypoint  # pub
    assert not by_name["persist"].is_entrypoint  # private
    handle = _flow(model, "handle")
    match = next(
        n for n in handle.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    assert {"Status::Active", "Status::Suspended"} <= set(match.metadata["values"])
    # Rust `match` is compiler-exhaustive: a missing `_` arm is enforced by the
    # compiler, not a runtime gap, so it must not be flagged and no synthetic
    # fallthrough branch is added.
    assert "missing_branch" not in {f.kind for f in model.findings if f.flow_id == handle.id}
    assert not any(b["implicit"] for b in match.metadata["branches"])


def _reaches(flow, start_id: str) -> set[str]:
    """Node ids reachable from `start_id` (following outgoing edges)."""
    out: dict[str, list[str]] = {}
    for edge in flow.edges:
        out.setdefault(edge.source, []).append(edge.target)
    seen: set[str] = set()
    stack = [start_id]
    while stack:
        cur = stack.pop()
        for nxt in out.get(cur, ()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def test_c_empty_case_falls_through_to_next_case(tmp_path: Path) -> None:
    # `case 1: case 2: return 10;` - the empty case 1 must reach the `return 10` of
    # case 2 (real fall-through), NOT dangle onto the post-switch "Complete" terminal.
    model = _analyze(
        tmp_path,
        "ft.c",
        "int classify(int x) {\n"
        "  switch (x) {\n"
        "    case 1:\n"
        "    case 2:\n"
        "      return 10;\n"
        "    case 3:\n"
        "      return 30;\n"
        "    default:\n"
        "      return 0;\n"
        "  }\n"
        "}\n",
    )
    flow = _flow(model, "classify")
    nodes = {n.id: n for n in flow.nodes}
    switch = next(n for n in flow.nodes if n.label.startswith("Switch"))
    # The edge for case 1 (label "1") - its target begins case 1's body.
    case1_target = next(e.target for e in flow.edges if e.source == switch.id and e.label == "1")
    reached = _reaches(flow, case1_target) | {case1_target}
    return_10 = next(n.id for n in flow.nodes if n.label.strip() == "Return 10")
    complete = next(
        (n.id for n in flow.nodes if n.kind is NodeKind.TERMINAL and "Complete" in n.label), None
    )
    # case 1 reaches the shared `return 10`...
    assert return_10 in reached
    # ...and does NOT fabricate a path to the post-switch join (there is a default, so
    # the switch is total and "Complete" is unreachable from case 1).
    assert complete is None or complete not in reached
    assert all(nodes[n].label.strip() != "Return 0" for n in reached)


def test_rust_wildcard_arm_is_default(tmp_path: Path) -> None:
    model = _analyze(
        tmp_path,
        "w.rs",
        "pub fn pick(s: Status) -> i32 {\n  match s {\n"
        "    Status::Active => 1,\n    _ => 0,\n  }\n}\n",
    )
    pick = _flow(model, "pick")
    # the `_` arm is recognized as the explicit default, not a synthetic fallthrough
    assert "missing_branch" not in {f.kind for f in model.findings if f.flow_id == pick.id}
    match = next(
        n for n in pick.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    assert any(b["label"] == DEFAULT and not b["implicit"] for b in match.metadata["branches"])
