from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from agent_suite.components import COMPONENTS
from agent_suite.lock import (
    ComponentPin,
    DriftEntry,
    DriftKind,
    LockDriftResult,
    RegistaVersionQuad,
    SuiteLock,
    check_drift,
    deserialize_lock,
    format_drift_text,
    generate_lock,
    load_lock_file,
    read_regista_quad,
    serialize_lock,
    write_lock_file,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


_QUAD = RegistaVersionQuad(
    library_version="0.4.0",
    schema_version=38,
    canonical_workflow_version="2",
    envelope_version=4,
)


def _quad(**overrides: object) -> RegistaVersionQuad:
    defaults: dict[str, object] = {
        "library_version": "0.4.0",
        "schema_version": 38,
        "canonical_workflow_version": "2",
        "envelope_version": 4,
    }
    defaults.update(overrides)
    return RegistaVersionQuad(**defaults)  # type: ignore[arg-type]


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


def _version_json(
    library: str = "0.4.0",
    schema: int = 38,
    workflow: str = "2",
    envelope: int = 4,
) -> str:
    return json.dumps(
        {
            "component": "regista",
            "library_version": library,
            "schema_version": schema,
            "canonical_workflow_version": workflow,
            "envelope_version": envelope,
            "canonical_workflow_hash": "abc123",
            "available_signing_schemes": ["ed25519"],
        }
    )


class StubVersionRunner:
    """Returns canned `regista version --json` output (or raises)."""

    def __init__(self, output: subprocess.CompletedProcess[str] | Exception) -> None:
        self._output = output

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if isinstance(self._output, Exception):
            raise self._output
        return self._output


def _all_versions(version: str = "1.0.0") -> dict[str, str | None]:
    return {c.ident: version for c in COMPONENTS}


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


def test_round_trip_with_quad() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            "regista": ComponentPin(repo="hraedon/regista", version="0.4.0"),
            "dossier": ComponentPin(repo="hraedon/dossier", version="0.1.0"),
        },
    )
    text = serialize_lock(lock)
    restored = deserialize_lock(text)
    assert restored.release == "1.0.0"
    assert restored.regista_quad == _QUAD
    assert restored.components["regista"].repo == "hraedon/regista"
    assert restored.components["regista"].version == "0.4.0"
    assert restored.components["dossier"].version == "0.1.0"


def test_round_trip_without_quad() -> None:
    lock = SuiteLock(
        release="0.0.1",
        regista_quad=None,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.4.0")},
    )
    text = serialize_lock(lock)
    restored = deserialize_lock(text)
    assert restored.regista_quad is None
    assert len(restored.components) == 1


def test_round_trip_all_components() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            c.ident: ComponentPin(repo=c.repo, version="2.0.0") for c in COMPONENTS
        },
    )
    restored = deserialize_lock(serialize_lock(lock))
    assert len(restored.components) == len(COMPONENTS)
    for c in COMPONENTS:
        assert restored.components[c.ident].repo == c.repo


def test_serialize_is_tomllib_parseable() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.4.0")},
    )
    text = serialize_lock(lock)
    import tomllib

    data = tomllib.loads(text)
    assert data["suite"]["release"] == "1.0.0"
    assert data["suite"]["regista_schema_version"] == 38
    assert data["components"]["regista"]["version"] == "0.4.0"


def test_deserialize_rejects_missing_suite() -> None:
    with pytest.raises(ValueError, match="missing \\[suite\\]"):
        deserialize_lock("[components]\nregista = {repo='x', version='1'}\n")


def test_deserialize_rejects_non_string_version() -> None:
    text = "[suite]\nrelease='1.0'\n\n[components.regista]\nrepo='r'\nversion=42\n"
    with pytest.raises(ValueError, match="string repo and version"):
        deserialize_lock(text)


def test_deserialize_rejects_incomplete_quad() -> None:
    text = "[suite]\nrelease='1.0'\nregista_library_version='0.4'\n"
    with pytest.raises(ValueError, match="incomplete regista quad"):
        deserialize_lock(text)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def test_file_round_trip(tmp_path: Path) -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.4.0")},
    )
    path = tmp_path / "SUITE.lock"
    write_lock_file(lock, path)
    loaded = load_lock_file(path)
    assert loaded is not None
    assert loaded == lock


def test_load_missing_file_returns_none(tmp_path: Path) -> None:
    assert load_lock_file(tmp_path / "nonexistent.lock") is None


# ---------------------------------------------------------------------------
# read_regista_quad — the quad is read from regista, not hardcoded
# ---------------------------------------------------------------------------


