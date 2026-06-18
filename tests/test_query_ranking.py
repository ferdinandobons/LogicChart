"""Relevance/scoring correctness for query_model and the CLI <-> MCP JSON contract.

These tests pin the exact per-bucket weights and the deterministic ordering, lock the
no-match / empty-query behavior, and prove the substring/entry-kind false positives that
an adversarial review found are gone. The CORE relevance (real queries still surface the
right flows) is covered by the demo golden test; here we isolate the scoring mechanics.
"""

from __future__ import annotations

import json
from pathlib import Path

from logicchart.artifacts import load_model
from logicchart.cli import main
from logicchart.model import (
    Evidence,
    Finding,
    Flow,
    FlowNode,
    NodeKind,
    ProjectModel,
    Severity,
    SourceLocation,
)
from logicchart.query import (
    ENTRYPOINT_BONUS,
    FINDING_WEIGHT,
    IDENTITY_WEIGHT,
    NODE_WEIGHT,
    QueryMatch,
    finding_context,
    impact_model,
    query_model,
)


def _loc(path: str = "app.py", line: int = 1) -> SourceLocation:
    return SourceLocation(path=path, start_line=line, end_line=line + 1)


def _flow(
    flow_id: str,
    name: str,
    *,
    symbol: str | None = None,
    node_labels: tuple[str, ...] = (),
    is_entrypoint: bool = False,
    entry_kind: str = "function",
    framework: str = "generic",
) -> Flow:
    nodes = [
        FlowNode(
            id=f"{flow_id}-n{index}",
            kind=NodeKind.ACTION,
            label=label,
            location=_loc(),
        )
        for index, label in enumerate(node_labels)
    ]
    return Flow(
        id=flow_id,
        name=name,
        symbol=symbol if symbol is not None else name,
        language="python",
        framework=framework,
        entry_kind=entry_kind,
        is_entrypoint=is_entrypoint,
        location=_loc(),
        nodes=nodes,
    )


def _finding(flow_id: str, message: str) -> Finding:
    return Finding(
        id=f"{flow_id}-find",
        kind="missing_branch",
        severity=Severity.WARNING,
        message=message,
        evidence=Evidence.POTENTIAL_GAP,
        flow_id=flow_id,
        location=_loc(),
    )


def _model(flows: list[Flow], findings: list[Finding] | None = None) -> ProjectModel:
    return ProjectModel(
        schema_version="1.1",
        generated_at="2026-06-16T00:00:00+00:00",
        root="/tmp/project",
        flows=flows,
        findings=findings or [],
    )


def test_bucket_weights_and_order_are_exact() -> None:
    """Three flows that hit the SAME term in different buckets rank identity > finding
    > node, with scores equal to the named per-bucket constants."""
    model = _model(
        flows=[
            _flow("f-id", "widget", symbol="widget"),  # identity hit
            _flow("f-node", "alpha", node_labels=("the widget toggles",)),  # node hit
            _flow("f-find", "beta"),  # finding hit
        ],
        findings=[_finding("f-find", "widget review gap")],
    )
    matches = query_model(model, "widget")

    assert [m.flow.id for m in matches] == ["f-id", "f-find", "f-node"]
    by_id = {m.flow.id: m.score for m in matches}
    assert by_id["f-id"] == IDENTITY_WEIGHT
    assert by_id["f-find"] == FINDING_WEIGHT
    assert by_id["f-node"] == NODE_WEIGHT


def test_entrypoint_bonus_only_breaks_ties_between_real_matches() -> None:
    """The entrypoint bonus is added only on top of a positive term score."""
    model = _model(
        flows=[
            _flow("plain", "widget", symbol="widget"),
            _flow("entry", "widget", symbol="widget", is_entrypoint=True),
        ]
    )
    matches = query_model(model, "widget")
    by_id = {m.flow.id: m.score for m in matches}
    assert by_id["entry"] == IDENTITY_WEIGHT + ENTRYPOINT_BONUS
    assert by_id["plain"] == IDENTITY_WEIGHT
    # The entrypoint sorts first on the bonus tie-break.
    assert matches[0].flow.id == "entry"


def test_entrypoint_with_zero_term_overlap_is_not_returned() -> None:
    """An entrypoint matching no query term must not appear as score=1 filler."""
    model = _model(
        flows=[
            _flow("hit", "widget", symbol="widget"),
            _flow("noise", "unrelated", symbol="unrelated", is_entrypoint=True),
        ]
    )
    matches = query_model(model, "widget")
    assert [m.flow.id for m in matches] == ["hit"]
    assert all(m.score > 0 and m.reasons for m in matches)


