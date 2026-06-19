# LogicChart Product Vision

## North Star

LogicChart is an agent-first, local understanding layer for code logic.

Developers should be able to set it up once, then ask their coding agent simple questions
such as:

- How does this feature work?
- What logic is involved in this change?
- What could break if I edit this file?
- Where is this state handled?
- Why did the AI-generated code create this branch?
- Which decisions, callers, callees, and missing cases should I review?

LogicChart should give the agent deterministic, visual, and structured context so the
answer is grounded in the actual codebase instead of plausible narration.

## Product Positioning

LogicChart is not primarily a terminal tool or a graph viewer.

It is a support system for coding agents. Its job is to make code logic inspectable,
queryable, and explainable for both humans and AI, especially in projects where modern
development is mediated by agents such as Codex, Claude, Cursor, or similar tools.

The CLI and viewer remain important, but they are supporting surfaces:

1. MCP and agent workflows are the primary product surface.
2. CLI exists for setup, repair, CI, explicit refresh, and debugging.
3. The viewer exists for optional human inspection and deep visual exploration.
4. Generated artifacts are the shared source of truth between humans, agents, CI, and UI.

## Core Promise

After setup, users should not need to remember LogicChart commands.

They should ask their coding agent ordinary questions, and the agent should use
LogicChart automatically to:

- retrieve the relevant flows;
- inspect decisions, calls, callers, callees, and outcomes;
- identify logical findings and their evidence tier;
- understand impact from changed files, symbols, flows, findings, and dependencies;
- request deterministic visual snapshots;
- distinguish verified facts from inferred review candidates;
- generate useful explanations without losing source-grounded traceability.

## Design Principles

### Agent-first

Every major capability should be usable through MCP and structured payloads. Human-facing
CLI commands should mirror these capabilities, but should not be the main expected path.

### Local-first and deterministic

The core model must work offline and must not require an LLM. Correctness comes from the
local analyzer, schema validation, source locations, evidence tiers, and deterministic
snapshots.

### Visual context for agents

Because the product is about flowcharts, agents need visual artifacts too. SVG snapshots
for flows, findings, impact sets, and explicit subgraphs are first-class context, not a
secondary export feature.

### One orchestration path

Agents should not have to manually stitch together many low-level tools for common tasks.
LogicChart should provide a unified context workflow that accepts a user question, changed
files, selected code, target flow, finding, or symbol, then returns a bounded understanding
pack.

### Enrichment belongs to the coding agent

The coding agent already has a model. LogicChart should not require provider keys for the
main enrichment workflow.

Instead, LogicChart should:

- expose deterministic context to the agent;
- tell the agent which ids can be annotated;
- accept agent-authored annotations through a validated sidecar;
- keep annotations separate from deterministic facts;
- reject annotations that reference unknown flow, node, finding, or scope ids.

Provider-managed enrichment can remain an advanced optional path, but it should not be the
primary product story.

### Trust boundaries must be explicit

LogicChart should always make clear whether a statement is:

- `VERIFIED`: syntax-backed or source-backed;
- `INFERRED`: deterministic heuristic;
- `POTENTIAL_GAP`: review candidate;
- `agent_generated`: optional explanatory annotation from the coding agent.

Agents must not present inferred findings or generated enrichment as confirmed bugs.

## Target Setup Experience

The ideal setup is a single guided command:

```bash
logicchart setup-agent codex
```

Equivalent targets should exist for Claude, Cursor, and other supported agent surfaces.

The setup flow should:

- create or update `logicchart.toml` only when needed;
- install or refresh agent instructions;
- register the MCP server when requested;
- generate the initial `logicchart-out` model;
- run `logicchart doctor`;
- validate artifacts;
- explain what users can now ask their coding agent;
- avoid asking for LLM provider credentials unless the user explicitly chooses an advanced
  provider-managed enrichment flow.

## Target Agent Experience

The primary MCP capability should become a unified context tool, conceptually:

