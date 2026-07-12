from __future__ import annotations

import time

import pytest

from agent_suite.dual_control import (
    DEFAULT_REQUEST_TTL,
    DEFAULT_TOKEN_TTL,
    DualControlApproval,
    DualControlDecision,
    DualControlRequest,
    DualControlState,
    ProtectedOperation,
    StepUpLevel,
    ValidatedToken,
    _hash_token,
    compute_operation_digest,
    create_approval,
    create_request,
    evaluate_approval,
    required_step_up,
)


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


def test_compute_operation_digest_is_deterministic() -> None:
    d1 = compute_operation_digest(ProtectedOperation.KEY_ROTATE, {"key_id": "k1"})
    d2 = compute_operation_digest(ProtectedOperation.KEY_ROTATE, {"key_id": "k1"})
    assert d1 == d2


def test_compute_operation_digest_is_parameter_sensitive() -> None:
    d1 = compute_operation_digest(ProtectedOperation.KEY_ROTATE, {"key_id": "k1"})
    d2 = compute_operation_digest(ProtectedOperation.KEY_ROTATE, {"key_id": "k2"})
    assert d1 != d2


def test_compute_operation_digest_is_operation_sensitive() -> None:
    d1 = compute_operation_digest(ProtectedOperation.KEY_ROTATE, {"key_id": "k1"})
    d2 = compute_operation_digest(ProtectedOperation.KEY_REVOKE, {"key_id": "k1"})
    assert d1 != d2


def test_create_request_succeeds_with_valid_token() -> None:
    request = _make_request()
    assert request.operation is ProtectedOperation.KEY_ROTATE
    assert request.requester_principal == "user-001"
    assert request.request_id
    assert request.operation_digest.startswith("sha256:")


def test_create_request_fails_on_expired_token() -> None:
    expired_token = _make_token(expires_in=-1)
    with pytest.raises(ValueError, match="expired"):
        create_request(
            operation=ProtectedOperation.KEY_ROTATE,
            requester_token=expired_token,
            operation_params={},
        )


def test_create_request_fails_on_insufficient_step_up() -> None:
    weak_token = _make_token(level=StepUpLevel.SINGLE_FACTOR)
    with pytest.raises(ValueError, match="step-up"):
        create_request(
            operation=ProtectedOperation.KEY_ROTATE,
            requester_token=weak_token,
            operation_params={},
        )


def test_evaluate_approval_approves_with_two_distinct_principals() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-002")
    approval = create_approval(request, approver_token)
    decision = evaluate_approval(request, approval, approver_token)
    assert decision.is_approved
    assert decision.state is DualControlState.APPROVED


def test_evaluate_approval_rejects_same_principal() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-001")
    with pytest.raises(ValueError, match="distinct"):
        create_approval(request, approver_token)


def test_evaluate_approval_rejects_expired_request() -> None:
    request = _make_request()
    expired_request = DualControlRequest(
        request_id=request.request_id,
        operation=request.operation,
        requester_principal=request.requester_principal,
        operation_digest=request.operation_digest,
        step_up_required=request.step_up_required,
        created_at=request.created_at - DEFAULT_REQUEST_TTL - 1,
        expires_at=request.created_at - 1,
        requester_token_hash=request.requester_token_hash,
    )
    approver_token = _make_token(principal="user-002")
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash=approver_token.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(expired_request, approval, approver_token)
    assert decision.state is DualControlState.EXPIRED


def test_evaluate_approval_rejects_expired_approver_token() -> None:
    request = _make_request(requester="user-001")
    expired_approver = ValidatedToken(
        principal_id="user-002",
        step_up_level=StepUpLevel.MULTI_FACTOR,
        validated_at=time.time() - DEFAULT_TOKEN_TTL - 1,
        expires_at=time.time() - 1,
        token_hash=_hash_token("expired"),
    )
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash=expired_approver.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, expired_approver)
    assert decision.state is DualControlState.REJECTED
    assert "expired" in decision.detail


def test_evaluate_approval_rejects_insufficient_step_up_on_approver() -> None:
    request = _make_request(requester="user-001")
    weak_approver = _make_token(principal="user-002", level=StepUpLevel.SINGLE_FACTOR)
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash=weak_approver.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, weak_approver)
    assert decision.state is DualControlState.REJECTED
    assert "step-up" in decision.detail


def test_evaluate_approval_rejects_digest_mismatch() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-002")
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash=approver_token.token_hash,
        operation_digest="sha256:wrong",
    )
    decision = evaluate_approval(request, approval, approver_token)
    assert decision.state is DualControlState.REJECTED
    assert "digest" in decision.detail


