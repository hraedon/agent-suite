"""Unit tests for the bootstrap module — ordering, idempotency, dry-run, refusal.

All tests use stubbed runners and installed checks — no live infra (AGENTS.md:
"Ordering/idempotency unit-tested with stubbed component CLIs (no live infra
in CI)").
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_suite.bootstrap import (
    BootstrapResult,
    BootstrapTier,
    StepKind,
    StepResult,
    StepStatus,
    _compute_ok,
    _is_terminal,
    _steps_for_tier,
    format_text,
    run_bootstrap,
)
from agent_suite.harness import HarnessTarget

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    """Returns canned output keyed by the first token of the command."""

    def __init__(self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        key = cmd[0]
        if key in self._outputs:
            out = self._outputs[key]
            if isinstance(out, Exception):
                raise out
            return out
        return _completed(stdout='{"reachable": true, "ok": true}', returncode=0)


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _installed_except(*missing: str):
    def check(cli: str) -> bool:
        return cli not in missing
    return check


_OK_DOCTOR = _completed(stdout='{"reachable": true, "ok": true}')
_OK_SECRETS = _completed(stdout="Available providers:\n  env\n  file\n  literal\n")
_OK_INSTALL = _completed(
    stdout=(
        '{"tool":"component","harness":"test","status":"installed",'
        '"actions":[],"no_op":false}'
    )
)
_ALREADY_INSTALL = _completed(
    stdout=(
        '{"tool":"component","harness":"test","status":"installed",'
        '"actions":[],"no_op":true}'
    )
)


def _provision_result(
    *,
    project: str = "test-proj",
    schema_created: bool = True,
    migrations: list[int] | None = None,
    service_role_created: bool = True,
    error: str | None = None,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """A ``regista provision --json`` body, in the shape regista really emits."""
    return _completed(
        returncode=returncode,
        stdout=json.dumps(
            [
                {
                    "project": project,
                    "schema_created": schema_created,
                    "migrations_applied": [1, 2] if migrations is None else migrations,
                    "service_role_created": service_role_created,
                    "error": error,
                }
            ]
        ),
    )


def _principal_result(
    *,
    principal: str = "suite-service",
    project: str = "test-proj",
    key_id: str = "pk_1",
    already_existed: bool = False,
    public_key_registered: bool = True,
    private_key_stored: bool = True,
    error: str | None = None,
    returncode: int = 0,
) -> subprocess.CompletedProcess[str]:
    """A ``regista provision-principal --json`` body."""
    return _completed(
        returncode=returncode,
        stdout=json.dumps(
            {
                "principal_id": principal,
                "project": project,
                "key_id": key_id,
                "fingerprint": "ff" * 8,
                "scheme": "ed25519",
                "private_key_stored": private_key_stored,
                "public_key_registered": public_key_registered,
                "already_existed": already_existed,
                "secret_backend": "file",
                "error": error,
            }
        ),
    )


def _error_envelope(
    code: str, message: str, *, returncode: int = 1
) -> subprocess.CompletedProcess[str]:
    """The CLI-contract §3 error envelope, on stdout, as regista emits it."""
    return _completed(
        returncode=returncode,
        stdout=json.dumps(
            {
                "ok": False,
                "error": {
                    "code": code,
                    "message": message,
                    "detail": None,
                    "retryable": False,
                    "partial": None,
                },
            }
        ),
    )


def _notes_doctor(
    status: str = "ok", detail: str = "schema current"
) -> subprocess.CompletedProcess[str]:
    return _completed(
        stdout=json.dumps(
            {
                "ok": status == "ok",
                "checks": [{"name": "schema_up_to_date", "status": status, "detail": detail}],
            }
        )
    )


_OK_PROVISION = _provision_result()
_ALREADY_PROVISIONED = _provision_result(
    schema_created=False, migrations=[], service_role_created=False
)
_OK_PRINCIPAL = _principal_result()
_ALREADY_PRINCIPAL = _principal_result(
    already_existed=True, public_key_registered=False, private_key_stored=False
)
_OK_ENROLL = _completed(
    stdout=(
        '{"principal_id": "human-1", "key_id": "k1", "scheme": "ed25519", '
        '"already_existed": false, "secret_backend": "file"}'
    )
)

#: The exact WI-040 shape: exit 0, and a body saying the work did not happen.
_EXIT0_ERROR_PROVISION = _provision_result(
    schema_created=False,
    migrations=[],
    service_role_created=False,
    error=(
        "permission denied to create role\nDETAIL:  Only roles with the "
        "CREATEROLE attribute may create roles."
    ),
    returncode=0,
)
#: regista WI-223's refusal, recognised by its code rather than its wording.
_REFUSED_PRINCIPAL = _error_envelope(
    "PRINCIPAL_KEY_ALREADY_EXISTS",
    "Refusing to mint a second keypair: principal 'suite-service' already has "
    "a key in the signing key file /etc/agent-suite/keys.json (pk_1)",
)
_FAIL_PROVISION = _completed(returncode=1, stderr="connection refused")


def _world(
    **overrides: subprocess.CompletedProcess[str] | Exception,
) -> dict[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]:
    """A healthy stubbed estate, with named parts swapped out.

    Every child the bootstrap calls is stubbed here, so a test names only the
    thing it is about. The runner matches the **longest** prefix, so a specific
    verb (``agent-notes doctor``) always beats a whole-CLI stub.
    """
    world: dict[tuple[str, ...], subprocess.CompletedProcess[str] | Exception] = {
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "secrets"): _OK_SECRETS,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "--json", "principal", "enroll"): _OK_ENROLL,
        ("agent-notes", "doctor"): _notes_doctor(),
        ("agent-notes-migrate",): _completed(stdout="applied"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
        ("acb",): _OK_INSTALL,
        ("agent-wake",): _OK_INSTALL,
    }
    keys = {
        "doctor": ("regista", "doctor"),
        "secrets": ("regista", "secrets"),
        "provision": ("regista", "provision"),
        "principal": ("regista", "provision-principal"),
        "enroll": ("regista", "--json", "principal", "enroll"),
        "notes_doctor": ("agent-notes", "doctor"),
        "migrate": ("agent-notes-migrate",),
        "notes": ("agent-notes",),
        "cairn": ("cairn",),
        "acb": ("acb",),
        "wake": ("agent-wake",),
    }
    for name, value in overrides.items():
        world[keys[name]] = value
    return world


# ---------------------------------------------------------------------------
# Step ordering
# ---------------------------------------------------------------------------


def test_steps_for_tier_01_excludes_tier2() -> None:
    steps = _steps_for_tier(BootstrapTier.CORE_01)
    assert StepKind.CAPABILITIES not in steps
    assert StepKind.SIGNALING not in steps
    assert StepKind.PROBE_SECRETS in steps
    assert StepKind.PROVISION in steps


def test_steps_for_tier_all_includes_everything() -> None:
    steps = _steps_for_tier(BootstrapTier.ALL)
    assert StepKind.CAPABILITIES in steps
    assert StepKind.SIGNALING in steps
    assert len(steps) == len(StepKind)


def test_step_order_is_documented_order() -> None:
    steps = _steps_for_tier(BootstrapTier.ALL)
    expected = list(StepKind)
    assert steps == expected


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_acts_on_nothing() -> None:
    runner = StubRunner({})
    result = run_bootstrap(
        dry_run=True,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.dry_run is True
    assert result.ok is True
    assert len(runner.calls) == 0
    for step in result.steps:
        if step.step is StepKind.USER_ONBOARDING:
            assert step.status is StepStatus.SKIPPED
        else:
            assert step.status is StepStatus.PENDING


# ---------------------------------------------------------------------------
# Full bootstrap
# ---------------------------------------------------------------------------


def test_full_bootstrap_tier_01() -> None:
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is True
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[StepKind.PROBE_SECRETS] is StepStatus.DONE
    assert statuses[StepKind.PROBE_DB] is StepStatus.DONE
    assert statuses[StepKind.PROVISION] is StepStatus.DONE
    assert statuses[StepKind.FACES] is StepStatus.DONE
    assert statuses[StepKind.PROVENANCE] is StepStatus.DONE
    assert StepKind.CAPABILITIES not in statuses
    assert StepKind.SIGNALING not in statuses


def test_bootstrap_explicit_codex_failure_stops_pipeline_with_diagnostics() -> None:
    unsupported = _completed(
        returncode=1,
        stdout=(
            '{"tool":"agent-notes","harness":"codex",'
            '"status":"unsupported","actions":[{"kind":"unsupported",'
            '"path":"","detail":"Codex adapter pending Plan 019"}],'
            '"no_op":false}'
        ),
    )
    runner = _MultiCmdRunner(_world(notes=unsupported))

    result = run_bootstrap(
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        harness=HarnessTarget.CODEX,
        runner=runner,
        env={},
        installed=_installed_all,
    )

    assert result.ok is False
    assert ("agent-notes", "install-harness", "codex", "--json") in runner.calls
    assert not any(call[0] == "cairn" for call in runner.calls)
    faces = next(step for step in result.steps if step.step is StepKind.FACES)
    provenance = next(step for step in result.steps if step.step is StepKind.PROVENANCE)
    assert faces.status is StepStatus.FAILED
    assert "unsupported" in faces.detail
    assert "Codex adapter pending Plan 019" in faces.detail
    assert provenance.status is StepStatus.SKIPPED


def test_bootstrap_rejects_installed_json_for_wrong_harness() -> None:
    wrong_harness = _completed(
        stdout=(
            '{"tool":"agent-notes","harness":"opencode",'
            '"status":"installed","actions":[],"no_op":false}'
        )
    )
    runner = _MultiCmdRunner(_world(notes=wrong_harness))

    result = run_bootstrap(
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        harness=HarnessTarget.CLAUDE,
        runner=runner,
        env={},
        installed=_installed_all,
    )

    assert result.ok is False
    faces = next(step for step in result.steps if step.step is StepKind.FACES)
    assert faces.status is StepStatus.FAILED
    assert "harness mismatch" in faces.detail
    assert not any(call[0] == "cairn" for call in runner.calls)


# ---------------------------------------------------------------------------
# Idempotency — second run is a no-op
# ---------------------------------------------------------------------------


def test_second_run_is_noop() -> None:
    runner = _MultiCmdRunner(_world(
                 provision=_ALREADY_PROVISIONED,
                 principal=_ALREADY_PRINCIPAL,
                 notes=_ALREADY_INSTALL,
                 cairn=_ALREADY_INSTALL,
             ))
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is True
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[StepKind.PROVISION] is StepStatus.ALREADY_DONE
    assert statuses[StepKind.FACES] is StepStatus.ALREADY_DONE
    assert statuses[StepKind.PROVENANCE] is StepStatus.ALREADY_DONE


# ---------------------------------------------------------------------------
# Missing dependencies
# ---------------------------------------------------------------------------


def test_missing_postgres_fails_with_named_message() -> None:
    runner = _MultiCmdRunner(_world(
                 doctor=_completed( stdout='{"reachable": false, "ok": false}', returncode=0 ),
             ))
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is False
    db_step = next(s for s in result.steps if s.step is StepKind.PROBE_DB)
    assert db_step.status is StepStatus.FAILED
    assert "Postgres" in db_step.detail or "unreachable" in db_step.detail
    # Subsequent steps should be skipped
    provision_step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert provision_step.status is StepStatus.SKIPPED


def test_missing_regista_aborts() -> None:
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=StubRunner({}),
        env={},
        installed=_installed_none,
    )
    assert result.ok is False
    secrets_step = result.steps[0]
    assert secrets_step.status is StepStatus.FAILED
    assert "regista" in secrets_step.detail


# ---------------------------------------------------------------------------
# Key clobber refusal
# ---------------------------------------------------------------------------


def test_key_refusal_is_refused_by_its_error_code() -> None:
    """A refusal is recognised by ``PRINCIPAL_KEY_ALREADY_EXISTS``, not by prose.

    With ``reuse_existing_key`` off, the refusal stands and stops the pipeline.
    """
    runner = _MultiCmdRunner(_world(principal=_REFUSED_PRINCIPAL))
    from agent_suite.provisioning import provision_principal

    report = provision_principal(
        runner=runner,
        project="test-proj",
        principal="suite-service",
        reuse_existing_key=False,
    )
    assert report.ok is False
    assert report.outcome.value == "refused"
    assert "PRINCIPAL_KEY_ALREADY_EXISTS" in report.detail


def test_provision_error_body_with_exit_zero_fails_the_step() -> None:
    """WI-040: the defect that made ``bootstrap: OK`` meaningless.

    ``regista provision --json`` exits 0 while its body reports
    ``error: permission denied to create role`` and
    ``service_role_created: false``. The old code read the exit code, called the
    step ``already_done`` on a clean host, and printed ``bootstrap: OK`` over an
    install whose service role did not exist.
    """
    runner = _MultiCmdRunner(_world(provision=_EXIT0_ERROR_PROVISION))
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is False
    provision_step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert provision_step.status is StepStatus.FAILED
    assert "permission denied to create role" in provision_step.detail
    # and the operator is told the child violated the exit-code contract
    assert "exited 0" in provision_step.detail
    # nothing downstream ran
    faces = next(s for s in result.steps if s.step is StepKind.FACES)
    assert faces.status is StepStatus.SKIPPED


def test_provision_first_run_of_a_clean_host_is_not_already_done() -> None:
    """``already_done`` on a clean host is what tipped the qualification off."""
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    provision_step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert provision_step.status is StepStatus.DONE
    assert "service role created" in provision_step.detail


# ---------------------------------------------------------------------------
# Tier filtering
# ---------------------------------------------------------------------------


def test_tier_all_includes_tier2() -> None:
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="all",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is True
    steps_run = {s.step for s in result.steps}
    assert StepKind.CAPABILITIES in steps_run
    assert StepKind.SIGNALING in steps_run


def test_tier2_missing_cli_skipped_not_failed() -> None:
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="all",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_except("acb", "agent-wake"),
    )
    assert result.ok is True
    cap_step = next(s for s in result.steps if s.step is StepKind.CAPABILITIES)
    sig_step = next(s for s in result.steps if s.step is StepKind.SIGNALING)
    assert cap_step.status is StepStatus.SKIPPED
    assert sig_step.status is StepStatus.SKIPPED


# ---------------------------------------------------------------------------
# User onboarding
# ---------------------------------------------------------------------------


def _users_file(tmp_path: Path, **extra: object) -> Path:
    """A dossier local-backend users file with one human in it."""
    entry: dict[str, object] = {
        "stable_id": "4814fec5-7b84-4f61-ae43-99a91dc76a63",
        "username": "human-1",
        "display_name": "Human One",
        "password": "scrypt:redacted",
    }
    entry.update(extra)
    path = tmp_path / "users.json"
    path.write_text(json.dumps([entry], indent=2))
    return path


def test_user_onboarding_runs_when_specified(tmp_path) -> None:
    overlay = tmp_path / "suite.env"
    users = _users_file(tmp_path)
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        user="human-1",
        config_path=str(overlay),
        runner=runner,
        env={"DOSSIER_USERS_PATH": str(users)},
        installed=_installed_all,
    )
    assert result.ok is True
    user_step = next(
        s for s in result.steps if s.step is StepKind.USER_ONBOARDING
    )
    assert user_step.status is StepStatus.DONE
    assert "REGISTA_PRINCIPAL_ID=human-1" in overlay.read_text()


def test_user_onboarding_records_the_dossier_binding(tmp_path) -> None:
    """WI-052: the key alone leaves the human unattributable.

    dossier finds a human's per-actor Ed25519 key through an explicit
    ``principal_id`` on their identity record, and never derives one. Before
    this, ``bootstrap --user`` provisioned the key and the overlay and wrote no
    binding, so a by-the-book onboarding still produced a human whose
    acceptance was signed with the shared store key (or refused outright).
    """
    users = _users_file(tmp_path)
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        user="human-1",
        config_path=str(tmp_path / "suite.env"),
        runner=_MultiCmdRunner(_world()),
        env={"DOSSIER_USERS_PATH": str(users)},
        installed=_installed_all,
    )
    assert result.ok is True
    written = json.loads(users.read_text())
    assert written[0]["principal_id"] == "human-1"
    # the rest of the record is untouched
    assert written[0]["stable_id"] == "4814fec5-7b84-4f61-ae43-99a91dc76a63"
    assert written[0]["password"] == "scrypt:redacted"


def test_user_onboarding_without_a_dossier_binding_is_not_clean(tmp_path) -> None:
    """A host where the binding cannot be recorded must not report success.

    The qualification run onboarded ``qual-human`` by the book and the human
    was still unattributable. "Nothing to bind against" is a named manual
    action, not a silent pass.
    """
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        user="qual-human",
        config_path=str(tmp_path / "suite.env"),
        runner=_MultiCmdRunner(_world()),
        env={},
        installed=_installed_all,
    )
    assert result.ok is False
    user_step = next(s for s in result.steps if s.step is StepKind.USER_ONBOARDING)
    assert user_step.status is StepStatus.REFUSED
    assert "principal_id" in user_step.detail


def test_user_onboarding_skipped_when_not_specified() -> None:
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    user_step = next(
        (s for s in result.steps if s.step is StepKind.USER_ONBOARDING),
        None,
    )
    assert user_step is not None
    assert user_step.status is StepStatus.SKIPPED


# ---------------------------------------------------------------------------
# assert_never coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(StepStatus))
def test_is_terminal_dispatch_is_total(status: StepStatus) -> None:
    assert isinstance(_is_terminal(status), bool)


@pytest.mark.parametrize("status", list(StepStatus))
def test_compute_ok_dispatch_is_total(status: StepStatus) -> None:
    result = _compute_ok([StepResult(StepKind.PROBE_SECRETS, status)])
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


def test_format_text_dry_run() -> None:
    result = BootstrapResult(ok=True, dry_run=True, steps=[])
    text = format_text(result)
    assert "dry-run" in text
    assert "OK" in text


def test_format_text_failure() -> None:
    result = BootstrapResult(
        ok=False,
        dry_run=False,
        steps=[
            StepResult(StepKind.PROBE_DB, StepStatus.FAILED, "Postgres unreachable"),
        ],
    )
    text = format_text(result)
    assert "NOT OK" in text
    assert "probe_db" in text


# ---------------------------------------------------------------------------
# Multi-command stub runner (handles regista doctor vs regista provision)
# ---------------------------------------------------------------------------


class _MultiCmdRunner:
    """Routes stubbed output by matching command prefixes."""

    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        # Longest prefix wins, so ("agent-notes", "doctor") beats
        # ("agent-notes",) regardless of the order a test declared them.
        for prefix in sorted(self._outputs, key=len, reverse=True):
            if cmd[: len(prefix)] != prefix:
                continue
            out = self._outputs[prefix]
            if isinstance(out, Exception):
                raise out
            if out is _OK_INSTALL or out is _ALREADY_INSTALL:
                no_op = "true" if out is _ALREADY_INSTALL else "false"
                return _completed(
                    stdout=(
                        f'{{"tool":"{cmd[0]}","harness":"{cmd[2]}",'
                        f'"status":"installed","actions":[],"no_op":{no_op}}}'
                    )
                )
            return out
        return _completed(stdout='{"reachable": true, "ok": true}')


# ---------------------------------------------------------------------------
# WI-042 — every configured project slug gets provisioned
# ---------------------------------------------------------------------------


def test_every_configured_project_is_provisioned() -> None:
    """`suite.env.example` ships CAIRN_PROJECT as a *different* slug.

    Only REGISTA_PROJECT was provisioned, so cairn was red after a by-the-book
    bootstrap that printed OK: "Project schema 'agent_provenance' does not
    exist". The undocumented remedy was a manual `regista provision`.
    """
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        projects=("qual_linux", "agent_provenance", "agent_notes_proj"),
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is True
    provisioned = [c[3] for c in runner.calls if c[:2] == ("regista", "provision")]
    assert provisioned == ["qual_linux", "agent_provenance", "agent_notes_proj"]
    step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert "agent_provenance" in step.detail


def test_configured_project_slugs_reads_every_component_var() -> None:
    from agent_suite.config import configured_project_slugs

    assert configured_project_slugs(
        {
            "REGISTA_PROJECT": "qual_linux",
            "CAIRN_PROJECT": "agent_provenance",
            "AGENT_NOTES_PROJECT": "qual_linux",
            "DOSSIER_PROJECTS": "qual_linux, portfolio",
        }
    ) == ("qual_linux", "agent_provenance", "portfolio")


def test_dry_run_names_every_project_it_would_provision() -> None:
    result = run_bootstrap(
        dry_run=True,
        tier="0-1",
        project="qual_linux",
        projects=("qual_linux", "agent_provenance"),
        dsn="postgresql://test:test@localhost/test",
        runner=_MultiCmdRunner(_world()),
        env={},
        installed=_installed_all,
    )
    step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert step.status is StepStatus.PENDING
    assert "agent_provenance" in step.detail


# ---------------------------------------------------------------------------
# WI-043 — the agent-notes projection database
# ---------------------------------------------------------------------------


def test_projection_schema_is_migrated_and_verified() -> None:
    """A clean host's agent-notes projection DB had 11 missing tables/views.

    `install-harness` wires skills and env and never touches the projection
    schema, and the remedy lived only in a troubleshooting table.
    """
    calls: list[tuple[str, ...]] = []
    state = {"migrated": False}

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ("agent-notes", "doctor"):
            return _notes_doctor(
                "ok" if state["migrated"] else "fail",
                "schema current" if state["migrated"] else
                "Missing tables/views: ['memories', 'work_items']",
            )
        if cmd[:1] == ("agent-notes-migrate",):
            state["migrated"] = True
            return _completed(stdout="applied 12 migration file(s)")
        return _MultiCmdRunner(_world())(cmd)

    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    assert result.ok is True
    step = next(s for s in result.steps if s.step is StepKind.PROJECTIONS)
    assert step.status is StepStatus.DONE
    assert ("agent-notes-migrate", "--all") in calls
    # It ran before the faces were wired, so the face has a schema to write to.
    order = [s.step for s in result.steps]
    assert order.index(StepKind.PROJECTIONS) < order.index(StepKind.FACES)


def test_projection_step_is_a_noop_when_the_schema_is_current() -> None:
    runner = _MultiCmdRunner(_world())
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        env={},
        installed=_installed_all,
    )
    step = next(s for s in result.steps if s.step is StepKind.PROJECTIONS)
    assert step.status is StepStatus.ALREADY_DONE
    assert not [c for c in runner.calls if c[0] == "agent-notes-migrate"]


def test_missing_projection_schema_that_cannot_be_migrated_fails() -> None:
    """The artifact-only blocker is reported, not skipped past.

    On a host where the wheel shipped no schema, `agent-notes-migrate` cannot
    run at all — so the bootstrap must say the projection database is not up to
    date, rather than reporting OK and leaving the face red.
    """
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=_MultiCmdRunner(
            _world(notes_doctor=_notes_doctor("fail", "Missing tables/views: [...]"))
        ),
        env={},
        installed=_installed_except("agent-notes-migrate"),
    )
    assert result.ok is False
    step = next(s for s in result.steps if s.step is StepKind.PROJECTIONS)
    assert step.status is StepStatus.FAILED
    assert "agent-notes-migrate" in step.detail


def test_migrate_exiting_zero_without_fixing_the_schema_fails() -> None:
    """"The command succeeded" is not "the schema is present"."""
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=_MultiCmdRunner(
            _world(
                notes_doctor=_notes_doctor("fail", "Missing tables/views: ['memories']"),
                migrate=_completed(stdout="No .sql files found in schema/"),
            )
        ),
        env={},
        installed=_installed_all,
    )
    assert result.ok is False
    step = next(s for s in result.steps if s.step is StepKind.PROJECTIONS)
    assert step.status is StepStatus.FAILED
    assert "still does not pass" in step.detail


def test_a_skipped_schema_check_is_not_a_pass() -> None:
    """A check that did not run cannot stand in for one that passed."""
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="qual_linux",
        dsn="postgresql://test:test@localhost/test",
        runner=_MultiCmdRunner(
            _world(
                notes_doctor=_notes_doctor("skip", "skipped (prerequisite failed)"),
                migrate=_completed(stdout="nothing to do"),
            )
        ),
        env={},
        installed=_installed_all,
    )
    assert result.ok is False
    step = next(s for s in result.steps if s.step is StepKind.PROJECTIONS)
    assert step.status is StepStatus.FAILED
