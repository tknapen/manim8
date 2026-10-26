# Milestone 2.5 friction log: an agent takes a brief to rendered checkpoints

**Date:** 26 October 2026. **Agent:** the coding agent building this repository, using the CLI only.
**Result:** the second example, `examples/families/computational_neuroscience/prf_tuning`, which validates and
renders five named checkpoints without layout warnings. The run surfaced ten friction points in the
Milestone 2 vocabulary; eight were resolved by extending the registry and the renderer (ADR-016), two are
deferred.

## The brief

A short animation for a computational neuroscience audience: what a population receptive field (pRF) is, the
Gaussian model with a centre and a size, the equation with its symbols, and a side-by-side comparison of a small
and a large pRF on identical axes. Four scenes, 45 seconds, no empirical data: the profiles are analytic, and the
comparison uses a labelled synthetic table.

## Commands used

```bash
uv run scianim workspace init workspace --with-example
uv run scianim family env sync workspace/families/computational_neuroscience
uv run scianim registry                      # what kinds exist (added during the run, see item 7)
uv run scianim registry function_plot        # parameters of one kind
uv run scianim validate workspace/families/computational_neuroscience/prf_tuning
uv run scianim codegen  workspace/families/computational_neuroscience/prf_tuning
uv run scianim snapshot workspace/families/computational_neuroscience/prf_tuning --all --no-cache
```

The first pass used the Milestone 2 registry as it stood. The second pass used the registry after the changes
below; the storyboard in the example is the second-pass storyboard.

## Friction points and what changed

1. **Two captions anchored `top_left` overlapped.** A title and a subtitle both defaulted to the same anchor.
   The layout report flagged the overlap, which is the intended safety net, but the vocabulary had no way to
   say "under the title". Resolved: every text-like kind accepts `below` or `right_of` naming an earlier object
   of the same scene, plus `gap_px_at_1080p` (default: the style's baseline grid). The validator rejects a
   reference to an object declared later or in another scene. During the second pass `text_caption` still
   bypassed the shared placement helper; the overlap warning in the first manifest of that pass caught it.
2. **Axes through the origin.** With an x range spanning zero, the y axis was drawn through the middle of the
   plot and its label sat inside the data. Resolved: axes are drawn along the left and bottom edges of the plot
   box, tick and axis labels outside, for every plot kind.
3. **Symbol names rendered literally.** `x_0` appeared as "x_0" in symbol definitions and marker labels.
   Resolved: Greek names become Greek letters and a trailing `_<digits>` becomes subscript digits
   (`pretty_symbol`); the YAML keeps the plain ASCII symbol id.
4. **`comparison_plot` always drew points.** Wrong for smooth analytic profiles. Resolved: `show_points`.
5. **No per-object timing.** Every object of a scene appeared at the scene start, so a checkpoint could not
   show "the profile before the label". Resolved: `reveal_at_seconds` on any storyboard object; `codegen`
   constructs all objects first and emits reveals and checkpoints in time order.
6. **An analytic curve needed a CSV.** The Gaussian profile had to be tabulated by hand into `data/`.
   Resolved: `function_plot` samples whitelisted arithmetic expressions in `x` (`exp(-((x - 2)^2) / (2 * 1.5^2))`),
   with `x_range`, `samples` and optional `y_range`. The expression grammar is closed (operators, numeric
   literals, `pi`/`e`/`tau`, elementary functions); names, attributes and other calls are rejected at
   validation, which keeps YAML free of executable code.
7. **No way to see the vocabulary.** Writing a storyboard meant reading the Pydantic models. Resolved:
   `scianim registry` lists kinds with their roles and requirements; `scianim registry <kind>` prints the
   parameter model with defaults and docstrings.
8. **No annotation markers.** The centre and the width of the profile had nowhere to go. Resolved: `markers`
   on `function_plot`, each a dashed vertical line at `x` with an optional label and `style_role`.
9. **Stale generated code after editing the storyboard** failed validation with "snapshots without a
   `checkpoint()` marker". The error was correct but did not say what to do. Resolved: the message now ends
   with the instruction to run `scianim codegen`.
10. **Inconsistent headroom between plot kinds.** The single profile touched the top of its axis box (y range
    0 to 1) while the comparison panels had a step of headroom (0 to 1.2), because headroom was only added when
    the data maximum was exactly on a tick. Resolved: headroom is added whenever the maximum lies within a
    quarter step of the top; all kinds now agree.

Registry version is `0.2.0`; earlier cache keys are invalidated.

## Deferred

- **Panel titles differ in vertical position by glyph descent.** In `comparison_plot`, "large" (with a
  descender) sits about 3 px higher than "small" at 540p because Manim's `Text` exposes a bounding box and no
  baseline. A baseline-aligned text helper would need glyph metrics from Pango; left for the layout work of
  Milestone 3, where the review UI will make such offsets visible.
- **The family's `components` allowlist must be edited to admit a new kind.** `function_plot` produced a
  warning until it was added to `family.yaml`. This is by design (a family declares its vocabulary), but an
  agent extending the registry has to remember two places. A `scianim family components add` command would
  remove the hand edit; not needed yet.

## Acceptance evidence

Second-pass render of `workspace/families/computational_neuroscience/prf_tuning` (job `job_20261026T132516_3f5dff`,
960 by 540, 3.3 s inside the family environment):

| snapshot | scene | t (s) | animation # | fidelity | layout warnings |
| --- | --- | --- | --- | --- | --- |
| `intro_visible` | introduction | 6 | 4 | exact | none |
| `gaussian_visible` | gaussian | 16 | 8 | exact | none |
| `size_labelled` | gaussian | 21 | 11 | exact | none |
| `equation_complete` | equation | 30 | 15 | exact | none |
| `comparison_complete` | comparison | 42 | 19 | exact | none |

Inspection against the storyboard descriptions: the subtitle sits under the title with the left edges aligned;
the profile shows edge axes, the centre marker `x₀` and the width marker `x₀ + σ` in the emphasis ink, with the
label absent at 16 s and present at 21 s together with the highlighted σ; the equation lists four symbols with
`x₀` and `σ` typeset; the comparison shows two panels on identical axes without points. The only worker warning
is the font substitution Helvetica → TeX Gyre Heros, as ADR-015 intends. The integration test
`test_prf_tuning_renders_timed_reveals_and_relational_placement` reproduces this run in CI.

## Follow-up

After the dry run, the text sizes that the renders exposed as hidden multipliers (tick labels, captions and
marker labels at 22 px at 1080p) became named roles with a validated minimum, and the despined-axes convention
became a chart token (ADR-017). The acceptance table above records the run as it happened, before that change.