def test_evaluate_approval_rejects_request_id_mismatch() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-002")
    approval = DualControlApproval(
        request_id="wrong-id",
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash=approver_token.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, approver_token)
    assert decision.state is DualControlState.REJECTED
    assert "request_id" in decision.detail


def test_evaluate_approval_rejects_token_hash_mismatch() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-002")
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-002",
        approved_at=time.time(),
        approver_token_hash="sha256:wrong",
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, approver_token)
    assert decision.state is DualControlState.REJECTED
    assert "token_hash" in decision.detail


def test_required_step_up_returns_correct_levels() -> None:
    assert required_step_up(ProtectedOperation.KEY_ROTATE) is StepUpLevel.MULTI_FACTOR
    assert required_step_up(ProtectedOperation.KEY_REVOKE) is StepUpLevel.MULTI_FACTOR
    assert required_step_up(ProtectedOperation.BREAK_GLASS) is StepUpLevel.HARD_TOKEN
    assert required_step_up(ProtectedOperation.APPLY_SIGNED_BUNDLE) is StepUpLevel.MULTI_FACTOR
    assert required_step_up(ProtectedOperation.SERVICE_REPAIR) is StepUpLevel.MULTI_FACTOR
    assert required_step_up(ProtectedOperation.RESTORE_AND_VERIFY) is StepUpLevel.MULTI_FACTOR


def test_validated_token_meets_level() -> None:
    mfa = _make_token(level=StepUpLevel.MULTI_FACTOR)
    assert mfa.meets_level(StepUpLevel.SINGLE_FACTOR)
    assert mfa.meets_level(StepUpLevel.MULTI_FACTOR)
    assert not mfa.meets_level(StepUpLevel.HARD_TOKEN)


def test_decision_to_dict() -> None:
    decision = DualControlDecision(
        state=DualControlState.APPROVED,
        request_id="req-001",
        operation=ProtectedOperation.KEY_ROTATE,
        detail="ok",
    )
    d = decision.to_dict()
    assert d["state"] == "approved"
    assert d["request_id"] == "req-001"
    assert d["operation"] == "key_rotate"


def test_create_approval_fails_on_expired_token() -> None:
    request = _make_request(requester="user-001")
    expired = _make_token(principal="user-002", expires_in=-1)
    with pytest.raises(ValueError, match="expired"):
        create_approval(request, expired)


def test_create_approval_fails_on_insufficient_step_up() -> None:
    request = _make_request(requester="user-001")
    weak = _make_token(principal="user-002", level=StepUpLevel.SINGLE_FACTOR)
    with pytest.raises(ValueError, match="step-up"):
        create_approval(request, weak)


def test_evaluate_approval_rejects_same_principal_directly() -> None:
    request = _make_request(requester="user-001")
    same_principal_token = _make_token(principal="user-001")
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-001",
        approved_at=time.time(),
        approver_token_hash=same_principal_token.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, same_principal_token)
    assert decision.state is DualControlState.REJECTED
    assert "distinct" in decision.detail


def test_evaluate_approval_rejects_approver_principal_mismatch() -> None:
    request = _make_request(requester="user-001")
    approver_token = _make_token(principal="user-002")
    approval = DualControlApproval(
        request_id=request.request_id,
        approver_principal="user-999",
        approved_at=time.time(),
        approver_token_hash=approver_token.token_hash,
        operation_digest=request.operation_digest,
    )
    decision = evaluate_approval(request, approval, approver_token)
    assert decision.state is DualControlState.REJECTED
    assert "approver_principal" in decision.detail


def test_create_request_rejects_step_up_downgrade() -> None:
    token = _make_token(level=StepUpLevel.HARD_TOKEN)
    request = create_request(
        operation=ProtectedOperation.BREAK_GLASS,
        requester_token=token,
        operation_params={},
        step_up_required=StepUpLevel.SINGLE_FACTOR,
    )
    assert request.step_up_required is StepUpLevel.HARD_TOKEN


def test_create_approval_fails_on_expired_request() -> None:
    request = _make_request(requester="user-001")
    expired_request = DualControlRequest(
        request_id=request.request_id,
        operation=request.operation,
        requester_principal=request.requester_principal,
        operation_digest=request.operation_digest,
        step_up_required=request.step_up_required,
        created_at=request.created_at - DEFAULT_REQUEST_TTL - 1,
        expires_at=request.created_at - 1,
        requester_token_hash=request.requester_token_hash,
    )
    approver_token = _make_token(principal="user-002")
    with pytest.raises(ValueError, match="request has expired"):
        create_approval(expired_request, approver_token)
