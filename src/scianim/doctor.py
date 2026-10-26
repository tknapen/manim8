"""`scianim doctor`: prerequisites for the control plane and for a family environment."""

from __future__ import annotations

import importlib.util
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from scianim.families.resolve import (
    FamilyContext,
    check_system_requirements,
    probe_environment,
    run_command,
)


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True

    @property
    def blocking(self) -> bool:
        return self.required and not self.ok


def control_plane_checks(workspace: Path) -> list[Check]:
    checks: list[Check] = []
    version = sys.version_info
    checks.append(
        Check(
            "python >= 3.12 (control plane)",
            version >= (3, 12),
            f"{version.major}.{version.minor}.{version.micro} at {sys.executable}",
        )
    )
    uv = shutil.which("uv")
    if uv:
        result = run_command([uv, "--version"], cwd=Path.cwd(), timeout=30)
        checks.append(Check("uv", result.ok, result.stdout.strip() or result.stderr.strip()))
    else:
        checks.append(Check("uv", False, "not on PATH; install from https://docs.astral.sh/uv/"))
    writable = os.access(workspace, os.W_OK)
    checks.append(Check("workspace writable", writable, str(workspace)))
    fc_list = shutil.which("fc-list")
    checks.append(
        Check(
            "fontconfig (fc-list)",
            fc_list is not None,
            fc_list or "not found; font checks fall back to directory scans",
            required=False,
        )
    )
    manim_spec = importlib.util.find_spec("manim")
    checks.append(
        Check(
            "manim absent from control plane",
            manim_spec is None,
            "not importable in this process (correct)"
            if manim_spec is None
            else f"importable from {manim_spec.origin}; it belongs only in family environments",
        )
    )
    return checks


def family_checks(ctx: FamilyContext) -> list[Check]:
    checks: list[Check] = []
    manifest = ctx.manifest
    checks.append(
        Check(
            f"family '{manifest.id}' pyproject",
            (ctx.env_root / "pyproject.toml").exists(),
            str(ctx.env_root / "pyproject.toml"),
        )
    )
    checks.append(Check(f"family '{manifest.id}' lockfile", ctx.lockfile.exists(), str(ctx.lockfile)))
    probe = probe_environment(ctx)
    if not probe.get("available"):
        checks.append(Check(f"family '{manifest.id}' environment", False, str(probe.get("reason"))))
        return checks
    checks.append(
        Check(
            f"family '{manifest.id}' environment",
            True,
            f"python {probe.get('python')} at {ctx.venv_python}",
        )
    )
    for module, label, required in (
        ("manim", "manim", True),
        ("scianim_bridge", "scianim-bridge", True),
        ("scianim_core", "scianim-core", True),
        ("av", "PyAV (video encoding)", True),
        ("manimpango", "manimpango (text)", True),
        ("cairo", "pycairo (cairo renderer)", True),
        ("typst", "typst (equations)", False),
    ):
        value = probe.get(module)
        error = (probe.get("errors") or {}).get(module) if isinstance(probe.get("errors"), dict) else None  # type: ignore[union-attr]
        checks.append(
            Check(
                f"  {label}",
                value is not None,
                str(value) if value is not None else (error or "not importable"),
                required=required,
            )
        )
    for rc in check_system_requirements(manifest, probe):
        checks.append(
            Check(
                f"  requirement {rc.requirement.kind} '{rc.requirement.name}'",
                rc.satisfied,
                rc.detail,
                required=not rc.requirement.optional,
            )
        )
    if any(
        r.kind == "binary" and r.name in ("latex", "pdflatex", "xelatex", "lualatex")
        for r in manifest.system_requirements
    ):
        checks.append(
            Check(
                "  dvisvgm (needed with LaTeX)",
                shutil.which("dvisvgm") is not None,
                shutil.which("dvisvgm") or "not on PATH",
            )
        )
    return checks
