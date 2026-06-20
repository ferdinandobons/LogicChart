# LogicChart

LogicChart is an agent-first workflow navigator for code logic.

It builds a deterministic decision-flowchart model of a local codebase, then exposes focused
workflow slices to coding agents through MCP. A workflow slice is the product unit: a bounded,
source-grounded, navigable piece of the codebase flowchart selected for a question, a change,
a symbol, a state, a review signal, or a file.

LogicChart is not primarily a terminal query tool, a generic graph database, or a visualizer.
The normal workflow is:

```text
ask your coding agent -> MCP agent_context -> workflow_slice -> grounded answer or edit
```

The CLI exists to set up the agent, refresh artifacts, validate them, diagnose the install,
start MCP, and open the manual viewer when a human wants to inspect the flowchart directly.

> Status: early alpha. The model is versioned, but schema and MCP payloads may evolve before
> 1.0.
>
> Latest release: [v0.8.0](https://github.com/ferdinandobons/LogicChart/releases/tag/v0.8.0) ·
> [Changelog](CHANGELOG.md)

## Why It Exists

Modern codebases are increasingly changed through coding agents. The hard part is often not
writing the next patch, but knowing which logic is involved, which states are handled, which
callers and callees matter, and which review signals are certain versus speculative.

LogicChart gives the agent deterministic context before it answers:

- entrypoints, decisions, branches, calls, outcomes, and source ranges;
- domain states such as statuses, roles, permissions, enums, and feature flags;
- review signals with explicit evidence tiers;
- impact context for changed files, symbols, flows, findings, and dependency paths;
- deterministic visual snapshots when a flowchart is clearer than text;
- optional agent-authored annotations kept separate from analyzer facts.

The core stays local-first and offline. No provider key is required for the main workflow,
and LogicChart never needs to run the analyzed application.

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

`setup-agent` creates or refreshes `logicchart.toml` only when needed, installs managed
agent instructions, installs a provider-native LogicChart skill where the selected agent
supports one, registers project-scoped MCP for the selected agent, generates the initial
artifacts, runs `doctor`, validates the result, and prints examples of questions to ask
the agent.

For Codex, the generated project MCP config approves LogicChart tool calls by default.
LogicChart MCP is local, deterministic, and scoped to the configured project root; use this
only for repositories you trust.

After setup, ask your coding agent ordinary questions:

```text
How does checkout work?
What logic is impacted by this change?
Where is this status handled?
What should I test after editing this file?
Show me the flow around this review signal.
```

For manual visual inspection:

```bash
logicchart view
```

For explicit refresh during development:

```bash
logicchart update
logicchart validate --check-sync
```

## Generated Artifacts

LogicChart writes deterministic artifacts under `logicchart-out/`:

| File | Commit? | Purpose |
| --- | --- | --- |
| `logic-flow.json` | Yes | Canonical model consumed by MCP, CI, scripts, and the viewer. |
| `logic-flow.md` | Yes | Human-reviewable Markdown with Mermaid flowcharts and review signals. |
| `logic-flow.html` | Usually no | Local interactive viewer generated from the model. |
| `logic-annotations.json` | Optional | Validated sidecar for agent-generated labels and summaries. |

Commit `logic-flow.json` and `logic-flow.md` when LogicChart is part of the project
workflow. Regenerate HTML locally when a human needs the viewer.

## Workflow Slices

`workflow_slice` is the center of the product.

An agent calls MCP `agent_context` with the context it naturally has:

- a natural-language question;
- changed files;
- selected code;
- current file;
- flow id, symbol, finding id, or dependency path;
- domain/value filters such as status, role, or enum member;
- scope and token budget;
- optional visual preference.

`agent_context` returns a deterministic `workflow_slice` plus a compatible context pack.
The slice includes:

- normalized intent and task type;
- a deterministic presentation contract for agent answers;
- selected primary and supporting flows;
- ordered source-grounded workflow steps;
- decision nodes, branches, handled values, and outcomes;
- calls, callers, callees, and unresolved call context;
- domain logic and missing values when modeled;
- review signals with evidence tiers and guardrails;
- source ranges the agent can cite;
- visual snapshot handles and viewer targets;
- omissions caused by token budget, ambiguity, stale artifacts, or unsupported capability;
- follow-up tools for expansion, path tracing, focused explanation, snapshots, and review.

For natural-language questions, the slice is anchored to one primary flow when LogicChart can
rank a best match; related routes, callers, callees, tests, and neighboring behavior stay in
`supporting_flows`. Agents should answer from `workflow_slice.presentation`, primary and
supporting flows, ordered steps, decision nodes, review signals, and source ranges before
showing any raw JSON or YAML. Lower-level tools are for progressive follow-up, not
prerequisites for ordinary questions.

## MCP Runtime

MCP is the primary runtime surface. `setup-agent` configures it for supported agents, and
`logicchart mcp` is the underlying server command.

Codex project setup writes `default_tools_approval_mode = "approve"` for the LogicChart MCP
server so routine `agent_context`, slice expansion, snapshot, validate, and update calls do
not stop on every tool approval prompt. This approval applies only to that project-scoped
LogicChart server block.

When supported by the agent, setup also installs a project-scoped LogicChart skill. The
skill tells the agent to use `agent_context` for implicit code-logic questions and to call
`snapshot_slice` when the user asks to show, visualize, render, diagram, or open a
workflow/canvas view. If inline SVG rendering is not available, the agent should show a
canonical top-to-bottom Mermaid `flowchart TD` from
`workflow_slice.presentation.canonical_visual.diagram`, keep its `diagram_hash` when useful,
then provide the returned `viewer_targets` command and hash target. Agents should not
synthesize alternate Mermaid diagrams or add limits, error codes, or branches that are not
present in the `workflow_slice` payload. The agent may choose a shallower or deeper view
by asking LogicChart for a narrower slice, `expand_slice`, or `workflow_path`, but every
displayed block must come from deterministic slice fields or a focused explain tool. A
language-friendly rewrite is allowed only as a separate translation layer in the language
used by the user, preserving ids or source anchors and not adding facts. In practice, SVG
snapshots are the best inline visual when the client supports images, canonical
top-to-bottom Mermaid is the portable text fallback, and `logicchart view` remains the
interactive manual viewer.

High-value MCP tools include:

| Tool | Use |
| --- | --- |
| `agent_context` | Default one-call path for natural code-logic questions and change impact. |
| `expand_slice` | Widen or deepen an existing workflow slice by stable flow/finding handles. |
| `workflow_path` | Trace between two flows, symbols, routes, states, or concepts when statically modeled. |
| `snapshot_slice` | Render a deterministic SVG snapshot for the selected slice. |
| `explain_flow`, `explain_node`, `explain_edge` | Inspect focused entities when the first slice is not enough. |
| `domain_map` | Aggregate state/domain handling, missing values, related flows, and review signals. |
| `preview_annotation_targets`, `write_annotations`, `validate_annotations`, `annotation_status`, `clear_annotations` | Manage local agent-authored annotation sidecars. |
| `validate_artifacts`, `update_logicchart` | Recover from stale or missing artifacts inside the agent workflow. |

Snapshot tools return deterministic SVG and metadata, including omission counts and layout
quality where available. Workflow-slice and `snapshot_slice` payloads also include
`viewer_targets`, with hash fragments such as `#flow=<flow-id>` that can be appended to the
generated viewer URL for manual follow-up.

## Trust Model

LogicChart separates deterministic facts, deterministic heuristics, review candidates, and
generated text.

Evidence tiers:

- `VERIFIED`: syntax-backed or source-backed.
- `INFERRED`: deterministic heuristic with explainable basis.
- `POTENTIAL_GAP`: review candidate, not a confirmed defect.
- `agent_generated`: optional annotation text written by a coding agent.

Agents must not present `INFERRED`, `POTENTIAL_GAP`, or `agent_generated` content as
confirmed bugs. The analyzer model remains the source of truth; annotations only improve
readability.

## Agent-Authored Annotations

LogicChart does not ask for provider keys in the primary workflow.

Preferred enrichment loop:

1. The agent calls `agent_context` or `preview_annotation_targets`.
2. The agent generates clearer labels, summaries, explanations, or remediation notes using
   its own model.
3. The agent writes them through MCP `write_annotations`.
4. LogicChart validates schema version, model hash, stable ids, text limits, and provenance.
5. MCP responses, snapshots, and the viewer display annotations as optional generated text.

`write_annotations` accepts `generated_by.kind="agent_generated"` provenance only. Advanced
provider-managed enrichment code may exist for maintainers, but it is not the public setup
story and is not required for normal use.

See [docs/llm.md](docs/llm.md) for the annotation workflow.

## Manual Viewer

The viewer is the official manual inspection experience:

```bash
logicchart view
```

It opens a local, offline HTML artifact for humans who want to inspect the decision
flowchart directly. The viewer is secondary to the agent workflow, but it remains a central
product capability.

The viewer provides:

- a progressive codebase canvas from scopes to entrypoints to flow detail;
- direct flow and path deep links;
- source and review-signal details;
- review-signal diagnostics with evidence tiers and related evidence;
- optional annotation overlays when the sidecar matches the current model;
- project quality metrics;
- pan, zoom, fit, reset, drag, full-screen, and PNG/JPG export;
- stable selection for flows, nodes, and edges.

Useful commands:

```bash
logicchart view
logicchart view --port 8771
logicchart view --render-only --no-open
```

See [docs/viewer.md](docs/viewer.md) for the viewer architecture and verification loop.

## CLI Surface

The public CLI is intentionally small:

| Command | Purpose |
| --- | --- |
| `logicchart setup-agent` | Configure a project once for a coding agent. |
| `logicchart update` | Refresh generated artifacts after source changes. |
| `logicchart view` | Open or render the manual viewer. |
| `logicchart validate` | Validate artifact schema, sync state, quality gates, and annotations. |
| `logicchart doctor` | Diagnose install, parser, artifact, and capability issues. |
| `logicchart mcp` | Start the MCP server over stdio. |

The old command-shaped analysis workflows belong behind MCP or internal orchestration. Users
should not need to memorize `query`, `impact`, `explain`, `navigate`, or `snapshot`
commands.

Use help before scripting:

```bash
logicchart --help
logicchart setup-agent --help
logicchart update --help
logicchart view --help
logicchart validate --help
logicchart doctor --help
logicchart mcp --help
```

## Setup-Agent

Supported setup targets:

```bash
logicchart setup-agent codex
logicchart setup-agent claude ../my-app
logicchart setup-agent gemini
logicchart setup-agent cursor --full
```

The selected target controls which instruction file and optional skill are written.
`setup-agent` does not create unrelated agent files:

- `AGENTS.md` plus `.agents/skills/logicchart/SKILL.md` for Codex;
- `CLAUDE.md` plus `.claude/skills/logicchart/SKILL.md` for Claude Code;
- `GEMINI.md` for Gemini CLI instructions;
- `.cursor/rules/logicchart.mdc` for Cursor.

Codex, Claude, and Cursor also receive their project-scoped MCP config. Gemini is currently
instruction-only; use an agent with project-scoped MCP support for the runtime integration.

`setup-agent` preserves local notes inside managed instruction blocks. Put private fixture
warnings or project-specific checks in the local-notes section instead of editing the
standard LogicChart guidance by hand.

Useful flags:

- `--full`: ignore the incremental cache.
- `--no-html`: skip the local HTML artifact.
- `--profile demo|self|project`: use a built-in analysis profile.

## Update And Validate

Use `update` after meaningful source changes:

```bash
logicchart update
logicchart update --full
logicchart update --no-html
```

Use `--full` after analyzer upgrades or when cached file models should be ignored.

Use `validate` in CI and before committing artifacts:

```bash
logicchart validate
logicchart validate --check-sync
logicchart validate --quality --json
logicchart validate --annotations --json
logicchart validate --max-skipped-files 0 --max-parse-warnings 0 --min-call-resolution 0.5
```

Validation checks schema, artifact freshness, optional annotation sidecars, finding-rule
metadata contracts, and deterministic quality metrics. Quality gates can fail on skipped
files, parse warnings, low call-resolution rate, or high generic-label ratio.

## Domain Logic

LogicChart is built for code-logic understanding, not just call graphs. It extracts and
aggregates domain concepts such as:

- enum members;
- status and lifecycle states;
- roles and permissions;
- feature flags;
- handled and missing values;
- related decisions and review signals.

MCP `domain_map` connects these concepts to flows, nodes, source ranges, snapshots, and
`agent_context`. Value filters match handled and missing values, including enum-style suffix
matches such as `PAID` for `Status.PAID`.

## Review Signals

Review signals are deterministic inspection guidance. They are not automatic bug reports.

Single-flow signals include:

- `missing_branch`;
- `dead_code`;
- `broad_except_swallow`;
- `no_op_branch`;
- `asymmetric_return`;
- `dead_guard`.

Cross-flow signals include:

- `inconsistent_case_handling`;
- `enum_exhaustiveness`;
- `outcome_inconsistency`;
- `logging_asymmetry`;
- `auth_divergence` when `gated_detectors = true`.

Every signal carries normalized diagnostic metadata:

- stable rule id, detector category, severity, evidence tier, and confidence basis;
- source scope with flow, node, file, and line ranges;
- detector inputs and expected/actual/missing state when applicable;
- evidence chain with detector-specific proof points;
- review prompt and suggested next actions.

The shared rule registry is emitted under `metadata.finding_rules`, so Markdown, the viewer,
and MCP explain review signals with the same contracts.

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

Generated models include `metadata.language_capabilities`, with feature flags and limitation
notes per language. Agents should use that contract when explaining analyzer depth.

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

Defaults prune common VCS, dependency, cache, temporary, generated, and output directories,
including `.git`, `node_modules`, virtualenv folders, `.next`, `.turbo`, `.svelte-kit`,
`dist`, `build`, `out`, `target`, `coverage`, `vendor`, `Pods`, and `logicchart-out`.

Use `exclude_dirs` for whole directory names that should be skipped before traversal. Use
`exclude` for file or path globs.

With no declared scopes, top-level directories become inferred scopes. A file can belong to
multiple declared scopes.

Built-in profiles:

| Profile | Source roots | Output directory | Use |
| --- | --- | --- | --- |
| `demo` | `examples` | `logicchart-out/` | Public demo artifact. |
| `self` | `src/logicchart` | `logicchart-out/self/` | Dogfood map for LogicChart internals. |
| `project` | `src`, `tests`, `examples` | `logicchart-out/project/` | Whole-checkout map for agents. |

## Limitations

LogicChart does not run code, observe runtime state, perform full symbolic execution, prove
business correctness, or reconstruct deep framework state. It statically models source files,
control flow, selected framework conventions, and resolvable internal calls.

Important practical limits:

- dynamic dispatch may remain unresolved;
- language capability varies by analyzer frontend;
- generated or unsupported files may be skipped;
- large slices are token-budgeted and report omissions;
- review signals require human or agent review before action.

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

## Philosophy Check

A feature belongs in LogicChart when it helps an agent or human answer at least one of
these questions better:

- Which workflow slice answers this question?
- What does this code do?
- Which logical path am I looking at?
- What decisions and states control the behavior?
- What calls or callers are involved?
- What changes if I edit this?
- What looks missing, risky, or uncertain?
- What evidence proves this?
- What visual context can clarify it quickly?

If a feature does not improve code-logic understanding, impact reasoning, trust, or visual
orientation, it should not be central to the product.

## License

Apache License 2.0. See [LICENSE](LICENSE).

LogicChart was created by Ferdinando Bonsegna. If you use, fork, or build on it, keep the
[NOTICE](NOTICE) file intact and credit the project with a link back to this repository.
