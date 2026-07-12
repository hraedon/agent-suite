"""Protocol foundation for the Windows Agent Suite Setup surface.

Defines the closed preflight, plan, action, and receipt states, the
deterministic plan digest, and signed execution receipts (HMAC-SHA256).
A future CLI and UI must both supply the same read-only ``HostObservation``
and consume the deterministic plan/receipt functions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from agent_suite.profiles import Profile


PROTOCOL_VERSION = "1.0.0-draft.1"


class ProbeState(Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    UNSUPPORTED = "unsupported"


class PreflightState(Enum):
    READY = "ready"
    BLOCKED = "blocked"


class SetupOperation(Enum):
    INSTALL_RELEASE = "install_release"
    CONFIGURE_SERVICES = "configure_services"
    WIRE_HARNESSES = "wire_harnesses"
    APPLY_SIGNED_BUNDLE = "apply_signed_bundle"
    REPAIR = "repair"
    RESTORE_AND_VERIFY = "restore_and_verify"


class PlanState(Enum):
    READY = "ready"
    NO_OP = "no_op"
    BLOCKED = "blocked"


class ActionState(Enum):
    PLANNED = "planned"
    NO_OP = "no_op"
    REFUSED = "refused"
    SKIPPED_DRY_RUN = "skipped_dry_run"
    APPLIED = "applied"
    FAILED = "failed"


class ReceiptState(Enum):
    DRY_RUN = "dry_run"
    NO_OP = "no_op"
    BLOCKED = "blocked"
    APPLIED = "applied"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True)
class HostObservation:
    """Non-secret facts supplied by a platform-specific read-only probe."""

    os_name: str
    python_version: str
    powershell: ProbeState
    elevation: ProbeState
    service_account: ProbeState
    postgres: ProbeState
    dns: ProbeState
    tls: ProbeState
    secret_provider: ProbeState
    artifact_release_identity: str
    artifact_lock_identity: str
    ownership_conflict: bool
    satisfied_operations: frozenset[SetupOperation] = frozenset()


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    state: ProbeState
    required: bool
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "state": self.state.value,
            "required": self.required,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class PreflightReport:
    protocol_version: str
    state: PreflightState
    checks: tuple[PreflightCheck, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "state": self.state.value,
            "checks": [check.to_dict() for check in self.checks],
        }


@dataclass(frozen=True)
class SetupRequest:
    profile: Profile
    target_release_identity: str
    target_lock_identity: str
    operations: frozenset[SetupOperation]


@dataclass(frozen=True)
class PlannedAction:
    ident: str
    operation: SetupOperation
    summary: str
    state: ActionState

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.ident,
            "operation": self.operation.value,
            "summary": self.summary,
            "state": self.state.value,
        }


@dataclass(frozen=True)
class SetupPlan:
    protocol_version: str
    plan_id: str
    profile: Profile
    target_release_identity: str
    target_lock_identity: str
    state: PlanState
    actions: tuple[PlannedAction, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "plan_id": self.plan_id,
            "profile": self.profile.value,
            "target_release_identity": self.target_release_identity,
            "target_lock_identity": self.target_lock_identity,
            "state": self.state.value,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(frozen=True)
class ActionReceipt:
    ident: str
    state: ActionState

    def to_dict(self) -> dict[str, object]:
        return {"id": self.ident, "state": self.state.value}


@dataclass(frozen=True)
class SetupReceipt:
    protocol_version: str
    plan_id: str
    state: ReceiptState
    actions: tuple[ActionReceipt, ...]
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol_version": self.protocol_version,
            "plan_id": self.plan_id,
            "state": self.state.value,
            "actions": [action.to_dict() for action in self.actions],
            "detail": self.detail,
        }


def _probe_check(name: str, state: ProbeState, detail: str) -> PreflightCheck:
    return PreflightCheck(name=name, state=state, required=True, detail=detail)


def run_preflight(observation: HostObservation, request: SetupRequest) -> PreflightReport:
    """Evaluate supplied observations for the requested operations without acting."""
    operations = request.operations
    needs_elevation = bool(
        operations
        & {
            SetupOperation.CONFIGURE_SERVICES,
            SetupOperation.APPLY_SIGNED_BUNDLE,
            SetupOperation.REPAIR,
            SetupOperation.RESTORE_AND_VERIFY,
        }
    )
    needs_service_account = SetupOperation.CONFIGURE_SERVICES in operations
    needs_postgres = bool(
        operations
        & {
            SetupOperation.INSTALL_RELEASE,
            SetupOperation.CONFIGURE_SERVICES,
            SetupOperation.APPLY_SIGNED_BUNDLE,
            SetupOperation.RESTORE_AND_VERIFY,
        }
    )
    needs_secret_provider = needs_postgres
    needs_network = bool(operations)
    os_state = ProbeState.AVAILABLE if observation.os_name.lower() == "windows" else ProbeState.UNSUPPORTED
    python_state = _python_support(observation.python_version)
    identity_state = (
        ProbeState.AVAILABLE
        if observation.artifact_release_identity and observation.artifact_lock_identity
        else ProbeState.UNKNOWN
    )
    ownership_state = (
        ProbeState.UNAVAILABLE if observation.ownership_conflict else ProbeState.AVAILABLE
    )
    checks = (
        _probe_check("windows", os_state, "native Windows host required"),
        _probe_check("python", python_state, "Python 3.12 or newer required"),
        _probe_check("powershell", observation.powershell, "PowerShell availability"),
        PreflightCheck(
            "elevation",
            observation.elevation,
            needs_elevation,
            "required for host-authority operations",
        ),
        PreflightCheck(
            "service_account",
            observation.service_account,
            needs_service_account,
            "required when configuring Windows services",
        ),
        PreflightCheck("postgres", observation.postgres, needs_postgres, "Postgres reachability"),
        PreflightCheck("dns", observation.dns, needs_network, "DNS reachability"),
        PreflightCheck("tls", observation.tls, needs_network, "TLS reachability"),
        PreflightCheck(
            "secret_provider",
            observation.secret_provider,
            needs_secret_provider,
            "provider availability only",
        ),
        _probe_check("release_identity", identity_state, "immutable release and lock identity"),
        _probe_check("ownership", ownership_state, "no conflicting installation owner"),
    )
    ready = all(check.state is ProbeState.AVAILABLE for check in checks if check.required)
    return PreflightReport(
        protocol_version=PROTOCOL_VERSION,
        state=PreflightState.READY if ready else PreflightState.BLOCKED,
        checks=checks,
    )


def _python_support(version: str) -> ProbeState:
    parts = version.split(".")
    try:
        major, minor = int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return ProbeState.UNKNOWN
    return ProbeState.AVAILABLE if (major, minor) >= (3, 12) else ProbeState.UNSUPPORTED


def _summary(operation: SetupOperation) -> str:
    match operation:
        case SetupOperation.INSTALL_RELEASE:
            return "Install exact locked release artifacts"
        case SetupOperation.CONFIGURE_SERVICES:
            return "Configure owned Windows services and scheduled tasks"
        case SetupOperation.WIRE_HARNESSES:
            return "Wire selected harnesses for the selected Windows account"
        case SetupOperation.APPLY_SIGNED_BUNDLE:
            return "Validate and apply an allowlisted signed configuration bundle"
        case SetupOperation.REPAIR:
            return "Repair suite-owned state without clobbering unrelated state"
        case SetupOperation.RESTORE_AND_VERIFY:
            return "Guide restore and cryptographic verification"
        case _ as unreachable:
            assert_never(unreachable)


def build_plan(request: SetupRequest, observation: HostObservation) -> SetupPlan:
    """Build a canonical plan from the same request and observation; never execute it."""
    preflight = run_preflight(observation, request)
    identities_match = (
        request.target_release_identity == observation.artifact_release_identity
        and request.target_lock_identity == observation.artifact_lock_identity
    )
    blocked = (
        preflight.state is PreflightState.BLOCKED
        or not identities_match
    )
    actions: list[PlannedAction] = []
    for operation in sorted(request.operations, key=lambda item: item.value):
        if blocked:
            state = ActionState.REFUSED
        elif operation in observation.satisfied_operations:
            state = ActionState.NO_OP
        else:
            state = ActionState.PLANNED
        actions.append(
            PlannedAction(
                ident=f"setup.{operation.value}",
                operation=operation,
                summary=_summary(operation),
                state=state,
            )
        )
    if blocked:
        plan_state = PlanState.BLOCKED
    elif all(action.state is ActionState.NO_OP for action in actions):
        plan_state = PlanState.NO_OP
    else:
        plan_state = PlanState.READY
    unsigned = {
        "protocol_version": PROTOCOL_VERSION,
        "profile": request.profile.value,
        "target_release_identity": request.target_release_identity,
        "target_lock_identity": request.target_lock_identity,
        "state": plan_state.value,
        "actions": [action.to_dict() for action in actions],
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan_id = "sha256:" + hashlib.sha256(canonical).hexdigest()
    return SetupPlan(
        protocol_version=PROTOCOL_VERSION,
        plan_id=plan_id,
        profile=request.profile,
        target_release_identity=request.target_release_identity,
        target_lock_identity=request.target_lock_identity,
        state=plan_state,
        actions=tuple(actions),
    )


def dry_run(plan: SetupPlan) -> SetupReceipt:
    """Return a receipt proving no action was executed."""
    invalid_states = {
        ActionState.SKIPPED_DRY_RUN,
        ActionState.APPLIED,
        ActionState.FAILED,
    }
    if any(action.state in invalid_states for action in plan.actions):
        raise ValueError("dry_run accepts only canonical non-executed plan actions")
    if plan.state is PlanState.BLOCKED:
        receipt_state = ReceiptState.BLOCKED
        detail = "preflight blocked; no host actions executed"
    elif plan.state is PlanState.NO_OP:
        receipt_state = ReceiptState.NO_OP
        detail = "desired state already satisfied; no host actions executed"
    else:
        receipt_state = ReceiptState.DRY_RUN
        detail = "dry run only; no host actions executed"
    receipts = tuple(
        ActionReceipt(
            ident=action.ident,
            state=(
                ActionState.SKIPPED_DRY_RUN
                if action.state is ActionState.PLANNED
                else action.state
            ),
        )
        for action in plan.actions
    )
    return SetupReceipt(
        protocol_version=PROTOCOL_VERSION,
        plan_id=plan.plan_id,
        state=receipt_state,
        actions=receipts,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Signed execution receipts (HMAC-SHA256)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SigningKeyRef:
    """Reference to a signing key — never the key itself."""

    key_id: str
    algorithm: str

    def to_dict(self) -> dict[str, object]:
        return {"key_id": self.key_id, "algorithm": self.algorithm}


@dataclass(frozen=True)
class SignedReceipt:
    """A ``SetupReceipt`` with an HMAC-SHA256 signature over its canonical form."""

    receipt: SetupReceipt
    key_ref: SigningKeyRef
    signature: str

    def to_dict(self) -> dict[str, object]:
        return {
            "receipt": self.receipt.to_dict(),
            "key_ref": self.key_ref.to_dict(),
            "signature": self.signature,
        }


def _canonical_receipt(receipt: SetupReceipt, key_ref: SigningKeyRef) -> bytes:
    """Deterministic canonical form for signing/verification.

    Includes both the receipt content and the key reference, so that
    tampering with either the receipt or the key_id invalidates the
    signature.
    """
    unsigned = {
        "receipt": {
            "protocol_version": receipt.protocol_version,
            "plan_id": receipt.plan_id,
            "state": receipt.state.value,
            "actions": [action.to_dict() for action in receipt.actions],
            "detail": receipt.detail,
        },
        "key_ref": key_ref.to_dict(),
    }
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_receipt(receipt: SetupReceipt, key: bytes, key_id: str) -> SignedReceipt:
    """Sign a receipt with HMAC-SHA256.

    The ``key`` is the raw HMAC key bytes, provided by the caller (resolved
    from DPAPI, Vault, etc.). The module never stores or resolves the key.
    """
    key_ref = SigningKeyRef(key_id=key_id, algorithm="hmac-sha256")
    canonical = _canonical_receipt(receipt, key_ref)
    signature = hmac.new(key, canonical, hashlib.sha256).hexdigest()
    return SignedReceipt(
        receipt=receipt,
        key_ref=key_ref,
        signature=signature,
    )


def verify_signed_receipt(signed: SignedReceipt, key: bytes) -> bool:
    """Verify the signature. Returns ``True`` if valid, ``False`` otherwise.

    Never raises — all errors (bad key, tampered receipt, malformed data,
    wrong algorithm) return ``False``.
    """
    try:
        if signed.key_ref.algorithm != "hmac-sha256":
            return False
        canonical = _canonical_receipt(signed.receipt, signed.key_ref)
        expected = hmac.new(key, canonical, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signed.signature)
    except Exception:
        return False
