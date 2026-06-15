from __future__ import annotations

from pathlib import Path

from logicchart.analysis.registry import supported_suffixes
from logicchart.config import LogicChartConfig
from logicchart.util import relpath

# The running LogicChart package directory. discovery.py lives at
# <pkg>/analysis/discovery.py, so two parents up is <pkg> (".../logicchart").
_SELF_PACKAGE_DIR = Path(__file__).resolve().parent.parent


def discover_source_files(root: Path, config: LogicChartConfig) -> list[Path]:
    excluded_roots = _self_exclude_roots(root) if config.self_exclude else []
    suffixes = supported_suffixes()
    files: set[Path] = set()
    for source_root in config.source_roots:
        base = (root / source_root).resolve()
        if not base.exists():
            continue
        candidates = [base] if base.is_file() else base.rglob("*")
        for candidate in candidates:
            if not candidate.is_file() or candidate.suffix.lower() not in suffixes:
                continue
            # Self-exclusion is a resolved-path prefix check, not a glob in
            # `config.exclude`, because the running package may be installed
            # outside the analyzed tree (a virtualenv has no project-relative path).
            resolved = candidate.resolve()
            if any(resolved.is_relative_to(item) for item in excluded_roots):
                continue
            relative = relpath(candidate, root)
            if not config.is_excluded(relative):
                files.add(candidate)
    return sorted(files, key=lambda item: relpath(item, root))


def _self_exclude_roots(root: Path) -> list[Path]:
    """Return directories that belong to LogicChart itself, to keep the tool's own
    parser internals out of the published artifact.

    Always excludes the running LogicChart package directory. When the analyzed
    root *is* the LogicChart source checkout (its ``src/logicchart`` resolves to the
    package being run), also excludes the project's own ``tests/`` suite.
    """
    roots = [_SELF_PACKAGE_DIR]
    if (root / "src" / "logicchart").resolve() == _SELF_PACKAGE_DIR:
        roots.append((root / "tests").resolve())
    return roots
