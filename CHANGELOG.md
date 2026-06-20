# Changelog

All notable changes to LogicChart will be documented in this file.

The project follows Semantic Versioning.

## Unreleased

### Added

- Added structured diagnostic metadata for every finding, including stable detector rule
  ids, confidence basis, expected/actual/missing state, evidence chains, review prompts,
  and suggested next actions.
- Added detector-specific single-flow diagnostic evidence for implicit fallbacks, constant
  guards, swallowed handlers, no-op branches, and asymmetric dispatch returns.
- Added bounded related-decision scope to cross-flow diagnostics, including related flow
  and node ids plus source ranges for evidence-chain entries.
- Added deterministic review-signal explanation payloads with evidence-tier guardrails for MCP
  and internal agent context.
- Added optional finding-annotation enrichment overlays across MCP finding/review/context
  tools and the Review Signals panel.
- Added optional scope-annotation labels and summaries to the React flowchart and flow
  navigation annotation payloads.
- Added stable finding ids to the generated Markdown findings list.
- Added a shared finding-rule registry to generated model metadata and exposed it through
  MCP with a new `finding_rules` tool.
- Added concise true-positive and intentional-suppression examples to every finding-rule
  contract in metadata and MCP responses.
- Added deterministic SVG MCP snapshot tools for flow, finding, impact, and explicit
  flow/finding subgraph visual context.
- Added deterministic SVG snapshot rendering for MCP visual context.
- Added structured, recoverable MCP artifact-load errors with error codes, artifact paths,
  guardrails, and next-tool/CLI recovery actions.
- Added MCP artifact workflow hints for update/validate/review sequencing, including stale
  model recovery through `update_logicchart`.
- Added structured recoverable errors for unknown MCP flow/finding targets and invalid
  snapshot targets.
- Added token-budget handling to MCP flow, finding, and impact SVG snapshots, including
  omission counts for capped visual context.
- Added target, unresolved-target, impact-reason, and subgraph metadata to impact snapshot
  payloads for MCP and internal use.
- Added deterministic layout metadata to flow, finding, and impact snapshot payloads,
  including canvas size, rendered positions, compact flags, and omitted edge/flow counts.
- Added deterministic layout metadata to subgraph snapshot payloads, including flow
  sections, rendered node positions, compact flags, and unresolved target reporting.
- Added snapshot `layout_quality` summaries across CLI and MCP visual payloads, reporting
  complete versus compact rendering plus key omission counts for agents.
- Added snapshot `layout_quality.clarity` signals for rendered-box overlaps, edge
  obstacles, canvas overflow, and minimum box gaps in CLI and MCP visual payloads.
- Added a compact diagnostic panel to MCP finding SVG snapshots with evidence tier,
  confidence, review prompt, and evidence-chain summaries.
- Added deterministic model-quality metrics, exposed through generated metadata,
  `logicchart validate --quality`, MCP summaries, and `validate_artifacts`.
- Added optional parse-warning quality thresholds to CLI `validate` and MCP
  `validate_artifacts`.
- Added per-language depth metrics to the quality payload, including file/flow coverage,
  decisions, calls, findings, source coverage, capability metadata, and attention signals.
- Added TypeScript/JavaScript expression-bodied arrow function support, including ternary
  React component decisions with explicit return branches and capability-matrix metadata.
- Added an MCP `analysis_quality` tool with bounded analyzer-quality payloads, guardrails,
  and next-tool hints for agent review workflows.
- Added parse-warning attention signals and bounded parse-warning samples to MCP
  `analysis_quality`.
- Added a Project Quality panel to the generated viewer details rail, showing analyzer
  coverage, call-resolution, finding, generic-label, graph-density, and language metrics.
- Added right-rail expand-all and collapse-all controls for the Project Quality, Source,
  and Review Signals detail sections.
- Added a deterministic language capability matrix to generated metadata and MCP summaries.
- Added a fast `logicchart doctor` language-capability summary for supported language ids,
  feature flags, and limitation notes without running analysis or smoke tests.
- Added persisted skipped-file reasons in generated metadata, quality metrics, and the
  viewer quality panel.
- Added optional quality thresholds for CI-oriented `validate` and MCP artifact validation.
- Added MCP flow-navigation packs with callers, callees, decisions, findings, and next-tool
  hints for token-bounded agent workflows.
- Added MCP `preview_enrichment` so agents can inspect bounded candidate annotation targets
  locally without making provider calls.
- Added MCP finding-context packs with focus flow, related evidence nodes, related flows,
  evidence guardrails, and next-tool hints for review-signal inspection.
- Added deterministic impact targets for flow ids, symbols, and finding ids across CLI and
  MCP, with subgraph ids and unresolved-target reporting.
