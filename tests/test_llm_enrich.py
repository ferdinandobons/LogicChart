from __future__ import annotations

import json
from pathlib import Path

import pytest

from logicchart import llm_enrich
from logicchart.analysis.project import ProjectAnalyzer
from logicchart.annotations import annotations_path, load_annotations, model_hash
from logicchart.artifacts import load_model, write_artifacts
from logicchart.cli import main
from logicchart.config import LogicChartConfig
from logicchart.llm_config import get_provider, logicchart_env_path, write_logicchart_env
from logicchart.llm_enrich import EnrichmentOptions, build_enrichment_preview
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


def _analyzed_project_with_finding(tmp_path: Path) -> ProjectModel:
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


def test_cli_enrich_preview_builds_payload_without_provider_call(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _analyzed_project(tmp_path)

    assert main(["enrich", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["provider_call_made"] is False
    assert payload["send_required"] is True
    assert payload["llm_configured"] is False
    assert payload["provider"] is None
    assert payload["output"].endswith("logicchart-out/logic-annotations.json")
    assert payload["request"]["task"] == "Return LogicChart annotation sidecar JSON only."
    assert payload["request"]["flows"]
    assert payload["request"]["flows"][0]["nodes"]
    assert "LOGICCHART_LLM_API_KEY" not in json.dumps(payload)


def test_cli_enrich_dry_run_alias_is_local_preview(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _analyzed_project(tmp_path)

    assert main(["enrich", str(tmp_path), "--dry-run", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["provider_call_made"] is False
    assert payload["request"]["flows"]


def test_cli_enrich_rejects_send_with_preview_alias(tmp_path: Path) -> None:
    _analyzed_project(tmp_path)

    assert main(["enrich", str(tmp_path), "--send", "--preview"]) == 1


def test_enrichment_preview_prioritizes_flows_with_findings(tmp_path: Path) -> None:
    model = _analyzed_project_with_finding(tmp_path)
    config = LogicChartConfig.load(tmp_path)
    finding = model.findings[0]

    preview = build_enrichment_preview(
        tmp_path,
        model,
        config,
        EnrichmentOptions(max_flows=1, max_findings=1),
    )
    targeted_preview = build_enrichment_preview(
        tmp_path,
        model,
        config,
        EnrichmentOptions(finding_ids=(finding.id,), max_flows=1, max_findings=1),
    )

    assert preview["targets"]["flow_ids"] == [finding.flow_id]
    assert preview["targets"]["finding_ids"] == [finding.id]
    assert targeted_preview["targets"]["flow_ids"] == [finding.flow_id]
    assert targeted_preview["targets"]["finding_ids"] == [finding.id]


def test_cli_enrich_send_requires_local_llm_config(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _analyzed_project(tmp_path)

    assert main(["enrich", str(tmp_path), "--send"]) == 1
    assert "LLM config is missing" in capsys.readouterr().err


def test_send_enrichment_writes_validated_annotation_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _analyzed_project(tmp_path)
    config = LogicChartConfig.load(tmp_path)
    flow = model.flows[0]
    node = next(item for item in flow.nodes if item.kind.value == "decision")
    write_logicchart_env(
        logicchart_env_path(tmp_path),
        provider=get_provider("deepseek"),
        model="deepseek-v4-pro",
        api_key="sk-test",
    )
    preview = build_enrichment_preview(
        tmp_path,
        load_model(tmp_path, config),
        config,
        EnrichmentOptions(max_flows=1, max_nodes_per_flow=4),
    )
    calls: list[dict[str, object]] = []

    def fake_call_openai_chat(**kwargs: object) -> str:
        calls.append(kwargs)
        return json.dumps(
            {
                "schema_version": "1.0",
                "model_hash": preview["model_hash"],
                "flows": {flow.id: {"label": "Role authorization gate"}},
                "nodes": {node.id: {"label": "Admin role check"}},
                "findings": {},
                "scopes": {},
            }
        )

    monkeypatch.setattr(llm_enrich, "_call_openai_chat", fake_call_openai_chat)

    annotations = llm_enrich.send_enrichment_request(preview)
    output = llm_enrich.write_enrichment_annotations(tmp_path, model, config, annotations)
    loaded = load_annotations(tmp_path, model, config)

    assert output == annotations_path(tmp_path, config)
    assert loaded.ok
    assert loaded.annotations is not None
    assert loaded.annotations["flows"][flow.id]["label"] == "Role authorization gate"
    assert loaded.annotations["generated_by"]["provider"] == "deepseek"
    assert calls
    assert calls[0]["api_key"] == "sk-test"
    assert calls[0]["request_payload"] == preview["request"]


def test_enrichment_rejects_unknown_provider_output_ids(tmp_path: Path) -> None:
    model = _analyzed_project(tmp_path)
    config = LogicChartConfig.load(tmp_path)

    with pytest.raises(llm_enrich.EnrichmentError, match="missing-flow"):
        llm_enrich.write_enrichment_annotations(
            tmp_path,
            model,
            config,
            {
                "schema_version": "1.0",
                "model_hash": model_hash(model),
                "flows": {"missing-flow": {"label": "Unknown"}},
            },
        )
