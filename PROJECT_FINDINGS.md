# LogicChart Project Findings and Improvement Plan

This document captures the current product status and the main improvement areas after
the React flowchart viewer work. It is intentionally broader than a UI review: the goal is
to make LogicChart excellent at its purpose, which is turning large codebases into
navigable, deterministic decision flowcharts for humans and coding agents.

## Current Status

LogicChart is in a strong alpha state.

- The viewer is now the most mature surface: the official chart path is the React
  progressive flowchart runtime, with persisted expansion state, node dragging, link
  focus, layout/detail caching, asynchronous chunked expansion with progress feedback,
  graph-bounds-aware PNG/JPG export, and layout quality tests. The minimap has been removed
  to keep large-canvas updates lighter. The Details rail now lets Project Quality, Source,
  and Logical Errors collapse independently during large-codebase inspection with visible,
  keyboard-accessible section headers plus rail-level expand-all/collapse-all controls,
  while tablet-width drawer layouts keep the canvas toolbar outside the right rail overlay.
  Selected tree rows and Details collapse controls use flat solid colors rather than shaded
  gradients or drop shadows. Flow nodes also expose deterministic accessibility summaries
  for source, node, decision, call, caller, and finding counts.
- The static-analysis core is usable across 11 language ids and has a stable model shape:
  `Flow`, `FlowNode`, `FlowEdge`, `Finding`, evidence tiers, scopes, files, and metadata.
- TypeScript/JavaScript expression-bodied arrow functions now produce real return flow,
  and TSX/JSX ternary arrow components produce decision branches instead of shallow
  generic action nodes. The language capability matrix marks this support explicitly for
  agent orientation.
- Python `try`/`else` blocks now model the success-only `else` path before reconnecting to
  the following flow, while skipping that path when the `try` body already terminates.
- Python, TypeScript/JavaScript, and profile-driven tree-sitter analyzers now classify
  branch outcomes through `try`/`finally`, so switch/case fall-through and asymmetric
  return findings do not treat returning cleanup paths as ordinary fall-through.
- Python loops now expose decisions and calls inside `for`, `async for`, `while`, and loop
  `else` bodies before reconnecting to post-loop flow.
- Python flow extraction now keeps nested local functions, classes, and lambdas out of the
  parent flow's call and decision attribution, reducing false edges on large service
  functions with local helpers.
- TypeScript/JavaScript and profile-driven tree-sitter analyzers now expose loop-body
  decisions and calls with conservative `Iteration`/`Done` paths and explicit
  `break`/`continue` handling.
- TypeScript/JavaScript and profile-driven tree-sitter parse errors now surface as
  skipped-file or parse-warning quality signals instead of silently clean canonical
  flowcharts.
- The deterministic baseline is correct for the product: no API key is required, and LLM
  usage remains optional enrichment, never a requirement for core correctness. The
  `logicchart enrich` path previews the bounded provider payload locally by default and
  calls a provider only with explicit `--send`.
- The CLI update workflow can now bypass the incremental cache with
  `logicchart update --full`, which keeps agent instructions concise while allowing safe
  regeneration after analyzer upgrades or LogicChart itself changes.
- The quickstart path and CLI help now prioritize no-flag first-run commands:
  `logicchart analyze`, `logicchart view`, `logicchart llm setup`, and `logicchart enrich`.
  Advanced flags remain available and documented for cache bypass, automation, JSON output,
  CI render-only workflows, and explicit provider sends.
- Source discovery now prunes known VCS, dependency, cache, temporary, and generated
  directories before traversal, including `.git`, `node_modules`, venv folders, build
  outputs, coverage, `vendor`, and `logicchart-out`. Projects can add their own whole-tree
  exclusions with `exclude_dirs` in `logicchart.toml`, while `exclude` remains for
  file/path globs.
- Local quality gates are currently healthy: Python tests, coverage, type checking,
  frontend tests, frontend type checking, viewer build, artifact validation, and npm audit
  have all passed in this workspace.
- Phase 1 diagnostic work has started: every finding now carries normalized diagnostic
  metadata, generated models include a shared detector-rule registry, MCP exposes
  `finding_rules`, and the Logical Errors panel expands selected findings into a compact
  diagnostic inspector with related-flow and evidence-node links.
- Phase 2 visual-context work has started: MCP can now return deterministic SVG snapshots
  for a flow, a selected finding, or an impact set without scraping the browser.
- Analysis-quality work has started: generated models now include deterministic quality
  metrics, `logicchart validate --quality` can print or emit them as JSON, and MCP summary
  and artifact validation can expose them to agents, and the viewer shows the same payload
  in a compact Project Quality panel. Quality now includes per-language depth signals for
  large polyglot codebases.

