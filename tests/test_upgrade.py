"""Unit tests for the upgrade module — advancement check, apply, rollback, interop gate.

All tests use stubbed runners and installed checks — no live infra (AGENTS.md:
"Ordering/idempotency unit-tested with stubbed component CLIs (no live infra
in CI)").
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_suite import doctor as doctor_mod
from agent_suite import lock as lock_mod
from agent_suite.components import (
    COMPONENTS,
    Component,
    Tier,
    UpgradeKind,
    component_by_ident,
)
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
    _check_command,
    _mutation_command,
    _mutation_requirement,
    _rollback_all,
    _rollback_one,
    check_advancements,
    format_advancement_text,
    format_rollback_text,
    format_upgrade_text,
    run_rollback,
    run_upgrade,
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
    return (
        f"Collecting {package}\n"
        f"  Using cached {package}-{version}-py3-none-any.whl\n"
        f"Would install {package}-{version}\n"
    )


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


def _pipx_kind_component(
    ident: str = "pipxtool",
    package: str = "pipxtool",
) -> Component:
    """A component declared with the legacy ``UpgradeKind.PIPX`` descriptor.

    No shipped suite component uses this kind (all six are ``UpgradeKind.PYTHON``);
    the fixture exists to prove the closed dispatch is topology-aware and
    exact-version on the apply and rollback paths too, rather than a bare
    ``pipx upgrade``/``pipx install`` trap that diverges from the read-only check
    (WI-025 follow-up).
    """
    return Component(
        ident=ident,
        repo=f"YOUR-ORG/{ident}",
        tier=Tier.PLUMBING,
        doctor_cmd=(ident, "doctor", "--json"),
        upgrade_kind=UpgradeKind.PIPX,
        upgrade_package=package,
        distribution_names=(package,),
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
# Fixture-driven topology matrix — check/apply symmetry per InstallMode
# ---------------------------------------------------------------------------
#
# WI-025: the advancement *check* and the *apply* mutation must be driven by one
# shared decision — the same detected interpreter/manager and the same actual
# ``record.distribution``. These fixtures pin the exact command shape for every
# supported and unsupported topology so a refactor that silently routes check
# through a different owner (e.g. a global ``pip``) or a different distribution
# name fails loudly instead of producing a misleading "advancement available".


@dataclass(frozen=True)
class _Topology:
    """One installed-runtime shape a component CLI can be reached through."""

    label: str
    mode: InstallMode
    interpreter: str | None
    manager: str | None
    distribution: str | None
    pep668: bool = False

    def record(self, component: object) -> RuntimeProvenance:
        ident = getattr(component, "ident")
        return RuntimeProvenance(
            component=ident,
            distribution=self.distribution,
            version="0.5.1",
            cli_path=f"/bin/{getattr(component, 'doctor_cmd')[0]}",
            interpreter=self.interpreter,
            mode=self.mode,
            source=ArtifactSource.UNRECORDED,
            manager=self.manager,
            pep668=self.pep668,
        )


# The canonical suite distribution name is ``regista-hraedon``; the fork case
# proves check/apply follow the *installed* distribution, not the descriptor.
_DIST = "regista-hraedon"
_FORK = "regista-hraedon-fork"

_SUPPORTED_TOPOLOGIES: tuple[_Topology, ...] = (
    _Topology(
        label="pip_user_pep668",
        mode=InstallMode.PIP_USER,
        interpreter="/usr/bin/python3",
        manager=None,
        distribution=_DIST,
        pep668=True,
    ),
    _Topology(
        label="venv",
        mode=InstallMode.VENV,
        interpreter="/venv/bin/python",
        manager=None,
        distribution=_DIST,
    ),
    _Topology(
        label="pipx",
        mode=InstallMode.PIPX,
        interpreter="/home/u/.local/pipx/venvs/regista/bin/python",
        manager="/usr/local/bin/pipx",
        distribution=_DIST,
    ),
    _Topology(
        label="uv_tool_dogfood",
        mode=InstallMode.UV_TOOL,
        interpreter="/home/u/.local/share/uv/tools/regista-hraedon/bin/python",
        manager="/home/u/.local/bin/uv",
        distribution=_DIST,
    ),
    _Topology(
        label="venv_forked_distribution",
        mode=InstallMode.VENV,
        interpreter="/venv/bin/python",
        manager=None,
        distribution=_FORK,
    ),
)

_UNSUPPORTED_TOPOLOGIES: tuple[_Topology, ...] = (
    _Topology(
        label="editable",
        mode=InstallMode.EDITABLE,
        interpreter="/projects/regista/.venv/bin/python",
        manager=None,
        distribution=_DIST,
    ),
    _Topology(
        label="system",
        mode=InstallMode.SYSTEM,
        interpreter="/usr/bin/python3",
        manager=None,
        distribution=_DIST,
    ),
    _Topology(
        label="absent",
        mode=InstallMode.ABSENT,
        interpreter=None,
        manager=None,
        distribution=None,
    ),
    _Topology(
        label="unknown",
        mode=InstallMode.UNKNOWN,
        interpreter=None,
        manager=None,
        distribution=None,
    ),
)


def _owner(command: tuple[str, ...]) -> str:
    """The interpreter or manager binary a command is rooted at."""
    return command[0]


@pytest.mark.parametrize(
    "topology", _SUPPORTED_TOPOLOGIES, ids=lambda t: t.label
)
def test_supported_topology_check_and_apply_share_owner_and_distribution(
    topology: _Topology,
) -> None:
    """For every supported mode, check and apply target the same owner + dist."""
    regista = component_by_ident("regista")
    record = topology.record(regista)
    distribution = _mutation_requirement(record, regista)
    assert distribution == (topology.distribution or regista.upgrade_package)

    check = _check_command(record, distribution)
    apply = _mutation_command(record, f"{distribution}==0.5.3")
    assert check is not None, f"{topology.label}: check must not refuse a supported mode"
    assert apply is not None, f"{topology.label}: apply must not refuse a supported mode"

    # Both commands are rooted at an owner detected on *this* runtime — the
    # interpreter or the manager from the same provenance record — never a bare
    # global tool name. A pipx check legitimately reads via the tool venv's own
    # interpreter while the apply drives the pipx manager; both are facets of the
    # one detected installation, which is what "same owner" guarantees.
    owner_set = {topology.interpreter, topology.manager} - {None}
    assert _owner(check) in owner_set, (
        f"{topology.label}: check rooted at {_owner(check)}, not a detected owner"
    )
    assert _owner(apply) in owner_set, (
        f"{topology.label}: apply rooted at {_owner(apply)}, not a detected owner"
    )
    assert _owner(check) not in {"pip", "pip3", "pipx", "uv"}
    assert _owner(apply) not in {"pip", "pip3", "pipx", "uv"}

    # The exact installed distribution appears on both sides — never the
    # canonical descriptor name when the installed name differs.
    assert any(distribution == arg for arg in check), (
        f"{topology.label}: check does not target installed distribution {distribution}"
    )
    assert apply[-1] == f"{distribution}==0.5.3"
    # Check is strictly read-only.
    assert "--dry-run" in check


@pytest.mark.parametrize(
    "topology", _UNSUPPORTED_TOPOLOGIES, ids=lambda t: t.label
)
def test_unsupported_topology_refuses_explicitly(topology: _Topology) -> None:
    """Unsupported modes yield no command on either side (a named refusal)."""
    regista = component_by_ident("regista")
    record = topology.record(regista)
    distribution = _mutation_requirement(record, regista)
    assert _check_command(record, distribution) is None
    assert _mutation_command(record, f"{distribution}==0.5.3") is None


@pytest.mark.parametrize(
    "topology", _SUPPORTED_TOPOLOGIES, ids=lambda t: t.label
)
def test_check_advancement_targets_installed_distribution(
    topology: _Topology,
) -> None:
    """``check_advancements`` resolves the latest version of the installed dist.

    The stub only answers the exact command the detected owner would run, so a
    check that accidentally fell back to a global ``pip`` (or probed the
    canonical descriptor name) would miss the stub and report an error.
    """
    regista = component_by_ident("regista")
    record = topology.record(regista)
    distribution = _mutation_requirement(record, regista)
    check = _check_command(record, distribution)
    assert check is not None

    runner = StubRunner({
        check[:4]: _completed(stdout=_pip_would_install(distribution, "0.5.3")),
    })
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        provenance_probe=lambda _: record,
        components=(regista,),
    )
    advancement = report.advancements[0]
    assert advancement.status is AdvancementStatus.ADVANCEMENT_AVAILABLE
    assert advancement.target_version == "0.5.3"
    # The probe ran against the detected owner, never a bare global ``pip``.
    assert runner.calls, "expected the probe to shell out to the detected owner"
    assert runner.calls[0][0] != "pip", "check must not fall back to global pip"
    assert _owner(runner.calls[0]) == _owner(check)


@pytest.mark.parametrize(
    "topology", _UNSUPPORTED_TOPOLOGIES, ids=lambda t: t.label
)
def test_check_advancement_names_refusal_for_unsupported_mode(
    topology: _Topology,
) -> None:
    """``check_advancements`` reports a named refusal, not a bogus target."""
    regista = component_by_ident("regista")
    record = topology.record(regista)
    runner = StubRunner({})
    report = check_advancements(
        component="regista",
        runner=runner,
        installed=lambda _: True,
        provenance_probe=lambda _: record,
        components=(regista,),
    )
    advancement = report.advancements[0]
    if topology.mode is InstallMode.ABSENT:
        assert advancement.status is AdvancementStatus.NOT_INSTALLED
    else:
        assert advancement.status is AdvancementStatus.ERROR
        assert "refused" in advancement.detail
    assert advancement.target_version is None
    # No mutation was attempted.
    assert not any("install" in call for call in runner.calls)


def test_uv_tool_dogfood_check_and_apply_exact_commands() -> None:
    """The dogfood uv-tool shape: ``uv pip`` probe, ``uv tool install`` apply."""
    uv = "/home/u/.local/bin/uv"
    tool_python = "/home/u/.local/share/uv/tools/regista-hraedon/bin/python"
    record = RuntimeProvenance(
        component="regista",
        distribution=_DIST,
        version="0.5.1",
        cli_path="/home/u/.local/bin/regista",
        interpreter=tool_python,
        mode=InstallMode.UV_TOOL,
        source=ArtifactSource.UNRECORDED,
        manager=uv,
    )
    assert _check_command(record, _DIST) == (
        uv, "pip", "install", "--python", tool_python,
        "--dry-run", "--upgrade", "--no-deps", _DIST,
    )
    assert _mutation_command(record, f"{_DIST}==0.5.3") == (
        uv, "tool", "install", "--force", f"{_DIST}==0.5.3",
    )


def test_pipx_check_uses_venv_pip_apply_uses_pipx_manager() -> None:
    """pipx: the probe reads the tool venv via its own pip; apply drives pipx."""
    pipx = "/usr/local/bin/pipx"
    venv_python = "/home/u/.local/pipx/venvs/regista/bin/python"
    record = RuntimeProvenance(
        component="regista",
        distribution=_DIST,
        version="0.5.1",
        cli_path="/home/u/.local/bin/regista",
        interpreter=venv_python,
        mode=InstallMode.PIPX,
        source=ArtifactSource.UNRECORDED,
        manager=pipx,
    )
    assert _check_command(record, _DIST) == (
        venv_python, "-m", "pip", "install",
        "--dry-run", "--upgrade", "--no-deps", _DIST,
    )
    assert _mutation_command(record, f"{_DIST}==0.5.3") == (
        pipx, "install", "--force", f"{_DIST}==0.5.3",
    )


def test_repair_refuses_system_install_before_any_mutation(tmp_path: Path) -> None:
    """A SYSTEM install (e.g. distro-managed) is refused, never mutated."""
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
        provenance_probe=lambda comp: RuntimeProvenance(
            component=comp.ident,
            distribution=_DIST,
            version="0.5.1",
            cli_path="/usr/bin/regista",
            interpreter="/usr/bin/python3",
            mode=InstallMode.SYSTEM,
            source=ArtifactSource.UNRECORDED,
        ),
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "refused" in result.detail
    assert "system" in result.detail
    assert not any("install" in call for call in runner.calls)


def test_check_then_apply_use_identical_owner_and_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: the owner+distribution the check probes is what apply mutates.

    A single stub answers only the detected owner's exact command prefix; if the
    apply step routed through a different interpreter/manager or a different
    distribution name than the check, the stub would miss and the upgrade would
    fail. A green result therefore proves check and apply stayed on one owner.
    """
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={"regista": ComponentPin(regista.repo, "0.5.1")},
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        doctor_mod,
        "aggregate",
        lambda **kw: doctor_mod.SuiteReport(
            suite_ok=True,
            components=[],
            lock=LockDriftResult(matches=True, note="lock matches"),
        ),
    )
    interpreter = "/opt/suite/bin/python"
    before = RuntimeProvenance(
        component="regista",
        distribution=_DIST,
        version="0.5.1",
        cli_path="/opt/suite/bin/regista",
        interpreter=interpreter,
        mode=InstallMode.VENV,
        source=ArtifactSource.UNRECORDED,
    )
    advanced = RuntimeProvenance(**{**before.__dict__, "version": "0.5.3"})
    probe = SequenceProbe([before, before, advanced, advanced])

    class OwnerRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            # Only the detected owner is answered; anything else (a global pip,
            # a different interpreter) is an unknown command -> failure.
            if command[0] != interpreter:
                return _completed(returncode=1, stderr="unexpected owner")
            if "--dry-run" in command:
                return _completed(stdout=_pip_would_install(_DIST, "0.5.3"))
            if "install" in command:
                return _completed(stdout="ok")
            return _completed(returncode=1)

    runner = OwnerRunner()
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
    install_calls = [c for c in runner.calls if "install" in c and "--dry-run" not in c]
    assert install_calls == [
        (interpreter, "-m", "pip", "install", "--upgrade", "--no-deps", f"{_DIST}==0.5.3")
    ]
    # Every package-manager call (check or apply) was rooted at the detected
    # owner — never a bare global pip/pipx/uv. Component version probes such as
    # ``regista version`` are not package-manager calls and are allowed.
    package_managers = {"pip", "pip3", "pipx", "uv"}
    assert all(c[0] not in package_managers for c in runner.calls)
    pip_calls = [c for c in runner.calls if "pip" in c]
    assert pip_calls and all(c[0] == interpreter for c in pip_calls)


