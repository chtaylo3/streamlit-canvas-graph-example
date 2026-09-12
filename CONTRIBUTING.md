# Contributing

This project currently accepts pull requests only from approved repository
collaborators. Everyone is welcome to open an issue to report a bug or propose a
change. Please avoid including credentials, private repository names, manifests,
dependency snapshots, or other confidential data.

Approved contributors should create a focused branch and run:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

The canvas frontend and stock renderer are supplied by the exactly pinned
`streamlit-graph-canvas` packages. This example does not maintain or build a
separate Node.js frontend.

All contributions are provided under the Apache License 2.0 and must pass the
required repository checks and maintainer review policy.
