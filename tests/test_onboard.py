"""Unit tests for the onboard module — spec -> provision -> sign event-zero.

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

from agent_suite.harness import HarnessTarget
from agent_suite.onboard import (
    RECOGNIZED_SPEC_VERSIONS,
    OnboardResult,
    OnboardStatus,
    OnboardStep,
    OnboardStepResult,
    _compute_ok,
    _extract_schema_version,
    _is_terminal,
    format_text,
    run_onboard,
)
from agent_suite.provisioning import ProvisionOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


class StubRunner:
    """Returns canned output keyed by the first token of the command."""

    def __init__(
        self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]
    ) -> None:
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
        return _completed(stdout='{"ok": true}', returncode=0)


class MultiCmdRunner:
    """Routes stubbed output by matching command prefixes."""

    def __init__(
        self,
        outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception],
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix in sorted(self._outputs, key=len, reverse=True):
            if cmd[: len(prefix)] == prefix:
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
        return _completed(stdout='{"ok": true}', returncode=0)


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _installed_except(*missing: str):
    def check(cli: str) -> bool:
        return cli not in missing

    return check


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
        stdout=json.dumps([{
            "project": project,
            "schema_created": schema_created,
            "migrations_applied": [1] if migrations is None else migrations,
            "service_role_created": service_role_created,
            "error": error,
        }]),
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
        stdout=json.dumps({
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
        }),
    )


def _error_envelope(
    code: str, message: str, *, returncode: int = 1
) -> subprocess.CompletedProcess[str]:
    """The CLI-contract §3 error envelope, on stdout, as regista emits it."""
    return _completed(
        returncode=returncode,
        stdout=json.dumps({
            "ok": False,
            "error": {
                "code": code,
                "message": message,
                "detail": None,
                "retryable": False,
                "partial": None,
            },
        }),
    )


_OK_PROVISION = _provision_result()
_OK_PRINCIPAL = _principal_result()
_OK_SIGN = _completed(stdout='{"event_id": "evt-0", "signed": true}')
_OK_INSTALL = _completed(
    stdout=(
        '{"tool":"component","harness":"test","status":"installed",'
        '"actions":[],"no_op":false}'
    )
)
_ALREADY_PROVISIONED = _provision_result(
    schema_created=False, migrations=[], service_role_created=False
)
_ALREADY_PRINCIPAL = _principal_result(
    already_existed=True, public_key_registered=False, private_key_stored=False
)
_ALREADY_INSTALL = _completed(
    stdout=(
        '{"tool":"component","harness":"test","status":"installed",'
        '"actions":[],"no_op":true}'
    )
)
#: regista WI-223's refusal to mint a second keypair, recognised by its code.
_REFUSED_PRINCIPAL = _error_envelope(
    "PRINCIPAL_KEY_ALREADY_EXISTS",
    "Refusing to mint a second keypair: principal 'suite-service' already has "
    "a key in the signing key file /etc/agent-suite/keys.json (pk_1)",
)
#: A ``provision-principal`` that succeeded by reusing the existing key.
_REUSED_PRINCIPAL = _principal_result(private_key_stored=False)
#: The WI-040 shape: exit 0 and a body reporting the work did not happen.
_EXIT0_ERROR_PROVISION = _provision_result(
    schema_created=False,
    migrations=[],
    service_role_created=False,
    error="permission denied to create role",
    returncode=0,
)
_FAIL_PROVISION = _completed(returncode=1, stderr="connection timeout")
_FAIL_SIGN = _completed(returncode=1, stderr="signing key not found")

_SPEC_V1 = "schema_version: \"1\"\nproject: test-proj\n"
_SPEC_V2 = "schema_version: \"2\"\nproject: test-proj\n"
_SPEC_NO_VERSION = "project: test-proj\ntitle: Test Project\n"


def _make_spec(tmp_path: Path, content: str, name: str = "spec.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# _extract_schema_version
# ---------------------------------------------------------------------------


def test_extract_schema_version_quoted() -> None:
    assert _extract_schema_version('schema_version: "1"\n') == "1"


def test_extract_schema_version_unquoted() -> None:
    assert _extract_schema_version("schema_version: 1.0\n") == "1.0"


def test_extract_schema_version_single_quoted() -> None:
    assert _extract_schema_version("schema_version: '1'\n") == "1"


def test_extract_schema_version_missing() -> None:
    assert _extract_schema_version("project: foo\n") is None


def test_extract_schema_version_empty() -> None:
    assert _extract_schema_version("schema_version:\n") is None


def test_extract_schema_version_indented() -> None:
    assert _extract_schema_version("  schema_version: \"1\"\n") == "1"


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------


def test_dry_run_acts_on_nothing(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = StubRunner({})
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=True,
        runner=runner,
        installed=_installed_all,
    )
    assert result.dry_run is True
    assert result.ok is True
    assert len(runner.calls) == 0
    for step in result.steps:
        assert step.status is OnboardStatus.PENDING
    harness_step = next(s for s in result.steps if s.step is OnboardStep.WIRE_HARNESS)
    assert "--json" in harness_step.detail
    assert "install-harness" in harness_step.detail


def test_dry_run_without_spec(tmp_path: Path) -> None:
    runner = StubRunner({})
    result = run_onboard(
        project="test-proj",
        spec_path=None,
        dry_run=True,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert len(runner.calls) == 0
    validate_step = result.steps[0]
    assert validate_step.status is OnboardStatus.SKIPPED
    assert "spec-unanchored" in validate_step.detail


# ---------------------------------------------------------------------------
# Full onboard with spec
# ---------------------------------------------------------------------------


def test_full_onboard_with_spec(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.spec_anchored is True
    assert result.spec_version == "1"
    assert result.spec_version_recognized is True
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[OnboardStep.VALIDATE_SPEC] is OnboardStatus.DONE
    assert statuses[OnboardStep.PROVISION] is OnboardStatus.DONE
    assert statuses[OnboardStep.SIGN_SPEC] is OnboardStatus.DONE
    assert statuses[OnboardStep.WIRE_HARNESS] is OnboardStatus.DONE


def test_full_onboard_without_spec() -> None:
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=None,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.spec_anchored is False
    assert result.spec_version is None
    assert result.spec_version_recognized is None
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[OnboardStep.VALIDATE_SPEC] is OnboardStatus.SKIPPED
    assert statuses[OnboardStep.PROVISION] is OnboardStatus.DONE
    assert statuses[OnboardStep.SIGN_SPEC] is OnboardStatus.SKIPPED
    assert statuses[OnboardStep.WIRE_HARNESS] is OnboardStatus.DONE


# ---------------------------------------------------------------------------
# Idempotency — second run is a no-op
# ---------------------------------------------------------------------------


def test_second_run_is_noop(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _ALREADY_PROVISIONED,
        ("regista", "provision-principal"): _ALREADY_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _ALREADY_INSTALL,
        ("cairn",): _ALREADY_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.spec_anchored is True
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[OnboardStep.PROVISION] is OnboardStatus.ALREADY_DONE
    assert statuses[OnboardStep.WIRE_HARNESS] is OnboardStatus.ALREADY_DONE


# ---------------------------------------------------------------------------
# Spec version interchange discipline
# ---------------------------------------------------------------------------


def test_unrecognized_spec_version_flagged(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V2)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.spec_version == "2"
    assert result.spec_version_recognized is False
    validate_step = next(s for s in result.steps if s.step is OnboardStep.VALIDATE_SPEC)
    assert "not recognised" in validate_step.detail or "UNRECOGNISED" in validate_step.detail


def test_spec_without_version_still_onboards(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_NO_VERSION)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.spec_version is None
    assert result.spec_version_recognized is None


# ---------------------------------------------------------------------------
# spec.md hash
# ---------------------------------------------------------------------------


def test_spec_md_hash_passed_to_sign(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    _make_spec(tmp_path, "# Test Project\nA human-readable spec.\n", name="spec.md")
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    sign_cmd = next(c for c in runner.calls if c[:3] == ("regista", "spec", "sign"))
    assert "--spec-md-hash" in sign_cmd
    hash_idx = sign_cmd.index("--spec-md-hash") + 1
    assert len(sign_cmd[hash_idx]) == 64  # SHA-256 hex digest


def test_no_spec_md_hash_when_md_absent(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    sign_cmd = next(c for c in runner.calls if c[:3] == ("regista", "spec", "sign"))
    assert "--spec-md-hash" not in sign_cmd


# ---------------------------------------------------------------------------
# Missing dependencies / failures
# ---------------------------------------------------------------------------


def test_missing_regista_aborts(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=StubRunner({}),
        installed=_installed_none,
    )
    assert result.ok is False
    provision_step = next(s for s in result.steps if s.step is OnboardStep.PROVISION)
    assert provision_step.status is OnboardStatus.FAILED
    assert "regista" in provision_step.detail


def test_spec_file_not_found_aborts(tmp_path: Path) -> None:
    runner = MultiCmdRunner({})
    result = run_onboard(
        project="test-proj",
        spec_path=tmp_path / "nonexistent.yaml",
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    validate_step = result.steps[0]
    assert validate_step.status is OnboardStatus.FAILED
    assert "cannot read spec" in validate_step.detail
    assert len(runner.calls) == 0


def test_provision_failure_aborts(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _FAIL_PROVISION,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[OnboardStep.PROVISION] is OnboardStatus.FAILED
    assert OnboardStep.SIGN_SPEC not in statuses
    assert OnboardStep.WIRE_HARNESS not in statuses


def test_sign_failure_aborts(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _FAIL_SIGN,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    assert result.spec_anchored is False
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[OnboardStep.SIGN_SPEC] is OnboardStatus.FAILED
    assert OnboardStep.WIRE_HARNESS not in statuses


# ---------------------------------------------------------------------------
# Key clobber refusal
# ---------------------------------------------------------------------------


def test_principal_refusal_is_cleared_by_reusing_the_existing_key(
    tmp_path: Path,
) -> None:
    """The live regression: onboarding a principal into a second project.

    regista WI-223 refuses to mint a second keypair for a principal that already
    has a signable one, because the signer selects by principal_id with no
    project scoping and would sign the *first* project's events with a key only
    the second project registered. ``--reuse-existing-key`` registers the
    existing public key in the additional project instead. Neither onboard nor
    bootstrap passed it, so multi-project onboarding of one principal stopped
    with REFUSED.
    """
    spec = _make_spec(tmp_path, _SPEC_V1)
    calls: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ("regista", "provision-principal"):
            if "--reuse-existing-key" in cmd:
                return _REUSED_PRINCIPAL
            return _REFUSED_PRINCIPAL
        if cmd[:2] == ("regista", "provision"):
            return _OK_PROVISION
        if cmd[:3] == ("regista", "spec", "sign"):
            return _OK_SIGN
        return _completed(
            stdout=json.dumps({
                "tool": cmd[0], "harness": cmd[2], "status": "installed",
                "actions": [], "no_op": False,
            })
        )

    result = run_onboard(
        project="second-project",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    provision_step = next(s for s in result.steps if s.step is OnboardStep.PROVISION)
    assert provision_step.status is OnboardStatus.DONE
    assert "--reuse-existing-key" in provision_step.detail
    # It tried without the flag first, so a principal with no existing key is
    # still minted a fresh one rather than being told to reuse nothing.
    principal_calls = [c for c in calls if c[:2] == ("regista", "provision-principal")]
    assert len(principal_calls) == 2
    assert "--reuse-existing-key" not in principal_calls[0]
    assert "--reuse-existing-key" in principal_calls[1]


def test_principal_refusal_stands_when_reuse_is_not_wanted(tmp_path: Path) -> None:
    """With reuse off the refusal is reported as REFUSED, not swallowed."""
    from agent_suite.provisioning import provision_principal

    report = provision_principal(
        runner=lambda cmd: _REFUSED_PRINCIPAL,
        project="second-project",
        principal="suite-service",
        reuse_existing_key=False,
    )
    assert report.ok is False
    assert report.outcome is ProvisionOutcome.REFUSED
    assert "PRINCIPAL_KEY_ALREADY_EXISTS" in report.detail


def test_provision_error_body_with_exit_zero_is_a_failure(tmp_path: Path) -> None:
    """WI-040, at the onboard entry point."""
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _EXIT0_ERROR_PROVISION,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    provision_step = next(s for s in result.steps if s.step is OnboardStep.PROVISION)
    assert provision_step.status is OnboardStatus.FAILED
    assert "permission denied to create role" in provision_step.detail


# ---------------------------------------------------------------------------
# Harness wiring
# ---------------------------------------------------------------------------


def test_harness_all_expands_stable_targets(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        harness=HarnessTarget.ALL,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    harness_cmds = [c for c in runner.calls if "install-harness" in c]
    assert harness_cmds == [
        ("agent-notes", "install-harness", "claude", "--json"),
        ("agent-notes", "install-harness", "opencode", "--json"),
        ("cairn", "install-harness", "claude", "--json"),
        ("cairn", "install-harness", "opencode", "--json"),
    ]


def test_harness_claude_only(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        harness=HarnessTarget.CLAUDE,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    for cmd in runner.calls:
        if "install-harness" in cmd:
            assert cmd == (cmd[0], "install-harness", "claude", "--json")


def test_harness_opencode_only(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        harness=HarnessTarget.OPENCODE,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    for cmd in runner.calls:
        if "install-harness" in cmd:
            assert cmd == (cmd[0], "install-harness", "opencode", "--json")


def test_harness_codex_is_positional(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
        ("agent-notes",): _OK_INSTALL,
        ("cairn",): _OK_INSTALL,
    })

    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        harness=HarnessTarget.CODEX,
        runner=runner,
        installed=_installed_all,
    )

    assert result.ok is True
    harness_cmds = [cmd for cmd in runner.calls if "install-harness" in cmd]
    assert harness_cmds == [
        ("agent-notes", "install-harness", "codex", "--json"),
        ("cairn", "install-harness", "codex", "--json"),
    ]


def test_missing_face_cli_fails(tmp_path: Path) -> None:
    spec = _make_spec(tmp_path, _SPEC_V1)
    runner = MultiCmdRunner({
        ("regista", "provision"): _OK_PROVISION,
        ("regista", "provision-principal"): _OK_PRINCIPAL,
        ("regista", "spec", "sign"): _OK_SIGN,
    })
    result = run_onboard(
        project="test-proj",
        spec_path=spec,
        dry_run=False,
        runner=runner,
        installed=_installed_except("agent-notes"),
    )
    assert result.ok is False
    harness_step = next(s for s in result.steps if s.step is OnboardStep.WIRE_HARNESS)
    assert harness_step.status is OnboardStatus.FAILED
    assert "agent-notes" in harness_step.detail


# ---------------------------------------------------------------------------
# assert_never coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(OnboardStatus))
def test_is_terminal_dispatch_is_total(status: OnboardStatus) -> None:
    assert isinstance(_is_terminal(status), bool)


@pytest.mark.parametrize("status", list(OnboardStatus))
def test_compute_ok_dispatch_is_total(status: OnboardStatus) -> None:
    result = _compute_ok([OnboardStepResult(OnboardStep.VALIDATE_SPEC, status)])
    assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------


def test_format_text_dry_run() -> None:
    result = OnboardResult(
        ok=True, dry_run=True, project="test-proj",
        spec_anchored=False, spec_version=None,
        spec_version_recognized=None, steps=[],
    )
    text = format_text(result)
    assert "dry-run" in text
    assert "OK" in text


def test_format_text_spec_anchored() -> None:
    result = OnboardResult(
        ok=True, dry_run=False, project="test-proj",
        spec_anchored=True, spec_version="1",
        spec_version_recognized=True, steps=[],
    )
    text = format_text(result)
    assert "spec-anchored" in text
    assert "schema_version: 1" in text
    assert "recognised" in text


def test_format_text_spec_unanchored() -> None:
    result = OnboardResult(
        ok=True, dry_run=False, project="test-proj",
        spec_anchored=False, spec_version=None,
        spec_version_recognized=None, steps=[],
    )
    text = format_text(result)
    assert "spec-unanchored" in text


def test_format_text_failure() -> None:
    result = OnboardResult(
        ok=False, dry_run=False, project="test-proj",
        spec_anchored=False, spec_version=None,
        spec_version_recognized=None,
        steps=[OnboardStepResult(OnboardStep.PROVISION, OnboardStatus.FAILED, "no regista")],
    )
    text = format_text(result)
    assert "NOT OK" in text
    assert "provision" in text


def test_format_text_unrecognized_version() -> None:
    result = OnboardResult(
        ok=True, dry_run=False, project="test-proj",
        spec_anchored=True, spec_version="99",
        spec_version_recognized=False, steps=[],
    )
    text = format_text(result)
    assert "UNRECOGNISED" in text


# ---------------------------------------------------------------------------
# Recognized versions sanity
# ---------------------------------------------------------------------------


def test_recognized_versions_contains_v1() -> None:
    assert "1" in RECOGNIZED_SPEC_VERSIONS
