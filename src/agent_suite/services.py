"""Bring up the suite's long-running OS services on an artifact-only host.

Why this exists (WI-044)
------------------------
The Plan 020 Linux qualification found that **no wheel ships a systemd unit**,
that no ``dossier.service`` existed in any repo at all, and that
``docs/install-linux.md`` §7 nevertheless told operators to
``sudo systemctl enable --now dossier`` and claimed "the bootstrap installs
them". It also attributed unit installation to each component's
``install-harness``, which wires *agent harnesses* (Claude / OpenCode / Codex)
and has never touched an OS service. An artifact-only host could not install any
suite service, and the qualification had to hand-write a unit to make the
reboot-recovery checklist item testable.

The decision
------------
**Units are generated at install time by code that ships in the wheel; they are
not shipped as data files.** The one host-specific thing in a unit is where the
component's CLI lives, and systemd resolves an unqualified ``ExecStart`` only
against its own fixed search path (``/usr/local/sbin``, ``/usr/local/bin``,
``/usr/sbin``, ``/usr/bin``, …), never the invoking user's ``PATH``. A static
unit file therefore cannot be correct on both a system-scoped install and a
``~/.local/bin`` one — shipping the text is exactly what produced WI-045, where
all three suite timers failed ``203/EXEC``. A generator, by contrast, is code and
is in every wheel already, so there is no second copy to drift and no
``force-include`` to forget.

**Each component owns its own unit**, per the shape ``install-harness-contract.md``
already states: agent-suite invokes the component command, it does not define the
component's unit. So ``dossier`` gained ``dossier install-service`` (in the
dossier repo, generated the same way) and this module is the umbrella that runs
each such installer in tier order. Which components have OS services is knowledge
:mod:`agent_suite.components` already holds (``Component.service_unit``), so the
operator does not have to.

The suite's own scheduled work stays with ``agent-suite schedule install``: a
oneshot timer is a different lifecycle from a long-running face, and
:mod:`agent_suite.schedule` already generates and verifies those.

Verification, not observation
-----------------------------
A component installer reporting success is a claim; ``systemctl is-active`` is
evidence. This module asks for both, and reports ``FAILED`` when a unit is
present but not running — the standing review question is "does this check
verify, or merely observe presence?", and the answer for a service is that it has
to be up.

One ``is-active`` read is not enough. A ``Type=exec`` service is reported
``active`` as soon as its executable *starts*; a process that then dies is only
visible once ``Restart=`` takes effect. Measured on the qualification host:
installing dossier with an unassignable bind address reported ``active`` and
exit 0 while the service was already flapping. So the check settles, re-reads, and
requires ``NRestarts`` to still be zero.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol

from agent_suite.components import COMPONENTS, Component, Tier
from agent_suite.schedule import SystemScopeProbe, is_system_scoped_bin_dir


class Runner(Protocol):
    """Run an OS command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Which(Protocol):
    """Resolve an executable name to an absolute path, or ``None``."""

    def __call__(self, executable: str) -> str | None: ...


# Injectable so tests do not spend the settle window.
Sleeper = Callable[[float], None]


# Long enough for a service that dies on startup to have died; short enough not
# to stall an install. Shorter than a typical RestartSec so a pending restart
# still reads as `activating` rather than a fresh `active`.
SETTLE_SECONDS = 3.0


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)


def _default_which(executable: str) -> str | None:
    return shutil.which(executable)


class ServiceStatus(Enum):
    """The outcome of installing or removing one component's OS service."""

    INSTALLED = "installed"
    REMOVED = "removed"
    NO_SERVICE = "no_service"  # component is a CLI, nothing to install
    CLI_MISSING = "cli_missing"
    CLI_NON_SYSTEM_SCOPE = "cli_non_system_scope"  # resolved from a user-writable dir (WI-038)
    UNSUPPORTED = "unsupported"  # CLI has no install-service command
    FAILED = "failed"


_OK_STATUSES = (ServiceStatus.INSTALLED, ServiceStatus.REMOVED, ServiceStatus.NO_SERVICE)


@dataclass
class ComponentServiceResult:
    """What happened for one component, and who verified what.

    ``verified`` is what *this* process checked; ``component_verified`` is what
    the component's own installer claimed. Keeping them apart matters: copying a
    component's claim into our own evidence field would launder an observation
    into a verification, which is the defect class Plan 020 Lane J is about.
    """

    component: str
    unit: str
    status: ServiceStatus
    detail: str = ""
    command: tuple[str, ...] = ()
    verified: list[str] = field(default_factory=list)
    component_verified: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.status in _OK_STATUSES

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "unit": self.unit,
            "status": self.status.value,
            "detail": self.detail,
            "command": list(self.command),
            "verified": self.verified,
            "component_verified": self.component_verified,
        }


