# Changelog

The distributions `manim8`, `manim8-core` and `manim8-bridge` share one version. Decisions are recorded in
`docs/ARCHITECTURE_DECISIONS.md`; this file lists what changed for someone upgrading.

## Unreleased (0.1.0a0)

First version under the name manim8 (ADR-037).

- The distributions are `manim8`, `manim8-core` and `manim8-bridge`; the command `manim8` joins `scianim`.
  Import names are unchanged. A family environment created before the rename must be migrated:
  `scianim migrate <workspace>`, then `scianim family env sync <family>`.
- An installed control plane creates family environments that take the bridge from the package index at its
  own version, and carries the style sheets and example templates.
- Parallel video renders (`--workers`), with windows of frames rather than whole plays (ADR-029, ADR-031).
- A segment store shared by every render; a re-render draws only the plays a change touched; caches are keyed
  by the drawing code (ADR-033).
- A raster renderer for surfaces beside the Cairo one, `--surface-renderer raster` (ADR-032).
- Scene actions `move_object`, `fade_object`, `transform_equation`, data-bound sweeps, the `sphere` kind and the
  `drop_impact` example (ADR-034).
- `scianim propose from-feedback`: review feedback becomes proposals by rules (ADR-036).
- `scianim style stills` and `style publish` for growing a personal theme (ADR-038).
- Baseline theme `default@0.5.0`, line and wash after Keenan Crane (ADR-030).

Fixed:

- A track still moving near a scene's end (an orbit to the end of the clip) stopped `motion.transition_seconds`
  early, at speed: generated scenes advanced tracks only to the start of the end-of-scene fade, even in the last
  scene, which keeps its objects and never fades. The last scene's tracks now run to its end, and a scene that
  fades carries its running tracks through the fade. The camera of the Gabor and `drop_impact` clips now comes
  to rest at the clip's end. Regenerate scenes with `scianim codegen`.
- Status and manifest files are written atomically, so the review server never reads one half written.
- A re-render redrew every play after the first sweep that moved a plot marker, and after any `move_object`,
  even when nothing had changed: those updates shifted points frame by frame, so a drawn play ended a rounding
  away from a cached one and the next play's hash missed the segment store. Moves and markers are now placed
  exactly, and an unchanged re-render draws nothing (ADR-039). Play records carry their content hash.
