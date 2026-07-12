from __future__ import annotations

from agent_suite.windows_setup import (
    HostObservation,
    ProbeState,
    SetupOperation,
    SetupReceipt,
    ReceiptState,
    SigningKeyRef,
    SignedReceipt,
    sign_receipt,
    verify_signed_receipt,
    dry_run,
    build_plan,
    SetupRequest,
)
from agent_suite.profiles import Profile


def _make_receipt() -> SetupReceipt:
    observation = HostObservation(
        os_name="Windows",
        python_version="3.12.4",
        powershell=ProbeState.AVAILABLE,
        elevation=ProbeState.AVAILABLE,
        service_account=ProbeState.AVAILABLE,
        postgres=ProbeState.AVAILABLE,
        dns=ProbeState.AVAILABLE,
        tls=ProbeState.AVAILABLE,
        secret_provider=ProbeState.AVAILABLE,
        artifact_release_identity="release:test",
        artifact_lock_identity="sha256:" + "a" * 64,
        ownership_conflict=False,
    )
    request = SetupRequest(
        profile=Profile.B,
        target_release_identity="release:test",
        target_lock_identity="sha256:" + "a" * 64,
        operations=frozenset({SetupOperation.WIRE_HARNESSES}),
    )
    plan = build_plan(request, observation)
    return dry_run(plan)


def test_sign_and_verify_round_trip() -> None:
    receipt = _make_receipt()
    key = b"test-secret-key"
    signed = sign_receipt(receipt, key, "key-001")
    assert signed.key_ref.key_id == "key-001"
    assert signed.key_ref.algorithm == "hmac-sha256"
    assert len(signed.signature) == 64
    assert verify_signed_receipt(signed, key) is True


def test_verify_fails_with_wrong_key() -> None:
    receipt = _make_receipt()
    signed = sign_receipt(receipt, b"correct-key", "key-001")
    assert verify_signed_receipt(signed, b"wrong-key") is False


def test_verify_fails_on_tampered_receipt() -> None:
    receipt = _make_receipt()
    key = b"test-secret-key"
    signed = sign_receipt(receipt, key, "key-001")
    tampered_receipt = SetupReceipt(
        protocol_version=receipt.protocol_version,
        plan_id=receipt.plan_id,
        state=ReceiptState.APPLIED,
        actions=receipt.actions,
        detail="tampered detail",
    )
    tampered = SignedReceipt(
        receipt=tampered_receipt,
        key_ref=signed.key_ref,
        signature=signed.signature,
    )
    assert verify_signed_receipt(tampered, key) is False


def test_verify_fails_on_tampered_signature() -> None:
    receipt = _make_receipt()
    key = b"test-secret-key"
    signed = sign_receipt(receipt, key, "key-001")
    tampered = SignedReceipt(
        receipt=receipt,
        key_ref=signed.key_ref,
        signature="0" * 64,
    )
    assert verify_signed_receipt(tampered, key) is False


def test_canonical_receipt_is_deterministic() -> None:
    receipt = _make_receipt()
    key_ref = SigningKeyRef(key_id="key-001", algorithm="hmac-sha256")
    from agent_suite.windows_setup import _canonical_receipt

    first = _canonical_receipt(receipt, key_ref)
    second = _canonical_receipt(receipt, key_ref)
    assert first == second


def test_canonical_receipt_changes_on_detail_change() -> None:
    receipt = _make_receipt()
    key_ref = SigningKeyRef(key_id="key-001", algorithm="hmac-sha256")
    from agent_suite.windows_setup import _canonical_receipt

    original = _canonical_receipt(receipt, key_ref)
    modified_receipt = SetupReceipt(
        protocol_version=receipt.protocol_version,
        plan_id=receipt.plan_id,
        state=receipt.state,
        actions=receipt.actions,
        detail="different detail",
    )
    modified = _canonical_receipt(modified_receipt, key_ref)
    assert original != modified


def test_verify_returns_false_on_exception() -> None:
    bad_signed = SignedReceipt(
        receipt=_make_receipt(),
        key_ref=SigningKeyRef(key_id="key-001", algorithm="hmac-sha256"),
        signature="not-a-hex-string",
    )
    assert verify_signed_receipt(bad_signed, b"any-key") is False


def test_signed_receipt_to_dict_contains_all_fields() -> None:
    receipt = _make_receipt()
    signed = sign_receipt(receipt, b"key", "key-001")
    d = signed.to_dict()
    assert "receipt" in d
    assert "key_ref" in d
    assert "signature" in d
    assert d["key_ref"]["key_id"] == "key-001"
    assert d["key_ref"]["algorithm"] == "hmac-sha256"


def test_verify_fails_on_key_ref_tampering() -> None:
    receipt = _make_receipt()
    key = b"test-secret-key"
    signed = sign_receipt(receipt, key, "key-001")
    tampered = SignedReceipt(
        receipt=receipt,
        key_ref=SigningKeyRef(key_id="different-key", algorithm="hmac-sha256"),
        signature=signed.signature,
    )
    assert verify_signed_receipt(tampered, key) is False


def test_verify_fails_on_wrong_algorithm() -> None:
    receipt = _make_receipt()
    key = b"test-secret-key"
    signed = sign_receipt(receipt, key, "key-001")
    tampered = SignedReceipt(
        receipt=receipt,
        key_ref=SigningKeyRef(key_id="key-001", algorithm="hmac-sha512"),
        signature=signed.signature,
    )
    assert verify_signed_receipt(tampered, key) is False
