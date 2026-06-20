# Agent-Authored Enrichment

LogicChart is deterministic, local-first, and does not require provider keys. The main
enrichment workflow is handled by the coding agent that is already working with the user:

1. The user asks the coding agent for clearer labels, summaries, or explanations.
2. The agent calls MCP `agent_context` for a deterministic `workflow_slice`.
3. The agent writes generated text as validated annotations.
4. LogicChart keeps those annotations separate from deterministic facts.

Generated annotation text must be treated as `agent_generated`. It can improve readability,
but it must not replace source-backed flow data, diagnostic evidence, or review-signal tiers.

## MCP Annotation Workflow

`preview_annotation_targets` is the preferred local-only MCP helper. It selects bounded
candidate flows and review signals, returns the context an agent may want to annotate, and
always reports `provider_call_made: false`.

Use it to inspect annotation targets and payload size. Then use:

- `write_annotations` to merge validated `agent_generated` labels, summaries,
  explanations, and remediation notes into `logicchart-out/logic-annotations.json`.
- `validate_annotations` to check the sidecar against the current model hash and ids.
- `annotation_status` to inspect sidecar status, counts, and optional contents.
- `clear_annotations` with `confirm=true` to remove optional generated annotation text.

`preview_enrichment` remains as a compatibility/local-preview helper, but should not be
treated as a provider-send workflow. The public CLI intentionally does not expose `llm` or
`enrich` commands.

## Provider-Managed Code Path

Provider-managed enrichment support remains in internal modules for compatibility and
experimentation, but it is not the primary product path and is not part of the public CLI.
No setup flow should ask users for API keys during normal LogicChart use.

If provider-managed code is used by maintainers or tests, the same trust rules apply:

- do not commit `.env.logicchart`;
- do not send source-derived payloads without explicit user approval;
- validate returned annotations against the current model hash and known ids;
- reject unknown targets, unsupported fields, stale hashes, and overlong text;
- display provider or agent text separately from deterministic diagnostics.

## Viewer and MCP Display

When a valid annotation sidecar is present, LogicChart may display labels, summaries,
review-signal explanations, remediation notes, and scope descriptions in MCP responses,
snapshots, and the viewer. These annotations remain optional. The analyzer, validation,
review signals, evidence tiers, and flow structure must remain correct without them.
