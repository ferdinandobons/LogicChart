# Changelog

All notable changes to LogicChart will be documented in this file.

The project follows Semantic Versioning.

## Unreleased

### Changed

- Reoriented LogicChart around code-logic comprehension instead of review findings:
  MCP workflow slices, agent instructions, Markdown artifacts, and the generated viewer
  now emphasize deterministic flows, decisions, calls, source anchors, visual snapshots,
  and manual exploration through `logicchart view`.
- Moved MCP into the default runtime install so `uv tool install logicchart` includes the
  primary agent surface without requiring an optional extra.
- Updated `logicchart setup-agent codex|claude|gemini|cursor` so setup writes only the
  requested target's instruction file and installs provider-native LogicChart skill
  guidance where supported.
- Updated agent guidance so visual workflow answers use the deterministic
  `workflow_slice.presentation.canonical_visual.diagram` or MCP snapshot artifacts instead
  of hand-building divergent Mermaid diagrams.
- Replaced standalone LLM/viewer docs with the README, generated agent instructions, and
  `CONTRIBUTING.md` as the maintained public guidance surfaces.

### Added

- Added `workflow_slice` to MCP `agent_context`, with stable slice handles, ordered
  workflow steps, primary/supporting flows, decisions, calls, domain logic, source ranges,
  visual handles, omissions, guardrails, and next-tool hints.
- Added MCP `expand_slice`, `workflow_path`, `snapshot_slice`, `explain_flow`,
  `explain_node`, and `explain_edge` for progressive workflow-slice navigation and focused
  source-grounded inspection.
- Added deterministic visual presentation metadata for workflow slices, including stable
  top-to-bottom Mermaid fallback, `diagram_hash`, viewer targets, and local SVG/HTML
  snapshot artifacts for clients that can render inline widgets.
- Added optional local annotation sidecars and MCP annotation tools for agent-authored
  enrichment without requiring provider keys.
- Added analyzer quality, skipped-file, language-capability, and parse-warning metadata for
  comprehension-oriented validation and viewer summaries.

### Removed

- Removed the public CLI surface for `query`, `impact`, `explain`, `navigate`, and
  `snapshot`; those deterministic capabilities remain internal/MCP-only.
- Removed `analyze`, `init`, `install`, `llm`, and `enrich` from the public CLI surface;
  `update` owns refresh/full analysis and `setup-agent` owns initialization and agent
  setup.
- Removed dead internal finding detector modules, diagnostic helpers, gated detector
  configuration, detector-only tests, and obsolete example expected-finding docs.
- Removed dead provider-managed LLM enrichment code and provider/model configuration. MCP
  annotation preview is now local-only and feeds agent-authored sidecars.
- Removed `docs/llm.md`, `docs/viewer.md`, and the obsolete viewer screenshot asset now
  covered by the README and generated agent/setup guidance.
- Removed findings/review queues from the generated viewer and public MCP workflow path.
  The legacy empty `findings` field remains in schema 1.1 for artifact compatibility.

### Fixed

- Fixed visual workflow guidance so repeated chat requests prefer vertical/top-to-bottom
  deterministic visuals and offer language-friendly or expanded follow-ups without
  changing graph facts.
- Fixed stale docs and examples that still described LogicChart as a review-signal or
  detector product.

## 0.8.0 - 2026-06-17

### Added

- Added dedicated viewer documentation covering the progressive flowchart product shape,
  the static and React runtime split, layout invariants, and browser verification loop.
- Added React-viewer viewport panning with reset coverage in the frontend test suite.

### Changed

- Clarified README and contributor instructions for the framework-backed viewer runtime,
  generated runtime bundle, cache-busted browser checks, and viewer-specific gates.

### Fixed

- Fixed the React viewer so clicking empty canvas space clears selected connections, and
  dimmed scope-entry links now fade consistently with dimmed canvas nodes.

## 0.7.0 - 2026-06-16

### Added

- Added PNG and JPG export buttons for the currently visible flowchart canvas.
- Added session-local drag positioning for scope, flow, and inline decision blocks, with
  reset restoring the automatic progressive layout.

### Changed

