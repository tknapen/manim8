# SciAnim Studio: user guide

A scientist describes a brief animation, a clip of a few seconds to half a minute in which one mechanism moves;
the system keeps the description as validated YAML, enforces a personal
style, renders named checkpoints and videos with Manim inside an isolated family environment, and offers a local
browser for review. You never edit Manim code. Every command below is `uv run scianim ...` from a checkout, or
`scianim ...` once installed.

## Setting up

```bash
uv sync --group dev
scianim doctor                                            # uv, Python, fonts
scianim workspace init ~/animations --with-example        # styles, the example family and its three projects
scianim family env sync ~/animations/families/computational_neuroscience   # Manim + bridge, once per family
```

A workspace holds `styles/` (versioned themes), `families/` (one render environment each, with projects
nested inside) and `assets/`. Examples in the repository are read-only templates; everything that changes lives
in your workspace. The nearest `family.yaml` above a project decides its environment and default style.

## Ways to start

**Prompt only.** Write the brief in plain language and hand the context to a coding agent.

```bash
scianim project init my_topic --family computational_neuroscience --workspace ~/animations
# write references/brief.md; drop data into data/
scianim context ~/animations/families/computational_neuroscience/my_topic
```

`.scianim/context/CONTEXT.md` tells the agent what the brief, sources, style and registry are and how to
answer: with proposal files. The agent writes `proposals/prop_spec.yaml` (`create_spec`) and
`proposals/prop_storyboard.yaml` (`create_storyboard`); you apply them:

```bash
scianim propose validate <project> proposals/prop_spec.yaml
scianim propose apply    <project> proposals/prop_spec.yaml
scianim propose apply    <project> proposals/prop_storyboard.yaml
```

A proposal that changes equations, sources, constraints or data bindings is recorded as needing your
sign-off; the tool never approves scientific content.

**YAML first.** Write `animation.yaml` (intent: brief, sources, equations, output, constraints) and
`storyboard.yaml` (scenes, registered objects, snapshots) yourself. `scianim registry` lists the component
kinds and `scianim registry function_plot` the parameters of one. `scianim validate <project>` checks
everything, including cross-file rules, before anything renders.

**With a scientific CSV.** Declare it as a source with its role and a citation that says what it is:

```yaml
sources:
  - id: tuning
    type: csv
    path: data/tuning.csv
    role: illustrative_data
    citation: "Synthetic curves computed for this example; not measurements"
```

`scianim sources probe <project>` records what the file says (columns, types, ranges, row count) under
`.scianim/sources/`; a plot binds to it with an explicit `encoding` and `transforms`, and a `data_label`
tells the viewer what they are looking at. Toy data must be labelled toy data.

**With a paper.** Add the PDF as a `scientific_reference` source. Probing extracts text per page so claims
can cite a page; figures and equations are not extracted. PDFs are never redistributed in bundles unless you
say so.

**With a reference image.** Add it with the role that applies: `composition_reference`, `style_reference`,
`target_keyframe` or `scientific_reference`. The storyboard and the proposal record which role was used;
third-party images stay out of bundles by default.

## Checkpoints, review and video

```bash
scianim codegen  <project>                  # scene module from the storyboard, one section per scene
scianim snapshot <project> --all            # named checkpoints from the real animation flow
scianim inspect  <project>                  # what is missing, overlapping, too small or blank
scianim serve --workspace ~/animations      # http://127.0.0.1:8765/
```

In the browser: the overview (brief, storyboard, revisions, proposals, jobs), review (filmstrip, click an
object or drag a region, comment, mark a checkpoint approved, needs revision or scientific concern), compare
(two renders, pixel and layout differences), video and jobs. Feedback is written to `feedback/*.yaml`; the CLI
writes the same records with `scianim feedback add`.

```bash
scianim timing <project>                    # scene durations proposed from narration; conflicts reported
scianim render <project> --profile draft    # 2/3 resolution, sections, subtitles, sampled frames
scianim render <project> --profile final    # exact dimensions and fps; fails if a frame is off
```

## Making something move

