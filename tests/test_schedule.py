"""Unit tests for the schedule module — file generation, install, remove, OS detection.

All tests use stubbed runners — no real systemd or Windows.
"""

from __future__ import annotations

import shlex
import stat
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_suite.schedule import (
    REFERENCE_BIN_DIR,
    SCHEDULES,
    SUITE_ENV_PATH,
    SYSTEM_BIN_DIRS,
    SYSTEM_PATH,
    ContextScope,
    InstallStatus,
    OSTarget,
    ResolvedCommand,
    ScheduleKind,
    ScheduleReport,
    ScheduleResult,
    ScopeContext,
    _systemd_service,
    _systemd_timer,
    _windows_task_script,
    build_invoking_context,
    check_actor_system_scoped,
    check_exec_start_runnable,
    format_schedule_report,
    generate_schedule_files,
    install_schedules,
    invoking_context_for,
    is_system_scoped_bin_dir,
    reference_command,
    remove_schedules,
    resolve_command,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    def __init__(
        self,
        outputs: (
            Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
            | None
        ) = None,
    ) -> None:
        self._outputs = outputs or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                return out
        return _completed(stdout="", returncode=0)


def _command_name(spec) -> str:  # type: ignore[no-untyped-def]
    return shlex.split(spec.command)[0]


def _fake_bin_dir(tmp_path: Path, *, executable: bool = True) -> Path:
    """A directory holding a real file per schedule command name.

    Real files, not names: the install path checks the resolved ExecStart is an
    existing executable, so a stub that only pretends would not exercise it.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for spec in SCHEDULES:
        exe = bindir / _command_name(spec)
        if not exe.exists():
            exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            exe.chmod(0o755 if executable else 0o644)
    return bindir


def _verifying_runner(
    bindir: Path,
    *,
    timer_state: str = "active",
    reported_exec_path: str | None = None,
) -> StubRunner:
    """A systemd stub that answers the post-install verification.

    ``reported_exec_path`` overrides what ``systemctl show`` claims ExecStart
    resolved to (a literal ``None`` sentinel is not needed — pass the pre-fix
    bare command name to simulate the WI-045 unit). ``timer_state`` overrides
    ``systemctl is-active``.
    """
    outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str]] = {}
    for spec in SCHEDULES:
        exec_path = reported_exec_path or str(bindir / _command_name(spec))
        outputs[("systemctl", "show", f"{spec.name}.service")] = _completed(
            stdout=f"{{ path={exec_path} ; argv[]={spec.command} ; ignore_errors=no }}"
        )
        outputs[("systemctl", "is-active", f"{spec.name}.timer")] = _completed(
            stdout=timer_state, returncode=0 if timer_state == "active" else 3
        )
    outputs[("systemctl", "daemon-reload")] = _completed()
    outputs[("systemctl", "enable")] = _completed()
    return StubRunner(outputs)


def _no_which(executable: str) -> str | None:
    """Never resolve from the ambient PATH — tests must not depend on the host."""
    return None


def _treat_as_system_scoped(monkeypatch: pytest.MonkeyPatch, bindir: Path) -> None:
    """Treat *bindir* as a system bin dir for this test (WI-038).

    A real install resolves system-scoped; tests build executables in a private
    tmp dir (they cannot write into /usr/local/bin in CI), so SYSTEM_BIN_DIRS is
    patched to include the tmp dir. The scope probe consults SYSTEM_BIN_DIRS
    *first* (before the ownership / profile check), so this monkeypatch takes
    effect on every host OS: on Windows a tmp dir under ``%%USERPROFILE%%`` would
    otherwise read as user-scoped, and on POSIX a test-user-owned tmp dir would
    otherwise read as non-root-owned. Without this the reversed WI-038 gate would
    refuse the install as a non-system bin dir — which is exactly the behavior
    the non-system refusal tests below assert separately."""
    monkeypatch.setattr("agent_suite.schedule.SYSTEM_BIN_DIRS", (bindir,))


def _treat_box_as_system_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the box-side scope measurement to True for this test (WI-038).

    ``_box_system_scoped`` honestly measures ownership of the pinned SYSTEM_PATH
    directories, and on GitHub-hosted runners ``/usr/local/bin`` (and friends)
    are deliberately agent-writable — the measurement correctly reports False
    there, which is the very hazard WI-038 exists to refuse. Tests that assert
    the *plumbing* (the measured value reaches the context/report) pin the
    measurement; the measurement itself is asserted separately by
    test_box_scope_measurement_reports_user_writable_system_path."""
    monkeypatch.setattr("agent_suite.schedule._box_system_scoped", lambda: True)


# ---------------------------------------------------------------------------
# File generation
# ---------------------------------------------------------------------------


def test_generate_systemd_files() -> None:
    spec = SCHEDULES[0]
    files = generate_schedule_files(spec, os_target=OSTarget.SYSTEMD)
    assert len(files) == 2  # .service + .timer
    service_path, service_content = files[0]
    timer_path, timer_content = files[1]
    assert service_path.name == f"{spec.name}.service"
    assert timer_path.name == f"{spec.name}.timer"
    assert "ExecStart=" in service_content
    assert "OnCalendar=" in timer_content
    assert "EnvironmentFile=" in service_content


def test_generate_windows_files() -> None:
    spec = SCHEDULES[0]
    files = generate_schedule_files(spec, os_target=OSTarget.WINDOWS_TASK)
    assert len(files) == 1  # .ps1 script
    path, content = files[0]
    assert path.suffix == ".ps1"
    assert "Register-ScheduledTask" in content
    assert spec.name in content


def test_generated_files_have_no_work_domain_identifiers() -> None:
    """No real hostnames, DSNs, or principal IDs in generated unit files."""
    for spec in SCHEDULES:
        for os_target in [OSTarget.SYSTEMD, OSTarget.WINDOWS_TASK]:
            files = generate_schedule_files(spec, os_target=os_target)
            for _, content in files:
                assert "suite-db.example" not in content
                assert "REGISTA_DSN=" not in content or "EnvironmentFile" in content
                # The unit file references suite.env via EnvironmentFile, not inline


def test_generated_files_use_suite_env_not_hardcoded_config() -> None:
    """systemd units load suite.env via EnvironmentFile, not inline values."""
    spec = SCHEDULES[0]
    files = generate_schedule_files(spec, os_target=OSTarget.SYSTEMD)
    service_content = files[0][1]
    assert "EnvironmentFile=-/etc/agent-suite/suite.env" in service_content


# ---------------------------------------------------------------------------
# Install (dry-run)
# ---------------------------------------------------------------------------


def test_install_dry_run_prints_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(bindir,),
    )
    assert report.os_target is OSTarget.SYSTEMD
    assert len(report.results) == len(SCHEDULES)
    for r in report.results:
        assert r.status is InstallStatus.INSTALLED
        assert len(r.files_written) > 0
        assert "dry-run" in r.detail


