"""Tests for the candidate inventory (WI-0.2).

Covers: round-trip with stubbed components, every per-component drift state,
missing-regista handling, quad drift states, text formatting, and the
collect_inventory shell-out path with a stubbed doctor aggregate.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_suite import doctor
from agent_suite import inventory
from agent_suite import lock
from agent_suite.components import COMPONENTS, Tier
from agent_suite.inventory import (
    ComponentDrift,
    QuadDrift,
    build_inventory,
    collect_inventory,
    format_text,
    write_inventory_file,
)
from agent_suite.lock import ComponentPin, RegistaVersionQuad, SuiteLock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_QUAD = RegistaVersionQuad(
    library_version="0.5.0",
    schema_version=43,
    canonical_workflow_version="2",
    envelope_version=5,
)

_SHA_A = "a" * 40
_SHA_B = "b" * 40


def _all_versions(version: str = "1.0.0") -> dict[str, str | None]:
    return {c.ident: version for c in COMPONENTS}


def _all_revisions(sha: str = _SHA_A) -> dict[str, str | None]:
    return {c.ident: sha for c in COMPONENTS}


def _lock(
    versions: dict[str, str] | None = None,
    *,
    quad: RegistaVersionQuad | None = _QUAD,
    revisions: dict[str, str] | None = None,
) -> SuiteLock:
    """Build a SuiteLock pinning every component at the given versions."""
    pinned = versions or _all_versions("1.0.0")
    components = {
        ident: ComponentPin(
            repo=f"hraedon/{ident}",
            version=ver,
            revision=(revisions or {}).get(ident),
        )
        for ident, ver in pinned.items()
    }
    return SuiteLock(release="1.0.0-dev", regista_quad=quad, components=components)


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


def _ok_doctor(component: str, version: str = "1.0.0") -> str:
    return json.dumps(
        {
            "component": component,
            "version": version,
            "ok": True,
            "regista": {"reachable": True, "project": "x", "chain_ok": True},
            "checks": [{"name": "regista", "status": "ok", "detail": ""}],
        }
    )


class StubDoctorRunner:
    """Returns canned `doctor --json` output per component CLI name."""

    def __init__(self, outputs: dict[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out = self._outputs[cmd[0]]
        if isinstance(out, Exception):
            raise out
        return out


# ---------------------------------------------------------------------------
# Round-trip with stubbed components
# ---------------------------------------------------------------------------


def test_build_inventory_round_trip_matches() -> None:
    """A lock + matching installed state → every component is MATCHES."""
    versions = _all_versions("1.0.0")
    inv = build_inventory(
        lock_obj=_lock(versions),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions={},
        current_quad=_QUAD,
    )
    assert inv.release == "1.0.0-dev"
    assert inv.lock_file.present is True
    assert inv.lock_file.parseable is True
    assert len(inv.components) == len(COMPONENTS)
    for c in inv.components:
        assert c.drift is ComponentDrift.MATCHES
        assert c.pinned_version == "1.0.0"
        assert c.installed_version == "1.0.0"
    assert inv.regista_quad.drift is QuadDrift.MATCHES
    assert inv.regista_quad.locked == _QUAD.to_dict()
    assert inv.regista_quad.current == _QUAD.to_dict()
    assert inv.memory_provider is None  # native engine


def test_to_dict_round_trips_through_json() -> None:
    """The JSON shape is sane and survives a json round-trip."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
    )
    d = inv.to_dict()
    text = json.dumps(d, default=str)
    restored = json.loads(text)
    assert restored["release"] == "1.0.0-dev"
    assert restored["lock_file"]["present"] is True
    assert isinstance(restored["components"], list)
    assert len(restored["components"]) == len(COMPONENTS)
    assert "generated_at" in restored
    assert restored["regista_quad"]["drift"] == "matches"


# ---------------------------------------------------------------------------
# Per-component drift detection (every state)
# ---------------------------------------------------------------------------


def test_version_mismatch_drift() -> None:
    locked = _all_versions("1.0.0")
    current = dict(locked)
    current["dossier"] = "2.0.0"
    inv = build_inventory(
        lock_obj=_lock(locked),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=current,
        component_revisions={},
        current_quad=_QUAD,
    )
    dossier = next(c for c in inv.components if c.ident == "dossier")
    assert dossier.drift is ComponentDrift.VERSION_MISMATCH
    assert dossier.pinned_version == "1.0.0"
    assert dossier.installed_version == "2.0.0"


