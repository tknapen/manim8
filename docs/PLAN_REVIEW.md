# Review of the SciAnim Studio plan

**Status:** review notes, 26 October 2026
**Reviewed:** `docs/PROJECT_SPEC.md` 0.1, `docs/IMPLEMENTATION_PLAN.md`, `AGENTS.md`, and the `examples/` fixtures
**Method:** every claim below about what Manim can do was checked against the source of manim 0.22.0 and manim-voiceover 0.4.0 (wheels downloaded from PyPI; the documentation site was unreachable from the review environment). Line references are to those versions.

## Summary

The architecture is sound: typed YAML as the contract, a process boundary around Manim, per-family `uv` environments, deliberate checkpoints, immutable revisions. Nothing below reopens those choices. The recommendations concern where the leverage is and what Manim already provides that the plan proposes to rebuild.

1. Make the component registry the center of the design, with a typed parameter schema per object `kind`, from Milestone 0.
2. Take checkpoints from inside the real animation flow instead of a parallel `build_snapshot` constructor. Manim's fast-forward mode and `get_frame()` make this cheap.
3. Map storyboard scenes to Manim sections. `--save_sections` and per-section `skip_animations` give scene-level incremental rendering almost for free.
4. Add narration to the storyboard schema now and derive scene durations from it. Subtitles and voiceover alignment already exist in Manim and manim-voiceover.
5. Emit a layout report (normalized bounding boxes per named object) with every snapshot, and use it for machine-checkable visual QA and object-anchored feedback.
6. Promote equations and data bindings from prose to typed fields.
7. Prefer Typst over LaTeX as the default equation engine. It removes the TeX distribution from the clean-machine story.
8. Split the Python package into a control-plane distribution and a minimal render bridge, and declare system requirements per family.

## 1. The component registry is the product

The storyboard's `objects[].kind` values (`plot`, `equation_label`, `equation`, `comparison_plot` in the example) are the interface shared by the agent that writes storyboards, the validator, and the code that renders. The spec names a component library (section 10.4) but leaves `kind` undefined, defers components to Milestone 5, and calls them "optional conveniences". That ordering puts the most reusable part last, and it means the UI (Milestone 3) and the video pipeline (Milestone 4) are built before anything exercises the storyboard vocabulary.

Proposal: a registry in which each `kind` has a Pydantic parameter model (so `scianim validate` checks object parameters, not only the presence of a `kind`), a declared list of the style roles it consumes, a Manim implementation in the render bridge, and named-state support. Scientific explainers compose a small set of primitives: axes with curves and bands, an equation with term highlighting, a side-by-side comparison with shared scales, a schematic population or network, callouts, captions. When most of a storyboard renders from registered components, output is more reliable, cache keys are more precise (component version plus parameters), and the agent's job shrinks to composition plus occasional bespoke code. Bespoke code stays allowed, but it is the escape hatch and must implement the checkpoint and layout-report protocol described below.

Milestones: registry schema in 0, the first three components in 2 (the example needs them anyway), the rest spread over 4 and 5.

## 2. Checkpoints from the animation flow

Section 8.2 proposes that generated scenes implement `build_snapshot(state_id)`, constructing each named state independently of the animation. This duplicates the state logic: every object placement exists once in `construct()` and once per snapshot builder, and the two drift. A snapshot built that way is not evidence about the video.

What Manim provides, verified in 0.22.0:

- `-s` / `--save_last_frame` is documented as "Fast-forward animations and save the last frame as PNG" (`manim/cli/render/render_options.py`). In fast-forward, `Scene.get_time_progression` returns a single time step `[run_time]` per `play()` call (`manim/scene/scene.py`, lines 1125 to 1128), so a full scene is traversed in one interpolation step per animation with no frames encoded. The remaining cost is object construction such as typesetting.
- `CairoRenderer.get_frame()` returns the current frame as a height by width by 3 array at any point (`manim/renderer/cairo_renderer.py`, lines 186 to 195), and `update_frame()` redraws it from the scene's current mobjects.
- `-n` / `--from_animation_number a,b` bounds the animations rendered. `CairoRenderer.update_skipping_status` skips plays before `a` and ends the scene after `b` (lines 261 to 283). Combined with `-s`, this yields the frame at any animation boundary with no code at all.

