import networkx as nx
from streamlit_graph_canvas import GroupDisplay, serialize_graph

from streamlit_canvas_graph.canvas import (
    DEPENDENCY_SCHEMA,
    _renderer_registry,
    build_canvas_graph,
    dependency_schema,
)


def test_build_canvas_graph_preserves_explorer_semantics() -> None:
    graph = nx.DiGraph()
    graph.add_node(
        "repo",
        node_type="repository",
        name="example/repository",
        ecosystem=None,
        version=None,
    )
    graph.add_node(
        "package",
        node_type="dependency",
        name="example-package",
        ecosystem="PyPI",
        version="1.2.3",
    )
    graph.add_edge("repo", "package", edge_type="depends_on")

    canvas = build_canvas_graph(
        graph,
        dimmed_ids={"repo"},
        emphasized_edges={("repo", "package")},
    )

    nodes = {node.id: node for node in canvas.nodes}
    assert nodes["repo"].type == "repository"
    assert nodes["repo"].dimmed is True
    assert nodes["repo"].badges["children"] == 1
    assert nodes["package"].data == {
        "ecosystem": "PyPI",
        "version": "1.2.3",
    }
    assert nodes["package"].dimmed is False
    assert canvas.edges[0].type == "depends_on"
    assert canvas.edges[0].emphasized is True
    assert canvas.edges[0].dimmed is True
    assert canvas.edges[0].data["relationship"] == "depends_on"

    serialized = serialize_graph(
        DEPENDENCY_SCHEMA,
        canvas,
        renderer_registry=_renderer_registry(),
    )
    presentation = serialized.envelope["presentation"]
    serialized_nodes = {node["id"]: node for node in presentation["nodes"]}
    assert serialized_nodes["repo"]["dimmed"] is True
    assert serialized_nodes["package"]["dimmed"] is False
    assert serialized_nodes["repo"]["badges"][0]["primitives"]
    assert presentation["edges"][0]["dimmed"] is True


def test_category_owners_have_no_ambiguous_degree_badge() -> None:
    for name, node_type in DEPENDENCY_SCHEMA.node_types.items():
        if name in {"manifest", "dependency"}:
            assert all(b.name != "children" for b in node_type.badges)
        else:
            assert node_type.badges[0].name == "children"


def test_optional_peer_keeps_relationship_under_emphasis() -> None:
    graph = nx.DiGraph()
    graph.add_node("package", node_type="dependency", name="plugin")
    graph.add_node("peer", node_type="dependency", name="host")
    graph.add_edge("package", "peer", edge_type="peer_requires", optional=True)
    edge = build_canvas_graph(graph, emphasized_edges={("package", "peer")}).edges[0]
    assert edge.type == "peer_requires"
    assert edge.optional and edge.emphasized


def test_real_context_emphasis_preserves_both_manifest_categories() -> None:
    from streamlit_canvas_graph.graph import emphasized_context_edges

    graph = nx.DiGraph()
    graph.add_node("repo", node_type="repository", name="repo")
    graph.add_node("lock", node_type="manifest", name="uv.lock")
    graph.add_edge("repo", "lock", edge_type="contains")
    for relationship, count in (("depends_on", 8), ("resolves", 9)):
        for index in range(count):
            child = f"{relationship}-{index}"
            graph.add_node(child, node_type="dependency", name=child)
            graph.add_edge("lock", child, edge_type=relationship)
    emphasis = emphasized_context_edges(graph, "lock", ["repo", "lock"], set(graph))
    canvas = build_canvas_graph(graph, emphasized_edges=emphasis)
    children = [edge for edge in canvas.edges if edge.source == "lock"]
    assert len(children) == 17 and all(edge.emphasized for edge in children)
    assert {edge.type for edge in children} == {"depends_on", "resolves"}
    assert next(node for node in canvas.nodes if node.id == "lock").badges == {}
    for display in GroupDisplay:
        schema = dependency_schema({"manifest": (display, 8)})
        assert all(
            group.display == display and group.threshold == 8
            for group in schema.node_types["manifest"].child_groups
        )


def test_sibling_policy_uses_focused_type_without_expanding_children(monkeypatch):
    import streamlit_canvas_graph.canvas as module

    graph = nx.DiGraph()
    for node, kind in (
        ("account", "account"),
        ("repo", "repository"),
        ("other-repo", "repository"),
        ("manifest", "manifest"),
        ("sibling", "manifest"),
        ("hidden", "dependency"),
    ):
        graph.add_node(node, node_type=kind, name=node)
    for a, b, kind in (
        ("account", "repo", "owns"),
        ("account", "other-repo", "owns"),
        ("repo", "manifest", "contains"),
        ("repo", "sibling", "contains"),
        ("sibling", "hidden", "depends_on"),
    ):
        graph.add_edge(a, b, edge_type=kind)
    visible = graph.subgraph({"account", "repo", "manifest"})
    monkeypatch.setattr(module, "graph_canvas", lambda data, *args, **kwargs: data)
    result = module.dependency_canvas(
        visible,
        key="test",
        context_graph=graph,
        context_anchor="manifest",
        sibling_policies={"manifest": (True, 0.4), "repository": (False, 0.2)},
    )
    assert {n.id for n in result.nodes} == {"account", "repo", "manifest", "sibling"}
    assert next(n for n in result.nodes if n.id == "sibling").opacity == 0.4


def test_edge_identity_survives_context_changes_and_parallel_relationships():
    graph = nx.MultiDiGraph()
    for node in ("a", "b", "c"):
        graph.add_node(node, node_type="dependency", name=node)
    graph.add_edge("a", "b", edge_type="depends_on")
    graph.add_edge("a", "b", edge_type="peer_requires")
    graph.add_edge("b", "c", edge_type="depends_on")
    full = build_canvas_graph(graph)
    assert len({edge.id for edge in full.edges}) == 3
    reduced = build_canvas_graph(graph.subgraph({"a", "b"}))
    assert {edge.id for edge in reduced.edges} <= {edge.id for edge in full.edges}
