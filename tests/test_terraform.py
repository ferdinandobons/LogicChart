"""Terraform / HCL: resource dependency graph (Stage D)."""

from __future__ import annotations

from pathlib import Path

from logicchart.analysis.project import ProjectAnalyzer
from logicchart.model import NodeKind, ProjectModel

_MAIN = """variable "region" {
  default = "us-east-1"
}

resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
}

resource "aws_subnet" "web" {
  vpc_id     = aws_vpc.main.id
  region     = var.region
  depends_on = [aws_vpc.main]
}

module "db" {
  source = "./db"
  vpc    = aws_vpc.main.id
}

output "vpc_id" {
  value = aws_vpc.main.id
}
"""


def _analyze(tmp_path: Path) -> ProjectModel:
    infra = tmp_path / "infra"
    infra.mkdir()
    (infra / "main.tf").write_text(_MAIN, encoding="utf-8")
    return ProjectAnalyzer(tmp_path).analyze(full=True).model


def _flow(model: ProjectModel, name: str):
    return next(f for f in model.flows if f.name == name)


def test_terraform_blocks_become_flows(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    by_name = {f.name: f for f in model.flows}
    assert {"aws_vpc.main", "aws_subnet.web", "module.db", "output.vpc_id", "var.region"} <= set(
        by_name
    )
    assert all(f.language == "terraform" for f in model.flows)
    # resources and modules are entry points; variables/outputs are not
    assert by_name["aws_vpc.main"].is_entrypoint
    assert by_name["module.db"].is_entrypoint
    assert not by_name["var.region"].is_entrypoint
    assert not by_name["output.vpc_id"].is_entrypoint
    assert model.metadata["scopes"] == {"infra": 5}


def test_terraform_dependency_edges_resolve(tmp_path: Path) -> None:
    model = _analyze(tmp_path)
    vpc = _flow(model, "aws_vpc.main")
    subnet = _flow(model, "aws_subnet.web")
    module = _flow(model, "module.db")
    output = _flow(model, "output.vpc_id")
    # every block that references the vpc links to it
    assert vpc.id in subnet.calls
    assert vpc.id in module.calls
    assert vpc.id in output.calls
    # and the vpc records its dependents
    assert {subnet.id, module.id, output.id} <= set(vpc.called_by)


def test_terraform_dependency_nodes_are_labelled(tmp_path: Path) -> None:
    subnet = _flow(_analyze(tmp_path), "aws_subnet.web")
    deps = {n.label for n in subnet.nodes if n.kind is NodeKind.CALL}
    assert "Depends on aws_vpc.main" in deps
    assert "Depends on var.region" in deps
