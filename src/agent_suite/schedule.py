"""Schedule suite operations via the OS scheduler — not a daemon.

Implements Plan 005 WI-2.1 (scheduled backup + verify-restore) and WI-3.1
(scheduled doctor + alerting). Per the plan's principle: "Use the OS scheduler,
not a daemon." This module generates the systemd timer/unit files (Linux) and
Windows Scheduled Task scripts (Windows) that run the suite's own commands on a
cadence. It does not run a long-lived process.

The generated units call ``agent-suite`` subcommands — they are thin wrappers
around the existing CLI, not new logic. An operator installs them with
``agent-suite schedule install`` and removes them with ``agent-suite schedule
remove``. The schedule definitions are declarative and idempotent: re-running
``install`` produces the same files.

Design (AGENTS.md): the generated files contain **no work-domain identifiers**
— DSNs, hosts, and project slugs come from ``suite.env`` at run time, never
baked into the unit files. ``assert_never`` over the closed-set enum.
stdlib-only core.

``ExecStart`` is an absolute path, resolved at install time (WI-045)
-------------------------------------------------------------------
These units used to be generated with a bare command name
(``ExecStart=cairn integrity``). systemd *does* resolve an unqualified
``ExecStart`` since v239, but only against its own **fixed** search path
(``/usr/local/sbin``, ``/usr/local/bin``, ``/usr/sbin``, ``/usr/bin``, …) — it
never consults the invoking user's ``PATH``. On any host whose component CLIs
live under ``~/.local/bin`` (a ``uv tool`` / ``pip install --user`` layout) every
unit therefore failed ``203/EXEC``, which means the weekly chain-integrity timer
never fired anywhere it was installed. Two review rounds refuted the concern with
"systemd ≥239 resolves bare names against its fixed path": true about systemd,
and the wrong conclusion, because ``~/.local/bin`` is not on that path.

A wheel cannot ship a unit file that is correct under both a system-scoped
install (``/usr/local/bin``) and a per-user one (``~/.local/bin``) — the path is
a property of the host, not of the release. So the unit text is **generated** at
install time from the location the installing process can actually see, and
``install`` refuses loudly rather than writing a unit whose ``ExecStart`` does not
exist. The copies under ``deploy/`` are reference renderings against
``REFERENCE_BIN_DIR``; they are documentation, not the installed artifact.

The deployment-time verification is in :func:`_verify_installed_unit`. Each
check answers a different question, because the interesting one is not
"did we write a file":

* the resolved executable is absolute, exists, and is executable — asked
  *before* anything is written;
* systemd's own parse of ``ExecStart`` names that executable — asked after
  ``daemon-reload``, so a malformed line cannot pass;
* the timer is ``active`` — asked after ``enable --now``, so an armed timer is
  proven rather than assumed.

Note that a timer arms perfectly well in front of a service whose ``ExecStart``
does not exist: ``enable --now`` succeeded on every affected host. The timer
check alone would not have caught WI-045, which is why all three run.
"""

from __future__ import annotations

import os
import platform
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

# ---------------------------------------------------------------------------
# Injectable interfaces
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run an OS command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)


class Which(Protocol):
    """Resolve an executable name to an absolute path, or ``None``."""

    def __call__(self, executable: str) -> str | None: ...


def _default_which(executable: str) -> str | None:
    return shutil.which(executable)


# ---------------------------------------------------------------------------
# Closed-set enums
# ---------------------------------------------------------------------------


class ScheduleKind(Enum):
    """The closed set of scheduled operations (Plan 005).

    ``assert_never`` is used over this enum so a newly added schedule can't be
    silently unhandled in the generation or install logic.
    """

    BACKUP_VERIFY = "backup-verify"  # WI-2.1: nightly pg_dump + weekly verify-restore
    DOCTOR_ALERT = "doctor-alert"  # WI-3.1: periodic doctor + red-routing
    CHAIN_INTEGRITY = "chain-integrity"  # cairn WI-030: scheduled full replay


