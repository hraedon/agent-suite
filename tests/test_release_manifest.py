"""Tests for the immutable release manifest (Sol Gate 0 / Workstream 2).

Covers:
- Round-trip: ``deserialize_manifest(serialize_manifest(m)) == m``
- ``compute_manifest_self_sha256`` is stable across calls (deterministic)
- ``build_manifest`` correctly extracts constituent SHAs from a stubbed SUITE.lock
- ``bind_to_manifest`` correctly reports ``fully_bound=True`` for a matching
  inventory and ``fully_bound=False`` for a divergent one (with named mismatches)
- A dry-run fixture: build a manifest against a fixture SUITE.lock, serialize,
  deserialize, verify
- CLI integration (build + verify subcommands)
- Wheel hash verification (positive + negative)
- Tamper-evidence (self-SHA mismatch on deserialization)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from agent_suite.inventory import (
    ConstituentBinding,
    InventoryManifestBinding,
    build_inventory,
)
from agent_suite.lock import ComponentPin, RegistaVersionQuad, SuiteLock, serialize_lock
from agent_suite.release_manifest import (
    SCHEMA_VERSION,
    ManifestVerifyResult,
    ReleaseManifest,
    ReleaseManifestSubcommand,
    build_manifest,
    collect_wheel_artifacts,
    compute_manifest_self_sha256,
    deserialize_manifest,
    format_build_text,
    format_verify_text,
    serialize_manifest,
    verify_manifest_against_wheels,
)
from agent_suite.release_manifest import _sha256_text, _wheel_filename


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


_QUAD = RegistaVersionQuad(
    library_version="0.5.1",
    schema_version=43,
    canonical_workflow_version="2",
    envelope_version=5,
)

_SHA_A = "a" * 40
_SHA_B = "b" * 40
_SHA_C = "c" * 40
_SHA_D = "d" * 40
_SHA_E = "e" * 40
_SHA_F = "f" * 40

# Component idents and SHAs matching the real SUITE.lock shape.
_CONSTITUENT_DATA: dict[str, tuple[str, str, str]] = {
    # ident -> (repo, version, revision)
    "regista": ("hraedon/regista", "0.5.1", _SHA_A),
    "dossier": ("hraedon/dossier", "0.0.1", _SHA_B),
    "agent-notes": ("hraedon/agent-notes", "1.0.0", _SHA_C),
    "agent-provenance": ("hraedon/agent-provenance", "0.1.0", _SHA_D),
    "agent-capability-broker": ("hraedon/agent-capability-broker", "0.1.0", _SHA_E),
    "agent-wake": ("hraedon/agent-wake", "0.1.0", _SHA_F),
}

_FIXED_TIMESTAMP = "2026-07-19T12:00:00+00:00"


def _build_lock() -> SuiteLock:
    """Build a SuiteLock matching the real SUITE.lock shape."""
    components = {
        ident: ComponentPin(repo=repo, version=version, revision=rev)
        for ident, (repo, version, rev) in _CONSTITUENT_DATA.items()
    }
    return SuiteLock(
        release="1.0.0-dev",
        regista_quad=_QUAD,
        components=components,
    )


def _build_manifest(
    *,
    release_tag: str = "v1.0.0-rc1",
    umbrella_tag_sha: str = _SHA_A,
    generated_at: str = _FIXED_TIMESTAMP,
) -> ReleaseManifest:
    """Build a manifest from the fixture lock (pure, no I/O)."""
    lock = _build_lock()
    lock_text = serialize_lock(lock)
    return build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag=release_tag,
        umbrella_tag_sha=umbrella_tag_sha,
        generated_at=generated_at,
    )


# ---------------------------------------------------------------------------
# Round-trip: deserialize(serialize(m)) == m
# ---------------------------------------------------------------------------


def test_round_trip_serialize_deserialize() -> None:
    """serialize_manifest followed by deserialize_manifest is identity."""
    manifest = _build_manifest()
    text = serialize_manifest(manifest)
    restored = deserialize_manifest(text)
    assert restored == manifest


def test_round_trip_through_json_dumps() -> None:
    """The manifest survives a json.dumps + json.loads + deserialize_manifest cycle."""
    manifest = _build_manifest()
    text = json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":"))
    restored = deserialize_manifest(text)
    assert restored == manifest


def test_serialize_is_deterministic_sorted_no_whitespace() -> None:
    """Serialization produces sorted-key, no-whitespace JSON."""
    manifest = _build_manifest()
    text = serialize_manifest(manifest)
    # No whitespace between separators.
    assert ", " not in text
    assert ": " not in text
    # Keys are sorted.
    parsed = json.loads(text)
    keys = list(parsed.keys())
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# compute_manifest_self_sha256 is stable + deterministic
# ---------------------------------------------------------------------------


def test_self_sha256_is_stable_across_calls() -> None:
    """Calling compute_manifest_self_sha256 twice yields the same hash."""
    manifest = _build_manifest()
    sha1 = compute_manifest_self_sha256(manifest)
    sha2 = compute_manifest_self_sha256(manifest)
    assert sha1 == sha2
    assert len(sha1) == 64  # SHA-256 hex digest


def test_self_sha256_matches_recorded_value() -> None:
    """The manifest_self_sha256 field equals compute_manifest_self_sha256."""
    manifest = _build_manifest()
    assert manifest.manifest_self_sha256 == compute_manifest_self_sha256(manifest)


def test_self_sha256_excludes_self_field() -> None:
    """The self-SHA is computed with manifest_self_sha256="" — changing it
    must not affect the computed hash."""
    manifest = _build_manifest()
    from dataclasses import replace

    modified = replace(manifest, manifest_self_sha256="deadbeef" * 8)
    # The computed hash must be the same regardless of the recorded self_sha.
    assert compute_manifest_self_sha256(manifest) == compute_manifest_self_sha256(modified)


def test_self_sha256_changes_on_content_modification() -> None:
    """Tampering with any content field changes the self-SHA."""
    manifest = _build_manifest()
    from dataclasses import replace

    modified = replace(manifest, release_tag="v1.0.0-rc2")
    assert compute_manifest_self_sha256(manifest) != compute_manifest_self_sha256(modified)


# ---------------------------------------------------------------------------
# build_manifest correctly extracts constituent SHAs from SUITE.lock
# ---------------------------------------------------------------------------


def test_build_manifest_extracts_constituent_shas() -> None:
    """build_manifest extracts each component's pinned revision from the lock."""
    manifest = _build_manifest()
    assert len(manifest.constituents) == 6
    by_ident = {c.ident: c for c in manifest.constituents}
    for ident, (repo, version, rev) in _CONSTITUENT_DATA.items():
        c = by_ident[ident]
        assert c.repo == repo
        assert c.pinned_revision == rev
        assert c.package_version == version