- Added deterministic dependency-path impact targets across CLI, snapshots, MCP
  `analyze_impact`, `get_impact_snapshot`, and `context_pack`.
- Added first-party file dependency records for Python, TypeScript/JavaScript, Go, and
  Java imports, so changed config/type/helper files can impact importing flows even when
  the changed file has no modeled flow.
- Added conservative C# `using` dependency records, so impact analysis can include ASP.NET
  or service methods that depend on changed first-party C# files.
- Added per-flow impact reasons to MCP/internal impact analysis, so agents can see why
  each direct or caller impact was selected.
- Added deterministic query filters for source paths, symbols/names, decision domains,
  handled values, finding kind, finding severity, and finding evidence tier across MCP and
  internal context paths.
- Added query-result follow-up hints for MCP tools, so agents can move
  from a ranked match to navigation, visual snapshot, impact, or context-pack review.
- Added bounded finding metadata and subgraph snapshot targets to MCP/internal query results,
  so agents can move from `query_logic` directly into focused review-signal inspection without
  loading a full graph.
- Added optional inline visual context to MCP `context_pack`, with SVG impact, subgraph,
  flow, and finding snapshots gated by `include_visual` and capped by `token_budget`.
- Added deterministic query filters to MCP `context_pack`, matching `query_logic` for
  source, language, state-domain, handled-value, finding-kind, severity, and evidence
  slices.
- Added a deterministic `visual_byte_budget` cap for inline MCP `context_pack` SVG
  snapshots, with omission counts and recovery through returned snapshot tools.
- Added explicit flow/symbol/finding impact targets and per-flow impact reasons to MCP
  `context_pack`, matching `analyze_impact` for agent-oriented context retrieval.
- Added bounded flow-navigation packs to MCP `context_pack`, so agents get caller/callee,
  decision, finding, annotation, and next-tool orientation for relevant flows without an
  immediate second tool call.
- Added MCP `agent_context` as the primary agent entrypoint for ordinary code-logic
  questions, change-impact review, focused flow/finding inspection, selected-code context,
  and optional visual context.
- Added `workflow_slice` to MCP `agent_context`, with stable slice handles, ordered
  workflow steps, primary/supporting flows, decisions, calls, domain logic, review signals,
  source ranges, visual handles, omissions, guardrails, and next-tool hints.
- Added `viewer_targets` to workflow-slice and `snapshot_slice` MCP payloads so agents can
  hand humans stable `logicchart view` hash fragments for manual inspection.
- Added MCP `expand_slice`, `workflow_path`, `snapshot_slice`, `explain_flow`,
  `explain_node`, and `explain_edge` for progressive workflow-slice navigation and focused
  source-grounded inspection.
- Added provider-native LogicChart skill installation for Codex and Claude setup, guiding
  agents to use MCP `agent_context` by default and `snapshot_slice`/`viewer_targets` for
  visual workflow requests.
- Updated generated LogicChart agent guidance so visual workflow requests prefer a
  detailed Mermaid flowchart fallback with decision/error branches instead of a compact
  linear summary when inline SVG is unavailable.
- Added direct MCP contract tests for visual `context_pack`, flow-navigation packs, and
  recoverable helper payloads, complementing end-to-end stdio coverage.
- Added stricter finding-rule contract tests that pin every detector's public purpose,
  preconditions, caveats, metadata fields, review prompt, and next-action shape.
- Added artifact validation for present finding-rule metadata contracts, including current
  registry sync, rule-declared finding metadata fields, and diagnostic rule-id alignment.
- Added JSON Schema coverage for optional generated diagnostic, finding-rule, quality,
  language-capability, and skipped-file metadata while keeping artifact schema 1.1
  forward-compatible for custom metadata.
- Added deterministic accessibility summaries to viewer flow nodes for broad-canvas
  scanning.
- Added a local optional `logic-annotations.json` sidecar schema, validation, viewer
  overlays, and MCP status/navigation exposure.
- Added MCP `preview_annotation_targets`, `write_annotations`, `validate_annotations`,
  `annotation_status`, and `clear_annotations` for agent-authored annotation sidecars
  without provider-key setup.
- Added MCP `write_annotations` provenance validation so the primary annotation write path
  accepts `agent_generated` content only.
- Added MCP `domain_map` and `agent_context` domain/value filters so agents can inspect
  handled values, missing values, related decisions, findings, and subgraph ids for
  state-like domains such as statuses and roles.
- Added missing-value matching to MCP `domain_map` value filters, including enum-style
  suffix matching such as `PAID` for `Status.PAID`.
- Added internal provider-managed enrichment helpers behind the deterministic annotation
  sidecar, while keeping the public product path agent-authored and provider-key-free.
