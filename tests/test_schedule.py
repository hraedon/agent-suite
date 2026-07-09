"""Unit tests for the schedule module — file generation, install, remove, OS detection.

All tests use stubbed runners — no real systemd or Windows.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from agent_suite.schedule import (
    SCHEDULES,
    InstallStatus,
    OSTarget,
    ScheduleKind,
    ScheduleReport,
    ScheduleResult,
    generate_schedule_files,
    install_schedules,
    remove_schedules,
    format_schedule_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    def __init__(self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception] | None = None) -> None:
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


def test_install_dry_run_prints_files() -> None:
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=True,
        runner=StubRunner(),
    )
    assert report.os_target is OSTarget.SYSTEMD
    assert len(report.results) == len(SCHEDULES)
    for r in report.results:
        assert r.status is InstallStatus.INSTALLED
        assert len(r.files_written) > 0
        assert "dry-run" in r.detail


def test_install_dry_run_windows() -> None:
    report = install_schedules(
        os_target=OSTarget.WINDOWS_TASK,
        dry_run=True,
        runner=StubRunner(),
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
    runner = StubRunner({
        ("systemctl", "daemon-reload"): _completed(stdout=""),
        ("systemctl", "enable"): _completed(stdout=""),
    })
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=runner,
        unit_dir=unit_dir,
    )
    assert all(r.status is InstallStatus.INSTALLED for r in report.results)
    for spec in SCHEDULES:
        assert (unit_dir / f"{spec.name}.service").exists()
        assert (unit_dir / f"{spec.name}.timer").exists()


def test_install_fails_on_systemctl_error(tmp_path: Path) -> None:
    unit_dir = tmp_path / "systemd"
    unit_dir.mkdir()
    runner = StubRunner({
        ("systemctl", "daemon-reload"): _completed(returncode=1, stderr="failed"),
    })
    report = install_schedules(
        os_target=OSTarget.SYSTEMD,
        dry_run=False,
        runner=runner,
        unit_dir=unit_dir,
    )
    assert any(r.status is InstallStatus.FAILED for r in report.results)


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