def _provider(adapter_version: str) -> lock_mod.ProviderExtension:
    return lock_mod.ProviderExtension(
        provider_name="hindsight",
        adapter_version=adapter_version,
        protocol_version="1.0",
        deployment_mode="remote",
        support_level="supported",
        config_digest=None,
    )


def test_advancement_reprobes_provider_extension_into_candidate_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An advancement re-probes the memory-provider extension post-upgrade.

    ``agent-notes`` is itself upgradeable and is the source of the provider pin,
    so an advancement can change the reported adapter version. The candidate
    lock must carry the *post-upgrade* provider extension (which the interop
    gate then verifies); carrying the stale pre-upgrade value would make the
    gate report spurious provider drift and roll back a legitimate advancement.
    """
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    pre_provider = _provider("1.0")
    current_lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(regista.repo, "0.5.3")},
        provider_extension=pre_provider,
    )
    lock_path.write_text(serialize_lock(current_lock), encoding="utf-8")

    before = _runtime(regista, version="0.5.3")
    advanced = RuntimeProvenance(**{**before.__dict__, "version": "0.5.4"})
    probe = SequenceProbe([before, before, advanced, advanced])

    # Pre-upgrade probe matches the lock (no estate drift); post-upgrade probe
    # reflects the advanced agent-notes adapter version.
    provider_sequence = iter([pre_provider, _provider("2.0")])

    def sequenced_provider_probe(**_: object) -> lock_mod.ProviderExtension:
        return next(provider_sequence)

    class AdvancementRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            if "--dry-run" in command:
                return _completed(stdout=_pip_would_install("regista-hraedon", "0.5.4"))
            if "install" in command:
                return _completed(stdout="ok")
            return _completed(returncode=1)

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
        runner=AdvancementRunner(),
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=probe,
        provider_probe=sequenced_provider_probe,
    )

    assert result.ok is True
    assert result.lock_written is True
    written = lock_mod.load_lock_file(lock_path)
    assert written is not None
    assert written.provider_extension is not None
    assert written.provider_extension.adapter_version == "2.0"


def test_advancement_provider_reprobe_failure_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed post-upgrade provider re-probe aborts and rolls back."""
    regista = component_by_ident("regista")
    lock_path = tmp_path / "SUITE.lock"
    pre_provider = _provider("1.0")
    current_lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"regista": ComponentPin(regista.repo, "0.5.3")},
        provider_extension=pre_provider,
    )
    lock_path.write_text(serialize_lock(current_lock), encoding="utf-8")
    original = lock_path.read_bytes()

    before = _runtime(regista, version="0.5.3")
    advanced = RuntimeProvenance(**{**before.__dict__, "version": "0.5.4"})
    restored = RuntimeProvenance(**{**before.__dict__, "version": "0.5.3"})
    # pre-drift probe, pre-apply, post-install verify, rollback preflight, rollback verify
    probe = SequenceProbe([before, before, advanced, advanced, restored])

    calls = {"n": 0}

    def flaky_provider_probe(**_: object) -> lock_mod.ProviderExtension:
        calls["n"] += 1
        if calls["n"] == 1:
            return pre_provider  # pre-upgrade estate drift probe
        raise RuntimeError("agent-notes memory-provider describe failed")

    class AdvancementRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            if "--dry-run" in command:
                return _completed(stdout=_pip_would_install("regista-hraedon", "0.5.4"))
            if "install" in command:
                return _completed(stdout="ok")
            return _completed(returncode=1)

    result = run_upgrade(
        component="regista",
        lock_path=lock_path,
        runner=AdvancementRunner(),
        installed=lambda _: True,
        components=(regista,),
        provenance_probe=probe,
        provider_probe=flaky_provider_probe,
    )

    assert result.ok is False
    assert "memory-provider probe failed" in result.detail
    assert result.rollback_performed is True
    # The lock was never advanced.
    assert lock_path.read_bytes() == original