def test_build_manifest_records_regista_quad() -> None:
    """The regista version quad from the lock is recorded in the manifest."""
    manifest = _build_manifest()
    assert manifest.regista_library_version == _QUAD.library_version
    assert manifest.regista_schema_version == _QUAD.schema_version
    assert manifest.regista_workflow_version == _QUAD.canonical_workflow_version
    assert manifest.regista_envelope_version == _QUAD.envelope_version


def test_build_manifest_records_lock_identity() -> None:
    """The lock identity (sha256, release, component_count) is recorded."""
    lock = _build_lock()
    lock_text = serialize_lock(lock)
    manifest = _build_manifest()
    assert manifest.lock_identity.lock_file_sha256 == _sha256_text(lock_text)
    assert manifest.lock_identity.release == "1.0.0-dev"
    assert manifest.lock_identity.component_count == 6


def test_build_manifest_records_umbrella_tag_sha() -> None:
    """The umbrella tag SHA is recorded as passed in."""
    manifest = _build_manifest(umbrella_tag_sha=_SHA_B)
    assert manifest.umbrella_tag_sha == _SHA_B
    assert manifest.umbrella_repo == "hraedon/agent-suite"


def test_build_manifest_schema_version_is_v1() -> None:
    """The schema_version field is 'v1' (the initial shape)."""
    manifest = _build_manifest()
    assert manifest.schema_version == SCHEMA_VERSION
    assert manifest.schema_version == "v1"