def test_install_dry_run_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bindir = _fake_bin_dir(tmp_path)
    # WI-038 (reversed): a successful install is system-scoped on either OS.
    # The test builds its executables in a private tmp dir (it cannot write into
    # a real system bin dir in CI), so mark that dir system-scoped to exercise
    # the success path; the non-system refusal is asserted separately.
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.WINDOWS_TASK,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(bindir,),
    )
    assert report.os_target is OSTarget.WINDOWS_TASK
    for r in report.results:
        assert r.status is InstallStatus.INSTALLED


# ---------------------------------------------------------------------------
# Install (real — systemd, stubbed)
# ---------------------------------------------------------------------------


def test_install_systemd_writes_files_and_enables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=_verifying_runner(bindir),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.INSTALLED for r in report.results), [
        r.detail for r in report.results
    ]
    for spec in SCHEDULES:
        assert (unit_dir / f"{spec.name}.service").exists()
        assert (unit_dir / f"{spec.name}.timer").exists()


def test_install_fails_on_systemctl_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    runner = StubRunner({
        ("systemctl", "daemon-reload"): _completed(returncode=1, stderr="failed"),
    })
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=runner,
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert any(r.status is InstallStatus.FAILED for r in report.results)


# ---------------------------------------------------------------------------
# WI-045 — ExecStart must be an absolute path, and install must verify it
#
# The qualification found all three units failing 203/EXEC. systemd resolves an
# unqualified ExecStart only against its own fixed search path, never the
# invoking user's PATH, so on a ~/.local/bin (uv tool / pip --user) layout every
# unit was dead and the weekly chain-integrity timer never fired anywhere.
#
# Nothing in this file used to run a unit or look at what ExecStart pointed at:
# test_deploy_reference_copies_match_generator_output asserted the shipped copies
# equal the generator's output, which is byte-equality between two things that
# were both wrong. These tests ask instead whether the value would work.
# ---------------------------------------------------------------------------


def test_every_generated_execstart_is_an_absolute_path() -> None:
    """Generation-level gate: no schedule may render a bare ExecStart.

    Covers both renderings — the deploy/ reference form and an install-time
    resolution — because the defect was in the default, not in one caller.
    """
    for spec in SCHEDULES:
        for resolved in (None, ResolvedCommand("/opt/agent-suite/bin/x", "arg")):
            unit = _systemd_service(spec, resolved=resolved)
            exec_line = next(
                line for line in unit.splitlines() if line.startswith("ExecStart=")
            )
            value = exec_line.removeprefix("ExecStart=")
            program = shlex.split(value)[0]
            assert Path(program).is_absolute(), (
                f"{spec.name}: ExecStart={value!r} is not an absolute path — systemd "
                f"will fail it 203/EXEC on any host whose CLIs are not on systemd's "
                f"own fixed search path"
            )


