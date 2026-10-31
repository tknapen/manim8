# SciAnim Studio: agent-ready project specification

**Status:** Proposed architecture / implementation handoff  
**Version:** 0.2 (26 October 2026; revised after [`PLAN_REVIEW.md`](PLAN_REVIEW.md))  
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

Most of an animation is composed from a **registry of typed components** (section 10.4) and previewed through **named checkpoints reached by the real animation flow** (section 8.2). Bespoke Manim code is the escape hatch, not the norm.

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
- Write or edit the narration script per scene; scene durations are proposed from it and subtitles are derived from it.
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
5. **Still previews.** A preview worker renders named checkpoints reached by the real animation flow, each with a layout report. User annotates images or objects and approves visual language/scientific content.
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
| Equations | Typst through Manim's `MathTypst` by default; LaTeX opt-in per family | Typst installs from PyPI inside the family lockfile; LaTeX needs a system TeX distribution and `dvisvgm` that no lockfile can pin |
| Video encoding | Manim's built-in PyAV encoder | No system `ffmpeg` is needed to render; Manim encodes through `av` |
| Scene segmentation | One Manim section per storyboard scene (`next_section`, `--save_sections`) | Per-scene videos and a JSON index give incremental rendering and duration verification |
| Components | Registry of typed kinds shared by validator, code generator and renderer | Most storyboards render without bespoke code; parameters are validated; cache keys are precise |
| Control plane | Python 3.12+ with Pydantic v2 | Typed contracts, validation, CLI, manageable testing |
| YAML | `ruamel.yaml` or PyYAML for parsing; Pydantic for validation | Human-editable specifications with explicit schema versions |
| CLI | Typer | Clear scriptable agent interface |
| Backend | FastAPI | Local API, job orchestration, review metadata |
| Web frontend | React + TypeScript + Vite | Fine-grained image annotation and side-by-side version review |
| Local metadata | SQLite, accessed via SQLAlchemy or equivalent | Reliable revision/job records without running extra services |
| Render job runner | Local subprocess worker and process group management | Isolates dependency-heavy rendering from control/API processes |
| Family environments | `uv`-managed project environment and `uv.lock` per declared family, plus declared `system_requirements` | Fast reproducible installs and sharing; no base-environment contamination; system-level prerequisites are explicit |
| Source control | Git | Human-readable specs, code, themes, reusable components, documentation |
| Render cache | Content-addressed keys plus artifact manifests | Reuse unchanged scenes and preview assets |
| LLM integration | Adapter interface, provider-agnostic | Works with different coding agents or model APIs |

**Boundary:** The orchestration server must not import Manim or arbitrary per-family scientific packages. It invokes a renderer in a *separate process* using the selected family environment. This boundary is essential to isolation. The code is split into three distributions: `scianim-core` (Pydantic contracts only), `scianim` (control plane: CLI, validation, jobs, API) and `scianim-bridge` (render-side helpers that import Manim). Families depend on `scianim-bridge`; nothing in a family environment depends on `scianim`.

**Core in V1:** One primary Manim rendering backend. Later adapters may support Matplotlib, VTK, PyVista, Blender, or other specialized visualizations, but that is not required to ship the first useful version.

---

## 4. Repository and workspace layout

A recommended layout for the implementation repository:

```text
scianim-studio/
├── README.md
├── AGENTS.md                         # Top-level agent operating contract
├── pyproject.toml                    # uv workspace root and the `scianim` control-plane package
├── uv.lock
├── .gitignore
├── packages/
│   ├── scianim_core/                 # `scianim-core`: Pydantic contracts only (specs, component
│   │                                 #   parameter models, job payloads, manifests). Depends on pydantic.
│   └── scianim_bridge/               # `scianim-bridge`: render-side helpers (style tokens, components,
│                                     #   checkpoint(), layout report, worker). Depends on manim + core.
├── src/scianim/                      # Control plane. Never imports manim or scianim_bridge.
│   ├── cli.py
│   ├── workspace.py                  # workspace init/list, family init, project init
│   ├── config/                       # YAML parsing and validation
│   ├── styles/                       # Versioned token cascade resolution and export
│   ├── families/                     # Nearest-family resolution, groups, assets, uv sync
│   ├── planning/                     # Storyboard timing, narration estimates, cross-file checks
│   ├── codegen/                      # Deterministic scene code from registered components
│   ├── render/                       # Job payloads, worker launch, cache keys, manifests
│   ├── revisions/                    # Write-once revision directories
│   ├── review/                       # Static review sheets, comparisons, feedback files
│   ├── clean.py                      # Reclaim caches and superseded working renders
│   ├── bundles/                      # Export, import, checksums, portability (later)
│   ├── agents/                       # Provider-neutral context and patch contracts (later)
│   ├── api/                          # FastAPI server (Milestone 3)
│   └── security/                     # Path control, trust, process constraints
├── web/                              # React + TypeScript UI (Milestone 3)
├── styles/                           # Bundled themes, copied into new workspaces
│   ├── default/0.1.0/style.yaml      #   <name>/<version>/style.yaml; inheritance pins name@version
│   └── tomas_scientific/0.1.0/style.yaml
├── schemas/                          # JSON Schemas exported from scianim-core
├── docs/
├── tests/
├── examples/                         # Read-only templates for `--from-example`; never rendered in place
│   └── families/computational_neuroscience/            # family.yaml, pyproject.toml, uv.lock
│       └── divisive_normalization/                     # project template nested under its family
└── workspace/                        # User data, created by `scianim workspace init`; gitignored
    ├── workspace.yaml
    ├── styles/<name>/<version>/style.yaml              # the user's themes (bundled ones copied in)
    ├── assets/                                         # asset://<id> shared across families
    └── families/
        └── computational_neuroscience/
            ├── family.yaml           # Family ID, style, environment, system requirements
            ├── pyproject.toml        # Family render dependencies: manim, scianim-bridge, science packages
            ├── uv.lock               # Committed / shareable dependency lock
            ├── .venv/                # Local only; never export/commit
            ├── assets/               # asset://<id> shared within the family
            ├── components/           # Custom builders shared within the family
            ├── perception/           # A topical group: a folder with group.yaml (style overrides,
            │   ├── group.yaml        #   assets, tags); never an environment
            │   └── retinotopy_intro/
            └── divisive_normalization/
                ├── animation.yaml    # `family:` is optional: the nearest family.yaml is authoritative
                ├── storyboard.yaml
                ├── references/
                ├── data/
                ├── code/             # Generated, reviewable Python (scene module, custom builders)
                ├── feedback/         # Canonical annotation records (*.yaml); the UI edits these
                ├── revisions/        # rev_0001/ ...: write-once copies of specs, code, resolved style
                ├── renders/          # working/<job>/ and rev_0001/<job>/: PNGs, manifest.json, sheets
                └── .scianim/         # jobs, logs, cache pointers, materialized assets, Manim media
```

