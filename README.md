# LogicChart

**Turn Python and TypeScript code into navigable decision flowcharts.**

LogicChart is an open-source static analysis tool for humans and coding agents. It extracts
entry points, meaningful functional decisions, outcomes, internal calls, and potential gaps
from a source folder. The result is a persistent logical model plus an interactive flowchart
that makes change impact easier to reason about.

LogicChart works locally without an API key. Optional LLM integrations may enrich labels or
explanations in future releases, but they are never required to build the verified graph.

> **Status:** early alpha. The logical IR is versioned, but its schema may evolve before 1.0.

## Why LogicChart

Code navigation tools are good at answering "where is this symbol?" LogicChart is designed
for the harder follow-up questions:

- What decisions can this route make?
- Which states are handled here but missing elsewhere?
- What entry points may be affected by changing this service?
- Which paths return early, fail, redirect, or persist data?
- Is the flowchart still synchronized after a substantial code change?

## Outputs

```text
logicchart-out/
├── logic-flow.json   canonical model for CLI and MCP
├── logic-flow.md     reviewable Mermaid decision flows
└── logic-flow.html   local interactive viewer, ignored by Git by default
```

The JSON and Markdown files are intended to be committed. The HTML file is regenerated
locally.

## Supported Code

Initial support:

- Python functions, methods, branches, match statements, exceptions, returns, and calls
- TypeScript and TSX functions, methods, arrows, branches, switches, exceptions, and calls
- FastAPI routes
- Next.js route handlers, middleware, server actions, pages, and layouts
- Shallow React components, hooks, and event handlers
- Public/exported functions, CLI commands, event handlers, and tests

LogicChart deliberately does not attempt full symbolic execution, runtime tracing, or deep
React state reconstruction.

## Install From Source

LogicChart is not published yet. Install the current repository with:

```bash
git clone https://github.com/ferdinandobons/LogicChart.git logicchart
cd logicchart
uv tool install .
```

For development:

```bash
uv sync --extra dev --extra mcp
uv run logicchart --help
```

## Quick Start

From the project you want to analyze:

```bash
logicchart init
logicchart analyze --full
logicchart view
```

Incrementally refresh after source changes:

```bash
logicchart impact
logicchart update
```

Ask targeted questions:

```bash
logicchart query "where is suspended user status handled?"
logicchart query "what can reject a payment?"
logicchart impact src/users/service.py app/api/users/route.ts
```

## Agent Instructions

Install persistent instructions that tell coding agents to consult and refresh LogicChart:

```bash
logicchart install
```

This updates supported project-level files:

- `AGENTS.md` for Codex
- `CLAUDE.md` for Claude Code
- `GEMINI.md` for Gemini CLI
- `.cursor/rules/logicchart.mdc` for Cursor

Use `--platform codex`, `claude`, `gemini`, or `cursor` to install one target only.

## MCP Server

Install the optional MCP dependency:

```bash
pip install "logicchart[mcp]"
```

Start the stdio server in the analyzed project:

```bash
logicchart mcp .
```

Example MCP configuration:

```json
{
  "mcpServers": {
    "logicchart": {
      "command": "logicchart",
      "args": ["mcp", "/absolute/path/to/project"]
    }
  }
}
```

Available tools:

- `list_flows`
- `get_flow`
- `query_logic`
- `get_findings`
- `analyze_impact`
- `update_logicchart`

## Evidence Levels

- `VERIFIED`: directly extracted from syntax or framework conventions
- `INFERRED`: produced by an explainable deterministic heuristic
- `POTENTIAL_GAP`: a review candidate, never automatically treated as a bug

## Finding Kinds

Single-flow (reason about one flow):

- `missing_branch`: a `match`/`switch` or `if`/`elif` chain on a state-like subject with no explicit `else`/`default`.
- `dead_code`: code after a point where every path already returned or raised.
- `broad_except_swallow`: an exception handler whose body silently discards the error.
- `no_op_branch`: an explicit `if` branch with an empty body.
- `asymmetric_return`: a dispatch where most cases return/raise but one falls through (a likely missing return).

Cross-flow (compare sibling flows):

- `inconsistent_case_handling`: a value a strict majority of sibling flows branching on the same subject and enum/union handle, but which this flow omits with no explicit default.
- `enum_exhaustiveness`: a flow dispatches on a declared enum (handling several members) but omits other declared members, with no explicit default.

## Configuration

`logicchart init` creates:

```toml
[logicchart]
source_roots = ["."]
exclude = []
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true

[logicchart.entrypoints]
include = []
exclude = []
```

`self_exclude` (default `true`) keeps LogicChart's own installed package — and, when
you analyze its source checkout, its `tests/` — out of the generated model, so the
artifact is never polluted by the tool scanning its own internals.

Use `.logicchartignore` for generated files or directories that should not be analyzed.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

See [docs/design.md](docs/design.md) for the architecture and scope.
The canonical artifact format is documented by
[schema/logic-flow.schema.json](schema/logic-flow.schema.json).

## License

Apache License 2.0. See [LICENSE](LICENSE).