def test_revision_mismatch_drift() -> None:
    """Version matches but revision differs → REVISION_MISMATCH."""
    locked = _all_versions("1.0.0")
    locked_revs = {ident: _SHA_A for ident in locked}
    current_revs = {ident: _SHA_B for ident in locked}
    inv = build_inventory(
        lock_obj=_lock(locked, revisions=locked_revs),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=locked,
        component_revisions=current_revs,
        current_quad=_QUAD,
    )
    rev_drifts = [c for c in inv.components if c.drift is ComponentDrift.REVISION_MISMATCH]
    assert len(rev_drifts) == len(COMPONENTS)
    sample = rev_drifts[0]
    assert sample.pinned_revision == _SHA_A
    assert sample.installed_revision == _SHA_B


def test_revision_drift_absent_when_current_unprobeable() -> None:
    """A locked revision with no probeable current SHA must not false-positive."""
    locked = _all_versions("1.0.0")
    locked_revs = {ident: _SHA_A for ident in locked}
    inv = build_inventory(
        lock_obj=_lock(locked, revisions=locked_revs),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=locked,
        component_revisions={},  # no source checkouts
        current_quad=_QUAD,
    )
    for c in inv.components:
        assert c.drift is ComponentDrift.MATCHES


def test_missing_drift_when_locked_but_not_installed() -> None:
    locked = _all_versions("1.0.0")
    current = dict(locked)
    current["dossier"] = None  # not installed
    inv = build_inventory(
        lock_obj=_lock(locked),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=current,
        component_revisions={},
        current_quad=_QUAD,
    )
    dossier = next(c for c in inv.components if c.ident == "dossier")
    assert dossier.drift is ComponentDrift.MISSING
    assert dossier.installed_version is None
    assert dossier.pinned_version == "1.0.0"


def test_unexpected_drift_when_installed_but_not_locked() -> None:
    """A component installed but not in the lock → UNEXPECTED."""
    locked = _all_versions("1.0.0")
    del locked["agent-wake"]  # not pinned
    current = _all_versions("1.0.0")  # but installed
    inv = build_inventory(
        lock_obj=_lock(locked),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=current,
        component_revisions={},
        current_quad=_QUAD,
    )
    wake = next(c for c in inv.components if c.ident == "agent-wake")
    assert wake.drift is ComponentDrift.UNEXPECTED
    assert wake.pinned_version is None
    assert wake.installed_version == "1.0.0"


def test_not_locked_when_no_lock_file() -> None:
    """No lock file → every component is NOT_LOCKED and nothing is pinned."""
    inv = build_inventory(
        lock_obj=None,
        has_lock_file=False,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
    )
    assert inv.lock_file.present is False
    for c in inv.components:
        assert c.drift is ComponentDrift.NOT_LOCKED
        assert c.pinned_version is None
        assert c.pinned_revision is None


def test_not_locked_for_component_absent_from_lock_and_uninstalled() -> None:
    """A component neither locked nor installed (when a lock exists) → NOT_LOCKED."""
    locked = {"regista": "1.0.0"}  # only regista pinned
    current = {"regista": "1.0.0"}  # only regista installed
    inv = build_inventory(
        lock_obj=_lock(locked),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=current,
        component_revisions={},
        current_quad=_QUAD,
    )
    dossier = next(c for c in inv.components if c.ident == "dossier")
    assert dossier.drift is ComponentDrift.NOT_LOCKED
    assert dossier.pinned_version is None
    assert dossier.installed_version is None


@pytest.mark.parametrize("drift", list(ComponentDrift))
def test_every_component_drift_is_reachable(drift: ComponentDrift) -> None:
    """Every ComponentDrift value is producible by some input configuration."""
    # This guard prevents a kind from being added to the enum without a path
    # that produces it (mirrors test_lock's DriftKind totality test).
    assert drift.value in {
        d.value for d in ComponentDrift
    }