A figure can show two conditions side by side; an animation can vary one quantity while the viewer watches the
equation term, its value and the curve change together. Give a `function_plot` named `parameters` (named after
the equation's symbols), write its series and markers in terms of them, fix its `y_range`, and add a scene
action:

```yaml
objects:
  - id: profile_plot
    kind: function_plot
    equation: {id: gaussian_prf}
    params:
      x_range: [-10, 10]
      y_range: [0, 1.2]
      parameters: {x_0: 2, sigma: 1.5}
      series: [{label: "Gaussian pRF", expression: "exp(-((x - x_0)^2) / (2 * sigma^2))"}]
      markers: [{x: "x_0 + sigma", label: "x₀ + σ", style_role: emphasis}]
  - id: size_label
    kind: equation_label
    equation: {id: gaussian_prf, highlight: [sigma]}
    params: {text: "size sigma", anchor: top_right}
actions:
  - id: widen
    kind: vary_parameter
    target: profile_plot
    parameter: sigma
    to: 4
    at_seconds: 6.5
    duration_seconds: 4
    emphasize: [size_label]
```

The σ in the equation pulses as the sweep begins, a readout under the label counts from 1.5 to 4.0 deg, the
curve widens and the marker moves with it. A checkpoint placed inside the window captures that exact frame.
Give the action a `lead_in_seconds` and the term lights up first, with the readout at its starting value; the
curve moves only when the lead-in is over. Actions that drive different things may overlap; `scianim
validate` says when one would end during the scene's fade-out. The style's `motion` tokens set the rate
profiles (`easing` for sweeps, fades and colour; `camera_easing` for orbits, where `eased_linear` ramps up over
`ramp_seconds`, holds its speed and ramps down), the size and length of the pulse, and the rest an object keeps
between two motions (`hold_seconds`); `scianim validate` warns when a storyboard asks for linear motion, a
lead-in shorter than the pulse or a shorter rest. The rules behind the tokens are written out in the theme's
`PHILOSOPHY.md`.

## Surfaces, the camera, and things moving together

A `surface_plot` draws z = f(x, y) over a fixed box as a fine mesh; an `orbit_camera` action turns the camera
around it; a `function_image` samples a field to pixels (a grating under a disc, say). Actions run at the
same time when they drive different things, so the camera can keep turning while the filter changes. A clip
that changes several parameters in turn is written as segments: the equation reference takes
`highlight_mode: active`, so its terms wait in the equation's ink and only the term at work carries the
accent; each `vary_parameter` has a `lead_in_seconds` during which that term lights up before the value
moves; and a `fade_axes` action takes the surface's frame and labels away once the viewer has read the box:

```yaml
objects:
  - id: gabor_label
    kind: equation_label
    equation: {id: gabor, highlight: [theta, f, x_0, y_0, sigma], highlight_mode: active}
    params: {text: "Gabor filter", anchor: top_left}
actions:
  - {id: orbit, kind: orbit_camera, to_theta_degrees: 255, at_seconds: 0, duration_seconds: 26}
  - {id: axes_away, kind: fade_axes, target: gabor_surface, at_seconds: 3, duration_seconds: 0.8}
  - {id: rotate, kind: vary_parameter, target: gabor_surface, parameter: theta, to: 90, at_seconds: 4, lead_in_seconds: 1, duration_seconds: 3.5, emphasize: [gabor_label]}
  - {id: frequency, kind: vary_parameter, target: gabor_surface, parameter: f, to: 1.4, at_seconds: 9.5, lead_in_seconds: 1, duration_seconds: 3.5, emphasize: [gabor_label]}
  - {id: shift_x, kind: vary_parameter, target: gabor_surface, parameter: x_0, to: 1.2, at_seconds: 15, lead_in_seconds: 1, duration_seconds: 3.5, emphasize: [gabor_label]}
  - {id: shift_y, kind: vary_parameter, target: gabor_surface, parameter: y_0, to: -1, at_seconds: 15, lead_in_seconds: 1, duration_seconds: 3.5, emphasize: [gabor_label]}
```

When `frequency` begins, θ gives the colour up and f takes it, and θ's readout recedes to the secondary ink;
`shift_x` and `shift_y` run together, so x₀ and y₀ are in colour at once. Text, equations and readouts stay
fixed on the page while the surface turns; a surface's axis labels follow their anchors but keep facing you
until they fade. Only two actions that drive the same parameter of the same object, two orbits, or two axes
fades of the same object may not overlap. The `three_d` style tokens set the camera's starting angles, the
mesh weight and the surface opacity (nearly solid since `default@0.3.1`). A surface's `size_fraction` sets its
footprint and `lift_fraction` raises it above the page's centre, so a large surface can sit behind the text
(text is always drawn on top) while the floor frame, which hangs below the surface, keeps its labels on the
page. Surfaces render through Cairo as thousands of small cells: snapshots are quick, a draft video takes
tens of minutes, and the 80-cell Gabor mesh at 60 fps takes about two hours.

## Revisions, forks and comparison

```bash
scianim revision create <project> -m "first cut"      # revisions/rev_0001, write-once
scianim snapshot <project> --revision rev_0001
scianim compare  <project> rev_0001 working            # diff images under .scianim/compare/
scianim stale    <project> --since rev_0001            # which scenes a change touched
```

Approval binds to the image hash of an immutable revision, never to the working copy. To fork, copy the
project directory under its family (or another family) with a new id in `animation.yaml`; `scianim project
init --from-example` does the same from a template.

## Export and import

```bash
scianim bundle export <project> -o my_topic.scianim.zip        # or a family directory for every project
scianim bundle inspect my_topic.scianim.zip                    # contents and checksums, no code executed
scianim bundle import my_topic.scianim.zip --into ~/elsewhere  # then: scianim family env sync ...
```

Bundles carry the specs, data, code, revisions, feedback, applied proposals, the style chain, the family
manifest, shared components and the lockfile, and never `.venv`, caches, secrets, symlinks or absolute paths.
PDFs and third-party images are omitted by default and listed with relink instructions in `bundle.yaml` and
the README; `--include-source-assets` includes them when rights permit, `--include-renders` adds renders.
Rebuilding the environment after import is an explicit step.

## Where things are

```text
<project>/animation.yaml            intent (write-once per revision)
<project>/storyboard.yaml           scenes, objects, snapshots
<project>/code/                     generated scene module and custom builders
<project>/data/ references/         sources
<project>/feedback/                 review records
<project>/proposals/applied/        agent proposals with diffs and claims
<project>/revisions/rev_NNNN/       frozen specs, code and resolved style
<project>/renders/<revision>/<job>/ PNGs, videos, manifest.json, review_sheet.html
<project>/.scianim/                 caches, logs, extracts, context (safe to delete)
```
