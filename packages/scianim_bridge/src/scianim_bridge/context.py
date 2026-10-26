"""The job context: everything a scene needs, loaded from the job file the control plane wrote."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from scianim_bridge.data import DataTable, load_csv
from scianim_core import CheckpointRecord, RenderJob, ResolvedStyle
from scianim_core.animation import Equation, OutputSpec

JOB_FILE_ENV = "SCIANIM_JOB_FILE"
PROJECT_ROOT_ENV = "SCIANIM_PROJECT_ROOT"
Mode = Literal["snapshot", "video"]


@dataclass
class JobContext:
    job: RenderJob
    project_root: Path
    records: list[CheckpointRecord] = field(default_factory=list)
    captured: set[str] = field(default_factory=set)
    _tables: dict[str, DataTable] = field(default_factory=dict)

    @property
    def mode(self) -> Mode:
        return "snapshot" if self.job.operation == "render_snapshots" else "video"

    @property
    def style(self) -> ResolvedStyle:
        return self.job.resolved_style

    @property
    def output(self) -> OutputSpec:
        return self.job.output

    @property
    def equations(self) -> dict[str, Equation]:
        return self.job.equations

    @property
    def output_dir(self) -> Path:
        path = self.project_root / self.job.output_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def table(self, source_id: str) -> DataTable:
        if source_id not in self._tables:
            try:
                relative = self.job.data_files[source_id]
            except KeyError:
                raise KeyError(
                    f"data source '{source_id}' is not among the job's data files {sorted(self.job.data_files)}"
                ) from None
            self._tables[source_id] = load_csv(self.project_root / relative)
        return self._tables[source_id]

    @classmethod
    def from_file(cls, job_file: Path, project_root: Path | None = None) -> JobContext:
        job = RenderJob.model_validate_json(job_file.read_text(encoding="utf-8"))
        root = project_root or Path(os.environ.get(PROJECT_ROOT_ENV) or Path.cwd())
        return cls(job=job, project_root=root.resolve())

    @classmethod
    def from_env(cls) -> JobContext | None:
        job_file = os.environ.get(JOB_FILE_ENV)
        if not job_file:
            return None
        return cls.from_file(Path(job_file))


_CURRENT: JobContext | None = None


def set_current(ctx: JobContext | None) -> None:
    global _CURRENT
    _CURRENT = ctx


def current() -> JobContext | None:
    """The worker-installed context, else one from the environment, else None."""
    return _CURRENT if _CURRENT is not None else JobContext.from_env()
