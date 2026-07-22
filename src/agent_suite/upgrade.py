"""Installation-aware lock reconciliation, advancement, and rollback.

The command treats repair and advancement as separate transactions. Drift is
reconciled exactly to the existing lock without rewriting it. A matching
runtime may advance through exact resolved targets and a temporary candidate
lock. Runtime provenance identifies the interpreter and manager owning each
visible CLI; unsupported or ambiguous installations fail before mutation.
Every mutation is fingerprint-checked, post-verified, and journalled for
reverse-order rollback to captured pre-state. ``--dry-run`` plans without
acting and ``--check`` is read-only. The stdlib-only core shells only to the
owning package manager, component CLIs, and system service manager.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never, cast

from agent_suite.components import COMPONENTS, Component, Locality, UpgradeKind
from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite.runtime_provenance import (
    InstallMode,
    RuntimeProvenance,
    probe_runtime_provenance,
)


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as doctor.Runner / lock.VersionRunner)
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a component CLI or OS command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


class ProvenanceProbe(Protocol):
    """Inspect the installed artifact reached by a component's visible CLI."""

    def __call__(self, component: Component) -> RuntimeProvenance: ...


class ProviderProbe(Protocol):
    def __call__(
        self, *, runner: Runner, installed: Installed
    ) -> lock_mod.ProviderExtension | None: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


def _default_provenance_probe(component: Component) -> RuntimeProvenance:
    return probe_runtime_provenance(component)


def _default_provider_probe(
    *, runner: Runner, installed: Installed
) -> lock_mod.ProviderExtension | None:
    from agent_suite.config import memory_provider_config

    engine = str(memory_provider_config()["engine"])
    provider = lock_mod.read_provider_extension(
        engine=engine, runner=runner, installed=installed
    )
    if engine != "native" and provider is None:
        raise RuntimeError(f"configured provider {engine!r} could not be attributed")
    return provider


# ---------------------------------------------------------------------------
# Closed-set enums (assert_never in every dispatch)
# ---------------------------------------------------------------------------


class AdvancementStatus(Enum):
    """The closed set of per-component advancement-check outcomes.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    UP_TO_DATE = "up_to_date"
    ADVANCEMENT_AVAILABLE = "advancement_available"
    NOT_INSTALLED = "not_installed"
    UNREACHABLE = "unreachable"
    ERROR = "error"


class ApplyStatus(Enum):
    """The closed set of per-component apply-step outcomes."""

    APPLIED = "applied"
    ALREADY_CURRENT = "already_current"
    SKIPPED = "skipped"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class RollbackStatus(Enum):
    """The closed set of rollback outcomes."""

    APPLIED = "applied"
    REFUSED_MIGRATION_BOUNDARY = "refused_migration_boundary"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ComponentAdvancement:
    """One component's available-advancement check result."""

    component: str
    current_version: str | None
    target_version: str | None
    status: AdvancementStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "current_version": self.current_version,
            "target_version": self.target_version,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class AdvancementReport:
    """The outcome of ``upgrade --check`` (read-only)."""

    advancements: list[ComponentAdvancement] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "advancements": [a.to_dict() for a in self.advancements],
            "note": self.note,
        }


@dataclass
class ApplyStep:
    """One component's apply outcome during an upgrade."""

    component: str
    status: ApplyStatus
    from_version: str | None
    to_version: str | None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "status": self.status.value,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "detail": self.detail,
        }


@dataclass
class UpgradeResult:
    """The full upgrade outcome."""

    ok: bool
    dry_run: bool
    check_only: bool
    component_filter: str | None
    advancements: list[ComponentAdvancement] = field(default_factory=list)
    apply_steps: list[ApplyStep] = field(default_factory=list)
    interop_passed: bool = False
    lock_written: bool = False
    rollback_performed: bool = False
    interop_evidence_ref: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "check_only": self.check_only,
            "component_filter": self.component_filter,
            "advancements": [item.to_dict() for item in self.advancements],
            "apply_steps": [s.to_dict() for s in self.apply_steps],
            "interop_passed": self.interop_passed,
            "lock_written": self.lock_written,
            "rollback_performed": self.rollback_performed,
            "interop_evidence_ref": self.interop_evidence_ref,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class _PlannedMutation:
    component: Component
    before: RuntimeProvenance
    target_version: str
    advances_lock: bool


@dataclass
class RollbackResult:
    """The outcome of ``upgrade --to <lock-ref>``."""

    ok: bool
    status: RollbackStatus
    target_ref: str
    target_lock: lock_mod.SuiteLock | None = None
    current_schema_version: int | None = None
    target_schema_version: int | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "target_ref": self.target_ref,
            "target_lock": self.target_lock.to_dict() if self.target_lock else None,
            "current_schema_version": self.current_schema_version,
            "target_schema_version": self.target_schema_version,
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Version discovery — thin orchestration via the OS package manager
# ---------------------------------------------------------------------------

_ALREADY_SATISFIED = "Requirement already satisfied"


