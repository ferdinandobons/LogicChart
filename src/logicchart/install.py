from __future__ import annotations

import json
import re
from pathlib import Path

START = "<!-- logicchart:instructions:start -->"
END = "<!-- logicchart:instructions:end -->"
MCP_CONFIG_TARGETS = ("codex", "claude", "cursor")
CODEX_MCP_START = "# logicchart:mcp-config:start"
CODEX_MCP_END = "# logicchart:mcp-config:end"

INSTRUCTION_BLOCK = f"""{START}
## LogicChart

This project uses LogicChart to keep decision flows synchronized with the source code.

For codebase questions about behavior, decisions, missing cases, or change impact:

1. Prefer `logicchart query "<question>"` before broad file-by-file searches.
2. Use `logicchart impact [changed files...]` before implementing a substantial change.
3. Review `logicchart-out/logic-flow.md` and any related `POTENTIAL_GAP` findings.
4. Use `logicchart explain <finding-id>` before treating a logical finding as actionable.
5. Use `logicchart navigate <flow-id>` to inspect callers, callees, decisions, and findings.
6. Use `logicchart snapshot flow <flow-id>` when visual flow context would help.

When helping a user set up or learn LogicChart:

1. Start with `logicchart --help`, then use `logicchart <command> --help` for the specific
   command you plan to run or recommend.
2. Use `logicchart doctor` when install, dependency, or parser capability issues are
   unclear.
3. For optional LLM setup, use `logicchart llm providers`, `logicchart llm setup --help`,
   `logicchart llm show`, and `logicchart enrich --help`; prefer `--api-key-stdin`,
   review `logicchart enrich --dry-run --json` or `logicchart enrich --preview --json`
   output before `--send`, and never print or commit keys.

After a substantial code change:

1. Run `logicchart impact`.
2. Review every affected entry point and caller flow.
3. Run `logicchart update`; use `logicchart update --full` after analyzer upgrades or
   when cached file models should be ignored.
4. Commit synchronized changes to:
   - `logicchart-out/logic-flow.json`
   - `logicchart-out/logic-flow.md`

For viewer/UI changes:

1. Run `npm run viewer:typecheck`, `npm run viewer:test`, and `npm run viewer:build`.
2. Regenerate HTML artifacts with `logicchart update` and
   `logicchart view examples/demo --render-only --no-open`.
3. Check the generated demo viewer with a cache-buster URL.

Do not present inferred findings as confirmed bugs. LogicChart marks syntax-backed facts as
`VERIFIED`, deterministic heuristics as `INFERRED`, and review candidates as `POTENTIAL_GAP`.
{END}
"""


def install_all(root: Path, platform: str = "all", mcp_config: str = "none") -> list[Path]:
    changed = install_agent_instructions(root, platform)
    if mcp_config != "none":
        changed.extend(install_mcp_config(root, mcp_config))
    return changed


def install_agent_instructions(root: Path, platform: str = "all") -> list[Path]:
    targets: list[Path] = []
    if platform in {"all", "codex"}:
        targets.append(root / "AGENTS.md")
    if platform in {"all", "claude"}:
        targets.append(root / "CLAUDE.md")
    if platform in {"all", "gemini"}:
        targets.append(root / "GEMINI.md")
    if platform in {"all", "cursor"}:
        targets.append(root / ".cursor" / "rules" / "logicchart.mdc")

    changed: list[Path] = []
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        updated = _upsert(existing, INSTRUCTION_BLOCK)
        if target.suffix == ".mdc" and not updated.startswith("---"):
            frontmatter = (
                "---\ndescription: Keep LogicChart synchronized\nalwaysApply: true\n---\n\n"
            )
            updated = frontmatter + updated
        if updated != existing:
            target.write_text(updated, encoding="utf-8")
            changed.append(target)
    return changed