The main gap is no longer "make the canvas usable". The remaining gap is to keep raising
logical diagnostics and agent/MCP visual context to the same level as the viewer.

## Private Real-World Fixture: Certifexp

`examples/Certifexp` is a private local real-world fixture. It must not be tracked in Git
and must not be included in the public root LogicChart artifact.

Rules:

- Keep `examples/Certifexp/` ignored by `.gitignore`.
- Keep `examples/Certifexp/` ignored by the root `.logicchartignore`, so `logicchart update`
  for this repository cannot accidentally embed private project facts in `logicchart-out`.
- Use `tests/test_certifexp_local.py` as the local regression gate. It skips when the
  fixture is absent, so public CI remains reproducible.
- The local test and root-wide analyzer check avoid nested Git data, virtual environments,
  generated graph output, build artifacts, dependency directories, or infrastructure state
  files.

Run the local real-project gate with:

```bash
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run pytest tests/test_certifexp_local.py
```

## Finding 1: Logical Errors Need a First-Class Diagnostic Model

### What exists now

Logical errors are represented as `Finding` objects with:

- `kind`
- `severity`
- `message`
- `evidence`
- `flow_id`
- `node_id`
- `location`
- `detail`
- free-form `metadata`

This is simple and works, but it makes the UI and MCP treat a logical error mostly as a
row of text. The viewer can select the node and source line, but the model does not yet
provide a complete diagnostic object with cause, proof, confidence, and recommended review.

### Why this matters

The more important LogicChart becomes, the more users will ask: "Why is this a finding?",
"What exact cases are missing?", "Which sibling flows were compared?", "Can I trust this?",
and "What should I inspect next?" A text message is not enough for that.

### Improvement

Add a normalized diagnostic layer in the JSON model, or evolve `Finding` into a richer
schema:

- `rule_id`: stable detector identifier.
- `category`: `single_flow`, `cross_flow`, `project`, `llm_enrichment`.
- `confidence`: numeric or tiered confidence, not only evidence.
- `inputs`: extracted facts used by the detector.
- `evidence_chain`: nodes, branches, values, sibling flows, enum declarations, and source
  ranges that explain the finding.
- `expected`: the expected state, branch, outcome, or behavior when applicable.
- `actual`: what this flow currently handles.
- `missing`: missing enum members, missing branches, missing log, missing return, etc.
- `review_prompt`: concise human review question.
- `suggested_next_actions`: inspect node, inspect sibling flow, add default, confirm
  middleware, suppress as intentional, etc.
- `related_flow_ids` and `related_node_ids`: so UI and MCP can build a focused subgraph.

Current checkpoint:

- A compatibility-preserving diagnostic object is emitted under `finding.metadata`.
- A shared detector-rule registry is emitted under `model.metadata.finding_rules`.
- `explain_finding_chain`, `get_findings`, `review_queue`, and `context_pack` expose the
  diagnostic object over MCP.
- `logicchart explain <finding-id>` exposes the same deterministic explanation payload over
  the CLI, with evidence-tier guardrails and JSON output for agents.
- `logicchart-out/logic-flow.md` includes finding ids and ready-to-run `logicchart explain`
  commands so agents can move from the Markdown review queue to the evidence chain.
- `get_finding_context` exposes a bounded deterministic subgraph with the focus flow,
  evidence nodes, related flows/findings, evidence guardrail, and next-tool hints.
- Cross-flow diagnostics include bounded related-decision scope with related flow/node ids
  and structured source ranges in the evidence chain.
- Single-flow diagnostics include detector-specific evidence-chain entries for implicit
  fallbacks, constant guards, handler outcomes, empty branches, and asymmetric dispatch
  returns.
- `logicchart validate` now checks present finding-rule contracts against the current
  detector registry and emitted findings, so rule-declared metadata fields and diagnostic
  rule ids cannot drift silently.
- The viewer shows selected-finding diagnostics with confidence, missing/expected/actual
  state, rule purpose, review prompt, next actions, a compact focused diagnostic subgraph,
  related flows, and evidence nodes.

Still open:

- Promote diagnostics into a stricter schema version only when the backward-compatibility
  and consumer story are ready.
- Keep expanding detector-specific evidence only where it adds review value without
  implying heuristic findings are confirmed bugs.

### Resulting UX

The Logical Errors panel should become a diagnostic inspector:

- top summary: kind, evidence, confidence, impact surface;
- why it triggered: deterministic explanation chain;
- what is missing: explicit values or branches;
- where to inspect: flowchart nodes and source ranges;
- what to do next: review actions.

