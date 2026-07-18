"""The candidate inventory — reconcile the locked set against what's installed.

Implements WI-0.2. ``agent-suite inventory`` emits a structured view of the
suite's current state: the release identity, whether a lock is present, each
component's pinned vs installed version and revision, the regista quad (locked
vs current), and the locked memory-provider extension. Per-component drift is
named with a closed :class:`ComponentDrift` set so a reader can see at a glance
what matches and what has diverged — the same honest-health rule that governs
``doctor``: a gap is a named state, not silence.

The module is stdlib-only and composes :mod:`agent_suite.doctor` (for installed
versions) and :mod:`agent_suite.lock` (for the lock + regista quad + revisions)
— it adds no new shelling, just a structured reconciliation view over state the
suite already probes. ``assert_never`` guards the closed drift sets so a newly
added kind can't slip through ungated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from agent_suite import doctor
from agent_suite import lock
from agent_suite.components import COMPONENTS, Component


# ---------------------------------------------------------------------------
# Default artifact path (mirrors lock._suite_release's path resolution)
# ---------------------------------------------------------------------------


def _default_inventory_path() -> Path:
    """Resolve ``data/candidate-inventory.json`` relative to the package root.

    Mirrors :func:`agent_suite.lock._suite_release`: ``__file__`` is
    ``<root>/src/agent_suite/inventory.py`` and ``parents[2]`` is ``<root>``,
    so the artifact lands beside ``data/release-board.json``.
    """
    return Path(__file__).resolve().parents[2] / "data" / "candidate-inventory.json"


# ---------------------------------------------------------------------------
# Closed sets — assert_never enforces totality in formatting + dispatch
# ---------------------------------------------------------------------------


class ComponentDrift(Enum):
    """The closed set of per-component drift states an inventory can report.

    ``NOT_LOCKED`` covers two honest cases that are the same from a reader's
    perspective: (a) no lock file exists at all, so nothing is pinned; (b) a
    lock exists but does not pin this component (and it is not installed).
    Either way the component has no pinned baseline to drift against.
    """

    MATCHES = "matches"
    VERSION_MISMATCH = "version_mismatch"
    REVISION_MISMATCH = "revision_mismatch"
    MISSING = "missing"  # pinned by the lock but not installed
    UNEXPECTED = "unexpected"  # installed but not pinned by the lock
    NOT_LOCKED = "not_locked"  # no lock file, or the lock doesn't pin this component


class QuadDrift(Enum):
    """The closed set of regista-quad drift states."""

    MATCHES = "matches"  # both present and equal, or both absent (baseline unchanged)
    MISMATCH = "mismatch"  # both present but differ
    MISSING = "missing"  # locked but regista absent now
    UNEXPECTED = "unexpected"  # not locked but regista present now
    NOT_LOCKED = "not_locked"  # no lock file (so no locked quad)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LockFileStatus:
    present: bool
    path: str
    parseable: bool = True
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "present": self.present,
            "path": self.path,
            "parseable": self.parseable,
            "note": self.note,
        }


@dataclass(frozen=True)
class ComponentInventory:
    ident: str
    repo: str
    pinned_revision: str | None
    pinned_version: str | None
    installed_version: str | None
    installed_revision: str | None
    drift: ComponentDrift

    def to_dict(self) -> dict[str, object]:
        return {
            "ident": self.ident,
            "repo": self.repo,
            "pinned_revision": self.pinned_revision,
            "pinned_version": self.pinned_version,
            "installed_version": self.installed_version,
            "installed_revision": self.installed_revision,
            "drift": self.drift.value,
        }


@dataclass(frozen=True)
class RegistaQuadInventory:
    locked: dict[str, object] | None
    current: dict[str, object] | None
    drift: QuadDrift

    def to_dict(self) -> dict[str, object]:
        return {
            "locked": self.locked,
            "current": self.current,
            "drift": self.drift.value,
        }


@dataclass(frozen=True)
class Inventory:
    release: str
    lock_file: LockFileStatus
    components: list[ComponentInventory]
    regista_quad: RegistaQuadInventory
    memory_provider: dict[str, object] | None
    generated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "release": self.release,
            "lock_file": self.lock_file.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "regista_quad": self.regista_quad.to_dict(),
            "memory_provider": self.memory_provider,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Drift computation (pure — no I/O)
# ---------------------------------------------------------------------------


def _component_drift(
    *,
    has_lock: bool,
    in_lock: bool,
    pinned_version: str | None,
    pinned_revision: str | None,
    installed_version: str | None,
    installed_revision: str | None,
) -> ComponentDrift:
    """Compute one component's drift. See :class:`ComponentDrift` for the rules."""
    if not has_lock:
        return ComponentDrift.NOT_LOCKED
    if in_lock:
        if installed_version is None:
            return ComponentDrift.MISSING
        if pinned_version is not None and installed_version != pinned_version:
            return ComponentDrift.VERSION_MISMATCH
        # Version matches (or is un-pinned). Revision drift is reported only
        # when both sides carry a SHA — mirroring lock.check_drift so a
        # wheel install with no probeable revision never false-positives.
        if (
            pinned_revision is not None
            and installed_revision is not None
            and pinned_revision != installed_revision
        ):
            return ComponentDrift.REVISION_MISMATCH
        return ComponentDrift.MATCHES
    # Component is not in the lock.
    if installed_version is not None:
        return ComponentDrift.UNEXPECTED
    return ComponentDrift.NOT_LOCKED


