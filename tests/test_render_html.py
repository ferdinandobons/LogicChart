"""Viewer-shell smoke tests.

The HTML viewer is assembled from a template plus extracted assets
(``render/assets/styles.css`` and ``render/assets/shell.js``) and a JSON payload
built by :func:`build_payload`. These tests pin the seams so a future split of
the assets cannot silently drop the style block, the data hook, or the canvas.
"""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.render.html import render_html
from logicchart.render.payload import build_payload


def _model(tmp_path: Path):
    (tmp_path / "service.py").write_text(
        "def handle(account):\n    if account.active:\n        return ok()\n    return denied()\n",
        encoding="utf-8",
    )
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def test_render_html_emits_shell(tmp_path: Path) -> None:
    html = render_html(_model(tmp_path), tmp_path)
    # Style block survived the asset extraction.
    assert "<style>" in html
    # The JSON payload hook the shell script reads from is present.
    assert "logicchart-data" in html
    # The main canvas the viewer draws into is wired up.
    assert 'id="canvas"' in html


def test_build_payload_has_flows(tmp_path: Path) -> None:
    payload = build_payload(_model(tmp_path), tmp_path)
    assert isinstance(payload, dict)
    assert payload["flows"]
