"""The suite's own gates must fail on the state the qualification produced.

Two gates went green over the exact defects they exist to catch:

* ``bootstrap-contract.md`` §5 requires the mixed human+agent chain to verify
  "with per-actor signatures". The Lane C lock passed while producing
  ``Bundle verified — 5 event(s), 4 signature(s) verified, 1 unverifiable
  (symmetric scheme)``. The unverifiable one is the human's acceptance, signed
  with the shared store HMAC key that anyone holding it could forge.
* ``regista replay`` reported ``principal_binding_failures=0`` on a chain every
  event of which was signed by a key the project never registered — because the
  check had not run, and a missing count read as a zero one.

The numbers below are the real ones from
``qual-linux-evidence/50-item7-signed-e2e-flow.txt``, so this file is the
regression proof for both.
"""

from __future__ import annotations

import pytest

from agent_suite.signature_assurance import (
    BindingStatus,
    bundle_verdict,
    principal_binding,
)

# ---------------------------------------------------------------------------
# §5 — "the bundle verified" is not "per-actor signatures"
# ---------------------------------------------------------------------------

#: What the qualification run actually produced, verbatim in shape.
_QUAL_BUNDLE = {
    "verified": True,
    "event_count": 5,
    "anchor_receipt_count": 0,
    "segment_count": 0,
    "signatures_verified": 4,
    "signatures_unverifiable": 1,
    "signature_check": "enforced",
    "bundle_hash_ok": True,
    "global_chain_ok": True,
    "work_item_chain_ok": True,
    "segment_chain_ok": True,
    "errors": [],
}


def test_the_lane_c_lock_state_fails_the_gate() -> None:
    """4 verified / 1 unverifiable must not pass a per-actor-signature gate."""
    verdict = bundle_verdict(_QUAL_BUNDLE)
    assert verdict.ok is False
    assert verdict.unverifiable == 1
    assert "symmetric" in verdict.detail
    assert "forge" in verdict.detail


def test_a_fully_per_actor_chain_passes() -> None:
    verdict = bundle_verdict(
        {**_QUAL_BUNDLE, "signatures_verified": 5, "signatures_unverifiable": 0}
    )
    assert verdict.ok is True
    assert verdict.events == 5
    assert verdict.unverifiable == 0


def test_v6_external_bootstrap_is_not_mislabeled_as_symmetric() -> None:
    verdict = bundle_verdict(
        {
            **_QUAL_BUNDLE,
            "signatures_unverifiable": 1,
            "unverifiable_details": [
                "envelope=v6; reasons=key_binding_unresolved; "
                "unbound=bootstrap_external_authority"
            ],
        }
    )

    assert verdict.ok is False
    assert "bootstrap_external_authority" in verdict.detail
    assert "symmetric" not in verdict.detail


def test_a_missing_unverifiable_count_is_not_zero() -> None:
    payload = {k: v for k, v in _QUAL_BUNDLE.items() if k != "signatures_unverifiable"}
    payload["signatures_verified"] = 5
    verdict = bundle_verdict(payload)
    assert verdict.ok is False
    assert "not zero" in verdict.detail


def test_a_bundle_that_skipped_signature_checking_does_not_pass() -> None:
    """A v1 bundle verifies its hashes and checks no signatures at all."""
    verdict = bundle_verdict(
        {
            **_QUAL_BUNDLE,
            "signatures_verified": 0,
            "signatures_unverifiable": 0,
            "signature_check": "skipped_v1_bundle",
        }
    )
    assert verdict.ok is False
    assert "without enforcing" in verdict.detail


def test_an_unverified_bundle_reports_its_reason() -> None:
    verdict = bundle_verdict(
        {
            **_QUAL_BUNDLE,
            "verified": False,
            "errors": [
                "No public key for key_id 'pk_e6c7e5800b4642c4' in bundle registry"
            ],
        }
    )
    assert verdict.ok is False
    assert "pk_e6c7e5800b4642c4" in verdict.detail


def test_fewer_verified_than_events_does_not_pass() -> None:
    verdict = bundle_verdict(
        {**_QUAL_BUNDLE, "signatures_verified": 3, "signatures_unverifiable": 0}
    )
    assert verdict.ok is False
    assert "only 3 of 5" in verdict.detail


# ---------------------------------------------------------------------------
# WI-051 — attributability, and never reading absence as zero
# ---------------------------------------------------------------------------


def test_binding_verified_with_zero_failures_is_a_pass() -> None:
    binding = principal_binding(
        {"principal_binding_verified": True, "principal_binding_failures": 0}
    )
    assert binding.status is BindingStatus.VERIFIED
    assert binding.ok is True


def test_binding_failures_are_named_as_unattributable_not_tampering() -> None:
    binding = principal_binding(
        {"principal_binding_verified": True, "principal_binding_failures": 4}
    )
    assert binding.status is BindingStatus.FAILED
    assert "not attributable" in binding.detail
    assert "tampering" not in binding.detail


@pytest.mark.parametrize(
    "payload",
    [
        # The check did not run: regista omits the count entirely.
        {"principal_binding_verified": False},
        # An older regista emits neither field.
        {},
        # A count of zero without the flag — the shape that would silently
        # green the run again.
        {"principal_binding_failures": 0},
        # `--no-verify-principal-binding` labels rather than counts.
        {"principal_binding_verified": False, "principal_binding": "not-verified"},
    ],
)
def test_absence_of_the_check_is_never_a_pass(payload: dict[str, object]) -> None:
    binding = principal_binding(payload)
    assert binding.status is BindingStatus.NOT_VERIFIED
    assert binding.ok is False


def test_a_non_numeric_count_is_treated_as_unverified() -> None:
    binding = principal_binding(
        {"principal_binding_verified": True, "principal_binding_failures": "many"}
    )
    assert binding.status is BindingStatus.NOT_VERIFIED
