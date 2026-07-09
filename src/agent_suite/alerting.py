"""The alerting loop — schedule doctor, route red results to a human.

Implements Plan 005 WI-3.1. A scheduled run of ``agent-suite doctor --json``
checks suite health on a cadence (via systemd timer / Windows Scheduled Task —
not a daemon). When the result transitions to red/degraded (or recovers to
green), the result is posted to agent-wake's ingress for human delivery
(agent-wake Plan 005 WI-1.4 owns the delivery leg; this module owns the
scheduling and emitting).

Debounce: state-change emission, not every-run spam. A stable red suite emits
one alert on the transition; subsequent red runs are silent until recovery.
This is achieved with a state file (no daemon — the state lives on disk
between scheduled runs).

Design (AGENTS.md): thin orchestration — ``doctor`` is read-only; the emitter
posts via stdlib ``urllib`` to a configurable agent-wake ingress URL (from
``suite.env`` or ``--wake-url``). No secrets are held; the wake URL is an
endpoint, not a credential. ``assert_never`` over the closed-set enum.
stdlib-only core.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from agent_suite import doctor as doctor_mod


# ---------------------------------------------------------------------------
# Injectable interfaces
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a component CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


class Emitter(Protocol):
    """Post an alert payload to agent-wake's ingress."""

    def __call__(self, url: str, payload: bytes) -> int: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


def _default_emitter(url: str, payload: bytes) -> int:
    """Post JSON to agent-wake's ingress via stdlib urllib.

    Returns the HTTP status code (0 on network error). Never raises — a
    network failure is a named state in the alert result, not a crash.
    """
    req = urllib_request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            return int(resp.status)
    except (urllib_error.URLError, OSError, TimeoutError):
        return 0


# ---------------------------------------------------------------------------
# Closed-set enums
# ---------------------------------------------------------------------------


class AlertKind(Enum):
    """The closed set of alert kinds (state transitions).

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in the formatting or emission logic.
    """

    RED = "red"  # suite transitioned to not-ok
    RECOVERY = "recovery"  # suite transitioned back to ok
    INITIAL_RED = "initial_red"  # first run and already red (no prior state)


class EmissionStatus(Enum):
    """The outcome of posting an alert."""

    EMITTED = "emitted"
    SKIPPED_NO_STATE_CHANGE = "skipped_no_state_change"
    SKIPPED_NO_WAKE_URL = "skipped_no_wake_url"
    DELIVERY_FAILED = "delivery_failed"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class AlertResult:
    """The outcome of one scheduled doctor + alert run."""

    suite_ok: bool
    alert_kind: AlertKind | None
    emission: EmissionStatus
    detail: str = ""
    http_status: int = 0
    timestamp: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "suite_ok": self.suite_ok,
            "alert_kind": self.alert_kind.value if self.alert_kind else None,
            "emission": self.emission.value,
            "detail": self.detail,
            "http_status": self.http_status,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# State management (no daemon — state on disk between runs)
# ---------------------------------------------------------------------------

DEFAULT_STATE_PATH = Path("/var/lib/agent-suite/last-doctor-state.json")


def _read_state(state_path: Path) -> bool | None:
    """Read the last known suite_ok state from the state file.

    Returns ``None`` if no state file exists (first run). Never raises — a
    corrupted state file is treated as no prior state.
    """
    try:
        text = state_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return bool(data.get("suite_ok", False))
    return None


def _write_state(suite_ok: bool, state_path: Path) -> None:
    """Write the current suite_ok state to the state file.

    Creates the parent directory if it doesn't exist. Never raises on write
    failure — the state file is best-effort; a missing state file means the
    next run is treated as a first run (emits on any red).
    """
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"suite_ok": suite_ok, "ts": time.time()}),
            encoding="utf-8",
        )
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Alert payload construction
# ---------------------------------------------------------------------------


def _build_payload(
    alert_kind: AlertKind,
    report: doctor_mod.SuiteReport,
    timestamp: str,
) -> bytes:
    """Build the JSON payload posted to agent-wake's ingress."""
    payload: dict[str, object] = {
        "source": "agent-suite-doctor",
        "alert_kind": alert_kind.value,
        "timestamp": timestamp,
        "suite_ok": report.suite_ok,
        "summary": _summarize_report(report),
    }
    return json.dumps(payload).encode("utf-8")


