"""The compatibility lock — pin the known-good component set.

Implements Plan 001 WI-2.1. `agent-suite lock` generates `SUITE.lock` from the
currently-pinned set: the regista version quad (read from `regista version
--json`, Plan 025 WI-4.1) plus each installed component's version (from its
`doctor --json`). `doctor` compares installed versions against the lock and
reports named drift.

The lock is TOML (parseable by stdlib ``tomllib``); serialization is manual
because the stdlib has no TOML *writer* — the format is simple and stable.

Design rules (AGENTS.md): the quad is read from regista, never hardcoded;
the core imports only stdlib + its own modules; every closed-set dispatch uses
``assert_never`` so a new drift kind can't slip through ungated.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.components import COMPONENTS, Component

DEFAULT_LOCK_PATH = Path("SUITE.lock")

_REGISTA_VERSION_CMD: tuple[str, ...] = ("regista", "version", "--json")

# A full git SHA is 40 hex chars (sha-1) or 64 (sha-256). Used to validate
# both locked revisions (on deserialize) and probed revisions (on read) so a
# hand-edited tag name or short hash can't masquerade as a pinned SHA.
_SHA_LENGTHS: tuple[int, ...] = (40, 64)
_HEX_DIGITS: frozenset[str] = frozenset("0123456789abcdef")


def _is_valid_sha(value: str) -> bool:
    """Return True iff ``value`` is a 40- or 64-char lowercase/uppercase hex SHA."""
    return len(value) in _SHA_LENGTHS and all(c in _HEX_DIGITS for c in value.lower())


def _suite_release() -> str:
    """Derive the suite release identity.

    The agent-suite package is at 0.0.1 in pyproject (pre-1.0 development),
    but the suite's actual release identity is declared in
    ``data/release-board.json`` (currently ``"1.0.0-dev"``). The lock's
    ``release`` field is a release identity, not a package version: it must
    agree with the release board so the two artifacts don't drift. Prefer
    the declared release; fall back to the package version; finally fall
    back to ``"0.0.1"`` when neither is available.
    """
    try:
        release_path = Path(__file__).resolve().parents[2] / "data" / "release-board.json"
        if release_path.is_file():
            data = json.loads(release_path.read_text(encoding="utf-8"))
            declared = data.get("release")
            if isinstance(declared, str) and declared:
                return declared
    except (OSError, json.JSONDecodeError):
        pass
    try:
        from importlib.metadata import version

        pkg_version = version("agent-suite")
        if pkg_version and pkg_version != "0.0.1":
            return pkg_version
    except Exception:
        pass
    return "0.0.1"


class VersionRunner(Protocol):
    """Run a command and return the completed process (matches doctor.Runner)."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegistaVersionQuad:
    """The four interop versions regista declares (Plan 025 WI-4.1).

    These are what a consumer must pin against: the library version, the schema
    version, the canonical-workflow version, and the envelope version.
    """

    library_version: str
    schema_version: int
    canonical_workflow_version: str
    envelope_version: int

    def to_dict(self) -> dict[str, object]:
        return {
            "library_version": self.library_version,
            "schema_version": self.schema_version,
            "canonical_workflow_version": self.canonical_workflow_version,
            "envelope_version": self.envelope_version,
        }


@dataclass(frozen=True)
class ComponentPin:
    """One component's pinned state in the lock.

    ``revision`` is the optional full git SHA the lock was generated against.
    It is what makes the lock a *reproducible candidate definition* rather
    than a version hint: a version can be republished, but a SHA cannot. The
    field is optional so older locks (and locks generated in environments
    where the source checkout is absent) round-trip cleanly; when present,
    ``check_drift`` reports a named ``REVISION_MISMATCH`` for any component
    whose current HEAD SHA differs.
    """

    repo: str
    version: str
    revision: str | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {"repo": self.repo, "version": self.version}
        if self.revision is not None:
            d["revision"] = self.revision
        return d


@dataclass(frozen=True)
class ProviderExtension:
    """A pinned memory-provider extension (Plan 012 WI-3.1).

    When the memory engine is not native (e.g. Hindsight), the lock pins the
    provider name, adapter version, protocol version, deployment mode, and
    support level so ``doctor`` can detect drift if the operator switches
    engines or the adapter is upgraded.
    """

    provider_name: str
    adapter_version: str | None
    protocol_version: str
    deployment_mode: str
    support_level: str
    config_digest: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "provider_name": self.provider_name,
            "adapter_version": self.adapter_version,
            "protocol_version": self.protocol_version,
            "deployment_mode": self.deployment_mode,
            "support_level": self.support_level,
            "config_digest": self.config_digest,
        }