class OSTarget(Enum):
    """The OS scheduler target.

    ``assert_never`` is used over this enum so a newly added OS can't be
    silently unhandled.
    """

    SYSTEMD = "systemd"  # Linux with systemd
    WINDOWS_TASK = "windows-task"  # Windows Scheduled Task


class InstallStatus(Enum):
    """The outcome of installing or removing a schedule."""

    INSTALLED = "installed"
    ALREADY_INSTALLED = "already_installed"
    REMOVED = "removed"
    NOT_INSTALLED = "not_installed"
    UNSUPPORTED_OS = "unsupported_os"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScheduleSpec:
    """Declarative spec for one scheduled operation."""

    kind: ScheduleKind
    name: str  # unit/task name (e.g. "agent-suite-backup")
    description: str
    on_calendar: str  # systemd OnCalendar expression (e.g. "daily", "weekly")
    command: str  # the agent-suite command to run
    windows_trigger: str  # Windows task trigger (e.g. "DAILY", "WEEKLY")
    # Unit-level Environment= defaults, rendered before EnvironmentFile so the
    # operator's suite.env still overrides them (systemd file-beats-unit).
    environment: tuple[str, ...] = ()


SCHEDULES: tuple[ScheduleSpec, ...] = (
    ScheduleSpec(
        kind=ScheduleKind.BACKUP_VERIFY,
        name="agent-suite-backup",
        description="Nightly pg_dump of the suite Postgres store + weekly verify-restore",
        on_calendar="daily",
        command="agent-suite backup --verify-restore",
        windows_trigger="DAILY",
    ),
    ScheduleSpec(
        kind=ScheduleKind.DOCTOR_ALERT,
        name="agent-suite-doctor-alert",
        description="Periodic doctor health check + alert routing on state change",
        on_calendar="hourly",
        command="agent-suite alert-check",
        windows_trigger="DAILY",
        # Same pin as CHAIN_INTEGRITY: this unit's doctor subprocess is the
        # automated READER of the verdict — without the pin, an install whose
        # suite.env predates the variable has the writer and the hourly
        # reader split-brained and the escalation loop reads never_run.
        environment=("CAIRN_INTEGRITY_DIR=/var/lib/agent-suite/cairn",),
    ),
    # Weekly cadence under a 192h staleness window (set in suite.env — the
    # window must exceed the cadence with margin, or Persistent=true catch-up
    # and RandomizedDelaySec produce transient stale warnings on a healthy
    # estate). The verdict dir is pinned to a shared system path: the timer
    # runs as root while doctors run as humans, and cairn's per-user default
    # would leave every human-run doctor reading an empty state home
    # ("never_run" forever). suite.env can still override. Failures close the
    # loop through DOCTOR_ALERT once a first verdict/attempt marker exists —
    # deployment runs `cairn integrity` once at install (see
    # docs/operating-the-suite.md) so the loop is closed from day one.
    ScheduleSpec(
        kind=ScheduleKind.CHAIN_INTEGRITY,
        name="agent-suite-chain-integrity",
        description="Weekly full cairn chain replay; records the verdict doctor reports",
        on_calendar="weekly",
        command="cairn integrity",
        windows_trigger="WEEKLY",
        environment=("CAIRN_INTEGRITY_DIR=/var/lib/agent-suite/cairn",),
    ),
)


@dataclass
class ScheduleResult:
    """The outcome of a schedule install/remove operation.

    ``exec_start`` records the absolute command the unit was written with, and
    ``verified`` names the checks that actually passed. An empty ``verified`` on
    an ``INSTALLED`` result would mean "a file exists", which is what WI-045
    reported for a year.
    """

    kind: ScheduleKind
    status: InstallStatus
    files_written: list[str] = field(default_factory=list)
    detail: str = ""
    exec_start: str = ""
    verified: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "files_written": self.files_written,
            "detail": self.detail,
            "exec_start": self.exec_start,
            "verified": self.verified,
        }


@dataclass
class ScheduleReport:
    """The outcome of installing or removing all schedules."""

    results: list[ScheduleResult] = field(default_factory=list)
    os_target: OSTarget | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "os_target": self.os_target.value if self.os_target else None,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# OS detection
