# Examples are read-only templates

Nothing here is meant to be rendered in place. `scianim workspace init <dir> --with-example` copies the family
and the project below into a workspace, where environments, revisions and renders live:

```text
examples/families/computational_neuroscience/            # family template: family.yaml, pyproject.toml, uv.lock
examples/families/computational_neuroscience/divisive_normalization/   # project template nested under its family
examples/families/computational_neuroscience/prf_tuning/              # second project: a 12 s clip, the pRF's centre and size swept
examples/families/computational_neuroscience/orientation_tuning/     # third project: a 20 s clip from the agent loop, kappa swept
```

The projects sit under their family on purpose: the nearest `family.yaml` above a project is authoritative, so a
project does not need a `family:` key. `scianim family init --from-example` and `scianim project init
--from-example` copy from here too.