def test_shipped_reference_units_have_absolute_existing_prefix() -> None:
    """The units under deploy/systemd/ are absolute and use the documented prefix.

    The reference copies are what an operator installs by hand, so the property
    has to hold of the *files*, not only of the generator.
    """
    repo = Path(__file__).resolve().parents[1]
    for spec in SCHEDULES:
        unit = (repo / "deploy/systemd" / f"{spec.name}.service").read_text()
        exec_line = next(line for line in unit.splitlines() if line.startswith("ExecStart="))
        program = shlex.split(exec_line.removeprefix("ExecStart="))[0]
        assert Path(program).is_absolute(), f"{spec.name}: {exec_line}"
        assert Path(program).parent == REFERENCE_BIN_DIR, (
            f"{spec.name}: reference copy uses {Path(program).parent}, not the documented "
            f"{REFERENCE_BIN_DIR}"
        )


def test_reference_bin_dir_is_on_systemd_fixed_search_path() -> None:
    """The documented prefix must be somewhere systemd itself would look.

    A reference copy installed verbatim has to work; /usr/local/bin is on
    systemd's fixed ExecStart path, ~/.local/bin is not — that asymmetry is the
    whole defect.
    """
    assert str(REFERENCE_BIN_DIR) in (
        "/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin",
    )


def test_resolve_command_prefers_bin_dir_and_returns_absolute(tmp_path: Path) -> None:
    bindir = _fake_bin_dir(tmp_path)
    resolved = resolve_command("cairn integrity", which=_no_which, search_dirs=(bindir,))
    assert resolved is not None
    assert resolved.exec_path == str(bindir / "cairn")
    assert resolved.arguments == "integrity"
    assert resolved.exec_start == f"{bindir / 'cairn'} integrity"


def test_resolve_command_returns_none_rather_than_a_bare_name() -> None:
    """An unresolvable command must not degrade to the bare word.

    agent-suite WI-038 moves per-box CLIs to a system PATH, which would make a
    bare name work — but a per-user install must still get working timers or a
    loud refusal, never a unit that reports success and fails at 3am.
    """
    assert resolve_command("definitely-not-a-real-cli x", which=_no_which) is None


def test_check_exec_start_runnable_rejects_bare_and_missing(tmp_path: Path) -> None:
    bare = check_exec_start_runnable(ResolvedCommand("cairn", "integrity"))
    assert bare is not None and "not absolute" in bare

    missing = check_exec_start_runnable(ResolvedCommand(str(tmp_path / "nope")))
    assert missing is not None and "does not exist" in missing

    not_exec = tmp_path / "plain"
    not_exec.write_text("x", encoding="utf-8")
    assert "not an executable file" in (check_exec_start_runnable(
        ResolvedCommand(str(not_exec))
    ) or "")

    ok = tmp_path / "runnable"
    ok.write_text("#!/bin/sh\n", encoding="utf-8")
    ok.chmod(0o755)
    assert check_exec_start_runnable(ResolvedCommand(str(ok))) is None


def test_install_refuses_to_write_a_unit_it_cannot_resolve(tmp_path: Path) -> None:
    """Unresolvable command: FAILED, nothing written, and the reason names the fault.

    A unit with a bare ExecStart is worse than no unit — it reports installed and
    then fails 203/EXEC only when the timer fires.
    """
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(tmp_path / "empty",),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)
    assert all("203/EXEC" in r.detail for r in report.results)
    assert list(unit_dir.iterdir()) == []


def test_install_refuses_a_candidate_that_is_present_but_not_executable(
    tmp_path: Path,
) -> None:
    """A file that exists but is not executable is still 203/EXEC.

    Resolution requires the executable bit, so this does not resolve at all and
    the refusal comes from the same place as a missing file — the point is that
    nothing is written and the mode is not mistaken for a working install.
    """
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path, executable=False)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)
    assert all("203/EXEC" in r.detail for r in report.results)
    assert list(unit_dir.iterdir()) == []


def test_dry_run_is_a_real_preflight_not_a_print(tmp_path: Path) -> None:
    """`--dry-run` must fail on an unresolvable command, not print a plan."""
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(tmp_path / "empty",),
        unit_dir=tmp_path / "systemd",
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)


def test_install_fails_when_systemd_parses_a_different_execstart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verification reads systemd's own parse, not the string we just wrote.

    Stub systemd into reporting the pre-fix bare name: install must refuse to
    call that installed, even though the file on disk is ours.
    """
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        # systemd reports the pre-fix bare name, whatever we wrote.
        runner=_verifying_runner(bindir, reported_exec_path="cairn"),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)
    assert all("not verified" in r.detail for r in report.results)


def test_install_fails_when_the_timer_did_not_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`enable --now` returning 0 is not evidence the timer is running."""
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=_verifying_runner(bindir, timer_state="inactive"),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)
    assert all("not active" in r.detail for r in report.results)