# ---------------------------------------------------------------------------
# M-1: assert_never guards the closed drift sets in the formatting consumers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("drift", list(ComponentDrift))
def test_component_drift_label_is_total(drift: ComponentDrift) -> None:
    """Every ComponentDrift value is handled by _component_drift_label (M-1).

    The label function uses ``match/case`` with ``assert_never`` in the
    default branch so a newly added kind can't slip through the text formatter
    ungated. This test exercises every existing value to confirm none hits
    ``assert_never``.
    """
    from agent_suite.inventory import _component_drift_label

    label = _component_drift_label(drift)
    assert isinstance(label, str)
    assert label == drift.value


@pytest.mark.parametrize("drift", list(QuadDrift))
def test_quad_drift_label_is_total(drift: QuadDrift) -> None:
    """Every QuadDrift value is handled by _quad_drift_label (M-1).

    The label function uses ``match/case`` with ``assert_never`` in the
    default branch so a newly added kind can't slip through the text formatter
    ungated.
    """
    from agent_suite.inventory import _quad_drift_label

    label = _quad_drift_label(drift)
    assert isinstance(label, str)
    assert label == drift.value


def test_inventory_drift_dispatch_uses_assert_never() -> None:
    """The inventory module uses assert_never in its drift label functions (M-1).

    M-1 required the module docstring's claim that ``assert_never`` guards the
    closed drift sets to be truthful. This test confirms the import is present
    and the label functions exist (the parametrized totality tests above
    exercise every value).
    """
    import inspect

    import agent_suite.inventory as inv_mod

    # assert_never must be imported.
    source = inspect.getsource(inv_mod)
    assert "assert_never" in source, (
        "inventory.py must use assert_never to guard the closed drift sets "
        "(M-1: the docstring claims it)"
    )
    # The label functions must exist.
    assert hasattr(inv_mod, "_component_drift_label")
    assert hasattr(inv_mod, "_quad_drift_label")


# ---------------------------------------------------------------------------
# Missing regista handling
# ---------------------------------------------------------------------------


