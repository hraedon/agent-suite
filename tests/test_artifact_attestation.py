"""Tests for artifact-era attestation (WI-036).

The point of these tests is that the attestation never claims more than it can
prove. Each rung of the ladder is exercised with a real on-disk fixture — a
built wheel, an unpacked "install" with a RECORD, a PEP 610 ``direct_url.json``
— so the strength the code reports is the strength the evidence supports.
"""

from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from agent_suite.artifact_attestation import (
    ArtifactAttestation,
    AttestationStrength,
    attest_component,
    binds_release_identity,
    format_text,
    strength_label,
    verify_installed_artifacts,
)
from agent_suite.lock import ComponentPin, RegistaVersionQuad, SuiteLock, serialize_lock
from agent_suite.release_manifest import (
    ConstituentArtifact,
    ReleaseManifest,
    build_manifest,
)
from agent_suite.runtime_provenance import (
    ArtifactSource,
    InstallMode,
    RuntimeProvenance,
)

_QUAD = RegistaVersionQuad(
    library_version="0.5.1",
    schema_version=43,
    canonical_workflow_version="2",
    envelope_version=5,
)
_FIXED_TIMESTAMP = "2026-07-31T12:00:00+00:00"

# The fixture distribution: one package with two modules, packaged as a real
# wheel and then "installed" by unpacking it.
_DIST = "widget"
_VERSION = "1.2.3"
_WHEEL_NAME = f"{_DIST}-{_VERSION}-py3-none-any.whl"
_PAYLOAD: dict[str, str] = {
    f"{_DIST}/__init__.py": '"""fixture package."""\n__version__ = "1.2.3"\n',
    f"{_DIST}/core.py": "def run() -> int:\n    return 7\n",
}


def _record_digest(data: bytes) -> str:
    raw = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + raw.decode("ascii")


def _record_text(files: dict[str, bytes], *, record_path: str) -> str:
    lines = [
        f"{name},{_record_digest(body)},{len(body)}"
        for name, body in sorted(files.items())
    ]
    lines.append(f"{record_path},,")
    return "\n".join(lines) + "\n"


