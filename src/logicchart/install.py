from __future__ import annotations

import json
import re
from pathlib import Path

START = "<!-- logicchart:instructions:start -->"
END = "<!-- logicchart:instructions:end -->"
LOCAL_NOTES_START = "<!-- logicchart:local-notes:start -->"
LOCAL_NOTES_END = "<!-- logicchart:local-notes:end -->"
LOCAL_NOTES_HINT = (
    "<!-- Add project-specific local notes here. This section is preserved by "
    "`logicchart setup-agent`. -->"
)
AGENT_INSTRUCTION_TARGETS = {
    "codex": Path("AGENTS.md"),
    "claude": Path("CLAUDE.md"),
    "gemini": Path("GEMINI.md"),
    "cursor": Path(".cursor/rules/logicchart.mdc"),
}
AGENT_SKILL_TARGETS = {
    "codex": Path(".agents/skills/logicchart/SKILL.md"),
    "claude": Path(".claude/skills/logicchart/SKILL.md"),
}
MCP_CONFIG_TARGETS = ("codex", "claude", "cursor")
CODEX_MCP_START = "# logicchart:mcp-config:start"
CODEX_MCP_END = "# logicchart:mcp-config:end"

SKILL_DESCRIPTION = (
    "Use when answering codebase logic, behavior, workflow/flusso, decision, "
    "state/status, change impact, testing, review-signal, or visual workflow/canvas "
    "questions in a project that uses LogicChart. Prefer the LogicChart MCP "
    "agent_context tool before broad searches, and use snapshot_slice, the canonical "
    "workflow_slice Mermaid visual, or viewer_targets when the user asks to show, "
    "visualize, render, diagram, canvas, workflow, flusso, or workflow_slice."
)

SKILL_TEMPLATE = f"""---
name: logicchart
description: {SKILL_DESCRIPTION}
---

# LogicChart

Use LogicChart as the first path for code-logic questions in projects with LogicChart
configured.

## Default Workflow

1. Call MCP `agent_context` before broad file-by-file search. Pass the user question plus
   changed files, current file, selected code, flow id, symbol, finding id, or dependency
   path when available.
2. Inspect `workflow_slice`. Answer from deterministic fields: presentation,
   primary/supporting flows, ordered steps, decisions, source ranges, and review signals.
3. Use `expand_slice`, `workflow_path`, `explain_flow`, `explain_node`, or `explain_edge`
   only when the first slice is too narrow.
4. After substantial source changes, run `update_logicchart` and `validate_artifacts`;
   keep `logicchart-out/logic-flow.json` and `logicchart-out/logic-flow.md`
   synchronized when they change.

## Visual Workflow Requests

When the user asks to show a workflow, workflow_slice, diagram, visual flow, canvas,
flusso, or similar code path:

1. Call `agent_context` with `include_visual=true` when available.
2. Use a stable concise `token_budget` for similar requests unless the user asks for more
   or less detail. Choose depth by using the returned slice handles, `expand_slice`, or
   `workflow_path`; do not manually invent omitted branches.
3. Call `snapshot_slice` using `workflow_slice.id`, `workflow_slice.handle.flow_ids`, and
   `workflow_slice.handle.finding_ids`.
4. Show the SVG snapshot or rendered visual first when the client supports it.
5. If inline SVG rendering is not possible, render
   `workflow_slice.presentation.canonical_visual.diagram` exactly as the top-to-bottom
   Mermaid fallback. Keep the returned `diagram_hash` visible when useful. Do not
   synthesize a new Mermaid diagram and do not add limits, error codes, branches, or
   service steps that are absent from the `workflow_slice` payload.
6. Say that the displayed diagram is a bounded summary of the selected logic and can be
   expanded. If a more readable version is useful, present it as a human-friendly
   translation derived only from returned node, edge, decision, and source fields.
7. Also provide the `viewer_targets` command and hash
   target so the user can open the same visual in `logicchart view`.
8. Treat `workflow_slice.presentation` as supporting context for this request, not as the
   primary output.
9. Keep the textual summary short and secondary. Do not answer with raw JSON or YAML unless
   the user explicitly asks for it.

## Guardrails

- MCP is local-first and deterministic; do not ask for provider keys for the primary
  workflow.
- Keep agent-authored annotations separate from deterministic facts.
- Treat `VERIFIED` as syntax-backed, `INFERRED` as heuristic, and `POTENTIAL_GAP` as a
  review candidate, not a confirmed defect.
- Use `logicchart view` only for the human manual UI.
"""