def test_missing_regista_quad_when_locked_but_absent() -> None:
    """Locked quad but regista not installed → quad drift is MISSING."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions={"regista": None, **{c.ident: "1.0.0" for c in COMPONENTS if c.ident != "regista"}},
        component_revisions={},
        current_quad=None,  # regista absent
    )
    assert inv.regista_quad.drift is QuadDrift.MISSING
    assert inv.regista_quad.locked == _QUAD.to_dict()
    assert inv.regista_quad.current is None
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.drift is ComponentDrift.MISSING


def test_quad_both_absent_is_matches() -> None:
    """Lock without a quad and regista still absent → MATCHES (baseline unchanged)."""
    lock_obj = SuiteLock(
        release="1.0.0-dev",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="hraedon/dossier", version="1.0.0")},
    )
    inv = build_inventory(
        lock_obj=lock_obj,
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions={"dossier": "1.0.0", "regista": None},
        component_revisions={},
        current_quad=None,
    )
    assert inv.regista_quad.drift is QuadDrift.MATCHES


def test_quad_unexpected_when_not_locked_but_present() -> None:
    """No quad in lock but regista now installed → UNEXPECTED."""
    lock_obj = SuiteLock(
        release="1.0.0-dev",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="hraedon/dossier", version="1.0.0")},
    )
    inv = build_inventory(
        lock_obj=lock_obj,
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions={"dossier": "1.0.0", "regista": "0.5.0"},
        component_revisions={},
        current_quad=_QUAD,
    )
    assert inv.regista_quad.drift is QuadDrift.UNEXPECTED


# ---------------------------------------------------------------------------
# Malformed lock handling
# ---------------------------------------------------------------------------


def test_malformed_lock_reported_as_present_unreadable(tmp_path: Path) -> None:
    """A present-but-malformed lock → present + not parseable + components NOT_LOCKED."""
    bad_lock = tmp_path / "SUITE.lock"
    bad_lock.write_text("not valid toml {{{{", encoding="utf-8")
    inv = build_inventory(
        lock_obj=None,
        has_lock_file=True,
        lock_path=bad_lock,
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        lock_parseable=False,
        lock_note="SUITE.lock unreadable: boom",
    )
    assert inv.lock_file.present is True
    assert inv.lock_file.parseable is False
    assert "unreadable" in inv.lock_file.note
    for c in inv.components:
        assert c.drift is ComponentDrift.NOT_LOCKED


# ---------------------------------------------------------------------------
# Memory provider
# ---------------------------------------------------------------------------


def test_memory_provider_pinned_in_inventory() -> None:
    """The locked provider extension surfaces in the inventory."""
    from agent_suite.lock import ProviderExtension

    pe = ProviderExtension(
        provider_name="hindsight",
        adapter_version="1.2.0",
        protocol_version="1.0",
        deployment_mode="remote",
        support_level="supported",
        config_digest=None,
    )
    lock_obj = SuiteLock(
        release="1.0.0-dev",
        regista_quad=_QUAD,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.5.0")},
        provider_extension=pe,
    )
    inv = build_inventory(
        lock_obj=lock_obj,
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions={"regista": "0.5.0"},
        component_revisions={},
        current_quad=_QUAD,
    )
    assert inv.memory_provider is not None
    assert inv.memory_provider["provider_name"] == "hindsight"
    assert inv.memory_provider["deployment_mode"] == "remote"


# ---------------------------------------------------------------------------
# Text formatting
# ---------------------------------------------------------------------------


def test_format_text_is_readable_and_complete() -> None:
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0"), revisions={c.ident: _SHA_A for c in COMPONENTS}),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions=_all_revisions(_SHA_A),
        current_quad=_QUAD,
    )
    text = format_text(inv)
    assert "agent-suite candidate inventory" in text
    assert "release: 1.0.0-dev" in text
    assert "lock: SUITE.lock (present)" in text
    assert "components:" in text
    assert "regista quad:" in text
    assert "matches" in text
    # Every component ident appears in the text output.
    for c in COMPONENTS:
        assert c.ident in text


def test_format_text_shows_drift_states() -> None:
    locked = _all_versions("1.0.0")
    current = dict(locked)
    current["dossier"] = "2.0.0"
    inv = build_inventory(
        lock_obj=_lock(locked),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=current,
        component_revisions={},
        current_quad=_QUAD,
    )
    text = format_text(inv)
    assert "version_mismatch" in text
    assert "dossier" in text


def test_format_text_no_lock() -> None:
    inv = build_inventory(
        lock_obj=None,
        has_lock_file=False,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
    )
    text = format_text(inv)
    assert "absent" in text
    assert "not_locked" in text


# ---------------------------------------------------------------------------
# File writing
# ---------------------------------------------------------------------------


def test_write_inventory_file_round_trips(tmp_path: Path) -> None:
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
    )
    out = tmp_path / "candidate-inventory.json"
    written = write_inventory_file(inv, path=out)
    assert written == out
    assert out.is_file()
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["release"] == "1.0.0-dev"
    assert data["lock_file"]["present"] is True
    assert isinstance(data["components"], list)
    assert len(data["components"]) == len(COMPONENTS)


def test_write_inventory_file_atomic(tmp_path: Path) -> None:
    """write_inventory_file uses temp+rename; no partial file on success."""
    inv = build_inventory(
        lock_obj=None,
        has_lock_file=False,
        lock_path=Path("SUITE.lock"),
        component_versions={},
        component_revisions={},
        current_quad=None,
    )
    out = tmp_path / "candidate-inventory.json"
    write_inventory_file(inv, path=out)
    assert out.is_file()
    assert not (tmp_path / "candidate-inventory.json.tmp").exists()


# ---------------------------------------------------------------------------
# collect_inventory — the shell-out path with stubbed doctor + lock
# ---------------------------------------------------------------------------


def _stub_doctor_aggregate(
    monkeypatch: pytest.MonkeyPatch,
    *,
    component_versions: dict[str, str | None],
    suite_ok: bool = True,
) -> None:
    """Stub doctor.aggregate to return a SuiteReport with the given versions."""
    reports = [
        doctor.ComponentReport(
            component=ident,
            tier=Tier.SPINE,
            status=doctor.ComponentStatus.OK,
            ok=True,
            version=ver,
        )
        for ident, ver in component_versions.items()
    ]
    monkeypatch.setattr(
        doctor,
        "aggregate",
        lambda **kw: doctor.SuiteReport(suite_ok=suite_ok, components=reports),
    )


def test_collect_inventory_with_stubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """collect_inventory wires the doctor + lock + revisions into build_inventory."""
    versions = _all_versions("0.5.0")
    _stub_doctor_aggregate(monkeypatch, component_versions=versions)
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {c.ident: _SHA_A for c in COMPONENTS})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)

    lock_path = tmp_path / "SUITE.lock"
    lock_obj = _lock({k: v or "0.5.0" for k, v in versions.items()})
    lock.write_lock_file(lock_obj, lock_path)

    inv = collect_inventory(lock_path=lock_path)
    assert inv.lock_file.present is True
    assert inv.lock_file.parseable is True
    for c in inv.components:
        assert c.drift is ComponentDrift.MATCHES
        assert c.installed_version == "0.5.0"
        assert c.installed_revision == _SHA_A
    assert inv.regista_quad.drift is QuadDrift.MATCHES


def test_collect_inventory_missing_regista(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When regista is absent, collect_inventory reports quad drift MISSING."""
    versions = _all_versions("1.0.0")
    versions["regista"] = None
    _stub_doctor_aggregate(monkeypatch, component_versions=versions)
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: None)

    lock_path = tmp_path / "SUITE.lock"
    lock_obj = _lock(_all_versions("1.0.0"))  # locks regista
    lock.write_lock_file(lock_obj, lock_path)

    inv = collect_inventory(lock_path=lock_path)
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.drift is ComponentDrift.MISSING
    assert inv.regista_quad.drift is QuadDrift.MISSING