def _build_wheel(dest_dir: Path) -> Path:
    """Write a real (minimal but valid) wheel containing ``_PAYLOAD``."""
    dist_info = f"{_DIST}-{_VERSION}.dist-info"
    members: dict[str, bytes] = {
        name: body.encode("utf-8") for name, body in _PAYLOAD.items()
    }
    members[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {_DIST}\nVersion: {_VERSION}\n"
    ).encode()
    members[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    record = _record_text(members, record_path=f"{dist_info}/RECORD")
    members[f"{dist_info}/RECORD"] = record.encode("utf-8")

    dest_dir.mkdir(parents=True, exist_ok=True)
    wheel_path = dest_dir / _WHEEL_NAME
    with zipfile.ZipFile(wheel_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(members):
            archive.writestr(name, members[name])
    return wheel_path


def _install_wheel(
    wheel: Path,
    env_root: Path,
    *,
    direct_url: dict[str, object] | None = None,
) -> Path:
    """Unpack ``wheel`` into a venv-shaped tree; return the .dist-info path.

    Mirrors what an installer does: unpack into site-packages, then add
    ``INSTALLER`` / ``direct_url.json`` and extend RECORD to cover them. The
    ``pyvenv.cfg`` marker is what bounds RECORD path traversal.
    """
    site_packages = env_root / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    (env_root / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site_packages)
    dist_info = site_packages / f"{_DIST}-{_VERSION}.dist-info"

    extra: dict[str, bytes] = {}
    installer = dist_info / "INSTALLER"
    installer.write_bytes(b"test\n")
    extra[f"{dist_info.name}/INSTALLER"] = installer.read_bytes()
    if direct_url is not None:
        payload = json.dumps(direct_url, separators=(",", ":")).encode("utf-8")
        (dist_info / "direct_url.json").write_bytes(payload)
        extra[f"{dist_info.name}/direct_url.json"] = payload

    original = (dist_info / "RECORD").read_text(encoding="utf-8")
    kept = [line for line in original.splitlines() if line and not line.endswith(",,")]
    for name, body in sorted(extra.items()):
        kept.append(f"{name},{_record_digest(body)},{len(body)}")
    kept.append(f"{dist_info.name}/RECORD,,")
    (dist_info / "RECORD").write_text("\n".join(kept) + "\n", encoding="utf-8")
    return dist_info


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _constituent(
    *,
    wheel_sha256: str = "",
    wheel_filename: str = _WHEEL_NAME,
    version: str = _VERSION,
) -> ConstituentArtifact:
    return ConstituentArtifact(
        ident="regista",
        repo="hraedon/regista",
        pinned_revision="a" * 40,
        package_version=version,
        wheel_filename=wheel_filename,
        wheel_sha256=wheel_sha256,
        source_archive_sha256="",
    )


def _provenance(
    dist_info: Path | None,
    *,
    version: str | None = _VERSION,
    mode: InstallMode = InstallMode.UV_TOOL,
    source: ArtifactSource = ArtifactSource.ARCHIVE,
    archive_url: str | None = None,
    archive_sha256: str | None = None,
) -> RuntimeProvenance:
    return RuntimeProvenance(
        component="regista",
        distribution=_DIST,
        version=version,
        cli_path="/usr/local/bin/regista",
        interpreter="/opt/env/bin/python",
        mode=mode,
        source=source,
        dist_info_path=str(dist_info) if dist_info is not None else None,
        archive_url=archive_url,
        archive_sha256=archive_sha256,
    )


@pytest.fixture
def wheel_and_install(tmp_path: Path) -> tuple[Path, Path]:
    """A built wheel plus an install unpacked from it."""
    wheel = _build_wheel(tmp_path / "wheels")
    dist_info = _install_wheel(
        wheel,
        tmp_path / "env",
        direct_url={"url": wheel.as_uri(), "archive_info": {}},
    )
    return wheel, dist_info


# ---------------------------------------------------------------------------
# The strength ladder
# ---------------------------------------------------------------------------


def test_every_strength_has_a_label_and_a_binding_answer() -> None:
    """No rung may be silently unhandled (assert_never over the enum)."""
    for strength in AttestationStrength:
        assert strength_label(strength)
        assert isinstance(binds_release_identity(strength), bool)


def test_only_hash_rungs_bind_release_identity() -> None:
    """RECORD self-consistency must NOT be reported as a release binding."""
    assert binds_release_identity(AttestationStrength.WHEEL_HASH_CHAIN)
    assert binds_release_identity(AttestationStrength.RECORDED_ARCHIVE_HASH)
    assert not binds_release_identity(AttestationStrength.INSTALL_RECORD_ONLY)
    assert not binds_release_identity(AttestationStrength.VERSION_ONLY)
    assert not binds_release_identity(AttestationStrength.NOT_APPLICABLE)


def test_wheel_on_disk_yields_the_full_hash_chain(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """manifest sha256 -> wheel bytes -> wheel RECORD -> installed files."""
    wheel, dist_info = wheel_and_install
    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    result = attest_component(
        expected, _provenance(dist_info, archive_url=wheel.as_uri()),
        wheels_dir=wheel.parent,
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert result.binds_release_identity
    assert result.files_verified == len(_PAYLOAD) + 2  # payload + METADATA + WHEEL


def test_without_a_wheel_the_best_available_is_install_record_only(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """No wheel on disk: verified, but explicitly not bound to the release."""
    wheel, dist_info = wheel_and_install
    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    result = attest_component(
        expected, _provenance(dist_info, archive_url=wheel.as_uri())
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert not result.binds_release_identity
    assert result.files_verified > 0


def test_recorded_archive_hash_binds_without_the_wheel(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """A PEP 610 archive hash recorded at install time is a real binding."""
    wheel, dist_info = wheel_and_install
    digest = _sha256_file(wheel)
    expected = _constituent(wheel_sha256=digest)
    result = attest_component(
        expected,
        _provenance(dist_info, archive_url=wheel.as_uri(), archive_sha256=digest),
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.RECORDED_ARCHIVE_HASH
    assert result.binds_release_identity


def test_recorded_archive_hash_mismatch_is_a_failure(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    expected = _constituent(wheel_sha256="0" * 64)
    result = attest_component(
        expected,
        _provenance(
            dist_info, archive_url=wheel.as_uri(), archive_sha256=_sha256_file(wheel)
        ),
    )
    assert not result.ok
    assert any("recorded archive sha256" in m for m in result.mismatches)


def test_no_dist_info_degrades_to_version_only(tmp_path: Path) -> None:
    """Nothing to hash: report version-only rather than inventing evidence."""
    expected = _constituent()
    result = attest_component(expected, _provenance(None))
    assert result.ok
    assert result.strength is AttestationStrength.VERSION_ONLY
    assert not result.binds_release_identity


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------


def test_edited_installed_file_fails_the_chain(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """The whole point: modified code on disk must not pass attestation."""
    wheel, dist_info = wheel_and_install
    target = dist_info.parent / _DIST / "core.py"
    target.write_text("def run() -> int:\n    return 0  # tampered\n", encoding="utf-8")
    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    result = attest_component(
        expected, _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not result.ok
    assert any("core.py" in m and "digest mismatch" in m for m in result.mismatches)
    # The chain is not claimed when it did not hold.
    assert result.strength is not AttestationStrength.WHEEL_HASH_CHAIN


def test_rewritten_record_still_fails_the_wheel_chain(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """An attacker who edits a file AND its RECORD digest still fails.

    This is exactly why the wheel RECORD (covered by the manifest's wheel
    hash) is the strong rung and the install's own RECORD is not.
    """
    wheel, dist_info = wheel_and_install
    target = dist_info.parent / _DIST / "core.py"
    tampered = b"def run() -> int:\n    return 0  # tampered\n"
    target.write_bytes(tampered)
    record = dist_info / "RECORD"
    lines = []
    for line in record.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{_DIST}/core.py,"):
            lines.append(
                f"{_DIST}/core.py,{_record_digest(tampered)},{len(tampered)}"
            )
        else:
            lines.append(line)
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")

    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    # Self-consistent: the install agrees with its own (rewritten) RECORD.
    weak = attest_component(expected, _provenance(dist_info))
    assert weak.ok
    assert weak.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert not weak.binds_release_identity
    # Bound to the release: the tamper is caught.
    strong = attest_component(
        expected, _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not strong.ok
    assert any("core.py" in m for m in strong.mismatches)


def test_missing_installed_file_is_a_mismatch(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    (dist_info.parent / _DIST / "core.py").unlink()
    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    result = attest_component(
        expected, _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not result.ok
    assert any("missing on disk" in m for m in result.mismatches)


def test_wheel_hash_mismatch_is_reported_before_the_chain(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """A wheels-dir wheel that isn't the manifest's wheel is a failure."""
    wheel, dist_info = wheel_and_install
    expected = _constituent(wheel_sha256="1" * 64)
    result = attest_component(
        expected, _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not result.ok
    assert any("wheel_sha256 mismatch" in m for m in result.mismatches)


def test_absent_wheel_in_wheels_dir_is_a_mismatch(
    wheel_and_install: tuple[Path, Path], tmp_path: Path
) -> None:
    wheel, dist_info = wheel_and_install
    empty = tmp_path / "empty"
    empty.mkdir()
    expected = _constituent(wheel_sha256=_sha256_file(wheel))
    result = attest_component(expected, _provenance(dist_info), wheels_dir=empty)
    assert not result.ok
    assert any("not found in" in m for m in result.mismatches)


# ---------------------------------------------------------------------------
# Non-cryptographic agreement checks
# ---------------------------------------------------------------------------


def test_version_mismatch_fails(wheel_and_install: tuple[Path, Path]) -> None:
    wheel, dist_info = wheel_and_install
    expected = _constituent(wheel_sha256=_sha256_file(wheel), version="9.9.9")
    result = attest_component(
        expected, _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not result.ok
    assert any("version mismatch" in m for m in result.mismatches)


def test_installed_from_a_differently_named_wheel_fails(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """Same version, different wheel filename — a real release divergence."""
    wheel, dist_info = wheel_and_install
    expected = _constituent(
        wheel_sha256="", wheel_filename=f"{_DIST}-{_VERSION}-py3-none-manylinux.whl"
    )
    result = attest_component(
        expected, _provenance(dist_info, archive_url=wheel.as_uri())
    )
    assert not result.ok
    assert any("but the manifest records" in m for m in result.mismatches)


# ---------------------------------------------------------------------------
# Not-applicable paths — honest, not silently passing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "source", "fragment"),
    [
        (InstallMode.ABSENT, ArtifactSource.UNKNOWN, "absent"),
        (InstallMode.UNKNOWN, ArtifactSource.UNKNOWN, "could not be determined"),
        (InstallMode.EDITABLE, ArtifactSource.EDITABLE, "not a release wheel"),
        (InstallMode.VENV, ArtifactSource.VCS, "not a release wheel"),
        (InstallMode.VENV, ArtifactSource.LOCAL, "not a release wheel"),
    ],
)
def test_non_artifact_installs_are_not_applicable(
    mode: InstallMode, source: ArtifactSource, fragment: str
) -> None:
    result = attest_component(
        _constituent(wheel_sha256="a" * 64), _provenance(None, mode=mode, source=source)
    )
    assert result.strength is AttestationStrength.NOT_APPLICABLE
    assert result.ok
    assert fragment in result.detail


# ---------------------------------------------------------------------------
# Suite-level roll-up
# ---------------------------------------------------------------------------


def _manifest(*, wheel_hashes: dict[str, tuple[str, str]] | None = None) -> ReleaseManifest:
    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=_QUAD,
        components={
            "regista": ComponentPin("hraedon/regista", _VERSION, "a" * 40),
            "dossier": ComponentPin("hraedon/dossier", "0.1.0", "b" * 40),
        },
    )
    return build_manifest(
        lock=lock,
        lock_text=serialize_lock(lock),
        release_tag="v1.0.0-rc.9",
        umbrella_tag_sha="c" * 40,
        wheel_hashes=wheel_hashes,
        generated_at=_FIXED_TIMESTAMP,
    )


def test_verify_installed_artifacts_rolls_up_the_weakest_rung(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {
        "regista": _provenance(dist_info, archive_url=wheel.as_uri()),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(manifest, provenance)
    assert result.ok
    # regista is only self-consistent; dossier is absent and not counted.
    assert result.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert result.unbound == ("regista",)
    assert "no release-identity binding for: regista" in result.note


def test_require_binding_turns_an_unbound_install_red(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {"regista": _provenance(dist_info, archive_url=wheel.as_uri())}
    lenient = verify_installed_artifacts(manifest, provenance)
    strict = verify_installed_artifacts(manifest, provenance, require_binding=True)
    assert lenient.ok
    assert not strict.ok
    assert "no cryptographic binding" in strict.note


def test_require_binding_is_satisfied_by_the_wheel_chain(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {"regista": _provenance(dist_info, archive_url=wheel.as_uri())}
    result = verify_installed_artifacts(
        manifest, provenance, wheels_dir=wheel.parent, require_binding=True
    )
    assert result.ok, result.note
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert result.unbound == ()


def test_missing_provenance_record_is_named_not_assumed_ok() -> None:
    manifest = _manifest()
    result = verify_installed_artifacts(manifest, {})
    assert result.ok  # nothing installed to contradict the manifest
    assert result.note == "no installed artifact matched a manifest constituent"
    assert all(
        c.strength is AttestationStrength.NOT_APPLICABLE for c in result.components
    )


def test_umbrella_artifact_is_attested_when_present(
    wheel_and_install: tuple[Path, Path],
) -> None:
    """A v2 manifest's umbrella entry participates in attestation (WI-035)."""
    wheel, dist_info = wheel_and_install
    lock = SuiteLock(
        release="1.0.0-dev",
        regista_quad=_QUAD,
        components={"regista": ComponentPin("hraedon/regista", _VERSION, "a" * 40)},
    )
    manifest = build_manifest(
        lock=lock,
        lock_text=serialize_lock(lock),
        release_tag="v1.0.0-rc.9",
        umbrella_tag_sha="c" * 40,
        umbrella_package_version=_VERSION,
        umbrella_wheel=(_WHEEL_NAME, _sha256_file(wheel)),
        generated_at=_FIXED_TIMESTAMP,
    )
    assert manifest.umbrella_artifact is not None
    provenance = {
        "regista": _provenance(None, mode=InstallMode.ABSENT),
        "agent-suite": _provenance(dist_info, archive_url=wheel.as_uri()),
    }
    result = verify_installed_artifacts(
        manifest, provenance, wheels_dir=wheel.parent, require_binding=True
    )
    assert result.ok, result.note
    idents = [c.component for c in result.components]
    assert "agent-suite" in idents


def test_format_text_names_the_rung_and_the_failures(
    wheel_and_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = wheel_and_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, "2" * 64)})
    provenance = {"regista": _provenance(dist_info, archive_url=wheel.as_uri())}
    result = verify_installed_artifacts(manifest, provenance, wheels_dir=wheel.parent)
    text = format_text(result)
    assert "artifact attestation: FAILED" in text
    assert "wheel_sha256 mismatch" in text
    assert isinstance(result, ArtifactAttestation)
    # The JSON shape carries the binding answer explicitly.
    payload = result.to_dict()
    assert payload["binds_release_identity"] is False
    assert isinstance(payload["components"], list)
