"""Is a chain actually *attributable*? — read regista's own verdict, honestly.

Two closely related defects, both "presence read as verification":

**WI-051.** ``regista replay`` gained a real principal-binding check: it fails
when the key the signer would select for a principal is not active in the
project the events live in. `verify_restore` read only ``warnings`` and so
reported a cross-project key collision as *"possible chain-link tampering"* —
which points the operator at entirely the wrong thing. The chain links are
intact and the signatures are valid; the problem is that nothing is
**attributable**, and only ``regista bundle verify`` rejects it.

The same WI is why a missing count must never read as zero. ``ReplayReport``
emits ``principal_binding_verified`` always and omits
``principal_binding_failures`` when the check did not run — deliberately, so no
consumer can read "not checked" as "zero failures". This module honours that:
:func:`principal_binding` reports ``NOT_VERIFIED`` unless the child said the
check ran.

**WI-052 ask 4.** ``bootstrap-contract.md`` §5 requires the mixed human+agent
chain to verify "with per-actor signatures", and the Lane C lock went green
while producing *4 signatures verified, 1 unverifiable (symmetric scheme)* — the
human leg, signed with the shared store HMAC key that anybody holding it could
forge. "The bundle verified" is not that requirement. :func:`bundle_verdict`
makes the requirement checkable: every signature verified, **zero
unverifiable**, and the check enforced rather than skipped.

A prose requirement that a green lock can violate is not a gate, so the
assertion lives here as a function with tests, not as a sentence in a document.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, assert_never

__all__ = [
    "BindingStatus",
    "BundleVerdict",
    "PrincipalBinding",
    "bundle_verdict",
    "principal_binding",
]


class BindingStatus(StrEnum):
    """Whether a replay proved the events are attributable to their signers."""

    #: The check ran and found every event's signer registered in the project.
    VERIFIED = "verified"
    #: The check ran and found events signed by a key the project never
    #: registered. The chain is intact and unattributable.
    FAILED = "failed"
    #: The check did not run. Not a pass — an absence of evidence.
    NOT_VERIFIED = "not_verified"


@dataclass(frozen=True)
class PrincipalBinding:
    """What a ``regista replay --json`` payload says about attributability."""

    status: BindingStatus
    failures: int | None
    detail: str

    @property
    def ok(self) -> bool:
        match self.status:
            case BindingStatus.VERIFIED:
                return True
            case BindingStatus.FAILED | BindingStatus.NOT_VERIFIED:
                return False
            case other:
                assert_never(other)


def principal_binding(payload: Mapping[str, Any]) -> PrincipalBinding:
    """Read the principal-binding verdict out of a replay payload.

    ``principal_binding_verified`` is the gate. An older regista, or a caller
    that passed ``--no-verify-principal-binding``, does not emit a count at all;
    absent that flag being true, this reports ``NOT_VERIFIED`` even when
    ``failures`` reads as 0.
    """
    verified = payload.get("principal_binding_verified")
    raw_failures = payload.get("principal_binding_failures")
    failures: int | None
    try:
        failures = None if raw_failures is None else int(raw_failures)
    except (TypeError, ValueError):
        failures = None
        return PrincipalBinding(
            BindingStatus.NOT_VERIFIED,
            None,
            "regista replay emitted a non-numeric principal_binding_failures; "
            "treating the binding as unverified",
        )

    if failures is not None and failures > 0:
        return PrincipalBinding(
            BindingStatus.FAILED,
            failures,
            f"{failures} event(s) signed by a key not registered in this "
            f"project — the chain is intact but not attributable, and "
            f"`regista bundle verify` will reject it",
        )
    if verified is not True:
        return PrincipalBinding(
            BindingStatus.NOT_VERIFIED,
            failures,
            "regista replay did not verify principal binding "
            "(principal_binding_verified is not true), so a zero failure count "
            "would mean 'not checked', not 'none found'",
        )
    return PrincipalBinding(
        BindingStatus.VERIFIED,
        failures or 0,
        "every event's signing key is registered to its actor in this project",
    )


@dataclass(frozen=True)
class BundleVerdict:
    """Whether an audit bundle meets the §5 per-actor-signature requirement."""

    ok: bool
    events: int
    verified: int
    unverifiable: int | None
    detail: str


def bundle_verdict(payload: Mapping[str, Any]) -> BundleVerdict:
    """Judge a ``regista bundle verify --json`` payload against §5.

    Requires all four of: the bundle verified; the signature check was
    *enforced*; every signature verified; and ``signatures_unverifiable`` is
    present **and** zero. A symmetric ("unverifiable") signature is not a
    per-actor signature — it is the shared store key, which every actor and the
    server hold.
    """
    events = int(payload.get("event_count") or 0)
    verified = int(payload.get("signatures_verified") or 0)
    raw_unverifiable = payload.get("signatures_unverifiable")
    unverifiable = None if raw_unverifiable is None else int(raw_unverifiable)
    check = str(payload.get("signature_check") or "unknown")

    if payload.get("verified") is not True:
        errors = payload.get("errors")
        reason = "; ".join(str(e) for e in errors) if isinstance(errors, list) else ""
        return BundleVerdict(
            False, events, verified, unverifiable,
            f"bundle verification failed: {reason or 'no reason reported'}",
        )
    if check != "enforced":
        return BundleVerdict(
            False, events, verified, unverifiable,
            f"signature_check={check!r}: the bundle verified without enforcing "
            f"signature checking, so it says nothing about who signed what",
        )
    if unverifiable is None:
        return BundleVerdict(
            False, events, verified, None,
            "bundle payload carries no signatures_unverifiable count; a missing "
            "count is not zero",
        )
    if unverifiable > 0:
        return BundleVerdict(
            False, events, verified, unverifiable,
            f"{unverifiable} of {events} signature(s) are unverifiable "
            f"(symmetric scheme) — those events are signed with the shared "
            f"store key, which anyone holding it could forge, so they are not "
            f"per-actor signatures",
        )
    if verified != events:
        return BundleVerdict(
            False, events, verified, unverifiable,
            f"only {verified} of {events} event(s) carry a verified signature",
        )
    return BundleVerdict(
        True, events, verified, unverifiable,
        f"{events} event(s), all per-actor: {verified} verified, 0 unverifiable",
    )
