"""Unit tests for the schedule module — file generation, install, remove, OS detection.

All tests use stubbed runners — no real systemd or Windows.
"""

from __future__ import annotations

import shlex
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_suite.schedule import (
    REFERENCE_BIN_DIR,
    SCHEDULES,
    InstallStatus,
    OSTarget,
    ResolvedCommand,
    ScheduleKind,
    ScheduleReport,
    ScheduleResult,
    _systemd_service,
    _systemd_timer,
    _windows_task_script,
    check_exec_start_runnable,
    format_schedule_report,
    generate_schedule_files,
    install_schedules,
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


def test_install_dry_run_prints_files(tmp_path: Path) -> None:
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_dry_run_windows(tmp_path: Path) -> None:
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_systemd_writes_files_and_enables(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_fails_on_systemctl_error(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_fails_when_systemd_parses_a_different_execstart(tmp_path: Path) -> None:
    """Verification reads systemd's own parse, not the string we just wrote.

    Stub systemd into reporting the pre-fix bare name: install must refuse to
    call that installed, even though the file on disk is ours.
    """
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_fails_when_the_timer_did_not_arm(tmp_path: Path) -> None:
    """`enable --now` returning 0 is not evidence the timer is running."""
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
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


def test_install_reports_the_checks_that_actually_passed(tmp_path: Path) -> None:
    """An INSTALLED result names its evidence; presence of a file is not evidence."""
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    bindir = _fake_bin_dir(tmp_path)
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


def test_doctor_alert_unit_pins_explicit_path_from_resolved_bin_dir() -> None:
    """WI-038: the unit runs as root with systemd's stripped PATH, but the doctor
    ``alert-check`` shells out to resolves component CLIs via the process PATH
    (``shutil.which`` + subprocess). Without an explicit PATH the scheduled doctor
    sees a different estate than the operator. The unit pins a PATH whose first
    entry is the directory the installer resolved ``ExecStart`` from, so the
    root-run doctor resolves the same binaries the operator installed."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    resolved = ResolvedCommand("/opt/agent-suite/bin/agent-suite", "alert-check")
    unit = _systemd_service(spec, resolved=resolved)
    assert _unit_path_value(unit).split(":")[0] == "/opt/agent-suite/bin"


def test_unit_path_renders_before_environment_file() -> None:
    """The pinned PATH is a unit-level default the operator's ``suite.env`` may
    override, so it must render before ``EnvironmentFile`` (file-beats-unit)."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    unit = _systemd_service(spec, resolved=ResolvedCommand("/opt/x/bin/agent-suite", ""))
    assert unit.index("Environment=PATH=") < unit.index("EnvironmentFile=")


def test_reference_unit_path_first_entry_is_reference_bin_dir() -> None:
    """The deploy/ reference rendering pins ``REFERENCE_BIN_DIR`` first, so a
    reference copy installed verbatim on a system-scoped host resolves the system
    component CLIs rather than nothing."""
    spec = next(s for s in SCHEDULES if s.kind is ScheduleKind.DOCTOR_ALERT)
    assert _unit_path_value(_systemd_service(spec)).split(":")[0] == str(REFERENCE_BIN_DIR)


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
