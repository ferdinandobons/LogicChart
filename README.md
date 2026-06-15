# LogicChart

**Map the decisions in your Python and TypeScript code as navigable flowcharts - deterministically, with no API key.**

LogicChart reads a source folder and, for each entry point, extracts the control flow it can
verify from syntax: the `if` / `switch` / `match` branches, the exception paths, what each
branch does (return early, raise, redirect, persist data), and the internal calls that link
one flow to the next. It does **not** run your code or attempt full symbolic execution - it
reasons about structure. The result is a committed, versioned model plus reviewable
flowcharts and an interactive viewer, so change impact is easy to reason about - for humans
and for coding agents.

Every finding is labeled by **how it was derived** - `VERIFIED`, `INFERRED`, or
`POTENTIAL_GAP` - so the report never blurs a fact with a guess. (Optional LLM integrations
may enrich labels in the future, but they are never required to build the verified graph.)

> **Status:** early alpha (v0.2.0). The logical model is versioned, but its schema may still
> evolve before 1.0.

## See it in 30 seconds

This Next.js route handler switches on `user.status` but forgets a case:

```ts
switch (user.status) {
  case UserStatus.ACTIVE:    return Response.json(user);
  case UserStatus.SUSPENDED: return new Response("Blocked", { status: 403 });
  // no default - DELETED (and any future status) silently falls through
}
```

`logicchart analyze` writes this line to the committed report, and labels how sure it is:

```text
- **WARNING · POTENTIAL_GAP · missing_branch** Decision has no explicit fallback: switch user.status
```

`POTENTIAL_GAP` means "a review candidate, not a confirmed bug." Run it yourself on
[`examples/demo`](examples/demo).

## Why LogicChart

Your IDE answers "where is this symbol?" LogicChart is built for the questions that come up
in review and refactoring:

- **Catch missing cases** before code review - a `switch` / `match` / `if`-chain with no fallback.
- **Check state handling is consistent** across sibling flows - a status one route handles
  but another silently drops.
- **See change impact** - which entry points are reachable from the service you're about to edit.
- **Give coding agents a deterministic control-flow map** they can query instead of re-reading files.

## Install

