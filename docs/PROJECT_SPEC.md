# SciAnim Studio: agent-ready project specification

**Status:** Proposed architecture / implementation handoff  
**Version:** 0.1 (26 October 2026)  
**Working name:** SciAnim Studio (`scianim` CLI and Python package; name can be changed before publication)  
**Primary audience:** Coding agents and developers implementing a personal scientific-animation system  
**Source of truth:** This specification. `AGENTS.md` describes how an agent should implement it; `docs/IMPLEMENTATION_PLAN.md` breaks it into milestones.

---

## 1. Executive summary

Build a **local-first, Python-based system for producing reproducible, highly controlled scientific animations**, with **Manim Community Edition as the principal rendering engine**. A scientist should be able to provide a natural-language prompt, scientific PDFs, figures, sketches, tables, CSV data, equations, or a YAML specification and then review, correct, and approve the generated animation **without writing or inspecting Manim code**.

The system must have a recognizable personal visual signature enforced by **versioned visual stylesheets**. It must preserve scientific fidelity, permit precise output constraints (duration, aspect ratio, dimensions, frame rate, key moments), and support iterative review at storyboard and still-frame stages before computationally expensive full rendering.

Each animation exists in a **hierarchical workspace**. Related animations can share styles, assets, reusable components, and a pinned Python environment; unrelated families may require distinct dependency stacks. Animations or whole families can be exported as **portable, shareable bundles**, with source files and provenance where legally permitted, and **without embedding local virtual environments**.

A lightweight **web interface** is central, not an afterthought. Its primary role is to inspect specifications, see annotated storyboards and snapshots, request targeted revisions, compare versions, and start preview/final render jobs.

### Governing principle

> Natural language expresses intent; validated YAML records the contract; a storyboard records the proposed visual implementation; versioned Python and artifacts make the result reproducible; the web interface makes iterative review efficient.

### Non-goals

- Not a generic video editor or a replacement for Adobe After Effects, Blender, or Manim itself.
- Not a system in which every Manim operation must be specified in YAML.
- Not a cloud-first, multi-user SaaS product in version 1.
- Not fully automatic scientific fact-checking, unrestricted execution of downloaded code, or automatic redistribution of copyrighted PDFs, fonts, or data.
- Not a requirement that the user edit Python, inspect Manim internals, or repeatedly restate visual preferences.

---

## 2. User experience and product requirements

### 2.1 Supported ways to start

The same pipeline should accept one or a mixture of:

1. **Conversational brief:** “Make a 75-second explanation of divisive normalization, introducing the pool after 20 seconds.”
2. **Structured YAML:** Complete or partial `animation.yaml` defining output and narrative constraints.
3. **Paper(s):** PDFs, optionally with specified pages, figures, or passages to emphasize.
4. **Images:** Still frames, screenshots, reference figures, hand drawings, existing animation keyframes.
5. **Data:** CSV initially; optional NumPy, Parquet, or HDF5 via family-specific data adapters.
6. **Mathematics:** Equations, Markdown/LaTeX, symbolic expressions, conceptual descriptions.
7. **Existing projects:** “Use the previous receptive-field animation as the basis, but change the explanatory sequence.”

The agent should synthesize these into a structured brief and editable YAML, *not* directly jump from a vague instruction to opaque generated Manim code.

### 2.2 What the user should be able to do

- Set and inherit a personal stylesheet with colors, typography, line weights, spacing, plot conventions, camera behavior, and transition defaults.
- Pin exact technical output constraints: duration, resolution, aspect ratio, frame rate, file format, audio options, and safe zones.
- Declare scientific invariants: exact equations, expected axes, variable definitions, labels, numerical transformations, and source-attribution obligations.
- Specify milestones at approximate or exact timestamps; optionally provide hard positional constraints and reference stills.
- Ask for storyboards and targeted snapshots before producing a full animation.
- Comment directly on a snapshot or select a rectangle/element and ask for a revision.
- Compare revisions side-by-side, retain previous work, and roll back.
- Reuse prior components, styles, scenes, and data adapters in a new animation.
- Keep multiple family-specific virtual environments pinned and isolated.
- Share an animation/family as a self-describing archive or repository subtree.
- Reproduce past renders from the same inputs, code, dependencies, and settings, acknowledging renderer/platform nondeterminism where relevant.

### 2.3 User-facing review workflow

1. **Create / import.** User provides references and a brief or existing YAML.
2. **Interpret.** Agent extracts and summarizes sources, identifies assumptions and unresolved decisions.
3. **Specify.** Agent creates or updates `animation.yaml`. A validation pass distinguishes hard requirements from preferences.
4. **Storyboard.** Agent creates `storyboard.yaml` and explanatory thumbnail cards. User accepts or revises narrative order.
5. **Still previews.** A preview worker renders explicit checkpoints (not an accidental final frame). User annotates images and approves visual language/scientific content.
6. **Draft video.** Worker renders a fast, lower-cost complete animation. User revises timing, continuity, and dynamics.
7. **Final render.** Worker produces requested deliverables; project stores a provenance manifest and version lineage.
8. **Reuse / export.** User can fork, package, or share the animation.

Review and render stages can be revisited independently. **Do not require a full render after every textual change.**

---

## 3. Architectural decisions

These are default decisions for the implementation, not irrevocable product constraints.

