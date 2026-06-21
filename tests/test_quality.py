from __future__ import annotations

import json
from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.artifacts import write_artifacts
from logicchart.cli import main
from logicchart.quality import model_quality, render_quality
from logicchart.validation import validate_logicchart


def test_model_quality_counts_calls_and_labels(tmp_path: Path) -> None:
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
    assert "language_capabilities" in model.metadata
    assert "python" in model.metadata["language_capabilities"]
    assert quality["files"]["total"] == 1
    assert quality["files"]["skipped"]["total"] == 0
    assert quality["flows"]["total"] >= 2
    assert quality["flows"]["entrypoints"] >= 1
    assert quality["calls"]["total"] >= 2
    assert quality["calls"]["resolved"] >= 1
    assert quality["calls"]["unresolved"] >= 1
    python_depth = quality["languages"]["depth"]["python"]
    assert python_depth["files"] == 1
    assert python_depth["flows"] >= 2
    assert python_depth["decisions"] >= 1
    assert python_depth["calls"] >= 2
    assert python_depth["resolved_calls"] >= 1
    assert python_depth["unresolved_calls"] >= 1
    assert python_depth["capability"]["frontend"] == "python_ast"
    assert quality["source_locations"]["coverage"] > 0
    rendered = render_quality(quality)
    assert "Graph density" in rendered
    assert "Language depth:" in rendered
    assert "python:" in rendered


def test_validate_quality_json_and_text_output(tmp_path: Path, capsys) -> None:
    (tmp_path / "app.py").write_text(
        "def handle(flag):\n    if flag:\n        return 1\n    return 0\n",
        encoding="utf-8",
    )
    ProjectAnalyzer(tmp_path).analyze(full=True)
    assert main(["update", str(tmp_path), "--full", "--no-html"]) == 0
    capsys.readouterr()

    assert main(["validate", str(tmp_path), "--quality", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["quality"]["files"]["total"] == 1
    assert "calls" in payload["quality"]

    assert main(["validate", str(tmp_path), "--quality"]) == 0
    text = capsys.readouterr().out
    assert "Analysis quality:" in text
    assert "Skipped files:" in text
    assert "Source coverage:" in text
    assert "Language depth:" in text


def test_validate_report_can_compute_quality_for_older_artifact(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert main(["update", str(tmp_path), "--full", "--no-html"]) == 0
    artifact_path = tmp_path / "logicchart-out" / "logic-flow.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["metadata"].pop("quality", None)
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    report = validate_logicchart(tmp_path, include_quality=True)

    assert report.ok
    assert report.quality is not None
    assert report.quality["files"]["total"] == 1


def test_skipped_file_reasons_are_persisted_and_cached(tmp_path: Path) -> None:
    (tmp_path / "ok.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n    return 1\n", encoding="utf-8")

    first = ProjectAnalyzer(tmp_path).analyze(full=True)
    second = ProjectAnalyzer(tmp_path).analyze()

    assert first.skipped_files
    assert second.skipped_files == first.skipped_files
    skipped = second.model.metadata["skipped_files"]
    assert skipped == first.model.metadata["skipped_files"]
    assert skipped[0]["path"] == "broken.py"
    assert skipped[0]["language"] == "python"
    assert "invalid syntax" in skipped[0]["reason"]
    assert second.model.metadata["quality"]["files"]["skipped"]["total"] == 1
    assert second.model.metadata["quality"]["files"]["skipped"]["sample"][0]["path"] == "broken.py"


def test_quality_thresholds_fail_and_pass(tmp_path: Path, capsys) -> None:
    (tmp_path / "ok.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (tmp_path / "broken.py").write_text("def broken(:\n    return 1\n", encoding="utf-8")
    (tmp_path / "partial.ts").write_text(
        "export function partial() {\n  return 1;\n}\n@",
        encoding="utf-8",
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    write_artifacts(tmp_path, result.model, include_html=False)

    failed = validate_logicchart(tmp_path, quality_thresholds={"max_skipped_files": 0})
    passed = validate_logicchart(tmp_path, quality_thresholds={"max_skipped_files": 1})
    parse_failed = validate_logicchart(tmp_path, quality_thresholds={"max_parse_warnings": 0})
    parse_passed = validate_logicchart(tmp_path, quality_thresholds={"max_parse_warnings": 1})

    assert not failed.ok
    assert failed.quality is not None
    assert failed.errors == ["quality threshold failed: skipped files 1 > max 0"]
    assert passed.ok
    assert not parse_failed.ok
    assert parse_failed.quality is not None
    assert parse_failed.errors == ["quality threshold failed: parse warnings 1 > max 0"]
    assert parse_passed.ok
    assert main(["validate", str(tmp_path), "--max-parse-warnings", "0"]) == 1
    cli_output = capsys.readouterr()
    assert "quality threshold failed: parse warnings 1 > max 0" in cli_output.err
    assert main(["validate", str(tmp_path), "--max-parse-warnings", "1"]) == 0
    capsys.readouterr()