# ---------------------------------------------------------------------------
# UpgradeKind.PIPX dispatch — apply / rollback / refusal are topology-aware
# ---------------------------------------------------------------------------
#
# No shipped component uses UpgradeKind.PIPX, but the closed dispatch must still
# be safe: apply and rollback go through the same detected-runtime, exact-version
# machinery as UpgradeKind.PYTHON (never a bare ``pipx upgrade``/``pipx install``
# that ignores the detected manager/interpreter and the installed distribution),
# and the refusal preflights cover this kind too.

_PIPX_MGR = "/usr/local/bin/pipx"
_PIPX_VENV_PY = "/home/u/.local/pipx/venvs/pipxtool/bin/python"
_PIPX_DIST = "pipxtool-real"  # installed distribution != upgrade_package "pipxtool"


def _pipx_mode_record(comp: Component, version: str) -> RuntimeProvenance:
    return RuntimeProvenance(
        component=comp.ident,
        distribution=_PIPX_DIST,
        version=version,
        cli_path="/home/u/.local/bin/pipxtool",
        interpreter=_PIPX_VENV_PY,
        mode=InstallMode.PIPX,
        source=ArtifactSource.UNRECORDED,
        manager=_PIPX_MGR,
    )


def test_pipx_kind_apply_is_topology_aware_and_exact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A PIPX-kind advancement installs ``record.distribution==target`` via the
    detected pipx manager — never a bare ``pipx upgrade <upgrade_package>``."""
    comp = _pipx_kind_component()
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={comp.ident: ComponentPin(comp.repo, "0.5.1")},
            )
        ),
        encoding="utf-8",
    )
    before = _pipx_mode_record(comp, "0.5.1")
    advanced = RuntimeProvenance(**{**before.__dict__, "version": "0.5.3"})
    probe = SequenceProbe([before, before, advanced, advanced])

    class PipxRunner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            self.calls.append(command)
            # The read-only check reads the tool venv via its own pip.
            if command[:3] == (_PIPX_VENV_PY, "-m", "pip"):
                return _completed(stdout=_pip_would_install(_PIPX_DIST, "0.5.3"))
            # The apply drives the detected pipx manager, exact-version.
            if command[:2] == (_PIPX_MGR, "install"):
                return _completed(stdout="ok")
            return _completed(returncode=1, stderr="unexpected command")

    runner = PipxRunner()
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
        component=comp.ident,
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(comp,),
        provenance_probe=probe,
        provider_probe=lambda **_: None,
    )

    assert result.ok is True
    install_calls = [c for c in runner.calls if c[:2] == (_PIPX_MGR, "install")]
    assert install_calls == [(_PIPX_MGR, "install", "--force", f"{_PIPX_DIST}==0.5.3")]
    # The legacy non-exact, non-topology-aware trap must never appear.
    assert all("upgrade" not in c for c in runner.calls)
    # No bare global pip / pipx anywhere.
    assert all(c[0] not in {"pip", "pip3", "pipx"} for c in runner.calls)


def test_pipx_kind_repair_uses_detected_manager_and_distribution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A drifted PIPX-kind runtime is repaired exactly to the lock via the
    detected manager, targeting the installed distribution."""
    comp = _pipx_kind_component()
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={comp.ident: ComponentPin(comp.repo, "0.5.3")},
            )
        ),
        encoding="utf-8",
    )
    before = _pipx_mode_record(comp, "0.5.1")
    after = RuntimeProvenance(**{**before.__dict__, "version": "0.5.3"})
    probe = SequenceProbe([before, before, after])
    runner = StubRunner({
        (_PIPX_MGR, "install"): _completed(stdout="ok"),
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
        component=comp.ident,
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(comp,),
        provenance_probe=probe,
        provider_probe=lambda **_: None,
    )

    assert result.ok is True
    assert result.lock_written is False  # repair never rewrites the lock
    install = next(c for c in runner.calls if "install" in c)
    assert install == (_PIPX_MGR, "install", "--force", f"{_PIPX_DIST}==0.5.3")


def test_pipx_kind_rollback_one_is_topology_aware_and_exact() -> None:
    """``_rollback_one`` for a PIPX-kind component pins the installed
    distribution at the exact target via the detected manager."""
    comp = _pipx_kind_component()
    record = _pipx_mode_record(comp, "0.5.3")
    runner = StubRunner({(_PIPX_MGR, "install"): _completed(stdout="ok")})

    step = _rollback_one(comp, "0.5.0", runner=runner, provenance=record)

    assert step.status is ApplyStatus.ROLLED_BACK
    assert runner.calls == [(_PIPX_MGR, "install", "--force", f"{_PIPX_DIST}==0.5.0")]


def test_pipx_kind_rollback_one_requires_provenance() -> None:
    comp = _pipx_kind_component()
    step = _rollback_one(comp, "0.5.0", runner=StubRunner({}), provenance=None)
    assert step.status is ApplyStatus.FAILED
    assert "provenance is required" in step.detail


def test_pipx_kind_rollback_all_refuses_unsupported_mode_before_mutation() -> None:
    """``_rollback_all`` preflight now covers the PIPX kind: an unsupported
    detected mode is refused before any mutation, like the PYTHON kind."""
    comp = _pipx_kind_component()
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={comp.ident: ComponentPin(comp.repo, "0.5.0")},
    )
    editable = RuntimeProvenance(
        component=comp.ident,
        distribution=_PIPX_DIST,
        version="0.5.3",
        cli_path="/projects/pipxtool/.venv/bin/pipxtool",
        interpreter="/projects/pipxtool/.venv/bin/python",
        mode=InstallMode.EDITABLE,
        source=ArtifactSource.EDITABLE,
    )
    runner = StubRunner({})

    steps = _rollback_all(
        lock, runner=runner, components=(comp,), provenance_probe=lambda _: editable
    )

    assert any(s.status is ApplyStatus.FAILED for s in steps)
    assert "refused" in steps[0].detail
    assert not any("install" in c for c in runner.calls)