Proposal: a bridge helper, roughly `checkpoint(scene, "excitation_visible")`, that the generated `construct()` calls at the named moments. In snapshot mode the worker runs the scene fast-forwarded and the helper writes a PNG plus metadata each time it is reached. In video mode the helper records the frame index and otherwise does nothing. One code path produces all checkpoints in one pass, and the storyboard's `snapshots[].id` list validates against the markers present in the code.

One caveat, also verified: in fast-forward each `play()` advances in a single step with `dt = run_time`, and the trailing `update_mobjects(0)` call is skipped (`scene.py`, lines 1384 to 1417). Content driven by `ValueTracker` and `always_redraw` ends in the correct state. Updaters that integrate `dt` do not. The bridge should detect `dt`-dependent updaters and either warn or route that checkpoint to the spec's existing "sampled video frame" path. This is narrower than the spec's statement that the last-frame option cannot render arbitrary states "without additional code". The additional code is a small helper, not a parallel constructor.

## 3. Scenes as Manim sections

Section 11.3 and Milestone 4 ask for scene-level invalidation implemented by the control plane. Manim already has the unit, verified:

- `Scene.next_section(name, section_type, skip_animations)` (`manim/scene/scene.py`, lines 378 to 388).
- `--save_sections` writes one video per section and a JSON index with each section's name, type, relative path and probed video metadata (`manim/scene/scene_file_writer.py`, `next_section` at lines 326 to 348 and `combine_to_section_videos` at lines 966 to 984).
- `skip_animations=True` on a section skips rendering its animations entirely.

Proposal: the code generator emits `next_section(scene_id)` at each storyboard scene boundary. Draft and final renders use `--save_sections`. The manifest stores the section index, which gives per-scene duration verification against the storyboard without extra probing. When the dependency graph marks a scene unchanged, the worker re-runs the file with `skip_animations=True` for that section and concatenates its cached section video with the freshly rendered ones. Hard-milestone verification becomes a check on cumulative section durations.

A related point: Manim caches per `play()` call using `get_hash_from_play_call` (`manim/utils/hashing.py`), keyed on the scene, camera, animations, current mobjects, backend, encoder fingerprint and renderer state. If the worker gives each project revision a stable `media_dir`, this cache operates underneath the scene-level cache. The spec should state whether it relies on it. Disabling it (`disable_caching`) discards free incremental rendering.

## 4. Narration first

The spec defers audio to "Later" and proposes a separate schema when narration arrives (section 17.8). The gap is not audio but timing. An explainer's pacing follows what is being said, and the storyboard's `start_seconds` and `end_seconds` are hand-typed numbers with nothing to anchor them. A `narration` field per scene (plain text, optionally with named marks) costs nothing now and is hard to retrofit once storyboards exist.

With `audio: none` it already provides:

- A reviewable script next to each scene, which is what a scientist actually edits.
- A default duration per scene from a words-per-minute estimate, reconciled against hard milestones by the planner. Impossible combinations surface as validation errors rather than as a rushed scene.
- Subtitles. Manim writes an SRT file from `Scene.add_subcaption` or `play(..., subcaption=...)` (`manim/scene/scene.py`, lines 1726 to 1766; the file is written in `SceneFileWriter.finish`).

Later it provides alignment. manim-voiceover 0.4.0 offers `VoiceoverScene.voiceover(text)` as a context manager yielding a tracker with `duration`, `get_remaining_duration()` and `time_until_bookmark(mark)`. `wait_until_bookmark` aligns an animation to a word in the narration. Word boundaries come from Whisper transcription when the speech service does not supply them. Services include an offline `pyttsx3` backend, a human-voice `recorder`, and several cloud providers. It depends on Pydantic v2, so it coexists with the bridge. Marks in the `narration` field map directly onto its bookmarks.

## 5. Layout reports and object-anchored feedback

Section 9.2 anchors feedback to normalized rectangles, and section 15.2 lists visual QA checks (clipping, legibility, consistent roles) as human review. Both improve if the worker emits, next to each checkpoint PNG, the bounding box of every storyboard-named object in normalized coordinates, with text content and rendered size in pixels at output resolution. Manim exposes this directly (`Mobject.get_center`, `get_corner`, `get_critical_point`, `width`, `height` in `manim/mobject/mobject.py`).