def test_install_reports_the_checks_that_actually_passed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An INSTALLED result names its evidence; presence of a file is not evidence."""
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=_verifying_runner(bindir),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    for result in report.results:
        assert result.status is InstallStatus.INSTALLED, result.detail
        assert result.verified == [
            "exec_start_runnable",
            "systemd_execstart_runnable",
            "timer_active",
        ]
        assert Path(shlex.split(result.exec_start)[0]).is_absolute()
        assert result.to_dict()["verified"] == result.verified


def test_windows_task_action_separates_program_from_arguments() -> None:
    """`New-ScheduledTaskAction -Execute` takes the program; args go in -Argument.

    `-Execute 'cairn integrity'` asks the Task Scheduler to launch a program
    literally named "cairn integrity".
    """
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.CHAIN_INTEGRITY)
    script = _windows_task_script(spec)
    assert "-Execute 'cairn' -Argument 'integrity'" in script

    resolved = ResolvedCommand("C:/Python312/Scripts/cairn.exe", "integrity")
    script = _windows_task_script(spec, resolved=resolved)
    assert "-Execute 'C:/Python312/Scripts/cairn.exe' -Argument 'integrity'" in script


def test_reference_command_is_os_shaped() -> None:
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.CHAIN_INTEGRITY)
    assert reference_command(spec).exec_path == str(REFERENCE_BIN_DIR / "cairn")
    # Windows has no canonical install prefix (`pip install` uses whichever
    # Scripts/ the interpreter owns) and its scheduler does resolve against PATH.
    assert reference_command(spec, os_target=OSTarget.WINDOWS_TASK).exec_path == "cairn"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------


def test_remove_systemd_deletes_files(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    for spec in SCHEDULES:
        (unit_dir / f"{spec.name}.service").write_text("dummy")
        (unit_dir / f"{spec.name}.timer").write_text("dummy")

    runner = StubRunner({
        ("systemctl", "disable"): _completed(stdout=""),
        ("systemctl", "daemon-reload"): _completed(stdout=""),
    })
    report = remove_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=runner,
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.REMOVED for r in report.results)
    for spec in SCHEDULES:
        assert not (unit_dir / f"{spec.name}.service").exists()
        assert not (unit_dir / f"{spec.name}.timer").exists()


def test_remove_is_idempotent(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    runner = StubRunner({
        ("systemctl", "disable"): _completed(stdout=""),
        ("systemctl", "daemon-reload"): _completed(stdout=""),
    })
    report = remove_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=runner,
        unit_dir=unit_dir,
    )
    # Removing when nothing exists should still succeed
    assert all(r.status is InstallStatus.REMOVED for r in report.results)


# ---------------------------------------------------------------------------
# Unsupported OS
# ---------------------------------------------------------------------------


def test_install_unsupported_os(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent_suite.schedule.detect_os_target", lambda: None)
    report = install_schedules(dry_run=False, runner=StubRunner())
    assert all(r.status is InstallStatus.UNSUPPORTED_OS for r in report.results)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_schedule_report() -> None:
    report = ScheduleReport(
        os_target=OSTarget.SYSTEMD,
        results=[
            ScheduleResult(
                kind=ScheduleKind.BACKUP_VERIFY,
                status=InstallStatus.INSTALLED,
                files_written=["/etc/systemd/system/agent-suite-backup.service"],
                detail="installed",
            ),
        ],
    )
    text = format_schedule_report(report, "install")
    assert "systemd" in text
    assert "backup-verify" in text
    assert "installed" in text


def test_chain_integrity_schedule_is_declared():
    """cairn WI-030: the full chain replay is a scheduled operation, weekly to
    match cairn's default verdict staleness window (168h), and its failure
    path closes through the hourly DOCTOR_ALERT schedule."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.CHAIN_INTEGRITY)
    assert spec.command == "cairn integrity"
    assert spec.on_calendar == "weekly"
    assert spec.windows_trigger == "WEEKLY"
    assert spec.name == "agent-suite-chain-integrity"


def test_windows_weekly_trigger_includes_days_of_week():
    """New-ScheduledTaskTrigger's Weekly parameter set makes -DaysOfWeek
    mandatory; a bare -Weekly dies non-interactively (review round 1 M1)."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.CHAIN_INTEGRITY)
    script = _windows_task_script(spec)
    assert "-Weekly -DaysOfWeek" in script
    daily = next(s for s in SCHEDULES if s.kind is ScheduleKind.BACKUP_VERIFY)
    assert "-Daily -At 2am" in _windows_task_script(daily)


def test_chain_integrity_unit_pins_shared_verdict_dir():
    """The timer runs as root while doctors run as humans: without a shared
    CAIRN_INTEGRITY_DIR every human-run doctor reads its own empty state
    home and reports never_run forever (review round 1 M2). Environment=
    renders before EnvironmentFile so suite.env still overrides."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.CHAIN_INTEGRITY)
    unit = _systemd_service(spec)
    env_pos = unit.index("Environment=CAIRN_INTEGRITY_DIR=/var/lib/agent-suite/cairn")
    file_pos = unit.index("EnvironmentFile=")
    assert env_pos < file_pos


