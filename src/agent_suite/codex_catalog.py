"""Suite-owned Codex plugin catalog and composition.

Plan 007 WI-0.1: the suite pins four component plugins and installs them
through Codex's *supported* plugin mechanism.  This module owns the catalog
metadata and the add/remove composition logic.  It does not vendor component
assets — each plugin is published by a Codex **marketplace** and the suite
references it by its ``name@marketplace`` selector.

Ground truth (Codex CLI 0.144.5, validated live 2026-07-17):

- Plugins are installed with ``codex plugin add <PLUGIN@MARKETPLACE>`` and
  removed with ``codex plugin remove <PLUGIN@MARKETPLACE>``.  There is no
  ``install`` / ``uninstall`` verb, and ``add`` takes a *marketplace selector*,
  never a raw component directory.
- ``codex plugin list --json`` emits ``{"installed": [...], "available": [...]}``.
  Installed entries carry ``pluginId`` (== ``name@marketplace``), ``name``,
  ``marketplaceName``, ``version`` and ``enabled``.  ``--available`` additionally
  lists installable (not-yet-installed) marketplace plugins.
- A marketplace must be configured first via
  ``codex plugin marketplace add <SOURCE>`` (a local path or Git source).
- ``add`` and ``remove`` are idempotent (re-running exits 0).

Design (AGENTS.md):
- Thin orchestration: shells ``codex plugin add/remove/list``, never
  reimplements plugin resolution or asset copying.
- Idempotent: a plugin already present is a no-op; one whose marketplace does
  not publish it is honestly ``UNSUPPORTED`` (fail-closed — never a silent
  success), not skipped-as-green.
- ``--dry-run`` prints the plan without acting.
- Injectable runner + installed check (same pattern as bootstrap/doctor).
- stdlib-only core.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, assert_never


# ---------------------------------------------------------------------------
# Injectable interfaces (same shape as bootstrap.Runner / doctor.Runner)
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a Codex CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches ``shutil.which``)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=120)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
# The marketplace the suite release publishes its component plugins from.
# Operators (or the fixture test harness) may override this per invocation.
# ---------------------------------------------------------------------------

SUITE_MARKETPLACE = "agent-suite"


# ---------------------------------------------------------------------------
# Closed-set enums
# ---------------------------------------------------------------------------


class CodexPluginId(Enum):
    """The four pinned component plugins in the suite catalog.

    The value is the Codex plugin ``name`` (the stable component identity);
    the marketplace-qualified selector is ``name@marketplace``.
    """

    AGENT_NOTES = "agent-notes"
    CAIRN = "cairn"
    ACB = "acb"
    AGENT_WAKE = "agent-wake"


class CodexPluginProfile(Enum):
    """Named Codex plugin slices with progressively stronger requirements."""

    CORE = "core"
    CREDENTIALED = "credentialed"
    FULL = "full"


class PluginStepStatus(Enum):
    """The outcome of a single plugin add/remove step.

    The composition loops use ``in`` membership checks against success-status
    sets, which are safe-by-default: a newly added status defaults to not-ok
    without requiring an exhaustive match.  ``UNSUPPORTED`` and ``FAILED`` are
    both non-success — an un-published or errored plugin never counts green.
    """

    PENDING = "pending"
    INSTALLED = "installed"
    ALREADY_INSTALLED = "already_installed"
    REMOVED = "removed"
    ALREADY_ABSENT = "already_absent"
    UNSUPPORTED = "unsupported"
    VERSION_MISMATCH = "version_mismatch"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Catalog — the four pinned plugins
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CodexPluginEntry:
    """One pinned Codex plugin in the suite catalog.

    ``plugin_name`` is the Codex plugin ``name`` and ``marketplace`` is the
    marketplace that publishes it; together they form the ``name@marketplace``
    selector passed to ``codex plugin add/remove``.  The suite does not vendor
    the plugin asset — it is published by the (release or fixture) marketplace.
    """

    plugin_id: CodexPluginId
    component_ident: str
    plugin_name: str
    marketplace: str
    version: str

    @property
    def selector(self) -> str:
        """The ``name@marketplace`` selector Codex's plugin commands accept."""
        return f"{self.plugin_name}@{self.marketplace}"


