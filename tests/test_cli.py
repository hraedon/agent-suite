from __future__ import annotations

import pytest

from agent_suite import doctor as doctor_mod
from agent_suite.cli import Command, main


def test_subcommands_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub doctor aggregation so the CLI test never shells out to real binaries.
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=False, components=[]),
    )
    for command in Command:
        assert main([command.value]) == 0


def test_doctor_exit_code_nonzero_when_unhealthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=False, components=[]),
    )
    assert main(["doctor", "--exit-code"]) == 1


def test_doctor_exit_code_zero_when_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=True, components=[]),
    )
    assert main(["doctor", "--exit-code"]) == 0


def test_doctor_json_emits_valid_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(suite_ok=True, components=[]),
    )
    import json

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["doctor", "--json"])
    assert rc == 0
    parsed = json.loads(buf.getvalue())
    assert parsed["suite_ok"] is True
    assert "components" in parsed and "lock" in parsed


def test_no_subcommand_errors() -> None:
    with pytest.raises(SystemExit):
        main([])
