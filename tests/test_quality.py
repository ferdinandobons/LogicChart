from __future__ import annotations

import json
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.cli import main
from logicchart.quality import model_quality, render_quality
from logicchart.validation import validate_logicchart


def test_model_quality_counts_calls_findings_and_labels(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text(
        "def target():\n"
        "    return 1\n\n"
        "def handle(order):\n"
        "    if order.status == Status.OPEN:\n"
        "        return target()\n"
        "    elif order.status == Status.CLOSED:\n"
        "        return missing()\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    quality = model.metadata["quality"]

    assert quality == model_quality(model)
    assert quality["files"]["total"] == 1
    assert quality["flows"]["total"] >= 2
    assert quality["flows"]["entrypoints"] >= 1
    assert quality["calls"]["total"] >= 2
    assert quality["calls"]["resolved"] >= 1
    assert quality["calls"]["unresolved"] >= 1
    assert quality["findings"]["total"] >= 1
    assert "missing_branch" in quality["findings"]["by_kind"]
    assert quality["source_locations"]["coverage"] > 0
    assert "Graph density" in render_quality(quality)


def test_validate_quality_json_and_text_output(tmp_path: Path, capsys) -> None:
    (tmp_path / "app.py").write_text(
        "def handle(flag):\n    if flag:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    ProjectAnalyzer(tmp_path).analyze(full=True)
    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()

    assert main(["validate", str(tmp_path), "--quality", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["quality"]["files"]["total"] == 1
    assert "calls" in payload["quality"]

    assert main(["validate", str(tmp_path), "--quality"]) == 0
    text = capsys.readouterr().out
    assert "Analysis quality:" in text
    assert "Source coverage:" in text


def test_validate_report_can_compute_quality_for_older_artifact(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert main(["analyze", str(tmp_path), "--full", "--no-html"]) == 0
    artifact_path = tmp_path / "logicchart-out" / "logic-flow.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["metadata"].pop("quality", None)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    report = validate_logicchart(tmp_path, include_quality=True)

    assert report.ok
    assert report.quality is not None
    assert report.quality["files"]["total"] == 1
