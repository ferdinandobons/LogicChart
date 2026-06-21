"""Query consumption-surface regression coverage."""

from __future__ import annotations

from logicchart.model import ProjectModel
from logicchart.query import impact_model


def test_normalize_path_preserves_dot_prefixed_paths() -> None:
    model = ProjectModel(schema_version="2.0", generated_at="x", root=".")
    result = impact_model(model, [".github/workflows/ci.yml", "./src/app.py", "../x/y.py"])
    assert ".github/workflows/ci.yml" in result.changed_files
    assert "src/app.py" in result.changed_files  # only the leading "./" is stripped
    assert "../x/y.py" in result.changed_files
