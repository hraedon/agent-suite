from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Mapping

import pytest

from agent_suite.components import COMPONENTS, Component, Locality, Tier
from agent_suite.doctor import (
    ComponentReport,
    ComponentStatus,
    RemoteHealthResult,
    SuiteReport,
    _compute_suite_ok,
    aggregate,
    format_text,
)
from agent_suite.profiles import Profile


def _aggregate_safe(
    *,
    installed: Callable[[str], bool],
    runner: StubRunner,
    components: tuple[Component, ...] = COMPONENTS,
    lock_path: Path | None = None,
    shared_endpoints: dict[str, str] | None = None,
    remote_checker: Callable[[str], RemoteHealthResult] | None = None,
) -> SuiteReport:
    """Call aggregate() with lock-drift stubbed so tests don't shell out."""
    if lock_path is None:
        lock_path = Path(tempfile.mktemp())
    return aggregate(
        installed=installed,
        runner=runner,
        components=components,
        lock_path=lock_path,
        version_installed=lambda _: False,
        key_watch_checks=False,
        shared_endpoints=shared_endpoints,
        remote_checker=remote_checker,
        memory_provider_checks=False,
        codex_health_checks=False,
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
    """Returns canned `doctor --json` output (or raises) per component CLI name.

    Unknown commands return a non-zero exit — this lets the doctor's
    error-handling paths work without every test stubbing every CLI.
    """

    def __init__(self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        out = self._outputs.get(cmd[0])
        if out is None:
            return _completed(stdout="", returncode=1, stderr=f"{cmd[0]}: not stubbed")
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
    report = _aggregate_safe(installed=_installed_all(), runner=_runner_for(outputs))
    assert report.suite_ok is True
    assert all(r.status is ComponentStatus.OK for r in report.components)
    assert len(report.components) == len(COMPONENTS)


def test_umbrella_shape_matches_contract() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = _aggregate_safe(installed=_installed_all(), runner=_runner_for(outputs))
    d = report.to_dict()
    assert set(d) == {"suite_ok", "components", "lock", "duration_ms"}
    comp = d["components"][0]
    assert {"component", "tier", "status", "ok", "version", "detail", "regista", "checks", "duration_ms"} <= set(
        comp
    )
    assert d["lock"]["matches"] is None  # no lock file in test env


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

    report = _aggregate_safe(installed=installed, runner=_runner_for(outputs))
    wake_r = next(r for r in report.components if r.component == "agent-wake")
    assert wake_r.status is ComponentStatus.ABSENT
    assert wake_r.ok is False
    assert report.suite_ok is True  # optional tier absent does not fail the suite


def test_spine_absent_fails_suite() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.tier is not Tier.SPINE}

    def installed(cli: str) -> bool:
        return cli != "regista"

    report = _aggregate_safe(installed=installed, runner=_runner_for(outputs))
    spine = next(r for r in report.components if r.tier is Tier.SPINE)
    assert spine.status is ComponentStatus.ABSENT
    assert report.suite_ok is False


def test_all_absent_fails_suite() -> None:
    report = _aggregate_safe(installed=_installed_none(), runner=StubRunner({}))
    # Dossier is a shared-service component — without an endpoint it is
    # NOT_CONFIGURED (Plan 004 WI-1.6), not ABSENT. All others are ABSENT.
    for r in report.components:
        if r.component == "dossier":
            assert r.status is ComponentStatus.NOT_CONFIGURED
        else:
            assert r.status is ComponentStatus.ABSENT
    assert report.suite_ok is False


# --- failure modes -----------------------------------------------------------


def test_unreachable_installed_is_failure() -> None:
    notes = _component_by_cli("agent-notes")
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c is not notes}
    runner = StubRunner(
        {**{k: _completed(stdout=v) for k, v in outputs.items()}, "agent-notes": OSError("boom")}
    )
    report = _aggregate_safe(installed=_installed_all(), runner=runner)
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
    report = _aggregate_safe(installed=_installed_all(), runner=runner)
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert report.suite_ok is False


def test_ok_false_is_failed() -> None:
    bad = json.dumps(
        {"component": "regista", "version": "1", "ok": False, "regista": {}, "checks": []}
    )
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=bad)
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED


def test_non_json_stdout_is_failed() -> None:
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout="not json at all")
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
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
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.DEGRADED
    assert report.suite_ok is True


# --- missing ok field (fail-honest) ------------------------------------------


