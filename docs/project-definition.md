# LogicChart - Project Definition

> Single source of intent for building LogicChart. Describes the complete target
> product, then a separate **Build Order & Dependencies** section that fixes what
> must be built first and why. This document is the input for an automated build
> (`/goal`); it defines *what* and *in what order*, not line-level implementation.

---

**Status & repository.** The repository is **private for now**. Whether LogicChart ships
as open source or as a paid product is **deliberately deferred** - that decision will be
made later, based on how the built product turns out. The design keeps both doors open: it
stays local-first and self-contained (no mandatory hosted backend), while nothing in the
architecture precludes a future hosted or commercial layer. Read "reference-quality OSS"
anywhere below as the intended *quality bar*, not a committed licensing decision.

## 1. What it is

LogicChart is a local **static-analysis tool** that turns a folder of
source code into **one model and three artifacts derived from it**:

- **`logic-flow.json`** - the canonical data model (the single source of truth).
- **`logic-flow.md`** - committable Mermaid **decision flowcharts**, rendered directly
  in GitHub and pull requests.
- **`logic-flow.html`** - an interactive local viewer: navigate flows, click a node,
  jump to the exact source line.

The navigable **decision flowchart is the centerpiece**. Logical holes and
inconsistencies are **highlighted inside the flowchart**, not emitted as a flat list.
A flowchart alone is a picture that goes stale; hole-detection alone is a linter with no
context. LogicChart is both: a navigable flowchart, always kept in sync with the code,
that highlights gaps and inconsistencies on itself. Finding the holes is also the reason
the flowchart is worth keeping continuously up to date.

It runs entirely locally, with no API key. (Optional LLM enrichment of labels may be
added later but must never be required to build the verified model.)

## 2. Who it is for

**Dual audience, served by the same JSON model - no parallel tracks. Every feature goes
through the canonical IR.**

- **Humans** open the HTML viewer or read the `.md` in a PR: navigate a flow, filter by
  severity, see nodes with holes highlighted, jump to source.
- **Models / coding agents** query the same model over MCP: "show me the flow for X",
  "list the findings", "where is account state handled?" - same data, machine-readable.

## 3. Why it exists (honest differentiation)

Existing tools each cover part of the space:

| Tool class | Examples | Finds | Limit |
|---|---|---|---|
| Built-in-rule linters | SonarQube, PMD, ESLint, SpotBugs | Single-spot issues (switch without `default`, empty `catch`, dead code) | Look at one place at a time; never compare places to each other |
| Query / SAST engines | CodeQL, Semgrep, Joern | "Operation reached without a preceding check" (absence) | You hand-author a rule per invariant; expert effort |
| Type checkers | TypeScript, mypy, pyright | Enum exhaustiveness | Only with types set up, only inside the type system |
| Comprehension / viz | Sourcegraph, IDE call hierarchy, code2flow | Structure / diagrams | Do not look for logical holes; AI-drawn flowcharts are unverified |

The defensible moat is the **combination no live tool offers together**:

1. Finds inconsistencies **across different places** (not only within one place).
2. With **zero rules to author** - it finds them automatically.
3. **Without requiring a type system** - works on loosely-typed Python/JS.
4. As a **committed, agent-queryable artifact** with an explicit evidence ledger
   (`VERIFIED` / `INFERRED` / `POTENTIAL_GAP`), every claim traceable to a line.

Honest framing: absence detection per se is **not** novel (CodeQL/Joern do it with
hand-authored queries; rustc/pyright do built-in exhaustiveness with types;
SonarQube/PMD/SpotBugs ship single-flow detectors). The novelty is the combination above
plus the specific question **"what did this flow forget that its sibling flows
remembered?"** Position against **live** tools (Joern, SonarQube, CodeScene), not against
discontinued ones.

One-line positioning: *"SonarQube tells you what's broken in one place; CodeQL tells you
if you write the rule; LogicChart tells you - automatically, without types - what one part
of the code forgot relative to similar parts, and writes it into the repo so an agent can
use it too."*

## 4. Core concepts