## Finding 2: Logical Error Kinds Are Good, but Need Stronger Contracts

### Current detector families

Single-flow detectors:

- `missing_branch`
- `dead_code`
- `broad_except_swallow`
- `no_op_branch`
- `asymmetric_return`
- `dead_guard`

Cross-flow/project detectors:

- `inconsistent_case_handling`
- `enum_exhaustiveness`
- `outcome_inconsistency`
- `logging_asymmetry`
- `auth_divergence` when gated

### How they are calculated today

- `enum_exhaustiveness` compares one dispatch against a declared enum or string-literal
  union and flags declared members omitted without an explicit default.
- `inconsistent_case_handling` uses a quorum across sibling flows branching on the same
  subject/value namespace.
- `outcome_inconsistency` compares the material outcome of equivalent conditions across
  sibling flows.
- `logging_asymmetry` looks for shared error-path guards that log/reject in one flow but
  proceed silently in another.
- `missing_branch` flags state-like if/elif, switch, or match decisions with no explicit
  fallback.
- `broad_except_swallow` flags exception handlers that swallow or only log errors.
- `dead_code` is emitted when all previous paths already returned or raised.
- `dead_guard` uses module-level boolean constants to flag always-true or always-false
  guards.

### Improvement

Keep the detectors, but make each one publish a stable rule contract:

- detector purpose;
- exact preconditions;
- false-positive caveats;
- metadata fields guaranteed by that detector;
- evidence tier rationale;
- examples of true positive and intentional suppression.

This can live in code as a registry and render into docs/MCP responses automatically.

Current checkpoint:

- Every `FindingKind` has a shared rule contract emitted through
  `metadata.finding_rules` and exposed via MCP `finding_rules`.
- Rule contracts include purpose, exact preconditions, caveats, evidence rationale,
  guaranteed metadata fields, review prompt, and suggested next actions.
- Rule contracts now include concise true-positive and intentional-suppression examples,
  so MCP/metadata consumers can distinguish actionable findings from expected review-only
  cases without relying on long prose.
- Diagnostics reuse the same contracts for `review_prompt` and `suggested_next_actions`,
  so CLI explanations, MCP payloads, snapshots, and the viewer stay aligned.
- Tests now pin the public rule-contract shape for every finding kind and verify filtered
  lookup behavior for known and unknown kinds.

Still open:

- Keep expanding detector-specific examples and evidence only where they add review value.

## Finding 3: Schema 1.1 Is Too Flexible for a Mature Product

### Problem

`finding.kind` is currently any string in the JSON Schema, and `metadata` is untyped. That
is flexible, but it means consumers cannot reliably build advanced UI or agent behavior
without detector-specific assumptions.

Current checkpoint:

- Schema 1.1 now validates optional generated metadata contracts for finding diagnostics,
  finding-rule registry entries, quality metrics, language capability records, and skipped
  files while still allowing custom metadata for forward compatibility.
- Artifact validation now enforces present finding-rule metadata contracts against emitted
  findings without requiring a schema bump or rejecting legacy artifacts that omit the
  registry.
- The schema still intentionally avoids enumerating `finding.kind` or bumping to 1.2 until
  the migration and consumer story is ready.

### Improvement

Introduce schema 1.2 with:

- enumerated `finding.kind`;
- structured `diagnostics`;
- stable metadata contracts per finding kind;
- optional `annotations` sidecar reference;
- optional `quality` section with analyzer and graph metrics.

Keep backward compatibility by loading 1.1 and normalizing it internally.

## Finding 4: Optional LLM Enrichment Should Be a Sidecar, Not the Core Model

### Product direction

LLM support makes sense for readability:

- better human labels for nodes;
- short descriptions for each block;
- summaries for scopes, entrypoints, and call chains;
- friendlier explanation of logical errors;
- risk summaries for code review.

It should not be used to decide the canonical control-flow structure. The deterministic
model must remain the source of truth.

### Proposed design

Add optional setup and enrichment commands:

```bash
logicchart llm providers
logicchart llm setup
logicchart enrich
logicchart enrich --send
```

`logicchart llm setup` writes local credentials and provider/model selection to the
dedicated `.env.logicchart` file without making a provider call. `logicchart enrich`
previews the bounded request payload without making a provider call unless `--send` is
passed. Successful enrichment writes:

```text
logicchart-out/logic-annotations.json
```

The sidecar should be keyed by stable ids:

- flow id;
- node id;
- edge id;
- finding id;
- model hash;
- source digest.

Current checkpoint:

