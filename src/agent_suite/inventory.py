"""The candidate inventory — reconcile the locked set against what's installed.

Implements WI-0.2. ``agent-suite inventory`` emits a structured view of the
suite's current state: the release identity, whether a lock is present, each
component's pinned vs installed version and revision, the regista quad (locked
vs current), the locked memory-provider extension, and now the workspace
provenance required by Plan 015 Gate 0: origin revision, local-only commits,
dirty working-tree state, plan status, and deployed version. Per-component drift
is named with a closed :class:`ComponentDrift` set so a reader can see at a
glance what matches and what has diverged — the same honest-health rule that
governs ``doctor``: a gap is a named state, not silence.

The module is stdlib-only and composes :mod:`agent_suite.doctor` (for installed
versions) and :mod:`agent_suite.lock` (for the lock + regista quad + revisions)
— it adds no new shelling beyond the origin/plan probes documented below, just a
structured reconciliation view over state the suite already probes.
``assert_never`` guards the closed drift sets in the formatting consumers
(:func:`_component_drift_label`, :func:`_quad_drift_label`) so a newly added kind
can't slip through the text formatter ungated — mirroring
:func:`agent_suite.lock.format_drift_text`. The producer functions
(:func:`_component_drift`, :func:`_quad_drift`) are total by construction
(mypy's return-type checking on the closed enum).

The inventory now also represents the umbrella repository itself, because
Plan 015 WI-0.2 AC requires "all seven repositories and the deployed estate".
A top-level ``summary`` carries the source-tree convergence gate:
``source_tree_converged`` is true only when no constituent is dirty, none
are ahead of origin, none are behind origin, every constituent's origin
provenance is known (fail-closed), and no drift is recorded. Release-
candidate readiness is broader (immutable artifacts, deployed posture,
operator config) and lives in the release board, not this field.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, assert_never

from agent_suite import doctor
from agent_suite import lock
from agent_suite.components import COMPONENTS, Component

if TYPE_CHECKING:
    from agent_suite.release_manifest import ReleaseManifest


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
    """One constituent (component or umbrella) in the candidate inventory.

    The ``provenance_known`` field is the fail-closed gate for the origin
    probe: it is ``False`` when ``_probe_origin_state`` could not determine
    the origin revision (no remote, subprocess failure, malformed output).
    A constituent with unknown provenance fails ``source_tree_converged``
    even when its local-only commit count reads zero — the read of zero is
    not the same as a confirmed-zero ahead-count.

    ``behind_origin`` is true when ``HEAD`` is at an ancestor of
    ``origin/main`` (i.e. the checkout is stale relative to upstream). The
    ahead/behind distinction matters: a checkout that is both ahead AND
    behind has diverged and needs a rebase; a checkout that is only behind
    is just stale; a checkout that is only ahead is local-only-but-current.
    """

    ident: str
    repo: str
    role: str  # "component" | "umbrella"
    origin_revision: str | None
    local_only_commits: int
    behind_origin: int
    provenance_known: bool
    working_tree_dirty: bool
    pinned_revision: str | None
    pinned_version: str | None
    installed_version: str | None
    installed_revision: str | None
    drift: ComponentDrift
    schema_version: int | None
    workflow_version: str | None
    envelope_version: int | None
    plan_status: str | None
    deployed_version: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "ident": self.ident,
            "repo": self.repo,
            "role": self.role,
            "origin_revision": self.origin_revision,
            "local_only_commits": self.local_only_commits,
            "behind_origin": self.behind_origin,
            "provenance_known": self.provenance_known,
            "working_tree_dirty": self.working_tree_dirty,
            "pinned_revision": self.pinned_revision,
            "pinned_version": self.pinned_version,
            "installed_version": self.installed_version,
            "installed_revision": self.installed_revision,
            "drift": self.drift.value,
            "schema_version": self.schema_version,
            "workflow_version": self.workflow_version,
            "envelope_version": self.envelope_version,
            "plan_status": self.plan_status,
            "deployed_version": self.deployed_version,
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
class Summary:
    """Source-tree convergence gate (Plan 015 WI-0.2 AC).

    ``source_tree_converged`` is the renamed, honest field: it reports
    whether every constituent's source tree agrees with its pinned origin
    revision at the moment of inventory collection. It is True only when:

    - no constituent has a dirty working tree,
    - no constituent has local-only commits ahead of origin,
    - no constituent is behind origin/main,
    - every constituent's origin provenance is known (fail closed),
    - every pinned component resolves to its locked version + revision,
    - the regista quad matches the locked quad.

    Release-candidate readiness is **broader** than source-tree convergence:
    it also requires immutable wheel artifacts (not editable checkouts),
    deployed-version verification, and the operator-side production posture
    documented in the release board. ``source_tree_converged`` does NOT
    claim release readiness; the release board does, and today the board
    honestly records the candidate as not publishable.
    """

    any_dirty: bool
    any_ahead: bool
    any_behind: bool
    any_provenance_unknown: bool
    drift_count: int
    source_tree_converged: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "any_dirty": self.any_dirty,
            "any_ahead": self.any_ahead,
            "any_behind": self.any_behind,
            "any_provenance_unknown": self.any_provenance_unknown,
            "drift_count": self.drift_count,
            "source_tree_converged": self.source_tree_converged,
        }


@dataclass(frozen=True)
class ConstituentBinding:
    """One constituent's binding between an inventory and a release manifest.

    ``pinned_revision_matches`` is True when the manifest's
    ``pinned_revision`` equals the inventory's ``installed_revision``.
    ``package_version_matches`` is True when the manifest's
    ``package_version`` equals the inventory's ``installed_version``.
    ``constituent_present`` is True when the constituent appears in the
    inventory at all (it may be absent if the component is not installed).
    """

    ident: str
    pinned_revision_matches: bool
    package_version_matches: bool
    constituent_present: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "ident": self.ident,
            "pinned_revision_matches": self.pinned_revision_matches,
            "package_version_matches": self.package_version_matches,
            "constituent_present": self.constituent_present,
        }


@dataclass(frozen=True)
class InventoryManifestBinding:
    """The outcome of binding an estate inventory to a release manifest.

    ``fully_bound`` is True iff every manifest constituent is present in
    the inventory AND both the pinned revision and package version match.
    A constituent that is absent from the inventory or has a divergent
    version/revision makes ``fully_bound`` False — the operator's estate
    does not match the published candidate.
    """

    release_tag: str
    bindings: tuple[ConstituentBinding, ...]
    fully_bound: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "release_tag": self.release_tag,
            "bindings": [b.to_dict() for b in self.bindings],
            "fully_bound": self.fully_bound,
        }


@dataclass(frozen=True)
class Inventory:
    release: str
    lock_file: LockFileStatus
    umbrella: ComponentInventory
    components: list[ComponentInventory]
    regista_quad: RegistaQuadInventory
    memory_provider: dict[str, object] | None
    summary: Summary
    generated_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "release": self.release,
            "lock_file": self.lock_file.to_dict(),
            "umbrella": self.umbrella.to_dict(),
            "components": [c.to_dict() for c in self.components],
            "regista_quad": self.regista_quad.to_dict(),
            "memory_provider": self.memory_provider,
            "summary": self.summary.to_dict(),
            "generated_at": self.generated_at,
        }

    def bind_to_manifest(self, manifest: ReleaseManifest) -> InventoryManifestBinding:
        """Bind this operator's estate inventory to a published release manifest.

        Returns per-constituent: ``pinned_revision_matches`` (constituent's
        ``pinned_revision`` == ``installed_revision``),
        ``package_version_matches`` (constituent's ``package_version`` ==
        ``installed_version``), ``constituent_present`` (constituent exists
        in the inventory at all).

        ``fully_bound`` is True iff every manifest constituent is present
        in the inventory AND both the pinned revision and the package
        version match for each. This is the signal an operator uses to
        confirm their estate matches a published release candidate.
        """
        # Map component ident → inventory entry for O(1) lookup.
        inv_by_ident: dict[str, ComponentInventory] = {
            c.ident: c for c in self.components
        }
        bindings: list[ConstituentBinding] = []
        for constituent in manifest.constituents:
            inv_entry = inv_by_ident.get(constituent.ident)
            if inv_entry is None:
                bindings.append(
                    ConstituentBinding(
                        ident=constituent.ident,
                        pinned_revision_matches=False,
                        package_version_matches=False,
                        constituent_present=False,
                    )
                )
                continue
            pinned_rev_matches = (
                inv_entry.installed_revision is not None
                and constituent.pinned_revision == inv_entry.installed_revision
            )
            pkg_matches = (
                inv_entry.installed_version is not None
                and constituent.package_version == inv_entry.installed_version
            )
            bindings.append(
                ConstituentBinding(
                    ident=constituent.ident,
                    pinned_revision_matches=pinned_rev_matches,
                    package_version_matches=pkg_matches,
                    constituent_present=True,
                )
            )
        fully_bound = all(
            b.constituent_present
            and b.pinned_revision_matches
            and b.package_version_matches
            for b in bindings
        )
        return InventoryManifestBinding(
            release_tag=manifest.release_tag,
            bindings=tuple(bindings),
            fully_bound=fully_bound,
        )


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
# Drift labels — assert_never enforces totality in the formatting consumers
# ---------------------------------------------------------------------------


def _component_drift_label(drift: ComponentDrift) -> str:
    """Format a :class:`ComponentDrift` as a text label for ``format_text``.

    ``match/case`` with ``assert_never`` in the default branch mirrors
    :func:`agent_suite.lock.format_drift_text`: a newly added
    :class:`ComponentDrift` value can't slip through the formatter ungated.
    """
    match drift:
        case ComponentDrift.MATCHES:
            return str(drift.value)
        case ComponentDrift.VERSION_MISMATCH:
            return str(drift.value)
        case ComponentDrift.REVISION_MISMATCH:
            return str(drift.value)
        case ComponentDrift.MISSING:
            return str(drift.value)
        case ComponentDrift.UNEXPECTED:
            return str(drift.value)
        case ComponentDrift.NOT_LOCKED:
            return str(drift.value)
        case other:
            assert_never(other)


def _quad_drift_label(drift: QuadDrift) -> str:
    """Format a :class:`QuadDrift` as a text label for ``format_text``.

    ``match/case`` with ``assert_never`` in the default branch mirrors
    :func:`agent_suite.lock.format_drift_text`: a newly added :class:`QuadDrift`
    value can't slip through the formatter ungated.
    """
    match drift:
        case QuadDrift.MATCHES:
            return str(drift.value)
        case QuadDrift.MISMATCH:
            return str(drift.value)
        case QuadDrift.MISSING:
            return str(drift.value)
        case QuadDrift.UNEXPECTED:
            return str(drift.value)
        case QuadDrift.NOT_LOCKED:
            return str(drift.value)
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Origin / plan / deployed-version probes (impure — default injection only)
# ---------------------------------------------------------------------------


def _package_root() -> Path:
    """Return the agent-suite repository root (<root> where src/ lives)."""
    return Path(__file__).resolve().parents[2]


def _checkout_path_for_ident(
    ident: str,
    search_roots: tuple[Path, ...] | None = None,
) -> Path | None:
    """Resolve the local checkout path used for origin/plan probes.

    ``ident`` is either a component ident or ``"agent-suite"`` for the
    umbrella. Returns ``None`` when no suitable checkout exists.
    """
    if ident == "agent-suite":
        root = _package_root()
        return root if (root / ".git").exists() else None

    comp = next((c for c in COMPONENTS if c.ident == ident), None)
    if comp is None:
        return None

    basename = comp.repo.split("/", 1)[-1] if "/" in comp.repo else comp.repo
    # L-4: reject path-traversal basenames (mirrors lock._probe_revision).
    if not basename or basename in (".", "..") or "/" in basename or "\\" in basename:
        return None

    roots = search_roots if search_roots is not None else lock._default_search_roots()
    for root in roots:
        candidate = root / basename
        if candidate.is_dir() and (candidate / ".git").exists():
            return candidate
    return None


def _probe_origin_state(checkout_path: Path) -> tuple[str | None, int, int, bool, bool]:
    """Return ``(origin_revision, ahead, behind, dirty, provenance_known)``.

    ``provenance_known`` is the fail-closed flag. It is True **only** when
    every relevant Git probe succeeded: origin resolution, ahead count,
    behind count, and working-tree status. If any one of them failed (no
    remote, subprocess error, malformed output), the safe-looking defaults
    remain but ``provenance_known`` is False so the summary's
    ``any_provenance_unknown`` flag fires and convergence is honestly
    withheld.

    A subtler failure mode Sol reproduced (round 3 finding #1): the prior
    implementation marked ``provenance_known=True`` as soon as
    ``git rev-parse origin/main`` succeeded, leaving the ahead/behind/dirty
    reads to fall through to their 0/0/False defaults on partial failure.
    A checkout with a known origin but a broken ahead-probe would read as
    "clean, current, not dirty" even though the ahead read failed. This
    function treats every probe as a precondition.

    ``behind`` is computed from ``git rev-list HEAD..origin/main --count``
    (commits on origin not in HEAD). ``ahead`` is ``origin/main..HEAD``.
    The two together distinguish "local-only" from "stale" from "diverged."
    """
    # Each probe records both its value AND whether it succeeded. The final
    # provenance_known flag is the AND of every probe_ok.
    origin_revision: str | None = None
    ahead = 0
    behind = 0
    dirty = False
    origin_ok = False
    ahead_ok = False
    behind_ok = False
    dirty_ok = False

    try:
        result = subprocess.run(
            ("git", "-C", str(checkout_path), "rev-parse", "origin/main"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if lock._is_valid_sha(sha):
                origin_revision = sha
                origin_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    try:
        result = subprocess.run(
            ("git", "-C", str(checkout_path), "rev-list", "origin/main..HEAD", "--count"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            ahead = int(result.stdout.strip())
            ahead_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        pass

    try:
        result = subprocess.run(
            ("git", "-C", str(checkout_path), "rev-list", "HEAD..origin/main", "--count"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            behind = int(result.stdout.strip())
            behind_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, ValueError):
        pass

    try:
        result = subprocess.run(
            ("git", "-C", str(checkout_path), "status", "--porcelain"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            dirty = bool(result.stdout.strip())
            dirty_ok = True
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass

    provenance_known = origin_ok and ahead_ok and behind_ok and dirty_ok
    return origin_revision, ahead, behind, dirty, provenance_known


_STATUS_RE = re.compile(r"^\*\*status:\*\*\s*(.+?)\s*(?:\*\*)?\s*$", re.IGNORECASE)


def _probe_plan_status(checkout_path: Path) -> str | None:
    """Scan ``checkout_path/plans`` for the newest plan file and read its status.

    The newest file is chosen by mtime. The status line must match
    ``**Status:** <value>`` (Markdown strong). Returns ``None`` when the
    directory is absent, no plan file exists, the newest file is unreadable,
    or no status line is found. This is best-effort commentary.
    """
    plans_dir = checkout_path / "plans"
    if not plans_dir.is_dir():
        return None
    files = sorted(plans_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not files:
        return None
    try:
        text = files[0].read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        match = _STATUS_RE.match(line.strip())
        if match:
            return match.group(1).strip() or None
    return None


def _probe_head(checkout_path: Path) -> str | None:
    """Return the current HEAD SHA of a checkout, or None on failure."""
    try:
        result = subprocess.run(
            ("git", "-C", str(checkout_path), "rev-parse", "HEAD"),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            sha = result.stdout.strip()
            if lock._is_valid_sha(sha):
                return sha
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def _umbrella_package_version() -> str | None:
    """Return the installed ``agent-suite`` package version, or None."""
    try:
        from importlib.metadata import version

        pkg_version = version("agent-suite")
        return pkg_version if pkg_version else None
    except Exception:
        return None


def _default_origin_probe(ident: str) -> tuple[str | None, int, int, bool, bool]:
    """Default origin-state probe used by :func:`collect_inventory`.

    Maps ``ident`` to its checkout path and runs the defensive git probes
    (origin revision, ahead, behind, dirty, provenance_known). Returns
    ``(None, 0, 0, False, False)`` when no checkout is found — note
    ``provenance_known=False`` so the failure surfaces in the summary's
    any_provenance_unknown flag (fail closed).
    """
    path = _checkout_path_for_ident(ident)
    if path is None:
        return None, 0, 0, False, False
    return _probe_origin_state(path)


def _deployed_version_env_var(ident: str) -> str:
    """Env var name used for the best-effort deployed-version lookup."""
    return f"{ident.upper().replace('-', '_')}_DEPLOYED_VERSION"


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
    origin_probe: Callable[[str], tuple[str | None, int, int, bool, bool]] = _default_origin_probe,
    plan_statuses: dict[str, str | None] | None = None,
    deployed_versions: dict[str, str | None] | None = None,
    umbrella_version: str | None = None,
    umbrella_revision: str | None = None,
) -> Inventory:
    """Build the inventory from a lock and the current installed state.

    All inputs are injectable so tests drive every drift state without
    shelling out. ``lock_obj`` is ``None`` when the lock file is absent or
    unreadable (distinguished by ``has_lock_file`` + ``lock_parseable`` so the
    report can say "present but malformed" honestly). ``release`` defaults to
    :func:`agent_suite.lock._suite_release` (the release board identity).

    ``origin_probe`` receives a component ident (or ``"agent-suite"`` for the
    umbrella) and returns ``(origin_revision, local_only_commits,
    working_tree_dirty)``. Tests inject a stub; the default uses defensive git
    commands against the workspace checkout.
    """
    rel = release if release is not None else lock._suite_release()
    lock_status = LockFileStatus(
        present=has_lock_file,
        path=str(lock_path),
        parseable=lock_parseable,
        note=lock_note,
    )

    statuses = plan_statuses if plan_statuses is not None else {}
    deployed = deployed_versions if deployed_versions is not None else {}

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

        origin_revision, ahead, behind, dirty, provenance_known = origin_probe(comp.ident)

        schema_version: int | None = None
        workflow_version: str | None = None
        envelope_version: int | None = None
        if comp.ident == "regista" and current_quad is not None:
            schema_version = current_quad.schema_version
            workflow_version = current_quad.canonical_workflow_version
            envelope_version = current_quad.envelope_version

        comp_entries.append(
            ComponentInventory(
                ident=comp.ident,
                repo=comp.repo,
                role="component",
                origin_revision=origin_revision,
                local_only_commits=ahead,
                behind_origin=behind,
                provenance_known=provenance_known,
                working_tree_dirty=dirty,
                pinned_revision=pinned_revision,
                pinned_version=pinned_version,
                installed_version=installed_version,
                installed_revision=installed_revision,
                drift=drift,
                schema_version=schema_version,
                workflow_version=workflow_version,
                envelope_version=envelope_version,
                plan_status=statuses.get(comp.ident),
                deployed_version=deployed.get(comp.ident),
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

    # Umbrella entry: the agent-suite repository itself.
    umbrella_origin, umbrella_ahead, umbrella_behind, umbrella_dirty, umbrella_provenance = (
        origin_probe("agent-suite")
    )
    # The umbrella has no SUITE.lock pin (the lock pins the constituents,
    # not the orchestrator). Drift is computed against origin/main: if the
    # local HEAD differs from origin AND provenance is known, that is a
    # real drift (local-only or stale). The earlier code hardcoded drift to
    # MATCHES, which masked both stale and divergent orchestrator checkouts.
    umbrella_drift: ComponentDrift
    if umbrella_provenance and umbrella_origin is not None:
        if umbrella_ahead > 0 or umbrella_behind > 0:
            umbrella_drift = ComponentDrift.REVISION_MISMATCH
        else:
            umbrella_drift = ComponentDrift.MATCHES
    else:
        # Provenance unknown — surface as not_locked rather than matches so
        # the summary's any_provenance_unknown flag fires (fail closed).
        umbrella_drift = ComponentDrift.NOT_LOCKED
    umbrella_entry = ComponentInventory(
        ident="agent-suite",
        repo="hraedon/agent-suite",
        role="umbrella",
        origin_revision=umbrella_origin,
        local_only_commits=umbrella_ahead,
        behind_origin=umbrella_behind,
        provenance_known=umbrella_provenance,
        working_tree_dirty=umbrella_dirty,
        pinned_revision=None,
        pinned_version=None,
        installed_version=umbrella_version if umbrella_version is not None else rel,
        installed_revision=umbrella_revision,
        drift=umbrella_drift,
        schema_version=None,
        workflow_version=None,
        envelope_version=None,
        plan_status=statuses.get("agent-suite"),
        deployed_version=deployed.get("agent-suite"),
    )

    all_constituents = [umbrella_entry, *comp_entries]
    any_dirty = any(c.working_tree_dirty for c in all_constituents)
    any_ahead = any(c.local_only_commits > 0 for c in all_constituents)
    any_behind = any(c.behind_origin > 0 for c in all_constituents)
    any_provenance_unknown = any(not c.provenance_known for c in all_constituents)
    drift_count = sum(1 for c in all_constituents if c.drift is not ComponentDrift.MATCHES)
    if quad_inv.drift is not QuadDrift.MATCHES:
        drift_count += 1
    summary = Summary(
        any_dirty=any_dirty,
        any_ahead=any_ahead,
        any_behind=any_behind,
        any_provenance_unknown=any_provenance_unknown,
        drift_count=drift_count,
        source_tree_converged=(
            not any_dirty
            and not any_ahead
            and not any_behind
            and not any_provenance_unknown
            and drift_count == 0
        ),
    )

    return Inventory(
        release=rel,
        lock_file=lock_status,
        umbrella=umbrella_entry,
        components=comp_entries,
        regista_quad=quad_inv,
        memory_provider=memory_provider,
        summary=summary,
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

    # Best-effort plan statuses and deployed versions for every constituent.
    plan_statuses: dict[str, str | None] = {}
    deployed_versions: dict[str, str | None] = {}
    for ident in ("agent-suite", *(c.ident for c in components)):
        checkout = _checkout_path_for_ident(ident)
        if checkout is not None:
            plan_statuses[ident] = _probe_plan_status(checkout)
        deployed_var = _deployed_version_env_var(ident)
        deployed_versions[ident] = os.environ.get(deployed_var)

    umbrella_checkout = _checkout_path_for_ident("agent-suite")
    umbrella_revision = _probe_head(umbrella_checkout) if umbrella_checkout is not None else None

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
        origin_probe=_default_origin_probe,
        plan_statuses=plan_statuses,
        deployed_versions=deployed_versions,
        umbrella_version=_umbrella_package_version(),
        umbrella_revision=umbrella_revision,
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


def _convergence_text(summary: Summary) -> str:
    """Render the source_tree_converged flag with named blockers.

    Reports SOURCE-TREE-CONVERGED when every gate is clean; otherwise lists
    each blocker explicitly. The release-candidate-readiness verdict lives
    in the release board, not here — see data/release-board.json WI-0.2.
    """
    if summary.source_tree_converged:
        return "SOURCE-TREE-CONVERGED"
    reasons: list[str] = []
    if summary.any_dirty:
        reasons.append("dirty workspace")
    if summary.any_ahead:
        reasons.append("unpushed commits")
    if summary.any_behind:
        reasons.append("stale vs origin")
    if summary.any_provenance_unknown:
        reasons.append("unknown origin provenance")
    if summary.drift_count:
        reasons.append(f"{summary.drift_count} drift")
    return f"NOT CONVERGED: {', '.join(reasons)}"


def format_text(inv: Inventory) -> str:
    """Human-readable summary for ``agent-suite inventory`` without ``--json``."""
    lines: list[str] = ["agent-suite candidate inventory"]
    lines.append(f"release: {inv.release}")
    lines.append(f"generated: {inv.generated_at}")
    lines.append(f"Source tree: {_convergence_text(inv.summary)}")

    if inv.lock_file.present:
        lock_tag = "present" if inv.lock_file.parseable else "present (unreadable)"
    else:
        lock_tag = "absent"
    lines.append(f"lock: {inv.lock_file.path} ({lock_tag})")
    if inv.lock_file.note:
        lines.append(f"  note: {inv.lock_file.note}")

    lines.append("")
    lines.append("umbrella:")
    lines.append(_format_constituent_line(inv.umbrella))

    lines.append("")
    lines.append("components:")
    for c in inv.components:
        lines.append(_format_constituent_line(c))

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
    lines.append(f"  drift:   {_quad_drift_label(q.drift)}")

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


def _format_constituent_line(c: ComponentInventory) -> str:
    """Format one constituent row for text output, including provenance hints."""
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
    extras: list[str] = []
    if c.working_tree_dirty:
        extras.append("dirty")
    if c.local_only_commits:
        extras.append(f"ahead:{c.local_only_commits}")
    if c.plan_status:
        extras.append(f"plan:{c.plan_status}")
    if c.deployed_version:
        extras.append(f"deployed:{c.deployed_version}")
    extra = f" ({', '.join(extras)})" if extras else ""
    return (
        f"  {c.ident:<24} {pinned:<28} {installed:<28} "
        f"{_component_drift_label(c.drift)}{extra}"
    )
