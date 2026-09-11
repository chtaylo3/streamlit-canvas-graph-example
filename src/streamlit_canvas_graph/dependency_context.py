"""Manifest-scoped dependency status and representative dependency chains."""

from __future__ import annotations

import networkx as nx

DEPENDENCY_RELATIONSHIPS = {"depends_on", "optional_depends_on"}


def direct_dependencies(graph: nx.DiGraph, manifest: str | None) -> set[str]:
    if manifest not in graph or graph.nodes[manifest].get("node_type") != "manifest":
        return set()
    return {
        target
        for target in graph.successors(manifest)
        if graph.edges[manifest, target].get("is_direct")
        and graph.edges[manifest, target].get("edge_type") in DEPENDENCY_RELATIONSHIPS
    }


def dependency_chains(
    graph: nx.DiGraph, manifest: str | None, selected: str
) -> list[list[str]]:
    """One shortest chain per direct root, without enumerating cyclic paths."""
    roots = direct_dependencies(graph, manifest)
    if not roots or selected not in graph:
        return []
    dependencies = nx.subgraph_view(
        graph,
        filter_node=lambda n: graph.nodes[n].get("node_type") == "dependency",
        filter_edge=lambda a, b: (
            graph.edges[a, b].get("edge_type") in DEPENDENCY_RELATIONSHIPS
        ),
    )
    if selected not in dependencies:
        return []
    paths = nx.single_target_shortest_path(dependencies, selected)
    return [
        [manifest, *paths[root]]
        for root in sorted(roots, key=lambda n: (graph.nodes[n].get("name", n), n))
        if root in paths
    ]