- `logicchart llm providers` lists current provider/model presets, with DeepSeek v4 as
  the preferred default and free-form model/base-url overrides for provider drift.
- `logicchart llm setup` writes `.env.logicchart`, masks secrets in output, and keeps the
  setup path local-only.
- `logicchart enrich` builds a local preview payload by default, including selected
  scopes, flows, nodes, findings, diagnostic metadata, omission counts, and guardrails
  with `provider_call_made: false`.
- `logicchart enrich --send` is the explicit external-send boundary. It currently supports
  OpenAI-compatible chat APIs, calls the configured provider from `.env.logicchart`, and
  writes annotations only after schema, model-hash, id, field, and text-limit validation.
- `logicchart-out/logic-annotations.json` has a strict local schema.
- Sidecars are keyed by stable flow/node/finding/scope ids plus a deterministic model hash.
- `logicchart validate` validates a present sidecar automatically and `--annotations`
  includes sidecar status when it is absent.
- Generated viewers embed and overlay matching flow/node labels and descriptions only when
  the sidecar hash matches the current model.
- MCP summaries expose sidecar status, and flow-navigation packs include matching
  annotations for the selected flow.
- MCP `preview_enrichment` exposes the same bounded local preview payload as
  `logicchart enrich`, with `provider_call_made: false`, selected target ids,
  next-tool pointers for review/snapshots, and next CLI commands for setup or explicit
  provider send.

Still open:

- Add dedicated send adapters for non-OpenAI-compatible API formats only when there is a
  clear provider need.
- Add finding/scoped summary overlays beyond the current flow/node label/description layer.

### Safety rules

- Local deterministic analysis remains default.
- No source is sent to an LLM unless the user explicitly runs enrichment.
- The prompt uses minimal snippets and structured facts, not whole repositories.
- Sidecar output is validated against a strict schema.
- Enrichment cannot create or remove flow nodes; it can only annotate them.

## Finding 5: MCP Needs Visual Context, Not Only JSON/Text

### What exists now

The MCP server exposes useful tools: summary, flow listing, flow retrieval, query, findings,
finding explanation, state handling lookup, decision search, impact analysis, review queue,
context pack, flow-navigation packs, artifact validation, and update.

### Gap

Agents still receive mostly text/JSON. For a tool whose core value is a flowchart, MCP
should be able to return a focused visual artifact for the exact flow, finding, or impact
set being discussed.

### Improvement

Add MCP tools such as:

- `get_flow_snapshot(flow_id, format="svg")`
- `get_finding_snapshot(finding_id, format="svg")`
- `get_impact_snapshot(changed_files, scope=None, format="svg")`
- `get_context_pack(question, include_visual=True)`

These should render deterministic subgraphs from the model, not scrape the currently open
browser. Browser screenshots are useful for manual UI checks, but MCP should produce
repeatable snapshots from the artifact.

### Implementation direction

Create a shared subgraph renderer that can be used by:

- CLI;
- MCP;
- tests;
- the HTML viewer export path.

The renderer should accept a model slice and output SVG first. PNG/JPG can be generated
from SVG as an optional rasterization layer.

Current checkpoint:

- MCP exposes `get_flow_snapshot`, `get_finding_snapshot`, `get_impact_snapshot`, and
  `get_subgraph_snapshot`.
- Snapshots are generated from the deterministic model and returned as inline SVG.
- `logicchart snapshot flow|finding|impact|subgraph` exposes the same deterministic SVG
  snapshots over the CLI for agents that are not connected to MCP.
- Finding snapshots include a compact diagnostic side panel with evidence tier,
  confidence, review prompt, and evidence-chain summaries next to the highlighted flow.
- Unsupported raster formats return an explicit supported-format response instead of
  silently falling back to browser screenshots.
- Unknown flow/finding snapshot targets return structured recoverable errors with stable
  `error_code` fields instead of untyped error strings.
- Impact snapshots now carry target lists, unresolved targets, impact reasons, and
  subgraph ids, matching `impact --json`/MCP `analyze_impact` instead of forcing agents to
  infer target errors from an empty SVG.
- Flow, finding, and impact snapshot payloads now include deterministic layout metadata:
  canvas size, rendered positions, node/column dimensions, compact flags, and omitted
  edge/flow counts for large subgraph review.
- Subgraph snapshots render explicit flow/finding id sets from query, impact, finding
  context, or context-pack results, highlight selected finding nodes, report unresolved
  targets, and include deterministic section/node layout metadata.
- Snapshot payloads now include `layout_quality`, a compact/complete status plus key
  omission counts and a guardrail for agents, so MCP/CLI consumers can tell whether the
  SVG is complete without parsing geometry.