Consequences:

- Safe-zone violations, overlaps between labeled objects, and text below `minimum_body_px_at_1080p` become deterministic checks run by the worker, with no vision model involved. They belong in the artifact manifest as warnings.
- The UI can resolve a click to an object ID, so a feedback record says `object: pool_label` rather than only a rectangle. The agent then edits one object's parameters instead of inferring intent from pixels.
- The agent can self-check before asking for review by comparing the report and the image against the snapshot `description` and listing discrepancies. Section 7.2 and `AGENTS.md` should add this step; the plan currently treats the agent as blind to its own output.
- A `scianim compare revA revB` command can report which objects moved or changed, not only a pixel diff.

## 6. Equations and data bindings as typed fields

In the example the equation lives in prose: `text: "Illustrate the schematic equation r = E / (sigma + P)."` The invariant in section 6.2, never silently alter a supplied equation, cannot be checked against prose. Add an `equations` section to `animation.yaml` with `id`, the typeset source (`latex` or `typst`), a `symbols` map from each symbol to its meaning and optional unit, and an optional source locator. Storyboard objects then reference `equation: schematic_equation` and `highlight: [P]`, and the renderer must typeset exactly the stored string. Term highlighting gets stable targets, and a changed equation becomes a detectable `spec_change` that re-requires content approval (section 9.3).

Likewise `data_source: responses` on a plot does not say which columns are plotted. Add an encoding (`x`, `y`, `group`, `error`) and an explicit `transform` list (filter, normalize, derive) on the binding. This satisfies the requirement that transformations be explicit and logged by construction rather than by discipline. Vega-Lite's encoding vocabulary is a reasonable model because language models already know it.

## 7. Typst as the default equation engine

The spec lists "a supported LaTeX environment" among prerequisites, and both style files set `typography.equation.engine: latex`. A TeX distribution is the heaviest and least reproducible dependency in the stack. Manim's LaTeX path shells out to a `latex`-family compiler and to `dvisvgm` 2.4 or newer (`manim/utils/tex_file_writing.py`, lines 140 to 260), and `manim checkhealth` checks for both binaries. None of this can be pinned by `uv.lock`.

Manim 0.22.0 ships `Typst` and `MathTypst` mobjects (`manim/mobject/text/typst_mobject.py`, lines 274 and 763) behind a `typst` extra that depends on the `typst` PyPI package (wheel metadata). That puts the typesetter inside the Python environment and therefore inside the family lockfile. Proposal: make `typst` the default engine in `styles/default/style.yaml`, keep `latex` as a per-family opt-in for notation Typst cannot express, and have `doctor` report which engine a family resolves. As `AGENTS.md` already demands for the stack as a whole, this must be tested on a clean machine before it is promised.

On the same theme, Manim 0.22.0 encodes video through PyAV (`av>=15` in the wheel metadata; `import av` in `manim/scene/scene_file_writer.py` and `manim/scene/video_segment_encoder.py`). Its configuration no longer has an ffmpeg executable option and a search of the package finds no ffmpeg invocation. `doctor` should check for PyAV inside the family environment rather than for a system `ffmpeg`, which is then needed only if the control plane uses the CLI for frame extraction, and PyAV can do that as well.

## 8. Package split and system requirements

Section 4.2 says the family `pyproject.toml` depends on "the `scianim` rendering bridge version", but section 4 shows a single package. If families depend on the distribution that carries FastAPI, SQLAlchemy and the CLI, every family environment inherits the control plane's dependency graph, which defeats the isolation goal. Publish two distributions from the monorepo: `scianim` (control plane) and `scianim-bridge` (style-token loading, the checkpoint helper, the layout report, manifest emission), with the bridge depending only on Manim and Pydantic.

