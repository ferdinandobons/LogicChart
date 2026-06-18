<!-- logicchart:instructions:start -->
## LogicChart

This project uses LogicChart to keep decision flows synchronized with the source code.

For codebase questions about behavior, decisions, missing cases, or change impact:

1. Prefer `logicchart query "<question>"` before broad file-by-file searches.
2. Use `logicchart impact [changed files...]` before implementing a substantial change.
3. Review `logicchart-out/logic-flow.md` and any related `POTENTIAL_GAP` findings.

After a substantial code change:

1. Run `logicchart impact`.
2. Review every affected entry point and caller flow.
3. Run `logicchart update`.
4. Commit synchronized changes to:
   - `logicchart-out/logic-flow.json`
   - `logicchart-out/logic-flow.md`

For viewer/UI changes:

1. Run `npm run viewer:typecheck`, `npm run viewer:test`, and `npm run viewer:build`.
2. Regenerate HTML artifacts with `logicchart update` and
   `logicchart view examples/demo --render-only --no-open`.
3. Check the generated demo viewer with a cache-buster URL.

Do not present inferred findings as confirmed bugs. LogicChart marks syntax-backed facts as
`VERIFIED`, deterministic heuristics as `INFERRED`, and review candidates as `POTENTIAL_GAP`.
<!-- logicchart:instructions:end -->
