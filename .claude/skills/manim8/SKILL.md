---
name: manim8
description: >-
  Make short scientific animations with manim8 (SciAnim Studio): clips of 5 to 30 seconds that show one
  mechanism moving, rendered by Manim from validated YAML in the person's style. Use when someone wants to
  animate or visualize a scientific idea, equation, model or dataset, turn a paper or a figure into a clip, or
  review and revise the checkpoints and drafts of such a clip, or when the working directory holds a manim8
  workspace (workspace.yaml, family.yaml, animation.yaml, storyboard.yaml).
---

# manim8: a scientific clip from a brief

You turn a scientist's idea into a brief clip in which one mechanism moves: a parameter sweeps, a curve
follows, the term of the equation that drives it lights up. You write and validate the YAML, render, look at
what you rendered, and bring the person pictures and questions. They decide what the clip claims and when a
stage is approved. The files are the state, never the conversation: `animation.yaml` (what the clip must
show), `storyboard.yaml` (how), `feedback/` (comments), `proposals/` (changes, with their reasons) and
revisions (frozen versions that comments and approvals refer to).

## Running the command

Use `scianim` if it is on PATH (an installed manim8 also answers to `manim8`). Otherwise run it from a
checkout: inside one (its `pyproject.toml` names `manim8`), `uv run scianim ...`; elsewhere, if
`checkout.txt` sits next to this file (`${CLAUDE_SKILL_DIR}/checkout.txt`), it names the checkout, and the
command is `uv run --project <that path> scianim ...`. Below, `scianim` stands for whichever applies. Check
an option with `scianim <command> --help` before guessing it.

## First time on a machine

1. Find the workspace: walk up from the working directory to a `workspace.yaml`, or ask where the person's
   animations live. `scianim workspace list <dir>` shows its families and projects.
2. If there is none, ask where to create it, then `scianim workspace init <dir> --with-example`.
3. `scianim doctor`, then once per family `scianim family env sync <workspace>/families/<family>` (minutes the
   first time, seconds after) and `scianim doctor --project <project>`.
4. If Cairo or Pango is missing, give the person the command for their system: `brew install cairo pango
   pkg-config` on macOS, `sudo apt-get install -y libcairo2-dev libpango1.0-dev pkg-config` on Debian or
   Ubuntu. In a cloud session you run as root and may run the apt line yourself.