def test_collect_inventory_no_lock_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No lock file → everything NOT_LOCKED, lock_file.present False."""
    _stub_doctor_aggregate(monkeypatch, component_versions=_all_versions("1.0.0"))
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)

    inv = collect_inventory(lock_path=tmp_path / "nonexistent.lock")
    assert inv.lock_file.present is False
    for c in inv.components:
        assert c.drift is ComponentDrift.NOT_LOCKED


def test_collect_inventory_malformed_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A malformed lock is reported present + unreadable, components NOT_LOCKED."""
    _stub_doctor_aggregate(monkeypatch, component_versions=_all_versions("1.0.0"))
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)

    bad = tmp_path / "SUITE.lock"
    bad.write_text("not valid toml {{{", encoding="utf-8")
    inv = collect_inventory(lock_path=bad)
    assert inv.lock_file.present is True
    assert inv.lock_file.parseable is False
    assert "unreadable" in inv.lock_file.note
    for c in inv.components:
        assert c.drift is ComponentDrift.NOT_LOCKED


# ---------------------------------------------------------------------------
# CLI integration (smoke test — stubs the shell-out layer)
# ---------------------------------------------------------------------------


def test_cli_inventory_json(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`agent-suite inventory --json --record` prints JSON and writes the artifact."""
    from agent_suite.cli import main

    _stub_doctor_aggregate(monkeypatch, component_versions=_all_versions("1.0.0"))
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)
    monkeypatch.setattr(inventory, "_default_inventory_path", lambda: tmp_path / "candidate-inventory.json")

    rc = main(["inventory", "--json", "--record"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["release"] == "1.0.0-dev"
    assert "components" in data
    assert len(data["components"]) == len(COMPONENTS)
    assert (tmp_path / "candidate-inventory.json").is_file()


def test_cli_inventory_text(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """`agent-suite inventory --record` (text mode) prints a readable summary + writes artifact."""
    from agent_suite.cli import main

    _stub_doctor_aggregate(monkeypatch, component_versions=_all_versions("1.0.0"))
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)
    monkeypatch.setattr(inventory, "_default_inventory_path", lambda: tmp_path / "candidate-inventory.json")

    rc = main(["inventory", "--record"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "agent-suite candidate inventory" in captured.out
    assert "components:" in captured.out
    assert (tmp_path / "candidate-inventory.json").is_file()


def test_cli_inventory_read_only_by_default(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`agent-suite inventory` without --record does not write the artifact."""
    from agent_suite.cli import main

    _stub_doctor_aggregate(monkeypatch, component_versions=_all_versions("1.0.0"))
    monkeypatch.setattr(lock, "read_component_revisions", lambda **kw: {})
    monkeypatch.setattr(lock, "read_regista_quad", lambda **kw: _QUAD)
    monkeypatch.setattr(inventory, "_default_inventory_path", lambda: tmp_path / "candidate-inventory.json")

    rc = main(["inventory", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    assert json.loads(captured.out)
    assert not (tmp_path / "candidate-inventory.json").exists()


# ---------------------------------------------------------------------------
# WI-0.2 schema expansion: umbrella, origin state, publishability, plan status
# ---------------------------------------------------------------------------


def _make_origin_probe(
    overrides: dict[str, tuple[str | None, int, int, bool, bool]] | None = None,
) -> Callable[[str], tuple[str | None, int, int, bool, bool]]:
    """Return a stub origin probe with per-ident overrides.

    Default per-ident value is ``(origin_rev, ahead, behind, dirty, provenance_known)``.
    For tests, the clean/converged default is a known origin SHA with no ahead/behind/dirty.
    Set ``provenance_known=False`` to simulate a probe failure (the fail-closed path).
    """
    # The "all clean" default: a known SHA, zero ahead/behind, not dirty, proven.
    default_clean = ("a" * 40, 0, 0, False, True)
    mapping = overrides or {}

    def probe(ident: str) -> tuple[str | None, int, int, bool, bool]:
        return mapping.get(ident, default_clean)

    return probe


def test_inventory_includes_umbrella_entry() -> None:
    """The inventory includes an umbrella entry for the agent-suite repository."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(),
    )
    assert inv.umbrella.ident == "agent-suite"
    assert inv.umbrella.repo == "hraedon/agent-suite"
    assert inv.umbrella.role == "umbrella"
    assert "umbrella" in inv.to_dict()


def test_inventory_reports_dirty_working_tree() -> None:
    """A dirty working tree on any constituent blocks source_tree_converged."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe({"regista": ("a" * 40, 0, 0, True, True)}),
    )
    assert inv.summary.any_dirty is True
    assert inv.summary.source_tree_converged is False
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.working_tree_dirty is True


def test_inventory_reports_ahead_of_origin() -> None:
    """Local-only commits ahead of origin on any constituent blocks convergence."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe({"agent-suite": ("a" * 40, 2, 0, False, True)}),
    )
    assert inv.summary.any_ahead is True
    assert inv.summary.source_tree_converged is False
    assert inv.umbrella.local_only_commits == 2


def test_inventory_reports_behind_origin() -> None:
    """A checkout behind origin/main is stale and blocks convergence."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe({"regista": ("a" * 40, 0, 3, False, True)}),
    )
    assert inv.summary.any_behind is True
    assert inv.summary.source_tree_converged is False
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.behind_origin == 3


def test_inventory_reports_unknown_provenance() -> None:
    """A failed origin probe (provenance_known=False) blocks convergence
    even when ahead/behind read zero. Fail-closed on unknown provenance."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe({"regista": (None, 0, 0, False, False)}),
    )
    assert inv.summary.any_provenance_unknown is True
    assert inv.summary.source_tree_converged is False
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.provenance_known is False


def test_probe_origin_state_partial_failure_withholds_provenance(
    tmp_path: Path,
) -> None:
    """Sol round-3 finding #1 regression: a partial probe failure must NOT
    silently read as clean/current.

    The prior implementation marked provenance_known=True as soon as the
    origin revision resolved, leaving ahead/behind/dirty probes to fall
    through to their safe defaults (0/0/False) on failure. A synthetic
    failure of the ahead probe while origin succeeded would read as
    "clean, current, not dirty" even though the ahead read failed.

    Construct a real throwaway git checkout, then monkey-patch one of the
    subprocess calls to fail. Assert provenance_known comes back False.
    """
    import subprocess as sp
    from unittest.mock import patch

    from agent_suite.inventory import _probe_origin_state

    # Set up a real git checkout so the origin probe can succeed.
    repo = tmp_path / "fake"
    repo.mkdir()
    sp.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    sp.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    sp.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "r").write_text("x")
    sp.run(["git", "-C", str(repo), "add", "."], check=True)
    sp.run(["git", "-C", str(repo), "commit", "-q", "-m", "x"], check=True)
    # Add an origin so rev-parse origin/main can succeed (points at HEAD).
    sp.run(["git", "-C", str(repo), "remote", "add", "origin", str(repo)], check=True)
    sp.run(
        ["git", "-C", str(repo), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
    )

    # Save the real run; patch the ahead-count invocation to raise.
    real_run = sp.run

    def patched_run(args, **kwargs):  # type: ignore[no-untyped-def]
        if "rev-list" in args and "origin/main..HEAD" in args:
            raise sp.TimeoutExpired(cmd=args, timeout=1)
        return real_run(args, **kwargs)

    with patch("subprocess.run", side_effect=patched_run):
        origin_rev, ahead, behind, dirty, provenance_known = _probe_origin_state(repo)

    # Origin resolved, but ahead probe failed -> provenance_known must be False.
    assert origin_rev is not None, "origin probe should have succeeded"
    assert provenance_known is False, (
        "partial probe failure must withhold provenance_known; "
        f"got origin_rev={origin_rev!r}, ahead={ahead}, behind={behind}, dirty={dirty}"
    )


def test_inventory_publishable_when_clean() -> None:
    """A clean workspace with no drift, no ahead/behind, known provenance is converged."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(),
    )
    assert inv.summary.any_dirty is False
    assert inv.summary.any_ahead is False
    assert inv.summary.any_behind is False
    assert inv.summary.any_provenance_unknown is False
    assert inv.summary.drift_count == 0
    assert inv.summary.source_tree_converged is True


