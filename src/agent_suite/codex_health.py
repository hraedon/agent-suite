"""Codex-aware plugin health for the suite doctor.

Plan 007 WI-2.1: the umbrella doctor reports the state of each pinned Codex
component plugin.  This module is read-only (like the doctor itself) and never
raises — a failed ``codex`` command is a named state, never a traceback.

Ground truth (Codex CLI 0.144.5, validated live 2026-07-17):

- The only stable, machine-readable window into plugin state is
  ``codex plugin list --json`` → ``{"installed": [...], "available": [...]}``,
  where each installed entry carries ``name``, ``version`` and ``enabled``.
- **There is no ``codex hooks status`` command.**  Hook *trust* is granted
  through Codex's interactive ``/hooks`` review inside a session; it is not
  exposed by any CLI, so the doctor cannot observe whether a plugin's command
  hooks have been trusted, blocked by managed policy, or exercised.

The doctor therefore reports exactly what the CLI can prove — plugin absent,
installed-and-disabled, or installed-and-enabled — and defers hook-trust
confirmation to the operator's ``/hooks`` review (see
``docs/install-harness-contract.md`` §2).  Claiming trust/activity states from a
command that does not exist would be dishonest health.

Design (AGENTS.md):
- stdlib-only core.
- Injectable runner + installed check (same pattern as doctor).
- ``assert_never`` over every closed-set enum.
- Informational: Codex is experimental and not in the stable ``all`` expansion,
  so plugin states do not affect ``suite_ok``.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, assert_never

from agent_suite.codex_catalog import (
    CODEX_PLUGIN_CATALOG,
    CodexPluginEntry,
    CodexPluginId,
    parse_plugin_list,
    plugin_list_argv,
)

# Guidance appended to an installed-enabled plugin: the one thing the CLI
# cannot tell us is whether the plugin's command hooks have been trusted.
_HOOK_TRUST_NOTE = (
    "hook trust is confirmed via Codex's interactive /hooks review and is not "
    "observable via the CLI"
)


# ---------------------------------------------------------------------------
# Injectable interfaces
# ---------------------------------------------------------------------------


class Runner(Protocol):
    """Run a Codex CLI command and return the completed process."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a CLI is installed (matches ``shutil.which``)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


# ---------------------------------------------------------------------------
# Closed-set enum (assert_never in every dispatch)
# ---------------------------------------------------------------------------


class CodexPluginHealthStatus(Enum):
    """The Codex plugin health states the doctor can observe via the CLI.

    A plugin is matched by its *qualified* ``(name, marketplace)`` identity, so
    a same-name plugin from a different marketplace does not satisfy the pin.
    These states are determinable from ``codex plugin list --json``:

    - PLUGIN_ABSENT: the pinned plugin is not installed.
    - INSTALLED_DISABLED: the pinned plugin is installed but disabled.
    - INSTALLED_ENABLED: the pinned plugin is installed, enabled, and at the
      pinned version.  Whether its command hooks have been *trusted* is
      confirmed through Codex's interactive ``/hooks`` review (no CLI exposes it).
    - VERSION_MISMATCH: the pinned plugin is installed and enabled but at a
      version other than the one the catalog pins.
    - INVALID_METADATA: Codex returned the qualified plugin but did not provide
      an explicit boolean ``enabled`` field or string ``version`` field. Such
      incomplete inventory can never satisfy readiness.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in any dispatch.
    """

    PLUGIN_ABSENT = "plugin_absent"
    INSTALLED_DISABLED = "installed_disabled"
    INSTALLED_ENABLED = "installed_enabled"
    VERSION_MISMATCH = "version_mismatch"
    INVALID_METADATA = "invalid_metadata"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class CodexPluginHealthReport:
    """The health of one Codex plugin."""

    plugin_id: CodexPluginId
    status: CodexPluginHealthStatus
    detail: str = ""
    version: str | None = None
    enabled: bool | None = None

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "plugin_id": self.plugin_id.value,
            "status": self.status.value,
            "detail": self.detail,
        }
        if self.version is not None:
            d["version"] = self.version
        if self.enabled is not None:
            d["enabled"] = self.enabled
        return d


