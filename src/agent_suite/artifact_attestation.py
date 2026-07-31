"""Artifact-era attestation — bind *installed* components to a release manifest.

Wheel-installed components carry no VCS revision by construction (PEP 610
records ``archive_info``, not ``vcs_info``), so the lock check degrades to a
version-only comparison. A version string is a *claim*, not evidence. This
module supplies the artifact-era strengthening — and, just as importantly, it
refuses to overstate what that strengthening proves.

## What the strong rung actually proves

:attr:`AttestationStrength.WHEEL_HASH_CHAIN` verifies, cryptographically:
manifest ``wheel_sha256`` → the wheel's bytes → the ``RECORD`` *inside* that
wheel (covered by the same hash) → the SHA-256 of **every file the wheel
shipped**.

That is the honest claim, and it is narrower than "every file the interpreter
executes". Hashing the files a wheel shipped does **not** bind:

- **Bytecode caches.** ``__pycache__/*.pyc`` is written by pip at install time
  with an *empty* ``RECORD`` digest, or created lazily by the interpreter at
  first import when the installer did not compile (uv's default). CPython loads
  a cached ``.pyc`` in preference to its source whenever the cache header's
  source mtime+size match, *without reading the source* — so a forged ``.pyc``
  executes while the ``.py`` digest stays pristine. No digest anywhere covers
  it.
- **Installer-generated files.** Console scripts (``bin/<name>``),
  ``INSTALLER``, ``REQUESTED`` and ``direct_url.json`` are written by the
  installer, not shipped by the wheel, so they are absent from the wheel
  ``RECORD`` and are only covered by the install's own (unsigned, rewritable)
  ``RECORD``.
- **Anything simply added to the tree.** A ``.pth`` file dropped into
  ``site-packages`` executes on every interpreter start and appears in no
  ``RECORD`` at all.
- **Relocated ``*.data/`` payloads**, whose install location a wheel ``RECORD``
  path does not describe.

Rather than let those classes pass silently, every one of them is *enumerated
and named* as :class:`Unattested`, and any component with unattested content
reports ``binds_release_identity: false`` no matter how strong its rung —
because on such a tree the rung does not answer the question the operator is
actually asking. Routine health does not fail on unattested content (a
runtime-generated ``.pyc`` on a correct host is not evidence of compromise);
``require_binding`` does, which is what platform qualification wants.

## The ladder

1. :attr:`AttestationStrength.WHEEL_HASH_CHAIN` — as above. Requires the
   release wheel to still be reachable (``--wheels-dir``). Neither uv nor pip
   retains it, and a wheel's SHA-256 **cannot be reconstructed** from the
   unpacked tree (a wheel is a ZIP; member order, timestamps and compression do
   not survive unpacking), so any check claiming to recompute ``wheel_sha256``
   from ``site-packages`` would be a lie.
2. :attr:`AttestationStrength.RECORDED_ARCHIVE_HASH` — PEP 610
   ``archive_info.hashes`` recorded at install time, compared to the manifest.
   A true binding of the installed *distribution* to the artifact bytes, silent
   about later edits. Opportunistic: pip records it for a hashed URL; **uv
   installing from a local wheel file records** ``archive_info: {}``.
3. :attr:`AttestationStrength.INSTALL_RECORD_ONLY` — installed files match the
   install's own ``RECORD``. Real cryptography, but ``RECORD`` is unsigned and
   lives in the writable tree it describes, so it proves internal consistency,
   not provenance. Never reported as binding.
4. :attr:`AttestationStrength.VERSION_ONLY` — version and the PEP 610 wheel
   *filename* agree with the manifest. Not cryptographic at all.
5. :attr:`AttestationStrength.NO_PROVENANCE` — the manifest names a component
   whose runtime provenance could not be read. A **gap**, counted against
   ``require_binding``; never silently "not applicable".

An install receipt written at deploy time was considered and rejected: it would
live in the same writable tree as ``RECORD``, forgeable by exactly the same
actor, so it would add ceremony without adding strength.

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
import re
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
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
_MAX_EXAMPLES = 4
# A generated console script imports its entry point; this is the line every
# mainstream installer emits (pip, uv, `installer`, hatch).
_SCRIPT_IMPORT_RE = re.compile(
    r"^\s*from\s+(?P<module>[\w.]+)\s+import\s+(?P<attr>\w+)", re.MULTILINE
)


class AttestationStrength(Enum):
    """How strongly an installed component is tied to the release manifest.

    Ordered strongest → weakest. ``assert_never`` is used over this enum so a
    newly added rung can't be silently unhandled in the labelling or the
    binding decision.
    """

    WHEEL_HASH_CHAIN = "wheel_hash_chain"
    RECORDED_ARCHIVE_HASH = "recorded_archive_hash"
    INSTALL_RECORD_ONLY = "install_record_only"
    VERSION_ONLY = "version_only"
    NO_PROVENANCE = "no_provenance"
    NOT_APPLICABLE = "not_applicable"


_STRENGTH_ORDER: tuple[AttestationStrength, ...] = (
    AttestationStrength.WHEEL_HASH_CHAIN,
    AttestationStrength.RECORDED_ARCHIVE_HASH,
    AttestationStrength.INSTALL_RECORD_ONLY,
    AttestationStrength.VERSION_ONLY,
    AttestationStrength.NO_PROVENANCE,
    AttestationStrength.NOT_APPLICABLE,
)


class UnattestedKind(Enum):
    """A class of content in the attested tree that hashing cannot bind.

    ``assert_never`` is used over this enum so a newly recognised class can't
    be silently unlabelled.
    """

    BYTECODE_CACHE = "bytecode_cache"
    UNRECORDED_FILE = "unrecorded_file"
    BLANK_DIGEST = "blank_digest"
    RELOCATED_DATA = "relocated_data"
    SITE_CUSTOMIZATION = "site_customization"
    INSTALLER_GENERATED = "installer_generated"
    WHEEL_UNAVAILABLE = "wheel_unavailable"


def unattested_kind_label(kind: UnattestedKind) -> str:
    """Say exactly why this class of content is outside the hash chain."""
    match kind:
        case UnattestedKind.BYTECODE_CACHE:
            return (
                "bytecode cache covered by no digest; CPython may execute it in "
                "preference to the verified source"
            )
        case UnattestedKind.UNRECORDED_FILE:
            return "file present in the install tree but recorded by no RECORD"
        case UnattestedKind.BLANK_DIGEST:
            return "RECORD row carries no digest, so the file is unverifiable"
        case UnattestedKind.RELOCATED_DATA:
            return "*.data/ payload relocated at install time; RECORD path does not locate it"
        case UnattestedKind.SITE_CUSTOMIZATION:
            return (
                "*.pth file in site-packages accounted for by no installed "
                "distribution; it executes on every interpreter start"
            )
        case UnattestedKind.INSTALLER_GENERATED:
            return (
                "installer-generated file (console script, INSTALLER, direct_url.json); "
                "not shipped by the wheel, so the manifest hash does not cover it"
            )
        case UnattestedKind.WHEEL_UNAVAILABLE:
            return "release wheel not present, so the hash chain could not be attempted"
        case other:
            assert_never(other)


@dataclass(frozen=True)
class Unattested:
    """One named class of unattestable content, with bounded examples."""

    kind: UnattestedKind
    count: int
    examples: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "reason": unattested_kind_label(self.kind),
            "count": self.count,
            "examples": list(self.examples),
        }


def binds_release_identity(strength: AttestationStrength) -> bool:
    """Whether this rung ties the install to the manifest at all.

    ``INSTALL_RECORD_ONLY`` returns False on purpose: it verifies the install
    against its own unsigned ``RECORD``, which proves internal consistency, not
    provenance. A rung returning True here is *necessary but not sufficient* —
    see :attr:`ComponentAttestation.binds_release_identity`, which additionally
    requires the tree to hold no unattested content.
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
        case AttestationStrength.NO_PROVENANCE:
            return False
        case AttestationStrength.NOT_APPLICABLE:
            return False
        case other:
            assert_never(other)


