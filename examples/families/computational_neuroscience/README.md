# Family manifest fixture

`family.yaml` declares a family-scoped render environment. This documentation-only handoff deliberately does not include a resolved `uv.lock` or runnable family environment, because the `scianim` package and renderer have not been implemented yet.

During Milestones 0–1, create a family `pyproject.toml` with pinned supported Manim and SciAnim versions, generate `uv.lock` using `uv`, and check the lockfile into version control. Keep `.venv` local and excluded from export.

A user’s workspace hierarchy may contain nested topical folders; these inherit this family environment until a child folder explicitly declares a new `family.yaml`.
