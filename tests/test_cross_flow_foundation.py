"""Cross-flow foundation: enum tables, effects, and schema metadata."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.common import effect_tags
from logicchart.analysis.project import ProjectAnalyzer


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
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    enums = model.metadata["enums"]["typescript"]
    assert enums["Role"] == ["Role.ADMIN", "Role.MEMBER"]
    assert enums["Status"] == ["a", "b", "c"]


def test_enum_table_is_language_scoped(tmp_path: Path) -> None:
    (tmp_path / "domain.py").write_text(
        "from enum import Enum\n\nclass Status(str, Enum):\n    ACTIVE = 'active'\n",
        encoding="utf-8",
    )
    (tmp_path / "types.ts").write_text(
        'export type Status = "active" | "deleted";\n', encoding="utf-8"
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    enums = model.metadata["enums"]
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
    assert "log" not in effect_tags(["error"])
    assert "db_write" in effect_tags(["save_user"])
    assert "db_write" not in effect_tags(["created_at"])


def test_ts_parenthesized_union_is_flattened(tmp_path: Path) -> None:
    (tmp_path / "t.ts").write_text('export type S = ("a" | "b") | "c";\n', encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    enums = model.metadata["enums"]["typescript"]
    assert enums["S"] == ["a", "b", "c"]


def test_project_schema_version_tracks_current_artifact_contract(tmp_path: Path) -> None:
    (tmp_path / "svc.py").write_text(
        "def route(order):\n"
        "    if order.status == OrderStatus.PAID:\n        return a()\n"
        "    elif order.status == OrderStatus.CART:\n        return b()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    assert model.schema_version == "2.0"
