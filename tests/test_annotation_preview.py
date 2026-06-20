from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.annotation_preview import AnnotationPreviewOptions, build_annotation_preview
from logicchart.artifacts import write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.model import ProjectModel


def _analyzed_project(tmp_path: Path) -> ProjectModel:
    (tmp_path / "app.py").write_text(
        "def authorize(user):\n"
        "    if user.role == 'admin':\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model, include_html=False)
    return result.model


def _analyzed_multi_flow_project(tmp_path: Path) -> ProjectModel:
    (tmp_path / "a_health.py").write_text(
        "def health():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (tmp_path / "z_orders.py").write_text(
        "from enum import Enum\n\n"
        "class Status(Enum):\n"
        "    OPEN = 'open'\n"
        "    CLOSED = 'closed'\n"
        "    DELETED = 'deleted'\n\n"
        "def handle(status):\n"
        "    match status:\n"
        "        case Status.OPEN:\n"
        "            return 'open'\n"
        "        case Status.CLOSED:\n"
        "            return 'closed'\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model, include_html=False)
    return result.model


def test_enrichment_preview_builds_payload_without_provider_call(tmp_path: Path) -> None:
    model = _analyzed_project(tmp_path)
    config = LogicChartConfig.load(tmp_path)
    payload = build_annotation_preview(tmp_path, model, config, AnnotationPreviewOptions())

    assert payload["provider_call_made"] is False
    assert payload["send_required"] is False
    assert payload["output"].endswith("logicchart-out/logic-annotations.json")
    assert payload["request"]["task"] == "Return LogicChart annotation sidecar JSON only."
    assert payload["request"]["flows"]
    assert payload["request"]["flows"][0]["nodes"]


def test_enrichment_preview_prioritizes_entrypoint_flow_order(tmp_path: Path) -> None:
    model = _analyzed_multi_flow_project(tmp_path)
    config = LogicChartConfig.load(tmp_path)

    preview = build_annotation_preview(
        tmp_path,
        model,
        config,
        AnnotationPreviewOptions(max_flows=1),
    )

    assert preview["targets"]["flow_ids"]
    assert "finding_ids" not in preview["targets"]


def test_enrichment_preview_scope_filter_uses_flow_scope_metadata(tmp_path: Path) -> None:
    frontend = tmp_path / "frontend"
    backend = tmp_path / "backend"
    frontend.mkdir()
    backend.mkdir()
    (frontend / "app.py").write_text("def render():\n    return 'ok'\n", encoding="utf-8")
    (backend / "api.py").write_text("def handle():\n    return 'ok'\n", encoding="utf-8")
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    config = LogicChartConfig.load(tmp_path)

    preview = build_annotation_preview(
        tmp_path,
        model,
        config,
        AnnotationPreviewOptions(scope="frontend", max_flows=10),
    )

    flow_payloads = preview["request"]["flows"]
    assert [flow["name"] for flow in flow_payloads] == ["render"]
    assert flow_payloads[0]["scopes"] == ["frontend"]
    assert set(preview["request"]["scopes"]) == {"frontend"}