def _unit_path_value(unit: str) -> str:
    """The ``PATH`` value from a generated unit's ``Environment=PATH=`` line."""
    line = next(
        line for line in unit.splitlines() if line.startswith("Environment=PATH=")
    )
    return line.removeprefix("Environment=PATH=")


def test_unit_pins_system_path_only_not_resolved_bin_dir() -> None:
    """WI-038 (reversed): the unit pins *only* the system PATH. The previous
    approach prepended the directory the installer resolved ``ExecStart`` from,
    which can hide a tampered / foreign bin dir under a root-run unit. The unit
    must not search the resolved bin dir — a non-system actor resolution is
    refused at install time instead (see test_install_refuses_non_system_bin_dir).

    The pinned PATH is always the POSIX ``SYSTEM_PATH`` literal regardless of
    host OS (systemd is Linux-only), so this holds on a Windows host too."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    resolved_dir = "/opt/agent-suite/bin"
    resolved = ResolvedCommand(f"{resolved_dir}/agent-suite", "alert-check")
    unit = _systemd_service(spec, resolved=resolved)
    path = _unit_path_value(unit)
    assert path == SYSTEM_PATH
    assert "/" in path  # POSIX, never backslash-joined
    assert resolved_dir not in path.split(":")


def test_unit_system_path_contains_reference_bin_dir() -> None:
    """The pinned system PATH contains REFERENCE_BIN_DIR, so a reference copy
    installed verbatim on a system-scoped host resolves the system component
    CLIs (rather than pinning nothing useful). ``SYSTEM_PATH`` is the canonical
    POSIX literal — never re-derived from host-flavored Path objects."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    path = _unit_path_value(_systemd_service(spec))
    assert str(REFERENCE_BIN_DIR) in path.split(":")
    assert path == SYSTEM_PATH


