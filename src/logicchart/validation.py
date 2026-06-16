from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, cast

from logicchart.analysis import ProjectAnalyzer
from logicchart.analysis.registry import supported_language_ids
from logicchart.artifacts import output_paths
from logicchart.config import LogicChartConfig
from logicchart.model import ProjectModel
from logicchart.util import read_json


@dataclass(slots=True)
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact: str = ""

    def add_error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "artifact": self.artifact,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def validate_logicchart(
    root: Path,
    *,
    config: LogicChartConfig | None = None,
    check_sync: bool = False,
) -> ValidationReport:
    """Validate the persisted LogicChart artifact and optional source sync.

    The baseline validation is read-only: it loads the JSON model, checks it against the
    bundled JSON Schema when `jsonschema` is installed, and verifies that every language in
    the artifact is registered by the current analyzer. `check_sync` intentionally runs the
    analyzer to compare the current source tree against the committed model.
    """
    active_config = config or LogicChartConfig.load(root)
    json_path, _, _ = output_paths(root, active_config)
    report = ValidationReport(artifact=str(json_path))

    try:
        artifact = read_json(json_path)
    except OSError as error:
        report.add_error(f"Could not read {json_path}: {error}")
        return report
    except ValueError as error:
        report.add_error(f"Malformed JSON in {json_path}: {error}")
        return report

    try:
        model = ProjectModel.from_dict(artifact)
    except ValueError as error:
        report.add_error(str(error))
        return report

    _validate_languages(model, report)
    _validate_json_schema(artifact, report)

    if check_sync:
        try:
            fresh = ProjectAnalyzer(root, active_config).analyze(full=True).model
        except (OSError, ValueError, SyntaxError) as error:
            report.add_error(f"Could not re-analyze sources for sync check: {error}")
        else:
            if _without_generated_at(fresh.to_dict()) != _without_generated_at(model.to_dict()):
                report.add_error(
                    "logic-flow.json is stale; run `logicchart update` and commit the artifacts."
                )

    return report


def schema_language_ids(schema: dict[str, Any]) -> tuple[str, ...]:
    return _schema_language_ids(schema, "flow")


def schema_file_language_ids(schema: dict[str, Any]) -> tuple[str, ...]:
    return _schema_language_ids(schema, "file")


def _schema_language_ids(schema: dict[str, Any], definition: str) -> tuple[str, ...]:
    flow_language = (
        schema.get("$defs", {})
        .get(definition, {})
        .get("properties", {})
        .get("language", {})
        .get("enum", [])
    )
    return tuple(str(item) for item in flow_language)


def _validate_languages(model: ProjectModel, report: ValidationReport) -> None:
    supported = set(supported_language_ids())
    found = {flow.language for flow in model.flows} | {record.language for record in model.files}
    unknown = sorted(found - supported)
    if unknown:
        report.add_error("Artifact uses unregistered language ids: " + ", ".join(unknown))


def _validate_json_schema(artifact: dict[str, Any], report: ValidationReport) -> None:
    try:
        schema = _read_bundled_schema()
    except (OSError, ValueError) as error:
        report.add_error(f"Could not read bundled schema: {error}")
        return

    schema_languages = set(schema_language_ids(schema))
    schema_file_languages = set(schema_file_language_ids(schema))
    supported = set(supported_language_ids())
    if schema_languages != supported or schema_file_languages != supported:
        report.add_error(
            "Schema language enums are out of sync with registry: "
            f"flow={sorted(schema_languages)} file={sorted(schema_file_languages)} "
            f"registry={sorted(supported)}"
        )

    try:
        from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
    except ImportError:
        report.warnings.append("jsonschema is not installed; skipped JSON Schema validation.")
        return

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(artifact), key=lambda item: list(item.path))
    for validation_error in errors:
        location = "/".join(str(part) for part in validation_error.path) or "<root>"
        report.add_error(f"{location}: {validation_error.message}")


def _without_generated_at(payload: dict[str, Any]) -> dict[str, Any]:
    clone = dict(payload)
    clone.pop("generated_at", None)
    return clone


def _read_bundled_schema() -> dict[str, Any]:
    checkout_schema = Path(__file__).parents[2] / "schema" / "logic-flow.schema.json"
    if checkout_schema.exists():
        return read_json(checkout_schema)

    schema_resource = (
        resources.files("logicchart").joinpath("schema").joinpath("logic-flow.schema.json")
    )
    return cast(dict[str, Any], json.loads(schema_resource.read_text(encoding="utf-8")))
