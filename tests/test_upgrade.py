"""Unit tests for the upgrade module — advancement check, apply, rollback, interop gate.

All tests use stubbed runners and installed checks — no live infra (AGENTS.md:
"Ordering/idempotency unit-tested with stubbed component CLIs (no live infra
in CI)").
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping

import pytest

from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite.components import COMPONENTS, component_by_ident
from agent_suite.lock import (
    ComponentPin,
    LockDriftResult,
    RegistaVersionQuad,
    SuiteLock,
    serialize_lock,
)
from agent_suite.runtime_provenance import ArtifactSource, InstallMode, RuntimeProvenance
from agent_suite.upgrade import (
    AdvancementReport,
    AdvancementStatus,
    ApplyStatus,
    ComponentAdvancement,
    RollbackResult,
    RollbackStatus,
    UpgradeResult,
    check_advancements,
    format_advancement_text,
    format_rollback_text,
    format_upgrade_text,
    run_rollback,
    run_upgrade,
    _mutation_command,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


_QUAD = RegistaVersionQuad(
    library_version="0.4.0",
    schema_version=38,
    canonical_workflow_version="2",
    envelope_version=4,
)


def _lock(versions: dict[str, str], quad: RegistaVersionQuad | None = None) -> SuiteLock:
    return SuiteLock(
        release="1.0.0",
        regista_quad=quad or _QUAD,
        components={
            ident: ComponentPin(repo=f"YOUR-ORG/{ident}", version=ver)
            for ident, ver in versions.items()
        },
    )


class StubRunner:
    """Routes stubbed output by matching command prefixes."""

    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                return out
        return _completed(stdout="", returncode=1, stderr="unknown command")


class SequenceProbe:
    def __init__(self, records: list[RuntimeProvenance]) -> None:
        self.records = records
        self.calls = 0

    def __call__(self, component: object) -> RuntimeProvenance:
        index = min(self.calls, len(self.records) - 1)
        self.calls += 1
        return self.records[index]


def _pip_would_install(package: str, version: str) -> str:
    return f"Collecting {package}\n  Using cached {package}-{version}-py3-none-any.whl\nWould install {package}-{version}\n"


def _pip_already_satisfied(package: str, version: str) -> str:
    return f"Requirement already satisfied: {package}=={version}\n"


def _runtime(
    component: object,
    *,
    version: str = "0.4.0",
    mode: InstallMode = InstallMode.VENV,
) -> RuntimeProvenance:
    ident = getattr(component, "ident")
    package = getattr(component, "upgrade_package")
    return RuntimeProvenance(
        component=ident,
        distribution=package,
        version=version,
        cli_path=f"/venv/bin/{getattr(component, 'doctor_cmd')[0]}",
        interpreter="/venv/bin/python",
        mode=mode,
        source=ArtifactSource.UNRECORDED,
    )


# ---------------------------------------------------------------------------
# check_advancements (--check, read-only)
# ---------------------------------------------------------------------------


def test_check_reports_advancement_available() -> None:
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip"): _completed(
            stdout=_pip_would_install("regista-hraedon", "0.5.0"),
            stderr="",
        ),
    })
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    assert len(report.advancements) == 1
    a = report.advancements[0]
    assert a.status is AdvancementStatus.ADVANCEMENT_AVAILABLE
    assert a.target_version == "0.5.0"


def test_check_reports_up_to_date() -> None:
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip"): _completed(
            stdout="",
            stderr=_pip_already_satisfied("regista-hraedon", "0.4.0"),
        ),
    })
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.UP_TO_DATE


def test_check_reports_not_installed() -> None:
    report = check_advancements(
        component="regista",
        runner=StubRunner({}),
        installed=lambda _: False,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.NOT_INSTALLED


def test_check_reports_unreachable_on_pip_missing() -> None:
    def raise_fnf(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("pip")
    report = check_advancements(
        component="regista",
        runner=raise_fnf,  # type: ignore[arg-type]
        installed=lambda _: True,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    a = report.advancements[0]
    assert a.status is AdvancementStatus.UNREACHABLE


def test_check_unknown_component_returns_empty() -> None:
    report = check_advancements(
        component="nonexistent",
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert report.advancements == []
    assert "unknown component" in report.note


def test_check_all_components() -> None:
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip"): _completed(
            stdout=_pip_would_install("regista-hraedon", "0.5.0"),
            stderr="",
        ),
    })
    report = check_advancements(
        runner=runner,
        installed=lambda _: True,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    assert len(report.advancements) == len(COMPONENTS)


# ---------------------------------------------------------------------------
# run_upgrade --check
# ---------------------------------------------------------------------------


def test_upgrade_check_only_is_read_only() -> None:
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip"): _completed(
            stdout="Requirement already satisfied: regista-hraedon==0.4.0\n"
        ),
    })
    result = run_upgrade(
        check_only=True,
        runner=runner,
        installed=lambda _: True,
        provenance_probe=_runtime,
        components=COMPONENTS,
    )
    assert result.ok is True
    assert result.check_only is True
    # check_only discovers advancements (read-only pip calls) but does not write/upgrade
    assert all(s.status is not ApplyStatus.APPLIED for s in result.apply_steps)
    assert len(result.apply_steps) == 0  # no apply steps in check-only mode


# ---------------------------------------------------------------------------
# run_upgrade --dry-run
# ---------------------------------------------------------------------------


def test_upgrade_dry_run_does_not_act(tmp_path: Path) -> None:
    regista = component_by_ident("regista")
    lock = _lock({"regista": "0.4.0"})
    lock_text = serialize_lock(lock)
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(lock_text, encoding="utf-8")

    result = run_upgrade(
        dry_run=True,
        component="regista",
        runner=StubRunner({}),
        installed=lambda _: True,
        components=(regista,),
        lock_path=lock_path,
        provenance_probe=lambda comp: _runtime(comp, version="0.3.0"),
        provider_probe=lambda **_: None,
    )
    assert result.ok is True
    assert result.dry_run is True
    assert all(s.status is ApplyStatus.SKIPPED for s in result.apply_steps)


# ---------------------------------------------------------------------------
# run_upgrade — no lock
# ---------------------------------------------------------------------------


def test_upgrade_without_lock_fails(tmp_path: Path) -> None:
    result = run_upgrade(
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
        lock_path=tmp_path / "nonexistent.lock",
    )
    assert result.ok is False
    assert "no SUITE.lock" in result.detail


# ---------------------------------------------------------------------------
# run_upgrade — unknown component
# ---------------------------------------------------------------------------


def test_upgrade_unknown_component_fails() -> None:
    result = run_upgrade(
        component="nonexistent",
        runner=StubRunner({}),
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert "unknown component" in result.detail


def test_repair_uses_exact_owner_and_leaves_lock_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(_lock({"regista": "0.5.3"})), encoding="utf-8"
    )
    original = lock_path.read_bytes()
    before = _runtime(regista, version="0.5.1", mode=InstallMode.PIP_USER)
    before = RuntimeProvenance(**{**before.__dict__, "pep668": True})
    after = RuntimeProvenance(**{**before.__dict__, "version": "0.5.3"})
    probe = SequenceProbe([before, before, after])
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip", "install"): _completed(stdout="ok"),
    })
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=True,
            components=[],
            lock=LockDriftResult(matches=True, note="lock matches"),
        ),
    )

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=probe,
        provider_probe=lambda **_: None,
    )

    assert result.ok is True
    assert result.lock_written is False
    assert lock_path.read_bytes() == original
    install = next(call for call in runner.calls if "install" in call)
    assert install == (
        "/venv/bin/python",
        "-m",
        "pip",
        "install",
        "--user",
        "--break-system-packages",
        "--upgrade",
        "--no-deps",
        "regista-hraedon==0.5.3",
    )


def test_repair_refuses_editable_before_any_mutation(tmp_path: Path) -> None:
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(_lock({"regista": "0.5.3"})), encoding="utf-8"
    )
    runner = StubRunner({})

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=lambda comp: _runtime(
            comp, version="0.5.1", mode=InstallMode.EDITABLE
        ),
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "refused" in result.detail
    assert not any("install" in call for call in runner.calls)


def test_post_install_mismatch_rolls_back_captured_version(tmp_path: Path) -> None:
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(_lock({"regista": "0.5.3"})), encoding="utf-8"
    )
    before = _runtime(regista, version="0.5.1")
    wrong = RuntimeProvenance(**{**before.__dict__, "version": "9.9.9"})
    restored = RuntimeProvenance(**{**before.__dict__, "version": "0.5.1"})
    probe = SequenceProbe([before, before, wrong, wrong, restored])
    runner = StubRunner({
        ("/venv/bin/python", "-m", "pip", "install"): _completed(stdout="ok"),
    })

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=probe,
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert result.rollback_performed is True
    requirements = [
        call[-1]
        for call in runner.calls
        if "install" in call and "--dry-run" not in call
    ]
    assert requirements == ["regista-hraedon==0.5.3", "regista-hraedon==0.5.1"]


def test_advancement_refuses_unselected_component_drift(tmp_path: Path) -> None:
    regista = component_by_ident("regista")
    dossier = component_by_ident("dossier")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={
                    "regista": ComponentPin(regista.repo, "0.5.3"),
                    "dossier": ComponentPin(dossier.repo, "0.0.1"),
                },
            )
        ),
        encoding="utf-8",
    )

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=StubRunner({}),
        installed=lambda _: True,
        components=(regista, dossier),
        provenance_probe=lambda comp: _runtime(
            comp, version="0.5.3" if comp.ident == "regista" else "0.0.2"
        ),
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "dossier.version" in result.detail


def test_advancement_refuses_revision_only_drift(tmp_path: Path) -> None:
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={
                    "regista": ComponentPin(regista.repo, "0.5.3", "a" * 40),
                },
            )
        ),
        encoding="utf-8",
    )
    record = RuntimeProvenance(
        **{**_runtime(regista, version="0.5.3").__dict__, "revision": "b" * 40}
    )

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=StubRunner({}),
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=lambda _: record,
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "regista.revision" in result.detail


def test_service_execstart_must_match_visible_cli_before_repair(tmp_path: Path) -> None:
    dossier = component_by_ident("dossier")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={"dossier": ComponentPin(dossier.repo, "0.0.2")},
            )
        ),
        encoding="utf-8",
    )
    runner = StubRunner({
        ("systemctl", "show"): _completed(
            stdout="/venv/bin/dossier-wrapper /venv/bin/dossier serve\n"
        ),
    })

    result = run_upgrade(
        component="dossier",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(dossier,),
        provenance_probe=lambda comp: _runtime(comp, version="0.0.1"),
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "ExecStart" in result.detail
    assert not any("install" in call for call in runner.calls)


def test_final_lock_write_failure_rolls_back_advancement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={"regista": ComponentPin(regista.repo, "0.5.3")},
            )
        ),
        encoding="utf-8",
    )
    original = lock_path.read_bytes()
    before = _runtime(regista, version="0.5.3")
    advanced = RuntimeProvenance(**{**before.__dict__, "version": "0.5.4"})
    probe = SequenceProbe([before, before, advanced, advanced, before])

    class AdvancementRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            if "--dry-run" in command:
                return _completed(
                    stdout=_pip_would_install("regista-hraedon", "0.5.4")
                )
            if "install" in command:
                return _completed(stdout="ok")
            return _completed(returncode=1)

    runner = AdvancementRunner()
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=True,
            components=[],
            lock=LockDriftResult(matches=True, note="lock matches"),
        ),
    )
    real_write = lock_mod.write_lock_file

    def fail_final_write(lock: SuiteLock, path: Path = lock_path) -> None:
        if path == lock_path:
            raise OSError("simulated final write failure")
        real_write(lock, path)

    monkeypatch.setattr(lock_mod, "write_lock_file", fail_final_write)

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=probe,
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert result.rollback_performed is True
    assert "final lock write failed" in result.detail
    assert lock_path.read_bytes() == original
    requirements = [
        call[-1]
        for call in runner.calls
        if "install" in call and "--dry-run" not in call
    ]
    assert requirements == ["regista-hraedon==0.5.4", "regista-hraedon==0.5.3"]


@pytest.mark.parametrize(
    ("mode", "manager", "expected"),
    [
        (
            InstallMode.PIPX,
            "/opt/pipx",
            ("/opt/pipx", "install", "--force", "regista-hraedon==0.5.3"),
        ),
        (
            InstallMode.UV_TOOL,
            "/opt/uv",
            (
                "/opt/uv",
                "tool",
                "install",
                "--force",
                "regista-hraedon==0.5.3",
            ),
        ),
    ],
)
def test_managed_tool_commands_use_fingerprinted_manager(
    mode: InstallMode,
    manager: str,
    expected: tuple[str, ...],
) -> None:
    regista = component_by_ident("regista")
    record = RuntimeProvenance(
        **{
            **_runtime(regista, version="0.5.1", mode=mode).__dict__,
            "manager": manager,
        }
    )
    assert _mutation_command(record, "regista-hraedon==0.5.3") == expected


# ---------------------------------------------------------------------------
# run_rollback — migration boundary refusal
# ---------------------------------------------------------------------------


def test_rollback_refuses_schema_migration_boundary(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.3.0"}, quad=RegistaVersionQuad(
        library_version="0.3.0", schema_version=37,
        canonical_workflow_version="2", envelope_version=4,
    ))
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
        ("regista", "version"): _completed(stdout=json.dumps({
            "library_version": "0.4.0", "schema_version": 38,
            "canonical_workflow_version": "2", "envelope_version": 4,
        })),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.REFUSED_MIGRATION_BOUNDARY
    assert "schema migration boundary" in result.detail
    assert result.current_schema_version == 38
    assert result.target_schema_version == 37


def test_rollback_succeeds_when_schema_matches(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.4.0"}, quad=_QUAD)
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
        ("regista", "version"): _completed(stdout=json.dumps({
            "library_version": "0.4.0", "schema_version": 38,
            "canonical_workflow_version": "2", "envelope_version": 4,
        })),
        ("/venv/bin/python", "-m", "pip"): _completed(stdout="installed"),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
        provenance_probe=_runtime,
    )
    assert result.ok is True
    assert result.status is RollbackStatus.APPLIED
    assert lock_path.exists()


def test_rollback_fails_when_git_ref_missing(tmp_path: Path) -> None:
    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(returncode=1, stderr="bad revision"),
    })

    result = run_rollback(
        to_ref="bad-ref",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.FAILED
    assert "no SUITE.lock" in result.detail


def test_rollback_refuses_when_current_schema_unknown(tmp_path: Path) -> None:
    target_lock = _lock({"regista": "0.4.0"}, quad=_QUAD)
    git_output = serialize_lock(target_lock)

    lock_path = tmp_path / "SUITE.lock"
    runner = StubRunner({
        ("git", "show"): _completed(stdout=git_output),
    })

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: False,  # regista not installed
        components=COMPONENTS,
    )
    assert result.ok is False
    assert result.status is RollbackStatus.FAILED
    assert "cannot determine current schema" in result.detail


def test_historical_rollback_preflights_all_targets_before_mutation(
    tmp_path: Path,
) -> None:
    regista = component_by_ident("regista")
    dossier = component_by_ident("dossier")
    target = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={
            "regista": ComponentPin(regista.repo, "0.5.1"),
            "dossier": ComponentPin(dossier.repo, "0.0.1"),
        },
    )
    runner = StubRunner({("git", "show"): _completed(stdout=serialize_lock(target))})

    result = run_rollback(
        to_ref="HEAD~1",
        lock_path=tmp_path / "SUITE.lock",
        runner=runner,
        installed=lambda _: False,
        components=(regista, dossier),
        provenance_probe=lambda comp: _runtime(
            comp,
            version="0.5.2" if comp.ident == "regista" else "0.0.2",
            mode=(
                InstallMode.VENV
                if comp.ident == "regista"
                else InstallMode.EDITABLE
            ),
        ),
    )

    assert result.ok is False
    assert "refused" in result.detail
    assert not any("install" in call for call in runner.calls)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_advancement_text() -> None:
    report = AdvancementReport(
        advancements=[
            ComponentAdvancement(
                component="regista",
                current_version="0.4.0",
                target_version="0.5.0",
                status=AdvancementStatus.ADVANCEMENT_AVAILABLE,
                detail="0.4.0 -> 0.5.0",
            ),
        ],
        note="1 advancement(s) available: regista",
    )
    text = format_advancement_text(report)
    assert "regista" in text
    assert "0.5.0" in text


def test_format_upgrade_text_dry_run() -> None:
    result = UpgradeResult(ok=True, dry_run=True, check_only=False, component_filter=None)
    text = format_upgrade_text(result)
    assert "dry-run" in text
    assert "OK" in text


def test_format_rollback_text_refused() -> None:
    result = RollbackResult(
        ok=False,
        status=RollbackStatus.REFUSED_MIGRATION_BOUNDARY,
        target_ref="HEAD~1",
        current_schema_version=38,
        target_schema_version=37,
        detail="refused: schema migration boundary",
    )
    text = format_rollback_text(result)
    assert "refused" in text
    assert "38" in text
    assert "37" in text
