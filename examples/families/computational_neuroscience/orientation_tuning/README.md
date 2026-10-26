# Orientation tuning: an example produced by the agent loop

This project is the output of Milestone 5's acceptance loop (`tests/integration/test_agent_loop.py`): a
plain-language brief (`references/brief.md`) and a synthetic table (`data/tuning.csv`) went through three
proposal files (`proposals/applied/`): a spec, a storyboard and a targeted revision answering a review comment.
The applied records keep each proposal's claims, open questions and unified diff.

All curves are synthetic von Mises functions computed for the example; nothing here is recorded data. The
storyboard uses the kinds added in Milestone 5: `caption_with_citation`, `network_graph`,
`schematic_population` and `receptive_field_glyph`, beside `scientific_plot`, `equation_label` and
`function_plot`.

Copy it into a workspace with `scianim workspace init <dir> --with-example`, then `scianim codegen` and
`scianim snapshot --all` render its five checkpoints; `scianim render --profile draft` makes the 40 s video.
