# Contributing to LogicChart

LogicChart welcomes bug reports, language fixtures, framework adapters, documentation, and
code contributions.

## Development Setup

```bash
uv sync --extra dev
uv run pytest
```

Viewer UI/layout work also uses the frontend workspace:

```bash
npm install
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
```

`npm run viewer:build` writes the offline React runtime to
`src/logicchart/render/assets/generated/logicchart-viewer-runtime.iife.js`; regenerate the
demo HTML before browser checks and open it with `?runtime=react` when testing the typed
canvas path.

Viewer changes should preserve the manual exploration invariants: scope nodes use the same
node styling family as other blocks, each scope connects to all visible entrypoints,
expanded details reserve layout space before rendering, selected links dim unrelated
blocks, and invisible hit paths never become visible bounding boxes.

The recommended viewer loop is:

```bash
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart update
UV_CACHE_DIR=/tmp/logicchart-uv-cache uv run logicchart view examples/demo --render-only --no-open
```

Use a cache-buster when reloading the generated demo viewer in a browser:

```text
logic-flow.html?runtime=react&v=<stamp>#scope=frontend
```

Before submitting a pull request:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov
npm run viewer:typecheck
npm run viewer:test
npm run viewer:build
npm audit --audit-level=high
```

## Analyzer Changes

Every analyzer change should include a minimal source fixture and assertions for:

- detected entry points;
- decision nodes and branch labels;
- source locations;
- evidence level;
- call metadata and domain metadata when the fixture exercises them.

Keep language-specific extraction separate from the shared logical IR. Framework knowledge
belongs in a focused adapter or classifier, not in the renderer.

## Compatibility

LogicChart supports Python 3.10 and later. Avoid changing the canonical JSON schema without
updating `schema_version`, migration notes, and serialization tests.