def test_unit_path_renders_before_environment_file() -> None:
    """The pinned system PATH is a unit-level default the operator's ``suite.env``
    may override, so it must render before ``EnvironmentFile`` (file-beats-unit)."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    unit = _systemd_service(spec, resolved=ResolvedCommand("/opt/x/bin/agent-suite", ""))
    assert unit.index("Environment=PATH=") < unit.index("EnvironmentFile=")


def test_check_actor_system_scoped_refuses_non_system_dir(tmp_path: Path) -> None:
    """An actor that resolved the CLI from a non-system bin dir is refused (WI-038,
    reversed) rather than having that dir merged into the unit PATH."""
    reason = check_actor_system_scoped(
        ResolvedCommand(str(tmp_path / "agent-suite"), "alert-check")
    )
    assert reason is not None
    assert "non-system bin directory" in reason


def test_check_actor_system_scoped_accepts_system_dir() -> None:
    """A system bin dir resolves cleanly (no refusal)."""
    assert check_actor_system_scoped(ResolvedCommand("/usr/local/bin/agent-suite")) is None


def test_opt_root_owned_dir_is_accepted_via_ownership_not_path_membership() -> None:
    """DEFECT 1: the scope predicate tests ownership/writability, not PATH
    membership. ``/opt`` is NOT on the system PATH allowlist, so whatever the
    predicate answers for it is decided by ownership alone — exactly the
    ``/opt/agent-suite`` venv layout ``docs/install-linux.md`` §2/§7 prescribes.
    The expected verdict is computed independently from ``stat`` (root-owned and
    not group/other-writable → accepted) rather than assumed, because hosts
    differ: a real install box has a root-owned mode-755 ``/opt`` and is
    accepted; a GitHub-hosted runner deliberately makes ``/opt`` agent-writable
    and must be refused — the very hazard WI-038 exists for. Either verdict
    proves the predicate is ownership, not membership; the literal-membership
    predicate this replaces answered False for ``/opt`` unconditionally."""
    opt = Path("/opt")
    assert opt.exists(), "/opt must exist to demonstrate the docs layout"
    assert opt not in SYSTEM_BIN_DIRS  # acceptance is NOT path membership
    st = opt.stat()
    system_owned = st.st_uid == 0 and not st.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    assert is_system_scoped_bin_dir(opt) is system_owned  # decided via OWNERSHIP
    # bin_dir of "/opt/agent-suite" is "/opt" → accepted iff root-owned
    reason = check_actor_system_scoped(ResolvedCommand("/opt/agent-suite"))
    if system_owned:
        assert reason is None
    else:
        assert reason is not None and "non-system bin directory" in reason


def test_user_owned_local_bin_dir_is_refused(tmp_path: Path) -> None:
    """DEFECT 1: a user-writable / user-owned bin dir (~/.local/bin, a uv-tool
    user dir, a pytest tmp_path) is refused — the privilege-escalation shape
    WI-038 forbids. tmp_path is owned by the test user (uid != 0), so the
    ownership predicate refuses it without any allowlist."""
    user_bin = tmp_path  # owned by the invoking (non-root) user
    assert user_bin.stat().st_uid != 0
    assert user_bin not in SYSTEM_BIN_DIRS
    assert is_system_scoped_bin_dir(user_bin) is False
    reason = check_actor_system_scoped(ResolvedCommand(str(user_bin / "agent-suite")))
    assert reason is not None
    assert "non-system bin directory" in reason


def test_documented_opt_bin_dir_install_works_when_system_scoped(
    tmp_path: Path,
) -> None:
    """DEFECT 1: the ``sudo agent-suite schedule install --bin-dir
    /opt/agent-suite/bin`` command from docs/install-linux.md §7 must work. CI
    cannot create a root-owned ``/opt/agent-suite/bin``, so the layout is built
    in tmp and a scope probe marks it system-scoped — mimicking the root-owned
    property a real ``/opt`` install has (see
    test_opt_root_owned_dir_is_accepted_via_ownership_not_path_membership). The
    user-owned refusal is asserted separately by
    test_install_refuses_non_system_bin_dir_records_context."""
    opt_bin = _fake_bin_dir(tmp_path)  # stands in for /opt/agent-suite/bin
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(opt_bin,),
        system_scope_probe=lambda d: d.resolve() == opt_bin.resolve(),
    )
    assert all(r.status is InstallStatus.INSTALLED for r in report.results), [
        r.detail for r in report.results
    ]


def test_invoking_context_box_vs_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    """The invoking context surfaces both scopes (WI-038): the box (the machine
    the unit runs in, system-scoped) and the actor (who resolved the CLI). Both
    sides carry MEASURED values — system_scoped runs the probe / the pinned-path
    ownership check (never hardcoded), uid is read from the process / resolved
    from the unit's User=root, and PATH provenance + config sources are recorded.
    An actor that resolved from a system dir agrees with the box; one that
    resolved from a foreign dir is flagged non-system so an operator reading the
    result can tell a root/cron run from an operator run. The box measurement is
    pinned (host SYSTEM_PATH ownership varies by runner); its honesty is covered
    by test_box_scope_measurement_reports_user_writable_system_path."""
    _treat_box_as_system_scoped(monkeypatch)
    system_ctx = invoking_context_for(
        ResolvedCommand("/usr/local/bin/agent-suite"),
        actor_uid=1000,
        actor_euid=1000,
        path_env="/usr/local/bin:/usr/bin",
    )
    assert system_ctx.actor.system_scoped is True
    assert system_ctx.box.system_scoped is True  # measured, not hardcoded
    assert system_ctx.box.scope is ContextScope.BOX
    assert system_ctx.actor.scope is ContextScope.ACTOR
    assert system_ctx.box.bin_dir == str(REFERENCE_BIN_DIR)
    assert system_ctx.actor.bin_dir == "/usr/local/bin"

    # The box side is a real measurement: root's uid, the pinned system PATH,
    # and the suite EnvironmentFile — not the two-field tautology it replaced.
    assert system_ctx.box.uid == 0
    assert system_ctx.box.euid is None
    assert system_ctx.box.path_provenance == f"systemd-unit:{SYSTEM_PATH}"
    assert system_ctx.box.config_sources == (str(SUITE_ENV_PATH),)
    # The actor side records who invoked it and how PATH was resolved.
    assert system_ctx.actor.uid == 1000
    assert system_ctx.actor.euid == 1000
    assert system_ctx.actor.path_provenance == "/usr/local/bin:/usr/bin"

    foreign_ctx = invoking_context_for(
        ResolvedCommand("/home/op/.local/bin/agent-suite"),
        actor_uid=1000,
        actor_euid=1000,
        path_env="/home/op/.local/bin:/usr/bin",
    )
    assert foreign_ctx.actor.system_scoped is False
    assert foreign_ctx.box.system_scoped is True

    assert system_ctx.to_dict()["actor"] == ScopeContext(
        scope=ContextScope.ACTOR,
        bin_dir="/usr/local/bin",
        system_scoped=True,
        uid=1000,
        euid=1000,
        path_provenance="/usr/local/bin:/usr/bin",
        config_sources=(),
    ).to_dict()
    assert system_ctx.to_dict()["box"] == ScopeContext(
        scope=ContextScope.BOX,
        bin_dir=str(REFERENCE_BIN_DIR),
        system_scoped=True,
        uid=0,
        euid=None,
        path_provenance=f"systemd-unit:{SYSTEM_PATH}",
        config_sources=(str(SUITE_ENV_PATH),),
    ).to_dict()


def test_build_invoking_context_measures_real_uid_when_not_injected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without injected values the actor uid/euid/PATH are measured from the
    process, so the doctor (which does not know the schedule's resolved CLI) can
    build the same shape against its own invocation."""
    _treat_box_as_system_scoped(monkeypatch)
    ctx = build_invoking_context(
        actor_bin_dir=REFERENCE_BIN_DIR,
        path_env=None,
    )
    assert ctx.actor.uid is not None  # measured from this process
    assert ctx.actor.system_scoped is True
    assert ctx.box.system_scoped is True


