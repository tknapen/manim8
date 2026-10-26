# SciAnim Studio — implementation plan for coding agents

**Purpose:** Translate the complete [project specification](PROJECT_SPEC.md) (version 0.2) into small, testable implementation units. This document is a task checklist, not a claim that the package has already been implemented. The rationale for the 0.2 changes is in [`PLAN_REVIEW.md`](PLAN_REVIEW.md); decisions are recorded in [`ARCHITECTURE_DECISIONS.md`](ARCHITECTURE_DECISIONS.md).

## Prioritization rules

1. Implement bottom-up: typed contracts → style and environment resolution → component registry and code generation → in-flow checkpoints with layout reports → static review sheet → web review → sections and full video → agent automation → portable bundles.
2. The component registry and `scianim codegen` for registered kinds precede the web UI. Nothing exercises the storyboard vocabulary until code renders from it.
3. Do not build several partially connected UIs before a named checkpoint renders from the real animation flow.
4. Every milestone leaves a usable CLI operation and a regression test.
5. Keep Manim and specialized scientific packages in isolated family environments. Families depend on `scianim-bridge`, never on `scianim`.
6. Record technical decisions that materially change public contracts in `ARCHITECTURE_DECISIONS.md`.

## Status (26 October 2026)

Milestones 0, 1 and 2 are implemented and pass their acceptance commands on the example project (see the README's
developer section for the exact commands), and the hierarchy decisions of ADR-010 to ADR-014 are implemented:
versioned styles, the nearest-family rule with groups, workspaces with read-only examples, write-once revisions,
`asset://` sources and family components. Known gaps: `environment.manager` values other than `uv` are rejected
rather than implemented; the `custom` kind is validated but has no rendered example; the job log is per job
rather than append-only across jobs; approvals, feedback files and the SQLite index are Milestone 3. Milestone 2.5
(the agent dry run) is complete and documented in [`FRICTION_LOG_M2_5.md`](FRICTION_LOG_M2_5.md). Milestone 3
(the local review UI: API, SQLite index, feedback files, comparison, React front end) is complete (ADR-018).
Milestone 4 (frame-exact timing, draft and final video with sections, subtitles, probes and sampled frames) is
complete except for section splicing (ADR-019). Milestone 5 (source adapters, context bundles, proposals,
self-inspection, four more kinds) is complete except for voiceover (ADR-020). Milestone 6 (bundles and the user
guide) is complete (ADR-021). Open items across milestones: section splicing (ADR-019) and voiceover (ADR-020).

## Milestone 0 — repository and contracts

**Build tasks**

- [x] Bootstrap a `uv` workspace with three distributions: `scianim-core` (`packages/scianim_core`, Pydantic only), `scianim` (control plane, `src/scianim`) and `scianim-bridge` (`packages/scianim_bridge`, Manim side). Python 3.12+, Ruff, pytest, type checking, simple CI.
- [x] Pydantic models in `scianim-core` for `animation.yaml` (including `equations`), `storyboard.yaml` (including `narration`, object `params`, `data` bindings with `encoding` and `transforms`, `equation` references), `style.yaml` (including `typography.equation.engine` and `motion.narration_words_per_minute`) and `family.yaml` (including `system_requirements`), all with `schema_version`.
- [x] Component registry in `scianim-core`: `kind` → parameter model, consumed roles, data and equation requirements, version. Object `params` validate against the registry; `kind: custom` requires a `builder` reference and never code.
- [x] Contracts for the worker protocol: render job payload, checkpoint record with layout report and fidelity, artifact `manifest.json`.
- [x] Emit JSON Schemas into `schemas/`; check generated schemas are reproducible.
- [x] Reject unknown core fields, invalid aspect ratios, negative durations, missing hard milestones, path escapes, invalid color tokens, unknown component kinds, invalid `params`, unknown data sources and equation IDs.
- [x] `scianim validate <file-or-project>` with actionable errors and nonzero status on failure; project mode runs the cross-file checks.
- [x] `scianim doctor`: `uv`, Python version, writable workspace, fonts; per family: PyAV and the equation engine (`typst` package, or `latex` plus `dvisvgm`) inside the family environment, and the declared `system_requirements`.
- [x] Load and validate the included examples.

**Acceptance**

```bash
E=examples/families/computational_neuroscience/divisive_normalization
scianim validate $E/animation.yaml $E/storyboard.yaml $E     # templates validate in place (read-only)
scianim workspace init workspace --with-example               # instances live in a workspace
scianim doctor --project workspace/families/computational_neuroscience/divisive_normalization
pytest tests/unit
```

