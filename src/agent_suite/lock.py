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


def _suite_release() -> str:
    """Derive the suite release from installed package metadata."""
    try:
        from importlib.metadata import version

        return version("agent-suite")
    except Exception:
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
    """One component's pinned state in the lock."""

    repo: str
    version: str

    def to_dict(self) -> dict[str, object]:
        return {"repo": self.repo, "version": self.version}


@dataclass(frozen=True)
class SuiteLock:
    """The full compatibility manifest.

    ``regista_quad`` is ``None`` when regista was not installed at lock-generation
    time (a suite without its spine is unusual but the lock must round-trip).
    """

    release: str
    regista_quad: RegistaVersionQuad | None
    components: dict[str, ComponentPin] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "suite": {
                "release": self.release,
                "regista": self.regista_quad.to_dict() if self.regista_quad else None,
            },
            "components": {k: v.to_dict() for k, v in self.components.items()},
        }


class DriftKind(Enum):
    """The closed set of drift kinds a lock check can report.

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in the aggregation or formatting logic.
    """

    VERSION_MISMATCH = "version_mismatch"
    QUAD_MISMATCH = "quad_mismatch"
    COMPONENT_MISSING = "component_missing"
    UNEXPECTED_COMPONENT = "unexpected_component"


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


# ---------------------------------------------------------------------------
# Lock generation
# ---------------------------------------------------------------------------


def generate_lock(
    *,
    component_versions: dict[str, str | None],
    runner: VersionRunner = _default_runner,
    installed: Installed = _default_installed,
    components: tuple[Component, ...] = COMPONENTS,
    release: str | None = None,
) -> SuiteLock:
    """Build a :class:`SuiteLock` from the current installed state.

    ``component_versions`` maps component ident → version (or ``None`` if
    absent). The regista quad is read from ``regista version --json``, not
    hardcoded. Only installed components are pinned in the lock. ``release``
    defaults to the installed package version.
    """
    quad = read_regista_quad(runner=runner, installed=installed)

    pins: dict[str, ComponentPin] = {}
    for comp in components:
        version = component_versions.get(comp.ident)
        if version is not None:
            pins[comp.ident] = ComponentPin(repo=comp.repo, version=version)

    return SuiteLock(
        release=release if release is not None else _suite_release(),
        regista_quad=quad,
        components=pins,
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
        pins[ident] = ComponentPin(repo=repo, version=version)

    return SuiteLock(release=release, regista_quad=quad, components=pins)


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
) -> LockDriftResult:
    """Compare current state against a lock, reporting named drift.

    If ``lock`` is ``None`` (no lock file), returns ``matches=None`` — the
    distinction from ``False`` (drift) matters for honest health reporting.
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
            case other:
                assert_never(other)
    return "\n".join(lines)
