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

import json
import os
import platform
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.config import (
    SCHEDULE_BACKUP_DIR_ENV,
    SCHEDULE_VERIFY_RESTORE_DSN_ENV,
    _parse_env_file,
    same_postgres_database,
    system_suite_env_path,
)

# ---------------------------------------------------------------------------
# Injectable interfaces
# ---------------------------------------------------------------------------


_DEFAULT_RUNNER_TIMEOUT_SECONDS = 30.0

# Windows PowerShell 5.1 and the ScheduledTasks CIM provider can take longer
# than the shared timeout to cold-start. Keep the larger budget scoped to the
# two mutating Task Scheduler calls (WI-071 B2).
POWERSHELL_TASK_TIMEOUT_SECONDS = 240.0


class Runner(Protocol):
    """Run an OS command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


def _default_runner(
    cmd: tuple[str, ...], *, timeout: float = _DEFAULT_RUNNER_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, check=False
    )


def _run_powershell_task(
    runner: Runner, cmd: tuple[str, ...]
) -> subprocess.CompletedProcess[str]:
    """Run a Task Scheduler mutation without changing the Runner contract."""
    if runner is _default_runner:
        return _default_runner(cmd, timeout=POWERSHELL_TASK_TIMEOUT_SECONDS)
    return runner(cmd)


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

    BACKUP_VERIFY = "backup-verify"  # WI-2.1: nightly pg_dump
    RESTORE_VERIFY = "restore-verify"  # WI-2.1: weekly scratch restore + verification
    DOCTOR_ALERT = "doctor-alert"  # WI-3.1: periodic doctor + red-routing
    CHAIN_INTEGRITY = "chain-integrity"  # cairn WI-030: scheduled full replay
    INVARIANT_PROBES = "invariant-probes"


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


class ContextScope(Enum):
    """The closed set of invoking-context scopes (WI-038 box vs actor).

    ``assert_never`` is used over this enum so a newly added scope can't be
    silently unhandled in the scope-construction dispatch. ``BOX`` is the
    machine/host environment the scheduled unit runs in; ``ACTOR`` is the
    process that installed the schedule.
    """

    BOX = "box"
    ACTOR = "actor"


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
    windows_trigger: str  # Windows task trigger (e.g. "DAILY", "WEEKLY", "HOURLY")
    # Unit-level Environment= defaults, rendered before EnvironmentFile so the
    # operator's suite.env still overrides them (systemd file-beats-unit).
    environment: tuple[str, ...] = ()
    # The restore is deliberately later than the nightly dump on the weekly
    # day, so the two jobs cannot race over the shared latest-dump path.
    windows_time: str = "2am"
    systemd_time: str | None = None  # explicit HH:MM:SS on the weekly day
    windows_repetition_minutes: int | None = None
    required_env: tuple[str, ...] = ()
    dedicated_dsn_env: str | None = None
    randomized_delay_seconds: int = 300


SCHEDULES: tuple[ScheduleSpec, ...] = (
    ScheduleSpec(
        kind=ScheduleKind.BACKUP_VERIFY,
        name="agent-suite-backup",
        description="Nightly pg_dump of the suite Postgres store",
        on_calendar="daily",
        command=f"agent-suite backup --dir-env {SCHEDULE_BACKUP_DIR_ENV}",
        windows_trigger="DAILY",
        required_env=(SCHEDULE_BACKUP_DIR_ENV,),
    ),
    ScheduleSpec(
        kind=ScheduleKind.RESTORE_VERIFY,
        name="agent-suite-restore-verify",
        description="Weekly restore of the latest dump into scratch + verify-restore",
        on_calendar="weekly",
        command=(
            f"agent-suite restore --dir-env {SCHEDULE_BACKUP_DIR_ENV} "
            f"--dsn-env {SCHEDULE_VERIFY_RESTORE_DSN_ENV}"
        ),
        windows_trigger="WEEKLY",
        windows_time="4am",
        systemd_time="04:00:00",
        required_env=(SCHEDULE_BACKUP_DIR_ENV, SCHEDULE_VERIFY_RESTORE_DSN_ENV),
        dedicated_dsn_env=SCHEDULE_VERIFY_RESTORE_DSN_ENV,
    ),
    ScheduleSpec(
        kind=ScheduleKind.DOCTOR_ALERT,
        name="agent-suite-doctor-alert",
        description="Periodic doctor health check + alert routing on state change",
        on_calendar="hourly",
        command="agent-suite alert-check",
        windows_trigger="HOURLY",
        windows_repetition_minutes=60,
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
    ScheduleSpec(
        kind=ScheduleKind.INVARIANT_PROBES,
        name="agent-suite-invariant-probes",
        description="Recurring evidentiary invariant measurements",
        on_calendar="*:0/5",
        command="agent-suite invariant-probes --json",
        windows_trigger="HOURLY",
        windows_repetition_minutes=5,
        randomized_delay_seconds=30,
    ),
)


@dataclass(frozen=True)
class ScopeContext:
    """One side of the box-vs-actor split (WI-038).

    Both sides carry the same shape so the split is a real comparison. The
    defect WI-038 records is a root-run unit resolving a different estate than
    the operator that installed it — the unit pins *only* the system PATH and
    refuses an actor that resolved the CLI from a non-system (user-writable /
    foreign) bin directory, so the box's root-run estate and the actor's agree.
    An operator reading a result can tell a root/cron run (actor system-scoped;
    box system-scoped) from an operator run that tried to anchor a per-user bin
    dir.

    Each field is a *measured* value, not a hardcoded tautology: ``system_scoped``
    is computed by the scope probe (:class:`SystemScopeProbe`), ``uid``/``euid``
    are read from the process, and ``path_provenance`` / ``config_sources``
    record how PATH was resolved and which config the scope reads. Carrying
    these on the doctor result (WI-038) is what makes a scheduled red
    triageable from doctor output — the box (machine/host) context vs the actor
    (invoking user) context.
    """

    scope: ContextScope
    bin_dir: str
    system_scoped: bool
    uid: int | None = None
    euid: int | None = None
    path_provenance: str = ""
    config_sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "scope": self.scope.value,
            "bin_dir": self.bin_dir,
            "system_scoped": self.system_scoped,
            "uid": self.uid,
            "euid": self.euid,
            "path_provenance": self.path_provenance,
            "config_sources": list(self.config_sources),
        }


@dataclass
class InvokingContext:
    """HOW a schedule install was invoked, split into the box and the actor.

    Surfaced on every :class:`ScheduleResult` (WI-038) so an operator can tell a
    root/cron run from an operator run and distinguish the box's estate (the
    machine the scheduled unit runs in) from the actor's (who installed it).
    """

    actor: ScopeContext
    box: ScopeContext

    def to_dict(self) -> dict[str, object]:
        return {
            "actor": self.actor.to_dict(),
            "box": self.box.to_dict(),
        }


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
    invoking_context: InvokingContext | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "status": self.status.value,
            "files_written": self.files_written,
            "detail": self.detail,
            "exec_start": self.exec_start,
            "verified": self.verified,
            "invoking_context": (
                self.invoking_context.to_dict() if self.invoking_context else None
            ),
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

# The system PATH a generated unit pins — and *only* this. systemd runs the
# unit as root with a stripped PATH, so without an explicit pin the doctor that
# ``alert-check`` shells out to would resolve component CLIs against a different
# set of binaries than the operator — a different estate (WI-038). The pin is
# the standard system directories and nothing else: the previous WI-038 approach
# prepended the directory the installer resolved ``ExecStart`` from, which can
# hide a tampered / user-writable / foreign bin dir under a root-run unit. The
# unit instead pins only the system PATH and the install *refuses* a resolved
# executable whose bin directory is not one of these (see
# :func:`check_actor_system_scoped`). It renders as a unit-level default
# *before* ``EnvironmentFile`` so the operator's ``suite.env`` can still
# override it.
_SYSTEMD_FALLBACK_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

SYSTEM_PATH: str = _SYSTEMD_FALLBACK_PATH
"""The ``PATH`` a generated systemd unit runs with.