@pytest.mark.skipif(
    sys.platform == "win32", reason="box scope is ownership-measured on POSIX only"
)
def test_box_scope_measurement_reports_user_writable_system_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The box-side system_scoped is a real measurement, not an assertion: when
    the pinned SYSTEM_PATH resolves to user-owned (agent-writable) directories —
    as on GitHub-hosted runners, where this suite runs — it reports False. This
    is what keeps the pinned value in the plumbing tests above honest."""
    assert tmp_path.stat().st_uid != 0  # owned by the (non-root) test user
    monkeypatch.setattr("agent_suite.schedule.SYSTEM_PATH", str(tmp_path))
    ctx = build_invoking_context(actor_bin_dir=REFERENCE_BIN_DIR, path_env=None)
    assert ctx.box.system_scoped is False


def test_install_refuses_non_system_bin_dir_records_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WI-038 (reversed): an install that resolves the CLI from a non-system bin
    dir is FAILED, writes nothing, and records the invoking context so the
    operator can see the actor bin dir that tripped the refusal."""
    _treat_box_as_system_scoped(monkeypatch)
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)  # a tmp dir — non-system by construction
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=_verifying_runner(bindir),
        which=_no_which,
        search_dirs=(bindir,),
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.FAILED for r in report.results)
    assert all("non-system bin directory" in r.detail for r in report.results)
    assert list(unit_dir.iterdir()) == []
    for r in report.results:
        assert r.invoking_context is not None
        assert r.invoking_context.actor.system_scoped is False
        assert r.invoking_context.box.system_scoped is True
        assert r.to_dict()["invoking_context"] == r.invoking_context.to_dict()


def test_install_records_invoking_context_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful system-scoped install records the invoking context with both
    scopes system-scoped."""
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
    _treat_as_system_scoped(monkeypatch, bindir)
    _treat_box_as_system_scoped(monkeypatch)
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(bindir,),
    )
    for r in report.results:
        assert r.status is InstallStatus.INSTALLED, r.detail
        ctx = r.invoking_context
        assert ctx is not None
        assert ctx.actor.system_scoped is True
        assert ctx.box.system_scoped is True
        assert ctx.actor.bin_dir == str(bindir)


def test_deploy_reference_copies_match_generator_output():
    """docs/operating-the-suite.md promises the reference copies in deploy/
    are identical to what `schedule install` generates — enforce it.

    Byte-equality between the copies and the generator, and nothing more: this
    test passed for the entire life of WI-045 because both sides were equally
    broken. It cannot catch a unit that does not run. That property is asserted
    by test_every_generated_execstart_is_an_absolute_path and
    test_shipped_reference_units_have_absolute_existing_prefix; keep them
    together so the pair is obvious to the next reader.
    """
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    for spec in SCHEDULES:
        assert (repo / "deploy/systemd" / f"{spec.name}.service").read_text() == (
            _systemd_service(spec)
        ), spec.name
        assert (repo / "deploy/systemd" / f"{spec.name}.timer").read_text() == (
            _systemd_timer(spec)
        ), spec.name
        assert (repo / "deploy/windows" / f"{spec.name}.ps1").read_text() == (
            _windows_task_script(spec)
        ), spec.name


# ---------------------------------------------------------------------------
# Windows scope logic (DEFECT 3) — exercised on this Linux host by mocking the
# OS surface (os.name / os.sep / sys.platform / USERPROFILE). The systemd unit
# PATH is always POSIX (a separate, Linux-only concern); the Windows-native
# path handling is for Scheduled-Task scope checks only. The two must not be
# conflated, or a win32 host produces backslash-joined ``\usr\local\sbin``
# against the unit's forward-slash literal.
# ---------------------------------------------------------------------------


def _mock_windows(monkeypatch: pytest.MonkeyPatch, *, userprofile: str) -> None:
    """Pretend to run under Windows so the win32 scope branches execute here.

    Patches ``sys.platform`` (what :func:`_is_system_owned` /
    :func:`_box_system_scoped` consult) and sets ``USERPROFILE``; pytest restores
    them after the test. ``os.name`` is deliberately NOT patched: Python 3.14's
    ``pathlib`` refuses to instantiate ``WindowsPath`` on Linux when ``os.name``
    is ``nt``, which would break every ``Path(...)`` in the code under test. The
    win32 scope logic keys off ``sys.platform``, so this still exercises the real
    branches; the uid helpers' ``os.name`` branch is covered separately by
    :func:`test_uid_helpers_return_none_under_windows`.
    """
    import agent_suite.schedule as sched

    monkeypatch.setattr(sched.sys, "platform", "win32")
    monkeypatch.setenv("USERPROFILE", userprofile)


def _fake_bins_in(bindir: Path) -> Path:
    bindir.mkdir(parents=True, exist_ok=True)
    for spec in SCHEDULES:
        exe = bindir / _command_name(spec)
        if not exe.exists():
            exe.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            exe.chmod(0o755)
    return bindir


def test_uid_helpers_return_none_under_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """On Windows there is no uid concept. The helpers key off ``sys.platform``
    (the same guard mypy narrows on when type-checking the win32 platform, where
    ``os.getuid``/``pwd`` do not exist); this patches it in isolation and
    confirms each returns ``None``."""
    from agent_suite.schedule import _current_euid, _current_uid, _system_unit_uid

    monkeypatch.setattr("sys.platform", "win32")
    assert _current_uid() is None
    assert _current_euid() is None
    assert _system_unit_uid() is None


def test_win32_system_path_is_posix_regardless_of_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFECT 3: the systemd unit PATH is always the POSIX ``SYSTEM_PATH``
    literal, even when the host reports as win32. It must never be re-derived
    from host-flavored Path objects (which join with backslashes on Windows)."""
    _mock_windows(monkeypatch, userprofile=str(tmp_path / "winuser"))
    path = _unit_path_value(_systemd_service(SCHEDULES[0]))
    assert path == SYSTEM_PATH
    assert "\\" not in path
    assert all(entry.startswith("/") for entry in path.split(":"))


