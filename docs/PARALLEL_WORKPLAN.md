# Work plan: the next stages, written for parallel implementation

**Status:** agreed with the author on 31 October 2026 (decisions in section 12). Baseline at the time of
writing: `claude/scianim-handoff` at `3f4307a` (`default@0.5.0`, parallel video renders, ADR-001 to ADR-030).

This plan turns the open items of `IMPLEMENTATION_PLAN.md` into work packages that separate agents can
implement at the same time. Each package names what it owns, what it may touch, the contract it exposes to the
others, how it is tested and what "done" means. A short seam package goes first and lands the handful of
shared changes that two or more packages need, so that the parallel branches do not edit the same lines.

Sizes are in agent-days of focused work, including tests and documentation; they are estimates. Every package
ends with an ADR (numbers reserved below), regenerated schemas where contracts changed, and the usual gates:
`ruff check`, `ruff format --check`, `pytest tests/unit`, the bridge tests in the family environment,
`scianim schemas export schemas --check`, and the integration subset the package names.

## 1. Package map

| Id | Package | Size | Depends on | Owns (primary files) | ADR |
|---|---|---|---|---|---|
| 0 | Seams | S (1) | nothing | small, listed in section 2 | none |
| A | Frame windows across workers | M (2–3) | 0 | `render/parallel.py`, `scene.py` play splitting, `jobs.py` fields | 031 |
| B | Raster surfaces, depth-correct frames, vectorised sampling | L (4–6) | 0 | `components/surfaces.py`, new `raster.py`, `expressions.py` | 032 |
| C | Splicing and cache honesty | M (3) | 0, A | `render/splice.py` (new), `planning/dependencies.py`, media fingerprint | 033 |
| D | Scene actions: move, fade, transform, data sweeps | L (4–6) | 0 | `storyboard.py` actions, `codegen`, `checks.py`, tracks in `scene.py`, `equations.py` | 034 |
| E | Voiceover: audio files, marks, local TTS | L (5) | postponed, not scheduled | `animation.py` audio block, new `audio.py`, `planning/timing.py` | 035 (reserved) |
| F | Review-to-revision loop | M (3) | 0 | `agent/feedback_proposals.py` (new), proposal kinds, UI button | 036 |
| G | Distribution and versioning | M (3 + CI time) | 0 | `pyproject.toml` files, workflows, `families/resolve.py` sources, `migrate` | 037 |
| H | Personal signature process | S–M (1–2) | 0 | `style stills` and `style publish` commands, `styles/` | 038 |

Conflicts to manage (section 11 has the rules): A and B both touch the camera orbit in `scene.py`; A and C both
plan parts in `render/parallel.py`; A and D both add tracks to `scene.py`; everyone adds to `cli.py` and to
`scianim_core/jobs.py`. The seam package removes the first three by landing the hooks both sides need. When E
is scheduled, its seam (a movie-finishing hook in `video.py` where audio is muxed) is added then.

## 2. Package 0: seams

One small pull request, reviewed before the others branch. Nothing here changes behaviour on its own.

