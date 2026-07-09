"""Unit tests for the alerting module — state-change debounce, emission, recovery.

All tests use stubbed runners and installed checks — no live infra.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from agent_suite.alerting import (
    AlertKind,
    AlertResult,
    EmissionStatus,
    format_alert_text,
    run_alert_check,
)
from agent_suite.doctor import SuiteReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    def __init__(self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out = self._outputs[cmd[0]]
        if isinstance(out, Exception):
            raise out
        return out


class StubEmitter:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.calls: list[tuple[str, bytes]] = []

    def __call__(self, url: str, payload: bytes) -> int:
        self.calls.append((url, payload))
        return self.status


def _stub_doctor(monkeypatch: pytest.MonkeyPatch, suite_ok: bool) -> None:
    from agent_suite import doctor as doctor_mod

    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: SuiteReport(suite_ok=suite_ok, components=[]),
    )


# ---------------------------------------------------------------------------
# State-change debounce
# ---------------------------------------------------------------------------


def test_first_run_red_emits_initial_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is AlertKind.INITIAL_RED
    assert result.emission is EmissionStatus.EMITTED
    assert len(emitter.calls) == 1
    assert state_path.exists()


def test_stable_red_does_not_emit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"suite_ok": False, "ts": 0}))
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is None
    assert result.emission is EmissionStatus.SKIPPED_NO_STATE_CHANGE
    assert len(emitter.calls) == 0


def test_recovery_emits_on_red_to_green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=True)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"suite_ok": False, "ts": 0}))
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is AlertKind.RECOVERY
    assert result.emission is EmissionStatus.EMITTED


def test_stable_green_does_not_emit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=True)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"suite_ok": True, "ts": 0}))
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is None
    assert result.emission is EmissionStatus.SKIPPED_NO_STATE_CHANGE


def test_green_to_red_emits_red(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"suite_ok": True, "ts": 0}))
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is AlertKind.RED
    assert result.emission is EmissionStatus.EMITTED


# ---------------------------------------------------------------------------
# No wake URL
# ---------------------------------------------------------------------------


def test_no_wake_url_skips_emission(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    monkeypatch.delenv("AGENT_WAKE_INGRESS_URL", raising=False)
    result = run_alert_check(
        wake_url=None,
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
    )
    assert result.alert_kind is AlertKind.INITIAL_RED
    assert result.emission is EmissionStatus.SKIPPED_NO_WAKE_URL
    assert "AGENT_WAKE_INGRESS_URL" in result.detail


def test_wake_url_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    monkeypatch.setenv("AGENT_WAKE_INGRESS_URL", "http://wake.example/ingress")
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url=None,
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.emission is EmissionStatus.EMITTED
    assert emitter.calls[0][0] == "http://wake.example/ingress"


# ---------------------------------------------------------------------------
# Delivery failure
# ---------------------------------------------------------------------------


def test_delivery_failure_on_http_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    emitter = StubEmitter(500)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.emission is EmissionStatus.DELIVERY_FAILED
    assert result.http_status == 500


def test_delivery_failure_on_network_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"

    def failing_emitter(url: str, payload: bytes) -> int:
        return 0

    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=failing_emitter,
    )
    assert result.emission is EmissionStatus.DELIVERY_FAILED
    assert result.http_status == 0


# ---------------------------------------------------------------------------
# State file resilience
# ---------------------------------------------------------------------------


def test_corrupted_state_treated_as_no_prior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=False)
    state_path = tmp_path / "state.json"
    state_path.write_text("not json")
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is AlertKind.INITIAL_RED


def test_missing_state_treated_as_no_prior(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_doctor(monkeypatch, suite_ok=True)
    state_path = tmp_path / "nonexistent.json"
    emitter = StubEmitter(200)
    result = run_alert_check(
        wake_url="http://wake.example/ingress",
        state_path=state_path,
        runner=StubRunner({}),
        installed=lambda _: False,
        emitter=emitter,
    )
    assert result.alert_kind is None  # first run green = no alert
    assert result.emission is EmissionStatus.SKIPPED_NO_STATE_CHANGE


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_alert_text() -> None:
    result = AlertResult(
        suite_ok=False,
        alert_kind=AlertKind.RED,
        emission=EmissionStatus.EMITTED,
        detail="alert (red) delivered",
        http_status=200,
        timestamp="2026-07-09T12:00:00+0000",
    )
    text = format_alert_text(result)
    assert "red" in text
    assert "emitted" in text
    assert "200" in text
