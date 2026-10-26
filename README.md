# SciAnim Studio

SciAnim Studio is a local-first system for producing reproducible, personally styled scientific animations with Manim. A scientist describes an animation in ordinary language or YAML; the system enforces a versioned stylesheet and typed scientific constraints; a storyboard composed of registered components is rendered into named checkpoint stills, each with a layout report; and final videos are produced from isolated, pinned family environments.

The repository started as a documentation-first handoff and is being implemented incrementally. Check `docs/IMPLEMENTATION_PLAN.md` for what exists and what does not; do not assume a feature works because it is specified.

## Start here

1. **[`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)** (0.2) — architecture, feature requirements, YAML contracts, style system, component registry, in-flow checkpoints, isolated family environments, web review workflow, revision design, security, tests and phase plan.
2. **[`AGENTS.md`](AGENTS.md)** — instructions and guardrails for a coding agent working in this repository.
3. **[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)** — prioritized milestones, acceptance criteria and suggested first three pull requests.
4. **[`docs/ARCHITECTURE_DECISIONS.md`](docs/ARCHITECTURE_DECISIONS.md)** — decisions that shape the contracts.
5. **[`docs/PLAN_REVIEW.md`](docs/PLAN_REVIEW.md)** — the review, checked against the Manim 0.22 source, that produced spec 0.2.
6. **[`examples/`](examples/)** and **[`styles/`](styles/)** — an example animation and storyboard, a family manifest, a synthetic CSV, and the default and personal style tokens.

## Key architectural choices

- Natural-language prompting is the comfortable interface; **versioned YAML** is the persistent authoritative specification.
- `animation.yaml` captures intent, typed equations and hard constraints; `storyboard.yaml` captures scenes with narration, registered component objects, explicit data bindings and named checkpoints.
- A **component registry** is the contract shared by the validator, the code generator and the renderer. Storyboards made of registered kinds render without hand-written code; `kind: custom` is the explicit escape hatch.
- Styles are semantic, inherited and versioned; the renderer receives a resolved token document with provenance and hash.
- **Checkpoints are named markers reached by the real animation flow**, captured in Manim's fast-forward mode, with a layout report (normalized bounding boxes per object) that drives machine-checkable visual QA and object-anchored feedback.
- Each storyboard scene is one Manim section, which gives per-scene videos and scene-level incremental rendering.
- Equations default to Typst, which installs from PyPI into the family lockfile; LaTeX is a per-family opt-in.
- Three distributions: `scianim-core` (contracts), `scianim` (control plane) and `scianim-bridge` (render side). The control plane never imports Manim; families depend only on the bridge.
- Family environments are pinned with `uv.lock` and declare their system requirements; `.venv` directories are never committed or shared.
- Shareable bundles contain manifests, sources (when permitted), specs, code and lockfiles rather than machine-specific environments.

## Example status

The YAML and CSV files in `examples/` are **illustrative fixtures**. The dataset is synthetic. The personal stylesheet is provisional: it demonstrates token structure, not a finalized design language. References to papers or figures must be added from actual user-provided assets.

## Suggested first prompt to a coding agent

> Read `AGENTS.md`, `docs/PROJECT_SPEC.md`, `docs/IMPLEMENTATION_PLAN.md` and `docs/ARCHITECTURE_DECISIONS.md` in full. Continue from the first unchecked task in the implementation plan. Keep Manim out of the control-plane environment. Tell me what was actually implemented and tested, what remains uncertain, and show the commands to reproduce your checks.
