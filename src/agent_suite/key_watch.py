"""Key-rotation and store-growth watch checks for the doctor umbrella.

Implements Plan 005 WI-2.2. The doctor gains two suite-level checks:

1. **Key rotation age** — shells ``regista principal list --json`` and checks
   each key's ``valid_from`` against the rotation-cadence policy (default 90
   days, from ``docs/key-operations.md`` §2). A key approaching the cadence
   warns; a key past the cadence fails (with the runbook reference).

2. **Store growth telemetry** — shells ``regista stats --json`` and surfaces
   per-project event counts and byte sizes so the regista Plan 028 archival
   decision is made from data, not guesswork.

Design (AGENTS.md): thin orchestration — these checks shell regista's own CLI
and apply the suite's *policy* (rotation cadence from the operator docs). The
mechanics (key registry, replay) are regista's. If regista doesn't expose the
command, the check reports ``UNSUPPORTED`` — a named state, not a crash, and
not smoothed into "ok." ``assert_never`` over every closed-set enum.
stdlib-only core.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol


# ---------------------------------------------------------------------------
# Injectable interfaces
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
# Closed-set enums
# ---------------------------------------------------------------------------


class KeyAgeStatus(Enum):
    """The closed set of key-rotation-age check outcomes.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    OK = "ok"  # all keys within rotation cadence
    APPROACHING = "approaching"  # key age within 80-100% of cadence — warn
    EXPIRED = "expired"  # key age past cadence — fail
    UNSUPPORTED = "unsupported"  # regista doesn't expose principal list
    UNREACHABLE = "unreachable"  # regista CLI missing or command failed
    ERROR = "error"  # unexpected error / bad JSON


class StoreGrowthStatus(Enum):
    """The closed set of store-growth check outcomes."""

    OK = "ok"
    UNSUPPORTED = "unsupported"  # regista doesn't expose stats
    UNREACHABLE = "unreachable"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


DEFAULT_ROTATION_CADENCE_DAYS = 90
DEFAULT_WARN_THRESHOLD_PCT = 80  # warn at 80% of cadence


@dataclass
class KeyInfo:
    """One signing key's rotation-relevant info."""

    principal_id: str
    key_id: str
    valid_from: str  # ISO 8601 timestamp from regista
    age_days: float
    status: KeyAgeStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "principal_id": self.principal_id,
            "key_id": self.key_id,
            "valid_from": self.valid_from,
            "age_days": round(self.age_days, 1),
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class KeyRotationResult:
    """The outcome of the key-rotation-age check."""

    ok: bool
    status: KeyAgeStatus
    keys: list[KeyInfo] = field(default_factory=list)
    cadence_days: int = DEFAULT_ROTATION_CADENCE_DAYS
    detail: str = ""
    runbook_ref: str = "docs/key-operations.md §2"

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "keys": [k.to_dict() for k in self.keys],
            "cadence_days": self.cadence_days,
            "detail": self.detail,
            "runbook_ref": self.runbook_ref,
        }


@dataclass
class ProjectGrowth:
    """One project's store-growth telemetry."""

    project: str
    event_count: int = 0
    store_bytes: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "event_count": self.event_count,
            "store_bytes": self.store_bytes,
            "detail": self.detail,
        }


@dataclass
class StoreGrowthResult:
    """The outcome of the store-growth check."""

    ok: bool
    status: StoreGrowthStatus
    projects: list[ProjectGrowth] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "projects": [p.to_dict() for p in self.projects],
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Key rotation age check
# ---------------------------------------------------------------------------

_REGISTA_PRINCIPAL_CMD: tuple[str, ...] = ("regista", "principal", "list", "--json")