- **Decision-flow IR** (not a call-graph). Node kinds: `entry`, `decision`, `action`,
  `call`, `terminal`, `error`. Functional decisions (auth, state, validation, outcome) are
  shown; implementation noise is compressed.
- **Evidence levels**: `VERIFIED` (from syntax/framework conventions), `INFERRED`
  (deterministic heuristic), `POTENTIAL_GAP` (review candidate, never auto-treated as a
  bug). Every node and finding links back to a source file and line.
- **Confidence-tiered findings**: every finding carries a confidence score; the emission
  threshold is configurable; the default report shows only high-confidence findings.
- **Always in sync**: incremental, per-file caching keyed by content hash; explicit
  `update` after code changes.

## 5. The complete product

This section describes the full target. The order in which these are built is fixed
separately in **§9 - Build Order & Dependencies**.

### 5.1 Detectors

Each detector emits findings with an evidence level and a confidence score. Annotations:
`FP` = false-positive risk; `needs:` = the IR capability it depends on.

**Single-flow** (reason about one flow):

- **Missing `else`/`default` on a state-like decision** - extend the existing
  `missing_branch` from `switch`/`match` to `if`/`elif` chains. `FP: low`. *The flagship
  safe signal: the one finding that survives the real demo as a true positive.*
- **Dead / unreachable code after `return`/`raise`** (orphan node). `FP: low`.
- **Dead-join**: code after all branches `return`/`raise`. `FP: low`.
- **Broad-except / catch-all that swallows the error** (empty / log-only handler, no
  rethrow or error return). `FP: low`. `needs: branch_outcome`.
- **No-op branch** (body has no return/raise/assign/boundary-call). `FP: medium`.
  `needs: branch_outcome`.
- **Asymmetric early-return vs fallthrough** across sibling branches. `FP: medium`.
  `needs: branch_outcome`.
- **Always-true / always-false guard** from a literal or module constant. `FP: low`.
- **Resource opened but missing cleanup on the error path**. `FP: medium`.
  `needs: context-manager marker + branch_outcome`.

**Cross-flow** (compare many flows - the differentiated capability):

- **Quorum-aware divergent value-set coverage** - flag a value handled by a **majority of
  sibling flows** on the same subject but **missing here**; keyed on
  `(language, normalized_subject, value_namespace)`; **skip any flow with a pass-through /
  implicit default**. `FP: medium`. `needs: branch_outcome + subject/namespace keying +
  quorum logic`. *The de-noised rebuild of today's noisy detector; the marquee cross-flow
  signal.*
- **Enum/union member missing vs the declared closed set** (harvest `Enum` / `Literal` /
  TS unions). `FP: medium`. `needs: enum table`.
- **Outcome inconsistency** for the same condition (403 here, 404 there; `raise` vs
  `return null`). `FP: medium`.
- **Default/fallback semantic inconsistency** - both siblings have a default but do
  materially different things (one returns empty-200, one 500). `FP: medium`.
  `needs: branch_outcome + effect tags`.
- **Logging / observability asymmetry** on error paths (one branch logs+alerts, a sibling
  silently returns). `FP: low`. `needs: branch_outcome + effect tags`.
- **Feature-flag / config-gated branch asymmetry** (a path guarded by a flag in flow A,
  unguarded in sibling B). `FP: medium`.
- **Return-shape / contract divergence** - two flows returning the same logical object
  with structurally different shapes. `FP: medium`. `needs: def/use`.

**Gated (highest value, highest FP - opt-in, require the call-resolver fix):**

- **Authorization present on one entry path, missing on a sibling** for the same resource
  (opt-in, with a middleware/DI caveat). `needs: call-resolver fix + widened auth lexicon`.
- **Validation present on one route, absent on a sibling** converging on the same write
  sink. `needs: call-resolver fix`.
- **Same downstream effect reached under inconsistent preconditions** (guard-set
  divergence at a shared resolved sink). `needs: call-resolver fix`.

**Later (need a data-flow primitive):** type/schema contradiction across flows;
contradictory guards (needs operator + negation polarity); state-machine transition
inconsistency; null/None/undefined handling missing; subsumed branch via interval
reasoning; copy-paste decision drift.

