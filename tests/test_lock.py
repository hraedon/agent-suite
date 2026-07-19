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
            "regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0"),
            "dossier": ComponentPin(repo="YOUR-ORG/dossier", version="0.1.0"),
        },
    )
    text = serialize_lock(lock)
    restored = deserialize_lock(text)
    assert restored.release == "1.0.0"
    assert restored.regista_quad == _QUAD
    assert restored.components["regista"].repo == "YOUR-ORG/regista"
    assert restored.components["regista"].version == "0.4.0"
    assert restored.components["dossier"].version == "0.1.0"


def test_round_trip_without_quad() -> None:
    lock = SuiteLock(
        release="0.0.1",
        regista_quad=None,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
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
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
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
    with pytest.raises(ValueError, match="invalid regista quad"):
        deserialize_lock(text)


def test_deserialize_rejects_non_integer_quad() -> None:
    text = (
        "[suite]\nrelease='1.0'\n"
        "regista_library_version='0.4'\n"
        "regista_schema_version='not-a-number'\n"
        "regista_workflow_version='2'\n"
        "regista_envelope_version=4\n"
    )
    with pytest.raises(ValueError, match="invalid regista quad"):
        deserialize_lock(text)


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def test_file_round_trip(tmp_path: Path) -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
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
            ident: ComponentPin(repo=f"YOUR-ORG/{ident}", version=ver)
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
        components={"dossier": ComponentPin(repo="YOUR-ORG/dossier", version="1.0.0")},
    )
    result = check_drift(
        lock,
        current_quad=None,
        component_versions={"dossier": "1.0.0", "regista": None},
    )
    assert result.matches is True
    assert result.drift == []


def test_lock_without_quad_but_regista_now_installed_is_drift() -> None:
    """A lock generated without regista, but regista is now installed — drift."""
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={"dossier": ComponentPin(repo="YOUR-ORG/dossier", version="1.0.0")},
    )
    result = check_drift(
        lock,
        current_quad=_QUAD,
        component_versions={"dossier": "1.0.0", "regista": "0.4.0"},
    )
    assert result.matches is False
    unexpected = [d for d in result.drift if d.kind is DriftKind.UNEXPECTED_COMPONENT]
    assert any(d.component == "regista" and d.field == "version_quad" for d in unexpected)


# ---------------------------------------------------------------------------
# Revision pinning (Plan 001 WI-2.1 — reproducible candidate definitions)
# ---------------------------------------------------------------------------


_SHA_A = "a" * 40
_SHA_B = "b" * 40


def test_revision_round_trips_through_serialize() -> None:
    """A pinned revision survives serialize -> deserialize unchanged."""
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            "regista": ComponentPin(
                repo="YOUR-ORG/regista", version="0.5.1", revision=_SHA_A
            ),
        },
    )
    restored = deserialize_lock(serialize_lock(lock))
    assert restored.components["regista"].revision == _SHA_A


def test_revision_is_optional_in_round_trip() -> None:
    """Older locks without revisions round-trip with revision=None."""
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            "regista": ComponentPin(repo="YOUR-ORG/regista", version="0.5.1"),
        },
    )
    text = serialize_lock(lock)
    assert "revision" not in text
    restored = deserialize_lock(text)
    assert restored.components["regista"].revision is None


def test_revision_drift_is_named_when_both_sides_have_sha() -> None:
    """A locked revision vs a different current revision → REVISION_MISMATCH."""
    locked_versions = _all_versions("1.0.0")
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            ident: ComponentPin(
                repo=f"YOUR-ORG/{ident}", version=ver, revision=_SHA_A
            )
            for ident, ver in locked_versions.items()
        },
    )
    current_revisions = {ident: _SHA_B for ident in locked_versions}
    result = check_drift(
        lock,
        current_quad=_QUAD,
        component_versions=locked_versions,
        component_revisions=current_revisions,
    )
    assert result.matches is False
    rev_drifts = [d for d in result.drift if d.kind is DriftKind.REVISION_MISMATCH]
    assert len(rev_drifts) == len(locked_versions)
    sample = rev_drifts[0]
    assert sample.locked == _SHA_A
    assert sample.current == _SHA_B
    assert sample.field == "revision"


