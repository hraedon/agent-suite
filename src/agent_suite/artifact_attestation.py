"""Artifact-era attestation — bind *installed* components to a release manifest.

Wheel-installed components carry no VCS revision by construction (PEP 610
records ``archive_info``, not ``vcs_info``), so the lock check degrades to a
version-only comparison. A version string is a *claim*, not evidence: two
different wheels can carry the same version. This module supplies the
artifact-era strengthening — it answers "is the code actually executing on
this host the code the release manifest hashed?"

## What is actually verifiable (and what is not)

uv and pip do **not** retain the wheel file after installing it, so the
original artifact cannot be re-hashed from the installed tree. Neither can
the wheel's SHA-256 be *reconstructed*: a wheel is a ZIP, and its bytes
depend on member order, timestamps and compression, none of which survive
unpacking. Any check claiming to recompute ``wheel_sha256`` from
``site-packages`` would be a lie. What is genuinely available, strongest
first:

1. :attr:`AttestationStrength.WHEEL_HASH_CHAIN` — the full chain. Available
   only when the release wheel file is still reachable (``--wheels-dir``, the
   staged artifacts a wheel deployment installed from). Then:
   manifest ``wheel_sha256`` → the wheel's bytes → the ``RECORD`` *inside*
   that wheel (covered by the same hash) → the SHA-256 of every installed
   file. This is an end-to-end cryptographic binding from the published
   release identity to the bytes on disk that the interpreter imports.
2. :attr:`AttestationStrength.RECORDED_ARCHIVE_HASH` — PEP 610
   ``archive_info.hashes`` recorded at install time, compared against the
   manifest's ``wheel_sha256``. A true binding of the installed distribution
   to the artifact bytes, but it says nothing about whether the unpacked
   files were modified afterwards. Opportunistic: pip records it when
   installing from a hashed URL; **uv installing from a local wheel file
   records** ``archive_info: {}`` **and so supplies nothing here.**
3. :attr:`AttestationStrength.INSTALL_RECORD_ONLY` — every installed file
   matches the digest in the install's own ``RECORD``. This is a real
   cryptographic check and it detects post-install tampering of individual
   files, but it is **not** a binding to the release manifest: ``RECORD`` is
   unsigned and lives in the same writable tree it describes, so anyone able
   to edit a module can edit its digest. Reported as *not binding release
   identity* — deliberately, so nobody reads it as more than it is.
4. :attr:`AttestationStrength.VERSION_ONLY` — the distribution version and
   (when PEP 610 recorded a URL) the installed-from wheel *filename* agree
   with the manifest. Not cryptographic at all. An attacker-supplied wheel
   with the right name and version passes.

An install receipt written at deploy time was considered and rejected here:
it would live in the same writable tree as ``RECORD`` and be forgeable by
exactly the same actor, so it would add ceremony without adding strength.
The honest way to get a cryptographic binding on a wheel host is to keep the
release wheels on the host and point ``--wheels-dir`` at them (path 1), or to
install from a hashed URL so the installer records ``archive_info.hashes``
(path 2).

Design rules (AGENTS.md): stdlib-only, read-only, ``assert_never`` over every
closed-set dispatch, and never a traceback on a malformed artifact — an
unreadable ``RECORD`` is a named mismatch.
"""

from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import io
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never

from agent_suite.release_manifest import ConstituentArtifact, ReleaseManifest
from agent_suite.runtime_provenance import (
    ArtifactSource,
    InstallMode,
    RuntimeProvenance,
)

_CHUNK = 65536


class AttestationStrength(Enum):
    """How strongly an installed component is bound to the release manifest.

    Ordered strongest → weakest. ``assert_never`` is used over this enum so a
    newly added rung can't be silently unhandled in the labelling or the
    binding decision.
    """

    WHEEL_HASH_CHAIN = "wheel_hash_chain"
    RECORDED_ARCHIVE_HASH = "recorded_archive_hash"
    INSTALL_RECORD_ONLY = "install_record_only"
    VERSION_ONLY = "version_only"
    NOT_APPLICABLE = "not_applicable"