def _parse_iso_timestamp(ts: str) -> float | None:
    """Parse an ISO 8601 timestamp to epoch seconds. Returns None on failure."""
    try:
        clean = ts.replace("Z", "+00:00")
        from datetime import datetime

        dt = datetime.fromisoformat(clean)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def check_key_rotation(
    *,
    cadence_days: int = DEFAULT_ROTATION_CADENCE_DAYS,
    warn_threshold_pct: int = DEFAULT_WARN_THRESHOLD_PCT,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> KeyRotationResult:
    """Check signing-key ages against the rotation-cadence policy.

    Shells ``regista principal list --json`` and evaluates each active key's
    age against ``cadence_days`` (default 90, per ``docs/key-operations.md``).
    A key at 80-100% of cadence warns; past cadence fails.

    If regista is not installed or doesn't support ``principal list``, returns
    ``UNSUPPORTED`` — a named state, not "ok." Never raises.
    """
    if not installed("regista"):
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.UNREACHABLE,
            detail="regista not installed — cannot check key rotation age",
        )

    try:
        result = runner(_REGISTA_PRINCIPAL_CMD)
    except FileNotFoundError:
        return KeyRotationResult(
            ok=True, status=KeyAgeStatus.UNREACHABLE, detail="regista not found at run time"
        )
    except subprocess.TimeoutExpired:
        return KeyRotationResult(
            ok=True, status=KeyAgeStatus.UNREACHABLE, detail="regista principal list timed out"
        )
    except OSError as exc:
        return KeyRotationResult(
            ok=True, status=KeyAgeStatus.UNREACHABLE, detail=f"regista principal list failed: {exc}"
        )

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        if "unknown" in stderr or "not found" in stderr or "no such" in stderr or "invalid choice" in stderr or "unrecognized" in stderr:
            return KeyRotationResult(
                ok=True,
                status=KeyAgeStatus.UNSUPPORTED,
                detail="regista does not support 'principal list' — key-age check requires regista Plan 026 WI-3.1",
            )
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.UNREACHABLE,
            detail=f"regista principal list exit {result.returncode}: {result.stderr.strip()[:200]}",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return KeyRotationResult(
            ok=True, status=KeyAgeStatus.ERROR, detail="regista principal list emitted non-JSON"
        )

    principals: list[dict[str, object]] = []
    if isinstance(data, list):
        principals = [p for p in data if isinstance(p, dict)]
    elif isinstance(data, dict):
        raw_principals = data.get("principals")
        if isinstance(raw_principals, list):
            principals = [p for p in raw_principals if isinstance(p, dict)]
    else:
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.ERROR,
            detail="regista principal list emitted unexpected JSON shape",
        )

    now = time.time()
    warn_age = cadence_days * warn_threshold_pct / 100
    keys: list[KeyInfo] = []
    overall_ok = True
    overall_status = KeyAgeStatus.OK

    for p in principals:
        principal_id = str(p.get("principal_id", p.get("id", "unknown")))
        keys_list = p.get("keys")
        if not isinstance(keys_list, list):
            continue
        for k in keys_list:
            if not isinstance(k, dict):
                continue
            valid_from = str(k.get("valid_from", k.get("created_at", "")))
            key_id = str(k.get("key_id", k.get("id", "unknown")))
            valid_to = k.get("valid_to")

            if valid_to is not None and str(valid_to):
                continue  # key is windowed out — skip

            ts = _parse_iso_timestamp(valid_from) if valid_from else None
            if ts is None:
                keys.append(
                    KeyInfo(
                        principal_id=principal_id,
                        key_id=key_id,
                        valid_from=valid_from,
                        age_days=0,
                        status=KeyAgeStatus.ERROR,
                        detail="could not parse valid_from timestamp",
                    )
                )
                overall_ok = False
                if overall_status is KeyAgeStatus.OK:
                    overall_status = KeyAgeStatus.ERROR
                continue

            age_days = (now - ts) / 86400.0

            if age_days >= cadence_days:
                status = KeyAgeStatus.EXPIRED
                detail = (
                    f"key age {age_days:.0f}d exceeds {cadence_days}d cadence — "
                    f"rotate per {os.path.basename('docs/key-operations.md')} §2"
                )
                overall_ok = False
                overall_status = KeyAgeStatus.EXPIRED
            elif age_days >= warn_age:
                status = KeyAgeStatus.APPROACHING
                detail = (
                    f"key age {age_days:.0f}d approaching {cadence_days}d cadence "
                    f"({age_days/cadence_days*100:.0f}%)"
                )
                if overall_status is KeyAgeStatus.OK:
                    overall_status = KeyAgeStatus.APPROACHING
            else:
                status = KeyAgeStatus.OK
                detail = f"key age {age_days:.0f}d (cadence: {cadence_days}d)"

            keys.append(
                KeyInfo(
                    principal_id=principal_id,
                    key_id=key_id,
                    valid_from=valid_from,
                    age_days=age_days,
                    status=status,
                    detail=detail,
                )
            )

    if not principals:
        detail = "no principals registered"
    elif not keys:
        detail = "no active keys found (all windowed out or no keys registered)"
    else:
        detail = f"{len(keys)} key(s) checked"

    return KeyRotationResult(
        ok=overall_ok and overall_status not in (KeyAgeStatus.EXPIRED,),
        status=overall_status,
        keys=keys,
        cadence_days=cadence_days,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# Store growth check
# ---------------------------------------------------------------------------

_REGISTA_STATS_CMD: tuple[str, ...] = ("regista", "stats", "--json")


def _safe_int(val: object) -> int:
    """Coerce a value to int, returning 0 on failure."""
    if isinstance(val, (int, float)):
        return int(val)
    if isinstance(val, str):
        try:
            return int(val)
        except ValueError:
            return 0
    return 0


def check_store_growth(
    *,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> StoreGrowthResult:
    """Check per-project store growth (events/bytes) for archival decisions.

    Shells ``regista stats --json`` and surfaces per-project event counts and
    byte sizes. If regista doesn't support ``stats``, returns ``UNSUPPORTED``.
    Never raises.
    """
    if not installed("regista"):
        return StoreGrowthResult(
            ok=True, status=StoreGrowthStatus.UNREACHABLE, detail="regista not installed"
        )

    try:
        result = runner(_REGISTA_STATS_CMD)
    except FileNotFoundError:
        return StoreGrowthResult(
            ok=True, status=StoreGrowthStatus.UNREACHABLE, detail="regista not found at run time"
        )
    except subprocess.TimeoutExpired:
        return StoreGrowthResult(
            ok=True, status=StoreGrowthStatus.UNREACHABLE, detail="regista stats timed out"
        )
    except OSError as exc:
        return StoreGrowthResult(
            ok=True, status=StoreGrowthStatus.UNREACHABLE, detail=f"regista stats failed: {exc}"
        )

    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        if "unknown" in stderr or "not found" in stderr or "no such" in stderr or "invalid choice" in stderr or "unrecognized" in stderr:
            return StoreGrowthResult(
                ok=True,
                status=StoreGrowthStatus.UNSUPPORTED,
                detail="regista does not support 'stats' — store-growth check requires a regista feature",
            )
        return StoreGrowthResult(
            ok=True,
            status=StoreGrowthStatus.UNREACHABLE,
            detail=f"regista stats exit {result.returncode}: {result.stderr.strip()[:200]}",
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return StoreGrowthResult(
            ok=True, status=StoreGrowthStatus.ERROR, detail="regista stats emitted non-JSON"
        )

    projects: list[ProjectGrowth] = []
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                projects.append(
                    ProjectGrowth(
                        project=str(item.get("project", item.get("schema", "unknown"))),
                        event_count=_safe_int(item.get("event_count", item.get("events", 0))),
                        store_bytes=_safe_int(item.get("store_bytes", item.get("bytes", 0))),
                    )
                )
    elif isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                projects.append(
                    ProjectGrowth(
                        project=str(key),
                        event_count=_safe_int(val.get("event_count", val.get("events", 0))),
                        store_bytes=_safe_int(val.get("store_bytes", val.get("bytes", 0))),
                    )
                )

    return StoreGrowthResult(
        ok=True,
        status=StoreGrowthStatus.OK,
        projects=projects,
        detail=f"{len(projects)} project(s) with growth telemetry",
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_key_rotation_text(result: KeyRotationResult) -> str:
    """Human-readable summary for the key-rotation check."""
    lines: list[str] = ["key rotation watch:"]
    if not result.keys:
        lines.append(f"  {result.status.value}: {result.detail}")
        return "\n".join(lines)
    for k in result.keys:
        lines.append(
            f"  {k.principal_id}/{k.key_id:<8} {k.status.value:<12} "
            f"{k.age_days:.0f}d  {k.detail}"
        )
    lines.append(f"  cadence: {result.cadence_days}d  ({result.runbook_ref})")
    return "\n".join(lines)


def format_store_growth_text(result: StoreGrowthResult) -> str:
    """Human-readable summary for the store-growth check."""
    lines: list[str] = ["store growth telemetry:"]
    if not result.projects:
        lines.append(f"  {result.status.value}: {result.detail}")
        return "\n".join(lines)
    for p in result.projects:
        lines.append(f"  {p.project:<24} {p.event_count:>10} events  {p.store_bytes:>12} bytes")
    return "\n".join(lines)
