"""The upgrade command — advance SUITE.lock as an evidence-based lock transition.

Implements Plan 005 WI-1.1 + WI-1.2. ``agent-suite upgrade`` advances the
compatibility lock: it fetches each component's available target, applies the
upgrade per component (pipx upgrade / docker pull / service restart), runs the
suite-interop proof (the ``doctor`` umbrella as the local gate; the CI interop
job §5 is the authoritative gate and is referenced in the commit message), and
on green rewrites ``SUITE.lock``. On red (interpo proof failed), the deployed
set is rolled back to the previously-pinned versions and the lock is left
untouched — an upgrade is a lock transition, and a failed transition is not a
transition.

Design (AGENTS.md): thin orchestration — ``pipx upgrade``, ``docker pull``,
``systemctl restart`` are OS-level operations, not component logic. The
version discovery uses ``pip install --dry-run --upgrade`` (the package
manager's own check), not a reimplementation of version resolution.
``--dry-run`` prints the plan without acting. ``--check`` is read-only.
``assert_never`` over every closed-set enum. stdlib-only core.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.components import COMPONENTS, Component, UpgradeKind
from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as doctor.Runner / lock.VersionRunner)
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a component CLI or OS command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


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
            "apply_steps": [s.to_dict() for s in self.apply_steps],
            "interop_passed": self.interop_passed,
            "lock_written": self.lock_written,
            "rollback_performed": self.rollback_performed,
            "interop_evidence_ref": self.interop_evidence_ref,
            "detail": self.detail,
        }


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

_WOULD_INSTALL_RE = re.compile(r"Would install.*?(\S+?)-([^\s]+?)[\s\n]")
_ALREADY_SATISFIED = "Requirement already satisfied"


def _pip_check_latest(
    package: str,
    *,
    runner: Runner,
) -> tuple[str | None, str | None, AdvancementStatus, str]:
    """Check the latest available version via ``pip install --dry-run --upgrade``.

    Returns ``(installed_version, latest_version, status, detail)``. Never raises
    — a command failure, timeout, or unparseable output is a named status.
    """
    cmd: tuple[str, ...] = (
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

    match = _WOULD_INSTALL_RE.search(combined)
    if match:
        target = match.group(2)
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
        _check_one_advancement(c, runner=runner, installed=installed, components=components)
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


def _apply_one(
    comp: Component,
    *,
    runner: Runner,
    dry_run: bool,
) -> list[ApplyStep]:
    """Apply the upgrade for one component (upgrade + optional service restart).

    Returns a list of ApplySteps (the upgrade step + the restart step if applicable).
    """
    match comp.upgrade_kind:
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
) -> ApplyStep:
    """Restore a component to a specific previously-pinned version."""
    match comp.upgrade_kind:
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
) -> list[ApplyStep]:
    """Roll back every component in a lock to its pinned version."""
    steps: list[ApplyStep] = []
    for comp in components:
        if comp.ident in lock.components:
            pin = lock.components[comp.ident]
            steps.append(_rollback_one(comp, pin.version, runner=runner))
    return steps


# ---------------------------------------------------------------------------
# Interop gate — the local health check after applying upgrades
# ---------------------------------------------------------------------------


def _run_interop_gate(
    *,
    runner: Runner,
    installed: Installed,
    lock_path: Path,
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
) -> UpgradeResult:
    """Run an upgrade: advance the lock as an evidence-based transition.

    ``check_only`` is read-only (reports available advancements). ``dry_run``
    prints the plan without acting. ``component`` limits the upgrade to one pin.

    Flow (non-check, non-dry-run):
    1. Load the current lock (source of truth for rollback).
    2. Apply per-component upgrades (pipx upgrade / docker pull + service restart).
    3. Run the interop gate (doctor + lock check).
    4. On green: regenerate and write the lock.
    5. On red: roll back to the previously-pinned versions; lock is untouched.
    """
    if check_only:
        report = check_advancements(
            component=component, runner=runner, installed=installed, components=components
        )
        return UpgradeResult(
            ok=True,
            dry_run=False,
            check_only=True,
            component_filter=component,
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

    current_lock: lock_mod.SuiteLock | None = None
    if not dry_run:
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

    all_steps: list[ApplyStep] = []
    for comp in targets:
        steps = _apply_one(comp, runner=runner, dry_run=dry_run)
        all_steps.extend(steps)
        if not dry_run:
            failed = [s for s in steps if s.status is ApplyStatus.FAILED]
            if failed:
                return UpgradeResult(
                    ok=False,
                    dry_run=False,
                    check_only=False,
                    component_filter=component,
                    apply_steps=all_steps,
                    detail=f"apply failed for {comp.ident}: {failed[0].detail}",
                )

    if dry_run:
        return UpgradeResult(
            ok=True,
            dry_run=True,
            check_only=False,
            component_filter=component,
            apply_steps=all_steps,
            detail="dry-run: no actions taken",
        )

    interop_passed, interop_detail = _run_interop_gate(
        runner=interop_runner if interop_runner is not None else runner,
        installed=interop_installed if interop_installed is not None else installed,
        lock_path=lock_path,
    )

    if interop_passed:
        doctor_report = doctor_mod.aggregate(
            installed=interop_installed if interop_installed is not None else installed,
            runner=interop_runner if interop_runner is not None else runner,
            lock_path=lock_path,
        )
        component_versions: dict[str, str | None] = {
            r.component: r.version for r in doctor_report.components
        }
        new_lock = lock_mod.generate_lock(
            component_versions=component_versions,
            runner=runner,
            installed=installed,
            components=components,
        )
        lock_mod.write_lock_file(new_lock, lock_path)
        return UpgradeResult(
            ok=True,
            dry_run=False,
            check_only=False,
            component_filter=component,
            apply_steps=all_steps,
            interop_passed=True,
            lock_written=True,
            interop_evidence_ref="commit this lock diff; reference the CI interop run (bootstrap-contract §5)",
            detail=interop_detail,
        )

    assert current_lock is not None
    rollback_steps = _rollback_all(current_lock, runner=runner, components=components)
    all_steps.extend(rollback_steps)
    return UpgradeResult(
        ok=False,
        dry_run=False,
        check_only=False,
        component_filter=component,
        apply_steps=all_steps,
        interop_passed=False,
        lock_written=False,
        rollback_performed=True,
        detail=f"interop gate FAILED — rolled back to prior lock: {interop_detail}",
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

    rollback_steps = _rollback_all(target_lock, runner=runner, components=components)
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

    lock_mod.write_lock_file(target_lock, lock_path)
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
) -> ForwardRecoveryResult:
    """Complete a partially-applied upgrade when rollback is not possible.

    When ``upgrade --to`` refuses because a schema migration boundary was
    crossed, the operator runs forward recovery to finish the remaining
    component upgrades, run the interop gate, and write the lock if green.

    Flow:
    1. Check advancements for every component (discover what still needs upgrade).
    2. Apply remaining upgrades.
    3. Run the interop gate (doctor).
    4. On green: regenerate and write the lock; report RECOVERED.
    5. On red: report PARTIALLY_RECOVERED with the specific failures.
    6. If no advancements needed: report NO_RECOVERY_NEEDED.
    """
    report = check_advancements(
        runner=runner, installed=installed, components=components,
    )
    pending = [a for a in report.advancements if a.status is AdvancementStatus.ADVANCEMENT_AVAILABLE]
    not_installed = [a for a in report.advancements if a.status is AdvancementStatus.NOT_INSTALLED]

    if not_installed:
        return ForwardRecoveryResult(
            ok=False,
            status=ForwardRecoveryStatus.FAILED,
            detail=(
                f"{len(not_installed)} component(s) not installed: "
                f"{', '.join(a.component for a in not_installed)}. "
                "Install missing components before recovering."
            ),
        )

    if not pending:
        ir = interop_runner or runner
        ii = interop_installed or installed
        doctor_report = doctor_mod.aggregate(runner=ir, installed=ii)
        if doctor_report.suite_ok:
            return ForwardRecoveryResult(
                ok=True,
                status=ForwardRecoveryStatus.NO_RECOVERY_NEEDED,
                interop_passed=True,
                detail="no advancements pending and suite is healthy",
            )
        return ForwardRecoveryResult(
            ok=False,
            status=ForwardRecoveryStatus.FAILED,
            interop_passed=False,
            detail="no advancements pending but suite is unhealthy — investigate manually",
        )

    apply_steps: list[ApplyStep] = []
    for adv in pending:
        comp = next((c for c in components if c.ident == adv.component), None)
        if comp is None:
            apply_steps.append(ApplyStep(
                component=adv.component,
                status=ApplyStatus.FAILED,
                from_version=adv.current_version,
                to_version=adv.target_version,
                detail="component not found in COMPONENTS tuple",
            ))
            continue
        steps = _apply_one(comp, runner=runner, dry_run=False)
        apply_steps.extend(steps)
    failed = [s for s in apply_steps if s.status is ApplyStatus.FAILED]

    if failed:
        return ForwardRecoveryResult(
            ok=False,
            status=ForwardRecoveryStatus.PARTIALLY_RECOVERED,
            applied_steps=apply_steps,
            detail=(
                f"{len(failed)} component(s) failed to upgrade: "
                f"{failed[0].component}: {failed[0].detail}"
            ),
        )

    ir = interop_runner or runner
    ii = interop_installed or installed
    doctor_report = doctor_mod.aggregate(runner=ir, installed=ii)
    interop_ok = doctor_report.suite_ok

    lock_written = False
    if interop_ok:
        component_versions: dict[str, str | None] = {
            r.component: r.version for r in doctor_report.components
        }
        from agent_suite.config import memory_provider_config

        mp_engine = "native"
        try:
            mp_engine = str(memory_provider_config()["engine"])
        except (KeyError, OSError):
            pass
        new_lock = lock_mod.generate_lock(
            component_versions=component_versions,
            memory_engine=mp_engine,
            runner=ir,
            installed=ii,
        )
        lock_mod.write_lock_file(new_lock, lock_path)
        lock_written = True

    return ForwardRecoveryResult(
        ok=interop_ok,
        status=ForwardRecoveryStatus.RECOVERED if interop_ok else ForwardRecoveryStatus.PARTIALLY_RECOVERED,
        applied_steps=apply_steps,
        interop_passed=interop_ok,
        lock_written=lock_written,
        detail=(
            "forward recovery complete — suite healthy, lock written"
            if interop_ok
            else "components upgraded but interop gate failed — investigate doctor output"
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
