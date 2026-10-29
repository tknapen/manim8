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

## ADR-019: Frame-exact timing, per-scene sections and sampled frames for video

**Status:** accepted, 26 October 2026 (Milestone 4)

**Decision.** Every play and wait in generated code lasts a whole number of frames. The bridge's
`play_frames(n, ...)` asks Manim for half a frame less than `n` for animated plays (Manim's time
progression `np.arange(0, run_time, 1/fps)` rounds up) and half a frame more for static waits (Manim's
frozen-frame path truncates), pins the path with `frozen_frame`, and then sets the renderer clock to exactly
`n / fps`. Storyboard times therefore map to frame indices by nearest-frame rounding (`frames_for`), scene
boundaries land within half a frame of the storyboard, and a storyboard of `duration` seconds renders to
`round(duration * fps)` frames. A video job (`scianim render --profile draft|final`) runs the same scene code
with `--save_sections`; the worker copies the movie, the per-scene section videos and Manim's section index,
and the SRT written from `narrate()` subcaptions into the job directory, probes every file with PyAV (frame
counts come from decoding, not from container metadata), and records a `TimingReport` that compares each
section and the total with the storyboard at a documented tolerance of one frame. A final render that misses
the tolerance fails; a draft only warns. Draft renders scale the output to two thirds (1280 by 720 for a
1080p spec); final renders use the exact dimensions and fps, and the worker rejects a movie whose probed size
or rate differs from the job.

The worker also decodes the movie once and saves the first frame at or after the moment each storyboard
checkpoint was actually reached (`sampled_video_frame`, fidelity exact, no layout report), plus any extra
`--sample id=seconds`. These are the confirmation the spec asks for when fast-forward marks a checkpoint
approximate.

`scianim timing` proposes scene durations from narration at the style's speaking rate (padded by 1.25, at
least 3 s, snapped to frames) and reports conflicts with hard milestones, snapshots and timed reveals; it never
edits the storyboard in place (`--out` writes a proposal). `scianim stale` lists the scenes whose timing,
narration, objects, snapshots, data, equations, custom code or style changed since a revision.

**Deferred.** Splicing cached section videos into a new movie (`skip_animations=True` on unchanged sections)
is not implemented. Manim's own per-play cache under the revision's stable `media_dir` already skips
unchanged plays, so a re-render after a one-scene change re-encodes only that scene's plays; the stale-scene
report says which scenes to review. Splicing would need a PyAV remux of section files and a way to keep
subtitles and sections consistent; it is worth doing when renders become long enough for the per-play cache
not to suffice.

**Why.** A reviewer must be able to trust that 00:24 in the storyboard is 00:24 in the video. Manim's two
rounding paths differ by one frame per play, which accumulated to nine frames over a 60 s example before this
change; requesting half-frame offsets is the smallest intervention that makes both paths exact without
patching Manim.

## ADR-020: Agents work through files: extracts, context bundles and proposals

**Status:** accepted, 26 October 2026 (Milestone 5)

**Decision.** No model is called from the control plane. The agent-facing surface is three kinds of file:

