# 1. Ten minutes to a picture

You will render the four checkpoints of an example clip, look at them and leave a comment, without writing any
YAML. The example shows divisive normalization: a response that grows with its drive until a normalization pool
compresses it. The commands run from a checkout of manim8; `~/animations` is the workspace this tutorial
creates, and it can live anywhere.

## Before you start

You need git, [uv](https://docs.astral.sh/uv/) and the two system libraries Manim draws with, Cairo and Pango:

```bash setup
brew install cairo pango pkg-config                                  # macOS
sudo apt-get install -y libcairo2-dev libpango1.0-dev pkg-config     # Debian or Ubuntu
```

manim8 is not on PyPI yet, so you work from a checkout and every command goes through `uv run`:

```bash setup
git clone https://github.com/tknapen/manim8
cd manim8
uv sync
```

In a cloud session the environment's setup script installs the libraries with the `apt-get` line above and
runs `uv sync`; everything below is the same.

## Check the machine

```bash
uv run scianim doctor
```

Every row should read `ok`. The last one says that Manim cannot be imported here, which is correct: the
control plane never imports it, and renders run in a separate process.

## Create a workspace

```bash
uv run scianim workspace init ~/animations --with-example
```

A workspace holds `styles/` (versioned themes), `families/` (one render environment each, with its projects
inside) and `assets/`. `--with-example` copies the example family and its five projects; the examples in the
checkout are templates and stay untouched.

## Build the render environment

```bash
uv run scianim family env sync ~/animations/families/computational_neuroscience
uv run scianim doctor --project ~/animations/families/computational_neuroscience/divisive_normalization
```

The sync installs Manim and the bridge into the family's own environment (`.venv` in the family folder). The
first sync downloads Manim and its dependencies and takes a few minutes; later ones take seconds. The second
`doctor` checks that environment: PyAV, the equation engine (Typst), fonts and the declared system libraries.

## Render the checkpoints

```bash
uv run scianim codegen ~/animations/families/computational_neuroscience/divisive_normalization
uv run scianim snapshot ~/animations/families/computational_neuroscience/divisive_normalization --all
```

```text output
status: succeeded
4 checkpoint(s)
```

`codegen` writes the Manim scene from the storyboard into `code/scene_divisive_normalization.py`; you never
edit it, you regenerate it. `snapshot` runs the real animation in Manim's fast-forward mode and captures the
named checkpoints on the way: `excitation_visible` at 4 s, `pool_introduced` at 8 s, `pool_raised` at 13 s and
`rebalanced` at 17.2 s. Each is a PNG under `renders/working/<job>/`, and `manifest.json` beside them records,
for every object on screen, its bounding box and any layout warning (text too small, objects overlapping,
something outside the safe area). The table the command prints lists the checkpoints; a dash under
"layout warnings" means none.

## Look

The snapshot also wrote `review_sheet.html` beside the images: open it in a browser. For comments on regions
of an image and for comparing renders, start the review server and open `http://127.0.0.1:8765/`:

```bash notest
uv run scianim serve --workspace ~/animations
```

In a cloud session the server runs inside the session's container; ask Claude to show you the checkpoint
images instead.

## Leave a comment

In the review page, click a checkpoint and write. From the terminal:

```bash
uv run scianim feedback add ~/animations/families/computational_neuroscience/divisive_normalization --snapshot pool_raised --text "Should the compressed curve sit lower?" --author me
```

```text output
feedback/fb_
```

The comment is a file under `feedback/`, bound to the checkpoint and to the image it was written about. An
agent, or you, answers it by proposing a change to the storyboard; a comment never lives only in a chat.

Next: [change one thing](02_change_one_thing.md).
