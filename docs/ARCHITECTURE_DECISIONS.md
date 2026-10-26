# Architecture decision records

Short records of decisions that shape public contracts. Add a record when a contract changes; do not edit history, supersede it.

## ADR-001: Three distributions in one uv workspace

**Status:** accepted, 26 October 2026

**Decision.** The repository publishes `scianim-core` (Pydantic contracts only), `scianim` (control plane: CLI, validation, style resolution, families, jobs, later the API) and `scianim-bridge` (render side: style access, components, `SnapshotScene`, `checkpoint()`, layout report, worker). Family environments depend on `scianim-bridge`; the control plane depends on `scianim-core`; nothing in a family depends on `scianim`.

**Why.** The spec requires that the control plane never import Manim and that families not inherit control-plane dependencies. A single package cannot satisfy both. A separate contracts package avoids duplicating the job and manifest models on both sides of the process boundary.

**Consequences.** Three `pyproject.toml` files; the bridge pins `manim` and `pydantic`; JSON is the only thing that crosses the boundary.

## ADR-002: Checkpoints are markers in the animation flow

**Status:** accepted, 26 October 2026

**Decision.** Generated scene code calls `checkpoint(scene, id, expected_time)` at named moments inside `construct()`. In snapshot mode the worker runs the scene in Manim's fast-forward mode (the mechanism behind `-s`), and the helper captures the frame with `renderer.update_frame` and `renderer.get_frame()`. There is no separate `build_snapshot` constructor.

**Why.** Manim 0.22 collapses each `play()` to a single time step when skipping (`Scene.get_time_progression`), so a full scene is traversed cheaply with correct end states for tracker-driven content. A parallel constructor duplicates placement logic and drifts from the video.

**Consequences.** Checkpoints are evidence about the video. Time-based updaters are not reproduced faithfully in fast-forward; the bridge flags them (`fidelity: approximate`) and such checkpoints are confirmed from sampled video frames. Components never use `dt`-integrating updaters.

## ADR-003: The component registry is the storyboard contract

**Status:** accepted, 26 October 2026

**Decision.** Storyboard objects are instances of registered kinds with typed `params` validated by Pydantic models in `scianim-core`. `scianim codegen` produces the scene module deterministically from registered kinds. `kind: custom` names a builder function in the project's `code/` directory; YAML never contains executable code.

**Why.** The object vocabulary is the interface the agent writes, the validator checks and the renderer builds. Leaving it undefined makes every animation bespoke code and every cache key coarse.

**Consequences.** Adding a kind means a parameter model, a bridge implementation and a registry version bump. Component versions enter cache keys.

## ADR-004: Typst is the default equation engine

**Status:** accepted, 26 October 2026

**Decision.** `typography.equation.engine` defaults to `typst`, rendered through Manim's `MathTypst` with the `typst` PyPI extra pinned in the family lock. `latex` is a per-family opt-in that declares `latex` and `dvisvgm` in `system_requirements`.

**Why.** A TeX distribution is the heaviest unpinnable dependency in the stack. Typst installs from PyPI and therefore inside `uv.lock`.

**Consequences.** Equations carry a `typst` source (and optionally `latex`). Clean-machine verification of the Typst path is part of Milestone 2's acceptance. Notation Typst cannot express is an open decision (spec section 17).

## ADR-005: Manifests are `manifest.json`; revisions are files

**Status:** accepted, 26 October 2026

**Decision.** Every job writes `manifest.json`. Revisions are stored as immutable file copies plus manifests, indexed by SQLite later. Git as the revision store is deferred (spec section 17, item 10).

**Why.** The GitHub Python `.gitignore` template ignores `*.manifest`. File-based revisions keep the workspace independent of Git for now.

## ADR-006: One Manim section per storyboard scene

**Status:** accepted, 26 October 2026

**Decision.** Generated code emits `next_section(scene_id)` at each scene boundary. Video renders use `--save_sections`; the section index is stored in the manifest; unchanged sections are skipped with `skip_animations=True` and their cached clips concatenated.

**Why.** Manim already provides the segmentation, per-section files and metadata the plan needed for scene-level invalidation.

## ADR-007: Narration is in the storyboard schema; audio stays `none` in V1

**Status:** accepted, 26 October 2026

**Decision.** Each scene may carry `narration.text` with optional `<mark name="..."/>` marks. Scene durations are proposed from it at `motion.narration_words_per_minute`; subtitles are emitted through Manim subcaptions. Voiceover (manim-voiceover bookmarks) is a later addition that maps marks to bookmarks.

**Why.** Timing in an explainer follows what is said. Adding the field later would orphan existing storyboards.

## ADR-008: Family environments list `scianim-core` explicitly

**Status:** accepted, 26 October 2026

**Decision.** A family's `pyproject.toml` depends on both `scianim-bridge` and `scianim-core`, with path sources for
each during development.

**Why.** uv applies a project's `tool.uv.sources` only to packages the project itself depends on. With `scianim-core`
reachable only transitively through the bridge, resolution looked for it on PyPI and failed. Listing it directly is
the smallest fix and remains correct once both packages are published.

## ADR-009: Rendering prerequisites are headers, not a TeX distribution

**Status:** accepted, 26 October 2026

**Decision.** The documented system prerequisites for a family are the Cairo and Pango development headers (pycairo
and manimpango compile against them on Linux), a font named by the style, and nothing else. `doctor` verifies PyAV,
Typst, manimpango and pycairo inside the family environment.

**Why.** Verified on a clean Ubuntu 24.04 container: with `libcairo2-dev` and `libpango1.0-dev` present, the family
lock installs manim 0.22.0 from PyPI and the example renders without LaTeX or a system ffmpeg.