_STRENGTH_ORDER: tuple[AttestationStrength, ...] = (
    AttestationStrength.WHEEL_HASH_CHAIN,
    AttestationStrength.RECORDED_ARCHIVE_HASH,
    AttestationStrength.INSTALL_RECORD_ONLY,
    AttestationStrength.VERSION_ONLY,
    AttestationStrength.NOT_APPLICABLE,
)


def binds_release_identity(strength: AttestationStrength) -> bool:
    """Whether this rung cryptographically ties the install to the manifest.

    ``INSTALL_RECORD_ONLY`` returns False on purpose: it verifies the install
    against its own unsigned ``RECORD``, which proves internal consistency,
    not provenance.
    """
    match strength:
        case AttestationStrength.WHEEL_HASH_CHAIN:
            return True
        case AttestationStrength.RECORDED_ARCHIVE_HASH:
            return True
        case AttestationStrength.INSTALL_RECORD_ONLY:
            return False
        case AttestationStrength.VERSION_ONLY:
            return False
        case AttestationStrength.NOT_APPLICABLE:
            return False
        case other:
            assert_never(other)


def strength_label(strength: AttestationStrength) -> str:
    """Human-readable label naming exactly what was proven."""
    match strength:
        case AttestationStrength.WHEEL_HASH_CHAIN:
            return "wheel hash chain (manifest -> wheel bytes -> installed files)"
        case AttestationStrength.RECORDED_ARCHIVE_HASH:
            return "PEP 610 recorded archive hash matches manifest"
        case AttestationStrength.INSTALL_RECORD_ONLY:
            return "install RECORD self-consistent (not bound to release identity)"
        case AttestationStrength.VERSION_ONLY:
            return "version/filename agreement only (not cryptographic)"
        case AttestationStrength.NOT_APPLICABLE:
            return "not an artifact install; manifest wheel attestation does not apply"
        case other:
            assert_never(other)


def _weakest(strengths: list[AttestationStrength]) -> AttestationStrength:
    for candidate in reversed(_STRENGTH_ORDER):
        if candidate in strengths:
            return candidate
    return AttestationStrength.NOT_APPLICABLE


@dataclass(frozen=True)
class ComponentAttestation:
    """The outcome of attesting one installed component against the manifest."""

    component: str
    strength: AttestationStrength
    ok: bool
    expected_version: str
    installed_version: str | None
    expected_wheel_filename: str
    expected_wheel_sha256: str
    files_verified: int
    mismatches: tuple[str, ...]
    detail: str

    @property
    def binds_release_identity(self) -> bool:
        return binds_release_identity(self.strength)

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "strength": self.strength.value,
            "binds_release_identity": self.binds_release_identity,
            "ok": self.ok,
            "expected_version": self.expected_version,
            "installed_version": self.installed_version,
            "expected_wheel_filename": self.expected_wheel_filename,
            "expected_wheel_sha256": self.expected_wheel_sha256,
            "files_verified": self.files_verified,
            "mismatches": list(self.mismatches),
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ArtifactAttestation:
    """Suite-level artifact attestation against one release manifest.

    ``ok`` is False when any attested component mismatched. ``unbound`` names
    the components whose strongest available attestation does not bind release
    identity (rungs 3 and 4) — reported honestly rather than smoothed away,
    because on a uv-tool host with no retained wheels that is the true state.
    ``ok`` only *fails* on an unbound component when the caller asked for
    ``require_binding``.
    """

    ok: bool
    release_tag: str
    strength: AttestationStrength
    components: tuple[ComponentAttestation, ...]
    unbound: tuple[str, ...]
    require_binding: bool
    note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "release_tag": self.release_tag,
            "strength": self.strength.value,
            "binds_release_identity": binds_release_identity(self.strength),
            "components": [c.to_dict() for c in self.components],
            "unbound": list(self.unbound),
            "require_binding": self.require_binding,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# RECORD reading — PEP 376 / PEP 427
# ---------------------------------------------------------------------------


def _record_hash_to_hex(value: str) -> str | None:
    """Convert a ``RECORD`` hash field (``sha256=<urlsafe-b64-nopad>``) to hex.

    Returns ``None`` for an empty field (``RECORD``'s own row) or any
    non-sha256 / malformed value — the caller reports those as unverified
    rather than pretending they passed.
    """
    if not value or not value.startswith("sha256="):
        return None
    raw = value.partition("=")[2]
    padded = raw + "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(padded).hex()
    except (binascii.Error, ValueError):
        return None


