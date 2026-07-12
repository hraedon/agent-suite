from __future__ import annotations

import json

from agent_suite.windows_setup import (
    ActionState,
    HostObservation,
    PlanState,
    PreflightState,
    ProbeState,
    ReceiptState,
    SetupOperation,
    SetupRequest,
    build_plan,
    dry_run,
    run_preflight,
)
from agent_suite.profiles import Profile


def _observation(**changes: object) -> HostObservation:
    values: dict[str, object] = {
        "os_name": "Windows",
        "python_version": "3.12.4",
        "powershell": ProbeState.AVAILABLE,
        "elevation": ProbeState.AVAILABLE,
        "service_account": ProbeState.AVAILABLE,
        "postgres": ProbeState.AVAILABLE,
        "dns": ProbeState.AVAILABLE,
        "tls": ProbeState.AVAILABLE,
        "secret_provider": ProbeState.AVAILABLE,
        "artifact_release_identity": "release:example-1",
        "artifact_lock_identity": "sha256:" + "a" * 64,
        "ownership_conflict": False,
    }
    values.update(changes)
    return HostObservation(**values)  # type: ignore[arg-type]


def _request(*operations: SetupOperation) -> SetupRequest:
    return SetupRequest(
        profile=Profile.B,
        target_release_identity="release:example-1",
        target_lock_identity="sha256:" + "a" * 64,
        operations=frozenset(operations),
    )


def test_ready_plan_is_deterministic_and_dry_run_never_applies() -> None:
    observation = _observation()
    request = _request(SetupOperation.WIRE_HARNESSES, SetupOperation.INSTALL_RELEASE)
    preflight = run_preflight(observation, request)
    first = build_plan(request, observation)
    second = build_plan(request, observation)
    assert preflight.state is PreflightState.READY
    assert first == second
    assert first.plan_id.startswith("sha256:")
    assert json.dumps(first.to_dict(), sort_keys=True) == json.dumps(second.to_dict(), sort_keys=True)
    receipt = dry_run(first)
    assert receipt.state is ReceiptState.DRY_RUN
    assert {action.state for action in receipt.actions} == {ActionState.SKIPPED_DRY_RUN}
    assert receipt.state not in {ReceiptState.APPLIED, ReceiptState.PARTIAL, ReceiptState.FAILED}
    assert "no host actions executed" in receipt.detail


def test_failed_required_probe_blocks_and_refuses_every_action() -> None:
    observation = _observation(postgres=ProbeState.UNAVAILABLE)
    request = _request(SetupOperation.INSTALL_RELEASE)
    preflight = run_preflight(observation, request)
    plan = build_plan(request, observation)
    receipt = dry_run(plan)
    assert preflight.state is PreflightState.BLOCKED
    assert plan.state is PlanState.BLOCKED
    assert [action.state for action in plan.actions] == [ActionState.REFUSED]
    assert receipt.state is ReceiptState.BLOCKED


def test_satisfied_operations_are_explicit_no_op() -> None:
    satisfied = frozenset({SetupOperation.INSTALL_RELEASE, SetupOperation.CONFIGURE_SERVICES})
    observation = _observation(satisfied_operations=satisfied)
    request = _request(SetupOperation.CONFIGURE_SERVICES, SetupOperation.INSTALL_RELEASE)
    plan = build_plan(request, observation)
    receipt = dry_run(plan)
    assert plan.state is PlanState.NO_OP
    assert {action.state for action in plan.actions} == {ActionState.NO_OP}
    assert receipt.state is ReceiptState.NO_OP


def test_non_windows_and_unknown_version_fail_closed() -> None:
    request = _request(SetupOperation.WIRE_HARNESSES)
    report = run_preflight(_observation(os_name="Linux", python_version="unknown"), request)
    assert report.state is PreflightState.BLOCKED
    states = {check.name: check.state for check in report.checks}
    assert states["windows"] is ProbeState.UNSUPPORTED
    assert states["python"] is ProbeState.UNKNOWN


def test_empty_operation_set_is_no_op() -> None:
    observation = _observation()
    request = _request()
    plan = build_plan(request, observation)
    assert plan.state is PlanState.NO_OP
    assert dry_run(plan).state is ReceiptState.NO_OP


def test_plan_refuses_release_or_lock_identity_mismatch() -> None:
    observation = _observation()
    request = SetupRequest(
        profile=Profile.B,
        target_release_identity="release:different",
        target_lock_identity="sha256:" + "b" * 64,
        operations=frozenset({SetupOperation.INSTALL_RELEASE}),
    )
    plan = build_plan(request, observation)
    assert plan.state is PlanState.BLOCKED
    assert [action.state for action in plan.actions] == [ActionState.REFUSED]


def test_per_user_harness_wiring_does_not_require_elevation_or_service_account() -> None:
    observation = _observation(
        elevation=ProbeState.UNAVAILABLE,
        service_account=ProbeState.UNAVAILABLE,
        postgres=ProbeState.UNAVAILABLE,
        secret_provider=ProbeState.UNAVAILABLE,
    )
    request = _request(SetupOperation.WIRE_HARNESSES)
    report = run_preflight(observation, request)
    checks = {check.name: check for check in report.checks}
    assert report.state is PreflightState.READY
    assert checks["elevation"].required is False
    assert checks["service_account"].required is False
    assert checks["postgres"].required is False
    assert checks["secret_provider"].required is False


def test_service_configuration_requires_elevation_and_service_account() -> None:
    observation = _observation(
        elevation=ProbeState.UNAVAILABLE,
        service_account=ProbeState.UNAVAILABLE,
    )
    request = _request(SetupOperation.CONFIGURE_SERVICES)
    report = run_preflight(observation, request)
    checks = {check.name: check for check in report.checks}
    assert report.state is PreflightState.BLOCKED
    assert checks["elevation"].required is True
    assert checks["service_account"].required is True


def test_dry_run_rejects_forged_executed_action_state() -> None:
    observation = _observation()
    request = _request(SetupOperation.INSTALL_RELEASE)
    plan = build_plan(request, observation)
    forged = type(plan)(
        protocol_version=plan.protocol_version,
        plan_id=plan.plan_id,
        profile=plan.profile,
        target_release_identity=plan.target_release_identity,
        target_lock_identity=plan.target_lock_identity,
        state=plan.state,
        actions=(
            type(plan.actions[0])(
                ident=plan.actions[0].ident,
                operation=plan.actions[0].operation,
                summary=plan.actions[0].summary,
                state=ActionState.APPLIED,
            ),
        ),
    )
    import pytest

    with pytest.raises(ValueError, match="canonical non-executed"):
        dry_run(forged)
