from pathlib import Path

from logicchart.analysis.typescript import TypeScriptAnalyzer
from logicchart.config import LogicChartConfig
from logicchart.model import NodeKind


def test_next_route_and_switch_are_detected(tmp_path: Path) -> None:
    route_dir = tmp_path / "app" / "api" / "users"
    route_dir.mkdir(parents=True)
    source = route_dir / "route.ts"
    source.write_text(
        """
export async function POST(request: Request) {
  const user = await loadUser(request);
  switch (user.status) {
    case UserStatus.ACTIVE:
      return Response.json(user);
    case UserStatus.SUSPENDED:
      throw new Error("blocked");
  }
}
""",
        encoding="utf-8",
    )

    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)

    assert len(analysis.flows) == 1
    flow = analysis.flows[0]
    assert flow.is_entrypoint
    assert flow.framework == "nextjs"
    assert flow.entry_kind == "route"
    assert any(node.kind is NodeKind.DECISION for node in flow.nodes)


def _reaches(flow, start_id: str) -> set[str]:
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


def test_empty_case_falls_through_to_next_case(tmp_path: Path) -> None:
    # `case 'a': case 'b': return X` - the empty case 'a' must reach case 'b''s return,
    # not dangle onto the post-switch terminal.
    source = tmp_path / "ft.ts"
    source.write_text(
        "export function classify(x: string) {\n"
        "  switch (x) {\n"
        "    case 'a':\n"
        "    case 'b':\n"
        "      return 10;\n"
        "    case 'c':\n"
        "      return 30;\n"
        "    default:\n"
        "      return 0;\n"
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = analysis.flows[0]
    switch = next(n for n in flow.nodes if n.label.startswith("Switch"))
    case_a = next(e.target for e in flow.edges if e.source == switch.id and e.label == "'a'")
    reached = _reaches(flow, case_a) | {case_a}
    return_10 = next(n.id for n in flow.nodes if n.label.strip() == "Return 10")
    complete = next(
        (n.id for n in flow.nodes if n.kind is NodeKind.TERMINAL and "Complete" in n.label), None
    )
    assert return_10 in reached
    assert complete is None or complete not in reached


def test_exported_react_component_is_an_entrypoint(tmp_path: Path) -> None:
    source = tmp_path / "UserPanel.tsx"
    source.write_text(
        """
export function UserPanel({ user }: Props) {
  if (!user.isAuthorized) {
    return <LoginPrompt />;
  }
  return <Dashboard user={user} />;
}
""",
        encoding="utf-8",
    )

    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = analysis.flows[0]

    assert flow.is_entrypoint
    assert flow.framework == "react"
    assert flow.entry_kind == "component"


def test_expression_bodied_arrow_component_models_ternary_decision(tmp_path: Path) -> None:
    source = tmp_path / "UserBadge.tsx"
    source.write_text(
        """
export const UserBadge = ({ user }: Props) =>
  user.active ? <Active user={user} /> : <Inactive />;
""",
        encoding="utf-8",
    )

    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = analysis.flows[0]

    assert flow.is_entrypoint
    assert flow.framework == "react"
    assert flow.entry_kind == "component"
    decision = next(node for node in flow.nodes if node.kind is NodeKind.DECISION)
    assert decision.label == "user.active"
    assert decision.metadata["branches"] == [
        {"label": "Yes", "outcome": "returns", "implicit": False},
        {"label": "No", "outcome": "returns", "implicit": False},
    ]
    assert any(node.label.startswith("Return <Active") for node in flow.nodes)
    assert any(node.label.startswith("Return <Inactive") for node in flow.nodes)
    assert not any(node.label == "Complete" for node in flow.nodes)


def test_loop_body_decision_is_modeled_before_post_loop(tmp_path: Path) -> None:
    source = tmp_path / "orders.ts"
    source.write_text(
        """
export function processOrders(orders: Order[]) {
  for (let index = 0; index < orders.length; index++) {
    const order = orders[index];
    if (order.status === "open") {
      approve(order);
    }
  }
  return done();
}
""",
        encoding="utf-8",
    )

    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "processOrders")
    labels = [node.label for node in flow.nodes]

    assert any(label.startswith("Repeat: for ") for label in labels)
    assert 'order.status === "open"' in labels
    assert "Call approve()" in labels
    assert "Call done()" in labels
    assert "Return done()" in labels

    loop = next(node for node in flow.nodes if node.label.startswith("Repeat: for "))
    by_label = {node.label: node.id for node in flow.nodes}
    iteration_target = next(
        edge.target for edge in flow.edges if edge.source == loop.id and edge.label == "Iteration"
    )
    assert by_label['order.status === "open"'] in _reaches(flow, iteration_target)
    assert any(
        edge.source == loop.id and edge.target == by_label["Call done()"] and edge.label == "Done"
        for edge in flow.edges
    )
    assert any(
        edge.source == by_label["Call approve()"] and edge.target == by_label["Call done()"]
        for edge in flow.edges
    )


def test_loop_continue_does_not_flow_to_post_loop(tmp_path: Path) -> None:
    source = tmp_path / "orders.ts"
    source.write_text(
        """
export function processOrders(orders: Order[]) {
  for (const order of orders) {
    if (order.status === "skip") {
      continue;
    }
    handle(order);
  }
  return done();
}
""",
        encoding="utf-8",
    )

    analysis = TypeScriptAnalyzer(tmp_path, LogicChartConfig()).analyze(source)
    flow = next(item for item in analysis.flows if item.name == "processOrders")
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