def _parse_record(text: str) -> dict[str, str | None]:
    """Parse ``RECORD`` CSV text into ``relative path -> sha256 hex or None``."""
    entries: dict[str, str | None] = {}
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0]:
            continue
        digest = row[1] if len(row) > 1 else ""
        entries[row[0].replace("\\", "/")] = _record_hash_to_hex(digest)
    return entries


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _install_root(site_packages: Path) -> Path:
    """The environment prefix that a ``RECORD`` may legitimately reach into.

    ``RECORD`` paths are relative to ``site-packages`` but console scripts sit
    at ``../../../bin/<name>``. Rather than trusting arbitrary traversal out of
    an unsigned file, resolve the containing environment (the nearest ancestor
    holding ``pyvenv.cfg``) and refuse to read outside it. Falls back to
    ``site-packages`` when there is no venv marker.
    """
    for candidate in (site_packages, *site_packages.parents[:4]):
        if (candidate / "pyvenv.cfg").is_file():
            return candidate
    return site_packages


def _verify_against_record(
    entries: dict[str, str | None],
    site_packages: Path,
    *,
    label: str,
) -> tuple[list[str], int]:
    """Verify installed files against ``entries``; return (mismatches, verified)."""
    try:
        root = _install_root(site_packages).resolve()
    except (OSError, RuntimeError):
        return ([f"{label}: install root could not be resolved; nothing verified"], 0)
    mismatches: list[str] = []
    verified = 0
    for relative, expected in sorted(entries.items()):
        if expected is None:
            continue
        if ".data/" in relative:
            # PEP 427 relocates ``*.data/`` payloads at install time, so the
            # RECORD path does not describe where the file landed.
            mismatches.append(f"{label}: {relative} is a relocated .data entry; not verified")
            continue
        target = (site_packages / relative)
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            mismatches.append(
                f"{label}: {relative} resolves outside the install root; refusing to read"
            )
            continue
        if not resolved.is_file():
            mismatches.append(f"{label}: {relative} is recorded but missing on disk")
            continue
        try:
            actual = _sha256_file(resolved)
        except OSError as exc:
            mismatches.append(f"{label}: {relative} unreadable ({exc.strerror or exc})")
            continue
        if actual != expected:
            mismatches.append(
                f"{label}: {relative} digest mismatch — "
                f"recorded={expected[:16]}... actual={actual[:16]}..."
            )
            continue
        verified += 1
    return mismatches, verified


def _wheel_record(wheel: Path) -> dict[str, str | None]:
    """Read the ``RECORD`` from inside a wheel. Raises ``ValueError`` if absent."""
    try:
        with zipfile.ZipFile(wheel) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/RECORD") and name.count("/") == 1
            ]
            if len(names) != 1:
                raise ValueError(
                    f"wheel {wheel.name} does not contain exactly one dist-info/RECORD"
                )
            return _parse_record(archive.read(names[0]).decode("utf-8"))
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ValueError(f"wheel {wheel.name} is unreadable: {exc}") from exc


