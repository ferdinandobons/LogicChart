"""Worked-corpus golden master for examples/shop as a comprehension fixture."""

from __future__ import annotations

import shutil
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import ProjectModel

SHOP = Path(__file__).resolve().parent.parent / "examples" / "shop"


def _analyze_shop_copy(tmp_path: Path) -> ProjectModel:
    for item in ("backend", "frontend", "tests", "logicchart.toml"):
        src = SHOP / item
        dst = tmp_path / item
        if src.is_dir():
            shutil.copytree(src, dst)
        elif src.is_file():
            shutil.copy2(src, dst)
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def test_shop_fixture_models_core_flows(tmp_path: Path) -> None:
    model = _analyze_shop_copy(tmp_path)
    names = {flow.name for flow in model.flows}

    assert {
        "authenticate",
        "change_email",
        "charge",
        "processCheckout",
        "OrdersPage",
        "capture_payment",
        "purge_user",
    } <= names
    assert model.schema_version == "2.0"
    assert "quality" in model.metadata


def test_shop_controls_remain_navigable(tmp_path: Path) -> None:
    model = _analyze_shop_copy(tmp_path)
    flow_keys = {(flow.location.path, flow.name) for flow in model.flows}

    controls = {
        ("backend/users_service.py", "authenticate"),
        ("frontend/app/api/users/route.ts", "GET"),
        ("frontend/app/account/page.tsx", "AccountPage"),
        ("frontend/middleware.ts", "middleware"),
        ("backend/api/users_routes.py", "reset_password"),
        ("backend/api/users_routes.py", "get_profile"),
        ("backend/api/orders_routes.py", "cancel"),
        ("backend/api/orders_routes.py", "request_refund"),
    }
    assert controls <= flow_keys