def test_build_manifest_raises_on_missing_regista_quad() -> None:
    """A lock without a regista quad is rejected — the spine is required."""
    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=None,
        components={"regista": ComponentPin(repo="hraedon/regista", version="0.5.1", revision=_SHA_A)},
    )
    with pytest.raises(ValueError, match="no regista quad"):
        build_manifest(
            lock=lock,
            lock_text="dummy",
            release_tag="v1.0.0",
            umbrella_tag_sha=_SHA_A,
        )


def test_build_manifest_raises_on_missing_revision() -> None:
    """A lock without pinned revisions is rejected — not reproducible."""
    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=_QUAD,
        components={
            "regista": ComponentPin(repo="hraedon/regista", version="0.5.1", revision=None),
        },
    )
    with pytest.raises(ValueError, match="no valid pinned revision"):
        build_manifest(
            lock=lock,
            lock_text="dummy",
            release_tag="v1.0.0",
            umbrella_tag_sha=_SHA_A,
        )


def test_build_manifest_wheel_hashes_empty_when_not_provided() -> None:
    """When no wheel_hashes are passed, wheel_sha256 and source_archive_sha256 are empty."""
    manifest = _build_manifest()
    for c in manifest.constituents:
        assert c.wheel_sha256 == ""
        assert c.source_archive_sha256 == ""
        assert c.wheel_filename == ""


def test_build_manifest_with_wheel_hashes() -> None:
    """When wheel_hashes are provided, they are recorded in the constituents."""
    wheel_sha = "0" * 64
    source_sha = "1" * 64
    wheel_hashes = {
        "regista": ("regista-0.5.1-py3-none-any.whl", wheel_sha),
    }
    source_hashes = {"regista": source_sha}
    manifest = _build_manifest()
    # Rebuild with hashes.
    lock = _build_lock()
    lock_text = serialize_lock(lock)
    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        source_archive_hashes=source_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )
    regista = next(c for c in manifest.constituents if c.ident == "regista")
    assert regista.wheel_filename == "regista-0.5.1-py3-none-any.whl"
    assert regista.wheel_sha256 == wheel_sha
    assert regista.source_archive_sha256 == source_sha
    # Other constituents still have empty hashes.
    dossier = next(c for c in manifest.constituents if c.ident == "dossier")
    assert dossier.wheel_sha256 == ""


# ---------------------------------------------------------------------------
# Deserialization validation
# ---------------------------------------------------------------------------


def test_deserialize_rejects_wrong_schema_version() -> None:
    """A manifest with an unsupported schema_version is rejected."""
    manifest = _build_manifest()
    d = manifest.to_dict()
    d["schema_version"] = "v999"
    text = json.dumps(d, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="unsupported schema_version"):
        deserialize_manifest(text)


def test_deserialize_rejects_invalid_pinned_revision() -> None:
    """A constituent with an invalid pinned_revision is rejected."""
    manifest = _build_manifest()
    d = manifest.to_dict()
    d["constituents"][0]["pinned_revision"] = "not-a-sha"
    text = json.dumps(d, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="pinned_revision must be"):
        deserialize_manifest(text)


