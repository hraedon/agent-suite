from __future__ import annotations

import json
import subprocess

from agent_suite.codex_catalog import CodexPluginEntry, CodexPluginId, CodexPluginProfile
from agent_suite.codex_verify import VerifyStatus, verify_codex_profile


_CATALOG = (
    CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_NOTES,
        component_ident="agent-notes",
        plugin_name="agent-notes",
        marketplace="local-proof",
        version="1.0.0",
    ),
    CodexPluginEntry(
        plugin_id=CodexPluginId.CAIRN,
        component_ident="agent-provenance",
        plugin_name="cairn",
        marketplace="local-proof",
        version="0.1.0",
    ),
)


def _proc(cmd: tuple[str, ...], code: int = 0, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")


def _plugin_payload() -> str:
    installed = [
        {
            "name": entry.plugin_name,
            "marketplaceName": entry.marketplace,
            "version": entry.version,
            "enabled": True,
        }
        for entry in _CATALOG
    ]
    return json.dumps({"installed": installed, "available": installed})


class ReadyRunner:
    direct_notes = False
    direct_cairn = False

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        if cmd == ("codex", "--version"):
            return _proc(cmd, stdout="codex-cli 0.144.5\n")
        if cmd == ("codex", "login", "status"):
            return _proc(cmd, stdout="Logged in\n")
        if cmd == ("codex", "plugin", "marketplace", "list", "--json"):
            return _proc(cmd, stdout=json.dumps({"marketplaces": [{"name": "local-proof"}]}))
        if cmd in {
            ("codex", "plugin", "list", "--available", "--json"),
            ("codex", "plugin", "list", "--json"),
        }:
            return _proc(cmd, stdout=_plugin_payload())
        if cmd == ("agent-notes", "doctor", "--json"):
            status = "ok" if self.direct_notes else "skip"
            detail = "codex: direct wired" if self.direct_notes else "codex: plugin wired"
            return _proc(
                cmd,
                code=1,
                stdout=json.dumps(
                    {
                        "checks": [
                            {"name": "codex_harness", "status": status, "detail": detail}
                        ]
                    }
                ),
            )
        if cmd == ("cairn", "doctor", "--json"):
            detail = (
                "both direct hooks configured and plugin enabled"
                if self.direct_cairn
                else "Cairn Codex plugin installed and enabled"
            )
            return _proc(
                cmd,
                code=1,
                stdout=json.dumps(
                    {
                        "checks": [
                            {"name": "codex_harness_wired", "status": "warn", "detail": detail}
                        ]
                    }
                ),
            )
        raise AssertionError(f"unexpected command: {cmd}")


def _installed(name: str) -> bool:
    return name in {"codex", "agent-notes", "cairn"}


def test_verify_separates_machine_readiness_from_hook_handoff() -> None:
    report = verify_codex_profile(
        profile=CodexPluginProfile.CORE,
        marketplace="local-proof",
        catalog=_CATALOG,
        runner=ReadyRunner(),
        installed=_installed,
    )
    assert report.ok is True
    assert report.machine_ready is True
    assert report.ready is False
    trust = next(check for check in report.checks if check.name == "hook_trust_handoff")
    assert trust.status is VerifyStatus.ACTION_REQUIRED

    reviewed = verify_codex_profile(
        profile=CodexPluginProfile.CORE,
        marketplace="local-proof",
        catalog=_CATALOG,
        hooks_reviewed=True,
        runner=ReadyRunner(),
        installed=_installed,
    )
    assert reviewed.ready is True
    assert "not persisted" in next(
        check.detail for check in reviewed.checks if check.name == "hook_trust_handoff"
    )


def test_verify_fails_on_direct_and_plugin_duplication() -> None:
    runner = ReadyRunner()
    runner.direct_notes = True
    report = verify_codex_profile(
        profile=CodexPluginProfile.CORE,
        marketplace="local-proof",
        catalog=_CATALOG,
        hooks_reviewed=True,
        runner=runner,
        installed=_installed,
    )
    overlap = next(
        check for check in report.checks if check.name == "direct_install_overlap:agent-notes"
    )
    assert overlap.status is VerifyStatus.FAIL
    assert report.machine_ready is False
    assert report.ready is False


def test_verify_fails_when_auth_or_marketplace_is_unavailable() -> None:
    class BrokenRunner(ReadyRunner):
        def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
            if cmd == ("codex", "login", "status"):
                return _proc(cmd, code=1)
            if cmd == ("codex", "plugin", "marketplace", "list", "--json"):
                return _proc(cmd, stdout=json.dumps({"marketplaces": []}))
            return super().__call__(cmd)

    report = verify_codex_profile(
        profile=CodexPluginProfile.CORE,
        marketplace="local-proof",
        catalog=_CATALOG,
        hooks_reviewed=True,
        runner=BrokenRunner(),
        installed=_installed,
    )
    failures = {check.name for check in report.checks if check.status is VerifyStatus.FAIL}
    assert {"codex_auth", "marketplace_configured"} <= failures
    assert report.ready is False


def test_verify_fails_closed_when_codex_is_missing() -> None:
    report = verify_codex_profile(
        profile=CodexPluginProfile.CORE,
        marketplace="local-proof",
        catalog=_CATALOG,
        installed=lambda _name: False,
    )
    assert report.ok is False
    assert report.checks[0].name == "codex_cli"
