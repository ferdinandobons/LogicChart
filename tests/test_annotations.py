from __future__ import annotations

import json
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.annotations import annotations_path, load_annotations, model_hash
from logicchart.artifacts import write_artifacts
from logicchart.validation import validate_logicchart


def _analyzed_project(tmp_path: Path):
    (tmp_path / "app.py").write_text(
        "def authorize(user):\n"
        "    if user.role == 'admin':\n"
        "        return True\n"
        "    return False\n",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model)
    return result.model


def test_annotation_sidecar_loads_when_model_hash_matches(tmp_path: Path) -> None:
    model = _analyzed_project(tmp_path)
    flow = model.flows[0]
    node = next(item for item in flow.nodes if item.kind.value == "decision")
    path = annotations_path(tmp_path)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model_hash": model_hash(model),
                "generated_by": {"kind": "manual"},
                "flows": {
                    flow.id: {
                        "label": "Role authorization gate",
                        "summary": "Decides whether the current user can continue.",
                    }
                },
                "nodes": {
                    node.id: {
                        "label": "Admin role check",
                        "description": "Checks the admin role branch.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_annotations(tmp_path, model)
    report = validate_logicchart(tmp_path, include_annotations=True)

    assert loaded.ok
    assert loaded.status == "loaded"
    assert loaded.annotations is not None
    assert loaded.annotations["flows"][flow.id]["label"] == "Role authorization gate"
    assert report.ok
    assert report.annotations is not None
    assert report.annotations["status"] == "loaded"
    assert report.annotations["counts"] == {
        "findings": 0,
        "flows": 1,
        "nodes": 1,
        "scopes": 0,
    }


def test_annotation_sidecar_rejects_stale_hash_and_unknown_ids(tmp_path: Path) -> None:
    model = _analyzed_project(tmp_path)
    path = annotations_path(tmp_path)
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "model_hash": "stale",
                "flows": {"missing-flow": {"label": "Unknown"}},
            }
        ),
        encoding="utf-8",
    )

    loaded = load_annotations(tmp_path, model)
    report = validate_logicchart(tmp_path)

    assert not loaded.ok
    assert loaded.status == "stale"
    assert any("current model_hash" in error for error in loaded.errors)
    assert any("missing-flow" in error for error in loaded.errors)
    assert not report.ok
    assert report.annotations is not None
    assert report.annotations["status"] == "stale"
