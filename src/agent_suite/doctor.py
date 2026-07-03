"""The doctor umbrella — aggregate each component's health into one report.

Implements Plan 001 WI-1.1. `agent-suite doctor` shells each installed component's
`<tool> doctor --json` (the common shape regista Plan 025 WI-3.1 defines) and folds
them into the umbrella shape from `docs/bootstrap-contract.md` §3.

Honest-health rules (AGENTS.md): a component that isn't installed is `absent` (a
named state, not silence — and not a failure for an optional tier); a component
that's installed but unreachable or reports `ok:false` is a failure. The umbrella
is strictly read-only.

The component `<tool> doctor --json` contract is not yet implemented by any
component, so this module parses defensively: a missing/`ok:false`/non-JSON result
is a named status, never a traceback.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite import lock
from agent_suite.components import COMPONENTS, Component, Tier


class ComponentStatus(Enum):
    """The closed set of per-component health states.

    `assert_never` is used over this enum so a newly added status can't be silently
    unhandled in the aggregation or gating logic.
    """

    OK = "ok"  # installed; doctor green
    DEGRADED = "degraded"  # installed; ok but in a non-fatal degrade mode (e.g. coordinator-absent)
    ABSENT = "absent"  # not installed on this box
    UNREACHABLE = "unreachable"  # installed, but the doctor command could not be run/caught
    FAILED = "failed"  # installed; doctor exited non-zero, emitted no JSON, or reported ok:false


class Runner(Protocol):
    """Run a component's doctor command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches `shutil.which`)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


@dataclass
class ComponentReport:
    component: str
    tier: Tier
    status: ComponentStatus
    ok: bool = False
    version: str | None = None
    detail: str = ""
    regista: dict[str, object] | None = None
    checks: list[dict[str, object]] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "tier": self.tier.value,
            "status": self.status.value,
            "ok": self.ok,
            "version": self.version,
            "detail": self.detail,
            "regista": self.regista,
            "checks": self.checks,
        }


def _check_lock_drift(
    reports: list[ComponentReport],
    *,
    lock_path: Path = lock.DEFAULT_LOCK_PATH,
    version_runner: lock.VersionRunner = lock._default_runner,
    version_installed: lock.Installed = lock._default_installed,
) -> lock.LockDriftResult:
    """Compare installed component versions against SUITE.lock.

    Uses the regista quad from ``regista version --json`` (not the doctor
    output, which lacks the full quad) so the schema/workflow/envelope versions
    are checked too — not just the library version.

    A malformed lock file is a named state (``matches=False``), not a crash —
    the doctor is read-only and must never traceback.
    """
    try:
        existing = lock.load_lock_file(lock_path)
    except ValueError as exc:
        return lock.LockDriftResult(
            matches=False,
            note=f"SUITE.lock is unreadable: {exc}",
        )
    component_versions: dict[str, str | None] = {r.component: r.version for r in reports}
    current_quad = lock.read_regista_quad(runner=version_runner, installed=version_installed)
    return lock.check_drift(
        existing,
        current_quad=current_quad,
        component_versions=component_versions,
    )


@dataclass
class SuiteReport:
    suite_ok: bool
    components: list[ComponentReport]
    lock: lock.LockDriftResult = field(
        default_factory=lambda: lock.LockDriftResult(matches=None, note="")
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_ok": self.suite_ok,
            "components": [c.to_dict() for c in self.components],
            "lock": self.lock.to_dict(),
        }