def test_deserialize_rejects_tampered_self_sha() -> None:
    """A manifest whose self-SHA doesn't match its content is rejected."""
    manifest = _build_manifest()
    d = manifest.to_dict()
    d["manifest_self_sha256"] = "0" * 64  # wrong SHA
    text = json.dumps(d, sort_keys=True, separators=(",", ":"))
    with pytest.raises(ValueError, match="manifest_self_sha256 mismatch"):
        deserialize_manifest(text)


def test_deserialize_accepts_empty_umbrella_tag_sha() -> None:
    """An empty umbrella_tag_sha is valid (honest 'unresolvable at build time')."""
    manifest = _build_manifest(umbrella_tag_sha="")
    text = serialize_manifest(manifest)
    restored = deserialize_manifest(text)
    assert restored.umbrella_tag_sha == ""
    assert restored == manifest


# ---------------------------------------------------------------------------
# bind_to_manifest — matching and divergent inventories
# ---------------------------------------------------------------------------


def _build_matching_inventory() -> "build_inventory":  # type: ignore[valid-type]
    """Build an inventory whose components match the fixture manifest exactly."""
    versions = {ident: data[1] for ident, data in _CONSTITUENT_DATA.items()}
    revisions = {ident: data[2] for ident, data in _CONSTITUENT_DATA.items()}
    return build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
    )


def test_bind_to_manifest_fully_bound_when_matching() -> None:
    """A matching inventory + manifest → fully_bound=True."""
    from agent_suite.inventory import build_inventory

    versions = {ident: data[1] for ident, data in _CONSTITUENT_DATA.items()}
    revisions = {ident: data[2] for ident, data in _CONSTITUENT_DATA.items()}
    inv = build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
    )
    manifest = _build_manifest()
    binding = inv.bind_to_manifest(manifest)
    assert binding.fully_bound is True
    assert binding.release_tag == "v1.0.0-rc1"
    assert len(binding.bindings) == 6
    for b in binding.bindings:
        assert b.constituent_present is True
        assert b.pinned_revision_matches is True
        assert b.package_version_matches is True


def test_bind_to_manifest_not_fully_bound_on_revision_mismatch() -> None:
    """A divergent installed revision → fully_bound=False with named mismatch."""
    from agent_suite.inventory import build_inventory

    versions = {ident: data[1] for ident, data in _CONSTITUENT_DATA.items()}
    revisions = {ident: data[2] for ident, data in _CONSTITUENT_DATA.items()}
    # Diverge regista's installed revision.
    revisions["regista"] = _SHA_B
    inv = build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
    )
    manifest = _build_manifest()
    binding = inv.bind_to_manifest(manifest)
    assert binding.fully_bound is False
    regista_binding = next(b for b in binding.bindings if b.ident == "regista")
    assert regista_binding.constituent_present is True
    assert regista_binding.pinned_revision_matches is False
    assert regista_binding.package_version_matches is True


def test_bind_to_manifest_not_fully_bound_on_version_mismatch() -> None:
    """A divergent installed version → fully_bound=False with named mismatch."""
    from agent_suite.inventory import build_inventory

    versions = {ident: data[1] for ident, data in _CONSTITUENT_DATA.items()}
    revisions = {ident: data[2] for ident, data in _CONSTITUENT_DATA.items()}
    # Diverge dossier's installed version.
    versions["dossier"] = "9.9.9"
    inv = build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
    )
    manifest = _build_manifest()
    binding = inv.bind_to_manifest(manifest)
    assert binding.fully_bound is False
    dossier_binding = next(b for b in binding.bindings if b.ident == "dossier")
    assert dossier_binding.constituent_present is True
    assert dossier_binding.pinned_revision_matches is True
    assert dossier_binding.package_version_matches is False