- Snapshot `layout_quality` now includes a separate rendered-geometry `clarity` report for
  box overlaps, edge paths that cross intermediate boxes, canvas overflow, minimum box
  gaps, and bounded samples, so agents can distinguish complete snapshots from visually
  crowded ones.
- MCP exposes `get_flow_navigation` for token-bounded caller/callee, decision, finding,
  and next-tool orientation before an agent pulls the complete graph.
- `logicchart navigate <flow-id>` exposes the same bounded flow-navigation contract over
  the CLI, so agents can inspect callers, callees, decisions, findings, and next steps
  without requiring MCP.
- `context_pack(include_visual=true)` can include inline SVG impact, subgraph, flow, and
  finding snapshots while the default response stays lightweight with follow-up snapshot
  tools. Inline SVGs are additionally capped by `visual_byte_budget`; omitted visuals are
  counted and remain recoverable through the returned snapshot tool calls.

Still open:

- Add optional SVG-to-PNG/JPG rasterization.
- Tune the default context-pack visual byte budget after more real agent usage.

## Finding 6: MCP Coverage and Contracts Lag Behind the Core

### Problem

The MCP server has much lower test coverage than analyzer and viewer code. That is risky
because MCP is one of the main agent-facing promises of the product.

### Improvement

Add tests for:

- every MCP tool's structured output shape;
- missing/corrupt/stale artifact behavior;
- token budget behavior;
- scope/language/finding filters;
- review queue ordering;
- context pack relevance;
- future visual snapshot outputs;
- update/validate sequence after source changes.

The MCP should be treated as a public API, not as an internal convenience wrapper.

Current checkpoint:

- MCP exposes `analysis_quality`, a bounded analyzer-quality tool with guardrails and
  next-tool hints so agents do not need to mine the full summary payload.
- MCP tests now assert the structured `analysis_quality` payload, token-budget schema, and
  language-depth fields instead of relying only on text containment.
- `analysis_quality` now surfaces parse warnings as a first-class attention item and bounds
  parse-warning samples under token budgets.
- Model-reading MCP tools return structured recoverable artifact-load errors with
  `error_code`, artifact paths, guardrails, and next-tool/CLI recovery actions for missing
  or malformed generated models.
- MCP tests cover missing and malformed artifact behavior end-to-end through the stdio
  server.
- MCP `validate_artifacts` and `update_logicchart` now return structured workflow hints for
  stale-model recovery and the update -> validate -> review sequence.
- MCP tests cover a source-change cycle where validation detects stale artifacts,
  `update_logicchart` regenerates the model, and validation passes afterward.
- MCP tests cover unknown flow/finding targets for retrieval, navigation, explanation,
  context, and snapshot tools as structured recoverable errors.
- MCP `context_pack` now embeds bounded flow-navigation packs for the relevant impact/query
  flows, including caller/callee, decision, finding, annotation, and next-tool orientation.
- MCP `preview_enrichment` lets agents inspect the optional LLM enrichment payload locally
  before any external provider send, while keeping `--send` as an explicit CLI boundary.
- MCP `context_pack` now accepts the same deterministic source/language/domain/value and
  finding kind/severity/evidence filters as `query_logic`, keeping filtered review and
  visual context aligned with the requested slice.
- CLI `query --json` and MCP `query_logic` now include bounded finding metadata,
  `subgraph_flow_ids`, `subgraph_finding_ids`, and direct subgraph snapshot follow-up
  commands/tools for focused logical-error review.
- MCP tests now directly pin the visual `context_pack` helper contract, including inline
  impact/subgraph/flow/finding snapshots and `visual_byte_budget` omissions, without
  relying only on stdio integration.
- MCP tests now directly pin flow-navigation pack shape and recoverable helper payloads
  for artifact loading, validation, update workflow, and unknown targets.
- Generated agent instruction blocks now tell Codex, Claude, Gemini, and Cursor to use
  `logicchart --help`, subcommand help, `doctor`, and safe `llm` setup commands when
  guiding users through setup or tool usage.

## Finding 7: Language Support Needs Depth Metrics, Not Only a Count

### Current status

LogicChart supports 11 language ids, but the depth varies:

- Python and TypeScript/JavaScript have dedicated analyzers and richer framework handling.
- Go, Java, C#, PHP, C, C++, Rust, and Ruby use profile-driven tree-sitter analyzers.

That architecture is good, but "supported" can mean different depths of semantic
understanding.

### Improvement

Add a language capability matrix generated from tests:

- function/method detection;
- route/entrypoint detection;
- if/else decisions;
- switch/match decisions;
- try/catch/finally;
- returns/raises/throws;
- call extraction;
- import-aware call linking;
- enum/closed-set extraction;
- framework adapters;
- known limitations.

This should appear in docs and in `logicchart doctor` or `logicchart validate --quality`.

Current checkpoint:

- Generated models include `metadata.language_capabilities` for every supported language
  id, including analyzer frontend, suffixes, and coarse feature statuses.
- Capability entries include concise `limitations` notes for partial or unsupported
  features, so agents and UI quality payloads can explain analyzer depth without
  overstating support.
- The quality payload includes per-language depth metrics for files, flows, decisions,
  calls, findings, source coverage, skipped files, and capability metadata.
- Registry tests now smoke-check every supported language id against real analyzer output
  for declared function/method, decision, switch/match, call, and return support, so the
  matrix is a pinned product contract rather than only a documentation table.
- `logicchart doctor` now surfaces a fast static language-capability summary with supported
  language ids, feature-flag count, limitation-note count, and the smoke-test contract
  pointer, without analyzing project files or running the full test suite.

Still open:

- Keep the doctor summary compact and static; do not turn it into a runtime smoke-test
  runner or analyzer benchmark.

## Finding 8: Query and Impact Are Deterministic but Still Basic

### Current status

`query` ranks by lexical overlap across identity, nodes, structure, metadata, and findings.
`impact` follows file-level direct impact, first-party import dependencies,
explicit flow/symbol/finding targets, and caller relationships.

### Improvement

Add richer query and impact modes while preserving deterministic behavior:

- query by state domain and value;
- query by detector/finding kind, severity, and evidence tier;
- query by source path, symbol, scope, language;
- impact by flow id, symbol, finding id, and dependency path;
- explain why each result was selected;
- include visual subgraph ids in the result.

Current checkpoint:

- `logicchart query` and MCP `query_logic` accept deterministic `source_path`, `symbol`,
  `domain`, `value`, `finding_kind`, `finding_severity`, and `finding_evidence` filters
  that can work without lexical query terms.
- CLI/MCP query rows include follow-up hints for flow navigation, flow snapshots, impact
  checks, and context packs, so agents can move from search result to review workflow
  without guessing tool names or arguments.
- `logicchart impact` accepts `--flow`, `--symbol`, `--finding`, and
  `--dependency-path` in addition to changed file paths, while preserving Git-diff
  defaults when no target is provided.
- MCP `analyze_impact` and `get_impact_snapshot` accept the same target types.
- JSON/MCP impact responses include target lists, unresolved targets, subgraph flow ids,
  and subgraph finding ids.
- CLI/MCP impact snapshots include the same target, unresolved-target, impact-reason, and
  subgraph fields as the non-visual impact responses.
- JSON/MCP impact responses include per-flow impact reasons, distinguishing changed-file
  matches, imported changed-file dependencies, explicit flow/symbol/finding/dependency-path
  targets, and caller propagation.
- MCP `context_pack` accepts the same explicit impact targets and preserves per-flow
  impact reasons plus subgraph ids, so agents can request a bounded context pack for an
  exact flow, symbol, finding, or source subtree without inventing a changed file.
- MCP `context_pack` also accepts the deterministic query filters from `query_logic`, so
  agents can request bounded packs for source, language, state-domain, handled-value, or
  finding evidence slices without retrieving the whole project review queue.
- MCP recovery and validation hints now point agents to `update_logicchart(full=true)` and
  `logicchart update --full` when artifacts are missing, stale, or cache bypass is safer.
- Generated `files[]` records now include first-party `dependencies` for Python,
  TypeScript/JavaScript, Go, Java, and C# imports; `impact` uses those edges to include
  flows from files that import a changed file even when the changed file has no modeled
  flow of its own.

Still open:

- Extend dependency-edge-aware impact to more profile-driven languages only when their
  import metadata is precise enough to avoid noisy dependency edges.

Optional LLM query reformulation could help map natural language to deterministic query
fields, but final retrieval should still be model-backed.

## Finding 9: Viewer Complexity Should Be Shared with CLI/MCP Where Possible

### Problem

The React viewer now has sophisticated graph layout, expansion, selection, export, progress
feedback, and quality-report logic. But much of that intelligence lives in frontend code
only.

### Improvement

Separate three layers:

1. Model slicing: choose the relevant flows, nodes, edges, diagnostics.
2. Layout computation: produce deterministic coordinates and routes.
3. Presentation: React interaction, DOM, panels, keyboard/mouse behavior.

MCP and CLI snapshots need layers 1 and 2 without React interactivity.

## Finding 10: Analyzer Quality Metrics Are Missing