1. **Segments from every video render.** The serial video worker reports `WorkerResult.segments` (one
   `SegmentRecord` per play, Manim's partial movie files) exactly as a part does, and video modes set Manim's
   `max_files_cached` to `-1` so the files outlive the render. Needed by C (reuse) and useful to A (one code
   path for segment accounting). Files: `packages/scianim_bridge/src/scianim_bridge/worker.py` (call
   `collect_segments` from the video branch too; it currently requires `job.part`, so give it a range argument
   that defaults to every play).
2. **A `FadeTrack`.** A track that eases an object's opacity between two values, with `finish` optionally
   removing the group from the scene; `end_scene` uses it instead of a raw Manim `FadeOut` play, so that every
   play in generated code is a track play or a static wait. Needed by A (only track plays can be split at a
   frame) and by D (`fade_object` is this track with a storyboard face). File: `scene.py`, beside `AxesFade`.
   Test: the end-of-scene fade produces the same frames as before (compare a divisive-normalization checkpoint
   hash before and after).
3. **A camera hook.** `SnapshotScene.camera_moved()` is called by `CameraOrbit.apply` after it sets the camera,
   and forwards to `component.on_camera()` for every registered component that defines it (today none).
   Needed by B (a raster surface redraws when the camera moves). Files: `scene.py`, `components/base.py`.
4. **Part planning signature.** `render/parallel.py` exposes
   `plan_parts(plays, weights, workers, *, reusable: frozenset[int] = frozenset()) -> list[PartRange]` as the
   one function that decides ranges; today it wraps `part_ranges`. A extends it with frame windows, C passes
   `reusable` (plays whose segments will be spliced in, never part of a range).
5. **Integration test markers.** `pyproject.toml` declares markers `video`, `surface`, `loop`, `bundle`
   beside `integration`, and the existing tests are tagged, so a package runs its subset
   (`pytest tests/integration -m "integration and video"`) and the full suite runs before a merge.
6. **Plan lines.** `IMPLEMENTATION_PLAN.md` gains one unchecked line per package under a new "Milestone 9:
   toward a full-featured package" heading, so each package later ticks its own line without conflicts.

Acceptance for the seam: all suites green; a two-worker render of the orientation example still matches the
serial one frame for frame (the existing integration test); the divisive-normalization `pool_raised`
checkpoint hash is unchanged by the fade track.

## 3. Package A: frame windows across workers

**Goal.** A part's range is a window of frames rather than whole plays, so one long sweep can be shared by
several workers. On four cores this evens the parts; on sixteen it brings the full-quality Gabor from 45 to
about 15 minutes, and together with B to a few.

**Design.**
- The planning pass is unchanged: plays with frames, kind and measured cost. Cost per frame inside a play is
  taken as uniform (measured seconds over frames; the estimate otherwise).
- The control plane chooses `N` windows by cumulative per-frame weight, as global frame indices `0..F`, and
  snaps a boundary to the nearest play boundary when it falls within `MIN_PIECE_FRAMES` (half a second) of
  one, or when the play is not splittable. The sorted interior boundaries are sent to **every** part
  (`PartRange.split_frames: list[int]`), together with the part's own `first_frame`, `last_frame`.
- Every worker splits the same plays at the same frames, so Manim's animation numbers agree across parts. The
  control plane derives the split play list from the plan (`split_plan(plays, boundaries) -> list[PlayRecord]`,
  with `source_index` and `piece` on each piece) and expresses `first_play`, `last_play` in that numbering;
  `_check_parts_against_plan` compares against the split plan.
- In the bridge, `play_frames(frames, *animations)` is the splitting point. It knows the clock in frames; if
  the play crosses a boundary, it plays the pieces in turn. A static wait splits into two waits. A track play
  splits into `TrackSegment`s that know their place in the whole play: `TrackSegment(track, f0, f1, frames,
  offset, total)` with progress `(offset + alpha * (frames - 0.5)) / total` for alpha below one and
  `(offset + frames) / total` at one, so piece frames land exactly where the whole play's frames would have
  (today's formula is the case `offset = 0, total = frames`). Track fractions are linear in time
  (`Track.target_fraction`) and every track applies an absolute state for a fraction, so a piece renders the
  same pixels as the whole play. `finish()` runs only after the last piece.
- Plays built from arbitrary animations (custom builders calling `play_frames` with Manim animations) are not
  splittable: the scene logs `PlayRecord.splittable = False` for them and the control plane snaps boundaries
  away from them.
- Checkpoints sit between plays and are unaffected. The merge is unchanged; pieces carry their scene id, so
  sections are unchanged.

**Contracts (additive).** `PartRange`: `first_frame`, `last_frame`, `split_frames`. `PlayRecord`:
`splittable: bool = True`, `source_index: int | None`, `piece: int = 0`. No YAML or CLI change; `--workers`
means the same.

**Files owned.** `src/scianim/render/parallel.py` (window planning, `split_plan`, the checks),
`packages/scianim_bridge/src/scianim_bridge/scene.py` (`play_frames`, `TrackSegment`, `run_until`,
`wait_until`), `packages/scianim_core/src/scianim_core/jobs.py` (the fields), `tests/unit/test_parallel.py`,
`packages/scianim_bridge/tests/test_parallel_bridge.py`, `tests/integration/test_video.py` (extend the
parallel test). Touches with care: `worker.py` (pass `split_frames` into the scene; three lines).

**Steps.** (1) `TrackSegment` offsets and a bridge test that a play rendered as two pieces applies the same
fractions per frame as one play (drive `interpolate_mobject` by hand, as `test_sweeps.py` does). (2) Static
wait splitting. (3) `split_plan` and window planning with unit tests (boundaries snap; pieces cover every
frame once; part numbering matches). (4) Thread `split_frames` through `part_job` and the worker. (5) Extend
the integration test: six workers on the orientation example put boundaries inside the 90- and 81-frame
plays; sampled checkpoint hashes equal the serial render's; a sample one frame after a boundary (`--sample`)
equals the serial frame. (6) ADR-031, user guide paragraph, plan line.

**Acceptance.** The orientation clip with `--workers 6` on four cores: parts within 25 percent of each other
by measured weights; frames identical to serial. The Gabor at full quality with sixteen workers: no part
longer than the total work divided by the number of cores plus the planning pass, within 20 percent.

**Risks.** Manim's static-image optimisation caches the non-moving mobjects per play; a piece boundary is a
play boundary for Manim, so it only costs one extra static render per piece. The cached-segment hash of a
piece differs from the whole play's, so the first windowed render after a serial one draws everything
(expected; C makes reuse explicit).

## 4. Package B: raster surfaces, depth-correct frames, vectorised sampling

**Goal.** A surface frame costs about a tenth of today's; the floor frame is hidden where the surface covers
it; a sampled image evaluates its field in one array call.

**Measured basis.** Cairo costs about a millisecond per cell per frame through Manim's per-mobject path (2.8 s
per frame for the 80-cell Gabor at 1080p). Filling and outlining 6400 quads with Pillow at twice the frame
size takes 97 ms on this machine; a box downsample (`Image.reduce(2)`) and the array hand-over add under
100 ms. Expect 0.2 to 0.3 s per frame at 1080p, less at the snapshot size.

**Design.**
- A new module `scianim_bridge/raster.py`: `RasterSurface` keeps the `(n+1)^2` vertex grid in world
  coordinates and, on every redraw, projects it through the scene's camera (reuse Manim's
  `ThreeDCamera.project_points` and its frame-to-pixel mapping, so the raster agrees with everything else on
  screen), sorts cells by view depth (painter's order; a surface graph has no overhangs that a single sort
  cannot handle), fills each quad with its wash and the shading of ADR-030 (the shading becomes one pure
  function in `tokens.py`, shared with the Cairo path), strokes the mesh at `mesh_stroke_px_at_1080p` in
  `mesh_role`, draws the floor frame and ticks into the same raster with a depth test per segment against the
  surface height at that `(x, y)` (hidden pieces omitted), and reduces to frame size. The result is an
  `ImageMobject` the size of the frame, fixed in frame, inserted in the scene where the surface group is.