def test_deterministic_tie_break_by_id() -> None:
    """Equal score AND equal name -> stable order by unique flow id, regardless of
    insertion order."""
    forward = _model(
        flows=[
            _flow("z-id", "widget", symbol="widget"),
            _flow("a-id", "widget", symbol="widget"),
        ]
    )
    reverse = _model(
        flows=[
            _flow("a-id", "widget", symbol="widget"),
            _flow("z-id", "widget", symbol="widget"),
        ]
    )
    assert [m.flow.id for m in query_model(forward, "widget")] == ["a-id", "z-id"]
    assert [m.flow.id for m in query_model(reverse, "widget")] == ["a-id", "z-id"]


def test_no_match_returns_empty() -> None:
    model = _model(flows=[_flow("f", "widget", symbol="widget")])
    assert query_model(model, "nonexistent_term") == []


def test_empty_and_punctuation_only_query_returns_empty() -> None:
    model = _model(flows=[_flow("f", "widget", symbol="widget", is_entrypoint=True)])
    assert query_model(model, "") == []
    assert query_model(model, "??? !!! ...") == []
    # Stopwords-only collapses to no terms, too.
    assert query_model(model, "what is the") == []


def test_structured_query_filters_can_match_without_terms() -> None:
    decision = FlowNode(
        id="orders:n1",
        kind=NodeKind.DECISION,
        label="if order.status == OPEN",
        location=_loc("src/orders.py", 4),
        metadata={
            "domain": "status",
            "value_namespace": "OrderStatus",
            "values": ["OPEN"],
            "branches": [{"label": "OPEN", "outcome": "return open"}],
        },
    )
    flow = Flow(
        id="orders-flow",
        name="handle_order",
        symbol="api.orders:handle_order",
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=True,
        location=_loc("src/orders.py", 1),
        nodes=[decision],
    )
    model = _model([flow, _flow("other", "other", symbol="api.other:handle")])

    matches = query_model(
        model,
        "",
        source_path="orders.py",
        symbol="api.orders:handle_order",
        domain="status",
        value="OPEN",
    )

    assert [match.flow.id for match in matches] == ["orders-flow"]
    assert matches[0].score == 4 * 5 + ENTRYPOINT_BONUS
    assert matches[0].reasons == [
        "source path matches `orders.py`",
        "symbol/name matches `api.orders:handle_order`",
        "decision domain matches `status`",
        "decision value matches `OPEN`",
    ]


def test_substring_no_longer_matches() -> None:
    """'order' must NOT match inside 'reordering_queue' (token, not substring); it must
    still match a flow whose identity contains 'order' as a whole token."""
    model = _model(
        flows=[
            _flow("re", "reordering_queue", symbol="reordering_queue"),
            _flow("ok", "create order", symbol="createOrder", node_labels=("order ok",)),
        ]
    )
    matches = query_model(model, "order")
    assert [m.flow.id for m in matches] == ["ok"]


def test_entry_kind_and_framework_are_not_matchable() -> None:
    """Querying the internal vocabulary 'route'/'function' must not return everything."""
    model = _model(
        flows=[
            _flow("r1", "alpha", symbol="alpha", entry_kind="route", framework="next"),
            _flow("r2", "beta", symbol="beta", entry_kind="route", framework="next"),
        ]
    )
    assert query_model(model, "route") == []
    assert query_model(model, "function") == []
    assert query_model(model, "next") == []


def test_repeated_query_term_does_not_inflate_rank() -> None:
    model = _model(flows=[_flow("f", "widget", symbol="widget")])
    once = query_model(model, "widget")
    thrice = query_model(model, "widget widget widget")
    assert [m.score for m in once] == [m.score for m in thrice] == [IDENTITY_WEIGHT]


def test_unicode_terms_survive_tokenization() -> None:
    """Unicode \\w words (café, 日本語) must not be dropped or corrupted by the ASCII-only
    tokenizer they replaced; they tokenize to standalone matchable terms."""
    model = _model(
        flows=[
            _flow("c", "café handler", symbol="cafeHandler"),
            _flow("j", "日本語 flow", symbol="jpFlow"),
        ]
    )
    assert [m.flow.id for m in query_model(model, "café")] == ["c"]
    assert [m.flow.id for m in query_model(model, "日本語")] == ["j"]


def test_limit_is_respected_and_non_positive_means_no_limit() -> None:
    flows = [_flow(f"f{i}", "widget", symbol="widget") for i in range(5)]
    model = _model(flows=flows)
    assert len(query_model(model, "widget", limit=2)) == 2
    assert len(query_model(model, "widget", limit=0)) == 5
    # A negative limit must NOT silently drop results via slice semantics.
    assert len(query_model(model, "widget", limit=-1)) == 5


