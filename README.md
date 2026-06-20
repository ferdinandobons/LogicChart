# LogicChart

LogicChart is a local-first workflow navigator for code logic.

It builds a deterministic decision-flowchart model of a local codebase and exposes that
model in two ways:

- `logicchart view` for manual exploration of the complete graph.
- MCP `agent_context` for coding agents that need a bounded, source-grounded
  `workflow_slice`.

The product unit is the `workflow_slice`: a deterministic slice of the modeled code
logic selected from a question, changed file, symbol, state, flow id, or dependency path.
Agents can render that slice visually, explain it, expand it, or trace a path without
inventing steps that are not in the graph.

LogicChart is not a bug finder, a generic graph database, or an LLM enrichment service.
The core workflow is deterministic, local, and offline. No LLM provider key is required.

> Status: early alpha. The model is versioned, but schema and MCP payloads may evolve
> before 1.0.
>
> Latest release: [v0.8.0](https://github.com/ferdinandobons/LogicChart/releases/tag/v0.8.0)
> · [Changelog](CHANGELOG.md)

## Why It Exists

Coding agents are useful only when they understand the logic they are about to explain or
change. Reading files one by one is slow and inconsistent; asking an LLM to reconstruct a
workflow from source often produces different diagrams for the same prompt.

LogicChart gives agents a deterministic navigation layer:

- entrypoints, decisions, branches, calls, outcomes, and source ranges;
- domain concepts such as statuses, roles, permissions, enums, and feature flags;
- impact context for changed files, symbols, flows, and dependency paths;
- canonical visual slices with stable diagram hashes;
- optional agent-authored labels and summaries kept separate from analyzer facts.

## Quick Start

Install from this source checkout. MCP support is included by default:

```bash
git clone https://github.com/ferdinandobons/LogicChart.git logicchart
cd logicchart
uv tool install .
```

From the codebase you want to analyze:

```bash
logicchart setup-agent codex
```

`setup-agent` creates `logicchart.toml` when needed, installs the selected agent
instruction file, installs a provider-native LogicChart skill where supported, registers
project-scoped MCP where supported, generates initial artifacts, runs `doctor`, and
validates the result.

After setup, ask the coding agent ordinary questions:

```text
How does checkout work?
Show me the workflow for certificate upload.
What logic is impacted by this change?
Where is this status handled?
What should I test after editing this file?
```

For manual exploration:

```bash
logicchart view
```

For explicit refresh during development:

```bash
logicchart update
logicchart validate --check-sync
```

## Setup-Agent

Supported targets:

```bash
logicchart setup-agent codex
logicchart setup-agent claude ../my-app
logicchart setup-agent gemini
logicchart setup-agent cursor --full
```

The selected target controls which files are written:

| Target | Files |
| --- | --- |
| `codex` | `AGENTS.md`, `.agents/skills/logicchart/SKILL.md`, project MCP config |
| `claude` | `CLAUDE.md`, `.claude/skills/logicchart/SKILL.md`, project MCP config |
| `gemini` | `GEMINI.md` |
| `cursor` | `.cursor/rules/logicchart.mdc`, project MCP config |

`setup-agent <target>` writes only that target's agent file. Run it separately for each
agent surface you want to configure.

Codex, Claude, and Cursor receive project-scoped MCP setup. Gemini is currently
instruction-only; use an agent with project-scoped MCP support for runtime integration.

## Agent Workflow

For natural-language questions, agents should start with MCP `agent_context`.

`agent_context` returns a `workflow_slice` with:

- normalized intent and task type;
- primary and supporting flows;
- ordered source-grounded steps;
- decision nodes, branches, values, and outcomes;
- calls, callers, callees, and unresolved call context;
- domain logic for relevant state-like concepts;
- source ranges the agent can cite;
- visual handles for `snapshot_slice` and `logicchart view`;
- omissions caused by token budget, ambiguity, stale artifacts, or unsupported capability;
- follow-up tools for expansion, path tracing, focused explanation, and snapshots.

When a user asks for a visual workflow, the agent should first render the deterministic
visual returned by LogicChart:

1. Use `snapshot_slice` when the client can show inline SVG or an HTML/SVG widget.
2. If inline SVG is unavailable, use the returned local artifact path.
3. If a text fallback is needed, render `workflow_slice.presentation.canonical_visual.diagram`
   exactly as returned.

The model may choose the first visible depth, but the text inside shown blocks must come
from LogicChart payloads. The answer should say that the diagram is a bounded summary and
can be expanded. If the user wants a more language-friendly view, the agent may rewrite
labels in the user's language as a separate presentation layer, preserving ids or source
anchors and without adding facts.

## MCP Surface

Primary MCP tools:

| Tool | Purpose |
| --- | --- |
| `agent_context` | Default entrypoint for natural-language questions and changed-code context. |
| `expand_slice` | Widen or deepen a workflow slice from stable flow handles. |
| `workflow_path` | Trace a deterministic path between flows, symbols, or concepts. |
| `snapshot_slice` | Render a deterministic visual snapshot for a slice. |
| `explain_flow` | Explain one flow with ordered steps, decisions, calls, and source anchors. |
| `explain_node` | Explain one flowchart node with local edge and source context. |
| `explain_edge` | Explain one modeled edge with source context. |
| `domain_map` | Aggregate state/domain handling across decisions and flows. |
| `validate_artifacts` | Check generated model validity and optional sync. |
| `update_logicchart` | Refresh JSON, Markdown, and HTML artifacts from local source. |
| `preview_annotation_targets` | Preview local flow/node/scope annotation targets. |
| `write_annotations` | Write validated agent-authored labels and summaries. |

Use `logicchart view` for the manual UI. The CLI intentionally stays small:
`setup-agent`, `update`, `view`, `validate`, `doctor`, and `mcp`.

## Generated Artifacts

LogicChart writes deterministic artifacts under `logicchart-out/`:

| File | Commit? | Purpose |
| --- | --- | --- |
| `logic-flow.json` | Yes | Canonical model consumed by MCP, CI, scripts, and the viewer. |
| `logic-flow.md` | Yes | Human-readable Markdown summary with Mermaid flowcharts. |
| `logic-flow.html` | Usually no | Local interactive viewer generated from the model. |
| `logic-annotations.json` | Optional | Validated sidecar for agent-generated labels and summaries. |

Commit `logic-flow.json` and `logic-flow.md` when LogicChart is part of the project
workflow. Regenerate HTML locally when a human needs the viewer.

## Manual Viewer

`logicchart view` opens the complete interactive flowchart for a human. It is the official
manual experience for broad exploration:

```bash
logicchart view
logicchart view examples/demo
logicchart view --render-only --no-open
```

Use the viewer when you need to inspect the whole project graph, navigate scopes, compare
neighboring flows, or visually follow callers and callees. Use MCP when an agent should
answer a bounded question with a focused `workflow_slice`.

## Domain Logic

LogicChart extracts and aggregates domain concepts such as:

- enum members;
- status and lifecycle states;
- roles and permissions;
- feature flags;
- handled values and the decisions that branch on them.

MCP `domain_map` connects these concepts to flows, nodes, source ranges, snapshots, and
`agent_context`. Value filters match handled values, including enum-style suffix matches
such as `PAID` for `Status.PAID`.

## Supported Code

LogicChart currently extracts control flow for 11 language ids:

| Language | Current coverage |
| --- | --- |
| Python (`.py`) | AST analyzer with functions, methods, decisions, loops, calls, returns, exceptions, tests, enum harvest, and import dependencies. |
| TypeScript / TSX (`.ts`, `.tsx`) | Tree-sitter analyzer with Next.js and React entrypoint detection, decisions, loops, calls, returns, expression-bodied arrows, tests, enum harvest, and import dependencies. |
| JavaScript / JSX (`.js`, `.jsx`, `.mjs`, `.cjs`) | Tree-sitter analyzer with JavaScript labeling, decisions, loops, calls, returns, expression-bodied arrows, tests, and import dependencies. |
| Go (`.go`) | Profile-driven tree-sitter analyzer with functions, methods, decisions, loops, calls, returns, tests, and import dependencies. |
| Java (`.java`) | Profile-driven tree-sitter analyzer with methods, decisions, loops, calls, returns, exceptions, tests, imports, and Spring route annotations. |
| C# (`.cs`) | Profile-driven tree-sitter analyzer with methods, decisions, loops, calls, returns, exceptions, and tests. |
| PHP (`.php`) | Profile-driven tree-sitter analyzer with functions, methods, decisions, loops, calls, returns, exceptions, and tests. |
| C (`.c`, `.h`) | Profile-driven tree-sitter analyzer with functions, decisions, loops, calls, returns, and tests. |
| C++ (`.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`, `.ipp`, `.tpp`) | Profile-driven tree-sitter analyzer with functions, methods, decisions, loops, calls, returns, exceptions, and tests. |
| Rust (`.rs`) | Profile-driven tree-sitter analyzer with functions, decisions, loops, calls, match handling, returns, and tests. |
| Ruby (`.rb`) | Profile-driven tree-sitter analyzer with methods, decisions, loops, calls, returns, and tests. |

Generated models include `metadata.language_capabilities`, with feature flags and
limitation notes per language. Agents should use that contract when explaining analyzer
depth.

## Configuration

LogicChart works without config. Add `logicchart.toml` only when defaults are not enough:

```toml
[logicchart]
source_roots = ["."]
exclude = []
exclude_dirs = []
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true

[logicchart.entrypoints]
include = []
exclude = []

[logicchart.scopes]
backend = ["backend/**", "services/**"]
frontend = ["frontend/**", "web/**"]
edge = ["edge/**", "workers/**"]
```

Defaults prune common VCS, dependency, cache, temporary, generated, and output
directories, including `.git`, `node_modules`, virtualenv folders, `.next`, `.turbo`,
`.svelte-kit`, `dist`, `build`, `out`, `target`, `coverage`, `vendor`, `Pods`, and
`logicchart-out`.

## Limitations

LogicChart does not run code, observe runtime state, perform full symbolic execution,
prove business correctness, or reconstruct deep framework state. It statically models
source files, control flow, selected framework conventions, and resolvable internal calls.

Important practical limits:

- dynamic dispatch may remain unresolved;
- language capability varies by analyzer frontend;
- generated or unsupported files may be skipped;
- large slices are token-budgeted and report omissions;
- the displayed first slice is a bounded summary and can be expanded with MCP tools.

## Development

For local development in this repository:

```bash
uv sync --extra dev
uv run logicchart --help
```

Standard gates:

```bash
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run ruff check .
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run ruff format --check .
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run mypy
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run pytest --cov
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart validate . --check-sync --json
```

Viewer gates:

```bash
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart update
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart view examples/demo --render-only --no-open
```

Schemas:

- [schema/logic-flow.schema.json](schema/logic-flow.schema.json) documents the canonical
  artifact model.
- [schema/logic-annotations.schema.json](schema/logic-annotations.schema.json) documents the
  optional annotation sidecar.