- Added directory-level discovery pruning for known VCS, dependency, cache, temporary, and
  generated trees such as `.git`, `node_modules`, venv folders, build outputs, coverage,
  `vendor`, and `logicchart-out`, plus configurable `exclude_dirs` entries in
  `logicchart.toml`.
- Added Python analyzer modeling for `try`/`else` success paths, so post-success work is
  connected before the flow continues.
- Added Python loop-body flow modeling, so decisions and calls inside `for`, `async for`,
  `while`, and loop `else` blocks stay visible before post-loop flow continues.
- Added TypeScript/JavaScript and profile-driven tree-sitter loop-body flow modeling, so
  frontend and polyglot backend loop bodies expose internal decisions and calls.
- Added tree-sitter parse-error surfacing for TypeScript/JavaScript and profile-driven
  languages: unrecoverable malformed files are skipped, while recoverable partial parses
  keep extracted flows and add parse-warning quality signals.
- Added language capability smoke tests for every supported language id, checking declared
  function, decision, switch/match, call, and return support against real analyzer output.
- Added concise limitation notes to `metadata.language_capabilities` for partial or
  unsupported analyzer features.
- Added header-clickable collapsible Details rail sections for Project Quality, Source,
  and Review Signals.
- Added React viewer layout/detail caches and a visible loader/progress bar for
  large-codebase expand overview operations.
- Added a preserved `logicchart:local-notes` section to generated agent instructions, so
  project-specific private checks survive later `logicchart setup-agent` refreshes.

### Changed

- Updated MCP finding responses, review queues, context packs, and review-signal explanations to
  include normalized diagnostic details.
- Updated `workflow_slice` to include a deterministic presentation contract and to anchor
  natural-language queries to one primary flow, keeping related matches in supporting flows.
- Moved the MCP runtime dependency into the default install so `uv tool install` includes
  the primary MCP surface without requiring `.[mcp]`.
- Updated generated agent instructions across Codex, Claude, Gemini, and Cursor to prefer
  MCP `agent_context` for codebase questions and keep `logicchart view` as the manual UI
  path.
- Added `logicchart setup-agent codex|claude|gemini|cursor` as the public one-command setup
  path for target-specific agent instructions, MCP config where supported, artifact
  generation, doctor, and validation.
- Changed `setup-agent` to write only the requested target's instruction file, avoiding
  unrelated `AGENTS.md`/`CLAUDE.md`/`GEMINI.md` creation in projects that use a single
  agent surface.
- Changed Codex MCP setup to approve the project-scoped LogicChart server by default,
  avoiding repeated approval prompts for the central local workflow tools.
- Updated quickstart and command help to prioritize the final agent-first/manual-viewer
  surface: `logicchart setup-agent`, `logicchart update`, `logicchart view`,
  `logicchart validate`, `logicchart doctor`, and `logicchart mcp`.
- Removed the public CLI surface for `query`, `impact`, `explain`, `navigate`, and
  `snapshot`; their underlying deterministic capabilities remain available to MCP and
  internal orchestration.
- Removed `analyze`, `init`, `install`, `llm`, and `enrich` from the public CLI surface;
  `update` owns refresh/full analysis and `setup-agent` owns initialization and agent
  setup.
- Updated Expand All performance so the viewer opens all scopes and flows as a lightweight
  expanded overview with progress feedback, deferred inline detail charts, cached direct
  call indexes, and simplified overview edge routing for large real-world codebases.
- Updated the enrichment documentation to present agent-authored annotations as the
  preferred path and provider-managed enrichment as advanced/internal.
- Updated Details rail section headers so Project Quality, Source, and Review Signals can
  be collapsed by click or keyboard with synchronized expanded state.
- Updated the Review Signals panel so selected signals expand into a compact diagnostic
  inspector with a focused diagnostic subgraph, related-flow and evidence-node links,
  while keeping broad review-signal lists bounded.
- Removed the canvas minimap from the generated viewer so large-canvas updates avoid the
  extra SVG bounds pass and duplicate viewport synchronization work.

### Fixed

- Fixed Python source-snippet extraction to avoid repeatedly splitting large files through
  `ast.get_source_segment`, making full analysis of large Python services substantially
  faster.
- Fixed Python parent-flow attribution so calls, decisions, local constant-shadow metadata,
  and lambda callback bodies inside local helpers no longer leak into the enclosing flow.
- Fixed finding/source panel activation so opening a flow no longer clears the more precise
  selected finding or source-line selection.
- Fixed tablet-width Details drawer overlap so canvas toolbar controls wrap into the
  remaining canvas space instead of sitting underneath the right rail.
- Fixed selected tree rows and Details collapse controls to use flat solid colors instead
  of gradients, translucent mixes, or drop shadows.

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