def _would_install_version(package: str, output: str) -> str | None:
    """Extract one resolved version without splitting hyphenated project names."""
    name_parts = [re.escape(part) for part in re.split(r"[-_.]+", package)]
    normalized_name = r"[-_.]+".join(name_parts)
    for line in output.splitlines():
        if not line.lstrip().lower().startswith("would install "):
            continue
        match = re.search(
            rf"\b{normalized_name}-(?P<version>[^\s]+)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group("version")
    return None


def _pip_install_command(
    record: RuntimeProvenance,
    requirement: str,
    *,
    dry_run: bool,
) -> tuple[str, ...] | None:
    """Build a pip operation for the exact interpreter that owns the CLI."""
    if record.interpreter is None:
        return None
    if record.mode is InstallMode.UV_TOOL:
        if record.manager is None:
            return None
        command = [
            record.manager,
            "pip",
            "install",
            "--python",
            record.interpreter,
        ]
    elif record.mode in (
        InstallMode.PIP_USER,
        InstallMode.VENV,
        InstallMode.PIPX,
    ):
        command = [record.interpreter, "-m", "pip", "install"]
        if record.mode is InstallMode.PIP_USER:
            command.append("--user")
            if record.pep668:
                command.append("--break-system-packages")
    else:
        return None
    if dry_run:
        command.append("--dry-run")
    command.extend(("--upgrade", "--no-deps", requirement))
    return tuple(command)


def _mutation_command(
    record: RuntimeProvenance,
    requirement: str,
) -> tuple[str, ...] | None:
    """Build an exact-version mutation through the detected installation manager."""
    match record.mode:
        case InstallMode.PIP_USER | InstallMode.VENV:
            return _pip_install_command(record, requirement, dry_run=False)
        case InstallMode.PIPX:
            if record.manager is None:
                return None
            return (record.manager, "install", "--force", requirement)
        case InstallMode.UV_TOOL:
            if record.manager is None:
                return None
            return (record.manager, "tool", "install", "--force", requirement)
        case (
            InstallMode.EDITABLE
            | InstallMode.SYSTEM
            | InstallMode.ABSENT
            | InstallMode.UNKNOWN
        ):
            return None
        case other:
            assert_never(other)


def _mutation_refusal(record: RuntimeProvenance) -> str:
    return (
        f"refused: {record.component} is installed as {record.mode.value}; "
        "use its owning deployment workflow or reinstall it in a managed "
        "user/venv/pipx/uv-tool environment"
    )


def _pip_check_latest(
    package: str,
    *,
    runner: Runner,
    command: tuple[str, ...] | None = None,
) -> tuple[str | None, str | None, AdvancementStatus, str]:
    """Check the latest available version via ``pip install --dry-run --upgrade``.

    Returns ``(installed_version, latest_version, status, detail)``. Never raises
    — a command failure, timeout, or unparseable output is a named status.
    """
    cmd = command or (
        "pip", "install", "--dry-run", "--upgrade", "--no-deps", package,
    )
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return None, None, AdvancementStatus.UNREACHABLE, "pip not found on PATH"
    except subprocess.TimeoutExpired:
        return None, None, AdvancementStatus.UNREACHABLE, "pip check timed out"
    except OSError as exc:
        return None, None, AdvancementStatus.UNREACHABLE, f"pip check failed: {exc}"

    combined = result.stdout + result.stderr
    if _ALREADY_SATISFIED in combined and "Would install" not in combined:
        installed_match = re.search(r"already satisfied: " + re.escape(package) + r"[^\d]*([\d.]+)", combined)
        installed = installed_match.group(1) if installed_match else None
        return installed, installed, AdvancementStatus.UP_TO_DATE, "already up to date"

    target = _would_install_version(package, combined)
    if target is not None and "Would install" in combined:
        installed_match = re.search(
            r"would install " + re.escape(package) + r"[^\d]*([\d.]+)", combined
        )
        installed = installed_match.group(1) if installed_match else None
        return installed, target, AdvancementStatus.ADVANCEMENT_AVAILABLE, f"{installed or '?'} -> {target}"

    if result.returncode != 0:
        return None, None, AdvancementStatus.ERROR, f"pip exit {result.returncode}: {result.stderr.strip()[:200]}"

    return None, None, AdvancementStatus.ERROR, "could not parse pip dry-run output"


def _docker_check_latest(
    comp: Component,
    *,
    runner: Runner,
) -> tuple[str | None, str | None, AdvancementStatus, str]:
    """Check the latest available container image via ``docker pull`` (dry-run not available).

    For Docker components, version discovery is best-effort: we read the current
    version from ``<tool> doctor --json`` and report UP_TO_DATE (the actual
    upgrade applies a ``docker pull`` which either updates or is a no-op).
    """
    cli_name = comp.doctor_cmd[0]
    try:
        result = runner(comp.doctor_cmd)
    except FileNotFoundError:
        return None, None, AdvancementStatus.NOT_INSTALLED, f"{cli_name} not found"
    except subprocess.TimeoutExpired:
        return None, None, AdvancementStatus.UNREACHABLE, f"{cli_name} doctor timed out"
    except OSError as exc:
        return None, None, AdvancementStatus.UNREACHABLE, f"{cli_name} doctor failed: {exc}"

    if result.returncode != 0:
        return None, None, AdvancementStatus.UNREACHABLE, f"{cli_name} doctor exit {result.returncode}"

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, None, AdvancementStatus.ERROR, f"{cli_name} doctor non-JSON"

    version = data.get("version") if isinstance(data, dict) else None
    return (
        str(version) if version else None,
        str(version) if version else None,
        AdvancementStatus.UP_TO_DATE,
        "docker — pull will update if newer image exists",
    )


def _check_one_advancement(
    comp: Component,
    *,
    runner: Runner,
    installed: Installed,
    provenance_probe: ProvenanceProbe,
    components: tuple[Component, ...] = COMPONENTS,
) -> ComponentAdvancement:
    """Check one component for available advancements."""
    cli_name = comp.doctor_cmd[0]
    if not installed(cli_name):
        return ComponentAdvancement(
            component=comp.ident,
            current_version=None,
            target_version=None,
            status=AdvancementStatus.NOT_INSTALLED,
            detail=f"{cli_name} not installed",
        )

    match comp.upgrade_kind:
        case UpgradeKind.PYTHON:
            record = provenance_probe(comp)
            if record.mode is InstallMode.ABSENT:
                return ComponentAdvancement(
                    component=comp.ident,
                    current_version=None,
                    target_version=None,
                    status=AdvancementStatus.NOT_INSTALLED,
                    detail=record.detail,
                )
            command = _pip_install_command(
                record, comp.upgrade_package, dry_run=True
            )
            if command is None:
                return ComponentAdvancement(
                    component=comp.ident,
                    current_version=record.version,
                    target_version=None,
                    status=AdvancementStatus.ERROR,
                    detail=_mutation_refusal(record),
                )
            _, latest_ver, status, detail = _pip_check_latest(
                comp.upgrade_package, runner=runner, command=command
            )
            return ComponentAdvancement(
                component=comp.ident,
                current_version=record.version,
                target_version=latest_ver,
                status=status,
                detail=detail,
            )
        case UpgradeKind.PIPX:
            installed_ver, latest_ver, status, detail = _pip_check_latest(
                comp.upgrade_package, runner=runner
            )
            return ComponentAdvancement(
                component=comp.ident,
                current_version=installed_ver,
                target_version=latest_ver,
                status=status,
                detail=detail,
            )
        case UpgradeKind.DOCKER:
            installed_ver, latest_ver, status, detail = _docker_check_latest(
                comp, runner=runner
            )
            return ComponentAdvancement(
                component=comp.ident,
                current_version=installed_ver,
                target_version=latest_ver,
                status=status,
                detail=detail,
            )
        case other:
            assert_never(other)


def check_advancements(
    *,
    component: str | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    provenance_probe: ProvenanceProbe = _default_provenance_probe,
    components: tuple[Component, ...] = COMPONENTS,
) -> AdvancementReport:
    """Check each component for available version advancements (read-only).

    If ``component`` is given, check only that one. Never raises — a missing
    component, unreachable registry, or parse failure is a named status.
    """
    targets = components
    if component is not None:
        targets = tuple(c for c in components if c.ident == component)
        if not targets:
            return AdvancementReport(
                advancements=[],
                note=f"unknown component: {component}",
            )

    advancements = [
        _check_one_advancement(
            c,
            runner=runner,
            installed=installed,
            provenance_probe=provenance_probe,
            components=components,
        )
        for c in targets
    ]
    available = [a for a in advancements if a.status is AdvancementStatus.ADVANCEMENT_AVAILABLE]
    if not available:
        note = "no advancements available"
    else:
        names = ", ".join(a.component for a in available)
        note = f"{len(available)} advancement(s) available: {names}"

    return AdvancementReport(advancements=advancements, note=note)


# ---------------------------------------------------------------------------
# Apply step — pipx upgrade / docker pull / service restart
# ---------------------------------------------------------------------------


def _apply_python(
    comp: Component,
    record: RuntimeProvenance,
    target_version: str,
    *,
    runner: Runner,
    dry_run: bool,
) -> ApplyStep:
    """Install one exact version through the manager owning the visible CLI."""
    distribution = record.distribution or comp.upgrade_package
    requirement = f"{distribution}=={target_version}"
    cmd = _mutation_command(record, requirement)
    if cmd is None:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=record.version,
            to_version=target_version,
            detail=_mutation_refusal(record),
        )
    label = " ".join(cmd)
    if dry_run:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.SKIPPED,
            from_version=record.version,
            to_version=target_version,
            detail=f"would run: {label}",
        )
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=record.version,
            to_version=target_version,
            detail=f"command not found: {cmd[0]}",
        )
    except subprocess.TimeoutExpired:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=record.version,
            to_version=target_version,
            detail=f"install timed out: {label}",
        )
    except OSError as exc:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=record.version,
            to_version=target_version,
            detail=f"install failed: {exc}",
        )
    if result.returncode != 0:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=record.version,
            to_version=target_version,
            detail=f"install exit {result.returncode}: {result.stderr.strip()[:200]}",
        )
    return ApplyStep(
        component=comp.ident,
        status=ApplyStatus.APPLIED,
        from_version=record.version,
        to_version=target_version,
        detail=f"installed {requirement} via {record.mode.value}",
    )


