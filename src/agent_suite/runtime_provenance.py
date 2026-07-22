"""Installed-runtime provenance for suite components.

Candidate source checkouts and deployed artifacts are deliberately separate
facts.  This module inspects the interpreter that owns a component's visible
CLI, then reads that interpreter's distribution metadata.  It never falls
back to a similarly named checkout under ``/projects``.

The probe is conservative: an artifact without direct-origin metadata has a
trustworthy distribution version but no source revision; a PEP 610 VCS install
may expose a commit; and an editable local install is attributed only to its
exact, clean Git checkout.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from agent_suite.components import COMPONENTS, Component, Locality


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Which(Protocol):
    def __call__(self, executable: str) -> str | None: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_which(executable: str) -> str | None:
    return shutil.which(executable)


class InstallMode(Enum):
    """How an installed Python component must be mutated."""

    PIP_USER = "pip_user"
    VENV = "venv"
    PIPX = "pipx"
    UV_TOOL = "uv_tool"
    EDITABLE = "editable"
    SYSTEM = "system"
    ABSENT = "absent"
    UNKNOWN = "unknown"


class ArtifactSource(Enum):
    """What PEP 610 says about the installed artifact's origin."""

    UNRECORDED = "unrecorded"
    VCS = "vcs"
    EDITABLE = "editable"
    LOCAL = "local"
    ARCHIVE = "archive"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuntimeProvenance:
    component: str
    distribution: str | None
    version: str | None
    cli_path: str | None
    interpreter: str | None
    mode: InstallMode
    source: ArtifactSource
    revision: str | None = None
    source_path: str | None = None
    manager: str | None = None
    manager_package: str | None = None
    pep668: bool = False
    detail: str = ""

    def fingerprint(self) -> tuple[object, ...]:
        """Stable mutation target identity used for pre-apply revalidation."""
        return (
            self.distribution,
            self.version,
            self.cli_path,
            self.interpreter,
            self.mode,
            self.source,
            self.revision,
            self.source_path,
            self.manager,
            self.manager_package,
            self.pep668,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "distribution": self.distribution,
            "version": self.version,
            "cli_path": self.cli_path,
            "interpreter": self.interpreter,
            "mode": self.mode.value,
            "source": self.source.value,
            "revision": self.revision,
            "source_path": self.source_path,
            "manager": self.manager,
            "manager_package": self.manager_package,
            "pep668": self.pep668,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class _ManagerContext:
    pipx_apps: dict[str, str]
    uv_root: Path | None
    pipx_executable: str | None
    uv_executable: str | None


_METADATA_PROBE = r"""
import importlib.metadata as metadata
import importlib.util
import json
import pathlib
import site
import sys
import sysconfig
import urllib.parse
import urllib.request

cli = sys.argv[1]
cli_path = pathlib.Path(sys.argv[2]).resolve()
candidates = []
for requested in sys.argv[3:]:
    try:
        dist = metadata.distribution(requested)
    except metadata.PackageNotFoundError:
        continue
    entries = [
        ep for ep in dist.entry_points
        if ep.group == "console_scripts" and ep.name == cli
    ]
    if not entries:
        continue
    owns_script = False
    owns_module = False
    files = dist.files or ()
    try:
        resolved_files = {
            pathlib.Path(dist.locate_file(item)).resolve() for item in files
        }
    except (OSError, RuntimeError):
        resolved_files = set()
    if cli_path in resolved_files:
        owns_script = True
    for entry in entries:
        module = entry.value.partition(":")[0]
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, AttributeError, ValueError):
            spec = None
        if spec is not None and isinstance(spec.origin, str):
            try:
                if pathlib.Path(spec.origin).resolve() in resolved_files:
                    owns_module = True
            except (OSError, RuntimeError):
                pass
    candidates.append((requested, dist, owns_script, owns_module))

script_owners = [candidate for candidate in candidates if candidate[2]]
module_script_owners = [candidate for candidate in script_owners if candidate[3]]
if len(module_script_owners) == 1:
    selected = module_script_owners[0][:2]
elif len(script_owners) == 1:
    selected = script_owners[0][:2]
else:
    selected = None

if selected is None:
    detail = (
        "multiple declared distributions ambiguously own CLI"
        if candidates else "no declared distribution owns CLI"
    )
    print(json.dumps({"ok": False, "detail": detail}))
    raise SystemExit(0)

requested, dist = selected
source = "unrecorded"
revision = None
source_path = None
raw_direct = dist.read_text("direct_url.json")
if raw_direct is not None:
    try:
        direct = json.loads(raw_direct)
    except (TypeError, json.JSONDecodeError):
        direct = None
    if not isinstance(direct, dict) or not isinstance(direct.get("url"), str):
        source = "unknown"
    else:
        vcs = direct.get("vcs_info")
        directory = direct.get("dir_info")
        archive = direct.get("archive_info")
        members = sum(isinstance(item, dict) for item in (vcs, directory, archive))
        if members != 1:
            source = "unknown"
        elif isinstance(vcs, dict) and vcs.get("vcs") == "git":
            source = "vcs"
            commit = vcs.get("commit_id")
            if isinstance(commit, str):
                revision = commit
        elif isinstance(vcs, dict):
            source = "unknown"
        elif isinstance(directory, dict) and directory.get("editable") is True:
            source = "editable"
        elif isinstance(directory, dict):
            source = "local"
        elif isinstance(archive, dict):
            source = "archive"

        if source in ("editable", "local"):
            raw_url = direct.get("url")
            if isinstance(raw_url, str):
                parsed = urllib.parse.urlparse(raw_url)
                if parsed.scheme == "file" and parsed.netloc in ("", "localhost"):
                    decoded = urllib.request.url2pathname(
                        urllib.parse.unquote(parsed.path)
                    )
                    source_path = str(pathlib.Path(decoded).resolve())

user_site_raw = site.getusersitepackages()
if isinstance(user_site_raw, str):
    user_sites = [user_site_raw]
else:
    user_sites = list(user_site_raw)

stdlib = pathlib.Path(sysconfig.get_path("stdlib"))
print(json.dumps({
    "ok": True,
    "distribution": dist.metadata.get("Name") or requested,
    "version": dist.version,
    "interpreter": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "location": str(pathlib.Path(dist.locate_file("")).resolve()),
    "scripts": str(pathlib.Path(sysconfig.get_path("scripts")).resolve()),
    "user_sites": [str(pathlib.Path(p).resolve()) for p in user_sites],
    "pep668": (stdlib / "EXTERNALLY-MANAGED").is_file(),
    "source": source,
    "revision": revision,
    "source_path": source_path,
}))
"""


def _is_valid_sha(value: object) -> bool:
    if not isinstance(value, str) or len(value) not in (40, 64):
        return False
    return all(char in "0123456789abcdef" for char in value.lower())


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (OSError, RuntimeError, ValueError):
        return False
    return True


def _manager_context(runner: Runner, which: Which) -> _ManagerContext:
    pipx_apps: dict[str, str] = {}
    pipx_executable = which("pipx")
    try:
        result = runner(((pipx_executable or "pipx"), "list", "--json"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        result = None
    if result is not None and result.returncode == 0:
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            venvs = payload.get("venvs")
            if isinstance(venvs, dict):
                for metadata in venvs.values():
                    if not isinstance(metadata, dict):
                        continue
                    outer = metadata.get("metadata")
                    if not isinstance(outer, dict):
                        continue
                    main = outer.get("main_package")
                    if not isinstance(main, dict):
                        continue
                    package = main.get("package")
                    paths = main.get("app_paths")
                    if not isinstance(package, str) or not isinstance(paths, list):
                        continue
                    for raw_path in paths:
                        if not isinstance(raw_path, dict):
                            continue
                        path_value = raw_path.get("__Path__")
                        if isinstance(path_value, str):
                            pipx_apps[str(Path(path_value).resolve())] = package

    uv_root: Path | None = None
    uv_executable = which("uv")
    try:
        uv_result = runner(((uv_executable or "uv"), "tool", "dir"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        uv_result = None
    if uv_result is not None and uv_result.returncode == 0 and uv_result.stdout.strip():
        uv_root = Path(uv_result.stdout.strip()).expanduser().resolve()
    return _ManagerContext(
        pipx_apps=pipx_apps,
        uv_root=uv_root,
        pipx_executable=pipx_executable,
        uv_executable=uv_executable,
    )


def _env_key(comp: Component) -> str:
    ident = comp.ident.upper().replace("-", "_")
    return f"AGENT_SUITE_{ident}_PYTHON"


def _interpreter_candidates(comp: Component, cli_path: Path, which: Which) -> list[str]:
    """Return one explicitly attributable interpreter, or none.

    An environment override is an operator assertion and takes precedence.
    Otherwise only a simple Python shebang is accepted; unrelated ambient
    interpreters are never searched for matching metadata.
    """
    override = os.environ.get(_env_key(comp))
    if override:
        return [str(Path(override).expanduser())]

    try:
        with cli_path.open("rb") as handle:
            first_line = handle.readline(4096).decode("utf-8")
    except (OSError, RuntimeError, UnicodeDecodeError):
        first_line = ""
    if first_line.startswith("#!"):
        try:
            words = shlex.split(first_line[2:].strip(), posix=os.name != "nt")
        except ValueError:
            words = []
        if words:
            if Path(words[0]).name == "env" and len(words) == 2:
                resolved = which(words[1])
                if resolved:
                    return [resolved]
            elif len(words) == 1 and "python" in Path(words[0]).name.lower():
                return [words[0]]
    return []


def _read_probe(
    comp: Component,
    cli_path: Path,
    *,
    runner: Runner,
    which: Which,
) -> dict[str, object] | None:
    for interpreter in _interpreter_candidates(comp, cli_path, which):
        cmd = (
            interpreter,
            "-c",
            _METADATA_PROBE,
            comp.doctor_cmd[0],
            str(cli_path),
            *comp.distribution_names,
        )
        try:
            result = runner(cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
        if result.returncode != 0:
            continue
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("ok") is True:
            return payload
    return None


def _editable_revision(path: str | None, runner: Runner) -> tuple[str | None, str]:
    if not path:
        return None, "editable install has no trustworthy local path"
    checkout = Path(path)
    if not checkout.is_dir():
        return None, "editable source path is absent"
    try:
        status = runner(("git", "-C", str(checkout), "status", "--porcelain"))
        head = runner(("git", "-C", str(checkout), "rev-parse", "HEAD"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None, "editable source Git state is unavailable"
    if status.returncode != 0 or head.returncode != 0:
        return None, "editable source is not a readable Git checkout"
    if status.stdout.strip():
        return None, "editable source is dirty; revision is intentionally unknown"
    revision = head.stdout.strip()
    if not _is_valid_sha(revision):
        return None, "editable source returned an invalid Git revision"
    return revision, "editable source is clean and revision-attributed"


def probe_runtime_provenance(
    comp: Component,
    *,
    runner: Runner = _default_runner,
    which: Which = _default_which,
    managers: _ManagerContext | None = None,
) -> RuntimeProvenance:
    """Inspect the artifact actually reached by a component's visible CLI."""
    raw_cli = which(comp.doctor_cmd[0])
    if raw_cli is None:
        return RuntimeProvenance(
            component=comp.ident,
            distribution=None,
            version=None,
            cli_path=None,
            interpreter=None,
            mode=InstallMode.ABSENT,
            source=ArtifactSource.UNKNOWN,
            detail="component CLI is absent",
        )

    try:
        cli_path = Path(raw_cli).expanduser().resolve()
    except (OSError, RuntimeError):
        return RuntimeProvenance(
            component=comp.ident,
            distribution=None,
            version=None,
            cli_path=raw_cli,
            interpreter=None,
            mode=InstallMode.UNKNOWN,
            source=ArtifactSource.UNKNOWN,
            detail="visible CLI path could not be resolved safely",
        )
    probe = _read_probe(comp, cli_path, runner=runner, which=which)
    if probe is None:
        return RuntimeProvenance(
            component=comp.ident,
            distribution=None,
            version=None,
            cli_path=str(cli_path),
            interpreter=None,
            mode=InstallMode.UNKNOWN,
            source=ArtifactSource.UNKNOWN,
            detail="could not identify the distribution owning the visible CLI",
        )

    distribution = probe.get("distribution")
    version = probe.get("version")
    interpreter = probe.get("interpreter")
    location = probe.get("location")
    prefix = probe.get("prefix")
    base_prefix = probe.get("base_prefix")
    user_sites = probe.get("user_sites")
    raw_source = probe.get("source")
    source_path = probe.get("source_path")
    source = ArtifactSource.UNKNOWN
    if isinstance(raw_source, str):
        try:
            source = ArtifactSource(raw_source)
        except ValueError:
            source = ArtifactSource.UNKNOWN

    context = managers if managers is not None else _manager_context(runner, which)
    resolved_cli = str(cli_path)
    mode = InstallMode.UNKNOWN
    manager: str | None = None
    manager_package: str | None = None
    detail = "runtime identified"
    if source is ArtifactSource.EDITABLE:
        mode = InstallMode.EDITABLE
    elif resolved_cli in context.pipx_apps:
        mode = InstallMode.PIPX
        manager = context.pipx_executable
        manager_package = context.pipx_apps[resolved_cli]
    elif isinstance(interpreter, str) and context.uv_root is not None and _path_within(
        Path(interpreter), context.uv_root
    ):
        mode = InstallMode.UV_TOOL
        manager = context.uv_executable
        manager_package = distribution if isinstance(distribution, str) else None
    elif isinstance(prefix, str) and isinstance(base_prefix, str) and prefix != base_prefix:
        normalized = str(Path(interpreter).expanduser()) if isinstance(interpreter, str) else ""
        if "/pipx/venvs/" not in normalized and "/uv/tools/" not in normalized:
            mode = InstallMode.VENV
    elif isinstance(location, str) and isinstance(user_sites, list) and any(
        isinstance(site_path, str) and _path_within(Path(location), Path(site_path))
        for site_path in user_sites
    ):
        mode = InstallMode.PIP_USER
    elif isinstance(location, str):
        mode = InstallMode.SYSTEM

    revision: str | None = None
    if source is ArtifactSource.VCS and _is_valid_sha(probe.get("revision")):
        revision = str(probe["revision"])
        detail = "PEP 610 VCS commit attributed"
    elif source is ArtifactSource.EDITABLE:
        revision, detail = _editable_revision(
            source_path if isinstance(source_path, str) else None, runner
        )

    return RuntimeProvenance(
        component=comp.ident,
        distribution=distribution if isinstance(distribution, str) else None,
        version=version if isinstance(version, str) else None,
        cli_path=resolved_cli,
        interpreter=interpreter if isinstance(interpreter, str) else None,
        mode=mode,
        source=source,
        revision=revision,
        source_path=source_path if isinstance(source_path, str) else None,
        manager=manager,
        manager_package=manager_package,
        pep668=probe.get("pep668") is True,
        detail=detail,
    )


def read_runtime_provenance(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    runner: Runner = _default_runner,
    which: Which = _default_which,
) -> dict[str, RuntimeProvenance]:
    context = _manager_context(runner, which)
    records: dict[str, RuntimeProvenance] = {}
    for comp in components:
        try:
            records[comp.ident] = probe_runtime_provenance(
                comp, runner=runner, which=which, managers=context
            )
        except (OSError, RuntimeError, ValueError):
            records[comp.ident] = RuntimeProvenance(
                component=comp.ident,
                distribution=None,
                version=None,
                cli_path=None,
                interpreter=None,
                mode=InstallMode.UNKNOWN,
                source=ArtifactSource.UNKNOWN,
                detail="runtime provenance probe failed safely",
            )
    return records


def read_runtime_revisions(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    runner: Runner = _default_runner,
    which: Which = _default_which,
    strict: bool = True,
) -> dict[str, str | None]:
    """Return revisions attributable to installed artifacts.

    In strict mode, an installed per-box CLI whose provenance is ambiguous or
    failed raises ``RuntimeError`` so health gates cannot confuse probe failure
    with an ordinary versioned artifact that simply has no source revision.
    """
    provenance = read_runtime_provenance(
        components, runner=runner, which=which
    )
    failures = [
        comp.ident
        for comp in components
        if comp.locality is Locality.PER_BOX
        and provenance[comp.ident].mode is InstallMode.UNKNOWN
    ]
    if strict and failures:
        raise RuntimeError(
            "runtime provenance is ambiguous or unavailable for: "
            + ", ".join(failures)
        )
    return {
        comp.ident: (
            None
            if comp.locality is Locality.SHARED_SERVICE
            else provenance[comp.ident].revision
        )
        for comp in components
    }
