"""Unit tests for the backup / restore module."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from agent_suite.backup import (
    BackupResult,
    BackupStatus,
    BackupStep,
    BackupStepResult,
    RestoreResult,
    RestoreStep,
    RestoreStepResult,
    _mask_dsn,
    format_backup_text,
    format_restore_text,
    run_backup,
    run_restore,
)
from agent_suite.evidence import EvidenceExportResult
from agent_suite.verify_restore import VerifyRestoreResult


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


class StubRunner:
    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str]]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                return out
        return _completed(stdout="{}", returncode=0)


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _installed_except(*missing: str):
    def check(cli: str) -> bool:
        return cli not in missing
    return check


_DOCTOR_OK = _completed(stdout='{"suite_ok": true, "components": []}')

_DSN = "postgresql://DB-SERVICE-ACCOUNT:secretpw@suite-db.example:5432/regista"

_DUMP_OK = _completed(stdout="", returncode=0)

_RESTORE_OK = _completed(stdout="", returncode=0)


def _stub_verify_restore_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_suite.backup.verify_restore",
        lambda **kw: VerifyRestoreResult(ok=True, projects=[], note="ok"),
    )


def _stub_verify_restore_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_suite.backup.verify_restore",
        lambda **kw: VerifyRestoreResult(ok=False, projects=[], note="drift detected"),
    )


def _stub_evidence_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_suite.backup.run_evidence_export",
        lambda **kw: EvidenceExportResult(
            ok=True, output_dir=str(kw.get("output_dir", "/tmp")),
            projects=[], manifest_path="manifest.json", note="ok",
        ),
    )


# --- backup dry-run ----------------------------------------------------------


def test_backup_dry_run(tmp_path: Path) -> None:
    result = run_backup(
        backup_dir=tmp_path,
        dsn=_DSN,
        dry_run=True,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.dry_run is True
    pre_doctor = next(s for s in result.steps if s.step is BackupStep.PRE_DOCTOR)
    assert pre_doctor.status is BackupStatus.DONE
    for step in result.steps:
        if step.step is BackupStep.PRE_DOCTOR:
            continue
        assert step.status is BackupStatus.PENDING


# --- backup no DSN -----------------------------------------------------------


def test_backup_no_dsn(tmp_path: Path) -> None:
    result = run_backup(
        backup_dir=tmp_path,
        dsn=None,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_all,
    )
    assert result.ok is False
    pg_step = next(s for s in result.steps if s.step is BackupStep.PG_DUMP)
    assert pg_step.status is BackupStatus.FAILED


# --- backup pg_dump not installed --------------------------------------------


def test_backup_pg_dump_not_installed(tmp_path: Path) -> None:
    result = run_backup(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_except("pg_dump"),
    )
    assert result.ok is False
    pg_step = next(s for s in result.steps if s.step is BackupStep.PG_DUMP)
    assert pg_step.status is BackupStatus.FAILED


# --- backup success ----------------------------------------------------------


def test_backup_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_verify_restore_ok(monkeypatch)
    _stub_evidence_ok(monkeypatch)

    def _write_dump(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("pg_dump",):
            dump_path = Path(cmd[-1].split("=", 1)[1])
            dump_path.write_bytes(b"dump content")
            return _completed(returncode=0)
        return _DOCTOR_OK

    result = run_backup(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=_write_dump,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.manifest_path is not None
    assert Path(result.manifest_path).exists()
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[BackupStep.PRE_DOCTOR] is BackupStatus.DONE
    assert statuses[BackupStep.PG_DUMP] is BackupStatus.DONE
    assert statuses[BackupStep.VERIFY_DUMP] is BackupStatus.DONE
    assert statuses[BackupStep.EVIDENCE_EXPORT] is BackupStatus.DONE
    assert statuses[BackupStep.MANIFEST] is BackupStatus.DONE


# --- backup verify failure ---------------------------------------------------


def test_backup_verify_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_verify_restore_fail(monkeypatch)
    _stub_evidence_ok(monkeypatch)

    def _write_dump(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("pg_dump",):
            dump_path = Path(cmd[-1].split("=", 1)[1])
            dump_path.write_bytes(b"dump content")
            return _completed(returncode=0)
        return _DOCTOR_OK

    result = run_backup(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=_write_dump,
        installed=_installed_all,
    )
    assert result.ok is False
    verify_step = next(s for s in result.steps if s.step is BackupStep.VERIFY_DUMP)
    assert verify_step.status is BackupStatus.FAILED
    step_kinds = {s.step for s in result.steps}
    assert BackupStep.EVIDENCE_EXPORT not in step_kinds
    assert BackupStep.MANIFEST not in step_kinds


# --- backup manifest no secrets ----------------------------------------------


def test_backup_manifest_no_secrets(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_verify_restore_ok(monkeypatch)
    _stub_evidence_ok(monkeypatch)

    def _write_dump(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("pg_dump",):
            dump_path = Path(cmd[-1].split("=", 1)[1])
            dump_path.write_bytes(b"dump content")
            return _completed(returncode=0)
        return _DOCTOR_OK

    result = run_backup(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=_write_dump,
        installed=_installed_all,
    )
    assert result.manifest_path is not None
    manifest_text = Path(result.manifest_path).read_text()
    assert "secretpw" not in manifest_text
    assert "***:***" in manifest_text


# --- restore dry-run ---------------------------------------------------------


def test_restore_dry_run(tmp_path: Path) -> None:
    result = run_restore(
        backup_dir=tmp_path,
        dsn=_DSN,
        dry_run=True,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.dry_run is True
    pre_doctor = next(s for s in result.steps if s.step is RestoreStep.PRE_DOCTOR)
    assert pre_doctor.status is BackupStatus.DONE
    for step in result.steps:
        if step.step is RestoreStep.PRE_DOCTOR:
            continue
        assert step.status is BackupStatus.PENDING


# --- restore no DSN ----------------------------------------------------------


def test_restore_no_dsn(tmp_path: Path) -> None:
    result = run_restore(
        backup_dir=tmp_path,
        dsn=None,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_all,
    )
    assert result.ok is False
    pg_step = next(s for s in result.steps if s.step is RestoreStep.PG_RESTORE)
    assert pg_step.status is BackupStatus.FAILED


# --- restore dump missing ----------------------------------------------------


def test_restore_dump_missing(tmp_path: Path) -> None:
    result = run_restore(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=StubRunner({("agent-suite", "doctor"): _DOCTOR_OK}),
        installed=_installed_all,
    )
    assert result.ok is False
    pg_step = next(s for s in result.steps if s.step is RestoreStep.PG_RESTORE)
    assert pg_step.status is BackupStatus.FAILED
    assert "not found" in pg_step.detail


# --- restore success ---------------------------------------------------------


def test_restore_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_verify_restore_ok(monkeypatch)
    dump_path = tmp_path / "database.dump"
    dump_path.write_bytes(b"dump content")

    def _runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("pg_restore",):
            return _RESTORE_OK
        return _DOCTOR_OK

    result = run_restore(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=_runner,
        installed=_installed_all,
    )
    assert result.ok is True
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[RestoreStep.PRE_DOCTOR] is BackupStatus.DONE
    assert statuses[RestoreStep.PG_RESTORE] is BackupStatus.DONE
    assert statuses[RestoreStep.VERIFY_RESTORE] is BackupStatus.DONE
    assert statuses[RestoreStep.POST_DOCTOR] is BackupStatus.DONE


# --- restore verify failure --------------------------------------------------


def test_restore_verify_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_verify_restore_fail(monkeypatch)
    dump_path = tmp_path / "database.dump"
    dump_path.write_bytes(b"dump content")

    def _runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd[:2] == ("pg_restore",):
            return _RESTORE_OK
        return _DOCTOR_OK

    result = run_restore(
        backup_dir=tmp_path,
        dsn=_DSN,
        runner=_runner,
        installed=_installed_all,
    )
    assert result.ok is False
    verify_step = next(
        s for s in result.steps if s.step is RestoreStep.VERIFY_RESTORE
    )
    assert verify_step.status is BackupStatus.FAILED
    step_kinds = {s.step for s in result.steps}
    assert RestoreStep.POST_DOCTOR not in step_kinds


# --- _mask_dsn ----------------------------------------------------------------


def test_mask_dsn() -> None:
    masked = _mask_dsn("postgresql://user:password@host:5432/db")
    assert "password" not in masked
    assert "user" not in masked
    assert "***:***" in masked
    assert "host:5432/db" in masked

    masked_no_creds = _mask_dsn("postgresql://host:5432/db")
    assert masked_no_creds == "postgresql://host:5432/db"

    masked_no_scheme = _mask_dsn("just-a-string")
    assert masked_no_scheme == "just-a-string"


# --- format functions --------------------------------------------------------


def test_format_backup_text() -> None:
    result = BackupResult(
        ok=True,
        dry_run=False,
        backup_dir="/tmp/backup",
        steps=[
            BackupStepResult(BackupStep.PRE_DOCTOR, BackupStatus.DONE, "ok"),
        ],
        manifest_path="/tmp/backup/manifest.json",
        note="ok",
    )
    text = format_backup_text(result)
    assert len(text) > 0
    assert "backup" in text


def test_format_restore_text() -> None:
    result = RestoreResult(
        ok=True,
        dry_run=False,
        backup_dir="/tmp/backup",
        steps=[
            RestoreStepResult(RestoreStep.PRE_DOCTOR, BackupStatus.DONE, "ok"),
        ],
        note="ok",
    )
    text = format_restore_text(result)
    assert len(text) > 0
    assert "restore" in text
