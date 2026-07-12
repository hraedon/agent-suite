from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_suite.windows_setup import (
    PROTOCOL_VERSION,
    ActionState,
    HostObservation,
    PlanState,
    PlannedAction,
    PreflightState,
    ProbeState,
    ReceiptState,
    SetupOperation,
    SetupPlan,
    SetupRequest,
    SigningKeyStore,
    apply_plan,
    build_plan,
    dry_run,
    profile_operations,
    run_preflight,
    sign_receipt,
    verify_signed_receipt,
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


# ---------------------------------------------------------------------------
# WI-1.1 — Profile-aware operation selection
# ---------------------------------------------------------------------------


def test_profile_operations_a() -> None:
    ops = profile_operations(Profile.A)
    assert ops == frozenset({SetupOperation.WIRE_HARNESSES})


def test_profile_operations_b() -> None:
    ops = profile_operations(Profile.B)
    assert ops == frozenset({
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
    })


def test_profile_operations_c() -> None:
    ops = profile_operations(Profile.C)
    assert ops == frozenset({
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
        SetupOperation.CONFIGURE_SERVICES,
    })


# ---------------------------------------------------------------------------
# WI-1.2 — Artifact install executor
# ---------------------------------------------------------------------------


def test_apply_plan_dry_run_delegates() -> None:
    observation = _observation()
    request = _request(SetupOperation.WIRE_HARNESSES)
    plan = build_plan(request, observation)
    assert plan.state is PlanState.READY
    receipt = apply_plan(plan, dry_run=True)
    assert receipt.state is ReceiptState.DRY_RUN
    assert {a.state for a in receipt.actions} == {ActionState.SKIPPED_DRY_RUN}


def test_apply_plan_rejects_non_ready_plan() -> None:
    blocked_obs = _observation(postgres=ProbeState.UNAVAILABLE)
    blocked_req = _request(SetupOperation.INSTALL_RELEASE)
    blocked_plan = build_plan(blocked_req, blocked_obs)
    assert blocked_plan.state is PlanState.BLOCKED
    with pytest.raises(ValueError, match="READY"):
        apply_plan(blocked_plan)

    satisfied = frozenset({SetupOperation.WIRE_HARNESSES})
    noop_obs = _observation(satisfied_operations=satisfied)
    noop_req = _request(SetupOperation.WIRE_HARNESSES)
    noop_plan = build_plan(noop_req, noop_obs)
    assert noop_plan.state is PlanState.NO_OP
    with pytest.raises(ValueError, match="READY"):
        apply_plan(noop_plan)


def test_apply_plan_all_succeed() -> None:
    observation = _observation()
    request = _request(
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
    )
    plan = build_plan(request, observation)
    assert plan.state is PlanState.READY

    runners = {
        SetupOperation.WIRE_HARNESSES.value: lambda action: ActionState.APPLIED,
        SetupOperation.INSTALL_RELEASE.value: lambda action: ActionState.APPLIED,
    }
    receipt = apply_plan(plan, runners=runners)
    assert receipt.state is ReceiptState.APPLIED
    assert all(a.state is ActionState.APPLIED for a in receipt.actions)


def test_apply_plan_partial_failure() -> None:
    observation = _observation()
    request = _request(
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
    )
    plan = build_plan(request, observation)

    runners = {
        SetupOperation.WIRE_HARNESSES.value: lambda action: ActionState.APPLIED,
        SetupOperation.INSTALL_RELEASE.value: lambda action: ActionState.FAILED,
    }
    receipt = apply_plan(plan, runners=runners)
    assert receipt.state is ReceiptState.PARTIAL
    states = {a.ident: a.state for a in receipt.actions}
    assert states["setup.wire_harnesses"] is ActionState.APPLIED
    assert states["setup.install_release"] is ActionState.FAILED


def test_apply_plan_all_fail() -> None:
    observation = _observation()
    request = _request(
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
    )
    plan = build_plan(request, observation)

    runners = {
        SetupOperation.WIRE_HARNESSES.value: lambda action: ActionState.FAILED,
        SetupOperation.INSTALL_RELEASE.value: lambda action: ActionState.FAILED,
    }
    receipt = apply_plan(plan, runners=runners)
    assert receipt.state is ReceiptState.FAILED
    assert all(a.state is ActionState.FAILED for a in receipt.actions)


def test_apply_plan_no_op_actions_pass_through() -> None:
    satisfied = frozenset({SetupOperation.WIRE_HARNESSES})
    observation = _observation(satisfied_operations=satisfied)
    request = _request(
        SetupOperation.WIRE_HARNESSES,
        SetupOperation.INSTALL_RELEASE,
    )
    plan = build_plan(request, observation)
    assert plan.state is PlanState.READY

    action_states = {a.operation: a.state for a in plan.actions}
    assert action_states[SetupOperation.WIRE_HARNESSES] is ActionState.NO_OP
    assert action_states[SetupOperation.INSTALL_RELEASE] is ActionState.PLANNED

    runners = {
        SetupOperation.INSTALL_RELEASE.value: lambda action: ActionState.APPLIED,
    }
    receipt = apply_plan(plan, runners=runners)
    receipt_states = {a.ident: a.state for a in receipt.actions}
    assert receipt_states["setup.wire_harnesses"] is ActionState.NO_OP
    assert receipt_states["setup.install_release"] is ActionState.APPLIED
    assert receipt.state is ReceiptState.APPLIED


def test_apply_plan_refused_actions_pass_through() -> None:
    actions = (
        PlannedAction(
            ident="setup.wire_harnesses",
            operation=SetupOperation.WIRE_HARNESSES,
            summary="Wire selected harnesses for the selected Windows account",
            state=ActionState.REFUSED,
        ),
        PlannedAction(
            ident="setup.install_release",
            operation=SetupOperation.INSTALL_RELEASE,
            summary="Install exact locked release artifacts",
            state=ActionState.PLANNED,
        ),
    )
    plan = SetupPlan(
        protocol_version=PROTOCOL_VERSION,
        plan_id="sha256:test-refused-passthrough",
        profile=Profile.B,
        target_release_identity="release:example-1",
        target_lock_identity="sha256:" + "a" * 64,
        state=PlanState.READY,
        actions=actions,
    )

    runners = {
        SetupOperation.INSTALL_RELEASE.value: lambda action: ActionState.APPLIED,
    }
    receipt = apply_plan(plan, runners=runners)
    receipt_states = {a.ident: a.state for a in receipt.actions}
    assert receipt_states["setup.wire_harnesses"] is ActionState.REFUSED
    assert receipt_states["setup.install_release"] is ActionState.APPLIED
    assert receipt.state is ReceiptState.APPLIED


# ---------------------------------------------------------------------------
# WI-1.3 — DPAPI-protected signing key custody
# ---------------------------------------------------------------------------


def test_signing_key_store_creates_key(tmp_path: Path) -> None:
    store = SigningKeyStore(tmp_path, dpapi_available=False)
    key_bytes, key_id = store.get_or_create_key("test-key")
    assert key_id == "test-key"
    assert len(key_bytes) == 32
    assert (tmp_path / "test-key.bin").exists()


def test_signing_key_store_loads_existing_key(tmp_path: Path) -> None:
    store = SigningKeyStore(tmp_path, dpapi_available=False)
    first_bytes, first_id = store.get_or_create_key("test-key")
    second_bytes, second_id = store.get_or_create_key("test-key")
    assert first_id == second_id
    assert first_bytes == second_bytes


def test_signing_key_store_rotate(tmp_path: Path) -> None:
    store = SigningKeyStore(tmp_path, dpapi_available=False)
    old_bytes, old_id = store.get_or_create_key("default")
    assert old_id == "default"
    assert (tmp_path / "default.bin").exists()

    new_bytes, new_id = store.rotate_key("default")
    assert new_id != "default"
    assert new_id.startswith("default-")
    assert len(new_bytes) == 32
    assert new_bytes != old_bytes

    assert not (tmp_path / "default.bin").exists()
    archived_files = list(tmp_path.glob("default.archived-*.bin"))
    assert len(archived_files) == 1
    assert (tmp_path / f"{new_id}.bin").exists()

    archived_bytes = archived_files[0].read_bytes()
    assert archived_bytes == old_bytes


def test_signing_key_store_without_dpapi(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = SigningKeyStore(tmp_path, dpapi_available=False)
    key_bytes, _ = store.get_or_create_key("plaintext-key")

    raw_bytes = (tmp_path / "plaintext-key.bin").read_bytes()
    assert raw_bytes == key_bytes
    assert len(raw_bytes) == 32

    warnings = [
        r for r in caplog.records
        if r.levelname == "WARNING" and "plaintext" in r.message.lower()
    ]
    assert len(warnings) >= 1


def test_signing_key_store_key_id_in_receipt(tmp_path: Path) -> None:
    store = SigningKeyStore(tmp_path, dpapi_available=False)
    key_bytes, key_id = store.get_or_create_key("suite-signing-key")

    observation = _observation()
    request = _request(SetupOperation.WIRE_HARNESSES)
    plan = build_plan(request, observation)
    receipt = dry_run(plan)

    signed = sign_receipt(receipt, key_bytes, key_id)
    assert signed.key_ref.key_id == "suite-signing-key"
    assert signed.key_ref.algorithm == "hmac-sha256"
    assert verify_signed_receipt(signed, key_bytes) is True
