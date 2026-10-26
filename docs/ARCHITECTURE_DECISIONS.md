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

## ADR-010: Versioned style directories with pinned inheritance

**Status:** accepted, 26 October 2026

**Decision.** Sheets live at `styles/<name>/<version>/style.yaml`; resolution is by name and version; a sheet
inherits another only as `name@version`.

**Why.** A single sheet per theme cannot keep an old project rendering with its pinned theme after a bump, and a
bundle must carry exactly the pinned sheet. Pinned inheritance keeps a theme's resolved tokens stable when its
parent gains a version.

## ADR-011: The nearest family is authoritative

**Status:** accepted, 26 October 2026

**Decision.** The closest `family.yaml` above a project defines its family. `animation.yaml` may omit `family:`;
if present it must match. A project outside every family directory is looked up by id in `families/` search
roots, where the id must be unique. `group.yaml` files between family and project add style overrides in order.

**Why.** The previous permissive search could silently bind a project to a grandparent or a sibling tree.

## ADR-012: Examples are read-only templates; workspaces hold instances

**Status:** accepted, 26 October 2026

**Decision.** Nothing under `examples/` is rendered in place. `scianim workspace init` creates a workspace
(bundled styles copied in), `family init` and `project init` populate it, optionally `--from-example`. Family
`pyproject.toml` files are generated with relative path sources to the source checkout; the example lock is
copied only when that relative path is identical.

**Why.** Rendering into the repository tree muddled fixtures and user data, and the spec requires that users never
create folders by hand.

## ADR-013: Revisions are write-once directories; data is recorded by hash

**Status:** accepted, 26 October 2026

**Decision.** `revision create` copies specs, generated code and the resolved style into `revisions/rev_NNNN/`
with `revision.json`. Data files stay in `data/`; their hashes are recorded and `snapshot --revision` refuses to
render when they changed. Renders are project-local under `renders/<revision>/<job>/`; `scianim clean` removes
Manim's media cache and superseded working renders and never touches revisions.

**Why.** Copying data per revision would duplicate large inputs; hashing keeps revisions honest without the cost.
Project-local renders keep bundles and review sheets self-contained.

## ADR-015: Twin Ink is the baseline theme; fonts resolve through declared fallbacks

**Status:** accepted, 26 October 2026

**Decision.** `default@0.2.0` is a white-page theme with a blue ink for signal and a red ink for attention,
Helvetica text and Palatino-lineage math (`math_font: "TeX Gyre Pagella Math"`, `latex_packages: ["newpxmath"]`).
Every text role meets a 4.5:1 contrast ratio against the background; tints are reserved for fills. The bridge
resolves a typeface to the first installed family among `font_family` and `font_fallbacks` and reports any
substitution in the worker result; the Typst math font is injected as a `show math.equation` preamble. The
personal theme `tomas_scientific@0.2.0` inherits the baseline and records only differences.

**Why.** Helvetica and Palatino are proprietary; metric-compatible open fonts (TeX Gyre Heros, Nimbus Sans,
TeX Gyre Pagella Math) keep renders reproducible on machines without them, and a reported substitution is
better than a silent one. The previous dark placeholder was never a design.

## ADR-014: Shared assets are materialized into the project per job

**Status:** accepted, 26 October 2026

**Decision.** `asset://<id>` resolves to the family's `assets/`, then the workspace's. At job time the file is
copied into the project's `.scianim/assets/` and the job references that project-relative path.

**Why.** Job payloads and manifests must stay free of machine-specific absolute paths; the copy is cheap and
hashed.

## ADR-016: Analytic curves, relational placement and timed reveals are storyboard vocabulary

**Status:** accepted, 26 October 2026 (Milestone 2.5 dry run)

**Decision.** The registry gains `function_plot`: curves sampled from arithmetic expressions in `x` that
`scianim_core.expressions` validates against a whitelist (the binary operators `+ - * / ** %` with `^` accepted
for power, unary sign, numeric literals, the constants `pi`, `e`, `tau`, and the elementary functions `exp`,
`log`, `log10`, `sqrt`, `sin`, `cos`, `tan`, `tanh`, `abs`, `min`, `max`, `pow`, `floor`, `ceil`). Names,
attributes, subscripts, comprehensions and any other call are rejected at validation, and the renderer evaluates
the compiled expression with an empty builtins namespace. Every text-like object accepts `below` or `right_of`
naming an earlier object of the same scene, with `gap_px_at_1080p` defaulting to the style's baseline grid, and
every storyboard object accepts `reveal_at_seconds`. `scianim registry [kind]` prints the kinds and parameter
models. The registry version is `0.2.0`, so earlier cache keys are invalidated.

