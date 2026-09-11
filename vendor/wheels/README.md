# Local graph-canvas wheel

The example app uses the wheel under `113e68b6a624/` through
`[tool.uv.sources]` in `pyproject.toml`. Run `uv sync --locked` from the app root.
Use uv for this checkout: pip does not apply the source override.

This wheel was rebuilt on September 11, 2026 from signed component commit
`229aff70c465d37f96e9a751fbdb716b605fe007` on branch
`feat/canvas-display-and-routing` (PR #21), rebased onto main after PR #12.
It includes configurable collections, stable navigation, search, label policies,
the selected design-review improvements, and the measured-node connector fix.
It replaces the previous `af338ecf6b88/` development wheel.
It is a local development build using version `0.1.0rc1`, not the PyPI artifact
of that version. The contrib renderer remains pinned to the published package.

SHA-256:
`113e68b6a624168de3a6ec4bc580f06b32e232d4a1b5e441ad93644108332b62`

The directory uses the first 12 hash characters so each rebuilt artifact has a
new source path even if its package version has not changed. This prevents a
lockfile or environment from silently retaining an earlier local build.

To update:

1. Run the component's frontend artifact generation and checks, then
   `uv build --package streamlit-graph-canvas --out-dir /tmp/canvas-wheels`.
2. Compute the wheel's SHA-256 and copy it to `vendor/wheels/<first-12-hash-characters>/`.
3. Update the source path in `pyproject.toml`, then run `uv lock` and
   `uv sync --locked` in the example app.
4. Update this provenance and checksum and run integration checks. Include the
   wheel, source configuration, and lockfile together when committing.

Keep the wheel in the repository so recreating `.venv` does not lose it.