def _apply_pipx(
    comp: Component,
    *,
    runner: Runner,
    dry_run: bool,
) -> ApplyStep:
    """Apply a pipx upgrade for one component."""
    if dry_run:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.SKIPPED,
            from_version=None,
            to_version=None,
            detail=f"would run: pipx upgrade {comp.upgrade_package}",
        )
    cmd: tuple[str, ...] = ("pipx", "upgrade", comp.upgrade_package)
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail="pipx not found on PATH",
        )
    except subprocess.TimeoutExpired:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail="pipx upgrade timed out",
        )
    except OSError as exc:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"pipx upgrade failed: {exc}",
        )

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "already" in stderr.lower() or "latest" in stderr.lower():
            return ApplyStep(
                component=comp.ident,
                status=ApplyStatus.ALREADY_CURRENT,
                from_version=None,
                to_version=None,
                detail=f"{comp.upgrade_package} already at latest",
            )
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"pipx upgrade exit {result.returncode}: {stderr[:200]}",
        )

    return ApplyStep(
        component=comp.ident,
        status=ApplyStatus.APPLIED,
        from_version=None,
        to_version=None,
        detail=f"pipx upgrade {comp.upgrade_package} completed",
    )


def _apply_docker(
    comp: Component,
    *,
    runner: Runner,
    dry_run: bool,
) -> ApplyStep:
    """Apply a docker pull for one component."""
    if dry_run:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.SKIPPED,
            from_version=None,
            to_version=None,
            detail=f"would run: docker pull {comp.upgrade_package}",
        )
    cmd: tuple[str, ...] = ("docker", "pull", comp.upgrade_package)
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail="docker not found on PATH",
        )
    except subprocess.TimeoutExpired:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail="docker pull timed out",
        )
    except OSError as exc:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"docker pull failed: {exc}",
        )

    if result.returncode != 0:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"docker pull exit {result.returncode}: {result.stderr.strip()[:200]}",
        )

    return ApplyStep(
        component=comp.ident,
        status=ApplyStatus.APPLIED,
        from_version=None,
        to_version=None,
        detail=f"docker pull {comp.upgrade_package} completed",
    )


def _restart_service(
    comp: Component,
    *,
    runner: Runner,
    dry_run: bool,
) -> ApplyStep:
    """Restart the OS service for a component after upgrade."""
    if not comp.service_unit:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.SKIPPED,
            from_version=None,
            to_version=None,
            detail="no service unit — CLI-only component",
        )
    if dry_run:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.SKIPPED,
            from_version=None,
            to_version=None,
            detail=f"would run: systemctl restart {comp.service_unit}",
        )
    cmd: tuple[str, ...] = ("systemctl", "restart", comp.service_unit)
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail="systemctl not found (not on systemd?)",
        )
    except subprocess.TimeoutExpired:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"systemctl restart {comp.service_unit} timed out",
        )
    except OSError as exc:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"systemctl restart failed: {exc}",
        )

    if result.returncode != 0:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=None,
            detail=f"systemctl restart exit {result.returncode}: {result.stderr.strip()[:200]}",
        )

    return ApplyStep(
        component=comp.ident,
        status=ApplyStatus.APPLIED,
        from_version=None,
        to_version=None,
        detail=f"service {comp.service_unit} restarted",
    )


def _service_uses_runtime(
    comp: Component,
    record: RuntimeProvenance,
    *,
    runner: Runner,
) -> tuple[bool, str]:
    """Prove a systemd service executes the same CLI artifact before restart."""
    if not comp.service_unit:
        return True, "CLI-only component"
    if record.cli_path is None:
        return False, "service ownership cannot be proven without a CLI path"
    command = (
        "systemctl",
        "show",
        comp.service_unit,
        "--property=ExecStart",
        "--value",
    )
    try:
        result = runner(command)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, f"service ownership probe failed: {type(exc).__name__}"
    if result.returncode != 0:
        return False, f"service ownership probe exit {result.returncode}"
    raw_exec = result.stdout.strip()
    path_match = re.search(r"(?:^|[;{\s])path=([^\s;}]+)", raw_exec)
    executable: str | None = path_match.group(1) if path_match else None
    if executable is None:
        try:
            words = shlex.split(raw_exec)
        except ValueError:
            words = []
        if words:
            executable = words[0]
    try:
        matches_cli = (
            executable is not None
            and Path(executable).resolve() == Path(record.cli_path).resolve()
        )
    except (OSError, RuntimeError):
        matches_cli = False
    if not matches_cli:
        return False, (
            f"service {comp.service_unit} ExecStart does not reference "
            f"the visible CLI as its executable ({record.cli_path})"
        )
    return True, "service ExecStart matches visible CLI"