@dataclass
class ServicesReport:
    """The outcome across all components with an OS service."""

    results: list[ComponentServiceResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    def to_dict(self) -> dict[str, object]:
        return {"ok": self.ok, "results": [r.to_dict() for r in self.results]}


def service_components(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    max_tier: Tier | None = None,
) -> tuple[Component, ...]:
    """Components that declare a long-running OS service unit.

    Read from ``Component.service_unit`` so the list lives in one place. Passing
    ``max_tier=Tier.FACE`` restricts to the Tier 0-1 core, matching
    ``bootstrap --tier 0-1``.
    """
    order = (Tier.SPINE, Tier.FACE, Tier.PLUMBING)
    limit = order.index(max_tier) if max_tier is not None else len(order) - 1
    return tuple(
        c for c in components if c.service_unit and order.index(c.tier) <= limit
    )


def _cli_name(comp: Component) -> str:
    """The component's CLI — the first word of its doctor invocation."""
    return comp.doctor_cmd[0]


def _locate_cli(name: str, *, which: Which, bin_dir: Path | None) -> str | None:
    """Find a component CLI absolutely, honouring ``--bin-dir`` first.

    ``--bin-dir`` has to steer *discovery*, not only be forwarded: under ``sudo``
    the ``PATH`` is replaced by ``secure_path``, so a CLI installed outside it is
    invisible to ``shutil.which`` and the operator's whole reason for passing
    ``--bin-dir`` is that the default lookup cannot see it.
    """
    if bin_dir is not None:
        candidate = bin_dir / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return which(name)


def _read_state(unit: str, *, runner: Runner) -> tuple[str, str | None]:
    try:
        result = runner(("systemctl", "is-active", unit))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return "", f"could not read {unit} state: {type(exc).__name__}"
    return result.stdout.strip(), None


def _read_restarts(unit: str, *, runner: Runner) -> tuple[str, str | None]:
    try:
        result = runner(("systemctl", "show", unit, "--property=NRestarts", "--value"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return "", f"could not read {unit} restart count: {type(exc).__name__}"
    if result.returncode != 0:
        return "", f"systemctl show NRestarts for {unit} exited {result.returncode}"
    return result.stdout.strip(), None


def _verify_active(
    unit: str,
    *,
    runner: Runner,
    settle_seconds: float = SETTLE_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> tuple[list[str], str | None]:
    """The component's own report is a claim; systemd staying up is proof."""
    state, failure = _read_state(unit, runner=runner)
    if failure is not None:
        return [], failure
    if state != "active":
        return [], f"{unit} is {state or 'unknown'}, not active"

    sleeper(settle_seconds)

    state, failure = _read_state(unit, runner=runner)
    if failure is not None:
        return [], failure
    if state != "active":
        return [], (
            f"{unit} came up and then went {state or 'unknown'} within "
            f"{settle_seconds:g}s — it started but is not staying up"
        )

    restarts, failure = _read_restarts(unit, runner=runner)
    if failure is not None:
        return [], failure
    if restarts and restarts != "0":
        return [], (
            f"{unit} restarted {restarts} time(s) within {settle_seconds:g}s of install — "
            f"it is flapping, not running"
        )
    return ["service_active_after_settle"], None


def _run_component_installer(
    comp: Component,
    *,
    uninstall: bool,
    dry_run: bool,
    runner: Runner,
    which: Which,
    bin_dir: Path | None,
    extra_args: tuple[str, ...],
    settle_seconds: float,
    sleeper: Sleeper,
    scope_probe: SystemScopeProbe | None = None,
) -> ComponentServiceResult:
    cli = _cli_name(comp)
    resolved = _locate_cli(cli, which=which, bin_dir=bin_dir)
    if resolved is None:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.CLI_MISSING,
            detail=(
                f"{cli} is not on PATH — cannot install {comp.service_unit}. "
                f"Install the component on a system PATH (docs/install-linux.md §2) or "
                f"pass --bin-dir, and re-run. Note sudo replaces PATH with secure_path"
            ),
        )

    resolved_bin = Path(resolved).parent
    if not is_system_scoped_bin_dir(resolved_bin, probe=scope_probe):
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.CLI_NON_SYSTEM_SCOPE,
            detail=(
                f"{cli} resolved to {resolved}, a non-system bin directory "
                f"{resolved_bin} — refusing to anchor a root-run service on a "
                f"foreign / user-writable dir (WI-038). Install the component on a "
                f"system PATH (docs/install-linux.md §2) or a root-owned --bin-dir."
            ),
        )

    cmd: tuple[str, ...] = (resolved, "install-service", "--json", *extra_args)
    if uninstall:
        cmd = (*cmd, "--uninstall")
    if dry_run:
        cmd = (*cmd, "--dry-run")

    try:
        result = runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.FAILED,
            detail=f"{cli} install-service error: {type(exc).__name__}",
            command=cmd,
        )

    # argparse exits 2 for an unrecognised subcommand: the component predates the
    # contract. Say so plainly instead of reporting a generic failure — the
    # operator's next action is different.
    if result.returncode == 2:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.UNSUPPORTED,
            detail=(
                f"{cli} has no `install-service` command, so {comp.service_unit} cannot be "
                f"installed from an artifact. Upgrade {comp.ident} or install the unit from "
                f"that repo's deploy/ directory"
            ),
            command=cmd,
        )

    payload: dict[str, object] = {}
    if result.stdout.strip():
        try:
            parsed = json.loads(result.stdout)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}
    detail = str(payload.get("detail") or result.stderr.strip()[:200] or "")

    if result.returncode != 0:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.FAILED,
            detail=detail or f"{cli} install-service exited {result.returncode}",
            command=cmd,
        )

    raw_verified = payload.get("verified")
    claimed = (
        [v for v in raw_verified if isinstance(v, str)] if isinstance(raw_verified, list) else []
    )

    if uninstall:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.REMOVED,
            detail=detail or "removed",
            command=cmd,
            component_verified=claimed,
        )

    if dry_run:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.INSTALLED,
            detail=detail or "dry-run: would be installed (not acted)",
            command=cmd,
            component_verified=claimed,
        )

    # The component said it installed the unit. Ask systemd whether it is up.
    verified, failure = _verify_active(
        comp.service_unit, runner=runner, settle_seconds=settle_seconds, sleeper=sleeper
    )
    if failure is not None:
        return ComponentServiceResult(
            component=comp.ident,
            unit=comp.service_unit,
            status=ServiceStatus.FAILED,
            detail=f"{cli} reported success but {failure}",
            command=cmd,
            verified=verified,
            component_verified=claimed,
        )

    return ComponentServiceResult(
        component=comp.ident,
        unit=comp.service_unit,
        status=ServiceStatus.INSTALLED,
        detail=detail or "installed and verified",
        command=cmd,
        verified=verified,
        component_verified=claimed,
    )


