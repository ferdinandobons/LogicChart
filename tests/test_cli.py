import json
import os
from pathlib import Path

import pytest

from codedebrief.analysis import project as project_module
from codedebrief.cli import build_parser, main

REMOVED_AGENT_COMMAND_SNIPPETS = (
    "codedebrief query",
    "codedebrief impact",
    "codedebrief explain",
    "codedebrief navigate",
    "codedebrief snapshot",
    "codedebrief llm",
    "codedebrief enrich",
    "--api-key-stdin",
)


def _assert_current_agent_instructions(content: str) -> None:
    assert "Prefer the CodeDebrief MCP `agent_context` tool" in content
    assert "returned `workflow_slice`" in content
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
    assert "compact horizontal overview" in content
    assert "full returned `workflow_slice`" in content
    assert "clearest useful subset" in content
    assert "too large, saved externally, truncated" in content
    assert "smaller `token_budget`" in content
    assert "narrower `flow_id`, `symbol`,\n   `current_file`, or `scope`" in content
    assert "hand-building a\n   diagram" in content
    assert "bounded summary" in content
    assert "can be expanded" in content
    assert "short high-level written flow" in content
    assert "happy path first" in content
    assert "only the branches needed by the request" in content
    assert "language-friendly" in content
    assert "technical block labels and the high-level written flow" in content
    assert "language of the user's request" in content
    assert "simplify labels and\n   written flow" in content
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
    assert "`expand_slice`, `workflow_path`, `snapshot_slice`" in content
    assert "codedebrief view ..." in content
    assert "codedebrief <command> --help" in content
    assert "provider keys" in content
    assert "`codedebrief setup <target>` updates only that target's files" in content
    assert "After code or workflow-relevant changes" in content
    assert "artifacts as part of done" in content
    assert "run `codedebrief update` before finalizing or\n   committing" in content
    assert "codedebrief validate --check-sync" in content
    for snippet in REMOVED_AGENT_COMMAND_SNIPPETS:
        assert snippet not in content


def _assert_codedebrief_skill(content: str) -> None:
    assert content.startswith("---\nname: codedebrief\n")
    assert "`agent_context`" in content
    assert "include_visual=true" in content
    assert "artifacts as part of done for workflow-relevant changes" in content
    assert "MCP `update_codedebrief`" in content
    assert "`codedebrief update`" in content
    assert "`codedebrief validate --check-sync`" in content
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
    assert "compact horizontal overview" in content
    assert "`diagram_hash`" in content
    assert "stable token" in content
    assert "full returned `workflow_slice`" in content
    assert "clearest useful subset" in content
    assert "too large, saved externally, truncated" in content
    assert "smaller\n   `token_budget`" in content
    assert "hand-building a diagram" in content
    assert "low-signal implementation node" in content
    assert "bounded summary" in content
    assert 'short "High-level flow" section' in content
    assert "compact\n   happy-path walkthrough" in content
    assert "human-friendly" in content
    assert "language-friendly" in content
    assert "block labels and the high-level written flow" in content
    assert "language of\n   the user's request" in content
    assert "simplify the labels and\n   written flow" in content
    assert "expand omitted" in content
    assert "related area or deeper path" in content
    assert "synthesize a new Mermaid" in content
    assert "Do not read source files to rebuild" in content
    assert "must not change the displayed nodes, edges, labels, or branches" in content
    assert "never create a replacement Mermaid diagram" in content
    assert "absent" in content
    assert "`workflow_slice` payload" in content
    assert "`viewer_targets` command" in content
    assert "`workflow_slice.presentation` as supporting context" in content
    assert "Do not answer\n   with raw JSON or YAML" in content