def _apply_one(
    comp: Component,
    *,
    runner: Runner,
    dry_run: bool,
    provenance: RuntimeProvenance | None = None,
    target_version: str | None = None,
) -> list[ApplyStep]:
    """Apply the upgrade for one component (upgrade + optional service restart).

    Returns a list of ApplySteps (the upgrade step + the restart step if applicable).
    """
    match comp.upgrade_kind:
        case UpgradeKind.PYTHON:
            if provenance is None or target_version is None:
                upgrade_step = ApplyStep(
                    component=comp.ident,
                    status=ApplyStatus.FAILED,
                    from_version=provenance.version if provenance else None,
                    to_version=target_version,
                    detail="runtime provenance and exact target version are required",
                )
            else:
                upgrade_step = _apply_python(
                    comp,
                    provenance,
                    target_version,
                    runner=runner,
                    dry_run=dry_run,
                )
        case UpgradeKind.PIPX:
            upgrade_step = _apply_pipx(comp, runner=runner, dry_run=dry_run)
        case UpgradeKind.DOCKER:
            upgrade_step = _apply_docker(comp, runner=runner, dry_run=dry_run)
        case other:
            assert_never(other)

    steps = [upgrade_step]

    if upgrade_step.status in (ApplyStatus.APPLIED, ApplyStatus.ALREADY_CURRENT):
        if comp.service_unit:
            restart_step = _restart_service(comp, runner=runner, dry_run=dry_run)
            steps.append(restart_step)

    return steps


# ---------------------------------------------------------------------------
# Rollback step — restore a previously-pinned version
# ---------------------------------------------------------------------------


def _rollback_one(
    comp: Component,
    target_version: str,
    *,
    runner: Runner,
    provenance: RuntimeProvenance | None = None,
) -> ApplyStep:
    """Restore a component to a specific previously-pinned version."""
    match comp.upgrade_kind:
        case UpgradeKind.PYTHON:
            if provenance is None:
                return ApplyStep(
                    component=comp.ident,
                    status=ApplyStatus.FAILED,
                    from_version=None,
                    to_version=target_version,
                    detail="runtime provenance is required for rollback",
                )
            step = _apply_python(
                comp,
                provenance,
                target_version,
                runner=runner,
                dry_run=False,
            )
            if step.status is ApplyStatus.APPLIED:
                step.status = ApplyStatus.ROLLED_BACK
                step.detail = (
                    f"rolled back to {target_version} via {provenance.mode.value}"
                )
            return step
        case UpgradeKind.PIPX:
            cmd: tuple[str, ...] = (
                "pipx", "install", "--force", f"{comp.upgrade_package}=={target_version}",
            )
            label = f"pipx install {comp.upgrade_package}=={target_version}"
        case UpgradeKind.DOCKER:
            cmd = ("docker", "pull", f"{comp.upgrade_package}:{target_version}")
            label = f"docker pull {comp.upgrade_package}:{target_version}"
        case other:
            assert_never(other)

    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=target_version,
            detail=f"command not found for rollback: {cmd[0]}",
        )
    except subprocess.TimeoutExpired:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=target_version,
            detail=f"rollback timed out: {label}",
        )
    except OSError as exc:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=target_version,
            detail=f"rollback failed: {exc}",
        )

    if result.returncode != 0:
        return ApplyStep(
            component=comp.ident,
            status=ApplyStatus.FAILED,
            from_version=None,
            to_version=target_version,
            detail=f"rollback exit {result.returncode}: {result.stderr.strip()[:200]}",
        )

    return ApplyStep(
        component=comp.ident,
        status=ApplyStatus.ROLLED_BACK,
        from_version=None,
        to_version=target_version,
        detail=f"rolled back to {target_version} via {label}",
    )


def _rollback_all(
    lock: lock_mod.SuiteLock,
    *,
    runner: Runner,
    components: tuple[Component, ...] = COMPONENTS,
    provenance_probe: ProvenanceProbe = _default_provenance_probe,
) -> list[ApplyStep]:
    """Restore a lock transactionally after validating every target first."""
    steps: list[ApplyStep] = []
    planned: list[tuple[Component, lock_mod.ComponentPin, RuntimeProvenance | None]] = []
    for comp in components:
        if comp.ident not in lock.components:
            continue
        pin = lock.components[comp.ident]
        if comp.upgrade_kind is not UpgradeKind.PYTHON:
            return [
                ApplyStep(
                    component=comp.ident,
                    status=ApplyStatus.FAILED,
                    from_version=None,
                    to_version=pin.version,
                    detail="rollback preflight cannot capture this legacy install kind",
                )
            ]
        try:
            provenance = provenance_probe(comp)
        except Exception as exc:
            return [
                ApplyStep(
                    component=comp.ident,
                    status=ApplyStatus.FAILED,
                    from_version=None,
                    to_version=pin.version,
                    detail=f"rollback preflight probe failed: {type(exc).__name__}",
                )
            ]
        if provenance is not None:
            requirement = (
                f"{provenance.distribution or comp.upgrade_package}=={pin.version}"
            )
            if _mutation_command(provenance, requirement) is None:
                return [
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=provenance.version,
                        to_version=pin.version,
                        detail=_mutation_refusal(provenance),
                    )
                ]
            owned, detail = _service_uses_runtime(comp, provenance, runner=runner)
            if not owned:
                return [
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=provenance.version,
                        to_version=pin.version,
                        detail=f"refused: {detail}",
                    )
                ]
        planned.append((comp, pin, provenance))

    journal: list[tuple[Component, RuntimeProvenance]] = []

    def restore_journal() -> None:
        for changed, before in reversed(journal):
            if before.version is None:
                steps.append(
                    ApplyStep(
                        component=changed.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=None,
                        detail="cannot restore pre-rollback state: version unknown",
                    )
                )
                continue
            try:
                current = provenance_probe(changed)
                restored_step = _rollback_one(
                    changed,
                    before.version,
                    runner=runner,
                    provenance=current,
                )
                steps.append(restored_step)
                if restored_step.status is ApplyStatus.FAILED:
                    continue
                verified = provenance_probe(changed)
                if verified.version != before.version:
                    steps.append(
                        ApplyStep(
                            component=changed.ident,
                            status=ApplyStatus.FAILED,
                            from_version=verified.version,
                            to_version=before.version,
                            detail="pre-rollback restoration verification failed",
                        )
                    )
                elif changed.service_unit:
                    steps.append(
                        _restart_service(changed, runner=runner, dry_run=False)
                    )
            except Exception as exc:
                steps.append(
                    ApplyStep(
                        component=changed.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=before.version,
                        detail=f"pre-rollback restoration failed: {type(exc).__name__}",
                    )
                )

    for comp, pin, before in planned:
        if before is not None:
            try:
                current = provenance_probe(comp)
            except Exception as exc:
                steps.append(
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=pin.version,
                        detail=f"rollback fingerprint probe failed: {type(exc).__name__}",
                    )
                )
                restore_journal()
                return steps
            if current.fingerprint() != before.fingerprint():
                steps.append(
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=current.version,
                        to_version=pin.version,
                        detail="runtime changed after rollback planning",
                    )
                )
                restore_journal()
                return steps
        else:
            current = None
        step = _rollback_one(
            comp,
            pin.version,
            runner=runner,
            provenance=current,
        )
        steps.append(step)
        if step.status is ApplyStatus.FAILED:
            restore_journal()
            return steps
        if before is not None:
            journal.append((comp, before))
            try:
                restored = provenance_probe(comp)
            except Exception as exc:
                steps.append(
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=pin.version,
                        detail=f"rollback verification probe failed: {type(exc).__name__}",
                    )
                )
                restore_journal()
                return steps
            if restored.version != pin.version:
                steps.append(
                    ApplyStep(
                        component=comp.ident,
                        status=ApplyStatus.FAILED,
                        from_version=restored.version,
                        to_version=pin.version,
                        detail="rollback verification failed",
                    )
                )
                restore_journal()
                return steps
            if comp.service_unit:
                restart = _restart_service(comp, runner=runner, dry_run=False)
                steps.append(restart)
                if restart.status is ApplyStatus.FAILED:
                    restore_journal()
                    return steps
    return steps


