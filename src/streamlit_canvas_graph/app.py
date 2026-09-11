from __future__ import annotations

from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_graph_canvas import GroupDisplay

from streamlit_canvas_graph.canvas import CANVAS_ELEMENT_BUDGET, dependency_canvas
from streamlit_canvas_graph.database import create_demo_dataset, snapshot_rows
from streamlit_canvas_graph.dependency_context import (
    dependency_chains,
    direct_dependencies,
)
from streamlit_canvas_graph.graph import (
    add_peer_children,
    bounded_neighborhood,
    breadcrumb_path,
    emphasized_context_edges,
    load_graph,
    node_metrics,
    peer_relationships,
    repository_scope,
    scoped_explore_paths,
    structural_projection,
    thumbnail_path,
    vulnerabilities_for_node,
)
from streamlit_canvas_graph.settings import get_config
from streamlit_canvas_graph.thumbnails import COLORS

st.set_page_config(page_title="Dependency Explorer", page_icon="◉", layout="wide")

EXPLORE_LABELS = {
    "repository": "Repositories",
    "manifest": "Manifests",
    "dependency": "Dependencies",
    "account": "Accounts",
    "all": "All nodes",
}
NEXT_EXPLORE_TYPE = {
    "account": "repository",
    "repository": "manifest",
    "manifest": "dependency",
    "dependency": "dependency",
}


@st.cache_resource
def open_database(path: str) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(path, read_only=True)


@st.cache_data
def graph_for_snapshot(path: str, snapshot_id: str) -> nx.DiGraph:
    con = duckdb.connect(path, read_only=True)
    try:
        return load_graph(con, snapshot_id)
    finally:
        con.close()


def ring_figure(metrics: dict[str, dict[str, int]]) -> go.Figure:
    figure = go.Figure()
    specs = (("vulnerabilities", 0.35), ("updates", 0.58), ("scope", 0.78))
    for dimension, hole in specs:
        values = metrics.get(dimension, {})
        labels = list(values) or ["none"]
        counts = list(values.values()) or [1]
        figure.add_trace(
            go.Pie(
                labels=labels,
                values=counts,
                hole=hole,
                sort=False,
                marker={"colors": [COLORS.get(label, "#e2e8f0") for label in labels]},
                textinfo="none",
                hovertemplate="%{label}: %{value}<extra></extra>",
                domain={"x": [0, 1], "y": [0, 1]},
            )
        )
    figure.update_layout(
        height=330,
        margin={"l": 10, "r": 10, "t": 10, "b": 10},
        showlegend=True,
        legend={"orientation": "h"},
    )
    return figure


def select_node(
    node_id: str,
    *,
    panel: str = "metadata",
    node_type: str | None = None,
    repository_id: str | None = None,
) -> None:
    st.session_state.focus_id = node_id
    st.session_state.selected_id = node_id
    st.session_state.panel = panel
    if node_type in NEXT_EXPLORE_TYPE:
        st.session_state.pending_explore_type = NEXT_EXPLORE_TYPE[node_type]
    if repository_id is not None:
        st.session_state.current_repository = repository_id


def explore_path_label(
    graph: nx.DiGraph, node_id: str, path: tuple[str, ...], node_type: str
) -> str:
    def label(node: str) -> str:
        data = graph.nodes[node]
        if data["node_type"] == "manifest":
            return data.get("metadata", {}).get("path") or data["name"]
        if data["node_type"] == "dependency" and data.get("version"):
            return f"{data['name']}@{data['version']}"
        return data["name"]

    names = [label(node) for node in path]
    if node_type == "dependency" and len(names) > 4:
        names = [names[0], "…", *names[-2:]]
    if node_type in {"dependency", "all"} and len(names) > 1:
        return "  →  ".join(names)
    return f"{label(node_id)} · {graph.nodes[node_id]['node_type']}"


