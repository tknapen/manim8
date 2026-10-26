# Gaussian population receptive field (second example)

A 16 s clip: the pRF as a two-dimensional Gaussian hill over the visual field, drawn as a mesh
(`surface_plot`) under a camera that turns a quarter circle (`orbit_camera`), with the equation beside it. The
centre moves in both directions at once (two concurrent `vary_parameter` actions on x₀ and y₀), then the size
grows; each parameter's term pulses in the equation and a readout counts, the readouts stacking under the
equation in the order the actions began. The surface is computed from the equation and labelled so; nothing
here is measured. No paper is included under `references/`.

It was first written during the Milestone 2.5 agent dry run (`docs/FRICTION_LOG_M2_5.md`) as a one-dimensional
curve with a side-by-side comparison, and rebuilt twice since: as a brief clip around sweeps (ADR-023), and as
a surface under an orbit (ADR-024).

Copy it into a workspace with `scianim workspace init <dir> --with-example`, then `scianim codegen` and
`scianim snapshot --all` render its four checkpoints, one of them inside the concurrent segment;
`scianim render --profile draft` makes the clip (a 40-cell mesh takes a couple of minutes).