# ---------------------------------------------------------------------------
# Interop gate — the local health check after applying upgrades
# ---------------------------------------------------------------------------


def _run_interop_gate(
    *,
    runner: Runner,
    installed: Installed,
    lock_path: Path,
    revision_probe: doctor_mod.RevisionProbe | None = None,
) -> tuple[bool, str]:
    """Run the local interop gate: ``doctor`` + ``lock --check``.

    The authoritative interop proof is the CI job (bootstrap-contract §5) that
    drives one work-item across both faces. On the home box, the local gate is
    ``doctor`` (aggregated health) + ``lock --check`` (version match) — a green
    local gate is necessary but not sufficient; the commit message should
    reference the CI interop run as the authoritative evidence.
    """
    report = doctor_mod.aggregate(
        installed=installed,
        runner=runner,
        lock_path=lock_path,
        revision_probe=revision_probe,
    )
    if not report.suite_ok:
        failed = [c.component for c in report.components if not c.ok]
        return False, f"doctor: suite not ok (failed: {', '.join(failed) or 'see report'})"

    if report.lock.matches is False:
        drift_summary = report.lock.note
        return False, f"lock drift detected: {drift_summary}"

    return True, "interop gate passed (doctor green, lock matches)"


# ---------------------------------------------------------------------------
# Public API — upgrade
# ---------------------------------------------------------------------------


