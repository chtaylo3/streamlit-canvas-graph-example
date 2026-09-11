from __future__ import annotations

import json
from dataclasses import replace
from functools import lru_cache

import networkx as nx
from streamlit_graph_canvas import (
    BadgeBinding,
    CanvasResult,
    ChildGroup,
    Edge,
    EdgeStyle,
    EdgeType,
    EnabledRenderer,
    FitView,
    GraphData,
    GraphSchema,
    GroupDisplay,
    Node,
    NodeStyle,
    NodeType,
    PaletteTone,
    Region,
    RendererKind,
    RendererRegistry,
    SearchField,
    add_sibling_context,
    enable_renderers,
    graph_canvas,
)

from .badges import DIRECT_BADGE_KIND, DirectBadgeRenderer

_CONTRIB_DISTRIBUTION = "streamlit-graph-canvas-contrib"
_COUNT_CHIP = "streamlit-graph-canvas/contrib/count-chip"
CANVAS_ELEMENT_BUDGET = 500
CANVAS_LOADED_ELEMENT_BUDGET = 20_000
# Below this a group costs more indirection than the sprawl it saves.
_GROUP_THRESHOLD = 8
_MANIFEST_GROUP_THRESHOLD = 12

_COUNT_BADGE = BadgeBinding(
    name="children",
    kind=_COUNT_CHIP,
    region=Region.at(164, 10, 34, 22),
)

DEPENDENCY_SCHEMA = GraphSchema(
    node_types={
        "account": NodeType(
            "account",
            NodeStyle(
                width=210,
                height=96,
                fill="account",
                stroke="account_border",
                text="account_text",
            ),
            badges=(_COUNT_BADGE,),
            child_groups=(
                ChildGroup("owns", label="Repositories", display=GroupDisplay.TREE),
            ),
        ),
        "repository": NodeType(
            "repository",
            NodeStyle(
                width=210,
                height=96,
                fill="repository",
                stroke="repository_border",
            ),
            badges=(_COUNT_BADGE,),
            child_groups=(
                ChildGroup(
                    "contains", label="Manifests", threshold=_MANIFEST_GROUP_THRESHOLD
                ),
            ),
        ),
        "manifest": NodeType(
            "manifest",
            NodeStyle(width=210, height=96, fill="manifest", stroke="manifest_border"),
            # Category markers replace the ambiguous total-degree badge.
            # A lock file names its whole resolution closure, so a manifest can
            # own hundreds of children. Collapsed groups keep the two kinds
            # distinguishable without flattening them into one enormous band.
            child_groups=(
                ChildGroup(
                    "depends_on",
                    label="Direct dependencies",
                    threshold=_MANIFEST_GROUP_THRESHOLD,
                ),
                ChildGroup(
                    "resolves",
                    label="Resolved packages",
                    threshold=_MANIFEST_GROUP_THRESHOLD,
                ),
                ChildGroup(
                    "optional_depends_on",
                    label="Optional dependencies",
                    threshold=_MANIFEST_GROUP_THRESHOLD,
                ),
            ),
        ),
        "dependency": NodeType(
            "dependency",
            NodeStyle(
                width=210,
                height=96,
                fill="dependency",
                stroke="dependency_border",
            ),
            badges=(
                BadgeBinding("direct", DIRECT_BADGE_KIND, Region.at(142, 68, 58, 20)),
            ),
            child_groups=(
                ChildGroup(
                    "depends_on", label="Dependencies", threshold=_GROUP_THRESHOLD
                ),
                ChildGroup(
                    "optional_depends_on",
                    label="Optional dependencies",
                    threshold=_GROUP_THRESHOLD,
                ),
                ChildGroup(
                    "peer_requires",
                    label="Peer requirements",
                    threshold=_GROUP_THRESHOLD,
                ),
            ),
        ),
    },
    edge_types={
        "depends_on": EdgeType("depends_on", style=EdgeStyle(arrow="target")),
        # Without these the renderer folds every unknown relationship into
        # depends_on, so a lock file's resolution closure looks like direct
        # dependencies.
        "resolves": EdgeType(
            "resolves", style=EdgeStyle(stroke="resolved", width=1, dashed=True)
        ),
        "contains": EdgeType(
            "contains", style=EdgeStyle(stroke="structure", width=1.5)
        ),
        "owns": EdgeType("owns", style=EdgeStyle(stroke="structure", width=1.5)),
        "optional_depends_on": EdgeType(
            "optional_depends_on",
            style=EdgeStyle(stroke="optional", width=1, dashed=True, arrow="target"),
        ),
        "peer_requires": EdgeType(
            "peer_requires", style=EdgeStyle(stroke="peer", dashed=True, arrow="target")
        ),
    },
    palette={
        "account": PaletteTone("#0f172a", "#1e293b"),
        "account_border": PaletteTone("#334155", "#64748b"),
        "account_text": PaletteTone("#ffffff"),
        "repository": PaletteTone("#dbeafe", "#1e3a8a"),
        "repository_border": PaletteTone("#2563eb", "#60a5fa"),
        "manifest": PaletteTone("#ede9fe", "#4c1d95"),
        "manifest_border": PaletteTone("#7c3aed", "#a78bfa"),
        "dependency": PaletteTone("#cffafe", "#164e63"),
        "dependency_border": PaletteTone("#0891b2", "#22d3ee"),
        "peer_border": PaletteTone("#9333ea", "#c084fc"),
        "peer_text": PaletteTone("#581c87", "#f3e8ff"),
        "peer": PaletteTone("#9333ea", "#c084fc"),
        "accent": PaletteTone("#2563eb", "#60a5fa"),
        "on_accent": PaletteTone("#ffffff", "#0f172a"),
        "resolved": PaletteTone("#94a3b8", "#64748b"),
        "structure": PaletteTone("#475569", "#94a3b8"),
        "optional": PaletteTone("#a8a29e", "#78716c"),
    },
)


