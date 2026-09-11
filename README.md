# Streamlit Graph Canvas dependency explorer

A Streamlit application for browsing GitHub accounts, repositories, manifests,
direct dependencies, and transitive dependencies without rendering an entire
software portfolio at once.

The app reads local, snapshot-oriented DuckDB/Parquet data. GitHub access is
isolated in separate command-line tools, so the UI never receives or stores a
GitHub credential.

## Quick start

```bash
uv sync
uv run scg demo
uv run streamlit-canvas-graph
```

This checkout uses the locally built graph-canvas wheel stored in
[`vendor/wheels`](vendor/wheels/README.md). `uv sync` installs that wheel through
the source override in `pyproject.toml`; no separate manual installation is
needed. The contrib renderer package remains pinned to its published version.

The demo command writes two deterministic snapshots, Parquet tables, and UUID
ring thumbnails under the gitignored `data/demo/` directory. The app opens at
`http://localhost:8501` and uses that dataset by default.

To open another compatible database:

```bash
SCG_DATA_DIR=/path/to/data \
SCG_DATABASE=/path/to/data/dependency-explorer.duckdb \
uv run streamlit-canvas-graph
```

The thumbnail directory must be `${SCG_DATA_DIR}/thumbnails`, with files named
`<node_uuid>.png`.

## Configuration and secrets

Configuration is managed by Dynaconf through the typed
`streamlit_canvas_graph.settings.AppConfig` interface. Values are loaded in
this order:

1. Tracked, non-secret defaults from `settings.toml`.
2. Local secrets from `.secrets.toml`.
3. `SCG_*` environment variables, which have the highest priority.

Create a local secrets file from the safe template:

```bash
install -m 600 .secrets.toml.example .secrets.toml
```

Then edit `.secrets.toml`:

```toml
github_read_token = "github_pat_..."
github_provision_token = "github_pat_..."
```

Use a read-only fine-grained PAT for `github_read_token` and a separate,
write-enabled PAT for `github_provision_token`. The real `.secrets.toml` is
ignored by Git; `.secrets.toml.example` contains placeholders only.

Environment variables remain useful for CI and temporary terminal sessions:

```bash
export SCG_GITHUB_READ_TOKEN='github_pat_...'
export SCG_GITHUB_PROVISION_TOKEN='github_pat_...'
export SCG_DATA_DIR='/path/to/data'
export SCG_DATABASE='/path/to/data/dependency-explorer.duckdb'
```

The original `GITHUB_READ_TOKEN` and `GITHUB_PROVISION_TOKEN` names are accepted
as compatibility fallbacks, but new configuration should use the `SCG_` prefix.
Never place a real PAT in `settings.toml`, the repository catalog, or the
example secrets file.

## User experience

- Account → repository → manifest → shared dependency navigation.
- Two ancestor levels and one descendant level around the focus. Selecting a repository shows its manifests; selecting a manifest shows its dependencies.
- Ancestors outside the active breadcrumb trail are dimmed while the active
  lineage and immediate descendant edges remain emphasized.
- A rendered-element canvas budget applied after grouping, separate from the 20,000-element data-loading limit.
- The reusable `streamlit-graph-canvas==0.1.0rc1` component supplies the typed
  graph contract, React Flow canvas, ELK layout, pan/zoom, controls, minimap,
  keyboard navigation, and validated selection state.
- `streamlit-graph-canvas-contrib==0.1.0rc1` supplies explicitly enabled
  outgoing-child-count badges without application-owned JavaScript.
- Node metadata or enlarged ring details in the right panel.
- Snapshot history, global node search, manual refresh, severity cards, and a
  filterable vulnerability table.

The concentric rings use fixed semantics: direct/transitive on the inner ring,
major/minor/patch updates in the middle, and critical/high/medium/low findings
on the outer ring. Segment size represents count.

## Read-only GitHub ingestion

Create a fine-grained PAT with read-only access to repository metadata and
contents, grant it only to the repositories you intend to inspect, and expose
it through the environment:

```bash
export SCG_GITHUB_READ_TOKEN='...'
uv run scg ingest github --output data/github
```

The command discovers the authenticated account at runtime, lists only
non-archived repositories owned by that account, and prompts for a selection.
For a noninteractive but still explicit run:

```bash
uv run scg ingest github \
  --repo authenticated-owner/repository-one \
  --repo authenticated-owner/repository-two \
  --yes
```

Each run writes an immutable snapshot. GitHub SPDX SBOM data is augmented from
npm, PyPI, and NuGet lockfiles, then enriched through batched OSV requests and
ecosystem registry metadata. Unsupported or partial inputs are recorded in the
`ingestion_issues` table instead of being silently discarded.