CODEX_PLUGIN_CATALOG: tuple[CodexPluginEntry, ...] = (
    CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_NOTES,
        component_ident="agent-notes",
        plugin_name="agent-notes",
        marketplace=SUITE_MARKETPLACE,
        version="1.0.0",
    ),
    CodexPluginEntry(
        plugin_id=CodexPluginId.CAIRN,
        component_ident="agent-provenance",
        plugin_name="cairn",
        marketplace=SUITE_MARKETPLACE,
        version="0.1.0",
    ),
    CodexPluginEntry(
        plugin_id=CodexPluginId.ACB,
        component_ident="agent-capability-broker",
        plugin_name="acb",
        marketplace=SUITE_MARKETPLACE,
        version="0.1.0",
    ),
    CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_WAKE,
        component_ident="agent-wake",
        plugin_name="agent-wake",
        marketplace=SUITE_MARKETPLACE,
        version="0.1.0",
    ),
)


def catalog_for_profile(
    profile: CodexPluginProfile,
    catalog: tuple[CodexPluginEntry, ...] = CODEX_PLUGIN_CATALOG,
) -> tuple[CodexPluginEntry, ...]:
    """Select the plugins required for a named Codex testing/deployment slice.

    ``core`` is the minimum useful Plan 007 path (agent-notes + Cairn).
    ``credentialed`` adds ACB. ``full`` also adds wake, whose Codex adapter may
    remain experimental without blocking either smaller slice.
    """
    match profile:
        case CodexPluginProfile.CORE:
            required = frozenset({CodexPluginId.AGENT_NOTES, CodexPluginId.CAIRN})
        case CodexPluginProfile.CREDENTIALED:
            required = frozenset(
                {
                    CodexPluginId.AGENT_NOTES,
                    CodexPluginId.CAIRN,
                    CodexPluginId.ACB,
                }
            )
        case CodexPluginProfile.FULL:
            required = frozenset(CodexPluginId)
        case other:
            assert_never(other)
    return tuple(entry for entry in catalog if entry.plugin_id in required)


def catalog_by_plugin_id(
    plugin_id: CodexPluginId,
    catalog: tuple[CodexPluginEntry, ...] = CODEX_PLUGIN_CATALOG,
) -> CodexPluginEntry:
    """Look up a catalog entry by plugin id.  Raises ``KeyError`` if not found."""
    for entry in catalog:
        if entry.plugin_id is plugin_id:
            return entry
    raise KeyError(f"plugin not in catalog: {plugin_id.value}")


def with_marketplace(
    catalog: tuple[CodexPluginEntry, ...],
    marketplace: str,
) -> tuple[CodexPluginEntry, ...]:
    """Return a copy of ``catalog`` with every entry's marketplace overridden.

    Used when an operator (or the fixture test harness) installs the pinned set
    from a marketplace other than the release default — e.g. a local fixture.
    """
    return tuple(
        CodexPluginEntry(
            plugin_id=e.plugin_id,
            component_ident=e.component_ident,
            plugin_name=e.plugin_name,
            marketplace=marketplace,
            version=e.version,
        )
        for e in catalog
    )


# ---------------------------------------------------------------------------
# argv builders
# ---------------------------------------------------------------------------


def plugin_add_argv(selector: str, *, json_output: bool = True) -> tuple[str, ...]:
    """Build the ``codex plugin add <name@marketplace>`` argv."""
    base = ("codex", "plugin", "add", selector)
    return base + (("--json",) if json_output else ())


def plugin_remove_argv(selector: str, *, json_output: bool = True) -> tuple[str, ...]:
    """Build the ``codex plugin remove <name@marketplace>`` argv."""
    base = ("codex", "plugin", "remove", selector)
    return base + (("--json",) if json_output else ())


