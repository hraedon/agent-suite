from __future__ import annotations

import io
import contextlib
import json

import pytest

from agent_suite import bootstrap as bootstrap_mod
from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite import onboard as onboard_mod
from agent_suite import schedule as schedule_mod
from agent_suite import upgrade as upgrade_mod
from agent_suite import verify_restore as verify_restore_mod
from agent_suite.alerting import AlertResult, EmissionStatus
from agent_suite.cli import Command, main

_DSN = "postgresql://regista_service@suite-db.example:5432/regista"


def _stub_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub lock I/O and regista-quad reads so CLI tests don't shell out or write."""
    monkeypatch.setattr(lock_mod, "read_regista_quad", lambda **kw: None)
    monkeypatch.setattr(lock_mod, "write_lock_file", lambda lock, path=None: None)
    monkeypatch.setattr(lock_mod, "load_lock_file", lambda path=None: None)


def _stub_aggregate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    suite_ok: bool = False,
    with_post_restore: bool = False,
) -> None:
    post_restore = None
    if with_post_restore:
        post_restore = verify_restore_mod.VerifyRestoreResult(ok=True, projects=[])
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=suite_ok, components=[], post_restore=post_restore
        ),
    )


def _stub_bootstrap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        bootstrap_mod,
        "run_bootstrap",
        lambda **kw: bootstrap_mod.BootstrapResult(ok=True, dry_run=False, steps=[]),
    )


def _stub_onboard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        onboard_mod,
        "run_onboard",
        lambda **kw: onboard_mod.OnboardResult(
            ok=True, dry_run=False, project="project-slug",
            spec_anchored=False, spec_version=None,
            spec_version_recognized=None, steps=[],
        ),
    )


def _stub_verify_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_restore_mod,
        "verify_restore",
        lambda **kw: verify_restore_mod.VerifyRestoreResult(ok=True, projects=[]),
    )


def _stub_upgrade(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        upgrade_mod,
        "run_upgrade",
        lambda **kw: upgrade_mod.UpgradeResult(ok=True, dry_run=False, check_only=False, component_filter=None),
    )
    monkeypatch.setattr(
        upgrade_mod,
        "check_advancements",
        lambda **kw: upgrade_mod.AdvancementReport(advancements=[], note="no advancements"),
    )
    monkeypatch.setattr(
        upgrade_mod,
        "run_rollback",
        lambda **kw: upgrade_mod.RollbackResult(
            ok=True, status=upgrade_mod.RollbackStatus.APPLIED, target_ref="",
        ),
    )


def _stub_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        schedule_mod,
        "install_schedules",
        lambda **kw: schedule_mod.ScheduleReport(
            os_target=schedule_mod.OSTarget.SYSTEMD,
            results=[
                schedule_mod.ScheduleResult(
                    kind=schedule_mod.ScheduleKind.BACKUP_VERIFY,
                    status=schedule_mod.InstallStatus.INSTALLED,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        schedule_mod,
        "remove_schedules",
        lambda **kw: schedule_mod.ScheduleReport(
            os_target=schedule_mod.OSTarget.SYSTEMD,
            results=[
                schedule_mod.ScheduleResult(
                    kind=schedule_mod.ScheduleKind.BACKUP_VERIFY,
                    status=schedule_mod.InstallStatus.REMOVED,
                )
            ],
        ),
    )


def _stub_alert_check(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_suite import alerting as alerting_mod

    monkeypatch.setattr(
        alerting_mod,
        "run_alert_check",
        lambda **kw: AlertResult(
            suite_ok=True, alert_kind=None, emission=EmissionStatus.SKIPPED_NO_STATE_CHANGE,
        ),
    )


def test_subcommands_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    _stub_lock(monkeypatch)
    _stub_bootstrap(monkeypatch)
    _stub_onboard(monkeypatch)
    _stub_verify_restore(monkeypatch)
    _stub_upgrade(monkeypatch)
    _stub_schedule(monkeypatch)
    _stub_alert_check(monkeypatch)
    for command in Command:
        if command is Command.SCHEDULE:
            assert main([command.value, "list"]) == 0
        elif command is Command.ONBOARD:
            assert main([command.value, "project-slug"]) == 0
        else:
            assert main([command.value]) == 0


def test_lock_check_exits_nonzero_when_no_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    _stub_lock(monkeypatch)
    assert main(["lock", "--check"]) == 1


def test_lock_check_exits_nonzero_on_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    from agent_suite.lock import ComponentPin, SuiteLock

    existing = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="hraedon/dossier", version="0.1.0")},
    )
    monkeypatch.setattr(lock_mod, "load_lock_file", lambda path=None: existing)
    monkeypatch.setattr(lock_mod, "read_regista_quad", lambda **kw: None)
    assert main(["lock", "--check"]) == 1


def test_doctor_exit_code_nonzero_when_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    assert main(["doctor", "--exit-code"]) == 1


def test_doctor_exit_code_zero_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    assert main(["doctor", "--exit-code"]) == 0


def test_doctor_json_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["suite_ok"] is True
    assert "components" in parsed and "lock" in parsed
    assert "matches" in parsed["lock"]


def test_doctor_verify_restore_wires_post_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True, with_post_restore=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json", "--verify-restore", "--restore-dsn", _DSN])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "post_restore" in parsed
    assert parsed["post_restore"]["ok"] is True


def test_doctor_verify_restore_text_includes_section(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True, with_post_restore=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--verify-restore", "--restore-dsn", _DSN])
    assert rc == 0
    out = buf.getvalue()
    assert "post-restore verification" in out


def test_doctor_without_verify_restore_has_no_post_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    _stub_verify_restore(monkeypatch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "post_restore" not in parsed


def test_doctor_verify_restore_exit_code_nonzero_when_post_restore_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=False,
            components=[],
            post_restore=verify_restore_mod.VerifyRestoreResult(ok=False, projects=[]),
        ),
    )
    assert main(["doctor", "--verify-restore", "--restore-dsn", _DSN, "--exit-code"]) == 1


def test_doctor_verify_restore_errors_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    monkeypatch.delenv("REGISTA_DSN", raising=False)
    monkeypatch.setenv("AGENT_SUITE_CONFIG", "/nonexistent/suite.env")
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = main(["doctor", "--verify-restore"])
    assert rc == 1
    assert "no DSN" in err.getvalue()
    assert "REGISTA_DSN" in err.getvalue()


def test_doctor_verify_restore_uses_regista_dsn_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True, with_post_restore=True)
    monkeypatch.setenv("REGISTA_DSN", _DSN)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json", "--verify-restore"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "post_restore" in parsed


def test_lock_json_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    _stub_lock(monkeypatch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["lock", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "suite" in parsed
    assert "components" in parsed


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main([])