def render_details(
    connection: duckdb.DuckDBPyConnection,
    snapshot_id: str,
    graph: nx.DiGraph,
    data_root: Path,
    node_id: str,
) -> None:
    data = graph.nodes[node_id]
    st.subheader(data["name"])
    st.caption(f"{data['node_type'].title()} · {data.get('ecosystem') or 'GitHub'}")
    image = thumbnail_path(data_root, node_id)
    if image.exists():
        if st.button("Open ring details", key=f"ring-{node_id}", width="stretch"):
            st.session_state.panel = "ring"
        st.image(str(image), width=105)
    if st.session_state.get("panel") == "ring":
        st.plotly_chart(
            ring_figure(node_metrics(connection, snapshot_id, node_id)),
            config={"displayModeBar": False},
        )
        if st.button("Back to metadata", width="stretch"):
            st.session_state.panel = "metadata"
    else:
        fields: dict[str, Any] = {
            "Node ID": node_id,
            "Type": data["node_type"],
            "Ecosystem": data.get("ecosystem"),
            "Version": data.get("version"),
        }
        fields.update(data.get("metadata", {}))
        for key, value in fields.items():
            if value is not None:
                st.markdown(f"**{key.replace('_', ' ').title()}**  \n{value}")
        peers = peer_relationships(graph, node_id)
        if peers:
            st.markdown("**Peer requirements**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Package": peer["name"],
                            "Requested": peer["requested"] or "unspecified",
                            "Installed": peer["version"] or "unknown",
                            "Optional": "Yes" if peer["optional"] else "No",
                        }
                        for peer in peers
                    ]
                ),
                hide_index=True,
                width="stretch",
            )


@st.fragment
def canvas_panel(
    visible: nx.DiGraph,
    graph: nx.DiGraph,
    *,
    key: str,
    hidden: int,
    dimmed_ids: set[str],
    emphasized_edges: set[tuple[str, str]],
    policies: dict[str, tuple[GroupDisplay, int]],
    current_repository: str | None,
    direct_ids: set[str],
    highlight_paths: bool,
) -> None:
    """Render the canvas in isolation from the rest of the page.

    The canvas reports its viewport to Streamlit, and without a fragment every
    pan and zoom would re-execute the whole script: the DuckDB queries, the
    networkx neighbourhood, the plotly ring, and the vulnerability table. Those
    runs take long enough to trip Streamlit's stale-element styling, which is why
    the page dimmed while panning.

    Inside a fragment, a canvas interaction reruns only this function. A node
    click still needs the whole page, because the details column and the
    vulnerability table both key off the selection, so those paths escalate with
    an app-scoped rerun.
    """

    if hidden:
        st.info(
            f"The 500-element canvas budget omitted {hidden} additional nodes; these "
            "are not part of collapsed collections. Use search to refocus."
        )
    result = dependency_canvas(
        visible,
        dimmed_ids=dimmed_ids,
        emphasized_edges=emphasized_edges,
        key=key,
        policies=policies,
        direct_ids=direct_ids,
        highlight_paths=highlight_paths,
    )
    clicked = result.selected_node_ids[-1] if result.selected_node_ids else None
    if clicked in graph and clicked != st.session_state.get("selected_id"):
        select_node(
            clicked,
            node_type=graph.nodes[clicked]["node_type"],
            repository_id=repository_scope(graph, clicked, current_repository),
        )
        st.rerun(scope="app")
    st.caption(
        "Click a node to refocus; use a category's count marker to expand or collapse it. "
        "Counts describe distinct children loaded in this view, per relationship category. "
        "Account and repository badges count outgoing children, excluding parents. "
        "Dependency arrows point from a package to what it requires. "
        "Direct badges refer to the manifest selected in Dependency context."
    )