Tokens are never accepted as CLI arguments and are not written to logs,
DuckDB, Parquet, thumbnails, or Streamlit state.

## Private-data boundary

Snapshots contain GitHub account names, repository names and URLs, manifest
paths, dependency relationships, and vulnerability findings. The entire `data/`
tree is ignored by Git and must never be committed, attached to an issue, or
published as a build artifact. This application does not provide authentication;
serve private-derived datasets only on a trusted local machine or behind an
independently authenticated access layer.

## Optional private test copies

[`config/test-repositories.toml`](config/test-repositories.toml) contains four
dependency-rich public sources for each of npm, PyPI, and NuGet. All twelve are
selected by default. The catalog belongs only to the provisioning tool; the
Streamlit app and ingestion library do not import it.

Public GitHub forks cannot be made private. The provisioner therefore creates
independent private repositories containing only each source's current default
branch. It does not copy issues, pull requests, releases, Actions secrets,
tags, or full history.

Use a separate token authorized to create, push, and delete repositories:

```bash
export SCG_GITHUB_PROVISION_TOKEN='...'
uv run scg provision create
```

The command validates current visibility, license, default-branch SHA,
repository size, and expected manifests before displaying a complete preview.
Nothing is created until confirmation. Override the default set by repeating
`--source owner/repository`.

Every created repository is recorded by immutable GitHub repository ID in
`data/provisioning/repositories.json`. Cleanup is allowlisted to active records
in that local manifest and has a separate destructive confirmation:

```bash
uv run scg provision cleanup
```

Review upstream licenses before provisioning. License and attribution files
from the default branch are retained in each private copy.

## Contributing and security

Pull requests are accepted from approved repository collaborators. Other users
should open an issue to discuss a proposed change. See
[`CONTRIBUTING.md`](CONTRIBUTING.md), [`SECURITY.md`](SECURITY.md), and the
maintainer list in [`.github/MAINTAINERS.md`](.github/MAINTAINERS.md).

This project is licensed under the Apache License 2.0.

## Development

Python checks:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The application consumes the pinned `streamlit-graph-canvas` and
`streamlit-graph-canvas-contrib` wheels from PyPI. Their packaged frontend and
renderer assets mean this example requires no local Node.js build. Update both
pins together because the prerelease renderer contract is versioned as a pair.

## Data model

The normalized contract contains `snapshots`, `nodes`, `edges`,
`ring_metrics`, `vulnerabilities`, `package_versions`, and `ingestion_issues`.
Dependency identity is stable across repositories within a snapshot by
ecosystem, normalized package name, and resolved version. Each snapshot is also
exported as table-oriented Parquet under `parquet/<snapshot_uuid>/`.

Manifest-to-package edges identify declared direct dependencies. Ordinary and
development requirements use `depends_on`; optional requirements use
`optional_depends_on`. npm package-to-package relationships retain each
installation location long enough to apply Node's nearest-`node_modules`
resolution rules before packages are collapsed to stable name/version identity.
`peerDependencies` use the distinct `peer_requires` relationship because they
describe host compatibility rather than package ownership. Edge metadata records
the requested range, relationship kind, optionality, and available source and
target installation locations.

The separate `resolves` edge is a final provenance fallback. It anchors only a
dependency component that remains disconnected after ordinary, optional, and
peer relationships have been processed; it conveys provenance, not
direct-dependency status. Ingestion resolves each repository's
default branch to an immutable commit SHA and stores SHA-256 hashes for parsed
manifest and SBOM content. A snapshot is rolled back if any dependency remains
unreachable from a manifest before metrics and exports are finalized.

## Canvas display

Open **Canvas display** to choose **Always tree**, **Always collection**, or
**Use cutoff** independently for each owning node type. A cutoff of 8 means
that each relationship category with eight or more distinct children becomes a
collection. Smaller categories remain trees. Count markers expand and collapse
collections without a Python round trip.

**Explore dependency groups** opens the manifest with the most outgoing
relationships in the selected snapshot. Focusing a repository loads its manifests; focusing a manifest loads its children.

Manifest and package category counts replace the old total-degree badge.
Account and repository badges count outgoing children in the loaded view and
exclude parent links. A collapsed collection costs one node plus one parent edge.
Expansion counts each displayed member and only the edges actually drawn;
replaced membership edges do not count. Full collection totals are retained, with
shown/total counts and a display notice if expansion cannot fit. The separate
20,000-element data-loading limit reports omissions from collection totals.
`CANVAS_ELEMENT_BUDGET` configures the display limit; `CANVAS_LOADED_ELEMENT_BUDGET`
configures the loaded graph limit.
Peer relationships now use the same component grouping mechanism as dependencies.
Optional peers retain their `peer_requires` relationship and have dotted styling.