def test_query_match_to_dict_shape() -> None:
    match = QueryMatch(
        flow=_flow("f1", "widget", symbol="widget"),
        score=6,
        reasons=["`widget` matches the flow identity"],
    )
    payload = match.to_dict()
    assert payload == {
        "flow_id": "f1",
        "name": "widget",
        "language": "python",
        "entry_kind": "function",
        "framework": "generic",
        "scope": [],
        "score": 6,
        "reasons": ["`widget` matches the flow identity"],
        "source": "app.py:1",
    }
    assert "source" not in match.to_dict(include_source=False)


def test_finding_context_collects_related_subject_subgraph() -> None:
    focus_node = FlowNode(
        id="dispatch:status",
        kind=NodeKind.DECISION,
        label="if order.status == OPEN",
        location=_loc("orders.py", 10),
        metadata={
            "subject": "order.status",
            "value_namespace": "OrderStatus",
            "values": ["OPEN"],
            "branches": [{"label": "OPEN", "outcome": "return open"}],
        },
    )
    sibling_node = FlowNode(
        id="cancel:status",
        kind=NodeKind.DECISION,
        label="if order.status == CANCELLED",
        location=_loc("orders.py", 30),
        metadata={
            "subject": "order.status",
            "value_namespace": "OrderStatus",
            "values": ["CANCELLED"],
            "branches": [{"label": "CANCELLED", "outcome": "return cancel"}],
        },
    )
    focus_flow = Flow(
        id="dispatch",
        name="dispatch",
        symbol="dispatch",
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=True,
        location=_loc("orders.py", 1),
        nodes=[focus_node],
        calls=["audit"],
    )
    sibling_flow = Flow(
        id="cancel",
        name="cancel",
        symbol="cancel",
        language="python",
        framework="generic",
        entry_kind="function",
        is_entrypoint=True,
        location=_loc("orders.py", 24),
        nodes=[sibling_node],
    )
    audit_flow = _flow("audit", "audit")
    finding = Finding(
        id="dispatch-find",
        kind="enum_exhaustiveness",
        severity=Severity.WARNING,
        message="Declared OrderStatus members not handled for order.status: CANCELLED",
        evidence=Evidence.INFERRED,
        flow_id="dispatch",
        node_id="dispatch:status",
        location=_loc("orders.py", 10),
        metadata={
            "category": "cross_flow",
            "subject": "order.status",
            "value_namespace": "OrderStatus",
            "missing": ["CANCELLED"],
            "declared": ["OPEN", "CANCELLED"],
        },
    )
    related_finding = Finding(
        id="cancel-find",
        kind="missing_branch",
        severity=Severity.WARNING,
        message="Decision has no explicit fallback: order.status",
        evidence=Evidence.POTENTIAL_GAP,
        flow_id="cancel",
        node_id="cancel:status",
        location=_loc("orders.py", 30),
        metadata={
            "category": "single_flow",
            "subject": "order.status",
            "value_namespace": "OrderStatus",
        },
    )
    model = _model([focus_flow, sibling_flow, audit_flow], [finding, related_finding])

    context = finding_context(model, "dispatch-find", token_budget=160)

    assert context is not None
    assert context["evidence_guardrail"]["tier"] == "INFERRED"
    assert context["diagnostic_summary"]["missing"] == ["CANCELLED"]
    assert context["focus_flow"]["id"] == "dispatch"
    assert context["focus_node"]["node_id"] == "dispatch:status"
    by_flow = {item["id"]: item for item in context["related_flows"]}
    assert "called_by_finding_flow" in by_flow["audit"]["roles"]
    assert "handles_missing_value" in by_flow["cancel"]["roles"]
    by_node = {item["node_id"]: item for item in context["related_nodes"]}
    assert "finding_evidence" in by_node["dispatch:status"]["reasons"]
    assert "handles_missing_value" in by_node["cancel:status"]["reasons"]
    assert context["related_findings"][0]["id"] == "cancel-find"
    assert context["next_tools"]["visual_snapshot"]["tool"] == "get_finding_snapshot"