# ---------------------------------------------------------------------------


def detect_os_target() -> OSTarget | None:
    """Detect the OS scheduler target. Returns ``None`` if unsupported."""
    if platform.system() == "Windows":
        return OSTarget.WINDOWS_TASK
    if shutil.which("systemctl") is not None:
        return OSTarget.SYSTEMD
    return None


# ---------------------------------------------------------------------------
# systemd unit generation
# ---------------------------------------------------------------------------

SYSTEMD_UNIT_DIR = Path("/etc/systemd/system")

# The install prefix the reference copies under deploy/ are rendered against.
# Chosen because it is both what docs/install-linux.md §2 prescribes (pipx or a
# venv at /opt with the CLI linked system-wide) and one of the directories on
# systemd's own fixed ExecStart search path — so a reference copy installed
# verbatim on a system-scoped host works. It is a documented default, not a
# guess about the host: `schedule install` always substitutes the location it
# actually resolved.
REFERENCE_BIN_DIR = Path("/usr/local/bin")


@dataclass(frozen=True)
class ResolvedCommand:
    """A schedule command split into an absolute executable and its arguments."""

    exec_path: str
    arguments: str = ""

    @property
    def exec_start(self) -> str:
        """The ``ExecStart=`` / ``-Execute`` value: absolute, then arguments."""
        return f"{self.exec_path} {self.arguments}".rstrip()


def _split(command: str) -> tuple[str, str]:
    words = shlex.split(command)
    return words[0], shlex.join(words[1:])


def reference_command(
    spec: ScheduleSpec, *, os_target: OSTarget = OSTarget.SYSTEMD
) -> ResolvedCommand:
    """Render *spec*'s command for the ``deploy/`` reference copies.

    systemd gets :data:`REFERENCE_BIN_DIR`, so even an unresolved rendering is
    absolute and cannot reintroduce the WI-045 bare ``ExecStart``. Windows gets
    the bare program name: ``pip install agent-suite`` puts the console scripts
    in whichever ``Scripts`` directory the interpreter owns, there is no
    canonical prefix to reference, and unlike systemd the Task Scheduler does
    resolve a task's program against the system PATH. ``schedule install``
    substitutes the resolved absolute path on both.
    """
    name, arguments = _split(spec.command)
    match os_target:
        case OSTarget.SYSTEMD:
            return ResolvedCommand(str(REFERENCE_BIN_DIR / name), arguments)
        case OSTarget.WINDOWS_TASK:
            return ResolvedCommand(name, arguments)
        case other:
            assert_never(other)