def test_bind_to_manifest_not_fully_bound_when_constituent_absent() -> None:
    """A constituent absent from the inventory → fully_bound=False."""
    from agent_suite.components import Component, Tier
    from agent_suite.inventory import build_inventory

    # Build an inventory with only regista (custom components tuple) so the
    # other 5 manifest constituents are absent from the inventory entirely.
    regista_only = Component(
        ident="regista",
        repo="hraedon/regista",
        tier=Tier.SPINE,
        doctor_cmd=("regista", "doctor", "--json"),
    )
    versions = {"regista": "0.5.1"}
    revisions = {"regista": _SHA_A}
    inv = build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
        components=(regista_only,),
    )
    manifest = _build_manifest()
    binding = inv.bind_to_manifest(manifest)
    assert binding.fully_bound is False
    # regista should be present and matching.
    regista_binding = next(b for b in binding.bindings if b.ident == "regista")
    assert regista_binding.constituent_present is True
    assert regista_binding.pinned_revision_matches is True
    # The other 5 should be absent (not in the inventory's components list).
    absent = [b for b in binding.bindings if not b.constituent_present]
    assert len(absent) == 5
    for b in absent:
        assert b.pinned_revision_matches is False
        assert b.package_version_matches is False


def test_bind_to_manifest_to_dict_has_expected_shape() -> None:
    """The binding's to_dict has the expected JSON shape."""
    from agent_suite.inventory import build_inventory

    versions = {ident: data[1] for ident, data in _CONSTITUENT_DATA.items()}
    revisions = {ident: data[2] for ident, data in _CONSTITUENT_DATA.items()}
    inv = build_inventory(
        lock_obj=_build_lock(),
        has_lock_file=True,
        lock_path=Path("SUITE.lock"),
        component_versions=versions,
        component_revisions=revisions,
        current_quad=_QUAD,
    )
    manifest = _build_manifest()
    binding = inv.bind_to_manifest(manifest)
    d = binding.to_dict()
    assert d["release_tag"] == "v1.0.0-rc1"
    assert d["fully_bound"] is True
    assert isinstance(d["bindings"], list)
    assert len(d["bindings"]) == 6
    assert d["bindings"][0]["ident"] is not None


# ---------------------------------------------------------------------------
# Dry-run fixture: build → serialize → deserialize → verify
# ---------------------------------------------------------------------------


def test_dry_run_fixture_build_serialize_deserialize_verify(tmp_path: Path) -> None:
    """End-to-end dry-run: build a manifest from a fixture SUITE.lock, serialize,
    deserialize, and verify it round-trips cleanly.

    This is the end-to-end test the task spec requires: "a dry-run fixture
    that builds a manifest against a fixture SUITE.lock, serializes, deserializes,
    and verifies."
    """
    # Write a fixture SUITE.lock to disk.
    lock = _build_lock()
    lock_text = serialize_lock(lock)
    lock_file = tmp_path / "SUITE.lock"
    lock_file.write_text(lock_text, encoding="utf-8")

    # Build the manifest (pure function — pass the lock and text directly).
    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v0.0.0-test",
        umbrella_tag_sha=_SHA_A,
        generated_at=_FIXED_TIMESTAMP,
    )

    # Serialize to deterministic JSON.
    serialized = serialize_manifest(manifest)
    assert isinstance(serialized, str)
    assert serialized == serialize_manifest(manifest)  # deterministic

    # Write to disk and read back.
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(serialized, encoding="utf-8")
    restored = deserialize_manifest(manifest_path.read_text(encoding="utf-8"))

    # The round-trip must be exact.
    assert restored == manifest
    assert restored.constituents == manifest.constituents
    assert restored.manifest_self_sha256 == manifest.manifest_self_sha256

    # The self-SHA must be valid.
    assert restored.manifest_self_sha256 == compute_manifest_self_sha256(restored)