def test_win32_scope_probe_refuses_user_profile_dir_accepts_system_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFECT 3: on win32 a directory under the user profile is user-scoped
    (refused), one outside it is system-scoped (accepted)."""
    _mock_windows(monkeypatch, userprofile=str(tmp_path / "winuser"))
    profile = tmp_path / "winuser"
    user_dir = profile / "AppData" / "Local" / "uv"  # under profile
    system_dir = tmp_path / "ProgramData" / "agent-suite" / "bin"  # outside profile
    assert is_system_scoped_bin_dir(user_dir) is False
    assert is_system_scoped_bin_dir(system_dir) is True


def test_win32_treat_as_system_scoped_helper_takes_effect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFECT 3: the ``_treat_as_system_scoped`` helper patches SYSTEM_BIN_DIRS,
    which the probe must consult FIRST on win32 too — otherwise the helper is a
    no-op and ~8 tests relying on it break (pytest ``tmp_path`` lives under
    ``%%USERPROFILE%%`` on Windows)."""
    _mock_windows(monkeypatch, userprofile=str(tmp_path / "winuser"))
    bindir = _fake_bins_in(tmp_path / "winuser" / "AppData" / "Local" / "Temp" / "bin")
    assert bindir.is_relative_to(tmp_path / "winuser")  # genuinely under the profile
    # Without the allowlist the win32 ownership check refuses it.
    assert is_system_scoped_bin_dir(bindir) is False
    # The helper's monkeypatch now takes effect on win32.
    _treat_as_system_scoped(monkeypatch, bindir)
    assert is_system_scoped_bin_dir(bindir) is True


def test_win32_invoking_context_box_system_scoped_and_profile_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFECT 2b/3: on win32 the box is measured system-scoped and the actor
    scope follows the profile rule (outside profile = system-scoped)."""
    _mock_windows(monkeypatch, userprofile=str(tmp_path / "winuser"))
    outside = invoking_context_for(
        ResolvedCommand(str(tmp_path / "ProgramData" / "agent-suite" / "agent-suite")),
        path_env="C:/Program Files/agent-suite/bin",
    )
    assert outside.box.system_scoped is True
    assert outside.actor.system_scoped is True  # outside the profile

    inside = invoking_context_for(
        ResolvedCommand(str(tmp_path / "winuser" / "AppData" / "bin" / "agent-suite")),
        path_env="C:/Users/winuser/AppData",
    )
    assert inside.box.system_scoped is True
    assert inside.actor.system_scoped is False  # under the profile


def test_win32_install_accepts_system_scoped_bin_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """DEFECT 3: a Windows Scheduled-Task install resolves cleanly when the CLI
    is outside the user profile (system-scoped), and is refused when under it."""
    _mock_windows(monkeypatch, userprofile=str(tmp_path / "winuser"))
    system_bin = _fake_bins_in(tmp_path / "ProgramData" / "agent-suite" / "bin")
    report = install_schedules(
        os_target=OSTarget.WINDOWS_TASK,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(system_bin,),
    )
    assert all(r.status is InstallStatus.INSTALLED for r in report.results), [
        r.detail for r in report.results
    ]

    user_bin = _fake_bins_in(tmp_path / "winuser" / "AppData" / "bin")
    refused = install_schedules(
        os_target=OSTarget.WINDOWS_TASK,
        dry_run=True,
        runner=StubRunner(),
        which=_no_which,
        search_dirs=(user_bin,),
    )
    assert all(r.status is InstallStatus.FAILED for r in refused.results)
    assert all("non-system bin directory" in r.detail for r in refused.results)