- Redraw triggers: `rebuild(values)` (a sweep) and `on_camera()` (an orbit; seam hook). A frame with neither
  reuses the image.
- The component's `axes` group keeps the labels (Manim text, fixed orientation) and a hidden `ThreeDAxes` for
  coordinates; the frame lines move into the raster. `fade_axes` fades the raster's frame alpha and the labels.
- The layout report takes the projected vertex extents directly (exact, and cheaper than today's point
  projection).
- Selection: `ManimSettings.surface_renderer: Literal["cairo", "raster"]`, chosen with `scianim
  render|snapshot --surface-renderer` and the API field; the value enters the cache key. The two renderers are
  equals: the same tests run on both, the specimen tool can compose from either, and neither is deprecated.
  The default stays `cairo` so that no output changes until the author has reviewed raster stills; the
  decision to switch the default is deferred and is not part of this package.
- Vectorised sampling: `compile_expression(..., arrays=True)` compiles against a NumPy namespace
  (`np.exp`, `np.where` for the comparisons the grammar allows) and returns a callable over arrays;
  `function_image.array()` and the surface grid evaluate in one call. The plan pass gets faster too.
- Depth-correct frames in the Cairo path, as the small fallback: split each frame line into about twenty
  segments so Manim's per-mobject depth sort approximates occlusion.

**Contracts.** `ManimSettings.surface_renderer`; no YAML change; `--surface-renderer` on `snapshot` and
`render`; `JobCreate.surface_renderer` on the API.

**Files owned.** `components/surfaces.py`, new `raster.py`, `camera.py` (projection helper), `tokens.py`
(shading function), `scianim_core/expressions.py`, `scianim_core/jobs.py` (`surface_renderer`),
`src/scianim/render/jobs.py` (`manim_settings`), `cli.py` options, bridge tests `test_raster.py`,
`tests/unit/test_contracts.py` (expressions), `tests/integration/test_snapshots.py` (a raster Gabor snapshot).

**Steps.** (1) Expressions over arrays, with a unit test that scalar and array evaluation agree on a grid.
(2) Shading as a pure function; the Cairo path calls it (no visible change; the bridge shading test holds).
(3) `RasterSurface` with a bridge test that projects three known points and matches Manim's projection, that
painter's order puts the near cells last, and that a frame segment behind a ridge is omitted. (4) The
component switch and the camera hook. (5) Layout report from projected vertices; the existing layout tests
(ink-only box, lift) must still pass on both paths. (6) Integration: Gabor `rotating` under both renderers;
the projected bounding boxes agree within two percent of the frame; the raster frame renders in under 0.4 s
at the snapshot size. (7) Compose a raster twin of the `default@0.5.0` specimen beside the Cairo one
(`specimen_raster.png`, not replacing the published specimen) for the author's review. (8) ADR-032, guide,
plan line.