| Area | Initial choice | Reason |
|---|---|---|
| Rendering | Manim Community Edition | Programmatic, suitable for scientific 2D animation, equations, plots, and reusable scenes |
| Control plane | Python 3.12+ with Pydantic v2 | Typed contracts, validation, CLI, manageable testing |
| YAML | `ruamel.yaml` or PyYAML for parsing; Pydantic for validation | Human-editable specifications with explicit schema versions |
| CLI | Typer | Clear scriptable agent interface |
| Backend | FastAPI | Local API, job orchestration, review metadata |
| Web frontend | React + TypeScript + Vite | Fine-grained image annotation and side-by-side version review |
| Local metadata | SQLite, accessed via SQLAlchemy or equivalent | Reliable revision/job records without running extra services |
| Render job runner | Local subprocess worker and process group management | Isolates dependency-heavy rendering from control/API processes |
| Family environments | `uv`-managed project environment and `uv.lock` per declared family | Fast reproducible installs and sharing; no base-environment contamination |
| Source control | Git | Human-readable specs, code, themes, reusable components, documentation |
| Render cache | Content-addressed keys plus artifact manifests | Reuse unchanged scenes and preview assets |
| LLM integration | Adapter interface, provider-agnostic | Works with different coding agents or model APIs |

**Boundary:** The orchestration server must not import Manim or arbitrary per-family scientific packages. It invokes a renderer in a *separate process* using the selected family environment. This boundary is essential to isolation.

**Core in V1:** One primary Manim rendering backend. Later adapters may support Matplotlib, VTK, PyVista, Blender, or other specialized visualizations, but that is not required to ship the first useful version.

---

## 4. Repository and workspace layout

A recommended layout for the implementation repository:

```text
scianim-studio/
├── README.md
├── AGENTS.md                        # Top-level agent operating contract
├── pyproject.toml                    # Control-plane dependencies only
├── uv.lock
├── .gitignore
├── docs/
│   ├── PROJECT_SPEC.md              # This complete specification
│   ├── IMPLEMENTATION_PLAN.md       # Milestones and test gates
│   ├── ARCHITECTURE_DECISIONS.md     # Optional architecture decision records
│   └── user-guide/                  # Created later
├── schemas/
│   ├── animation.schema.json        # Exported from Pydantic
│   ├── storyboard.schema.json
│   ├── style.schema.json
│   ├── family.schema.json
│   └── bundle.schema.json
├── src/scianim/
│   ├── __init__.py
│   ├── cli.py
│   ├── config/                    # YAML parsing, inheritance and validation
│   ├── models/                    # Typed schema models and migrations
│   ├── sources/                   # PDF, CSV, image, and text ingestion
│   ├── planning/                  # Storyboard contracts, scheduling
│   ├── styles/                    # Resolved tokens, validation, inheritance
│   ├── components/                # Reusable visual primitives/recipes
│   ├── render/                    # Job protocols, worker entrypoints, snapshots
│   ├── revisions/                 # Immutable snapshots, diffs, lineage
│   ├── storage/                   # Project manifests, artifact store, cache
│   ├── bundles/                   # Export, import, checksums, portability
│   ├── agents/                    # Provider-neutral context and patch contracts
│   ├── api/                       # FastAPI server, schemas, routes
│   └── security/                  # Path control, trust, process constraints
├── web/                           # React + TypeScript UI
├── styles/
│   ├── default/style.yaml
│   └── tomas_scientific/style.yaml
├── recipes/                        # Built-in scene and plotting patterns
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/                    # Visually compared test snapshots
│   └── fixtures/
├── examples/
│   └── divisive_normalization/
└── workspace/                       # User data; configurable, normally ignored
    ├── assets/                     # Explicitly managed global assets
    └── families/
        └── computational_neuroscience/
            ├── family.yaml        # Family ID, style, environment, shared components
            ├── pyproject.toml     # Family render dependencies
            ├── uv.lock            # Committed / shareable dependency lock
            ├── .venv/             # Local only; never export/commit
            ├── assets/
            ├── components/
            ├── group.yaml         # Optional group-level preferences
            ├── divisive_normalization/
            │   ├── animation.yaml
            │   ├── storyboard.yaml
            │   ├── references/
            │   ├── data/
            │   ├── code/          # Generated, reviewable Python
            │   ├── feedback/      # Human annotations and requests
            │   ├── revisions/     # Revision snapshots and manifests
            │   ├── renders/       # Previews, drafts and finals
            │   └── .scianim/      # Local cache, current revision, transient jobs
            └── perception/
                └── retinotopy/
                    └── animation_example/
```

The workspace can reside outside the package repository (`SCIANIM_WORKSPACE=/path/...`). The displayed workspace tree is illustrative; **the user should not need to manually create these folders**.

### 4.1 Hierarchy and inheritance

- `styles/default/style.yaml` establishes the baseline style.
- A named personal stylesheet (e.g. `tomas_scientific`) overrides the baseline.
- A `family.yaml` may select a stylesheet version and supply family-specific defaults.
- Optional `group.yaml` files define local organizational defaults or shared assets.
- An `animation.yaml` can override only explicitly permitted tokens, not silently supersede declared hard rules.
- Each project has a stable ID independent of its folder name, so projects can be moved without losing revision identity.

**Do not use directory position alone to guess the Python environment.** Environment identity must be explicit in `family.yaml` and inherited until an intentionally declared child-family boundary. Nested folders that are merely topical categories do not create new environments.

### 4.2 Dependency isolation

A rendering family has:

- `pyproject.toml`: explicit `manim`, family visualization/data packages, and the `scianim` rendering bridge version.
- `uv.lock`: full resolved dependency graph, preferably including platform constraints where needed.
- `.venv/`: generated from the lock on the local machine; not part of the portable project.

A child animation reuses its family's environment unless it explicitly belongs to a child family with its own lockfile. Never install a requested dependency into the orchestrator's environment to make a family render work.

For local development, the family may use an editable/path dependency for the `scianim` package. For portable export, replace development-only absolute paths with a published package reference, a relative vendored source, or a documented install step. The bundle validator must flag unresolved absolute paths.

