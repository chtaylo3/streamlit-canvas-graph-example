from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from .model import EdgeType, NodeType
from .thumbnails import write_ring_thumbnail

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (snapshot_id VARCHAR PRIMARY KEY, captured_at TIMESTAMPTZ NOT NULL, source VARCHAR NOT NULL, metadata JSON NOT NULL);
CREATE TABLE IF NOT EXISTS nodes (snapshot_id VARCHAR NOT NULL, node_id VARCHAR NOT NULL, node_type VARCHAR NOT NULL, name VARCHAR NOT NULL, ecosystem VARCHAR, version VARCHAR, metadata JSON NOT NULL, PRIMARY KEY (snapshot_id, node_id));
CREATE TABLE IF NOT EXISTS edges (snapshot_id VARCHAR NOT NULL, source_id VARCHAR NOT NULL, target_id VARCHAR NOT NULL, edge_type VARCHAR NOT NULL, is_direct BOOLEAN NOT NULL DEFAULT FALSE, metadata JSON NOT NULL);
CREATE TABLE IF NOT EXISTS ring_metrics (snapshot_id VARCHAR NOT NULL, node_id VARCHAR NOT NULL, dimension VARCHAR NOT NULL, category VARCHAR NOT NULL, count INTEGER NOT NULL, PRIMARY KEY (snapshot_id, node_id, dimension, category));
CREATE TABLE IF NOT EXISTS vulnerabilities (snapshot_id VARCHAR NOT NULL, dependency_id VARCHAR NOT NULL, advisory_id VARCHAR NOT NULL, severity VARCHAR NOT NULL, cvss DOUBLE, summary VARCHAR NOT NULL, affected_range VARCHAR, fixed_version VARCHAR, advisory_url VARCHAR, metadata JSON NOT NULL, PRIMARY KEY (snapshot_id, dependency_id, advisory_id));
CREATE TABLE IF NOT EXISTS package_versions (snapshot_id VARCHAR NOT NULL, dependency_id VARCHAR NOT NULL, resolved_version VARCHAR NOT NULL, latest_version VARCHAR, update_kind VARCHAR, source VARCHAR NOT NULL, PRIMARY KEY (snapshot_id, dependency_id));
CREATE TABLE IF NOT EXISTS ingestion_issues (snapshot_id VARCHAR NOT NULL, repository_id VARCHAR, path VARCHAR, severity VARCHAR NOT NULL, code VARCHAR NOT NULL, message VARCHAR NOT NULL);
"""


def connect(path: Path | str, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(path), read_only=read_only)


def initialize_database(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(SCHEMA_SQL)


def stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, ":".join((kind, *parts))))


def latest_snapshot(connection: duckdb.DuckDBPyConnection) -> str | None:
    row = connection.execute(
        "SELECT snapshot_id FROM snapshots ORDER BY captured_at DESC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def snapshot_rows(connection: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    cursor = connection.execute(
        "SELECT snapshot_id, captured_at, source FROM snapshots ORDER BY captured_at DESC"
    )
    keys = ("snapshot_id", "captured_at", "source")
    return [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]


def export_snapshot_parquet(
    connection: duckdb.DuckDBPyConnection, snapshot_id: str, output: Path
) -> None:
    output.mkdir(parents=True, exist_ok=True)
    safe_snapshot = snapshot_id.replace("'", "''")
    for table in (
        "snapshots",
        "nodes",
        "edges",
        "ring_metrics",
        "vulnerabilities",
        "package_versions",
        "ingestion_issues",
    ):
        destination = (output / f"{table}.parquet").as_posix().replace("'", "''")
        connection.execute(
            f"COPY (SELECT * FROM {table} WHERE snapshot_id = '{safe_snapshot}') TO '{destination}' (FORMAT PARQUET)"
        )


def insert_node(
    connection: duckdb.DuckDBPyConnection,
    snapshot_id: str,
    node_id: str,
    node_type: str,
    name: str,
    ecosystem: str | None = None,
    version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    connection.execute(
        "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            snapshot_id,
            node_id,
            node_type,
            name,
            ecosystem,
            version,
            json.dumps(metadata or {}),
        ],
    )


def create_demo_dataset(root: Path, *, overwrite: bool = False) -> Path:
    """Create two deterministic snapshots and matching UUID thumbnails."""
    root.mkdir(parents=True, exist_ok=True)
    db_path = root / "dependency-explorer.duckdb"
    if db_path.exists() and not overwrite:
        return db_path
    if db_path.exists():
        db_path.unlink()
    assets = root / "thumbnails"
    assets.mkdir(exist_ok=True)
    con = connect(db_path)
    initialize_database(con)
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(days=7)
    account_id = stable_id("account", "demo-security-engineer")
    repositories = [
        ("payments-api", "private", "PyPI", "uv.lock"),
        ("customer-portal", "private", "npm", "package-lock.json"),
        ("operations-console", "public", "NuGet", "packages.lock.json"),
    ]
    packages = {
        "PyPI": [("fastapi", "0.115.0"), ("starlette", "0.40.0"), ("anyio", "4.6.0")],
        "npm": [("react", "18.3.1"), ("vite", "5.4.8"), ("esbuild", "0.24.0")],
        "NuGet": [
            ("Serilog", "4.1.0"),
            ("Dapper", "2.1.35"),
            ("Microsoft.Data.SqlClient", "5.2.2"),
        ],
    }
    for index in range(2):
        captured_at = base_time + timedelta(days=7 * index)
        snapshot_id = stable_id("snapshot", captured_at.isoformat())
        con.execute(
            "INSERT INTO snapshots VALUES (?, ?, ?, ?)",
            [snapshot_id, captured_at, "synthetic", json.dumps({"generator": "v1"})],
        )
        insert_node(
            con,
            snapshot_id,
            account_id,
            NodeType.ACCOUNT,
            "Demo Security Engineer",
            metadata={"account_subtype": "user", "login": "demo-user"},
        )
        all_node_ids = [account_id]
        for repo_name, visibility, ecosystem, manifest_name in repositories:
            repo_id = stable_id("repository", repo_name)
            manifest_id = stable_id("manifest", repo_name, manifest_name)
            insert_node(
                con,
                snapshot_id,
                repo_id,
                NodeType.REPOSITORY,
                repo_name,
                metadata={"visibility": visibility, "default_branch": "main"},
            )
            insert_node(
                con,
                snapshot_id,
                manifest_id,
                NodeType.MANIFEST,
                manifest_name,
                ecosystem,
                metadata={"path": manifest_name, "parser": "demo"},
            )
            con.executemany(
                "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                [
                    [snapshot_id, account_id, repo_id, EdgeType.OWNS, False, "{}"],
                    [snapshot_id, repo_id, manifest_id, EdgeType.CONTAINS, False, "{}"],
                ],
            )
            all_node_ids.extend([repo_id, manifest_id])
            previous_id = manifest_id
            for package_index, (package_name, version) in enumerate(
                packages[ecosystem]
            ):
                dep_id = stable_id(
                    "dependency", ecosystem.lower(), package_name.lower(), version
                )
                insert_node(
                    con,
                    snapshot_id,
                    dep_id,
                    NodeType.DEPENDENCY,
                    package_name,
                    ecosystem,
                    version,
                    {
                        "license": "MIT",
                        "purl": f"pkg:{ecosystem.lower()}/{package_name}@{version}",
                    },
                )
                con.execute(
                    "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        snapshot_id,
                        previous_id,
                        dep_id,
                        EdgeType.DEPENDS_ON,
                        package_index == 0,
                        "{}",
                    ],
                )
                update_kind = ("patch", "minor", "major")[(package_index + index) % 3]
                con.execute(
                    "INSERT INTO package_versions VALUES (?, ?, ?, ?, ?, ?)",
                    [snapshot_id, dep_id, version, version, update_kind, "synthetic"],
                )
                if package_index < 2:
                    severity = ("high", "medium", "low")[(package_index + index) % 3]
                    advisory_id = f"DEMO-{ecosystem.upper()}-{package_index + 1}"
                    con.execute(
                        "INSERT INTO vulnerabilities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            snapshot_id,
                            dep_id,
                            advisory_id,
                            severity,
                            8.1 - package_index,
                            f"Demonstration advisory affecting {package_name}",
                            f"<={version}",
                            None,
                            f"https://osv.dev/vulnerability/{advisory_id}",
                            "{}",
                        ],
                    )
                previous_id = dep_id
                all_node_ids.append(dep_id)
        populate_metrics(con, snapshot_id)
        for node_id in set(all_node_ids):
            write_ring_thumbnail(
                assets / f"{node_id}.png", metric_map(con, snapshot_id, node_id)
            )
        export_snapshot_parquet(con, snapshot_id, root / "parquet" / snapshot_id)
    con.close()
    return db_path


def metric_map(
    connection: duckdb.DuckDBPyConnection, snapshot_id: str, node_id: str
) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for dimension, category, count in connection.execute(
        "SELECT dimension, category, count FROM ring_metrics WHERE snapshot_id = ? AND node_id = ?",
        [snapshot_id, node_id],
    ).fetchall():
        result.setdefault(dimension, {})[category] = count
    return result


def populate_metrics(connection: duckdb.DuckDBPyConnection, snapshot_id: str) -> None:
    node_ids = [
        row[0]
        for row in connection.execute(
            "SELECT node_id FROM nodes WHERE snapshot_id = ?", [snapshot_id]
        ).fetchall()
    ]
    for node_id in node_ids:
        dep_ids = [
            row[0]
            for row in connection.execute(
                """WITH RECURSIVE descendants(id) AS (
                       SELECT ? UNION SELECT e.target_id FROM edges e
                       JOIN descendants d ON e.source_id = d.id
                       WHERE e.snapshot_id = ? AND e.edge_type != 'peer_requires'
                   )
                   SELECT DISTINCT n.node_id FROM descendants d JOIN nodes n
                     ON n.node_id = d.id
                   WHERE n.snapshot_id = ? AND n.node_type = 'dependency'""",
                [node_id, snapshot_id, snapshot_id],
            ).fetchall()
        ]
        placeholders = ",".join("?" for _ in dep_ids) or "NULL"
        direct = connection.execute(
            """SELECT count(DISTINCT target_id) FROM edges
               WHERE snapshot_id = ? AND source_id = ?
                 AND edge_type IN ('depends_on', 'optional_depends_on')""",
            [snapshot_id, node_id],
        ).fetchone()[0]
        peers = connection.execute(
            """SELECT count(DISTINCT target_id) FROM edges
               WHERE snapshot_id = ? AND source_id = ?
                 AND edge_type = 'peer_requires'""",
            [snapshot_id, node_id],
        ).fetchone()[0]
        values: list[tuple[str, str, int]] = [
            ("scope", "direct", direct),
            ("scope", "transitive", max(0, len(dep_ids) - direct)),
            ("scope", "peers", peers),
        ]
        for kind in ("major", "minor", "patch"):
            count = connection.execute(
                f"SELECT count(*) FROM package_versions WHERE snapshot_id = ? AND dependency_id IN ({placeholders}) AND update_kind = ?",
                [snapshot_id, *dep_ids, kind],
            ).fetchone()[0]
            values.append(("updates", kind, count))
        for severity in ("critical", "high", "medium", "low"):
            count = connection.execute(
                f"SELECT count(*) FROM vulnerabilities WHERE snapshot_id = ? AND dependency_id IN ({placeholders}) AND severity = ?",
                [snapshot_id, *dep_ids, severity],
            ).fetchone()[0]
            values.append(("vulnerabilities", severity, count))
        connection.executemany(
            "INSERT INTO ring_metrics VALUES (?, ?, ?, ?, ?)",
            [
                [snapshot_id, node_id, dimension, category, count]
                for dimension, category, count in values
            ],
        )
