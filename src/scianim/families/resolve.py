"""Family discovery (nearest ancestor wins), groups, assets, uv environments and system requirements."""

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
from typing import Literal

from scianim.config.loader import SpecError, load_family, load_group
from scianim_core import FamilyManifest, GroupManifest, SystemRequirement
from scianim_core.common import asset_id

FAMILY_FILE = "family.yaml"
GROUP_FILE = "group.yaml"
ASSETS_DIR = "assets"
COMPONENTS_DIR = "components"

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
try:
    from scianim_bridge.segment_store import code_fingerprint
    out["bridge_fingerprint"] = code_fingerprint()
except Exception:  # noqa: BLE001 - an older bridge has no fingerprint
    out["bridge_fingerprint"] = None
try:  # the font families Pango finds under this process's fontconfig (FONTCONFIG_FILE included), ADR-044
    import hashlib, manimpango
    families = "\n".join(sorted(set(manimpango.list_fonts())))
    out["fonts_fingerprint"] = hashlib.sha256(families.encode()).hexdigest()
except Exception:  # noqa: BLE001 - no manimpango: no fonts to name
    out["fonts_fingerprint"] = None
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

    @property
    def components_dir(self) -> Path:
        return self.root / COMPONENTS_DIR

    @property
    def assets_dir(self) -> Path:
        return self.root / ASSETS_DIR


@dataclass(frozen=True)
class GroupContext:
    manifest: GroupManifest
    path: Path

    @property
    def root(self) -> Path:
        return self.path.parent


@dataclass(frozen=True)
class FamilyLookup:
    context: FamilyContext
    via: Literal["ancestor", "search_root"]
    groups: tuple[GroupContext, ...]


def load_family_context(path: Path) -> FamilyContext:
    path = path.resolve()
    if path.is_dir():
        path = path / FAMILY_FILE
    return FamilyContext(manifest=load_family(path), path=path)


def load_group_context(path: Path) -> GroupContext:
    return GroupContext(manifest=load_group(path), path=path.resolve())


def nearest_family(project_root: Path) -> FamilyContext | None:
    """The closest `family.yaml` strictly above the project directory."""
    for parent in project_root.resolve().parents:
        candidate = parent / FAMILY_FILE
        if candidate.exists():
            return load_family_context(candidate)
    return None


def collect_groups(family_root: Path, project_root: Path) -> list[GroupContext]:
    """`group.yaml` files on the path from the family down to the project, outermost first."""
    family_root = family_root.resolve()
    project_root = project_root.resolve()
    if family_root not in project_root.parents:
        return []
    groups: list[GroupContext] = []
    node = family_root
    for part in project_root.relative_to(family_root).parts[:-1]:
        node = node / part
        candidate = node / GROUP_FILE
        if candidate.exists():
            groups.append(load_group_context(candidate))
    ids = [g.manifest.id for g in groups]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise SpecError(
            None, f"group id(s) {duplicates} appear more than once between {family_root} and {project_root}"
        )
    return groups


def locate_family(project_root: Path, declared: str | None, search_roots: list[Path]) -> FamilyLookup:
    """Resolve a project's family (spec section 4.1).

    The nearest ancestor `family.yaml` is authoritative; a declared `family:` must match it. Only a
    project outside every family directory is looked up by id in the search roots, where the id
    must be unique.
    """
    nearest = nearest_family(project_root)
    if nearest is not None:
        if declared is not None and nearest.manifest.id != declared:
            raise SpecError(
                nearest.path,
                f"project declares family '{declared}' but lives under family '{nearest.manifest.id}'; "
                "remove `family:` from animation.yaml or move the project",
            )
        return FamilyLookup(nearest, "ancestor", tuple(collect_groups(nearest.root, project_root)))
    if declared is None:
        raise SpecError(
            None,
            "no family: the project is not inside a family directory and animation.yaml has no `family:`",
        )
    matches: list[FamilyContext] = []
    looked: list[Path] = []
    for root in search_roots:
        if not root.is_dir():
            continue
        for candidate in sorted(root.glob(f"*/{FAMILY_FILE}")):
            looked.append(candidate)
            ctx = load_family_context(candidate)
            if ctx.manifest.id == declared:
                matches.append(ctx)
    if not matches:
        where = ", ".join(str(p) for p in looked) or "(no family.yaml files found)"
        raise SpecError(None, f"family '{declared}' not found; inspected: {where}")
    if len(matches) > 1:
        raise SpecError(
            None, f"family '{declared}' is declared in more than one place: {[str(m.path) for m in matches]}"
        )
    return FamilyLookup(matches[0], "search_root", ())


def resolve_asset(uri: str, family_root: Path | None, workspace_root: Path | None) -> Path:
    """`asset://<id>` -> file under the family's `assets/`, else the workspace's `assets/`."""
    ident = asset_id(uri)
    if any(part in ("..", "") for part in ident.split("/")):
        raise SpecError(None, f"asset id '{ident}' must be a plain relative path")
    searched: list[Path] = []
    for base in (family_root, workspace_root):
        if base is None:
            continue
        directory = base / ASSETS_DIR
        searched.append(directory)
        candidate = directory / ident
        if candidate.is_file():
            return candidate
    where = ", ".join(str(p) for p in searched) or "(no assets directories)"
    raise SpecError(None, f"asset '{uri}' not found; searched: {where}")


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
    """uv on PATH, else the binary of the `uv` package installed beside the control plane (manim8 depends on it,
    so a pip-only install can sync family environments, ADR-043)."""
    found = shutil.which("uv")
    if found:
        return found
    try:
        import uv  # the PyPI distribution that ships the uv binary; it imports nothing else

        return uv.find_uv_bin()
    except (ImportError, FileNotFoundError):
        return None