### 5.2 Surfaces

- **CLI**: `init`, `analyze`, `update`, `impact`, `query`, `view`, `install`, `mcp`,
  `hook` (install/uninstall/status the git auto-sync hook), `watch` (debounced rebuild on
  save), `install --hook` (opt-in Claude Code PreToolUse nudge), a `--deep`/audit mode (lowers
  the deterministic confidence threshold and enables higher-FP detectors - never an LLM pass),
  plus confidence-threshold and evidence-filter flags.
- **MCP tools**:
  - `logicchart_summary` - a small orientation snapshot (counts of flows, entrypoints,
    findings by kind/severity/evidence, domains, languages).
  - `list_findings` - ranked, filterable triage queue (severity/evidence/kind/domain/flow),
    returning deep-link fields only. The grep replacement.
  - `explain_finding(id)` - the full deterministic evidence chain (decision node, condition,
    branch labels, value set, the sibling flows/subject that triggered it, the exact missing
    values, the quorum fraction, the evidence level). Never reconstructs (and never
    hallucinates) the comparison.
  - `get_flow(..., projection)` - one flow with a neighborhood/projection to stay within an
    agent's context budget.
  - `where_is_state_handled(domain[, value])` - coverage-aware answer across flows.
  - `find_decisions` - structured search over decision nodes (domain/value/missing-fallback/
    evidence).
  - `explain_impact(changed_files)` - reachability-aware impact with caller paths to
    entrypoints and findings on the impacted subgraph.
  - `diff_models(base, head)` - the CI primitive: findings introduced/resolved/persisting by
    stable id; emit SARIF + GitHub markdown + non-zero exit.
  - `what_conflicts_with(domain, new_value)` and `trace_path(from, to)` - later; do not ship
    the tool name before its underlying data exists.
  - Every query/list tool takes a `token_budget` (and depth/projection) parameter so an agent
    can cap how much context one call returns.
  - Transport: **stdio by default**; an optional HTTP transport with an api-key may be offered
    for shared/team access, aligned with the deferred future-hosted-layer option.
- **HTML viewer**:
  - Core: a **findings inbox** (sorted severity > evidence > kind; click deep-links to the
    flow, pans to the node, opens an inspector) and a **severity/evidence filter bar**.
  - Then: evidence-distinct node styling (VERIFIED solid, INFERRED dashed, has-finding
    highlighted) with a legend; path-focus mode; **side-by-side conflict view** for
    cross-flow findings; a decision **case-matrix** (rows = flows, columns = values, cells =
    handled/missing/has-fallback); caller/callee navigation; configurable jump-to-source
    (VS Code / JetBrains / GitHub blob); deep-linkable URL state; an entrypoint overview map;
    keyboard-driven triage; a **diff mode** overlaying two `logic-flow.json` files.
- **Markdown**: signal/noise split - above-threshold findings in the main section,
  heuristic/low-confidence ones under a collapsible "review-only" subheading; per-node
  review points.
- **CI**: `diff_models` gate (SARIF + PR markdown + exit codes) flagging introduced findings
  and logic regressions (removed branch, coverage shrink).

### 5.3 Data model (IR) capabilities

- **Per-branch outcome annotations**: on each decision's outgoing edge, `branch_outcome` in
  `{returns, raises, falls_through, empty, continues}`; node-level `reachable_from_entry` /
  `reaches_terminal`; tag the synthetic `else`/`default` edge as `implicit`.
- **Decision identity**: normalized `subject` (dotted LHS), `operator` (`==`/`!=`/`in`/
  `is`), negation flag, and `value_namespace` (dotted enum prefix).
- **Import-aware call resolver**: per-file imports map (alias → fully-qualified target);
  resolve via imports + qualified symbol before the short-name fallback; record
  `link_confidence`; **keep ambiguous candidates instead of dropping them**.
- **Enum / value-universe table**: project-level map (symbol → members) harvested from
  Python `Enum`/`Literal` and TS enums/unions.
