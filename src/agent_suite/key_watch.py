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

WI-049 — three defects the Linux qualification exposed, all in this module
-------------------------------------------------------------------------

Every doctor run on the qualification host printed ``key rotation watch:
unsupported: regista does not support 'principal list'`` while
``regista principal list`` worked from the same shell. Three separate bugs, any
one of which alone hides the check:

1. **The argv was invalid.** regista declares ``--json``, ``--project`` and
   ``--hmac-key-path`` on its **top-level** parser, so they must precede the
   subcommand. ``regista principal list --json`` is an argparse *usage* error
   (``unrecognized arguments: --json``); and the probe passed neither the
   project nor the key path, so on a host carrying them only in ``suite.env``
   the command could not have run either way. See :func:`principal_list_argv`.

2. **Capability detection scanned prose.** ``"unknown" in stderr`` matched
   regista's ``[UNKNOWN_KEY_ID] hmac_key_path is required``, and
   ``"unrecognized" in stderr`` matched argparse's complaint about ``--json``.
   Both are commands that *exist and failed*, reported as a component
   limitation. Detection now keys on the only thing that means "this verb does
   not exist" — the parser naming the subcommand itself as an invalid choice
   (:func:`subcommand_absent`).

3. **The parser expected a shape regista never emits.** ``principal list``
   emits a **flat** list of key entries (``principal_id``, ``key_id``,
   ``valid_from``, ``status``, …), not principals each carrying a ``keys``
   list. Even a successful probe therefore found zero keys and said "no
   principals registered".