def _url_basename(url: str) -> str | None:
    """Filename component of a PEP 610 ``url``, or ``None`` if not derivable."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path
    if parsed.scheme == "file":
        try:
            path = urllib.request.url2pathname(urllib.parse.unquote(parsed.path))
        except (OSError, RuntimeError, ValueError, UnicodeDecodeError):
            return None
    name = Path(path.replace("\\", "/")).name
    return name or None


# ---------------------------------------------------------------------------
# Attesting one component
# ---------------------------------------------------------------------------


def _not_applicable(
    ident: str, expected: ConstituentArtifact, detail: str
) -> ComponentAttestation:
    return ComponentAttestation(
        component=ident,
        strength=AttestationStrength.NOT_APPLICABLE,
        ok=True,
        expected_version=expected.package_version,
        installed_version=None,
        expected_wheel_filename=expected.wheel_filename,
        expected_wheel_sha256=expected.wheel_sha256,
        files_verified=0,
        mismatches=(),
        detail=detail,
    )


def attest_component(
    expected: ConstituentArtifact,
    provenance: RuntimeProvenance,
    *,
    wheels_dir: Path | None = None,
) -> ComponentAttestation:
    """Attest one installed component against its manifest constituent.

    Climbs the strength ladder documented in the module docstring and reports
    the strongest rung that was actually reachable — never a stronger claim
    than the evidence supports.
    """
    ident = expected.ident
    if provenance.mode is InstallMode.ABSENT:
        return _not_applicable(ident, expected, "component CLI is absent on this host")
    if provenance.mode is InstallMode.UNKNOWN:
        return _not_applicable(
            ident, expected, "install mode could not be determined; nothing to attest"
        )
    if provenance.source in (
        ArtifactSource.EDITABLE,
        ArtifactSource.LOCAL,
        ArtifactSource.VCS,
    ):
        return _not_applicable(
            ident,
            expected,
            f"installed from {provenance.source.value}, not a release wheel — "
            "revision drift is the lock check's job here",
        )

    mismatches: list[str] = []

    # Rung 4 evidence: version, and the filename the installer recorded.
    if provenance.version != expected.package_version:
        mismatches.append(
            f"{ident}: version mismatch — manifest={expected.package_version} "
            f"installed={provenance.version}"
        )
    if provenance.archive_url and expected.wheel_filename:
        installed_from = _url_basename(provenance.archive_url)
        if installed_from is not None and installed_from != expected.wheel_filename:
            mismatches.append(
                f"{ident}: installed from {installed_from!r} but the manifest "
                f"records {expected.wheel_filename!r}"
            )
    strength = AttestationStrength.VERSION_ONLY
    detail = "no cryptographic evidence available for this install"
    verified = 0

    # Rung 3: the install's own RECORD. Always attempted when dist-info is
    # locatable — it is the floor of cryptographic self-consistency.
    record_entries: dict[str, str | None] | None = None
    site_packages: Path | None = None
    if provenance.dist_info_path:
        dist_info = Path(provenance.dist_info_path)
        site_packages = dist_info.parent
        try:
            record_entries = _parse_record((dist_info / "RECORD").read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            mismatches.append(f"{ident}: install RECORD is unreadable ({exc})")
    if record_entries is not None and site_packages is not None:
        record_mismatches, verified = _verify_against_record(
            record_entries, site_packages, label=ident
        )
        mismatches.extend(record_mismatches)
        if not record_mismatches:
            strength = AttestationStrength.INSTALL_RECORD_ONLY
            detail = f"{verified} installed file(s) match the install RECORD"

    # Rung 2: a hash the installer recorded at install time (PEP 610).
    if expected.wheel_sha256 and provenance.archive_sha256:
        if provenance.archive_sha256 != expected.wheel_sha256:
            mismatches.append(
                f"{ident}: recorded archive sha256 does not match the manifest — "
                f"manifest={expected.wheel_sha256} recorded={provenance.archive_sha256}"
            )
        elif strength is not AttestationStrength.WHEEL_HASH_CHAIN:
            strength = AttestationStrength.RECORDED_ARCHIVE_HASH
            detail = "installer-recorded archive sha256 matches the manifest wheel hash"

    # Rung 1: the release wheel is still on the host — full chain.
    if expected.wheel_sha256 and expected.wheel_filename and wheels_dir is not None:
        wheel = wheels_dir / expected.wheel_filename
        if not wheel.is_file():
            mismatches.append(
                f"{ident}: wheel {expected.wheel_filename!r} not found in {wheels_dir}"
            )
        else:
            try:
                actual = _sha256_file(wheel)
            except OSError as exc:
                mismatches.append(f"{ident}: wheel {wheel.name} unreadable ({exc})")
                actual = ""
            if actual and actual != expected.wheel_sha256:
                mismatches.append(
                    f"{ident}: wheel_sha256 mismatch — "
                    f"recorded={expected.wheel_sha256} actual={actual}"
                )
            elif actual and site_packages is not None:
                try:
                    wheel_entries = _wheel_record(wheel)
                except ValueError as exc:
                    mismatches.append(f"{ident}: {exc}")
                else:
                    chain_mismatches, chain_verified = _verify_against_record(
                        wheel_entries, site_packages, label=ident
                    )
                    mismatches.extend(chain_mismatches)
                    if not chain_mismatches:
                        strength = AttestationStrength.WHEEL_HASH_CHAIN
                        verified = chain_verified
                        detail = (
                            f"{chain_verified} installed file(s) match the RECORD inside "
                            f"the manifest-hashed wheel {wheel.name}"
                        )
            elif actual:
                mismatches.append(
                    f"{ident}: wheel hash verified but dist-info was not locatable, "
                    "so the installed files could not be chained to it"
                )

    return ComponentAttestation(
        component=ident,
        strength=strength,
        ok=not mismatches,
        expected_version=expected.package_version,
        installed_version=provenance.version,
        expected_wheel_filename=expected.wheel_filename,
        expected_wheel_sha256=expected.wheel_sha256,
        files_verified=verified,
        mismatches=tuple(mismatches),
        detail=detail,
    )


def verify_installed_artifacts(
    manifest: ReleaseManifest,
    provenance: dict[str, RuntimeProvenance],
    *,
    wheels_dir: Path | None = None,
    require_binding: bool = False,
) -> ArtifactAttestation:
    """Attest every installed component (and the umbrella) against ``manifest``.

    ``provenance`` is the map from
    :func:`agent_suite.runtime_provenance.read_runtime_provenance`. When
    ``wheels_dir`` points at the release wheels the deployment installed from,
    the full hash chain is available and used; otherwise the strongest
    reachable rung is reported and named.

    ``require_binding`` turns "no cryptographic binding to the release
    identity" into a failure. Off by default: a wheel host that no longer has
    the wheels cannot produce that binding, and the doctor must not call a
    correct estate red for an unavoidable evidence gap. Platform
    qualification turns it on.
    """
    attestations: list[ComponentAttestation] = []
    expected_all: list[ConstituentArtifact] = list(manifest.constituents)
    if manifest.umbrella_artifact is not None:
        expected_all.append(manifest.umbrella_artifact)
    for expected in expected_all:
        record = provenance.get(expected.ident)
        if record is None:
            attestations.append(
                _not_applicable(
                    expected.ident,
                    expected,
                    "manifest constituent has no runtime provenance record",
                )
            )
            continue
        attestations.append(attest_component(expected, record, wheels_dir=wheels_dir))

    considered = [a for a in attestations if a.strength is not AttestationStrength.NOT_APPLICABLE]
    unbound = tuple(a.component for a in considered if not a.binds_release_identity)
    strength = _weakest([a.strength for a in considered])
    mismatch_count = sum(len(a.mismatches) for a in attestations)
    ok = mismatch_count == 0 and not (require_binding and unbound)

    if mismatch_count:
        note = f"{mismatch_count} artifact mismatch(es)"
    elif not considered:
        note = "no installed artifact matched a manifest constituent"
    elif unbound and require_binding:
        note = (
            "no cryptographic binding to the release identity for: "
            + ", ".join(unbound)
        )
    elif unbound:
        note = (
            f"verified at '{strength.value}'; no release-identity binding for: "
            + ", ".join(unbound)
        )
    else:
        note = f"verified at '{strength.value}'"

    return ArtifactAttestation(
        ok=ok,
        release_tag=manifest.release_tag,
        strength=strength,
        components=tuple(attestations),
        unbound=unbound,
        require_binding=require_binding,
        note=note,
    )


def format_text(result: ArtifactAttestation) -> str:
    """Human-readable summary naming the strength of each component's evidence."""
    verdict = "ok" if result.ok else "FAILED"
    lines = [
        f"artifact attestation: {verdict} ({result.release_tag}) — {result.note}",
        f"  strongest common rung: {strength_label(result.strength)}",
    ]
    for c in result.components:
        flag = "ok  " if c.ok else "FAIL"
        bound = "bound" if c.binds_release_identity else "unbound"
        lines.append(f"  {flag} {c.component:<24} {c.strength.value:<22} {bound}  {c.detail}")
        for m in c.mismatches:
            lines.append(f"         {m}")
    return "\n".join(lines)


__all__ = [
    "ArtifactAttestation",
    "AttestationStrength",
    "ComponentAttestation",
    "attest_component",
    "binds_release_identity",
    "format_text",
    "strength_label",
    "verify_installed_artifacts",
]