@dataclass(frozen=True)
class SuiteLock:
    """The full compatibility manifest.

    ``regista_quad`` is ``None`` when regista was not installed at lock-generation
    time (a suite without its spine is unusual but the lock must round-trip).
    ``provider_extension`` is ``None`` when the memory engine is native (the
    default) or when agent-notes was absent at lock-generation time.
    """

    release: str
    regista_quad: RegistaVersionQuad | None
    components: dict[str, ComponentPin] = field(default_factory=dict)
    provider_extension: ProviderExtension | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "suite": {
                "release": self.release,
                "regista": self.regista_quad.to_dict() if self.regista_quad else None,
            },
            "components": {k: v.to_dict() for k, v in self.components.items()},
        }
        if self.provider_extension is not None:
            d["memory_provider"] = self.provider_extension.to_dict()
        return d


class DriftKind(Enum):
    """The closed set of drift kinds a lock check can report.

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in the aggregation or formatting logic.
    """

    VERSION_MISMATCH = "version_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    QUAD_MISMATCH = "quad_mismatch"
    COMPONENT_MISSING = "component_missing"
    UNEXPECTED_COMPONENT = "unexpected_component"
    PROVIDER_DRIFT = "provider_drift"


_QUAD_FIELDS: tuple[str, ...] = (
    "library_version",
    "schema_version",
    "canonical_workflow_version",
    "envelope_version",
)


@dataclass(frozen=True)
class DriftEntry:
    """A single named drift between the lock and the installed state."""

    kind: DriftKind
    component: str
    field: str
    locked: str
    current: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "component": self.component,
            "field": self.field,
            "locked": self.locked,
            "current": self.current,
        }


@dataclass(frozen=True)
class LockDriftResult:
    """The outcome of comparing installed state against a lock.

    ``matches`` is ``None`` (not ``False``) when no lock file exists — the
    distinction matters: ``False`` means "drift detected"; ``None`` means "no
    baseline to compare against." The doctor umbrella surfaces this honestly.
    """

    matches: bool | None
    drift: list[DriftEntry] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "matches": self.matches,
            "drift": [d.to_dict() for d in self.drift],
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Reading the regista version quad
# ---------------------------------------------------------------------------


