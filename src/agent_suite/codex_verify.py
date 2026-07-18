"""Operator-quality readiness verification for suite Codex plugin profiles."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, assert_never

from agent_suite.codex_catalog import (
    CodexPluginEntry,
    CodexPluginId,
    CodexPluginProfile,
    index_by_identity,
    parse_plugin_list,
    plugin_list_argv,
)
from agent_suite.codex_health import (
    CodexPluginHealthReport,
    CodexPluginHealthStatus,
    check_codex_health,
)


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


class VerifyStatus(Enum):
    PASS = "pass"
    FAIL = "fail"
    WARN = "warn"
    ACTION_REQUIRED = "action_required"
    SKIP = "skip"


@dataclass(frozen=True)
class VerifyCheck:
    name: str
    status: VerifyStatus
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "status": self.status.value, "detail": self.detail}


@dataclass
class CodexVerifyReport:
    profile: CodexPluginProfile
    marketplace: str
    ok: bool
    machine_ready: bool
    ready: bool
    checks: list[VerifyCheck] = field(default_factory=list)
    plugins: list[CodexPluginHealthReport] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "marketplace": self.marketplace,
            "ok": self.ok,
            "machine_ready": self.machine_ready,
            "ready": self.ready,
            "checks": [check.to_dict() for check in self.checks],
            "plugins": [plugin.to_dict() for plugin in self.plugins],
        }


def _safe_run(runner: Runner, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str] | None:
    try:
        return runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None


def _marketplace_check(
    runner: Runner,
    marketplace: str,
) -> VerifyCheck:
    result = _safe_run(runner, ("codex", "plugin", "marketplace", "list", "--json"))
    if result is None or result.returncode != 0:
        return VerifyCheck(
            "marketplace_configured",
            VerifyStatus.FAIL,
            f"could not inspect configured Codex marketplaces for {marketplace}",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    raw = payload.get("marketplaces") if isinstance(payload, dict) else None
    names = {
        item.get("name")
        for item in raw
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    } if isinstance(raw, list) else set()
    if marketplace not in names:
        return VerifyCheck(
            "marketplace_configured",
            VerifyStatus.FAIL,
            f"marketplace {marketplace!r} is not configured in this Codex profile",
        )
    return VerifyCheck(
        "marketplace_configured",
        VerifyStatus.PASS,
        f"marketplace {marketplace!r} is configured",
    )


def _availability_checks(
    runner: Runner,
    catalog: tuple[CodexPluginEntry, ...],
) -> list[VerifyCheck]:
    result = _safe_run(runner, plugin_list_argv(available=True))
    if result is None or result.returncode != 0:
        return [
            VerifyCheck(
                f"plugin_available:{entry.plugin_name}",
                VerifyStatus.FAIL,
                "could not inspect available Codex plugins",
            )
            for entry in catalog
        ]
    parsed = parse_plugin_list(result.stdout)
    if parsed is None:
        return [
            VerifyCheck(
                f"plugin_available:{entry.plugin_name}",
                VerifyStatus.FAIL,
                "Codex emitted malformed plugin inventory JSON",
            )
            for entry in catalog
        ]
    installed_plugins, available = parsed
    # Codex omits already-installed plugins from ``available``. Their qualified
    # installed identity still proves the configured marketplace source/pin.
    available_idx = index_by_identity([*available, *installed_plugins])
    checks: list[VerifyCheck] = []
    for entry in catalog:
        item = available_idx.get((entry.plugin_name, entry.marketplace))
        version = item.get("version") if item is not None else None
        if item is None:
            checks.append(
                VerifyCheck(
                    f"plugin_available:{entry.plugin_name}",
                    VerifyStatus.FAIL,
                    f"{entry.selector} is not published by a configured marketplace",
                )
            )
        elif version != entry.version:
            checks.append(
                VerifyCheck(
                    f"plugin_available:{entry.plugin_name}",
                    VerifyStatus.FAIL,
                    f"{entry.selector} offers v{version or 'unknown'}, pinned v{entry.version}",
                )
            )
        else:
            checks.append(
                VerifyCheck(
                    f"plugin_available:{entry.plugin_name}",
                    VerifyStatus.PASS,
                    f"{entry.selector} v{entry.version} is available",
                )
            )
    return checks


def _component_doctor_check(
    *,
    runner: Runner,
    installed: Installed,
    plugin_id: CodexPluginId,
    plugin_enabled: bool,
) -> VerifyCheck:
    command_by_plugin = {
        CodexPluginId.AGENT_NOTES: ("agent-notes", "doctor", "--json"),
        CodexPluginId.CAIRN: ("cairn", "doctor", "--json"),
        CodexPluginId.ACB: ("acb", "doctor", "--json"),
    }
    cmd = command_by_plugin.get(plugin_id)
    if cmd is None:
        return VerifyCheck(
            f"direct_install_overlap:{plugin_id.value}",
            VerifyStatus.SKIP,
            "component has no supported Codex adapter/doctor overlap probe",
        )
    if not installed(cmd[0]):
        return VerifyCheck(
            f"direct_install_overlap:{plugin_id.value}",
            VerifyStatus.WARN,
            f"{cmd[0]} doctor is unavailable; direct-install overlap was not inspected",
        )
    result = _safe_run(runner, cmd)
    if result is None:
        return VerifyCheck(
            f"direct_install_overlap:{plugin_id.value}",
            VerifyStatus.WARN,
            f"{cmd[0]} doctor could not run; direct-install overlap is unknown",
        )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = None
    raw_checks = payload.get("checks") if isinstance(payload, dict) else None
    checks = [item for item in raw_checks if isinstance(item, dict)] if isinstance(raw_checks, list) else []
    if not checks:
        return VerifyCheck(
            f"direct_install_overlap:{plugin_id.value}",
            VerifyStatus.WARN,
            f"{cmd[0]} doctor emitted no parseable overlap evidence",
        )

    if plugin_id is CodexPluginId.AGENT_NOTES:
        codex = next((item for item in checks if item.get("name") == "codex_harness"), None)
        detail = str(codex.get("detail", "")) if codex is not None else ""
        direct = "direct wired" in detail.lower() or "duplicate" in detail.lower()
    elif plugin_id is CodexPluginId.CAIRN:
        codex = next((item for item in checks if item.get("name") == "codex_harness_wired"), None)
        detail = str(codex.get("detail", "")) if codex is not None else ""
        direct = "direct" in detail.lower() and (
            "hooks configured" in detail.lower() or "both direct" in detail.lower()
        )
    elif plugin_id is CodexPluginId.ACB:
        codex_checks = [item for item in checks if item.get("harness") == "codex"]
        count = sum(item.get("status") == "ok" for item in codex_checks)
        return VerifyCheck(
            "direct_install_overlap:acb",
            VerifyStatus.PASS,
            (
                f"ACB doctor reports {count} direct Codex capability check(s); "
                "capability-specific shims are distinct from the plugin's generic guidance"
            ),
        )
    elif plugin_id is CodexPluginId.AGENT_WAKE:
        return VerifyCheck(
            "direct_install_overlap:agent-wake",
            VerifyStatus.SKIP,
            "agent-wake has no supported Codex adapter overlap to inspect",
        )
    else:
        assert_never(plugin_id)

    if direct and plugin_enabled:
        return VerifyCheck(
            f"direct_install_overlap:{plugin_id.value}",
            VerifyStatus.FAIL,
            "both the direct Codex adapter and plugin are active; remove one path",
        )
    return VerifyCheck(
        f"direct_install_overlap:{plugin_id.value}",
        VerifyStatus.PASS,
        "no direct/plugin duplication detected by the component doctor",
    )


def verify_codex_profile(
    *,
    profile: CodexPluginProfile,
    marketplace: str,
    catalog: tuple[CodexPluginEntry, ...],
    hooks_reviewed: bool = False,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> CodexVerifyReport:
    """Verify auth, marketplace, pins, overlap, and hook-trust handoff."""
    checks: list[VerifyCheck] = []
    if not installed("codex"):
        checks.append(VerifyCheck("codex_cli", VerifyStatus.FAIL, "Codex CLI is not installed"))
        return CodexVerifyReport(profile, marketplace, False, False, False, checks)

    version = _safe_run(runner, ("codex", "--version"))
    if version is None or version.returncode != 0:
        checks.append(VerifyCheck("codex_cli", VerifyStatus.FAIL, "Codex CLI could not run"))
    else:
        checks.append(VerifyCheck("codex_cli", VerifyStatus.PASS, version.stdout.strip()))

    auth = _safe_run(runner, ("codex", "login", "status"))
    checks.append(
        VerifyCheck(
            "codex_auth",
            VerifyStatus.PASS if auth is not None and auth.returncode == 0 else VerifyStatus.FAIL,
            "Codex reports an authenticated session"
            if auth is not None and auth.returncode == 0
            else "Codex authentication is unavailable; run `codex login` as the operator",
        )
    )
    checks.append(_marketplace_check(runner, marketplace))
    checks.extend(_availability_checks(runner, catalog))

    health = check_codex_health(runner=runner, installed=installed, catalog=catalog)
    plugin_enabled = {
        plugin.plugin_id: plugin.status is CodexPluginHealthStatus.INSTALLED_ENABLED
        for plugin in health.plugins
    }
    if not health.ok:
        checks.append(VerifyCheck("plugin_inventory", VerifyStatus.FAIL, health.detail))
    else:
        for plugin in health.plugins:
            status = (
                VerifyStatus.PASS
                if plugin.status is CodexPluginHealthStatus.INSTALLED_ENABLED
                else VerifyStatus.FAIL
            )
            checks.append(VerifyCheck(f"plugin_pin:{plugin.plugin_id.value}", status, plugin.detail))

    for entry in catalog:
        checks.append(
            _component_doctor_check(
                runner=runner,
                installed=installed,
                plugin_id=entry.plugin_id,
                plugin_enabled=plugin_enabled.get(entry.plugin_id, False),
            )
        )

    cairn_enabled = plugin_enabled.get(CodexPluginId.CAIRN, False)
    if not cairn_enabled:
        checks.append(
            VerifyCheck(
                "hook_trust_handoff",
                VerifyStatus.SKIP,
                "Cairn is not enabled, so hook review cannot complete",
            )
        )
    elif hooks_reviewed:
        checks.append(
            VerifyCheck(
                "hook_trust_handoff",
                VerifyStatus.PASS,
                "operator asserted /hooks review for this invocation; assertion is not persisted",
            )
        )
    else:
        checks.append(
            VerifyCheck(
                "hook_trust_handoff",
                VerifyStatus.ACTION_REQUIRED,
                "open a trusted Codex session, review Cairn command hooks with /hooks, then rerun with --hooks-reviewed",
            )
        )

    failed = any(check.status is VerifyStatus.FAIL for check in checks)
    action_required = any(check.status is VerifyStatus.ACTION_REQUIRED for check in checks)
    machine_ready = not failed
    return CodexVerifyReport(
        profile=profile,
        marketplace=marketplace,
        ok=not failed,
        machine_ready=machine_ready,
        ready=machine_ready and not action_required,
        checks=checks,
        plugins=health.plugins,
    )


def format_codex_verify_text(report: CodexVerifyReport) -> str:
    lines = [
        f"agent-suite Codex verify ({report.profile.value})",
        f"  marketplace: {report.marketplace}",
    ]
    for check in report.checks:
        lines.append(f"  {check.name:<38} {check.status.value:<16} {check.detail}")
    lines.append(
        f"  machine-ready: {'yes' if report.machine_ready else 'no'}; "
        f"operator-ready: {'yes' if report.ready else 'no'}"
    )
    return "\n".join(lines)
