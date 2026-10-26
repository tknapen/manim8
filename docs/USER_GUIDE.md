# SciAnim Studio: user guide

A scientist describes an animation; the system keeps the description as validated YAML, enforces a personal
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
