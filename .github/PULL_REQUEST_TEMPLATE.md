## Summary

<!-- What changed, and why? -->

## Verification

<!-- Mark the checks you ran. Leave unchecked items that do not apply. -->

- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run ruff check .`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run ruff format --check .`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run mypy`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run pytest --cov`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run codedebrief validate . --check-sync --json`
- [ ] `npm run viewer:typecheck`
- [ ] `npm run viewer:test`
- [ ] `npm run viewer:build`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run codedebrief update`
- [ ] `UV_CACHE_DIR=/tmp/codedebrief-uv-cache uv run codedebrief view . --render-only --no-open`

## Notes

<!-- Mention docs updates, generated artifact changes, release impact, or follow-up risks. -->
