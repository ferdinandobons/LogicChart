import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.analysis.registry import supported_language_ids
from logicchart.artifacts import load_model, output_paths, write_artifacts
from logicchart.config import LogicChartConfig
from logicchart.install import (
    END,
    LOCAL_NOTES_END,
    LOCAL_NOTES_START,
    START,
    install_agent_instructions,
    install_agent_skill,
    install_mcp_config,
)
from logicchart.query import impact_model, query_model
from logicchart.util import read_json
from logicchart.validation import (
    schema_file_language_ids,
    schema_language_ids,
    validate_logicchart,
)

REMOVED_AGENT_COMMAND_SNIPPETS = (
    "logicchart query",
    "logicchart impact",
    "logicchart explain",
    "logicchart navigate",
    "logicchart snapshot",
    "logicchart llm",
    "logicchart enrich",
    "--api-key-stdin",
)


def _assert_current_agent_instructions(content: str) -> None:
    assert "Prefer the LogicChart MCP `agent_context` tool" in content
    assert "When the user asks to show a workflow, flusso, visual flow, canvas" in content
    assert "canonical Mermaid visual" in content
    assert "`snapshot.svg`" in content
    assert "`include_svg=false`" in content
    assert "`artifact.mermaid_path`" in content
    assert "`artifact.mermaid_markdown_path`" in content
    assert "`artifact.mermaid_open_command`" in content
    assert "Mermaid would appear as a raw code block" in content
    assert "Do not paste a long Mermaid code block as the primary visual" in content
    assert "raw or copyable Mermaid" in content
    assert "Do not render\n   `snapshot.svg` inline by default" in content
    assert "`workflow_slice.presentation.canonical_visual.diagram` exactly" in content
    assert "top-to-bottom" in content
    assert "vertical/top-to-bottom" in content
    assert "horizontal" in content
    assert "summaries" in content
    assert "full returned `workflow_slice`" in content
    assert "clearest useful subset" in content
    assert "too large, saved externally, truncated" in content
    assert "smaller `token_budget`" in content
    assert "narrower `flow_id`, `symbol`,\n   `current_file`, or `scope`" in content
    assert "hand-building a\n   diagram" in content
    assert "bounded summary" in content
    assert "can be expanded" in content
    assert "language-friendly" in content
    assert "language of the user's request" in content
    assert "simplify labels" in content
    assert "omitted nodes/branches/adjacent flows" in content
    assert "related area" in content
    assert "synthesize a new Mermaid" in content
    assert "Do not read source\n   files to rebuild" in content
    assert "must not change displayed\n   nodes, edges, labels, or branches" in content
    assert "instead of creating\n   a replacement Mermaid diagram" in content
    assert "absent" in content
    assert "`workflow_slice` payload" in content
    assert "raw JSON" in content
    assert "YAML" in content
    assert "explicitly requested" in content
    assert "requested" in content
    assert "logicchart view ..." in content
    assert "provider keys" in content
    assert (
        "`logicchart setup-agent <target>` updates only that target's instruction file" in content
    )
    for snippet in REMOVED_AGENT_COMMAND_SNIPPETS:
        assert snippet not in content


def _assert_logicchart_skill(content: str) -> None:
    assert content.startswith("---\nname: logicchart\n")
    assert "description: Use when answering codebase logic" in content
    assert "workflow/flusso" in content
    assert "`agent_context`" in content
    assert "`workflow_slice`" in content
    assert "include_visual=true" in content
    assert "`snapshot_slice`" in content
    assert "`include_svg=false`" in content
    assert "`artifact.mermaid_path`" in content
    assert "`artifact.mermaid_markdown_path`" in content
    assert "`artifact.mermaid_open_command`" in content
    assert "Mermaid would appear as a raw code\n   block" in content
    assert "Do not paste a long\n   Mermaid code block as the primary visual" in content
    assert "raw or\n   copyable Mermaid" in content
    assert "Do not render `snapshot.svg` inline by default" in content
    assert "`workflow_slice.presentation.canonical_visual.diagram` exactly" in content
    assert "top-to-bottom" in content
    assert "vertical/top-to-bottom" in content
    assert "horizontal" in content
    assert "summaries" in content
    assert "`diagram_hash`" in content
    assert "stable token" in content
    assert "full returned `workflow_slice`" in content
    assert "clearest useful subset" in content
    assert "too large, saved externally, truncated" in content
    assert "smaller\n   `token_budget`" in content
    assert "hand-building a diagram" in content
    assert "low-signal implementation node" in content
    assert "bounded summary" in content
    assert "human-friendly" in content
    assert "language-friendly" in content
    assert "language of the user's request" in content
    assert "simplify the labels" in content
    assert "expand omitted" in content
    assert "related area or deeper path" in content
    assert "synthesize a new Mermaid" in content
    assert "Do not read source files to rebuild" in content
    assert "must not change the displayed nodes, edges, labels, or branches" in content
    assert "never create a replacement Mermaid diagram" in content
    assert "absent" in content
    assert "`workflow_slice` payload" in content
    assert "workflow_slice.handle.flow_ids" in content
    assert "`viewer_targets` command" in content
    assert "`workflow_slice.presentation` as supporting context" in content
    assert "Do not answer with raw JSON or YAML" in content
    assert "POTENTIAL_GAP" not in content


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
    html = html_path.read_text(encoding="utf-8")
    assert "<title>LogicChart</title>" in html
    assert 'id="typedViewerHost"' in html
    assert "Decision flow index" not in html
    assert load_model(tmp_path).flows
    schema = read_json(Path(__file__).parents[1] / "schema" / "logic-flow.schema.json")
    artifact = read_json(json_path)
    Draft202012Validator(schema).validate(artifact)
    assert schema_language_ids(schema) == supported_language_ids()
    assert schema_file_language_ids(schema) == supported_language_ids()
    assert artifact["root"] == "."
    assert str(tmp_path) not in markdown_path.read_text(encoding="utf-8")
    assert str(tmp_path) in html

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
    _assert_current_agent_instructions(contents)


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