def test_missing_ok_with_empty_checks_is_failed() -> None:
    missing_ok = json.dumps({"checks": []})
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=missing_ok)
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert r.ok is False
    assert "ok" in r.detail
    assert report.suite_ok is False


def test_empty_dict_is_failed() -> None:
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout="{}")
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert r.ok is False
    assert "ok" in r.detail


def test_missing_ok_with_all_ok_checks_is_failed() -> None:
    missing_ok = json.dumps({"checks": [{"status": "ok"}]})
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=missing_ok)
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert r.ok is False
    assert "ok" in r.detail


def test_missing_ok_no_checks_key_is_failed() -> None:
    missing_ok = json.dumps({"version": "1.0.0"})
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=missing_ok)
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert r.ok is False
    assert "ok" in r.detail


def test_present_ok_true_with_checks_is_ok() -> None:
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.OK
    assert r.ok is True


def test_present_ok_false_is_failed() -> None:
    bad = json.dumps({"ok": False, "checks": []})
    base = {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
    base["regista"] = _completed(stdout=bad)
    report = _aggregate_safe(installed=_installed_all(), runner=StubRunner(base))
    r = next(x for x in report.components if x.tier is Tier.SPINE)
    assert r.status is ComponentStatus.FAILED
    assert r.ok is False


# --- read-only / no mutation -------------------------------------------------


def test_doctor_only_reads_never_writes() -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    runner = StubRunner({k: _completed(stdout=v) for k, v in outputs.items()})
    _aggregate_safe(installed=_installed_all(), runner=runner)
    # Every call is exactly the component's `doctor --json` invocation — no writes.
    # Order is non-deterministic (concurrent probes); compare as sets.
    expected = {c.doctor_cmd for c in COMPONENTS}
    assert set(runner.calls) == expected


# --- status enum exhaustiveness ---------------------------------------------


@pytest.mark.parametrize("status", list(ComponentStatus))
def test_status_enum_dispatch_is_total(status: ComponentStatus) -> None:
    # _compute_suite_ok must handle every member without hitting assert_never.
    report = ComponentReport(component="x", tier=Tier.SPINE, status=status)
    assert isinstance(_compute_suite_ok([report]), bool)


def test_format_text_round_trip() -> None:
    report = _aggregate_safe(installed=_installed_none(), runner=StubRunner({}))
    text = format_text(report)
    assert "suite: NOT OK" in text
    assert "lock:" in text


# --- lock drift integration -------------------------------------------------


def test_doctor_lock_section_reports_no_lock(tmp_path: Path) -> None:
    report = _aggregate_safe(
        installed=_installed_none(), runner=StubRunner({}), lock_path=tmp_path / "missing.lock"
    )
    assert report.lock.matches is None
    assert "no SUITE.lock" in report.lock.note


def test_doctor_lock_section_reports_drift(tmp_path: Path) -> None:
    from agent_suite.lock import ComponentPin, SuiteLock, write_lock_file

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.1.0")},
    )
    lock_path = tmp_path / "SUITE.lock"
    write_lock_file(locked, lock_path)

    outputs = {c.doctor_cmd[0]: _ok_json(c.ident, version="0.4.0") for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=lock_path,
        version_installed=lambda _: False,
        revision_probe=lambda: {},
    )
    assert report.lock.matches is False
    assert any(
        d.kind.value == "version_mismatch" and d.component == "regista"
        for d in report.lock.drift
    )


def test_doctor_lock_section_reports_match(tmp_path: Path) -> None:
    from agent_suite.lock import ComponentPin, SuiteLock, write_lock_file

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={c.ident: ComponentPin(repo=c.repo, version="1.0.0") for c in COMPONENTS},
    )
    lock_path = tmp_path / "SUITE.lock"
    write_lock_file(locked, lock_path)

    outputs = {c.doctor_cmd[0]: _ok_json(c.ident, version="1.0.0") for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=lock_path,
        version_installed=lambda _: False,
        revision_probe=lambda: {},
    )
    assert report.lock.matches is True


def test_doctor_survives_malformed_lock(tmp_path: Path) -> None:
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text("not valid toml at all {{{")
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=lock_path,
        version_installed=lambda _: False,
    )
    assert report.lock.matches is False
    assert "unreadable" in report.lock.note


# --- verify-restore wiring (WI-4.2) -------------------------------------------


