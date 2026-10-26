# SciAnim Studio — implementation plan for coding agents

**Purpose:** Translate the complete [project specification](PROJECT_SPEC.md) into small, testable implementation units. This document is a task checklist, not a claim that the package has already been implemented.

## Prioritization rules

1. Implement bottom-up: typed spec → style/environment resolution → renderer/snapshots → web review → full video → agent automation → portable bundles.
2. Do not build several partially connected UIs before a named-frame render works.
3. Every milestone should leave a usable CLI operation and regression test.
4. Keep Manim and specialized scientific packages in isolated family environments.
5. Record technical decisions that materially change the public contracts.

## Milestone 0 — repository and contracts

**Build tasks**

- [ ] Bootstrap package `scianim`, Python 3.12+ project metadata, `uv.lock`, Ruff/pytest/type checking and simple CI.
- [ ] Implement Pydantic models for `animation.yaml`, `storyboard.yaml`, `style.yaml`, and `family.yaml` with `schema_version`.
- [ ] Emit JSON Schemas into `schemas/`; check generated schemas are reproducible.
- [ ] Reject unknown core fields, invalid aspect ratios, negative duration, missing hard milestones, path escapes, invalid color tokens.
- [ ] Define strict meaning of source paths, `family` IDs, output dimensions, and style override precedence.
- [ ] Implement `scianim validate <file>` with actionable errors and nonzero status on failure.
- [ ] Implement `scianim doctor` for binary prerequisites (Manim worker, `uv`, ffmpeg, LaTeX when needed), fonts, writable workspace.
- [ ] Load and validate included examples.

**Acceptance**

```bash
scianim validate examples/divisive_normalization/animation.yaml
scianim validate examples/divisive_normalization/storyboard.yaml
scianim doctor
pytest tests/unit
```

Validation must not import Manim in the current process. Run a negative test with an intentionally inconsistent aspect ratio, missing source, and unknown key.

**Deliverables:** CLI, typed models, schema files, reproducible test run and concise developer setup instructions.

## Milestone 1 — theme and family dependency boundary

**Build tasks**

- [ ] Implement default → theme version → family → group → project → scene token resolution.
- [ ] Implement style-token lookup with no hardcoded fallback for unknown tokens.
- [ ] Provide typed renderer-compatible style export (without importing Manim).
- [ ] Discover the declared family root and its `uv.lock`; support nested topical groups and explicit child families.
- [ ] Implement `scianim family env sync <family>` and clear error reporting for absent locks/unsupported platforms.
- [ ] Implement family worker launch via subprocess; capture stdout, stderr, process exit and elapsed time.
- [ ] Test that installing a specialized dependency into a family does not alter control dependencies.

**Acceptance:** Two families with different pinned dependencies can be resolved, synchronized and inspected separately. The parent service never imports Manim.

## Milestone 2 — named Manim checkpoint rendering

**Build tasks**

- [ ] Define a minimal `SnapshotCapableScene` / checkpoint-builder interface.
- [ ] Implement one deterministic scientific plot scene from example synthetic data.
- [ ] Render at least two named states into PNG files by building those states explicitly.
- [ ] Implement frame metadata: scene, snapshot ID, requested time, actual visual state, image dimensions, input hashes.
- [ ] Add a render artifact manifest and append-only job log.
- [ ] Compute a content-addressed cache key including theme/version, scene code, input data and environment lock.
- [ ] Implement `scianim snapshot <project> --all`.
- [ ] Make style token change invalidate the correct cached still(s).

**Acceptance:** Two PNGs produced by Manim (not mockups) from the same YAML, plus a manifest. Changing `palette.primary_signal` yields an observable change in the corresponding rendering.

## Milestone 3 — local review UI

**Build tasks**

- [ ] Create FastAPI project listing / revision / jobs / artifact endpoints.
- [ ] Add SQLite data models for projects, revisions, jobs, annotations and approvals.
- [ ] Scaffold React/TypeScript frontend and basic family/project navigation.
- [ ] Add filmstrip/grid and large snapshot viewer; distinguish schematic/actual frames.
- [ ] Add normalized point/rectangle annotations attached to exact revision and snapshot IDs.
- [ ] Add before/after comparison and “needs revision” / “approved” statuses.
- [ ] Add job polling, logs, retry/cancel; ensure HTTP request is nonblocking for render jobs.
- [ ] Record how a change invalidates stale previews and approvals.

**Acceptance:** A browser user can view a generated snapshot, mark a region, submit a request, and retrieve the annotation bound to the correct immutable revision after restarting the server.