def main() -> None:
    config = get_config()
    data_root = config.data_dir
    db_path = config.database
    if not db_path.exists():
        create_demo_dataset(data_root)
    connection = open_database(str(db_path))
    snapshots = snapshot_rows(connection)
    st.title("GitHub Dependency Explorer")
    st.caption(
        "Browse accounts, repositories, manifests, and direct or transitive dependencies without losing context."
    )
    if not snapshots:
        st.warning("This database contains no snapshots.")
        return
    controls = st.columns([2, 1.4, 3, 1])
    labels = {
        row["snapshot_id"]: f"{row['captured_at']:%Y-%m-%d %H:%M} · {row['source']}"
        for row in snapshots
    }
    snapshot_id = controls[0].selectbox(
        "Snapshot", list(labels), format_func=labels.get
    )
    relationship_graph = graph_for_snapshot(str(db_path), snapshot_id)
    graph = structural_projection(relationship_graph)
    focus_id = st.session_state.get("focus_id")
    if focus_id not in graph:
        focus_id = next(
            (node for node in graph if graph.nodes[node]["node_type"] == "account"),
            next(iter(graph)),
        )
        select_node(focus_id, node_type=graph.nodes[focus_id]["node_type"])
    current_repository = repository_scope(
        graph, focus_id, st.session_state.get("current_repository")
    )
    if current_repository is not None:
        st.session_state.current_repository = current_repository
    if pending_type := st.session_state.pop("pending_explore_type", None):
        st.session_state.explore_type = pending_type
    st.session_state.setdefault("explore_type", "repository")
    explore_type = controls[1].selectbox(
        "Explore",
        list(EXPLORE_LABELS),
        format_func=EXPLORE_LABELS.get,
        key="explore_type",
    )
    explore_paths = scoped_explore_paths(graph, explore_type, current_repository)
    search_options = sorted(
        explore_paths,
        key=lambda node: explore_path_label(
            graph, node, explore_paths[node], explore_type
        ).casefold(),
    )
    valid_search_values = {None, *search_options}
    if st.session_state.get("jump_to_node") not in valid_search_values:
        st.session_state.jump_to_node = None

    def jump_to_selected_node() -> None:
        node_id = st.session_state.get("jump_to_node")
        if node_id in graph:
            select_node(
                node_id,
                node_type=graph.nodes[node_id]["node_type"],
                repository_id=repository_scope(
                    graph, node_id, st.session_state.get("current_repository")
                ),
            )

    controls[2].selectbox(
        "Jump to node",
        [None, *search_options],
        format_func=lambda node: (
            f"Search {EXPLORE_LABELS[explore_type].lower()}…"
            if node is None
            else explore_path_label(graph, node, explore_paths[node], explore_type)
        ),
        key="jump_to_node",
        on_change=jump_to_selected_node,
    )
    if controls[3].button("Refresh data", width="stretch"):
        st.cache_data.clear()
        st.cache_resource.clear()
        st.rerun()
    trail = breadcrumb_path(graph, focus_id, current_repository)
    display_trail: list[str | None] = list(trail)
    if len(display_trail) > 6:
        display_trail = [*display_trail[:2], None, *display_trail[-3:]]
    st.caption("Current location")
    crumb_columns = st.columns(len(display_trail))
    for index, (column, node_id) in enumerate(zip(crumb_columns, display_trail)):
        if node_id is None:
            column.markdown(
                "<div style='text-align:center'>…</div>", unsafe_allow_html=True
            )
            continue
        if column.button(
            ("" if index == 0 else "› ") + graph.nodes[node_id]["name"],
            key=f"crumb-{snapshot_id}-{index}-{node_id}",
            width="stretch",
            disabled=node_id == focus_id,
        ):
            select_node(
                node_id,
                node_type=graph.nodes[node_id]["node_type"],
                repository_id=repository_scope(graph, node_id, current_repository),
            )
            st.rerun()
    with st.expander("Canvas display"):
        policies = {}
        labels = {
            "tree": "Always tree",
            "collection": "Always collection",
            "cutoff": "Use cutoff",
        }
        for kind in ("account", "repository", "manifest", "dependency"):
            default = "tree" if kind in {"account", "repository"} else "cutoff"
            columns = st.columns([2, 1])
            mode = columns[0].radio(
                f"{kind.title()} children",
                list(labels),
                format_func=labels.get,
                index=list(labels).index(default),
                key=f"display-{kind}",
                horizontal=True,
            )
            threshold = columns[1].number_input(
                f"{kind.title()} cutoff",
                min_value=1,
                value=8,
                step=1,
                disabled=mode != "cutoff",
                key=f"cutoff-{kind}",
            )
            policies[kind] = (GroupDisplay(mode), int(threshold))
        st.caption(
            "The cutoff applies separately to each relationship category. Grouping starts at the cutoff."
        )
    candidates = [
        node for node in graph if graph.nodes[node]["node_type"] == "manifest"
    ]
    if candidates and st.button("Explore dependency groups"):
        target = max(candidates, key=lambda node: graph.out_degree(node))
        select_node(
            target,
            node_type="manifest",
            repository_id=repository_scope(graph, target, current_repository),
        )
        st.rerun()
    peers = peer_relationships(relationship_graph, focus_id)
    # Reserve capacity for eager peer delivery, leaving room for navigation.
    reserved = min(len(peers) * 2, CANVAS_ELEMENT_BUDGET // 2)
    visible, hidden = bounded_neighborhood(
        graph,
        focus_id,
        descendants=1,
        limit=CANVAS_ELEMENT_BUDGET - reserved,
    )
    visible, hidden_peers = add_peer_children(
        visible,
        relationship_graph,
        focus_id,
        max_elements=CANVAS_ELEMENT_BUDGET,
    )
    if hidden_peers:
        st.info(
            f"{hidden_peers} peer requirements omitted by the canvas budget. All peers remain listed in node details."
        )
    manifests = (
        sorted(
            (
                n
                for n in graph.successors(current_repository)
                if graph.nodes[n]["node_type"] == "manifest"
            ),
            key=lambda n: (
                graph.nodes[n].get("metadata", {}).get("path", graph.nodes[n]["name"]),
                n,
            ),
        )
        if current_repository in graph
        else []
    )
    if st.session_state.get("dependency_context") not in manifests:
        st.session_state.dependency_context = next(
            (n for n in trail if n in manifests), manifests[0] if manifests else None
        )
    if focus_id in manifests and st.session_state.get("context_focus") != focus_id:
        st.session_state.dependency_context = focus_id
    st.session_state.context_focus = focus_id
    manifest_id = st.selectbox(
        "Dependency context",
        manifests,
        format_func=lambda n: (
            graph.nodes[n].get("metadata", {}).get("path", graph.nodes[n]["name"])
        ),
        key="dependency_context",
        disabled=not manifests,
    )
    direct_ids = direct_dependencies(graph, manifest_id)
    chains = dependency_chains(graph, manifest_id, focus_id)
    path_edges = {(a, b) for chain in chains for a, b in pairwise(chain)}
    # The existing canvas budget remains authoritative. Highlight the loaded
    # portions of representative paths, and list complete paths in details.
    highlight_paths = bool(chains)
    dimmed_ancestors = (nx.ancestors(graph, focus_id) & set(visible)) - set(trail)
    emphasized_edges = emphasized_context_edges(graph, focus_id, trail, set(visible))
    if highlight_paths:
        emphasized_edges = path_edges & set(visible.edges)
        dimmed_ancestors = set(visible) - {n for chain in chains for n in chain}
    canvas, details = st.columns([3, 1], gap="large")
    with canvas:
        canvas_panel(
            visible,
            graph,
            key=f"graph-{snapshot_id}",
            hidden=hidden,
            dimmed_ids=dimmed_ancestors,
            emphasized_edges=emphasized_edges,
            policies=policies,
            current_repository=current_repository,
            direct_ids=direct_ids,
            highlight_paths=highlight_paths,
        )
    with details:
        if manifest_id and graph.nodes[focus_id]["node_type"] == "dependency":
            context_name = (
                graph.nodes[manifest_id]
                .get("metadata", {})
                .get("path", graph.nodes[manifest_id]["name"])
            )
            if focus_id in direct_ids:
                st.info(f"Direct dependency of {context_name}.")
            indirect = [chain for chain in chains if len(chain) > 2]
            if indirect:
                st.write(
                    "Also required through other dependencies."
                    if focus_id in direct_ids
                    else f"Transitive dependency of {context_name}."
                )
                st.caption(
                    "One shortest chain per direct dependency; the canvas highlights loaded portions. Arrows mean ‘depends on’."
                )
                for chain in indirect[:20]:
                    st.text(" → ".join(graph.nodes[n]["name"] for n in chain))
                if len(indirect) > 20:
                    st.caption(
                        f"{len(indirect) - 20} more chains omitted from this list."
                    )
            elif focus_id not in direct_ids:
                st.caption(
                    f"No dependency chain recorded from direct dependencies of {context_name}."
                )
        render_details(
            connection,
            snapshot_id,
            relationship_graph,
            data_root,
            st.session_state.selected_id,
        )
    st.divider()
    st.subheader("Vulnerability posture")
    findings = vulnerabilities_for_node(
        connection, snapshot_id, st.session_state.selected_id
    )
    counts = {
        severity: sum(row["severity"] == severity for row in findings)
        for severity in ("critical", "high", "medium", "low")
    }
    cards = st.columns(4)
    for card, severity in zip(cards, counts, strict=True):
        card.metric(severity.title(), counts[severity])
    if findings:
        severities = st.multiselect("Severity", list(counts), default=list(counts))
        frame = pd.DataFrame([row for row in findings if row["severity"] in severities])
        st.dataframe(
            frame,
            hide_index=True,
            column_config={"advisory_url": st.column_config.LinkColumn("Advisory")},
        )
    else:
        st.success(
            "No vulnerabilities are associated with this node in the selected snapshot."
        )


main()
