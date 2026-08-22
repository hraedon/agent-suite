"""Unit tests for the backup / restore module."""

from __future__ import annotations

import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_suite.backup import (
    RESTORE_PARTIAL_REMEDY,
    BackupResult,
    BackupStatus,
    BackupStep,
    BackupStepResult,
    RestoreResult,
    RestoreStep,
    RestoreStepResult,
    _mask_dsn,
    _split_dsn_password,
    classify_pg_restore,
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


def test_split_uri_dsn_preserves_username_and_decodes_password() -> None:
    dsn = (
        "postgresql://DB-SERVICE-ACCOUNT:p%40ss%3Aword@suite-db.example:5432/"
        "regista?sslmode=require"
    )

    safe_dsn, password = _split_dsn_password(dsn)

    assert safe_dsn == (
        "postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/"
        "regista?sslmode=require"
    )
    assert password == "p@ss:word"


def test_split_uri_dsn_preserves_ipv6_host() -> None:
    safe_dsn, password = _split_dsn_password(
        "postgresql://svc:secret@[2001:db8::1]:5432/regista"
    )

    assert safe_dsn == "postgresql://svc@[2001:db8::1]:5432/regista"
    assert password == "secret"


def test_split_uri_dsn_without_password_is_unchanged() -> None:
    dsn = "postgresql://svc@suite-db.example:5432/regista"

    assert _split_dsn_password(dsn) == (dsn, None)


@pytest.fixture(autouse=True)
def _clear_regista_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep these tests hermetic: ``run_backup``/``run_restore`` fall back to
    ``$REGISTA_DSN`` when ``dsn`` is None, so a host that exports a real DSN
    (e.g. an operator box) would otherwise turn the ``dsn=None`` cases green.
    """
    monkeypatch.delenv("REGISTA_DSN", raising=False)


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


# ---------------------------------------------------------------------------
# WI-054 — a non-zero pg_restore is never DONE
# ---------------------------------------------------------------------------

#: The exact stderr shape that used to be downgraded to DONE. pg_restore emits
#: this when an object could not be created, and it exits 1 having *skipped* it.
_PG_RESTORE_ALREADY_EXISTS = _completed(
    returncode=1,
    stderr=(
        "pg_restore: error: could not execute query: ERROR:  relation "
        '"events" already exists\n'
        "pg_restore: warning: errors ignored on restore: 3\n"
    ),
)

_PG_RESTORE_NO_MATCHING = _completed(
    returncode=1,
    stderr="pg_restore: warning: no matching schemas were found\n",
)


def test_classify_pg_restore_zero_exit_is_done() -> None:
    verdict = classify_pg_restore(returncode=0, stderr="", dump_path="/b/database.dump")
    assert verdict.status is BackupStatus.DONE
    assert verdict.errors_ignored == 0


@pytest.mark.parametrize(
    "stderr",
    [
        'ERROR:  relation "events" already exists',
        "pg_restore: warning: no matching schemas were found",
        "ERROR:  permission denied for schema public",
        "",
    ],
)
def test_no_prose_can_turn_a_non_zero_pg_restore_into_success(stderr: str) -> None:
    """The WI-054 defect, pinned.

    ``"already exists"`` and ``"no matching"`` used to return DONE; every other
    message returned FAILED. Both readings came from scanning the message. The
    exit code is now the whole decision, so the first two rows here are no longer
    special — and none of them is success.
    """
    verdict = classify_pg_restore(returncode=1, stderr=stderr, dump_path="/b/d.dump")
    assert verdict.status is BackupStatus.PARTIAL
    assert verdict.status is not BackupStatus.DONE


def test_classify_pg_restore_reports_the_count_pg_restore_itself_computed() -> None:
    """The one number pg_restore emits that is structured, not prose."""
    verdict = classify_pg_restore(
        returncode=1,
        stderr=_PG_RESTORE_ALREADY_EXISTS.stderr,
        dump_path="/b/d.dump",
    )
    assert verdict.errors_ignored == 3
    assert "3 object(s) skipped" in verdict.detail


def test_classify_pg_restore_says_so_when_no_count_was_reported() -> None:
    verdict = classify_pg_restore(returncode=1, stderr="boom", dump_path="/b/d.dump")
    assert verdict.errors_ignored is None
    assert "not reported by pg_restore" in verdict.detail


@pytest.mark.parametrize(
    "restore_result", [_PG_RESTORE_ALREADY_EXISTS, _PG_RESTORE_NO_MATCHING]
)
def test_restore_with_skipped_objects_is_not_ok_even_when_verification_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    restore_result: subprocess.CompletedProcess[str],
) -> None:
    """The fail-open case this change closes.

    ``verify_restore`` replays the chain, and a chain can verify perfectly while
    an unrelated table never came back. Before WI-054 this combination reported
    ``restore: OK`` over a database missing objects.
    """
    _stub_verify_restore_ok(monkeypatch)
    (tmp_path / "database.dump").write_bytes(b"dump")
    runner = StubRunner({
        ("agent-suite", "doctor"): _DOCTOR_OK,
        ("pg_restore",): restore_result,
    })

    result = run_restore(
        backup_dir=tmp_path, dsn=_DSN, runner=runner, installed=_installed_all
    )

    statuses = {s.step: s.status for s in result.steps}
    assert statuses[RestoreStep.PG_RESTORE] is BackupStatus.PARTIAL
    assert result.ok is False
    assert "skipped objects" in result.note


def test_a_partial_pg_restore_still_runs_the_verification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """verify_restore is the authority on the store, so it must always speak.

    The old code returned early on any pg_restore it did not tolerate, leaving
    the operator with a half-restored database and no verdict on it.
    """
    _stub_verify_restore_ok(monkeypatch)
    (tmp_path / "database.dump").write_bytes(b"dump")
    runner = StubRunner({
        ("agent-suite", "doctor"): _DOCTOR_OK,
        ("pg_restore",): _completed(returncode=1, stderr="ERROR:  permission denied"),
    })

    result = run_restore(
        backup_dir=tmp_path, dsn=_DSN, runner=runner, installed=_installed_all
    )

    reached = [s.step for s in result.steps]
    assert RestoreStep.VERIFY_RESTORE in reached
    assert RestoreStep.POST_DOCTOR in reached
    assert result.ok is False


def test_a_partial_restore_whose_verification_fails_reports_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_verify_restore_fail(monkeypatch)
    (tmp_path / "database.dump").write_bytes(b"dump")
    runner = StubRunner({
        ("agent-suite", "doctor"): _DOCTOR_OK,
        ("pg_restore",): _PG_RESTORE_ALREADY_EXISTS,
    })

    result = run_restore(
        backup_dir=tmp_path, dsn=_DSN, runner=runner, installed=_installed_all
    )

    statuses = {s.step: s.status for s in result.steps}
    assert statuses[RestoreStep.PG_RESTORE] is BackupStatus.PARTIAL
    assert statuses[RestoreStep.VERIFY_RESTORE] is BackupStatus.FAILED
    assert result.ok is False


def test_partial_names_the_remedy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Same convention as verify-restore (99df507): a report names its remedy."""
    _stub_verify_restore_ok(monkeypatch)
    (tmp_path / "database.dump").write_bytes(b"dump")
    runner = StubRunner({
        ("agent-suite", "doctor"): _DOCTOR_OK,
        ("pg_restore",): _PG_RESTORE_ALREADY_EXISTS,
    })

    result = run_restore(
        backup_dir=tmp_path, dsn=_DSN, runner=runner, installed=_installed_all
    )
    text = format_restore_text(result)
    assert RESTORE_PARTIAL_REMEDY.split(";")[0] in text
    assert "NOT OK" in text