def _quad_drift(
    *,
    has_lock: bool,
    locked: lock.RegistaVersionQuad | None,
    current: lock.RegistaVersionQuad | None,
) -> QuadDrift:
    """Compute the regista-quad drift. Mirrors lock.check_drift's quad logic."""
    if not has_lock:
        return QuadDrift.NOT_LOCKED
    if locked is not None and current is not None:
        return QuadDrift.MATCHES if locked == current else QuadDrift.MISMATCH
    if locked is not None and current is None:
        return QuadDrift.MISSING
    if locked is None and current is not None:
        return QuadDrift.UNEXPECTED
    # Both None: the lock had no quad (regista was absent at generation) and it's
    # still absent — the baseline is unchanged, so this is not drift.
    return QuadDrift.MATCHES


# ---------------------------------------------------------------------------
# build_inventory — pure, fully injectable (the test surface)
# ---------------------------------------------------------------------------


def build_inventory(
    *,
    lock_obj: lock.SuiteLock | None,
    has_lock_file: bool,
    lock_path: Path,
    component_versions: dict[str, str | None],
    component_revisions: dict[str, str | None],
    current_quad: lock.RegistaVersionQuad | None,
    release: str | None = None,
    components: tuple[Component, ...] = COMPONENTS,
    lock_parseable: bool = True,
    lock_note: str = "",
) -> Inventory:
    """Build the inventory from a lock and the current installed state.

    All inputs are injectable so tests drive every drift state without
    shelling out. ``lock_obj`` is ``None`` when the lock file is absent or
    unreadable (distinguished by ``has_lock_file`` + ``lock_parseable`` so the
    report can say "present but malformed" honestly). ``release`` defaults to
    :func:`agent_suite.lock._suite_release` (the release board identity).
    """
    rel = release if release is not None else lock._suite_release()
    lock_status = LockFileStatus(
        present=has_lock_file,
        path=str(lock_path),
        parseable=lock_parseable,
        note=lock_note,
    )

    has_lock = lock_obj is not None  # a malformed lock is "no baseline"
    comp_entries: list[ComponentInventory] = []
    for comp in components:
        pin = lock_obj.components.get(comp.ident) if lock_obj is not None else None
        pinned_version = pin.version if pin is not None else None
        pinned_revision = pin.revision if pin is not None else None
        installed_version = component_versions.get(comp.ident)
        installed_revision = component_revisions.get(comp.ident)
        drift = _component_drift(
            has_lock=has_lock,
            in_lock=pin is not None,
            pinned_version=pinned_version,
            pinned_revision=pinned_revision,
            installed_version=installed_version,
            installed_revision=installed_revision,
        )
        comp_entries.append(
            ComponentInventory(
                ident=comp.ident,
                repo=comp.repo,
                pinned_revision=pinned_revision,
                pinned_version=pinned_version,
                installed_version=installed_version,
                installed_revision=installed_revision,
                drift=drift,
            )
        )

    locked_quad = lock_obj.regista_quad if lock_obj is not None else None
    quad_inv = RegistaQuadInventory(
        locked=(locked_quad.to_dict() if locked_quad is not None else None),
        current=(current_quad.to_dict() if current_quad is not None else None),
        drift=_quad_drift(
            has_lock=has_lock,
            locked=locked_quad,
            current=current_quad,
        ),
    )

    memory_provider: dict[str, object] | None = None
    if lock_obj is not None and lock_obj.provider_extension is not None:
        memory_provider = lock_obj.provider_extension.to_dict()

    return Inventory(
        release=rel,
        lock_file=lock_status,
        components=comp_entries,
        regista_quad=quad_inv,
        memory_provider=memory_provider,
        generated_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# collect_inventory — shells out (the CLI surface)
# ---------------------------------------------------------------------------


def collect_inventory(
    *,
    installed: doctor.Installed = doctor._default_installed,
    runner: doctor.Runner = doctor._default_runner,
    lock_path: Path = lock.DEFAULT_LOCK_PATH,
    components: tuple[Component, ...] = COMPONENTS,
    shared_endpoints: dict[str, str] | None = None,
    version_runner: lock.VersionRunner | None = None,
    version_installed: lock.Installed | None = None,
    release: str | None = None,
) -> Inventory:
    """Collect current state and build the inventory (shells out to component doctors).

    Reuses :func:`agent_suite.doctor.aggregate` for installed component
    versions (the same source ``agent-suite lock`` uses) with the heavy
    non-version checks disabled — the inventory only needs versions, not key
    rotation, memory-provider doctor, or codex health. The regista quad and
    per-component revisions are read via :mod:`agent_suite.lock`. A malformed
    lock is reported honestly (present + unreadable) rather than crashing.
    """
    has_lock_file = lock_path.is_file()
    lock_obj: lock.SuiteLock | None = None
    lock_parseable = True
    lock_note = ""
    if has_lock_file:
        try:
            lock_obj = lock.load_lock_file(lock_path)
        except ValueError as exc:
            lock_parseable = False
            lock_note = f"SUITE.lock unreadable: {exc}"

    v_runner = version_runner if version_runner is not None else lock._default_runner
    v_installed = (
        version_installed if version_installed is not None else lock._default_installed
    )

    report = doctor.aggregate(
        installed=installed,
        runner=runner,
        components=components,
        lock_path=lock_path,
        version_runner=v_runner,
        version_installed=v_installed,
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=False,
        shared_endpoints=shared_endpoints,
    )
    component_versions: dict[str, str | None] = {
        r.component: r.version for r in report.components
    }

    component_revisions = lock.read_component_revisions(components=components)
    current_quad = lock.read_regista_quad(runner=v_runner, installed=v_installed)

    return build_inventory(
        lock_obj=lock_obj,
        has_lock_file=has_lock_file,
        lock_path=lock_path,
        component_versions=component_versions,
        component_revisions=component_revisions,
        current_quad=current_quad,
        release=release,
        components=components,
        lock_parseable=lock_parseable,
        lock_note=lock_note,
    )


# ---------------------------------------------------------------------------
# Serialization + text formatting
# ---------------------------------------------------------------------------


def write_inventory_file(inv: Inventory, path: Path | None = None) -> Path:
    """Write the inventory as JSON to ``data/candidate-inventory.json`` (atomic).

    Both ``--json`` and text modes of the CLI write this artifact; the file is
    the WI-0.2 proof artifact referenced by the release board. The write is
    temp + rename (POSIX-atomic) so a partial write never corrupts an existing
    inventory.
    """
    target = path if path is not None else _default_inventory_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(
        json.dumps(inv.to_dict(), indent=2, default=str) + "\n", encoding="utf-8"
    )
    tmp.replace(target)
    return target


def _quad_str(quad: dict[str, object]) -> str:
    return (
        f"lib={quad.get('library_version')} "
        f"schema={quad.get('schema_version')} "
        f"workflow={quad.get('canonical_workflow_version')} "
        f"envelope={quad.get('envelope_version')}"
    )


def _short_sha(sha: str | None) -> str:
    if not sha:
        return ""
    return sha[:8]


def format_text(inv: Inventory) -> str:
    """Human-readable summary for ``agent-suite inventory`` without ``--json``."""
    lines: list[str] = ["agent-suite candidate inventory"]
    lines.append(f"release: {inv.release}")
    lines.append(f"generated: {inv.generated_at}")

    if inv.lock_file.present:
        lock_tag = "present" if inv.lock_file.parseable else "present (unreadable)"
    else:
        lock_tag = "absent"
    lines.append(f"lock: {inv.lock_file.path} ({lock_tag})")
    if inv.lock_file.note:
        lines.append(f"  note: {inv.lock_file.note}")

    lines.append("")
    lines.append("components:")
    for c in inv.components:
        if c.pinned_version:
            pinned = f"v{c.pinned_version}"
            if c.pinned_revision:
                pinned += f" @ {_short_sha(c.pinned_revision)}"
        else:
            pinned = "(not pinned)"
        if c.installed_version:
            installed = f"v{c.installed_version}"
            if c.installed_revision:
                installed += f" @ {_short_sha(c.installed_revision)}"
        else:
            installed = "(not installed)"
        lines.append(
            f"  {c.ident:<24} {pinned:<28} {installed:<28} {c.drift.value}"
        )

    lines.append("")
    lines.append("regista quad:")
    q = inv.regista_quad
    if q.locked is not None:
        lines.append(f"  locked:  {_quad_str(q.locked)}")
    else:
        lines.append("  locked:  (none)")
    if q.current is not None:
        lines.append(f"  current: {_quad_str(q.current)}")
    else:
        lines.append("  current: (regista absent)")
    lines.append(f"  drift:   {q.drift.value}")

    lines.append("")
    if inv.memory_provider is not None:
        mp = inv.memory_provider
        name = str(mp.get("provider_name", "unknown"))
        mode = str(mp.get("deployment_mode", ""))
        support = str(mp.get("support_level", ""))
        lines.append(f"memory provider: {name} ({mode}, {support})")
    else:
        lines.append("memory provider: (none / native)")
    return "\n".join(lines)
