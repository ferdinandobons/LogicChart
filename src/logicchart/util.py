from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, cast


def stable_id(*parts: str, length: int = 16) -> str:
    payload = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:length]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return cast(dict[str, Any], json.loads(text))
    except json.JSONDecodeError as error:
        # Name the offending file: a bare "Expecting value: line 1 column 1" gives a
        # caller no way to find which cache/model file is corrupt.
        raise ValueError(f"invalid JSON in {path}: {error}") from error


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def compact_text(value: str, limit: int = 100) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "..."


def metadata_scope_names(metadata: dict[str, Any]) -> list[str]:
    scopes = metadata.get("scope", [])
    if isinstance(scopes, str):
        return [scopes] if scopes else []
    if not isinstance(scopes, (list, tuple, set)):
        return []
    names: list[str] = []
    for scope in scopes:
        if scope is None:
            continue
        name = scope if isinstance(scope, str) else str(scope)
        if name:
            names.append(name)
    return names


def relpath(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
