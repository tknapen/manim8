# A drop falls onto still water

A 20 s clip of one event. The water is a `surface_plot` whose expression is an analytic model of a drop impact:
an outward-travelling, damped ring wave packet (the crater and the capillary ripples) plus a central column
whose height follows a pulse after impact (the rebound, the Worthington jet of the physics literature). Time
is the one parameter that varies (`vary_parameter t`); the equation beside the surface is the model itself,
and the caption, the data label and `animation.yaml` say plainly that it is a cartoon of the mechanism, not a
fluid simulation and not a measurement.

The clip exercises the actions of ADR-034: a `sphere` anchored to the surface's coordinates falls onto it
(`move_object` with `to_point` and the parabolic `ease_in_quad`), vanishes at impact (`fade_object`), the
free-fall equation at the top left becomes the surface model at that moment (`transform_equation`, the shared
`t` gliding into place and the rest of the glyphs pairing by shape), a smaller sphere leaves the tip of the
column, climbs and falls back (two more moves) and merges into it (a second fade), while the axes leave and
the camera orbits slowly.

The mesh is authored at 48 cells per axis so the clip renders in reasonable time under Cairo. Copy it into a
workspace with `scianim workspace init <dir> --with-example`, then `scianim codegen` and
`scianim snapshot --all` render its six checkpoints; `scianim render --profile storyboard` makes a quarter-size
clip for review.