def run_upgrade(
    *,
    component: str | None = None,
    check_only: bool = False,
    dry_run: bool = False,
    lock_path: Path = lock_mod.DEFAULT_LOCK_PATH,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    components: tuple[Component, ...] = COMPONENTS,
    interop_runner: Runner | None = None,
    interop_installed: Installed | None = None,
    provenance_probe: ProvenanceProbe = _default_provenance_probe,
    provider_probe: ProviderProbe = _default_provider_probe,
) -> UpgradeResult:
    """Reconcile drift or advance a healthy lock as one verified transaction.

    A drifted runtime is repaired *exactly* to the current lock and the lock is
    never rewritten.  Only a runtime already matching the lock may advance;
    that path resolves exact targets, gates against a candidate lock, and writes
    the candidate only after the gate passes.  The two intents are never mixed.
    """
    if check_only:
        report = check_advancements(
            component=component,
            runner=runner,
            installed=installed,
            provenance_probe=provenance_probe,
            components=components,
        )
        return UpgradeResult(
            ok=True,
            dry_run=False,
            check_only=True,
            component_filter=component,
            advancements=report.advancements,
            detail=report.note,
        )

    targets = components
    if component is not None:
        targets = tuple(c for c in components if c.ident == component)
        if not targets:
            return UpgradeResult(
                ok=False,
                dry_run=dry_run,
                check_only=False,
                component_filter=component,
                detail=f"unknown component: {component}",
            )

    try:
        current_lock = lock_mod.load_lock_file(lock_path)
    except ValueError as exc:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=f"cannot read current lock: {exc}",
        )
    if current_lock is None:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail="no SUITE.lock — run `agent-suite lock` to create one before upgrading",
        )

    try:
        estate_records = {comp.ident: provenance_probe(comp) for comp in components}
    except Exception as exc:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=f"runtime provenance probe failed: {type(exc).__name__}: {exc}",
        )
    records = {comp.ident: estate_records[comp.ident] for comp in targets}
    missing_pins = [comp.ident for comp in targets if comp.ident not in current_lock.components]
    if missing_pins:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=f"current lock has no pin for: {', '.join(missing_pins)}",
        )

    repair_plans = [
        _PlannedMutation(
            component=comp,
            before=records[comp.ident],
            target_version=current_lock.components[comp.ident].version,
            advances_lock=False,
        )
        for comp in targets
        if records[comp.ident].version
        != current_lock.components[comp.ident].version
    ]

    current_provider: lock_mod.ProviderExtension | None = None
    try:
        current_provider = provider_probe(runner=runner, installed=installed)
    except (KeyError, OSError, RuntimeError, ValueError) as exc:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=f"memory-provider provenance probe failed: {type(exc).__name__}",
        )
    estate_drift = lock_mod.check_drift(
        current_lock,
        current_quad=lock_mod.read_regista_quad(runner=runner, installed=installed),
        component_versions={
            ident: record.version for ident, record in estate_records.items()
        },
        component_revisions={
            comp.ident: (
                None
                if comp.locality is Locality.SHARED_SERVICE
                else estate_records[comp.ident].revision
            )
            for comp in components
        },
        current_provider_extension=current_provider,
    )
    repair_components = {plan.component.ident for plan in repair_plans}
    unrelated_drift = [
        drift
        for drift in estate_drift.drift
        if drift.component not in repair_components
    ]
    if unrelated_drift:
        first = unrelated_drift[0]
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=(
                "refused: estate has drift outside this exact repair plan: "
                f"{first.component}.{first.field} "
                f"({first.current} != {first.locked})"
            ),
        )

    plans = repair_plans
    intent = "repair"
    if not repair_plans:
        intent = "advance"

        def cached_probe(comp: Component) -> RuntimeProvenance:
            return records[comp.ident]

        advancement = check_advancements(
            component=component,
            runner=runner,
            installed=installed,
            provenance_probe=cast(ProvenanceProbe, cached_probe),
            components=components,
        )
        errors = [
            item
            for item in advancement.advancements
            if item.status
            in (
                AdvancementStatus.ERROR,
                AdvancementStatus.UNREACHABLE,
                AdvancementStatus.NOT_INSTALLED,
            )
        ]
        if errors:
            return UpgradeResult(
                ok=False,
                dry_run=dry_run,
                check_only=False,
                component_filter=component,
                detail=f"cannot build upgrade plan: {errors[0].detail}",
            )
        plans = [
            _PlannedMutation(
                component=next(c for c in targets if c.ident == item.component),
                before=records[item.component],
                target_version=str(item.target_version),
                advances_lock=True,
            )
            for item in advancement.advancements
            if item.status is AdvancementStatus.ADVANCEMENT_AVAILABLE
            and item.target_version is not None
        ]

    refusals = [
        _mutation_refusal(plan.before)
        for plan in plans
        if plan.component.upgrade_kind is UpgradeKind.PYTHON
        and _mutation_command(
            plan.before,
            f"{plan.before.distribution or plan.component.upgrade_package}"
            f"=={plan.target_version}",
        )
        is None
    ]
    if refusals:
        return UpgradeResult(
            ok=False,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail=refusals[0],
        )
    for plan in plans:
        service_owned, service_detail = _service_uses_runtime(
            plan.component, plan.before, runner=runner
        )
        if not service_owned:
            return UpgradeResult(
                ok=False,
                dry_run=dry_run,
                check_only=False,
                component_filter=component,
                detail=f"refused: {service_detail}",
            )

    if not plans:
        return UpgradeResult(
            ok=True,
            dry_run=dry_run,
            check_only=False,
            component_filter=component,
            detail="runtime matches SUITE.lock; no newer versions are available",
        )

    if dry_run:
        dry_steps: list[ApplyStep] = []
        for plan in plans:
            dry_steps.extend(
                _apply_one(
                    plan.component,
                    runner=runner,
                    dry_run=True,
                    provenance=plan.before,
                    target_version=plan.target_version,
                )
            )
        return UpgradeResult(
            ok=True,
            dry_run=True,
            check_only=False,
            component_filter=component,
            apply_steps=dry_steps,
            detail=f"dry-run: exact {intent} plan; no actions taken",
        )

    all_steps: list[ApplyStep] = []
    journal: list[_PlannedMutation] = []

    def rollback_journal(reason: str) -> UpgradeResult:
        rollback_failed = False
        for applied in reversed(journal):
            try:
                current = provenance_probe(applied.component)
            except Exception as exc:
                rollback_failed = True
                all_steps.append(
                    ApplyStep(
                        component=applied.component.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=applied.before.version,
                        detail=f"rollback provenance probe failed: {type(exc).__name__}",
                    )
                )
                continue
            if applied.before.version is None:
                rollback_step = ApplyStep(
                    component=applied.component.ident,
                    status=ApplyStatus.FAILED,
                    from_version=current.version,
                    to_version=None,
                    detail="cannot rollback: pre-upgrade version was unknown",
                )
            else:
                rollback_step = _rollback_one(
                    applied.component,
                    applied.before.version,
                    runner=runner,
                    provenance=current,
                )
            all_steps.append(rollback_step)
            if rollback_step.status is ApplyStatus.FAILED:
                rollback_failed = True
                continue
            try:
                restored = provenance_probe(applied.component)
            except Exception as exc:
                rollback_failed = True
                all_steps.append(
                    ApplyStep(
                        component=applied.component.ident,
                        status=ApplyStatus.FAILED,
                        from_version=None,
                        to_version=applied.before.version,
                        detail=f"rollback verification probe failed: {type(exc).__name__}",
                    )
                )
                continue
            if restored.version != applied.before.version:
                rollback_failed = True
                all_steps.append(
                    ApplyStep(
                        component=applied.component.ident,
                        status=ApplyStatus.FAILED,
                        from_version=restored.version,
                        to_version=applied.before.version,
                        detail="rollback verification failed",
                    )
                )
                continue
            if applied.component.service_unit:
                restart = _restart_service(
                    applied.component, runner=runner, dry_run=False
                )
                all_steps.append(restart)
                rollback_failed = rollback_failed or restart.status is ApplyStatus.FAILED
        suffix = " rollback incomplete" if rollback_failed else " rollback verified"
        return UpgradeResult(
            ok=False,
            dry_run=False,
            check_only=False,
            component_filter=component,
            apply_steps=all_steps,
            interop_passed=False,
            lock_written=False,
            rollback_performed=bool(journal),
            detail=f"{reason};{suffix}",
        )

    for plan in plans:
        try:
            current = provenance_probe(plan.component)
        except Exception as exc:
            return rollback_journal(
                f"pre-apply provenance probe failed for {plan.component.ident}: "
                f"{type(exc).__name__}"
            )
        if current.fingerprint() != plan.before.fingerprint():
            return rollback_journal(
                f"runtime changed after planning for {plan.component.ident}; refused mutation"
            )
        steps = _apply_one(
            plan.component,
            runner=runner,
            dry_run=False,
            provenance=current,
            target_version=plan.target_version,
        )
        all_steps.extend(steps)
        package_step = steps[0]
        if package_step.status is ApplyStatus.APPLIED:
            journal.append(plan)
        failed = [step for step in steps if step.status is ApplyStatus.FAILED]
        if failed:
            return rollback_journal(
                f"apply failed for {plan.component.ident}: {failed[0].detail}"
            )
        try:
            after = provenance_probe(plan.component)
        except Exception as exc:
            return rollback_journal(
                f"post-install provenance probe failed for {plan.component.ident}: "
                f"{type(exc).__name__}"
            )
        if after.version != plan.target_version:
            return rollback_journal(
                f"post-install verification failed for {plan.component.ident}: "
                f"expected {plan.target_version}, got {after.version or 'unknown'}"
            )
        records[plan.component.ident] = after
        estate_records[plan.component.ident] = after

    def runtime_revisions() -> dict[str, str | None]:
        return {
            comp.ident: (
                None
                if comp.locality is Locality.SHARED_SERVICE
                else (
                    records[comp.ident]
                    if comp.ident in records
                    else provenance_probe(comp)
                ).revision
            )
            for comp in components
        }

    gate_runner = interop_runner or runner
    gate_installed = interop_installed or installed
    gate_path = lock_path
    candidate_lock: lock_mod.SuiteLock | None = None
    temporary: tempfile.TemporaryDirectory[str] | None = None
    if intent == "advance":
        all_records = estate_records
        try:
            generated = lock_mod.generate_lock(
                component_versions={
                    ident: record.version for ident, record in all_records.items()
                },
                component_revisions={
                    comp.ident: (
                        None
                        if comp.locality is Locality.SHARED_SERVICE
                        else all_records[comp.ident].revision
                    )
                    for comp in components
                },
                runner=gate_runner,
                installed=gate_installed,
                components=components,
                release=current_lock.release,
            )
            candidate_lock = lock_mod.SuiteLock(
                release=generated.release,
                regista_quad=generated.regista_quad,
                components=generated.components,
                provider_extension=current_lock.provider_extension,
            )
            temporary = tempfile.TemporaryDirectory(prefix="agent-suite-upgrade-")
            gate_path = Path(temporary.name) / "SUITE.lock"
            lock_mod.write_lock_file(candidate_lock, gate_path)
        except Exception as exc:
            if temporary is not None:
                temporary.cleanup()
            return rollback_journal(
                f"candidate lock generation failed: {type(exc).__name__}: {exc}"
            )

    try:
        try:
            interop_passed, interop_detail = _run_interop_gate(
                runner=gate_runner,
                installed=gate_installed,
                lock_path=gate_path,
                revision_probe=runtime_revisions,
            )
        except Exception as exc:
            return rollback_journal(
                f"interop gate raised: {type(exc).__name__}: {exc}"
            )
    finally:
        if temporary is not None:
            temporary.cleanup()

    if not interop_passed:
        return rollback_journal(f"interop gate failed: {interop_detail}")

    lock_written = False
    if candidate_lock is not None:
        try:
            lock_mod.write_lock_file(candidate_lock, lock_path)
        except Exception as exc:
            return rollback_journal(
                f"final lock write failed: {type(exc).__name__}: {exc}"
            )
        lock_written = True
    return UpgradeResult(
        ok=True,
        dry_run=False,
        check_only=False,
        component_filter=component,
        apply_steps=all_steps,
        interop_passed=True,
        lock_written=lock_written,
        interop_evidence_ref=(
            "reference the authoritative CI interop run (bootstrap-contract §5)"
            if lock_written
            else "existing lock reconciled; no lock transition"
        ),
        detail=(
            interop_detail
            if lock_written
            else f"runtime reconciled to existing lock; {interop_detail}"
        ),
    )


