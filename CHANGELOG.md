# Changelog

The distributions `manim8`, `manim8-core` and `manim8-bridge` share one version. Decisions are recorded in
`docs/ARCHITECTURE_DECISIONS.md`; this file lists what changed for someone upgrading.

## Unreleased

- Stops (ADR-045): a storyboard snapshot may be marked `stop: true`, with an optional `label` and
  `stop_through`, to say that a player may hold the clip there until the presenter's next key. The clip stays
  one movie and the fields change no picture, no generated code and no scene fingerprint. Validation refuses a
  stop with anything revealing, moving or fading in the 0.3 s before it (an action may start at it), on a
  scene's first frame or the clip's last, within 0.5 s of another stop, where its checkpoint would be
  approximate (a `dt` updater in a custom builder or a project module it imports, or a Manim helper such as
  `always_rotate` that installs one), or while an orbit turns across it (unless `stop_through` names the orbit,
  which warns `stop_freezes_camera`). It warns `stop_on_motion_start` for an action that starts on the stop's
  own frame, whose first frame the hold shows (a deck that checks the pixels, such as lecturekit, refuses that
  stop), and for a custom builder that installs other updaters. After a video job the manifest's `result.stops` lists each stop's frame, time, label,
  notes, rests in frames and frozen orbits; a final render fails when a player could not hold a stop exactly,
  any other profile warns. `CheckpointRecord.frame_index` gives the movie frame of every still. `scianim timing`
  lists the parts between stops, and the review sheet marks them. Storyboards with stops need this version of
  `manim8-core`; schemas stay at 1.0.

## 0.1.0a0 (9 November 2026, commit d37489e)

First version under the name manim8 (ADR-037). It is released as commit `d37489e`, to be tagged `v0.1.0a0`; the README's install
section gives the uv and pip commands. PyPI wheels may follow.

- The distributions are `manim8`, `manim8-core` and `manim8-bridge`; the command `manim8` joins `scianim`.
  Import names are unchanged. A family environment created before the rename must be migrated:
  `scianim migrate <workspace>`, then `scianim family env sync <family>`.
- An installed control plane carries the style sheets and example templates. Installed from a wheel, it creates
  family environments that take the bridge from the package index at its own version; installed from git, from
  its own commit (below).
- Parallel video renders (`--workers`), with windows of frames rather than whole plays (ADR-029, ADR-031).
- A segment store shared by every render; a re-render draws only the plays a change touched; caches are keyed
  by the drawing code (ADR-033).
- A raster renderer for surfaces beside the Cairo one, `--surface-renderer raster` (ADR-032).
- Scene actions `move_object`, `fade_object`, `transform_equation`, data-bound sweeps, the `sphere` kind and the
  `drop_impact` example (ADR-034).
- `scianim propose from-feedback`: review feedback becomes proposals by rules (ADR-036).
- `scianim style stills` and `style publish` for growing a personal theme (ADR-038).
- Baseline theme `default@0.5.0`, line and wash after Keenan Crane (ADR-030).
- `SCIANIM_HASH_TRACE=1` makes a render write the inputs of Manim's per-play hash beside its job, to find why a
  play was drawn again instead of coming from the segment store (ADR-039).
- A pattern library (ADR-040, `docs/ANIMATION_PATTERNS.md`): 19 named ways of making a mechanism move, from a
  survey of the 3Blue1Brown videos repository and from studies on learning from animation, each with its beats,
  usual durations, pitfalls, status and a recipe scene from the examples. `scianim patterns list|show|check`;
  the agent's context bundle gains a Patterns section and `patterns.json`. Storyboard scenes may name the
  patterns they stage (`patterns: [sweep_with_readout]`); validation checks the ids. The wheel carries the
  library. `tools/survey_corpus.py` reproduces the survey.
- An `emphasize` action (ADR-041): a box in the emphasis ink around an object or symbols of its equation,
  optionally travelling from a symbol to the object it names, or a pulse of the symbols. `fade_object` takes
  `ink`, a fraction of full ink, to dim the context and restore it.