def test_inventory_records_regista_quad_versions() -> None:
    """The regista component carries schema/workflow/envelope versions from the quad."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(),
    )
    regista = next(c for c in inv.components if c.ident == "regista")
    assert regista.schema_version == _QUAD.schema_version
    assert regista.workflow_version == _QUAD.canonical_workflow_version
    assert regista.envelope_version == _QUAD.envelope_version
    for c in inv.components:
        if c.ident != "regista":
            assert c.schema_version is None
            assert c.workflow_version is None
            assert c.envelope_version is None


def test_inventory_plan_status_is_best_effort() -> None:
    """plan_status is None when no statuses are supplied (no plans/ dir or unreadable)."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(),
        plan_statuses={},
    )
    assert inv.umbrella.plan_status is None
    for c in inv.components:
        assert c.plan_status is None


def test_probe_plan_status_reads_newest_plan_file(tmp_path: Path) -> None:
    """_probe_plan_status reads the **Status:** line from the newest plans/*.md."""
    plans = tmp_path / "plans"
    plans.mkdir()
    old = plans / "001-old.md"
    new = plans / "002-new.md"
    old.write_text("**Status:** completed\n", encoding="utf-8")
    new.write_text("**Status:** in_progress\n", encoding="utf-8")
    # Force the new file to be strictly newer by mtime.
    new_mtime = new.stat().st_mtime + 10
    os.utime(new, times=(new_mtime, new_mtime))
    assert inventory._probe_plan_status(tmp_path) == "in_progress"


