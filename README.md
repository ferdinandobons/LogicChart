# LogicChart

LogicChart is a local-first static analyzer that turns large codebases into navigable
decision flowcharts.

It reads source code without running it, extracts the decisions that matter (`if`,
`switch`, `match`, exceptions, returns, and internal calls), and writes a deterministic
model that coding agents can use through MCP and humans can inspect in a local interactive
viewer.

**Why it exists:** when a frontend/backend system grows quickly, especially with AI-assisted
changes, it becomes hard to know which states are handled, which entry points call each
other, and what a change will touch. LogicChart gives humans and agents the same explicit
control-flow map.

> **Status:** early alpha. The logical model is versioned, but the schema may evolve before
> 1.0.
>
> **Latest release:** [v0.8.0](https://github.com/ferdinandobons/LogicChart/releases/tag/v0.8.0) ·
> [Changelog](CHANGELOG.md)

## What You Get

- A whole-codebase decision map, from one function to a large polyglot repo.
- A local HTML viewer built for broad codebase study: a progressive scope-to-flowchart
  canvas, file tree, flow search, language filter, inline decision charts, source panel,
  and prioritized review signals.
- A reviewable Markdown report with Mermaid flowcharts.
- A canonical JSON model for CI, scripts, and MCP/coding-agent context.
- Evidence labels on every review signal: `VERIFIED`, `INFERRED`, or `POTENTIAL_GAP`.
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
logicchart setup-agent codex
logicchart update
logicchart view
```

`setup-agent` installs agent instructions, registers the project MCP server, creates
`logicchart.toml` only when needed, generates artifacts, runs `doctor`, and validates the
result. LogicChart analyzes `.` by default and writes:

| File | Purpose |
|---|---|
| `logicchart-out/logic-flow.json` | canonical model consumed by MCP, CI, and the viewer; commit it |
| `logicchart-out/logic-flow.md` | reviewable decision flowcharts and review signals with stable finding ids; commit it |
| `logicchart-out/logic-flow.html` | local interactive viewer; regenerated and normally ignored |
| `logicchart-out/logic-annotations.json` | optional labels/summaries sidecar; never required for correctness |

For development inside this repository:

```bash
uv sync --extra dev --extra mcp
uv run logicchart --help
```

## The 30-Second Example

This Next.js route handles two `user.status` values while the enum declares more members:

```ts
switch (user.status) {
  case UserStatus.ACTIVE: return Response.json(user);
  case UserStatus.SUSPENDED: return new Response("Blocked", { status: 403 });
  // UserStatus.DELETED, ARCHIVED, and LOCKED are declared but never handled
}
```

After `logicchart update`, the generated review-signal report can include:

```text
- WARNING · INFERRED · enum_exhaustiveness Declared UserStatus members not handled for user.status: UserStatus.ARCHIVED, UserStatus.DELETED, UserStatus.LOCKED
```

`INFERRED` means a deterministic heuristic over a declared closed set, not a guess and not
an automatic bug claim. Run the bundled [`examples/demo`](examples/demo) project to see
this user-state review signal plus an order-state review signal in an 11-language, 2-scope
frontend/backend codebase.

## Large Codebases

LogicChart is designed for broad frontend/backend repositories, not only small scripts.

- **Scopes:** declare `backend`, `frontend`, `edge`, `services`, or any macro-part once, then
  let MCP context tools and the viewer focus on that scope.
- **Shape-agnostic UI:** the viewer does not hard-code backend/frontend layouts; it renders
  arbitrary scopes, entry points, calls, decisions, and outcomes from the generated model.
- **Incremental updates:** changed files are content-hashed and cached under `.logicchart/`.
- **Generated-code avoidance:** defaults prune known VCS, dependency, cache, temporary, and
  generated directories before traversal, including `.git`, `node_modules`, venv folders,
  `.next`, `.turbo`, `.svelte-kit`, `dist`, `build`, `out`, `target`, `coverage`, `vendor`,
  and `Pods`. Generated declarations, protobuf outputs, and minified JS remain file-level
  exclusions.
- **Viewer scale:** the canvas opens at scope level, expands one scope into progressive
  entrypoint/call rows, then unfolds selected decision charts in place. It does not dump
  every flow node into the DOM at once.
- **Bounded source payload:** the HTML embeds source snippets once per file and caps very
  large functions, so the viewer stays usable offline.

Use `.logicchartignore` or `logicchart.toml` when a repo has project-specific generated
paths. Add directories to `exclude_dirs` when the whole tree should be skipped before
traversal; use `exclude` for file/path glob exclusions.

## Viewer

```bash
logicchart view
```

The viewer is a local HTML artifact plus a temporary local server. It is built for
large-codebase study, not just one isolated function. It shows:

- A left codebase tree with flow search, language filtering, source-aware labels, and
  selection states that distinguish the active file context from the active flow.
- A central canvas that starts from top-level scopes such as `backend`, `frontend`, and
  `edge`; each scope connects directly to every visible entrypoint underneath it.
- Progressive scope/entrypoint/call expansion: open one or more scopes, then an entrypoint,
  then follow unlocked calls without leaving the same flowchart.
- Direct internal-flow opening that rebuilds the visible caller chain, so selected helpers
  remain connected to their scope entrypoint instead of becoming detached islands; flow and
  path deep links also open Details with the selected source context.
- Expand-in-place decision charts, so a selected flow can be studied without losing its
  surrounding codebase context.
- Link selection that highlights the source node, target node, and selected connection
  while dimming unrelated blocks.
- A synchronized source panel and review-signals panel with selected-signal diagnostics,
  bounded related-flow/evidence-node links, a compact focused diagnostic subgraph, and
  keyboard-accessible collapsible Details sections for project quality, source, and
  review signals.
- Review-signal density on scope nodes and tree file rows, useful for scanning large systems.
- Light/dark theme, pan/zoom, fit-to-content, drag-to-arrange blocks,
  collapse-all reset, fast expand-all overview with progress feedback, full-screen canvas,
  graph-bounds-aware PNG/JPG export, and responsive side panels.

Use `--render-only` to write `logic-flow.html` without serving it.

The shipped viewer is still a single local HTML artifact, but its primary canvas is the
typed frontend runtime built from `frontend/` with Vite, React, Zustand, Vitest, and an
XYFlow adapter. Generated viewers open on the progressive React canvas by default:

```text
logic-flow.html#scope=frontend
logic-flow.html#flow=<flow-id>
logic-flow.html#root
logic-flow.html#node=codebase
```

The React runtime owns the progressive multi-scope canvas, edge selection, flow-detail
expansion, viewport zoom/pan, root-collapsing reset, layout caching, fast expand overview
progress, and PNG/JPG export path. Raster exports size themselves from the graph bounds
rather than the current viewport, so large codebases do not collapse into a tiny fixed-size
image. The
surrounding HTML shell owns the tree, source, review signals, theme, fullscreen, side rails,
and viewer controls. See [docs/viewer.md](docs/viewer.md) for the UI architecture and
verification loop.

## Supported Code

LogicChart currently extracts control flow for **11 language ids**:

| Language | Coverage |
|---|---|
| Python (`.py`) | full AST analyzer, including loop-body flow, local-helper scoping, plus `try`/`except` and success-path `try`/`else` flow |
| TypeScript / TSX (`.ts`, `.tsx`) | tree-sitter analyzer with Next.js and React entry-point detection, loop-body flow, and expression-bodied arrow decisions |
| JavaScript / JSX (`.js`, `.jsx`, `.mjs`, `.cjs`) | tree-sitter analyzer, labeled separately from TypeScript, with loop-body flow and expression-bodied arrow decisions |
| Go (`.go`) | profile-driven tree-sitter analyzer with loop-body flow |
| Java (`.java`) | profile-driven tree-sitter analyzer with loop-body flow, including Spring route annotations |
| C# (`.cs`) | profile-driven tree-sitter analyzer with loop-body flow |
| PHP (`.php`) | profile-driven tree-sitter analyzer with loop-body flow |
| C (`.c`, `.h`) | profile-driven tree-sitter analyzer with loop-body flow |
| C++ (`.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`, `.ipp`, `.tpp`) | profile-driven tree-sitter analyzer with loop-body flow |
| Rust (`.rs`) | profile-driven tree-sitter analyzer with loop-body flow; Rust `match` is treated as compiler-exhaustive |
| Ruby (`.rb`) | profile-driven tree-sitter analyzer with loop-body flow |

Framework-aware entry points include:

- FastAPI routes
- Next.js route handlers, middleware, server actions, pages, and layouts
- React components, hooks, and event handlers, including expression-bodied arrow components
- Spring route handlers
- Public/exported functions, package-level functions and methods, CLI commands, and tests

A new control-flow language is a `LanguageProfile` plus a registry entry, not a new
pipeline.
Generated models include `metadata.language_capabilities`, a deterministic support matrix
with suffixes, analyzer frontend, and coarse feature coverage for each language id,
including expression-bodied function support where the analyzer models it. Capability
entries also include concise `limitations` notes for partial or unsupported features, so
agents can explain analyzer depth without overstating support. The registry test suite
smoke-checks declared baseline capabilities against real analysis fixtures for every
supported language id, so the matrix is treated as a product contract rather than a loose
documentation table.

## Commands

Every command takes the project path as a positional argument unless it has `--path`.
The default project path is `.`.

### `setup-agent`

Configure LogicChart once for a coding agent:

```bash
logicchart setup-agent codex
logicchart setup-agent claude ../my-app
logicchart setup-agent cursor --full
```

`setup-agent` creates `logicchart.toml` only when needed, refreshes every supported
agent instruction file, registers project-scoped MCP config for the selected agent,
generates the initial model, runs `doctor`, validates the artifact, and prints examples
of questions to ask the coding agent.

Supported targets:

- `codex`
- `claude`
- `cursor`

The selected target controls MCP registration. Instruction files are synchronized for all
known agent surfaces so future changes do not leave one coding agent with stale guidance.

Useful flags:

- `--full`: ignore the incremental cache.
- `--no-html`: skip the viewer artifact.
- `--profile demo|self|project`: use one of the built-in repository profiles.

### `update`

Incrementally refresh changed files:

```bash
logicchart update .
```

Useful flags:

- `--full`: ignore the incremental cache while keeping the shorter update workflow.
- `--no-html`: skip the viewer artifact.
- `--include-gaps`: expand review-only `POTENTIAL_GAP` review signals in Markdown.
- `--profile demo|self|project`: use one of the built-in repository profiles.

After substantial source changes, commit the refreshed `logic-flow.json` and
`logic-flow.md`. Use `logicchart update --full` after analyzer upgrades or when you need
to verify that cached file models cannot mask a change in LogicChart itself.

### Agent and MCP context tools

Question answering, impact analysis, review-signal explanation, flow navigation, and visual
snapshots are agent/MCP capabilities rather than public CLI commands. The old public
commands `query`, `impact`, `explain`, `navigate`, and `snapshot` are not part of the
agent-first CLI surface, so users do not need to memorize low-level analysis commands.

For normal use, ask your coding agent questions such as "how does checkout work?" or
"what logic is impacted by this change?". The agent should call MCP `agent_context` and
return grounded context with flows, callers, callees, decisions, review signals, evidence tiers,
source ranges, impact reasons, and visual snapshots when useful.

### Agent-authored Annotations

LogicChart does not require provider keys for enrichment. The preferred path is that the
coding agent reads deterministic MCP context, writes validated annotation sidecars, and
keeps generated text separate from deterministic facts.

Current MCP preview tools can identify candidate flow/review-signal targets for future
annotation writes. The agent can then use MCP `write_annotations`,
`validate_annotations`, `annotation_status`, and `clear_annotations` to manage the
validated `logic-annotations.json` sidecar without provider keys. Provider-managed
enrichment code remains advanced/internal and is not part of the public CLI workflow.

### `validate`

Check the artifact contract:

```bash
logicchart validate
logicchart validate --check-sync
logicchart validate --quality --json
logicchart validate --annotations --json
logicchart validate --max-skipped-files 0 --max-parse-warnings 0 --min-call-resolution 0.5
```

`--check-sync` re-analyzes sources and fails if the committed JSON model is stale.
Validation also checks present finding-rule contracts against the current detector
registry: rule-declared metadata fields must exist on matching findings, and a diagnostic
`rule_id` must match the finding kind.
`--quality` includes deterministic analysis metrics such as files and flows by language,
call-resolution rate, generic-label ratio, source-location coverage, review-signal counts, and
graph density. It also reports skipped-file counts and reasons when a source file could
not be parsed. Python syntax errors and unrecoverable tree-sitter parse errors are
recorded as skipped-file quality signals. Recoverable TypeScript/JavaScript or
profile-driven tree-sitter error nodes that still expose flows are preserved with parse
warnings in the quality payload instead of being silently treated as fully clean. The same
quality payload also includes per-language depth signals for files, flows, decisions,
calls, review signals, source coverage, and capability metadata.
`--annotations` reports validation status for an optional
`logicchart-out/logic-annotations.json` sidecar. If that file exists, validation checks it
even without the flag and fails when the sidecar is stale, malformed, or references ids
that are not in the current model.
Optional CI gates can fail validation on selected metrics:

- `--max-skipped-files N`
- `--max-parse-warnings N`
- `--min-call-resolution 0..1`
- `--max-generic-label-ratio 0..1`

Generated viewers surface the same payload in the Details rail as a compact Project
Quality panel.

### `doctor`

Check the active install, parser dependencies, and static language-capability contract:

```bash
logicchart doctor
```

This is useful after dependency changes or stale editable installs. The output also
summarizes the generated `metadata.language_capabilities` contract by language id, feature
flag count, and limitation-note count without analyzing project files or running the smoke
test suite.

### `mcp`

Start the MCP server for the configured project:

```bash
logicchart mcp .
```

Normally `setup-agent` writes the project-scoped MCP config so the coding agent starts
this command for you.

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
gated_detectors = false

[logicchart.entrypoints]
include = []
exclude = []

[logicchart.scopes]
backend = ["backend/**", "services/**"]
frontend = ["frontend/**", "web/**"]
edge = ["edge/**", "workers/**"]
```

LogicChart always prunes well-known dependency, VCS, cache, temporary, and generated
directories before traversal, including `.git`, `node_modules`, venv folders,
`dist`/`build`/`out`/`target`, `.next`, `.turbo`, `.svelte-kit`, `vendor`, coverage,
and `logicchart-out`. Add project-specific directory names or path globs to
`exclude_dirs`; add file/path glob exclusions to `exclude`.

With no `[logicchart.scopes]`, top-level directories become inferred scopes. A file can
belong to multiple declared scopes.

Built-in profiles:

| Profile | Source roots | Output directory | Use |
|---|---|---|---|
| `demo` | `examples` | `logicchart-out/` | public demo artifact |
| `self` | `src/logicchart` | `logicchart-out/self/` | dogfood map for LogicChart internals |
| `project` | `src`, `tests`, `examples` | `logicchart-out/project/` | whole-checkout map for agents |

## Review Signals

Evidence levels:

- `VERIFIED`: directly extracted from syntax or framework conventions.
- `INFERRED`: produced by an explainable deterministic heuristic.
- `POTENTIAL_GAP`: a review candidate, never automatically treated as a bug.

Single-flow review signals:

- `missing_branch`
- `dead_code`
- `broad_except_swallow`
- `no_op_branch`
- `asymmetric_return`
- `dead_guard`

Cross-flow review signals:

- `inconsistent_case_handling`
- `enum_exhaustiveness`
- `outcome_inconsistency`
- `logging_asymmetry`
- `auth_divergence` when `gated_detectors = true`

Every review signal also carries normalized diagnostic metadata:

- a stable `rule_id`, detector category, severity, evidence tier, and confidence basis;
- source scope linking the signal to its flow, node, related decision nodes, file, and
  line ranges;
- detector inputs, expected/actual state, missing values when applicable, and an evidence
  chain with detector-specific proof points such as implicit fallbacks, constant guards,
  branch outcomes, and bounded related-decision evidence for cross-flow signals;
- a review prompt and suggested next actions for humans and agents.

The shared rule registry is emitted under `metadata.finding_rules`, so CLI artifacts, the
HTML viewer, and MCP tools all explain review signals with the same detector contracts. Each
contract includes purpose, preconditions, caveats, evidence rationale, guaranteed metadata
fields, review prompt, suggested next actions, and concise examples for true positives
versus intentional suppressions.

For compatibility, the JSON schema and MCP parameters still use stable names such as
`findings`, `finding_id`, and `metadata.finding_rules`. The product surface presents those
records as review signals because they are deterministic inspection guidance, not automatic
bug claims.

## Limitations

LogicChart does not run your code, trace runtime behavior, perform full symbolic execution,
or reconstruct deep React state. It maps each entry point's own control flow plus internal
call links that can be resolved statically. Treat `POTENTIAL_GAP` review signals as review
candidates.

## Agents and MCP

LogicChart is moving to an agent-first workflow. Use MCP for token-bounded code-logic
context retrieval; use the CLI for setup, explicit artifact refresh, validation,
diagnostics, and the manual viewer.

Configure an agent once:

```bash
logicchart setup-agent codex
logicchart setup-agent claude
logicchart setup-agent cursor
```

Supported instruction targets:

- `AGENTS.md` for Codex
- `CLAUDE.md` for Claude Code
- `GEMINI.md` for Gemini CLI
- `.cursor/rules/logicchart.mdc` for Cursor

Running `setup-agent` for any supported MCP target refreshes all of those instruction
files together. Gemini is currently instruction-only; use the configured MCP target from
the agent that supports project-scoped MCP.

The installed block tells agents to start with `logicchart --help` and
`logicchart <command> --help` when helping users set up or learn the tool, to use
`logicchart doctor` for install/dependency uncertainty, to prefer MCP tools for code
logic questions, and to keep generated annotation text separate from deterministic facts.

Each managed instruction block also contains a `logicchart:local-notes` section. Put
project-specific private checks or local workflow notes there; later `logicchart
setup-agent` runs preserve that section while refreshing the standard LogicChart guidance.

Install the optional MCP dependency from this source checkout:

```bash
uv tool install '.[mcp]'
```

Start the server in the analyzed project:

```bash
logicchart mcp .
```

The primary MCP tool is `agent_context`. Agents should call it for ordinary questions
about how code works, what a change touches, where a state is handled, or which review signal
needs review. It accepts a user question, changed files, selected code, current file,
flow id, symbol, finding id, dependency path, domain/value filters, scope, token budget,
and visual preference, then returns a deterministic `workflow_slice` plus the compatible
context pack. The slice is the product unit agents should answer from: it includes the
normalized intent, selected primary/supporting flows, ordered steps, decisions, calls,
domain logic, review signals, source ranges, visual handles, omissions, guardrails, and
follow-up tool calls.

Workflow slices are progressively navigable. Use `expand_slice` to widen a slice from its
stable flow/finding handle, `workflow_path` to trace between two flows, symbols, or
concepts, `snapshot_slice` to render the selected slice as deterministic SVG context, and
`explain_flow`, `explain_node`, or `explain_edge` for focused fallback inspection.

Lower-level MCP tools remain available for expert follow-up: summary, analysis-quality
reports, flow listing, flow retrieval, flow-navigation packs, query, review signals,
finding-rule contracts, review-signal-chain explanation, review-signal context subgraphs,
state-handling lookup, domain maps, decision-node search, impact analysis, token-bounded
deterministic SVG snapshots for flows, review signals, impact sets, and explicit flow/finding
subgraphs, workflow-slice expansion/path/snapshot/explanation tools, annotation-target
preview/write/status/validation/clear tools, review queue, context pack, artifact validation,
and artifact update. Artifact validation and update
responses include guardrails plus `next_tools` and maintenance CLI hints for the
update -> validate -> review sequence, so agents can recover from stale generated models
without guessing the workflow. Recovery hints use `update_logicchart(full=true)` and
`logicchart update --full` when bypassing the incremental cache is the safer default.
Review-signal snapshots include a compact diagnostic panel with evidence tier, confidence,
review prompt, and evidence-chain summaries. MCP impact
analysis and `context_pack` include per-flow `reasons` alongside a top-level
`impact_reasons` map so agents can explain direct and transitive impact without
reconstructing the traversal. Snapshot payloads carry deterministic layout metadata along
with target, unresolved-target, impact-reason, and subgraph fields, plus `layout_quality`
summaries for complete versus compact renderings and `clarity` signals for overlaps,
overflow, gaps, and edge obstacles, so agents can reason about omitted or visually crowded
context without parsing SVG geometry. `agent_context` and `context_pack` accept the same
explicit `flow_ids`, `symbols`, `finding_ids`, and `dependency_paths` impact targets as
`analyze_impact`. `context_pack` also accepts the same deterministic query filters as
`query_logic` for source paths, language ids, state domains, handled values, finding
kinds, severities, and evidence tiers. The returned pack includes bounded flow-navigation
packs for relevant flows, so agents can inspect callers, callees, decisions, review signals,
annotations, and follow-up tools before deciding whether to request a complete flow or
visual snapshot. `domain_map` aggregates handled values, missing values, related decisions,
flows, review signals, and subgraph ids for questions about statuses, roles, permissions, and
other state-like domains. When `token_budget` is set, returned domain-map subgraph targets
are capped with explicit `omitted_subgraph_flow_count` metadata so agents do not
accidentally request huge visual snapshots.
The `get_subgraph_snapshot` tool is the bridge from query/impact/context results into one
bounded SVG: pass returned `subgraph_flow_ids` and `subgraph_finding_ids` directly to
render the focused model slice.
Use MCP `preview_annotation_targets` as a local-only way to inspect candidate annotation
targets and bounded context before calling `write_annotations`. It does not call a
provider and does not point agents at a public provider-send CLI path.
If the generated model is missing or malformed, model-reading MCP tools return structured
recoverable errors with an `error_code`, artifact path, guardrail text, and next tool/CLI
actions instead of surfacing a raw traceback. Unknown flow/finding targets and invalid
snapshot targets use the same structured error shape with recovery hints.
`analysis_quality` returns deterministic analyzer-depth signals with guardrails and
follow-up tool pointers, including parse-warning attention when tree-sitter recovered
flows from partially malformed files. `context_pack` stays lightweight by default and
returns snapshot follow-up tool calls; pass `include_visual=true` when an agent needs
inline, budget-capped SVG impact, subgraph, flow, and review-signal context in the same
response. `visual_byte_budget` caps the total inline SVG bytes deterministically; omitted
visuals remain available through the returned snapshot follow-up tools.

## Roadmap

Planned future evolutions:

- CI diff gate for introduced review signals, including SARIF output.
- Managed git auto-sync hooks and a merge strategy for `logic-flow.json`.

## Development

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
uv build
```

Viewer UI work also requires the frontend workspace:

```bash
npm install
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart update
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart view examples/demo --render-only --no-open
```

`npm run viewer:build` writes
`src/logicchart/render/assets/generated/logicchart-viewer-runtime.iife.js`, which is
embedded in generated HTML artifacts. Use a cache-buster query string when checking viewer
changes in the browser.

The canonical artifact format is documented by
[schema/logic-flow.schema.json](schema/logic-flow.schema.json). Schema 1.1 validates the
core model plus optional generated metadata contracts for review-signal diagnostics, finding
rules, quality, language capabilities, and skipped files while remaining forward-compatible
for custom metadata. Optional annotation sidecars use
[schema/logic-annotations.schema.json](schema/logic-annotations.schema.json).

## License

Apache License 2.0. See [LICENSE](LICENSE).

LogicChart was created by Ferdinando Bonsegna. If you use, fork, or build on it, please keep
the [NOTICE](NOTICE) file intact and credit the project with a link back to this repository.
