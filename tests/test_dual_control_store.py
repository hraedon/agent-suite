from __future__ import annotations

import json
import time

import pytest

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
)
from agent_suite.dual_control_store import (
    DualControlRecord,
    DualControlStore,
    DualControlStoreError,
)
from pathlib import Path


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


def test_create_stores_pending_request(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.PENDING
    assert record.request.request_id == request.request_id
    assert record.approval is None
    assert record.created_at > 0
    assert record.updated_at == record.created_at


def test_create_rejects_duplicate(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    with pytest.raises(DualControlStoreError, match="already exists"):
        store.create(request)


def test_approve_transitions_to_approved(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)
    approval = _make_approval(request)

    store.approve(request.request_id, approval)

    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.APPROVED
    assert record.approval is not None
    assert record.approval.request_id == approval.request_id
    assert record.updated_at >= record.created_at


def test_approve_rejects_non_pending(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)
    approval = _make_approval(request)
    store.approve(request.request_id, approval)

    with pytest.raises(DualControlStoreError, match="not PENDING"):
        store.approve(request.request_id, approval)


def test_approve_rejects_unknown_request(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    approval = _make_approval(request)

    with pytest.raises(DualControlStoreError, match="not found"):
        store.approve("nonexistent-id", approval)


def test_mark_executed_transitions_to_executed(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)
    approval = _make_approval(request)
    store.approve(request.request_id, approval)

    store.mark_executed(request.request_id)

    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.EXECUTED


def test_mark_executed_rejects_non_approved(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)

    with pytest.raises(DualControlStoreError, match="not APPROVED"):
        store.mark_executed(request.request_id)


def test_mark_executed_rejects_unknown_request(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    with pytest.raises(DualControlStoreError, match="not found"):
        store.mark_executed("nonexistent-id")


def test_get_returns_none_for_missing(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    assert store.get("nonexistent-id") is None


def test_list_pending_returns_only_pending(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    req1 = _make_request(requester="user-001")
    req2 = _make_request(requester="user-003")
    req3 = _make_request(requester="user-004")
    store.create(req1)
    store.create(req2)
    store.create(req3)

    approval = _make_approval(req2)
    store.approve(req2.request_id, approval)

    pending = store.list_pending()
    assert len(pending) == 2
    pending_ids = {rec.request.request_id for rec in pending}
    assert req1.request_id in pending_ids
    assert req3.request_id in pending_ids
    assert req2.request_id not in pending_ids


def test_cleanup_expired_removes_expired(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    expired_request = DualControlRequest(
        request_id="expired-req",
        operation=ProtectedOperation.KEY_ROTATE,
        requester_principal="user-001",
        operation_digest="sha256:fake",
        step_up_required=StepUpLevel.MULTI_FACTOR,
        created_at=time.time() - 1200,
        expires_at=time.time() - 600,
        requester_token_hash="sha256:fake",
    )
    valid_request = _make_request(requester="user-003")
    store.create(expired_request)
    store.create(valid_request)

    removed = store.cleanup_expired()

    assert removed == 1
    assert store.get("expired-req") is None
    assert store.get(valid_request.request_id) is not None


def test_cleanup_expired_returns_count(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    for i in range(3):
        expired_request = DualControlRequest(
            request_id=f"expired-{i}",
            operation=ProtectedOperation.KEY_ROTATE,
            requester_principal=f"user-{i}",
            operation_digest="sha256:fake",
            step_up_required=StepUpLevel.MULTI_FACTOR,
            created_at=time.time() - 1200,
            expires_at=time.time() - 600,
            requester_token_hash="sha256:fake",
        )
        store.create(expired_request)
    valid_request = _make_request(requester="user-valid")
    store.create(valid_request)

    removed = store.cleanup_expired()

    assert removed == 3


def test_store_survives_restart(tmp_path: Path) -> None:
    store_path = tmp_path / "store.json"
    store1 = DualControlStore(store_path)
    request = _make_request()
    store1.create(request)

    store2 = DualControlStore(store_path)
    record = store2.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.PENDING
    assert record.request.request_id == request.request_id


def test_atomic_write(tmp_path: Path) -> None:
    store_path = tmp_path / "store.json"
    store = DualControlStore(store_path)
    request = _make_request()
    store.create(request)

    assert store_path.exists()
    tmp_path_check = tmp_path / "store.json.tmp"
    assert not tmp_path_check.exists()

    with open(store_path) as f:
        data = json.load(f)
    assert request.request_id in data
    assert data[request.request_id]["state"] == "pending"


def test_record_to_dict_roundtrip(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)
    approval = _make_approval(request)
    store.approve(request.request_id, approval)

    record = store.get(request.request_id)
    assert record is not None
    d = record.to_dict()
    assert d["state"] == "approved"
    assert isinstance(d["request"], dict)
    assert d["request"]["request_id"] == request.request_id
    assert d["approval"] is not None
    assert d["approval"]["request_id"] == approval.request_id

    restored = DualControlRecord.from_dict(d)
    assert restored.state is DualControlState.APPROVED
    assert restored.request.request_id == request.request_id
    assert restored.approval is not None
    assert restored.approval.request_id == approval.request_id


def test_full_lifecycle(tmp_path: Path) -> None:
    store = DualControlStore(tmp_path / "store.json")
    request = _make_request()
    store.create(request)
    assert store.get(request.request_id) is not None
    assert len(store.list_pending()) == 1

    approval = _make_approval(request)
    store.approve(request.request_id, approval)
    assert len(store.list_pending()) == 0

    store.mark_executed(request.request_id)
    record = store.get(request.request_id)
    assert record is not None
    assert record.state is DualControlState.EXECUTED