# ---------------------------------------------------------------------------
# Public API — rollback to a prior committed lock
# ---------------------------------------------------------------------------


def _load_lock_from_git_ref(
    ref: str,
    *,
    lock_path: Path = lock_mod.DEFAULT_LOCK_PATH,
    runner: Runner = _default_runner,
) -> lock_mod.SuiteLock | None:
    """Load a SUITE.lock from a git ref via ``git show <ref>:SUITE.lock``.

    Returns ``None`` if the ref doesn't exist or the file isn't tracked at that
    ref. Raises ``ValueError`` if the file exists but is malformed (delegated
    to ``deserialize_lock``).
    """
    cmd: tuple[str, ...] = ("git", "show", f"{ref}:{lock_path.name}")
    try:
        result = runner(cmd)
    except FileNotFoundError:
        return None
    except subprocess.TimeoutExpired:
        return None
    except OSError:
        return None

    if result.returncode != 0:
        return None

    return lock_mod.deserialize_lock(result.stdout)


def run_rollback(
    to_ref: str,
    *,
    lock_path: Path = lock_mod.DEFAULT_LOCK_PATH,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    components: tuple[Component, ...] = COMPONENTS,
    provenance_probe: ProvenanceProbe = _default_provenance_probe,
) -> RollbackResult:
    """Roll back to a prior committed lock (``upgrade --to <lock-ref>``).

    A rollback restores each component to the version pinned in the target lock.
    It **refuses** to cross a schema-migration boundary: if the target lock's
    ``schema_version`` differs from the currently-deployed schema version, the
    command refuses rather than half-applies. Schema migrations are one-way;
    rolling back across one would leave the database in a state the old code
    can't read.

    What rollback **cannot** undo (documented for the operator):
    - **Schema migrations** — a forward schema migration is irreversible; this
      command refuses if one has occurred.
    - **Workflow versions** — if the canonical-workflow version changed, the
      old code may not understand events created under the new workflow. This
      is a warning, not a refusal (regista's compatibility rules decide).
    - **Data created after the target lock** — events, work items, and key
      registrations made after the target lock's point in time are not removed
      by a code-level rollback; they remain in the store.
    """
    try:
        target_lock = _load_lock_from_git_ref(to_ref, lock_path=lock_path, runner=runner)
    except ValueError as exc:
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            detail=f"target lock is malformed: {exc}",
        )

    if target_lock is None:
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            detail=f"no SUITE.lock found at git ref '{to_ref}'",
        )

    current_quad = lock_mod.read_regista_quad(runner=runner, installed=installed)

    current_schema = current_quad.schema_version if current_quad else None
    target_schema = target_lock.regista_quad.schema_version if target_lock.regista_quad else None

    if (
        current_schema is not None
        and target_schema is not None
        and current_schema != target_schema
    ):
        return RollbackResult(
            ok=False,
            status=RollbackStatus.REFUSED_MIGRATION_BOUNDARY,
            target_ref=to_ref,
            target_lock=target_lock,
            current_schema_version=current_schema,
            target_schema_version=target_schema,
            detail=(
                f"refused: schema migration boundary — current schema_version is "
                f"{current_schema}, target lock pins {target_schema}. "
                "Schema migrations are one-way; rolling back would leave the "
                "database in a state the old code cannot read. "
                "Restore from a backup taken before the migration instead."
            ),
        )

    if current_schema is None and target_schema is not None:
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            target_lock=target_lock,
            current_schema_version=None,
            target_schema_version=target_schema,
            detail=(
                "refused: cannot determine current schema_version (regista not "
                "installed or unreachable) — will not apply a rollback blind"
            ),
        )

    if (
        current_quad is not None
        and target_lock.regista_quad is not None
        and current_quad.canonical_workflow_version != target_lock.regista_quad.canonical_workflow_version
    ):
        pass

    prestate_pins: dict[str, lock_mod.ComponentPin] = {}
    try:
        for comp in components:
            if comp.ident not in target_lock.components:
                continue
            before = provenance_probe(comp)
            if before.version is None:
                return RollbackResult(
                    ok=False,
                    status=RollbackStatus.FAILED,
                    target_ref=to_ref,
                    target_lock=target_lock,
                    current_schema_version=current_schema,
                    target_schema_version=target_schema,
                    detail=f"rollback preflight could not capture {comp.ident} version",
                )
            prestate_pins[comp.ident] = lock_mod.ComponentPin(
                repo=comp.repo,
                version=before.version,
                revision=before.revision,
            )
    except Exception as exc:
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            target_lock=target_lock,
            current_schema_version=current_schema,
            target_schema_version=target_schema,
            detail=f"rollback preflight failed: {type(exc).__name__}: {exc}",
        )

    rollback_steps = _rollback_all(
        target_lock,
        runner=runner,
        components=components,
        provenance_probe=provenance_probe,
    )
    failed = [s for s in rollback_steps if s.status is ApplyStatus.FAILED]

    if failed:
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            target_lock=target_lock,
            current_schema_version=current_schema,
            target_schema_version=target_schema,
            detail=(
                f"rollback partially failed: {len(failed)} component(s) could not be "
                f"restored — {failed[0].component}: {failed[0].detail}. "
                "The store may be in a mixed state; investigate manually."
            ),
        )

    try:
        lock_mod.write_lock_file(target_lock, lock_path)
    except Exception as exc:
        prestate_lock = lock_mod.SuiteLock(
            release=target_lock.release,
            regista_quad=current_quad,
            components=prestate_pins,
            provider_extension=target_lock.provider_extension,
        )
        recovery_steps = _rollback_all(
            prestate_lock,
            runner=runner,
            components=components,
            provenance_probe=provenance_probe,
        )
        recovery_failed = any(
            step.status is ApplyStatus.FAILED for step in recovery_steps
        )
        return RollbackResult(
            ok=False,
            status=RollbackStatus.FAILED,
            target_ref=to_ref,
            target_lock=target_lock,
            current_schema_version=current_schema,
            target_schema_version=target_schema,
            detail=(
                f"target lock write failed: {type(exc).__name__}; "
                + (
                    "pre-rollback runtime restoration incomplete"
                    if recovery_failed
                    else "pre-rollback runtime restored"
                )
            ),
        )
    return RollbackResult(
        ok=True,
        status=RollbackStatus.APPLIED,
        target_ref=to_ref,
        target_lock=target_lock,
        current_schema_version=current_schema,
        target_schema_version=target_schema,
        detail=f"rolled back to lock at '{to_ref}'; {len(rollback_steps)} component(s) restored",
    )


