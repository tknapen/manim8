# Divisive normalization sample animation

This is an **illustrative specification fixture** and the first integration example. It contains:

- `animation.yaml`: scientific constraints, typed `equations`, and output constraints.
- `storyboard.yaml`: scenes with narration, registered component objects, explicit data bindings and named checkpoints.
- `data/synthetic_responses.csv`: generated toy data for a schematic normalization equation.
- `references/README.md`: note about adding real and redistributable papers.
- `code/`: the scene module produced by `scianim codegen` (generated, reviewable, regenerated rather than hand-edited).

The CSV is synthetic and must never be presented as a result from a published experiment. Each row satisfies `response_r = excitation_E / (sigma + pool_P)` with `sigma = 1`.

The chosen equation `r = E / (sigma + P)` is pedagogical; it is **not** offered as a full or generally correct biophysical normalization model. For a paper-specific animation, its exact mathematical form and scientific assumptions should be established from the supplied source.
