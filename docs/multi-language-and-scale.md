# LogicChart: multi-language and whole-codebase expansion

This document defines the next major phase of LogicChart. The goal: extend the deterministic
engine from Python + TypeScript to **all popular languages** (including infrastructure-as-code),
represent **complex code correctly**, and operate at **any scale** - from a single function (as
today) to an entire codebase or a macro-part of one (all the backend, all the frontend, the
Terraform infrastructure).

It builds on the existing architecture (see [project-definition.md](project-definition.md)):
per-file analyzers produce one IR (`logic-flow.json`, schema 1.1), and a project layer links
calls, runs cross-flow detectors, and renders Markdown/HTML. That shape is preserved; this phase
generalizes the language front-end and adds scope/scale to the project layer.

## 1. Principles (unchanged)

- **Deterministic, local, no API key.** Every new language is parsed with a grammar, not an LLM.
- **Evidence-tiered.** New extractors keep the `VERIFIED` / `INFERRED` / `POTENTIAL_GAP` ledger.
- **Per-file isolation.** One un-parseable file is skipped and reported, never aborts the run
  (already implemented) - essential when a codebase mixes many languages and dialects.
- **Graceful degradation.** A construct the profile does not model becomes a neutral action node,
  never a crash and never a wrong claim.

## 2. Pluggable language layer

### 2.1 Registry

A single registry maps a language to its file suffixes and an analyzer factory:

```
LanguageSpec(id, suffixes, factory)         # factory(root, config) -> LanguageAnalyzer
LANGUAGES: list[LanguageSpec]
language_for(path) -> language id            # by suffix, via the registry
analyzer_for(language, root, config)         # cached per language
```

`discovery.discover_source_files` collects every file whose suffix any spec claims;
`ProjectAnalyzer._analyze_file` dispatches through the registry. Adding a language is one
`LanguageSpec` entry plus its analyzer/profile - no edits to discovery or the project loop.

### 2.2 Profile-driven tree-sitter analyzer

Most languages share the same control-flow shape (functions, `if`, `switch`/`match`, loops,
`return`, `throw`/`raise`, `try`/`catch`, calls). A generalized `TreeSitterAnalyzer` runs the
common walk, parameterized by a `LanguageProfile` that names the grammar node types and supplies
small per-language extractors:

```
LanguageProfile(
  language, grammar,                         # tree-sitter Language
  function_types, callable_value_types,      # what defines a flow
  body_field, name_field,
  if_type, condition_field, consequence_field, alternative_field,
  switch_type, case_types, default_types,
  loop_types,
  return_type, throw_type, call_type,
  try_type, catch_types, finally_field,
  inert_types,                               # comments, empty statements
  classify_entrypoint(node, relative, source, config) -> (framework, entry_kind, is_entrypoint),
  is_test(relative, name) -> bool,
  import_map(root_node, source, relative) -> dict[str, str],
)
```

Each new control-flow language becomes a `LanguageProfile` (plus a tiny subclass only for genuine
quirks). Python keeps its dedicated `ast`-based analyzer (high fidelity, no grammar dep);
TypeScript keeps its tuned analyzer initially and may later be expressed as a profile once the
generic engine reaches parity. The IR contract (flows, nodes, edges, `branches`, decision
identity, effects, qualified calls) is identical across all front-ends.

### 2.3 Languages

- **Control-flow (profiles):** JavaScript/JSX, Go, Java, C#, Ruby, PHP, Rust, C, C++, Kotlin,
  Swift, Bash. Each ships with framework/entry-point hints where they matter (e.g. Spring,
  Rails, Gin, ASP.NET) and test-file detection.
- **Infrastructure-as-code (declarative):** Terraform/HCL is not control flow; it is a
  resource/module dependency graph. It gets its own analyzer that emits the same IR with a
  declarative flavor: each resource/module/data block is a node, `depends_on` and interpolation
  references are edges, and `module` calls link sub-graphs. Findings: missing/duplicate
  dependencies, unused variables/outputs, provider/version gaps. (Kubernetes/YAML manifests and
  CloudFormation can follow the same declarative pattern later.)