def install_mcp_config(root: Path, target: str = "all") -> list[Path]:
    root = root.resolve()
    targets = MCP_CONFIG_TARGETS if target == "all" else (target,)
    unknown = set(targets) - set(MCP_CONFIG_TARGETS)
    if unknown:
        known = ", ".join(("all", *MCP_CONFIG_TARGETS))
        raise ValueError(f"unknown MCP config target {target!r}; known targets: {known}")

    changed: list[Path] = []
    for item in targets:
        if item == "codex":
            path = _install_codex_mcp_config(root)
        elif item == "claude":
            path = _install_json_mcp_config(root / ".mcp.json", root)
        else:
            path = _install_json_mcp_config(root / ".cursor" / "mcp.json", root)
        if path is not None:
            changed.append(path)
    return changed


def _upsert(existing: str, block: str) -> str:
    if START in existing and END in existing:
        before, remainder = existing.split(START, 1)
        _, after = remainder.split(END, 1)
        # When the block sits at the very top (no prose before it), don't reintroduce a
        # leading blank line - otherwise re-running `install` on a freshly created file
        # would keep prepending whitespace instead of reaching a fixed point.
        prefix = before.rstrip() + "\n\n" if before.strip() else ""
        return prefix + block.rstrip() + "\n" + after.lstrip()
    if not existing.strip():
        # Match the fixed point the upsert branch produces for a block-only file, so a
        # second `install` on a freshly created file is a true no-op.
        return block.rstrip() + "\n"
    return existing.rstrip() + "\n\n" + block.rstrip() + "\n"


def _install_codex_mcp_config(root: Path) -> Path | None:
    target = root / ".codex" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    unmanaged = _without_managed_block(existing, CODEX_MCP_START, CODEX_MCP_END)
    if re.search(r"(?m)^\s*\[mcp_servers\.logicchart\]\s*$", unmanaged):
        raise ValueError(
            f"{target} already defines [mcp_servers.logicchart] outside the "
            "LogicChart managed block."
        )
    block = "\n".join(
        [
            CODEX_MCP_START,
            "[mcp_servers.logicchart]",
            'command = "logicchart"',
            f"args = {_toml_array(['mcp', str(root)])}",
            f"cwd = {json.dumps(str(root))}",
            'default_tools_approval_mode = "prompt"',
            CODEX_MCP_END,
            "",
        ]
    )
    updated = _upsert_managed_block(existing, block, CODEX_MCP_START, CODEX_MCP_END)
    if updated != existing:
        target.write_text(updated, encoding="utf-8")
        return target
    return None


def _install_json_mcp_config(target: Path, root: Path) -> Path | None:
    target.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object]
    if target.exists() and target.read_text(encoding="utf-8").strip():
        try:
            loaded = json.loads(target.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSON in {target}: {error}") from error
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} must contain a JSON object")
        data = loaded
    else:
        data = {}

    servers = data.setdefault("mcpServers", {})
    if not isinstance(servers, dict):
        raise ValueError(f"{target} has non-object mcpServers")
    existing_server = servers.get("logicchart", {})
    if existing_server is not None and not isinstance(existing_server, dict):
        raise ValueError(f"{target} has non-object mcpServers.logicchart")
    server = dict(existing_server or {})
    server.update({"command": "logicchart", "args": ["mcp", str(root)]})
    servers["logicchart"] = server

    updated = json.dumps(data, indent=2) + "\n"
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    if updated != existing:
        target.write_text(updated, encoding="utf-8")
        return target
    return None


def _without_managed_block(existing: str, start: str, end: str) -> str:
    if start not in existing or end not in existing:
        return existing
    before, remainder = existing.split(start, 1)
    _, after = remainder.split(end, 1)
    return before + after


def _upsert_managed_block(existing: str, block: str, start: str, end: str) -> str:
    if start in existing and end in existing:
        before, remainder = existing.split(start, 1)
        _, after = remainder.split(end, 1)
        prefix = before.rstrip() + "\n\n" if before.strip() else ""
        suffix = "\n" + after.lstrip() if after.strip() else ""
        return prefix + block.rstrip() + "\n" + suffix
    if not existing.strip():
        return block.rstrip() + "\n"
    return existing.rstrip() + "\n\n" + block.rstrip() + "\n"


def _toml_array(values: list[str]) -> str:
    return "[" + ", ".join(json.dumps(value) for value in values) + "]"