In the first implementation, **one environment per family** is sufficient. A content-addressed shared environment cache across families can be added later if identical locks make duplication costly. Avoid optimizing that before the lockfile workflow works reliably.

---

## 5. File formats and contracts

All machine-readable public specifications are UTF-8 YAML with a required `schema_version`. The code maintains Pydantic models and exports matching JSON Schemas. Unknown core fields are rejected with actionable errors, except within explicitly namespaced `extensions`.

### 5.1 `animation.yaml`: immutable scientific intent per revision

Required conceptual sections:

| Section | Fields / semantics |
|---|---|
| `schema_version` | Version identifier for migration, initially `1.0` |
| `id`, `title` | Stable slug ID and display title |
| `family` | Family ID, resolved through workspace registry / ancestry |
| `sources` | References to PDF, image, data and other inputs with optional locator and intended role |
| `output` | Exact delivery specification (duration, width/height, aspect ratio, fps, format, codec) |
| `style` | Theme name, pinned theme version and allowed overrides |
| `audience` | Optional target audience and background knowledge |
| `objective` | Concise explanatory goal |
| `scientific_constraints` | Hard content facts, required equations, conventions, and prohibitions |
| `timeline` | Milestones, each with a target time, description and optional tolerance |
| `direction` | Creative guidance; descriptive rather than executable code |
| `extensions` | Optional namespaced add-ons specific to a family or plugin |

**Hard versus soft:** Every timing or content constraint can explicitly declare `kind: hard` or `kind: preferred`. A hard output duration must be met within a documented frame tolerance (normally one frame); an impossible combination of constraints is a validation/planning error, not a reason to silently improvise.

Example:

```yaml
schema_version: "1.0"
id: divisive_normalization_intro
title: "Divisive normalization: excitation and pool"
family: computational_neuroscience

sources:
  - id: responses
    type: csv
    path: data/synthetic_responses.csv
    role: illustrative_data
    citation: "Synthetic demonstration; not empirical data"
  # Add PDFs or images the user actually supplies, e.g.:
  # - id: paper_a
  #   type: pdf
  #   path: references/paper_a.pdf
  #   locators: ["Figure 2", "Equation 1"]

output:
  duration_seconds: 60
  width_px: 1920
  height_px: 1080
  aspect_ratio: "16:9"
  fps: 30
  container: mp4
  video_codec: h264
  audio: none

style:
  name: tomas_scientific
  version: "0.1.0"
  overrides: {}

audience: graduate_neuroscience
objective: >-
  Introduce the logic of a normalization pool and show how
  increases in pool drive alter a schematic neural response.
scientific_constraints:
  - id: eq1
    kind: hard
    text: "Use schematic r = E / (sigma + P), defining E, P and sigma."
  - id: eq2
    kind: hard
    text: "Do not imply the supplied synthetic data are empirical observations."

timeline:
  - id: intro
    at_seconds: 0
    tolerance_seconds: 0
    kind: hard
    instruction: "Introduce excitation drive."
  - id: pool
    at_seconds: 15
    tolerance_seconds: 2
    kind: preferred
    instruction: "Introduce normalization pool."
  - id: equation
    at_seconds: 30
    tolerance_seconds: 1
    kind: hard
    instruction: "Display the equation and define terms."
  - id: comparison
    at_seconds: 45
    tolerance_seconds: 2
    kind: preferred
    instruction: "Compare two pool strengths with constant excitation."

direction:
  tone: "Precise, restrained, visually explanatory"
  avoid:
    - "Unnecessary transitions or decorative geometry"
    - "Text so small it cannot be read at presentation size"
extensions: {}
```

Paths inside animation bundles are project-relative. Shared assets use explicit identifiers (`asset://...`) resolved against a controlled registry. Reject `..` path escapes, disallow implicit network fetches, and preserve source-file checksums in revision manifests.

### 5.2 `storyboard.yaml`: proposed visual implementation

Storyboard revisions are distinct from intent revisions. The storyboard adds implementation details that should **not** be forced into the primary scientific brief:

- Ordered `scenes` or `shots` with stable IDs, start/end times, titles, pedagogical purposes.
- Visual objects/equations/charts and their roles, bound to style tokens.
- Source bindings for data-driven elements.
- Layout constraints such as anchors, grids, safe zones, target positions.
- Transitions, camera movements, emphasis actions, animation timing.
- **Snapshot checkpoints** at explicit moments, naming expected visual states.
- Conditions/acceptance notes for visual and scientific review.

Example:

```yaml
schema_version: "1.0"
project_id: divisive_normalization_intro
based_on_animation_revision: "<resolved-revision-id>"

scenes:
  - id: excitation
    start_seconds: 0
    end_seconds: 15
    purpose: "Establish what excitatory drive represents"
    objects:
      - id: drive_curve
        kind: plot
        style_role: primary_signal
        data_source: responses
    snapshots:
      - id: excitation_visible
        at_seconds: 9
        description: "Curve and labeled excitation axis are visible"

  - id: normalization_pool
    start_seconds: 15
    end_seconds: 30
    purpose: "Introduce the inhibitory/divisive pool term"
    objects:
      - id: pool_label
        kind: equation_label
        style_role: normalization_pool
    snapshots:
      - id: pool_introduced
        at_seconds: 24
        description: "Pool clearly distinguished from excitation"

  - id: equation
    start_seconds: 30
    end_seconds: 45
    purpose: "Explain schematic r = E/(sigma+P)"
    snapshots:
      - id: equation_complete
        at_seconds: 40
        description: "All terms visible and defined"

  - id: pool_comparison
    start_seconds: 45
    end_seconds: 60
    purpose: "Show effect of increasing P with E held constant"
    snapshots:
      - id: comparison_complete
        at_seconds: 55
        description: "Two conditions displayed with identical axes"
```