def _instruction_block(local_notes: str = "") -> str:
    notes = local_notes.strip() or LOCAL_NOTES_HINT
    return f"""{START}
## LogicChart

This project uses LogicChart to keep decision flows synchronized with the source code.

For codebase questions about behavior, decisions, missing cases, or change impact:

1. Prefer the LogicChart MCP `agent_context` tool before broad file-by-file searches.
2. Use `agent_context` for substantial changes, passing changed files, selected code,
   current file, flow id, symbol, finding id, or dependency path when available; inspect
   its returned `workflow_slice` before answering.
3. When the user asks to show a workflow, flusso, visual flow, canvas, or
   `workflow_slice`, prefer a visual answer: use `snapshot_slice` when available; if the
   client cannot render the SVG inline, render
   `workflow_slice.presentation.canonical_visual.diagram` exactly as the top-to-bottom
   Mermaid fallback.
   Choose depth by using the returned slice handles, `expand_slice`, or `workflow_path`;
   say that the displayed diagram is a bounded summary and can be expanded.
   Do not synthesize a new Mermaid diagram and do not add limits, error codes, branches,
   or service steps that are absent from the `workflow_slice` payload. A human-friendly
   translation is allowed only as a separate presentation layer derived from returned
   node, edge, decision, and source fields. Show raw JSON or YAML only when explicitly
   requested.
4. Use `expand_slice`, `workflow_path`, `snapshot_slice`, `explain_flow`, `explain_node`,
   or `explain_edge` only when the first slice needs more precise context.
5. Review `logicchart-out/logic-flow.md` and any related `POTENTIAL_GAP` review signals.
6. Use `logicchart view ...` only when a human wants the manual UI flowchart.

When helping a user set up or learn LogicChart:

1. Start with `logicchart --help`, then use `logicchart <command> --help` for the specific
   command you plan to run or recommend.
2. Use `logicchart doctor` when install, dependency, or parser capability issues are
   unclear.
3. Do not ask for LLM provider keys for the primary workflow. Agent-authored annotations
   should be generated by the coding agent and kept separate from deterministic facts.
4. `logicchart setup-agent <target>` updates only that target's instruction file. Run the
   command separately for each agent surface you want to configure, preserving any
   target-specific frontmatter and local notes.

After a substantial code change:

1. Use LogicChart MCP `agent_context` to review affected entry points and callers.
2. Ground the review in the returned `workflow_slice`; expand it through MCP only when
   the initial slice omits relevant callers, callees, domain states, or findings.
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

{LOCAL_NOTES_START}
{notes}
{LOCAL_NOTES_END}

Do not present inferred review signals as confirmed defects. LogicChart marks syntax-backed
facts as `VERIFIED`, deterministic heuristics as `INFERRED`, and review candidates as
`POTENTIAL_GAP`.
{END}
"""


INSTRUCTION_BLOCK = _instruction_block()


def install_all(root: Path, platform: str = "all", mcp_config: str = "none") -> list[Path]:
    changed = install_agent_instructions(root, platform)
    changed.extend(install_agent_skill(root, platform))
    if mcp_config != "none":
        changed.extend(install_mcp_config(root, mcp_config))
    return changed


def install_agent_instructions(root: Path, platform: str = "all") -> list[Path]:
    names = tuple(AGENT_INSTRUCTION_TARGETS) if platform == "all" else (platform,)
    unknown = set(names) - set(AGENT_INSTRUCTION_TARGETS)
    if unknown:
        known = ", ".join(("all", *AGENT_INSTRUCTION_TARGETS))
        raise ValueError(f"unknown agent instruction target {platform!r}; known targets: {known}")
    targets = [root / AGENT_INSTRUCTION_TARGETS[name] for name in names]

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


def install_agent_skill(root: Path, platform: str = "all") -> list[Path]:
    names = tuple(AGENT_SKILL_TARGETS) if platform == "all" else (platform,)
    unknown = set(names) - set(AGENT_INSTRUCTION_TARGETS)
    if unknown:
        known = ", ".join(("all", *AGENT_INSTRUCTION_TARGETS))
        raise ValueError(f"unknown agent skill target {platform!r}; known targets: {known}")

    changed: list[Path] = []
    for name in names:
        target_path = AGENT_SKILL_TARGETS.get(name)
        if target_path is None:
            continue
        target = root / target_path
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = target.read_text(encoding="utf-8") if target.exists() else ""
        if existing != SKILL_TEMPLATE:
            target.write_text(SKILL_TEMPLATE, encoding="utf-8")
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
        managed, after = remainder.split(END, 1)
        block = _instruction_block(_extract_local_notes(managed))
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


def _extract_local_notes(managed: str) -> str:
    if LOCAL_NOTES_START in managed and LOCAL_NOTES_END in managed:
        _, remainder = managed.split(LOCAL_NOTES_START, 1)
        notes, _ = remainder.split(LOCAL_NOTES_END, 1)
        stripped = notes.strip()
        return "" if stripped == LOCAL_NOTES_HINT else stripped
    return _extract_legacy_local_notes(managed)


def _extract_legacy_local_notes(managed: str) -> str:
    marker = "For local real-world regression checks:"
    start = managed.find(marker)
    if start == -1:
        return ""
    end = managed.find("\nDo not present inferred", start)
    if end == -1:
        end = len(managed)
    return managed[start:end].strip()


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
            'default_tools_approval_mode = "approve"',
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
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    data: dict[str, object]
    if existing.strip():
        try:
            loaded = json.loads(existing)
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