Cross-repository browser verification (requires the sibling component checkout
and its Playwright dependencies):

```bash
cd ../streamlit-graph-canvas/tests/e2e
node node_modules/@playwright/test/cli.js test --config playwright.example.config.ts
```

This starts the real app with an isolated synthetic database; it does not modify
your dependency snapshots.

Dependency arrows point from a package to what it requires. Select a manifest in
**Dependency context** to scope the **Direct** badges; choosing a manifest node
also sets that context. A package keeps its badge even when other dependencies
also require it. Selecting a package highlights one shortest chain through each
reachable direct dependency and dims unrelated graph elements. The details panel
lists up to 20 representative indirect chains alongside its direct status. The
rendered-element canvas budget still applies, so only drawn portions are highlighted.
Resolution membership and repository ownership retain their separate styling.

In **Canvas display**, **Show siblings** and **Opacity** apply to the focused
node's type. Each type remembers its own values during the session, including
when navigating up a level and back down to a different node of that type.
Opacity ranges from 10% to 80% (default 20%; higher is more opaque). Siblings are
same-type nodes sharing a visible parent and relationship category; their
children are not expanded. Existing view content takes priority over context
when applying the display budget. Siblings remain clickable.

Developers can hard-code policies per node type, or expose their own controls:

```python
sibling_policies = {
    "repository": (True, 0.2),
    "manifest": (True, 0.5),
    "dependency": (False, 0.2),
}
# Pass these to dependency_canvas along with context_graph and
# context_anchor set to the currently focused node.
```

Unspecified types default to disabled and 20% opacity. The reusable package's
`add_sibling_context` already handles arbitrary node types; policy storage and
UI choices belong to the consuming app.

When navigating between siblings under the same visible parents, peer ordering
and pan/zoom are preserved. Enabling siblings or navigating to a different level
still fits the new view. The layout may adjust spacing for different descendants.
The app uses stable relationship IDs for both focused and context edges.

Hierarchy navigation now animates over 250 ms: the canvas stays mounted while the
next layout is prepared, shared nodes move into place, and entering/leaving nodes
fade with their edges. The focused node provides continuity between layouts.
Pan and zoom animate when a new view needs fitting; sibling navigation preserves
the existing viewport. Rapid navigation interrupts the current transition, and
reduced-motion browser preferences disable animation automatically.

### Search the current view

Open **Find in this view** to search names (comma-separated alternatives), recorded
direct-dependency counts, recorded high findings, recorded critical findings below
a node, or ecosystem. Numeric filters support thresholds and all/any combinations.
Counts are computed from the snapshot graph, including descendants outside the
canvas. Repeated paths are deduplicated by package/advisory; descendant critical
counts exclude the node's own findings. Zero means no findings recorded, not that
the package was scanned or is safe.

Typing highlights matches and dims nonmatches to 25% opacity without reordering.
**Apply search** moves matches first in collections or peer groups containing at
least 100 searched, displayed nodes, subject to dependency layers. **Clear search**
restores normal ordering. Faded sibling context is excluded unless **Include
context nodes** is checked; collapsed collection members are excluded until
expanded. These are developer settings supplied to the reusable package.

The example uses local filtering with callbacks disabled. An app can opt into
**Send filters to app**, but that callback triggers a Streamlit rerun and can repeat
queries, calculations, and rendering. The package documents this cost and shows
it beside the optional submission button; typing never submits search callbacks.

Manifest collections and each manifest child relationship category default to a
cutoff of 12. Labels use the package's fixed-box `LabelPolicy()` default: directory
context on the first line, filename on the second, and middle ellipsis where needed.
Manifest paths come from snapshot metadata, with the basename as a fallback.
The full label appears after hovering over a shortened name for 600 ms; names
that fit do not reveal, and hovering elsewhere on a node does not reveal. Leaving
the name cancels the timer. Developers can configure `reveal_delay_ms` or choose
`reveal_mode="controls"` for the previous hover/focus/pin/copy behavior. These
interactions do not rerun Streamlit.
Developers can set `GraphSchema.label_policy` globally and replace it per type with
`NodeType.label_policy`; see the reusable package README for validated combinations.

The vendored component now reuses layout for label-policy and color changes,
reuses search results during geometry-only transitions, and closes label reveals
when the canvas moves. Group visibility uses an adjacency traversal before the
display budget is applied. These changes belong to the reusable component; the
example receives them through its local wheel pin.