def test_revision_drift_absent_when_current_has_no_sha() -> None:
    """A locked revision with no current probeable SHA must NOT false-positive."""
    locked_versions = _all_versions("1.0.0")
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={
            ident: ComponentPin(
                repo=f"YOUR-ORG/{ident}", version=ver, revision=_SHA_A
            )
            for ident, ver in locked_versions.items()
        },
    )
    # current_revisions omitted entirely (no source checkouts available)
    result = check_drift(
        lock,
        current_quad=_QUAD,
        component_versions=locked_versions,
    )
    assert result.matches is True
    rev_drifts = [d for d in result.drift if d.kind is DriftKind.REVISION_MISMATCH]
    assert rev_drifts == []


def test_revision_drift_absent_when_lock_has_no_sha() -> None:
    """A version-only lock cannot detect revision drift by design."""
    locked_versions = _all_versions("1.0.0")
    lock = _lock_with(locked_versions)  # revisions all None
    current_revisions = {ident: _SHA_A for ident in locked_versions}
    result = check_drift(
        lock,
        current_quad=_QUAD,
        component_versions=locked_versions,
        component_revisions=current_revisions,
    )
    assert result.matches is True


def test_revision_drift_format_is_named() -> None:
    result = LockDriftResult(
        matches=False,
        note="1 drift(s)",
        drift=[
            DriftEntry(
                kind=DriftKind.REVISION_MISMATCH,
                component="dossier",
                field="revision",
                locked=_SHA_A,
                current=_SHA_B,
            ),
        ],
    )
    text = format_drift_text(result)
    assert "revision" in text
    assert _SHA_A in text
    assert _SHA_B in text


def test_generate_lock_threads_revisions_into_pins() -> None:
    """generate_lock(component_revisions=...) records the SHA on each pin."""
    versions = _all_versions("1.0.0")
    revisions = {ident: _SHA_A for ident in versions}
    lock = generate_lock_locked_only(versions, revisions)
    for pin in lock.components.values():
        assert pin.revision == _SHA_A


def generate_lock_locked_only(
    versions: dict[str, str | None], revisions: dict[str, str | None]
) -> SuiteLock:
    """generate_lock with regista/runner stubbed out, for unit tests."""
    return generate_lock(
        component_versions=versions,
        component_revisions=revisions,
        runner=lambda cmd: subprocess.CompletedProcess(cmd, 1, "", ""),
        installed=lambda _: False,
    )


def test_read_component_revisions_returns_none_for_missing_checkout(
    tmp_path: Path,
) -> None:
    """When no source checkout exists, every revision is None (no false pin)."""
    from agent_suite.components import COMPONENTS
    from agent_suite.lock import read_component_revisions

    revisions = read_component_revisions(
        components=COMPONENTS, search_roots=(tmp_path / "nonexistent",)
    )
    assert set(revisions) == {c.ident for c in COMPONENTS}
    assert all(v is None for v in revisions.values())


def test_read_component_revisions_reads_local_checkout_sha(
    tmp_path: Path,
) -> None:
    """When a real git checkout exists, the HEAD SHA is captured."""
    import os
    import subprocess as sp

    from agent_suite.components import _component, Tier
    from agent_suite.lock import read_component_revisions

    basename = "fake-suite-comp"
    checkout = tmp_path / basename
    checkout.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    sp.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "README").write_text("hi\n")
    sp.run(["git", "-C", str(checkout), "add", "."], check=True)
    sp.run(["git", "-C", str(checkout), "commit", "-q", "-m", "init"], check=True, env=env)
    head = sp.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    comp = _component("fake", "owner/fake-suite-comp", Tier.SPINE, ("fake", "doctor"))
    revisions = read_component_revisions(components=(comp,), search_roots=(tmp_path,))
    assert revisions["fake"] == head


def test_serialize_sorts_component_keys() -> None:
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=None,
        components={
            "zebra": ComponentPin(repo="YOUR-ORG/zebra", version="1.0.0"),
            "alpha": ComponentPin(repo="YOUR-ORG/alpha", version="1.0.0"),
        },
    )
    text = serialize_lock(lock)
    alpha_pos = text.index("[components.alpha]")
    zebra_pos = text.index("[components.zebra]")
    assert alpha_pos < zebra_pos