def _is_executable_file(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def default_search_dirs() -> tuple[Path, ...]:
    """Where to look for a component CLI before falling back to ``PATH``.

    The directory the *installing process's own* interpreter lives in — for a
    pipx / venv / ``uv tool`` install that is the same ``bin/`` as its console
    scripts. The process performing the install knows where its own artifact is,
    and the unit should invoke that one.
    """
    return (Path(sys.executable).parent,) if sys.executable else ()


def resolve_command(
    command: str,
    *,
    which: Which = _default_which,
    search_dirs: tuple[Path, ...] | None = None,
) -> ResolvedCommand | None:
    """Resolve *command*'s executable to an absolute path, or ``None``.

    ``search_dirs`` is tried in order, then the invoking process's ``PATH``;
    ``None`` means :func:`default_search_dirs`. An explicit empty tuple searches
    ``PATH`` only.

    Deliberately **not** consulted: ``$SUDO_USER``'s ``~/.local/bin``. Making a
    root-run unit execute out of a user-writable directory is a
    privilege-escalation shape, and agent-suite WI-038 decided per-box component
    CLIs install system-scoped. When a per-user install leaves a command
    unresolvable the correct outcome is a refusal naming it, not a widened
    search — hence ``None`` rather than a bare fallback.
    """
    name, arguments = _split(command)

    candidate = Path(name)
    if candidate.is_absolute():
        return ResolvedCommand(str(candidate), arguments)

    dirs = default_search_dirs() if search_dirs is None else search_dirs
    for directory in dirs:
        entry = directory / name
        if _is_executable_file(entry):
            return ResolvedCommand(str(entry), arguments)

    found = which(name)
    if found:
        return ResolvedCommand(str(Path(found)), arguments)
    return None


def _systemd_service(spec: ScheduleSpec, *, resolved: ResolvedCommand | None = None) -> str:
    """Generate a systemd service unit file for a schedule.

    ``resolved`` is the install-time resolution of ``spec.command``; without one
    the documented :data:`REFERENCE_BIN_DIR` rendering is used. Either way the
    ``ExecStart`` is absolute — systemd never searches the invoking user's PATH
    (WI-045).
    """
    command = (resolved or reference_command(spec)).exec_start
    return (
        f"[Unit]\n"
        f"Description={spec.description}\n"
        f"Wants=network-online.target\n"
        f"After=network-online.target postgresql.service\n"
        f"\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"ExecStart={command}\n"
        + "".join(f"Environment={e}\n" for e in spec.environment)
        + "EnvironmentFile=-/etc/agent-suite/suite.env\n"
        "User=root\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _systemd_timer(spec: ScheduleSpec) -> str:
    """Generate a systemd timer unit file for a schedule."""
    return (
        f"[Unit]\n"
        f"Description={spec.description} (timer)\n"
        f"\n"
        f"[Timer]\n"
        f"OnCalendar={spec.on_calendar}\n"
        f"Persistent=true\n"
        f"RandomizedDelaySec=300\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )


def _windows_trigger_expr(trigger: str) -> str:
    """PowerShell trigger switches for a spec's windows_trigger.

    The Weekly parameter set makes ``-DaysOfWeek`` mandatory — a bare
    ``-Weekly`` dies non-interactively with a missing-parameter prompt.
    """
    if trigger.upper() == "WEEKLY":
        return "-Weekly -DaysOfWeek Sunday"
    return f"-{trigger.capitalize()}"


def _windows_task_script(spec: ScheduleSpec, *, resolved: ResolvedCommand | None = None) -> str:
    """Generate a PowerShell script that registers a Windows Scheduled Task.

    ``New-ScheduledTaskAction -Execute`` takes the *program*; arguments belong in
    ``-Argument``. The same install-time resolution as the systemd path is used,
    so the task action names a real executable rather than a bare word.
    """
    command = resolved or reference_command(spec, os_target=OSTarget.WINDOWS_TASK)
    argument = f" -Argument '{command.arguments}'" if command.arguments else ""
    return (
        f"# {spec.description}\n"
        f"# Generated by `agent-suite schedule install` — do not edit by hand.\n"
        f"# Re-run `agent-suite schedule install` to regenerate.\n"
        f"$action = New-ScheduledTaskAction -Execute '{command.exec_path}'{argument}\n"
        f"$trigger = New-ScheduledTaskTrigger "
        f"{_windows_trigger_expr(spec.windows_trigger)} -At 2am\n"
        f"$settings = New-ScheduledTaskSettingsSet `\n"
        f"  -StartWhenAvailable `\n"
        f"  -DontStopOnIdleEnd `\n"
        f"  -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)\n"
        f"Register-ScheduledTask `\n"
        f"  -TaskName '{spec.name}' `\n"
        f"  -Action $action `\n"
        f"  -Trigger $trigger `\n"
        f"  -Settings $settings `\n"
        f"  -RunLevel Highest `\n"
        f"  -Force\n"
    )


def _windows_unregister_script(spec: ScheduleSpec) -> str:
    """Generate a PowerShell script that unregisters a Windows Scheduled Task."""
    return (
        f"# Remove the '{spec.name}' scheduled task.\n"
        f"Unregister-ScheduledTask -TaskName '{spec.name}' "
        f"-Confirm:$false -ErrorAction SilentlyContinue\n"
    )


# ---------------------------------------------------------------------------
# File generation (dry-run friendly)
# ---------------------------------------------------------------------------


def generate_schedule_files(
    spec: ScheduleSpec,
    *,
    os_target: OSTarget,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
    resolved: ResolvedCommand | None = None,
) -> list[tuple[Path, str]]:
    """Generate the files for one schedule on the given OS target.

    Returns a list of ``(path, content)`` pairs. Used by both ``--dry-run``
    (print) and the actual install (write). ``resolved`` is the install-time
    resolution of ``spec.command``; omitting it yields the ``deploy/`` reference
    rendering.
    """
    match os_target:
        case OSTarget.SYSTEMD:
            service_path = unit_dir / f"{spec.name}.service"
            timer_path = unit_dir / f"{spec.name}.timer"
            return [
                (service_path, _systemd_service(spec, resolved=resolved)),
                (timer_path, _systemd_timer(spec)),
            ]
        case OSTarget.WINDOWS_TASK:
            script_dir = Path("C:/ProgramData/agent-suite/schedules")
            script_path = script_dir / f"{spec.name}.ps1"
            return [
                (script_path, _windows_task_script(spec, resolved=resolved)),
            ]
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Install-time verification
# ---------------------------------------------------------------------------

# systemd renders ExecStart as `{ path=/usr/bin/x ; argv[]=... }` for
# `systemctl show -p ExecStart`. Same extraction upgrade.py uses.
_EXEC_PATH_RE = re.compile(r"(?:^|[;{\s])path=([^\s;}]+)")


def _extract_exec_path(raw: str) -> str | None:
    match = _EXEC_PATH_RE.search(raw)
    if match:
        return match.group(1)
    try:
        words = shlex.split(raw)
    except ValueError:
        return None
    return words[0] if words else None


def check_exec_start_runnable(resolved: ResolvedCommand) -> str | None:
    """Return a failure reason, or ``None`` when the executable is runnable.

    The pre-write gate. systemd resolves an unqualified ``ExecStart`` only
    against its own fixed search path, so a name that is merely *findable by this
    process* is not enough — it has to be absolute, and it has to be there.
    """
    path = Path(resolved.exec_path)
    if not path.is_absolute():
        return (
            f"ExecStart is not absolute: {resolved.exec_path!r}. systemd resolves bare "
            f"names only against its own fixed path (/usr/local/sbin, /usr/local/bin, "
            f"/usr/sbin, /usr/bin), never the invoking user's PATH"
        )
    if not path.exists():
        return f"ExecStart does not exist: {resolved.exec_path}"
    if not _is_executable_file(path):
        return f"ExecStart is not an executable file: {resolved.exec_path}"
    return None


def _verify_installed_unit(
    spec: ScheduleSpec,
    resolved: ResolvedCommand,
    *,
    runner: Runner,
) -> tuple[list[str], str | None]:
    """Verify systemd agrees the unit is startable and its timer is armed.

    Returns ``(checks_passed, failure_reason)``. Two independent questions:

    * does *systemd's own parse* of ``ExecStart`` name a real executable —
      catching a malformed line that our own string never would; and
    * is the timer ``active`` after ``enable --now``.

    The second is not sufficient alone: a timer arms happily in front of a
    service whose ``ExecStart`` does not exist, which is exactly why WI-045
    survived every install.
    """
    passed: list[str] = []

    try:
        shown = runner((
            "systemctl", "show", f"{spec.name}.service", "--property=ExecStart", "--value",
        ))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return passed, f"could not read back ExecStart from systemd: {type(exc).__name__}"
    if shown.returncode != 0:
        return passed, f"systemctl show exited {shown.returncode}"
    systemd_path = _extract_exec_path(shown.stdout.strip())
    if systemd_path is None:
        return passed, "systemd reports no ExecStart for the installed unit"
    if Path(systemd_path) != Path(resolved.exec_path):
        return passed, (
            f"systemd parsed ExecStart as {systemd_path!r}, not the resolved "
            f"{resolved.exec_path!r}"
        )
    reason = check_exec_start_runnable(ResolvedCommand(systemd_path))
    if reason is not None:
        return passed, f"as parsed by systemd, {reason}"
    passed.append("systemd_execstart_runnable")

    try:
        active = runner(("systemctl", "is-active", f"{spec.name}.timer"))
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return passed, f"could not read timer state: {type(exc).__name__}"
    state = active.stdout.strip()
    if state != "active":
        return passed, f"timer {spec.name}.timer is {state or 'unknown'}, not active"
    passed.append("timer_active")

    return passed, None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_UNRESOLVED_HINT = (
    "install the component CLIs on a system PATH (docs/install-linux.md §2) or "
    "pass --bin-dir; systemd will not search the invoking user's PATH"
)


def install_schedules(
    *,
    os_target: OSTarget | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    which: Which = _default_which,
    search_dirs: tuple[Path, ...] | None = None,
    schedules: tuple[ScheduleSpec, ...] = SCHEDULES,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
) -> ScheduleReport:
    """Install all scheduled operations.

    On systemd: resolves each command to an absolute executable, writes
    ``.service`` + ``.timer`` files to ``unit_dir``, runs ``systemctl
    daemon-reload`` + ``systemctl enable --now <timer>``, and then **verifies**
    that systemd's parse of ``ExecStart`` names a runnable executable and that the
    timer is armed. A unit that cannot be verified is reported ``FAILED`` — this
    used to report ``installed`` on the strength of having written a file, and
    the chain-integrity timer was dead on every host for exactly that reason
    (WI-045).

    On systemd an unresolvable command is fatal and nothing is written: a unit
    with a bare ``ExecStart`` is worse than no unit, because it reports success
    and then fails only when the timer fires. On Windows the Task Scheduler does
    resolve a task's program against the system PATH, so an unresolved command
    degrades to the bare name and is recorded as such rather than refused.

    ``dry_run`` resolves and verifies the executable — so it is a real preflight —
    and prints the files that would be written without acting.
    """
    target = os_target or detect_os_target()
    if target is None:
        return ScheduleReport(
            os_target=None,
            results=[
                ScheduleResult(
                    kind=s.kind,
                    status=InstallStatus.UNSUPPORTED_OS,
                    detail="no supported OS scheduler detected (need systemd or Windows)",
                )
                for s in schedules
            ],
        )

    results: list[ScheduleResult] = []
    for spec in schedules:
        resolved = resolve_command(spec.command, which=which, search_dirs=search_dirs)

        if resolved is None:
            if target is OSTarget.SYSTEMD:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        detail=(
                            f"cannot resolve {shlex.split(spec.command)[0]!r} to an absolute "
                            f"path — refusing to write a unit that would fail 203/EXEC. "
                            f"{_UNRESOLVED_HINT}"
                        ),
                    )
                )
                continue
            resolved = reference_command(spec, os_target=target)

        # Pre-write gate: absolute, present, executable.
        reason = check_exec_start_runnable(resolved)
        if reason is not None and target is OSTarget.SYSTEMD:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.FAILED,
                    detail=f"{reason}. {_UNRESOLVED_HINT}",
                    exec_start=resolved.exec_start,
                )
            )
            continue
        pre_write_checks = [] if reason is not None else ["exec_start_runnable"]

        files = generate_schedule_files(
            spec, os_target=target, unit_dir=unit_dir, resolved=resolved
        )

        if dry_run:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.INSTALLED,
                    files_written=[str(p) for p, _ in files],
                    detail="dry-run: files would be written (not acted)",
                    exec_start=resolved.exec_start,
                    verified=pre_write_checks,
                )
            )
            continue

        written: list[str] = []
        failed = False
        for path, content in files:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
                written.append(str(path))
            except OSError as exc:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=written,
                        detail=f"failed to write {path}: {exc}",
                        exec_start=resolved.exec_start,
                        verified=pre_write_checks,
                    )
                )
                failed = True
                break

        if failed:
            continue

        verified = list(pre_write_checks)
        if target is OSTarget.SYSTEMD:
            reload_cmd: tuple[str, ...] = ("systemctl", "daemon-reload")
            enable_cmd: tuple[str, ...] = (
                "systemctl", "enable", "--now", f"{spec.name}.timer",
            )
            for cmd in (reload_cmd, enable_cmd):
                try:
                    result = runner(cmd)
                    if result.returncode != 0:
                        results.append(
                            ScheduleResult(
                                kind=spec.kind,
                                status=InstallStatus.FAILED,
                                files_written=written,
                                detail=f"systemctl failed: {result.stderr.strip()[:200]}",
                                exec_start=resolved.exec_start,
                                verified=verified,
                            )
                        )
                        failed = True
                        break
                except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                    results.append(
                        ScheduleResult(
                            kind=spec.kind,
                            status=InstallStatus.FAILED,
                            files_written=written,
                            detail=f"systemctl error: {exc}",
                            exec_start=resolved.exec_start,
                            verified=verified,
                        )
                    )
                    failed = True
                    break

            if failed:
                continue

            post_checks, verify_failure = _verify_installed_unit(
                spec, resolved, runner=runner
            )
            verified.extend(post_checks)
            if verify_failure is not None:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=written,
                        detail=f"unit written but not verified: {verify_failure}",
                        exec_start=resolved.exec_start,
                        verified=verified,
                    )
                )
                continue

        results.append(
            ScheduleResult(
                kind=spec.kind,
                status=InstallStatus.INSTALLED,
                files_written=written,
                detail="installed and verified" if verified else "installed",
                exec_start=resolved.exec_start,
                verified=verified,
            )
        )

    return ScheduleReport(results=results, os_target=target)


