# Local development wheels

The example app uses the published `0.1.0rc2` core and contrib packages from
PyPI. The previous development wheel and source override have been removed.
Run `uv sync --locked` to install the published dependencies.

For future component development, build and verify a wheel in the component
repository, then copy it into a directory named for the first 12 characters of
its SHA-256 digest. Add an explicit `[tool.uv.sources]` override, update the
lockfile, and record the source commit and full digest here. Use a new directory
for each distinct wheel, even if the package version is unchanged. Remove the
override when returning to a published package.