def test_atomic_write_does_not_leave_partial(tmp_path: Path) -> None:
    """write_lock_file uses temp+rename; no partial file on success."""
    lock = SuiteLock(
        release="1.0.0",
        regista_quad=_QUAD,
        components={"regista": ComponentPin(repo="YOUR-ORG/regista", version="0.4.0")},
    )
    path = tmp_path / "SUITE.lock"
    write_lock_file(lock, path)
    assert path.exists()
    assert not (tmp_path / "SUITE.lock.tmp").exists()


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


# ---------------------------------------------------------------------------
# Release identity derivation
# ---------------------------------------------------------------------------


def test_suite_release_prefers_release_board(tmp_path: Path, monkeypatch) -> None:
    """_suite_release reads data/release-board.json relative to the module file."""
    import json as _json

    from agent_suite.lock import _suite_release

    import agent_suite.lock as lock_mod

    # Fake module location: <tmp>/src/agent_suite/lock.py
    # _suite_release walks parents[2] to find <tmp> and reads data/release-board.json.
    fake_root = tmp_path
    fake_src = fake_root / "src" / "agent_suite"
    fake_src.mkdir(parents=True)
    (fake_root / "data").mkdir()
    (fake_root / "data" / "release-board.json").write_text(
        _json.dumps({"release": "9.9.9-test"}), encoding="utf-8"
    )
    monkeypatch.setattr(lock_mod, "__file__", str(fake_src / "lock.py"))
    assert _suite_release() == "9.9.9-test"


def test_suite_release_falls_back_when_no_board(tmp_path: Path, monkeypatch) -> None:
    """Without release-board.json, _suite_release still returns a string."""
    from agent_suite.lock import _suite_release

    import agent_suite.lock as lock_mod

    monkeypatch.setattr(
        lock_mod, "__file__", str(tmp_path / "nowhere" / "lock.py")
    )
    result = _suite_release()
    assert isinstance(result, str)
    assert result  # non-empty


# ---------------------------------------------------------------------------
# H-1: empty-string revision is normalized to None (no false REVISION_MISMATCH)
# ---------------------------------------------------------------------------


def test_empty_string_revision_normalized_to_none() -> None:
    """A hand-edited lock with `revision = ""` round-trips as revision=None.

    H-1: ``isinstance("", str)`` is True, so the prior parsing stored ``""``
    rather than None. That broke round-trip (None → omitted on serialize;
    "" → emitted as empty string) AND caused false drift: ``check_drift``'s
    gate ``locked_rev is not None`` is True for ``""``, so a hand-edited lock
    with ``revision = ""`` produced false REVISION_MISMATCH against any real SHA.
    """
    text = (
        "[suite]\nrelease='1.0'\n\n"
        "[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision=''\n"
    )
    lock = deserialize_lock(text)
    assert lock.components["regista"].revision is None

    # Round-trip: a None revision is omitted on serialize.
    round_tripped = deserialize_lock(serialize_lock(lock))
    assert round_tripped.components["regista"].revision is None

    # No false drift: a version-only pin (revision=None after normalization)
    # must not report REVISION_MISMATCH even when the current state has a SHA.
    result = check_drift(
        lock,
        current_quad=_QUAD,
        component_versions={"regista": "0.5.1"},
        component_revisions={"regista": _SHA_A},
    )
    rev_drifts = [d for d in result.drift if d.kind is DriftKind.REVISION_MISMATCH]
    assert rev_drifts == []


def test_whitespace_only_revision_normalized_to_none() -> None:
    """A whitespace-only revision string is also normalized to None (H-1)."""
    text = (
        "[suite]\nrelease='1.0'\n\n"
        "[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='   '\n"
    )
    lock = deserialize_lock(text)
    assert lock.components["regista"].revision is None


# ---------------------------------------------------------------------------
# L-2: deserialize validates revision SHA format
# ---------------------------------------------------------------------------


def test_deserialize_rejects_non_hex_revision() -> None:
    """A hand-edited revision that isn't a hex SHA is rejected (L-2).

    A tag name like ``revision = "v0.5.1"`` would otherwise be accepted and
    cause perpetual drift against any probed SHA.
    """
    text = (
        "[suite]\nrelease='1.0'\n\n"
        "[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='v0.5.1'\n"
    )
    with pytest.raises(ValueError, match="40- or 64-char hex SHA"):
        deserialize_lock(text)


