"""Unit tests for the deploy module — profile-driven end-to-end deploy flow."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agent_suite.bootstrap import BootstrapResult, StepResult, StepKind, StepStatus
from agent_suite.deploy import (
    DeployResult,
    DeployStep,
    DeployStepResult,
    DeployStepStatus,
    format_text,
    run_deploy,
)
from agent_suite.doctor import SuiteReport
from agent_suite.lock import SuiteLock


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _installed_except(*missing: str):
    def check(cli: str) -> bool:
        return cli not in missing
    return check


class StubRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        return _completed(stdout='{"reachable": true, "ok": true}')


# --- dry-run tests -----------------------------------------------------------


def test_deploy_dry_run_profile_a() -> None:
    runner = StubRunner()
    result = run_deploy(
        dry_run=True,
        profile="A",
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.dry_run is True
    assert result.profile == "A"
    assert len(runner.calls) == 0
    for step in result.steps:
        assert step.status in (DeployStepStatus.PENDING, DeployStepStatus.SKIPPED)


def test_deploy_dry_run_profile_b() -> None:
    runner = StubRunner()
    result = run_deploy(
        dry_run=True,
        profile="B",
        project="project-slug",
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.dry_run is True
    assert result.profile == "B"
    onboard_step = next(s for s in result.steps if s.step is DeployStep.ONBOARD)
    assert onboard_step.status is DeployStepStatus.PENDING


# --- preflight failure tests -------------------------------------------------


def test_deploy_preflight_missing_cli() -> None:
    result = run_deploy(
        profile="A",
        runner=StubRunner(),
        installed=_installed_except("regista"),
    )
    preflight = next(s for s in result.steps if s.step is DeployStep.PREFLIGHT)
    assert preflight.status is DeployStepStatus.FAILED
    assert result.ok is False
    bootstrap = next(s for s in result.steps if s.step is DeployStep.BOOTSTRAP)
    assert bootstrap.status is DeployStepStatus.SKIPPED


def test_deploy_preflight_missing_dossier() -> None:
    result = run_deploy(
        profile="B",
        project="project-slug",
        runner=StubRunner(),
        installed=_installed_except("dossier"),
    )
    preflight = next(s for s in result.steps if s.step is DeployStep.PREFLIGHT)
    assert preflight.status is DeployStepStatus.FAILED
    assert "dossier" in preflight.detail
    assert result.ok is False


# --- full deploy (monkeypatched composed functions) --------------------------


def _stub_composed_functions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "agent_suite.deploy.run_bootstrap",
        lambda **kw: BootstrapResult(
            ok=True,
            dry_run=False,
            steps=[StepResult(StepKind.PROBE_SECRETS, StepStatus.DONE, "ok")],
        ),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.aggregate",
        lambda **kw: SuiteReport(suite_ok=True, components=[]),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.load_lock_file",
        lambda path=None: None,
    )
    monkeypatch.setattr(
        "agent_suite.deploy.generate_lock",
        lambda **kw: SuiteLock(
            release="1.0.0",
            regista_quad=None,
            components={},
        ),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.write_lock_file",
        lambda lock, path=None: None,
    )
    monkeypatch.setattr(
        "agent_suite.deploy.read_regista_quad",
        lambda **kw: None,
    )


def test_deploy_profile_a_full(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _stub_composed_functions(monkeypatch)
    monkeypatch.chdir(tmp_path)

    result = run_deploy(
        profile="A",
        dsn="postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista",
        runner=StubRunner(),
        installed=_installed_all,
    )
    assert result.ok is True
    assert result.dry_run is False
    statuses = {s.step: s.status for s in result.steps}
    assert statuses[DeployStep.PREFLIGHT] is DeployStepStatus.DONE
    assert statuses[DeployStep.BOOTSTRAP] is DeployStepStatus.DONE
    assert statuses[DeployStep.ONBOARD] is DeployStepStatus.SKIPPED
    assert statuses[DeployStep.LOCK] is DeployStepStatus.DONE
    assert statuses[DeployStep.DOCTOR] is DeployStepStatus.DONE


def test_deploy_bootstrap_failure_stops_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "agent_suite.deploy.run_bootstrap",
        lambda **kw: BootstrapResult(
            ok=False,
            dry_run=False,
            steps=[StepResult(StepKind.PROBE_DB, StepStatus.FAILED, "Postgres unreachable")],
        ),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.aggregate",
        lambda **kw: SuiteReport(suite_ok=True, components=[]),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.load_lock_file",
        lambda path=None: None,
    )
    monkeypatch.setattr(
        "agent_suite.deploy.generate_lock",
        lambda **kw: SuiteLock(release="1.0.0", regista_quad=None, components={}),
    )
    monkeypatch.setattr(
        "agent_suite.deploy.write_lock_file",
        lambda lock, path=None: None,
    )
    monkeypatch.setattr(
        "agent_suite.deploy.read_regista_quad",
        lambda **kw: None,
    )
    monkeypatch.chdir(tmp_path)

    result = run_deploy(
        profile="A",
        dsn="postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista",
        runner=StubRunner(),
        installed=_installed_all,
    )
    assert result.ok is False
    bootstrap = next(s for s in result.steps if s.step is DeployStep.BOOTSTRAP)
    assert bootstrap.status is DeployStepStatus.FAILED
    assert "Postgres unreachable" in bootstrap.detail
    for step in result.steps:
        if step.step not in (DeployStep.PREFLIGHT, DeployStep.BOOTSTRAP):
            assert step.status is DeployStepStatus.SKIPPED


# --- format_text and to_dict -------------------------------------------------


def test_deploy_format_text() -> None:
    result = DeployResult(
        ok=True,
        dry_run=False,
        profile="A",
        steps=[
            DeployStepResult(DeployStep.PREFLIGHT, DeployStepStatus.DONE, "ok"),
        ],
    )
    text = format_text(result)
    assert len(text) > 0
    assert "deploy" in text


def test_deploy_result_to_dict() -> None:
    result = DeployResult(
        ok=True,
        dry_run=False,
        profile="A",
        steps=[
            DeployStepResult(DeployStep.PREFLIGHT, DeployStepStatus.DONE, "ok"),
        ],
    )
    d = result.to_dict()
    assert "ok" in d
    assert "dry_run" in d
    assert "profile" in d
    assert "steps" in d
    assert d["ok"] is True
    assert d["profile"] == "A"
    assert len(d["steps"]) == 1