def test_aggregate_with_verify_restore_dsn_attaches_post_restore(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        verify_restore_dsn="postgresql://svc@suite-db.example/regista",
    )
    assert report.post_restore is not None
    assert report.post_restore.ok is False
    assert report.suite_ok is False


def test_aggregate_without_verify_restore_dsn_has_no_post_restore(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
    )
    assert report.post_restore is None


def test_aggregate_post_restore_failure_makes_suite_not_ok(tmp_path: Path) -> None:
    from unittest.mock import patch

    from agent_suite.verify_restore import VerifyRestoreResult

    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    with patch(
        "agent_suite.doctor.verify_restore.verify_restore",
        return_value=VerifyRestoreResult(ok=False, projects=[]),
    ):
        report = aggregate(
            installed=_installed_all(),
            runner=_runner_for(outputs),
            lock_path=tmp_path / "SUITE.lock",
            version_installed=lambda _: False,
            verify_restore_dsn="postgresql://svc@suite-db.example/regista",
        )
    assert report.suite_ok is False
    assert report.post_restore is not None
    assert report.post_restore.ok is False


# --- profile classification (Plan 008 WI-0.1) ---------------------------------


def test_aggregate_with_profile_attaches_classification(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        key_watch_checks=False,
        profile=Profile.C,
    )
    assert report.profile_classification is not None
    assert report.profile_classification.profile is Profile.C
    assert report.profile_classification.missing_required == []
    assert report.profile_classification.extra_optional == []


def test_aggregate_without_profile_has_no_classification(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        key_watch_checks=False,
    )
    assert report.profile_classification is None


def test_aggregate_profile_classification_json_round_trip(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        key_watch_checks=False,
        profile=Profile.C,
    )
    d = report.to_dict()
    assert "profile_classification" in d
    pc = d["profile_classification"]
    assert isinstance(pc, dict)
    assert pc["profile"] == "C"
    assert pc["missing_required"] == []
    assert pc["extra_optional"] == []


def test_aggregate_profile_classification_text_section(tmp_path: Path) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        key_watch_checks=False,
        profile=Profile.A,
    )
    text = format_text(report)
    assert "profile classification" in text
    assert "profile: C (Operated full suite)" in text


def test_aggregate_profile_classification_without_profile_omits_from_dict(
    tmp_path: Path,
) -> None:
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        lock_path=tmp_path / "SUITE.lock",
        version_installed=lambda _: False,
        key_watch_checks=False,
    )
    d = report.to_dict()
    assert "profile_classification" not in d


# --- shared-service locality (Plan 004 WI-1.6) ---------------------------------


class StubRemoteChecker:
    """Returns a canned RemoteHealthResult per component ident."""

    def __init__(self, results: Mapping[str, RemoteHealthResult]) -> None:
        self._results = results
        self.calls: list[str] = []

    def __call__(self, url: str) -> RemoteHealthResult:
        self.calls.append(url)
        # The checker is called per-endpoint; tests look up by URL.
        for _ident, result in self._results.items():
            if url.endswith(_ident) or _ident in url or url == _ident:
                return result
        return self._results.get(url, RemoteHealthResult(ok=False, detail="no stub"))


def _remote_ok(version: str = "2.0.0") -> RemoteHealthResult:
    return RemoteHealthResult(ok=True, version=version, detail="")


def _remote_fail(detail: str = "connection refused") -> RemoteHealthResult:
    return RemoteHealthResult(ok=False, detail=detail)


def _installed_except(cli_to_skip: str) -> Callable[[str], bool]:
    return lambda cli: cli != cli_to_skip


def test_shared_service_not_installed_with_endpoint_is_remote() -> None:
    """Dossier not installed locally but endpoint configured → REMOTE status."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_ok("2.1.0")}),
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.REMOTE
    assert dr.ok is True
    assert dr.version == "2.1.0"
    assert "remote: ok @ 2.1.0" in dr.detail
    assert report.suite_ok is True


def test_shared_service_not_installed_without_endpoint_is_not_configured() -> None:
    """Dossier not installed locally and no endpoint → NOT_CONFIGURED."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints=None,
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.NOT_CONFIGURED
    assert dr.ok is False
    assert "not configured" in dr.detail.lower()
    assert "shared service" in dr.detail.lower()
    assert report.suite_ok is True  # not a failure, just not set up