- Reworked the viewer canvas toward a single progressive flowchart: scopes expand into
  entrypoint/call rows, selected decision charts unfold in that same route, and selected
  links highlight their source and target while unrelated blocks dim.
- Unified scope nodes with the rest of the canvas block styling so top-level areas do not
  read as a separate visual component family.

## 0.6.2 - 2026-06-16

### Changed

- Updated the HTML viewer so expanding a scope keeps the whole codebase map visible while
  drawing the active scope's files and flows in place.
- Added folder/file path focus in the viewer (`#path=...`) so clicking a tree folder
  highlights the matching canvas area without losing global context.

## 0.6.1 - 2026-06-16

### Fixed

- Fixed Markdown report rendering for enum-backed finding kinds so reports show public
  values such as `missing_branch` instead of Python enum names.

## 0.6.0 - 2026-06-16

### Added

- Added C++ control-flow support for `.cc`, `.cpp`, `.cxx`, `.hh`, `.hpp`, `.hxx`, `.ipp`,
  and `.tpp` files.

### Changed

- Improved large-codebase defaults by excluding more common dependency caches, build output,
  and generated-code patterns during discovery.
- Refined the HTML viewer for broad codebase study with scope/file finding density, a
  responsive details-panel toggle, and an empty state for tree search/filter misses.
- Restructured the README around project purpose, quick start, scale behavior, viewer usage,
  and supported languages.

## 0.5.0 - 2026-06-16

### Added

- Added `logicchart doctor` to check the active installation, parser grammar imports, and
  repair command for stale editable installs.

### Fixed

- Fixed analysis robustness when a lazy language grammar is missing from the active Python
  environment: affected files are now reported as skipped instead of aborting the whole run.
- Fixed `logicchart --version` so it follows installed package metadata instead of a stale
  duplicated constant.

## 0.4.1 - 2026-06-16

### Fixed

- Fixed packaged `logicchart validate` so installed wheels include and load the bundled JSON
  Schema outside the source checkout.

## 0.4.0 - 2026-06-16

### Added

- Added built-in analysis profiles for the public demo artifact, LogicChart self-analysis,
  and a whole-checkout project map without overwriting each other.
- Added `logicchart validate`, artifact/schema registry validation, and optional full
  source sync checks for local CI and agent workflows.
- Added richer query filters and ranking signals (`--language`, `--finding-kind`, scope,
  language, path, decision metadata, and finding text).
- Added MCP agent tools for prioritized review queues, compact context packs, and artifact
  validation.
- Added optional `logicchart install --mcp-config ...` project MCP config generation and
  server instructions for agent workflow guidance.
- Added viewer flow search and a prioritized review queue in the review-signals panel.
- Clarified the earlier CLI/MCP agent workflow in the README.

### Changed

- Simplified the README Quick Start to the two commands needed for first success:
  `logicchart analyze --full` and `logicchart view`.
- Updated public/package positioning around local-first decision flowcharts for humans and
  coding agents.
- Removed internal planning/design documents from `docs/`, keeping the public repository
  focused on end-user documentation and README assets.

### Removed

- Removed Terraform/HCL support.
- Removed the `diff` (CI gate) and `hook` (git auto-sync) commands; both are tracked as planned future evolutions.

## 0.3.0

Major capability expansion: from a Python/TypeScript analyzer to a polyglot,
whole-codebase one - 10 control-flow languages plus Terraform, organized by macro-part.

### Languages

- Profile-driven tree-sitter engine: a new control-flow language is a `LanguageProfile`
  (grammar vocabulary + a few extractors), not a bespoke analyzer.
- Added Go, Java, C#, PHP, C, Rust, and Ruby alongside the existing Python and
  TypeScript/JavaScript analyzers - 10 control-flow languages in all.
- Terraform/HCL support: each `resource` / `module` / `data` / `variable` / `output` block
  becomes a flow and each reference (`aws_vpc.main.id`, `depends_on`) becomes a dependency
  edge, so the IR carries a resource dependency graph.
- Pluggable language registry keyed by file suffix, with lazy grammar loading.
- Rust `match` is treated as compiler-exhaustive: a missing `_` arm is no longer flagged as
  a missing fallback.

