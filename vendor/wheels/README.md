# Local graph-canvas wheel

The example app uses the wheel under `c2792548796e/` through
`[tool.uv.sources]` in `pyproject.toml`. Run `uv sync --locked` from the app root.
Use uv for this checkout: pip does not apply the source override.

This wheel was rebuilt on September 11, 2026 from the sibling component checkout
on branch `feat/canvas-display-and-routing`, including its existing development
changes and the display-policy, edge-presentation, grouping, routing, and configurable arrowhead, sibling context, opacity, and stable sibling ordering and animated navigation changes.
It replaces the earlier child-groups wheel copied from `.venv/local-wheels/`.
It is a local development build using version `0.1.0rc1`, not the PyPI artifact
of that version. The contrib renderer remains pinned to the published package.

SHA-256:
`c2792548796e1d3bfd579b3313e851d054e623e3fe11e4b95da7cac48c8676df`

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