@dataclass
class CodexHealthReport:
    """The full Codex health report.

    ``ok`` describes whether the read-only probe ran successfully. ``ready``
    separately describes whether every required plugin is installed, enabled,
    and at its pinned version. This prevents a successful CLI invocation from
    being mistaken for a ready Codex integration.
    """

    ok: bool
    codex_installed: bool
    ready: bool = False
    codex_version: str | None = None
    plugins: list[CodexPluginHealthReport] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "ok": self.ok,
            "ready": self.ready,
            "codex_installed": self.codex_installed,
            "plugins": [p.to_dict() for p in self.plugins],
        }
        if self.codex_version is not None:
            d["codex_version"] = self.codex_version
        if self.detail:
            d["detail"] = self.detail
        return d


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _plugin_lookup(
    plugins: list[dict[str, object]],
    plugin_name: str,
    marketplace: str,
) -> dict[str, object] | None:
    """Find an installed plugin dict by its qualified ``(name, marketplace)``.

    Matching on the full identity — never the unqualified name — means a
    same-name plugin published by a different marketplace never satisfies the
    pin (it reads as absent, not as a false green).
    """
    for p in plugins:
        name = p.get("name")
        market = p.get("marketplaceName")
        if (
            isinstance(name, str)
            and isinstance(market, str)
            and name == plugin_name
            and market == marketplace
        ):
            return p
    return None


