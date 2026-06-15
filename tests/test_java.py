"""Java support via the profile-driven engine: switch, try/catch, calls (Stage C)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel

_SVC = """package com.svc;

public class Svc {
  public String handle(Status s) {
    if (s == Status.ACTIVE) {
      return "ok";
    }
    switch (s) {
      case ACTIVE: return "a";
      case SUSPENDED: return "s";
    }
    return persist(s);
  }

  private String persist(Status s) {
    return store(s);
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
    # No default in this switch -> missing_branch
    assert "missing_branch" in {f.kind for f in model.findings if f.flow_id == handle.id}


def test_java_same_class_call_resolves(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    handle = _flow(model, "Svc.handle")
    persist = _flow(model, "Svc.persist")
    assert persist.id in handle.calls


def test_java_try_catch_log_only_swallow(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    run = _flow(model, "Svc.run")
    error_decision = next(
        n for n in run.nodes if n.kind is NodeKind.DECISION and n.metadata.get("domain") == "error"
    )
    labels = {b["label"] for b in error_decision.metadata["branches"]}
    assert {"Success", "Error"} <= labels
    # The catch only logs -> broad_except_swallow
    assert "broad_except_swallow" in {f.kind for f in model.findings if f.flow_id == run.id}
