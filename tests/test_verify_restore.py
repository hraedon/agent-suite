from __future__ import annotations

import json
import subprocess
from typing import Callable, Mapping

import pytest

from agent_suite.verify_restore import (
    ProjectVerifyResult,
    ProjectVerifyStatus,
    VerifyRestoreResult,
    _compute_ok,
    format_text,
    verify_restore,
)


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _replay_json(
    *,
    replayed_ok: int = 1,
    replayed_drift: int = 0,
    halted: int = 0,
    warnings: int = 0,
) -> str:
    d: dict[str, object] = {
        "table_name": "events",
        "replayed_ok": replayed_ok,
        "replayed_drift": replayed_drift,
        "halted": halted,
    }
    if warnings > 0:
        d["warnings"] = warnings
    return json.dumps(d)


class StubRunner:
    """Returns canned output (or raises) keyed by project slug for replay."""

    def __init__(
        self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if "replay" in cmd and "--project" in cmd:
            key = cmd[cmd.index("--project") + 1]
        else:
            key = cmd[0]
        out = self._outputs[key]
        if isinstance(out, Exception):
            raise out
        return out


def _installed_all() -> Callable[[str], bool]:
    return lambda _name: True


_DSN = "postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista"


# --- test 1: all projects verified --------------------------------------------


def test_all_projects_verified() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=5)),
            "beta": _completed(stdout=_replay_json(replayed_ok=3)),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha", "beta"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is True
    assert len(result.projects) == 2
    assert all(p.status is ProjectVerifyStatus.VERIFIED for p in result.projects)
    assert result.projects[0].replayed_ok == 5
    assert result.projects[1].replayed_ok == 3


# --- test 2: drift detected ---------------------------------------------------


def test_drift_detected() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=5)),
            "beta": _completed(
                stdout=_replay_json(replayed_ok=3, replayed_drift=2, halted=1)
            ),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha", "beta"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    beta = next(p for p in result.projects if p.project == "beta")
    assert beta.status is ProjectVerifyStatus.DRIFT_DETECTED
    assert beta.replayed_drift == 2
    assert beta.halted == 1
    alpha = next(p for p in result.projects if p.project == "alpha")
    assert alpha.status is ProjectVerifyStatus.VERIFIED


# --- test 2b: warnings detected (chain-link tampering) ------------------------


def test_warnings_detected() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=5, warnings=3)),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.WARNINGS_DETECTED
    assert result.projects[0].warnings == 3
    assert "warnings" in result.projects[0].detail.lower()


def test_warnings_with_drift_classifies_as_drift() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(
                stdout=_replay_json(replayed_ok=3, replayed_drift=2, warnings=1)
            ),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.DRIFT_DETECTED
    assert result.projects[0].warnings == 1


def test_zero_warnings_is_verified() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=5, warnings=0)),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is True
    assert result.projects[0].status is ProjectVerifyStatus.VERIFIED
    assert result.projects[0].warnings == 0


def test_warnings_key_omitted_is_verified() -> None:
    runner = StubRunner(
        {"alpha": _completed(stdout=json.dumps({"replayed_ok": 5, "replayed_drift": 0, "halted": 0}))}
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is True
    assert result.projects[0].status is ProjectVerifyStatus.VERIFIED
    assert result.projects[0].warnings == 0


# --- test 3: unreachable project ----------------------------------------------

def test_unreachable_project() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=5)),
            "beta": OSError("connection refused"),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha", "beta"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    beta = next(p for p in result.projects if p.project == "beta")
    assert beta.status is ProjectVerifyStatus.UNREACHABLE
    assert "connection refused" in beta.detail


# --- test 4: empty project list -----------------------------------------------


def test_empty_project_list() -> None:
    result = verify_restore(
        dsn=_DSN,
        projects=[],
        runner=StubRunner({}),
        installed=_installed_all(),
    )
    assert result.ok is True
    assert result.projects == []
    assert "no projects" in result.note.lower()


# --- test 5: regista not installed --------------------------------------------


def test_regista_not_installed() -> None:
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=StubRunner({}),
        installed=lambda _name: False,
    )
    assert result.ok is False
    assert result.projects == []
    assert "regista" in result.note.lower()
    assert "install" in result.note.lower()


# --- test 6: format_text ------------------------------------------------------


