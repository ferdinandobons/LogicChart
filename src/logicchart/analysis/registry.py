"""The language registry: the single place that maps a language to its file suffixes
and an analyzer factory.

Adding a language is one `LanguageSpec` entry here plus its analyzer (a dedicated class
for Python, or a `LanguageProfile` for the profile-driven tree-sitter engine). Discovery
and the project loop dispatch through this registry, so neither needs to change.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from logicchart.analysis.python import PythonAnalyzer
from logicchart.analysis.typescript import TypeScriptAnalyzer
from logicchart.config import LogicChartConfig
from logicchart.model import FileAnalysis


class LanguageAnalyzer(Protocol):
    """Every language front-end turns one source file into a `FileAnalysis`."""

    def analyze(self, path: Path) -> FileAnalysis: ...


AnalyzerFactory = Callable[[Path, LogicChartConfig], LanguageAnalyzer]


@dataclass(frozen=True, slots=True)
class LanguageSpec:
    id: str
    suffixes: tuple[str, ...]
    factory: AnalyzerFactory


# The order is the dispatch precedence when two specs claim the same suffix (none do today).
LANGUAGES: tuple[LanguageSpec, ...] = (
    LanguageSpec("python", (".py",), PythonAnalyzer),
    LanguageSpec("typescript", (".ts", ".tsx"), TypeScriptAnalyzer),
)

_BY_SUFFIX: dict[str, LanguageSpec] = {
    suffix: spec for spec in LANGUAGES for suffix in spec.suffixes
}
_BY_ID: dict[str, LanguageSpec] = {spec.id: spec for spec in LANGUAGES}


def supported_suffixes() -> frozenset[str]:
    return frozenset(_BY_SUFFIX)


def spec_for_path(path: Path) -> LanguageSpec | None:
    return _BY_SUFFIX.get(path.suffix.lower())


def language_for(path: Path) -> str:
    spec = spec_for_path(path)
    if spec is None:
        raise ValueError(f"Unsupported source file: {path}")
    return spec.id


def spec_for_language(language: str) -> LanguageSpec:
    spec = _BY_ID.get(language)
    if spec is None:
        raise ValueError(f"Unknown language: {language}")
    return spec