- *Source extracts* (`.scianim/sources/<id>.json`, `scianim sources probe`): what a declared source says, read
  by an adapter per type (csv columns, dtypes, ranges and counts; markdown and text headings and words; pdf
  page texts with page anchors; image dimensions; another project's ids and revisions), with the file's
  sha256. Adapters never fill `inferred`; an interpretation carries who made it.
- *Context bundles* (`.scianim/context/`, `scianim context`): `CONTEXT.md` with the agent instruction contract
  (spec 7.2), the brief, equations, what each source says, the current storyboard, the style roles and type
  scale, the registry with every parameter, open feedback and the latest layout reports; plus `context.json`,
  the JSON Schemas and a proposal template. Any coding agent, hosted model behind an adapter, or person can
  work from it.
- *Proposals* (`proposals/<id>.yaml`, `scianim propose validate|apply|list`): a typed `Proposal` with
  summary, rationale, `uncertainties` (the questions the sources did not answer), `claims` with source ids
  and locators, and per target file either a whole `document` or a JSON-pointer `patch`. The control plane
  validates the resulting documents against the contracts and the cross-file rules before writing anything,
  applies them to the working copy, and keeps the proposal with a unified diff under `proposals/applied/`.
  A proposal that changes equations, sources, scientific constraints, or data and equation bindings (a new
  storyboard included) is recorded as requiring scientific sign-off; the tool never approves it.

`scianim inspect` is the agent's self-check before asking for review: for every checkpoint it lists objects
the storyboard reveals by that time but the layout report lacks, objects present that are not expected,
descriptions naming missing objects, layout warnings, approximate fidelity and blank frames, and can record the
discrepancies as feedback authored `agent:inspect`.

The registry gains `caption_with_citation` (a caption whose second line is a declared source's citation and
locator; the job carries citations), `schematic_population` (unit glyphs with labelled illustrative activity),
`receptive_field_glyph` (a Gaussian field as contour rings in a visual-field box) and `network_graph` (nodes on
a row, circle or grid with weighted, directed edges; negative weights dashed). Registry version 0.3.0.

**Deferred.** Voiceover through manim-voiceover bookmarks needs a speech service and is not wired; narration
marks already exist in the storyboard for it. Figure extraction from PDFs is page text only.

**Why.** Files keep the loop reproducible and vendor-neutral: the acceptance test replays a complete loop
(brief and synthetic CSV to spec, storyboard, real snapshots, inspection, a review comment, a targeted patch
and a revision comparison) with fixture proposals and no network. Separating what a source says from what
anyone inferred, and binding claims to locators, is the concrete form of spec section 6.2.

## ADR-021: Bundles are verified archives that carry everything but the environment

**Status:** accepted, 26 October 2026 (Milestone 6)

**Decision.** `scianim bundle export` writes `<name>.scianim.zip` with one `scianim-bundle/` root holding
`bundle.yaml` (a `BundleManifest`), a generated README with the family's system requirements and the
post-import steps, `projects/<id>/` (specs, data, references as text, code, revisions, feedback, applied
proposals, optionally renders), `family.yaml`, every style sheet in each project's inheritance chain, the
family's shared components and assets, `environments/pyproject.toml` with the lockfile, and `MANIFEST.sha256`
over every file. Members are written in sorted order with a fixed timestamp so the checksums are meaningful.
The export refuses symlinks and credential-looking files, never includes `.venv`, `.scianim`, caches or
renders unless asked, fails on absolute paths in text files unless `--redact-paths`, and omits PDFs and
third-party reference images unless `--include-source-assets`; every omission is recorded with a relink
instruction. `scianim bundle inspect` validates entry names (no absolute paths, `..`, symlinks or escapes from
the root), the manifest and every checksum without importing or running anything. `scianim bundle import`
verifies first, then creates the family (fresh `pyproject.toml` pointing at this checkout's packages; the
lockfile is reused only when `packages/` sits at the same relative place as at export), copies components,
assets and projects, adds style sheets that are absent and refuses a sheet that differs from an existing
version, never overwrites a project, and prints the explicit next steps (`family env sync`, `validate`).

**Why.** Sharing must not share secrets, machine paths or copyrighted sources; a reviewer must be able to
trust an archive before any code from it runs; and a theme version must mean the same tokens everywhere.
Rebuilding the environment is kept explicit because it needs network access and system libraries that a
bundle cannot carry.

## ADR-022: Scene actions; `vary_parameter` is the first, and checkpoints split it

**Status:** accepted, 26 October 2026

**Context.** The first three examples revealed static objects in sequence, which is a slide deck with
transitions. What an animation can show that a figure cannot is one quantity changing while the viewer watches
the equation term, its value and the curve move together, instead of two panels side by side.

**Decision.** A scene has an `actions` list beside its objects and snapshots. The first and only kind is
`vary_parameter`: it names a `function_plot` object in the same scene, one of that plot's named `parameters`,
a target value, a window (`at_seconds`, `duration_seconds`), an optional easing (the style's `motion.easing`
by default), the equation objects to `emphasize` (each must highlight that symbol), and whether to show a
readout (`show_value`, `value_decimals`, `value_label`). A `function_plot` declares `parameters` as named
constants that its series expressions and marker positions may use; markers accept an expression in the
parameters so they follow a sweep; a plot that a sweep targets must fix its `y_range`, because axes never
rescale while something varies. The validator refuses overlapping actions, reveals inside an action window,
targets or emphasized objects revealed after the action starts, and ids shared with objects; the readout is
registered under the action's id and appears in layout reports as kind `value_readout`.

Codegen emits `begin_vary()` at the action's start and one `vary_until(t)` per checkpoint inside the window
plus one for the end. The bridge keeps the sweep's value curve on the storyboard window, so each segment
continues the same easing and a checkpoint inside a sweep is reached by the real animation flow at the exact
frame (fidelity `exact`); nothing uses time-based updaters. In Manim's fast-forward mode a segment evaluates
once at its end, which lands on the same state. The sweep rebuilds the curves in place in the axes' frame
(the invisible axes travel with the plot group), moves the markers, staggers marker labels that would
collide, pulses the emphasized glyphs once (`motion.emphasis_scale` over `motion.emphasis_seconds`, both
tokens) and sets the readout text each frame; a series that leaves the fixed range is clipped and the manifest
records a warning. Project checks warn when an action would start late because reveals are still playing, or
would end inside the scene's fade-out; timing proposals treat an action outside its scene as a conflict;
staleness notices changed actions; inspection expects the readout once the action has begun.

**Why.** One action at a time keeps generated code a readable projection of the storyboard and keeps every
checkpoint a marker in the flow. Tying parameters to the equation's symbol names (a warning when they differ)
makes "emphasize σ, then vary σ" one statement rather than two that could drift apart. Further kinds (moving
an object, fading one out, transforming one equation into another) join the same list as a discriminated
union on `kind`.

## ADR-023: An animation is a brief clip, and the examples say so

**Status:** accepted, 26 October 2026

**Context.** The first examples grew into forty to sixty second sequences with title cards, a scene that only
listed symbol definitions, and side-by-side panels: slide decks with transitions. The intended product is a clip
of a few seconds to half a minute that shows one mechanism moving.

**Decision.** AGENTS.md, the spec's definition of success, the user guide and the agent context instructions
state that an animation here is brief: typically 5 to 30 seconds, one or two scenes, the equation beside the
picture, no title cards or definition-only scenes, and at least one quantity that varies while the viewer
watches. The project scaffold proposes 15 seconds. The three examples are rebuilt to that shape: the pRF clip
(12 s, one scene) moves the centre and then grows the size with stacked readouts under one equation label;
divisive normalization (18 s, two scenes) shows the drive alone and then raises the pool beside an equation
block; orientation tuning (20 s, three scenes, produced by the agent loop from its fixtures) shows the circuit,
the cited synthetic curve with the model named beside it, and the model sharpening as kappa rises. The kinds
the brief examples no longer use (`comparison_plot`, `receptive_field_glyph`) keep render coverage through a
gallery storyboard in the test fixtures, not through an example. Readouts of successive actions on the same
reference stack away from it. Project checks now warn when an explicit reveal is due while earlier reveals are
still playing, as they already did for actions, and the video probe reads the nominal frame rate (a
duration-derived average can differ by a millisecond's rounding and is not a frame-rate error).

**Why.** Examples teach the shape of the work more than any instruction does, and an agent asked for "an
animation of X" will copy them. Keeping the long-form machinery (sections, subtitles, timing proposals) costs
nothing; what changed is the default.

## ADR-024: Surfaces, a camera that orbits, and tracks that run together

**Status:** accepted, 26 October 2026

**Context.** The first brief clips varied one curve at a time. A convincing example needs an object with
real structure (a Gabor filter as a mesh in three dimensions), a camera that turns around it while its
parameters change one after the other, and flat text that stays legible throughout.

**Decision.** Two kinds join the registry. `surface_plot` draws z = f(x, y) over a fixed box as a fine mesh
(`resolution` cells per axis) with cells filled by the sign of the value (the two inks) or fading with height,
a despined floor frame with one vertical edge, outward ticks, and labels that keep their screen orientation
while following their anchors in the world; its `parameters` sweep like a function plot's, and the box never
rescales. `function_image` samples f(x, y) to pixels (a grating, a kernel) in two inks around white or in
grey, optionally masked to a disc, over a fixed `value_range`. A second action kind, `orbit_camera`, moves the
camera's azimuth and elevation to given angles over a window; it needs a surface in the scene, because flat
objects are fixed in the frame and do not turn.

Actions run concurrently. The validator refuses only two actions that drive the same parameter of the same
object at once, or two orbits that overlap. Codegen turns a scene into breakpoints (track starts and ends,
checkpoints, the start of the fade-out) and emits one `run_until(t, [tracks])` per segment, in which every
active track advances together; a reveal is a track too, so objects can fade in while a sweep runs, and
objects without a reveal time appear together at the scene start rather than one after another. A checkpoint
at a breakpoint captures the state before anything that starts there. Each track exposes `apply(fraction)`
over its own window, so split segments continue the same easing, and in Manim's fast-forward mode a segment
evaluates once at its end. The bridge scene is a `ThreeDScene`; every flat component is fixed in the frame
when it registers (and again after any `become`), surfaces are not, and the layout report projects a
surface's points through the camera so its box is the one on screen. Readouts are keyed by the swept object
and parameter, so a second action on the same parameter updates the first readout instead of adding one.
Style tokens gain a `three_d` group: the camera's starting elevation and azimuth, the mesh line weight and
the surface opacity.

**Why.** One action at a time was a simplification that made the first sweep easy and the second example
impossible. Breakpoints and tracks keep generated code a readable projection of the storyboard and keep every
checkpoint a marker in the flow, while letting the camera, the surface and the readouts move together. The
Cairo renderer draws a surface as thousands of small polygons, which is slow for long videos but exact and
deterministic; the OpenGL renderer would be faster and is not adopted, because the whole pipeline (sections,
frame-exact timing, checkpoint capture) is verified on Cairo.

## ADR-025: The baseline theme is line and wash (`default@0.3.0`)

**Status:** accepted, 28 October 2026

**Context.** The baseline `default@0.2.0` (Twin Ink) set a white page with a near-black ink, a saturated
blue and a saturated red. With surfaces, meshes and orbiting cameras in the examples, the red read as an
alarm rather than an accent, the black lines were heavier than the mesh they framed, and the washes were
too strong for a surface to show its mesh through. The look asked for is the one in Keenan Crane's geometry
figures: an object on a white page drawn with a thin dark line, filled with a flat pale wash, one warm
accent, and air around it.

**Decision.** A new published version, `default@0.3.0` (line and wash), with its own tokens: the line ink is
a dark indigo rather than black; the working blue is lighter and less saturated; red gives way to orange as
the accent and as the second condition; soft and uncertainty washes are paler; axes, annotation strokes and
mesh lines are thinner, a surface is laid at sixty percent opacity, and the camera starts a little lower and
closer to the diagonal. Text sizes, the type scale, despined axes and the motion tokens are unchanged. The
tokens are our own values chosen for that feeling, not a copy of any figure's colours. `default@0.2.0` is
not edited and remains resolvable; `tomas_scientific@0.3.0` pins the new baseline and changes nothing yet.
The examples, the scaffold and the agent-loop fixture pin `0.3.0`. The specimen beside the sheet is no
longer a plate drawn in Typst: `tools/specimen_line_and_wash.py` composes it from real checkpoint renders
of the four examples, so it shows what the renderer does, labelled with the fonts that were actually
resolved.

**Why.** A theme is a published version, so a change of taste is a new directory, never an edit (ADR-010);
an old animation re-rendered under its pinned theme still looks as it did. Components read every colour,
weight and size from tokens, so the whole change is one sheet and no code. A specimen composed from renders
cannot drift from the renderer, which a hand-drawn plate could.

## ADR-026: Segmented clips: a lead-in, an active highlight mode and axes that leave

**Status:** accepted, 29 October 2026

**Context.** A clip that changes several parameters in turn needs the viewer to know, before each change,
which term is about to act. Until now every highlighted term carried the accent colour throughout, the pulse
began at the same instant as the sweep, and a surface's frame, ticks and labels stayed for the whole clip
even though they matter only while the viewer learns the box.

**Decision.** Three additions to the storyboard contract, all typed and validated. `vary_parameter` gains
`lead_in_seconds` (default 0): the action's window is `lead_in_seconds + duration_seconds`, the emphasized
term takes the colour and pulses during the lead-in while the readout shows the starting value, and the
value moves only afterwards; checkpoints inside the lead-in are reached by the real flow like any other.
An equation reference gains `highlight_mode` (`always`, today's behaviour, or `active`): in `active` mode the
highlighted terms sit in the equation's own ink and only the term that a running action emphasizes takes
the colour; it keeps it until the next emphasized action on that equation begins, when the colour passes
to the new term and the earlier term's readout recedes to the secondary ink. Concurrent actions keep their
terms coloured together. A new action kind, `fade_axes`, fades a `surface_plot`'s frame, ticks and labels
out (or back in) over a window; once gone they leave the object's group, so the layout report sees the
shape alone. Each occurrence of a highlighted symbol is typeset as its own group, so a pulse grows every
occurrence about its own centre. The component registry is `0.4.0`. The Gabor example is rebuilt as such a
clip: the box is shown once, then orientation, frequency, location (two concurrent sweeps) and size change
in turn, with a lead-in before each.

**Why.** The lead-in makes "which term" precede "what happens", which is the point of a segmented clip; a
storyboard field, not a style token, because it is a choice per action. `active` mode is a property of the
equation object, so one YAML line switches a whole clip from "all terms marked" to "the term at work is
marked". Fading the axes is an action because it has a time, like everything else that happens in a scene,
and it is restricted to surfaces because only they draw their frame as a separable group today. The
pulse-per-occurrence fix is a bug fix made visible by the first equation with a repeated symbol.

## ADR-027: `default@0.3.1`, solid surfaces

**Status:** accepted, 29 October 2026

**Context.** Under `default@0.3.0` a surface is laid at sixty percent opacity. With the mesh behind a lobe
showing through, a surface with several lobes (a Gabor filter after its frequency rises) reads as a tangle
rather than a shape.

**Decision.** A new published version, `default@0.3.1`, that inherits `default@0.3.0` and sets one token:
`three_d.surface_opacity` is `0.92`. Its philosophy restates the line-and-wash principles with surfaces as
nearly solid shapes and adds that axes may leave once read and that the colour passes from term to term in a
segmented clip. `tomas_scientific@0.3.1` pins it and changes nothing. The examples, the family manifest, the
fixtures and the specimen tool pin `0.3.1`; the specimen beside the new sheet is composed from renders made
under it. `default@0.3.0` is not edited.

**Why.** Opacity is a property of every surface, so it is a theme token rather than a per-object parameter,
and a theme is a published version (ADR-010): a change of taste is a new directory. A patch version that
inherits its parent records exactly what changed, and the resolved style's provenance shows it.

## ADR-028: Motion rules are style tokens (`default@0.4.0`, slow in and slow out)

**Status:** accepted, 29 October 2026

**Context.** The segmented clips read as mechanical. The camera turned at constant speed from the first
frame to the last because the storyboards said `easing: linear`; the sine profile of the sweeps starts with
its acceleration at full strength; the pulse of a term began with a kick and the colour of a term and of a
readout changed linearly or snapped. None of this was a property of the style sheet, so a theme could not
make a clip smooth.

**Decision.** Smoothness is a set of `motion` tokens. `easing` (now `smooth`) is the profile of everything
that moves between two states and does not choose its own: sweeps, axes fades, the colour of a term and of a
readout. `camera_easing` (new; `None` means `easing`) is the profile of orbits, and the new profile
`eased_linear` ramps up over `ramp_seconds` (new, 1.5 s), turns at constant speed and ramps down, with
smoothstep ramps so velocity and acceleration are continuous; a motion shorter than two ramps becomes a plain
ease. `hold_seconds` (new, 0.5 s) is the rest asked for between the end of one motion of an object and the
moment the next moves its value. The pulse is a raised cosine. `scianim validate` warns when an action asks
for `easing: linear`, when a lead-in is shorter than the pulse, or when two motions of one object rest less
than `hold_seconds`. The rules are written out in the theme's philosophy. `default@0.4.0` inherits
`default@0.3.1` and sets the four tokens; `tomas_scientific@0.4.0` pins it; the examples, the family, the
fixtures and the specimen tool pin `0.4.0`, and the two camera orbits in the examples no longer override the
profile. The orientation-tuning stimulus turns for 5.7 s instead of 6 so the curve rests before it sharpens.
Older sheets resolve as before: the new tokens default to the previous behaviour (`camera_easing` follows
`easing`, `hold_seconds` is zero), only the pulse profile and the eased colour change apply to every sheet.

**Why.** Feel is a property of the theme, like colour and weight, so it belongs in the sheet and under
version control. A profile for the camera separate from the profile for sweeps is needed because the two
motions have different jobs: a sweep is the subject and should ease over its whole length; an orbit is
background and should be nearly uniform, with ramps only so that it never starts or stops at speed. A minimum
rest and a lead-in at least as long as the pulse are timing rules, which no profile can supply, so they are
checks rather than tokens the renderer applies.