def remove_schedules(
    *,
    os_target: OSTarget | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    schedules: tuple[ScheduleSpec, ...] = SCHEDULES,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
) -> ScheduleReport:
    """Remove all scheduled operations (idempotent — missing files are not an error)."""
    target = os_target or detect_os_target()
    if target is None:
        return ScheduleReport(
            os_target=None,
            results=[
                ScheduleResult(
                    kind=s.kind,
                    status=InstallStatus.UNSUPPORTED_OS,
                    detail="no supported OS scheduler detected",
                )
                for s in schedules
            ],
        )

    results: list[ScheduleResult] = []
    for spec in schedules:
        if dry_run:
            files = generate_schedule_files(spec, os_target=target, unit_dir=unit_dir)
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.REMOVED,
                    files_written=[str(p) for p, _ in files],
                    detail="dry-run: files would be removed",
                )
            )
            continue

        if target is OSTarget.SYSTEMD:
            disable_cmd: tuple[str, ...] = (
                "systemctl", "disable", "--now", f"{spec.name}.timer",
            )
            try:
                runner(disable_cmd)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
                pass

            for suffix in (".service", ".timer"):
                path = unit_dir / f"{spec.name}{suffix}"
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.REMOVED,
                    detail="removed",
                )
            )
        elif target is OSTarget.WINDOWS_TASK:
            script_dir = Path("C:/ProgramData/agent-suite/schedules")
            unregister_script = script_dir / f"unregister-{spec.name}.ps1"
            try:
                unregister_script.parent.mkdir(parents=True, exist_ok=True)
                unregister_script.write_text(
                    _windows_unregister_script(spec), encoding="utf-8"
                )
                runner((
                    "powershell", "-ExecutionPolicy", "Bypass",
                    "-File", str(unregister_script),
                ))
            except OSError:
                pass

            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.REMOVED,
                    detail="removed",
                )
            )
        else:
            assert_never(target)

    if target is OSTarget.SYSTEMD:
        try:
            runner(("systemctl", "daemon-reload"))
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            pass

    return ScheduleReport(results=results, os_target=target)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_schedule_report(report: ScheduleReport, action: str) -> str:
    """Human-readable summary for ``schedule install/remove``."""
    lines: list[str] = [f"agent-suite schedule {action}"]
    if report.os_target:
        lines.append(f"  OS: {report.os_target.value}")
    lines.append("")
    for r in report.results:
        lines.append(f"  {r.kind.value:<16} {r.status.value:<16} {r.detail}")
        if r.exec_start:
            lines.append(f"    ExecStart={r.exec_start}")
        if r.verified:
            lines.append(f"    verified: {', '.join(r.verified)}")
        for f in r.files_written:
            lines.append(f"    {f}")
    return "\n".join(lines)
