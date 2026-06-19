from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logicchart.config import LogicChartConfig
from logicchart.model import ProjectModel
from logicchart.util import read_json

ANNOTATIONS_FILENAME = "logic-annotations.json"
ANNOTATIONS_SCHEMA_VERSION = "1.0"
_TEXT_LIMIT = 2000
_LABEL_LIMIT = 120

_FLOW_FIELDS = {"label", "description", "summary"}
_NODE_FIELDS = {"label", "description"}
_FINDING_FIELDS = {"summary", "explanation", "remediation"}
_SCOPE_FIELDS = {"label", "description", "summary"}


@dataclass(slots=True)
class AnnotationLoadResult:
    path: str
    expected_model_hash: str
    status: str = "absent"
    ok: bool = True
    found_model_hash: str | None = None
    annotations: dict[str, Any] | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)
        if self.status == "absent":
            self.status = "invalid"

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "path": self.path,
            "status": self.status,
            "expected_model_hash": self.expected_model_hash,
            "errors": self.errors,
            "warnings": self.warnings,
        }
        if self.found_model_hash is not None:
            payload["found_model_hash"] = self.found_model_hash
        if self.annotations is not None:
            payload["counts"] = {
                bucket: len(self.annotations.get(bucket, {}))
                for bucket in ("flows", "nodes", "findings", "scopes")
            }
        return payload


def annotations_path(root: Path, config: LogicChartConfig | None = None) -> Path:
    active_config = config or LogicChartConfig.load(root)
    project_root = root.resolve()
    output = (project_root / active_config.output_dir).resolve()
    try:
        output.relative_to(project_root)
    except ValueError as error:
        raise ValueError("LogicChart output_dir must stay inside the analyzed project") from error
    return output / ANNOTATIONS_FILENAME


def model_hash(model: ProjectModel) -> str:
    payload = model.to_dict()
    payload.pop("generated_at", None)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_annotations(
    root: Path,
    model: ProjectModel,
    config: LogicChartConfig | None = None,
) -> AnnotationLoadResult:
    path = annotations_path(root, config)
    expected = model_hash(model)
    result = AnnotationLoadResult(path=str(path), expected_model_hash=expected)
    if not path.exists():
        return result

    result.status = "loaded"
    try:
        payload = read_json(path)
    except (OSError, ValueError) as error:
        result.status = "invalid"
        result.add_error(str(error))
        return result

    result.annotations = validate_annotations_payload(payload, model, result)
    if not result.ok and result.status == "loaded":
        result.status = "invalid"
    return result


def validate_annotations_payload(
    payload: dict[str, Any],
    model: ProjectModel,
    result: AnnotationLoadResult,
) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        result.add_error("logic-annotations.json must be a JSON object.")
        return None

    schema_version = payload.get("schema_version")
    if schema_version != ANNOTATIONS_SCHEMA_VERSION:
        result.add_error(
            f"logic-annotations.json schema_version must be {ANNOTATIONS_SCHEMA_VERSION!r}."
        )

    found_hash = payload.get("model_hash")
    if not isinstance(found_hash, str) or not found_hash:
        result.add_error("logic-annotations.json must include a non-empty model_hash.")
    else:
        result.found_model_hash = found_hash
        if found_hash != result.expected_model_hash:
            result.status = "stale"
            result.add_error(
                "logic-annotations.json targets model_hash "
                f"{found_hash}, but current model_hash is {result.expected_model_hash}."
            )

    known_flow_ids = {flow.id for flow in model.flows}
    known_node_ids = {node.id for flow in model.flows for node in flow.nodes}
    known_finding_ids = {finding.id for finding in model.findings}
    known_scopes = set(model.metadata.get("scopes", {}))

    normalized: dict[str, Any] = {
        "schema_version": ANNOTATIONS_SCHEMA_VERSION,
        "model_hash": result.expected_model_hash,
        "flows": _validate_bucket(
            payload,
            "flows",
            _FLOW_FIELDS,
            known_flow_ids,
            result,
        ),
        "nodes": _validate_bucket(
            payload,
            "nodes",
            _NODE_FIELDS,
            known_node_ids,
            result,
        ),
        "findings": _validate_bucket(
            payload,
            "findings",
            _FINDING_FIELDS,
            known_finding_ids,
            result,
        ),
        "scopes": _validate_bucket(
            payload,
            "scopes",
            _SCOPE_FIELDS,
            known_scopes,
            result,
        ),
    }
    generated_by = payload.get("generated_by")
    if generated_by is not None:
        if isinstance(generated_by, dict):
            normalized["generated_by"] = generated_by
        else:
            result.add_error("generated_by must be an object when present.")
    return normalized if result.ok else None


def _validate_bucket(
    payload: dict[str, Any],
    bucket: str,
    allowed_fields: set[str],
    known_ids: set[str],
    result: AnnotationLoadResult,
) -> dict[str, dict[str, str]]:
    raw = payload.get(bucket, {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        result.add_error(f"{bucket} must be an object keyed by stable ids.")
        return {}

    normalized: dict[str, dict[str, str]] = {}
    for target_id, value in raw.items():
        if not isinstance(target_id, str) or not target_id:
            result.add_error(f"{bucket} contains a non-string or empty id.")
            continue
        if target_id not in known_ids:
            result.add_error(f"{bucket}.{target_id} does not match the current model.")
            continue
        if not isinstance(value, dict):
            result.add_error(f"{bucket}.{target_id} must be an object.")
            continue
        normalized_entry: dict[str, str] = {}
        for name, field_value in value.items():
            if name not in allowed_fields:
                result.add_error(f"{bucket}.{target_id}.{name} is not a supported field.")
                continue
            if not isinstance(field_value, str) or not field_value.strip():
                result.add_error(f"{bucket}.{target_id}.{name} must be a non-empty string.")
                continue
            limit = _LABEL_LIMIT if name == "label" else _TEXT_LIMIT
            if len(field_value) > limit:
                result.add_error(
                    f"{bucket}.{target_id}.{name} exceeds the {limit} character limit."
                )
                continue
            normalized_entry[name] = field_value.strip()
        if normalized_entry:
            normalized[target_id] = normalized_entry
    return normalized