def plugin_list_argv(*, available: bool = False, json_output: bool = True) -> tuple[str, ...]:
    """Build the ``codex plugin list`` argv."""
    base: tuple[str, ...] = ("codex", "plugin", "list")
    if available:
        base = base + ("--available",)
    return base + (("--json",) if json_output else ())


# ---------------------------------------------------------------------------
# JSON parsing (real ``codex plugin list --json`` envelope)
# ---------------------------------------------------------------------------


def parse_plugin_list(
    stdout: str,
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    """Parse ``codex plugin list --json`` into ``(installed, available)`` lists.

    The real payload is an object ``{"installed": [...], "available": [...]}``.
    Empty stdout is treated as no plugins (a valid, healthy state).  Returns
    ``None`` on genuine parse failure (non-JSON, or a non-object payload) so
    callers can distinguish "empty" from "malformed".  Never raises.
    """
    if not stdout.strip():
        return ([], [])
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    installed_raw = payload.get("installed")
    available_raw = payload.get("available")
    installed = (
        [p for p in installed_raw if isinstance(p, dict)] if isinstance(installed_raw, list) else []
    )
    available = (
        [p for p in available_raw if isinstance(p, dict)] if isinstance(available_raw, list) else []
    )
    return (installed, available)


def _plugin_names(entries: list[dict[str, object]]) -> set[str]:
    """Collect the ``name`` field from a list of plugin dicts."""
    names: set[str] = set()
    for p in entries:
        name = p.get("name")
        if isinstance(name, str):
            names.add(name)
    return names


def index_by_identity(
    entries: list[dict[str, object]],
) -> dict[tuple[str, str], dict[str, object]]:
    """Index plugin dicts by their full ``(name, marketplaceName)`` identity.

    A pinned plugin is only ever matched by this qualified identity — never by
    unqualified name — so a same-name plugin from a *different* marketplace can
    never masquerade as the pinned one.
    """
    idx: dict[tuple[str, str], dict[str, object]] = {}
    for p in entries:
        name = p.get("name")
        market = p.get("marketplaceName")
        if isinstance(name, str) and isinstance(market, str):
            idx[(name, market)] = p
    return idx


def _entry_version(plugin_data: dict[str, object]) -> str | None:
    """Read the ``version`` field of a plugin dict, if present as a string."""
    raw = plugin_data.get("version")
    return raw if isinstance(raw, str) else None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class PluginStepResult:
    """The outcome of one plugin add/remove step."""

    plugin_id: CodexPluginId
    status: PluginStepStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin_id": self.plugin_id.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class CodexPluginInstallResult:
    """The full plugin add or remove outcome.

    ``action`` is ``"install"`` or ``"uninstall"``.  ``dry_run`` is True when
    the plan was printed without acting.
    """

    ok: bool
    dry_run: bool
    action: str
    results: list[PluginStepResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "action": self.action,
            "results": [r.to_dict() for r in self.results],
        }


# ---------------------------------------------------------------------------
# Plugin-state discovery
# ---------------------------------------------------------------------------


def _discover_plugin_state(
    runner: Runner,
    installed: Installed,
    *,
    available: bool,
) -> tuple[
    tuple[list[dict[str, object]], list[dict[str, object]]] | None,
    str | None,
]:
    """Run ``codex plugin list`` once and return the raw ``(installed, available)``.

    Returns ``(state, error)``. Callers must fail closed when ``state`` is
    unknown; an unreadable plugin registry cannot prove absence or support.
    """
    if not installed("codex"):
        return None, "codex CLI not installed"
    try:
        result = runner(plugin_list_argv(available=available))
    except Exception as exc:
        return None, f"codex plugin list failed: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or "no detail"
        return None, f"codex plugin list exited {result.returncode}: {detail}"
    parsed = parse_plugin_list(result.stdout)
    if parsed is None:
        return None, "codex plugin list emitted malformed JSON"
    return parsed, None


# ---------------------------------------------------------------------------
# install / uninstall composition
# ---------------------------------------------------------------------------


def install_codex_plugins(
    *,
    marketplace: str | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    catalog: tuple[CodexPluginEntry, ...] = CODEX_PLUGIN_CATALOG,
) -> CodexPluginInstallResult:
    """Install the suite-pinned Codex plugin set via ``codex plugin add``.

    Installation is idempotent: a plugin already present (by ``name``) is
    reported ``ALREADY_INSTALLED`` without re-running ``add``.  A plugin that no
    configured marketplace publishes is reported ``UNSUPPORTED`` and makes the
    overall result not-ok — the suite fails closed rather than painting an
    un-wired plugin green.

    ``marketplace`` overrides every entry's marketplace (e.g. to install from a
    local fixture marketplace instead of the release default).
    """
    if marketplace is not None:
        catalog = with_marketplace(catalog, marketplace)

    if not dry_run and not installed("codex"):
        return CodexPluginInstallResult(
            ok=False,
            dry_run=False,
            action="install",
            results=[
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    "codex CLI not installed — cannot install plugins",
                )
                for entry in catalog
            ],
        )

    installed_idx: dict[tuple[str, str], dict[str, object]] = {}
    available_idx: dict[tuple[str, str], dict[str, object]] = {}
    installed_names: set[str] = set()
    if not dry_run:
        state, state_error = _discover_plugin_state(runner, installed, available=True)
        if state is None:
            return CodexPluginInstallResult(
                ok=False,
                dry_run=False,
                action="install",
                results=[
                    PluginStepResult(
                        entry.plugin_id,
                        PluginStepStatus.FAILED,
                        state_error or "codex plugin state is unknown",
                    )
                    for entry in catalog
                ],
            )
        installed_list, available_list = state
        installed_idx = index_by_identity(installed_list)
        available_idx = index_by_identity(available_list)
        installed_names = _plugin_names(installed_list)

    results: list[PluginStepResult] = []

    for entry in catalog:
        if dry_run:
            cmd = plugin_add_argv(entry.selector)
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.PENDING,
                    f"would run: {' '.join(cmd)}",
                )
            )
            continue

        key = (entry.plugin_name, entry.marketplace)

        # Idempotency is judged by *qualified* identity + the version pin, so a
        # same-name plugin from another marketplace (or a wrong version) can
        # never report a false already-installed.
        inst = installed_idx.get(key)
        if inst is not None:
            inst_ver = _entry_version(inst)
            if inst_ver == entry.version:
                results.append(
                    PluginStepResult(
                        entry.plugin_id,
                        PluginStepStatus.ALREADY_INSTALLED,
                        f"{entry.selector} already installed (v{entry.version})",
                    )
                )
            else:
                results.append(
                    PluginStepResult(
                        entry.plugin_id,
                        PluginStepStatus.VERSION_MISMATCH,
                        f"{entry.selector} installed at v{inst_ver or 'unknown'}, "
                        f"pinned v{entry.version}",
                    )
                )
            continue

        avail = available_idx.get(key)
        if avail is None:
            detail = (
                f"no configured marketplace publishes {entry.selector}; "
                f"add one with `codex plugin marketplace add <source>`"
            )
            if entry.plugin_name in installed_names:
                detail += (
                    f" (a plugin named {entry.plugin_name} is installed from a "
                    f"different marketplace, which does not satisfy the pin)"
                )
            results.append(PluginStepResult(entry.plugin_id, PluginStepStatus.UNSUPPORTED, detail))
            continue

        avail_ver = _entry_version(avail)
        if avail_ver is not None and avail_ver != entry.version:
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.VERSION_MISMATCH,
                    f"{entry.selector} marketplace offers v{avail_ver}, pinned v{entry.version}",
                )
            )
            continue

        cmd = plugin_add_argv(entry.selector)
        try:
            result = runner(cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    f"add failed: {exc}",
                )
            )
            continue

        if result.returncode != 0:
            stderr = result.stderr.strip()
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    f"codex plugin add exited {result.returncode}: {stderr or 'no detail'}",
                )
            )
            continue

        results.append(
            PluginStepResult(
                entry.plugin_id,
                PluginStepStatus.INSTALLED,
                f"{entry.plugin_name} installed (v{entry.version})",
            )
        )

    if dry_run:
        return CodexPluginInstallResult(ok=True, dry_run=True, action="install", results=results)

    return CodexPluginInstallResult(
        ok=all(
            r.status in (PluginStepStatus.INSTALLED, PluginStepStatus.ALREADY_INSTALLED)
            for r in results
        ),
        dry_run=False,
        action="install",
        results=results,
    )


