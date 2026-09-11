import networkx as nx

from streamlit_canvas_graph.graph import (
    add_peer_children,
    bounded_neighborhood,
    breadcrumb_path,
    emphasized_context_edges,
    peer_relationships,
    repository_scope,
    scoped_explore_paths,
    structural_projection,
)


def test_bounded_neighborhood_two_up_one_down_and_cycle_safe() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from(
        [
            ("account", "repo"),
            ("repo", "manifest"),
            ("manifest", "direct"),
            ("direct", "transitive"),
            ("transitive", "direct"),
        ]
    )
    for node in graph:
        graph.nodes[node].update(name=node, node_type="dependency")
    visible, hidden = bounded_neighborhood(graph, "direct")
    assert set(visible) == {"repo", "manifest", "direct", "transitive"}
    assert hidden == 0


def test_bounded_neighborhood_reports_truncation() -> None:
    graph = nx.DiGraph()
    graph.add_node("root", name="root", node_type="account")
    for index in range(10):
        graph.add_node(str(index), name=str(index), node_type="repository")
        graph.add_edge("root", str(index))
    visible, hidden = bounded_neighborhood(graph, "root", limit=4)
    assert "root" in visible
    assert visible.number_of_nodes() + visible.number_of_edges() <= 4
    assert len(visible) == 2
    assert hidden == 9


def test_peer_relationships_are_not_part_of_structural_navigation() -> None:
    graph = nx.DiGraph()
    graph.add_node("package", name="package", node_type="dependency")
    graph.add_node("peer", name="react", version="19.1.0", node_type="dependency")
    graph.add_edge(
        "package",
        "peer",
        edge_type="peer_requires",
        relationship_types={"peer_requires"},
        relationship_metadata={
            "peer_requires": [
                {"requested": "^19", "optional": False},
            ]
        },
    )

    structural = structural_projection(graph)

    assert not structural.has_edge("package", "peer")
    assert peer_relationships(graph, "package") == [
        {
            "target_id": "peer",
            "name": "react",
            "version": "19.1.0",
            "requested": "^19",
            "optional": False,
        }
    ]


def test_peer_children_are_eager_and_budget_bounded() -> None:
    relationship_graph = nx.DiGraph()
    relationship_graph.add_node(
        "package", name="package", node_type="dependency", ecosystem="npm"
    )
    for index, optional in enumerate((False, True)):
        target = f"peer-{index}"
        relationship_graph.add_node(
            target,
            name=target,
            version="1.0.0",
            node_type="dependency",
            ecosystem="npm",
        )
        relationship_graph.add_edge(
            "package",
            target,
            edge_type="peer_requires",
            relationship_types={"peer_requires"},
            relationship_metadata={
                "peer_requires": [
                    {"requested": "^1", "optional": optional},
                ]
            },
        )
    visible = structural_projection(relationship_graph).subgraph(["package"]).copy()

    eager, hidden = add_peer_children(
        visible, relationship_graph, "package", max_elements=5
    )
    assert hidden == 0
    assert set(eager) == {"package", "peer-0", "peer-1"}
    assert eager.number_of_nodes() + eager.number_of_edges() == 5
    assert {data["edge_type"] for _, _, data in eager.edges(data=True)} == {
        "peer_requires"
    }
    assert eager.edges["package", "peer-1", 0]["optional"] is True
    limited, hidden = add_peer_children(
        visible, relationship_graph, "package", max_elements=3
    )
    assert hidden == 1
    assert limited.number_of_nodes() + limited.number_of_edges() == 3


def test_peer_children_preserve_parallel_ordinary_relationship() -> None:
    graph = nx.DiGraph()
    graph.add_node("a", node_type="dependency", name="a")
    graph.add_node("b", node_type="dependency", name="b")
    graph.add_edge(
        "a",
        "b",
        edge_type="depends_on",
        relationship_types={"depends_on", "peer_requires"},
    )
    result, hidden = add_peer_children(
        structural_projection(graph), graph, "a", max_elements=10
    )
    assert hidden == 0
    assert {data["edge_type"] for _, _, data in result.edges(data=True)} == {
        "depends_on",
        "peer_requires",
    }


def test_repository_scoped_paths_and_breadcrumbs() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from(
        [
            ("account", "repo-a"),
            ("account", "repo-b"),
            ("repo-a", "manifest-a"),
            ("repo-b", "manifest-b"),
            ("manifest-a", "direct-a"),
            ("direct-a", "shared"),
            ("manifest-b", "direct-b"),
            ("direct-b", "shared"),
        ]
    )
    types = {
        "account": "account",
        "repo-a": "repository",
        "repo-b": "repository",
        "manifest-a": "manifest",
        "manifest-b": "manifest",
        "direct-a": "dependency",
        "direct-b": "dependency",
        "shared": "dependency",
    }
    for node, node_type in types.items():
        graph.nodes[node].update(name=node, node_type=node_type)

    assert repository_scope(graph, "shared", "repo-a") == "repo-a"
    assert scoped_explore_paths(graph, "manifest", "repo-a") == {
        "manifest-a": ("manifest-a",)
    }
    assert scoped_explore_paths(graph, "dependency", "repo-a")["shared"] == (
        "manifest-a",
        "direct-a",
        "shared",
    )
    assert breadcrumb_path(graph, "shared", "repo-a") == (
        "account",
        "repo-a",
        "manifest-a",
        "direct-a",
        "shared",
    )
    assert emphasized_context_edges(
        graph,
        "direct-a",
        ("account", "repo-a", "manifest-a", "direct-a"),
        {"repo-a", "manifest-a", "direct-a", "shared"},
    ) == {
        ("repo-a", "manifest-a"),
        ("manifest-a", "direct-a"),
        ("direct-a", "shared"),
    }


def test_search_metrics_deduplicate_shared_transitive_findings_and_handle_cycles():
    from streamlit_canvas_graph.graph import node_search_metrics

    graph = nx.DiGraph()
    graph.add_nodes_from(
        (node, {"node_type": "dependency"}) for node in ["a", "b", "c", "d", "peer"]
    )
    for source, target in [("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("d", "b")]:
        graph.add_edge(source, target, edge_type="depends_on")
    graph.add_edge("a", "peer", edge_type="peer_requires")
    findings = [
        ("a", "A", "critical"),
        ("b", "B", "critical"),
        ("d", "D", "critical"),
        ("d", "D", "critical"),
        ("peer", "P", "critical"),
        ("a", "H", "high"),
    ]
    metrics = node_search_metrics(graph, findings)
    assert metrics["a"] == {
        "direct_dependency_count": 2,
        "high_vulnerabilities": 1,
        "critical_transitive_vulnerabilities": 2,
    }
    assert metrics["b"]["critical_transitive_vulnerabilities"] == 1
    assert metrics["d"]["critical_transitive_vulnerabilities"] == 1
    assert metrics["c"]["critical_transitive_vulnerabilities"] == 2
    # Metrics refer to the graph, not the subset currently displayed on canvas.
    assert (
        metrics["a"]["critical_transitive_vulnerabilities"]
        == metrics["c"]["critical_transitive_vulnerabilities"]
    )