**Acceptance.** Gabor at 80 cells, 1080p, 60 fps, one process: under five minutes; with four workers and A,
about two. The `rotating`, `moved` and `with_axes` checkpoints reviewed side by side with the Cairo ones, the
frame lines hidden where the surface covers them.

**Risks.** Anti-aliasing differs from Cairo's (supersampling versus analytic coverage); the
specimen decides whether raster becomes the default. Pillow's polygon has no sub-pixel coordinates; the 2×
supersample is the mitigation, 3× is the fallback at three times the fill cost. Transparent surfaces
(`surface_opacity` below one) need back-to-front blending, which painter's order gives for free.

## 5. Package C: splicing and cache honesty

**Goal.** A re-render after a change in one scene draws only that scene's plays and splices the others from
the previous render; Manim's per-play cache never serves a segment made by other renderer code.

**Design.**
- `planning/dependencies.py` gains `scene_fingerprints(report) -> dict[scene_id, sha256]`: the hash of a
  scene's storyboard mapping, the equations it references, the data files it binds (by content hash), the
  custom builders it names and the resolved style hash, with the output settings. `InputHashes` records
  `scene_fingerprints` in every video manifest.
- A new `render/splice.py`: given the plan pass and the latest succeeded video manifest of the same project,
  profile and Manim settings, a scene is **reusable** when its fingerprint is unchanged, its plays in the plan
  equal its plays in that manifest (frames, kind, scene id, in order) and every segment file exists with the
  recorded size and `sha256` (new optional field on `SegmentRecord`, filled by workers). Reusable plays are
  passed to `plan_parts(..., reusable=...)`; the merge receives the reused segments together with the new
  ones. The plan pass still runs (it is cheap and provides subtitles, checkpoints and the play list).
- A serial render (`workers = 1`) also splices when it can: the serial path becomes "one part over the plays
  that need drawing, then merge", which is the parallel pipeline with `N = 1`. The old single-process path
  remains for `--no-splice`.
- Cache honesty: the family probe reports `bridge_fingerprint` (sha256 of the installed `scianim_bridge`
  package files, Manim's and Typst's versions); the media directory becomes
  `.scianim/media/<revision>/<fingerprint>/`; the fingerprint also enters the scene-level cache key through
  `tool_versions`. `scianim clean --media` removes fingerprint directories other than the current one.
- The timing report notes which sections were spliced; the CLI prints "spliced 2 of 3 scenes from job_…".

**Contracts.** `InputHashes.scene_fingerprints: dict[Slug, Sha256] = {}`, `SegmentRecord.sha256: Sha256 |
None`, `ToolVersions.bridge_fingerprint: str | None`; `scianim render --no-splice`; `JobCreate.splice: bool`.