The checkout's `examples/` are read-only templates: copy one with `scianim project init <name> --family
<family> --workspace <ws> --from-example <example>`, never render into it.

## The loop

Each stage ends in something the person can look at. Stop after each one and wait for their answer.

1. **Brief.** Ask what the viewer should understand (one mechanism), for whom, how long (5 to 30 s), which
   equations and which sources (a paper, data). Create the project with `scianim project init`, put the
   person's files in `data/` and `references/` and the brief in `references/brief.md`, and run
   `scianim sources probe <project>`.
2. **Context.** `scianim context <project>`, then read `<project>/.scianim/context/CONTEXT.md`: the brief,
   what the sources say, the equations, the component registry, the style's roles, the pattern library and
   the rules of the project. It is your vocabulary: use only the component kinds, parameters and actions it
   lists. `scianim patterns show <id>` prints one pattern with a recipe scene that renders;
   `scianim registry <kind>` prints one component's parameters.
3. **Specification and storyboard.** Write proposals in `<project>/proposals/` from
   `.scianim/context/proposal.template.yaml`: `create_spec`, then `create_storyboard`, later `revise_*` with
   small patches. Give the rationale, every scientific claim with its source and locator, and the
   uncertainties the sources do not settle. Choose one pattern per scene, two at most, and name it in the
   scene's `patterns`. Check with `scianim propose validate <project> <file>`, write with
   `scianim propose apply <project> <file>`.
   If the brief says the clip is presented in parts (a lecturer holds it so the room can predict), ask where the
   holds go and what each should show. Mark those snapshots `stop: true`, with a short `label`, only on the
   person's word: a stop is their decision, like any reveal. A stop needs a still picture in the 0.3 s before
   it and no camera orbit turning across it; an action that should follow the stop starts a frame after it
   (`stop_on_motion_start` warns otherwise, and lecturekit refuses that stop). `scianim validate` says what is
   in the way, and `scianim timing <project>` lists the parts between stops (ADR-045).
4. **Keyframes.** `scianim validate <project>` until it reports no errors; read its warnings, which are usually
   right (a rest that is too short, a checkpoint inside a fade). Then `scianim codegen <project>` and
   `scianim snapshot <project> --all`. Look before you show: read every checkpoint image, its entry in the job's
   `manifest.json` (objects and layout warnings) and the findings of `scianim inspect <project>`, and fix what
   you can.
5. **Review.** `scianim revision create <project> -m "<what changed>"` so that comments refer to a fixed
   version, then snapshot that revision (`scianim snapshot <project> --all --revision rev_NNNN`). Show the
   person the images, or the `review_sheet.html` beside them; on their own machine they can open
   `scianim serve --workspace <ws>`. Record each comment they make in the conversation:
   `scianim feedback add <project> --revision rev_NNNN --snapshot <id> --text "<their words>" --author "<their
   name>"`. Answer it with a proposal that names it in `in_response_to`; `scianim propose from-feedback
   <project>` answers the comments a rule can.
6. **Draft.** `scianim render <project> --profile storyboard` for motion (small and fast), `--profile draft`
   at full size; give the video's path and collect comments as in 5. A re-render redraws only the plays a change
   reaches; the command says how many.
7. **Approval and final.** Only on the person's word. Record what they said:
   `scianim feedback status <project> --snapshot <id> --status approved --revision rev_NNNN --author "<their
   name>" --text "<their words>"`. Render the final only when they ask for it:
   `scianim render <project> --profile final --revision rev_NNNN`.

## Ask, do not decide

- Ask before approving anything, before a final render, before any change to equations, data, sources or
  claims that the person has not seen (a proposal marks it `touches_science`), before adding, moving or removing
  a stop, and before deleting or overwriting a file you did not write.
- Put what you cannot settle under the proposal's `uncertainties` and ask. Never invent numbers, citations or
  mechanisms. Illustrative data are labelled as such, in the source's `citation` and the object's
  `data_label`.
- A pattern the library marks planned cannot be staged with registered components; say what it would need
  instead of approximating it silently.

## Rules that keep a clip honest

- YAML is the specification. Never edit the generated scene in `code/`; regenerate it with `scianim codegen`.
  A bespoke object is `kind: custom` with a named builder in `code/`, and the person reviews that code.
- Equations are typed strings in `animation.yaml`; the storyboard emphasizes their symbols by name.
- Colours, fonts and sizes come from the style. Change them only through a new style version the person
  accepts (`scianim style stills`, then `scianim style publish`).
- Never say that a render happened if it did not: quote the status line and the paths the command printed.
- Revisions are never changed; make a new one.

## When something fails

- Every render prints the path of its worker log; read it first.
- Environment trouble: `scianim doctor --project <project>`, and `scianim family env sync` after updating
  manim8. In a workspace that was moved or cloned, the sync rewrites the family's bridge sources and says so;
  tell the person, and commit the family's `pyproject.toml` and `uv.lock` only when they ask.
- Another tool (a deck builder) reads a render with `scianim render <project> --json`: the manifest alone on
  stdout, the stops in `result.stops`. Do not parse the printed paths.
- Layout warnings: move or resize the object (its anchor, `below`, `right_of`), not the checkpoint.
- Timing warnings: change the times in the storyboard, not the style. The rest between two motions of one
  object comes from the style's `motion.hold_seconds`.

## More

In a manim8 checkout: `docs/USER_GUIDE.md` (the reference), `docs/tutorials/` (the same steps by hand),
`docs/ANIMATION_PATTERNS.md` (where the patterns come from) and `docs/WORKFLOW_PLAN.md` (the review loop).
