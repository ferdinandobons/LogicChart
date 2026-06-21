"""C# and PHP support via the profile-driven engine (Stage C)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel
from logicchart.query import impact_model

_CS = """namespace App {
  public class Svc {
    public int Handle(int status) {
      if (status == 1) { return 0; }
      switch (status) { case 1: return 1; case 2: return 2; }
      try { Risky(); } catch (Exception e) { Log(e); }
      return Persist(status);
    }
    private int Persist(int status) { return Store(status); }
  }
}
"""

_PHP = """<?php
class Svc {
  public function handle($status) {
    if ($status == "a") { return "ok"; }
    switch ($status) { case "a": return 1; case "b": return 2; }
    return $this->persist($status);
  }
  private function persist($status) { return store($status); }
}
"""


def _analyze(tmp_path: Path, name: str, content: str) -> ProjectModel:
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / name).write_text(content, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _flow(model: ProjectModel, name: str):
    return next(f for f in model.flows if f.name == name)


def test_csharp_methods_switch_try_calls(tmp_path: Path) -> None:
    model = _analyze(tmp_path, "Svc.cs", _CS)
    by_name = {f.name: f for f in model.flows}
    assert by_name["Svc.Handle"].language == "csharp"
    assert by_name["Svc.Handle"].is_entrypoint and not by_name["Svc.Persist"].is_entrypoint
    handle = _flow(model, "Svc.Handle")
    switch = next(
        n for n in handle.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    assert {"1", "2"} <= set(switch.metadata["values"])
    # try/catch produces the error boundary decision
    assert any(n.metadata.get("domain") == "error" for n in handle.nodes)
    assert _flow(model, "Svc.Persist").id in handle.calls


def test_else_if_chain_keeps_the_middle_branch(tmp_path: Path) -> None:
    # An `else if` whose alternative IS the nested if must still be walked - the middle
    # branch must not be dropped (regression for _statement_children).
    cs = (
        "class Svc { public int H(Status status) {\n"
        "  if (status == Active) { return 1; }\n"
        "  else if (status == Suspended) { return 2; }\n"
        "  else { return 0; }\n"
        "} }\n"
    )
    java = (
        "class Svc { int h(Status status) {\n"
        "  if (status == Active) { return 1; }\n"
        "  else if (status == Suspended) { return 2; }\n"
        "  else { return 0; }\n"
        "} }\n"
    )
    for name, content in (("Svc.cs", cs), ("Svc.java", java)):
        root = tmp_path / name.split(".")[1]
        root.mkdir()
        model = _analyze(root, name, content)
        flow = model.flows[0]
        labels = {n.label for n in flow.nodes if n.kind is NodeKind.DECISION}
        assert "status == Active" in labels
        assert "status == Suspended" in labels  # the middle branch survives


def test_csharp_using_dependencies_drive_changed_file_impact(tmp_path: Path) -> None:
    flags = tmp_path / "Company" / "App" / "Flags"
    auth = tmp_path / "Company" / "App" / "Auth"
    api = tmp_path / "Company" / "App" / "Api"
    flags.mkdir(parents=True)
    auth.mkdir(parents=True)
    api.mkdir(parents=True)
    (flags / "FeatureFlags.cs").write_text(
        "namespace Company.App.Flags;\n"
        "public class FeatureFlags {\n"
        "  public static bool Enabled() { return true; }\n"
        "}\n",
        encoding="utf-8",
    )
    (auth / "Policy.cs").write_text(
        "namespace Company.App.Auth;\npublic class Policy {\n  public static void Audit() {}\n}\n",
        encoding="utf-8",
    )
    (api / "OrdersController.cs").write_text(
        "using System;\n"
        "using Company.App.Flags;\n"
        "using Flags = Company.App.Flags.FeatureFlags;\n"
        "using static Company.App.Auth.Policy;\n\n"
        "namespace Company.App.Api;\n"
        "public class OrdersController {\n"
        "  [HttpGet]\n"
        "  public string Get() {\n"
        "    Audit();\n"
        '    if (Flags.Enabled()) { return "ok"; }\n'
        '    return "off";\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    model = ProjectAnalyzer(tmp_path).analyze(full=True).model

    route_record = next(
        record for record in model.files if record.path == "Company/App/Api/OrdersController.cs"
    )
    assert route_record.dependencies == [
        "Company/App/Flags/FeatureFlags.cs",
        "Company/App/Auth/Policy.cs",
    ]

    route = next(flow for flow in model.flows if flow.name == "OrdersController.Get")
    impact = impact_model(model, ["Company/App/Flags/FeatureFlags.cs"])

    assert route in impact.directly_impacted
    assert impact.impact_reasons[route.id] == [
        "depends on changed file `Company/App/Flags/FeatureFlags.cs`"
    ]


def test_php_methods_switch_calls(tmp_path: Path) -> None:
    model = _analyze(tmp_path, "Svc.php", _PHP)
    by_name = {f.name: f for f in model.flows}
    assert by_name["Svc.handle"].language == "php"
    assert by_name["Svc.handle"].is_entrypoint and not by_name["Svc.persist"].is_entrypoint
    handle = _flow(model, "Svc.handle")
    switch = next(
        n for n in handle.nodes if n.kind is NodeKind.DECISION and n.label.startswith("Switch")
    )
    assert {'"a"', '"b"'} <= set(switch.metadata["values"])
    assert _flow(model, "Svc.persist").id in handle.calls