def test_top_level_help_prioritizes_flag_light_quickstart() -> None:
    help_text = build_parser().format_help()

    assert "Quick start:" in help_text
    assert "codedebrief setup codex" in help_text
    assert "codedebrief update\n  codedebrief view" in help_text
    assert "codedebrief doctor" in help_text
    assert "codedebrief clear" in help_text
    assert "{setup,update,view,validate,doctor,clear,mcp}" in help_text
    assert "setup-agent" not in help_text
    for removed in (
        "analyze",
        "install",
        "init",
        "llm",
        "enrich",
        "query",
        "impact",
        "explain",
        "navigate",
        "snapshot",
    ):
        assert f"    {removed} " not in help_text
    assert "Add --help after any command" in help_text


def test_command_help_documents_simple_examples(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["setup", "--help"])

    assert exc_info.value.code == 0
    setup_help = capsys.readouterr().out
    assert "Examples:" in setup_help
    assert "codedebrief setup codex" in setup_help
    assert "codedebrief setup claude --source backend/ frontend/" in setup_help
    assert "codedebrief setup claude ../my-app --source backend-api frontend/src" in setup_help
    assert "codedebrief setup claude ../pipeline-map --source ../repo-a ../repo-b" in setup_help
    assert "ask your coding agent ordinary questions" in setup_help


