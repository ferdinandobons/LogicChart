# Changelog

All notable changes to CodeDebrief will be documented in this file.

The project follows Semantic Versioning.

## Unreleased

## 0.16.0 - 2026-06-22

### Added

- Allowed `source_roots` and `codedebrief setup --source` to point at sibling repositories,
  so one workspace can model workflows that span multiple local repos while keeping
  CodeDebrief config and artifacts in a dedicated root folder.
- Made CLI progress output clearer during `setup`, `update`, `view`, and non-JSON
  `validate`, including mode, source roots, artifact targets, and long-running steps.

### Fixed

- Kept `validate --check-sync` and MCP `validate_artifacts(check_sync=true)` from priming
  the normal incremental cache, so a following `update_codedebrief` still detects changed
  files and refreshes stale artifacts correctly.

## 0.15.0 - 2026-06-22

### Added

- Added `codedebrief setup <agent> --source <path> [...]` so initial setup can index only
  selected folders before the first artifact generation starts.

### Fixed

- Suppressed non-fatal Python `SyntaxWarning` messages from analyzed project files during
  `setup` and `update`; valid files with legacy string escapes are still analyzed.
- Wrote JSON MCP configs from WSL `/mnt/<drive>/...` projects through `wsl.exe --cd` so
  Windows-native agent clients do not receive raw WSL paths as command targets.

### Documentation

- Documented how to analyze only selected folders with `source_roots` while keeping
  `codedebrief-out` in the current project root.

## 0.14.1 - 2026-06-22

### Fixed

- Normalized Python comprehension labels so generated CodeDebrief artifacts stay
  synchronized across Python 3.10 and newer Python versions.

## 0.14.0 - 2026-06-22

### Added

- Added GitHub issue forms and a pull request template so reports and contributions collect
  the CodeDebrief context needed for triage.

### Changed

- Strengthened artifact updates with batch rollback across generated files and a local
  update lock shared by CLI, validation, and MCP refresh paths.
- Tightened `codedebrief.toml` parsing so malformed config values fail with explicit,
  field-level errors instead of being coerced silently.
- Expanded CI release parity to validate synchronized artifacts, build the viewer, build
  package distributions, check distribution metadata, and smoke-test an installed wheel.

### Fixed

- Made MCP artifact refresh failures return structured, recoverable errors with a clear
  validation follow-up instead of surfacing raw local exceptions.
- Compacted long labels and paths in generated SVG snapshots to reduce text overflow in
  rendered workflow diagrams.

## 0.13.0 - 2026-06-22

### Added

- Added a small GitHub Pages landing page for the repository website link.

### Changed

- Made artifact, Markdown, and config writes atomic so interrupted updates do not leave
  partial files behind.
- Improved Python call resolution for source-layout package aliases, same-class receivers,
  deterministic multi-target calls, and project-call quality metrics.
- Updated quality reporting to separate runtime/dynamic calls from project calls and reduce
  false generic-label warnings.
- Updated viewer Analysis Health wording and source snippet payloads so rendered flow
  context carries exact source ranges.

### Fixed

- Made `validate --check-sync` verify both JSON and Markdown artifact sync.
- Added setup and doctor guidance for migrating stale `logicchart` MCP configuration to
  `codedebrief`.
- Preserved compatibility for legacy `POTENTIAL_GAP` evidence while keeping review-finding
  concepts out of the public comprehension model.

## 0.12.0 - 2026-06-21

### Added

- Published the `codedebrief` package on PyPI and made `uv tool install codedebrief` the
  primary README install path.
- Added a README screenshot for the manual `codedebrief view` canvas.

### Changed

- Updated generated agent guidance so workflow artifacts are refreshed after
  workflow-relevant changes before finalizing or committing.
- Made CodeDebrief workflow visuals vertical by default, with horizontal output reserved
  for explicit compact-overview requests.

### Fixed

- Fixed the manual viewer details rail so the Analysis Health panel no longer leaves a
  stale empty source panel when no flow source is selected.

## 0.11.0 - 2026-06-21

### Added

- Added a README preview image that shows the kind of source-backed visual workflow a
  coding agent can present from CodeDebrief artifacts.

### Changed

- Renamed the project, Python package, CLI, MCP server, generated artifacts, viewer runtime,
  and documentation surface to CodeDebrief.
- Made `examples/` local-only and ignored; the committed dogfood artifact now maps
  `src/codedebrief` instead of relying on tracked demo/shop fixtures.

## 0.10.0 - 2026-06-21

### Changed

