from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from codedebrief.artifacts import output_paths
from codedebrief.config import DEFAULT_OUTPUT_DIR, CodeDebriefConfig

ERROR_EVENT_SCHEMA_VERSION = "codedebrief_error.v1"
ERROR_REPORT_SCHEMA_VERSION = "codedebrief_errors_report.v1"
ERROR_LOG_FILENAME = "codedebrief.errors.jsonl"
_DEFAULT_LIMIT = 8
_SEVERITIES = {"error", "warning", "info"}


def error_log_path(root: Path, config: CodeDebriefConfig | None = None) -> Path:
    project_root = root.resolve()
    try:
        active_config = config or CodeDebriefConfig.load(project_root)
        json_path, _, _ = output_paths(project_root, active_config)
        return json_path.with_name(ERROR_LOG_FILENAME)
    except (OSError, RuntimeError, ValueError, SyntaxError):
        return project_root / DEFAULT_OUTPUT_DIR / ERROR_LOG_FILENAME


def append_error_event(
    root: Path,
    *,
    command: str,
    phase: str,
    code: str,
    message: str,
    severity: str = "error",
    detail: str = "",
    recoverable: bool = True,
    artifact: str = "",
    next_steps: list[str] | None = None,
    context: dict[str, Any] | None = None,
    config: CodeDebriefConfig | None = None,
) -> Path | None:
    try:
        if not root.resolve().exists():
            return None
        path = error_log_path(root, config)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": ERROR_EVENT_SCHEMA_VERSION,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": severity if severity in _SEVERITIES else "error",
            "command": command,
            "phase": phase,
            "code": code,
            "message": message,
            "detail": detail,
            "recoverable": recoverable,
            "project": str(root.resolve()),
            "artifact": artifact,
            "next_steps": next_steps or [],
            "context": context or {},
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return path
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def read_error_events(
    root: Path,
    *,
    config: CodeDebriefConfig | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    path = error_log_path(root, config)
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                events.append(payload)
    except OSError:
        return []
    if limit is not None and limit >= 0:
        return events[-limit:]
    return events


def clear_error_events(root: Path, config: CodeDebriefConfig | None = None) -> Path:
    path = error_log_path(root, config)
    path.unlink(missing_ok=True)
    return path


def error_report(
    root: Path,
    *,
    config: CodeDebriefConfig | None = None,
    limit: int = _DEFAULT_LIMIT,
) -> dict[str, Any]:
    path = error_log_path(root, config)
    events = read_error_events(root, config=config)
    severity_counts = Counter(str(item.get("severity", "error")) for item in events)
    return {
        "schema_version": ERROR_REPORT_SCHEMA_VERSION,
        "project": str(root.resolve()),
        "path": str(path),
        "count": len(events),
        "summary": dict(sorted(severity_counts.items())),
        "events": events[-limit:] if limit >= 0 else events,
    }


def render_error_report(report: dict[str, Any]) -> str:
    lines = [
        "CodeDebrief errors",
        f"Project: {report.get('project', '')}",
        f"File: {report.get('path', '')}",
    ]
    events = report.get("events", [])
    if not report.get("count"):
        lines.append("Status: OK - no saved CodeDebrief errors.")
        return "\n".join(lines)

    summary = report.get("summary", {})
    summary_text = ", ".join(f"{count} {severity}" for severity, count in summary.items())
    lines.append(f"Summary: {summary_text or str(report.get('count')) + ' events'}")
    lines.append("Latest:")
    for event in events:
        severity = str(event.get("severity", "error"))
        command = str(event.get("command", "unknown"))
        code = str(event.get("code", "unknown"))
        message = str(event.get("message", "")).strip()
        timestamp = str(event.get("timestamp", "")).strip()
        heading = f"- [{severity}] {command}/{code}"
        if timestamp:
            heading += f" at {timestamp}"
        lines.append(heading)
        if message:
            lines.append(f"  {message}")
        detail = str(event.get("detail", "")).strip()
        if detail:
            lines.append(f"  Detail: {detail}")
        next_steps = event.get("next_steps", [])
        if isinstance(next_steps, list) and next_steps:
            lines.append(f"  Next: {next_steps[0]}")
    return "\n".join(lines)


def render_error_report_json(report: dict[str, Any]) -> str:
    return json.dumps(report, indent=2)