def _check_one(
    comp: Component,
    *,
    installed: Installed,
    runner: Runner,
) -> ComponentReport:
    cli_name = comp.doctor_cmd[0]

    if not installed(cli_name):
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.ABSENT,
            ok=False,
            detail=f"{cli_name} not installed (tier: {comp.tier.value})",
        )

    try:
        result = runner(comp.doctor_cmd)
    except FileNotFoundError:
        # Race: was installed at the check, gone at the run. Treat as absent.
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.ABSENT,
            ok=False,
            detail=f"{cli_name} not found at run time",
        )
    except subprocess.TimeoutExpired:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.UNREACHABLE,
            ok=False,
            detail=f"{cli_name} doctor timed out",
        )
    except OSError as exc:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.UNREACHABLE,
            ok=False,
            detail=f"{cli_name} doctor could not run: {exc}",
        )

    if result.returncode != 0:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor exit {result.returncode}: {result.stderr.strip() or 'no stderr'}",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor emitted non-JSON stdout",
        )

    if not isinstance(data, dict):
        return ComponentReport(
            component=comp.ident,
            tier=comp.tier,
            status=ComponentStatus.FAILED,
            ok=False,
            detail=f"{cli_name} doctor emitted JSON but not a dict (got {type(data).__name__})",
        )

    ok = bool(data.get("ok", False))
    degraded = bool(data.get("degraded", False))
    if not ok:
        status = ComponentStatus.FAILED
    elif degraded:
        status = ComponentStatus.DEGRADED
    else:
        status = ComponentStatus.OK

    regista = data.get("regista")
    checks = data.get("checks", [])
    return ComponentReport(
        component=comp.ident,
        tier=comp.tier,
        status=status,
        ok=ok,
        version=data.get("version"),
        detail=data.get("detail", ""),
        regista=regista if isinstance(regista, dict) else None,
        checks=checks if isinstance(checks, list) else [],
    )


def _compute_suite_ok(reports: list[ComponentReport]) -> bool:
    # Any installed-but-broken component fails the suite (contract: installed but
    # unreachable is a failure). The `assert_never` in the default arm keeps the
    # status enum closed — a newly added status can't slip through ungated.
    for r in reports:
        match r.status:
            case ComponentStatus.UNREACHABLE | ComponentStatus.FAILED:
                return False
            case ComponentStatus.OK | ComponentStatus.DEGRADED | ComponentStatus.ABSENT:
                continue
            case other:
                assert_never(other)

    # Spine absent => no functioning suite.
    if any(r.tier is Tier.SPINE and r.status is ComponentStatus.ABSENT for r in reports):
        return False

    # Nothing deployed at all => not ok (don't smooth an empty box into "healthy").
    if all(r.status is ComponentStatus.ABSENT for r in reports):
        return False

    return True


def aggregate(
    *,
    installed: Installed = _default_installed,
    runner: Runner = _default_runner,
    components: tuple[Component, ...] = COMPONENTS,
    lock_path: Path | None = None,
    version_runner: lock.VersionRunner | None = None,
    version_installed: lock.Installed | None = None,
) -> SuiteReport:
    """Run each component's doctor and fold into one umbrella report.

    Both `installed` and `runner` are injectable so tests drive aggregation against
    stubbed component doctors with no real binaries on PATH (no live infra in CI).
    `lock_path`, `version_runner`, and `version_installed` control the lock-drift
    check (also injectable for the same reason).
    """
    reports = [_check_one(c, installed=installed, runner=runner) for c in components]
    lock_result = _check_lock_drift(
        reports,
        lock_path=lock_path if lock_path is not None else lock.DEFAULT_LOCK_PATH,
        version_runner=version_runner if version_runner is not None else lock._default_runner,
        version_installed=version_installed
        if version_installed is not None
        else lock._default_installed,
    )
    return SuiteReport(
        suite_ok=_compute_suite_ok(reports), components=reports, lock=lock_result
    )


def format_text(report: SuiteReport) -> str:
    """Human-readable summary for `doctor` without --json."""
    lines: list[str] = []
    for c in report.components:
        tag = f"[{c.tier.value.upper()}]"
        ver = f" v{c.version}" if c.version else ""
        detail = f"  {c.detail}" if c.detail else ""
        lines.append(f"  {c.component:<22} {tag:<10} {c.status.value:<11}{ver}{detail}")
    lines.append("")
    lines.append(lock.format_drift_text(report.lock))
    lines.append(f"suite: {'OK' if report.suite_ok else 'NOT OK'}")
    return "\n".join(lines)
