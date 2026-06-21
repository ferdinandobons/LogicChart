"""Relevance/scoring correctness for query_model and the CLI <-> MCP JSON contract.

These tests pin the exact per-bucket weights and the deterministic ordering, lock the
no-match / empty-query behavior, and prove substring/entry-kind false positives are gone.
The CORE relevance (real queries still surface the right flows) is covered by the demo
golden test; here we isolate the scoring mechanics.
"""

from __future__ import annotations

from logicchart.model import (
    Flow,
    FlowNode,
    NodeKind,
    ProjectModel,
    SourceLocation,
)
from logicchart.query import (
    ENTRYPOINT_BONUS,
    IDENTITY_WEIGHT,
    NODE_WEIGHT,
    STRUCTURE_WEIGHT,
    QueryMatch,
    flow_in_scope,
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


def _model(flows: list[Flow]) -> ProjectModel:
    return ProjectModel(
        schema_version="2.0",
        generated_at="2026-06-16T00:00:00+00:00",
        root="/tmp/project",
        flows=flows,
    )


def test_bucket_weights_and_order_are_exact() -> None:
    """Three flows that hit the SAME term in different buckets rank identity > structure
    > node, with scores equal to the named per-bucket constants."""
    model = _model(
        flows=[
            _flow("f-id", "widget", symbol="widget"),  # identity hit
            _flow("f-node", "alpha", node_labels=("the widget toggles",)),  # node hit
            _flow("f-structure", "beta"),  # source path hit
        ],
    )
    model.flows[2].location = _loc("src/widget/service.py")
    matches = query_model(model, "widget")

    assert [m.flow.id for m in matches] == ["f-id", "f-structure", "f-node"]
    by_id = {m.flow.id: m.score for m in matches}
    assert by_id["f-id"] == IDENTITY_WEIGHT
    assert by_id["f-structure"] == STRUCTURE_WEIGHT
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


def test_query_scope_filter_normalizes_legacy_string_scope() -> None:
    flow = _flow("frontend", "frontend widget")
    flow.metadata["scope"] = "frontend"
    model = _model([flow])

    assert flow_in_scope(flow, "frontend")
    assert not flow_in_scope(flow, "front")
    assert query_model(model, "widget", scope="front") == []

    [match] = query_model(model, "widget", scope="frontend")
    assert match.to_dict(include_source=False)["scope"] == ["frontend"]


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


def test_query_splits_code_identifiers_and_light_language_variants() -> None:
    model = _model(
        flows=[
            _flow(
                "upload",
                "UnifiedUploadBox",
                symbol="frontend.components:UnifiedUploadBox",
                node_labels=("PUT file to presigned S3 URL",),
            ),
            _flow("other", "ProfilePanel", symbol="frontend.components:ProfilePanel"),
        ]
    )
    model.flows[0].location = _loc("frontend/certificati/UnifiedUploadBox.tsx")

    matches = query_model(model, "certificate upload")

    assert [m.flow.id for m in matches] == ["upload"]


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
        "subgraph_flow_ids": ["f1"],
        "next_tools": {
            "agent_context": {
                "tool": "agent_context",
                "arguments": {"flow_id": "f1"},
            },
            "snapshot_slice": {
                "tool": "snapshot_slice",
                "arguments": {"flow_ids": ["f1"], "format": "svg", "include_svg": False},
            },
            "expand_slice": {
                "tool": "expand_slice",
                "arguments": {"flow_ids": ["f1"], "direction": "neighbors"},
            },
        },
        "source": "app.py:1",
    }
    assert "source" not in match.to_dict(include_source=False)


def test_impact_model_accepts_flow_and_symbol_targets() -> None:
    target = _flow("target", "target", symbol="pkg:target")
    caller = _flow("caller", "caller", symbol="pkg:caller")
    caller.calls = ["target"]
    target.called_by = ["caller"]
    unrelated = _flow("other", "other", symbol="pkg:other")
    model = _model([target, caller, unrelated])

    result = impact_model(
        model,
        [],
        flow_ids=["target", "missing-flow"],
        symbols=["caller", "missing-symbol"],
    )

    assert result.changed_files == []
    assert result.target_flow_ids == ["target", "missing-flow"]
    assert result.target_symbols == ["caller", "missing-symbol"]
    assert {flow.id for flow in result.directly_impacted} == {"target", "caller"}
    assert result.impact_reasons == {
        "caller": ["explicit symbol/name target `caller`"],
        "target": ["explicit flow target `target`"],
    }
    assert result.subgraph_flow_ids == ["caller", "target"]
    assert {item["value"]: item["reason"] for item in result.unresolved_targets} == {
        "missing-flow": "not_found",
        "missing-symbol": "not_found",
    }


def test_impact_model_accepts_dependency_path_targets() -> None:
    charge = _flow("charge", "chargeOrder", symbol="svc:charge")
    charge.location = _loc("services/payments/charge.py", 10)
    refund = _flow("refund", "refundOrder", symbol="svc:refund")
    refund.location = _loc("services/payments/refund.py", 20)
    caller = _flow("caller", "loadCheckout", symbol="web:checkout")
    caller.location = _loc("frontend/checkout.py", 30)
    caller.calls = ["charge"]
    charge.called_by = ["caller"]
    similar = _flow("similar", "paymentsLegacy", symbol="svc:legacy")
    similar.location = _loc("services/payments-legacy/refund.py", 40)
    model = _model([charge, refund, caller, similar])

    result = impact_model(
        model,
        [],
        dependency_paths=["./services/payments", "missing/path"],
    )

    assert result.changed_files == []
    assert result.target_dependency_paths == ["services/payments", "missing/path"]
    assert {flow.id for flow in result.directly_impacted} == {"charge", "refund"}
    assert {flow.id for flow in result.transitively_impacted} == {"caller"}
    assert result.impact_reasons["charge"] == ["dependency path target `services/payments`"]
    assert result.impact_reasons["refund"] == ["dependency path target `services/payments`"]
    assert result.impact_reasons["caller"] == ["calls impacted flow `chargeOrder`"]
    assert "similar" not in result.subgraph_flow_ids
    assert result.unresolved_targets == [
        {"type": "dependency_path", "value": "missing/path", "reason": "not_found"}
    ]


def test_impact_model_follows_multi_level_callers() -> None:
    leaf = _flow("leaf", "leaf")
    middle = _flow("middle", "middle")
    root = _flow("root", "root")
    root.calls = ["middle"]
    middle.called_by = ["root"]
    middle.calls = ["leaf"]
    leaf.called_by = ["middle"]
    model = _model([root, middle, leaf])

    result = impact_model(model, [], flow_ids=["leaf"])

    assert [flow.id for flow in result.directly_impacted] == ["leaf"]
    assert {flow.id for flow in result.transitively_impacted} == {"middle", "root"}
    assert result.impact_reasons["middle"] == ["calls impacted flow `leaf`"]
    assert result.impact_reasons["root"] == ["calls impacted flow `middle`"]


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


def test_impact_model_marks_scope_filtered_dependency_paths() -> None:
    backend = _flow("backend", "backend", symbol="svc:backend")
    backend.location = _loc("backend/svc.py")
    backend.metadata["scope"] = ["backend"]
    model = _model([backend])

    result = impact_model(model, [], scope="frontend", dependency_paths=["backend"])

    assert result.directly_impacted == []
    assert result.unresolved_targets == [
        {"type": "dependency_path", "value": "backend", "reason": "scope_filtered"}
    ]