def _determine_plugin_status(
    plugin_entry: CodexPluginEntry,
    installed_list: list[dict[str, object]],
) -> CodexPluginHealthReport:
    """Determine the health status of one pinned plugin from ``codex plugin list``.

    Identity is the qualified ``(name, marketplace)`` selector and the version
    is validated against the catalog pin.
    """
    plugin_data = _plugin_lookup(installed_list, plugin_entry.plugin_name, plugin_entry.marketplace)
    if plugin_data is None:
        # Distinguish "truly absent" from "a different-marketplace variant is
        # present" so the operator sees why the pin is unsatisfied.
        detail = f"{plugin_entry.selector} not installed"
        for p in installed_list:
            if p.get("name") == plugin_entry.plugin_name:
                detail += (
                    f" (a plugin named {plugin_entry.plugin_name} is installed "
                    f"from a different marketplace, which does not satisfy the pin)"
                )
                break
        return CodexPluginHealthReport(
            plugin_id=plugin_entry.plugin_id,
            status=CodexPluginHealthStatus.PLUGIN_ABSENT,
            detail=detail,
        )

    version_raw = plugin_data.get("version")
    version = version_raw if isinstance(version_raw, str) else None

    enabled_raw = plugin_data.get("enabled")
    enabled = enabled_raw if isinstance(enabled_raw, bool) else None

    if enabled is None:
        return CodexPluginHealthReport(
            plugin_id=plugin_entry.plugin_id,
            status=CodexPluginHealthStatus.INVALID_METADATA,
            detail=f"{plugin_entry.selector} inventory has no explicit boolean enabled state",
            version=version,
            enabled=None,
        )

    if version is None:
        return CodexPluginHealthReport(
            plugin_id=plugin_entry.plugin_id,
            status=CodexPluginHealthStatus.INVALID_METADATA,
            detail=f"{plugin_entry.selector} inventory has no string version",
            version=None,
            enabled=enabled,
        )

    if enabled is False:
        return CodexPluginHealthReport(
            plugin_id=plugin_entry.plugin_id,
            status=CodexPluginHealthStatus.INSTALLED_DISABLED,
            detail=f"{plugin_entry.selector} installed but disabled",
            version=version,
            enabled=False,
        )

    if version is not None and version != plugin_entry.version:
        return CodexPluginHealthReport(
            plugin_id=plugin_entry.plugin_id,
            status=CodexPluginHealthStatus.VERSION_MISMATCH,
            detail=(
                f"{plugin_entry.selector} installed at v{version}, pinned v{plugin_entry.version}"
            ),
            version=version,
            enabled=enabled,
        )

    return CodexPluginHealthReport(
        plugin_id=plugin_entry.plugin_id,
        status=CodexPluginHealthStatus.INSTALLED_ENABLED,
        detail=f"{plugin_entry.selector} installed and enabled ({_HOOK_TRUST_NOTE})",
        version=version,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_codex_health(
    *,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
    catalog: tuple[CodexPluginEntry, ...] = CODEX_PLUGIN_CATALOG,
    required_plugin_ids: frozenset[CodexPluginId] | None = None,
) -> CodexHealthReport:
    """Check Codex plugin health for every catalog plugin.

    Shells a single ``codex plugin list --json``.  When the Codex CLI is not
    installed, returns a report with ``codex_installed=False`` and no plugin
    checks.  When the CLI is installed but the command fails or emits malformed
    output, returns ``ok=False`` with a named detail — never raises.

    When ``required_plugin_ids`` is omitted, every entry in ``catalog`` is
    required. The umbrella doctor can pass a smaller core set while still
    reporting optional plugin states.
    """
    if not installed("codex"):
        return CodexHealthReport(
            ok=True,
            codex_installed=False,
            plugins=[],
            detail="codex CLI not installed — Codex health not checked",
        )

    try:
        list_result = runner(plugin_list_argv())
    except FileNotFoundError:
        return CodexHealthReport(
            ok=True,
            codex_installed=False,
            detail="codex CLI not found at run time",
        )
    except subprocess.TimeoutExpired:
        return CodexHealthReport(
            ok=False,
            codex_installed=True,
            detail="codex plugin list timed out",
        )
    except OSError as exc:
        return CodexHealthReport(
            ok=False,
            codex_installed=True,
            detail=f"codex plugin list could not run: {exc}",
        )
    except Exception as exc:
        return CodexHealthReport(
            ok=False,
            codex_installed=True,
            detail=f"codex plugin list raised unexpectedly: {exc}",
        )

    if list_result.returncode != 0:
        stderr = list_result.stderr.strip()
        return CodexHealthReport(
            ok=False,
            codex_installed=True,
            detail=f"codex plugin list failed: {stderr or 'no detail'}",
        )

    parsed = parse_plugin_list(list_result.stdout)
    if parsed is None:
        return CodexHealthReport(
            ok=False,
            codex_installed=True,
            detail="codex plugin list emitted non-JSON or malformed output",
        )
    installed_list, _available_list = parsed

    plugin_reports = [_determine_plugin_status(entry, installed_list) for entry in catalog]
    required = (
        required_plugin_ids
        if required_plugin_ids is not None
        else frozenset(entry.plugin_id for entry in catalog)
    )
    report_by_id = {report.plugin_id: report for report in plugin_reports}
    ready = bool(required) and all(
        plugin_id in report_by_id
        and report_by_id[plugin_id].status is CodexPluginHealthStatus.INSTALLED_ENABLED
        for plugin_id in required
    )

    return CodexHealthReport(
        ok=True,
        codex_installed=True,
        ready=ready,
        codex_version=None,
        plugins=plugin_reports,
        detail="",
    )


# ---------------------------------------------------------------------------
# Dispatch helpers
# ---------------------------------------------------------------------------


def is_actionable_status(status: CodexPluginHealthStatus) -> bool:
    """Whether a plugin status requires operator attention.

    An installed-but-disabled plugin is the one CLI-observable state that
    usually wants attention (the operator wired it, then turned it off).
    ``assert_never`` keeps this exhaustive over the enum.
    """
    match status:
        case CodexPluginHealthStatus.INSTALLED_DISABLED:
            return True
        case CodexPluginHealthStatus.VERSION_MISMATCH:
            return True
        case CodexPluginHealthStatus.INVALID_METADATA:
            return True
        case CodexPluginHealthStatus.PLUGIN_ABSENT | CodexPluginHealthStatus.INSTALLED_ENABLED:
            return False
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_codex_health_text(report: CodexHealthReport) -> str:
    """Human-readable summary for the Codex health section."""
    lines: list[str] = ["codex health:"]
    if not report.codex_installed:
        lines.append(f"  codex: not installed  {report.detail}")
        return "\n".join(lines)
    ver = f" v{report.codex_version}" if report.codex_version else ""
    lines.append(f"  codex: installed{ver}")
    if not report.ok:
        lines.append(f"  health check error: {report.detail}")
        return "\n".join(lines)
    lines.append(f"  required plugins: {'ready' if report.ready else 'not ready'}")
    for p in report.plugins:
        lines.append(f"  {p.plugin_id.value:<22} {p.status.value:<28} {p.detail}")
    return "\n".join(lines)
