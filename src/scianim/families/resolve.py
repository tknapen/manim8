"""Family discovery, uv environment sync, environment probing and system requirements."""

from __future__ import annotations

import ctypes.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from scianim.config.loader import SpecError, load_family
from scianim_core import FamilyManifest, SystemRequirement

FAMILY_FILE = "family.yaml"

PROBE_SCRIPT = r"""
import json, importlib, platform, sys
out = {"python": platform.python_version(), "executable": sys.executable}
for name in ("manim", "av", "typst", "manimpango", "cairo", "scianim_bridge", "scianim_core", "numpy", "PIL"):
    try:
        mod = importlib.import_module(name)
        out[name] = getattr(mod, "__version__", None) or getattr(mod, "version", None) or "present"
    except Exception as exc:  # noqa: BLE001 - report any import failure
        out[name] = None
        out.setdefault("errors", {})[name] = f"{type(exc).__name__}: {exc}"[:200]
print(json.dumps(out))
"""


@dataclass(frozen=True)
class FamilyContext:
    manifest: FamilyManifest
    path: Path
    """The family.yaml file."""

    @property
    def root(self) -> Path:
        return self.path.parent

    @property
    def env_root(self) -> Path:
        return (self.root / self.manifest.environment.project_root).resolve()

    @property
    def lockfile(self) -> Path:
        return self.env_root / self.manifest.environment.lockfile

    @property
    def venv_dir(self) -> Path:
        return self.env_root / ".venv"

    @property
    def venv_python(self) -> Path:
        if os.name == "nt":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python"


def load_family_context(path: Path) -> FamilyContext:
    path = path.resolve()
    if path.is_dir():
        path = path / FAMILY_FILE
    return FamilyContext(manifest=load_family(path), path=path)


def find_family(project_root: Path, family_id: str, search_roots: list[Path]) -> FamilyContext:
    """Ancestors of the project first (spec 4.1), then declared search roots."""
    looked: list[Path] = []
    for parent in (project_root.resolve(), *project_root.resolve().parents):
        candidate = parent / FAMILY_FILE
        if candidate.exists():
            looked.append(candidate)
            ctx = load_family_context(candidate)
            if ctx.manifest.id == family_id:
                return ctx
    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob(f"*/{FAMILY_FILE}")):
            looked.append(candidate)
            ctx = load_family_context(candidate)
            if ctx.manifest.id == family_id:
                return ctx
    where = ", ".join(str(p) for p in looked) or "(no family.yaml files found)"
    raise SpecError(None, f"family '{family_id}' not found; inspected: {where}")


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    note: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def run_command(argv: list[str], cwd: Path, timeout: float = 1800, env: dict[str, str] | None = None) -> CommandResult:
    start = time.monotonic()
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    return CommandResult(argv, proc.returncode, proc.stdout, proc.stderr, time.monotonic() - start)


def uv_executable() -> str | None:
    return shutil.which("uv")


def sync_environment(ctx: FamilyContext, locked: bool = False, timeout: float = 1800) -> CommandResult:
    """Create or update the family `.venv` from its lockfile with uv.

    Without a lockfile, `uv lock` runs first and the result's note says so. With `locked=True`
    a missing or stale lockfile is an error instead.
    """
    if ctx.manifest.environment.manager != "uv":
        raise SpecError(
            ctx.path,
            f"environment manager '{ctx.manifest.environment.manager}' is not implemented yet",
        )
    uv = uv_executable()
    if uv is None:
        raise SpecError(ctx.path, "`uv` is not installed or not on PATH (https://docs.astral.sh/uv/)")
    if not (ctx.env_root / "pyproject.toml").exists():
        raise SpecError(ctx.path, f"family environment root {ctx.env_root} has no pyproject.toml")
    note = None
    if not ctx.lockfile.exists():
        if locked:
            raise SpecError(ctx.path, f"lockfile {ctx.lockfile} is missing and --locked was requested")
        lock = run_command([uv, "lock"], cwd=ctx.env_root, timeout=timeout)
        if not lock.ok:
            lock.note = "uv lock failed"
            return lock
        note = f"created lockfile {ctx.lockfile.name}; commit it"
    argv = [uv, "sync", "--no-dev"] + (["--locked"] if locked else [])
    result = run_command(argv, cwd=ctx.env_root, timeout=timeout)
    result.note = note
    return result


def probe_environment(ctx: FamilyContext, timeout: float = 120) -> dict[str, object]:
    """Report interpreter and package versions inside the family environment, without importing them here."""
    python = ctx.venv_python
    if not python.exists():
        return {
            "available": False,
            "reason": f"no environment at {ctx.venv_dir}; run `scianim family env sync`",
        }
    result = run_command([str(python), "-I", "-c", PROBE_SCRIPT], cwd=ctx.env_root, timeout=timeout)
    if not result.ok:
        return {"available": False, "reason": result.stderr.strip()[-500:] or "probe failed"}
    data = json.loads(result.stdout.strip().splitlines()[-1])
    data["available"] = True
    return data


@dataclass
class RequirementCheck:
    requirement: SystemRequirement
    satisfied: bool
    detail: str

    @property
    def blocking(self) -> bool:
        return not self.satisfied and not self.requirement.optional


def _font_installed(name: str) -> tuple[bool, str]:
    fc_list = shutil.which("fc-list")
    if fc_list:
        proc = subprocess.run([fc_list, ":", "family"], capture_output=True, text=True, timeout=60)
        families = {line.strip().lower() for line in proc.stdout.splitlines()}
        hit = any(name.lower() in fam for fam in families)
        return hit, "listed by fc-list" if hit else "not listed by fc-list"
    roots = [
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
        Path.home() / ".fonts",
        Path.home() / "Library/Fonts",
        Path("/Library/Fonts"),
        Path("C:/Windows/Fonts"),
    ]
    needle = name.replace(" ", "").lower()
    for root in roots:
        if root.is_dir():
            for file in root.rglob("*"):
                if needle in file.stem.replace(" ", "").lower():
                    return True, f"found {file}"
    return False, "fc-list unavailable and no matching font file found"


def check_system_requirements(
    manifest: FamilyManifest, probe: dict[str, object] | None = None
) -> list[RequirementCheck]:
    checks: list[RequirementCheck] = []
    for req in manifest.system_requirements:
        if req.kind == "binary":
            found = shutil.which(req.name)
            checks.append(RequirementCheck(req, found is not None, found or "not on PATH"))
        elif req.kind == "library":
            found = ctypes.util.find_library(req.name)
            checks.append(
                RequirementCheck(
                    req,
                    found is not None,
                    found or f"lib{req.name} not found by the dynamic loader",
                )
            )
        elif req.kind == "font":
            ok, detail = _font_installed(req.name)
            checks.append(RequirementCheck(req, ok, detail))
        elif req.kind == "python_module":
            present = bool(probe and probe.get(req.name))
            checks.append(
                RequirementCheck(
                    req,
                    present,
                    "importable in family environment" if present else "not importable",
                )
            )
        else:  # image
            checks.append(RequirementCheck(req, True, "container images are recorded, not verified, in this version"))
    return checks


def host_summary() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "uv": (shutil.which("uv") or "missing"),
    }
