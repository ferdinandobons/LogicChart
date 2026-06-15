"""The language registry: dispatch by suffix and lazy analyzer construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.analysis.registry import (
    language_for,
    spec_for_language,
    spec_for_path,
    supported_suffixes,
)


def test_known_suffixes_map_to_languages() -> None:
    assert language_for(Path("a/b.py")) == "python"
    assert language_for(Path("a/b.ts")) == "typescript"
    assert language_for(Path("a/b.tsx")) == "typescript"
    assert {".py", ".ts", ".tsx"} <= supported_suffixes()


def test_unknown_suffix_is_rejected() -> None:
    assert spec_for_path(Path("a/b.unknown")) is None
    with pytest.raises(ValueError, match="Unsupported source file"):
        language_for(Path("a/b.unknown"))


def test_spec_factory_builds_an_analyzer(tmp_path: Path) -> None:
    spec = spec_for_language("python")
    analyzer = spec.factory(tmp_path, _config(tmp_path))
    assert hasattr(analyzer, "analyze")


def test_project_analyzer_dispatches_and_caches(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def f(x):\n    return x\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text(
        "export function g(x: number) {\n  return x;\n}\n", encoding="utf-8"
    )
    analyzer = ProjectAnalyzer(tmp_path)
    model = analyzer.analyze(full=True).model
    languages = {flow.language for flow in model.flows}
    assert {"python", "typescript"} <= languages
    # Analyzers are cached lazily, one per language actually seen.
    assert set(analyzer._analyzers) == {"python", "typescript"}


def _config(root: Path):
    from logicchart.config import LogicChartConfig

    return LogicChartConfig.load(root)