def test_pipx_kind_rollback_all_restores_exact_version_via_manager() -> None:
    """A healthy PIPX-kind rollback restores the pinned version through the
    detected manager and verifies it."""
    comp = _pipx_kind_component()
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={comp.ident: ComponentPin(comp.repo, "0.5.0")},
    )
    before = _pipx_mode_record(comp, "0.5.3")
    rolled = RuntimeProvenance(**{**before.__dict__, "version": "0.5.0"})
    # preflight, fingerprint revalidation, post-rollback verification
    probe = SequenceProbe([before, before, rolled])
    runner = StubRunner({(_PIPX_MGR, "install"): _completed(stdout="ok")})

    steps = _rollback_all(
        lock, runner=runner, components=(comp,), provenance_probe=probe
    )

    assert all(s.status is not ApplyStatus.FAILED for s in steps)
    rolled_back = [s for s in steps if s.status is ApplyStatus.ROLLED_BACK]
    assert len(rolled_back) == 1
    assert rolled_back[0].to_version == "0.5.0"
    assert (_PIPX_MGR, "install", "--force", f"{_PIPX_DIST}==0.5.0") in runner.calls


def test_run_upgrade_refuses_pipx_kind_unsupported_mode_before_mutation(
    tmp_path: Path,
) -> None:
    """The run_upgrade refusal preflight covers the PIPX kind: a SYSTEM-installed
    PIPX-kind component is refused before any mutation."""
    comp = _pipx_kind_component()
    lock_path = tmp_path / "SUITE.lock"
    lock_path.write_text(
        serialize_lock(
            SuiteLock(
                release="1.0.0",
                regista_quad=None,
                components={comp.ident: ComponentPin(comp.repo, "0.5.3")},
            )
        ),
        encoding="utf-8",
    )
    runner = StubRunner({})

    result = run_upgrade(
        component=comp.ident,
        lock_path=lock_path,
        runner=runner,
        installed=lambda _: True,
        components=(comp,),
        provenance_probe=lambda c: RuntimeProvenance(
            component=c.ident,
            distribution=_PIPX_DIST,
            version="0.5.1",
            cli_path="/usr/bin/pipxtool",
            interpreter="/usr/bin/python3",
            mode=InstallMode.SYSTEM,
            source=ArtifactSource.UNRECORDED,
        ),
        provider_probe=lambda **_: None,
    )

    assert result.ok is False
    assert "refused" in result.detail
    assert "system" in result.detail
    assert not any("install" in c for c in runner.calls)


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