Always POSIX ``:``-joined ``/`` paths regardless of host OS — systemd is
Linux-only, so the unit PATH is a fixed POSIX literal. Windows-native path
handling (``USERPROFILE`` scope checks, Scheduled Task resolution) is a
separate concern and never reuses this constant (the two must not be conflated,
or a Windows host produces backslash-joined ``\\usr\\local\\sbin`` against the
unit's forward-slash literal)."""

SUITE_ENV_PATH = Path("/etc/agent-suite/suite.env")
"""The ``EnvironmentFile`` the generated units load — the box's config source."""

# The trusted system bin directories — the closed set the scope probe treats as
# system-scoped by explicit trust (the systemd fixed search path). Ownership /
# writability is the *primary* signal (a root-owned ``/opt/agent-suite/bin`` is
# system-scoped without being on this list); this set is an explicit allowlist
# the deployment — and the tests — can extend (WI-038).
SYSTEM_BIN_DIRS: tuple[Path, ...] = tuple(
    Path(entry) for entry in _SYSTEMD_FALLBACK_PATH.split(":")
)


def _unit_system_path_environment() -> str:
    """The ``PATH`` a generated unit runs with: the system directories only (WI-038).

    Deliberately independent of where the installer resolved ``ExecStart``: the
    unit must not search a foreign bin dir under root, so the actor's resolution
    is gated by :func:`check_actor_system_scoped` rather than merged into PATH.
    Always :data:`SYSTEM_PATH` (POSIX), never re-derived from host-flavored
    :class:`pathlib.Path` objects.
    """
    return f"PATH={SYSTEM_PATH}"


class SystemScopeProbe(Protocol):
    """Classify a bin directory as system-scoped (WI-038).

    ``True`` when the directory is not writable by an unprivileged user — the
    property that makes it safe to anchor a root-run scheduled unit on it. The
    default (:func:`_default_system_scope_probe`) measures ownership and mode
    bits on the real filesystem; tests inject a stub.
    """

    def __call__(self, bin_dir: Path) -> bool: ...


def _resolved(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def _is_system_owned(bin_dir: Path) -> bool:
    """Whether *bin_dir* is owned by the system and not user-writable (WI-038).

    POSIX: the directory exists, is owned by root (uid 0), and is neither
    group- nor other-writable. Windows: the directory is outside the user
    profile (the Task Scheduler resolves a task's program against the system
    PATH, so an all-users / machine location is system-scoped while a per-user
    profile / ``%%LOCALAPPDATA%%`` dir is the user-writable anchor WI-038
    refuses). A non-existent directory is not system-scoped.
    """
    if sys.platform == "win32":
        profile = _resolved(Path(os.environ.get("USERPROFILE") or Path.home()))
        try:
            return not bin_dir.is_relative_to(profile)
        except (OSError, ValueError):
            return False
    try:
        st = bin_dir.stat()
    except OSError:
        return False
    if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        return False
    return st.st_uid == 0


def _default_system_scope_probe(bin_dir: Path) -> bool:
    """System-scoped = an unprivileged user cannot write to *bin_dir* (WI-038).

    This is the predicate that decides whether an actor's resolved bin dir may
    anchor a root-run unit. It tests **ownership / writability**, not PATH
    membership: a root-owned ``/opt/agent-suite/bin`` is accepted (the layout
    ``docs/install-linux.md`` §2/§7 prescribes), while ``~/.local/bin`` and
    uv-tool user dirs (owned by the operator) are refused. :data:`SYSTEM_BIN_DIRS`
    is consulted first as an explicit trust set so the documented systemd search
    path — and the test fixtures that patch it — are accepted regardless of host
    filesystem ownership.
    """
    target = _resolved(bin_dir)
    if any(target == _resolved(d) for d in SYSTEM_BIN_DIRS):
        return True
    return _is_system_owned(target)


def is_system_scoped_bin_dir(
    bin_dir: Path, *, probe: SystemScopeProbe | None = None
) -> bool:
    """Whether *bin_dir* is system-scoped, delegating to *probe* (WI-038).

    Shared by ``schedule install`` and ``install-services`` so the two commands
    agree about the same directory. ``probe`` defaults to the ownership /
    writability measurement (:func:`_default_system_scope_probe`).
    """
    return (probe or _default_system_scope_probe)(bin_dir)


def _current_uid() -> int | None:
    """The invoking process's real uid (POSIX), or ``None`` (no uid on Windows)."""
    if sys.platform == "win32":
        return None
    return os.getuid()


def _current_euid() -> int | None:
    """The invoking process's effective uid (POSIX), or ``None`` on Windows."""
    if sys.platform == "win32":
        return None
    return os.geteuid()


def _system_unit_uid() -> int | None:
    """The uid the generated unit runs as (``User=root``), resolved from the name.

    Measured (resolved via the password database) rather than hardcoded, so the
    box's identity is a real lookup. ``None`` on Windows (no uid concept).
    """
    if sys.platform == "win32":
        return None
    try:
        import pwd

        return pwd.getpwnam("root").pw_uid
    except KeyError:
        return 0


def _box_system_scoped() -> bool:
    """Measured: are the directories the unit pins actually system-owned here?

    The box is the scheduled unit's runtime (root, the pinned system PATH); this
    checks the real filesystem state of those directories rather than asserting
    the result — so the box side carries a measured value, not a tautology. On
    Windows the unit concept does not apply (Task Scheduler runs ``-RunLevel
    Highest``), reported system-scoped.
    """
    if sys.platform == "win32":
        return True
    return all(_is_system_owned(Path(entry)) for entry in SYSTEM_PATH.split(":"))


def _scope_context(
    scope: ContextScope,
    *,
    bin_dir: Path,
    system_scoped: bool,
    uid: int | None,
    euid: int | None,
    path_provenance: str,
    config_sources: tuple[str, ...],
) -> ScopeContext:
    """Build one side of the box-vs-actor invoking context (WI-038).

    ``assert_never`` over :class:`ContextScope` keeps the closed set exhaustive.
    ``system_scoped`` is a *measured* value the caller computed (the actor runs
    the scope probe; the box runs :func:`_box_system_scoped`) — never hardcoded
    here, so the box side is a genuine measurement, not a tautology.
    """
    match scope:
        case ContextScope.BOX | ContextScope.ACTOR:
            return ScopeContext(
                scope=scope,
                bin_dir=str(bin_dir),
                system_scoped=system_scoped,
                uid=uid,
                euid=euid,
                path_provenance=path_provenance,
                config_sources=config_sources,
            )
        case other:
            assert_never(other)


def build_invoking_context(
    *,
    actor_bin_dir: Path,
    probe: SystemScopeProbe | None = None,
    actor_uid: int | None = None,
    actor_euid: int | None = None,
    path_env: str | None = None,
    actor_config_sources: tuple[str, ...] = (),
) -> InvokingContext:
    """The measured box-vs-actor invoking context (WI-038).

    The **actor** is the process invoking the install / doctor: its bin dir,
    uid/euid, PATH, and config sources. The **box** is the machine / host the
    scheduled unit runs in: root, the pinned system PATH, and the suite
    ``EnvironmentFile``. Both sides are measured — the actor's ``system_scoped``
    runs the scope probe, the box's runs :func:`_box_system_scoped`, and ``uid``
    is read from the process / resolved from the unit's ``User=root`` — so an
    operator reading the result can tell a root/cron run (actor system-scoped;
    box system-scoped) from an operator run that resolved the CLI from a
    per-user bin dir. Shared by ``schedule install`` and the doctor so the two
    report the same shape.
    """
    actor_probe = probe if probe is not None else _default_system_scope_probe
    return InvokingContext(
        actor=_scope_context(
            ContextScope.ACTOR,
            bin_dir=actor_bin_dir,
            system_scoped=actor_probe(actor_bin_dir),
            uid=actor_uid if actor_uid is not None else _current_uid(),
            euid=actor_euid if actor_euid is not None else _current_euid(),
            path_provenance=(
                path_env if path_env is not None else os.environ.get("PATH", "")
            ),
            config_sources=actor_config_sources,
        ),
        box=_scope_context(
            ContextScope.BOX,
            bin_dir=REFERENCE_BIN_DIR,
            system_scoped=_box_system_scoped(),
            uid=_system_unit_uid(),
            euid=None,
            path_provenance=f"systemd-unit:{SYSTEM_PATH}",
            config_sources=(str(SUITE_ENV_PATH),),
        ),
    )


def invoking_context_for(
    resolved: ResolvedCommand,
    *,
    probe: SystemScopeProbe | None = None,
    actor_uid: int | None = None,
    actor_euid: int | None = None,
    path_env: str | None = None,
    actor_config_sources: tuple[str, ...] = (),
) -> InvokingContext:
    """The box-vs-actor context for a resolved schedule command (WI-038).

    Thin wrapper over :func:`build_invoking_context` using the resolved
    command's bin dir as the actor anchor. When the actor is not system-scoped
    the install is refused by :func:`check_actor_system_scoped`.
    """
    return build_invoking_context(
        actor_bin_dir=Path(resolved.exec_path).parent,
        probe=probe,
        actor_uid=actor_uid,
        actor_euid=actor_euid,
        path_env=path_env,
        actor_config_sources=actor_config_sources,
    )



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
            # as_posix: the systemd rendering is a POSIX artifact whatever the
            # host; str() of a WindowsPath would backslash the ExecStart.
            return ResolvedCommand((REFERENCE_BIN_DIR / name).as_posix(), arguments)
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
    (WI-045). The unit also pins an explicit ``PATH`` of *only* the standard
    system directories so a root-run unit resolves the same system-scoped estate
    as the operator (WI-038); it does **not** prepend the directory the
    installer resolved ``ExecStart`` from — that can hide a tampered / foreign
    bin dir under root, so a non-system actor bin dir is refused at install time
    (:func:`check_actor_system_scoped`) instead of merged into the PATH. The pin
    renders before ``EnvironmentFile`` so ``suite.env`` can still override it.
    """
    effective = resolved or reference_command(spec)
    command = effective.exec_start
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
        + f"Environment={_unit_system_path_environment()}\n"
        + "EnvironmentFile=-/etc/agent-suite/suite.env\n"
        "User=root\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _systemd_timer(spec: ScheduleSpec) -> str:
    """Generate a systemd timer unit file for a schedule."""
    on_calendar = (
        f"Mon *-*-* {spec.systemd_time}" if spec.systemd_time else spec.on_calendar
    )
    return (
        f"[Unit]\n"
        f"Description={spec.description} (timer)\n"
        f"\n"
        f"[Timer]\n"
        f"OnCalendar={on_calendar}\n"
        f"Persistent=true\n"
        f"RandomizedDelaySec={spec.randomized_delay_seconds}\n"
        f"\n"
        f"[Install]\n"
        f"WantedBy=timers.target\n"
    )


def _windows_trigger_expr(
    trigger: str, *, repetition_minutes: int | None = None
) -> str:
    """PowerShell trigger switches for a spec's windows_trigger.

    The Weekly parameter set makes ``-DaysOfWeek`` mandatory — a bare
    ``-Weekly`` dies non-interactively with a missing-parameter prompt.  An
    hourly schedule uses Task Scheduler's once-plus-repetition parameter set;
    ``New-ScheduledTaskTrigger`` has no ``-Hourly`` parameter set at all, so an
    HOURLY spec without ``windows_repetition_minutes`` is refused here rather
    than emitted as a script that can never register (WI-071 L1).
    """
    if repetition_minutes is not None:
        return "-Once"
    if trigger.upper() == "HOURLY":
        raise ValueError(
            "an HOURLY windows_trigger requires windows_repetition_minutes — "
            "New-ScheduledTaskTrigger has no -Hourly parameter set"
        )
    if trigger.upper() == "WEEKLY":
        return "-Weekly -DaysOfWeek Sunday"
    return f"-{trigger.capitalize()}"


def _powershell_single_quote(value: str) -> str:
    """Quote a value for a PowerShell single-quoted string literal.

    The scheduled-task command is passed to PowerShell with ``-File`` rather
    than through a shell command string.  Values still have to be quoted in the
    generated script, though: a path containing an apostrophe must not change
    the script's syntax, and metacharacters must remain data rather than code.
    """
    if "\x00" in value:
        raise ValueError("PowerShell values cannot contain NUL")
    return "'" + value.replace("'", "''") + "'"


def _windows_trigger_type(
    trigger: str, *, repetition_minutes: int | None = None
) -> str:
    """Return the Scheduled Task CIM trigger type for a built-in cadence."""
    if repetition_minutes is not None:
        return "MSFT_TaskTimeTrigger"
    if trigger.upper() == "HOURLY":
        raise ValueError(
            "an HOURLY windows_trigger requires windows_repetition_minutes — "
            "New-ScheduledTaskTrigger has no -Hourly parameter set"
        )
    if trigger.upper() == "WEEKLY":
        return "MSFT_TaskWeeklyTrigger"
    return "MSFT_TaskDailyTrigger"


_WINDOWS_TIME_RE = re.compile(
    r"^(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5][0-9]))?(?P<ampm>[ap]m)$",
    re.IGNORECASE,
)


def _windows_time_parts(value: str) -> tuple[int, int]:
    """Convert the declarative ``2am``/``4am`` form to 24-hour parts."""
    match = _WINDOWS_TIME_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"unsupported Windows task time: {value!r}")
    hour = int(match.group("hour")) % 12
    if match.group("ampm").lower() == "pm":
        hour += 12
    minute = int(match.group("minute") or "0")
    return hour, minute


def _parse_windows_start_boundary(value: object) -> tuple[int, int] | None:
    """Read Task Scheduler's ISO StartBoundary without trusting its timezone."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    # Some Windows/.NET versions emit seven fractional-second digits while
    # Python's ISO parser accepts at most six.
    text = re.sub(r"(\.\d{6})\d+(?=(?:[+-]\d{2}:\d{2})?$)", r"\1", text)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for format_string in (
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %I:%M:%S %p",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(text, format_string)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed is None:
        return None
    return parsed.hour, parsed.minute


def _windows_task_script(spec: ScheduleSpec, *, resolved: ResolvedCommand | None = None) -> str:
    """Generate a PowerShell script that registers a Windows Scheduled Task.

    ``New-ScheduledTaskAction -Execute`` takes the *program*; arguments belong in
    ``-Argument``. The same install-time resolution as the systemd path is used,
    so the task action names a real executable rather than a bare word.  The
    script reads the task back after registration and exits non-zero unless the
    action and trigger that Windows registered match the requested values.  The
    JSON receipt is consumed by ``schedule install``; writing the script alone is
    never an ``INSTALLED`` claim (WI-067).
    """
    command = resolved or reference_command(spec, os_target=OSTarget.WINDOWS_TASK)
    execute = _powershell_single_quote(command.exec_path)
    arguments = _powershell_single_quote(command.arguments)
    argument = f" -Argument {arguments}" if command.arguments else ""
    repetition_argument = (
        f" -RepetitionInterval (New-TimeSpan -Minutes {spec.windows_repetition_minutes})"
        if spec.windows_repetition_minutes is not None
        else ""
    )
    task_name = _powershell_single_quote(spec.name)
    expected_trigger_type = _powershell_single_quote(
        _windows_trigger_type(
            spec.windows_trigger,
            repetition_minutes=spec.windows_repetition_minutes,
        )
    )
    trigger_kind = _powershell_single_quote(spec.windows_trigger.upper())
    expected_hour, expected_minute = _windows_time_parts(spec.windows_time)
    trigger_expr = _windows_trigger_expr(
        spec.windows_trigger,
        repetition_minutes=spec.windows_repetition_minutes,
    )
    if spec.windows_repetition_minutes is not None:
        trigger_setup = (
            f"  $startAt = (Get-Date).Date.AddHours({expected_hour})\n"
            f"  if ($startAt -le (Get-Date)) {{\n"
            f"    $startAt = $startAt.AddDays(1)\n"
            f"  }}\n"
            f"  # Omit -RepetitionDuration: Task Scheduler represents indefinite\n"
            f"  # repetition by leaving Repetition.Duration unset.\n"
            f"  $trigger = New-ScheduledTaskTrigger {trigger_expr} "
            f"-At $startAt{repetition_argument}\n"
        )
    else:
        trigger_setup = (
            f"  $trigger = New-ScheduledTaskTrigger {trigger_expr} "
            f"-At {spec.windows_time}{repetition_argument}\n"
        )
    repetition_check = (
        f"  $repetitionVerified = $repetitionMinutes -eq "
        f"{spec.windows_repetition_minutes}\n"
        if spec.windows_repetition_minutes is not None
        else "  $repetitionVerified = $null -eq $repetitionMinutes\n"
    )
    return (
        f"# {spec.description}\n"
        f"# Generated by `agent-suite schedule install` — do not edit by hand.\n"
        f"# Re-run `agent-suite schedule install` to regenerate.\n"
        f"try {{\n"
        f"  $action = New-ScheduledTaskAction -Execute {execute}{argument}\n"
        f"{trigger_setup}"
        f"  $settings = New-ScheduledTaskSettingsSet `\n"
        f"    -StartWhenAvailable `\n"
        f"    -DontStopOnIdleEnd `\n"
        f"    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15)\n"
        f"  Register-ScheduledTask `\n"
        f"    -TaskName {task_name} `\n"
        f"    -Action $action `\n"
        f"    -Trigger $trigger `\n"
        f"    -Settings $settings `\n"
        f"    -RunLevel Highest `\n"
        f"    -Force -ErrorAction Stop | Out-Null\n"
        f"  $registered = Get-ScheduledTask -TaskName {task_name} -ErrorAction Stop\n"
        f"  $registeredAction = @($registered.Actions)[0]\n"
        f"  $registeredTrigger = @($registered.Triggers)[0]\n"
        f"  $startBoundaryText = [string]$registeredTrigger.StartBoundary\n"
        f"  $startBoundaryVerified = $false\n"
        f"  try {{\n"
        f"    $startBoundary = [DateTimeOffset]::Parse($startBoundaryText, "
        f"[System.Globalization.CultureInfo]::InvariantCulture)\n"
        f"    $startBoundaryVerified = ($startBoundary.Hour -eq {expected_hour}) -and "
        f"($startBoundary.Minute -eq {expected_minute})\n"
        f"  }} catch {{\n"
        f"    try {{\n"
        f"      $startBoundary = [DateTimeOffset]::Parse($startBoundaryText)\n"
        f"      $startBoundaryVerified = ($startBoundary.Hour -eq {expected_hour}) -and "
        f"($startBoundary.Minute -eq {expected_minute})\n"
        f"    }} catch {{\n"
        f"      $startBoundaryVerified = $false\n"
        f"    }}\n"
        f"  }}\n"
        f"  $repetitionText = [string]$registeredTrigger.Repetition.Interval\n"
        f"  $repetitionMinutes = $null\n"
        f"  if ($repetitionText) {{\n"
        f"    try {{\n"
        f"      $repetitionMinutes = "
        f"([System.Xml.XmlConvert]::ToTimeSpan($repetitionText)).TotalMinutes\n"
        f"    }} catch {{\n"
        f"      try {{\n"
        f"        $repetitionMinutes = ([TimeSpan]::Parse($repetitionText)).TotalMinutes\n"
        f"      }} catch {{\n"
        f"        $repetitionMinutes = $null\n"
        f"      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"  $durationText = [string]$registeredTrigger.Repetition.Duration\n"
        f"  $durationMinutes = $null\n"
        f"  $durationVerified = -not [bool]$durationText\n"
        f"  if ($durationText) {{\n"
        f"    try {{\n"
        f"      $durationMinutes = "
        f"([System.Xml.XmlConvert]::ToTimeSpan($durationText)).TotalMinutes\n"
        f"    }} catch {{\n"
        f"      try {{\n"
        f"        $durationMinutes = ([TimeSpan]::Parse($durationText)).TotalMinutes\n"
        f"      }} catch {{\n"
        f"        $durationMinutes = $null\n"
        f"      }}\n"
        f"    }}\n"
        f"  }}\n"
        f"{repetition_check}"
        f"  $actionVerified = ([string]$registeredAction.Execute -eq {execute}) -and\n"
        f"    ([string]$registeredAction.Arguments -eq {arguments})\n"
        f"  $triggerType = [string]$registeredTrigger.CimClass.CimClassName\n"
        f"  $triggerVerified = ($triggerType -eq {expected_trigger_type}) -and "
        f"$startBoundaryVerified -and $repetitionVerified -and $durationVerified\n"
        f"  if ({trigger_kind} -eq 'WEEKLY') {{\n"
        f"    $triggerVerified = $triggerVerified -and\n"
        f"      ([string]$registeredTrigger.DaysOfWeek -match 'Sunday')\n"
        f"  }}\n"
        f"  if (-not $actionVerified -or -not $triggerVerified) {{\n"
        f"    throw \"registered task action or trigger does not match the requested schedule\"\n"
        f"  }}\n"
        f"  [ordered]@{{\n"
        f"    verified = $true\n"
        f"    task_name = [string]$registered.TaskName\n"
        f"    execute = [string]$registeredAction.Execute\n"
        f"    arguments = [string]$registeredAction.Arguments\n"
        f"    trigger = {trigger_kind}\n"
        f"    trigger_type = $triggerType\n"
        f"    trigger_time = $startBoundaryText\n"
        f"    trigger_time_verified = $startBoundaryVerified\n"
        f"    repetition_interval = $repetitionText\n"
        f"    repetition_minutes = $repetitionMinutes\n"
        f"    repetition_verified = $repetitionVerified\n"
        f"    repetition_duration = $durationText\n"
        f"    repetition_duration_minutes = $durationMinutes\n"
        f"    repetition_duration_verified = $durationVerified\n"
        f"    action_verified = $actionVerified\n"
        f"    trigger_verified = $triggerVerified\n"
        f"  }} | ConvertTo-Json -Compress\n"
        f"}} catch {{\n"
        f"  Write-Error $_\n"
        f"  exit 1\n"
        f"}}\n"
    )


def _windows_unregister_script(spec: ScheduleSpec) -> str:
    """Generate a PowerShell script that unregisters a Windows Scheduled Task."""
    task_name = _powershell_single_quote(spec.name)
    return (
        f"# Remove the '{spec.name}' scheduled task.\n"
        f"try {{\n"
        f"  $existing = Get-ScheduledTask -TaskName {task_name} "
        f"-ErrorAction SilentlyContinue\n"
        f"  if ($null -ne $existing) {{\n"
        f"    Unregister-ScheduledTask -TaskName {task_name} "
        f"-Confirm:$false -ErrorAction Stop | Out-Null\n"
        f"  }}\n"
        f"  $remaining = Get-ScheduledTask -TaskName {task_name} "
        f"-ErrorAction SilentlyContinue\n"
        f"  if ($null -ne $remaining) {{\n"
        f"    throw \"scheduled task remains registered\"\n"
        f"  }}\n"
        f"  [ordered]@{{ verified = $true; task_name = {task_name}; removed = $true }} "
        f"| ConvertTo-Json -Compress\n"
        f"}} catch {{\n"
        f"  Write-Error $_\n"
        f"  exit 1\n"
        f"}}\n"
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


def _verify_windows_registration(
    spec: ScheduleSpec,
    resolved: ResolvedCommand,
    result: subprocess.CompletedProcess[str],
) -> tuple[list[str], str | None]:
    """Validate the receipt emitted after a Windows task was registered.

    The PowerShell script queries Task Scheduler itself.  This second check is
    deliberately kept in Python as well: a successful process exit is not, by
    itself, evidence that the script's verification branch ran or that its
    output describes this spec.
    """
    if result.returncode != 0:
        detail = result.stderr.strip()[:300] or "no detail"
        return [], f"PowerShell task registration failed: {detail}"
    try:
        receipt = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return [], "PowerShell task registration returned no valid verification receipt"
    if not isinstance(receipt, dict):
        return [], "PowerShell task registration receipt was not an object"

    expected_trigger_type = _windows_trigger_type(
        spec.windows_trigger,
        repetition_minutes=spec.windows_repetition_minutes,
    )
    checks: tuple[tuple[str, object, object], ...] = (
        ("verified", receipt.get("verified"), True),
        ("task_name", receipt.get("task_name"), spec.name),
        ("execute", receipt.get("execute"), resolved.exec_path),
        ("arguments", receipt.get("arguments"), resolved.arguments),
        ("trigger", receipt.get("trigger"), spec.windows_trigger.upper()),
        ("trigger_type", receipt.get("trigger_type"), expected_trigger_type),
        ("trigger_time_verified", receipt.get("trigger_time_verified"), True),
        ("repetition_verified", receipt.get("repetition_verified"), True),
        (
            "repetition_duration_verified",
            receipt.get("repetition_duration_verified"),
            True,
        ),
        ("action_verified", receipt.get("action_verified"), True),
        ("trigger_verified", receipt.get("trigger_verified"), True),
    )
    for field_name, actual, expected in checks:
        if actual != expected:
            return [], (
                f"registered task verification mismatch for {field_name}: "
                f"expected {expected!r}, got {actual!r}"
            )

    expected_time = _windows_time_parts(spec.windows_time)
    actual_time = _parse_windows_start_boundary(receipt.get("trigger_time"))
    if actual_time != expected_time:
        return [], (
            "registered task verification mismatch for trigger_time: "
            f"expected {expected_time!r}, got {actual_time!r}"
        )
    if spec.windows_repetition_minutes is not None:
        actual_repetition = receipt.get("repetition_minutes")
        if actual_repetition != spec.windows_repetition_minutes:
            return [], (
                "registered task verification mismatch for repetition_minutes: "
                f"expected {spec.windows_repetition_minutes!r}, "
                f"got {actual_repetition!r}"
            )
    elif receipt.get("repetition_minutes") is not None:
        return [], (
            "registered task verification mismatch for repetition_minutes: "
            f"expected None, got {receipt.get('repetition_minutes')!r}"
        )
    duration = receipt.get("repetition_duration")
    duration_minutes = receipt.get("repetition_duration_minutes")
    if duration != "" or duration_minutes is not None:
        return [], (
            "registered task verification mismatch for repetition_duration: "
            f"expected indefinite (empty), got {duration!r}"
        )
    return [
        "windows_task_registered",
        "windows_action_verified",
        "windows_trigger_verified",
    ], None


def _verify_windows_removal(
    spec: ScheduleSpec,
    result: subprocess.CompletedProcess[str],
) -> tuple[list[str], str | None]:
    """Validate the receipt emitted after a Windows task was unregistered."""
    if result.returncode != 0:
        detail = result.stderr.strip()[:300] or "no detail"
        return [], f"PowerShell task removal failed: {detail}"
    try:
        receipt = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return [], "PowerShell task removal returned no valid verification receipt"
    if not isinstance(receipt, dict):
        return [], "PowerShell task removal receipt was not an object"
    if receipt.get("verified") is not True or receipt.get("task_name") != spec.name:
        return [], "PowerShell task removal was not verified"
    if receipt.get("removed") is not True:
        return [], "PowerShell task removal receipt did not confirm removal"
    return ["windows_task_unregistered", "windows_task_absent"], None


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


def _systemd_fire_time_env(spec: ScheduleSpec) -> dict[str, str]:
    """The environment a generated systemd unit will actually see at fire time.

    A systemd unit does not inherit the installer's shell: it sees the
    unit-level ``Environment=`` pins plus the optional ``EnvironmentFile`` at
    :func:`system_suite_env_path` (the file renders after the pins, so it wins
    — the same precedence the CLI itself applies when it loads the system file
    at fire time). Preflighting
    against ``os.environ`` greens an install whose required names live only in
    the operator's per-user suite.env, and then every fire fails
    FLAG_MISSING/DSN_MISSING (WI-071 M2).
    """
    env: dict[str, str] = {}
    for pin in spec.environment:
        key, _, value = pin.partition("=")
        env[key] = value
    env.update(_parse_env_file(system_suite_env_path()))
    return env


def _schedule_config_failure(spec: ScheduleSpec, *, os_target: OSTarget) -> str | None:
    """Return a safe configuration failure for a declarative schedule.

    This is intentionally a preflight rather than a check inside the scheduled
    command: an operator must not receive an ``INSTALLED`` claim for a unit
    whose required environment is absent.  On systemd the check reads the
    environment the *unit* will see (:func:`_systemd_fire_time_env`), not the
    installer's shell; on Windows the task runs as the registering user, whose
    fire-time environment ``os.environ`` (with suite.env already layered in)
    faithfully approximates.  Only variable names appear in the detail; DSN
    values stay in memory.
    """
    env: Mapping[str, str]
    if os_target is OSTarget.SYSTEMD:
        env = _systemd_fire_time_env(spec)
        source_hint = (
            f" in {system_suite_env_path()} — the unit reads that file, not the "
            "installer's shell environment"
        )
    else:
        env = os.environ
        source_hint = ""
    for env_name in spec.required_env:
        if not env.get(env_name, "").strip():
            return f"required environment variable {env_name} is not set{source_hint}"

    if spec.dedicated_dsn_env is not None:
        scratch_dsn = env.get(spec.dedicated_dsn_env, "").strip()
        production_dsn = env.get("REGISTA_DSN", "").strip()
        if production_dsn and same_postgres_database(scratch_dsn, production_dsn):
            return (
                f"{spec.dedicated_dsn_env} must identify a database distinct from "
                "REGISTA_DSN"
            )
    return None


def check_actor_system_scoped(
    resolved: ResolvedCommand,
    *,
    probe: SystemScopeProbe | None = None,
) -> str | None:
    """Return a refusal reason when the actor resolved the CLI from a non-system
    bin directory, or ``None`` when it is system-scoped (WI-038).

    The reversed WI-038 approach merged the resolved bin dir into the unit PATH;
    this refuses it instead, so a root-run unit never searches a foreign /
    user-writable directory. Scope is decided by ownership / writability
    (:func:`is_system_scoped_bin_dir`): a root-owned ``/opt/agent-suite/bin`` is
    accepted, a user-owned ``~/.local/bin`` is refused.
    """
    bin_dir = Path(resolved.exec_path).parent
    if is_system_scoped_bin_dir(bin_dir, probe=probe):
        return None
    return (
        f"resolved ExecStart {resolved.exec_path!r} from a non-system bin directory "
        f"{bin_dir} — refusing to anchor a root-run unit on a foreign / "
        f"user-writable dir (the unit pins only the system PATH). "
        f"{_UNRESOLVED_HINT}"
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
    system_scope_probe: SystemScopeProbe | None = None,
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
    and then fails only when the timer fires. On either OS a resolved command
    whose bin directory is not system-scoped is likewise refused (WI-038,
    reversed): the scheduled run resolves the estate from the process PATH, so an
    actor that resolved the CLI from a foreign / user-writable dir is rejected
    rather than having that dir trusted under root / the Task Scheduler. On
    Windows, a non-dry-run install executes each generated PowerShell script and
    requires its read-back receipt to prove the registered action and trigger.
    Task registration uses a larger timeout than the shared runner default so a
    cold ScheduledTasks provider cannot time out after applying the task.

    Every result carries an ``invoking_context`` (WI-038) recording how the
    install was invoked — the box (the machine the unit runs in, system-scoped)
    vs the actor (who resolved the CLI) — so an operator can tell a root/cron
    run from an operator run.

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

    config_failures = {
        spec.kind: failure
        for spec in schedules
        if (failure := _schedule_config_failure(spec, os_target=target)) is not None
    }
    if config_failures:
        first_failed_kind = next(iter(config_failures))
        first_failure = config_failures[first_failed_kind]
        first_failed_spec = next(s for s in schedules if s.kind is first_failed_kind)
        preflight_results = [
            ScheduleResult(
                kind=spec.kind,
                status=InstallStatus.FAILED,
                detail=(
                    config_failures[spec.kind]
                    if spec.kind in config_failures
                    else (
                        "not attempted because schedule configuration preflight "
                        f"failed for {first_failed_spec.name}: {first_failure}"
                    )
                ),
            )
            for spec in schedules
        ]
        return ScheduleReport(results=preflight_results, os_target=target)

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

        # WI-038: record HOW this install was invoked — the box (the machine the
        # scheduled unit runs in, system-scoped) vs the actor (the process that
        # resolved the CLI), so an operator can tell a root/cron run from an
        # operator run.
        ctx = invoking_context_for(resolved, probe=system_scope_probe)

        # Pre-write gate: absolute, present, executable.
        reason = check_exec_start_runnable(resolved)
        if reason is not None and target is OSTarget.SYSTEMD:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.FAILED,
                    detail=f"{reason}. {_UNRESOLVED_HINT}",
                    exec_start=resolved.exec_start,
                    invoking_context=ctx,
                )
            )
            continue

        # WI-038 (reversed): the scheduled run resolves the estate from the
        # process PATH, so refuse an actor that resolved the CLI from a non-system
        # bin dir rather than baking that dir into the unit PATH (systemd) or
        # trusting it under the Task Scheduler (Windows). The refusal carries the
        # invoking context so the operator can see the actor bin dir that tripped it.
        scope_reason = check_actor_system_scoped(resolved, probe=system_scope_probe)
        if scope_reason is not None:
            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.FAILED,
                    detail=scope_reason,
                    exec_start=resolved.exec_start,
                    invoking_context=ctx,
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
                    invoking_context=ctx,
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
                        invoking_context=ctx,
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
                                invoking_context=ctx,
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
                            invoking_context=ctx,
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
                        invoking_context=ctx,
                    )
                )
                continue

        elif target is OSTarget.WINDOWS_TASK:
            script_path = files[0][0]
            register_cmd: tuple[str, ...] = (
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
            )
            try:
                registration = _run_powershell_task(runner, register_cmd)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=written,
                        detail=f"PowerShell task registration error: {exc}",
                        exec_start=resolved.exec_start,
                        verified=verified,
                        invoking_context=ctx,
                    )
                )
                continue

            post_checks, verify_failure = _verify_windows_registration(
                spec, resolved, registration
            )
            verified.extend(post_checks)
            if verify_failure is not None:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=written,
                        detail=f"task written but not verified: {verify_failure}",
                        exec_start=resolved.exec_start,
                        verified=verified,
                        invoking_context=ctx,
                    )
                )
                continue
        else:
            assert_never(target)

        results.append(
            ScheduleResult(
                kind=spec.kind,
                status=InstallStatus.INSTALLED,
                files_written=written,
                detail="installed and verified" if verified else "installed",
                exec_start=resolved.exec_start,
                verified=verified,
                invoking_context=ctx,
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
            except OSError as exc:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=[str(unregister_script)],
                        detail=f"failed to write task removal script: {exc}",
                    )
                )
                continue

            unregister_cmd: tuple[str, ...] = (
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(unregister_script),
            )
            try:
                removal = _run_powershell_task(runner, unregister_cmd)
            except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=[str(unregister_script)],
                        detail=f"PowerShell task removal error: {exc}",
                    )
                )
                continue

            verified, verify_failure = _verify_windows_removal(spec, removal)
            if verify_failure is not None:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=[str(unregister_script)],
                        detail=f"task removal was not verified: {verify_failure}",
                        verified=verified,
                    )
                )
                continue

            cleanup_errors: list[str] = []
            for path in (
                script_dir / f"{spec.name}.ps1",
                unregister_script,
            ):
                try:
                    path.unlink(missing_ok=True)
                except OSError as exc:
                    cleanup_errors.append(f"{path}: {exc}")

            if cleanup_errors:
                results.append(
                    ScheduleResult(
                        kind=spec.kind,
                        status=InstallStatus.FAILED,
                        files_written=[str(unregister_script)],
                        detail=(
                            "task unregistered, but generated script cleanup failed: "
                            + "; ".join(cleanup_errors)
                        ),
                        verified=verified,
                    )
                )
                continue

            results.append(
                ScheduleResult(
                    kind=spec.kind,
                    status=InstallStatus.REMOVED,
                    detail="removed and verified",
                    verified=verified,
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
        if r.invoking_context is not None:
            actor = r.invoking_context.actor
            box = r.invoking_context.box
            actor_scope = "system" if actor.system_scoped else "NON-system"
            lines.append(
                f"    invoking context: actor={actor.bin_dir} ({actor_scope}), "
                f"box={box.bin_dir} (system)"
            )
        for f in r.files_written:
            lines.append(f"    {f}")
    return "\n".join(lines)
