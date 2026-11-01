# Releasing manim8

The three distributions (`manim8`, `manim8-core`, `manim8-bridge`) share one version and are released
together (ADR-037).

1. Decide the version. Set it in `pyproject.toml`, `packages/scianim_core/pyproject.toml`,
   `packages/scianim_bridge/pyproject.toml`, the three `__version__` strings, and the `manim8-core==` pins in
   the control-plane and bridge `pyproject.toml` files. `pytest tests/unit/test_distribution.py` checks that
   they agree.
2. If a contract changed incompatibly, raise its `schema_version`, add the migration to `scianim migrate`, and
   say so in `CHANGELOG.md`. Additive fields need defaults that keep old documents valid.
3. `uv lock`, and `uv lock` in `examples/families/computational_neuroscience/`; commit both lockfiles.
4. Run the full test suite, then `.github/scripts/release_install_check.sh` (it builds the wheels, installs
   them into an empty environment and renders from the installed command). The weekly `release-check`
   workflow runs the same on Linux and macOS; run it by hand before a release.
5. Update `CHANGELOG.md`, tag the commit `v<version>`.
6. Build and publish: `uv build --wheel -o dist .`, `uv build --wheel -o dist packages/scianim_core`,
   `uv build --wheel -o dist packages/scianim_bridge`, then `uv publish dist/*` with the project's index token.
   Publish `manim8-core` first; the other two pin it.
