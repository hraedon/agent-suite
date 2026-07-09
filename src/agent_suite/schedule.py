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
"""

from __future__ import annotations

import platform
import shutil
import subprocess
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


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
    ),
)


@dataclass
class ScheduleResult:
    """The outcome of a schedule install/remove operation."""

    kind: ScheduleKind
    status: InstallStatus
    files_written: list[str] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "files_written": self.files_written,
            "detail": self.detail,
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


def _systemd_service(spec: ScheduleSpec) -> str:
    """Generate a systemd service unit file for a schedule."""
    return (
        f"[Unit]\n"
        f"Description={spec.description}\n"
        f"Wants=network-online.target\n"
        f"After=network-online.target postgresql.service\n"
        f"\n"
        f"[Service]\n"
        f"Type=oneshot\n"
        f"ExecStart={spec.command}\n"
        f"EnvironmentFile=-/etc/agent-suite/suite.env\n"
        f"User=root\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=multi-user.target\n"
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


def _windows_task_script(spec: ScheduleSpec) -> str:
    """Generate a PowerShell script that registers a Windows Scheduled Task."""
    return (
        f"# {spec.description}\n"
        f"# Generated by `agent-suite schedule install` — do not edit by hand.\n"
        f"# Re-run `agent-suite schedule install` to regenerate.\n"
        f"$action = New-ScheduledTaskAction -Execute '{spec.command}'\n"
        f"$trigger = New-ScheduledTaskTrigger -{spec.windows_trigger} -At 2am\n"
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
        f"Unregister-ScheduledTask -TaskName '{spec.name}' -Confirm:$false -ErrorAction SilentlyContinue\n"
    )


# ---------------------------------------------------------------------------
# File generation (dry-run friendly)
# ---------------------------------------------------------------------------


def generate_schedule_files(
    spec: ScheduleSpec,
    *,
    os_target: OSTarget,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
) -> list[tuple[Path, str]]:
    """Generate the files for one schedule on the given OS target.

    Returns a list of ``(path, content)`` pairs. Used by both ``--dry-run``
    (print) and the actual install (write).
    """
    match os_target:
        case OSTarget.SYSTEMD:
            service_path = unit_dir / f"{spec.name}.service"
            timer_path = unit_dir / f"{spec.name}.timer"
            return [
                (service_path, _systemd_service(spec)),
                (timer_path, _systemd_timer(spec)),
            ]
        case OSTarget.WINDOWS_TASK:
            script_dir = Path("C:/ProgramData/agent-suite/schedules")
            script_path = script_dir / f"{spec.name}.ps1"
            return [
                (script_path, _windows_task_script(spec)),
            ]
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def install_schedules(
    *,
    os_target: OSTarget | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    schedules: tuple[ScheduleSpec, ...] = SCHEDULES,
    unit_dir: Path = SYSTEMD_UNIT_DIR,
) -> ScheduleReport:
    """Install all scheduled operations.

    On systemd: writes ``.service`` + ``.timer`` files to ``unit_dir`` and runs
    ``systemctl daemon-reload`` + ``systemctl enable --now <timer>``.
    On Windows: writes PowerShell scripts to ``C:/ProgramData/agent-suite/schedules/``.

    ``dry_run`` prints the files that would be written without acting.
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
        files = generate_schedule_files(spec, os_target=target, unit_dir=unit_dir)

        if dry_run:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.INSTALLED,
                    files_written=[str(p) for p, _ in files],
                    detail="dry-run: files would be written (not acted)",
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
                    )
                )
                failed = True
                break

        if failed:
            continue

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
                        )
                    )
                    failed = True
                    break

        if not failed:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.INSTALLED,
                    files_written=written,
                    detail="installed",
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
                runner(("powershell", "-ExecutionPolicy", "Bypass", "-File", str(unregister_script)))
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
        for f in r.files_written:
            lines.append(f"    {f}")
    return "\n".join(lines)
