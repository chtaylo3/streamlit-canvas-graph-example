import networkx as nx
from streamlit_graph_canvas import serialize_graph

from streamlit_canvas_graph.canvas import (
    DEPENDENCY_SCHEMA,
    _renderer_registry,
    build_canvas_graph,
)
from streamlit_canvas_graph.dependency_context import (
    dependency_chains,
    direct_dependencies,
)


def test_shared_direct_dependency_retains_both_paths_and_manifest_scope():
    graph = nx.DiGraph()
    for node in ("lock", "other"):
        graph.add_node(node, node_type="manifest", name=node)
    for node in ("sqlalchemy", "typing", "resolved", "peer"):
        graph.add_node(node, node_type="dependency", name=node)
    for a, b, kind, direct in [
        ("lock", "sqlalchemy", "depends_on", True),
        ("lock", "typing", "depends_on", True),
        ("lock", "resolved", "resolves", False),
        ("other", "sqlalchemy", "depends_on", True),
        ("sqlalchemy", "typing", "depends_on", False),
        ("typing", "sqlalchemy", "depends_on", False),
        ("resolved", "typing", "depends_on", False),
        ("sqlalchemy", "peer", "peer_requires", False),
    ]:
        graph.add_edge(a, b, edge_type=kind, is_direct=direct)
    assert direct_dependencies(graph, "lock") == {"sqlalchemy", "typing"}
    assert direct_dependencies(graph, "other") == {"sqlalchemy"}
    assert dependency_chains(graph, "lock", "typing") == [
        ["lock", "sqlalchemy", "typing"],
        ["lock", "typing"],
    ]
    assert dependency_chains(graph, "lock", "peer") == []
    assert dependency_chains(graph, None, "typing") == []
    canvas = build_canvas_graph(
        graph,
        direct_ids=direct_dependencies(graph, "lock"),
        emphasized_edges={("lock", "typing")},
        highlight_paths=True,
    )
    assert next(n for n in canvas.nodes if n.id == "typing").badges == {"direct": True}
    assert next(
        e for e in canvas.edges if e.source == "lock" and e.target == "typing"
    ).emphasized
    assert next(e for e in canvas.edges if e.target == "resolved").dimmed
    serialized = serialize_graph(
        DEPENDENCY_SCHEMA, canvas, renderer_registry=_renderer_registry()
    )
    typing = next(
        n for n in serialized.envelope["presentation"]["nodes"] if n["id"] == "typing"
    )
    assert any(
        p.get("text") == "Direct" for b in typing["badges"] for p in b["primitives"]
    )