def test_deserialize_rejects_wrong_length_revision() -> None:
    """A revision that is hex but wrong length (not 40 or 64) is rejected (L-2)."""
    # 39 chars — too short for sha-1
    short = "a" * 39
    text = (
        f"[suite]\nrelease='1.0'\n\n"
        f"[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='{short}'\n"
    )
    with pytest.raises(ValueError, match="40- or 64-char hex SHA"):
        deserialize_lock(text)

    # 65 chars — too long for sha-256
    long = "a" * 65
    text = (
        f"[suite]\nrelease='1.0'\n\n"
        f"[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='{long}'\n"
    )
    with pytest.raises(ValueError, match="40- or 64-char hex SHA"):
        deserialize_lock(text)


def test_deserialize_accepts_sha256_revision() -> None:
    """A 64-char sha-256 hex SHA is accepted (L-2 accepts both 40 and 64)."""
    sha256 = "a" * 64
    text = (
        f"[suite]\nrelease='1.0'\n\n"
        f"[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='{sha256}'\n"
    )
    lock = deserialize_lock(text)
    assert lock.components["regista"].revision == sha256


def test_deserialize_accepts_uppercase_hex_revision() -> None:
    """Uppercase hex SHAs (as git may emit) are accepted (L-2)."""
    sha = "A" * 40
    text = (
        f"[suite]\nrelease='1.0'\n\n"
        f"[components.regista]\nrepo='r'\nversion='0.5.1'\nrevision='{sha}'\n"
    )
    lock = deserialize_lock(text)
    assert lock.components["regista"].revision == sha


# ---------------------------------------------------------------------------
# L-3: _probe_revision validates SHA length
# ---------------------------------------------------------------------------


def test_probe_revision_validates_sha_length(tmp_path: Path) -> None:
    """_probe_revision rejects git output that isn't 40 or 64 hex chars (L-3).

    A truncated or malformed ``git rev-parse HEAD`` output must not be mistaken
    for a valid SHA.
    """
    import os
    import subprocess as sp

    from agent_suite.lock import _probe_revision

    basename = "fake-comp-truncated"
    checkout = tmp_path / basename
    checkout.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    sp.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "README").write_text("hi\n")
    sp.run(["git", "-C", str(checkout), "add", "."], check=True)
    sp.run(["git", "-C", str(checkout), "commit", "-q", "-m", "init"], check=True, env=env)

    # Monkey-patch subprocess.run to return a truncated SHA (39 chars).
    real_run = sp.run

    def fake_run(cmd, **kw):  # type: ignore[no-untyped-def]
        if cmd[:4] == ("git", "-C", str(checkout), "rev-parse"):
            return sp.CompletedProcess(cmd, 0, "a" * 39, "")
        return real_run(cmd, **kw)

    import agent_suite.lock as lock_mod
    orig_run = lock_mod.subprocess.run
    lock_mod.subprocess.run = fake_run  # type: ignore[method-assign]
    try:
        result = _probe_revision("owner/fake-comp-truncated", (tmp_path,))
        assert result is None
    finally:
        lock_mod.subprocess.run = orig_run  # type: ignore[method-assign]


def test_probe_revision_rejects_non_hex_sha(tmp_path: Path) -> None:
    """_probe_revision rejects non-hex git output (L-3)."""
    import os
    import subprocess as sp

    from agent_suite.lock import _probe_revision

    basename = "fake-comp-nonhex"
    checkout = tmp_path / basename
    checkout.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    sp.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "README").write_text("hi\n")
    sp.run(["git", "-C", str(checkout), "add", "."], check=True)
    sp.run(["git", "-C", str(checkout), "commit", "-q", "-m", "init"], check=True, env=env)

    real_run = sp.run

    def fake_run(cmd, **kw):  # type: ignore[no-untyped-def]
        if cmd[:4] == ("git", "-C", str(checkout), "rev-parse"):
            return sp.CompletedProcess(cmd, 0, "g" * 40, "")  # 'g' is not hex
        return real_run(cmd, **kw)

    import agent_suite.lock as lock_mod
    orig_run = lock_mod.subprocess.run
    lock_mod.subprocess.run = fake_run  # type: ignore[method-assign]
    try:
        result = _probe_revision("owner/fake-comp-nonhex", (tmp_path,))
        assert result is None
    finally:
        lock_mod.subprocess.run = orig_run  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# L-4: _probe_revision rejects path-traversal basenames
