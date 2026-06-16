# LogicChart

LogicChart is a local-first static analyzer that turns large codebases into navigable
decision flowcharts.

It reads source code without running it, extracts the decisions that matter (`if`,
`switch`, `match`, exceptions, returns, and internal calls), and writes a deterministic model
you can inspect in the terminal, commit to git, query from coding agents, or study in a
local interactive viewer.

**Why it exists:** when a frontend/backend system grows quickly, especially with AI-assisted
changes, it becomes hard to know which states are handled, which entry points call each
other, and what a change will touch. LogicChart gives humans and agents the same explicit
control-flow map.

> **Status:** early alpha. The logical model is versioned, but the schema may evolve before
> 1.0.
>
> **Latest release:** [v0.5.0](https://github.com/ferdinandobons/LogicChart/releases/tag/v0.5.0) ·
> [Changelog](CHANGELOG.md)

## What You Get

- A whole-codebase decision map, from one function to a large polyglot repo.
- A local HTML viewer built for broad codebase study: scope map, file tree, flow search,
  language filter, expandable flowcharts, source panel, and prioritized findings.
- A reviewable Markdown report with Mermaid flowcharts.
- A canonical JSON model for CI, scripts, and MCP/coding-agent context.
- Evidence labels on every finding: `VERIFIED`, `INFERRED`, or `POTENTIAL_GAP`.
- No API key, no code execution, and repeatable output for the same source tree.

## Quick Start

Install from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ferdinandobons/LogicChart.git logicchart
cd logicchart
uv tool install .
```

From the codebase you want to analyze:

```bash
logicchart analyze --full
logicchart view
```

No `init` step is required. LogicChart analyzes `.` by default and writes:

| File | Purpose |
|---|---|
| `logicchart-out/logic-flow.json` | canonical model consumed by CLI and MCP; commit it |
| `logicchart-out/logic-flow.md` | reviewable decision flowcharts and findings; commit it |
| `logicchart-out/logic-flow.html` | local interactive viewer; regenerated and normally ignored |

For development inside this repository:

```bash
uv sync --extra dev --extra mcp
uv run logicchart --help
```

## The 30-Second Example

This Next.js route switches on `user.status` but forgets a declared enum member:

```ts
switch (user.status) {
  case UserStatus.ACTIVE: return Response.json(user);
  case UserStatus.SUSPENDED: return new Response("Blocked", { status: 403 });
  // UserStatus.DELETED is declared but never handled
}
```

`logicchart analyze` reports:

```text
- WARNING · INFERRED · enum_exhaustiveness Declared UserStatus members not handled for user.status: UserStatus.DELETED
```

`INFERRED` means a deterministic heuristic over a declared closed set, not a guess. Run the
bundled [`examples/demo`](examples/demo) project to see the same finding in an 11-language,
3-scope codebase.

## Large Codebases

LogicChart is designed for broad frontend/backend repositories, not only small scripts.

- **Scopes:** declare `backend`, `frontend`, `edge`, `services`, or any macro-part once, then
  filter `query`, `impact`, and the viewer by that scope.
- **Incremental updates:** changed files are content-hashed and cached under `.logicchart/`.
- **Generated-code avoidance:** defaults skip common dependency/build trees such as
  `node_modules`, `.next`, `.turbo`, `.svelte-kit`, `dist`, `build`, `out`, `target`,
  `coverage`, `vendor`, `Pods`, generated declarations, protobuf outputs, and minified JS.
- **Viewer scale:** the canvas opens at scope level, expands one scope to file groups, then
  unfolds one flow's decision chart in place. It does not dump every flow node into the DOM
  at once.
- **Bounded source payload:** the HTML embeds source snippets once per file and caps very
  large functions, so the viewer stays usable offline.

Use `.logicchartignore` or `logicchart.toml` when a repo has project-specific generated
paths.

## Viewer

```bash
logicchart view
```

The viewer is a single local HTML file plus a temporary local server. It shows:

- A left codebase tree with flow search and language filtering.
- A central canvas with scope-level, file-level, and flow-level navigation.
- Expand-in-place decision flowcharts, so a flow can be studied without losing its
  surrounding codebase context.
- A synchronized source panel and logical-errors panel.
- Finding density on scope/file nodes, useful for scanning large systems.
- Light/dark theme, pan/zoom, reset, full-screen canvas, and responsive side panels.

Use `--render-only` to write `logic-flow.html` without serving it.

## Supported Code

LogicChart currently extracts control flow for **11 language ids**:

| Language | Coverage |
|---|---|
| Python (`.py`) | full AST analyzer |
| TypeScript / TSX (`.ts`, `.tsx`) | tree-sitter analyzer with Next.js and React entry-point detection |
| JavaScript / JSX (`.js`, `.jsx`, `.mjs`, `.cjs`) | tree-sitter analyzer, labeled separately from TypeScript |
| Go (`.go`) | profile-driven tree-sitter analyzer |
| Java (`.java`) | profile-driven tree-sitter analyzer, including Spring route annotations |
| C# (`.cs`) | profile-driven tree-sitter analyzer |
| PHP (`.php`) | profile-driven tree-sitter analyzer |
| C (`.c`, `.h`) | profile-driven tree-sitter analyzer |
| C++ (`.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`, `.ipp`, `.tpp`) | profile-driven tree-sitter analyzer |
| Rust (`.rs`) | profile-driven tree-sitter analyzer; Rust `match` is treated as compiler-exhaustive |
| Ruby (`.rb`) | profile-driven tree-sitter analyzer |

Framework-aware entry points include:

- FastAPI routes
- Next.js route handlers, middleware, server actions, pages, and layouts
- Shallow React components, hooks, and event handlers
- Spring route handlers
- Public/exported functions, package-level functions and methods, CLI commands, and tests

A new control-flow language is a `LanguageProfile` plus a registry entry, not a new
pipeline.

## Commands

Every command takes the project path as a positional argument unless it has `--path`.
The default project path is `.`.

### `analyze`

Build the model and write JSON, Markdown, and HTML:

```bash
logicchart analyze . --full
```

Useful flags:

- `--full`: ignore the incremental cache.
- `--no-html`: skip the viewer artifact.
- `--include-gaps`: expand review-only `POTENTIAL_GAP` findings in Markdown.
- `--profile demo|self|project`: use one of the built-in repository profiles.

### `update`

Incrementally refresh changed files:

```bash
logicchart update .
```

After substantial source changes, commit the refreshed `logic-flow.json` and
`logic-flow.md`.

### `query`

Ask the model where behavior is handled:

```bash
logicchart query "where is suspended user status handled?"
logicchart query "order status" --scope backend
logicchart query "enum exhaustiveness" --finding-kind enum_exhaustiveness
logicchart query "routes" --language typescript
```

Use `--json` for machine-readable output.

### `impact`

See which flows a change touches:

```bash
logicchart impact backend/users.py
logicchart impact --scope frontend
```

With no file arguments, `impact` uses `git diff` to infer changed files.

### `validate`

Check the artifact contract:

```bash
logicchart validate
logicchart validate --check-sync
```

`--check-sync` re-analyzes sources and fails if the committed JSON model is stale.

### `doctor`

Check the active install and parser dependencies:

```bash
logicchart doctor
```

This is useful after dependency changes or stale editable installs.

### `init`, `install`, and `mcp`

These are optional:

```bash
logicchart init
logicchart install
logicchart mcp .
```

- `init` creates a starter `logicchart.toml`.
- `install` writes persistent agent instructions to supported project files.
- `mcp` starts the optional MCP server over stdio.

## Configuration

LogicChart works without config. Add `logicchart.toml` only when defaults are not enough:

```toml
[logicchart]
source_roots = ["."]
exclude = []
include_public_functions = true
max_call_depth = 4
output_dir = "logicchart-out"
self_exclude = true
gated_detectors = false

[logicchart.entrypoints]
include = []
exclude = []

[logicchart.scopes]
backend = ["backend/**", "services/**"]
frontend = ["frontend/**", "web/**"]
edge = ["edge/**", "workers/**"]
```

With no `[logicchart.scopes]`, top-level directories become inferred scopes. A file can
belong to multiple declared scopes.

Built-in profiles:

| Profile | Source roots | Output directory | Use |
|---|---|---|---|
| `demo` | `examples` | `logicchart-out/` | public demo artifact |
| `self` | `src/logicchart` | `logicchart-out/self/` | dogfood map for LogicChart internals |
| `project` | `src`, `tests`, `examples` | `logicchart-out/project/` | whole-checkout map for agents |

## Findings

Evidence levels:

- `VERIFIED`: directly extracted from syntax or framework conventions.
- `INFERRED`: produced by an explainable deterministic heuristic.
- `POTENTIAL_GAP`: a review candidate, never automatically treated as a bug.

Single-flow findings:

- `missing_branch`
- `dead_code`
- `broad_except_swallow`
- `no_op_branch`
- `asymmetric_return`
- `dead_guard`

Cross-flow findings:

- `inconsistent_case_handling`
- `enum_exhaustiveness`
- `outcome_inconsistency`
- `logging_asymmetry`
- `auth_divergence` when `gated_detectors = true`

## Limitations

LogicChart does not run your code, trace runtime behavior, perform full symbolic execution,
or reconstruct deep React state. It maps each entry point's own control flow plus internal
call links that can be resolved statically. Treat `POTENTIAL_GAP` findings as review
candidates.

## Agents and MCP

LogicChart is CLI-first and MCP-enhanced. Use CLI commands for the explicit artifact
lifecycle; use MCP for token-bounded agent context retrieval.

Install persistent instructions:

```bash
logicchart install
logicchart install --mcp-config codex
```

Supported instruction targets:

- `AGENTS.md` for Codex
- `CLAUDE.md` for Claude Code
- `GEMINI.md` for Gemini CLI
- `.cursor/rules/logicchart.mdc` for Cursor

Install the optional MCP dependency from this source checkout:

```bash
uv tool install '.[mcp]'
```

Start the server in the analyzed project:

```bash
logicchart mcp .
```

Available MCP tools include summary, flow listing, flow retrieval, query, findings,
finding-chain explanation, state-handling lookup, decision-node search, impact analysis,
review queue, context pack, artifact validation, and artifact update.

## Roadmap

Planned future evolutions:

- CI diff gate for introduced findings, including SARIF output.
- Managed git auto-sync hooks and a merge strategy for `logic-flow.json`.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv build
```

The canonical artifact format is documented by
[schema/logic-flow.schema.json](schema/logic-flow.schema.json).

## License

Apache License 2.0. See [LICENSE](LICENSE).

LogicChart was created by Ferdinando Bonsegna. If you use, fork, or build on it, please keep
the [NOTICE](NOTICE) file intact and credit the project with a link back to this repository.
