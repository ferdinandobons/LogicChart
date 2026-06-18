# LogicChart Project Findings and Improvement Plan

This document captures the current product status and the main improvement areas after
the React flowchart viewer work. It is intentionally broader than a UI review: the goal is
to make LogicChart excellent at its purpose, which is turning large codebases into
navigable, deterministic decision flowcharts for humans and coding agents.

## Current Status

LogicChart is in a strong alpha state.

- The viewer is now the most mature surface: the official chart path is the React
  progressive flowchart runtime, with persisted expansion state, node dragging, link
  focus, aggregate minimap navigation, graph-bounds-aware PNG/JPG export, and layout
  quality tests. Flow nodes also expose deterministic accessibility summaries for
  source, node, decision, call, caller, and finding counts.
- The static-analysis core is usable across 11 language ids and has a stable model shape:
  `Flow`, `FlowNode`, `FlowEdge`, `Finding`, evidence tiers, scopes, files, and metadata.
- The deterministic baseline is correct for the product: no API key is required, and LLM
  usage should remain optional enrichment, never a requirement for core correctness.
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
  in a compact Project Quality panel.

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
- The local test analyzes only source-bearing subtrees, not the nested Git repo, virtual
  environments, generated graph output, build artifacts, dependency directories, or
  infrastructure state files.

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
- `get_finding_context` exposes a bounded deterministic subgraph with the focus flow,
  evidence nodes, related flows/findings, evidence guardrail, and next-tool hints.
- The viewer shows selected-finding diagnostics with confidence, missing/expected/actual
  state, rule purpose, review prompt, next actions, related flows, and evidence nodes.

Still open:

- Promote diagnostics into a stricter schema version only when the backward-compatibility
  and consumer story are ready.
- Consider a small focused chart for the diagnostic subgraph if related-flow links are not
  enough for large findings.
- Add richer detector-specific evidence chains where the current metadata is still shallow.

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

## Finding 3: Schema 1.1 Is Too Flexible for a Mature Product

### Problem

`finding.kind` is currently any string in the JSON Schema, and `metadata` is untyped. That
is flexible, but it means consumers cannot reliably build advanced UI or agent behavior
without detector-specific assumptions.

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

Add an optional command:

```bash
logicchart enrich --provider openai --model <model> --scope frontend
```

It writes:

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

- `logicchart-out/logic-annotations.json` has a strict local schema.
- Sidecars are keyed by stable flow/node/finding/scope ids plus a deterministic model hash.
- `logicchart validate` validates a present sidecar automatically and `--annotations`
  includes sidecar status when it is absent.
- Generated viewers embed and overlay matching flow/node labels and descriptions only when
  the sidecar hash matches the current model.
- MCP summaries expose sidecar status, and flow-navigation packs include matching
  annotations for the selected flow.

Still open:

- Add `logicchart enrich` only after the provider/model and external-code-send boundaries
  are explicitly approved.
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

- MCP exposes `get_flow_snapshot`, `get_finding_snapshot`, and `get_impact_snapshot`.
- Snapshots are generated from the deterministic model and returned as inline SVG.
- Unsupported raster formats return an explicit supported-format response instead of
  silently falling back to browser screenshots.
- MCP exposes `get_flow_navigation` for token-bounded caller/callee, decision, finding,
  and next-tool orientation before an agent pulls the complete graph.
- `context_pack(include_visual=true)` can include inline SVG impact, flow, and finding
  snapshots while the default response stays lightweight with follow-up snapshot tools.

Still open:

- Share more layout intelligence with the React viewer, especially for larger subgraphs.
- Add optional SVG-to-PNG/JPG rasterization.
- Keep monitoring whether context-pack visual payloads need stricter size caps after more
  real agent usage.

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

## Finding 8: Query and Impact Are Deterministic but Still Basic

### Current status

`query` ranks by lexical overlap across identity, nodes, structure, metadata, and findings.
`impact` follows file-level direct impact, explicit flow/symbol/finding targets, and caller
relationships.

### Improvement

Add richer query and impact modes while preserving deterministic behavior:

