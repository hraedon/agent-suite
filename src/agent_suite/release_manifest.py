"""The immutable release manifest — release-time description of a published candidate.

Sol Gate 0 Workstream 2: "Replace the current tag artifact with an immutable
release manifest. Record umbrella tag SHA, all six constituent SHAs, package
versions, wheel hashes and lock identity."

The manifest is distinct from the candidate inventory (``inventory.py``):
the inventory is the operator-specific live estate state (read at runtime
from checkouts + ``suite.env``), while the manifest is the immutable
release-time description of what was published. The two bind via
:meth:`agent_suite.inventory.Inventory.bind_to_manifest`.

Design rules (AGENTS.md): the core is stdlib-only (``json``, ``hashlib``,
``dataclasses``, ``pathlib``); serialization is deterministic (sorted keys,
no whitespace, no host-derived timestamps in the build path); SHA
validation reuses :func:`agent_suite.lock._is_valid_sha` for consistency;
every closed-set dispatch uses ``assert_never`` so a new subcommand can't
slip through ungated.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from agent_suite import lock as lock_mod
from agent_suite.lock import SuiteLock

# ---------------------------------------------------------------------------
# Schema version — bumped when the manifest shape changes in a way that
# consumers must gate on. v1 is the initial Sol Gate 0 Workstream 2 shape.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "v1"
_UMBRELLA_REPO = "hraedon/agent-suite"


def _wheel_filename(ident: str, version: str) -> str:
    """Construct the expected wheel filename for a component.

    Python wheel filenames use the distribution name with ``-`` → ``_``
    and the tag ``py3-none-any`` for pure-Python wheels. The actual built
    wheel may differ (platform tags, normalization); the manifest records
    what was found, not a guess — see :func:`_collect_wheel_artifacts`.
    """
    dist_name = ident.replace("-", "_")
    return f"{dist_name}-{version}-py3-none-any.whl"


def _source_archive_filename(ident: str, version: str) -> str:
    """Construct the expected sdist tarball filename for a component."""
    dist_name = ident.replace("-", "_")
    return f"{dist_name}-{version}.tar.gz"


def _sha256_file(path: Path) -> str:
    """Compute the SHA-256 hex digest of a file (64-char hex)."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_text(text: str) -> str:
    """Compute the SHA-256 hex digest of a UTF-8 string."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LockIdentity:
    """Identity of the SUITE.lock pinned in this release.

    ``lock_file_sha256`` is the SHA-256 of the SUITE.lock file content as
    it existed at release time. ``release`` is the ``[suite].release``
    value. ``component_count`` is the number of ``[components.*]`` entries
    — a manifest with a different component count than the lock it claims
    to bind to is a structural mismatch.
    """

    lock_file_sha256: str
    release: str
    component_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "lock_file_sha256": self.lock_file_sha256,
            "release": self.release,
            "component_count": self.component_count,
        }


@dataclass(frozen=True)
class ConstituentArtifact:
    """One pinned constituent in the release manifest.

    ``pinned_revision`` is the 40-char SHA from SUITE.lock — the
    reproducible candidate definition. ``wheel_sha256`` and
    ``source_archive_sha256`` are 64-char hex digests of the built
    artifacts. When wheels/sources are not built (e.g. local dev), both
    are empty strings — the manifest honestly records "not provided"
    rather than "failed to compute." A future work item will add the
    wheel-build step to CI; the schema is forward-compatible.
    """

    ident: str
    repo: str
    pinned_revision: str
    package_version: str
    wheel_filename: str
    wheel_sha256: str
    source_archive_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "ident": self.ident,
            "repo": self.repo,
            "pinned_revision": self.pinned_revision,
            "package_version": self.package_version,
            "wheel_filename": self.wheel_filename,
            "wheel_sha256": self.wheel_sha256,
            "source_archive_sha256": self.source_archive_sha256,
        }


@dataclass(frozen=True)
class ReleaseManifest:
    """Immutable release-time description of a published candidate.

    The manifest is NOT committed to main; it is attached to the GitHub
    release on tag push (alongside the candidate inventory). It records
    the umbrella tag SHA, all constituent SHAs, package versions, wheel
    hashes, and the lock identity so a consumer can verify that the
    release they installed matches the published candidate.

    ``manifest_self_sha256`` is the SHA-256 of the manifest serialized
    with ``manifest_self_sha256=""`` — a tamper-evidence field. It is
    computed after the manifest is built; the serialization excludes
    the field itself to avoid circularity.
    """

    schema_version: str
    release_tag: str
    umbrella_repo: str
    umbrella_tag_sha: str
    suite_release: str
    regista_library_version: str
    regista_schema_version: int
    regista_workflow_version: str
    regista_envelope_version: int
    lock_identity: LockIdentity
    constituents: tuple[ConstituentArtifact, ...]
    generated_at: str
    manifest_self_sha256: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "release_tag": self.release_tag,
            "umbrella_repo": self.umbrella_repo,
            "umbrella_tag_sha": self.umbrella_tag_sha,
            "suite_release": self.suite_release,
            "regista_library_version": self.regista_library_version,
            "regista_schema_version": self.regista_schema_version,
            "regista_workflow_version": self.regista_workflow_version,
            "regista_envelope_version": self.regista_envelope_version,
            "lock_identity": self.lock_identity.to_dict(),
            "constituents": [c.to_dict() for c in self.constituents],
            "generated_at": self.generated_at,
            "manifest_self_sha256": self.manifest_self_sha256,
        }


# ---------------------------------------------------------------------------
# Building the manifest — pure (all data passed in; no I/O)
# ---------------------------------------------------------------------------


def build_manifest(
    *,
    lock: SuiteLock,
    lock_text: str,
    release_tag: str,
    umbrella_tag_sha: str,
    umbrella_repo: str = _UMBRELLA_REPO,
    wheel_hashes: dict[str, tuple[str, str]] | None = None,
    source_archive_hashes: dict[str, str] | None = None,
    generated_at: str | None = None,
) -> ReleaseManifest:
    """Build a :class:`ReleaseManifest` from a lock and release inputs.

    This function is pure — all data is passed in; no file I/O or git
    shelling. The CLI resolves the umbrella tag SHA, reads the lock file,
    and collects wheel hashes, then calls this function.

    ``lock`` is the parsed :class:`agent_suite.lock.SuiteLock`.
    ``lock_text`` is the raw SUITE.lock file content (for the
    ``lock_file_sha256``). ``release_tag`` is the git tag (e.g.
    ``"v1.0.0-rc1"``). ``umbrella_tag_sha`` is the SHA of the tagged
    commit in agent-suite (may be ``""`` if unresolvable — honestly
    recorded).

    ``wheel_hashes`` maps component ident → ``(wheel_filename, sha256)``.
    When a component's wheel is not built, it is omitted from the dict
    and the manifest records empty strings for both fields. Same for
    ``source_archive_hashes`` (ident → sha256).

    ``generated_at`` defaults to the current UTC ISO timestamp. Pass
    an explicit value for deterministic test fixtures.

    Raises ``ValueError`` if the lock has no regista quad (the spine is
    required for a release) or if any component lacks a pinned revision
    (a release manifest without pinned revisions is not reproducible).
    """
    if lock.regista_quad is None:
        raise ValueError(
            "release manifest: lock has no regista quad — "
            "the spine is required for a release candidate"
        )

    quad = lock.regista_quad
    gen_at = generated_at if generated_at is not None else datetime.now(UTC).isoformat()
    wh = wheel_hashes or {}
    sah = source_archive_hashes or {}

    constituents: list[ConstituentArtifact] = []
    for ident in sorted(lock.components):
        pin = lock.components[ident]
        if pin.revision is None or not lock_mod._is_valid_sha(pin.revision):
            raise ValueError(
                f"release manifest: component {ident!r} has no valid pinned revision — "
                "a release manifest requires all components pinned to a full SHA"
            )
        wheel_filename, wheel_sha = wh.get(ident, ("", ""))
        source_sha = sah.get(ident, "")
        constituents.append(
            ConstituentArtifact(
                ident=ident,
                repo=pin.repo,
                pinned_revision=pin.revision,
                package_version=pin.version,
                wheel_filename=wheel_filename,
                wheel_sha256=wheel_sha,
                source_archive_sha256=source_sha,
            )
        )

    lock_identity = LockIdentity(
        lock_file_sha256=_sha256_text(lock_text),
        release=lock.release,
        component_count=len(lock.components),
    )

    manifest = ReleaseManifest(
        schema_version=SCHEMA_VERSION,
        release_tag=release_tag,
        umbrella_repo=umbrella_repo,
        umbrella_tag_sha=umbrella_tag_sha,
        suite_release=lock.release,
        regista_library_version=quad.library_version,
        regista_schema_version=quad.schema_version,
        regista_workflow_version=quad.canonical_workflow_version,
        regista_envelope_version=quad.envelope_version,
        lock_identity=lock_identity,
        constituents=tuple(constituents),
        generated_at=gen_at,
        manifest_self_sha256="",
    )

    self_sha = compute_manifest_self_sha256(manifest)
    return replace(manifest, manifest_self_sha256=self_sha)


# ---------------------------------------------------------------------------
# Serialization — deterministic (sorted keys, no whitespace)
# ---------------------------------------------------------------------------


def serialize_manifest(manifest: ReleaseManifest) -> str:
    """Serialize a manifest to deterministic JSON (sorted keys, no whitespace).

    The output is a single-line JSON string with ``sort_keys=True`` and
    ``separators=(",", ":")``. This is the canonical form used for
    :func:`compute_manifest_self_sha256` and for writing the manifest to
    disk. Two manifests with identical fields always produce identical
    bytes, so the self-SHA is a reliable tamper-evidence field.
    """
    return json.dumps(manifest.to_dict(), sort_keys=True, separators=(",", ":"))


def compute_manifest_self_sha256(manifest: ReleaseManifest) -> str:
    """Compute the SHA-256 of the manifest with ``manifest_self_sha256=""``.

    The field is excluded (set to empty) before hashing to avoid
    circularity. The hash covers every other field, including
    ``generated_at``. Two manifests built from the same inputs (same
    lock, same tag, same timestamp) produce the same self-SHA; any
    tampering with a serialized manifest changes the self-SHA.
    """
    bare = replace(manifest, manifest_self_sha256="")
    return _sha256_text(serialize_manifest(bare))


# ---------------------------------------------------------------------------
# Deserialization — validates structure + SHA format
# ---------------------------------------------------------------------------


def _require_str(data: dict[str, object], key: str, context: str) -> str:
    val = data.get(key)
    if not isinstance(val, str):
        raise ValueError(f"release manifest: {context}.{key} must be a string")
    return val


def _require_int(data: dict[str, object], key: str, context: str) -> int:
    val = data.get(key)
    if not isinstance(val, int) or isinstance(val, bool):
        raise ValueError(f"release manifest: {context}.{key} must be an integer")
    return val


def deserialize_manifest(text: str) -> ReleaseManifest:
    """Parse a JSON string into a :class:`ReleaseManifest`.

    Raises ``ValueError`` for structurally invalid manifests (missing
    fields, wrong types, invalid SHA format) so callers can distinguish
    "bad manifest" from "no manifest." Validates ``pinned_revision`` and
    ``umbrella_tag_sha`` (when non-empty) via :func:`lock._is_valid_sha`
    for consistency with the lock's SHA validation.
    """
    raw = json.loads(text)
    if not isinstance(raw, dict):
        raise ValueError("release manifest: expected a JSON object")

    schema_version = _require_str(raw, "schema_version", "manifest")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"release manifest: unsupported schema_version {schema_version!r} "
            f"(expected {SCHEMA_VERSION!r})"
        )

    release_tag = _require_str(raw, "release_tag", "manifest")
    umbrella_repo = _require_str(raw, "umbrella_repo", "manifest")
    umbrella_tag_sha = _require_str(raw, "umbrella_tag_sha", "manifest")
    suite_release = _require_str(raw, "suite_release", "manifest")
    regista_library_version = _require_str(raw, "regista_library_version", "manifest")
    regista_schema_version = _require_int(raw, "regista_schema_version", "manifest")
    regista_workflow_version = _require_str(raw, "regista_workflow_version", "manifest")
    regista_envelope_version = _require_int(raw, "regista_envelope_version", "manifest")
    generated_at = _require_str(raw, "generated_at", "manifest")
    manifest_self_sha256 = _require_str(raw, "manifest_self_sha256", "manifest")

    # umbrella_tag_sha may be "" (unresolvable at build time); validate when non-empty.
    if umbrella_tag_sha and not lock_mod._is_valid_sha(umbrella_tag_sha):
        raise ValueError(
            "release manifest: umbrella_tag_sha must be a 40- or 64-char hex SHA"
        )

    lock_raw = raw.get("lock_identity")
    if not isinstance(lock_raw, dict):
        raise ValueError("release manifest: lock_identity must be an object")
    lock_file_sha256 = _require_str(lock_raw, "lock_file_sha256", "lock_identity")
    lock_release = _require_str(lock_raw, "release", "lock_identity")
    lock_component_count = _require_int(lock_raw, "component_count", "lock_identity")
    lock_identity = LockIdentity(
        lock_file_sha256=lock_file_sha256,
        release=lock_release,
        component_count=lock_component_count,
    )

    const_raw = raw.get("constituents")
    if not isinstance(const_raw, list):
        raise ValueError("release manifest: constituents must be a list")
    constituents: list[ConstituentArtifact] = []
    for c in const_raw:
        if not isinstance(c, dict):
            raise ValueError("release manifest: constituent entry must be an object")
        ident = _require_str(c, "ident", "constituent")
        repo = _require_str(c, "repo", "constituent")
        pinned_revision = _require_str(c, "pinned_revision", "constituent")
        if not lock_mod._is_valid_sha(pinned_revision):
            raise ValueError(
                f"release manifest: constituent {ident!r} pinned_revision must be "
                "a 40- or 64-char hex SHA"
            )
        package_version = _require_str(c, "package_version", "constituent")
        wheel_filename = _require_str(c, "wheel_filename", "constituent")
        wheel_sha256 = _require_str(c, "wheel_sha256", "constituent")
        source_archive_sha256 = _require_str(c, "source_archive_sha256", "constituent")
        constituents.append(
            ConstituentArtifact(
                ident=ident,
                repo=repo,
                pinned_revision=pinned_revision,
                package_version=package_version,
                wheel_filename=wheel_filename,
                wheel_sha256=wheel_sha256,
                source_archive_sha256=source_archive_sha256,
            )
        )

    manifest = ReleaseManifest(
        schema_version=schema_version,
        release_tag=release_tag,
        umbrella_repo=umbrella_repo,
        umbrella_tag_sha=umbrella_tag_sha,
        suite_release=suite_release,
        regista_library_version=regista_library_version,
        regista_schema_version=regista_schema_version,
        regista_workflow_version=regista_workflow_version,
        regista_envelope_version=regista_envelope_version,
        lock_identity=lock_identity,
        constituents=tuple(constituents),
        generated_at=generated_at,
        manifest_self_sha256=manifest_self_sha256,
    )

    # Tamper-evidence: verify the self-SHA matches the content.
    expected_sha = compute_manifest_self_sha256(manifest)
    if manifest_self_sha256 != expected_sha:
        raise ValueError(
            "release manifest: manifest_self_sha256 mismatch — "
            f"recorded={manifest_self_sha256!r} computed={expected_sha!r}. "
            "The manifest was tampered with or corrupted after construction."
        )

    return manifest


# ---------------------------------------------------------------------------
# I/O helpers — used by the CLI (not by build_manifest, which is pure)
# ---------------------------------------------------------------------------


def collect_wheel_artifacts(
    wheels_dir: Path,
    lock: SuiteLock,
) -> dict[str, tuple[str, str]]:
    """Read wheel files from ``wheels_dir`` and return ``ident -> (filename, sha256)``.

    Looks for a wheel matching ``{dist_name}-{version}-*.whl`` in the
    directory. When found, returns the actual filename and its SHA-256.
    When not found, the component is omitted from the result (the
    manifest records empty strings for it — honest "not provided").
    """
    result: dict[str, tuple[str, str]] = {}
    for ident in sorted(lock.components):
        pin = lock.components[ident]
        dist_name = ident.replace("-", "_")
        # Match {dist_name}-{version}-*.whl; the tag portion may differ
        # from the default py3-none-any if the wheel has C extensions.
        prefix = f"{dist_name}-{pin.version}-"
        candidates = [
            p for p in wheels_dir.glob(f"{prefix}*.whl")
            if p.is_file()
        ]
        if candidates:
            # Prefer the py3-none-any wheel if present; else the first match.
            wheel = candidates[0]
            for c in candidates:
                if "py3-none-any" in c.name:
                    wheel = c
                    break
            result[ident] = (wheel.name, _sha256_file(wheel))
    return result


def collect_source_artifacts(
    sources_dir: Path,
    lock: SuiteLock,
) -> dict[str, str]:
    """Read sdist tarballs from ``sources_dir`` and return ``ident -> sha256``.

    Looks for ``{dist_name}-{version}.tar.gz`` in the directory. When
    found, returns its SHA-256. When not found, the component is omitted
    (the manifest records an empty string).
    """
    result: dict[str, str] = {}
    for ident in sorted(lock.components):
        pin = lock.components[ident]
        dist_name = ident.replace("-", "_")
        candidate = sources_dir / f"{dist_name}-{pin.version}.tar.gz"
        if candidate.is_file():
            result[ident] = _sha256_file(candidate)
    return result


# ---------------------------------------------------------------------------
# CLI subcommand dispatch — closed set with assert_never
# ---------------------------------------------------------------------------


class ReleaseManifestSubcommand(Enum):
    """The closed set of ``agent-suite release-manifest`` subcommands.

    ``assert_never`` is used over this enum so a newly added subcommand
    can't be silently unhandled in the CLI dispatch.
    """

    BUILD = "build"
    VERIFY = "verify"


@dataclass(frozen=True)
class ManifestVerifyResult:
    """The outcome of verifying a manifest against local artifacts.

    ``mismatches`` is a list of per-constituent named mismatches. The
    result is ``ok`` only when there are no mismatches and the manifest's
    self-SHA is valid (deserialization already checks the self-SHA).
    """

    ok: bool
    release_tag: str
    mismatches: list[str]
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "release_tag": self.release_tag,
            "mismatches": list(self.mismatches),
            "note": self.note,
        }


def verify_manifest_against_wheels(
    manifest: ReleaseManifest,
    wheels_dir: Path,
) -> ManifestVerifyResult:
    """Verify that the wheel hashes in the manifest match the local wheels.

    For each constituent whose ``wheel_sha256`` is non-empty, recompute
    the hash from the wheel file in ``wheels_dir`` and assert it matches.
    Constituents with empty ``wheel_sha256`` (not provided at build time)
    are skipped — the manifest honestly recorded "not provided," and
    there's nothing to verify against.

    Returns a :class:`ManifestVerifyResult` with named mismatches.
    """
    mismatches: list[str] = []
    for c in manifest.constituents:
        if not c.wheel_sha256:
            continue
        wheel_path = wheels_dir / c.wheel_filename
        if not wheel_path.is_file():
            mismatches.append(
                f"{c.ident}: wheel file {c.wheel_filename!r} not found in {wheels_dir}"
            )
            continue
        actual = _sha256_file(wheel_path)
        if actual != c.wheel_sha256:
            mismatches.append(
                f"{c.ident}: wheel_sha256 mismatch — "
                f"recorded={c.wheel_sha256} actual={actual}"
            )
    ok = not mismatches
    return ManifestVerifyResult(
        ok=ok,
        release_tag=manifest.release_tag,
        mismatches=mismatches,
        note="ok" if ok else f"{len(mismatches)} mismatch(es)",
    )


def format_verify_text(result: ManifestVerifyResult) -> str:
    """Human-readable summary of manifest verification."""
    if result.ok:
        return f"release-manifest verify: ok ({result.release_tag})"
    lines = [f"release-manifest verify: FAILED — {result.note}"]
    for m in result.mismatches:
        lines.append(f"  {m}")
    return "\n".join(lines)


def format_build_text(manifest: ReleaseManifest) -> str:
    """Human-readable summary of a built manifest."""
    lines = [
        "agent-suite release manifest",
        f"schema_version: {manifest.schema_version}",
        f"release_tag: {manifest.release_tag}",
        f"umbrella: {manifest.umbrella_repo} @ {manifest.umbrella_tag_sha[:12]}",
        f"suite_release: {manifest.suite_release}",
        f"regista: lib={manifest.regista_library_version} "
        f"schema={manifest.regista_schema_version} "
        f"workflow={manifest.regista_workflow_version} "
        f"envelope={manifest.regista_envelope_version}",
        f"lock_identity: sha256={manifest.lock_identity.lock_file_sha256[:12]}... "
        f"release={manifest.lock_identity.release} "
        f"components={manifest.lock_identity.component_count}",
        f"generated_at: {manifest.generated_at}",
        f"manifest_self_sha256: {manifest.manifest_self_sha256}",
        "",
        "constituents:",
    ]
    for c in manifest.constituents:
        wheel_tag = c.wheel_sha256[:12] if c.wheel_sha256 else "(not provided)"
        source_tag = c.source_archive_sha256[:12] if c.source_archive_sha256 else "(not provided)"
        lines.append(
            f"  {c.ident:<24} {c.repo:<32} "
            f"rev={c.pinned_revision[:12]} v{c.package_version} "
            f"wheel={wheel_tag} source={source_tag}"
        )
    return "\n".join(lines)