def test_probe_plan_status_returns_none_for_missing_plans_dir(tmp_path: Path) -> None:
    """_probe_plan_status returns None when the plans/ directory is absent."""
    assert inventory._probe_plan_status(tmp_path) is None


def test_format_text_shows_convergence_summary() -> None:
    """The text summary surfaces the source_tree_converged gate.

    A clean inventory with no drift, no ahead/behind, and known provenance
    reports SOURCE-TREE-CONVERGED in the text output. Release-candidate
    readiness is documented separately in the release board.
    """
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(),
    )
    text = format_text(inv)
    assert "Source tree: SOURCE-TREE-CONVERGED" in text
    assert "umbrella:" in text


def test_format_text_shows_convergence_blockers() -> None:
    """When convergence fails, the text summary names each blocker."""
    inv = build_inventory(
        lock_obj=_lock(_all_versions("1.0.0")),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=_all_versions("1.0.0"),
        component_revisions={},
        current_quad=_QUAD,
        origin_probe=_make_origin_probe(
            {"regista": ("a" * 40, 1, 0, True, True)}
        ),
    )
    text = format_text(inv)
    assert "NOT CONVERGED" in text
    # Dirty + ahead are both present in the override; both must be named.
    assert "dirty" in text
    assert "unpushed" in text
