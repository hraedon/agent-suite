"""Genuine separately authenticated dual control for protected operations.

A protected operation requires two distinct, independently authenticated
principals: a requester and an approver. The protocol is fail-closed — any
ambiguity, missing token, expired token, or same-principal check refuses the
operation.

This module defines the protocol; actual token validation (Entra, LDAP, etc.)
is performed by edge adapters that implement the ``TokenValidator`` protocol.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, assert_never


DEFAULT_TOKEN_TTL = 300
DEFAULT_REQUEST_TTL = 600


class ProtectedOperation(Enum):
    KEY_ROTATE = "key_rotate"
    KEY_REVOKE = "key_revoke"
    BREAK_GLASS = "break_glass"
    APPLY_SIGNED_BUNDLE = "apply_signed_bundle"
    SERVICE_REPAIR = "service_repair"
    RESTORE_AND_VERIFY = "restore_and_verify"


class StepUpLevel(Enum):
    SINGLE_FACTOR = "single_factor"
    MULTI_FACTOR = "multi_factor"
    HARD_TOKEN = "hard_token"


class DualControlState(Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"


class TokenValidator(Protocol):
    def validate(self, token: str, required_level: StepUpLevel) -> "ValidatedToken":
        ...


@dataclass(frozen=True)
class ValidatedToken:
    principal_id: str
    step_up_level: StepUpLevel
    validated_at: float
    expires_at: float
    token_hash: str

    def is_expired(self, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        return current >= self.expires_at

    def meets_level(self, required: StepUpLevel) -> bool:
        return _step_up_rank(self.step_up_level) >= _step_up_rank(required)


@dataclass(frozen=True)
class DualControlRequest:
    request_id: str
    operation: ProtectedOperation
    requester_principal: str
    operation_digest: str
    step_up_required: StepUpLevel
    created_at: float
    expires_at: float
    requester_token_hash: str

    def is_expired(self, now: float | None = None) -> bool:
        current = now if now is not None else time.time()
        return current >= self.expires_at


@dataclass(frozen=True)
class DualControlApproval:
    request_id: str
    approver_principal: str
    approved_at: float
    approver_token_hash: str
    operation_digest: str


@dataclass(frozen=True)
class DualControlDecision:
    state: DualControlState
    request_id: str
    operation: ProtectedOperation
    detail: str

    @property
    def is_approved(self) -> bool:
        return self.state is DualControlState.APPROVED

    def to_dict(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "detail": self.detail,
        }


def _hash_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def _step_up_rank(level: StepUpLevel) -> int:
    match level:
        case StepUpLevel.SINGLE_FACTOR:
            return 0
        case StepUpLevel.MULTI_FACTOR:
            return 1
        case StepUpLevel.HARD_TOKEN:
            return 2
        case _ as unreachable:
            assert_never(unreachable)


def compute_operation_digest(
    operation: ProtectedOperation, params: dict[str, object]
) -> str:
    canonical = json.dumps(
        {"operation": operation.value, "params": params},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def required_step_up(operation: ProtectedOperation) -> StepUpLevel:
    match operation:
        case ProtectedOperation.KEY_ROTATE:
            return StepUpLevel.MULTI_FACTOR
        case ProtectedOperation.KEY_REVOKE:
            return StepUpLevel.MULTI_FACTOR
        case ProtectedOperation.BREAK_GLASS:
            return StepUpLevel.HARD_TOKEN
        case ProtectedOperation.APPLY_SIGNED_BUNDLE:
            return StepUpLevel.MULTI_FACTOR
        case ProtectedOperation.SERVICE_REPAIR:
            return StepUpLevel.MULTI_FACTOR
        case ProtectedOperation.RESTORE_AND_VERIFY:
            return StepUpLevel.MULTI_FACTOR
        case _ as unreachable:
            assert_never(unreachable)


def create_request(
    operation: ProtectedOperation,
    requester_token: ValidatedToken,
    operation_params: dict[str, object],
    *,
    step_up_required: StepUpLevel | None = None,
    ttl: int = DEFAULT_REQUEST_TTL,
) -> DualControlRequest:
    """Create a dual control request from a validated requester token.

    Fails closed (raises ``ValueError``) if the token is expired or doesn't
    meet the step-up requirement. The ``step_up_required`` parameter may only
    raise the level above the operation's minimum — it cannot lower it.
    """
    minimum = required_step_up(operation)
    if step_up_required is not None:
        required = step_up_required if _step_up_rank(step_up_required) >= _step_up_rank(minimum) else minimum
    else:
        required = minimum

    if requester_token.is_expired():
        raise ValueError("requester token is expired")
    if not requester_token.meets_level(required):
        raise ValueError(
            f"requester token does not meet step-up requirement: "
            f"required {required.value}, got {requester_token.step_up_level.value}"
        )

    now = time.time()
    digest = compute_operation_digest(operation, operation_params)

    return DualControlRequest(
        request_id=secrets.token_hex(16),
        operation=operation,
        requester_principal=requester_token.principal_id,
        operation_digest=digest,
        step_up_required=required,
        created_at=now,
        expires_at=now + ttl,
        requester_token_hash=requester_token.token_hash,
    )


def evaluate_approval(
    request: DualControlRequest,
    approval: DualControlApproval,
    approver_token: ValidatedToken,
    *,
    now: float | None = None,
) -> DualControlDecision:
    """Evaluate whether a request + approval + approver token satisfies dual control.

    This is the core security gate. It is fail-closed: any check failure
    produces REJECTED or EXPIRED, never APPROVED.
    """
    current = now if now is not None else time.time()

    if request.is_expired(current):
        return DualControlDecision(
            state=DualControlState.EXPIRED,
            request_id=request.request_id,
            operation=request.operation,
            detail="request has expired",
        )

    if approver_token.is_expired(current):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail="approver token is expired",
        )

    if not approver_token.meets_level(request.step_up_required):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail=(
                f"approver token does not meet step-up requirement: "
                f"required {request.step_up_required.value}, "
                f"got {approver_token.step_up_level.value}"
            ),
        )

    if hmac.compare_digest(
        request.requester_principal, approver_token.principal_id
    ):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail=(
                "dual control requires two distinct principals — "
                "requester and approver are the same"
            ),
        )

    if not hmac.compare_digest(approval.request_id, request.request_id):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail="approval request_id does not match request",
        )

    if not hmac.compare_digest(approval.operation_digest, request.operation_digest):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail="approval operation_digest does not match request",
        )

    if not hmac.compare_digest(
        approval.approver_token_hash, approver_token.token_hash
    ):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail="approval approver_token_hash does not match approver token",
        )

    if not hmac.compare_digest(
        approval.approver_principal, approver_token.principal_id
    ):
        return DualControlDecision(
            state=DualControlState.REJECTED,
            request_id=request.request_id,
            operation=request.operation,
            detail="approval approver_principal does not match approver token",
        )

    return DualControlDecision(
        state=DualControlState.APPROVED,
        request_id=request.request_id,
        operation=request.operation,
        detail="dual control satisfied — two distinct principals authenticated",
    )


def create_approval(
    request: DualControlRequest,
    approver_token: ValidatedToken,
) -> DualControlApproval:
    """Create an approval from a validated approver token.

    Fails closed (raises ``ValueError``) if the request is expired, the
    approver token is expired, doesn't meet the step-up requirement, or is
    the same principal as the requester.
    """
    if request.is_expired():
        raise ValueError("request has expired")

    if approver_token.is_expired():
        raise ValueError("approver token is expired")

    if not approver_token.meets_level(request.step_up_required):
        raise ValueError(
            f"approver token does not meet step-up requirement: "
            f"required {request.step_up_required.value}, "
            f"got {approver_token.step_up_level.value}"
        )

    if hmac.compare_digest(request.requester_principal, approver_token.principal_id):
        raise ValueError(
            "dual control requires two distinct principals — "
            "approver is the same as requester"
        )

    return DualControlApproval(
        request_id=request.request_id,
        approver_principal=approver_token.principal_id,
        approved_at=time.time(),
        approver_token_hash=approver_token.token_hash,
        operation_digest=request.operation_digest,
    )