def test_impact_model_accepts_flow_symbol_and_finding_targets() -> None:
    target = _flow("target", "target", symbol="pkg:target")
    caller = _flow("caller", "caller", symbol="pkg:caller")
    caller.calls = ["target"]
    target.called_by = ["caller"]
    unrelated = _flow("other", "other", symbol="pkg:other")
    finding = Finding(
        id="target-find",
        kind="missing_branch",
        severity=Severity.WARNING,
        message="Decision has no explicit fallback",
        evidence=Evidence.POTENTIAL_GAP,
        flow_id="target",
        location=_loc("target.py", 3),
    )
    model = _model([target, caller, unrelated], [finding])

    result = impact_model(
        model,
        [],
        flow_ids=["target", "missing-flow"],
        symbols=["caller", "missing-symbol"],
        finding_ids=["target-find", "missing-finding"],
    )

    assert result.changed_files == []
    assert result.target_flow_ids == ["target", "missing-flow"]
    assert result.target_symbols == ["caller", "missing-symbol"]
    assert result.target_finding_ids == ["target-find", "missing-finding"]
    assert {flow.id for flow in result.directly_impacted} == {"target", "caller"}
    assert result.subgraph_flow_ids == ["caller", "target"]
    assert result.subgraph_finding_ids == ["target-find"]
    assert {item["value"]: item["reason"] for item in result.unresolved_targets} == {
        "missing-flow": "not_found",
        "missing-symbol": "not_found",
        "missing-finding": "not_found",
    }


def test_impact_model_marks_scope_filtered_targets() -> None:
    backend = _flow("backend", "backend", symbol="svc:backend")
    backend.metadata["scope"] = ["backend"]
    frontend = _flow("frontend", "frontend", symbol="web:frontend")
    frontend.metadata["scope"] = ["frontend"]
    model = _model([backend, frontend])

    result = impact_model(model, [], scope="frontend", flow_ids=["backend"])

    assert result.directly_impacted == []
    assert result.unresolved_targets == [
        {"type": "flow", "value": "backend", "reason": "scope_filtered"}
    ]


def _demo_source(tmp_path: Path) -> Path:
    source = tmp_path / "app.py"
    source.write_text(
        "def authorize(user):\n"
        "    if user.role == 'admin':\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )
    return tmp_path


def test_cli_no_match_prints_message(tmp_path: Path, capsys: object) -> None:
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["query", "zzqqxx_nonsense", "--path", str(root)]) == 0
    out = capsys.readouterr()  # type: ignore[attr-defined]
    assert out.out.strip() == "No matching logic flows found."


def test_cli_negative_limit_warns_and_keeps_results(tmp_path: Path, capsys: object) -> None:
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["query", "admin authorize", "--path", str(root), "--limit", "-1"]) == 0
    out = capsys.readouterr()  # type: ignore[attr-defined]
    assert "authorize" in out.out
    assert "negative --limit" in out.err


def test_cli_unknown_scope_warns_but_runs(tmp_path: Path, capsys: object) -> None:
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["query", "admin authorize", "--path", str(root), "--scope", "nope"]) == 0
    out = capsys.readouterr()  # type: ignore[attr-defined]
    assert "unknown scope" in out.err


def test_cli_json_matches_query_match_to_dict(tmp_path: Path, capsys: object) -> None:
    """The CLI --json shape is exactly QueryMatch.to_dict() (the same serializer the MCP
    query_logic tool now uses), including the path:line `source` field."""
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    assert main(["query", "admin authorize", "--path", str(root), "--json"]) == 0
    out = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(out.out)
    assert payload
    for row in payload:
        assert set(row) == {
            "flow_id",
            "name",
            "language",
            "entry_kind",
            "framework",
            "scope",
            "score",
            "reasons",
            "source",
        }
        assert ":" in row["source"]


def test_cli_impact_json_accepts_flow_target_without_changed_files(
    tmp_path: Path, capsys: object
) -> None:
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    flow = load_model(root).flows[0]

    assert main(["impact", "--path", str(root), "--flow", flow.id, "--json"]) == 0
    out = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(out.out)

    assert payload["changed_files"] == []
    assert payload["target_flow_ids"] == [flow.id]
    assert payload["directly_impacted"] == [flow.id]
    assert payload["subgraph_flow_ids"] == [flow.id]


def test_cli_query_json_accepts_structured_filters(tmp_path: Path, capsys: object) -> None:
    root = _demo_source(tmp_path)
    assert main(["analyze", str(root), "--full"]) == 0
    capsys.readouterr()  # type: ignore[attr-defined]
    flow = load_model(root).flows[0]

    assert (
        main(
            [
                "query",
                "",
                "--path",
                str(root),
                "--symbol",
                flow.symbol,
                "--source-path",
                "app.py",
                "--json",
            ]
        )
        == 0
    )
    out = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(out.out)

    assert [row["flow_id"] for row in payload] == [flow.id]
    assert "symbol/name matches" in payload[0]["reasons"][1]
