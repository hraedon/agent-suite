from __future__ import annotations

import json
import subprocess
from typing import Callable, Mapping

import pytest

from agent_suite.components import COMPONENTS, Component, Tier
from agent_suite.doctor import (
    ComponentReport,
    ComponentStatus,
    _compute_suite_ok,
    aggregate,
    format_text,
)


def _ok_json(component: str, version: str = "1.0.0") -> str:
    return json.dumps(
        {
            "component": component,
            "version": version,
            "ok": True,
            "regista": {"reachable": True, "project": "x", "chain_ok": True},
            "checks": [{"name": "regista", "status": "ok", "detail": ""}],
        }
    )


class StubRunner:
    """Returns canned `doctor --json` output (or raises) per component CLI name."""

    def __init__(self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        out = self._outputs[cmd[0]]
        if isinstance(out, Exception):
            raise out
        return out


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


def _installed_all() -> Callable[[str], bool]:
    return lambda _name: True


def _installed_none() -> Callable[[str], bool]:
    return lambda _name: False


def _runner_for(outputs: Mapping[str, str]) -> StubRunner:
    return StubRunner({k: _completed(stdout=v) for k, v in outputs.items()})


def _component_by_cli(cli: str) -> Component:
    for c in COMPONENTS:
        if c.doctor_cmd[0] == cli:
            return c
    raise KeyError(cli)


# --- aggregation correctness -------------------------------------------------


def test_all_ok_aggregates_green() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(installed=_installed_all(), runner=_runner_for(outputs))
    assert report.suite_ok is True
    assert all(r.status is ComponentStatus.OK for r in report.components)
    assert len(report.components) == len(COMPONENTS)


def test_umbrella_shape_matches_contract() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(installed=_installed_all(), runner=_runner_for(outputs))
    d = report.to_dict()
    assert set(d) == {"suite_ok", "components", "lock"}
    comp = d["components"][0]
    assert {"component", "tier", "status", "ok", "version", "detail", "regista", "checks"} <= set(
        comp
    )
    assert d["lock"]["matches"] is None  # WI-2.1 not yet implemented


def test_version_and_regista_pass_through() -> None:
    spine = _component_by_cli("regista")
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident, version="9.9.9") for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        components=(spine,),
    )
    r = report.components[0]
    assert r.version == "9.9.9"
    assert r.regista == {"reachable": True, "project": "x", "chain_ok": True}


# --- absent / tier-2 semantics -----------------------------------------------


def test_absent_tier2_is_absent_not_failure() -> None:
    wake = _component_by_cli("agent-wake")
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c is not wake}

    def installed(cli: str) -> bool:
        return cli != "agent-wake"

    report = aggregate(installed=installed, runner=_runner_for(outputs))
    wake_r = next(r for r in report.components if r.component == "agent-wake")
    assert wake_r.status is ComponentStatus.ABSENT
    assert wake_r.ok is False
    assert report.suite_ok is True  # optional tier absent does not fail the suite


def test_spine_absent_fails_suite() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.tier is not Tier.SPINE}

    def installed(cli: str) -> bool:
        return cli != "regista"

    report = aggregate(installed=installed, runner=_runner_for(outputs))
    spine = next(r for r in report.components if r.tier is Tier.SPINE)
    assert spine.status is ComponentStatus.ABSENT
    assert report.suite_ok is False


def test_all_absent_fails_suite() -> None:
    report = aggregate(installed=_installed_none(), runner=StubRunner({}))
    assert all(r.status is ComponentStatus.ABSENT for r in report.components)
    assert report.suite_ok is False


# --- failure modes -----------------------------------------------------------


def test_unreachable_installed_is_failure() -> None:
    notes = _component_by_cli("agent-notes")
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c is not notes}
    runner = StubRunner(
        {**{k: _completed(stdout=v) for k, v in outputs.items()}, "agent-notes": OSError("boom")}
    )
    report = aggregate(installed=_installed_all(), runner=runner)
    r = next(x for x in report.components if x.component == "agent-notes")
    assert r.status is ComponentStatus.UNREACHABLE
    assert report.suite_ok is False


def test_nonzero_exit_is_failed() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    runner = StubRunner(
        {
            k: _completed(stdout=v)
            if k != "regista"
            else _completed(returncode=1, stderr="db down")
            for k, v in outputs.items()
        }
    )
    report = aggregate(installed=_installed_all(), runner=runner)
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert report.suite_ok is False


def test_ok_false_is_failed() -> None:
    bad = json.dumps(
        {"component": "regista", "version": "1", "ok": False, "regista": {}, "checks": []}
    )
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=bad)
    report = aggregate(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED


def test_non_json_stdout_is_failed() -> None:
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout="not json at all")
    report = aggregate(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED


def test_degraded_not_failure() -> None:
    degraded = json.dumps(
        {
            "component": "regista",
            "version": "1",
            "ok": True,
            "degraded": True,
            "regista": {},
            "checks": [],
        }
    )
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=degraded)
    report = aggregate(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.DEGRADED
    assert report.suite_ok is True


# --- read-only / no mutation -------------------------------------------------


def test_doctor_only_reads_never_writes() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    runner = StubRunner({k: _completed(stdout=v) for k, v in outputs.items()})
    aggregate(installed=_installed_all(), runner=runner)
    # Every call is exactly the component's `doctor --json` invocation — no writes.
    expected = [c.doctor_cmd for c in COMPONENTS]
    assert runner.calls == expected


# --- status enum exhaustiveness ---------------------------------------------


@pytest.mark.parametrize("status", list(ComponentStatus))
def test_status_enum_dispatch_is_total(status: ComponentStatus) -> None:
    # _compute_suite_ok must handle every member without hitting assert_never.
    report = ComponentReport(component="x", tier=Tier.SPINE, status=status)
    assert isinstance(_compute_suite_ok([report]), bool)


def test_format_text_round_trip() -> None:
    report = aggregate(installed=_installed_none(), runner=StubRunner({}))
    text = format_text(report)
    assert "suite: NOT OK" in text
    assert "absent" in text
