"""Run the real app against isolated data for cross-repository browser tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from streamlit_canvas_graph.database import (
    connect,
    create_demo_dataset,
    insert_node,
    stable_id,
)
from streamlit_canvas_graph.model import NodeType


def main() -> None:
    with TemporaryDirectory(prefix="scg-browser-") as directory:
        root = Path(directory)
        database = create_demo_dataset(root)
        con = connect(database)
        for (snapshot,) in con.execute("SELECT snapshot_id FROM snapshots").fetchall():
            manifest = con.execute(
                "SELECT node_id FROM nodes WHERE snapshot_id = ? AND name = 'uv.lock'",
                [snapshot],
            ).fetchone()[0]
            # Keep the navigation lineage, but replace this manifest's children.
            con.execute(
                "DELETE FROM edges WHERE snapshot_id = ? AND source_id = ?",
                [snapshot, manifest],
            )
            for category, count in (("depends_on", 8), ("resolves", 9)):
                ids = []
                for index in range(count):
                    name = f"{category}-{index}"
                    node_id = stable_id("browser", name)
                    ids.append(node_id)
                    insert_node(
                        con, snapshot, node_id, NodeType.DEPENDENCY, name, "PyPI"
                    )
                    con.execute(
                        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                        [
                            snapshot,
                            manifest,
                            node_id,
                            category,
                            category == "depends_on",
                            "{}",
                        ],
                    )
                # A connected collection with a cycle exercises the routed paths.
                for source, target in zip(ids, ids[1:] + ids[:1]):
                    con.execute(
                        "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                        [snapshot, source, target, "depends_on", False, "{}"],
                    )
            peer_owner = stable_id("browser", "depends_on-0")
            peer_target = stable_id("browser", "peer-host")
            insert_node(
                con, snapshot, peer_target, NodeType.DEPENDENCY, "peer-host", "npm"
            )
            for target, optional in (
                (stable_id("browser", "depends_on-1"), True),
                (peer_target, False),
            ):
                con.execute(
                    "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        snapshot,
                        peer_owner,
                        target,
                        "peer_requires",
                        False,
                        '{"requested":"^1", "optional":' + str(optional).lower() + "}",
                    ],
                )
        con.close()
        env = dict(os.environ, SCG_DATA_DIR=str(root), SCG_DATABASE=str(database))
        app = Path(__file__).parents[2] / "src/streamlit_canvas_graph/app.py"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(app),
                "--server.headless=true",
                "--server.port=8515",
                "--browser.gatherUsageStats=false",
            ],
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