## 3. Scope and macro-parts

A codebase is rarely analyzed as one undifferentiated blob. LogicChart gains a first-class
**scope** concept so the same project can be viewed as small pieces (today), an entire codebase,
or a named macro-part.

- **Config.** Named scopes declared in `logicchart.toml`:

  ```toml
  [logicchart.scopes]
  backend  = ["backend/**", "services/**"]
  frontend = ["frontend/**", "web/**"]
  infra    = ["infra/**", "**/*.tf"]
  ```

  When no scopes are declared, each top-level `source_root` (or language family) is an implicit
  scope.
- **Tagging.** Every flow records the scope(s) it belongs to (`flow.metadata.scope`), derived
  from its path against the scope globs.
- **Surfaces.**
  - `analyze` / `view` / `query` / `impact` / `diff` accept `--scope <name>` to restrict to a
    macro-part, and a codebase-wide default that groups by scope.
  - The Markdown and HTML render a **codebase map**: scopes as clusters, entry-point counts and
    findings per scope, and cross-scope call edges where they resolve. Drilling into a scope
    shows its flows (the current per-flow view).
  - The MCP query surface filters by scope.

## 4. Whole-codebase scale

Representing entire codebases correctly and usably:

- **Performance.** Per-file analysis is independent and already content-hash cached; parallelize
  it across a worker pool. Linking and cross-flow detection stay single-pass over the combined
  model. Target: a large repo re-analyzes incrementally in seconds, full in a bounded budget.
- **Rendering at scale.** A 10k-node graph must not render all at once. The viewer gains:
  scope/language filters, an overview "map" of scopes/entry points that lazily expands into
  individual flows, and search-driven navigation. The committed Markdown stays per-flow but is
  organized by scope with a top-level index.
- **Memory.** The IR is per-flow and streams to JSON; rendering is scoped/lazy so memory tracks
  the visible slice, not the whole graph.

## 5. Complex-code correctness

"Any kind of code, even complex" is a correctness bar, validated by fixtures per language:
nested/anonymous functions and closures, async/await and coroutines, generators/iterators,
decorators/annotations, pattern matching, exceptions and multi-catch, early returns, labelled
breaks, and generics. The engine represents what it can verify and degrades the rest to neutral
nodes; it never emits a wrong `VERIFIED` claim. Each language's fixture doubles as a golden
master so regressions are caught.

## 6. Build order

Each stage ends with the review cadence from project-definition.md sec. 9 (a correctness review
and a code-quality review; automated gates green; the demo precision SLA holds).

- **Stage A - Pluggable language registry.** Refactor discovery + dispatch into the registry.
  Python + TS register. No behavior change.
- **Stage B - Profile-driven engine + first language.** Generalize the tree-sitter walk into a
  `LanguageProfile`-driven analyzer; add one new language (Go) end-to-end (grammar dep, profile,
  fixture, golden) to prove a language is cheap to add.
- **Stage C - Popular control-flow languages.** Java, C#, Ruby, PHP, Rust, C/C++, plain JS/JSX,
  Kotlin, Swift, Bash as profiles, each with fixtures, entry-point and test detection.
- **Stage D - Terraform / IaC.** The declarative resource-dependency analyzer and its render.
- **Stage E - Scope / macro-parts.** Config scopes, per-flow tagging, `--scope` across the CLI,
  scope-grouped render/query/diff, the codebase map.
- **Stage F - Whole-codebase scale.** Parallel analysis; viewer clustering/scope filtering and
  lazy rendering; performance and memory for entire codebases.
- **Stage G - Complex-code hardening.** Per-language complex fixtures and a correctness pass.

**Standing rules:** build the IR a feature needs before the feature; keep the default report
high-confidence; one bad file never aborts a run; measure noise against the demo corpora, not the
self-scan; every language ships with at least one fixture and golden assertions.