The storyboard is a **contract and planning format**, not a full substitute for generated Python. Its syntax must remain compact enough for LLMs to create and humans to inspect. Allow an optional explicit `layout`/`timing` substructure when finer control is requested.

### 5.3 Style files and design tokens

A stylesheet defines an artistic signature **semantically**, not merely through a handful of global color variables. Required categories:

- **Palette roles:** foreground, background, secondary text, highlight, muted, neutral, excitatory, suppressive, uncertainty, selection, error; tokens map to hex/RGB values.
- **Typography:** font family preferences and fallbacks; title/body/math styles; minimum sizes; weight, line-height and wrapping rules; font licensing checks for export.
- **Geometry:** standard canvas padding, safe-zone rules, gaps, graph line widths, marker sizes, grid and panel conventions.
- **Charts:** axes, tick density, background grid, legend positions, color order and scientific plotting defaults.
- **Motion:** duration defaults, easing, stagger, transition style, pacing and camera movement policies.
- **Components:** equations, labels, plots, neural fields, activation maps, annotation arrows, progress/timeline indicators.
- **Accessibility:** contrast thresholds, non-color discriminators, smallest permitted text at final delivery size.

Override order:

```text
system defaults
    ↓
versioned personal theme
    ↓
family style overrides
    ↓
group style overrides (optional)
    ↓
project overrides (allowlisted)
    ↓
scene overrides (allowlisted)
```

Reject missing/unknown design tokens rather than using unexplained defaults. Avoid hardcoded colors in generated Python except for documented escape hatches.

Theme changes must be **versioned**. Re-rendering an old animation uses its pinned theme by default; adopting a newer theme is an explicit revision, not a silent side effect.

### 5.4 `family.yaml`: scope and environment

Each family declares a unique ID, display name, environment root/lockfile, style selection, shared assets, and optional schema extensions. Nested children inherit a parent family only when no new family declaration exists. Dependencies are never inferred from `requirements.txt` files found at arbitrary depths.

### 5.5 Revision and artifact manifests

Every accepted change produces a revision ID, a timestamp, a change description, parent revision pointer(s), hashes of the spec/storyboard/generated code/style/sources, and optionally the issuing agent/model (if known). A render manifest records:

- Requested profile, dimensions, fps, duration and encoding.
- Actual output metadata, file checksum and validation results.
- Git commit or source-tree hash.
- `uv.lock` hash and selected interpreter/renderer versions.
- Source asset checksum list, with source provenance.
- Snapshot names and frame indices actually rendered.
- Errors, warnings, elapsed time and cache-hit information.

A revision is immutable. The *working copy* may evolve, but approval and render actions operate on revision snapshots; this avoids stale renders or confusing feedback attached to the wrong code version.

---

## 6. Scientific source ingestion and traceability

### 6.1 Source-adapter interface

Create a `SourceAdapter` interface that can probe, extract, normalize, and fingerprint inputs. V1 adapters:

- PDF: extract text, page references, equations where feasible, embedded figures or per-page image representations when needed; preserve page-level anchors.
- Image: collect dimensions, checksum, optional human/agent visual description, suggested role (target style, visual reference, factual figure, or background).
- CSV: inspect column names, dtypes, missingness, units where supplied, row count, basic statistics; do not infer semantic units as facts.
- Markdown/plain text: direct annotations or explanation text.
- Existing project: references to its released style/storyboard/components, with explicit version ID.

Source extraction should distinguish **what the source says** from **what the agent infers**. The UI should surface references for any scientific content the agent claims is based on a paper or dataset.

### 6.2 Scientific integrity contracts

- Never silently alter a supplied scientific equation or numerical relationship merely to improve appearance.
- Require explicit normalization, interpolation, filtering, unit conversions and plotting transforms; log them in provenance.
- Generated toy/synthetic data must be labeled as such.
- Track whether a figure was reproduced, redrawn, conceptually reinterpreted, or only aesthetically inspired by the reference.
- Provide source locators (paper, page, figure/equation, dataset column) for important scientific claims.
- Preserve display correctness: labels, units, legends, shared axes for comparisons, reference conditions and color mappings.
- Allow an `uncertainties` queue when source interpretation is ambiguous; the agent must ask rather than invent unsupported details.
- Human sign-off is the final gate for scientific validity. Automated linting cannot establish scientific truth.

### 6.3 Images supplied as references

A supplied still can have multiple distinct roles:

1. **Composition reference:** emulate placement, hierarchy, and proportions, not necessarily content.
2. **Style reference:** derive candidate colors/typography/line treatment, then map them into theme tokens.
3. **Scientific reference:** redraw a specific relationship or panel with traceable data and attribution.
4. **Target keyframe:** produce a checkpoint that resembles the supplied image, with a review comparison.

The user/agent should record which role applies. The system must not automatically copy third-party artwork into a redistributable bundle.

---

## 7. LLM integration and agent responsibilities

The architecture must work with different LLMs: a coding agent using the CLI, a hosted inference API, or a manually guided ChatGPT conversation. **Do not bind the project format to one model vendor.**

### 7.1 Role boundaries

| Role | Produces | May change |
|---|---|---|
| Brief interpreter | Requirements + ambiguity report | Draft spec only |
| Scientific planner | Structured content constraints and source links | Intent proposal |
| Storyboard designer | Narrative/shot plan and key checkpoints | Storyboard draft |
| Code generator | Versioned Manim code and component references | `code/` and associated tests |
| Validator/reviewer | Machine-checkable QA and problem reports | Feedback records, not approved spec |
| Renderer | Snapshot/draft/final outputs | Artifact directories only |
| User | Corrections and approvals | Authorized specification and review status |

These are logical roles and need not be separate model calls. In V1, one coding agent may perform all generative roles, provided the artifacts and checks remain separate.

