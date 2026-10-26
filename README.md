# SciAnim Studio — coding-agent handoff

This directory is a **documentation-first project handoff** for building a personalized scientific animation system on Manim. It is **not yet an installed or functioning Python package**. It is designed to be copied into a new repository and given to a coding agent.

## Start here

1. **[`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)** — comprehensive architecture, feature requirements, YAML contracts, style system, isolated family environments, web review workflow, revision design, security, tests and phase plan.
2. **[`AGENTS.md`](AGENTS.md)** — explicit instructions and guardrails for a coding agent working in this repository.
3. **[`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md)** — prioritized milestones, acceptance criteria and suggested first three pull requests.
4. **[`examples/`](examples/)** — editable YAML examples for an animation, storyboard, family, stylesheet, and a small synthetic CSV.
5. **[`docs/PLAN_REVIEW.md`](docs/PLAN_REVIEW.md)** — review of the plan against the Manim 0.22 source: component registry, in-flow checkpoints, sections, narration, layout reports, Typst, package split.

## Suggested first prompt to a coding agent

> Read `AGENTS.md`, `docs/PROJECT_SPEC.md` and `docs/IMPLEMENTATION_PLAN.md` in full. Implement Milestone 0 as the first PR: bootstrap a Python package with Pydantic schemas, YAML validation, a `scianim validate` CLI, tests, and instructions for running them. Use the included YAML as fixtures. Keep Manim out of the orchestration environment. Do not implement the web UI until Milestones 1–2 have demonstrated an isolated named-snapshot render. Tell me what was actually implemented and tested, what remains uncertain, and show the commands to reproduce your checks.

## Key architectural choices

- Natural-language prompting is the comfortable interface; **versioned YAML** is the persistent authoritative specification.
- `animation.yaml` captures intent and hard constraints; `storyboard.yaml` captures the visual implementation proposal.
- Styles are semantic, inherited and versioned, producing a recognizable personal visual signature.
- Family-specific Python environments have pinned dependencies; their `.venv` directories are neither committed nor shared.
- The preview system creates deliberate **named snapshot states** and can later sample already-rendered video. A generic “last frame” render is not a substitute.
- The local web UI makes storyboard review, still-image annotation and iterative revision practical.
- Shareable bundles contain manifests, sources (when permitted), specs, code and lockfiles rather than machine-specific environments.

## Example status

The YAML and CSV files in `examples/` are **illustrative fixtures**. The example dataset is synthetic. The sample stylesheet is intentionally provisional: it demonstrates token structure, not a finalized personal design language. References to papers or figures must be added from actual user-provided assets.

## Repository layout

See Section 4 of the project specification for the planned Python package tree and workspace hierarchy. The files in this handoff archive correspond to the documentation, agent instructions, and example specifications; implementation code has not yet been generated.