### Problem

`validate` confirms artifact shape and sync, but not analysis quality.

### Improvement

Add quality metrics:

- skipped files count by reason;
- parsed files by language;
- flows per file;
- generic action labels ratio;
- unresolved calls;
- ambiguous calls;
- low-confidence links;
- findings by evidence/kind/severity;
- source snippet coverage;
- graph density and huge-node warnings.

Current checkpoint:

- Generated models include `metadata.quality`.
- `logicchart validate --quality` prints human-readable quality metrics, and
  `--quality --json` emits them under `quality`.
- MCP `logicchart_summary` includes quality metrics.
- MCP `analysis_quality` provides a dedicated, token-bounded quality report with guardrails
  and next-tool hints.
- MCP `validate_artifacts(include_quality=true)` returns the same quality payload.
- The generated viewer Details rail includes a Project Quality panel with coverage,
  call-resolution, findings, label, graph-density, and language metrics.
- Viewer flow and source-path deep links open the Details rail with the matching source
  context, so copied URLs and agent-provided links land on an inspectable state.
- Generated models include `metadata.language_capabilities`, and MCP summaries expose that
  registry-derived matrix for agent orientation.
- Quality metrics include per-language depth signals for files, flows, decisions, calls,
  findings, source coverage, skipped files, and capability metadata.
- Generated models include `metadata.skipped_files`, and quality metrics include skipped
  counts, reason buckets, and samples.
- Tree-sitter parse errors in TypeScript/JavaScript and profile-driven languages are
  reported as skipped files when no flow can be extracted, or as parse-warning file
  quality signals when useful flow context exists.
- `logicchart validate` and MCP `validate_artifacts` can apply optional CI thresholds for
  skipped files, parse warnings, call-resolution rate, and generic-label ratio.

Expose these through:

- `logicchart validate --quality`;
- Done: MCP summary;
- Done: viewer project overview;
- Done: language capability matrix in metadata and MCP summary;
- Done: skipped-file reasons in metadata and quality metrics;
- Done: CI optional gate.

## Finding 11: Logical Error UI Should Explain, Not Just List

### Problem

The Logical Errors panel is bounded and safe, but it is still list-first. For large
codebases, a list is not enough.

### Improvement

Add a finding detail state:

- selecting a finding opens the flow and target node;
- the right panel shows the rule explanation;
- a mini diagnostic table shows handled/missing/declared values;
- related flows and evidence nodes are linked;
- a small focused chart shows only the diagnostic subgraph;
- LLM enrichment, when available, adds a short plain-language explanation.

## Finding 12: Documentation and Changelog Need Release Consolidation

### Problem

The current `Unreleased` section needs to stay consolidated around the substantial work
after `v0.8.0`: official React viewer path, static runtime removal, layout stabilization,
large-canvas performance work, graph-bounds-aware export, expand/reset controls, minimap
removal, and codebase rail improvements.

### Improvement

Before the next release:

- update `CHANGELOG.md`;
- update README release notes and latest-version links;
- document the official React-only runtime;
- document local Certifexp validation as private/local only;
- verify installed CLI version and doctor output;
- release only when CI is green and no immediate follow-up is pending.

## Recommended Roadmap

### Phase 1: Diagnostic Model

- Done: add a detector registry.
- Done: normalize finding metadata under a compatibility-preserving diagnostic object.
- Done: add baseline diagnostic evidence chains and bounded related-decision scope for
  cross-flow findings.
- Done: add detector-specific single-flow evidence-chain entries for flagship logical
  findings.
- Done: add tests for each detector's structured output.
- Done: update viewer Logical Errors panel to show diagnostic details and related
  flow/evidence-node links.
- Done: add a compact focused diagnostic subgraph to selected finding rows in the viewer.
- Done: add a CLI `explain` command for deterministic finding explanations and JSON output.
- Next: consider a compatible schema 1.2 only when the consumer migration story is ready.

### Phase 2: MCP Visual Context

- Done: add model-slice helpers for flow/finding/impact snapshots.
- Done: add deterministic SVG snapshot rendering.
- Done: expose snapshot tools over MCP.
- Done: expose deterministic SVG snapshots over CLI.
- Done: add tool contract tests for snapshot discovery and output shape.
- Done: add focused diagnostic panels to finding SVG snapshots.
- Done: add a flow-navigation MCP pack for caller/callee, decision, finding, and next-tool
  orientation.
- Done: share the flow-navigation pack with CLI via `logicchart navigate`.
- Done: add a finding-context MCP pack for focus flow, related nodes/flows/findings,
  evidence guardrails, and next-tool orientation.