### 7.2 Agent instruction contract

An agent must:

1. Read `AGENTS.md`, this specification, the active style, the family manifest, and the relevant animation spec.
2. Inspect supplied inputs before claiming what they contain.
3. List unresolved scientific assumptions and conflicting constraints before code generation.
4. Prefer reusable components over bespoke scene code where possible.
5. Generate and validate `animation.yaml` and `storyboard.yaml` before Manim code.
6. Keep all generated files within the assigned project, save source provenance, and avoid uncontrolled external commands.
7. Produce named snapshot checkpoints, not just a full video.
8. After feedback, modify the smallest affected scope; do not rewrite unrelated scenes.
9. Run appropriate validation/tests before claiming work is complete.
10. Report exactly which outputs were created, what was actually rendered, any warnings, and what still needs scientific approval.

### 7.3 Structured agent operations

Provider-neutral operations for V1:

- `create_spec(brief, sources, inherited_defaults) -> SpecProposal`
- `revise_spec(spec_revision, request) -> PatchProposal`
- `create_storyboard(spec_revision) -> StoryboardProposal`
- `revise_storyboard(storyboard_revision, feedback) -> PatchProposal`
- `generate_scene_code(approved_storyboard, style_tokens, component_catalog) -> CodeRevision`
- `analyze_feedback(annotation_set) -> TargetedChangeProposal`

All stateful operations are materialized as files/revisions; do not keep the only copy of crucial information inside an LLM conversation. Changes should be expressed as patches/diffs with human-readable summaries and validated before acceptance.

The agent may *propose* a spec change to resolve an impossible render; it may not silently change duration, data, or mathematical semantics.

### 7.4 Prompting ergonomics

Allow a user to provide as little as a goal and source material. The interface should infer ordinary style defaults and leave low-level layout to the agent. More structured prompts or YAML increase precision, particularly for exact scientific constraints, milestones, and output properties. The system should preserve intent even when a new model or coder takes over.

---

## 8. Preview rendering: the technical centerpiece

**Important:** A Manim still/last-frame render does not, by itself, solve arbitrary checkpoint extraction. V1 must support **explicitly defined snapshot states** that are generated and rendered intentionally.

### 8.1 Two kinds of previews

1. **Storyboard image:** A quick, optionally schematic still generated from scene/object layout, without running a full animation. Useful for narrative approval, but may not be pixel-identical to final Manim frames.
2. **Manim checkpoint:** An actual rendered frame representing a *known state* at a named moment. Produced from deliberate scene checkpoints or deterministic mini-scene constructors.

Never label a schematic storyboard image as an exact rendered keyframe. The UI must identify which kind is being shown.

### 8.2 Checkpoint implementation

Provide a contract that generated scene code can implement, for example:

```python
# Illustrative interface, not committed API syntax.
class SnapshotCapableScene:
    snapshot_states = ["excitation_visible", "pool_introduced"]

    def build_snapshot(self, state_id: str):
        """Construct a deterministic state for a named snapshot."""
        ...
```

A code-generation helper can create short Manim scenes that construct these checkpoint states. This is preferable to skipping ahead through arbitrary `play()` sequences and assuming all mobject updaters, randomness, and stateful transitions behave exactly as in a full video.

Where exact video-frame sampling is desired, **render a draft segment and extract frames** using a video tool (e.g. FFmpeg). Mark those as *sampled video frames*. This is more expensive but valid for checking motion-dependent states and cross-scene continuity.

### 8.3 Preview budget

- First pass: storyboard cards and 3–8 named checkpoints.
- Second pass: changed checkpoints only (dependency-based invalidation).
- Third pass: optional low-resolution draft, initially 720p and reduced quality settings.
- Final: exact requested output. No unapproved resolution/time substitutions.

Checkpoint caches must include: scene code hash, source/data hash, style version, checkpoint definition, renderer version and relevant environment lock hash. A time-only key is insufficient.

### 8.4 Timing fidelity

The planner should map seconds to frame indices at the chosen fps; internal shot timing can remain in seconds. If a requested timestamp falls between frames, use a documented rounding policy. Validate exact total frame count for hard-duration outputs. A storyboard boundary may be moved within stated tolerances, but not past an immutable hard milestone.

---

## 9. Web application

The browser interface is a **first-class feature**. It runs locally initially; remote hosting and authentication can come later.

### 9.1 Essential views

**A. Workspace browser**
- Expandable family/group/project tree; search, tags, thumbnail, revision status.
- Distinguish installed/healthy/broken family environments.
- Create project from prompt, upload, or template.

**B. Project overview**
- Brief, source files, output settings, theme, scientific constraints.
- Status of spec, storyboard, previews, draft render, final render.
- Editable structured fields for frequently changed properties.
- Text prompt input to request a revision.

**C. Storyboard editor**
- Scene cards with title, duration, purpose, key objects and milestones.
- Reorder, change durations, comment per scene and request alternatives.
- Timeline view of exact timestamps and hard constraints.

**D. Snapshot review**
- Grid or filmstrip of generated frames, expandable large image.
- Draw rectangle or click at normalized image coordinates, add text feedback.
- Attach comment to project revision, scene ID, snapshot ID and optionally time.
- Before/after slider or side-by-side comparison for two revisions.
- Mark a checkpoint “approved”, “needs revision” or “scientific concern”.

**E. Video review / exports**
- Low-resolution video scrubber and timestamped comments.
- Final render details, downloads, manifest, version history, export bundle.

**F. Jobs and logs**
- Queue, running job, error, elapsed time, worker logs, retry/cancel.
- Clearly show when previews are schematic vs Manim-derived.

### 9.2 Feedback model

Use explicit typed records:

```json
{
  "project_id": "divisive_normalization_intro",
  "revision_id": "rev_0004",
  "scene_id": "normalization_pool",
  "snapshot_id": "pool_introduced",
  "kind": "region_comment",
  "region": {"x": 0.20, "y": 0.36, "width": 0.25, "height": 0.14},
  "text": "Increase spacing between the pool label and the curve.",
  "severity": "visual"
}
```

Coordinates are normalized to [0, 1], independent of preview pixel dimensions. Store resolved image dimensions and transform if the UI uses a cropped/letterboxed view. A video comment may instead identify a time range.

### 9.3 Approval and invalidation

A project moves through review states, but revisions may invalidate only the affected downstream products. Example:

- Change typography token → invalidate all affected stills and rendered video, **not** scientific source extraction.
- Change scene 3 timing → invalidate its storyboard timing, dependent scenes, draft/final video, and any affected sampled frames; retain unrelated snapshot assets if safe.
- Change source CSV values → invalidate dependent plots and all renders containing them; preserve human notes and independent scenes.
- Change scientific equation → re-require human content approval for affected scenes even if their aesthetics are unchanged.

Never approve a *mutable path*; approve the hash/revision actually displayed.

### 9.4 UI implementation boundary

The frontend never executes generated Python. It uses a documented local HTTP API. FastAPI owns revision status and job lifecycle; worker processes run separately. HTTP API contracts and generated OpenAPI types should be covered by integration tests. V1 must support one local user; multi-user permissions are deferred.

---

## 10. Rendering architecture

### 10.1 Runner protocol

Rendering is performed via an isolated worker command with a structured job payload:

```json
{
  "job_id": "job_0042",
  "project_id": "divisive_normalization_intro",
  "revision_id": "rev_0004",
  "family_id": "computational_neuroscience",
  "operation": "render_snapshots",
  "snapshot_ids": ["excitation_visible", "pool_introduced"],
  "quality_profile": "preview"
}
```

The control plane resolves the family, checks its lock/environment, validates allowed paths and job arguments, and launches the worker in that environment. The worker emits JSON status/log messages and returns an artifact manifest.

### 10.2 Reproducibility and isolation

- Local renderer process with explicit cwd, environment variables and bounded resource settings where supported.
- No importing arbitrary user-generated Manim code into the HTTP server process.
- Explicit `ffmpeg`, LaTeX, font and Manim toolchain versions where feasible; verify required executables.
- Store seed values for stochastic scenes. Prefer deterministic data transforms and stable object ordering.
- Do not promise byte-identical MP4 files across OS/GPU/toolchain combinations; record enough to explain differences and reproduce visual intent.
- Cancel jobs by terminating the worker process group safely, preserving logs and failed-job metadata.
- Set an output-directory policy that prevents workers from overwriting approved artifact revisions.

### 10.3 Rendering profiles

| Profile | Typical use | Constraints |
|---|---|---|
| `storyboard` | Fast conceptual stills | May be schematic; not final-appearance evidence |
| `snapshot` | Actual checkpoint stills | Must be exact deliberate visual states |
| `draft` | Motion review | Reduced resolution/quality permitted, but preserve relative timing |
| `final` | Presentation/publication | Enforce requested dimensions, fps, duration, codec, file checks |

Define fast preview profiles separately from exact delivery settings. Never let a preview override persist into the final spec.

### 10.4 Reusable animation primitives

Initial library should include stable components with style-token interfaces:

- LaTeX equation block and term-by-term highlighting.
- Axes with plot curves, uncertainty bands, legend and labels.
- Parameter-driven equation + plot coupling.
- Side-by-side comparisons with shared axes/scales.
- Spatial receptive-field glyphs (1D/2D) and topographic maps.
- Small network graphs, arrows and activation/weight encodings.
- Figure caption, inline citations, source acknowledgment.
- Transformations/stepwise reveals with predictable checkpoint constructors.

Make components optional conveniences, not restrictions on novel Manim code. **A generated scene can use other APIs**, but it must remain style-compliant, traceable and snapshot-capable.

---

## 11. Versioning, iteration, and change management

### 11.1 Two parallel version concepts

- **Git commits:** Version the package, code, documentation, schemas, styles, templates and optionally human-authored project source.
- **Project revisions:** Numbered immutable states that tie together exact spec, storyboard, generated code, inputs and rendered artifacts. The UI tracks these independently of Git.

V1 may implement project revisions by storing full manifests plus immutable copies/diffs of YAML/code, rather than building a sophisticated graph database. SQLite can index revisions and feedback; files remain the canonical portable representation.

### 11.2 Revision types

`spec_change`, `storyboard_change`, `style_change`, `code_fix`, `source_change`, `preview_feedback`, `draft_feedback`, `final_export`.

Every revision must answer:

- What changed?
- Why?
- Which upstream inputs led to this state?
- Which downstream results are now stale?
- Which snapshots or videos have actually been generated/approved?

### 11.3 Efficient regeneration

Start with **scene-level invalidation** and conservative dependency tracking. The agent records which scenes use which source files and style tokens. If dependency resolution is uncertain, rerender more rather than serve falsely current previews.

Future optimization may be object-level caching or reusable shots. Neither should block a functional first version.

---

## 12. Packaging, sharing, and portability

### 12.1 Shareable unit

A single animation folder, an entire family, or a curated collection can be exported using a common archive structure. The archive should be inspectable without SciAnim installed.

Example export:

```text
DivisiveNormalization.scianim.zip
└── scianim-bundle/
    ├── bundle.yaml
    ├── README.md
    ├── projects/
    │   └── divisive_normalization_intro/
    │       ├── animation.yaml
    │       ├── storyboard.yaml
    │       ├── references/            # Only distributable source assets
    │       ├── data/
    │       ├── code/
    │       ├── revisions/
    │       └── renders/               # Optional selected renders
    ├── styles/
    ├── components/
    ├── environments/
    │   ├── pyproject.toml
    │   └── uv.lock
    └── MANIFEST.sha256
```