def read_regista_quad(
    *,
    runner: VersionRunner = _default_runner,
    installed: Installed = _default_installed,
) -> RegistaVersionQuad | None:
    """Shell ``regista version --json`` and parse the quad.

    Returns ``None`` if regista is absent, unreachable, or emits something
    unparseable — never raises. The caller decides whether a missing quad is
    a failure (it is for the spine, per ``doctor`` rules).
    """
    if not installed("regista"):
        return None

    try:
        result = runner(_REGISTA_VERSION_CMD)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    try:
        return RegistaVersionQuad(
            library_version=str(data["library_version"]),
            schema_version=int(data["schema_version"]),
            canonical_workflow_version=str(data["canonical_workflow_version"]),
            envelope_version=int(data["envelope_version"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


_PROVIDER_DESCRIBE_CMD: tuple[str, ...] = (
    "agent-notes", "memory-provider", "describe", "--json",
)


def _default_search_roots() -> tuple[Path, ...]:
    """Resolve the default search roots for component source checkouts.

    M-5: the prior default included ``Path("../projects")``, a path relative to
    CWD — so ``agent-suite lock`` run from anywhere other than
    ``/projects/agent-suite`` resolved to the wrong directory. The default is now
    absolute-only: ``/projects`` (the canonical POSIX workspace root). On
    Windows, ``/projects`` is drive-relative — we resolve it against the
    current drive so the path is genuinely absolute and ``is_absolute()``
    holds cross-platform. An operator may override the roots entirely by
    setting ``SUITE_WORKSPACE_ROOT`` to a single absolute path; that one root
    replaces the defaults (useful in CI or non-standard layouts).
    """
    env_root = os.environ.get("SUITE_WORKSPACE_ROOT")
    if env_root and env_root.strip():
        return (Path(env_root).expanduser().resolve(),)
    # Path("/projects").resolve() is /projects on POSIX and <current_drive>:\projects
    # on Windows — both are absolute, which is the contract callers rely on.
    return (Path("/projects").resolve(),)


def read_candidate_revisions(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    search_roots: tuple[Path, ...] | None = None,
) -> dict[str, str | None]:
    """Probe each candidate source checkout for its current git SHA.

    The compatibility lock is only a *reproducible candidate definition* when
    it pins the exact git revision each component was built from. The version
    field alone is a hint (a version can be republished); the SHA cannot.

    The lookup is deliberately conservative: it returns ``None`` for any
    component whose source checkout is absent or not a git repo, so a
    lock generated in an environment without checkouts (CI from wheels,
    production installs) still round-trips. The candidate checkout path is
    ``<search_root>/<repo-basename>`` (e.g. ``/projects/regista`` for
    ``hraedon/regista``); the first matching directory wins.

    The function never raises — git failures, missing directories, and
    non-checkout directories all return ``None`` for that component.

    ``search_roots`` defaults to :func:`_default_search_roots` (absolute-only;
    overridable via ``SUITE_WORKSPACE_ROOT``). Pass an explicit tuple from
    tests to avoid touching the real workspace.
    """
    roots = search_roots if search_roots is not None else _default_search_roots()
    revisions: dict[str, str | None] = {}
    for comp in components:
        revisions[comp.ident] = _probe_revision(comp.repo, roots)
    return revisions


def read_candidate_versions(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    search_roots: tuple[Path, ...] | None = None,
) -> dict[str, str | None]:
    """Read declared versions from the exact candidate checkout family.

    This companion to :func:`read_candidate_revisions` prevents lock authoring
    from pairing a runtime-reported version with an unrelated checkout SHA.
    Root and one-level-nested ``pyproject.toml`` files are considered (the
    latter covers repositories such as agent-wake's daemon package), and the
    declared project name must match a component distribution alias.
    """
    roots = search_roots if search_roots is not None else _default_search_roots()
    versions: dict[str, str | None] = {}
    for comp in components:
        basename = comp.repo.split("/", 1)[-1] if "/" in comp.repo else comp.repo
        version: str | None = None
        for root in roots:
            checkout = root / basename
            if not checkout.is_dir():
                continue
            pyprojects = (checkout / "pyproject.toml", *checkout.glob("*/pyproject.toml"))
            aliases = {name.lower().replace("_", "-") for name in comp.distribution_names}
            for pyproject in pyprojects:
                if not pyproject.is_file():
                    continue
                try:
                    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
                except (OSError, RuntimeError, tomllib.TOMLDecodeError):
                    continue
                project = data.get("project")
                if not isinstance(project, dict):
                    continue
                name = project.get("name")
                declared = project.get("version")
                if (
                    isinstance(name, str)
                    and name.lower().replace("_", "-") in aliases
                    and isinstance(declared, str)
                ):
                    version = declared
                    break
            break
        versions[comp.ident] = version
    return versions


def read_component_revisions(
    components: tuple[Component, ...] = COMPONENTS,
    *,
    search_roots: tuple[Path, ...] | None = None,
) -> dict[str, str | None]:
    """Compatibility alias for candidate revision discovery.

    Runtime drift checks must use
    :func:`agent_suite.runtime_provenance.read_runtime_revisions` instead.
    Keeping this wrapper avoids breaking callers while making its candidate-only
    semantics explicit at every in-tree call site.
    """
    return read_candidate_revisions(components=components, search_roots=search_roots)


def _probe_revision(
    repo: str,
    search_roots: tuple[Path, ...],
) -> str | None:
    """Find a local checkout for ``owner/repo`` and return its HEAD SHA."""
    basename = repo.split("/", 1)[-1] if "/" in repo else repo
    # L-4: reject path-traversal basenames. A repo like `..` (no slash) would
    # resolve to ``root.parent``; a basename with a separator could escape the
    # search root. Limited impact (subprocess uses a tuple, no shell), but the
    # defense is cheap and the failure mode (probing the wrong directory) is
    # confusing.
    if not basename or basename in (".", "..") or "/" in basename or "\\" in basename:
        return None
    for root in search_roots:
        candidate = root / basename
        if not candidate.is_dir():
            continue
        git_dir = candidate / ".git"
        if not git_dir.exists():
            continue
        try:
            status = subprocess.run(
                ("git", "-C", str(candidate), "status", "--porcelain"),
                capture_output=True,
                text=True,
                timeout=10,
            )
            result = subprocess.run(
                ("git", "-C", str(candidate), "rev-parse", "HEAD"),
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None
        if status.returncode != 0 or status.stdout.strip() or result.returncode != 0:
            return None
        sha = result.stdout.strip()
        # L-3: a full git SHA is 40 hex chars (sha-1) or 64 (sha-256); enforce
        # the length so a truncated or malformed output is not mistaken for a
        # valid SHA.
        if not _is_valid_sha(sha):
            return None
        return sha
    return None


def read_provider_extension(
    *,
    engine: str = "native",
    runner: VersionRunner = _default_runner,
    installed: Installed = _default_installed,
) -> ProviderExtension | None:
    """Shell ``agent-notes memory-provider describe --json`` and parse the pin.

    Returns ``None`` when the engine is native (no external pin needed),
    when agent-notes is absent, or when the command fails — never raises.
    """
    if engine == "native":
        return None
    if not installed("agent-notes"):
        return None
    try:
        result = runner(_PROVIDER_DESCRIBE_CMD)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    provider_name = data.get("engine")
    if not isinstance(provider_name, str):
        return None
    raw_adapter = data.get("version")
    adapter_version: str | None = raw_adapter if isinstance(raw_adapter, str) else None
    raw_protocol = data.get("protocol_version", "1.0")
    protocol_version = raw_protocol if isinstance(raw_protocol, str) else "1.0"
    return ProviderExtension(
        provider_name=provider_name,
        adapter_version=adapter_version,
        protocol_version=protocol_version,
        deployment_mode="remote",
        support_level="supported",
        config_digest=None,
    )


def generate_lock(
    *,
    component_versions: dict[str, str | None],
    component_revisions: dict[str, str | None] | None = None,
    runner: VersionRunner = _default_runner,
    installed: Installed = _default_installed,
    components: tuple[Component, ...] = COMPONENTS,
    release: str | None = None,
    memory_engine: str = "native",
) -> SuiteLock:
    """Build a :class:`SuiteLock` from the current installed state.

    ``component_versions`` maps component ident → version (or ``None`` if
    absent). ``component_revisions`` (optional) maps component ident → the
    full git SHA the candidate was generated against; absent entries leave
    the pin version-only, preserving round-trip with older locks. The
    regista quad is read from ``regista version --json``, not hardcoded.
    Only installed components are pinned in the lock. ``release`` defaults
    to the installed package version. When ``memory_engine`` is not
    ``"native"``, the provider extension is read from ``agent-notes
    memory-provider describe --json`` and pinned in the lock (Plan 012 WI-3.1).
    """
    quad = read_regista_quad(runner=runner, installed=installed)
    provider_ext = read_provider_extension(
        engine=memory_engine, runner=runner, installed=installed
    )

    revisions = component_revisions or {}
    pins: dict[str, ComponentPin] = {}
    for comp in components:
        version = component_versions.get(comp.ident)
        if version is not None:
            rev = revisions.get(comp.ident)
            pins[comp.ident] = ComponentPin(
                repo=comp.repo, version=version, revision=rev
            )

    return SuiteLock(
        release=release if release is not None else _suite_release(),
        regista_quad=quad,
        components=pins,
        provider_extension=provider_ext,
    )


# ---------------------------------------------------------------------------
# TOML serialization (manual write; tomllib read)
# ---------------------------------------------------------------------------


def _toml_escape(value: str) -> str:
    """Escape a string for a TOML basic-string (double-quoted)."""
    return json.dumps(value)


def serialize_lock(lock: SuiteLock) -> str:
    """Serialize a :class:`SuiteLock` to a TOML string.

    The format matches ``docs/bootstrap-contract.md`` §4. Uses ``tomllib``-
    compatible TOML so the stdlib can round-trip it back.
    """
    lines: list[str] = [
        "# agent-suite compatibility lock — generated by `agent-suite lock`",
        "# Do not edit by hand; regenerate with `agent-suite lock`.",
        "",
        "[suite]",
        f"release = {_toml_escape(lock.release)}",
    ]

    if lock.regista_quad is not None:
        q = lock.regista_quad
        lines.extend(
            [
                f"regista_library_version = {_toml_escape(q.library_version)}",
                f"regista_schema_version = {q.schema_version}",
                f"regista_workflow_version = {_toml_escape(q.canonical_workflow_version)}",
                f"regista_envelope_version = {q.envelope_version}",
            ]
        )
    else:
        lines.append("# regista was not installed when this lock was generated")

    lines.append("")

    for ident in sorted(lock.components):
        pin = lock.components[ident]
        lines.append(f"[components.{ident}]")
        lines.append(f"repo = {_toml_escape(pin.repo)}")
        lines.append(f"version = {_toml_escape(pin.version)}")
        if pin.revision is not None:
            lines.append(f"revision = {_toml_escape(pin.revision)}")
        lines.append("")

    if lock.provider_extension is not None:
        pe = lock.provider_extension
        lines.append("[memory_provider]")
        lines.append(f"provider_name = {_toml_escape(pe.provider_name)}")
        if pe.adapter_version is not None:
            lines.append(f"adapter_version = {_toml_escape(pe.adapter_version)}")
        lines.append(f"protocol_version = {_toml_escape(pe.protocol_version)}")
        lines.append(f"deployment_mode = {_toml_escape(pe.deployment_mode)}")
        lines.append(f"support_level = {_toml_escape(pe.support_level)}")
        if pe.config_digest is not None:
            lines.append(f"config_digest = {_toml_escape(pe.config_digest)}")
        lines.append("")

    return "\n".join(lines)


def deserialize_lock(text: str) -> SuiteLock:
    """Parse a TOML string into a :class:`SuiteLock`.

    Raises ``ValueError`` for structurally invalid locks (missing required
    fields, wrong types) so callers can distinguish "bad lock" from "no lock."
    """
    data = tomllib.loads(text)

    suite = data.get("suite")
    if not isinstance(suite, dict):
        raise ValueError("SUITE.lock: missing [suite] table")

    release = suite.get("release")
    if not isinstance(release, str):
        raise ValueError("SUITE.lock: suite.release must be a string")

    quad: RegistaVersionQuad | None = None
    has_quad = "regista_library_version" in suite
    if has_quad:
        try:
            quad = RegistaVersionQuad(
                library_version=str(suite["regista_library_version"]),
                schema_version=int(suite["regista_schema_version"]),
                canonical_workflow_version=str(suite["regista_workflow_version"]),
                envelope_version=int(suite["regista_envelope_version"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"SUITE.lock: invalid regista quad ({exc})") from exc

    raw_components = data.get("components", {})
    if not isinstance(raw_components, dict):
        raise ValueError("SUITE.lock: [components] must be a table")

    pins: dict[str, ComponentPin] = {}
    for ident, raw in raw_components.items():
        if not isinstance(raw, dict):
            raise ValueError(f"SUITE.lock: components.{ident} must be a table")
        repo = raw.get("repo")
        version = raw.get("version")
        if not isinstance(repo, str) or not isinstance(version, str):
            raise ValueError(
                f"SUITE.lock: components.{ident} must have string repo and version"
            )
        # revision is optional (older locks omit it; locks generated in
        # environments without source checkouts omit it). When present it
        # must be a string and is what makes the pin a reproducible candidate.
        # H-1: normalize empty/whitespace-only strings to None so a hand-edited
        # lock with `revision = ""` round-trips as None and does not false-
        # positive REVISION_MISMATCH (the drift gate is `locked_rev is not None`).
        # L-2: validate the SHA format (40- or 64-char hex) so a hand-edited
        # tag name like `revision = "v0.5.1"` is rejected rather than causing
        # perpetual drift against any probed SHA.
        raw_revision = raw.get("revision")
        revision: str | None
        if isinstance(raw_revision, str):
            stripped = raw_revision.strip()
            if not stripped:
                revision = None
            elif not _is_valid_sha(stripped):
                raise ValueError(
                    f"SUITE.lock: components.{ident}.revision must be a "
                    "40- or 64-char hex SHA"
                )
            else:
                revision = stripped
        else:
            revision = None
        pins[ident] = ComponentPin(repo=repo, version=version, revision=revision)

    provider_extension: ProviderExtension | None = None
    raw_mp = data.get("memory_provider")
    if isinstance(raw_mp, dict):
        provider_name = raw_mp.get("provider_name")
        if not isinstance(provider_name, str):
            raise ValueError("SUITE.lock: memory_provider.provider_name must be a string")
        raw_adapter = raw_mp.get("adapter_version")
        adapter_version: str | None = raw_adapter if isinstance(raw_adapter, str) else None
        raw_protocol = raw_mp.get("protocol_version")
        if not isinstance(raw_protocol, str):
            raise ValueError("SUITE.lock: memory_provider.protocol_version must be a string")
        raw_mode = raw_mp.get("deployment_mode")
        if not isinstance(raw_mode, str):
            raise ValueError("SUITE.lock: memory_provider.deployment_mode must be a string")
        raw_support = raw_mp.get("support_level")
        if not isinstance(raw_support, str):
            raise ValueError("SUITE.lock: memory_provider.support_level must be a string")
        raw_digest = raw_mp.get("config_digest")
        config_digest: str | None = raw_digest if isinstance(raw_digest, str) else None
        provider_extension = ProviderExtension(
            provider_name=provider_name,
            adapter_version=adapter_version,
            protocol_version=raw_protocol,
            deployment_mode=raw_mode,
            support_level=raw_support,
            config_digest=config_digest,
        )

    return SuiteLock(
        release=release,
        regista_quad=quad,
        components=pins,
        provider_extension=provider_extension,
    )


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------


def load_lock_file(path: Path = DEFAULT_LOCK_PATH) -> SuiteLock | None:
    """Load a lock file. Returns ``None`` if the file does not exist.

    Raises ``ValueError`` if the file exists but is malformed (so the caller
    can distinguish "no lock" from "bad lock").
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return deserialize_lock(text)


def write_lock_file(lock: SuiteLock, path: Path = DEFAULT_LOCK_PATH) -> None:
    """Write a lock file atomically (temp + rename).

    The temp file is created in the same directory so the rename is atomic
    on POSIX. This prevents a partial write from corrupting an existing lock.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialize_lock(lock) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Drift detection
# ---------------------------------------------------------------------------


def check_drift(
    lock: SuiteLock | None,
    *,
    current_quad: RegistaVersionQuad | None,
    component_versions: dict[str, str | None],
    component_revisions: dict[str, str | None] | None = None,
    current_provider_extension: ProviderExtension | None = None,
) -> LockDriftResult:
    """Compare current state against a lock, reporting named drift.

    If ``lock`` is ``None`` (no lock file), returns ``matches=None`` — the
    distinction from ``False`` (drift) matters for honest health reporting.

    Revision drift is reported only when *both* the locked pin and the
    current state carry a revision for the component. A lock without
    revision pins cannot detect revision drift (the version-only baseline is
    preserved); a current state where the revision is unprobeable (e.g. a
    wheel install with no source checkout) does not false-positive against a
    locked revision.
    """
    if lock is None:
        return LockDriftResult(
            matches=None,
            note="no SUITE.lock — run `agent-suite lock` to create one",
        )

    drift: list[DriftEntry] = []

    # --- regista quad drift ---
    if lock.regista_quad is not None and current_quad is not None:
        locked_q = lock.regista_quad
        current_q = current_quad
        for field_name in _QUAD_FIELDS:
            locked_val = str(getattr(locked_q, field_name))
            current_val = str(getattr(current_q, field_name))
            if locked_val != current_val:
                drift.append(
                    DriftEntry(
                        kind=DriftKind.QUAD_MISMATCH,
                        component="regista",
                        field=field_name,
                        locked=locked_val,
                        current=current_val,
                    )
                )
    elif lock.regista_quad is not None and current_quad is None:
        drift.append(
            DriftEntry(
                kind=DriftKind.COMPONENT_MISSING,
                component="regista",
                field="version_quad",
                locked="pinned",
                current="absent",
            )
        )
    elif lock.regista_quad is None and current_quad is not None:
        drift.append(
            DriftEntry(
                kind=DriftKind.UNEXPECTED_COMPONENT,
                component="regista",
                field="version_quad",
                locked="(not pinned)",
                current="present",
            )
        )
    # If the lock had no quad (regista was absent at generation time) and it's
    # still absent, that's not a drift — the baseline was already "no quad."

    # --- per-component version drift ---
    locked_components = set(lock.components)
    installed_components = {
        ident for ident, ver in component_versions.items() if ver is not None
    }
    current_revisions = component_revisions or {}

    for ident in sorted(locked_components | installed_components):
        in_lock = ident in lock.components
        version = component_versions.get(ident)
        installed_now = version is not None

        if in_lock and installed_now:
            locked_ver = lock.components[ident].version
            current_ver = str(version)
            if locked_ver != current_ver:
                drift.append(
                    DriftEntry(
                        kind=DriftKind.VERSION_MISMATCH,
                        component=ident,
                        field="version",
                        locked=locked_ver,
                        current=current_ver,
                    )
                )
            # Revision drift: only when both sides carry a SHA. A version-only
            # lock cannot detect revision drift by design; a current state
            # without a probeable revision must not false-positive.
            locked_rev = lock.components[ident].revision
            current_rev = current_revisions.get(ident)
            if (
                locked_rev is not None
                and current_rev is not None
                and locked_rev != current_rev
            ):
                drift.append(
                    DriftEntry(
                        kind=DriftKind.REVISION_MISMATCH,
                        component=ident,
                        field="revision",
                        locked=locked_rev,
                        current=current_rev,
                    )
                )
        elif in_lock and not installed_now:
            drift.append(
                DriftEntry(
                    kind=DriftKind.COMPONENT_MISSING,
                    component=ident,
                    field="version",
                    locked=lock.components[ident].version,
                    current="absent",
                )
            )
        elif not in_lock and installed_now:
            drift.append(
                DriftEntry(
                    kind=DriftKind.UNEXPECTED_COMPONENT,
                    component=ident,
                    field="version",
                    locked="(not pinned)",
                    current=str(version),
                )
            )

    # --- memory-provider extension drift (Plan 012 WI-3.1) ---
    if lock.provider_extension is not None and current_provider_extension is not None:
        pe = lock.provider_extension
        cur = current_provider_extension
        for field_name in (
            "provider_name",
            "adapter_version",
            "protocol_version",
            "deployment_mode",
            "support_level",
        ):
            locked_val = str(getattr(pe, field_name) or "")
            current_val = str(getattr(cur, field_name) or "")
            if locked_val != current_val:
                drift.append(
                    DriftEntry(
                        kind=DriftKind.PROVIDER_DRIFT,
                        component="memory_provider",
                        field=field_name,
                        locked=locked_val,
                        current=current_val,
                    )
                )
    elif lock.provider_extension is not None and current_provider_extension is None:
        drift.append(
            DriftEntry(
                kind=DriftKind.PROVIDER_DRIFT,
                component="memory_provider",
                field="provider_extension",
                locked="pinned",
                current="absent",
            )
        )
    elif lock.provider_extension is None and current_provider_extension is not None:
        drift.append(
            DriftEntry(
                kind=DriftKind.PROVIDER_DRIFT,
                component="memory_provider",
                field="provider_extension",
                locked="(not pinned)",
                current="present",
            )
        )

    matches = len(drift) == 0
    return LockDriftResult(
        matches=matches,
        drift=drift,
        note="ok" if matches else f"{len(drift)} drift(s) detected",
    )


def format_drift_text(result: LockDriftResult) -> str:
    """Human-readable summary of lock drift for ``doctor`` text output."""
    if result.matches is None:
        return f"lock: {result.note}"
    if result.matches:
        return "lock: ok (matches)"

    lines = [f"lock: DRIFT — {result.note}"]
    for d in result.drift:
        match d.kind:
            case DriftKind.VERSION_MISMATCH:
                lines.append(
                    f"  {d.component:<22} version: {d.locked} → {d.current}"
                )
            case DriftKind.REVISION_MISMATCH:
                lines.append(
                    f"  {d.component:<22} revision: {d.locked} → {d.current}"
                )
            case DriftKind.QUAD_MISMATCH:
                lines.append(
                    f"  regista.{d.field:<26} {d.locked} → {d.current}"
                )
            case DriftKind.COMPONENT_MISSING:
                lines.append(
                    f"  {d.component:<22} {d.field}: {d.locked} → {d.current}"
                )
            case DriftKind.UNEXPECTED_COMPONENT:
                lines.append(
                    f"  {d.component:<22} not in lock (installed: {d.current})"
                )
            case DriftKind.PROVIDER_DRIFT:
                lines.append(
                    f"  memory_provider       {d.field}: {d.locked} → {d.current}"
                )
            case other:
                assert_never(other)
    return "\n".join(lines)