Validation must not import Manim in the current process. Negative tests: inconsistent aspect ratio, missing source, unknown key, unknown component kind, bad `params`, equation reference to a missing ID, snapshot outside its scene.

**Deliverables:** CLI, typed models, registry, schema files, reproducible test run and concise developer setup instructions.

## Milestone 1 — theme and family dependency boundary

**Build tasks**

- [x] Token cascade: default → theme version chain → family → group → project (allowlisted) → scene (allowlisted). Deep merge; unknown token paths rejected; no hardcoded fallback for missing tokens.
- [x] `ResolvedStyle` export: every token, provenance per token, content hash; `scianim style resolve`.
- [x] Family discovery: nearest `family.yaml` is authoritative, `family:` optional, `group.yaml` layers, explicit child families, duplicate ids rejected.
- [x] Versioned style directories (`<name>/<version>/style.yaml`) with pinned inheritance; `scianim style list`.
- [x] Baseline theme `default@0.2.0` (Twin Ink) with philosophy and specimen plate; font fallback resolution reported in the manifest; Typst math font and LaTeX packages from tokens.
- [x] Workspaces: `workspace init|list`, `family init`, `project init`, read-only examples as templates.
- [x] `asset://` sources from family and workspace `assets/`; family `components/` on the worker path.
- [x] `scianim family env sync <family>` through `uv sync` in a subprocess, with clear errors for absent locks or unsupported platforms; check `system_requirements`.
- [x] Worker launch via subprocess from the family `.venv`: structured job file in, JSON result out; capture stdout, stderr, exit status and elapsed time.
- [x] Test that the control-plane process never imports `manim` or `scianim_bridge`, and that installing a specialized dependency into a family does not alter control-plane dependencies.

**Acceptance:** Two families with different pinned dependencies can be resolved, synchronized and inspected separately. The parent process never imports Manim.

## Milestone 2 — named checkpoints from the animation flow

**Build tasks**

- [x] `scianim-bridge`: `SnapshotScene` base with object registration; `checkpoint(scene, id, expected_time)` helper that in snapshot mode redraws, captures via `renderer.get_frame()`, writes a PNG and a record, and in video mode records the frame index.
- [x] Snapshot mode runs the scene fast-forwarded (Manim `format=png` semantics) so every checkpoint comes from one pass.
- [x] Fidelity check: detect time-based updaters at each checkpoint and mark `fidelity: approximate`.
- [x] Layout report per checkpoint: normalized bounding boxes per registered object, text and rendered height; warnings `outside_safe_zone`, `text_too_small`, `overlap`.
- [x] Registered components implemented in the bridge from style tokens only: `scientific_plot`, `equation_block` (Typst by default), `comparison_plot`, `equation_label`, `text_caption`.
- [x] `scianim codegen <project>`: deterministic scene module from a storyboard of registered kinds; one `next_section` per scene; reveals in order; `checkpoint()` at each snapshot's requested time; `custom` objects call named builders.
- [x] Static parity check: storyboard snapshot IDs equal the `checkpoint()` literals in the scene module.
- [x] Content-addressed cache key: resolved style hash, scene code, data files, snapshot definitions, registry version, bridge and Manim versions, lock hash, renderer configuration.
- [x] `scianim snapshot <project> --all` and `--id`; `manifest.json` per job with inputs, tool versions and checkpoint records; append-only job log.
- [x] `scianim review-sheet <project>`: static HTML contact sheet of checkpoints with storyboard text, narration and layout warnings.
- [x] A style token change invalidates the correct cached stills.

**Acceptance:** Two PNGs produced by Manim (not mockups) from the example YAML through `codegen` and `snapshot`, plus `manifest.json` with layout reports. Changing `palette.primary_signal` yields an observable change in the corresponding rendering and a new cache key.

## Milestone 2.5 — agent dry run

- [x] A coding agent takes the example from brief to storyboard to rendered checkpoints through the CLI alone, without schema changes during the run.
- [x] Record every point where the YAML vocabulary, registry or CLI was awkward; adjust schemas and registry before Milestone 3.

**Acceptance:** A storyboard written by the agent validates and renders; the friction log is in `docs/`.

**Result:** the dry run produced a second example, `examples/families/computational_neuroscience/prf_tuning`,
and [`FRICTION_LOG_M2_5.md`](FRICTION_LOG_M2_5.md). The first pass rendered with the Milestone 2 registry but
exposed eight friction points; the registry gained `function_plot`, relational placement, timed reveals and
`scianim registry` (ADR-016), after which the storyboard rendered without layout warnings. Two items are
deferred (see the log).

## Milestone 3 — local review UI

**Build tasks**