def test_read_quad_parses_regista_version_json() -> None:
    runner = StubVersionRunner(_completed(stdout=_version_json()))
    quad = read_regista_quad(
        runner=runner, installed=lambda _cli: True
    )
    assert quad is not None
    assert quad.library_version == "0.4.0"
    assert quad.schema_version == 38
    assert quad.canonical_workflow_version == "2"
    assert quad.envelope_version == 4


def test_read_quad_returns_none_when_regista_absent() -> None:
    quad = read_regista_quad(
        runner=StubVersionRunner(_completed(stdout="")),
        installed=lambda _cli: False,
    )
    assert quad is None


def test_read_quad_returns_none_on_nonzero_exit() -> None:
    quad = read_regista_quad(
        runner=StubVersionRunner(_completed(returncode=1, stderr="boom")),
        installed=lambda _cli: True,
    )
    assert quad is None


def test_read_quad_returns_none_on_bad_json() -> None:
    quad = read_regista_quad(
        runner=StubVersionRunner(_completed(stdout="not json")),
        installed=lambda _cli: True,
    )
    assert quad is None


def test_read_quad_returns_none_on_missing_field() -> None:
    bad = json.dumps({"component": "regista", "library_version": "0.4"})
    quad = read_regista_quad(
        runner=StubVersionRunner(_completed(stdout=bad)),
        installed=lambda _cli: True,
    )
    assert quad is None


def test_read_quad_returns_none_on_oserror() -> None:
    quad = read_regista_quad(
        runner=StubVersionRunner(OSError("boom")),
        installed=lambda _cli: True,
    )
    assert quad is None


def test_read_quad_coerces_string_integers() -> None:
    """regista may emit schema_version as a JSON int; we coerce defensively."""
    runner = StubVersionRunner(
        _completed(
            stdout=json.dumps(
                {
                    "library_version": "0.4.0",
                    "schema_version": 38,
                    "canonical_workflow_version": "2",
                    "envelope_version": 4,
                }
            )
        )
    )
    quad = read_regista_quad(runner=runner, installed=lambda _cli: True)
    assert quad is not None
    assert isinstance(quad.schema_version, int)
    assert isinstance(quad.envelope_version, int)


# ---------------------------------------------------------------------------
# generate_lock
# ---------------------------------------------------------------------------


def test_generate_lock_reads_quad_from_regista() -> None:
    runner = StubVersionRunner(_completed(stdout=_version_json()))
    lock = generate_lock(
        component_versions=_all_versions("1.0.0"),
        runner=runner,
        installed=lambda _cli: True,
    )
    assert lock.regista_quad is not None
    assert lock.regista_quad.library_version == "0.4.0"
    assert lock.regista_quad.schema_version == 38


def test_generate_lock_without_regista() -> None:
    lock = generate_lock(
        component_versions=_all_versions("1.0.0"),
        runner=StubVersionRunner(_completed(stdout="")),
        installed=lambda _cli: False,
    )
    assert lock.regista_quad is None
    assert len(lock.components) == len(COMPONENTS)


def test_generate_lock_skips_absent_components() -> None:
    versions = _all_versions("1.0.0")
    versions["agent-wake"] = None
    lock = generate_lock(
        component_versions=versions,
        runner=StubVersionRunner(_completed(stdout=_version_json())),
        installed=lambda _cli: True,
    )
    assert "agent-wake" not in lock.components
    assert "regista" in lock.components


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def _lock_with(versions: dict[str, str], quad: RegistaVersionQuad | None = None) -> SuiteLock:
    return SuiteLock(
        release="1.0.0",
        regista_quad=quad or _QUAD,
        components={
            ident: ComponentPin(repo=f"hraedon/{ident}", version=ver)
            for ident, ver in versions.items()
        },
    )


def test_no_lock_returns_none_matches() -> None:
    result = check_drift(
        None,
        current_quad=_QUAD,
        component_versions=_all_versions("1.0.0"),
    )
    assert result.matches is None
    assert result.drift == []
    assert "no SUITE.lock" in result.note


def test_matching_lock_no_drift() -> None:
    versions = _all_versions("1.0.0")
    lock = _lock_with(versions)
    result = check_drift(lock, current_quad=_QUAD, component_versions=versions)
    assert result.matches is True
    assert result.drift == []


