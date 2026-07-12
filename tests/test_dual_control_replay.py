from __future__ import annotations

import time
from pathlib import Path

from agent_suite.dual_control import (
    DEFAULT_TOKEN_TTL,
    DualControlApproval,
    DualControlRequest,
    DualControlState,
    ProtectedOperation,
    StepUpLevel,
    ValidatedToken,
    _hash_token,
    create_approval,
    create_request,
    evaluate_approval,
    mark_executed,
)
from agent_suite.dual_control_store import DualControlStore


def _make_token(
    principal: str = "user-001",
    level: StepUpLevel = StepUpLevel.MULTI_FACTOR,
    expires_in: float = DEFAULT_TOKEN_TTL,
) -> ValidatedToken:
    now = time.time()
    return ValidatedToken(
        principal_id=principal,
        step_up_level=level,
        validated_at=now,
        expires_at=now + expires_in,
        token_hash=_hash_token(f"token-{principal}-{now}"),
    )


def _make_request(
    operation: ProtectedOperation = ProtectedOperation.KEY_ROTATE,
    requester: str = "user-001",
    params: dict[str, object] | None = None,
) -> DualControlRequest:
    token = _make_token(principal=requester)
    return create_request(
        operation=operation,
        requester_token=token,
        operation_params=params or {"key_id": "key-001"},
    )


def _make_approval(request: DualControlRequest) -> DualControlApproval:
    approver_token = _make_token(principal="user-002")
    return create_approval(request, approver_token)


def _make_approver_token(principal: str = "user-002") -> ValidatedToken:
    return _make_token(principal=principal)


def test_evaluate_with_store_rejects_replay(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)

    decision1 = evaluate_approval(request, approval, approver_token, store=store)
    assert decision1.is_approved

    decision2 = evaluate_approval(request, approval, approver_token, store=store)
    assert decision2.state is DualControlState.REJECTED
    assert "already approved" in decision2.detail
    assert "replay" in decision2.detail


def test_evaluate_with_store_rejects_executed_replay(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)

    decision1 = evaluate_approval(request, approval, approver_token, store=store)
    assert decision1.is_approved

    store.mark_executed(request.request_id)

    decision2 = evaluate_approval(request, approval, approver_token, store=store)
    assert decision2.state is DualControlState.REJECTED
    assert "already executed" in decision2.detail
    assert "replay" in decision2.detail


def test_evaluate_with_store_rejects_unknown_request(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)

    decision = evaluate_approval(request, approval, approver_token, store=store)
    assert decision.state is DualControlState.REJECTED
    assert "not found in store" in decision.detail


def test_evaluate_without_store_works_as_before(tmp_path: Path) -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)

    decision = evaluate_approval(request, approval, approver_token)
    assert decision.is_approved
    assert decision.state is DualControlState.APPROVED


def test_evaluate_with_store_records_approval(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)

    decision = evaluate_approval(request, approval, approver_token, store=store)
    assert decision.is_approved

    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.APPROVED
    assert record.approval is not None
    assert record.approval.request_id == approval.request_id


def test_mark_executed_succeeds(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    approver_token = _make_approver_token()
    approval = create_approval(request, approver_token)
    store.approve(request.request_id, approval)

    decision = mark_executed(request.request_id, store)
    assert decision.state is DualControlState.EXECUTED
    assert decision.request_id == request.request_id
    assert decision.operation is request.operation

    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.EXECUTED


def test_mark_executed_fails_on_non_approved(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    decision = mark_executed(request.request_id, store)
    assert decision.state is DualControlState.FAILED
    assert "store error" in decision.detail


def test_mark_executed_fails_on_unknown_request(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")

    decision = mark_executed("nonexistent-id", store)
    assert decision.state is DualControlState.FAILED
    assert "store error" in decision.detail