def install_component_services(
    *,
    components: tuple[Component, ...] = COMPONENTS,
    max_tier: Tier | None = None,
    uninstall: bool = False,
    dry_run: bool = False,
    runner: Runner | None = None,
    which: Which | None = None,
    bin_dir: Path | None = None,
    settle_seconds: float = SETTLE_SECONDS,
    sleeper: Sleeper = time.sleep,
    system_scope_probe: SystemScopeProbe | None = None,
) -> ServicesReport:
    """Run each component's own ``install-service`` and verify the unit is up.

    ``bin_dir`` is passed through to the component installers so an operator whose
    CLIs live somewhere non-standard can state it once. ``runner``/``which``
    default to the real implementations, resolved here rather than bound as
    default arguments so a test can substitute the module attributes. A resolved
    CLI whose bin directory is not system-scoped is refused (WI-038), agreeing
    with ``schedule install`` via the shared :func:`is_system_scoped_bin_dir`;
    ``system_scope_probe`` overrides the default ownership probe for tests.
    """
    runner = runner if runner is not None else _default_runner
    which = which if which is not None else _default_which
    extra_args: tuple[str, ...] = ("--bin-dir", str(bin_dir)) if bin_dir else ()
    results = [
        _run_component_installer(
            comp,
            uninstall=uninstall,
            dry_run=dry_run,
            runner=runner,
            which=which,
            bin_dir=bin_dir,
            extra_args=extra_args,
            settle_seconds=settle_seconds,
            sleeper=sleeper,
            scope_probe=system_scope_probe,
        )
        for comp in service_components(components, max_tier=max_tier)
    ]
    return ServicesReport(results=results)


def format_services_report(report: ServicesReport, action: str) -> str:
    """Human-readable summary for ``agent-suite install-services``."""
    lines = [f"agent-suite {action}", ""]
    if not report.results:
        lines.append("  no component declares an OS service unit")
        return "\n".join(lines)
    for r in report.results:
        lines.append(f"  {r.component:<24} {r.unit:<16} {r.status.value:<12} {r.detail}")
        if r.verified:
            lines.append(f"    verified here: {', '.join(r.verified)}")
        if r.component_verified:
            lines.append(f"    {r.component} reports: {', '.join(r.component_verified)}")
        if r.command:
            lines.append(f"    ran: {shlex.join(r.command)}")
    lines.append("")
    lines.append(f"install-services: {'OK' if report.ok else 'FAILED'}")
    return "\n".join(lines)