The bundle manifest records `schema_version`, package compatibility, project IDs, optional family manifest, provenance, asset inclusion policy, license metadata and checksums.

### 12.2 Import/export rules

- Never package `.venv`, OS-specific caches, access tokens, secrets, or private model credentials.
- Exclude source PDFs and licensed fonts by default unless the user explicitly authorizes inclusion and rights permit sharing.
- Support `--include-renders`, `--include-source-assets`, `--redact-paths` flags with explicit checks.
- Treat imported Python as untrusted; inspecting a bundle must not execute its code. Import can validate manifests/paths/checksums without rendering.
- No absolute paths and no symlinks escaping the archive root.
- Preserve an explicit record of omitted sources and how to relink them.
- Export should be deterministic enough for meaningful checksum verification (allow exceptions for archive metadata only if documented).
- Include a lockfile and install instructions; rebuilding the environment is an explicit post-import step.

### 12.3 Collaboration evolution

For V1, a shared archive or a Git repository is enough. A future registry may allow discovery of themes, animation families, components, and public showcases, but this is beyond the first implementation.

---

## 13. Security and trust model

This application intentionally generates executable Python, so **security cannot be added later as an afterthought**.

- Assume scientific PDFs, imported Markdown/YAML, and bundle contents may contain malicious or misleading instructions. Treat them as *data*, not authoritative instructions to the agent.
- Never allow arbitrary Python/shell supplied by an HTTP request to execute in the FastAPI process.
- Validate filesystem paths, archive traversal, source checksums and environment selection.
- Run Manim in a separate process with a controlled working directory and no implicit access to stored credentials. For untrusted imported projects, require explicit trust/approval and preferably OS-level sandboxing before rendering.
- In V1, default to **local-only loopback binding** (127.0.0.1) and explain that running arbitrary user-generated Manim code is not a hardened public service.
- Disable automatic network access in rendering when practically enforceable; if not reliably enforced, do not claim strong sandbox isolation.
- Ask permission before downloading models/assets or invoking network-dependent package installation.
- Do not implicitly upload source PDFs or local datasets to an external LLM; the UI/agent adapter must disclose which content is transferred and provide local-only or redacted pathways where supported.
- Provide explicit per-project export controls for potentially sensitive or proprietary data.

---

## 14. API and CLI surface

The CLI is the **canonical agent interface**. The UI and model adapters call equivalent service operations rather than maintaining separate logic.

Recommended commands (final names to be refined during implementation):

```bash
scianim doctor
scianim workspace init /path/to/workspace
scianim family init computational_neuroscience --style tomas_scientific
scianim family env sync computational_neuroscience
scianim project init divisive_normalization_intro --family computational_neuroscience
scianim validate path/to/animation.yaml
scianim plan path/to/project             # Create/refresh storyboard proposal
scianim snapshot path/to/project --all   # Named checkpoint stills
scianim snapshot path/to/project --id equation_complete
scianim render path/to/project --profile draft
scianim render path/to/project --profile final
scianim revisions path/to/project
scianim bundle export path/to/project --output bundle.scianim.zip
scianim bundle inspect bundle.scianim.zip
scianim bundle import bundle.scianim.zip --into /path/to/workspace
scianim serve --host 127.0.0.1 --port 8765
```

Commands that require LLM reasoning (e.g. `plan`) must be able to call an installed/configured adapter *or* cleanly export a prompt/context package for an external coding agent. Do not require cloud API keys merely to validate or render a fully specified animation.

### 14.1 Essential HTTP resources

- `GET /api/families`, `GET /api/projects`, `POST /api/projects`
- `GET /api/projects/{id}`, `GET /api/projects/{id}/revisions`
- `POST /api/projects/{id}/spec-proposals`, `POST /api/projects/{id}/storyboard-proposals`
- `POST /api/projects/{id}/feedback`
- `POST /api/projects/{id}/approvals`
- `POST /api/projects/{id}/jobs` (snapshot, draft, final)
- `GET /api/jobs/{id}`, `POST /api/jobs/{id}/cancel`
- `GET /api/artifacts/{id}` (server-enforced paths)
- `POST /api/bundles/export`, `POST /api/bundles/import`

For jobs, return IDs and status; long-running render work must not block an HTTP request until completion. Use polling first; Server-Sent Events or WebSockets may be added later for live logs.

---

## 15. Validation, QA and acceptance criteria

### 15.1 Spec validation

- All hard output fields valid and mutually consistent (e.g. aspect ratio matches dimensions, fps positive, duration positive).
- `timeline` milestones within duration; exact/hard constraints do not conflict.
- All referenced input paths exist at the appropriate workflow stage, with explicit support for unresolved planned sources in draft specs only.
- Style name and pinned version resolvable.
- Namespaced extensions allowed; unknown root fields rejected.
- Missing data units flagged; scientific content not silently fabricated.

### 15.2 Visual QA

- No clipping outside declared safe zones, except intentionally full-bleed elements.
- Fonts load or explicit fallback reported; mathematical glyphs render correctly.
- Axis labels and legends are legible in final and draft views.
- Roles from the stylesheet are consistently applied.
- At least one simple scene has golden-reference snapshot tests (platform-tolerant image comparison rather than byte-identical pixels).

### 15.3 Render QA

- Generated output matches requested pixel dimensions, fps and frame-count/allowed duration tolerance.
- Outputs are readable by a standard media probe.
- Failed jobs preserve logs and cannot be mistaken for final approvals.
- Snapshot names and IDs resolve to the correct scene and revision.
- Changing a style token invalidates relevant cached snapshots.
- Rebuilding family environment from the committed lock works in a fresh checkout on supported platforms.