LogicChart is not on PyPI yet. Install it from source with [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/ferdinandobons/LogicChart.git logicchart
cd logicchart
uv tool install .            # the `logicchart` command, available everywhere
# uv tool install '.[mcp]'   # include the optional MCP server
```

For development (run without installing globally):

```bash
uv sync --extra dev --extra mcp
uv run logicchart --help     # prefix commands with `uv run`
```

## Quick Start

From the project you want to analyze:

```bash
logicchart init             # write a starter logicchart.toml (once)
logicchart analyze --full   # build the model + flowcharts
logicchart view             # open the interactive viewer in your browser
```

You get three files under `logicchart-out/`:

| File | Purpose |
|---|---|
| `logic-flow.json` | canonical model - consumed by the CLI and MCP; **commit it** |
| `logic-flow.md` | reviewable Mermaid flowcharts + a findings list; **commit it** |
| `logic-flow.html` | interactive local viewer (drag blocks to rearrange); regenerated, git-ignored |

In the Markdown report, `VERIFIED` / `INFERRED` findings sit in the main section and
`POTENTIAL_GAP` review candidates are folded under a collapsible block (`--include-gaps`
expands it). A file that can't be parsed is skipped and reported, never aborting the run.

## Commands

Every command takes the project path as a positional argument (default `.`). Examples below
run against the bundled [`examples/demo`](examples/demo).

### `analyze` - build the model

```bash
logicchart analyze examples/demo --full
```
```text
Analyzed 4 files: 6 flows, 1 review findings.
Wrote .../logic-flow.json
Wrote .../logic-flow.md
Wrote .../logic-flow.html
```
`--full` ignores the incremental cache; `--no-html` skips the viewer; `--include-gaps`
expands the review-only findings in the Markdown.

### `update` - incrementally refresh

```bash
logicchart update examples/demo
```
Re-analyzes only the files whose contents changed (content-hash cache), then rewrites the
JSON and Markdown. Commit those two files after a substantial change.

### `query` - ask the model a question

```bash
logicchart query "where is suspended user status handled?" --path examples/demo
```
```text
1. POST [route] frontend/app/api/users/route.ts:1  score=21 · `user` matches the flow identity ...
2. get_user [route] backend/users.py:23            score=16 · `suspended` appears in a decision ...
```
Ranks the flows most relevant to a behavior, state, or decision. Add `--json` for
machine-readable output.

### `impact` - what does a change touch?

```bash
logicchart impact backend/users.py --path examples/demo
```
```text
Changed files: 1
Directly impacted flows: 3
Transitively impacted flows: 0
Direct impact:
- Repository.fetch (backend/users.py:9)
- get_user (backend/users.py:23)
- load_user (backend/users.py:32)
```
With no file arguments it uses `git diff` to infer what changed.

### `view` - interactive flowchart

```bash
logicchart view examples/demo
```
Renders `logic-flow.html` and serves it at `http://127.0.0.1:8765`. In the viewer you can
filter flows, click a block to inspect its source and findings, and **drag blocks to
rearrange the diagram by hand** (the connectors follow; the reset button restores the
automatic layout). Add `--render-only` to write the HTML without serving.

### `diff` - gate a change in CI

```bash
logicchart diff base/logic-flow.json logicchart-out/logic-flow.json \
  --sarif logicchart.sarif --fail-on-introduced
```
Compares two models by stable finding id, prints a GitHub-Markdown summary of findings
introduced / resolved / persisting, optionally writes SARIF, and exits non-zero when a
finding is introduced.

### `hook` - keep the committed model fresh

```bash
logicchart hook install     # post-commit / post-checkout hooks + a union merge driver
logicchart hook status
logicchart hook uninstall
```
Automates `update` so the committed `logic-flow.json` does not drift between commits.

### `init` / `install` / `mcp`

```bash
logicchart init             # write a starter logicchart.toml
logicchart install          # install agent instructions (see Advanced)
logicchart mcp .            # start the MCP server (see Advanced)
```

## Supported Code

**Languages - any Python or TypeScript/TSX:** functions, methods, arrow functions,
`if` / `elif` / `else`, `switch` / `match`, exceptions, returns, and internal calls.

**Framework-aware entry points:**

- FastAPI routes
- Next.js route handlers, middleware, server actions, pages, and layouts
- Shallow React components, hooks, and event handlers
- Public/exported functions, CLI commands, and tests

**Limitations (by design):** LogicChart does not run your code, trace runtime behavior, do
full symbolic execution, or reconstruct deep React state. "Shallow" React means it reads the
structure of a component and its hooks, not what they render across re-renders - treat those
findings as review candidates. It maps each entry point's own control flow plus the internal
calls that connect flows, not arbitrarily deep call chains.

## Evidence Levels

- `VERIFIED`: directly extracted from syntax or framework conventions.
- `INFERRED`: produced by an explainable deterministic heuristic.
- `POTENTIAL_GAP`: a review candidate, never automatically treated as a bug.

## Finding Kinds

Single-flow (reason about one flow):

- `missing_branch`: a `match` / `switch` or `if` / `elif` chain on a state-like subject with no explicit `else` / `default`.
- `dead_code`: code after a point where every path already returned or raised.
- `broad_except_swallow`: an exception handler that silently discards the error - an empty body or one that only logs it, with no re-raise or error return.
- `no_op_branch`: an explicit `if` branch with an empty body.
- `asymmetric_return`: a dispatch where most cases return/raise but one falls through (a likely missing return).
- `dead_guard`: a truthiness guard on a module-level boolean constant, so one branch is always dead.

Cross-flow (compare sibling flows):

- `inconsistent_case_handling`: a value a strict majority of sibling flows branching on the same subject and enum/union handle, but which this flow omits with no explicit default.
- `enum_exhaustiveness`: a flow dispatches on a declared enum (handling several members) but omits other declared members, with no explicit default.
- `outcome_inconsistency`: the same `subject == value` condition resolves to a different outcome here (e.g. raise 404) than the majority of sibling flows (e.g. raise 410).
- `logging_asymmetry`: a guard that a sibling flow logs/alerts on while rejecting (raising) is handled silently here.
- `auth_divergence` (gated, opt-in via `gated_detectors`): an entry point that skips the authorization check its file-mates perform. Middleware/DI can authorize invisibly, so it is a review candidate.

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
gated_detectors = false

[logicchart.entrypoints]
include = []
exclude = []
```

`gated_detectors` (default `false`) enables opt-in, review-tier detectors such as
`auth_divergence` that are more prone to false positives (middleware/DI can authorize
invisibly), so they are off unless you turn them on.

`self_exclude` (default `true`) keeps LogicChart's own installed package - and, when you
analyze its source checkout, its `tests/` - out of the generated model, so the artifact is
never polluted by the tool scanning its own internals.

Use `.logicchartignore` for generated files or directories that should not be analyzed.

## Advanced: agents, MCP, and CI

> Optional - start with Quick Start above. These wire LogicChart into coding agents and tooling.

### Agent instructions

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

### MCP server

Install the optional MCP dependency (from the source checkout, since LogicChart is not on
PyPI yet):

```bash
uv tool install '.[mcp]'   # or, for development: uv sync --extra mcp
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

- `logicchart_summary` - flow/entrypoint counts and findings by kind/severity/evidence
- `list_flows`
- `get_flow`
- `query_logic`
- `get_findings`
- `explain_finding_chain` - the deterministic evidence chain behind one finding
- `where_state_handled` - every flow branching on a domain/value-namespace and the values it covers
- `find_decision_nodes` - structured search over decision nodes (domain/subject/missing-fallback)
- `analyze_impact`
- `diff_findings` - compare the current model against a baseline (the CI primitive)
- `update_logicchart`

Every query/list tool accepts a `token_budget` cap so an agent can bound how much context a
single call returns.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
```

See [docs/design.md](docs/design.md) for the architecture and scope. The canonical artifact
format is documented by [schema/logic-flow.schema.json](schema/logic-flow.schema.json).

## License

Apache License 2.0. See [LICENSE](LICENSE).