## Milestone 4 — storyboard timing and video rendering

**Build tasks**

- [ ] Validate scene intervals, milestones and overlap policy (cuts/transitions must be explicit).
- [ ] Generate draft MP4 from named scenes while preserving requested relative timing.
- [ ] Generate exact final output specification and verify width, height, fps, duration/frame count via media probe.
- [ ] Support video timestamp/range comments and frame sampling from a completed video.
- [ ] Save stderr/logs on failure; prevent a failed job from marking the revision approved.
- [ ] Implement incremental invalidation at scene level; be conservative about uncertain dependencies.

**Acceptance:** Example can produce a 720p draft and a 1920×1080, 30 fps, 60-second final output (subject to documented frame tolerance), with inspectable manifests.

## Milestone 5 — agent-assisted proposals and source ingestion

**Build tasks**

- [ ] Add PDF, CSV, image, Markdown adapters with provenance and checksums.
- [ ] Implement structured `create_spec`, `create_storyboard`, `revise_spec`, and targeted revision proposals.
- [ ] Add provider-neutral context bundles usable by external coding agents without an integrated LLM API.
- [ ] Make scientific invariants, unsupported inferences, and ambiguous citations visible in review.
- [ ] Preserve proposal diffs and do not auto-approve an agent-generated scientific change.
- [ ] Add a few reusable scene recipes: term-highlighted equation, plot, side-by-side comparison, schematic neural population.

**Acceptance:** A plain-language brief and synthetic CSV can lead to a valid proposed spec, storyboard, generated code, actual Manim snapshot, review comment, targeted update, and revision comparison. Source provenance survives the loop.

## Milestone 6 — portable families, bundles and documentation

**Build tasks**

- [ ] Implement `bundle.yaml`, asset manifest, stable project IDs, SHA-256 checksums.
- [ ] Export project/family bundles without `.venv`, credentials, absolute paths, or unapproved copyrighted assets.
- [ ] Inspect/import bundles without executing imported Python.
- [ ] Resolve imported dependencies from environment manifests and relink omitted assets explicitly.
- [ ] Round-trip project and family across fresh workspaces.
- [ ] Write a concise user guide: prompt-only, YAML-first, image reference, paper reference, scientific CSV, fork and revision, export/import.

**Acceptance:** Fresh-workspace bundle import validates, rebuilds its family environment on a supported platform and reproduces named snapshots. Missing licensed source files produce an explicit relinking warning, not silent substitution.

## Core automated test matrix

| Test | Category | Minimum assertion |
|---|---|---|
| Schema basic | Unit | Included animation/storyboard/theme/family YAML parses |
| Hard constraints | Unit | Conflicting dimensions, exact times, missing hard fields fail clearly |
| Theme cascade | Unit | Correct precedence; missing token fails |
| Family isolation | Integration | Worker dependencies cannot be imported by orchestration process |
| Named snapshot | Integration/visual | Two real Manim-generated PNGs and manifest |
| Source update | Integration | Changed CSV invalidates dependent scene snapshot |
| Style update | Integration/visual | Changed token invalidates affected snapshot and changes expected pixels |
| Annotation persistence | API/UI | Normalized region and revision IDs preserved after reload |
| Render metadata | Integration | Frame count, dimensions, fps and codec match hard output spec |
| Job cancellation | Integration | Worker terminates and metadata shows canceled status |
| Bundle security | Unit | Path traversal, symlink escape and forbidden files are rejected |
| Bundle round-trip | End to end | Metadata + files + checksums preserved on export/import |

## First PR suggestion

**PR 1: Package skeleton + YAML validation.** Include basic README, Pydantic models, exported schema files, `scianim validate`, four sample YAML validations, negative tests and CI. No UI and no LLM integration yet.

**PR 2: Theme resolution + isolated worker.** Include family resolver, uv sync contract, token cascade, process invocation, subprocess logs, isolation tests.

**PR 3: Named scientific snapshots.** Include example Manim scene, explicit checkpoint states, style tokens, PNG artifacts, manifest and visual test.

These three PRs establish the most important architectural assumptions before major feature work.

## Definition of done for any task

- Code and unit/integration tests exist, with commands documented.
- No invented scientific sources; supplied synthetic data correctly labeled.
- CLI/API errors are actionable and leave prior approved artifacts intact.
- A dependency or schema change is reflected in docs and locks.
- Artifacts claimed as rendered actually exist; generated hashes/metadata are consistent.
- Remaining limitations are reported precisely.