```text
agent_context(
  question,
  changed_files,
  selected_code,
  current_file,
  flow_id,
  symbol,
  finding_id,
  dependency_path,
  token_budget,
  include_visual
)
```

The response should include:

- matched flows and why they were selected;
- impact reasons;
- direct and transitive flow ids;
- caller and callee summaries;
- decision nodes and handled values;
- unresolved calls;
- related findings with evidence tiers;
- source snippets or source ranges;
- subgraph flow and finding ids;
- visual snapshot payloads or follow-up snapshot tool calls;
- omitted counts and budget guardrails;
- recommended next tools;
- recommended human review points.

This should be the default path for questions such as:

- "Explain how checkout works."
- "Review the logical impact of my change."
- "What logic touches this status?"
- "Show me the flow around this bug."
- "What should I test after this edit?"

## Agent-authored Enrichment

The future enrichment workflow should be:

1. The user asks the coding agent for a clearer explanation or better flow labels.
2. The agent calls LogicChart for deterministic context.
3. The agent generates summaries, explanations, and label suggestions using its own model.
4. The agent writes the annotations back through a LogicChart MCP write tool.
5. LogicChart validates target ids, schema, model hash, text limits, and annotation source.
6. The viewer, snapshots, `navigate`, `explain`, and context packs display those
   annotations separately from deterministic diagnostics.

Potential tools:

- `preview_annotation_targets`
- `write_annotations`
- `validate_annotations`
- `clear_annotations`
- `annotation_status`

Potential CLI mirrors:

- `logicchart annotations validate`
- `logicchart annotations import`
- `logicchart annotations clear`

Annotations should support:

- flow names and summaries;
- node labels and summaries;
- scope/group summaries;
- finding explanations;
- remediation notes;
- domain concept descriptions;
- "what to inspect next" notes.

## Strategic Product Pillars

### 1. Understand how code works

LogicChart should explain entrypoints, decisions, branches, calls, outcomes, and source
locations in a way that both humans and agents can follow.

### 2. Understand what changes affect

LogicChart should map edits to impacted flows, callers, findings, decisions, and test
suggestions.

### 3. Understand domain logic

LogicChart should identify important domains such as statuses, roles, permissions,
lifecycle states, payment states, and feature flags, then show where they are handled or
missing.

### 4. Understand trust and uncertainty

LogicChart should expose analyzer capability, skipped files, parse warnings, unresolved
calls, evidence tier, confidence, and snapshot omissions so agents do not overstate what
they know.

### 5. Make visual context available without opening the UI

The viewer remains useful, but agents should be able to request compact deterministic SVG
snapshots directly through MCP or CLI.

## Product Roadmap Direction

### Phase 1: Agent-first setup

- Add `logicchart setup-agent`.
- Make MCP setup and instruction refresh the default recommended path.
- Make `doctor` and artifact validation part of setup.
- Document common user questions instead of command-first workflows.

### Phase 2: Unified agent context

- Add a primary MCP `agent_context` tool.
- Add a CLI mirror for debugging and CI.
- Internally orchestrate query, impact, navigate, explain, and snapshot selection.
- Return one bounded context pack with next actions.

### Phase 3: Agent-authored annotations

- Add MCP write tools for validated annotations.
- Treat provider-managed LLM enrichment as advanced and optional.
- Keep annotation sidecars separate from deterministic model artifacts.

### Phase 4: Domain and state maps

- Extract state machines and domain concepts.
- Show handled values, missing values, transitions, invalid states, and ownership.
- Expose the same maps through MCP, CLI, and viewer.

### Phase 5: Change review intelligence

- Add change-aware review packs from diff/current files.
- Suggest logical tests from decisions and missing branches.
- Highlight generated or modified logic that lacks callers, outcomes, or explicit handling.

## Feature Acceptance Test

A feature belongs in LogicChart if it helps an agent or human answer at least one of these
questions better:

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
