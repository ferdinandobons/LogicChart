"""Stage 4 cross-flow foundation: enum table, effect tags, schema/metadata."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.common import effect_tags
from logicchart.analysis.project import ProjectAnalyzer

_THREE_FULL = """
def handle_a(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()


def handle_b(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()


def handle_c(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if account.status == Status.DELETED:
        return d()
"""


def test_python_enum_table_is_harvested(tmp_path: Path) -> None:
    (tmp_path / "domain.py").write_text(
        "from enum import Enum\n\n"
        "class Status(str, Enum):\n    ACTIVE = 'active'\n    GONE = 'gone'\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert model.metadata["enums"]["python"]["Status"] == ["Status.ACTIVE", "Status.GONE"]


def test_typescript_enum_and_union_table(tmp_path: Path) -> None:
    (tmp_path / "types.ts").write_text(
        'export enum Role { ADMIN, MEMBER }\nexport type Status = "a" | "b" | "c";\n',
        encoding="utf-8",
    )
    enums = ProjectAnalyzer(tmp_path).analyze(full=True).model.metadata["enums"]["typescript"]
    assert enums["Role"] == ["Role.ADMIN", "Role.MEMBER"]
    assert enums["Status"] == ["a", "b", "c"]


def test_enum_table_is_language_scoped(tmp_path: Path) -> None:
    # A Python enum and a same-named TS union are distinct value universes.
    (tmp_path / "domain.py").write_text(
        "from enum import Enum\n\nclass Status(str, Enum):\n    ACTIVE = 'active'\n",
        encoding="utf-8",
    )
    (tmp_path / "types.ts").write_text(
        'export type Status = "active" | "deleted";\n', encoding="utf-8"
    )
    enums = ProjectAnalyzer(tmp_path).analyze(full=True).model.metadata["enums"]
    assert enums["python"]["Status"] == ["Status.ACTIVE"]
    assert enums["typescript"]["Status"] == ["active", "deleted"]


def test_effect_tags_and_auth_flag(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def handler(account):\n"
        "    require_role(account, 'admin')\n"
        "    save(account)\n"
        "    return ok()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handler = next(f for f in model.flows if f.name == "handler")
    effects = {tag for node in handler.nodes for tag in node.metadata.get("effects", [])}

    assert handler.metadata["performs_auth_check"] is True
    assert "auth_check" in effects
    assert "db_write" in effects


def test_no_auth_flag_when_absent(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def handler(account):\n    return fetch(account)\n", encoding="utf-8"
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handler = next(f for f in model.flows if f.name == "handler")

    assert handler.metadata["performs_auth_check"] is False


def test_effect_tags_match_logger_methods_without_false_positives() -> None:
    assert "log" in effect_tags(["logger.info"])
    assert "log" in effect_tags(["logger.error"])
    assert "log" in effect_tags(["self.log.warning"])
    assert "log" not in effect_tags(["error"])  # a bare error() is not logging
    assert "db_write" in effect_tags(["save_user"])
    assert "db_write" not in effect_tags(["created_at"])  # word-boundary guard


def test_ts_parenthesized_union_is_flattened(tmp_path: Path) -> None:
    (tmp_path / "t.ts").write_text('export type S = ("a" | "b") | "c";\n', encoding="utf-8")
    enums = ProjectAnalyzer(tmp_path).analyze(full=True).model.metadata["enums"]["typescript"]
    assert enums["S"] == ["a", "b", "c"]


def test_same_enum_on_different_subjects_is_not_compared(tmp_path: Path) -> None:
    # `Status` reused on order.status and payment.status: subjects must not collapse.
    (tmp_path / "svc.py").write_text(
        """
def order_flow(order):
    if order.status == Status.ACTIVE:
        return a()
    if order.status == Status.SHIPPED:
        return b()
    if order.status == Status.CANCELLED:
        return c()


def payment_one(payment):
    if payment.status == Status.ACTIVE:
        return ok()


def payment_two(payment):
    if payment.status == Status.ACTIVE:
        return ok()
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert not any(f.kind == "inconsistent_case_handling" for f in model.findings)


def test_unrelated_default_does_not_suppress_real_gap(tmp_path: Path) -> None:
    body = (
        _THREE_FULL
        + """
def handle_partial(account, payment):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.SUSPENDED:
        return s()
    if payment.status == Status.PENDING:
        return p()
    else:
        return other()
"""
    )
    (tmp_path / "svc.py").write_text(body, encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    partial = next(f for f in model.flows if f.name == "handle_partial")
    flagged = [
        f
        for f in model.findings
        if f.kind == "inconsistent_case_handling" and f.flow_id == partial.id
    ]
    # The else is on payment.status, a different subject - it must not hide the
    # genuine account.status gap.
    assert any("DELETED" in f.message for f in flagged)


def test_explicit_default_on_same_subject_suppresses_flag(tmp_path: Path) -> None:
    body = (
        _THREE_FULL
        + """
def handle_with_default(account):
    if account.status == Status.ACTIVE:
        return ok()
    else:
        return fallback()
"""
    )
    (tmp_path / "svc.py").write_text(body, encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    with_default = next(f for f in model.flows if f.name == "handle_with_default")
    assert not any(
        f.kind == "inconsistent_case_handling" and f.flow_id == with_default.id
        for f in model.findings
    )


def test_two_siblings_are_below_the_quorum_floor(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        """
def handle_a(account):
    if account.status == Status.ACTIVE:
        return ok()
    if account.status == Status.DELETED:
        return d()


def handle_b(account):
    if account.status == Status.ACTIVE:
        return ok()
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    assert not any(f.kind == "inconsistent_case_handling" for f in model.findings)


def test_findings_carry_metadata_and_schema_is_1_1(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def route(order):\n"
        "    if order.status == OrderStatus.PAID:\n        return a()\n"
        "    elif order.status == OrderStatus.CART:\n        return b()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    assert model.schema_version == "1.1"
    assert all(isinstance(f.metadata, dict) for f in model.findings)
