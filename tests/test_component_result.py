"""The exit-0-with-error-body defect, and the envelope discipline that closes it.

WI-040. Every test here drives a *fake component* — a stub that emits a real
component's JSON shapes — because the defect was never in the suite's own
reporting: it was in what the suite accepted as evidence from a child. The
sharpest case is the one the qualification run hit, which no amount of care in
the reporting layer could have caught: a child that **exits 0** and reports in
its body that the work did not happen.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from agent_suite.component_result import (
    ChildOutcome,
    SyntheticCode,
    evaluate_component_result,
)
from agent_suite.provisioning import (
    PROJECT_RESULT_FIELDS,
    ProvisionOutcome,
    provision_principal,
    provision_project,
    provision_projects,
)

# ---------------------------------------------------------------------------
# A fake component: it answers --json, and it is wrong in specific ways
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _fake_component(
    *, body: object, returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return _completed(stdout=json.dumps(body), returncode=returncode, stderr=stderr)


#: regista's real provision body when the role step failed, verbatim in shape.
_PROVISION_ERROR_BODY = [
    {
        "project": "qual_linux",
        "schema_created": False,
        "migrations_applied": [],
        "service_role_created": False,
        "error": (
            "permission denied to create role\n"
            "DETAIL:  Only roles with the CREATEROLE attribute may create roles."
        ),
    }
]


# ---------------------------------------------------------------------------
# The headline case
# ---------------------------------------------------------------------------


def test_exit_zero_with_an_error_body_is_a_failure() -> None:
    """A fake component that exits 0 while reporting an error must fail the step.

    This is the whole of WI-040. `regista provision --json` exits 0 with
    ``{"error": "permission denied to create role", "service_role_created":
    false}``; the bootstrap read the exit code, reported the step
    ``already_done`` on a clean host, and printed ``bootstrap: OK`` over an
    install whose service role did not exist.
    """
    result = evaluate_component_result(
        command="regista provision --project qual_linux",
        returncode=0,
        stdout=json.dumps(_PROVISION_ERROR_BODY),
        stderr="",
        require_fields=PROJECT_RESULT_FIELDS,
    )
    assert result.ok is False
    assert result.outcome is ChildOutcome.FAILED
    assert result.code == SyntheticCode.CHILD_REPORTED_ERROR
    assert "permission denied to create role" in result.detail
    # The operator is told the child broke the exit-code contract, so the bug
    # gets filed against the child rather than mistaken for suite flakiness.
    assert "exited 0" in result.detail
    # No records escape a failed evaluation, so nothing downstream can read
    # fields off it and conclude something happened.
    assert result.records == ()


def test_exit_zero_with_an_error_envelope_is_a_failure() -> None:
    """Same rule for the CLI-contract §3 envelope shape."""
    result = evaluate_component_result(
        command="fake-tool do-thing",
        returncode=0,
        stdout=json.dumps(
            {
                "ok": False,
                "error": {
                    "code": "SECRET_RESOLVE_FAILED",
                    "message": "vault: permission denied",
                    "detail": None,
                    "retryable": False,
                    "partial": None,
                },
            }
        ),
        stderr="",
    )
    assert result.ok is False
    assert result.code == "SECRET_RESOLVE_FAILED"
    assert "exited 0" in result.detail


def test_provision_step_fails_on_the_exit_zero_error_body() -> None:
    """End to end through the provisioning step the bootstrap actually calls."""
    report = provision_project(
        runner=lambda _cmd: _fake_component(body=_PROVISION_ERROR_BODY),
        project="qual_linux",
    )
    assert report.ok is False
    assert report.outcome is ProvisionOutcome.FAILED


# ---------------------------------------------------------------------------
# Presence is not verification
# ---------------------------------------------------------------------------


def test_a_missing_completion_field_is_not_a_pass() -> None:
    """A field the child did not emit is a fact the suite does not have.

    The old fixtures modelled a child reporting only ``schema_created`` — and the
    old code was happy with that, which is why a body reporting
    ``service_role_created: false`` sailed through.
    """
    result = evaluate_component_result(
        command="regista provision --project p",
        returncode=0,
        stdout=json.dumps([{"project": "p", "schema_created": True}]),
        stderr="",
        require_fields=PROJECT_RESULT_FIELDS,
    )
    assert result.ok is False
    assert result.code == SyntheticCode.INCOMPLETE_RESULT
    assert "service_role_created" in result.detail


def test_json_requested_and_prose_returned_is_a_failure() -> None:
    result = evaluate_component_result(
        command="regista provision --project p",
        returncode=0,
        stdout="[OK] p: schema exists, service role created\n",
        stderr="",
        require_fields=PROJECT_RESULT_FIELDS,
    )
    assert result.ok is False
    assert result.code == SyntheticCode.MALFORMED_RESULT


def test_silent_nonzero_exit_is_a_failure() -> None:
    """No envelope, no record error — the exit code is all there is, and it counts."""
    result = evaluate_component_result(
        command="regista provision --project p",
        returncode=2,
        stdout=json.dumps([{
            "project": "p",
            "schema_created": True,
            "migrations_applied": [],
            "service_role_created": True,
            "error": None,
        }]),
        stderr="Traceback (most recent call last): ...",
        require_fields=PROJECT_RESULT_FIELDS,
    )
    assert result.ok is False
    assert result.code == SyntheticCode.UNEXPECTED_EXIT
    assert "Traceback" in result.detail


def test_already_done_requires_affirmative_evidence() -> None:
    """``already_done`` means "the child says it was already here"."""
    already = provision_project(
        runner=lambda _cmd: _fake_component(
            body=[{
                "project": "p",
                "schema_created": False,
                "migrations_applied": [],
                "service_role_created": False,
                "error": None,
            }]
        ),
        project="p",
    )
    assert already.outcome is ProvisionOutcome.ALREADY_DONE

    fresh = provision_project(
        runner=lambda _cmd: _fake_component(
            body=[{
                "project": "p",
                "schema_created": True,
                "migrations_applied": [1, 2],
                "service_role_created": True,
                "error": None,
            }]
        ),
        project="p",
    )
    assert fresh.outcome is ProvisionOutcome.DONE


def test_principal_result_claiming_nothing_registered_is_a_failure() -> None:
    """A success body that registered no key has not given the project an identity."""
    report = provision_principal(
        runner=lambda _cmd: _fake_component(
            body={
                "principal_id": "suite-service",
                "project": "p",
                "key_id": "",
                "already_existed": False,
                "public_key_registered": False,
                "error": None,
            }
        ),
        project="p",
        principal="suite-service",
    )
    assert report.ok is False
    assert report.outcome is ProvisionOutcome.FAILED
    assert "nothing signs for this principal here" in report.detail


# ---------------------------------------------------------------------------
# Classification is by code, never by message
# ---------------------------------------------------------------------------


def _refusal(message: str) -> subprocess.CompletedProcess[str]:
    return _fake_component(
        body={
            "ok": False,
            "error": {
                "code": "PRINCIPAL_KEY_ALREADY_EXISTS",
                "message": message,
                "detail": None,
                "retryable": False,
                "partial": None,
            },
        },
        returncode=1,
    )


@pytest.mark.parametrize(
    "message",
    [
        # The wording regista pinned in a test purely to satisfy the old parser.
        "Refusing to mint a second keypair: principal 'x' already has a key",
        # The wording it would naturally have had — which the old parser read as
        # "already provisioned", i.e. a *green* step.
        "principal 'x' already has a key that exists in the key file",
        # And a wording with none of the old keywords at all.
        "a signable Ed25519 entry is present for this principal",
    ],
)
def test_refusal_classification_does_not_depend_on_wording(message: str) -> None:
    report = provision_principal(
        runner=lambda _cmd: _refusal(message),
        project="p",
        principal="x",
        reuse_existing_key=False,
    )
    assert report.outcome is ProvisionOutcome.REFUSED
    assert report.ok is False


def test_unknown_error_code_is_failed_never_done() -> None:
    report = provision_principal(
        runner=lambda _cmd: _fake_component(
            body={
                "ok": False,
                "error": {
                    "code": "A_CODE_THE_SUITE_HAS_NEVER_SEEN",
                    "message": "something already exists somewhere",
                    "detail": None,
                    "retryable": False,
                    "partial": None,
                },
            },
            returncode=1,
        ),
        project="p",
        principal="x",
    )
    assert report.outcome is ProvisionOutcome.FAILED


# ---------------------------------------------------------------------------
# One principal, one key, registered in every project it acts in
# ---------------------------------------------------------------------------


def test_multi_project_onboarding_of_one_principal_succeeds() -> None:
    """The live regression: two projects, one principal, one key file.

    regista WI-223 refuses the second mint. ``--reuse-existing-key`` registers
    the existing public key in the second project. Without it, bootstrapping a
    host that names both ``REGISTA_PROJECT`` and ``CAIRN_PROJECT`` stops with
    REFUSED — which is what Plan 020 Lane F (two humans, two agents) needs.
    """
    minted: set[str] = set()
    calls: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        if cmd[:2] == ("regista", "provision"):
            return _fake_component(
                body=[{
                    "project": cmd[3],
                    "schema_created": True,
                    "migrations_applied": [1],
                    "service_role_created": True,
                    "error": None,
                }]
            )
        assert cmd[:2] == ("regista", "provision-principal")
        project = cmd[3]
        principal = cmd[5]
        reuse = "--reuse-existing-key" in cmd
        if minted and not reuse:
            # The shared key file already has a signable key for this principal.
            return _refusal(
                f"Refusing to mint a second keypair: principal {principal!r} "
                f"already has a key in the signing key file"
            )
        if reuse:
            return _fake_component(
                body={
                    "principal_id": principal,
                    "project": project,
                    "key_id": sorted(minted)[0],
                    "already_existed": False,
                    "public_key_registered": True,
                    "private_key_stored": False,
                    "error": None,
                }
            )
        minted.add("pk_first")
        return _fake_component(
            body={
                "principal_id": principal,
                "project": project,
                "key_id": "pk_first",
                "already_existed": False,
                "public_key_registered": True,
                "private_key_stored": True,
                "error": None,
            }
        )

    report = provision_projects(
        runner=runner,
        projects=("qual_linux", "agent_provenance"),
        principal="suite-service",
    )
    assert report.ok is True
    assert report.outcome is ProvisionOutcome.DONE
    # Exactly one keypair was minted, and it is registered in both projects.
    assert minted == {"pk_first"}
    reuse_calls = [c for c in calls if "--reuse-existing-key" in c]
    assert len(reuse_calls) == 1
    assert reuse_calls[0][3] == "agent_provenance"
    assert "pk_first" in report.detail


def test_provisioning_stops_at_the_first_broken_project() -> None:
    seen: list[str] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd[3])
        if cmd[:2] == ("regista", "provision") and cmd[3] == "agent_provenance":
            return _fake_component(body=_PROVISION_ERROR_BODY)
        if cmd[:2] == ("regista", "provision"):
            return _fake_component(
                body=[{
                    "project": cmd[3],
                    "schema_created": True,
                    "migrations_applied": [],
                    "service_role_created": True,
                    "error": None,
                }]
            )
        return _fake_component(
            body={
                "principal_id": cmd[5],
                "project": cmd[3],
                "key_id": "pk_1",
                "already_existed": True,
                "public_key_registered": False,
                "error": None,
            }
        )

    report = provision_projects(
        runner=runner,
        projects=("qual_linux", "agent_provenance", "third"),
        principal="suite-service",
    )
    assert report.ok is False
    assert "third" not in seen


def test_no_projects_configured_is_a_failure() -> None:
    report = provision_projects(runner=lambda _cmd: _completed(), projects=())
    assert report.ok is False
    assert "REGISTA_PROJECT" in report.detail


def test_a_child_traceback_is_reduced_to_its_exception() -> None:
    """An operator needs the exception, not the child's call stack.

    Real case from the qual container: regista's vault provider lets
    ``hvac.exceptions.Forbidden`` escape instead of mapping it to the error
    envelope, so the whole traceback is all the suite gets.
    """
    result = evaluate_component_result(
        command="regista secrets --ref vault:kv/a/b/c",
        returncode=1,
        stdout="",
        stderr=(
            "Traceback (most recent call last):\n"
            '  File "/root/.local/bin/regista", line 10, in <module>\n'
            "    sys.exit(main())\n"
            '  File ".../regista/_secrets.py", line 374, in resolve\n'
            "    resp = client.secrets.kv.v2.read_secret_version(\n"
            "hvac.exceptions.Forbidden: 1 error occurred: permission denied\n"
        ),
    )
    assert result.ok is False
    assert "hvac.exceptions.Forbidden" in result.detail
    assert "permission denied" in result.detail
    assert "sys.exit" not in result.detail
    assert "child crashed" in result.detail