# ---------------------------------------------------------------------------


def test_probe_revision_rejects_path_traversal() -> None:
    """A repo basename of `..` or containing separators is rejected (L-4).

    For ``repo = ".."`` (no slash), ``basename = ".."`` would resolve to
    ``root.parent``. Limited impact (subprocess uses tuple, no shell), but
    worth defending.
    """
    from agent_suite.lock import _probe_revision

    # `..` as the entire repo (no slash) → basename is `..`
    assert _probe_revision("..", (Path("/projects"),)) is None
    # `.` as the entire repo
    assert _probe_revision(".", (Path("/projects"),)) is None
    # A repo with multiple slashes → basename contains a separator
    # e.g. "foo/bar/baz" → basename "bar/baz" (contains "/")
    assert _probe_revision("foo/bar/baz", (Path("/projects"),)) is None
    # Empty basename
    assert _probe_revision("", (Path("/projects"),)) is None
    # A normal "owner/repo" still works (basename "repo" has no separator)
    # — verified by the existing test_read_component_revisions_reads_local_checkout_sha


def test_probe_revision_rejects_backslash_basename() -> None:
    """A basename containing a backslash is rejected (L-4)."""
    from agent_suite.lock import _probe_revision

    # A repo with no slash but a backslash in the basename
    assert _probe_revision("foo\\bar", (Path("/projects"),)) is None


# ---------------------------------------------------------------------------
# M-5: search roots are absolute, not relative to CWD
# ---------------------------------------------------------------------------


def test_default_search_roots_are_absolute() -> None:
    """The default search roots must be absolute paths (M-5).

    The prior default included ``Path("../projects")`` — relative to CWD — so
    ``agent-suite lock`` run from anywhere other than ``/projects/agent-suite``
    resolved to the wrong path.
    """
    from agent_suite.lock import _default_search_roots

    roots = _default_search_roots()
    for root in roots:
        assert root.is_absolute(), f"search root {root} must be absolute"
        # The relative fallback "../projects" must not appear
        assert str(root) != "../projects"


def test_default_search_roots_respect_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    """SUITE_WORKSPACE_ROOT overrides the default search roots (M-5)."""
    from agent_suite.lock import _default_search_roots

    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", "/custom/workspace")
    roots = _default_search_roots()
    assert roots == (Path("/custom/workspace"),)
    assert roots[0].is_absolute()


def test_read_component_revisions_finds_checkout_from_non_workspace_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Running from a non-workspace CWD still finds checkouts (M-5).

    The test creates a checkout under a custom root, sets SUITE_WORKSPACE_ROOT
    to that root, and changes CWD to /tmp (away from /projects/agent-suite).
    The revision must still be found.
    """
    import os
    import subprocess as sp

    from agent_suite.components import _component, Tier
    from agent_suite.lock import read_component_revisions

    basename = "fake-suite-comp-cwd"
    checkout = tmp_path / basename
    checkout.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    sp.run(["git", "init", "-q", str(checkout)], check=True)
    (checkout / "README").write_text("hi\n")
    sp.run(["git", "-C", str(checkout), "add", "."], check=True)
    sp.run(["git", "-C", str(checkout), "commit", "-q", "-m", "init"], check=True, env=env)
    head = sp.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Change CWD to somewhere completely unrelated.
    monkeypatch.chdir("/tmp")
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", str(tmp_path))

    comp = _component("fake", "owner/fake-suite-comp-cwd", Tier.SPINE, ("fake", "doctor"))
    revisions = read_component_revisions(components=(comp,))
    assert revisions["fake"] == head


def test_read_component_revisions_honest_none_when_checkout_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When the checkout is absent, the revision is honestly None (M-5)."""
    from agent_suite.components import _component, Tier
    from agent_suite.lock import read_component_revisions

    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", str(tmp_path / "nonexistent"))
    comp = _component("fake", "owner/fake-suite-comp", Tier.SPINE, ("fake", "doctor"))
    revisions = read_component_revisions(components=(comp,))
    assert revisions["fake"] is None