def test_format_text() -> None:
    result = VerifyRestoreResult(
        ok=False,
        projects=[
            ProjectVerifyResult(
                project="alpha",
                status=ProjectVerifyStatus.VERIFIED,
                replayed_ok=5,
                replayed_drift=0,
                halted=0,
            ),
            ProjectVerifyResult(
                project="beta",
                status=ProjectVerifyStatus.DRIFT_DETECTED,
                replayed_ok=3,
                replayed_drift=2,
                halted=1,
            ),
            ProjectVerifyResult(
                project="gamma",
                status=ProjectVerifyStatus.WARNINGS_DETECTED,
                replayed_ok=4,
                warnings=2,
            ),
        ],
        note="one or more projects failed verification",
    )
    text = format_text(result)
    assert "alpha" in text
    assert "beta" in text
    assert "gamma" in text
    assert "5 ok" in text
    assert "2 drift" in text
    assert "2 warnings" in text
    assert "warnings" in text
    assert "verify-restore: NOT OK" in text
    assert "failed verification" in text


def test_format_text_warnings_status() -> None:
    result = VerifyRestoreResult(
        ok=False,
        projects=[
            ProjectVerifyResult(
                project="delta",
                status=ProjectVerifyStatus.WARNINGS_DETECTED,
                replayed_ok=4,
                warnings=5,
                detail="warnings detected: 5 warnings (possible chain-link tampering)",
            ),
        ],
        note="one or more projects failed verification",
    )
    text = format_text(result)
    assert "delta" in text
    assert "5 warnings" in text
    assert "verify-restore: NOT OK" in text


# --- test 7: status enum exhaustiveness (assert_never) -----------------------


@pytest.mark.parametrize("status", list(ProjectVerifyStatus))
def test_status_enum_dispatch_is_total(status: ProjectVerifyStatus) -> None:
    result = ProjectVerifyResult(project="x", status=status)
    assert isinstance(_compute_ok([result]), bool)


# --- additional coverage ------------------------------------------------------


def test_non_json_output_is_error() -> None:
    runner = StubRunner({"alpha": _completed(stdout="not json at all")})
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.ERROR


def test_nonzero_exit_is_unreachable() -> None:
    runner = StubRunner(
        {"alpha": _completed(returncode=1, stderr="connection refused")}
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.UNREACHABLE


def test_timeout_is_unreachable() -> None:
    runner = StubRunner(
        {"alpha": subprocess.TimeoutExpired(cmd=("regista", "replay"), timeout=300)}
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.UNREACHABLE


def test_malformed_counts_is_error() -> None:
    runner = StubRunner(
        {"alpha": _completed(stdout=json.dumps({"replayed_ok": "abc"}))}
    )
    result = verify_restore(
        dsn=_DSN,
        projects=["alpha"],
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is False
    assert result.projects[0].status is ProjectVerifyStatus.ERROR


def test_to_dict_shape() -> None:
    result = VerifyRestoreResult(
        ok=True,
        projects=[
            ProjectVerifyResult(
                project="alpha",
                status=ProjectVerifyStatus.VERIFIED,
                replayed_ok=5,
            ),
        ],
        note="ok",
    )
    d = result.to_dict()
    assert set(d) == {"ok", "projects", "note"}
    p = d["projects"][0]
    assert {
        "project",
        "status",
        "replayed_ok",
        "replayed_drift",
        "halted",
        "warnings",
        "detail",
    } <= set(p)
    assert p["status"] == "verified"


def test_discover_projects_from_regista_doctor() -> None:
    doctor_json = json.dumps(
        {
            "component": "regista",
            "version": "1.0.0",
            "ok": True,
            "regista": {
                "reachable": True,
                "project": "discovered-project",
                "chain_ok": True,
            },
            "checks": [],
        }
    )
    runner = StubRunner(
        {
            "regista": _completed(stdout=doctor_json),
            "discovered-project": _completed(stdout=_replay_json(replayed_ok=3)),
        }
    )
    result = verify_restore(
        dsn=_DSN,
        projects=None,
        runner=runner,
        installed=_installed_all(),
    )
    assert result.ok is True
    assert len(result.projects) == 1
    assert result.projects[0].project == "discovered-project"
    assert result.projects[0].status is ProjectVerifyStatus.VERIFIED


def test_format_text_ok() -> None:
    result = VerifyRestoreResult(
        ok=True,
        projects=[
            ProjectVerifyResult(
                project="alpha",
                status=ProjectVerifyStatus.VERIFIED,
                replayed_ok=5,
            ),
        ],
        note="ok",
    )
    text = format_text(result)
    assert "verify-restore: OK" in text


def test_replay_commands_issued_correctly() -> None:
    runner = StubRunner(
        {
            "alpha": _completed(stdout=_replay_json(replayed_ok=1)),
            "beta": _completed(stdout=_replay_json(replayed_ok=1)),
        }
    )
    verify_restore(
        dsn=_DSN,
        projects=["alpha", "beta"],
        runner=runner,
        installed=_installed_all(),
    )
    assert len(runner.calls) == 2
    for cmd in runner.calls:
        assert cmd[0] == "regista"
        assert "replay" in cmd
        assert "--dsn" in cmd
        assert "--project" in cmd
        assert "--json" in cmd
