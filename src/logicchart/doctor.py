from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeDependency:
    package: str
    import_name: str
    purpose: str


@dataclass(frozen=True, slots=True)
class MissingDependency:
    package: str
    import_name: str
    purpose: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    ok: bool
    executable: str
    package_version: str
    package_location: str
    missing_dependencies: list[MissingDependency]
    repair_command: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_dependencies"] = [asdict(item) for item in self.missing_dependencies]
        return payload


RUNTIME_DEPENDENCIES = (
    RuntimeDependency("jsonschema", "jsonschema", "artifact validation"),
    RuntimeDependency("tree-sitter", "tree_sitter", "parser runtime"),
    RuntimeDependency("tree-sitter-typescript", "tree_sitter_typescript", "TypeScript/JavaScript"),
    RuntimeDependency("tree-sitter-c", "tree_sitter_c", "C"),
    RuntimeDependency("tree-sitter-c-sharp", "tree_sitter_c_sharp", "C#"),
    RuntimeDependency("tree-sitter-go", "tree_sitter_go", "Go"),
    RuntimeDependency("tree-sitter-java", "tree_sitter_java", "Java"),
    RuntimeDependency("tree-sitter-php", "tree_sitter_php", "PHP"),
    RuntimeDependency("tree-sitter-cpp", "tree_sitter_cpp", "C++"),
    RuntimeDependency("tree-sitter-ruby", "tree_sitter_ruby", "Ruby"),
    RuntimeDependency("tree-sitter-rust", "tree_sitter_rust", "Rust"),
)


def doctor_report(root: Path) -> DoctorReport:
    missing = [
        MissingDependency(item.package, item.import_name, item.purpose)
        for item in RUNTIME_DEPENDENCIES
        if importlib.util.find_spec(item.import_name) is None
    ]
    return DoctorReport(
        ok=not missing,
        executable=sys.executable,
        package_version=_package_version(),
        package_location=_package_location(),
        missing_dependencies=missing,
        repair_command=_repair_command(root),
    )


def render_doctor(report: DoctorReport) -> str:
    lines = [
        f"LogicChart doctor {'OK' if report.ok else 'FAILED'}",
        f"Python: {report.executable}",
        f"Package: logicchart {report.package_version}",
    ]
    if report.package_location:
        lines.append(f"Location: {report.package_location}")
    if report.missing_dependencies:
        lines.append("")
        lines.append("Missing runtime dependencies:")
        for item in report.missing_dependencies:
            lines.append(f"- {item.package} (import {item.import_name}) for {item.purpose}")
        lines.append("")
        lines.append("Repair this interpreter with:")
        lines.append(f"  {report.repair_command}")
    else:
        lines.append("All runtime parser dependencies are importable.")
    return "\n".join(lines)


def render_doctor_json(report: DoctorReport) -> str:
    return json.dumps(report.to_dict(), indent=2)


def _package_version() -> str:
    try:
        return metadata.version("logicchart")
    except metadata.PackageNotFoundError:
        return "not installed"


def _package_location() -> str:
    try:
        distribution = metadata.distribution("logicchart")
    except metadata.PackageNotFoundError:
        return ""
    direct_url = distribution.read_text("direct_url.json")
    if direct_url:
        try:
            payload = json.loads(direct_url)
        except json.JSONDecodeError:
            return ""
        url = payload.get("url")
        if isinstance(url, str) and url.startswith("file://"):
            return url.removeprefix("file://")
    return ""


def _repair_command(root: Path) -> str:
    project_root = root.resolve()
    if _looks_like_logicchart_checkout(project_root):
        return f"{sys.executable} -m pip install -e {project_root}"
    if _looks_like_logicchart_checkout(Path.cwd()):
        return f"{sys.executable} -m pip install -e {Path.cwd().resolve()}"
    return (
        f"{sys.executable} -m pip install --force-reinstall "
        "git+https://github.com/ferdinandobons/LogicChart.git"
    )


def _looks_like_logicchart_checkout(path: Path) -> bool:
    return (path / "pyproject.toml").exists() and (path / "src" / "logicchart" / "cli.py").exists()
