"""Unit tests for the bootstrap module — ordering, idempotency, dry-run, refusal.

All tests use stubbed runners and installed checks — no live infra (AGENTS.md:
"Ordering/idempotency unit-tested with stubbed component CLIs (no live infra
in CI)").
"""

from __future__ import annotations

import subprocess
from typing import Mapping

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
_OK_PROVISION = _completed(stdout='[{"project": "test", "schema_created": true}]')
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
_OK_PRINCIPAL = _completed(stdout='{"principal_id": "suite-service", "key_id": "k1"}')
_ALREADY_PRINCIPAL = _completed(returncode=1, stderr="already exists")
_ALREADY_PROVISIONED = _completed(
    stdout='[{"project": "test", "schema_created": false}]'
)
_CLOBDER_PROVISION = _completed(returncode=1, stderr="refuse: would clobber existing key")
_FAIL_PROVISION = _completed(returncode=1, stderr="connection refused")


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
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
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
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): unsupported,
        ("cairn",): _OK_INSTALL,
    })

    result = run_bootstrap(
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        harness=HarnessTarget.CODEX,
        runner=runner,
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
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): wrong_harness,
        ("cairn",): _OK_INSTALL,
    })

    result = run_bootstrap(
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        harness=HarnessTarget.CLAUDE,
        runner=runner,
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
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _ALREADY_PROVISIONED,
        ("regista", "provision-principal"): _ALREADY_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _ALREADY_INSTALL,
        ("cairn",): _ALREADY_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
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
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _completed(
            stdout='{"reachable": false, "ok": false}', returncode=0
        ),
        ("regista", "secrets"): _completed(stdout="ok"),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
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
        installed=_installed_none,
    )
    assert result.ok is False
    secrets_step = result.steps[0]
    assert secrets_step.status is StepStatus.FAILED
    assert "regista" in secrets_step.detail


# ---------------------------------------------------------------------------
# Key clobber refusal
# ---------------------------------------------------------------------------


def test_key_clobber_refused() -> None:
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _CLOBDER_PROVISION,
        ("regista", "provision-principal"): _CLOBDER_PROVISION,
        ("regista", "secrets"): _completed(stdout="ok"),
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    provision_step = next(s for s in result.steps if s.step is StepKind.PROVISION)
    assert provision_step.status is StepStatus.REFUSED
    assert "clobber" in provision_step.detail.lower()


# ---------------------------------------------------------------------------
# Tier filtering
# ---------------------------------------------------------------------------


def test_tier_all_includes_tier2() -> None:
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
        ("acb",): _OK_INSTALL,
        ("agent-wake",): _OK_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="all",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    steps_run = {s.step for s in result.steps}
    assert StepKind.CAPABILITIES in steps_run
    assert StepKind.SIGNALING in steps_run


def test_tier2_missing_cli_skipped_not_failed() -> None:
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="all",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
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


def test_user_onboarding_runs_when_specified() -> None:
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        user="human-1",
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    user_step = next(
        s for s in result.steps if s.step is StepKind.USER_ONBOARDING
    )
    assert user_step.status is StepStatus.SKIPPED
    assert "not yet implemented" in user_step.detail


def test_user_onboarding_skipped_when_not_specified() -> None:
    runner = _MultiCmdRunner({
        ("regista", "doctor"): _OK_DOCTOR,
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "secrets"): _completed(stdout="ok"),
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_bootstrap(
        dry_run=False,
        tier="0-1",
        project="test-proj",
        dsn="postgresql://test:test@localhost/test",
        runner=runner,
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
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
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
