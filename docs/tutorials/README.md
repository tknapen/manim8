# Tutorials

Short walkthroughs written against the real commands. Each page is also a test:
`tests/integration/test_tutorials.py` runs its shell blocks in order, applies its edits and checks the output
it quotes, so a tutorial that stops matching the package fails CI.

1. [Ten minutes to a picture](01_first_picture.md): render the checkpoints of an example clip, look at them,
   leave a comment. No YAML.
2. [Change one thing](02_change_one_thing.md): copy the example, change how far one parameter moves, meet a rule
   of the style, re-render only what changed, compare two revisions.

With an agent, the same steps are what the manim8 skill does on your behalf (`.claude/skills/manim8/`,
ADR-042); these pages are what you need to follow it and to take over when it gets stuck. The
[user guide](../USER_GUIDE.md) is the reference.

For maintainers: blocks fenced as `bash` run; `bash setup` and `bash notest` are shown but not run; a
`text output` block lists lines that must appear in the output of the `bash` block before it; a
`yaml before file=...` block followed by a `yaml after file=...` block is an edit, applied as a replacement
that must match exactly once. `~/animations` is replaced by a temporary directory.