def test_version_mismatch_is_named_drift() -> None:
    locked = _all_versions("1.0.0")
    current = dict(locked)
    current["dossier"] = "2.0.0"
    lock = _lock_with(locked)
    result = check_drift(lock, current_quad=_QUAD, component_versions=current)
    assert result.matches is False
    assert len(result.drift) == 1
    d = result.drift[0]
    assert d.kind is DriftKind.VERSION_MISMATCH
    assert d.component == "dossier"
    assert d.locked == "1.0.0"
    assert d.current == "2.0.0"


def test_quad_mismatch_is_named_drift() -> None:
    lock = _lock_with(_all_versions("1.0.0"), quad=_QUAD)
    current = _quad(schema_version=99)
    result = check_drift(lock, current_quad=current, component_versions=_all_versions("1.0.0"))
    assert result.matches is False
    quad_drifts = [d for d in result.drift if d.kind is DriftKind.QUAD_MISMATCH]
    assert len(quad_drifts) == 1
    assert quad_drifts[0].field == "schema_version"
    assert quad_drifts[0].locked == "38"
    assert quad_drifts[0].current == "99"


def test_multiple_quad_fields_drift() -> None:
    lock = _lock_with(_all_versions("1.0.0"), quad=_QUAD)
    current = _quad(schema_version=99, envelope_version=5, library_version="0.5.0")
    result = check_drift(lock, current_quad=current, component_versions=_all_versions("1.0.0"))
    quad_drifts = [d for d in result.drift if d.kind is DriftKind.QUAD_MISMATCH]
    assert len(quad_drifts) == 3


def test_component_missing_from_lock_is_unexpected() -> None:
    locked = _all_versions("1.0.0")
    del locked["agent-wake"]
    lock = _lock_with(locked)
    result = check_drift(
        lock, current_quad=_QUAD, component_versions=_all_versions("1.0.0")
    )
    assert result.matches is False
    unexpected = [d for d in result.drift if d.kind is DriftKind.UNEXPECTED_COMPONENT]
    assert len(unexpected) == 1
    assert unexpected[0].component == "agent-wake"


def test_component_in_lock_but_absent_is_missing() -> None:
    locked = _all_versions("1.0.0")
    lock = _lock_with(locked)
    current = dict(locked)
    current["dossier"] = None
    result = check_drift(lock, current_quad=_QUAD, component_versions=current)
    assert result.matches is False
    missing = [d for d in result.drift if d.kind is DriftKind.COMPONENT_MISSING]
    assert len(missing) == 1
    assert missing[0].component == "dossier"
    assert missing[0].current == "absent"


def test_regista_quad_missing_when_locked() -> None:
    lock = _lock_with(_all_versions("1.0.0"), quad=_QUAD)
    result = check_drift(
        lock, current_quad=None, component_versions=_all_versions("1.0.0")
    )
    assert result.matches is False
    missing = [d for d in result.drift if d.kind is DriftKind.COMPONENT_MISSING]
    assert any(d.component == "regista" and d.field == "version_quad" for d in missing)


def test_lock_without_quad_and_regista_still_absent_is_not_drift() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="hraedon/dossier", version="1.0.0")},
    )
    result = check_drift(
        lock,
        current_quad=None,
        component_versions={"dossier": "1.0.0", "regista": None},
    )
    assert result.matches is True
    assert result.drift == []


# ---------------------------------------------------------------------------
# format_drift_text
# ---------------------------------------------------------------------------


def test_format_no_lock() -> None:
    text = format_drift_text(LockDriftResult(matches=None, note="no file"))
    assert "no file" in text


def test_format_matching() -> None:
    text = format_drift_text(LockDriftResult(matches=True, note="ok"))
    assert "ok" in text


def test_format_drift_lists_entries() -> None:
    result = LockDriftResult(
        matches=False,
        note="1 drift(s)",
        drift=[
            DriftEntry(
                kind=DriftKind.VERSION_MISMATCH,
                component="dossier",
                field="version",
                locked="1.0.0",
                current="2.0.0",
            ),
            DriftEntry(
                kind=DriftKind.QUAD_MISMATCH,
                component="regista",
                field="schema_version",
                locked="38",
                current="99",
            ),
        ],
    )
    text = format_drift_text(result)
    assert "DRIFT" in text
    assert "dossier" in text
    assert "schema_version" in text


@pytest.mark.parametrize("kind", list(DriftKind))
def test_drift_kind_format_is_total(kind: DriftKind) -> None:
    """Every DriftKind must be handled in format_drift_text without assert_never."""
    entry = DriftEntry(
        kind=kind, component="x", field="version", locked="1", current="2"
    )
    result = LockDriftResult(matches=False, note="test", drift=[entry])
    text = format_drift_text(result)
    assert isinstance(text, str)