- Done: make MCP flow/finding/impact SVG snapshots honor `token_budget` by omitting excess
  nodes or impact flows while reporting omission counts.
- Done: add optional inline SVG visual context to `context_pack` with lightweight default
  follow-up tools.
- Done: add bounded flow-navigation packs directly to `context_pack` so agents can orient
  on relevant flows before pulling full graphs.
- Done: add deterministic layout metadata to flow/finding/impact snapshots for compacted
  large-subgraph review.
- Done: add rendered-geometry clarity signals to snapshot `layout_quality`, including
  overlap, overflow, gap, and edge-obstacle counts.
- Done: cap inline `context_pack` SVG payload size with `visual_byte_budget` while keeping
  omitted visuals available through follow-up snapshot tools.
- Done: add explicit flow/finding subgraph snapshots across MCP and CLI so agents can
  render the `subgraph_flow_ids`/`subgraph_finding_ids` they already receive.
- Done: include the explicit subgraph snapshot inline in `context_pack(include_visual=true)`
  when it fits the deterministic visual byte budget.
- Next: add optional raster outputs if a local renderer path is worth the dependency.

### Phase 3: LLM Enrichment

- Done: add local provider/model setup with `logicchart llm providers`, `logicchart llm
  setup`, and `logicchart llm show`.
- Done: use DeepSeek v4 (`deepseek-v4-pro`) as the preferred default while allowing
  free-form model and base URL overrides for changing provider catalogs.
- Done: save optional credentials in a dedicated, git-ignored `.env.logicchart` file with
  masked command output and no provider calls during setup.
- Done: add `logicchart enrich` as an explicit opt-in command that previews the bounded
  provider payload before any request, supports explicit `--dry-run`/`--preview` aliases,
  and calls the configured provider only with `--send`.
- Done: validate provider enrichment output against known ids, supported annotation
  fields, text limits, and the current model hash before writing the sidecar.
- Done: expose the enrichment preview through MCP as a local-only agent workflow helper,
  without adding an MCP provider-send path.
- Done: write/load `logic-annotations.json`.
- Done: validate annotations against a schema and model hash.
- Done: add viewer overlays for better flow/node labels and descriptions.
- Done: expose annotation status and matching flow annotations over MCP.
- Done: expose fresh finding annotations as optional enrichment in CLI explain/navigate,
  MCP finding/review/context tools, and the Logical Errors panel.
- Done: expose fresh scope annotations as progressive flowchart group labels and matching
  flow-navigation annotations, with sidecar bucket counts for agent orientation.

### Phase 4: Real-World Quality Gates

- Keep `examples/shop` as tracked golden fixture.
- Keep `examples/demo` as public polyglot viewer fixture.
- Use private `examples/Certifexp` as local smoke test only.
- Done: add baseline analyzer quality metrics.
- Done: add viewer quality overview.
- Done: add language capability matrix.
- Done: persist skipped-file reasons.
- Done: model expression-bodied TypeScript/JavaScript arrow returns and ternary component
  decisions.
- Done: add optional quality thresholds, including parse-warning thresholds for
  recoverable tree-sitter parse errors.
- Done: model Python `try`/`else` success paths without treating terminating `try` bodies as
  fall-through.
- Done: classify `try`/`finally` branch outcomes in Python, TypeScript/JavaScript, and
  profile-driven tree-sitter analyzers, including C-style switch case fall-through.
- Done: model Python loop bodies and loop `else` blocks so useful internal decisions/calls
  are no longer hidden behind a single loop action node.
- Done: keep Python local helper scopes from polluting parent-flow calls, decisions, and
  constant-shadow metadata.
- Done: keep Python local lambda callback bodies from making parent branch classification
  look functional.
- Done: model TypeScript/JavaScript and profile-driven tree-sitter loop bodies with
  explicit `break`/`continue` control nodes.
- Done: surface TypeScript/JavaScript and profile-driven tree-sitter parse errors as
  skipped-file or parse-warning quality signals.
- Done: add `logicchart update --full` so agents can force a fresh regeneration without
  switching to the longer `analyze --full` workflow.

### Phase 5: Release Consolidation

- Done: update changelog, README/docs guidance, generated agent instructions, and this
  findings file to describe the current stabilized surfaces.
- Done: re-run local Python, viewer, LogicChart artifact, demo render, and private
  Certifexp gates on the stabilization branch.
- Done: verify the installed user-facing CLI resolves to this checkout and reports a
  healthy `logicchart doctor --json`.
- Pending external check: verify GitHub CI after the branch push.
- Pending user approval: merge to `main`, version bump, tag, and release.