def repair_bridge_sources(ctx: FamilyContext, locked: bool = False, rewrite: bool = False) -> str | None:
    """Rewrite the family pyproject's bridge sources for this control plane when its path sources point at no
    package (a workspace moved, or cloned onto another machine), or always with `rewrite`. Returns a note saying
    what changed, or None when nothing did (ADR-043)."""
    from scianim.workspace import BRIDGE_SOURCE_ENV, bridge_source, rewrite_bridge_sources, unresolved_path_sources

    pyproject = ctx.env_root / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    broken = unresolved_path_sources(ctx.env_root, text)
    if not broken and not rewrite:
        return None
    if locked:
        why = (
            f"its path sources ({', '.join(broken)}) point at no package from {ctx.env_root}"
            if broken
            else "--rewrite-sources was requested"
        )
        raise SpecError(
            pyproject,
            f"the bridge sources must be rewritten ({why}), which changes the lockfile; sync without --locked",
        )
    source = bridge_source(ctx.env_root)
    updated = rewrite_bridge_sources(text, source)
    if updated == text:
        return None
    pyproject.write_text(updated, encoding="utf-8")
    why = (
        f"its path sources ({', '.join(broken)}) point at no package from here"
        if broken
        else "as requested" + (f" ({BRIDGE_SOURCE_ENV} is set)" if source.origin == BRIDGE_SOURCE_ENV else "")
    )
    return (
        f"rewrote the bridge sources in {pyproject}, {why}: the environment now takes manim8-bridge and "
        f"manim8-core from {source.describe()}; commit the change with the lockfile"
    )


def sync_environment(
    ctx: FamilyContext, locked: bool = False, timeout: float = 1800, rewrite_sources: bool = False
) -> CommandResult:
    """Create or update the family `.venv` from its lockfile with uv.

    Path sources for the bridge that point at no package are rewritten for this control plane first
    (`repair_bridge_sources`), and so are all bridge sources with `rewrite_sources`. Without a lockfile,
    `uv lock` runs first. The result's note says what was done. With `locked=True` a missing or stale lockfile,
    or sources that need rewriting, are an error instead.
    """
    if ctx.manifest.environment.manager != "uv":
        raise SpecError(ctx.path, f"environment manager '{ctx.manifest.environment.manager}' is not implemented yet")
    uv = uv_executable()
    if uv is None:
        raise SpecError(
            ctx.path, "`uv` is not on PATH and the `uv` package is not installed (https://docs.astral.sh/uv/)"
        )
    if not (ctx.env_root / "pyproject.toml").exists():
        raise SpecError(ctx.path, f"family environment root {ctx.env_root} has no pyproject.toml")
    from scianim.migrate import stale_family_pyproject

    if stale_family_pyproject((ctx.env_root / "pyproject.toml").read_text(encoding="utf-8")):
        raise SpecError(
            ctx.env_root / "pyproject.toml",
            "this environment names the render bridge `scianim-bridge`, which is now distributed as `manim8-bridge`; "
            f"run `scianim migrate {ctx.root}` and sync again",
        )
    notes: list[str] = []
    # The family has its own .venv; a caller's active environment (`uv run scianim`) is not the one to sync.
    env = {key: value for key, value in os.environ.items() if key != "VIRTUAL_ENV"}
    repaired = repair_bridge_sources(ctx, locked=locked, rewrite=rewrite_sources)
    if repaired:
        notes.append(repaired)
    if not ctx.lockfile.exists():
        if locked:
            raise SpecError(ctx.path, f"lockfile {ctx.lockfile} is missing and --locked was requested")
        lock = run_command([uv, "lock"], cwd=ctx.env_root, timeout=timeout, env=env)
        if not lock.ok:
            lock.note = "\n".join([*notes, "uv lock failed"])
            return lock
        notes.append(f"created lockfile {ctx.lockfile.name}; commit it")
    argv = [uv, "sync", "--no-dev"] + (["--locked"] if locked else [])
    result = run_command(argv, cwd=ctx.env_root, timeout=timeout, env=env)
    result.note = "\n".join(notes) or None
    return result


def probe_environment(ctx: FamilyContext, timeout: float = 120) -> dict[str, object]:
    """Report interpreter and package versions inside the family environment, without importing them here."""
    python = ctx.venv_python
    if not python.exists():
        return {"available": False, "reason": f"no environment at {ctx.venv_dir}; run `scianim family env sync`"}
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
                RequirementCheck(req, found is not None, found or f"lib{req.name} not found by the dynamic loader")
            )
        elif req.kind == "font":
            ok, detail = _font_installed(req.name)
            checks.append(RequirementCheck(req, ok, detail))
        elif req.kind == "python_module":
            present = bool(probe and probe.get(req.name))
            checks.append(
                RequirementCheck(req, present, "importable in family environment" if present else "not importable")
            )
        else:  # image
            checks.append(RequirementCheck(req, True, "container images are recorded, not verified, in this version"))
    return checks


def host_summary() -> dict[str, str]:
    return {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "uv": (uv_executable() or "missing"),
    }