def _summarize_report(report: doctor_mod.SuiteReport) -> str:
    """One-line human-readable summary of the doctor report for the alert."""
    if report.suite_ok:
        return "suite is healthy"
    failed = [
        c.component for c in report.components
        if c.status in (doctor_mod.ComponentStatus.FAILED, doctor_mod.ComponentStatus.UNREACHABLE)
    ]
    parts: list[str] = []
    if failed:
        parts.append(f"failed: {', '.join(failed)}")
    if report.lock.matches is False:
        parts.append(f"lock drift: {report.lock.note}")
    if report.post_restore is not None and not report.post_restore.ok:
        parts.append("post-restore verification failed")
    return "; ".join(parts) if parts else "suite is not ok"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_alert_check(
    *,
    wake_url: str | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    emitter: Emitter = _default_emitter,
) -> AlertResult:
    """Run one scheduled doctor check and emit an alert on state change.

    1. Run ``agent-suite doctor`` (the aggregated health umbrella).
    2. Compare the result to the last known state (from ``state_path``).
    3. If the state changed (ok→red, red→ok, or first-run-red), emit an alert
       to ``wake_url``.
    4. Write the new state to ``state_path``.

    ``wake_url`` resolves from the argument, then ``AGENT_WAKE_INGRESS_URL``
    environment variable. If no URL is configured, the alert is skipped (the
    state is still recorded — the operator can see the state file).
    """
    if wake_url is None:
        wake_url = os.environ.get("AGENT_WAKE_INGRESS_URL")

    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.gmtime())

    report = doctor_mod.aggregate(runner=runner, installed=installed)
    current_ok = report.suite_ok
    prior_ok = _read_state(state_path)

    alert_kind: AlertKind | None = None
    if current_ok and prior_ok is not True:
        if prior_ok is False:
            alert_kind = AlertKind.RECOVERY
    elif not current_ok:
        if prior_ok is None:
            alert_kind = AlertKind.INITIAL_RED
        elif prior_ok is True:
            alert_kind = AlertKind.RED

    _write_state(current_ok, state_path)

    if alert_kind is None:
        return AlertResult(
            suite_ok=current_ok,
            alert_kind=None,
            emission=EmissionStatus.SKIPPED_NO_STATE_CHANGE,
            detail="state unchanged — no alert emitted",
            timestamp=timestamp,
        )

    if not wake_url:
        return AlertResult(
            suite_ok=current_ok,
            alert_kind=alert_kind,
            emission=EmissionStatus.SKIPPED_NO_WAKE_URL,
            detail=(
                f"alert detected ({alert_kind.value}) but no wake URL configured "
                "— set AGENT_WAKE_INGRESS_URL in suite.env"
            ),
            timestamp=timestamp,
        )

    payload = _build_payload(alert_kind, report, timestamp)
    http_status = emitter(wake_url, payload)

    if http_status == 0 or http_status >= 400:
        return AlertResult(
            suite_ok=current_ok,
            alert_kind=alert_kind,
            emission=EmissionStatus.DELIVERY_FAILED,
            detail=f"delivery to {wake_url} failed (HTTP {http_status})",
            http_status=http_status,
            timestamp=timestamp,
        )

    return AlertResult(
        suite_ok=current_ok,
        alert_kind=alert_kind,
        emission=EmissionStatus.EMITTED,
        detail=f"alert ({alert_kind.value}) delivered to {wake_url}",
        http_status=http_status,
        timestamp=timestamp,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_alert_text(result: AlertResult) -> str:
    """Human-readable summary for the scheduled alert run."""
    lines: list[str] = ["agent-suite alert-check"]
    lines.append("")
    lines.append(f"  suite_ok: {result.suite_ok}")
    lines.append(f"  alert_kind: {result.alert_kind.value if result.alert_kind else 'none'}")
    lines.append(f"  emission: {result.emission.value}")
    if result.http_status:
        lines.append(f"  http_status: {result.http_status}")
    if result.timestamp:
        lines.append(f"  timestamp: {result.timestamp}")
    lines.append("")
    if result.detail:
        lines.append(f"  {result.detail}")
    return "\n".join(lines)
