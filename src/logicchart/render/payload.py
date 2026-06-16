from __future__ import annotations

from pathlib import Path
from typing import Any

from logicchart.model import ProjectModel


def build_payload(model: ProjectModel, source_root: Path | None = None) -> dict[str, Any]:
    data = model.to_dict()
    if source_root is not None:
        data["root"] = str(source_root)
    return data
