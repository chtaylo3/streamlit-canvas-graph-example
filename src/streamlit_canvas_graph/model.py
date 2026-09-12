from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeType(StrEnum):
    ACCOUNT = "account"
    REPOSITORY = "repository"
    MANIFEST = "manifest"
    DEPENDENCY = "dependency"


class EdgeType(StrEnum):
    OWNS = "owns"
    CONTAINS = "contains"
    DEPENDS_ON = "depends_on"
    OPTIONAL_DEPENDS_ON = "optional_depends_on"
    PEER_REQUIRES = "peer_requires"
    RESOLVES = "resolves"


SEVERITIES = ("critical", "high", "medium", "low")
UPDATE_KINDS = ("major", "minor", "patch")


@dataclass(slots=True)
class GraphNode:
    node_id: str
    node_type: str
    name: str
    ecosystem: str | None = None
    version: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GraphEdge:
    source_id: str
    target_id: str
    edge_type: str
    is_direct: bool = False
