from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import networkx as nx

PEER_EDGE_TYPE = "peer_requires"


def load_graph(connection: duckdb.DuckDBPyConnection, snapshot_id: str) -> nx.DiGraph:
    graph = nx.DiGraph()
    for row in connection.execute(
        "SELECT node_id, node_type, name, ecosystem, version, metadata FROM nodes "
        "WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchall():
        graph.add_node(
            row[0],
            node_type=row[1],
            name=row[2],
            ecosystem=row[3],
            version=row[4],
            metadata=json.loads(row[5]) if isinstance(row[5], str) else (row[5] or {}),
        )
    for row in connection.execute(
        "SELECT source_id, target_id, edge_type, is_direct, metadata "
        "FROM edges WHERE snapshot_id = ?",
        [snapshot_id],
    ).fetchall():
        source, target, edge_type, is_direct, raw_metadata = row
        metadata = (
            json.loads(raw_metadata)
            if isinstance(raw_metadata, str)
            else (raw_metadata or {})
        )
        if graph.has_edge(source, target):
            edge = graph.edges[source, target]
            edge["relationship_types"].add(edge_type)
            edge["relationship_metadata"].setdefault(edge_type, []).append(metadata)
            edge["is_direct"] = edge["is_direct"] or is_direct
            if edge["edge_type"] == PEER_EDGE_TYPE and edge_type != PEER_EDGE_TYPE:
                edge["edge_type"] = edge_type
            continue
        graph.add_edge(
            source,
            target,
            edge_type=edge_type,
            is_direct=is_direct,
            relationship_types={edge_type},
            relationship_metadata={edge_type: [metadata]},
        )
    return graph


def structural_projection(graph: nx.DiGraph) -> nx.DiGraph:
    """Return the ownership graph used for navigation, excluding peer-only arcs."""
    structural = graph.copy()
    for source, target, data in list(structural.edges(data=True)):
        relationships = set(data.get("relationship_types", {data.get("edge_type")}))
        relationships.discard(PEER_EDGE_TYPE)
        if not relationships:
            structural.remove_edge(source, target)
            continue
        data["relationship_types"] = relationships
        if data.get("edge_type") == PEER_EDGE_TYPE:
            data["edge_type"] = min(relationships)
    return structural


def peer_relationships(graph: nx.DiGraph, node_id: str | None) -> list[dict[str, Any]]:
    """Return installed peer requirements declared by one dependency node."""
    if node_id not in graph or graph.nodes[node_id].get("node_type") != "dependency":
        return []
    relationships: list[dict[str, Any]] = []
    for target in graph.successors(node_id):
        edge = graph.edges[node_id, target]
        edge_types = set(edge.get("relationship_types", {edge.get("edge_type")}))
        if PEER_EDGE_TYPE not in edge_types:
            continue
        records = edge.get("relationship_metadata", {}).get(PEER_EDGE_TYPE, [{}])
        metadata = records[0] if records else {}
        target_data = graph.nodes[target]
        relationships.append(
            {
                "target_id": target,
                "name": target_data.get("name", target),
                "version": target_data.get("version"),
                "requested": metadata.get("requested", ""),
                "optional": bool(metadata.get("optional", False)),
            }
        )
    return sorted(
        relationships,
        key=lambda item: (
            item["optional"],
            str(item["name"]).casefold(),
            str(item["version"] or ""),
        ),
    )


def add_peer_children(
    visible: nx.DiGraph,
    relationship_graph: nx.DiGraph,
    focus_id: str,
    *,
    max_elements: int,
) -> tuple[nx.MultiDiGraph, int]:
    """Deliver real peer edges eagerly; disclosure belongs to the component.

    Parallel edges preserve a package that is both an ordinary dependency and a
    peer requirement. Report omitted peers separately from collapsed members.
    """
    result = nx.MultiDiGraph(visible)
    hidden = 0
    for peer in peer_relationships(relationship_graph, focus_id):
        if focus_id not in result:
            hidden += 1
            continue
        target = str(peer["target_id"])
        cost = 1 + int(target not in result)
        if result.number_of_nodes() + result.number_of_edges() + cost > max_elements:
            hidden += 1
            continue
        if target not in result:
            result.add_node(target, **relationship_graph.nodes[target])
        result.add_edge(
            focus_id,
            target,
            edge_type=PEER_EDGE_TYPE,
            requested=peer["requested"],
            optional=peer["optional"],
        )
    return result, hidden


def bounded_neighborhood(
    graph: nx.DiGraph,
    focus_id: str | None,
    *,
    ancestors: int = 2,
    descendants: int = 1,
    limit: int = 500,
) -> tuple[nx.DiGraph, int]:
    if not graph:
        return graph.copy(), 0
    if not focus_id or focus_id not in graph:
        roots = [node for node, degree in graph.in_degree() if degree == 0]
        visible = set(roots)
        for root in roots:
            visible.update(_bfs_nodes(graph, root, descendants))
    else:
        visible = {focus_id}
        visible.update(_bfs_nodes(graph.reverse(copy=False), focus_id, ancestors))
        visible.update(_bfs_nodes(graph, focus_id, descendants))
    ranked = sorted(
        visible,
        key=lambda node: (
            node != focus_id,
            graph.nodes[node].get("node_type") == "dependency",
            graph.nodes[node].get("name", "").lower(),
        ),
    )
    selected: list[str] = []
    selected_set: set[str] = set()
    edge_count = 0
    for node in ranked:
        added_edges = sum(
            int(graph.has_edge(node, neighbor)) + int(graph.has_edge(neighbor, node))
            for neighbor in selected_set
        ) + int(graph.has_edge(node, node))
        candidate_elements = len(selected) + 1 + edge_count + added_edges
        if candidate_elements > limit:
            continue
        selected.append(node)
        selected_set.add(node)
        edge_count += added_edges
    return graph.subgraph(selected).copy(), max(0, len(visible) - len(selected))


def _bfs_nodes(graph: nx.DiGraph, source: str, depth: int) -> set[str]:
    result: set[str] = set()
    seen = {source}
    frontier = {source}
    for _ in range(depth):
        next_frontier: set[str] = set()
        for node in frontier:
            for neighbor in graph.successors(node):
                if neighbor not in seen:
                    seen.add(neighbor)
                    result.add(neighbor)
                    next_frontier.add(neighbor)
        frontier = next_frontier
        if not frontier:
            break
    return result


def repository_scope(
    graph: nx.DiGraph, node_id: str | None, current_repository: str | None = None
) -> str | None:
    if (
        current_repository in graph
        and graph.nodes[current_repository].get("node_type") == "repository"
        and (
            node_id == current_repository
            or (node_id in graph and nx.has_path(graph, current_repository, node_id))
        )
    ):
        return current_repository
    if node_id in graph and graph.nodes[node_id].get("node_type") == "repository":
        return node_id
    if node_id not in graph:
        return None
    repositories = [
        node
        for node in nx.ancestors(graph, node_id)
        if graph.nodes[node].get("node_type") == "repository"
    ]
    return min(
        repositories,
        key=lambda node: graph.nodes[node].get("name", "").casefold(),
        default=None,
    )


def scoped_explore_paths(
    graph: nx.DiGraph, node_type: str, repository_id: str | None
) -> dict[str, tuple[str, ...]]:
    if node_type in {"account", "repository"}:
        return {
            node: (node,)
            for node, data in graph.nodes(data=True)
            if data.get("node_type") == node_type
        }
    if repository_id not in graph:
        return {}
    paths = nx.single_source_shortest_path(graph, repository_id)
    if node_type == "all":
        return {
            node: tuple(path)
            for node, path in paths.items()
            if graph.nodes[node].get("node_type") != "account"
        }
    return {
        node: tuple(path[1:])
        for node, path in paths.items()
        if graph.nodes[node].get("node_type") == node_type
    }


def breadcrumb_path(
    graph: nx.DiGraph, node_id: str, repository_id: str | None
) -> tuple[str, ...]:
    if node_id not in graph:
        return ()
    if graph.nodes[node_id].get("node_type") == "account":
        return (node_id,)
    repository_id = repository_scope(graph, node_id, repository_id)
    if repository_id is None:
        return (node_id,)
    accounts = [
        node
        for node in graph.predecessors(repository_id)
        if graph.nodes[node].get("node_type") == "account"
    ]
    prefix = [accounts[0]] if accounts else []
    if node_id == repository_id:
        return (*prefix, repository_id)
    try:
        return (*prefix, *nx.shortest_path(graph, repository_id, node_id))
    except nx.NetworkXNoPath:
        return (*prefix, repository_id, node_id)


def emphasized_context_edges(
    graph: nx.DiGraph,
    focus_id: str,
    breadcrumb: tuple[str, ...],
    visible_nodes: set[str],
) -> set[tuple[str, str]]:
    lineage = {
        (source, target)
        for source, target in pairwise(breadcrumb)
        if source in visible_nodes
        and target in visible_nodes
        and graph.has_edge(source, target)
    }
    children = {
        (focus_id, target)
        for target in graph.successors(focus_id)
        if target in visible_nodes
    }
    return lineage | children


def node_metrics(
    connection: duckdb.DuckDBPyConnection, snapshot_id: str, node_id: str
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for dimension, category, count in connection.execute(
        "SELECT dimension, category, count FROM ring_metrics "
        "WHERE snapshot_id = ? AND node_id = ?",
        [snapshot_id, node_id],
    ).fetchall():
        result.setdefault(dimension, {})[category] = count
    return result


def vulnerabilities_for_node(
    connection: duckdb.DuckDBPyConnection, snapshot_id: str, node_id: str
) -> list[dict[str, Any]]:
    cursor = connection.execute(
        """
        WITH RECURSIVE descendants(id) AS (
            SELECT ? UNION SELECT e.target_id FROM edges e
            JOIN descendants d ON e.source_id = d.id
            WHERE e.snapshot_id = ? AND e.edge_type != 'peer_requires'
        )
        SELECT v.advisory_id, n.name AS package, n.version, v.severity, v.cvss,
               v.summary, v.fixed_version, v.advisory_url
        FROM vulnerabilities v JOIN nodes n
          ON n.snapshot_id = v.snapshot_id AND n.node_id = v.dependency_id
        WHERE v.snapshot_id = ? AND v.dependency_id IN (SELECT id FROM descendants)
        ORDER BY CASE v.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                 WHEN 'medium' THEN 2 ELSE 3 END, v.cvss DESC
        """,
        [node_id, snapshot_id, snapshot_id],
    )
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def thumbnail_path(data_root: Path, node_id: str) -> Path:
    return data_root / "thumbnails" / f"{node_id}.png"


def node_search_metrics(
    graph: nx.DiGraph,
    findings: list[tuple[str, str, str]],
) -> dict[str, dict[str, int]]:
    """Recorded metrics, independent of canvas visibility and collection state.

    A finding is a (dependency ID, advisory ID) pair. Critical findings reached
    through multiple paths are counted once. Transitive counts exclude the node's
    own findings, including in cyclic graphs. Zero means none recorded, not proof
    that the package was scanned or is vulnerability-free.
    """
    structural = structural_projection(graph)
    high: dict[str, set[str]] = {}
    critical = sorted(
        {
            (node, advisory)
            for node, advisory, severity in findings
            if severity.casefold() == "critical" and node in graph
        }
    )
    own: dict[str, int] = {}
    for index, (node, _) in enumerate(critical):
        own[node] = own.get(node, 0) | (1 << index)
    for node, advisory, severity in findings:
        if severity.casefold() == "high":
            high.setdefault(node, set()).add(advisory)
    dag = nx.condensation(structural)
    components = dag.graph["mapping"]
    reachable: dict[int, int] = {}
    for component in reversed(list(nx.topological_sort(dag))):
        mask = 0
        for node in dag.nodes[component]["members"]:
            mask |= own.get(node, 0)
        for child in dag.successors(component):
            mask |= reachable[child]
        reachable[component] = mask
    return {
        node: {
            "direct_dependency_count": sum(
                structural.nodes[child].get("node_type") == "dependency"
                and "depends_on"
                in structural.edges[node, child].get(
                    "relationship_types",
                    {structural.edges[node, child].get("edge_type")},
                )
                for child in structural.successors(node)
            ),
            "high_vulnerabilities": len(high.get(node, set())),
            "critical_transitive_vulnerabilities": (
                reachable[components[node]] & ~own.get(node, 0)
            ).bit_count(),
        }
        for node in structural
    }