- [x] FastAPI project listing / revision / jobs / artifact endpoints (`src/scianim/server/app.py`, OpenAPI at `/docs`).
- [x] File-based write-once revisions (`revision create|list`, `snapshot --revision`); project-local renders with `scianim clean`.
- [x] SQLite index of projects, revisions, jobs, annotations and approvals; files remain canonical (`scianim index rebuild`).
- [x] `feedback/*.yaml` as the canonical annotation store; `scianim feedback add|status|list`; the UI reads and writes the same records.
- [x] React/TypeScript frontend: family/project navigation, filmstrip and large viewer, kind labels (`manim_checkpoint`, `sampled_video_frame`, `storyboard_schematic`).
- [x] Region annotations in normalized coordinates plus object resolution from the layout report (`object_id`).
- [x] Before/after comparison; `scianim compare` for image diffs and moved or changed objects; statuses `approved`, `needs revision`, `scientific concern`.
- [x] Job polling, logs, retry/cancel; nonblocking render requests.
- [x] Record how a change invalidates stale previews and approvals (ADR-018: approvals bind to the image hash of an immutable revision; the compare tools show whether a later render is identical).

**Acceptance:** A browser user can view a generated snapshot, click an object or mark a region, submit a request, and retrieve the annotation bound to the correct immutable revision after restarting the server.

**Result:** `tests/unit/test_review_api.py` covers the records, the index, the comparison and the API without
rendering; `tests/integration/test_review_server.py` renders through the API, annotates an object, approves a
frozen revision and reads everything back after a restart; `tests/ui/e2e.mjs` drives the built UI in Chromium
through the same steps. Not built: the storyboard editor (view C) and video review (view E), which wait for
Milestone 4; project creation from the browser, which waits for Milestone 5.

## Milestone 4 — storyboard timing and video rendering

**Build tasks**

