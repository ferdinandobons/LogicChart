"""JavaScript / JSX support via the TypeScript analyzer (Stage C)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import ProjectModel


def _analyze(tmp_path: Path, files: dict[str, str]) -> ProjectModel:
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def test_plain_js_is_analyzed_and_labelled(tmp_path: Path) -> None:
    model = _analyze(
        tmp_path,
        {
            "svc.js": (
                "export function handle(user) {\n"
                "  switch (user.status) {\n"
                '    case "active": return ok(user);\n'
                '    case "suspended": return blocked();\n'
                "  }\n"
                "  return persist(user);\n"
                "}\n\n"
                "function persist(u) {\n  return db.save(u);\n}\n"
            )
        },
    )
    assert {f.language for f in model.flows} == {"javascript"}
    handle = next(f for f in model.flows if f.name == "handle")
    persist = next(f for f in model.flows if f.name == "persist")
    # the intra-file call to persist resolves to its flow
    assert persist.id in handle.calls


def test_jsx_react_component_is_detected(tmp_path: Path) -> None:
    model = _analyze(
        tmp_path,
        {
            "Card.jsx": (
                "export default function Card({ items }) {\n"
                "  if (items.length === 0) {\n    return null;\n  }\n"
                "  return items.map(render);\n"
                "}\n"
            )
        },
    )
    card = next(f for f in model.flows if f.name == "Card")
    assert card.language == "javascript"
    assert card.framework == "react"
    assert card.entry_kind == "component"
    assert card.is_entrypoint


def test_typescript_is_still_labelled_typescript(tmp_path: Path) -> None:
    model = _analyze(
        tmp_path,
        {"a.ts": "export function f(x: number) {\n  return x;\n}\n"},
    )
    assert next(f for f in model.flows if f.name == "f").language == "typescript"