def strength_label(strength: AttestationStrength) -> str:
    """Human-readable label naming exactly what was proven."""
    match strength:
        case AttestationStrength.WHEEL_HASH_CHAIN:
            return "wheel hash chain (manifest -> wheel bytes -> every file the wheel shipped)"
        case AttestationStrength.RECORDED_ARCHIVE_HASH:
            return "PEP 610 recorded archive hash matches manifest"
        case AttestationStrength.INSTALL_RECORD_ONLY:
            return "install RECORD self-consistent (not bound to release identity)"
        case AttestationStrength.VERSION_ONLY:
            return "version/filename agreement only (not cryptographic)"
        case AttestationStrength.NO_PROVENANCE:
            return "runtime provenance unavailable — nothing could be attested"
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
    unattested: tuple[Unattested, ...] = ()
    detail: str = ""

    @property
    def binds_release_identity(self) -> bool:
        """True only when a binding rung held **and** nothing is unattested.

        A tree containing a bytecode cache, an unrecorded file or an
        unaccounted ``.pth`` can execute code the hash chain never covered, so
        claiming a release binding for it would be false.
        """
        return binds_release_identity(self.strength) and not self.unattested

    def to_dict(self) -> dict[str, object]:
        return {
            "component": self.component,
            "strength": self.strength.value,
            "binds_release_identity": self.binds_release_identity,
            "rung_binds": binds_release_identity(self.strength),
            "ok": self.ok,
            "expected_version": self.expected_version,
            "installed_version": self.installed_version,
            "expected_wheel_filename": self.expected_wheel_filename,
            "expected_wheel_sha256": self.expected_wheel_sha256,
            "files_verified": self.files_verified,
            "mismatches": list(self.mismatches),
            "unattested": [u.to_dict() for u in self.unattested],
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ArtifactAttestation:
    """Suite-level artifact attestation against one release manifest.

    ``ok`` is False when any attested component mismatched, and — under
    ``require_binding`` — also when any considered component fails to bind or
    when nothing attestable was found at all. That last clause matters: a host
    with every component absent, or every component installed editable, has
    *zero* attestable artifacts, and a qualification gate that returned green
    for it would fail open.
    """

    ok: bool
    release_tag: str
    strength: AttestationStrength
    components: tuple[ComponentAttestation, ...]
    unbound: tuple[str, ...]
    require_binding: bool
    note: str
    wheel_files_checked: int = 0
    wheel_file_mismatches: tuple[str, ...] = ()

    @property
    def unattested_total(self) -> int:
        return sum(u.count for c in self.components for u in c.unattested)

    def to_dict(self) -> dict[str, object]:
        considered = [
            c for c in self.components if c.strength is not AttestationStrength.NOT_APPLICABLE
        ]
        return {
            "ok": self.ok,
            "release_tag": self.release_tag,
            "strength": self.strength.value,
            "binds_release_identity": bool(considered) and not self.unbound,
            "components": [c.to_dict() for c in self.components],
            "unbound": list(self.unbound),
            "unattested_total": self.unattested_total,
            "require_binding": self.require_binding,
            "wheel_files_checked": self.wheel_files_checked,
            "wheel_file_mismatches": list(self.wheel_file_mismatches),
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# RECORD reading — PEP 376 / PEP 427
# ---------------------------------------------------------------------------


def _record_hash_to_hex(value: str) -> str | None:
    """Convert a ``RECORD`` hash field (``sha256=<urlsafe-b64-nopad>``) to hex.

    Returns ``None`` for an empty field or any non-sha256 / malformed value.
    Callers must treat ``None`` as **unverifiable**, never as "skip silently":
    pip writes ``__pycache__`` rows with an empty digest, and an attacker can
    blank any row they can already write.
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


_SCHEME_TAIL_DIRS = ("lib", "lib64", "local")


def _install_root(site_packages: Path) -> Path:
    """The environment prefix a ``RECORD`` may legitimately reach into.

    ``RECORD`` paths are relative to ``site-packages`` but console scripts sit
    at ``../../../bin/<name>``. Rather than trusting arbitrary traversal out of
    an unsigned file, resolve the containing environment and refuse to read
    outside it.

    A venv is identified by ``pyvenv.cfg``. A non-venv install has no such
    marker, so the prefix is derived by stripping the recognised scheme tail:
    ``<prefix>/lib/python3.12/site-packages``,
    ``<prefix>/lib64/python3.12/site-packages``,
    ``/usr/lib/python3/dist-packages``, ``~/.local/lib/python3.12/site-packages``
    and Windows' ``<prefix>/Lib/site-packages`` all reduce to ``<prefix>``.
    Getting this wrong reds a *pristine* SYSTEM / PIP_USER / dist-packages
    install, which this codebase explicitly models (review MINOR-1), so the
    fallback must not be ``site_packages`` itself.
    """
    for candidate in (site_packages, *site_packages.parents[:5]):
        if (candidate / "pyvenv.cfg").is_file():
            return candidate
    current = site_packages
    if current.name.lower() in ("site-packages", "dist-packages"):
        current = current.parent
    if current.name.lower().startswith("python"):
        current = current.parent
    if current.name.lower() in _SCHEME_TAIL_DIRS:
        current = current.parent
    return current


# ---------------------------------------------------------------------------
# Coverage accounting
# ---------------------------------------------------------------------------


@dataclass
class _Coverage:
    """Running account of what was proven, what failed, and what cannot be."""

    mismatches: list[str] = field(default_factory=list)
    verified: int = 0
    unattested: dict[UnattestedKind, list[str]] = field(default_factory=dict)

    def note_unattested(self, kind: UnattestedKind, example: str) -> None:
        self.unattested.setdefault(kind, []).append(example)

    def to_unattested(self) -> tuple[Unattested, ...]:
        return tuple(
            Unattested(
                kind=kind,
                count=len(examples),
                examples=tuple(sorted(examples)[:_MAX_EXAMPLES]),
            )
            for kind, examples in sorted(
                self.unattested.items(), key=lambda item: item[0].value
            )
        )


def _verify_entries(
    entries: dict[str, str | None],
    site_packages: Path,
    root: Path,
    *,
    label: str,
    coverage: _Coverage,
    record_name: str,
) -> None:
    """Verify each ``RECORD`` row, accounting for rows that cannot be verified."""
    for relative, expected in sorted(entries.items()):
        if relative == record_name:
            continue  # RECORD cannot contain its own digest
        if ".data/" in relative:
            # PEP 427 relocates *.data/ payloads at install time, so the RECORD
            # path does not describe where the file landed. A gap, not a
            # mismatch — otherwise the first component shipping data_files
            # would red every attestation (review MINOR-4).
            coverage.note_unattested(UnattestedKind.RELOCATED_DATA, relative)
            continue
        if expected is None:
            # pip writes __pycache__ rows with an empty digest, and an attacker
            # can blank any row they can write. Either way the file is
            # unverifiable and must be named, not skipped (review MAJOR-1).
            kind = (
                UnattestedKind.BYTECODE_CACHE
                if relative.endswith(".pyc")
                else UnattestedKind.BLANK_DIGEST
            )
            coverage.note_unattested(kind, relative)
            continue
        target = site_packages / relative
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            coverage.mismatches.append(
                f"{label}: {relative} resolves outside the install root; refusing to read"
            )
            continue
        if not resolved.is_file():
            coverage.mismatches.append(f"{label}: {relative} is recorded but missing on disk")
            continue
        try:
            actual = _sha256_file(resolved)
        except OSError as exc:
            coverage.mismatches.append(f"{label}: {relative} unreadable ({exc.strerror or exc})")
            continue
        if actual != expected:
            coverage.mismatches.append(
                f"{label}: {relative} digest mismatch — "
                f"recorded={expected[:16]}... actual={actual[:16]}..."
            )
            continue
        coverage.verified += 1


def _owned_directories(entries: dict[str, str | None], site_packages: Path) -> list[Path]:
    """Directories under site-packages that this distribution owns.

    Derived from its own ``RECORD`` so the walk never wanders into a sibling
    distribution's files. Rows reaching outside site-packages (console scripts)
    are excluded — they are handled separately.
    """
    names: set[str] = set()
    for relative in entries:
        if "/" not in relative:
            continue
        head = relative.split("/", 1)[0]
        if not head or head in (".", "..") or head.startswith(".."):
            continue
        if (site_packages / head).is_dir():
            names.add(head)
    return [site_packages / name for name in sorted(names)]


def _scan_owned_tree(
    entries: dict[str, str | None],
    site_packages: Path,
    *,
    coverage: _Coverage,
) -> None:
    """Flag files present in the owned tree that no ``RECORD`` row covers.

    This is the check that catches an injected ``__pycache__/*.pyc`` where the
    installer wrote none (uv's default), and any other file added to a package
    directory after install (review MAJOR-1 exploits A and C).
    """
    for directory in _owned_directories(entries, site_packages):
        try:
            walked = sorted(directory.rglob("*"))
        except OSError:
            continue
        for path in walked:
            try:
                if not path.is_file():
                    continue
                relative = path.relative_to(site_packages).as_posix()
            except (OSError, ValueError):
                continue
            if relative in entries:
                continue
            kind = (
                UnattestedKind.BYTECODE_CACHE
                if path.suffix == ".pyc"
                else UnattestedKind.UNRECORDED_FILE
            )
            coverage.note_unattested(kind, relative)


def _environment_pth_files(site_packages: Path) -> list[str]:
    """``*.pth`` files in ``site-packages`` no installed distribution accounts for.

    A ``.pth`` executes on every interpreter start and is in no wheel's
    ``RECORD`` when an attacker drops it (review MAJOR-1 exploit C).
    Legitimate ones exist too — ``_virtualenv.pth``,
    ``distutils-precedence.pth`` — placed by the venv seeder rather than by a
    wheel, and equally unrecorded. So this is reported as an unattested class
    rather than a mismatch. The accounted-for set is the union of every
    ``*.dist-info/RECORD`` in the same directory, so a ``.pth`` that a real
    distribution *did* ship never shows up here.
    """
    accounted: set[str] = set()
    try:
        dist_infos = sorted(site_packages.glob("*.dist-info"))
        candidates = sorted(site_packages.glob("*.pth"))
    except OSError:
        return []
    for dist_info in dist_infos:
        try:
            text = (dist_info / "RECORD").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        accounted.update(_parse_record(text))
    return [path.name for path in candidates if path.name not in accounted]


def _console_script_rows(entries: dict[str, str | None]) -> list[str]:
    """``RECORD`` rows that install a script outside site-packages."""
    rows: list[str] = []
    for relative in entries:
        if not relative.startswith("../"):
            continue
        if any(part in ("bin", "Scripts") for part in relative.split("/")):
            rows.append(relative)
    return sorted(rows)


def _declared_console_targets(entry_points_text: str | None) -> set[tuple[str, str]]:
    """Parse ``entry_points.txt`` into the declared ``(module, attr)`` set."""
    targets: set[tuple[str, str]] = set()
    if not entry_points_text:
        return targets
    section = ""
    for raw_line in entry_points_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            continue
        if section != "console_scripts" or "=" not in line:
            continue
        value = line.split("=", 1)[1].strip()
        module, _, attr = value.partition(":")
        targets.add((module.strip(), attr.strip() or "main"))
    return targets


def _check_console_script_targets(
    rows: list[str],
    site_packages: Path,
    root: Path,
    declared: set[tuple[str, str]],
    *,
    label: str,
    coverage: _Coverage,
) -> None:
    """Assert each console script still points at a manifest-declared target.

    The script body is installer-generated, so no manifest hash covers it —
    which is exactly how a tampered ``bin/<name>`` slipped through with its
    install-``RECORD`` digest blanked (review MAJOR-1 exploit B). The wheel's
    ``entry_points.txt`` *is* covered by the manifest wheel hash, so a script
    whose import target is not among the declared console scripts is a hard
    mismatch. This does not prove the whole script body, so the script is still
    reported as installer-generated and therefore unattested.
    """
    for relative in rows:
        target = site_packages / relative
        try:
            resolved = target.resolve()
            resolved.relative_to(root)
        except (OSError, RuntimeError, ValueError):
            continue
        if not resolved.is_file():
            continue
        coverage.note_unattested(UnattestedKind.INSTALLER_GENERATED, relative)
        if not declared:
            continue
        try:
            body = resolved.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        found = _SCRIPT_IMPORT_RE.search(body)
        if found is None:
            continue
        pair = (found.group("module"), found.group("attr"))
        if pair not in declared:
            coverage.mismatches.append(
                f"{label}: console script {relative} imports "
                f"{pair[0]}:{pair[1]}, which is not a console_scripts entry point "
                "the release wheel declared"
            )


# ---------------------------------------------------------------------------
# Wheel reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _WheelContent:
    sha256: str
    record: dict[str, str | None]
    record_name: str
    entry_points: str | None


def _read_wheel(wheel: Path) -> _WheelContent:
    """Read a wheel **once** into memory, then hash and parse the same bytes.

    Two independent opens would mean the in-wheel ``RECORD`` is only "covered
    by the same hash" if nothing rewrote the file between reads — in a deploy
    directory whose write access is precisely the threat model (review
    MINOR-3). Raises ``ValueError`` on any unreadable or malformed wheel.
    """
    try:
        raw = wheel.read_bytes()
    except OSError as exc:
        raise ValueError(f"wheel {wheel.name} is unreadable: {exc}") from exc
    digest = hashlib.sha256(raw).hexdigest()
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/RECORD") and name.count("/") == 1
            ]
            if len(names) != 1:
                raise ValueError(
                    f"wheel {wheel.name} does not contain exactly one dist-info/RECORD"
                )
            record_name = names[0]
            record = _parse_record(archive.read(record_name).decode("utf-8"))
            entry_points: str | None = None
            ep_name = record_name.rsplit("/", 1)[0] + "/entry_points.txt"
            if ep_name in archive.namelist():
                entry_points = archive.read(ep_name).decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, UnicodeDecodeError, KeyError) as exc:
        raise ValueError(f"wheel {wheel.name} is unreadable: {exc}") from exc
    return _WheelContent(
        sha256=digest,
        record=record,
        record_name=record_name,
        entry_points=entry_points,
    )


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


def _terminal(
    ident: str,
    expected: ConstituentArtifact,
    detail: str,
    *,
    strength: AttestationStrength,
) -> ComponentAttestation:
    return ComponentAttestation(
        component=ident,
        strength=strength,
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
    pth_cache: dict[Path, list[str]] | None = None,
) -> ComponentAttestation:
    """Attest one installed component against its manifest constituent.

    Climbs the strength ladder documented in the module docstring, reports the
    strongest rung actually reachable, and enumerates every class of content in
    the tree that no digest covers.
    """
    ident = expected.ident
    if provenance.mode is InstallMode.ABSENT:
        return _terminal(
            ident,
            expected,
            "component CLI is absent on this host",
            strength=AttestationStrength.NOT_APPLICABLE,
        )
    if provenance.mode is InstallMode.UNKNOWN:
        return _terminal(
            ident,
            expected,
            "install mode could not be determined; nothing could be attested",
            strength=AttestationStrength.NO_PROVENANCE,
        )
    if provenance.source in (
        ArtifactSource.EDITABLE,
        ArtifactSource.LOCAL,
        ArtifactSource.VCS,
    ):
        return _terminal(
            ident,
            expected,
            f"installed from {provenance.source.value}, not a release wheel — "
            "revision drift is the lock check's job here",
            strength=AttestationStrength.NOT_APPLICABLE,
        )

    coverage = _Coverage()

    # Rung 4 evidence: version, and the filename the installer recorded.
    if provenance.version != expected.package_version:
        coverage.mismatches.append(
            f"{ident}: version mismatch — manifest={expected.package_version} "
            f"installed={provenance.version}"
        )
    if provenance.archive_url and expected.wheel_filename:
        installed_from = _url_basename(provenance.archive_url)
        if installed_from is not None and installed_from != expected.wheel_filename:
            coverage.mismatches.append(
                f"{ident}: installed from {installed_from!r} but the manifest "
                f"records {expected.wheel_filename!r}"
            )
    strength = AttestationStrength.VERSION_ONLY
    detail = "no cryptographic evidence available for this install"

    install_entries: dict[str, str | None] | None = None
    site_packages: Path | None = None
    root: Path | None = None
    install_record_name = ""
    if provenance.dist_info_path:
        dist_info = Path(provenance.dist_info_path)
        site_packages = dist_info.parent
        install_record_name = f"{dist_info.name}/RECORD"
        try:
            root = _install_root(site_packages).resolve()
        except (OSError, RuntimeError):
            root = None
        try:
            install_entries = _parse_record(
                (dist_info / "RECORD").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeDecodeError) as exc:
            coverage.mismatches.append(f"{ident}: install RECORD is unreadable ({exc})")

    # Rung 1: the release wheel is still on the host — the full chain.
    # A missing wheel is an unavoidable evidence gap, not a mismatch (review
    # MINOR-2), and it is only worth *reporting* as a gap when no other rung
    # ended up supplying a binding — see the deferred note below.
    wheel_content: _WheelContent | None = None
    wheel_absent: str | None = None
    if expected.wheel_sha256 and expected.wheel_filename and wheels_dir is not None:
        wheel = wheels_dir / expected.wheel_filename
        if not wheel.is_file():
            wheel_absent = expected.wheel_filename
        else:
            try:
                candidate = _read_wheel(wheel)
            except ValueError as exc:
                coverage.mismatches.append(f"{ident}: {exc}")
            else:
                if candidate.sha256 != expected.wheel_sha256:
                    coverage.mismatches.append(
                        f"{ident}: wheel_sha256 mismatch — "
                        f"recorded={expected.wheel_sha256} actual={candidate.sha256}"
                    )
                else:
                    wheel_content = candidate
    elif expected.wheel_sha256:
        wheel_absent = expected.wheel_filename or "(unnamed)"

    # Verify the tree. Wheel ``RECORD`` rows are authoritative (covered by the
    # manifest hash); install-only rows are installer-generated and can only be
    # checked against the install's own RECORD.
    if site_packages is not None and root is not None and install_entries is not None:
        if wheel_content is not None:
            _verify_entries(
                wheel_content.record,
                site_packages,
                root,
                label=ident,
                coverage=coverage,
                record_name=wheel_content.record_name,
            )
            install_only = {
                key: value
                for key, value in install_entries.items()
                if key not in wheel_content.record
            }
            _verify_entries(
                install_only,
                site_packages,
                root,
                label=ident,
                coverage=coverage,
                record_name=install_record_name,
            )
            _check_console_script_targets(
                _console_script_rows(install_entries),
                site_packages,
                root,
                _declared_console_targets(wheel_content.entry_points),
                label=ident,
                coverage=coverage,
            )
            if not coverage.mismatches:
                strength = AttestationStrength.WHEEL_HASH_CHAIN
                detail = (
                    f"{coverage.verified} file(s) match the RECORD inside the "
                    f"manifest-hashed wheel {expected.wheel_filename}"
                )
        else:
            _verify_entries(
                install_entries,
                site_packages,
                root,
                label=ident,
                coverage=coverage,
                record_name=install_record_name,
            )
            if not coverage.mismatches:
                strength = AttestationStrength.INSTALL_RECORD_ONLY
                detail = f"{coverage.verified} installed file(s) match the install RECORD"
        _scan_owned_tree(install_entries, site_packages, coverage=coverage)
        if pth_cache is None:
            pth_cache = {}
        if site_packages not in pth_cache:
            pth_cache[site_packages] = _environment_pth_files(site_packages)
        for name in pth_cache[site_packages]:
            coverage.note_unattested(UnattestedKind.SITE_CUSTOMIZATION, name)

    # Rung 2: a hash the installer recorded at install time (PEP 610).
    if expected.wheel_sha256 and provenance.archive_sha256:
        if provenance.archive_sha256 != expected.wheel_sha256:
            coverage.mismatches.append(
                f"{ident}: recorded archive sha256 does not match the manifest — "
                f"manifest={expected.wheel_sha256} recorded={provenance.archive_sha256}"
            )
        elif strength is not AttestationStrength.WHEEL_HASH_CHAIN:
            verified_note = (
                f"; {coverage.verified} installed file(s) also match the install RECORD"
                if strength is AttestationStrength.INSTALL_RECORD_ONLY
                else ""
            )
            strength = AttestationStrength.RECORDED_ARCHIVE_HASH
            detail = (
                "installer-recorded archive sha256 matches the manifest wheel hash"
                + verified_note
            )

    # Any mismatch invalidates every rung above version agreement: whatever the
    # chain was going to prove, it did not hold.
    if coverage.mismatches:
        strength = AttestationStrength.VERSION_ONLY
        detail = "verification failed; no rung above version agreement holds"

    # Only report the absent wheel as a gap if nothing else bound this install:
    # a PEP 610 recorded archive hash is a binding in its own right, and calling
    # it "unattested" because the wheel file is gone would understate it.
    if wheel_absent is not None and not binds_release_identity(strength):
        coverage.note_unattested(UnattestedKind.WHEEL_UNAVAILABLE, wheel_absent)

    unattested = coverage.to_unattested()
    if unattested and not coverage.mismatches:
        detail += (
            "; "
            + ", ".join(f"{u.count} {u.kind.value}" for u in unattested)
            + " covered by no digest"
        )

    # Deduplicate while preserving order — the wheel and install passes can name
    # the same file (review MINOR-5).
    seen: set[str] = set()
    ordered: list[str] = []
    for message in coverage.mismatches:
        if message not in seen:
            seen.add(message)
            ordered.append(message)

    return ComponentAttestation(
        component=ident,
        strength=strength,
        ok=not ordered,
        expected_version=expected.package_version,
        installed_version=provenance.version,
        expected_wheel_filename=expected.wheel_filename,
        expected_wheel_sha256=expected.wheel_sha256,
        files_verified=0 if ordered else coverage.verified,
        mismatches=tuple(ordered),
        unattested=unattested,
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

    ``provenance`` must include the umbrella's own record — see
    :func:`agent_suite.runtime_provenance.read_runtime_provenance_with_umbrella`.
    The umbrella is not a lock component, so a plain component probe would leave
    the one distribution the operator runs ``doctor`` *from* unattested
    (review MAJOR-2).

    When ``wheels_dir`` points at the release wheels the deployment installed
    from, the full hash chain is available; the wheel *files* are additionally
    verified for constituents not installed here, so ``--installed
    --wheels-dir`` is a strict superset of the wheels-only check.

    ``require_binding`` turns "no cryptographic binding to the release
    identity" into a failure, **including** the case where nothing attestable
    was found at all — a qualification gate that greened an empty or
    all-editable host would fail open (review MAJOR-3).
    """
    attestations: list[ComponentAttestation] = []
    expected_all: list[ConstituentArtifact] = list(manifest.constituents)
    if manifest.umbrella_artifact is not None:
        expected_all.append(manifest.umbrella_artifact)
    pth_cache: dict[Path, list[str]] = {}
    for expected in expected_all:
        record = provenance.get(expected.ident)
        if record is None:
            attestations.append(
                _terminal(
                    expected.ident,
                    expected,
                    "manifest constituent has no runtime provenance record; "
                    "nothing could be attested",
                    strength=AttestationStrength.NO_PROVENANCE,
                )
            )
            continue
        attestations.append(
            attest_component(expected, record, wheels_dir=wheels_dir, pth_cache=pth_cache)
        )

    # Wheel files for constituents that are not installed on this host, so
    # ``--installed --wheels-dir`` subsumes the wheels-only verification.
    wheel_files_checked = 0
    wheel_file_mismatches: list[str] = []
    if wheels_dir is not None:
        attested_here = {
            a.component
            for a in attestations
            if a.strength
            not in (AttestationStrength.NOT_APPLICABLE, AttestationStrength.NO_PROVENANCE)
        }
        for expected in expected_all:
            if expected.ident in attested_here or not expected.wheel_sha256:
                continue
            wheel = wheels_dir / expected.wheel_filename
            if not wheel.is_file():
                wheel_file_mismatches.append(
                    f"{expected.ident}: wheel {expected.wheel_filename!r} "
                    f"not found in {wheels_dir}"
                )
                continue
            try:
                actual = _sha256_file(wheel)
            except OSError as exc:
                wheel_file_mismatches.append(
                    f"{expected.ident}: wheel {wheel.name} unreadable ({exc})"
                )
                continue
            wheel_files_checked += 1
            if actual != expected.wheel_sha256:
                wheel_file_mismatches.append(
                    f"{expected.ident}: wheel_sha256 mismatch — "
                    f"recorded={expected.wheel_sha256} actual={actual}"
                )

    considered = [
        a for a in attestations if a.strength is not AttestationStrength.NOT_APPLICABLE
    ]
    unbound = tuple(a.component for a in considered if not a.binds_release_identity)
    strength = _weakest([a.strength for a in considered])
    mismatch_count = sum(len(a.mismatches) for a in attestations) + len(
        wheel_file_mismatches
    )
    ok = mismatch_count == 0 and not (require_binding and (unbound or not considered))

    if mismatch_count:
        note = f"{mismatch_count} artifact mismatch(es)"
    elif not considered:
        note = (
            "no installed artifact matched a manifest constituent — "
            "there is nothing here to attest"
        )
    elif unbound and require_binding:
        note = "no cryptographic binding to the release identity for: " + ", ".join(unbound)
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
        wheel_files_checked=wheel_files_checked,
        wheel_file_mismatches=tuple(wheel_file_mismatches),
    )


def format_text(result: ArtifactAttestation) -> str:
    """Human-readable summary naming the strength of each component's evidence."""
    verdict = "ok" if result.ok else "FAILED"
    lines = [
        f"artifact attestation: {verdict} ({result.release_tag}) — {result.note}",
        f"  weakest rung across attested components: {strength_label(result.strength)}",
    ]
    if result.unattested_total:
        lines.append(
            f"  {result.unattested_total} file(s) in the attested trees are covered by "
            "no digest, so no release binding is claimed for them"
        )
    for c in result.components:
        flag = "ok  " if c.ok else "FAIL"
        bound = "bound" if c.binds_release_identity else "unbound"
        lines.append(f"  {flag} {c.component:<24} {c.strength.value:<22} {bound}  {c.detail}")
        for m in c.mismatches:
            lines.append(f"         {m}")
        for u in c.unattested:
            lines.append(
                f"         unattested: {u.count} {u.kind.value} "
                f"({', '.join(u.examples)}) — {unattested_kind_label(u.kind)}"
            )
    if result.wheel_files_checked or result.wheel_file_mismatches:
        lines.append(
            "  wheel files verified for non-installed constituents: "
            f"{result.wheel_files_checked}"
        )
        for m in result.wheel_file_mismatches:
            lines.append(f"         {m}")
    return "\n".join(lines)


__all__ = [
    "ArtifactAttestation",
    "AttestationStrength",
    "ComponentAttestation",
    "Unattested",
    "UnattestedKind",
    "attest_component",
    "binds_release_identity",
    "format_text",
    "strength_label",
    "unattested_kind_label",
    "verify_installed_artifacts",
]