- **Effect tags** on call nodes (subset of `{io, db_read, db_write, network, auth_check,
  raises, log}`) and a flow-level `performs_auth_check`; widened auth lexicon
  (`require_admin`, `check_permission`, `ensure_authenticated`, `get_current_user`, …).
- **Lightweight def/use** records and captured assignment-RHS / return-shape (the smallest
  data-flow primitive).
- **Finding extension** via an **open `metadata` sub-object** (schema bump `1.0` → `1.1`)
  carrying `related_locations`, `rule_id`, `category`, `confidence`, `quorum` - so the closed
  required surface of the schema is touched once.
- **Stable finding ids** derived from structural anchors (symbol + node ordinal), not from
  mutable `domain`/`missing` strings, so "pin a finding, act, re-query the same id" survives
  IR changes.

### 5.4 Agent symbiosis & sync loop

LogicChart, the LLM, and the coding agent form a closed loop around the committed model, with
a strict division of labor (the pattern proven by graphify, adapted to LogicChart's
deterministic-core constraint):

- **The tool builds and owns the model** - deterministically. It is the only author of
  `logic-flow.json`.
- **The agent consumes and navigates** - it queries the model *before* grepping/reading and
  refreshes it *after* editing; it never authors the model.
- **The LLM only enriches** - labels, descriptions, tooltips (§8); it never adds or changes a
  node, edge, or finding.

Mechanics that keep the loop in sync, all on the deterministic (no-API) path:

- **`logicchart hook install`** - a post-commit (and post-checkout) git hook that runs the
  deterministic `update` on every commit, so the committed model never drifts; plus a git
  **union merge-driver** for `logic-flow.json` so teammates don't conflict on it.
- **`logicchart watch`** - a debounced background watcher that re-runs the deterministic pass
  and refreshes `logic-flow.json` on save, for parallel agent-swarm editing. Never invokes the
  enrichment layer.
- **`logicchart install --hook`** - opt-in: registers a Claude Code PreToolUse hook on
  Read/Grep/Glob that nudges the agent to run `logicchart query` first when a model exists,
  enforcing (not merely suggesting) the "query before file-by-file search" rule.
- **Agent-navigable index** - a derived `index.md` (alongside `logic-flow.md`) so an agent can
  browse the model by reading files instead of parsing JSON. Derived artifact, never a source
  of truth.
- **Sidecar agent memory (firewalled)** - resolved query answers may be cached in a separate
  memory store for reuse, but it is **never merged into `logic-flow.json`, never `VERIFIED`**,
  and toggling it never changes the verified model's content hash.
- **`update` shows a flow-diff** - new/closed findings and added/removed entry points since the
  last run (the local sibling of the `diff_models` CI primitive), keyed on the structural
  stable finding ids.

## 6. Architecture & constraints

- One **versioned JSON IR** powers the CLI, MCP, Markdown, and HTML. No feature bypasses it.
- **Pluggable analyzer layer** with a clear language→IR interface. Ship **Python + TS/TSX**;
  adding a language later (Go, Java, …) must be cheap.
- Framework adapters: FastAPI and Next.js to start (routes, middleware, server actions,
  pages, layouts; shallow React components/hooks/handlers), extensible.
- `logic-flow.json` and `.md` are committed; `.html` is generated locally and git-ignored.
- Output directory must stay inside the analyzed project; the viewer serves on localhost only.
- Quality gates: `mypy --strict`, `ruff` (check + format), tests with coverage, CI on a
  Python version matrix.
- Everything user-facing - code, output, docs - is in **English**.

## 7. Quality bar, non-goals

**Quality bar / success criteria**

- LogicChart **self-excludes its own `src/` and `tests/`** from the published artifact
  (default self-exclude or `.logicchartignore`), so the committed output is never polluted by
  the tool analyzing its own parser internals.
- Precision SLA is measured on **`examples/demo`** (target: ≤1 `POTENTIAL_GAP`, 0
  cross-language false positives after the subject/namespace + language-scoping fix).
- No detector ships without a **golden-master test**: a hard false-positive ceiling **and** a
  positive fixture containing a real cross-flow gap (so disabling a detector fails the test).
