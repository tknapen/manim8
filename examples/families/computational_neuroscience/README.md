# Family manifest fixture

`family.yaml` declares a family-scoped render environment and its system requirements. The family's `pyproject.toml` depends on `manim` and `scianim-bridge` (never on the `scianim` control plane); `uv.lock` pins the resolved graph and is committed. `.venv` stays local and excluded from export.

A user's workspace hierarchy may contain nested topical folders; these inherit this family environment until a child folder explicitly declares a new `family.yaml`.

`system_requirements` lists what `uv` cannot pin: the Cairo library that `pycairo` links against, fonts, and a TeX distribution if the family opts into LaTeX instead of the default Typst engine. `scianim doctor` checks them.
