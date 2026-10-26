# A Gabor filter in three dimensions

A 24 s clip around one object: the filter g(x, y) as a fine mesh (`surface_plot`), positive cells in the blue ink
and negative cells in the red, under a camera that turns a full circle (`orbit_camera`). While it turns, three
parameters change one after the other (`vary_parameter`): the carrier's orientation theta, its spatial
frequency f and the envelope's size sigma. The equation sits beside the surface, the changing term pulses, and a
readout counts. Everything flat stays fixed in the frame; only the surface turns.

Copy it into a workspace with `scianim workspace init <dir> --with-example`, then `scianim codegen` and
`scianim snapshot --all` render its five checkpoints; `scianim render --profile draft` makes the clip.