### Whole codebase and scopes

- Macro-part scopes: declare `[logicchart.scopes]` (or fall back to the inferred top-level
  directory) so one model can be viewed whole or restricted to backend/frontend/infra.
- `--scope` on `query` and `impact`; scope and language filters in the viewer.
- Every flow records the scope(s) it belongs to; the Markdown header summarizes the
  per-scope breakdown.

### Viewer

- UI refresh: a new logo - a blue entry-node circle, a violet connector, and an amber
  decision diamond in three solid colors with clear spacing (and a matching favicon); a
  light/dark theme toggle (remembered across sessions); refined palette; node hover and
  shadow states; selecting a block now highlights it and its connected edges while dimming
  the rest; and the legend now includes the cyan "outcome" (terminal) node color it was
  missing.

### Examples & fixes

- `examples/demo` is now a polyglot "users & orders" platform spanning all 10
  control-flow languages plus Terraform/HCL across backend/frontend/edge/infra scopes.
- `analyze` summary wording: "{n} finding(s)" instead of the earlier hybrid review
  wording.

## 0.2.1

- Interactive viewer: drag any block to rearrange the flowchart by hand; connected edges
  re-route live, hand-placed positions persist per flow, and reset restores the auto layout.
- README rewritten for clarity: sharper scope, a runnable 30-second example, an outcome-
  focused "Why", a per-command reference with real output, explicit limitations, and the
  agent/MCP integrations moved to an "Advanced" section.

## 0.2.0

First tagged release. A deterministic, local, no-API-key static analyzer that turns
Python and TypeScript source into a versioned logical model plus reviewable
flowcharts, with evidence-tiered findings (`VERIFIED` / `INFERRED` / `POTENTIAL_GAP`).

### Analysis & IR

- Deterministic Python (AST) and TypeScript/TSX (tree-sitter) analyzers producing one
  canonical `logic-flow.json` model (schema 1.1).
- Framework adapters: FastAPI routes; Next.js route handlers, middleware, server
  actions, pages, and layouts; shallow React components, hooks, and event handlers;
  public/exported functions, CLI commands, and tests.
- IR enrichment: per-branch outcomes, decision identity (subject/operator/negation/
  value namespace), reachability, side-effect tags, declared enum/union value tables,
  module-level constants, and stable structural finding ids.
- Import-aware call resolver with `module:symbol` boundary preservation, longest-prefix
  module resolution, submodule-import binding, and per-call link confidence.

### Detectors (11, evidence-tiered)

- Single-flow: `missing_branch`, `dead_code`, `broad_except_swallow` (empty **or**
  log-only handlers), `no_op_branch`, `asymmetric_return`, `dead_guard`.
- Cross-flow: `inconsistent_case_handling` (quorum-aware), `enum_exhaustiveness`,
  `outcome_inconsistency` (HTTP status-aware), `logging_asymmetry`.
- Gated (opt-in via `gated_detectors`): `auth_divergence`.

### Surfaces

- CLI: `init`, `analyze` (`--full`, `--include-gaps`), `update`, `impact`, `query`,
  `view`, `install`, `hook` (install/uninstall/status), `mcp`, and `diff`.
- CI diff gate: `diff` compares two models by stable finding id and emits a GitHub
  Markdown summary and SARIF (stable `partialFingerprints`), with `--fail-on-introduced`.
- Markdown report with a signal/noise split - `VERIFIED`/`INFERRED` in the main
  section, `POTENTIAL_GAP` folded under a collapsible review-only block (`--include-gaps`
  to expand) - plus injection-safe escaping of source-derived finding text.
- Interactive local HTML viewer.
- MCP server with 11 tools and a `token_budget` cap on every query/list tool.
- Agent instruction installer (`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, Cursor rules) and
  managed git auto-sync hooks with a `merge=union` driver for `logic-flow.json`.

### Robustness

- Incremental content-hash cache with per-file analysis.
- Per-file parse isolation: an un-parseable or non-UTF-8 file is skipped and reported
  in `skipped_files` rather than aborting the whole run.
- Malformed `logic-flow.json` is rejected with a clean error instead of a raw traceback.