- [x] Validate scene intervals, milestones and overlap policy; propose durations from narration at `narration_words_per_minute` and report conflicts with hard milestones (`scianim timing`, never in place).
- [x] Draft and final renders with `--save_sections`; store the section index; verify per-scene and total durations against the storyboard (`scianim render`, `TimingReport` in the manifest, ADR-019).
- [x] Subtitles: emit Manim subcaptions from `narration` so an SRT accompanies drafts and finals.
- [x] Verify width, height, fps and duration/frame count via media probe (PyAV in the worker; frame counts by decoding).
- [x] Sampled video frames at requested times, for comments and for checkpoints marked `approximate` (`sampled_video_frame` records at every checkpoint's actual time plus `--sample id=seconds`).
- [ ] Scene-level incremental rendering: `skip_animations=True` on unchanged sections, concatenate cached section videos; keep Manim's per-`play()` cache enabled through a stable `media_dir`. *Partly:* the per-play cache is on under `.scianim/media/<revision>` and `scianim stale` reports the scenes a change touches; section splicing is deferred (ADR-019).
- [x] Save stderr and logs on failure; a failed job can never mark a revision approved (feedback refuses non-succeeded renders).

**Acceptance:** The example produces a 720p draft and a 1920×1080, 30 fps, 60-second final output (within documented frame tolerance), with section index, SRT and inspectable manifests.

**Result:** `tests/integration/test_video.py` renders the example as a 1280×720 draft and a 1920×1080, 30 fps
final through the CLI and the API; both carry four section videos, an SRT, sampled frames at every checkpoint
and a timing report with exactly 1800 frames. The review UI gained a Video view (player with subtitles, timing
table, sampled frames, timestamped comments).

## Milestone 5 — agent-assisted proposals and source ingestion

**Build tasks**

- [x] PDF, CSV, image and Markdown adapters with provenance and checksums (`scianim sources probe`, extracts separate what a source says from what anyone inferred).
- [x] Structured `create_spec`, `create_storyboard`, `revise_spec`, `revise_storyboard` and targeted revision proposals as typed files (`scianim propose validate|apply|list`); narration is drafted inside storyboard proposals and checked by `scianim timing`. `generate_custom_builder` is not a tool operation: a builder is ordinary code in `code/` that `kind: custom` names.
- [x] Provider-neutral context bundles usable by external coding agents without an integrated LLM API (`scianim context`).
- [x] Agent self-inspection: compare checkpoint images and layout reports with snapshot descriptions before requesting review (`scianim inspect [--record]`).
- [x] Scientific invariants, unsupported inferences and ambiguous citations visible in review (uncertainties and claims on every applied proposal, shown in the overview); proposal diffs preserved; no auto-approval of scientific changes (sign-off flag).
- [x] Additional registered kinds: `schematic_population`, `receptive_field_glyph`, `network_graph`, `caption_with_citation`.
- [ ] Optional voiceover through manim-voiceover bookmarks mapped from narration marks (deferred: needs a speech service; ADR-020).

**Acceptance:** A plain-language brief and synthetic CSV lead to a valid proposed spec, storyboard, generated code, actual Manim snapshots, a review comment, a targeted update and a revision comparison. Source provenance survives the loop.

**Result:** `tests/integration/test_agent_loop.py` replays the loop from `tests/fixtures/agent_loop/` (brief,
synthetic CSV, three proposals) through the CLI alone, and the resulting project is the third example,
`examples/families/computational_neuroscience/orientation_tuning`.

## Milestone 6 — portable families, bundles and documentation

**Build tasks**

- [x] `bundle.yaml`, asset manifest, stable project IDs, SHA-256 checksums (`BundleManifest`, `MANIFEST.sha256`, ADR-021).
- [x] Export project and family bundles without `.venv`, credentials, absolute paths or unapproved copyrighted assets; include `system_requirements` in the bundle README.
- [x] Inspect and import bundles without executing imported Python.
- [x] Resolve imported dependencies from environment manifests and relink omitted assets explicitly (lockfile reused at the same package offset, else `family env sync` resolves afresh; omitted sources listed with relink steps).
- [x] Round-trip project and family across fresh workspaces (`tests/integration/test_bundles.py` reproduces a checkpoint hash after import and environment rebuild).
- [x] Concise user guide: [`USER_GUIDE.md`](USER_GUIDE.md).

**Acceptance:** A fresh-workspace bundle import validates, rebuilds its family environment on a supported platform and reproduces named snapshots. Missing licensed source files produce an explicit relinking warning, not silent substitution.

## Core automated test matrix

| Test | Category | Minimum assertion |
|---|---|---|
| Schema basic | Unit | Included animation/storyboard/theme/family YAML parses |
| Hard constraints | Unit | Conflicting dimensions, exact times, missing hard fields fail clearly |
| Registry params | Unit | Unknown kind, bad `params`, missing data or equation requirement fail; `custom` without builder fails |
| Cross-file | Unit | Unknown data source, equation ID or style role in a storyboard fails |
| Theme cascade | Unit | Correct precedence; missing token fails; provenance recorded; hash changes with a token |
| Narration estimate | Unit | Words-per-minute estimate and conflict report against hard milestones |
| Family isolation | Integration | Worker dependencies cannot be imported by the orchestration process |
| Named checkpoint | Integration/visual | Two real Manim-generated PNGs, records and `manifest.json` |
| Marker parity | Unit | Snapshot IDs equal `checkpoint()` literals in generated code |
| Layout report | Integration | Registered objects have bounding boxes; a deliberately oversized label triggers `outside_safe_zone` |
| Source update | Integration | Changed CSV invalidates the dependent scene snapshot |
| Style update | Integration/visual | Changed token invalidates the affected snapshot and changes expected pixels |
| Section index | Integration | Per-scene durations from `--save_sections` match the storyboard |
| Annotation persistence | API/UI | Normalized region, `object_id` and revision IDs preserved after reload |
| Render metadata | Integration | Frame count, dimensions, fps and codec match the hard output spec |
| Job cancellation | Integration | Worker terminates and metadata shows canceled status |
| Bundle security | Unit | Path traversal, symlink escape and forbidden files are rejected |
| Bundle round-trip | End to end | Metadata, files and checksums preserved on export and import |

## First PR suggestion

**PR 1: Workspace, contracts and validation.** Three-package `uv` workspace, Pydantic models including the component registry and worker contracts, exported schemas, `scianim validate` (file and project modes), `scianim doctor`, negative tests and CI. No UI and no LLM integration.

**PR 2: Style resolution and the isolated worker.** Token cascade with provenance and hash, family resolver, `uv sync` contract, worker launch, subprocess logs, isolation tests.

**PR 3: Checkpoints from the animation flow.** Bridge with `SnapshotScene`, `checkpoint()`, layout report, the first components, `codegen`, `snapshot`, `manifest.json`, review sheet, cache key and a visual test.

These three PRs establish the architectural assumptions before major feature work.

## Definition of done for any task

- Code and unit or integration tests exist, with commands documented.
- No invented scientific sources; supplied synthetic data correctly labeled.
- CLI and API errors are actionable and leave prior approved artifacts intact.
- A dependency or schema change is reflected in docs, exported schemas and locks.
- Artifacts claimed as rendered actually exist; generated hashes and metadata are consistent.
- Remaining limitations are reported precisely.