def test_update_nonexistent_path_errors_clearly(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"
    # A missing path must fail with a clear message, not silently report 0 flows.
    assert main(["update", str(missing), "--full"]) == 1
    captured = capsys.readouterr()
    assert "does not exist" in captured.err
    assert "Analyzed 0 files" not in captured.out
    assert not missing.exists()


def test_cli_catches_oserror_instead_of_leaking_a_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")

    import codedebrief.cli as cli_module

    def boom(*_args: object, **_kwargs: object) -> int:
        raise PermissionError("Permission denied")

    monkeypatch.setattr(cli_module, "_analyze", boom)
    # A PermissionError (an OSError subclass) surfaces as a clean failure, not a traceback.
    assert main(["update", str(tmp_path), "--full"]) == 1
    output = capsys.readouterr().err
    assert "CodeDebrief command FAILED" in output
    assert "Error: Permission denied" in output
    assert "codedebrief doctor --errors" in output
    error_log = tmp_path / "codedebrief-out" / "codedebrief.errors.jsonl"
    events = [json.loads(line) for line in error_log.read_text(encoding="utf-8").splitlines()]
    assert events[-1]["command"] == "update"
    assert events[-1]["code"] == "command_failed"
    assert events[-1]["message"] == "Permission denied"


def test_cli_doctor_can_show_and_clear_saved_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import codedebrief.cli as cli_module

    def boom(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError("bad generated model")

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(cli_module, "_analyze", boom)
        assert main(["update", str(tmp_path), "--full"]) == 1
    capsys.readouterr()

    assert main(["doctor", str(tmp_path), "--errors"]) == 0
    output = capsys.readouterr().out
    assert "CodeDebrief errors" in output
    assert "bad generated model" in output
    assert "update/command_failed" in output

    assert main(["doctor", str(tmp_path), "--errors", "--clear"]) == 0
    assert "errors cleared" in capsys.readouterr().out
    assert main(["doctor", str(tmp_path), "--errors", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0


def test_update_full_flag_dispatches_to_full_analysis(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import codedebrief.cli as cli_module

    calls: list[dict[str, object]] = []

    def fake_analyze(root: Path, **kwargs: object) -> int:
        calls.append({"root": root, **kwargs})
        return 0

    monkeypatch.setattr(cli_module, "_analyze", fake_analyze)

    assert main(["update", str(tmp_path), "--full", "--no-html"]) == 0
    assert calls == [
        {
            "root": tmp_path,
            "full": True,
            "include_html": False,
            "profile": None,
            "verbose": False,
        }
    ]


def test_cli_update_and_view(tmp_path: Path, capsys: object) -> None:
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

    assert main(["update", str(tmp_path), "--full"]) == 0
    assert (tmp_path / "codedebrief-out" / "codedebrief.json").exists()
    assert (tmp_path / "codedebrief-out" / "codedebrief.hash.json").exists()
    output = capsys.readouterr().out
    assert "CodeDebrief update" in output
    assert "Status: OK - refreshed" in output
    assert "Status: OK" in output
    assert "Cache:" in output
    assert "Output:" in output
    assert "Next: codedebrief view | codedebrief validate --check-sync" in output
    assert main(["update", str(tmp_path)]) == 0
    assert main(["view", str(tmp_path), "--render-only"]) == 0
    output = capsys.readouterr().out
    assert "CodeDebrief view" in output
    assert "Status: OK" in output
    assert "Next steps:" in output


def test_cli_update_does_not_rewrite_unchanged_artifacts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "main.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")

    assert main(["update", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    json_path = tmp_path / "codedebrief-out" / "codedebrief.json"
    markdown_path = tmp_path / "codedebrief-out" / "codedebrief.md"
    hash_path = tmp_path / "codedebrief-out" / "codedebrief.hash.json"
    old_time = 1_700_000_000_000_000_000
    os.utime(json_path, ns=(old_time, old_time))
    os.utime(markdown_path, ns=(old_time, old_time))
    os.utime(hash_path, ns=(old_time, old_time))

    assert main(["update", str(tmp_path), "--no-html"]) == 0

    assert json_path.stat().st_mtime_ns == old_time
    assert markdown_path.stat().st_mtime_ns == old_time
    assert hash_path.stat().st_mtime_ns == old_time
    assert "Cache: 1 hits, 0 changed, 0 deleted." in capsys.readouterr().out


def test_cli_update_rewrites_when_artifact_format_changes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "main.py"
    source.write_text("def f():\n    return 1\n", encoding="utf-8")

    assert main(["update", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()
    json_path = tmp_path / "codedebrief-out" / "codedebrief.json"
    markdown_path = tmp_path / "codedebrief-out" / "codedebrief.md"
    hash_path = tmp_path / "codedebrief-out" / "codedebrief.hash.json"
    old_time = 1_700_000_000_000_000_000
    os.utime(json_path, ns=(old_time, old_time))
    os.utime(markdown_path, ns=(old_time, old_time))
    os.utime(hash_path, ns=(old_time, old_time))
    monkeypatch.setattr(project_module, "ARTIFACT_FORMAT_VERSION", "test-next")

    assert main(["update", str(tmp_path), "--no-html"]) == 0

    assert json_path.stat().st_mtime_ns != old_time
    assert markdown_path.stat().st_mtime_ns != old_time
    assert hash_path.stat().st_mtime_ns != old_time
    assert "Cache: 1 hits, 0 changed, 0 deleted." in capsys.readouterr().out


@pytest.mark.parametrize(
    "command",
    [
        "setup-agent",
        "analyze",
        "install",
        "init",
        "llm",
        "enrich",
        "query",
        "impact",
        "explain",
        "navigate",
        "snapshot",
    ],
)
def test_removed_agent_commands_are_not_public_cli(command: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args([command])

    assert exc_info.value.code == 2


def test_cli_clear_removes_codedebrief_files_and_preserves_user_content(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "codedebrief.toml").write_text(
        '[codedebrief]\noutput_dir = "custom-codedebrief-out"\n',
        encoding="utf-8",
    )
    (tmp_path / ".codedebriefignore").write_text("scratch/**\n", encoding="utf-8")
    (tmp_path / "codedebrief-out").mkdir()
    (tmp_path / "codedebrief-out" / "codedebrief.json").write_text("{}", encoding="utf-8")
    (tmp_path / "custom-codedebrief-out").mkdir()
    (tmp_path / "custom-codedebrief-out" / "codedebrief.json").write_text("{}", encoding="utf-8")
    (tmp_path / ".agents" / "skills" / "codedebrief").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "codedebrief" / "SKILL.md").write_text(
        "managed skill\n", encoding="utf-8"
    )
    (tmp_path / ".claude" / "skills" / "codedebrief").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "codedebrief" / "SKILL.md").write_text(
        "managed skill\n", encoding="utf-8"
    )
    (tmp_path / ".gemini" / "skills" / "codedebrief").mkdir(parents=True)
    (tmp_path / ".gemini" / "skills" / "codedebrief" / "SKILL.md").write_text(
        "managed skill\n", encoding="utf-8"
    )
    (tmp_path / "AGENTS.md").write_text(
        (
            "Project notes\n\n"
            "<!-- codedebrief:instructions:start -->\nmanaged\n"
            "<!-- codedebrief:instructions:end -->\n\n"
            "Keep this note\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / "CLAUDE.md").write_text(
        "<!-- codedebrief:instructions:start -->\nmanaged\n<!-- codedebrief:instructions:end -->\n",
        encoding="utf-8",
    )
    (tmp_path / ".cursor" / "rules").mkdir(parents=True)
    (tmp_path / ".cursor" / "rules" / "codedebrief.mdc").write_text(
        "managed cursor rule\n", encoding="utf-8"
    )
    (tmp_path / ".codex").mkdir()
    (tmp_path / ".codex" / "config.toml").write_text(
        (
            "user = true\n\n"
            "# codedebrief:mcp-config:start\n"
            "[mcp_servers.codedebrief]\n"
            'command = "codedebrief"\n'
            "# codedebrief:mcp-config:end\n"
        ),
        encoding="utf-8",
    )
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "codedebrief": {"command": "codedebrief"},
                    "other": {"command": "other"},
                }
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / ".cursor" / "mcp.json").write_text(
        json.dumps({"mcpServers": {"codedebrief": {"command": "codedebrief"}}}),
        encoding="utf-8",
    )
    (tmp_path / ".gemini" / "settings.json").write_text(
        json.dumps(
            {
                "theme": "dark",
                "mcpServers": {
                    "codedebrief": {"command": "codedebrief"},
                    "other": {"command": "other"},
                },
            }
        ),
        encoding="utf-8",
    )

    assert main(["clear", str(tmp_path), "--yes"]) == 0

    output = capsys.readouterr().out
    assert "CodeDebrief clear" in output
    assert "Status: OK - CodeDebrief files removed from this folder." in output
    assert not (tmp_path / "codedebrief.toml").exists()
    assert not (tmp_path / ".codedebriefignore").exists()
    assert not (tmp_path / "codedebrief-out").exists()
    assert not (tmp_path / "custom-codedebrief-out").exists()
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".claude").exists()
    assert not (tmp_path / ".cursor" / "rules" / "codedebrief.mdc").exists()
    assert not (tmp_path / ".cursor" / "mcp.json").exists()
    assert not (tmp_path / "CLAUDE.md").exists()
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == (
        "Project notes\n\nKeep this note\n"
    )
    assert (tmp_path / ".codex" / "config.toml").read_text(encoding="utf-8") == ("user = true\n")
    claude_payload = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    gemini_payload = json.loads((tmp_path / ".gemini" / "settings.json").read_text())
    assert "codedebrief" not in claude_payload["mcpServers"]
    assert claude_payload["mcpServers"]["other"]["command"] == "other"
    assert gemini_payload["theme"] == "dark"
    assert "codedebrief" not in gemini_payload["mcpServers"]


def test_cli_clear_does_not_delete_project_root_when_output_dir_is_root(
    tmp_path: Path,
) -> None:
    (tmp_path / "codedebrief.toml").write_text('[codedebrief]\noutput_dir = "."\n')
    (tmp_path / "app.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    for artifact_name in (
        "codedebrief.json",
        "codedebrief.md",
        "codedebrief.hash.json",
        "codedebrief.html",
    ):
        (tmp_path / artifact_name).write_text("managed\n", encoding="utf-8")

    assert main(["clear", str(tmp_path), "--yes"]) == 0

    assert tmp_path.exists()
    assert (tmp_path / "app.py").exists()
    assert not (tmp_path / "codedebrief.toml").exists()
    for artifact_name in (
        "codedebrief.json",
        "codedebrief.md",
        "codedebrief.hash.json",
        "codedebrief.html",
    ):
        assert not (tmp_path / artifact_name).exists()


def test_cli_clear_removes_default_output_dir_without_listing_nested_config_twice(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output_dir = tmp_path / "codedebrief-out"
    output_dir.mkdir()
    (output_dir / "codedebrief.toml").write_text("[codedebrief]\n", encoding="utf-8")
    (output_dir / "codedebrief.json").write_text("{}", encoding="utf-8")

    assert main(["clear", str(tmp_path), "--yes"]) == 0

    output = capsys.readouterr().out
    assert not output_dir.exists()
    assert "- artifact directory:" in output
    assert f"- config file: {output_dir / 'codedebrief.toml'}" not in output


def test_cli_clear_requires_confirmation_without_yes_in_noninteractive_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = tmp_path / "codedebrief.toml"
    config.write_text("[codedebrief]\n", encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda _prompt: (_ for _ in ()).throw(EOFError))

    assert main(["clear", str(tmp_path)]) == 1

    assert config.exists()
    assert "confirmation required" in capsys.readouterr().out


def test_cli_validate_and_profiles(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    source = tmp_path / "src" / "codedebrief" / "main.py"
    source.parent.mkdir(parents=True)
    source.write_text(
        "def analyze_source(path):\n    if path:\n        return path\n    return None\n",
        encoding="utf-8",
    )

    assert main(["update", str(tmp_path), "--profile", "self", "--full", "--no-html"]) == 0
    assert (tmp_path / "codedebrief-out" / "self" / "codedebrief.json").exists()

    assert main(["validate", str(tmp_path), "--profile", "self"]) == 0
    assert "Status: OK - artifacts are valid." in capsys.readouterr().out


@pytest.mark.parametrize(
    ("agent", "instruction_path", "skill_path", "mcp_path", "display"),
    [
        (
            "codex",
            Path("AGENTS.md"),
            Path(".agents/skills/codedebrief/SKILL.md"),
            Path(".codex/config.toml"),
            "Codex",
        ),
        (
            "claude",
            Path("CLAUDE.md"),
            Path(".claude/skills/codedebrief/SKILL.md"),
            Path(".mcp.json"),
            "Claude",
        ),
        (
            "gemini",
            Path("GEMINI.md"),
            Path(".gemini/skills/codedebrief/SKILL.md"),
            Path(".gemini/settings.json"),
            "Gemini",
        ),
        (
            "cursor",
            Path(".cursor/rules/codedebrief.mdc"),
            None,
            Path(".cursor/mcp.json"),
            "Cursor",
        ),
    ],
)
def test_cli_setup_agent_can_write_config_instructions_mcp_and_artifacts(
    agent: str,
    instruction_path: Path,
    skill_path: Path | None,
    mcp_path: Path | None,
    display: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    instruction_paths = [
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("GEMINI.md"),
        Path(".cursor/rules/codedebrief.mdc"),
    ]
    skill_paths = [
        Path(".agents/skills/codedebrief/SKILL.md"),
        Path(".claude/skills/codedebrief/SKILL.md"),
        Path(".gemini/skills/codedebrief/SKILL.md"),
    ]

    assert main(["setup", agent, str(tmp_path), "--no-html"]) == 0
    assert (tmp_path / "codedebrief-out" / "codedebrief.toml").exists()
    assert not (tmp_path / "codedebrief.toml").exists()
    assert (tmp_path / instruction_path).exists()
    for path in instruction_paths:
        if path == instruction_path:
            assert (tmp_path / path).exists()
            _assert_current_agent_instructions((tmp_path / path).read_text(encoding="utf-8"))
        else:
            assert not (tmp_path / path).exists()
    for path in skill_paths:
        if path == skill_path:
            assert (tmp_path / path).exists()
            _assert_codedebrief_skill((tmp_path / path).read_text(encoding="utf-8"))
        else:
            assert not (tmp_path / path).exists()
    if mcp_path is not None:
        assert (tmp_path / mcp_path).exists()
    else:
        assert not (tmp_path / ".codex" / "config.toml").exists()
        assert not (tmp_path / ".mcp.json").exists()
        assert not (tmp_path / ".cursor" / "mcp.json").exists()
    assert (tmp_path / "codedebrief-out" / "codedebrief.json").exists()
    assert (tmp_path / "codedebrief-out" / "codedebrief.md").exists()
    agents_text = (tmp_path / instruction_path).read_text(encoding="utf-8")
    _assert_current_agent_instructions(agents_text)
    output = capsys.readouterr().out
    assert "CodeDebrief setup" in output
    assert f"Agent: {display}" in output
    assert "- Config created:" in output
    assert "- Agent integration updated:" in output
    assert "- Artifacts refreshed:" in output
    assert "- Runtime checked:" in output
    assert "- Artifacts valid" in output
    assert "Ready: CodeDebrief is configured for your coding agent." in output
    assert "Next steps:" in output

    assert main(["setup", agent, str(tmp_path), "--no-html"]) == 0
    assert "already up to date" in capsys.readouterr().out


def test_cli_setup_source_roots_limit_initial_analysis(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    scratch = tmp_path / "scratch"
    backend.mkdir()
    frontend.mkdir()
    scratch.mkdir()
    (backend / "api.py").write_text("def api():\n    return 1\n", encoding="utf-8")
    (frontend / "app.ts").write_text("export function app() { return 1; }\n", encoding="utf-8")
    (scratch / "ignored.py").write_text("def ignored():\n    return 1\n", encoding="utf-8")

    assert (
        main(["setup", "claude", str(tmp_path), "--source", "backend", "frontend", "--no-html"])
        == 0
    )

    config_text = (tmp_path / "codedebrief-out" / "codedebrief.toml").read_text(encoding="utf-8")
    artifact = json.loads((tmp_path / "codedebrief-out" / "codedebrief.json").read_text())
    analyzed_paths = {item["path"] for item in artifact["files"]}
    output = capsys.readouterr().out

    assert 'source_roots = ["backend", "frontend"]' in config_text
    assert analyzed_paths == {"backend/api.py", "frontend/app.ts"}
    assert "Sources: backend, frontend" in output
    assert "- Source roots set: backend, frontend" in output
    assert "- Artifacts refreshed: 2 files" in output


def test_cli_setup_accepts_sibling_repo_source_roots(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = tmp_path / "pipeline-map"
    service_a = tmp_path / "service-a"
    service_b = tmp_path / "service-b"
    workspace.mkdir()
    service_a.mkdir()
    service_b.mkdir()
    (service_a / "extract.py").write_text("def extract():\n    return 1\n", encoding="utf-8")
    (service_b / "load.ts").write_text("export function load() { return 1; }\n", encoding="utf-8")

    assert (
        main(
            [
                "setup",
                "claude",
                str(workspace),
                "--source",
                "../service-a",
                "../service-b",
                "--no-html",
            ]
        )
        == 0
    )

    config_text = (workspace / "codedebrief-out" / "codedebrief.toml").read_text(encoding="utf-8")
    artifact = json.loads((workspace / "codedebrief-out" / "codedebrief.json").read_text())
    analyzed_paths = {item["path"] for item in artifact["files"]}
    output = capsys.readouterr().out

    assert 'source_roots = ["../service-a", "../service-b"]' in config_text
    assert analyzed_paths == {"../service-a/extract.py", "../service-b/load.ts"}
    assert "Sources: ../service-a, ../service-b" in output
    assert "- Source roots set: ../service-a, ../service-b" in output
    assert "- Artifacts refreshed: 2 files" in output


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
