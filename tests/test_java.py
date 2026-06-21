"""Java support via the profile-driven engine: switch, try/catch, calls (Stage C)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel
from logicchart.query import impact_model

_SVC = """package com.svc;

public class Svc {
  public String handle(Status status) {
    if (status == Status.ACTIVE) {
      return "ok";
    }
    switch (status) {
      case ACTIVE: return "a";
      case SUSPENDED: return "s";
    }
    return persist(status);
  }

  private String persist(Status status) {
    return store(status);
  }

  public void run() {
    try {
      risky();
    } catch (Exception e) {
      log(e);
    } finally {
      cleanup();
    }
  }
}
"""


def _analyze(tmp_path: Path) -> ProjectModel:
    pkg = tmp_path / "com" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "Svc.java").write_text(_SVC, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _flow(model: ProjectModel, name: str):
    return next(f for f in model.flows if f.name == name)


def test_java_methods_and_visibility(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    by_name = {f.name: f for f in model.flows}
    assert {"Svc.handle", "Svc.persist", "Svc.run"} <= set(by_name)
    assert all(f.language == "java" for f in model.flows)
    assert by_name["Svc.handle"].is_entrypoint  # public
    assert not by_name["Svc.persist"].is_entrypoint  # private
    assert by_name["Svc.handle"].symbol == "com.svc:Svc.handle"


def test_java_switch_values_and_missing_branch(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    handle = _flow(model, "handle" if False else "Svc.handle")
    switch = next(
        n for n in handle.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    assert {"ACTIVE", "SUSPENDED"} <= set(switch.metadata["values"])


def test_java_switch_try_finally_case_outcome_returns(tmp_path: Path) -> None:
    pkg = tmp_path / "com" / "svc"
    pkg.mkdir(parents=True)
    (pkg / "Svc.java").write_text(
        """package com.svc;

public class Svc {
  public String handle(Status status) {
    switch (status) {
      case ACTIVE:
        try {
          return "a";
        } finally {
          cleanup();
        }
      case SUSPENDED:
        return "s";
      default:
        return "other";
    }
  }
}
""",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    handle = _flow(model, "Svc.handle")
    switch = next(
        n for n in handle.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    active = next(branch for branch in switch.metadata["branches"] if branch["label"] == "ACTIVE")
    assert active["outcome"] == "returns"


def test_java_same_class_call_resolves(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    handle = _flow(model, "Svc.handle")
    persist = _flow(model, "Svc.persist")
    assert persist.id in handle.calls


def test_java_import_dependencies_drive_changed_file_impact(tmp_path: Path) -> None:
    flags = tmp_path / "com" / "svc" / "flags"
    flags.mkdir(parents=True)
    (flags / "FeatureFlags.java").write_text(
        "package com.svc.flags;\n\n"
        "public class FeatureFlags {\n"
        "  public boolean enabled() { return true; }\n"
        "}\n",
        encoding="utf-8",
    )
    route = tmp_path / "com" / "svc" / "routes"
    route.mkdir(parents=True)
    (route / "Route.java").write_text(
        "package com.svc.routes;\n\n"
        "import com.svc.flags.FeatureFlags;\n\n"
        "public class Route {\n"
        "  public boolean handle() { return new FeatureFlags().enabled(); }\n"
        "}\n",
        encoding="utf-8",
    )

    model = ProjectAnalyzer(tmp_path).analyze(full=True).model
    route_record = next(item for item in model.files if item.path == "com/svc/routes/Route.java")
    assert route_record.dependencies == ["com/svc/flags/FeatureFlags.java"]

    handle = _flow(model, "Route.handle")
    result = impact_model(model, ["com/svc/flags/FeatureFlags.java"])
    assert handle.id in {flow.id for flow in result.directly_impacted}
    assert result.impact_reasons[handle.id] == [
        "depends on changed file `com/svc/flags/FeatureFlags.java`"
    ]


def test_java_try_catch_log_only_swallow(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    run = _flow(model, "Svc.run")
    error_decision = next(
        n for n in run.nodes if n.kind is NodeKind.DECISION and n.metadata.get("domain") == "error"
    )
    labels = {b["label"] for b in error_decision.metadata["branches"]}
    assert {"Success", "Error"} <= labels
