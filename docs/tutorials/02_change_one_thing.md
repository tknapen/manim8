# 2. Change one thing

You will copy the example, change how far one parameter moves, meet a rule of the style, re-render only what
the change reaches, and compare two revisions. This continues from [tutorial 1](01_first_picture.md), in the
same workspace and from the same checkout.

## Copy the example

```bash
uv run scianim project init my_normalization --family computational_neuroscience --workspace ~/animations --from-example divisive_normalization
uv run scianim validate ~/animations/families/computational_neuroscience/my_normalization
```

```text output
valid (0 errors, 0 warnings)
```

`validate` checks both files, `animation.yaml` (what the clip must show: equations, sources, constraints,
output) and `storyboard.yaml` (how: scenes, registered objects, actions, checkpoints), and the rules that link
them, before anything renders.

## Freeze it and render a quick video

```bash
uv run scianim codegen ~/animations/families/computational_neuroscience/my_normalization
uv run scianim revision create ~/animations/families/computational_neuroscience/my_normalization -m "As copied from the example"
uv run scianim render ~/animations/families/computational_neuroscience/my_normalization --profile storyboard
```

```text output
rev_0001 created
drew 18 of 18 plays
status: succeeded
```

A revision freezes the specification, the generated code and the resolved style; comments and approvals refer
to a revision, and it is never changed afterwards. The `storyboard` profile renders a small, fast video for
judging motion; `draft` and `final` render the same clip at full size. The command prints where the video,
its manifest and a review sheet are.

## Change the pool

In `~/animations/families/computational_neuroscience/my_normalization/storyboard.yaml`, the scene
`normalization` has an action `raise_pool` that raises the normalization pool `P` to 4 over four seconds:

```yaml before file=~/animations/families/computational_neuroscience/my_normalization/storyboard.yaml
        parameter: P
        to: 4
        at_seconds: 8.5
        duration_seconds: 4
```

Raise it to 6 instead, and let the rise take half a second longer:

```yaml after file=~/animations/families/computational_neuroscience/my_normalization/storyboard.yaml
        parameter: P
        to: 6
        at_seconds: 8.5
        duration_seconds: 4.5
```

```bash
uv run scianim validate ~/animations/families/computational_neuroscience/my_normalization
```

```text output
valid (0 errors, 2 warnings)
the style asks for a rest of 1s
```

The rise now ends at 13 s, and the next segment (`stabilize` and `lower_pool`) starts at 13.5 s. The style,
`tomas_scientific@0.5.1`, asks for a full second of rest between two motions of one object, so the viewer sees
the compressed curve before it changes again. A warning does not stop a render, but it is usually right. Keep
the larger pool and the four seconds:

```yaml before file=~/animations/families/computational_neuroscience/my_normalization/storyboard.yaml
        to: 6
        at_seconds: 8.5
        duration_seconds: 4.5
```

```yaml after file=~/animations/families/computational_neuroscience/my_normalization/storyboard.yaml
        to: 6
        at_seconds: 8.5
        duration_seconds: 4
```

```bash
uv run scianim validate ~/animations/families/computational_neuroscience/my_normalization
```

```text output
valid (0 errors, 0 warnings)
```

## Render again

```bash
uv run scianim codegen ~/animations/families/computational_neuroscience/my_normalization
uv run scianim render ~/animations/families/computational_neuroscience/my_normalization --profile storyboard
```

```text output
drew 4 of 18 plays
14 came unchanged from the segment store
```

Every play of a clip is stored under a hash of the scene's state when the play begins. The plays before the
change start from the same state as before, and so do those after the rebalancing, which brings the curve back
to where it was; they come from the store instead of being drawn again. Only the plays of the larger rise and
of the way back are new.

## Compare the two revisions

```bash
uv run scianim revision create ~/animations/families/computational_neuroscience/my_normalization -m "A larger pool: P rises to 6"
uv run scianim snapshot ~/animations/families/computational_neuroscience/my_normalization --all --revision rev_0001
uv run scianim snapshot ~/animations/families/computational_neuroscience/my_normalization --all --revision rev_0002
uv run scianim compare ~/animations/families/computational_neuroscience/my_normalization rev_0001 rev_0002
```

```text output
rev_0002 created
raise_pool text_changed
```

The two snapshots render each revision's checkpoints; the comparison lists, per checkpoint, whether the image
is identical, the share of pixels that changed and which objects changed in the layout report. Here only `pool_raised`
differs: the curve is more compressed and the readout `raise_pool` says `P = 6.0`. The other three checkpoints
are identical, and diff images are written under `.scianim/compare/`.

That is the loop at the level of files: a change, a validation that explains itself, a re-render that redraws
only what changed, and a comparison bound to revisions. With the manim8 skill, an agent runs these commands for
you, and you review the pictures and answer its questions.
