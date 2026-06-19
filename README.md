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
> **Latest release:** [v0.8.0](https://github.com/ferdinandobons/LogicChart/releases/tag/v0.8.0) ·
> [Changelog](CHANGELOG.md)

## What You Get

- A whole-codebase decision map, from one function to a large polyglot repo.
- A local HTML viewer built for broad codebase study: a progressive scope-to-flowchart
  canvas, file tree, flow search, language filter, inline decision charts, source panel,
  and prioritized findings.
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
logicchart analyze
logicchart view
```

No flags or `init` step are required for the first run. LogicChart analyzes `.` by default
and writes:

| File | Purpose |
|---|---|
| `logicchart-out/logic-flow.json` | canonical model consumed by CLI and MCP; commit it |
| `logicchart-out/logic-flow.md` | reviewable decision flowcharts and findings, including finding ids and `logicchart explain ...` commands; commit it |
| `logicchart-out/logic-flow.html` | local interactive viewer; regenerated and normally ignored |
| `logicchart-out/logic-annotations.json` | optional labels/summaries sidecar; never required for correctness |
| `.env.logicchart` | optional local LLM provider key/model config; ignored and never required |

For development inside this repository:

```bash
uv sync --extra dev --extra mcp
uv run logicchart --help
```

## The 30-Second Example

This Next.js route switches on `user.status` but forgets declared enum members:

```ts
switch (user.status) {
  case UserStatus.ACTIVE: return Response.json(user);
  case UserStatus.SUSPENDED: return new Response("Blocked", { status: 403 });
  // UserStatus.DELETED, ARCHIVED, and LOCKED are declared but never handled
}
```

`logicchart analyze` reports:

```text
- WARNING · INFERRED · enum_exhaustiveness Declared UserStatus members not handled for user.status: UserStatus.ARCHIVED, UserStatus.DELETED, UserStatus.LOCKED
```

`INFERRED` means a deterministic heuristic over a declared closed set, not a guess. Run the
bundled [`examples/demo`](examples/demo) project to see this user-state finding plus an
order-state finding in an 11-language, 2-scope frontend/backend codebase.

## Large Codebases

LogicChart is designed for broad frontend/backend repositories, not only small scripts.

- **Scopes:** declare `backend`, `frontend`, `edge`, `services`, or any macro-part once, then
  filter `query`, `impact`, and the viewer by that scope.
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
- A synchronized source panel and logical-errors panel with selected-finding diagnostics,
  bounded related-flow/evidence-node links, a compact focused diagnostic subgraph, and
  keyboard-accessible collapsible Details sections for project quality, source, and
  findings.
- Finding density on scope nodes and tree file rows, useful for scanning large systems.
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
surrounding HTML shell owns the tree, source, findings, theme, fullscreen, side rails,
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

### `analyze`

Build the model and write JSON, Markdown, and HTML:

```bash
logicchart analyze
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

Useful flags:

- `--full`: ignore the incremental cache while keeping the shorter update workflow.
- `--no-html`: skip the viewer artifact.
- `--include-gaps`: expand review-only `POTENTIAL_GAP` findings in Markdown.
- `--profile demo|self|project`: use one of the built-in repository profiles.

After substantial source changes, commit the refreshed `logic-flow.json` and
`logic-flow.md`. Use `logicchart update --full` after analyzer upgrades or when you need
to verify that cached file models cannot mask a change in LogicChart itself.

### `query`

Ask the model where behavior is handled:

```bash
logicchart query "where is suspended user status handled?"
logicchart query "order status" --scope backend
logicchart query "enum exhaustiveness" --finding-kind enum_exhaustiveness
logicchart query "" --finding-kind missing_branch --finding-evidence POTENTIAL_GAP
logicchart query "routes" --language typescript
logicchart query "" --source-path app/api/orders --symbol api.orders:handle_order
logicchart query "" --domain status --value OPEN
```

Use `--json` for machine-readable output. Structured filters are deterministic and can
stand on their own with an empty question: `--source-path`, `--symbol`, `--domain`,
`--value`, `--finding-kind`, `--finding-severity`, and `--finding-evidence` narrow the
model before ranking. JSON rows include `next_tools` and `next_cli` hints for navigation,
snapshots, impact checks, context-pack follow-up, and explicit subgraph snapshots. Rows
also include bounded finding metadata (`finding_count`, `finding_ids`,
`omitted_finding_count`, `finding_kinds`, `finding_severities`, `finding_evidence`) plus
`subgraph_flow_ids` and `subgraph_finding_ids`, so agents can move from a ranked match to
a focused logical-error review without loading the full graph first.

### `explain`

Explain one logical finding from the committed model:

```bash
logicchart explain finding-id
logicchart explain finding-id --json
```

The human output includes evidence tier, confidence basis, source range, decision context,
diagnostic expected/actual/missing state, review prompt, suggested next actions, and an
evidence-chain summary. The guardrail text distinguishes `VERIFIED`, `INFERRED`, and
`POTENTIAL_GAP` so review candidates are not presented as confirmed bugs. JSON output uses
the same deterministic explanation payload exposed by MCP.

### `navigate`

Inspect one flow before loading the complete graph:

```bash
logicchart navigate flow-id
logicchart navigate module.symbol --json
logicchart navigate flow-id --token-budget 240
```

The command returns the same bounded navigation pack as MCP `get_flow_navigation`: flow
shape, caller/callee summaries, decision nodes, related findings, annotations when present,
and next-tool hints for full flow, impact, query, and visual snapshot follow-up.

### `llm`

Configure optional enrichment credentials without making any provider call:

```bash
logicchart llm providers
logicchart llm setup
logicchart llm show
```

The default provider is DeepSeek with `deepseek-v4-pro`; `deepseek-v4-flash` is also
available as the fast/cost-oriented DeepSeek v4 preset. `setup` writes
`.env.logicchart` with `LOGICCHART_LLM_PROVIDER`, `LOGICCHART_LLM_MODEL`,
`LOGICCHART_LLM_BASE_URL`, `LOGICCHART_LLM_API_FORMAT`, and
`LOGICCHART_LLM_API_KEY`, and masks the key in all command output. The file is ignored by
git and chmodded to owner-only permissions when the platform supports it.

For non-interactive scripts or region-specific endpoints:

```bash
printf '%s' "$DEEPSEEK_API_KEY" | logicchart llm setup --api-key-stdin
printf '%s' "$DASHSCOPE_API_KEY" | logicchart llm setup --provider qwen --model qwen3-coder-plus --base-url https://dashscope-us.aliyuncs.com/compatible-mode/v1 --api-key-stdin
```

Provider/model presets cover DeepSeek, OpenAI, Anthropic, Google Gemini, xAI, Alibaba
Qwen, Z.AI, Kimi/Moonshot, and Mistral. Model catalogs change frequently, so `--model`
and `--base-url` are free-form overrides. LogicChart still works fully offline without
this file; LLM enrichment remains opt-in and must be run explicitly before any code or
artifact text is sent to a provider. See [docs/llm.md](docs/llm.md) for the verified
provider snapshot.

### `enrich`

Preview or run optional LLM annotation enrichment:

```bash
logicchart enrich
logicchart enrich --scope backend
logicchart enrich --flow flow-id --finding finding-id --json
logicchart enrich --scope frontend --send
```

Without `--send`, `enrich` is a local preview; `--dry-run` and `--preview` make that
default explicit. It loads the existing model, selects a bounded set of flows/findings,
prints the exact structured provider payload, and reports
`provider_call_made: false`. With `--send`, it reads `.env.logicchart`, calls the
configured OpenAI-compatible provider, validates the returned annotation sidecar against
the current model hash, and writes `logicchart-out/logic-annotations.json`.
Default selection prioritizes flows with logical findings so error explanations are part
of the first enrichment pass.

The provider can only annotate existing scope, flow, node, and finding ids. It cannot
change the deterministic flow structure, and provider output is rejected if it references
unknown ids, stale hashes, unsupported fields, or overlong text.
When present, finding annotations are shown separately from deterministic diagnostics in
`logicchart explain`, `logicchart navigate`, MCP finding/review/context tools, and the
Logical Errors panel.
Scope annotations are also rendered as progressive flowchart group labels and included in
flow-navigation annotation payloads for flows that belong to the annotated scope.

### `snapshot`

Render deterministic SVG visual context without starting the viewer or MCP server:

```bash
logicchart snapshot flow flow-id > flow.svg
logicchart snapshot finding finding-id --json
logicchart snapshot impact --flow flow-id --output impact.svg
logicchart snapshot impact --dependency-path backend/payments --json
logicchart snapshot subgraph --flow flow-id --finding finding-id --json
```

Snapshots are generated from the committed model artifact, not from browser screenshots.
`flow`, `finding`, `impact`, and `subgraph` support `--token-budget`; `impact` accepts
the same `--flow`, `--symbol`, `--finding`, `--dependency-path`, `--scope`, and
changed-file targets as `impact`. `subgraph` renders explicit flow/finding ids, resolves
finding targets back to their flows, highlights finding nodes, and reports unresolved
targets without requiring agents to synthesize a fake impact request.
Impact snapshot JSON includes the same target, unresolved-target, impact-reason, and
subgraph fields as `impact --json`, so agents can detect mistyped targets without parsing
the SVG. Snapshot JSON also includes deterministic layout metadata: canvas size, node or
column dimensions, rendered positions, compact/omission flags, and rendered/omitted edge
or flow counts. A `layout_quality` summary classifies the rendered snapshot as complete or
compact and repeats the key omission counts with a guardrail for agents. It also includes a
separate `clarity` report for rendered-box overlaps, canvas overflow, minimum box gaps, and
edge paths that cross intermediate boxes, so agents can tell a complete snapshot from a
visually clean one. Invalid snapshot targets and unsupported formats return structured,
recoverable error payloads in JSON mode. Only SVG is supported by the CLI today; raster
export remains available in the local viewer.

### `impact`

Show flows affected by changed files or explicit model targets:

```bash
logicchart impact backend/users.py
logicchart impact --scope frontend
logicchart impact --flow orders-route --json
logicchart impact --symbol api.orders:handle_order
logicchart impact --finding orders-route-missing-branch
logicchart impact --dependency-path backend/payments
```

With no file arguments and no explicit targets, `impact` uses `git diff` to infer changed
files. Explicit targets are deterministic and local: `--flow` matches a flow id,
`--symbol` matches an exact flow symbol or flow name, `--finding` starts from a finding id,
and `--dependency-path` starts from every modeled flow in or under a source path. JSON
output includes `subgraph_flow_ids`, `subgraph_finding_ids`, and any `unresolved_targets`
so agents can chain into flow navigation or snapshots. It also emits
`impact_reasons`, a per-flow explanation of whether each flow was selected by a changed
source file, an imported changed file, an explicit target, or caller propagation. For
Python, TypeScript/JavaScript, Go, Java, and C# generated file records include first-party
`dependencies`; when a changed file has no modeled flow of its own, `impact` can still
surface the entrypoints that import it.

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
call-resolution rate, generic-label ratio, source-location coverage, finding counts, and
graph density. It also reports skipped-file counts and reasons when a source file could
not be parsed. Python syntax errors and unrecoverable tree-sitter parse errors are
recorded as skipped-file quality signals. Recoverable TypeScript/JavaScript or
profile-driven tree-sitter error nodes that still expose flows are preserved with parse
warnings in the quality payload instead of being silently treated as fully clean. The same
quality payload also includes per-language depth signals for files, flows, decisions,
calls, findings, source coverage, and capability metadata.
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

Every finding also carries normalized diagnostic metadata:

- a stable `rule_id`, detector category, severity, evidence tier, and confidence basis;
- source scope linking the finding to its flow, node, related decision nodes, file, and
  line ranges;
- detector inputs, expected/actual state, missing values when applicable, and an evidence
  chain with detector-specific proof points such as implicit fallbacks, constant guards,
  branch outcomes, and bounded related-decision evidence for cross-flow findings;
- a review prompt and suggested next actions for humans and agents.

The shared rule registry is emitted under `metadata.finding_rules`, so CLI artifacts, the
HTML viewer, and MCP tools all explain findings with the same detector contracts. Each
contract includes purpose, preconditions, caveats, evidence rationale, guaranteed metadata
fields, review prompt, suggested next actions, and concise examples for true positives
versus intentional suppressions.

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

The installed block tells agents to start with `logicchart --help` and
`logicchart <command> --help` when helping users set up or learn the tool, to use
`logicchart doctor` for install/dependency uncertainty, and to guide optional LLM setup
through `logicchart llm providers`, `logicchart llm setup --help`, and `logicchart llm
show` without printing or committing API keys.

Each managed instruction block also contains a `logicchart:local-notes` section. Put
project-specific private checks or local workflow notes there; later `logicchart install`
runs preserve that section while refreshing the standard LogicChart guidance.

Install the optional MCP dependency from this source checkout:

```bash
uv tool install '.[mcp]'
```

Start the server in the analyzed project:

```bash
logicchart mcp .
```

Available MCP tools include summary, analysis-quality reports, flow listing, flow
retrieval, flow-navigation packs, query, findings, finding-rule contracts, finding-chain
explanation, finding-context subgraphs, state-handling lookup, decision-node search,
impact analysis, token-bounded deterministic SVG snapshots for flows, findings, impact
sets, and explicit flow/finding subgraphs, optional LLM enrichment preview, review queue,
context pack, artifact validation, and artifact update. Artifact
validation and update responses include guardrails plus `next_tools`/`next_cli` hints for
the update -> validate -> review sequence, so agents can recover from stale generated
models without guessing the workflow. Recovery hints use `update_logicchart(full=true)`
and `logicchart update --full` when bypassing the incremental cache is the safer default.
Finding snapshots include a compact diagnostic panel with evidence tier, confidence,
review prompt, and evidence-chain summaries. MCP impact
analysis and `context_pack` include per-flow `reasons` alongside a top-level
`impact_reasons` map so agents can explain direct and transitive impact without
reconstructing the traversal. Snapshot payloads carry deterministic layout metadata along
with target, unresolved-target, impact-reason, and subgraph fields, plus `layout_quality`
summaries for complete versus compact renderings and `clarity` signals for overlaps,
overflow, gaps, and edge obstacles, so agents can reason about omitted or visually crowded
context without parsing SVG geometry. `context_pack` accepts the same explicit `flow_ids`,
`symbols`, `finding_ids`, and `dependency_paths` impact targets as `analyze_impact`.
It also accepts the same deterministic query filters as `query_logic` for source paths,
language ids, state domains, handled values, finding kinds, severities, and evidence
tiers. The returned pack includes bounded flow-navigation packs for relevant flows, so
agents can inspect callers, callees, decisions, findings, annotations, and follow-up tools
before deciding whether to request a complete flow or visual snapshot.
The `get_subgraph_snapshot` tool and `logicchart snapshot subgraph` CLI command are the
bridge from query/impact/context results into one bounded SVG: pass returned
`subgraph_flow_ids` and `subgraph_finding_ids` directly to render the focused model slice.
Use MCP `preview_enrichment` to inspect the same bounded local payload as
`logicchart enrich` before any optional provider send; use `logicchart enrich --json` when
an agent or script needs the machine-readable payload. Provider calls remain an explicit
CLI action through `logicchart enrich --send`.
If the generated model is missing or malformed, model-reading MCP tools return structured
recoverable errors with an `error_code`, artifact path, guardrail text, and next tool/CLI
actions instead of surfacing a raw traceback. Unknown flow/finding targets and invalid
snapshot targets use the same structured error shape with recovery hints.
`analysis_quality` returns deterministic analyzer-depth signals with guardrails and
follow-up tool pointers, including parse-warning attention when tree-sitter recovered
flows from partially malformed files. `context_pack` stays lightweight by default and
returns snapshot follow-up tool calls; pass `include_visual=true` when an agent needs
inline, budget-capped SVG impact, subgraph, flow, and finding context in the same
response. `visual_byte_budget` caps the total inline SVG bytes deterministically; omitted
visuals remain available through the returned snapshot follow-up tools.

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
core model plus optional generated metadata contracts for finding diagnostics, finding
rules, quality, language capabilities, and skipped files while remaining forward-compatible
for custom metadata. Optional annotation sidecars use
[schema/logic-annotations.schema.json](schema/logic-annotations.schema.json).

## License

Apache License 2.0. See [LICENSE](LICENSE).

LogicChart was created by Ferdinando Bonsegna. If you use, fork, or build on it, please keep
the [NOTICE](NOTICE) file intact and credit the project with a link back to this repository.
