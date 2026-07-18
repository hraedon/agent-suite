from __future__ import annotations

import io
import contextlib
import json
from pathlib import Path

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
from agent_suite.harness import HarnessTarget

_DSN = "postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista"


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
            ok=True,
            dry_run=False,
            project="project-slug",
            spec_anchored=False,
            spec_version=None,
            spec_version_recognized=None,
            steps=[],
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
        lambda **kw: upgrade_mod.UpgradeResult(
            ok=True, dry_run=False, check_only=False, component_filter=None
        ),
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
            ok=True,
            status=upgrade_mod.RollbackStatus.APPLIED,
            target_ref="",
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
            suite_ok=True,
            alert_kind=None,
            emission=EmissionStatus.SKIPPED_NO_STATE_CHANGE,
        ),
    )


def _stub_evidence_export(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_suite import evidence as evidence_mod

    monkeypatch.setattr(
        evidence_mod,
        "run_evidence_export",
        lambda **kw: evidence_mod.EvidenceExportResult(
            ok=True,
            output_dir="/tmp/test-evidence",
            projects=[],
            manifest_path=None,
            note="ok",
        ),
    )


def _stub_backup_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_suite import backup as backup_mod

    monkeypatch.setattr(
        backup_mod,
        "run_backup",
        lambda **kw: backup_mod.BackupResult(
            ok=True,
            dry_run=kw.get("dry_run", False),
            backup_dir=str(kw.get("backup_dir", "/tmp/test-backup")),
            steps=[],
            manifest_path=None,
            note="ok",
        ),
    )
    monkeypatch.setattr(
        backup_mod,
        "run_restore",
        lambda **kw: backup_mod.RestoreResult(
            ok=True,
            dry_run=kw.get("dry_run", False),
            backup_dir=str(kw.get("backup_dir", "/tmp/test-backup")),
            steps=[],
            note="ok",
        ),
    )


def _stub_deploy(monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_suite import deploy as deploy_mod

    monkeypatch.setattr(
        deploy_mod,
        "run_bootstrap",
        lambda **kw: bootstrap_mod.BootstrapResult(
            ok=True, dry_run=kw.get("dry_run", False), steps=[]
        ),
    )
    monkeypatch.setattr(
        deploy_mod,
        "run_onboard",
        lambda **kw: onboard_mod.OnboardResult(
            ok=True,
            dry_run=kw.get("dry_run", False),
            project="test",
            spec_anchored=False,
            spec_version=None,
            spec_version_recognized=None,
            steps=[],
        ),
    )
    monkeypatch.setattr(
        deploy_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=True, components=[], post_restore=None),
    )
    monkeypatch.setattr(deploy_mod, "load_lock_file", lambda path=None: None)
    monkeypatch.setattr(
        deploy_mod,
        "check_drift",
        lambda *a, **kw: type("DR", (), {"matches": True, "to_dict": lambda s: {}})(),
    )
    monkeypatch.setattr(
        deploy_mod,
        "generate_lock",
        lambda **kw: lock_mod.SuiteLock(
            version=1,
            components={},
            regista_quad=None,
            memory_engine="native",
        ),
    )
    monkeypatch.setattr(deploy_mod, "write_lock_file", lambda lock, path=None: None)


def test_subcommands_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    _stub_lock(monkeypatch)
    _stub_bootstrap(monkeypatch)
    _stub_onboard(monkeypatch)
    _stub_verify_restore(monkeypatch)
    _stub_upgrade(monkeypatch)
    _stub_schedule(monkeypatch)
    _stub_alert_check(monkeypatch)
    _stub_evidence_export(monkeypatch)
    _stub_backup_restore(monkeypatch)
    _stub_deploy(monkeypatch)
    for command in Command:
        if command is Command.SCHEDULE:
            assert main([command.value, "list"]) == 0
        elif command is Command.ONBOARD:
            assert main([command.value, "project-slug"]) == 0
        elif command is Command.PREFLIGHT:
            assert main([command.value]) == 1
        elif command is Command.SETUP_INSTALL:
            assert main([command.value, "--dry-run"]) == 1
        elif command is Command.DUAL_CONTROL:
            assert main([command.value, "list", "--store-path", "/tmp/test-dc-store.json"]) == 0
        elif command is Command.DEPLOY:
            assert main([command.value, "--dry-run"]) == 0
        elif command is Command.EXPORT_EVIDENCE:
            assert main([command.value, "--output", "/tmp/test-evidence"]) == 0
        elif command is Command.BACKUP:
            assert main([command.value, "--dir", "/tmp/test-backup", "--dry-run"]) == 0
        elif command is Command.RESTORE:
            assert main([command.value, "--dir", "/tmp/test-backup", "--dry-run"]) == 0
        elif command is Command.CODEX_PLUGINS:
            # dry-run install is hermetic (never shells codex) and exits 2
            assert main([command.value, "install", "--dry-run"]) == 2
        elif command is Command.INVENTORY:
            # Redirect the artifact write so the test doesn't clobber the
            # committed data/candidate-inventory.json with stub output.
            from agent_suite import inventory as inventory_mod

            monkeypatch.setattr(
                inventory_mod,
                "_default_inventory_path",
                lambda: Path("/tmp/test-candidate-inventory.json"),
            )
            assert main([command.value]) == 0
        else:
            assert main([command.value]) == 0


def test_codex_plugin_profiles_are_accepted() -> None:
    for profile in ("core", "credentialed", "full"):
        assert main(["codex-plugins", "install", "--profile", profile, "--dry-run"]) == 2


def test_codex_health_applies_marketplace_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite import codex_health as codex_health_mod

    seen: dict[str, object] = {}

    def fake_health(**kwargs: object) -> codex_health_mod.CodexHealthReport:
        seen.update(kwargs)
        return codex_health_mod.CodexHealthReport(
            ok=True,
            ready=True,
            codex_installed=True,
        )

    monkeypatch.setattr(codex_health_mod, "check_codex_health", fake_health)
    assert main(["codex-plugins", "health", "--marketplace", "local-proof"]) == 0
    catalog = seen["catalog"]
    assert isinstance(catalog, tuple)
    assert all(entry.marketplace == "local-proof" for entry in catalog)


def test_codex_marketplace_build_requires_explicit_output() -> None:
    assert main(["codex-plugins", "build-marketplace"]) == 2


@pytest.mark.parametrize("command", ["bootstrap", "onboard", "deploy"])
def test_harness_selectors_accept_codex(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
) -> None:
    seen: dict[str, object] = {}

    if command == "bootstrap":
        monkeypatch.setattr(
            bootstrap_mod,
            "run_bootstrap",
            lambda **kw: (
                seen.update(kw) or bootstrap_mod.BootstrapResult(ok=True, dry_run=True, steps=[])
            ),
        )
        argv = [command, "--harness", "codex", "--dry-run"]
    elif command == "onboard":
        monkeypatch.setattr(
            onboard_mod,
            "run_onboard",
            lambda **kw: (
                seen.update(kw)
                or onboard_mod.OnboardResult(
                    ok=True,
                    dry_run=True,
                    project="project-slug",
                    spec_anchored=False,
                    spec_version=None,
                    spec_version_recognized=None,
                    steps=[],
                )
            ),
        )
        argv = [command, "project-slug", "--harness", "codex", "--dry-run"]
    else:
        from agent_suite import deploy as deploy_mod

        monkeypatch.setattr(
            deploy_mod,
            "run_deploy",
            lambda **kw: (
                seen.update(kw)
                or deploy_mod.DeployResult(ok=True, dry_run=True, profile="A", steps=[])
            ),
        )
        argv = [command, "--harness", "codex", "--dry-run"]

    assert main(argv) == 0
    assert seen["harness"] is HarnessTarget.CODEX


@pytest.mark.parametrize("command", ["bootstrap", "onboard", "deploy"])
def test_harness_selectors_reject_component_private_target(command: str) -> None:
    argv = [command]
    if command == "onboard":
        argv.append("project-slug")
    argv.extend(["--harness", "hermes", "--dry-run"])

    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2


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
        components={"dossier": ComponentPin(repo="YOUR-ORG/dossier", version="0.1.0")},
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


# --- doctor --profile (Plan 008 WI-0.1) --------------------------------------


def test_doctor_profile_flag_json_includes_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite.profiles import Profile, ProfileClassification

    classification = ProfileClassification(
        profile=Profile.A, missing_required=[], extra_optional=[]
    )
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=True,
            components=[],
            profile_classification=classification,
        ),
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--profile", "A", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "profile_classification" in parsed
    assert parsed["profile_classification"]["profile"] == "A"


def test_doctor_profile_flag_text_includes_section(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite.profiles import Profile, ProfileClassification

    classification = ProfileClassification(
        profile=Profile.B, missing_required=["dossier"], extra_optional=["agent-wake"]
    )
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=True,
            components=[],
            profile_classification=classification,
        ),
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--profile", "B"])
    assert rc == 0
    out = buf.getvalue()
    assert "profile classification" in out
    assert "B (Team workflow)" in out
    assert "dossier" in out


def test_doctor_without_profile_has_no_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "profile_classification" not in parsed