def test_dry_run_fixture_with_real_suite_lock() -> None:
    """Build a manifest against the real SUITE.lock in the repo root.

    This confirms the manifest can be built from the actual committed lock
    and produces sane output. Wheel hashes will be empty (no wheels built
    locally) — the manifest honestly records 'not provided.'
    """
    repo_root = Path(__file__).resolve().parents[1]
    lock_path = repo_root / "SUITE.lock"
    if not lock_path.is_file():
        pytest.skip("SUITE.lock not found at repo root")
    from agent_suite.lock import load_lock_file

    lock_text = lock_path.read_text(encoding="utf-8")
    lock_obj = load_lock_file(lock_path)
    assert lock_obj is not None, "SUITE.lock must be parseable"

    manifest = build_manifest(
        lock=lock_obj,
        lock_text=lock_text,
        release_tag="v0.0.0-test",
        umbrella_tag_sha="",
        generated_at=_FIXED_TIMESTAMP,
    )
    assert manifest.schema_version == "v1"
    assert manifest.suite_release == lock_obj.release
    assert manifest.lock_identity.component_count == len(lock_obj.components)
    assert len(manifest.constituents) == len(lock_obj.components)
    # Every constituent has a valid pinned revision (the lock pins them).
    for c in manifest.constituents:
        assert len(c.pinned_revision) == 40
    # Wheel hashes are empty (no wheels built locally).
    for c in manifest.constituents:
        assert c.wheel_sha256 == ""
        assert c.source_archive_sha256 == ""


# ---------------------------------------------------------------------------
# Wheel hash verification
# ---------------------------------------------------------------------------


def _make_wheel_file(dir_path: Path, ident: str, version: str, content: bytes = b"fake wheel") -> Path:
    """Create a fake wheel file in ``dir_path`` and return its path."""
    wheel_name = _wheel_filename(ident, version)
    path = dir_path / wheel_name
    path.write_bytes(content)
    return path


def test_collect_wheel_artifacts_finds_wheels(tmp_path: Path) -> None:
    """collect_wheel_artifacts finds wheels by ident+version prefix."""
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    _make_wheel_file(wheels_dir, "regista", "0.5.1")
    _make_wheel_file(wheels_dir, "dossier", "0.0.1")

    lock = _build_lock()
    result = collect_wheel_artifacts(wheels_dir, lock)
    assert "regista" in result
    assert result["regista"][0] == "regista-0.5.1-py3-none-any.whl"
    assert len(result["regista"][1]) == 64
    assert "dossier" in result
    # Components without wheels are omitted.
    assert "agent-notes" not in result


def test_verify_manifest_against_wheels_passes(tmp_path: Path) -> None:
    """A manifest with correct wheel hashes verifies cleanly."""
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    lock = _build_lock()
    lock_text = serialize_lock(lock)

    # Create real wheel files and collect their hashes.
    wheel_hashes: dict[str, tuple[str, str]] = {}
    for ident, (repo, version, rev) in _CONSTITUENT_DATA.items():
        wheel_path = _make_wheel_file(wheels_dir, ident, version)
        sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        wheel_hashes[ident] = (wheel_path.name, sha)

    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )

    result = verify_manifest_against_wheels(manifest, wheels_dir)
    assert result.ok is True
    assert result.mismatches == []


def test_verify_manifest_against_wheels_detects_mismatch(tmp_path: Path) -> None:
    """A wheel whose content changed after manifest construction is detected."""
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    lock = _build_lock()
    lock_text = serialize_lock(lock)

    # Create a wheel file for regista.
    wheel_path = _make_wheel_file(wheels_dir, "regista", "0.5.1", content=b"original")
    sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    wheel_hashes = {"regista": (wheel_path.name, sha)}

    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )

    # Tamper with the wheel file.
    wheel_path.write_bytes(b"tampered")

    result = verify_manifest_against_wheels(manifest, wheels_dir)
    assert result.ok is False
    assert len(result.mismatches) == 1
    assert "regista" in result.mismatches[0]


def test_verify_manifest_skips_empty_wheel_hashes(tmp_path: Path) -> None:
    """Constituents with empty wheel_sha256 are skipped during verification."""
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    # Build a manifest with no wheel hashes (all empty).
    manifest = _build_manifest()
    result = verify_manifest_against_wheels(manifest, wheels_dir)
    assert result.ok is True
    assert result.mismatches == []