- **Default report** shows `VERIFIED` + `INFERRED`; `POTENTIAL_GAP` / low-confidence findings
  are grouped separately or behind `--include-gaps`.
- Inferred findings are never presented as confirmed bugs.
- The output carries a blunt provenance legend - *"so you always know what was found vs
  guessed"* - and `explain_finding`/queries quote the exact source span. `POTENTIAL_GAP` (a
  review-candidate finding) is a deliberate step beyond a mere uncertainty tag and stays gated
  behind `--include-gaps`.
- A **worked-example corpus**: a `worked/` folder of sample repos with checked-in
  `logic-flow.json` and a candid `review.md` scoring what the analysis got right and wrong
  (false positives, missed cases) - doubling as a regression suite and a public honesty
  artifact, generalizing the golden-master + `examples/demo` SLA.

**Non-goals**

- No full symbolic execution, runtime tracing, exact data-flow, or deep React state
  reconstruction.
- Not as deep as CodeQL for security taint analysis, nor as broad as SonarQube's hundreds of
  single-spot rules. LogicChart favors explainable, high-signal heuristics, always linked to
  the evidence that produced them.

## 8. Static analysis vs the LLM layer (the boundary)

The verified model and **every structural finding are produced by deterministic static
analysis only**. No language model is required - or involved - in building the graph or
detecting holes. This is a hard constraint: determinism is what makes the output
reproducible, git-diffable, CI-gateable, and trustworthy, which is the product's entire
wedge.

**Always static (the truth layer):** parsing code into flows/decisions/branches; every
structural and cross-flow detector; evidence levels; line links; the JSON IR; anything
labeled `VERIFIED` or able to gate CI. Same input → same output, no API key, no
hallucination.

**Optional LLM enrichment (a presentation layer, off by default):** LogicChart MAY use a
model purely to make the graph *clearer for humans* - never to decide what the graph
contains. Allowed enrichments:

- friendlier node labels (e.g. "Block suspended users" instead of
  `account.status == AccountStatus.SUSPENDED`);
- prose descriptions, tooltips, and natural-language summaries for flows, decisions, and
  findings, surfaced in the viewer and in `explain_finding`;
- opt-in fuzzy domain-synonym hints (`user.status` ≡ `account.state`) offered as `INFERRED`
  review suggestions only.

**Two ways to supply the model, both opt-in:**

1. **Bring your own coding agent** - when LogicChart is driven by an agent (Claude Code,
   Cursor, Codex), the agent generates the enrichment from the deterministic model; no API
   key lives in LogicChart.
2. **Bring your own API key** - configure a model provider so the CLI and viewer can enrich
   labels, descriptions, and tooltips directly.

**Rules the enrichment layer must obey:**

- It enriches; it never constrains or alters flowchart generation. The deterministic graph
  is byte-identical with or without it.
- No enrichment output is ever `VERIFIED` (presentation or `INFERRED` at most), is never
  required, never blocks CI, and is off by default.
- Enrichment is stored separately from the canonical model (a sidecar/cache), so the
  committed `logic-flow.json` and its content hash stay deterministic. Turning enrichment
  on or off must never change the verified graph.

**Boundary by input type, drawn even sharper than comparable tools.** Some tools route
non-code inputs (docs, PDFs, images) *through* a model to generate graph fragments. LogicChart
does not: **code is the only input, and the entire graph is deterministic.** The model only
relabels or describes what the deterministic pass already produced - it never authors a node,
edge, or finding. (A tool whose `INFERRED` edges are a *model's* guesses is a weaker guarantee
than LogicChart's `INFERRED`, which is always a *deterministic* heuristic and stays
reproducible and CI-gateable.)

**Prompt-injection hardening.** Whenever the enrichment layer sends source code or comments to
a model, it must instruct the model to treat all source content as inert data, never as
instructions.

**Backend abstraction with graceful degradation.** If/when the API-key path is added, it goes
through a provider abstraction with a no-key local option (e.g. Ollama) and a
bring-your-own-agent/CLI fallback, so the core `query`/`impact`/`update` commands never
hard-depend on a paid key.