def uninstall_codex_plugins(
    *,
    marketplace: str | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    catalog: tuple[CodexPluginEntry, ...] = CODEX_PLUGIN_CATALOG,
) -> CodexPluginInstallResult:
    """Uninstall the suite-pinned Codex plugin set via ``codex plugin remove``.

    Idempotent: a plugin already absent is reported ``ALREADY_ABSENT``.
    """
    if marketplace is not None:
        catalog = with_marketplace(catalog, marketplace)

    if not dry_run and not installed("codex"):
        return CodexPluginInstallResult(
            ok=False,
            dry_run=False,
            action="uninstall",
            results=[
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    "codex CLI not installed — cannot uninstall plugins",
                )
                for entry in catalog
            ],
        )

    installed_idx: dict[tuple[str, str], dict[str, object]] = {}
    if not dry_run:
        state, state_error = _discover_plugin_state(runner, installed, available=False)
        if state is None:
            return CodexPluginInstallResult(
                ok=False,
                dry_run=False,
                action="uninstall",
                results=[
                    PluginStepResult(
                        entry.plugin_id,
                        PluginStepStatus.FAILED,
                        state_error or "codex plugin state is unknown",
                    )
                    for entry in catalog
                ],
            )
        installed_list, _ = state
        installed_idx = index_by_identity(installed_list)

    results: list[PluginStepResult] = []

    for entry in catalog:
        if dry_run:
            cmd = plugin_remove_argv(entry.selector)
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.PENDING,
                    f"would run: {' '.join(cmd)}",
                )
            )
            continue

        # Remove only the pinned plugin (by qualified identity); a same-name
        # plugin from another marketplace is not ours to touch.
        if (entry.plugin_name, entry.marketplace) not in installed_idx:
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.ALREADY_ABSENT,
                    f"{entry.selector} not installed (nothing to remove)",
                )
            )
            continue

        cmd = plugin_remove_argv(entry.selector)
        try:
            result = runner(cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    f"remove failed: {exc}",
                )
            )
            continue

        if result.returncode != 0:
            stderr = result.stderr.strip()
            results.append(
                PluginStepResult(
                    entry.plugin_id,
                    PluginStepStatus.FAILED,
                    f"codex plugin remove exited {result.returncode}: {stderr or 'no detail'}",
                )
            )
            continue

        results.append(
            PluginStepResult(
                entry.plugin_id,
                PluginStepStatus.REMOVED,
                f"{entry.plugin_name} removed",
            )
        )

    if dry_run:
        return CodexPluginInstallResult(ok=True, dry_run=True, action="uninstall", results=results)

    return CodexPluginInstallResult(
        ok=all(
            r.status in (PluginStepStatus.REMOVED, PluginStepStatus.ALREADY_ABSENT) for r in results
        ),
        dry_run=False,
        action="uninstall",
        results=results,
    )


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_install_text(result: CodexPluginInstallResult) -> str:
    """Human-readable summary for plugin install/uninstall without --json."""
    verb = "install" if result.action == "install" else "uninstall"
    if result.dry_run:
        lines: list[str] = [f"agent-suite codex-plugins {verb} --dry-run (plan, no actions taken)"]
    else:
        lines = [f"agent-suite codex-plugins {verb}"]
    lines.append("")
    for r in result.results:
        lines.append(f"  {r.plugin_id.value:<22} {r.status.value:<22} {r.detail}")
    lines.append("")
    lines.append(f"codex-plugins {verb}: {'OK' if result.ok else 'NOT OK'}")
    return "\n".join(lines)
