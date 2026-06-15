"""Git sync machinery (§5.4): keep the committed model from drifting.

`hook install` writes managed post-commit / post-checkout hooks that run the
deterministic `update`, and registers a union merge driver for `logic-flow.json`
so teammates do not conflict on it. All deterministic - no LLM, no API key.
"""

from __future__ import annotations

import stat
from pathlib import Path

_MARKER = "# LogicChart auto-sync (managed - remove this block to disable)"
_MANAGED_BLOCK = (
    f"{_MARKER}\n"
    "command -v logicchart >/dev/null 2>&1 && logicchart update --no-html >/dev/null 2>&1 || true\n"
)
_HOOK_NAMES = ("post-commit", "post-checkout")
_ATTR_LINE = "logic-flow.json merge=union"


def install_hooks(root: Path) -> list[Path]:
    hooks_dir = _hooks_dir(root)
    hooks_dir.mkdir(parents=True, exist_ok=True)
    changed: list[Path] = []
    for name in _HOOK_NAMES:
        path = hooks_dir / name
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        if _MARKER in existing:
            continue
        body = existing.rstrip() + "\n\n" if existing.strip() else "#!/bin/sh\n"
        path.write_text(body + _MANAGED_BLOCK, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        changed.append(path)
    attributes = root / ".gitattributes"
    if _ensure_line(attributes, _ATTR_LINE):
        changed.append(attributes)
    return changed


def uninstall_hooks(root: Path) -> list[Path]:
    removed: list[Path] = []
    for name in _HOOK_NAMES:
        path = _hooks_dir(root) / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        if _MARKER not in text:
            continue
        remaining = text.replace(_MANAGED_BLOCK, "").rstrip()
        if remaining and remaining != "#!/bin/sh":
            path.write_text(remaining + "\n", encoding="utf-8")
        else:
            path.unlink()
        removed.append(path)
    # Symmetric with install: also drop the managed merge-driver attribute line.
    attributes = root / ".gitattributes"
    if _remove_line(attributes, _ATTR_LINE):
        removed.append(attributes)
    return removed


def hooks_status(root: Path) -> dict[str, bool]:
    hooks_dir = _hooks_dir(root)
    return {
        name: (hooks_dir / name).exists()
        and _MARKER in (hooks_dir / name).read_text(encoding="utf-8")
        for name in _HOOK_NAMES
    }


def _hooks_dir(root: Path) -> Path:
    git_dir = root / ".git"
    if not git_dir.exists():
        raise RuntimeError("Not a git repository (no .git directory).")
    return git_dir / "hooks"


def _ensure_line(path: Path, line: str) -> bool:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if line in existing.splitlines():
        return False
    prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + line + "\n", encoding="utf-8")
    return True


def _remove_line(path: Path, line: str) -> bool:
    if not path.exists():
        return False
    lines = path.read_text(encoding="utf-8").splitlines()
    if line not in lines:
        return False
    remaining = [item for item in lines if item != line]
    if remaining:
        path.write_text("\n".join(remaining) + "\n", encoding="utf-8")
    else:
        path.unlink()
    return True
