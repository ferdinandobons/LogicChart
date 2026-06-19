from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any, cast

from logicchart.analysis import ProjectAnalyzer
from logicchart.analysis.registry import supported_language_ids
from logicchart.annotations import load_annotations
from logicchart.artifacts import output_paths
from logicchart.config import LogicChartConfig
from logicchart.model import ProjectModel
from logicchart.quality import model_quality
from logicchart.util import read_json


@dataclass(slots=True)
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    artifact: str = ""
    annotations: dict[str, Any] | None = None
    quality: dict[str, Any] | None = None

    def add_error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "ok": self.ok,
            "artifact": self.artifact,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.quality is not None:
            payload["quality"] = self.quality
        if self.annotations is not None:
            payload["annotations"] = self.annotations
        return payload


def validate_logicchart(
    root: Path,
    *,
    config: LogicChartConfig | None = None,
    check_sync: bool = False,
    include_annotations: bool = False,
    include_quality: bool = False,
    quality_thresholds: dict[str, float | int] | None = None,
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
    _validate_finding_rule_contracts(model, report)
    _validate_json_schema(artifact, report)
    annotations = load_annotations(root, model, active_config)
    if include_annotations or annotations.status != "absent":
        report.annotations = annotations.to_dict()
    if annotations.status != "absent" and not annotations.ok:
        for annotation_error in annotations.errors:
            report.add_error(f"annotations: {annotation_error}")
    active_thresholds = quality_thresholds or {}
    if include_quality or active_thresholds:
        report.quality = model.metadata.get("quality") or model_quality(model)
    if active_thresholds and report.quality is not None:
        _validate_quality_thresholds(report, report.quality, active_thresholds)

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


def _validate_finding_rule_contracts(model: ProjectModel, report: ValidationReport) -> None:
    rules = model.metadata.get("finding_rules")
    if rules is None:
        return
    if not isinstance(rules, dict):
        report.add_error("metadata.finding_rules must be an object when present.")
        return
    for finding in model.findings:
        rule = rules.get(finding.kind)
        if not isinstance(rule, dict):
            report.add_error(f"{finding.id}: missing finding rule contract for {finding.kind!r}.")
            continue
        if rule.get("rule_id") != finding.kind:
            report.add_error(
                f"{finding.id}: finding rule contract id {rule.get('rule_id')!r} "
                f"does not match finding kind {finding.kind!r}."
            )
        metadata_fields = rule.get("metadata_fields", [])
        if not isinstance(metadata_fields, list):
            report.add_error(f"{finding.id}: rule metadata_fields must be a list.")
            continue
        invalid_fields = [field for field in metadata_fields if not isinstance(field, str)]
        if invalid_fields:
            report.add_error(f"{finding.id}: rule metadata_fields entries must be strings.")
            continue
        missing = [field for field in metadata_fields if field not in finding.metadata]
        if missing:
            report.add_error(
                f"{finding.id}: finding metadata is missing rule-declared fields: "
                + ", ".join(missing)
            )
        diagnostic = finding.metadata.get("diagnostic")
        if isinstance(diagnostic, dict) and diagnostic.get("rule_id") != finding.kind:
            report.add_error(
                f"{finding.id}: diagnostic rule_id {diagnostic.get('rule_id')!r} "
                f"does not match finding kind {finding.kind!r}."
            )


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


def _validate_quality_thresholds(
    report: ValidationReport, quality: dict[str, Any], thresholds: dict[str, float | int]
) -> None:
    files = quality.get("files", {})
    calls = quality.get("calls", {})
    labels = quality.get("labels", {})
    skipped = files.get("skipped", {}) if isinstance(files, dict) else {}
    parse_errors = files.get("parse_errors", {}) if isinstance(files, dict) else {}
    if "max_skipped_files" in thresholds:
        actual_skipped = int(_number(skipped.get("total"), 0))
        skipped_limit = int(thresholds["max_skipped_files"])
        if actual_skipped > skipped_limit:
            report.add_error(
                f"quality threshold failed: skipped files {actual_skipped} > max {skipped_limit}"
            )
    if "max_parse_warnings" in thresholds:
        actual_parse_warnings = int(_number(parse_errors.get("total"), 0))
        parse_warning_limit = int(thresholds["max_parse_warnings"])
        if actual_parse_warnings > parse_warning_limit:
            report.add_error(
                "quality threshold failed: parse warnings "
                f"{actual_parse_warnings} > max {parse_warning_limit}"
            )
    if "min_call_resolution" in thresholds:
        actual_resolution = _number(calls.get("resolution_rate"), 0.0)
        resolution_limit = float(thresholds["min_call_resolution"])
        if actual_resolution < resolution_limit:
            report.add_error(
                "quality threshold failed: call resolution "
                f"{actual_resolution:.0%} < min {resolution_limit:.0%}"
            )
    if "max_generic_label_ratio" in thresholds:
        actual_generic = _number(labels.get("generic_ratio"), 0.0)
        generic_limit = float(thresholds["max_generic_label_ratio"])
        if actual_generic > generic_limit:
            report.add_error(
                "quality threshold failed: generic label ratio "
                f"{actual_generic:.0%} > max {generic_limit:.0%}"
            )


def _number(value: Any, default: float) -> float:
    return float(value) if isinstance(value, (int, float)) else default


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