The result now also carries :attr:`KeyRotationResult.checked`. "No key is past
cadence" and "nothing was looked at" are different facts, and a report that
cannot tell them apart is the same defect as regista's
``principal_binding_failures=0`` over a chain nobody verified.
"""

from __future__ import annotations

import json
import os
import re
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
    return subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=False)


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
    UNSUPPORTED = "unsupported"  # regista's parser has no such subcommand
    UNREACHABLE = "unreachable"  # regista CLI missing, or the command failed
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

#: How the remedy for a *failed* (as opposed to absent) probe is stated. Kept as
#: one string so the detail and the tests cannot drift.
KEY_WATCH_REMEDY = (
    "set REGISTA_PROJECT and REGISTA_KEY_PATH in suite.env (regista resolves "
    "neither from a project-less invocation) — the key-age check was NOT run"
)


# ---------------------------------------------------------------------------
# Probing regista: argv shape and capability detection
# ---------------------------------------------------------------------------


def principal_list_argv(
    *, project: str | None = None, key_path: str | None = None
) -> tuple[str, ...]:
    """Build ``regista principal list`` with its global options in front.

    ``--json``, ``--project`` and ``--hmac-key-path`` are declared on regista's
    **top-level** parser, so argparse only accepts them *before* the subcommand.
    ``regista principal list --json`` exits 2 with ``unrecognized arguments:
    --json`` — which the old prose scan read as "regista has no ``principal
    list``" (WI-049).

    ``project`` and ``key_path`` are passed when known because
    ``cmd_principal_list`` requires a project and opens the key file: a probe
    that omits them fails with ``[UNKNOWN_KEY_ID] hmac_key_path is required`` on
    every host that keeps them in ``suite.env`` rather than the ambient
    environment (qualification finding QL-F23 / regista WI-225).
    """
    argv: list[str] = ["regista", "--json"]
    if project:
        argv += ["--project", project]
    if key_path:
        argv += ["--hmac-key-path", key_path]
    argv += ["principal", "list"]
    return tuple(argv)


#: argparse's wording for a subcommand its parser does not define. This is the
#: only signal that means "the component does not have this verb"; every other
#: non-zero exit is a verb that exists and failed.
_INVALID_CHOICE_RE = re.compile(r"invalid choice:\s*'(?P<name>[^']+)'")


def subcommand_absent(stderr: str, *, path: tuple[str, ...]) -> bool:
    """Whether the child's parser rejected one of ``path`` as an unknown verb.

    ``UNSUPPORTED`` is a claim about the *component*, so it needs evidence about
    the component — not a substring that happens to appear in an error message.
    argparse says ``invalid choice: 'stats'`` for a verb it does not define, and
    names the offending token; nothing else does. A usage error about an
    *option* (``unrecognized arguments: --json``), a missing DSN, an
    unresolvable key ref or a database outage are all commands that exist and
    failed, and reporting them as a component limitation tells the operator
    there is nothing to fix (WI-049).
    """
    for match in _INVALID_CHOICE_RE.finditer(stderr):
        if match.group("name") in path:
            return True
    return False


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
    """The outcome of the key-rotation-age check.

    ``checked`` is the WI-049 honesty field: True only when the registry was
    actually read. Without it ``ok=True`` with an empty ``keys`` list reads
    identically whether every key is inside cadence or whether the probe never
    ran, and a consumer cannot tell "verified" from "not looked at".
    """

    ok: bool
    status: KeyAgeStatus
    keys: list[KeyInfo] = field(default_factory=list)
    cadence_days: int = DEFAULT_ROTATION_CADENCE_DAYS
    detail: str = ""
    runbook_ref: str = "docs/key-operations.md §2"
    checked: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "checked": self.checked,
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
    checked: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "status": self.status.value,
            "checked": self.checked,
            "projects": [p.to_dict() for p in self.projects],
            "detail": self.detail,
        }


# ---------------------------------------------------------------------------
# Key rotation age check
# ---------------------------------------------------------------------------

#: The subcommand path whose absence would genuinely mean regista cannot do this.
_PRINCIPAL_LIST_PATH: tuple[str, ...] = ("principal", "list")


def _parse_iso_timestamp(ts: str) -> float | None:
    """Parse an ISO 8601 timestamp to epoch seconds. Returns None on failure."""
    try:
        clean = ts.replace("Z", "+00:00")
        from datetime import datetime

        dt = datetime.fromisoformat(clean)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None


def _key_entries(
    data: object,
) -> tuple[tuple[tuple[str, dict[str, object]], ...], str | None]:
    """Normalise ``principal list --json`` output to ``(principal_id, key)`` pairs.

    regista emits a **flat** list of ``PrincipalKeyEntry.to_dict()`` — one object
    per *key*, each carrying its own ``principal_id`` — not one object per
    principal with a nested ``keys`` list. This module read the nested shape, so
    a successful probe against the real CLI produced zero keys and reported "no
    principals registered": a check that ran, found nothing, and said so as if
    the registry were empty (WI-049).

    Both shapes are accepted, because the nested one is the shape the suite
    documented and a regista that grew it should not silently stop being read.
    """
    if isinstance(data, dict):
        nested = data.get("principals")
        if not isinstance(nested, list):
            return (), "a JSON object with no 'principals' list"
        records = [item for item in nested if isinstance(item, dict)]
    elif isinstance(data, list):
        records = [item for item in data if isinstance(item, dict)]
    else:
        return (), f"unexpected JSON shape ({type(data).__name__})"

    pairs: list[tuple[str, dict[str, object]]] = []
    for record in records:
        principal_id = str(record.get("principal_id", record.get("id", "unknown")))
        nested_keys = record.get("keys")
        if isinstance(nested_keys, list):
            pairs.extend(
                (principal_id, key) for key in nested_keys if isinstance(key, dict)
            )
        elif "key_id" in record or "valid_from" in record:
            # The flat shape: the record *is* the key.
            pairs.append((principal_id, record))
    return tuple(pairs), None


def check_key_rotation(
    *,
    cadence_days: int = DEFAULT_ROTATION_CADENCE_DAYS,
    warn_threshold_pct: int = DEFAULT_WARN_THRESHOLD_PCT,
    project: str | None = None,
    key_path: str | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> KeyRotationResult:
    """Check signing-key ages against the rotation-cadence policy.

    Shells ``regista --json [--project …] [--hmac-key-path …] principal list``
    and evaluates each active key's age against ``cadence_days`` (default 90,
    per ``docs/key-operations.md``). A key at 80-100% of cadence warns; past
    cadence fails.

    ``UNSUPPORTED`` is reserved for a regista whose parser has no ``principal
    list``. Anything else that goes wrong is ``UNREACHABLE`` with the child's
    real diagnostic and the remedy — a command that failed is not a component
    limitation (WI-049). In every non-``OK`` case ``checked`` stays False, so no
    consumer can read a skipped check as a clean one.
    """
    if not installed("regista"):
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.UNREACHABLE,
            detail="regista not installed — key-age check was NOT run",
        )

    argv = principal_list_argv(project=project, key_path=key_path)
    try:
        result = runner(argv)
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
        diagnostic = result.stderr.strip()
        if subcommand_absent(diagnostic, path=_PRINCIPAL_LIST_PATH):
            return KeyRotationResult(
                ok=True,
                status=KeyAgeStatus.UNSUPPORTED,
                detail=(
                    "regista's CLI has no 'principal list' subcommand — "
                    "key-age check requires regista Plan 026 WI-3.1"
                ),
            )
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.UNREACHABLE,
            detail=(
                f"regista principal list exit {result.returncode}: "
                f"{diagnostic[:200] or 'no diagnostic output'} — {KEY_WATCH_REMEDY}"
            ),
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return KeyRotationResult(
            ok=True, status=KeyAgeStatus.ERROR, detail="regista principal list emitted non-JSON"
        )

    entries, shape_error = _key_entries(data)
    if shape_error is not None:
        return KeyRotationResult(
            ok=True,
            status=KeyAgeStatus.ERROR,
            detail=f"regista principal list emitted {shape_error}",
        )

    now = time.time()
    warn_age = cadence_days * warn_threshold_pct / 100
    keys: list[KeyInfo] = []
    overall_ok = True
    overall_status = KeyAgeStatus.OK

    for principal_id, k in entries:
        valid_from = str(k.get("valid_from", k.get("created_at", "")))
        key_id = str(k.get("key_id", k.get("id", "unknown")))
        valid_to = k.get("valid_to")
        status_field = k.get("status")

        if valid_to is not None and str(valid_to):
            continue  # key is windowed out — skip
        if isinstance(status_field, str) and status_field and status_field != "active":
            continue  # revoked / superseded — not a key anybody signs with

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

    if not entries:
        detail = "registry read: no principal keys registered"
    elif not keys:
        detail = "registry read: no active keys (all windowed out or revoked)"
    else:
        detail = f"{len(keys)} key(s) checked"

    return KeyRotationResult(
        ok=overall_ok and overall_status not in (KeyAgeStatus.EXPIRED,),
        status=overall_status,
        keys=keys,
        cadence_days=cadence_days,
        detail=detail,
        checked=True,
    )


# ---------------------------------------------------------------------------
# Store growth check
# ---------------------------------------------------------------------------

#: Global options first, same as ``principal list`` — see :func:`principal_list_argv`.
_REGISTA_STATS_CMD: tuple[str, ...] = ("regista", "--json", "stats")

#: ``stats`` really is absent from regista's parser today, so this check's
#: ``UNSUPPORTED`` is a *true* negative — but it was reached by the same prose
#: scan, which would have said the same thing about a ``stats`` that existed and
#: failed. Detection is now evidence-based either way.
_STATS_PATH: tuple[str, ...] = ("stats",)


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
        diagnostic = result.stderr.strip()
        if subcommand_absent(diagnostic, path=_STATS_PATH):
            return StoreGrowthResult(
                ok=True,
                status=StoreGrowthStatus.UNSUPPORTED,
                detail=(
                    "regista's CLI has no 'stats' subcommand — "
                    "store-growth telemetry requires a regista feature"
                ),
            )
        return StoreGrowthResult(
            ok=True,
            status=StoreGrowthStatus.UNREACHABLE,
            detail=(
                f"regista stats exit {result.returncode}: "
                f"{diagnostic[:200] or 'no diagnostic output'} — telemetry was NOT read"
            ),
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
        checked=True,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_key_rotation_text(result: KeyRotationResult) -> str:
    """Human-readable summary for the key-rotation check.

    A result with no keys says whether the registry was *read* and found empty
    or never read at all, so the line cannot be mistaken for a clean check.
    """
    lines: list[str] = ["key rotation watch:"]
    if not result.keys:
        prefix = "" if result.checked else "not checked — "
        lines.append(f"  {result.status.value}: {prefix}{result.detail}")
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
        prefix = "" if result.checked else "not checked — "
        lines.append(f"  {result.status.value}: {prefix}{result.detail}")
        return "\n".join(lines)
    for p in result.projects:
        lines.append(f"  {p.project:<24} {p.event_count:>10} events  {p.store_bytes:>12} bytes")
    return "\n".join(lines)