def test_shared_service_endpoint_down_is_failed() -> None:
    """Dossier endpoint configured but unreachable → FAILED with URL in detail."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_fail("connection refused")}),
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.FAILED
    assert dr.ok is False
    assert "dossier.example.com" in dr.detail
    assert "connection refused" in dr.detail
    assert report.suite_ok is False


def test_shared_service_installed_locally_uses_local_doctor() -> None:
    """When dossier IS installed locally, local doctor takes precedence over endpoint."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS}
    checker = StubRemoteChecker({"dossier": _remote_ok("99.0.0")})
    report = _aggregate_safe(
        installed=_installed_all(),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=checker,
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.OK  # local doctor, not remote
    assert dr.version == "1.0.0"  # from the local doctor output, not the remote
    assert checker.calls == []  # remote checker was never called


def test_remote_status_does_not_fail_suite() -> None:
    """A suite where dossier is remote-ok and everything else is ok → suite OK."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_ok()}),
    )
    assert report.suite_ok is True


def test_not_configured_does_not_fail_suite_when_others_ok() -> None:
    """A suite where dossier is not-configured but everything else is ok → suite OK."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
    )
    assert report.suite_ok is True


def test_all_absent_or_not_configured_fails_suite() -> None:
    """All components absent or not_configured → suite NOT OK."""
    report = _aggregate_safe(
        installed=_installed_none(),
        runner=StubRunner({}),
    )
    statuses = {r.component: r.status for r in report.components}
    # dossier should be NOT_CONFIGURED (shared service, no endpoint)
    assert statuses["dossier"] is ComponentStatus.NOT_CONFIGURED
    # everything else should be ABSENT
    for ident, status in statuses.items():
        if ident != "dossier":
            assert status is ComponentStatus.ABSENT
    assert report.suite_ok is False


def test_remote_version_feeds_lock_drift() -> None:
    """The version from a remote health check participates in lock-drift comparison."""
    from agent_suite.lock import ComponentPin, SuiteLock, write_lock_file

    locked = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={
            c.ident: ComponentPin(repo=c.repo, version="1.0.0") for c in COMPONENTS
        },
    )
    lock_path = Path(tempfile.mktemp())
    write_lock_file(locked, lock_path)

    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = aggregate(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        lock_path=lock_path,
        version_installed=lambda _: False,
        revision_probe=lambda: {},
        key_watch_checks=False,
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_ok("2.0.0")}),
    )
    assert report.lock.matches is False
    assert any(
        d.component == "dossier" and d.kind.value == "version_mismatch"
        for d in report.lock.drift
    )


def test_format_text_shows_remote_status() -> None:
    """format_text renders the remote status and version for shared-service components."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_ok("3.0.0")}),
    )
    text = format_text(report)
    assert "remote" in text
    assert "3.0.0" in text


def test_format_text_shows_not_configured() -> None:
    """format_text renders the not_configured state for shared-service without endpoint."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
    )
    text = format_text(report)
    assert "not_configured" in text
    assert "shared service" in text.lower()


def test_profile_classification_remote_counts_as_installed() -> None:
    """A shared-service component in REMOTE status should count as installed for profile."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = aggregate(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": _remote_ok()}),
        profile=Profile.B,
    )
    assert report.profile_classification is not None
    assert "dossier" not in report.profile_classification.missing_required


def test_profile_classification_not_configured_counts_as_missing() -> None:
    """A shared-service component in NOT_CONFIGURED should count as missing for profile."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = aggregate(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        profile=Profile.B,
    )
    assert report.profile_classification is not None
    assert "dossier" in report.profile_classification.missing_required


def test_dossier_is_only_shared_service_component() -> None:
    """Only dossier is marked as SHARED_SERVICE in the default component set."""
    shared = [c for c in COMPONENTS if c.locality is Locality.SHARED_SERVICE]
    assert len(shared) == 1
    assert shared[0].ident == "dossier"
    assert shared[0].endpoint_env_var == "DOSSIER_URL"


def test_component_report_to_dict_includes_new_statuses() -> None:
    """ComponentReport.to_dict() serializes the new status values correctly."""
    for status in (ComponentStatus.REMOTE, ComponentStatus.NOT_CONFIGURED):
        report = ComponentReport(
            component="dossier", tier=Tier.FACE, status=status, ok=True, version="1.0"
        )
        d = report.to_dict()
        assert d["status"] == status.value


