from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

from logicchart.analysis.registry import supported_suffixes
from logicchart.config import LogicChartConfig

# Running LogicChart package dir: discovery.py is <pkg>/analysis/discovery.py,
# so two parents up is <pkg> (".../logicchart").
_SELF_PACKAGE_DIR = Path(__file__).resolve().parent.parent


def discover_source_files(root: Path, config: LogicChartConfig) -> list[Path]:
    root_resolved = root.resolve()
    excluded_roots = _self_exclude_roots(root_resolved) if config.self_exclude else []
    suffixes = supported_suffixes()
    files: set[Path] = set()
    for source_root in config.source_roots:
        base = (root_resolved / source_root).resolve()
        if not base.exists():
            continue
        for candidate in _candidate_paths(root_resolved, base, config, excluded_roots):
            if not candidate.is_file() or candidate.suffix.lower() not in suffixes:
                continue
            # Self-exclusion uses a resolved-path prefix check, not a `config.exclude`
            # glob: the running package may live outside the analyzed tree (e.g. a
            # virtualenv has no project-relative path).
            resolved = candidate.resolve()
            if any(resolved.is_relative_to(item) for item in excluded_roots):
                continue
            # A symlink (or junction) whose target resolves outside the analyzed root has
            # no project-relative path, so relpath would raise. Skip it rather than abort
            # discovery - it isn't part of this project's tree.
            if not resolved.is_relative_to(root_resolved):
                continue
            relative = _resolved_relpath(resolved, root_resolved)
            if not config.is_excluded(relative) and not config.is_excluded_dir(relative):
                files.add(candidate)
    return sorted(files, key=lambda item: _resolved_relpath(item.resolve(), root_resolved))


def _candidate_paths(
    root_resolved: Path,
    base: Path,
    config: LogicChartConfig,
    excluded_roots: list[Path],
) -> Iterator[Path]:
    if base.is_file():
        yield base
        return
    for current, dirnames, filenames in os.walk(base):
        current_path = Path(current)
        current_resolved = current_path.resolve()
        if not current_resolved.is_relative_to(root_resolved):
            dirnames[:] = []
            continue
        if any(current_resolved.is_relative_to(item) for item in excluded_roots):
            dirnames[:] = []
            continue
        relative_current = _resolved_relpath(current_resolved, root_resolved)
        if relative_current != "." and (
            config.is_excluded_dir(relative_current) or config.is_excluded(relative_current)
        ):
            dirnames[:] = []
            continue
        kept_dirs: list[str] = []
        for dirname in dirnames:
            directory = current_path / dirname
            resolved = directory.resolve()
            if not resolved.is_relative_to(root_resolved):
                continue
            if any(resolved.is_relative_to(item) for item in excluded_roots):
                continue
            relative = _resolved_relpath(resolved, root_resolved)
            if config.is_excluded_dir(relative) or config.is_excluded(relative):
                continue
            kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in filenames:
            yield current_path / filename


def _resolved_relpath(path: Path, root_resolved: Path) -> str:
    return path.relative_to(root_resolved).as_posix()


def _self_exclude_roots(root: Path) -> list[Path]:
    """Return LogicChart's own directories, to keep the tool's parser internals out
    of the published artifact.

    Always excludes the running package directory. When the analyzed root *is* the
    LogicChart source checkout (its ``src/logicchart`` resolves to the running
    package), also excludes the project's own ``tests/`` suite.
    """
    roots = [_SELF_PACKAGE_DIR]
    if (root / "src" / "logicchart").resolve() == _SELF_PACKAGE_DIR:
        roots.append((root / "tests").resolve())
    return roots
