"""File-based state store for dual control requests.

Tracks PENDING → APPROVED → EXECUTED transitions and prevents replay.
Uses a JSON file with fcntl (Linux) or msvcrt (Windows) locking for
concurrent access safety. stdlib-only.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_suite.dual_control import (
    DualControlApproval,
    DualControlRequest,
    DualControlState,
    ProtectedOperation,
    StepUpLevel,
)


@dataclass(frozen=True)
class DualControlRecord:
    request: DualControlRequest
    approval: DualControlApproval | None
    state: DualControlState
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "request": {
                "request_id": self.request.request_id,
                "operation": self.request.operation.value,
                "requester_principal": self.request.requester_principal,
                "operation_digest": self.request.operation_digest,
                "step_up_required": self.request.step_up_required.value,
                "created_at": self.request.created_at,
                "expires_at": self.request.expires_at,
                "requester_token_hash": self.request.requester_token_hash,
            },
            "approval": None,
            "state": self.state.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.approval is not None:
            result["approval"] = {
                "request_id": self.approval.request_id,
                "approver_principal": self.approval.approver_principal,
                "approved_at": self.approval.approved_at,
                "approver_token_hash": self.approval.approver_token_hash,
                "operation_digest": self.approval.operation_digest,
            }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DualControlRecord:
        req = data["request"]
        request = DualControlRequest(
            request_id=req["request_id"],
            operation=ProtectedOperation(req["operation"]),
            requester_principal=req["requester_principal"],
            operation_digest=req["operation_digest"],
            step_up_required=StepUpLevel(req["step_up_required"]),
            created_at=req["created_at"],
            expires_at=req["expires_at"],
            requester_token_hash=req["requester_token_hash"],
        )
        approval: DualControlApproval | None = None
        ap = data.get("approval")
        if ap is not None:
            approval = DualControlApproval(
                request_id=ap["request_id"],
                approver_principal=ap["approver_principal"],
                approved_at=ap["approved_at"],
                approver_token_hash=ap["approver_token_hash"],
                operation_digest=ap["operation_digest"],
            )
        return cls(
            request=request,
            approval=approval,
            state=DualControlState(data["state"]),
            created_at=data["created_at"],
            updated_at=data["updated_at"],
        )


class DualControlStoreError(Exception):
    """Raised when store operations fail."""


class DualControlStore:
    """File-based dual control state store with locking."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._ensure_dir()

    def create(self, request: DualControlRequest) -> None:
        """Store a pending request. Raises if request_id already exists."""
        with self._lock():
            records = self._read_all()
            if request.request_id in records:
                raise DualControlStoreError(
                    f"request {request.request_id} already exists"
                )
            now = time.time()
            records[request.request_id] = DualControlRecord(
                request=request,
                approval=None,
                state=DualControlState.PENDING,
                created_at=now,
                updated_at=now,
            )
            self._write_all(records)

    def approve(self, request_id: str, approval: DualControlApproval) -> None:
        """Record approval for a pending request.

        Raises if not found, not PENDING, or already approved.
        """
        with self._lock():
            records = self._read_all()
            if request_id not in records:
                raise DualControlStoreError(f"request {request_id} not found")
            record = records[request_id]
            if record.state is not DualControlState.PENDING:
                raise DualControlStoreError(
                    f"request {request_id} is not PENDING "
                    f"(state={record.state.value})"
                )
            now = time.time()
            records[request_id] = DualControlRecord(
                request=record.request,
                approval=approval,
                state=DualControlState.APPROVED,
                created_at=record.created_at,
                updated_at=now,
            )
            self._write_all(records)

    def get(self, request_id: str) -> DualControlRecord | None:
        """Retrieve state for a request. None if not found."""
        with self._lock():
            records = self._read_all()
            return records.get(request_id)

    def mark_executed(self, request_id: str) -> None:
        """Transition APPROVED → EXECUTED.

        Raises if not found or not APPROVED.
        """
        with self._lock():
            records = self._read_all()
            if request_id not in records:
                raise DualControlStoreError(f"request {request_id} not found")
            record = records[request_id]
            if record.state is not DualControlState.APPROVED:
                raise DualControlStoreError(
                    f"request {request_id} is not APPROVED "
                    f"(state={record.state.value})"
                )
            if record.request.is_expired():
                raise DualControlStoreError(f"request {request_id} has expired")
            now = time.time()
            records[request_id] = DualControlRecord(
                request=record.request,
                approval=record.approval,
                state=DualControlState.EXECUTED,
                created_at=record.created_at,
                updated_at=now,
            )
            self._write_all(records)

    def list_pending(self) -> list[DualControlRecord]:
        """List all PENDING requests."""
        with self._lock():
            records = self._read_all()
            return [
                rec
                for rec in records.values()
                if rec.state is DualControlState.PENDING
            ]

    def cleanup_expired(self) -> int:
        """Remove EXPIRED records. Returns count removed."""
        with self._lock():
            records = self._read_all()
            expired_ids = [
                rid
                for rid, rec in records.items()
                if rec.state is DualControlState.PENDING
                and rec.request.is_expired()
            ]
            for rid in expired_ids:
                del records[rid]
            if expired_ids:
                self._write_all(records)
            return len(expired_ids)

    def _ensure_dir(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict[str, DualControlRecord]:
        """Read all records from the JSON file. Empty dict if file missing."""
        if not self._path.exists():
            return {}
        try:
            with open(self._path, encoding="utf-8") as f:
                raw: dict[str, Any] = json.load(f)
        except json.JSONDecodeError as exc:
            raise DualControlStoreError(f"corrupted store file: {exc}") from exc
        return {
            rid: DualControlRecord.from_dict(record)
            for rid, record in raw.items()
        }

    def _write_all(self, records: dict[str, DualControlRecord]) -> None:
        """Write all records atomically (write to temp, rename)."""
        data = {rid: rec.to_dict() for rid, rec in records.items()}
        tmp_path = self._path.parent / (self._path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(str(tmp_path), str(self._path))

    @contextmanager
    def _lock(self) -> Iterator[None]:
        """File lock for concurrent access.

        Use fcntl on Linux, msvcrt on Windows.
        """
        lock_path = self._path.parent / (self._path.name + ".lock")
        fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_UN)
            except OSError:
                pass
            os.close(fd)