- Tutorials (`docs/tutorials/`): ten minutes to a picture, and change one thing. Each page runs in CI as written.
- Cache keys follow the fonts (ADR-044): the font families the family environment's Pango finds, under the
  fontconfig the render runs with, enter the job cache key, the segment store's key and Manim's media
  directory. A job rendered where a style's faces were missing no longer answers a render that has them. The
  first render after the upgrade is not a cache hit.
- The manim8 agent skill (ADR-042): `.claude/skills/manim8/SKILL.md`, a playbook for an agent that drives the
  package from a brief to a final clip, asking at each stage; `scianim skill install [--to DIR]` puts it where an
  agent finds it outside the checkout. The wheel carries it.
- For another tool that renders a project (ADR-043; lecturekit is the first): `scianim render --json` and
  `scianim snapshot --json` print the job's `ArtifactManifest` as the only output on stdout, the cached job's with
  `cache_hit` true, and nothing on a failure; human output goes to stderr. `--style name@version` renders one job,
  of the working copy or of a revision, under another published style; it enters the cache key and
  `job.resolved_style`, and a style that would change the generated timing is refused.
- Family environments take `manim8-bridge` and `manim8-core` from where the control plane came from: a
  control plane installed from git pins them by uv git sources to its own commit (read from its PEP 610
  `direct_url.json`), a checkout uses its `packages/`, any other install the package index. `SCIANIM_BRIDGE_SOURCE`
  (`index`, `git:<url>@<ref>`, `path:<packages dir>`) overrides it. `scianim family env sync` rewrites path
  sources that point at no package (a workspace moved or cloned), and `--rewrite-sources` rewrites them on request;
  `scianim doctor` reports them.
- manim8 depends on the `uv` package and uses its binary when `uv` is not on PATH, so a pip install can sync
  family environments.
- `scianim workspace init` writes a `.gitignore` for `renders/`, `.scianim/`, `.venv/` and Manim's `media/`.
- `.github/scripts/git_install_check.sh`, run in CI: a non-editable git install, a family synced from the same
  commit, and `render --json` fresh, cached and under `--style`.
- `tomas_scientific@0.5.1` asks for a rest of one second between two motions of one object
  (`motion.hold_seconds`), after the survey's median pause; the examples pin it. The halves of a ballistic arc
  (`ease_out_quad` then `ease_in_quad`) need no rest between them.

Fixed:

- Validation and other messages lost text in square brackets, so a slug pattern printed as `^{0,63}$`; messages
  are now escaped before rich prints them.
- `family env sync` run through `uv run` warned that the control plane's active virtual environment did not
  match the family's; the family's uv commands no longer see `VIRTUAL_ENV`.

- `scianim context` failed on a storyboard with moves, fades or transforms (it read every action other than an
  orbit or an axes fade as a sweep); the bundle and the review server now share one action summary.
- Fades started from full ink whatever the object showed; they start from its current ink, so a dimmed object
  fades out from its dimmed level at the end of a scene.
- A track still moving near a scene's end (an orbit to the end of the clip) stopped `motion.transition_seconds`
  early, at speed: generated scenes advanced tracks only to the start of the end-of-scene fade, even in the last
  scene, which keeps its objects and never fades. The last scene's tracks now run to its end, and a scene that
  fades carries its running tracks through the fade. The camera of the Gabor and `drop_impact` clips now comes
  to rest at the clip's end. Regenerate scenes with `scianim codegen`.
- Status and manifest files are written atomically, so the review server never reads one half written.
- A re-render redrew most of a clip even when nothing had changed: after a sweep that moved a plot marker, a
  `move_object`, an orbit, a raster sweep or a readout beside a transforming equation, a drawn play and a cached
  one left different state, and some state (the raster surface's painting time, Manim's global config through a
  layout function, and on recent Python releases the order Manim serializes a function's globals in, which
  follows the per-process string-hash seed) differed between processes, so the next play's hash missed the
  segment store. Workers now run with `PYTHONHASHSEED=0`. Every play
  now leaves the same state however Manim executes it, and an unchanged re-render draws nothing (ADR-039). Play
  records carry their content hash.
- An object revealed while a `move_object` moved it stalled during the reveal and ended short of its target:
  reveals were Manim `FadeIn` transforms, which reset positions every frame. A reveal is now an ink ramp with the
  same opacities. In `drop_impact` the smaller drop now rises to the storyboard's height; re-render it.
