"""Discovery edge cases: a symlink whose target resolves outside the root is skipped,
not allowed to abort the whole walk (relpath/relative_to would otherwise raise)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from logicchart.analysis.discovery import discover_source_files
from logicchart.config import LogicChartConfig


@pytest.mark.skipif(
    sys.platform == "win32", reason="symlink creation often needs elevation on Windows"
)
def test_symlink_pointing_outside_root_is_skipped(tmp_path: Path) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()

    # A real in-tree file plus a symlink whose resolved target is OUTSIDE the project.
    (project / "real.py").write_text("def handler(x):\n    return x\n", encoding="utf-8")
    (outside / "external.py").write_text("def external():\n    return 1\n", encoding="utf-8")
    link = project / "linked.py"
    try:
        link.symlink_to(outside / "external.py")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported in this environment")

    files = discover_source_files(project, LogicChartConfig())
    names = {path.name for path in files}

    # The in-tree file is found; the out-of-tree symlink is skipped without crashing.
    assert "real.py" in names
    assert "external.py" not in names
    # Every returned path has a valid project-relative path (no relpath would raise).
    for path in files:
        assert path.resolve().is_relative_to(project.resolve())


def test_large_codebase_default_excludes_skip_generated_trees(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "real.py").write_text("def handler(x):\n    return x\n", encoding="utf-8")
    (project / "node_modules").mkdir()
    (project / "node_modules" / "dep.ts").write_text(
        "export function dep() { return 1; }\n", encoding="utf-8"
    )
    nested = project / "apps" / "web" / "dist"
    nested.mkdir(parents=True)
    (nested / "bundle.js").write_text("export function built() { return 1; }\n", encoding="utf-8")
    (project / "target").mkdir()
    (project / "target" / "gen.cpp").write_text("int generated() { return 1; }\n", encoding="utf-8")
    nested_git = project / "backend" / ".git" / "hooks"
    nested_git.mkdir(parents=True)
    (nested_git / "hook.py").write_text("def hook():\n    return 1\n", encoding="utf-8")
    nested_venv = project / "backend" / ".venv" / "lib"
    nested_venv.mkdir(parents=True)
    (nested_venv / "site.py").write_text("def installed():\n    return 1\n", encoding="utf-8")
    nested_cache = project / "backend" / ".pytest_cache"
    nested_cache.mkdir(parents=True)
    (nested_cache / "cached.py").write_text("def cached():\n    return 1\n", encoding="utf-8")
    generated_dir = project / "__generated__"
    generated_dir.mkdir()
    (generated_dir / "client.ts").write_text("export function generated() { return 1; }\n")
    temp_dir = project / "backend" / "temp"
    temp_dir.mkdir()
    (temp_dir / "scratch.py").write_text("def scratch():\n    return 1\n", encoding="utf-8")
    (project / "src" / "api.pb.go").write_text(
        "package src\n\nfunc Generated() int { return 1 }\n", encoding="utf-8"
    )

    files = {
        path.relative_to(project).as_posix()
        for path in discover_source_files(project, LogicChartConfig())
    }

    assert files == {"src/real.py"}


def test_config_exclude_dirs_prunes_project_specific_directories(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "logicchart.toml").write_text(
        '[logicchart]\nexclude_dirs = ["private-fixtures", "generated-*"]\n',
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "src" / "real.py").write_text("def handler(x):\n    return x\n", encoding="utf-8")
    private = project / "private-fixtures"
    private.mkdir()
    (private / "secret.py").write_text("def secret():\n    return 1\n", encoding="utf-8")
    generated = project / "apps" / "generated-client"
    generated.mkdir(parents=True)
    (generated / "client.ts").write_text("export function generated() { return 1; }\n")

    config = LogicChartConfig.load(project)
    files = {
        path.relative_to(project).as_posix() for path in discover_source_files(project, config)
    }

    assert files == {"src/real.py"}


def test_default_exclude_dirs_apply_to_source_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "logicchart.toml").write_text(
        '[logicchart]\nsource_roots = ["node_modules"]\n',
        encoding="utf-8",
    )
    dependency = project / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "index.ts").write_text("export function installed() { return 1; }\n")

    config = LogicChartConfig.load(project)
    files = discover_source_files(project, config)

    assert files == []


def test_default_exclude_dirs_apply_inside_source_roots(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "logicchart.toml").write_text(
        '[logicchart]\nsource_roots = ["src", "node_modules/package", "apps/web/dist/bundle.js"]\n',
        encoding="utf-8",
    )
    (project / "src").mkdir()
    (project / "src" / "real.py").write_text("def handler(x):\n    return x\n", encoding="utf-8")
    dependency = project / "node_modules" / "package"
    dependency.mkdir(parents=True)
    (dependency / "index.ts").write_text("export function installed() { return 1; }\n")
    bundled = project / "apps" / "web" / "dist"
    bundled.mkdir(parents=True)
    (bundled / "bundle.js").write_text("export function bundled() { return 1; }\n")

    config = LogicChartConfig.load(project)
    files = {
        path.relative_to(project).as_posix() for path in discover_source_files(project, config)
    }

    assert files == {"src/real.py"}