- Reoriented CodeDebrief around code-logic comprehension instead of review findings:
  MCP workflow slices, agent instructions, Markdown artifacts, and the generated viewer
  now emphasize deterministic flows, decisions, calls, source anchors, visual snapshots,
  and manual exploration through `codedebrief view`.
- Moved MCP into the default runtime install so release and source-checkout installs include
  the primary agent surface without requiring an optional extra.
- Updated agent setup so it writes only the
  requested target's instruction, skill, and MCP files.
- Added Gemini CLI / Antigravity parity for Gemini setup: it now writes the
  provider-native CodeDebrief skill and project-scoped `.gemini/settings.json` MCP config,
  including the same Mermaid artifact guidance used by Claude when inline rendering is not
  available.
- Updated agent guidance so visual workflow answers use the deterministic
  `workflow_slice.presentation.canonical_visual.diagram` first, persist Mermaid `.mmd` /
  Markdown artifacts for clients without inline Mermaid rendering, avoid long raw Mermaid
  code blocks as the primary visual, and reserve SVG snapshots for explicit SVG or
  local-inspection requests.
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
  top-to-bottom Mermaid output, `diagram_hash`, viewer targets, local `.mmd` / Markdown
  snapshot artifacts, and legacy SVG/HTML artifacts for local inspection.
- Added analyzer quality, skipped-file, language-capability, and parse-warning metadata for
  comprehension-oriented validation and viewer summaries.

### Removed

- Removed the public CLI surface for `query`, `impact`, `explain`, `navigate`, and
  `snapshot`; those deterministic capabilities remain internal/MCP-only.
- Removed `analyze`, `init`, `install`, `llm`, and `enrich` from the public CLI surface;
  `update` owns refresh/full analysis and setup owns initialization and agent setup.
- Removed dead internal finding detector modules, diagnostic helpers, gated detector
  configuration, detector-only tests, and obsolete example expected-finding docs.
- Removed dead provider-managed LLM enrichment code and provider/model configuration.
- Removed `docs/llm.md`, `docs/viewer.md`, and the obsolete viewer screenshot asset now
  covered by the README and generated agent/setup guidance.
- Removed findings/review queues from the generated viewer and public MCP workflow path.
- Removed the legacy `findings` artifact field and moved the canonical model schema to
  `2.0`.

### Fixed

- Fixed visual workflow guidance so repeated chat requests prefer vertical/top-to-bottom
  deterministic visuals and offer language-friendly or expanded follow-ups without
  changing graph facts.
- Fixed stale docs and examples that still described CodeDebrief as a review-signal or
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

- Added `codedebrief doctor` to check the active installation, parser grammar imports, and
  repair command for stale editable installs.

### Fixed

- Fixed analysis robustness when a lazy language grammar is missing from the active Python
  environment: affected files are now reported as skipped instead of aborting the whole run.
- Fixed `codedebrief --version` so it follows installed package metadata instead of a stale
  duplicated constant.

## 0.4.1 - 2026-06-16

### Fixed

- Fixed packaged `codedebrief validate` so installed wheels include and load the bundled JSON
  Schema outside the source checkout.

## 0.4.0 - 2026-06-16

### Added

- Added built-in analysis profiles for the public demo artifact, CodeDebrief self-analysis,
  and a whole-checkout project map without overwriting each other.
- Added `codedebrief validate`, artifact/schema registry validation, and optional full
  source sync checks for local CI and agent workflows.
- Added richer query filters and ranking signals (`--language`, `--finding-kind`, scope,
  language, path, decision metadata, and finding text).
- Added MCP agent tools for prioritized review queues, compact context packs, and artifact
  validation.
- Added optional `codedebrief install --mcp-config ...` project MCP config generation and
  server instructions for agent workflow guidance.
- Added viewer flow search and a prioritized review queue in the review-signals panel.
- Clarified the earlier CLI/MCP agent workflow in the README.

### Changed

- Simplified the README Quick Start to the two commands needed for first success:
  `codedebrief analyze --full` and `codedebrief view`.
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

- Macro-part scopes: declare `[codedebrief.scopes]` (or fall back to the inferred top-level
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
  canonical `codedebrief.json` model (schema 1.1).
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
  managed git auto-sync hooks with a `merge=union` driver for `codedebrief.json`.

### Robustness

- Incremental content-hash cache with per-file analysis.
- Per-file parse isolation: an un-parseable or non-UTF-8 file is skipped and reported
  in `skipped_files` rather than aborting the whole run.
- Malformed `codedebrief.json` is rejected with a clean error instead of a raw traceback.
