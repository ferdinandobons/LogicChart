from __future__ import annotations

from pathlib import Path

from logicchart.config import LogicChartConfig
from logicchart.model import ProjectModel
from logicchart.render.html import render_html
from logicchart.render.markdown import render_markdown
from logicchart.util import read_json, write_json


def output_paths(root: Path, config: LogicChartConfig | None = None) -> tuple[Path, Path, Path]:
    active_config = config or LogicChartConfig.load(root)
    project_root = root.resolve()
    output = (project_root / active_config.output_dir).resolve()
    try:
        output.relative_to(project_root)
    except ValueError as error:
        raise ValueError("LogicChart output_dir must stay inside the analyzed project") from error
    return (
        output / "logic-flow.json",
        output / "logic-flow.md",
        output / "logic-flow.html",
    )


def write_artifacts(
    root: Path,
    model: ProjectModel,
    *,
    include_html: bool = True,
    include_gaps: bool = False,
    config: LogicChartConfig | None = None,
) -> tuple[Path, Path, Path | None]:
    json_path, markdown_path, html_path = output_paths(root, config)
    write_json(json_path, model.to_dict())
    markdown_path.write_text(render_markdown(model, include_gaps=include_gaps), encoding="utf-8")
    if include_html:
        html_path.write_text(render_html(model, source_root=root.resolve()), encoding="utf-8")
        return json_path, markdown_path, html_path
    return json_path, markdown_path, None


def load_model(root: Path, config: LogicChartConfig | None = None) -> ProjectModel:
    json_path, _, _ = output_paths(root, config)
    if not json_path.exists():
        raise FileNotFoundError(
            f"No LogicChart model found at {json_path}. Run `logicchart analyze` first."
        )
    return ProjectModel.from_dict(read_json(json_path))