**Memory firewall.** Any agent- or LLM-authored answer or memory lives only in the sidecar
store (§5.4); it is never folded back into `logic-flow.json` and never labeled `VERIFIED`, so
the committed model stays deterministic.

## 9. Build Order & Dependencies

The product above is one coherent target. It must be built in this order because later
capabilities depend on earlier ones, and because shipping the high-false-positive cross-flow
detector before its foundations exist would destroy the credibility the product depends on.

**Stage 0 - Credibility hygiene (do first, cheap).**
Self-exclude LogicChart's own source from the published artifact; re-baseline all
noise expectations on `examples/demo`; add an immediate language-scoping guard to the
existing cross-flow detector (key the bucket on at least `(language, domain)`, which alone
removes the demo's only false positive); add the golden-master noise test.

**Stage 1 - IR foundation.**
Add per-branch `branch_outcome` + reachability flags, and decision identity
(`subject` / `operator` / negation / `value_namespace`). *Rationale: `branch_outcome`
unblocks four single-flow detectors **and** is what lets the cross-flow detector tell a
legitimate implicit-default apart from a real missing case.*

**Stage 2 - Reliable single-flow detectors (the trust layer ships here).**
`missing_branch` extended to `if`/`elif` (flagship); dead-code and dead-join; then
broad-except-swallow, no-op-branch, asymmetric-return (now enabled by `branch_outcome`).

**Stage 3 - Call-resolver fix.**
Import-aware resolution with `link_confidence`, keeping ambiguous candidates. *Hard
prerequisite for any interprocedural / cross-flow-via-calls detector; until it lands, those
detectors cannot be trusted and must not be promised.*

**Stage 4 - Cross-flow foundation.**
Quorum logic + subject/namespace keying; the enum/value-universe table; effect tags on
calls; the open Finding `metadata` sub-object (schema `1.1`); structural stable finding ids.

**Stage 5 - Cross-flow detectors (the differentiated headline).**
Quorum-aware value-set divergence; enum-vs-declared exhaustiveness; outcome inconsistency;
default-semantic inconsistency; logging asymmetry; feature-flag asymmetry; return-shape
divergence.

**Stage 6 - Consumption upgrades.**
The richer MCP tools (`where_is_state_handled`, `explain_impact`, `find_decisions`,
`diff_models`); the viewer features beyond the inbox + filter; the CI diff gate.

**Stage 7 - Gated and later.**
Auth/validation divergence (opt-in, after the resolver fix + widened auth lexicon); the
def/use data-flow primitive and the detectors it unblocks (type/schema contradiction,
contradictory guards, state-machine inconsistency, null-handling); additional-language
analyzers via the pluggable layer.

**Not yet implemented (explicitly deferred).** Some surfaces named in §5.2/§5.4 are not in
the current CLI and are deferred rather than dropped, so the gap is documented, not silent:
the `watch` debounced rebuild; `install --hook` (the Claude Code PreToolUse nudge - distinct
from the delivered `hook install` git auto-sync); the `--deep`/audit mode; and the
confidence-threshold / evidence-filter query flags. The signal/noise split and `--include-gaps`
gating (§5.2/§7) and the §5.3 query tools that exist today are delivered.

**Standing rules across stages:** build the IR a detector needs before the detector; never
ship an MCP tool name before its underlying data exists; keep the default report
high-confidence; measure every noise claim against `examples/demo`, not the self-scan.

**Review cadence (a gate at the end of each stage).** At the conclusion of each stage - each
group of steps above - run two reviews before moving on:

1. a **correctness code review** - bugs, edge cases, regressions, and confirmation that the
   planted-fixture findings still fire while the controls stay silent;
2. a **code-quality review** - readability, naming, simplification, dead code, duplication,
   test coverage, and adherence to `mypy --strict` / `ruff` and the project's conventions.

Both reviews - alongside the automated gates (`mypy`, `ruff`, tests, and the golden-master
precision SLA on `examples/demo`) - must pass before the next stage starts. Findings from
either review are fixed or explicitly deferred with a written reason; a stage is not "done"
until its reviews are clean.