`environment.manager: uv` captures Python packages. Fonts, Pango and Cairo libraries, SoX (required by manim-voiceover's `sox` dependency), and a TeX distribution where used are system-level. Add `system_requirements` to `family.yaml` (binaries with minimum versions, font files with hashes, optionally a container image digest) so `doctor` checks per family and an exported bundle tells a recipient what to install. Allowing `manager: docker` or `apptainer` as an alternative is the only route to full reproducibility for families that keep LaTeX.

## Smaller items

- Cache keys (section 8.3) should include the renderer configuration that changes pixels or bytes: `renderer` (cairo or opengl), `tex_template` and `tex_template_file`, `pixel_format`, `video_codec`, `video_encoder_options`, `seed`, `quality`, and the resolved font files. All are `ManimConfig` options (`manim/_config/utils.py`, `_OPTS`).
- Milestone order: the agent loop (Milestone 5) is the first test of whether the YAML vocabulary suits a language model, yet it follows the UI and video pipeline, which harden around that vocabulary. Add a short step after Milestone 2: have a coding agent produce the example's scene code from the storyboard through the CLI, and record where the schema was awkward, before Milestone 3 begins.
- A static review sheet per revision (an HTML contact sheet of checkpoints with the storyboard text and the layout report) is cheap to generate in Milestone 2, gives most of the review value before any React work, and doubles as a bundle artifact. The interactive UI then adds annotation and comparison on top.
- Section 14 makes the CLI canonical, but annotations exist only in the UI (Milestone 3). Make `feedback/*.yaml` the canonical store, with the UI as an editor, so an agent can read and write feedback without a browser.
- Revisions (section 11.1) reimplement versioning next to Git. Using Git plumbing for project revisions (one commit per revision, tags for approvals) would give diffs, lineage and bundles for free. The cost is coupling the workspace to Git and complicating the story for users who do not use it. It deserves an ADR either way.
- Golden image tests (section 15.2): specify the comparison metric (SSIM or a perceptual hash with a threshold) and the platform on which goldens are generated. Otherwise the tests will be flaky across Cairo versions and font stacks.
- The repository's `.gitignore` is the GitHub Python template. It ignores `*.manifest`, `*.spec`, `*.log` and `lib/`. The spec uses manifests everywhere. Name them `manifest.json` or `*.manifest.yaml`, never with a bare `.manifest` extension, or Git will silently drop them.

## What should stay as it is

The process boundary around Manim, per-family lockfiles with `.venv` excluded, immutable revisions with approvals bound to hashes, the hard versus preferred distinction on constraints, normalized feedback coordinates, loopback-only serving, and the refusal to treat PDF text as instructions are all right and should not be reopened.

## Verified facts

| Claim | Where (manim 0.22.0 unless noted) |
|---|---|
| `next_section(name, section_type, skip_animations)` | `manim/scene/scene.py` 378 to 388 |
| `--save_sections` writes per-section videos and a JSON index | `manim/scene/scene_file_writer.py` 326 to 348 and 966 to 984 |
| Fast-forward uses a single time step per `play()` | `manim/scene/scene.py` 1125 to 1128 |
| Trailing `update_mobjects(0)` is skipped when fast-forwarding | `manim/scene/scene.py` 1412 |
| `-s` fast-forwards and saves the last frame; `-n a,b` bounds the animations rendered | `manim/cli/render/render_options.py` 137 to 178; `manim/renderer/cairo_renderer.py` 261 to 283 |
| `get_frame()` returns the current frame as an array | `manim/renderer/cairo_renderer.py` 186 to 195 |
| Subcaptions via `add_subcaption` and `play(subcaption=...)` | `manim/scene/scene.py` 1726 to 1766 |
| `Typst` and `MathTypst` mobjects behind a `typst` extra | `manim/mobject/text/typst_mobject.py` 274 and 763; wheel metadata |
| LaTeX path needs a `latex`-family compiler and `dvisvgm` 2.4 or newer | `manim/utils/tex_file_writing.py` 140 to 260; `manim/cli/checkhealth/checks.py` 175 and 197 |
| Encoding through PyAV; no ffmpeg binary invoked | wheel metadata (`av>=15`); search of the package |
| Per-`play()` cache key | `manim/utils/hashing.py`, `get_hash_from_play_call` |
| `ManimConfig` options include `seed`, `tex_template`, `renderer`, `video_codec`, `video_encoder_options`, `pixel_format` | `manim/_config/utils.py`, `_OPTS` |
| manim-voiceover: `voiceover()` tracker with `duration` and bookmarks, Whisper word boundaries, `pyttsx3` and `recorder` services, Pydantic v2 | manim-voiceover 0.4.0: `voiceover_scene.py`, `tracker.py`, `services/base.py`, wheel metadata |