def test_artifact_uses_comprehension_schema_without_review_queue(tmp_path: Path) -> None:
    (tmp_path / "orders.py").write_text(
        "def route(order):\n"
        "    if order.status == 'draft':\n"
        "        return draft(order)\n"
        "    elif order.status == 'paid':\n"
        "        return paid(order)\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    artifact = result.model.to_dict()
    schema = read_json(Path(__file__).parents[1] / "schema" / "logic-flow.schema.json")

    Draft202012Validator(schema).validate(artifact)
    assert artifact["schema_version"] == "2.0"
    assert "quality" in artifact["metadata"]
    assert "quality" in schema["$defs"]["project_metadata"]["properties"]


def test_install_on_a_fresh_dir_is_idempotent(tmp_path: Path) -> None:
    # A fresh plain-markdown agent file (no existing block) must reach a fixed point on
    # the first install: the second run changes nothing and reports nothing.
    first = install_agent_instructions(tmp_path, "all")
    expected_targets = [
        tmp_path / "AGENTS.md",
        tmp_path / "CLAUDE.md",
        tmp_path / "GEMINI.md",
        tmp_path / ".cursor" / "rules" / "logicchart.mdc",
    ]
    assert first == expected_targets
    for target in first:
        content = target.read_text(encoding="utf-8")
        assert content.count(START) == 1
        assert content.count(END) == 1
        _assert_current_agent_instructions(content)
    assert (
        first[-1]
        .read_text(encoding="utf-8")
        .startswith("---\ndescription: Keep LogicChart synchronized\nalwaysApply: true\n---\n\n")
    )

    contents_after_first = {target: target.read_text(encoding="utf-8") for target in first}

    second = install_agent_instructions(tmp_path, "all")
    assert second == []  # nothing was rewritten the second time
    for target, content in contents_after_first.items():
        # The on-disk content is byte-identical after the no-op second run.
        assert target.read_text(encoding="utf-8") == content


def test_install_agent_skill_writes_provider_native_skill_files(tmp_path: Path) -> None:
    codex_skill = tmp_path / ".agents" / "skills" / "logicchart" / "SKILL.md"
    claude_skill = tmp_path / ".claude" / "skills" / "logicchart" / "SKILL.md"

    changed = install_agent_skill(tmp_path, "codex")

    assert changed == [codex_skill]
    _assert_logicchart_skill(codex_skill.read_text(encoding="utf-8"))
    assert not claude_skill.exists()
    assert install_agent_skill(tmp_path, "codex") == []

    changed = install_agent_skill(tmp_path, "claude")

    assert changed == [claude_skill]
    _assert_logicchart_skill(claude_skill.read_text(encoding="utf-8"))
    assert install_agent_skill(tmp_path, "claude") == []


def test_install_agent_skill_all_writes_supported_skill_files_only(tmp_path: Path) -> None:
    expected_targets = [
        tmp_path / ".agents" / "skills" / "logicchart" / "SKILL.md",
        tmp_path / ".claude" / "skills" / "logicchart" / "SKILL.md",
    ]

    changed = install_agent_skill(tmp_path, "all")

    assert changed == expected_targets
    for target in expected_targets:
        _assert_logicchart_skill(target.read_text(encoding="utf-8"))
    assert not (tmp_path / ".gemini" / "skills" / "logicchart" / "SKILL.md").exists()
    assert not (tmp_path / ".cursor" / "skills" / "logicchart" / "SKILL.md").exists()
    assert install_agent_skill(tmp_path, "all") == []


def test_install_agent_skill_noops_for_agents_without_native_skill_path(tmp_path: Path) -> None:
    assert install_agent_skill(tmp_path, "gemini") == []
    assert install_agent_skill(tmp_path, "cursor") == []
    assert not (tmp_path / ".gemini").exists()
    assert not (tmp_path / ".cursor" / "skills").exists()


def test_install_rejects_unknown_agent_skill_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown agent skill target"):
        install_agent_skill(tmp_path, "unknown-agent")


def test_install_rejects_unknown_agent_instruction_target(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown agent instruction target"):
        install_agent_instructions(tmp_path, "unknown-agent")


def test_install_preserves_project_local_notes(tmp_path: Path) -> None:
    changed = install_agent_instructions(tmp_path, "codex")
    assert changed == [tmp_path / "AGENTS.md"]
    target = tmp_path / "AGENTS.md"
    content = target.read_text(encoding="utf-8")
    local_note = (
        "For local real-world regression checks:\n\n"
        "1. Keep `examples/Certifexp/` private and untracked.\n"
    )
    target.write_text(
        content.replace(
            f"{LOCAL_NOTES_START}\n"
            "<!-- Add project-specific local notes here. This section is preserved by "
            "`logicchart setup-agent`. -->\n"
            f"{LOCAL_NOTES_END}",
            f"{LOCAL_NOTES_START}\n{local_note}{LOCAL_NOTES_END}",
        ),
        encoding="utf-8",
    )

    changed = install_agent_instructions(tmp_path, "codex")

    assert changed == []
    updated = target.read_text(encoding="utf-8")
    assert local_note.strip() in updated
    assert updated.count(LOCAL_NOTES_START) == 1
    assert updated.count(LOCAL_NOTES_END) == 1


def test_install_all_refreshes_every_agent_target_and_preserves_local_notes(
    tmp_path: Path,
) -> None:
    install_agent_instructions(tmp_path, "all")
    targets = {
        "codex": tmp_path / "AGENTS.md",
        "claude": tmp_path / "CLAUDE.md",
        "gemini": tmp_path / "GEMINI.md",
        "cursor": tmp_path / ".cursor" / "rules" / "logicchart.mdc",
    }
    local_notes = {
        "codex": "Codex local note: keep private fixtures untracked.",
        "claude": "Claude local note: preserve project-specific workflow notes.",
        "gemini": "Gemini local note: keep generated examples out of commits.",
        "cursor": "Cursor local note: keep this rule project-scoped.",
    }

    for name, target in targets.items():
        content = target.read_text(encoding="utf-8")
        target.write_text(
            content.replace(
                f"{LOCAL_NOTES_START}\n"
                "<!-- Add project-specific local notes here. This section is preserved by "
                "`logicchart setup-agent`. -->\n"
                f"{LOCAL_NOTES_END}",
                f"{LOCAL_NOTES_START}\n{local_notes[name]}\n{LOCAL_NOTES_END}",
            ),
            encoding="utf-8",
        )

    changed = install_agent_instructions(tmp_path, "all")

    assert changed == []
    for name, target in targets.items():
        content = target.read_text(encoding="utf-8")
        _assert_current_agent_instructions(content)
        assert local_notes[name] in content
        assert content.count(LOCAL_NOTES_START) == 1
        assert content.count(LOCAL_NOTES_END) == 1


def test_install_migrates_legacy_local_notes(tmp_path: Path) -> None:
    target = tmp_path / "AGENTS.md"
    target.write_text(
        f"""{START}
## LogicChart

For viewer/UI changes:

1. Check the generated demo viewer with a cache-buster URL.

For local real-world regression checks:

1. Keep `examples/Certifexp/` private and untracked.
2. Do not commit Certifexp source or generated artifacts.

Legacy LogicChart instructions outside local notes should be replaced.
{END}
""",
        encoding="utf-8",
    )

    changed = install_agent_instructions(tmp_path, "codex")

    assert changed == [target]
    updated = target.read_text(encoding="utf-8")
    assert "For local real-world regression checks:" in updated
    assert "Do not commit Certifexp source or generated artifacts." in updated
    assert updated.index(LOCAL_NOTES_START) < updated.index("For local real-world")
    assert updated.index("generated artifacts.") < updated.index(LOCAL_NOTES_END)
    assert "Legacy LogicChart instructions outside local notes should be replaced." not in updated


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
    assert 'default_tools_approval_mode = "approve"' in codex

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