@lru_cache(maxsize=1)
def _renderer_registry() -> RendererRegistry:
    """Enable the explicitly pinned stock renderer distribution."""

    stock = enable_renderers([_CONTRIB_DISTRIBUTION])
    return RendererRegistry(
        {
            **stock.renderers,
            DIRECT_BADGE_KIND: EnabledRenderer(
                RendererKind(DIRECT_BADGE_KIND, None, None, frozenset({"prims"})),
                DirectBadgeRenderer(),
                "streamlit-canvas-graph",
                "0.1.0",
            ),
        }
    )


def _node_data(data: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "ecosystem": data.get("ecosystem"),
        "version": data.get("version"),
    }
    metrics = data.get("search_metrics")
    if isinstance(metrics, dict):
        result.update(metrics)
    metadata = data.get("metadata")
    if isinstance(metadata, dict) and metadata.get("synthetic"):
        result["synthetic"] = True
    if data.get("peer_count") is not None:
        result["peer_count"] = data["peer_count"]
    return result


def dependency_schema(
    policies: dict[str, tuple[GroupDisplay, int]] | None = None,
) -> GraphSchema:
    """Apply each node type's display policy independently to its categories."""
    policies = policies or {}
    return replace(
        DEPENDENCY_SCHEMA,
        node_types={
            name: replace(
                kind,
                child_groups=tuple(
                    replace(
                        group, display=policies[name][0], threshold=policies[name][1]
                    )
                    if name in policies
                    else group
                    for group in kind.child_groups
                ),
            )
            for name, kind in DEPENDENCY_SCHEMA.node_types.items()
        },
    )


