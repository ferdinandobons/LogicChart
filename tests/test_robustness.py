"""Robustness: one bad file never aborts the run; malformed JSON fails cleanly."""

from __future__ import annotations

from pathlib import Path

import pytest

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import ProjectModel
from logicchart.util import read_json


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_one_unparseable_file_does_not_abort_the_run(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    _write(tmp_path / "broken.py", "def broken(:\n")  # SyntaxError
    (tmp_path / "py2.py").write_text('print "hello"\n', encoding="utf-8")  # Py2 SyntaxError
    (tmp_path / "latin1.py").write_bytes(b"x = '\xff'\n")  # UnicodeDecodeError
    (tmp_path / "bad.ts").write_bytes(b"export const x = '\xff'\n")  # TS decode error

    result = ProjectAnalyzer(tmp_path).analyze(full=True)

    # The clean file still produced a flow and the model was written.
    assert any(flow.name == "handler" for flow in result.model.flows)
    skipped = {relative for relative, _ in result.skipped_files}
    assert skipped == {"broken.py", "py2.py", "latin1.py", "bad.ts"}
    # Every file (good and degraded) is still recorded so callers see the full tree.
    recorded = {record.path for record in result.model.files}
    assert {"good.py", "broken.py", "latin1.py", "bad.ts"} <= recorded
    # Each skip carries a non-empty human-readable reason.
    assert all(reason for _, reason in result.skipped_files)


def test_incremental_run_skips_a_newly_broken_file(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    ProjectAnalyzer(tmp_path).analyze(full=True)
    _write(tmp_path / "broken.py", "def broken(:\n")

    result = ProjectAnalyzer(tmp_path).analyze(full=False)

    assert any(flow.name == "handler" for flow in result.model.flows)
    assert [relative for relative, _ in result.skipped_files] == ["broken.py"]


def test_tree_sitter_parse_errors_are_skipped_with_quality_reasons(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    _write(tmp_path / "partial.ts", "export function ok() {\n  return 1;\n}\n@")
    _write(tmp_path / "broken.ts", "export function broken( {\n  return 1;\n")
    _write(tmp_path / "broken.go", "package main\n\n@\n")

    result = ProjectAnalyzer(tmp_path).analyze(full=True)

    assert any(flow.name == "handler" for flow in result.model.flows)
    assert any(flow.name == "ok" for flow in result.model.flows)
    skipped = dict(result.skipped_files)
    assert set(skipped) == {"broken.go", "broken.ts"}
    assert "typescript parse error in broken.ts" in skipped["broken.ts"]
    assert "go parse error in broken.go" in skipped["broken.go"]
    quality = result.model.metadata["quality"]
    assert quality["files"]["skipped"]["total"] == 2
    assert quality["files"]["skipped"]["by_reason"] == {
        skipped["broken.go"]: 1,
        skipped["broken.ts"]: 1,
    }
    assert quality["files"]["parse_errors"]["total"] == 1
    assert quality["files"]["parse_errors"]["sample"][0]["path"] == "partial.ts"
    assert quality["languages"]["depth"]["typescript"]["parse_error_files"] == 1
    ts_attention = next(
        item for item in quality["languages"]["attention"] if item["language"] == "typescript"
    )
    assert "parse_errors" in ts_attention["signals"]


def test_utf8_bom_python_file_parses(tmp_path: Path) -> None:
    # A valid Python file saved as UTF-8-with-BOM must parse, not be skipped/garbled.
    (tmp_path / "bom.py").write_bytes(b"\xef\xbb\xbf" + b"def handler(x):\n    return x\n")
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    assert any(flow.name == "handler" for flow in result.model.flows)
    assert not result.skipped_files


def test_utf8_bom_treesitter_file_parses(tmp_path: Path) -> None:
    # The tree-sitter read path must strip a leading BOM too (Go here).
    (tmp_path / "main.go").write_bytes(
        b"\xef\xbb\xbf" + b"package main\n\nfunc main() {\n\tprintln(1)\n}\n"
    )
    result = ProjectAnalyzer(tmp_path).analyze(full=True)
    assert any(flow.name == "main" for flow in result.model.flows)
    assert not result.skipped_files


def test_read_json_names_the_offending_file(tmp_path: Path) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid JSON in .*broken\.json"):
        read_json(bad)


def test_corrupt_index_forces_a_clean_full_reanalyze(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    analyzer = ProjectAnalyzer(tmp_path)
    analyzer.analyze(full=True)
    # Corrupt the cache index: a half-written or hand-edited index.json must not crash.
    analyzer.index_path.write_text("{ this is not json", encoding="utf-8")

    result = ProjectAnalyzer(tmp_path).analyze(full=False)

    # The run recovered: the corrupt index was discarded and every file re-analyzed clean.
    assert any(flow.name == "handler" for flow in result.model.flows)
    assert result.cache_hits == 0
    assert "good.py" in result.changed_files


def test_index_with_bad_entry_shapes_forces_reanalyze(tmp_path: Path) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    analyzer = ProjectAnalyzer(tmp_path)
    analyzer.analyze(full=True)
    # Valid JSON but a malformed entry (missing the `sha256`/`cache` keys) must not crash.
    analyzer.index_path.write_text(
        '{"cache_version": "2", "files": {"good.py": {"oops": 1}}}', encoding="utf-8"
    )

    result = ProjectAnalyzer(tmp_path).analyze(full=False)

    assert any(flow.name == "handler" for flow in result.model.flows)
    assert result.cache_hits == 0


def test_a_file_that_vanishes_mid_run_does_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    _write(tmp_path / "ghost.py", "def ghost():\n    return 1\n")

    import logicchart.analysis.project as project_module

    real_sha256 = project_module.file_sha256

    def flaky_sha256(path: Path) -> str:
        # Simulate the file being deleted/locked between discovery and hashing: hashing
        # ghost.py raises OSError. This used to abort the WHOLE run from outside the guard.
        if path.name == "ghost.py":
            raise OSError("No such file or directory")
        return real_sha256(path)

    monkeypatch.setattr(project_module, "file_sha256", flaky_sha256)

    result = ProjectAnalyzer(tmp_path).analyze(full=True)

    # The good file still produced its flow; the unreadable one is recorded as skipped.
    assert any(flow.name == "handler" for flow in result.model.flows)
    skipped = {relative for relative, _ in result.skipped_files}
    assert "ghost.py" in skipped
    assert all(reason for _, reason in result.skipped_files)


def test_missing_lazy_language_dependency_does_not_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(tmp_path / "good.py", "def handler(x):\n    return x\n")
    _write(tmp_path / "legacy.cs", "class Legacy { void Handle() {} }\n")

    import logicchart.analysis.project as project_module

    real_spec_for_language = project_module.spec_for_language

    def flaky_spec_for_language(language: str):
        if language == "csharp":
            raise ModuleNotFoundError("No module named 'tree_sitter_c_sharp'")
        return real_spec_for_language(language)

    monkeypatch.setattr(project_module, "spec_for_language", flaky_spec_for_language)

    result = ProjectAnalyzer(tmp_path).analyze(full=True)

    assert any(flow.name == "handler" for flow in result.model.flows)
    assert result.skipped_files == [("legacy.cs", "No module named 'tree_sitter_c_sharp'")]
    recorded = {record.path for record in result.model.files}
    assert {"good.py", "legacy.cs"} <= recorded


@pytest.mark.parametrize(
    "payload",
    [
        {"flows": "notalist", "files": [], "root": ".", "generated_at": "x"},
        {"root": ".", "generated_at": "x"},  # missing schema_version
        {
            "schema_version": "2.0",
            "generated_at": "x",
            "root": ".",
            "files": [{"path": "a", "language": "python", "sha256": "h", "bogus": 1}],
        },
        {
            "schema_version": "2.0",
            "generated_at": "x",
            "root": ".",
            "flows": [
                {
                    "id": "f",
                    "name": "n",
                    "symbol": "s",
                    "language": "python",
                    "framework": "g",
                    "entry_kind": "function",
                    "is_entrypoint": False,
                    "location": "not-a-dict",
                }
            ],
        },
    ],
)
def test_from_dict_rejects_malformed_models_cleanly(payload: dict) -> None:
    with pytest.raises(ValueError, match=r"malformed logic-flow\.json"):
        ProjectModel.from_dict(payload)
