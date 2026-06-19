import json
from pathlib import Path

import pytest

from logicchart.annotations import annotations_path, model_hash
from logicchart.artifacts import load_model
from logicchart.cli import main
from logicchart.config import LogicChartConfig


def test_analyze_nonexistent_path_errors_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"
    # A missing path must fail with a clear message, not silently report 0 flows.
    assert main(["analyze", str(missing), "--full"]) == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err
    assert "Analyzed 0 files" not in captured.out


def test_cli_catches_oserror_instead_of_leaking_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    import logicchart.cli as cli_module

    def boom(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(cli_module, "_analyze", boom)
    # A PermissionError (an OSError subclass) surfaces as a clean `error:` line, rc 1.
    assert main(["analyze", str(tmp_path), "--full"]) == 1
    assert "error:" in capsys.readouterr().err


def test_update_full_flag_dispatches_to_full_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import logicchart.cli as cli_module

    calls: list[dict[str, object]] = []

    def fake_analyze(root: Path, **kwargs: object) -> int:
        calls.append({"root": root, **kwargs})
        return 0

    monkeypatch.setattr(cli_module, "_analyze", fake_analyze)

    assert main(["update", str(tmp_path), "--full", "--no-html", "--include-gaps"]) == 0
    assert calls == [
        {
            "root": tmp_path,
            "full": True,
            "include_html": False,
            "include_gaps": True,
            "profile": None,
        }
    ]


def test_cli_analyze_query_and_view(tmp_path: Path, capsys: object) -> None:
    source = tmp_path / "main.py"
    source.write_text(
        """
def authorize(user):
    if user.role == "admin":
        return True
    return False
""",
        encoding="utf-8",
    )

    assert main(["analyze", str(tmp_path), "--full"]) == 0
    assert (tmp_path / "logicchart-out" / "logic-flow.json").exists()
    assert main(["query", "admin authorization", "--path", str(tmp_path)]) == 0
    assert main(["view", str(tmp_path), "--render-only"]) == 0


def test_cli_explain_finding_human_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "service.py").write_text(
        """
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    DELETED = "deleted"


def handle(status):
    match status:
        case Status.OPEN:
            return "open"
        case Status.CLOSED:
            return "closed"
""",
        encoding="utf-8",
    )

    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    model = load_model(tmp_path, LogicChartConfig())
    finding = model.findings[0]
    annotations_path(tmp_path).write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model_hash": model_hash(model),
                "findings": {
                    finding.id: {
                        "summary": "Deleted status is missing.",
                        "explanation": "The match covers OPEN and CLOSED only.",
                        "remediation": "Add a DELETED case or explicit fallback.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(["explain", finding.id, "--path", str(tmp_path)]) == 0
    human = capsys.readouterr().out
    assert f"Finding: {finding.id}" in human
    assert "Annotation:" in human
    assert "Deleted status is missing." in human
    assert "Evidence:" in human
    assert "Suggested next actions:" in human
    assert "Guardrail:" in human

    assert main(["explain", finding.id, "--path", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["id"] == finding.id
    assert payload["annotation"]["remediation"] == "Add a DELETED case or explicit fallback."
    assert payload["diagnostic"]["rule_id"] == finding.kind

    assert main(["explain", "missing-finding", "--path", str(tmp_path)]) == 1
    assert "finding not found: missing-finding" in capsys.readouterr().err


def test_cli_navigate_flow_human_and_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "service.py").write_text(
        """
def authorize(user):
    if user.role == "admin":
        return allow()
    return deny()
""",
        encoding="utf-8",
    )

    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    model = load_model(tmp_path, LogicChartConfig())
    flow = next(item for item in model.flows if item.name == "authorize")
    finding = model.findings[0] if model.findings else None
    if finding is not None:
        annotations_path(tmp_path).write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "model_hash": model_hash(model),
                    "findings": {finding.id: {"summary": "Authorization finding note."}},
                }
            ),
            encoding="utf-8",
        )

    assert main(["navigate", flow.id, "--path", str(tmp_path)]) == 0
    human = capsys.readouterr().out
    assert f"Flow: authorize ({flow.id})" in human
    assert "Decision nodes:" in human
    assert "Next tools:" in human

    assert main(["navigate", flow.symbol, "--path", str(tmp_path), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["flow"]["id"] == flow.id
    assert payload["decision_nodes"][0]["label"] == "user.role == 'admin'"
    assert payload["next_tools"]["visual_snapshot"]["tool"] == "get_flow_snapshot"
    if finding is not None:
        assert payload["findings"][0]["annotation"]["summary"] == "Authorization finding note."

    assert main(["navigate", "missing-flow", "--path", str(tmp_path)]) == 1
    assert "flow not found: missing-flow" in capsys.readouterr().err


def test_cli_snapshot_flow_finding_and_impact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "service.py").write_text(
        """
from enum import Enum


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    DELETED = "deleted"


def handle(status):
    match status:
        case Status.OPEN:
            return "open"
        case Status.CLOSED:
            return "closed"
""",
        encoding="utf-8",
    )

    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    model = load_model(tmp_path, LogicChartConfig())
    flow = next(item for item in model.flows if item.name == "handle")
    finding = model.findings[0]

    assert main(["snapshot", "flow", flow.id, "--path", str(tmp_path)]) == 0
    assert "<svg" in capsys.readouterr().out

    assert main(["snapshot", "finding", finding.id, "--path", str(tmp_path), "--json"]) == 0
    finding_payload = json.loads(capsys.readouterr().out)
    assert finding_payload["finding_id"] == finding.id
    assert "Finding context" in finding_payload["svg"]

    assert (
        main(
            [
                "snapshot",
                "subgraph",
                "--path",
                str(tmp_path),
                "--flow",
                flow.id,
                "--finding",
                finding.id,
                "--json",
            ]
        )
        == 0
    )
    subgraph_payload = json.loads(capsys.readouterr().out)
    assert subgraph_payload["flow_ids"] == [flow.id]
    assert subgraph_payload["finding_ids"] == [finding.id]
    assert finding.node_id in subgraph_payload["highlighted_node_ids"]
    assert subgraph_payload["layout"]["engine"] == "static-subgraph-snapshot-v1"
    assert "Subgraph snapshot" in subgraph_payload["svg"]

    output = tmp_path / "impact.svg"
    assert (
        main(
            [
                "snapshot",
                "impact",
                "--path",
                str(tmp_path),
                "--flow",
                flow.id,
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert output.exists()
    assert "Impact snapshot" in output.read_text(encoding="utf-8")
    capsys.readouterr()

    assert (
        main(
            [
                "snapshot",
                "impact",
                "--path",
                str(tmp_path),
                "--flow",
                "missing-flow",
                "--json",
            ]
        )
        == 0
    )
    missing_payload = json.loads(capsys.readouterr().out)
    assert missing_payload["target_flow_ids"] == ["missing-flow"]
    assert missing_payload["unresolved_targets"] == [
        {"type": "flow", "value": "missing-flow", "reason": "not_found"}
    ]
    assert "Unresolved targets: flow:missing-flow" in missing_payload["svg"]

    assert (
        main(
            [
                "snapshot",
                "subgraph",
                "--path",
                str(tmp_path),
                "--flow",
                "missing-flow",
                "--json",
            ]
        )
        == 0
    )
    missing_subgraph = json.loads(capsys.readouterr().out)
    assert missing_subgraph["unresolved_targets"] == [
        {"type": "flow", "value": "missing-flow", "reason": "not_found"}
    ]
    assert "No valid flows matched" in missing_subgraph["svg"]

    assert main(["snapshot", "flow", flow.id, "--path", str(tmp_path), "--format", "png"]) == 1
    assert "Unsupported snapshot format: png" in capsys.readouterr().err


def test_cli_validate_and_profiles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "src" / "logicchart" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def analyze_source(path):\n    if path:\n        return path\n    return None\n",
        encoding="utf-8",
    )

    assert main(["analyze", str(tmp_path), "--profile", "self", "--full", "--no-html"]) == 0
    assert (tmp_path / "logicchart-out" / "self" / "logic-flow.json").exists()

    assert main(["validate", str(tmp_path), "--profile", "self"]) == 0
    assert "validation OK" in capsys.readouterr().out

    assert (
        main(
            [
                "query",
                "logicchart analyze source",
                "--path",
                str(tmp_path),
                "--profile",
                "self",
                "--language",
                "python",
            ]
        )
        == 0
    )
    assert "analyze_source" in capsys.readouterr().out


def test_cli_validate_reports_absent_annotation_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    assert main(["validate", str(tmp_path), "--annotations", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["annotations"]["status"] == "absent"


def test_cli_install_can_write_mcp_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["install", str(tmp_path), "--platform", "codex", "--mcp-config", "codex"]) == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert (tmp_path / ".codex" / "config.toml").exists()
    assert "logicchart explain <finding-id>" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "logicchart navigate <flow-id>" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "logicchart snapshot flow <flow-id>" in (tmp_path / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "logicchart <command> --help" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "logicchart llm setup --help" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "logicchart enrich --help" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "logicchart enrich --dry-run --json" in (tmp_path / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert "--api-key-stdin" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Updated" in capsys.readouterr().out

    assert main(["install", str(tmp_path), "--platform", "codex", "--mcp-config", "codex"]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_cli_doctor_reports_active_install(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["package_version"] != "not installed"
    assert payload["missing_dependencies"] == []
    assert "python" in payload["language_capabilities"]["supported_languages"]
    assert "typescript" in payload["language_capabilities"]["supported_languages"]
    assert payload["language_capabilities"]["feature_count"] >= 10
    assert payload["language_capabilities"]["limitation_note_count"] > 0
