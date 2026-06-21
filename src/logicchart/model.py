from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class Evidence(str, Enum):
    VERIFIED = "VERIFIED"
    INFERRED = "INFERRED"
    POTENTIAL_GAP = "POTENTIAL_GAP"


class NodeKind(str, Enum):
    ENTRY = "entry"
    ACTION = "action"
    DECISION = "decision"
    CALL = "call"
    TERMINAL = "terminal"
    ERROR = "error"


@dataclass(slots=True)
class SourceLocation:
    path: str
    start_line: int
    end_line: int


@dataclass(slots=True)
class FlowNode:
    id: str
    kind: NodeKind
    label: str
    location: SourceLocation
    evidence: Evidence = Evidence.VERIFIED
    detail: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FlowEdge:
    id: str
    source: str
    target: str
    label: str = ""
    evidence: Evidence = Evidence.VERIFIED


@dataclass(slots=True)
class Flow:
    id: str
    name: str
    symbol: str
    language: str
    framework: str
    entry_kind: str
    is_entrypoint: bool
    location: SourceLocation
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FileRecord:
    path: str
    language: str
    sha256: str
    flow_ids: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)


@dataclass(slots=True)
class FileAnalysis:
    path: str
    language: str
    sha256: str
    flows: list[Flow] = field(default_factory=list)
    enums: dict[str, list[str]] = field(default_factory=dict)
    constants: dict[str, bool] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileAnalysis:
        return cls(
            path=data["path"],
            language=data["language"],
            sha256=data["sha256"],
            flows=[_flow_from_dict(item) for item in data.get("flows", [])],
            enums=data.get("enums", {}),
            constants=data.get("constants", {}),
            dependencies=data.get("dependencies", []),
        )


@dataclass(slots=True)
class ProjectModel:
    schema_version: str
    generated_at: str
    root: str
    flows: list[Flow] = field(default_factory=list)
    files: list[FileRecord] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls, root: Path) -> ProjectModel:
        return cls(
            schema_version="2.0",
            generated_at=datetime.now(timezone.utc).isoformat(),
            root=str(root.resolve()),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectModel:
        # Loading a committed `logic-flow.json` deserializes untrusted JSON, so a malformed
        # shape must surface as a clean ValueError, not a raw KeyError / TypeError traceback
        # leaking to the CLI or the MCP transport.
        if not isinstance(data, dict):
            raise ValueError("malformed logic-flow.json: expected a JSON object at the top level")
        try:
            flows = [_flow_from_dict(item) for item in data.get("flows", [])]
            files = [FileRecord(**item) for item in data.get("files", [])]
            return cls(
                schema_version=data["schema_version"],
                generated_at=data["generated_at"],
                root=data["root"],
                flows=flows,
                files=files,
                metadata=data.get("metadata", {}),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"malformed logic-flow.json: {error}") from error


def _location_from_dict(data: dict[str, Any]) -> SourceLocation:
    return SourceLocation(**data)


def _node_from_dict(data: dict[str, Any]) -> FlowNode:
    return FlowNode(
        id=data["id"],
        kind=NodeKind(data["kind"]),
        label=data["label"],
        location=_location_from_dict(data["location"]),
        evidence=Evidence(data.get("evidence", Evidence.VERIFIED.value)),
        detail=data.get("detail", ""),
        metadata=data.get("metadata", {}),
    )


def _edge_from_dict(data: dict[str, Any]) -> FlowEdge:
    return FlowEdge(
        id=data["id"],
        source=data["source"],
        target=data["target"],
        label=data.get("label", ""),
        evidence=Evidence(data.get("evidence", Evidence.VERIFIED.value)),
    )


def _flow_from_dict(data: dict[str, Any]) -> Flow:
    return Flow(
        id=data["id"],
        name=data["name"],
        symbol=data["symbol"],
        language=data["language"],
        framework=data.get("framework", "generic"),
        entry_kind=data.get("entry_kind", "function"),
        is_entrypoint=data.get("is_entrypoint", False),
        location=_location_from_dict(data["location"]),
        nodes=[_node_from_dict(item) for item in data.get("nodes", [])],
        edges=[_edge_from_dict(item) for item in data.get("edges", [])],
        calls=data.get("calls", []),
        called_by=data.get("called_by", []),
        tests=data.get("tests", []),
        metadata=data.get("metadata", {}),
    )