**Why.** The dry run showed that a Gaussian receptive-field profile should not need a CSV, that two captions
anchored `top_left` overlap, and that a storyboard with no per-object timing cannot stage a reveal inside a
scene. An expression whitelist keeps the `YAML never contains executable code` boundary: the expression grammar
is closed, has no side effects and cannot reach Python objects. Relational placement and reveal times are the
smallest additions that let an agent compose a scene from the registry alone.

## ADR-017: Axes are despined and every text size is a named token

**Status:** accepted, 26 October 2026

**Decision.** `charts.spines` lists the axis lines a plot draws; the baseline sets `[left, bottom]`, so every
plot kind is despined: no top or right spine, no frame, the two spines along the data box edges and never
through the origin, ticks outward, with `charts.spine_offset_px_at_1080p` to move the spines away from the data
and `geometry.tick_length_px_at_1080p` for the ticks. Typography gains one role per kind of text (`title`,
`body`, `annotation`, `axis_label`, `tick_label`, `caption`, plus `equation.size_px_at_1080p` and
`equation.label_size_px_at_1080p`) and `minimum_text_px_at_1080p`, which replaces `minimum_body_px_at_1080p`.
The resolved style rejects any role below the minimum; components set each piece of text in its role and never
multiply one size to obtain another; every component reports the smallest text it draws, so the layout report's
`text_too_small` covers tick labels and symbol definitions. Twin Ink's scale at 1080p is title 54, body 34,
annotation and axis label 30, tick label and caption 26, equation 46 and 38, minimum 26.

`default@0.2.0` is edited in place rather than versioned to 0.3.0: it was created on the same branch the same
day, no revision references it, and nothing outside this branch has resolved it, so it is not a published
version in the sense of section 5.3.

**Why.** The Milestone 2.5 renders set tick labels, captions and marker labels at hidden multiples of the body
size (22 px at 1080p), below the style's own minimum, and plots never reported their text to the layout check.
A multiplier in bridge code is a hardcoded size by another name. Named roles make the hierarchy a reviewable
decision in the sheet, the validator makes the minimum a promise rather than a hope, and despined axes are the
plotting convention of the field the baseline is for.

## ADR-018: Review records are files; the server and the index are views of them

**Status:** accepted, 26 October 2026 (Milestone 3)

**Decision.** A review annotation is a typed `FeedbackRecord` stored as `feedback/<id>.yaml` in the project,
written by `scianim feedback add|status` or by the review server; both produce the same record. A record binds
to `project_id`, `revision_id` (`working` or `rev_NNNN`), the `job_id` whose image was shown, `scene_id`,
`snapshot_id`, an optional `object_id` resolved from the layout report, a `region` in normalized image
coordinates, the displayed image's `sha256` and pixel size. Status records (`approved`, `needs_revision`,
`scientific_concern`) require the image hash, and `approved` refuses the working copy. The SQLite index
(`<workspace>/.scianim/index.sqlite`) caches projects, revisions, jobs, checkpoints and feedback; it carries a
schema version and is dropped and rebuilt from the files whenever that version changes, so it can never be the
only copy of anything. Jobs the server runs record their lifecycle in `.scianim/jobs/<job>/status.json`
next to the worker log, so queued, running and canceled jobs are visible without a manifest.

**Invalidation rule.** An approval refers to one image: the hash of the checkpoint PNG rendered from one
immutable revision. A later revision does not inherit it. What `scianim compare` and the Compare view can
show is whether a later render of the same snapshot is pixel-identical to the approved image; when it is, the
reviewer may carry the approval over with a new status record on the new revision, which again names the
hash it saw. Comments are requests for change and may target the working copy; a comment stays attached to
the revision and image it was made on. Scene-level dependency tracking (spec section 11.3) is deferred to the
video milestone; until then nothing is marked stale implicitly, and the compare tools make staleness visible
instead.

**Server boundary.** The API (`scianim serve`, loopback by default) accepts only ids that match the contracts'
patterns, serves artifacts from `renders/` and `.scianim/compare/` of a known project, and runs renders by
building the same typed job as the CLI and launching the family worker in a separate process; a request can
name a project, a revision and snapshot ids, never a path or code. The React UI is built into the package so
that `uv run scianim serve` needs no Node at run time; CI rebuilds it and fails when the committed bundle
differs from the source.

**Why.** Files keep the agent and the browser on equal footing (spec section 9.2) and keep bundles
self-contained; the index exists only for listing speed. Binding approvals to image hashes is the concrete form
of "never approve a mutable path" (section 9.3) that the system can verify.
