import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.analysis.registry import supported_language_ids
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.install import END, START, install_agent_instructions, install_mcp_config
from logicchart.query import impact_model, query_model
from logicchart.util import read_json
from logicchart.validation import (
    schema_file_language_ids,
    schema_language_ids,
    validate_logicchart,
)


def test_artifacts_query_impact_and_agent_install(tmp_path: Path) -> None:
    source = tmp_path / "users.py"
    source.write_text(
        """
def get_user(user_id: str):
    user = repository.fetch(user_id)
    if user.status == "suspended":
        return None
    return user
""",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    json_path, markdown_path, html_path = write_artifacts(tmp_path, result.model)

    assert json_path.exists()
    assert markdown_path.exists()
    assert html_path is not None and html_path.exists()
    assert "flowchart TD" in markdown_path.read_text(encoding="utf-8")
    assert "Decision flow index" in html_path.read_text(encoding="utf-8")
    assert load_model(tmp_path).flows
    schema = read_json(Path(__file__).parents[1] / "schema" / "logic-flow.schema.json")
    artifact = read_json(json_path)
    Draft202012Validator(schema).validate(artifact)
    assert schema_language_ids(schema) == supported_language_ids()
    assert schema_file_language_ids(schema) == supported_language_ids()
    assert artifact["root"] == "."
    assert str(tmp_path) not in markdown_path.read_text(encoding="utf-8")
    assert str(tmp_path) in html_path.read_text(encoding="utf-8")

    matches = query_model(result.model, "suspended user")
    assert matches and matches[0].flow.name == "get_user"

    impact = impact_model(result.model, ["users.py"])
    assert impact.directly_impacted

    changed = install_agent_instructions(tmp_path, "codex")
    assert changed == [tmp_path / "AGENTS.md"]
    install_agent_instructions(tmp_path, "codex")
    contents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert contents.count(START) == 1
    assert contents.count(END) == 1


def test_validate_logicchart_reports_ok_for_current_artifact(tmp_path: Path) -> None:
    (tmp_path / "main.go").write_text(
        "package main\n\nfunc route(status string) string {\n"
        "  switch status {\n"
        '  case "ok":\n'
        '    return "ok"\n'
        "  default:\n"
        '    return "fallback"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    json_path, _, _ = write_artifacts(tmp_path, result.model, include_html=False)

    report = validate_logicchart(tmp_path)

    assert report.ok
    assert report.errors == []
    assert report.artifact == str(json_path)


def test_install_on_a_fresh_dir_is_idempotent(tmp_path: Path) -> None:
    # A fresh plain-markdown agent file (no existing block) must reach a fixed point on
    # the first install: the second run changes nothing and reports nothing.
    first = install_agent_instructions(tmp_path, "all")
    assert first  # all four targets were created
    for target in first:
        content = target.read_text(encoding="utf-8")
        assert content.count(START) == 1
        assert content.count(END) == 1

    contents_after_first = {target: target.read_text(encoding="utf-8") for target in first}

    second = install_agent_instructions(tmp_path, "all")
    assert second == []  # nothing was rewritten the second time
    for target, content in contents_after_first.items():
        # The on-disk content is byte-identical after the no-op second run.
        assert target.read_text(encoding="utf-8") == content


def test_install_mcp_config_writes_project_scoped_files(tmp_path: Path) -> None:
    changed = install_mcp_config(tmp_path, "all")

    assert changed == [
        tmp_path / ".codex" / "config.toml",
        tmp_path / ".mcp.json",
        tmp_path / ".cursor" / "mcp.json",
    ]
    codex = (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8")
    assert "[mcp_servers.logicchart]" in codex
    assert 'command = "logicchart"' in codex
    assert f'"{tmp_path}"' in codex
    assert 'default_tools_approval_mode = "prompt"' in codex

    claude = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    cursor = json.loads((tmp_path / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
    for payload in (claude, cursor):
        server = payload["mcpServers"]["logicchart"]
        assert server["command"] == "logicchart"
        assert server["args"] == ["mcp", str(tmp_path)]

    assert install_mcp_config(tmp_path, "all") == []


def test_output_directory_cannot_escape_project(tmp_path: Path) -> None:
    config = LogicChartConfig(output_dir="../outside")

    with pytest.raises(ValueError, match="must stay inside"):
        output_paths(tmp_path, config)