`scianim workspace init <dir>` creates a workspace anywhere (the repository's `workspace/` is gitignored for convenience); `scianim family init` and `scianim project init` populate it, optionally from the read-only templates under `examples/`. **The user never creates these folders by hand.** `scianim workspace list` inventories families, groups and projects and reports duplicate ids.

### 4.1 Hierarchy and inheritance

- Styles live at `styles/<name>/<version>/style.yaml`, in the workspace and in the bundled set the workspace was initialized from. A project pins `name` and `version`; a sheet inherits another only as `name@version`. Several versions of one theme coexist, so old projects keep rendering with their pinned theme after a bump, and a bundle carries exactly the pinned sheet.
- A `family.yaml` selects a stylesheet version and supplies family-specific overrides and system requirements.
- **The nearest `family.yaml` above a project is authoritative.** `animation.yaml` may omit `family:`; when present it must match the nearest declaration, and a mismatch is an error rather than a search. Only a project outside every family directory is looked up by id, and that id must be unique. A `family.yaml` deeper in the tree is an explicit child-family boundary.
- Optional `group.yaml` files in the folders between a family and a project define topical groups: style overrides applied after the family's, shared assets and tags. A group never declares an environment.
- An `animation.yaml` can override only explicitly permitted tokens, not silently supersede declared hard rules.
- Each project has a stable ID independent of its folder name, so projects can be moved without losing revision identity. Duplicate project ids within a workspace are reported by `scianim workspace list`.
- `asset://<id>` sources resolve against the family's `assets/`, then the workspace's; custom builders resolve against the project's `code/`, then the family's `components/`.

### 4.2 Dependency isolation

A rendering family has:

- `pyproject.toml`: explicit `manim`, family visualization/data packages, and the `scianim-bridge` version (never `scianim` itself).
- `uv.lock`: full resolved dependency graph, preferably including platform constraints where needed.
- `.venv/`: generated from the lock on the local machine; not part of the portable project.

A child animation reuses its family's environment unless it explicitly belongs to a child family with its own lockfile. Never install a requested dependency into the orchestrator's environment to make a family render work.

For local development, the family may use an editable/path dependency for the `scianim` package. For portable export, replace development-only absolute paths with a published package reference, a relative vendored source, or a documented install step. The bundle validator must flag unresolved absolute paths.

In the first implementation, **one environment per family** is sufficient. A content-addressed shared environment cache across families can be added later if identical locks make duplication costly. Avoid optimizing that before the lockfile workflow works reliably.

`uv` pins Python packages only. Fonts, Pango and Cairo libraries, SoX for voiceover, and a TeX distribution where a family opts into LaTeX are system-level. `family.yaml` therefore declares `system_requirements` (binaries with minimum versions, font files with hashes, optionally a container image digest); `scianim doctor` checks them per family and bundles list them for recipients. `environment.manager` may be `uv` (default), `docker` or `apptainer`; the container managers are the route to full reproducibility for families that keep LaTeX.

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
| `equations` | Typed equations: `id`, `typst` and/or `latex` source, `symbols` with meanings and optional units, optional source locator. The renderer typesets the stored string exactly; constraints and storyboard objects reference equations by `id` |
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

equations:
  - id: schematic_equation
    typst: "r = E / (sigma + P)"
    latex: "r = \\frac{E}{\\sigma + P}"
    symbols:
      r: {meaning: "schematic response"}
      E: {meaning: "excitatory drive"}
      P: {meaning: "normalization pool drive"}
      sigma: {meaning: "positive stabilizing constant"}

audience: graduate_neuroscience
objective: >-
  Introduce the logic of a normalization pool and show how
  increases in pool drive alter a schematic neural response.
scientific_constraints:
  - id: eq1
    kind: hard
    equation: schematic_equation
    text: "Show the schematic equation exactly as stored and define E, P and sigma."
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

- Ordered `scenes` with stable IDs, start/end times, titles, pedagogical purposes. Each scene becomes one Manim section.
- `narration` per scene: the script, optionally with named marks (`<mark name="pool"/>`). It anchors pacing, produces subtitles, and later aligns voiceover.
- `objects`: instances of registered component kinds (section 10.4) with typed `params`. Data-driven objects carry an explicit `data` binding (`source`, `encoding`, `transforms`); equation objects reference `equations[].id` from the animation spec and may name terms to `highlight`, with a `highlight_mode` (`always`: every named term carries the accent; `active`: only the term that a running action emphasizes does, and the colour passes to the next term when its action begins). Every object is bound to style roles, never to literal colors. An object may carry `reveal_at_seconds`, an absolute time inside its scene at which it appears; objects without it appear at the scene start in declaration order. Text-like objects are placed by `anchor`, or relative to an earlier object of the same scene with `below` or `right_of` and an optional `gap_px_at_1080p` (the style's baseline grid by default).
- Layout constraints such as anchors, grids, safe zones, target positions.
- `actions`: things that happen while the scene plays. `vary_parameter` names a `function_plot`, `surface_plot` or `function_image`, one of its named `parameters`, a target value and a window (`at_seconds`, an optional `lead_in_seconds`, `duration_seconds`); the equation objects listed under `emphasize` (each must highlight that symbol) light their term up and pulse it once as the action begins, a readout under the first of them shows the value (`show_value`, `value_decimals`, `value_label`), and the picture follows the value once the lead-in is over. `orbit_camera` turns the camera to given angles (`to_theta_degrees`, `to_phi_degrees`) over a window; it needs a surface in the scene. `fade_axes` fades a surface's frame, ticks and labels out (`visible: false`) or back in over a window, leaving the surface itself. Actions run concurrently; only two that drive the same parameter of the same object, two orbits, or two axes fades of the same object may not overlap. Reveals are tracks too, and objects without a reveal time appear together at the scene start. Ranges stay fixed on anything that varies. A checkpoint inside a window splits every running track at that frame, so it is still a marker reached by the real flow (ADR-022, ADR-024, ADR-026).
- Transitions and camera movements (not yet in the schema).
- **Snapshot checkpoints** at explicit moments, naming expected visual states. Each becomes a `checkpoint()` marker in the generated code.
- Conditions/acceptance notes for visual and scientific review.

Example:

```yaml
schema_version: "1.0"
project_id: divisive_normalization_intro
based_on_animation_revision: "<resolved-revision-id>"

scenes:
  - id: excitation
    start_seconds: 0
    end_seconds: 6
    purpose: "Excitatory drive alone: the response grows with it."
    narration:
      text: "The response begins with excitatory drive: as the drive grows, so does the response."
    objects:
      - id: drive_caption
        kind: text_caption
        style_role: foreground
        params: {text: "Excitatory drive alone", role: body}
      - id: drive_curve
        kind: scientific_plot
        style_role: primary_signal
        data:
          source: responses
          encoding: {x: excitation_E, y: response_r, group: condition}
          transforms:
            - {op: filter, column: condition, equals: low_pool}
        params:
          x_label: "excitatory drive E"
          y_label: "response r"
          data_label: "synthetic data"
    snapshots:
      - id: excitation_visible
        at_seconds: 4
        description: "Caption and the synthetic excitation curve with labelled axes"

  - id: normalization
    start_seconds: 6
    end_seconds: 18
    purpose: "Divide by a normalization pool, then raise the pool and watch the response compress."
    narration:
      text: >-
        Dividing by a normalization pool P compresses it: as the pool grows, the same drive
        yields a smaller response.
    objects:
      - id: response_curve
        kind: function_plot
        style_role: primary_signal
        equation: {id: schematic_equation}
        params:
          x_label: "excitatory drive E"
          y_label: "response r"
          x_range: [0, 10]
          y_range: [0, 6]
          anchor: center_left
          width_fraction: 0.55
          parameters: {sigma: 1, P: 1}
          series:
            - {label: "schematic response", expression: "x / (sigma + P)"}
          data_label: "schematic curve from the equation"
      - id: normalization_equation
        kind: equation_block
        style_role: foreground
        equation: {id: schematic_equation, highlight: [P]}
        params: {anchor: top_right, scale: 0.9}
        reveal_at_seconds: 7
    actions:
      - id: raise_pool
        kind: vary_parameter
        target: response_curve
        parameter: P
        to: 4
        at_seconds: 8.5
        duration_seconds: 4
        emphasize: [normalization_equation]
    snapshots:
      - id: pool_introduced
        at_seconds: 8
        description: "The response curve for P = 1 with the equation beside it; P highlighted"
      - id: pool_raised
        at_seconds: 14
        description: "After the sweep the curve is compressed; the readout reads P = 4.0"
```

The storyboard is a **contract and planning format**, not a full substitute for generated Python. Its syntax must remain compact enough for LLMs to create and humans to inspect. `scianim validate` checks each object's `params` against its kind's parameter model, each `data.source` against the animation's sources, each `equation.id` against `equations`, each `style_role` against the resolved palette, and each snapshot ID against the `checkpoint()` markers in generated code once code exists. A storyboard made only of registered kinds is rendered without hand-written code (`scianim codegen`); an object with `kind: custom` names a builder function in `code/` and is the explicit escape hatch. Allow an optional explicit `layout`/`timing` substructure when finer control is requested.

### 5.3 Style files and design tokens

A stylesheet defines an artistic signature **semantically**, not merely through a handful of global color variables. Required categories:

- **Palette roles:** foreground, background, secondary text, highlight, muted, neutral, excitatory, suppressive, uncertainty, selection, error; tokens map to hex/RGB values.
- **Typography:** font family preferences and fallbacks (the renderer picks the first installed family and reports any substitution in the manifest); one named role per kind of text, each with its own size token: `title`, `body`, `annotation` (marker labels, legend entries, symbol definitions), `axis_label`, `tick_label`, `caption`, and `equation` with `size_px_at_1080p` and `label_size_px_at_1080p`; `minimum_text_px_at_1080p`, which no role may fall below (the resolved style rejects one that does); weight, line-height and wrapping rules; the equation engine (`typst` by default, `latex` opt-in) with its math font (`math_font` and fallbacks for Typst, `latex_packages` for LaTeX); font licensing checks for export. Components never scale one role to obtain another.
- **Geometry:** standard canvas padding, safe-zone rules, gaps, graph line widths, marker sizes, grid and panel conventions.
- **Charts:** `spines` (the axis lines that are drawn; every plot kind is despined by default, with only the left and bottom spines along the data box edges and never through the origin), `spine_offset_px_at_1080p`, tick density, background grid, legend positions, color order and scientific plotting defaults.
- **Motion:** duration defaults, easing, stagger, transition style, pacing (including `narration_words_per_minute` for duration proposals) and camera movement policies; the rules of smoothness as tokens: `easing` for sweeps, fades and colour, `camera_easing` with `ramp_seconds` for orbits (`eased_linear` ramps up, holds its speed and ramps down), `hold_seconds` for the rest between two motions of one object, and the pulse (`emphasis_scale`, `emphasis_seconds`); `scianim validate` warns when a storyboard asks for linear motion, a lead-in shorter than the pulse or a shorter rest (ADR-028).
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

Resolution produces a `ResolvedStyle` document with every token, a provenance map naming the layer that set each token, and a content hash. The renderer receives this document, never the YAML chain, and the hash enters cache keys.

The bundled baseline is `default@0.5.0`, **line and wash after Keenan Crane**: a white page, every edge drawn in one thin dark-blue line that ends and bends in a half circle, flat pale washes with blue and orange as the working pair, surfaces solid and modelled by one soft light from the viewer's upper left over a quiet mesh in the muted ink, labels in the same Palatino lineage as the equations, filled dots rimmed in the page colour, and the motion rules of slow in and slow out as tokens (ADR-025, ADR-027, ADR-028, ADR-030). It is published as a chain of versions, each inheriting the previous, with a philosophy and a specimen rendered from the examples beside the newest; the personal layer `tomas_scientific@0.5.0` pins it and is deliberately thin.

Theme changes must be **versioned**: a new version is a new directory `styles/<name>/<version>/`, never an edit of a published one. Re-rendering an old animation uses its pinned theme by default; adopting a newer theme is an explicit revision, not a silent side effect. Inheritance is pinned (`inherits: default@0.1.0`) so a theme's resolved tokens do not drift when its parent gains a version.

### 5.4 `family.yaml`: scope and environment

Each family declares a unique ID, display name, environment root/lockfile and manager, `system_requirements` (binaries, fonts, libraries or a container image that `uv` cannot pin), style selection, shared assets, the component kinds it expects, and optional schema extensions. Nested children inherit a parent family only when no new family declaration exists. Dependencies are never inferred from `requirements.txt` files found at arbitrary depths.

### 5.5 Revision and artifact manifests

Every accepted change produces a revision ID, a timestamp, a change description, parent revision pointer(s), hashes of the spec/storyboard/generated code/style/sources, and optionally the issuing agent/model (if known). A render manifest records:

- Requested profile, dimensions, fps, duration and encoding.
- Actual output metadata, file checksum and validation results.
- Git commit or source-tree hash.
- `uv.lock` hash and selected interpreter/renderer versions.
- Source asset checksum list, with source provenance.
- Snapshot names and frame indices actually rendered.
- Errors, warnings, elapsed time and cache-hit information.
- Checkpoint records with kind (`manim_checkpoint`, `sampled_video_frame`, `storyboard_schematic`), layout report and fidelity warnings.
- Renderer configuration: renderer backend, equation engine, pixel format, codec and encoder options, seed.

Manifests are JSON files named `manifest.json`. Never use a bare `.manifest` extension: the common Python `.gitignore` template ignores `*.manifest`, `*.spec`, `*.log` and `lib/`.

A revision is immutable. The *working copy* may evolve, but approval and render actions operate on revision snapshots; this avoids stale renders or confusing feedback attached to the wrong code version. `scianim revision create` writes `revisions/rev_NNNN/` once (specs, generated code, resolved style, `revision.json` with hashes); data files stay in `data/` and are recorded by hash, and `scianim snapshot --revision rev_NNNN` refuses to render if they changed. Renders go to `renders/<revision>/<job>/`; `renders/working/` holds renders of the working copy, which `scianim clean` may discard.

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
4. Prefer registered components over bespoke scene code; declare any bespoke object explicitly as `kind: custom`.
5. Generate and validate `animation.yaml` and `storyboard.yaml` before Manim code.
6. Keep all generated files within the assigned project, save source provenance, and avoid uncontrolled external commands.
7. Produce named snapshot checkpoints, not just a full video.
8. After feedback, modify the smallest affected scope; do not rewrite unrelated scenes.
9. Run appropriate validation/tests before claiming work is complete.
10. Inspect the rendered checkpoint images and layout reports against each snapshot's description, and list discrepancies, before requesting human review.
11. Report exactly which outputs were created, what was actually rendered, any warnings, and what still needs scientific approval.

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

**Important:** Checkpoints must be named, deliberate and traceable to the storyboard. Manim's fast-forward mode (the mechanism behind its `-s` flag) makes it cheap to reach them from the real animation code; what it does not provide on its own are names, layout reports and fidelity warnings. The render bridge adds those.

### 8.1 Three kinds of previews

1. **Storyboard image** (`storyboard_schematic`): a quick, optionally schematic still generated from scene/object layout, without running a full animation. Useful for narrative approval, but may not be pixel-identical to final Manim frames.
2. **Manim checkpoint** (`manim_checkpoint`): an actual rendered frame at a named marker reached by the real animation flow in fast-forward mode (section 8.2).
3. **Sampled video frame** (`sampled_video_frame`): a frame extracted from a rendered draft or final video at a requested time. More expensive, but exact for motion-dependent states and for checkpoints that fast-forward cannot reproduce faithfully.

Never label a schematic storyboard image as an exact rendered keyframe. The UI and manifests always identify which kind is being shown.

### 8.2 Checkpoint implementation

Checkpoints are **named markers reached by the real animation flow**, not states rebuilt by a parallel constructor. Generated scene code calls a helper from the render bridge at each named moment:

```python
# Illustrative; the committed API lives in scianim_bridge.
from scianim_bridge import SnapshotScene, checkpoint


class DivisiveNormalizationIntro(SnapshotScene):
    def construct(self):
        self.next_section("excitation")
        ...  # components build and register their mobjects under storyboard object IDs
        checkpoint(self, "excitation_visible", expected_time=9.0)
```

In snapshot mode the worker runs the scene in Manim's fast-forward mode: every `play()` advances in a single time step, no frames are encoded, and the whole scene is traversed in one pass. Each time `checkpoint()` is reached the helper redraws the frame (`renderer.update_frame`), captures it (`renderer.get_frame()`), writes a PNG, and records the animation index, the expected scene time, the layout report (section 8.5) and any fidelity warnings. In video mode the same call records the frame index and otherwise does nothing. One code path therefore produces both the stills and the video, and the storyboard's `snapshots[].id` list must match the markers present in the code; `scianim validate` checks this parity statically by parsing the code for `checkpoint(...)` calls with literal IDs.

**Fidelity caveat.** In fast-forward each `play()` advances with one `dt` equal to its run time, and Manim skips its trailing zero-`dt` update. Content driven by `ValueTracker` and `always_redraw` ends in the correct state; updaters that integrate `dt` do not. The bridge checks the scene's mobjects for time-based updaters at each checkpoint and marks the record `fidelity: approximate`; such checkpoints should be confirmed from a **sampled video frame** of the section. Generated code from registered components never uses `dt`-integrating updaters.

Manim's `-n a,b` option combined with `-s` yields the frame at any animation boundary without extra code. It is a debugging aid, not the checkpoint mechanism, because it cannot name states or emit layout reports.

### 8.3 Preview budget

- First pass: storyboard cards and 3–8 named checkpoints.
- Second pass: changed checkpoints only (dependency-based invalidation).
- Third pass: optional low-resolution draft, initially 720p and reduced quality settings.
- Final: exact requested output. No unapproved resolution/time substitutions.

Checkpoint caches must include: scene code hash, source/data hash, resolved style hash, checkpoint definition, component registry version, bridge and Manim versions, the environment lock hash, and the renderer configuration that changes pixels or bytes (renderer backend, equation engine and template, pixel format, codec and encoder options, seed, quality) together with the resolved font files. A time-only key is insufficient.

### 8.4 Timing fidelity

The planner should map seconds to frame indices at the chosen fps; internal shot timing can remain in seconds. If a requested timestamp falls between frames, use a documented rounding policy. Validate exact total frame count for hard-duration outputs. A storyboard boundary may be moved within stated tolerances, but not past an immutable hard milestone.

Scene durations are **proposed from narration**: the planner estimates speaking time from each scene's `narration.text` at `motion.narration_words_per_minute`, then reconciles the proposal with hard milestones and the output duration. Conflicts are validation errors, not silent compression. Each storyboard scene is one Manim section (`next_section(scene_id)`), so a `--save_sections` render yields per-scene videos and a JSON index whose probed durations verify the storyboard timing frame by frame.

### 8.5 Layout report

Every checkpoint record carries a layout report: for each storyboard-named object present in the scene, its bounding box in normalized frame coordinates (origin top-left, [0, 1] on both axes), its kind, and for text-like objects the text content and rendered height in pixels at output resolution. The bridge computes this from Manim's own geometry (`get_corner`, `width`, `height`) without any image analysis; a three-dimensional object's box is its points projected through the camera, counting only members that draw ink, so a surface's invisible helper axes do not widen it.

The report powers deterministic visual QA in the worker: `outside_safe_zone` (bounding box beyond `layout.safe_margin_fraction`), `text_too_small` (the smallest text an object draws, tick labels and symbol definitions included, below `typography.minimum_text_px_at_1080p` scaled to the output height), and `overlap` between text-like objects. Warnings go into the manifest; they are advice for the reviewer and the agent, not hard failures. Downstream, the UI resolves a click to an object ID, feedback records carry `object_id`, `scianim compare` lists objects that moved or changed between revisions, and the agent inspects the report and the image against each snapshot's `description` before requesting review.

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

**G. Review sheet (static)**
- A per-revision HTML contact sheet of checkpoints with storyboard text, narration and layout warnings, generated by the CLI without the server. It is the first review surface (Milestone 2) and ships inside bundles.

### 9.2 Feedback model

Use explicit typed records:

```json
{
  "project_id": "divisive_normalization_intro",
  "revision_id": "rev_0004",
  "scene_id": "normalization_pool",
  "snapshot_id": "pool_introduced",
  "object_id": "pool_label",
  "kind": "region_comment",
  "region": {"x": 0.20, "y": 0.36, "width": 0.25, "height": 0.14},
  "text": "Increase spacing between the pool label and the curve.",
  "severity": "visual"
}
```

Coordinates are normalized to [0, 1], independent of preview pixel dimensions. Store resolved image dimensions and transform if the UI uses a cropped/letterboxed view. A video comment may instead identify a time range.

Feedback records are files in the project's `feedback/` directory (`*.yaml`), created by the CLI or by the UI; the UI is an editor for the same records, so an agent can read and write feedback without a browser. `object_id` is optional and resolved from the layout report when the reviewer clicks an object; a region is always stored as well.

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
  "scene_module": "code/scene_divisive_normalization_intro.py",
  "scene_class": "DivisiveNormalizationIntro",
  "snapshot_ids": ["excitation_visible", "pool_introduced"],
  "quality_profile": "snapshot",
  "output": {"width_px": 1920, "height_px": 1080, "fps": 30, "duration_seconds": 60},
  "resolved_style": {"hash": "sha256:...", "tokens": {"palette": {"primary_signal": "#56B4E9"}}},
  "data_files": {"responses": "data/synthetic_responses.csv"},
  "manim": {"renderer": "cairo", "pixel_width": 960, "pixel_height": 540, "media_dir": ".scianim/media/rev_0004"},
  "output_dir": ".scianim/jobs/job_0042",
  "cache_key": "sha256:..."
}
```

The control plane resolves the family, checks its lock/environment, validates allowed paths and job arguments, and launches the worker in that environment. The worker emits JSON status/log messages and returns an artifact manifest. The payload is self-contained: the worker needs no access to YAML, style chains or control-plane code. Give each revision a stable Manim `media_dir` under `.scianim/` so Manim's own per-`play()` cache works beneath the scene-level cache; do not disable it.

A video job with `workers` above one runs as three derived jobs of the same payload (ADR-029): `plan_video` fast-forwards through the scene and returns every play (`PlayRecord`: animation number, scene, start, frames, whether it is a still wait) and the checkpoints reached; `render_video_part` draws one contiguous range of plays (`part`) through Manim's animation-number window into a media directory of its own, fast-forwarding through the rest, and returns one encoded segment per play; `merge_video` joins the segments (`merge`) into the movie and its sections by copying packets, then verifies the timing and samples the checkpoints like a serial render. The stages' job files, logs and results live under the job's directory; the manifest is the parent job's, its result lists the parts and the measured time of every play. The control plane never decodes or joins video itself.

### 10.2 Reproducibility and isolation

- Local renderer process with explicit cwd, environment variables and bounded resource settings where supported.
- No importing arbitrary user-generated Manim code into the HTTP server process.
- Record Manim, PyAV, Typst or LaTeX toolchain and font versions in the manifest; `doctor` verifies executables and libraries against each family's `system_requirements`. Manim encodes through PyAV, so a system `ffmpeg` is not required to render.
- Store seed values for stochastic scenes. Prefer deterministic data transforms and stable object ordering.
- Do not promise byte-identical MP4 files across OS/GPU/toolchain combinations; record enough to explain differences and reproduce visual intent.
- Cancel jobs by terminating the worker process group safely, preserving logs and failed-job metadata.
- Set an output-directory policy that prevents workers from overwriting approved artifact revisions.

### 10.3 Rendering profiles

| Profile | Typical use | Constraints |
|---|---|---|
| `storyboard` | Fast conceptual stills | May be schematic; not final-appearance evidence |
| `snapshot` | Actual checkpoint stills | Named markers reached by the real animation flow in fast-forward; fidelity warnings recorded |
| `draft` | Motion review | Reduced resolution/quality permitted, but preserve relative timing |
| `final` | Presentation/publication | Enforce requested dimensions, fps, duration, codec, file checks |

Define fast preview profiles separately from exact delivery settings. Never let a preview override persist into the final spec. A video may be rendered at any profile: the two small ones give a quick look at the motion in a fraction of the time, and are no more evidence of final appearance than their stills.

### 10.4 Component registry

The registry is the contract shared by the storyboard author (human or agent), the validator, the code generator and the renderer. Each registered `kind` has:

- a Pydantic parameter model in `scianim-core`, so `scianim validate` checks `params` and not only the presence of a kind;
- a declared list of the style roles and tokens it consumes, and whether it requires a `data` binding or an `equation` reference;
- an implementation in `scianim-bridge` that builds Manim mobjects from the resolved style, the bound data and the parameters, registers them under the object ID for the layout report, and exposes deterministic reveal animations;
- a version, included in cache keys.

Initial kinds (V1, extended in Milestone 5 with `caption_with_citation`, `schematic_population`, `receptive_field_glyph` and `network_graph`): `scientific_plot` (axes, curves, optional bands and legend), `function_plot` (analytic curves from arithmetic expressions in `x` and named `parameters`, with labelled vertical markers whose positions may be expressions in those parameters; no data file; the target of `vary_parameter` actions), `surface_plot` (z = f(x, y) over a fixed box as a fine mesh in three dimensions, cells filled by sign, by height or on a diverging scale that keeps a flat field grey, labels that face the viewer; what `orbit_camera` turns around), `function_image` (f(x, y) sampled to pixels in two inks or grey, optionally a disc; a grating or a kernel), `equation_block` (typeset equation with optional symbol definitions and term highlighting), `equation_label`, `comparison_plot` (side-by-side panels with shared scales), `text_caption`. Planned next: `schematic_population`, receptive-field glyphs and topographic maps, small network graphs, figure captions with citations, stepwise reveals.

`scianim codegen` turns a storyboard composed entirely of registered kinds into a scene module deterministically, with one section per scene, components revealed in order, and one `checkpoint()` per snapshot at its requested time. This is the normal path. Bespoke Manim code is the escape hatch: an object declared `kind: custom` names a builder function in the project's `code/` directory (`params.builder: "custom:build_pool_schematic"`); the builder receives the scene, the resolved style and the object parameters, must register its mobjects for the layout report, and must not hardcode colors or fonts. YAML never contains executable code. The only computed values a storyboard may carry are the expressions of `function_plot` series and markers, `surface_plot` and `function_image`, which `scianim_core.expressions` parses and checks against a whitelist of arithmetic operators, named constants and elementary functions before the renderer compiles them; anything else (names, attributes, calls outside the whitelist) is rejected at validation. `scianim registry [kind]` prints the registered kinds and, for one kind, its parameter model, so an author or agent never has to read the Python models.

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

Start with **scene-level invalidation** built on Manim sections. The code generator emits one section per storyboard scene. When a revision changes, the dependency graph (scene to objects to data sources, equations, style tokens and custom builders) marks affected scenes; the worker re-renders with `skip_animations=True` on unchanged sections and concatenates their cached section videos with the fresh ones. The section index gives the per-scene durations needed to verify hard milestones after the splice. If dependency resolution is uncertain, rerender more rather than serve falsely current previews.

Beneath this, Manim's own per-`play()` cache (keyed on scene, camera, animations, mobjects, backend and encoder state) stays enabled through a stable `media_dir` per revision. Object-level caching and reusable shots are future optimizations; neither should block a functional first version.

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
scianim workspace init /path/to/workspace [--with-example]
scianim workspace list /path/to/workspace     # Families, groups, projects; duplicate ids
scianim family init computational_neuroscience --style tomas_scientific@0.1.0 [--from-example ...]
scianim family env sync computational_neuroscience
scianim project init divisive_normalization --family computational_neuroscience [--from-example ...]
scianim style list path/to/project           # Visible themes by name and version
scianim registry [kind]                   # Registered component kinds and their parameter models
scianim validate path/to/animation.yaml
scianim validate path/to/project          # Cross-file checks: storyboard, style roles, markers
scianim style resolve path/to/project     # Resolved tokens with provenance and hash
scianim codegen path/to/project           # Scene module from registered components
scianim review-sheet path/to/project      # Static HTML contact sheet of checkpoints
scianim compare path/to/project revA revB # Image diffs and moved/changed objects
scianim feedback add path/to/project --snapshot pool_introduced --object pool_label --text "..."
scianim feedback status path/to/project --revision rev_0002 --snapshot pool_introduced --status approved
scianim feedback list path/to/project
scianim index rebuild [--workspace DIR]     # Recreate the SQLite cache from the files
scianim schemas export schemas/
scianim sources probe path/to/project    # What each source says, with checksums (.scianim/sources/)
scianim context path/to/project [--out DIR]  # Provider-neutral bundle for an external agent
scianim propose validate path/to/project proposals/prop_x.yaml   # Check a proposal; writes nothing
scianim propose apply path/to/project proposals/prop_x.yaml      # Apply it; diff and claims on record
scianim inspect path/to/project [--job ID] [--record]  # Self-check checkpoints against the storyboard
scianim snapshot path/to/project --all   # Named checkpoint stills
scianim snapshot path/to/project --id equation_complete
scianim render path/to/project --profile draft     # 2/3 resolution, sections, SRT, sampled checkpoint frames
scianim render path/to/project --profile final     # exact dimensions and fps; fails when timing misses by > 1 frame
scianim render path/to/project --workers 4         # ranges of the clip drawn in four processes at once, joined losslessly
scianim timing path/to/project [--out proposed.yaml]  # Durations from narration; conflicts with milestones
scianim stale path/to/project [--since rev_0002]   # Scenes a change touches since a revision
scianim revision create path/to/project -m "..."   # Write-once revisions/rev_NNNN
scianim revision list path/to/project
scianim snapshot path/to/project --revision rev_0002
scianim clean path/to/project [--keep N]        # Media cache and superseded working renders
scianim bundle export path/to/project --output bundle.scianim.zip
scianim bundle inspect bundle.scianim.zip
scianim bundle import bundle.scianim.zip --into /path/to/workspace
scianim serve --host 127.0.0.1 --port 8765
```

Commands that require LLM reasoning must be able to call an installed/configured adapter *or* cleanly export a prompt/context package for an external coding agent. Do not require cloud API keys merely to validate or render a fully specified animation. In the implementation the reasoning happens outside the tool: `scianim context` exports the package and the agent answers with proposal files that `scianim propose` validates and applies (ADR-020); a `plan` command that calls an adapter can be layered on top of the same two files.

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

Implemented in Milestone 3 (`scianim serve`, loopback by default, OpenAPI at `/docs`): `GET /api/workspace`, `GET /api/projects`, `GET /api/projects/{id}` (brief, storyboard, validation, revisions, jobs), `GET /api/projects/{id}/revisions`, `GET|POST /api/projects/{id}/jobs`, `GET /api/projects/{id}/jobs/{job}` with its checkpoints and layout reports, `GET .../jobs/{job}/log`, `POST .../jobs/{job}/cancel`, `GET /api/projects/{id}/artifacts/{path}` (confined to `renders/`), `GET|POST /api/projects/{id}/feedback`, `GET /api/projects/{id}/compare?a=&b=` with diff images. Projects are addressed by id; a workspace with duplicate project ids reports the duplicate as a problem and serves the first. Project creation, proposals, approvals as a separate resource and bundles wait for later milestones; approvals are feedback records of kind `status`.

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

- No clipping outside declared safe zones, except intentionally full-bleed elements (machine-checked from the layout report: `outside_safe_zone`).
- Fonts load or explicit fallback reported; mathematical glyphs render correctly.
- Axis labels and legends are legible in final and draft views (machine-checked: `text_too_small`, `overlap`).
- Roles from the stylesheet are consistently applied.
- At least one simple scene has golden-reference snapshot tests. Compare with a stated metric and threshold (SSIM, or a perceptual-hash distance) rather than byte-identical pixels, and record the platform and font stack on which the goldens were generated.

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
- Emit a layout report per checkpoint and a static review sheet per revision.
- `scianim codegen` for storyboards made of registered kinds.

**Gate:** An edited theme token changes the intended objects in new checkpoint PNGs; no complete MP4 is required.

### Phase 1.5: Agent dry run

- Have a coding agent take the example from brief to storyboard to rendered checkpoints through the CLI alone, and record every point where the YAML vocabulary or the CLI was awkward.
- Adjust the schemas before the UI hardens around them.

**Gate:** A storyboard written by an agent for the example validates and renders without schema changes made during the run.

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

1. **Style signature:** the baseline is now `default@0.5.0` (line and wash after Keenan Crane: lit matte surfaces, a quiet mesh, Palatino labels, round line ends, with its philosophy and a specimen rendered from the examples; ADR-025, ADR-027, ADR-028, ADR-030); the personal layer `tomas_scientific@0.5.0` is deliberately thin. Which tokens the personal signature should change, and alternative sample stills for approval, remain to be decided.
2. **Version strategy:** Pydantic schemas and themes need a migration policy before community sharing.
3. **Supported platforms:** prioritize macOS/Linux, optionally Windows; test LaTeX/FFmpeg/Manim prerequisites explicitly.
4. **PDF ingestion:** acceptable local extraction fidelity and when visual/manual inspection is needed.
5. **Agent execution security:** how much local filesystem and network access the chosen coding agent gets, and what it must ask before executing.
6. **Narrative authoring:** whether initial UI storyboard edits directly change YAML or produce validated patch proposals.
7. **Bundle defaults:** export only source manifests unless assets are redistributable and specifically selected.
8. **Audio:** V1 `audio: none`, but `narration` is in the storyboard schema from the start; subtitles come from it through Manim subcaptions, and voiceover alignment through manim-voiceover bookmarks is the later addition.
9. **Frame sampling:** how scene checkpoint states and full-video time samples are reconciled, with no claims of frame equivalence unless verified.
10. **Revision store:** the file-based write-once store of section 11 is implemented; whether to move revisions onto Git plumbing (one commit per revision, tags for approvals) stays open. The trade is free diffs and lineage against coupling the workspace to Git.
11. **Typst coverage:** which notation the default Typst engine cannot express, and the per-family opt-in path to LaTeX.

---

## 18. Definition of success

The product is brief animations: clips of a few seconds to half a minute, one or two scenes, in which one mechanism moves while the equation term, its value and the picture change together; not slide decks or narrated lectures. SciAnim Studio succeeds when the user can supply a paper, dataset, illustration, existing scene, or simple prompt; see a scientifically faithful animation plan for such a clip under a recognizable personalized style; point at a still and request a change; inspect differences across versions; and export a precise final Manim animation **without ever needing to write or read Manim code**.

At the engineering level, success means another coding agent can understand the package contracts, reproduce the render from versioned inputs, extend an animation family with additional scientific packages without contaminating the core installation, and share a project as a self-contained and auditable bundle.

**Build the smallest vertical slice of that experience first.** A named scientific snapshot, rendered inside an isolated family environment from a validated YAML specification, is more valuable than a large unfinished application shell.
