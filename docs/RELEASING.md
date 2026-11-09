# Releasing manim8

The three distributions (`manim8`, `manim8-core`, `manim8-bridge`) share one version and are released
together (ADR-037). A release is a git tag on the default branch; publishing wheels to PyPI is optional and can
come later (ADR-043).

1. Decide the version. Set it in `pyproject.toml`, `packages/scianim_core/pyproject.toml`,
   `packages/scianim_bridge/pyproject.toml`, the three `__version__` strings, and the `manim8-core==` pins in
   the control-plane and bridge `pyproject.toml` files. `pytest tests/unit/test_distribution.py` checks that
   they agree.
2. If a contract changed incompatibly, raise its `schema_version`, add the migration to `scianim migrate`, and
   say so in `CHANGELOG.md`. Additive fields need defaults that keep old documents valid.
3. `uv lock`, and `uv lock` in `examples/families/computational_neuroscience/`; commit both lockfiles.
4. Run the full test suite, then both install checks:
   - `.github/scripts/git_install_check.sh` installs manim8 from git (not editable) into an empty environment,
     syncs the example family, whose environment must take the bridge from the same commit, and renders the
     example twice with `--json` (the second a cache hit) and once with `--style`;
   - `.github/scripts/release_install_check.sh` builds the three wheels, installs them into an empty
     environment and renders from the installed command, with the wheel directory standing in for the index.

   CI runs both on every push. The weekly `release-check` workflow runs the wheel check on Linux and macOS; run
   it by hand before a release.
5. Update `CHANGELOG.md`: move the entries under the version's heading, with the date.
6. Tag the commit and push the tag: `git tag -a v<version> -m "manim8 <version>"`, then
   `git push origin v<version>`. That is the release. Installing it:
   - `uv pip install "manim8 @ git+https://github.com/tknapen/manim8@v<version>"` (or `uv tool install ...`);
   - with pip, name the contracts too:
     `pip install "manim8 @ git+https://github.com/tknapen/manim8@v<version>"
     "manim8-core @ git+https://github.com/tknapen/manim8@v<version>#subdirectory=packages/scianim_core"`.

   Either install writes family environments pinned by git to the tag's commit.
7. Optional, later: publish to PyPI. `uv build --wheel -o dist .`, `uv build --wheel -o dist
   packages/scianim_core`, `uv build --wheel -o dist packages/scianim_bridge`, then `uv publish dist/*` with the
   project's index token. Publish `manim8-core` first; the other two pin it. A control plane installed from
   those wheels writes family environments that take the bridge from the index at its own version.

A consumer pins a release by its tag. lecturekit's `manim8` extra, for example, names both requirements with a
`python_version >= '3.12'` marker, so pip and uv resolve them alike.
