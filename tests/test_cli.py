from __future__ import annotations

import io
import contextlib
import json

import pytest

from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite.cli import Command, main


def _stub_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub lock I/O and regista-quad reads so CLI tests don't shell out or write."""
    monkeypatch.setattr(lock_mod, "read_regista_quad", lambda **kw: None)
    monkeypatch.setattr(lock_mod, "write_lock_file", lambda lock, path=None: None)
    monkeypatch.setattr(lock_mod, "load_lock_file", lambda path=None: None)


def _stub_aggregate(monkeypatch: pytest.MonkeyPatch, *, suite_ok: bool = False) -> None:
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=suite_ok, components=[]),
    )


def test_subcommands_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    _stub_lock(monkeypatch)
    for command in Command:
        assert main([command.value]) == 0


def test_lock_check_exits_nonzero_when_no_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    _stub_lock(monkeypatch)
    assert main(["lock", "--check"]) == 1


def test_lock_check_exits_nonzero_on_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    from agent_suite.lock import ComponentPin, SuiteLock

    existing = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="hraedon/dossier", version="0.1.0")},
    )
    monkeypatch.setattr(lock_mod, "load_lock_file", lambda path=None: existing)
    monkeypatch.setattr(lock_mod, "read_regista_quad", lambda **kw: None)
    assert main(["lock", "--check"]) == 1


def test_doctor_exit_code_nonzero_when_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=False)
    assert main(["doctor", "--exit-code"]) == 1


def test_doctor_exit_code_zero_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    assert main(["doctor", "--exit-code"]) == 0


def test_doctor_json_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["suite_ok"] is True
    assert "components" in parsed and "lock" in parsed
    assert "matches" in parsed["lock"]


def test_lock_json_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_aggregate(monkeypatch, suite_ok=True)
    _stub_lock(monkeypatch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["lock", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert "suite" in parsed
    assert "components" in parsed


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main([])