def build_canvas_graph(
    graph: nx.DiGraph,
    *,
    dimmed_ids: set[str] | None = None,
    emphasized_edges: set[tuple[str, str]] | None = None,
    direct_ids: set[str] | None = None,
    highlight_paths: bool = False,
) -> GraphData:
    """Translate the explorer graph into the public graph-canvas contract."""

    dimmed = dimmed_ids or set()
    emphasized = emphasized_edges or set()
    nodes = tuple(
        Node(
            id=str(node_id),
            type=str(data["node_type"]),
            label=str(data["name"]),
            data=_node_data(data),
            badges=(
                {"children": len(set(graph.successors(node_id)))}
                if data["node_type"] in {"account", "repository"}
                else {"direct": node_id in (direct_ids or set())}
                if data["node_type"] == "dependency"
                else {}
            ),
            dimmed=node_id in dimmed,
        )
        for node_id, data in graph.nodes(data=True)
    )
    records = (
        graph.edges(keys=True, data=True)
        if graph.is_multigraph()
        else (
            (source, target, 0, data) for source, target, data in graph.edges(data=True)
        )
    )
    edges = tuple(
        Edge(
            id="edge-"
            + json.dumps(
                [str(source), str(target), repr(edge_key), data.get("edge_type")],
                separators=(",", ":"),
            ),
            source=str(source),
            target=str(target),
            type=(
                data.get("edge_type")
                if data.get("edge_type") in DEPENDENCY_SCHEMA.edge_types
                else "depends_on"
            ),
            emphasized=(source, target) in emphasized,
            optional=bool(data.get("optional", False)),
            data={
                "relationship": data.get("edge_type", "depends_on"),
                "requested": data.get("requested"),
                "optional": bool(data.get("optional", False)),
            },
            dimmed=(source, target) not in emphasized
            if highlight_paths
            else source in dimmed or target in dimmed,
        )
        for source, target, edge_key, data in records
    )
    return GraphData(nodes=nodes, edges=edges)


def dependency_canvas(
    graph: nx.DiGraph,
    *,
    dimmed_ids: set[str] | None = None,
    emphasized_edges: set[tuple[str, str]] | None = None,
    direct_ids: set[str] | None = None,
    highlight_paths: bool = False,
    key: str,
    context_graph: nx.DiGraph | None = None,
    context_anchor: str | None = None,
    sibling_policies: dict[str, tuple[bool, float]] | None = None,
    preserve_viewport: bool = False,
    policies: dict[str, tuple[GroupDisplay, int]] | None = None,
) -> CanvasResult:
    """Render a dependency graph through the installed graph-canvas packages."""

    visible = build_canvas_graph(
        graph,
        dimmed_ids=dimmed_ids,
        emphasized_edges=emphasized_edges,
        direct_ids=direct_ids,
        highlight_paths=highlight_paths,
    )
    active_search_ids = tuple(n.id for n in visible.nodes if not n.dimmed)
    enabled = False
    if context_graph is not None and context_anchor in context_graph:
        kind = context_graph.nodes[context_anchor]["node_type"]
        enabled, opacity = (sibling_policies or {}).get(kind, (False, 0.2))
        if enabled:
            parents = set(context_graph.predecessors(context_anchor)) & set(graph)
            candidates = {
                n
                for parent in parents
                for n in context_graph.successors(parent)
                if context_graph.nodes[n]["node_type"] == kind
            }
            available = build_canvas_graph(
                context_graph.subgraph(parents | candidates), direct_ids=direct_ids
            )
            available = GraphData(
                tuple(
                    replace(n, badges={"children": context_graph.out_degree(n.id)})
                    if n.type in {"account", "repository"}
                    else n
                    for n in available.nodes
                ),
                available.edges,
            )
            visible = add_sibling_context(
                visible,
                available,
                context_anchor,
                enabled=True,
                opacity=opacity,
                max_elements=CANVAS_LOADED_ELEMENT_BUDGET,
            )
    return graph_canvas(
        visible,
        dependency_schema(policies),
        key=key,
        fit_view=FitView.INITIAL if preserve_viewport else FitView.TOPOLOGY_CHANGE,
        transition_ms=250,
        navigation_anchor=context_anchor,
        max_elements=CANVAS_ELEMENT_BUDGET,
        max_loaded_elements=CANVAS_LOADED_ELEMENT_BUDGET,
        search_active_ids=active_search_ids,
        search_reorder_threshold=100,
        search_nonmatch_opacity=0.25,
        search_fields=(
            SearchField(
                "direct_dependency_count",
                "Recorded direct dependencies",
                "number",
                description="Recorded immediate dependencies, including hidden nodes.",
            ),
            SearchField(
                "high_vulnerabilities",
                "Recorded high findings",
                "number",
                description="Findings on this node only. Zero means none recorded, not proof of safety.",
            ),
            SearchField(
                "critical_transitive_vulnerabilities",
                "Recorded critical findings below",
                "number",
                description="Unique package/advisory findings below this node, including hidden descendants. Shared paths count once; this node is excluded.",
            ),
            SearchField("ecosystem", "Ecosystem"),
        ),
        renderer_registry=_renderer_registry(),
        height=590,
    )
