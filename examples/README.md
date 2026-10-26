# Examples are read-only templates

Nothing here is meant to be rendered in place. `scianim workspace init <dir> --with-example` copies the family
and the project below into a workspace, where environments, revisions and renders live:

```text
examples/families/computational_neuroscience/            # family template: family.yaml, pyproject.toml, uv.lock
examples/families/computational_neuroscience/divisive_normalization/   # project template nested under its family
```

The project sits under its family on purpose: the nearest `family.yaml` above a project is authoritative, so the
project does not need a `family:` key. `scianim family init --from-example` and `scianim project init
--from-example` copy from here too.