def test_verify_manifest_detects_missing_wheel(tmp_path: Path) -> None:
    """A wheel file referenced by the manifest but absent from the dir is a mismatch."""
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    lock = _build_lock()
    lock_text = serialize_lock(lock)

    # Record a hash for a wheel that doesn't exist in the dir.
    wheel_hashes = {"regista": ("regista-0.5.1-py3-none-any.whl", "0" * 64)}
    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )

    result = verify_manifest_against_wheels(manifest, wheels_dir)
    assert result.ok is False
    assert "not found" in result.mismatches[0]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_release_manifest_build_json(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`agent-suite release-manifest build --tag v0.0.0-test --json` produces JSON."""
    from agent_suite.cli import main

    # The CLI resolves DEFAULT_LOCK_PATH at call time via a local import,
    # so monkeypatching the module attribute is sufficient. Use the real
    # SUITE.lock (it exists in the repo root).
    repo_root = Path(__file__).resolve().parents[1]
    import agent_suite.lock as lock_mod

    monkeypatch.setattr(lock_mod, "DEFAULT_LOCK_PATH", repo_root / "SUITE.lock")

    rc = main(["release-manifest", "build", "--tag", "v0.0.0-test", "--json"])
    captured = capsys.readouterr()
    assert rc == 0
    data = json.loads(captured.out)
    assert data["schema_version"] == "v1"
    assert data["release_tag"] == "v0.0.0-test"
    assert data["umbrella_repo"] == "hraedon/agent-suite"
    assert isinstance(data["constituents"], list)
    assert len(data["constituents"]) == 6
    assert data["manifest_self_sha256"]  # non-empty


def test_cli_release_manifest_build_text(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`agent-suite release-manifest build --tag v0.0.0-test` (text mode) is readable."""
    from agent_suite.cli import main

    repo_root = Path(__file__).resolve().parents[1]
    import agent_suite.lock as lock_mod

    monkeypatch.setattr(lock_mod, "DEFAULT_LOCK_PATH", repo_root / "SUITE.lock")

    rc = main(["release-manifest", "build", "--tag", "v0.0.0-test"])
    captured = capsys.readouterr()
    assert rc == 0
    assert "agent-suite release manifest" in captured.out
    assert "constituents:" in captured.out
    assert "manifest_self_sha256:" in captured.out


def test_cli_release_manifest_verify_with_wheels(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`release-manifest verify` with a matching wheels-dir passes."""
    from agent_suite.cli import main

    # Build a manifest with real wheel files.
    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    lock = _build_lock()
    lock_text = serialize_lock(lock)
    wheel_hashes: dict[str, tuple[str, str]] = {}
    for ident, (repo, version, rev) in _CONSTITUENT_DATA.items():
        wheel_path = _make_wheel_file(wheels_dir, ident, version)
        sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
        wheel_hashes[ident] = (wheel_path.name, sha)

    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0-test",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(serialize_manifest(manifest), encoding="utf-8")

    rc = main([
        "release-manifest", "verify", str(manifest_path),
        "--wheels-dir", str(wheels_dir),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "ok" in captured.out


def test_cli_release_manifest_verify_detects_mismatch(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`release-manifest verify` exits non-zero on a wheel hash mismatch."""
    from agent_suite.cli import main

    wheels_dir = tmp_path / "wheels"
    wheels_dir.mkdir()
    lock = _build_lock()
    lock_text = serialize_lock(lock)

    wheel_path = _make_wheel_file(wheels_dir, "regista", "0.5.1", content=b"original")
    sha = hashlib.sha256(wheel_path.read_bytes()).hexdigest()
    wheel_hashes = {"regista": (wheel_path.name, sha)}

    manifest = build_manifest(
        lock=lock,
        lock_text=lock_text,
        release_tag="v1.0.0-test",
        umbrella_tag_sha=_SHA_A,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )
    manifest_path = tmp_path / "release-manifest.json"
    manifest_path.write_text(serialize_manifest(manifest), encoding="utf-8")

    # Tamper with the wheel.
    wheel_path.write_bytes(b"tampered")

    rc = main([
        "release-manifest", "verify", str(manifest_path),
        "--wheels-dir", str(wheels_dir),
    ])
    captured = capsys.readouterr()
    assert rc == 1
    assert "FAILED" in captured.out or "mismatch" in captured.out


def test_cli_release_manifest_build_missing_lock(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`release-manifest build` exits non-zero when SUITE.lock is missing."""
    from agent_suite.cli import main

    import agent_suite.lock as lock_mod

    monkeypatch.setattr(lock_mod, "DEFAULT_LOCK_PATH", tmp_path / "nonexistent.lock")

    rc = main(["release-manifest", "build", "--tag", "v0.0.0-test", "--json"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "SUITE.lock not found" in captured.err


# ---------------------------------------------------------------------------
# ReleaseManifestSubcommand totality (assert_never guard)
# ---------------------------------------------------------------------------


def test_release_manifest_subcommand_is_closed_set() -> None:
    """The ReleaseManifestSubcommand enum has exactly BUILD and VERIFY."""
    values = {s.value for s in ReleaseManifestSubcommand}
    assert values == {"build", "verify"}


# ---------------------------------------------------------------------------
# Format text
# ---------------------------------------------------------------------------


def test_format_build_text_is_readable() -> None:
    """format_build_text produces a readable summary."""
    manifest = _build_manifest()
    text = format_build_text(manifest)
    assert "agent-suite release manifest" in text
    assert "release_tag: v1.0.0-rc1" in text
    assert "constituents:" in text
    assert "regista" in text
    for ident in _CONSTITUENT_DATA:
        assert ident in text


def test_format_verify_text_ok() -> None:
    """format_verify_text shows 'ok' for a passing verification."""
    result = ManifestVerifyResult(
        ok=True, release_tag="v1.0.0", mismatches=[], note="ok"
    )
    text = format_verify_text(result)
    assert "ok" in text
    assert "v1.0.0" in text


def test_format_verify_text_failed() -> None:
    """format_verify_text names mismatches for a failing verification."""
    result = ManifestVerifyResult(
        ok=False,
        release_tag="v1.0.0",
        mismatches=["regista: wheel_sha256 mismatch — recorded=x actual=y"],
        note="1 mismatch(es)",
    )
    text = format_verify_text(result)
    assert "FAILED" in text
    assert "regista" in text
    assert "mismatch" in text


# ---------------------------------------------------------------------------
# ConstituentBinding + InventoryManifestBinding dataclasses
# ---------------------------------------------------------------------------


def test_constituent_binding_to_dict() -> None:
    """ConstituentBinding.to_dict has the expected shape."""
    b = ConstituentBinding(
        ident="regista",
        pinned_revision_matches=True,
        package_version_matches=True,
        constituent_present=True,
    )
    d = b.to_dict()
    assert d == {
        "ident": "regista",
        "pinned_revision_matches": True,
        "package_version_matches": True,
        "constituent_present": True,
    }


def test_inventory_manifest_binding_to_dict() -> None:
    """InventoryManifestBinding.to_dict has the expected shape."""
    binding = InventoryManifestBinding(
        release_tag="v1.0.0",
        bindings=(
            ConstituentBinding(
                ident="regista",
                pinned_revision_matches=True,
                package_version_matches=True,
                constituent_present=True,
            ),
        ),
        fully_bound=True,
    )
    d = binding.to_dict()
    assert d["release_tag"] == "v1.0.0"
    assert d["fully_bound"] is True
    assert isinstance(d["bindings"], list)
    assert len(d["bindings"]) == 1