- query by state domain and value;
- query by detector/finding kind;
- query by source path, symbol, scope, language;
- impact by flow id, symbol, finding id, and dependency path;
- explain why each result was selected;
- include visual subgraph ids in the result.

Current checkpoint:

- `logicchart query` and MCP `query_logic` accept deterministic `source_path`, `symbol`,
  `domain`, and `value` filters that can work without lexical query terms.
- `logicchart impact` accepts `--flow`, `--symbol`, and `--finding` in addition to changed
  file paths, while preserving Git-diff defaults when no target is provided.
- MCP `analyze_impact` and `get_impact_snapshot` accept the same target types.
- JSON/MCP impact responses include target lists, unresolved targets, subgraph flow ids,
  and subgraph finding ids.

Still open:

- Add dependency-path impact once call/dependency edges carry enough precision.

Optional LLM query reformulation could help map natural language to deterministic query
fields, but final retrieval should still be model-backed.

## Finding 9: Viewer Complexity Should Be Shared with CLI/MCP Where Possible

### Problem

The React viewer now has sophisticated graph layout, expansion, selection, minimap, export,
and quality-report logic. But much of that intelligence lives in frontend code only.

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
- MCP `validate_artifacts(include_quality=true)` returns the same quality payload.
- The generated viewer Details rail includes a Project Quality panel with coverage,
  call-resolution, findings, label, graph-density, and language metrics.
- Generated models include `metadata.language_capabilities`, and MCP summaries expose that
  registry-derived matrix for agent orientation.
- Generated models include `metadata.skipped_files`, and quality metrics include skipped
  counts, reason buckets, and samples.
- `logicchart validate` and MCP `validate_artifacts` can apply optional CI thresholds for
  skipped files, call-resolution rate, and generic-label ratio.

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

The current `Unreleased` section does not yet summarize the substantial work after
`v0.8.0`: official React viewer path, static runtime removal, layout stabilization,
minimap behavior, graph-bounds-aware export, expand/reset controls, and codebase rail
improvements.

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
- Done: add baseline diagnostic evidence chains.
- Done: add tests for each detector's structured output.
- Done: update viewer Logical Errors panel to show diagnostic details and related
  flow/evidence-node links.
- Next: deepen detector-specific evidence chains and consider a compatible schema 1.2.

### Phase 2: MCP Visual Context

- Done: add model-slice helpers for flow/finding/impact snapshots.
- Done: add deterministic SVG snapshot rendering.
- Done: expose snapshot tools over MCP.
- Done: add tool contract tests for snapshot discovery and output shape.
- Done: add a flow-navigation MCP pack for caller/callee, decision, finding, and next-tool
  orientation.
- Done: add a finding-context MCP pack for focus flow, related nodes/flows/findings,
  evidence guardrails, and next-tool orientation.
- Done: make MCP flow/finding/impact SVG snapshots honor `token_budget` by omitting excess
  nodes or impact flows while reporting omission counts.
- Done: add optional inline SVG visual context to `context_pack` with lightweight default
  follow-up tools.
- Next: add optional raster outputs if a local renderer path is worth the dependency.

### Phase 3: LLM Enrichment

- Next: add `logicchart enrich` after provider/model approval.
- Done: write/load `logic-annotations.json`.
- Done: validate annotations against a schema and model hash.
- Done: add viewer overlays for better flow/node labels and descriptions.
- Done: expose annotation status and matching flow annotations over MCP.

### Phase 4: Real-World Quality Gates

- Keep `examples/shop` as tracked golden fixture.
- Keep `examples/demo` as public polyglot viewer fixture.
- Use private `examples/Certifexp` as local smoke test only.
- Done: add baseline analyzer quality metrics.
- Done: add viewer quality overview.
- Done: add language capability matrix.
- Done: persist skipped-file reasons.
- Done: add optional quality thresholds.

### Phase 5: Release Consolidation

- Update changelog.
- Re-run local CI gates.
- Verify GitHub CI.
- Refresh installed CLI.
- Release only after the cumulative state is stable.