class ForwardRecoveryStatus(Enum):
    RECOVERED = "recovered"
    PARTIALLY_RECOVERED = "partially_recovered"
    FAILED = "failed"
    NO_RECOVERY_NEEDED = "no_recovery_needed"


@dataclass
class ForwardRecoveryResult:
    ok: bool
    status: ForwardRecoveryStatus
    applied_steps: list[ApplyStep] = field(default_factory=list)
    interop_passed: bool = False
    lock_written: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "applied_steps": [s.to_dict() for s in self.applied_steps],
            "interop_passed": self.interop_passed,
            "lock_written": self.lock_written,
            "detail": self.detail,
        }


def run_forward_recovery(
    *,
    lock_path: Path = lock_mod.DEFAULT_LOCK_PATH,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    components: tuple[Component, ...] = COMPONENTS,
    interop_runner: Runner | None = None,
    interop_installed: Installed | None = None,
    provenance_probe: ProvenanceProbe = _default_provenance_probe,
) -> ForwardRecoveryResult:
    """Refuse the legacy forward-recovery path until it shares the transaction.

    When ``upgrade --to`` refuses because a schema migration boundary was
    crossed, the operator runs forward recovery to finish the remaining
    component upgrades, run the interop gate, and write the lock if green.

    The previous implementation bypassed runtime fingerprints and gated changed
    versions against the old lock, so it could not safely complete a genuine
    advancement. Keep the API as an explicit fail-closed compatibility surface;
    operators must reconcile to the current lock with ``upgrade`` or author and
    review a new candidate lock.

    Legacy flow (retired):
    1. Check advancements for every component (discover what still needs upgrade).
    2. Apply remaining upgrades.
    3. Run the interop gate (doctor).
    4. On green: regenerate and write the lock; report RECOVERED.
    5. On red: report PARTIALLY_RECOVERED with the specific failures.
    6. If no advancements needed: report NO_RECOVERY_NEEDED.
    """
    return ForwardRecoveryResult(
        ok=False,
        status=ForwardRecoveryStatus.FAILED,
        detail=(
            "forward recovery is retired until it uses the installation-aware "
            "transaction engine; run `agent-suite upgrade` to reconcile to the "
            "current lock, or author and review a new candidate lock"
        ),
    )

def format_forward_recovery_text(result: ForwardRecoveryResult) -> str:
    lines: list[str] = ["agent-suite upgrade --forward-recover"]
    lines.append("")
    for s in result.applied_steps:
        lines.append(f"  {s.component:<22} {s.status.value:<14} {s.detail}")
    lines.append("")
    lines.append(f"  interop gate: {'PASSED' if result.interop_passed else 'FAILED'}")
    lines.append(f"  lock written: {result.lock_written}")
    lines.append(f"  status: {result.status.value}")
    lines.append("")
    lines.append(f"forward-recovery: {'OK' if result.ok else 'NOT OK'}")
    if result.detail:
        lines.append(f"  {result.detail}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_advancement_text(report: AdvancementReport) -> str:
    """Human-readable summary for ``upgrade --check``."""
    lines: list[str] = ["agent-suite upgrade --check"]
    lines.append("")
    for a in report.advancements:
        current = a.current_version or "?"
        target = a.target_version or "?"
        arrow = f"  {a.component:<22} {current:<12} -> {target:<12} {a.status.value}"
        if a.detail:
            arrow += f"  ({a.detail})"
        lines.append(arrow)
    lines.append("")
    lines.append(report.note)
    return "\n".join(lines)


def format_upgrade_text(result: UpgradeResult) -> str:
    """Human-readable summary for ``upgrade``."""
    lines: list[str] = []
    if result.check_only:
        lines.append("agent-suite upgrade --check")
    elif result.dry_run:
        lines.append("agent-suite upgrade --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite upgrade")
    if result.component_filter:
        lines.append(f"  component: {result.component_filter}")
    lines.append("")
    for s in result.apply_steps:
        lines.append(f"  {s.component:<22} {s.status.value:<14} {s.detail}")
    if result.check_only:
        for item in result.advancements:
            current = item.current_version or "?"
            target = item.target_version or "?"
            lines.append(
                f"  {item.component:<22} {current:<12} -> {target:<12} "
                f"{item.status.value}"
            )
    lines.append("")
    if not result.check_only and not result.dry_run:
        lines.append(f"  interop gate: {'PASSED' if result.interop_passed else 'FAILED'}")
        lines.append(f"  lock written: {result.lock_written}")
        lines.append(f"  rollback performed: {result.rollback_performed}")
        if result.interop_evidence_ref:
            lines.append(f"  evidence: {result.interop_evidence_ref}")
    lines.append("")
    lines.append(f"upgrade: {'OK' if result.ok else 'NOT OK'}")
    if result.detail:
        lines.append(f"  {result.detail}")
    return "\n".join(lines)


def format_rollback_text(result: RollbackResult) -> str:
    """Human-readable summary for ``upgrade --to``."""
    lines: list[str] = [f"agent-suite upgrade --to {result.target_ref}"]
    lines.append("")
    lines.append(f"  status: {result.status.value}")
    if result.current_schema_version is not None and result.target_schema_version is not None:
        lines.append(
            f"  schema: current={result.current_schema_version}, target={result.target_schema_version}"
        )
    lines.append("")
    lines.append(f"rollback: {'OK' if result.ok else 'NOT OK'}")
    if result.detail:
        lines.append(f"  {result.detail}")
    return "\n".join(lines)