def test_empty_string_endpoint_treated_as_not_configured() -> None:
    """An empty-string DOSSIER_URL should be treated as not configured."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": ""},
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.NOT_CONFIGURED


def test_remote_ok_without_version_shows_unknown() -> None:
    """Healthz returning ok:true without version → REMOTE with 'unknown' version."""
    outputs = {c.doctor_cmd[0]: _ok_json(c.ident) for c in COMPONENTS if c.ident != "dossier"}
    report = _aggregate_safe(
        installed=_installed_except("dossier"),
        runner=_runner_for(outputs),
        shared_endpoints={"dossier": "https://dossier.example.com"},
        remote_checker=StubRemoteChecker({"dossier": RemoteHealthResult(ok=True, version=None)}),
    )
    dr = next(r for r in report.components if r.component == "dossier")
    assert dr.status is ComponentStatus.REMOTE
    assert dr.ok is True
    assert dr.version is None
    assert "unknown" in dr.detail


def test_default_remote_check_rejects_non_http_scheme() -> None:
    """_default_remote_check rejects file:// and other non-http(s) schemes."""
    from agent_suite.doctor import _default_remote_check

    result = _default_remote_check("file:///etc/passwd")
    assert result.ok is False
    assert "non-http" in result.detail.lower() or "scheme" in result.detail.lower()


def test_status_enum_dispatch_is_total_with_new_statuses() -> None:
    """_compute_suite_ok must handle REMOTE and NOT_CONFIGURED without assert_never."""
    for status in (ComponentStatus.REMOTE, ComponentStatus.NOT_CONFIGURED):
        report = ComponentReport(component="x", tier=Tier.FACE, status=status)
        assert isinstance(_compute_suite_ok([report]), bool)


def test_codex_health_section_in_doctor_output() -> None:
    """aggregate() with codex_health_checks=True includes codex health."""
    from agent_suite.codex_health import CodexPluginHealthStatus

    spine = _component_by_cli("regista")
    plugin_list_stdout = json.dumps({
        "installed": [
            {
                "pluginId": "agent-notes@agent-suite",
                "name": "agent-notes",
                "marketplaceName": "agent-suite",
                "version": "1.0.0",
                "enabled": True,
            },
        ],
        "available": [],
    })

    class CodexRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(cmd)
            if cmd[:3] == ("codex", "plugin", "list"):
                return _completed(stdout=plugin_list_stdout)
            return _completed(stdout='{"ok": true}')

    codex_runner = CodexRunner()
    report = aggregate(
        installed=lambda name: name == "codex" or name == "regista",
        runner=codex_runner,
        components=(spine,),
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=True,
    )
    assert report.codex_health is not None
    assert report.codex_health.codex_installed is True
    assert report.codex_health.ok is True
    assert len(report.codex_health.plugins) == 4
    notes_plugin = next(
        p for p in report.codex_health.plugins
        if p.plugin_id.value == "agent-notes"
    )
    assert notes_plugin.status is CodexPluginHealthStatus.INSTALLED_ENABLED
    # doctor must never shell a nonexistent `codex hooks status`
    assert not any(c[:2] == ("codex", "hooks") for c in codex_runner.calls)
    text = format_text(report)
    assert "codex health:" in text
    assert "agent-notes" in text


def test_codex_health_absent_when_checks_disabled() -> None:
    """aggregate() with codex_health_checks=False omits codex health."""
    spine = _component_by_cli("regista")
    report = aggregate(
        installed=_installed_all(),
        runner=_runner_for({spine.doctor_cmd[0]: _ok_json(spine.ident)}),
        components=(spine,),
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=False,
    )
    assert report.codex_health is None
    text = format_text(report)
    assert "codex health:" not in text


def test_codex_health_failure_does_not_affect_suite_ok() -> None:
    """codex_health.ok=False must not make suite_ok False (informational only)."""
    spine = _component_by_cli("regista")

    class CodexFailRunner:
        def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            if cmd[0] == "codex":
                return _completed(stdout="", returncode=1, stderr="plugin db down")
            if cmd[0] == "regista":
                return _completed(stdout=_ok_json("regista"))
            return _completed(stdout='{"ok": true}')

    report = aggregate(
        installed=lambda name: name == "codex" or name == "regista",
        runner=CodexFailRunner(),
        components=(spine,),
        lock_path=Path(tempfile.mktemp()),
        version_installed=lambda _: False,
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=True,
    )
    assert report.codex_health is not None
    assert report.codex_health.ok is False
    assert report.suite_ok is True
