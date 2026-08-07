from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path

import pytest

from agent_suite import bootstrap as bootstrap_mod
from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite import onboard as onboard_mod
from agent_suite import schedule as schedule_mod
from agent_suite import services as services_mod
from agent_suite import upgrade as upgrade_mod
from agent_suite import verify_restore as verify_restore_mod
from agent_suite.alerting import AlertResult, EmissionStatus
from agent_suite.cli import PREFLIGHT_ALIAS, Command, _build_parser, main
from agent_suite.harness import HarnessTarget

_DSN = "postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista"


def _stub_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub lock I/O and regista-quad reads so CLI tests don't shell out or write."""
    monkeypatch.setattr(lock_mod, "read_regista_quad", lambda **kw: None)
    monkeypatch.setattr(lock_mod, "write_lock_file", lambda lock, path=None: None)
    monkeypatch.setattr(lock_mod, "load_lock_file", lambda path=None: None)
    monkeypatch.setattr(lock_mod, "read_candidate_versions", lambda **kw: {})
    monkeypatch.setattr(lock_mod, "read_candidate_revisions", lambda **kw: {})


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


def _stub_install_services(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make component-CLI discovery deterministic and shell out to nothing.

    Without this the dispatch test would invoke a real `dossier install-service`
    on any host where dossier happens to be on PATH.
    """
    monkeypatch.setattr(services_mod, "_default_which", lambda executable: None)


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
    _stub_install_services(monkeypatch)
    _stub_alert_check(monkeypatch)
    _stub_evidence_export(monkeypatch)
    _stub_backup_restore(monkeypatch)
    _stub_deploy(monkeypatch)
    for command in Command:
        if command is Command.SCHEDULE:
            assert main([command.value, "list"]) == 0
        elif command is Command.ONBOARD:
            assert main([command.value, "project-slug"]) == 0
        elif command is Command.OFFBOARD:
            # regista is absent under test, so the leaver path fails honestly
            # rather than reporting a principal it never revoked.
            assert main([command.value, "--user", "someone", "--dry-run"]) == 1
        elif command is Command.INSTALL_SERVICES:
            # No component CLI is installed under test, so the install refuses
            # honestly rather than reporting a service it never brought up.
            assert main([command.value, "--dry-run"]) == 1
        elif command is Command.PREFLIGHT_WINDOWS:
            # Exit 1 on Linux (PLATFORM_NOT_APPLICABLE) and on a blocked
            # Windows host alike — see the WI-050 tests below for which.
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
            assert main([command.value, "install", "--dry-run"]) == 0
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
        elif command is Command.RELEASE_MANIFEST:
            # build requires SUITE.lock; _stub_lock patches load_lock_file
            # to return None, so the build exits 1 (lock unreadable).
            assert main([command.value, "build", "--tag", "v0.0.0-test"]) == 1
        else:
            assert main([command.value]) == 0


def test_scheduled_restore_requires_dedicated_dsn_and_never_falls_back(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """The weekly restore's env indirection fails before touching restore."""
    from agent_suite import backup as backup_mod
    from agent_suite import config as config_mod

    monkeypatch.setattr(config_mod, "system_suite_env_path", lambda: tmp_path / "system.env")
    monkeypatch.setattr(config_mod, "user_suite_env_path", lambda: tmp_path / "user.env")
    monkeypatch.delenv("AGENT_SUITE_VERIFY_RESTORE_DSN", raising=False)
    monkeypatch.setenv("REGISTA_DSN", _DSN)
    monkeypatch.setattr(
        backup_mod,
        "run_restore",
        lambda **_kwargs: pytest.fail("restore must not run without the scratch DSN"),
    )

    code = main(
        [
            "restore",
            "--dir",
            str(tmp_path),
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ]
    )
    assert code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["error"]["code"] == "DSN_MISSING"
    assert _DSN not in json.dumps(document)


def test_scheduled_restore_rejects_the_production_dsn(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_suite import config as config_mod

    monkeypatch.setattr(config_mod, "system_suite_env_path", lambda: tmp_path / "system.env")
    monkeypatch.setattr(config_mod, "user_suite_env_path", lambda: tmp_path / "user.env")
    monkeypatch.setenv("REGISTA_DSN", _DSN)
    monkeypatch.setenv("AGENT_SUITE_VERIFY_RESTORE_DSN", _DSN)

    code = main(
        [
            "restore",
            "--dir",
            str(tmp_path),
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ]
    )
    assert code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["error"]["code"] == "DSN_NOT_DEDICATED"
    assert _DSN not in json.dumps(document)


def test_scheduled_restore_normalizes_uri_before_database_comparison(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from agent_suite import backup as backup_mod
    from agent_suite import config as config_mod

    monkeypatch.setattr(config_mod, "system_suite_env_path", lambda: tmp_path / "system.env")
    monkeypatch.setattr(config_mod, "user_suite_env_path", lambda: tmp_path / "user.env")
    monkeypatch.setenv(
        "REGISTA_DSN",
        "postgresql://prod:one@SUITE-DB.EXAMPLE:5432/regista?sslmode=require",
    )
    monkeypatch.setenv(
        "AGENT_SUITE_VERIFY_RESTORE_DSN",
        "postgres://scratch:two@suite-db.example/regista?application_name=verify",
    )
    monkeypatch.setattr(
        backup_mod,
        "run_restore",
        lambda **_kwargs: pytest.fail("equivalent production DSN must be rejected first"),
    )

    code = main(
        [
            "restore",
            "--dir",
            str(tmp_path),
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ]
    )
    assert code == 1
    document = json.loads(capsys.readouterr().out)
    assert document["error"]["code"] == "DSN_NOT_DEDICATED"
    assert "prod:one" not in json.dumps(document)


def test_scheduled_backup_and_restore_env_indirection_happy_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    """WI-071 L5: the values behind --dir-env/--dsn-env reach the orchestration.

    The failure paths (missing/conflicting/invalid indirections) are covered
    above; this proves the happy path actually hands the *resolved* values to
    ``run_backup``/``run_restore`` rather than the variable names.
    """
    from agent_suite import backup as backup_mod
    from agent_suite import config as config_mod
    from agent_suite.backup import BackupResult, RestoreResult

    monkeypatch.setattr(config_mod, "system_suite_env_path", lambda: tmp_path / "system.env")
    monkeypatch.setattr(config_mod, "user_suite_env_path", lambda: tmp_path / "user.env")
    backup_dir = tmp_path / "backups"
    scratch_dsn = "postgresql://verify:pw@suite-db.example:5432/regista_verify"
    monkeypatch.setenv("AGENT_SUITE_BACKUP_DIR", str(backup_dir))
    monkeypatch.setenv("AGENT_SUITE_VERIFY_RESTORE_DSN", scratch_dsn)
    monkeypatch.setenv("REGISTA_DSN", _DSN)

    seen: dict[str, dict[str, object]] = {}

    def fake_run_backup(**kwargs: object) -> BackupResult:
        seen["backup"] = kwargs
        return BackupResult(ok=True, dry_run=False, backup_dir=str(kwargs["backup_dir"]))

    def fake_run_restore(**kwargs: object) -> RestoreResult:
        seen["restore"] = kwargs
        return RestoreResult(ok=True, dry_run=False, backup_dir=str(kwargs["backup_dir"]))

    monkeypatch.setattr(backup_mod, "run_backup", fake_run_backup)
    monkeypatch.setattr(backup_mod, "run_restore", fake_run_restore)

    assert main(["backup", "--dir-env", "AGENT_SUITE_BACKUP_DIR", "--json"]) == 0
    assert (
        main(
            [
                "restore",
                "--dir-env",
                "AGENT_SUITE_BACKUP_DIR",
                "--dsn-env",
                "AGENT_SUITE_VERIFY_RESTORE_DSN",
                "--json",
            ]
        )
        == 0
    )
    capsys.readouterr()

    assert seen["backup"]["backup_dir"] == backup_dir
    assert seen["backup"]["dsn"] == _DSN
    assert seen["restore"]["backup_dir"] == backup_dir
    assert seen["restore"]["dsn"] == scratch_dsn


def test_codex_plugin_profiles_are_accepted() -> None:
    for profile in ("core", "credentialed", "full"):
        assert main(["codex-plugins", "install", "--profile", profile, "--dry-run"]) == 0


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


def test_doctor_passes_codex_marketplace_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_aggregate(**kwargs: object) -> doctor_mod.SuiteReport:
        seen.update(kwargs)
        return doctor_mod.SuiteReport(suite_ok=True, components=[])

    monkeypatch.setattr(doctor_mod, "aggregate", fake_aggregate)
    assert main(["doctor", "--codex-marketplace", "local-proof"]) == 0
    assert seen["codex_marketplace"] == "local-proof"


def test_doctor_reads_codex_marketplace_from_suite_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def fake_aggregate(**kwargs: object) -> doctor_mod.SuiteReport:
        seen.update(kwargs)
        return doctor_mod.SuiteReport(suite_ok=True, components=[])

    monkeypatch.setattr(doctor_mod, "aggregate", fake_aggregate)
    monkeypatch.setenv("AGENT_SUITE_CODEX_MARKETPLACE", "local-env")
    assert main(["doctor"]) == 0
    assert seen["codex_marketplace"] == "local-env"


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


# --- doctor artifact attestation flags (WI-036) -------------------------------


def _write_manifest(path: Path) -> str:
    """Write a real (self-SHA-valid) manifest and return its release tag."""
    from agent_suite.lock import ComponentPin, RegistaVersionQuad, SuiteLock, serialize_lock
    from agent_suite.release_manifest import build_manifest, serialize_manifest

    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=RegistaVersionQuad(
            library_version="0.5.1",
            schema_version=43,
            canonical_workflow_version="2",
            envelope_version=5,
        ),
        components={"regista": ComponentPin("hraedon/regista", "0.5.1", "a" * 40)},
    )
    manifest = build_manifest(
        lock=lock,
        lock_text=serialize_lock(lock),
        release_tag="v1.0.0-rc.9",
        umbrella_tag_sha="c" * 40,
        generated_at="2026-07-31T00:00:00+00:00",
    )
    path.write_text(serialize_manifest(manifest), encoding="utf-8")
    return manifest.release_tag


def test_doctor_release_manifest_is_passed_to_aggregate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "release-manifest.json"
    tag = _write_manifest(manifest_path)
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    seen: dict[str, object] = {}

    def _fake_aggregate(**kwargs: object) -> doctor_mod.SuiteReport:
        seen.update(kwargs)
        return doctor_mod.SuiteReport(suite_ok=True, components=[])

    monkeypatch.setattr(doctor_mod, "aggregate", _fake_aggregate)
    rc = main(
        [
            "doctor",
            "--release-manifest", str(manifest_path),
            "--artifact-wheels-dir", str(wheels),
            "--require-artifact-binding",
        ]
    )
    assert rc == 0
    manifest = seen["release_manifest"]
    assert manifest is not None
    assert getattr(manifest, "release_tag") == tag
    assert seen["artifact_wheels_dir"] == wheels
    assert seen["require_artifact_binding"] is True


def test_doctor_release_manifest_from_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "release-manifest.json"
    _write_manifest(manifest_path)
    monkeypatch.setenv("AGENT_SUITE_RELEASE_MANIFEST", str(manifest_path))
    seen: dict[str, object] = {}

    def _fake_aggregate(**kwargs: object) -> doctor_mod.SuiteReport:
        seen.update(kwargs)
        return doctor_mod.SuiteReport(suite_ok=True, components=[])

    monkeypatch.setattr(doctor_mod, "aggregate", _fake_aggregate)
    assert main(["doctor"]) == 0
    assert seen["release_manifest"] is not None


def test_doctor_unreadable_manifest_is_a_named_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    bad = tmp_path / "release-manifest.json"
    bad.write_text("{not json", encoding="utf-8")
    _stub_aggregate(monkeypatch, suite_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--release-manifest", str(bad), "--json"])
    assert rc != 0
    assert "MANIFEST_UNREADABLE" in buf.getvalue()


def test_doctor_missing_wheels_dir_is_a_named_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(
            [
                "doctor",
                "--artifact-wheels-dir", str(tmp_path / "nope"),
                "--json",
            ]
        )
    assert rc != 0
    assert "WHEELS_DIR_MISSING" in buf.getvalue()


def test_doctor_without_manifest_passes_none(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def _fake_aggregate(**kwargs: object) -> doctor_mod.SuiteReport:
        seen.update(kwargs)
        return doctor_mod.SuiteReport(suite_ok=True, components=[])

    monkeypatch.setattr(doctor_mod, "aggregate", _fake_aggregate)
    assert main(["doctor"]) == 0
    assert seen["release_manifest"] is None
    assert seen["artifact_wheels_dir"] is None
    assert seen["require_artifact_binding"] is False


def test_release_manifest_verify_installed_attests_this_host(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`release-manifest verify --installed` reports the installed artifacts."""
    import agent_suite.runtime_provenance as rp_mod

    manifest_path = tmp_path / "release-manifest.json"
    _write_manifest(manifest_path)
    monkeypatch.setattr(
        rp_mod,
        "read_runtime_provenance",
        lambda *a, **kw: {
            "regista": rp_mod.RuntimeProvenance(
                component="regista",
                distribution="regista-hraedon",
                version="9.9.9",  # wrong: the manifest says 0.5.1
                cli_path="/usr/local/bin/regista",
                interpreter="/opt/env/bin/python",
                mode=rp_mod.InstallMode.UV_TOOL,
                source=rp_mod.ArtifactSource.ARCHIVE,
            )
        },
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(
            ["release-manifest", "verify", str(manifest_path), "--installed", "--json"]
        )
    assert rc == 1
    parsed = json.loads(buf.getvalue())
    assert parsed["ok"] is False
    assert any(
        "version mismatch" in m
        for c in parsed["components"]
        for m in c["mismatches"]
    )


def test_release_manifest_verify_installed_green_when_versions_agree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agent_suite.runtime_provenance as rp_mod

    manifest_path = tmp_path / "release-manifest.json"
    _write_manifest(manifest_path)
    monkeypatch.setattr(
        rp_mod,
        "read_runtime_provenance",
        lambda *a, **kw: {
            "regista": rp_mod.RuntimeProvenance(
                component="regista",
                distribution="regista-hraedon",
                version="0.5.1",
                cli_path="/usr/local/bin/regista",
                interpreter="/opt/env/bin/python",
                mode=rp_mod.InstallMode.UV_TOOL,
                source=rp_mod.ArtifactSource.ARCHIVE,
            )
        },
    )
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["release-manifest", "verify", str(manifest_path), "--installed"])
    assert rc == 0
    out = buf.getvalue()
    assert "artifact attestation: ok" in out
    # ... and it is explicit that this is NOT a release-identity binding.
    assert "unbound" in out


# ---------------------------------------------------------------------------
# WI-050 — the Windows preflight is named for the platform it checks
# ---------------------------------------------------------------------------


def test_preflight_windows_is_the_canonical_name() -> None:
    """A generically-named verb that only checks Windows misleads by its name.

    `deploy` already uses "preflight" for a different step ("would check required
    CLIs: agent-notes, cairn, dossier, regista"), and `docs/install-linux.md`
    never mentions the standalone command — so on Linux the thing called
    `preflight` was the one thing named after a check the operator could not run.
    """
    assert Command.PREFLIGHT_WINDOWS.value == "preflight-windows"
    assert PREFLIGHT_ALIAS not in {c.value for c in Command}


def test_the_old_preflight_name_still_works(capsys: pytest.CaptureFixture[str]) -> None:
    """Backward compatibility: anyone scripting `agent-suite preflight` keeps working."""
    code = main([PREFLIGHT_ALIAS, "--json"])
    err = capsys.readouterr().err
    assert code == 1
    assert "deprecated" in err
    assert Command.PREFLIGHT_WINDOWS.value in err


def test_the_alias_is_accepted_by_the_parser() -> None:
    args = _build_parser().parse_args([PREFLIGHT_ALIAS, "--profile", "C"])
    assert args.command == PREFLIGHT_ALIAS
    assert args.profile == "C"


@pytest.mark.skipif(os.name == "nt", reason="the not-applicable path is the non-Windows one")
def test_on_a_non_windows_host_nothing_is_probed_and_the_report_says_why(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """WI-050's headline: the old report was red about a platform, not a host.

    On a supported Linux host this printed `State: blocked`, exit 1, with
    `windows unsupported (required)`, `powershell unsupported (required)` and
    `dns/tls unavailable` — a failure report an operator naturally reads as "my
    host is broken". The exit code is unchanged (contract §2, and a script that
    stopped must keep stopping); the report is now true.
    """
    code = main([Command.PREFLIGHT_WINDOWS.value, "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["ok"] is False
    assert payload["error"]["code"] == "PLATFORM_NOT_APPLICABLE"
    assert "Nothing was probed" in payload["error"]["detail"]
    # None of the misleading probe rows appear, because no probe ran.
    body = json.dumps(payload)
    assert "blocked" not in body
    assert "powershell" not in body


@pytest.mark.skipif(os.name == "nt", reason="the not-applicable path is the non-Windows one")
def test_the_not_applicable_report_is_a_contract_envelope(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from agent_suite.conformance.envelope import validate_envelope

    main([Command.PREFLIGHT_WINDOWS.value, "--json"])
    assert validate_envelope(json.loads(capsys.readouterr().out)) == []


def test_the_secret_provider_row_is_named_for_what_it_checks() -> None:
    """It used to state in its own detail that it observes presence only.

    A preflight runs before any config exists, so presence is genuinely all it
    can establish — the honest fix is the name, not a check with no subject.
    Resolution is verified by `bootstrap` step 0 (WI-041).
    """
    from agent_suite.profiles import Profile
    from agent_suite.windows_setup import (
        HostObservation,
        ProbeState,
        SetupRequest,
        profile_operations,
        run_preflight,
    )

    observation = HostObservation(
        os_name="Windows",
        python_version="3.12.3",
        powershell=ProbeState.AVAILABLE,
        elevation=ProbeState.AVAILABLE,
        service_account=ProbeState.AVAILABLE,
        postgres=ProbeState.AVAILABLE,
        dns=ProbeState.AVAILABLE,
        tls=ProbeState.AVAILABLE,
        secret_provider=ProbeState.AVAILABLE,
        artifact_release_identity="r",
        artifact_lock_identity="l",
        ownership_conflict=False,
    )
    request = SetupRequest(
        profile=Profile.B,
        target_release_identity="r",
        target_lock_identity="l",
        operations=profile_operations(Profile.B),
    )
    names = {check.name for check in run_preflight(observation, request).checks}
    assert "secret_provider_present" in names
    assert "secret_provider" not in names


def test_the_shipped_windows_installer_calls_the_canonical_verb() -> None:
    """`scripts/install-windows.ps1` is the documented Windows install path.

    Leaving it on the deprecated alias would make every documented install print a
    deprecation warning it cannot act on.
    """
    script = (
        Path(__file__).resolve().parents[1] / "scripts" / "install-windows.ps1"
    ).read_text(encoding="utf-8")
    assert f"agent-suite {Command.PREFLIGHT_WINDOWS.value}" in script
    assert "agent-suite preflight --" not in script