### 15.4 End-to-end acceptance scenario

On a clean supported machine, with the example synthetic CSV and no external paid LLM API:

1. Run `scianim doctor` and initialize a workspace.
2. Resolve the example family environment with `uv`.
3. Validate example `animation.yaml` and `storyboard.yaml`.
4. Render **at least two named snapshot states** from a Manim scene.
5. Open them in the local browser, place a region annotation, and save it to a specific revision.
6. Make a style change, see affected snapshots become stale, regenerate them, compare old/new.
7. Render a 720p draft and a final MP4 respecting the declared output contract.
8. Inspect render provenance and revision lineage.
9. Export a bundle without `.venv` or secrets, import it into a fresh workspace, verify manifests, rebuild dependencies, and reproduce the snapshots.

This is the definition of the **first complete product**, as distinct from the smaller first coding milestone.

---

## 16. Implementation phases and priorities

Implementation order is intentionally chosen to de-risk source-of-truth, environments and snapshots **before** investing heavily in LLM automation.

### Phase 0: Technical foundations

- Bootstrap Python package, linters/tests, schemas, `uv` setup.
- A sample family environment runs a minimal Manim scene in a child process.
- Validate dimensions, source paths, theme resolution and lockfile discovery.
- Basic `scianim doctor`, `validate`, `family env sync` commands.

**Gate:** A fresh checkout can install a family environment and validate a YAML spec without importing Manim into the control process.

### Phase 1: Named snapshot MVP

- Render a programmatically constructed named snapshot from an example scientific Manim scene.
- Produce artifact manifests, logs, and reproducible IDs.
- Add basic stylesheet tokens and a minimal component (plot + labels).
- Wire `scianim snapshot` to family environment resolution.

**Gate:** An edited theme token changes the intended objects in new checkpoint PNGs; no complete MP4 is required.

### Phase 2: Browser-based review

- Local FastAPI endpoints, SQLite project/job/revision database.
- React interface to browse scenes/checkpoints and view images.
- Image-region annotations, notes, revision IDs and approval flags.
- Snapshot regeneration and side-by-side comparison.

**Gate:** User can leave an anchored visual correction without touching Python.

### Phase 3: Full storyboard and video loop

- `storyboard.yaml` scene timeline, source bindings, validation.
- Draft and final rendering with metadata probe and technical QA.
- Revision invalidation, render logs, cancellation/retry.

**Gate:** A 60-second example moves from specification to approved storyboard to draft and final MP4.

### Phase 4: Agent-assisted creation and revision

- Provider-neutral agent adapter and documented context export.
- Brief-to-spec and spec-to-storyboard flows.
- Code-generation templates for a few core scientific animation patterns.
- Targeted patch/update workflow; uncertainty reporting and source traceability.

**Gate:** From supplied prompt + example data, an agent builds a valid spec and storyboard, generates named checkpoints, and applies one region-specific revision with a traceable diff.

### Phase 5: Portable families and bundles

- Nested thematic grouping, family manifests, environment inheritance.
- Portable export/import with hashed manifest and license/source filtering.
- Documentation and golden-reference end-to-end examples.

**Gate:** Shared bundle round-trips into a fresh workspace with no absolute paths, no local environment, and working reproducible renders.

### Later (explicitly not MVP)

- Self-hosted multi-agent generation, autonomous scientific verification, multi-user permissions.
- Non-Manim renderer plugins and 3D/volume visualizations as first-class outputs.
- Audio narration alignment, automatic captions, multilingual variants.
- Public registry/store for families and styles; web-hosted renderer farm.
- Fine-grained object-level incremental rendering, interactive animations, bidirectional editing of generated geometry.

A smaller task-by-task implementation checklist is in `docs/IMPLEMENTATION_PLAN.md`.

---

## 17. Open decisions that must be documented, not guessed

The implementing agent should put considered decisions in an ADR or issue, not silently improvise:

1. **Style signature:** initial colors, fonts, transition tempo and plotting defaults should be proposed with 2–3 alternative sample stills for the user to approve. The project name `tomas_scientific` is a placeholder, not a claim that these tokens are finalized.
2. **Version strategy:** Pydantic schemas and themes need a migration policy before community sharing.
3. **Supported platforms:** prioritize macOS/Linux, optionally Windows; test LaTeX/FFmpeg/Manim prerequisites explicitly.
4. **PDF ingestion:** acceptable local extraction fidelity and when visual/manual inspection is needed.
5. **Agent execution security:** how much local filesystem and network access the chosen coding agent gets, and what it must ask before executing.
6. **Narrative authoring:** whether initial UI storyboard edits directly change YAML or produce validated patch proposals.
7. **Bundle defaults:** export only source manifests unless assets are redistributable and specifically selected.
8. **Audio:** V1 `audio: none`; narration/subtitles should have their own explicit schema when introduced.
9. **Frame sampling:** how scene checkpoint states and full-video time samples are reconciled, with no claims of frame equivalence unless verified.

---

## 18. Definition of success

SciAnim Studio succeeds when the user can supply a paper, dataset, illustration, existing scene, or simple prompt; see a scientifically faithful animation plan under a recognizable personalized style; point at a still and request a change; inspect differences across versions; and export a precise final Manim animation **without ever needing to write or read Manim code**.

At the engineering level, success means another coding agent can understand the package contracts, reproduce the render from versioned inputs, extend an animation family with additional scientific packages without contaminating the core installation, and share a project as a self-contained and auditable bundle.

**Build the smallest vertical slice of that experience first.** A named scientific snapshot, rendered inside an isolated family environment from a validated YAML specification, is more valuable than a large unfinished application shell.