**Files owned.** new `src/scianim/render/splice.py`, `planning/dependencies.py` (fingerprints),
`families/resolve.py` (`PROBE_SCRIPT` fingerprint), `src/scianim/render/jobs.py` (media directory, cache
key), `src/scianim/clean.py`, `scianim_core/jobs.py` (fields), `worker.py` (segment hashes), `cli.py`,
`runner.py`, tests: unit (`test_video_and_timing.py` fingerprints, `test_parallel.py` reuse selection),
integration (`test_video.py`: render the orientation clip, change the `sharpen` target, re-render, assert that
only the `model` scene's plays were drawn and that the `circuit` and `data` checkpoints hash as before).

**Steps.** (1) Fingerprints with unit tests (a narration edit changes only its scene; a style change changes
every scene). (2) Segment hashes from workers. (3) Reuse selection and the merge inputs. (4) The serial path
through the pipeline with `N = 1`. (5) Media fingerprint and `clean`. (6) ADR-033, guide ("re-rendering after
a change"), plan lines (this closes the deferred half of ADR-019).

**Acceptance.** On the orientation example: a second render after a one-scene change takes about that
scene's share of the first render's time; frames of the untouched scenes are byte-identical to the first
render's. After `git pull` of a bridge change, no segment from before the change appears in a new movie
(the media fingerprint differs; verified by a test that fakes the fingerprint).

**Dependency.** Builds on A's `plan_parts`; until A lands, C can be developed against the seam signature with
whole-play ranges and rebased once.

## 6. Package D: scene actions

**Goal.** The four action kinds ADR-022 left open: move or fade an object, transform one equation into
another, and sweep a parameter of a data-bound plot.

**Design.**
- `move_object`: `{kind: move_object, id, target, to_anchor: Anchor | null, by: [dx, dy] | null, at_seconds,
  duration_seconds, easing}`; exactly one of `to_anchor`, `by` (fractions of the safe frame). A `MoveTrack`
  captures the start position when the segment begins and interpolates to the absolute target; flat objects
  only (the validator refuses surfaces and images that turn with the camera). Readouts and emphasis follow
  because they are placed relative to their reference on every apply.
- `fade_object`: `{kind: fade_object, id, target, visible, at_seconds, duration_seconds, easing}` on the seam's
  `FadeTrack`; a faded-out object stays registered but `visible = False` (the layout report and inspection
  already honour that flag); `fade_axes` remains the special case for a surface's frame.
- `transform_equation`: `{kind: transform_equation, id, target, to: <equation id>, at_seconds,
  duration_seconds, match: by_symbol | by_shape}`. The equation component typesets the target with the same
  per-occurrence symbol groups (`_group_symbols`), pairs occurrences by symbol name (`by_symbol`) or by
  Manim's shape matching for the rest, fades unmatched glyphs out and in, and on `finish` becomes the new
  equation: later `vary_parameter` emphasis on that object resolves symbols against it. A `TransformTrack`
  wraps the Manim transform the way `RevealTrack` wraps a fade. The validator tracks the equation active on an
  object over time and refuses an emphasis of a symbol the active equation lacks.
- Data sweeps: `DataBinding.transforms` entries may name parameters (`{kind: smooth, window: $w}` becomes
  `window: {parameter: w, default: 5}`), the `data_plot` component recomputes its series from the table when a
  parameter changes, and `vary_parameter` accepts those parameters for data-bound objects. Small tables only;
  the validator warns above ten thousand rows.
- Registry version 0.5.0. `codegen` emits `begin_move`, `begin_fade`, `begin_transform` and the existing
  `begin_vary` for data parameters; `check_actions` extends the overlap and hold rules to the new kinds; the
  server's `action_summary` and the review UI show them; the user guide gets one example each.
- **The fifth example, `drop_impact`** (the author's choice: something visually appealing, a drop of water
  falling onto a water surface and bouncing back). One scene of about twenty seconds in a new project folder
  of the example family (it needs no new environment). A `surface_plot` is the water: its expression is a
  damped radial capillary wave with time as a parameter, `h(r, t) = A exp(-r / lambda) cos(k r - omega t)
  exp(-t / tau)` for `t` after impact, plus a central Gaussian column whose height follows a pulse after
  impact (the rebound, the Worthington jet of the physics literature); the equation is shown and its terms are
  emphasised as the sweep runs. Above it a `sphere`, a new small registered kind placed in the data
  coordinates of an anchor surface (`anchor: <surface id>`, `position: [x, y, z]`, `radius_fraction`,
  `style_role`), falls with `move_object` (`to_point` in the anchor's coordinates, so `move_object` covers
  flat objects by anchor or offset and anchored 3D objects by point), fades at impact (`fade_object`), the
  ripples spread (`vary_parameter t`), the column rises and a smaller sphere pinches off, climbs and falls
  back (two more moves), and the rings fade while the camera orbits slowly. The caption and the data label say
  what it is: an analytic model of the surface, not a fluid simulation; the example's `animation.yaml` says so
  in its scientific notes. The clip exercises move, fade, the surface sweep and term emphasis; a
  `transform_equation` turns the drop's free-fall equation into the wave equation at impact. The data-bound
  sweep is exercised by one added action in `divisive_normalization`, which has the CSV. The specimen tool's
  frame list gains two `drop_impact` checkpoints (ten frames, three rows).

**Contracts.** The action models above; `DataBinding` parameterised transforms; `REGISTRY_VERSION = "0.5.0"`.
Schemas regenerated.

**Files owned.** `scianim_core/storyboard.py` (actions), `scianim_core/components.py` (bindings, the `sphere`
kind, version), a new `components/solids.py` (the sphere),
`examples/families/computational_neuroscience/drop_impact/` (new),
`src/scianim/codegen/generate.py`, `src/scianim/planning/checks.py`, `src/scianim/server/app.py`
(`action_summary`), `ui/src/views/Overview.tsx` (action labels), bridge `scene.py` (tracks and `begin_*`
methods, appended after the existing ones), `components/equations.py`, `components/plots.py` (data
recompute), tests (`tests/unit/test_actions.py`, bridge `test_sweeps.py`, integration snapshot of the
extended example), `examples/`, docs, ADR-034.

**Steps.** (1) Models and validator rules with unit tests. (2) `MoveTrack` and `FadeTrack` faces with codegen
and bridge tests, including the anchored 3D move. (3) The `sphere` kind. (4) Data-bound sweeps. (5)
`transform_equation`: typesetting correspondence first (a bridge test that two occurrences of `theta` map to
two in the target and `phi` fades out), then the track. (6) The `drop_impact` example, its snapshots, a
storyboard-profile video for the author to review, and the integration assertion that the transformed
equation's checkpoint is exact. (7) ADR, guide, registry docs in the spec (section 10.4), plan line. The
example depends on B for render time only: a per-frame surface rebuild is slow under Cairo but correct, so
the example is authored at 48 cells until B lands.

**Acceptance.** `drop_impact` validates, renders its checkpoints exactly, and the sampled video frames at the
transform's end show the target equation with the emphasised term coloured; the author has seen the clip. `scianim validate` refuses
an emphasis of a symbol absent from the active equation with a message naming both equations.

**Risks.** Equation transforms are the hard part: Typst output groups glyphs per symbol only where we wrapped
them, so the grammar of what can be matched is "named symbols"; everything else is shape matching, which can
look arbitrary. The ADR should state that limit.

## 7. Package E: voiceover (postponed)

**Postponed by the author on 31 October 2026: no speech or soundtrack work for now.** The design below is kept
so that the package can be scheduled later without re-deriving it; nothing in the other packages depends on
it, and its seam (a movie-finishing hook) is added when it starts.

**Goal.** Narration becomes sound: first from audio files the author supplies, then with marks that align
actions to speech, then with a local speech engine. No path requires a paid service.

**Design, in three phases.**
1. *Files mode.* `animation.yaml` `audio: {mode: files, directory: audio}`; the author places
   `audio/<scene_id>.wav` (or `.mp3`, `.flac`). A bridge operation `probe_audio` reports durations (PyAV in
   the family environment; the control plane never decodes). `scianim timing --from-audio` proposes scene
   durations from them (padding and snapping as today). The video job carries `audio_tracks: [{scene_id,
   path, offset_seconds}]`; the seam's `finish_movie` muxes them: one AAC stream, each file placed at its
   scene's start, silence between, trimmed or padded to the movie's length, video packets copied. Subtitles
   unchanged. `scianim doctor` checks that the files exist and their rates.
2. *Marks.* An action may say `at_mark: <name>` instead of `at_seconds`; `scianim codegen` resolves it to
   seconds from the scene's mark times, which come from `audio/<scene_id>.marks.json` (name to seconds,
   produced by a forced aligner run outside SciAnim) or, without one, from word position at the style's
   speaking rate. The resolved seconds are written into the generated scene and reported; `scianim validate`
   warns when an action's time differs from its mark by more than `hold_seconds`, and `scianim timing --align`
   writes a storyboard proposal with actions moved to their marks (never in place).
3. *Local synthesis.* `audio: {mode: tts, voice: ...}` and `scianim voiceover synthesize`, a bridge operation
   behind a small `SpeechSynthesizer` interface with one bundled engine, Piper (open models, runs offline,
   declared as an optional family system requirement). It writes the files of phase 1 plus the marks of
   phase 2 where the engine reports word timing (to be confirmed for Piper; otherwise the marks come from a
   forced aligner or from word position as in phase 2), after which files mode applies. Adapters for
   hosted services can be added per family later; `manim-voiceover` is not a dependency, because the mixing is
   thirty lines of PyAV we already own and its service plug-ins assume keys.

**Contracts.** `AnimationSpec.audio: AudioSpec` (today a literal `none`; becomes a model with `mode`,
`directory`, `voice`, back-compatible with `none`), `SceneAction.at_mark`, `RenderJob.audio_tracks`,
`Operation` gains `probe_audio` and `synthesize_speech`, `VideoRecord.audio_codec`.

**Files owned.** `scianim_core/animation.py`, `scianim_core/storyboard.py` (`at_mark`, with D: this is one
field on the action base, agree the line before branching), `scianim_core/jobs.py`, new bridge `audio.py`,
`worker.py` (two operations), `video.py` (the hook body only), `src/scianim/planning/timing.py`,
`src/scianim/codegen/generate.py` (mark resolution: a separate function D does not touch), `cli.py`
(`voiceover` group, `timing` flags), `families/resolve.py` (Piper requirement check), tests: unit (audio
block, mark resolution, timing from durations), bridge (mux a synthetic tone into a one-second test movie
and probe it; durations), integration (`audio` marker: files mode end to end with a generated WAV fixture),
docs, ADR-035.

**Acceptance.** Phase 1: the divisive-normalization example with two WAV fixtures renders a movie whose
audio stream starts each clip at its scene boundary within one frame, verified by probing. Phase 2: a mark in
the orientation narration moves `sharpen` to the spoken word, and `validate` warns when the storyboard
disagrees. Phase 3: `scianim voiceover synthesize` produces the files on a machine with Piper installed; the
integration test skips when it is absent.

**Decisions for the author.** Whether Piper is the engine to bundle; whether phase 3 is wanted before the
others prove themselves.

## 8. Package F: review-to-revision loop

**Goal.** Feedback written in the review UI or with `scianim feedback add` becomes typed proposals with
diffs, so the loop brief, storyboard, render, review, revision runs without a person editing YAML.

**Design.**
- `scianim propose from-feedback <project> [--since <rev>]` reads open feedback (`FeedbackRecord` of kinds
  `region_comment`, `object_comment`, `general_comment`, `status`) and the latest inspection findings and
  produces one proposal per addressed item, deterministically and without a model, by a rule table:
  layout warnings (`outside_safe_zone`, `overlap`, `text_too_small`) become concrete patches (another anchor,
  a smaller `size_fraction`, a larger size for the role, bounded by the style's minimum); comments that name a
  registered parameter or a token become a patch with the value left as an `uncertainty` when the comment
  gives none; `needs_revision` without a usable comment becomes a proposal whose `targets` is the current
  document and whose `uncertainties` ask the question; `scientific_concern` is never auto-patched: it becomes a
  proposal flagged `touches_science` with the concern quoted. Every proposal carries `in_response_to` with the
  feedback ids and `based_on_revision`.
- A new proposal kind `revise_storyboard_from_feedback` (and `revise_spec_from_feedback` for spec-level
  comments). Applying marks the feedback addressed (a new `status` record authored `agent:feedback`), so the
  next run does not repeat it.
- The context bundle gains the open feedback and the rule-derived candidates (`scianim context --feedback`),
  so an external agent or a person can complete what the rules left open; the control plane still calls no
  model (ADR-020).
- UI: the Review view gets "Propose from feedback", which runs the generator as a job and links to the
  proposals list; the Overview lists proposals with their feedback links.

**Contracts.** `ProposalKind` additions; `FeedbackRecord.addressed_by: str | None`; a `proposals` job
operation in the runner (control plane only, no worker).

**Files owned.** new `src/scianim/agent/feedback_proposals.py`, `agent/proposals.py` (kinds, apply marks
feedback), `scianim_core/proposals.py`, `scianim_core/feedback.py`, `feedback/store.py`, `cli.py`
(`propose from-feedback`, `context --feedback`), `server/app.py` and `runner.py` (the job), `ui/src/views/
Review.tsx`, tests: unit (`test_agent_operations.py`: each rule on a fixture manifest and feedback set),
integration (`loop` marker: extend `test_agent_loop.py` with a review comment, generated proposal, apply,
re-snapshot, inspection clean), docs (guide "Review" section), ADR-036.

**Acceptance.** The agent-loop integration test runs the full circle with no network: a comment "the
equation sits outside the safe zone" produces a patch moving its anchor, applying it and re-rendering clears
the inspection finding, and the comment is marked addressed.

## 9. Package G: distribution and versioning

**Goal.** Installable from PyPI on a clean macOS or Linux machine, with a stated policy for schema and theme
changes and CI that proves the clean install.

**Design.**
- Versioning policy (the ADR): the three distributions share one version and release together; the YAML
  `schema_version` moves only on breaking changes, with `scianim migrate <project>` rewriting documents
  forward (the migration hint for unversioned sheets is the seed); published themes are immutable (ADR-010),
  a baseline minor adds tokens with defaults, a major may remove; `REGISTRY_VERSION` pins component params and
  the worker refuses a job whose registry version it does not know.
- Packaging: `uv build` for the three wheels; `family.yaml` `environment.bridge` chooses `workspace` (path
  source, the checkout) or `release` (`scianim-bridge==<version>` from PyPI); `sync_environment` writes the
  family `pyproject.toml` accordingly; `scianim doctor` reports a control-plane and bridge version mismatch.
- CI: the existing jobs plus `macos-latest` for the family-render job (fonts through a Homebrew font cask,
  to be confirmed, or the bundled fallbacks), and a nightly job that builds the wheels, installs them into a fresh virtual
  environment and runs the acceptance from the installed `scianim` (workspace init, env sync in release mode
  against the freshly built bridge wheel served from a local index, snapshot, storyboard-profile video).
- Windows stays documented as unsupported until someone needs it (Cairo and Pango wheels are the blocker).
- `docs/RELEASING.md` (checklist) and `CHANGELOG.md` (seeded from the ADR log).

**Files owned.** the three `pyproject.toml` files, `uv.lock`, `.github/workflows/*.yml`,
`families/resolve.py` (sources), `cli.py` (`migrate`), `src/scianim/migrate.py` (new), docs, ADR-037.
Tests: unit (migrate on fixture documents), CI jobs as the test.

**Acceptance.** A GitHub Actions run on macOS and Linux installs the built wheels into an empty environment
and renders the divisive-normalization checkpoints and a storyboard-profile video from the installed CLI.

**Decisions taken.** The product and distribution name is **manim8** (the author's choice): PyPI
distributions `manim8`, `manim8-core` and `manim8-bridge` (availability checked at the first release). The
import packages (`scianim`, `scianim_core`, `scianim_bridge`) and the `scianim` command keep their names until
this package decides whether to rename them in the same release (a mechanical but repository-wide change; the
ADR weighs it). Provisionally: first public version `0.1.0`, Windows documented as unsupported. The package builds and tests wheels without
publishing; publishing needs a PyPI token from the author when the time comes.

## 10. Package H: personal signature process

**Goal.** Grow `tomas_scientific` one reviewed token at a time, with stills to approve.

**Design.** `scianim style stills <project> --candidate <style.yaml> --against tomas_scientific@0.5.0
--snapshot <id> [...]` renders the named checkpoints under the pinned sheet and under the candidate (an
unpublished sheet given by path, resolved through a temporary styles directory), writes a two-column sheet
with the token diff above the pairs (reuse `review/sheet.py` and the compare machinery), and lists the layout
warnings each side produced. `scianim style publish <candidate> <name>@<version>` copies the sheet into
`styles/<name>/<version>/` with `inherits` pinned and refuses to overwrite. The Compare view already shows
two renders; it gets a "style" label when the two jobs differ only in style hash.

**Candidate tokens to put to the author first.** The emphasis orange against the blue (saturation), the
camera's starting angles, `light_azimuth_degrees`, `motion.ramp_seconds` and `hold_seconds`, the label sizes.

**Files owned.** `cli.py` (`style stills`, `style publish`), `src/scianim/styles/stills.py` (new),
`review/sheet.py` (two-column variant), `styles/tomas_scientific/`, tests: unit (two jobs with different
style hashes, publish refuses overwrite), integration (renders two snapshots and composes the sheet), ADR-038.

## 11. Working in parallel: rules

1. **Branches.** `stage/a-frame-windows`, `stage/b-raster-surfaces`, `stage/c-splicing`,
   `stage/d-actions`, `stage/e-voiceover`, `stage/f-feedback-loop`, `stage/g-distribution`,
   `stage/h-signature`, each from `claude/scianim-handoff` after the seam package merges; rebase on it daily;
   one pull request per package, squash-merged with its ADR.
2. **Merge order.** 0, then A, B, D, H, F in any order as they finish, C after A, G when the CI matrix is
   green. E is not scheduled.
3. **Shared files are append-only.** `scianim_core/jobs.py`, `storyboard.py`, `animation.py`: new fields
   with defaults, appended at the end of a class, never reordered. `cli.py`: new commands at the end of their
   group. `scene.py`: new tracks appended after `RevealTrack`, new `begin_*` methods after `begin_orbit`.
   `schemas/*.json`: regenerated in every pull request; conflicts there are resolved by regenerating, never by
   hand.
4. **Contracts first.** A package that needs a field another package owns asks for it in the seam package or
   proposes it on the integration branch before building on it; no package edits another's primary files.
5. **Tests by marker.** Each package runs its integration subset locally; the full suite runs in CI on every
   pull request; a package that adds more than three minutes to the suite says so in its ADR.
6. **Renders are evidence.** A package that changes pixels (B, D, H) attaches the checkpoints it reviewed to
   its pull request and remakes the specimen only when the baseline look is meant to change.
7. **Reserved ADR numbers** are listed in the map; a package that needs a second ADR takes the next free
   number after 038 and says so in its pull request.

## 12. Decisions taken, and what remains with the author

Taken on 31 October 2026:

- B: the two surface renderers are equals; the default stays `cairo` until the author has reviewed raster
  stills, and switching the default is a later decision outside the package.
- D: the new actions get a fifth example, `drop_impact` (a drop falling onto a water surface and rebounding,
  an analytic model labelled as such); the data-bound sweep is shown in `divisive_normalization`.
- E: postponed; no speech or soundtrack work now.
- G: the name is `manim8` for the product and the distributions; the import and command names are decided
  inside the package. H: provisional defaults as written in its section.

Nothing is required from the author before the packages branch. Later, three reviews and one credential:
the raster stills beside the Cairo ones (B), the `drop_impact` clip (D), the signature stills (H), and a PyPI
token at the first public release (G).
