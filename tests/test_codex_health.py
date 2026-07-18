"""Unit tests for Codex plugin health (the doctor's Codex section).

Health is derived from a single ``codex plugin list --json`` call (the only
stable machine-readable window into plugin state in Codex 0.144.5).  There is no
``codex hooks status`` command — hook trust is an interactive ``/hooks`` step —
so the doctor reports only the three CLI-observable states.  A live proof against
the real binary lives in ``tests/test_codex_live.py``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Callable, Mapping

import pytest

from agent_suite.codex_catalog import CODEX_PLUGIN_CATALOG, CodexPluginEntry, CodexPluginId
from agent_suite.codex_health import (
    CodexHealthReport,
    CodexPluginHealthReport,
    CodexPluginHealthStatus,
    _determine_plugin_status,
    check_codex_health,
    format_codex_health_text,
    is_actionable_status,
)


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class Runner:
    def __init__(
        self,
        outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception],
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        key = cmd[:3]
        out = self._outputs.get(key)
        if out is None:
            return _completed(stdout="", returncode=1, stderr=f"{cmd}: not stubbed")
        if isinstance(out, Exception):
            raise out
        return out


def _installed_all() -> Callable[[str], bool]:
    return lambda _name: True


def _installed_none() -> Callable[[str], bool]:
    return lambda _name: False


_SINGLE_CATALOG: tuple[CodexPluginEntry, ...] = (
    CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_NOTES,
        component_ident="agent-notes",
        plugin_name="agent-notes",
        marketplace="agent-suite",
        version="1.0.0",
    ),
)


def _entry() -> CodexPluginEntry:
    return _SINGLE_CATALOG[0]


# the pinned version per plugin name, so fixtures satisfy the version pin
_PIN_VERSION = {e.plugin_name: e.version for e in CODEX_PLUGIN_CATALOG}


def _inst(
    name: str = "agent-notes",
    *,
    version: str | None = None,
    enabled: bool | None = True,
    marketplace: str = "agent-suite",
) -> dict[str, object]:
    version = version if version is not None else _PIN_VERSION.get(name, "1.0.0")
    p: dict[str, object] = {
        "pluginId": f"{name}@{marketplace}",
        "name": name,
        "marketplaceName": marketplace,
        "version": version,
        "installed": True,
    }
    if enabled is not None:
        p["enabled"] = enabled
    return p


def _list_json(installed: list[dict[str, object]]) -> str:
    return json.dumps({"installed": installed, "available": []})


def _runner_listing(installed: list[dict[str, object]]) -> Runner:
    return Runner({("codex", "plugin", "list"): _completed(stdout=_list_json(installed))})


def _check(
    runner: Runner,
    *,
    installed: Callable[[str], bool] | None = None,
    catalog: tuple[CodexPluginEntry, ...] = _SINGLE_CATALOG,
) -> CodexHealthReport:
    return check_codex_health(
        runner=runner,
        installed=installed or _installed_all(),
        catalog=catalog,
    )


# --- codex not installed -----------------------------------------------------


def test_codex_not_installed_returns_ok_empty() -> None:
    report = _check(Runner({}), installed=_installed_none())
    assert report.ok is True
    assert report.codex_installed is False
    assert report.plugins == []
    assert "not installed" in report.detail


def test_codex_not_installed_does_not_call_runner() -> None:
    runner = Runner({})
    _check(runner, installed=_installed_none())
    assert runner.calls == []


# --- the health check shells exactly one command, never `codex hooks` --------


def test_check_shells_only_plugin_list() -> None:
    runner = _runner_listing([_inst(enabled=True)])
    _check(runner)
    assert runner.calls == [("codex", "plugin", "list", "--json")]
    assert not any(c[:2] == ("codex", "hooks") for c in runner.calls)


# --- the three observable states ---------------------------------------------


def test_plugin_absent() -> None:
    report = _check(_runner_listing([]))
    assert report.ok is True
    assert report.codex_installed is True
    assert len(report.plugins) == 1
    p = report.plugins[0]
    assert p.status is CodexPluginHealthStatus.PLUGIN_ABSENT
    assert "not installed" in p.detail
    assert report.ready is False


def test_empty_stdout_means_all_absent_and_ok() -> None:
    # a real box with no plugins can emit an empty envelope; healthy, all absent
    report = _check(Runner({("codex", "plugin", "list"): _completed(stdout="")}))
    assert report.ok is True
    assert report.plugins[0].status is CodexPluginHealthStatus.PLUGIN_ABSENT


def test_plugin_installed_enabled() -> None:
    report = _check(_runner_listing([_inst(enabled=True, version="1.0.0")]))
    assert report.ok is True
    p = report.plugins[0]
    assert p.status is CodexPluginHealthStatus.INSTALLED_ENABLED
    assert p.enabled is True
    assert p.version == "1.0.0"
    assert "/hooks" in p.detail  # honest note that hook trust is not CLI-observable
    assert report.ready is True


def test_plugin_installed_disabled() -> None:
    report = _check(_runner_listing([_inst(enabled=False)]))
    assert report.ok is True
    p = report.plugins[0]
    assert p.status is CodexPluginHealthStatus.INSTALLED_DISABLED
    assert p.enabled is False
    assert "disabled" in p.detail


def test_missing_enabled_field_fails_closed() -> None:
    report = _check(_runner_listing([_inst(enabled=None)]))
    p = report.plugins[0]
    assert p.status is CodexPluginHealthStatus.INVALID_METADATA
    assert p.enabled is None
    assert report.ready is False


def test_non_boolean_enabled_field_fails_closed() -> None:
    plugin = _inst(enabled=True)
    plugin["enabled"] = "yes"
    report = _check(_runner_listing([plugin]))
    assert report.plugins[0].status is CodexPluginHealthStatus.INVALID_METADATA
    assert report.ready is False


def test_missing_version_field_fails_closed() -> None:
    plugin = _inst(enabled=True)
    del plugin["version"]
    report = _check(_runner_listing([plugin]))
    assert report.plugins[0].status is CodexPluginHealthStatus.INVALID_METADATA
    assert report.ready is False


# --- command failures --------------------------------------------------------


def test_plugin_list_nonzero_exit_is_not_ok() -> None:
    runner = Runner(
        {("codex", "plugin", "list"): _completed(returncode=1, stderr="plugin db down")}
    )
    report = _check(runner)
    assert report.ok is False
    assert report.codex_installed is True
    assert "failed" in report.detail
    assert "plugin db down" in report.detail


def test_plugin_list_nonzero_no_stderr() -> None:
    runner = Runner({("codex", "plugin", "list"): _completed(returncode=2)})
    report = _check(runner)
    assert report.ok is False
    assert "no detail" in report.detail


def test_plugin_list_malformed_json_is_not_ok() -> None:
    runner = Runner({("codex", "plugin", "list"): _completed(stdout="not json {{{")})
    report = _check(runner)
    assert report.ok is False
    assert "non-JSON" in report.detail or "malformed" in report.detail


def test_plugin_list_file_not_found_returns_not_installed() -> None:
    runner = Runner({("codex", "plugin", "list"): FileNotFoundError("codex")})
    report = _check(runner)
    assert report.ok is True
    assert report.codex_installed is False
    assert "not found" in report.detail


def test_plugin_list_timeout_returns_not_ok() -> None:
    runner = Runner(
        {("codex", "plugin", "list"): subprocess.TimeoutExpired(cmd=["codex"], timeout=30)}
    )
    report = _check(runner)
    assert report.ok is False
    assert report.codex_installed is True
    assert "timed out" in report.detail


def test_plugin_list_oserror_returns_not_ok() -> None:
    runner = Runner({("codex", "plugin", "list"): OSError("permission denied")})
    report = _check(runner)
    assert report.ok is False
    assert "could not run" in report.detail
    assert "permission denied" in report.detail


def test_plugin_list_generic_exception_returns_not_ok() -> None:
    runner = Runner({("codex", "plugin", "list"): RuntimeError("unexpected boom")})
    report = _check(runner)
    assert report.ok is False
    assert "raised unexpectedly" in report.detail


# --- full catalog integration ------------------------------------------------


def test_full_catalog_all_enabled() -> None:
    installed = [_inst(name=pid.value, enabled=True) for pid in CodexPluginId]
    runner = _runner_listing(installed)
    report = check_codex_health(runner=runner, installed=_installed_all())
    assert report.ok is True
    assert len(report.plugins) == 4
    assert all(p.status is CodexPluginHealthStatus.INSTALLED_ENABLED for p in report.plugins)
    assert report.ready is True


def test_full_catalog_all_absent() -> None:
    runner = _runner_listing([])
    report = check_codex_health(runner=runner, installed=_installed_all())
    assert report.ok is True
    assert len(report.plugins) == 4
    assert all(p.status is CodexPluginHealthStatus.PLUGIN_ABSENT for p in report.plugins)
    assert report.ready is False


def test_required_subset_can_be_ready_while_optional_plugins_are_absent() -> None:
    installed = [
        _inst(name="agent-notes", enabled=True),
        _inst(name="cairn", enabled=True),
    ]
    report = check_codex_health(
        runner=_runner_listing(installed),
        installed=_installed_all(),
        required_plugin_ids=frozenset({CodexPluginId.AGENT_NOTES, CodexPluginId.CAIRN}),
    )
    assert report.ready is True
    statuses = {p.plugin_id: p.status for p in report.plugins}
    assert statuses[CodexPluginId.ACB] is CodexPluginHealthStatus.PLUGIN_ABSENT
    assert statuses[CodexPluginId.AGENT_WAKE] is CodexPluginHealthStatus.PLUGIN_ABSENT


def test_full_catalog_mixed() -> None:
    installed = [
        _inst(name="agent-notes", enabled=True),
        _inst(name="cairn", enabled=False),
    ]
    runner = _runner_listing(installed)
    report = check_codex_health(runner=runner, installed=_installed_all())
    assert report.ok is True
    statuses = {p.plugin_id: p.status for p in report.plugins}
    assert statuses[CodexPluginId.AGENT_NOTES] is CodexPluginHealthStatus.INSTALLED_ENABLED
    assert statuses[CodexPluginId.CAIRN] is CodexPluginHealthStatus.INSTALLED_DISABLED
    assert statuses[CodexPluginId.ACB] is CodexPluginHealthStatus.PLUGIN_ABSENT
    assert statuses[CodexPluginId.AGENT_WAKE] is CodexPluginHealthStatus.PLUGIN_ABSENT


# --- _determine_plugin_status direct -----------------------------------------


def test_determine_absent() -> None:
    report = _determine_plugin_status(_entry(), [])
    assert report.status is CodexPluginHealthStatus.PLUGIN_ABSENT
    assert report.version is None
    assert report.enabled is None


def test_determine_disabled() -> None:
    report = _determine_plugin_status(_entry(), [_inst(enabled=False)])
    assert report.status is CodexPluginHealthStatus.INSTALLED_DISABLED
    assert report.enabled is False
    assert report.version == "1.0.0"


def test_determine_enabled() -> None:
    report = _determine_plugin_status(_entry(), [_inst(enabled=True, version="1.0.0")])
    assert report.status is CodexPluginHealthStatus.INSTALLED_ENABLED
    assert report.version == "1.0.0"


def test_determine_matches_by_name_not_other_plugins() -> None:
    report = _determine_plugin_status(_entry(), [_inst(name="cairn", enabled=True)])
    assert report.status is CodexPluginHealthStatus.PLUGIN_ABSENT


def test_determine_same_name_other_marketplace_is_absent_not_false_green() -> None:
    # Sol's repro: agent-notes@other-market v9.9.9 while pin is agent-notes@agent-suite
    report = _determine_plugin_status(
        _entry(), [_inst(marketplace="other-market", version="9.9.9", enabled=True)]
    )
    assert report.status is CodexPluginHealthStatus.PLUGIN_ABSENT
    assert report.status is not CodexPluginHealthStatus.INSTALLED_ENABLED
    assert "different marketplace" in report.detail


def test_determine_pinned_marketplace_wrong_version_is_mismatch() -> None:
    report = _determine_plugin_status(_entry(), [_inst(version="9.9.9", enabled=True)])
    assert report.status is CodexPluginHealthStatus.VERSION_MISMATCH
    assert report.version == "9.9.9"
    assert "9.9.9" in report.detail and "1.0.0" in report.detail


def test_determine_disabled_takes_precedence_over_version() -> None:
    report = _determine_plugin_status(_entry(), [_inst(version="9.9.9", enabled=False)])
    assert report.status is CodexPluginHealthStatus.INSTALLED_DISABLED


# --- is_actionable_status (exhaustive) --------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CodexPluginHealthStatus.PLUGIN_ABSENT, False),
        (CodexPluginHealthStatus.INSTALLED_DISABLED, True),
        (CodexPluginHealthStatus.INSTALLED_ENABLED, False),
        (CodexPluginHealthStatus.VERSION_MISMATCH, True),
        (CodexPluginHealthStatus.INVALID_METADATA, True),
    ],
)
def test_is_actionable_status(status: CodexPluginHealthStatus, expected: bool) -> None:
    assert is_actionable_status(status) is expected


def test_is_actionable_status_covers_all_enum_values() -> None:
    for status in CodexPluginHealthStatus:
        assert isinstance(is_actionable_status(status), bool)


# --- format_codex_health_text ------------------------------------------------


def test_format_text_codex_not_installed() -> None:
    report = CodexHealthReport(
        ok=True,
        codex_installed=False,
        detail="codex CLI not installed — Codex health not checked",
    )
    text = format_codex_health_text(report)
    assert "codex health:" in text
    assert "not installed" in text


def test_format_text_installed_with_plugins() -> None:
    report = CodexHealthReport(
        ok=True,
        codex_installed=True,
        plugins=[
            CodexPluginHealthReport(
                plugin_id=CodexPluginId.AGENT_NOTES,
                status=CodexPluginHealthStatus.INSTALLED_ENABLED,
                detail="agent-notes installed and enabled",
                version="1.0.0",
                enabled=True,
            ),
        ],
    )
    text = format_codex_health_text(report)
    assert "codex health:" in text
    assert "installed" in text
    assert "agent-notes" in text
    assert "installed_enabled" in text


def test_format_text_with_error() -> None:
    report = CodexHealthReport(
        ok=False,
        codex_installed=True,
        detail="codex plugin list failed: db down",
    )
    text = format_codex_health_text(report)
    assert "error" in text
    assert "db down" in text


# --- to_dict serialization ---------------------------------------------------


def test_plugin_report_to_dict_minimal() -> None:
    report = CodexPluginHealthReport(
        plugin_id=CodexPluginId.AGENT_NOTES,
        status=CodexPluginHealthStatus.PLUGIN_ABSENT,
        detail="not installed",
    )
    assert report.to_dict() == {
        "plugin_id": "agent-notes",
        "status": "plugin_absent",
        "detail": "not installed",
    }


def test_plugin_report_to_dict_omits_none_fields() -> None:
    report = CodexPluginHealthReport(
        plugin_id=CodexPluginId.AGENT_NOTES,
        status=CodexPluginHealthStatus.INSTALLED_ENABLED,
        detail="enabled",
        version="1.0.0",
        enabled=True,
    )
    d = report.to_dict()
    assert d["version"] == "1.0.0"
    assert d["enabled"] is True


def test_health_report_to_dict_minimal() -> None:
    report = CodexHealthReport(ok=True, codex_installed=False)
    assert report.to_dict() == {
        "ok": True,
        "ready": False,
        "codex_installed": False,
        "plugins": [],
    }


def test_health_report_to_dict_omits_none_version_and_empty_detail() -> None:
    report = CodexHealthReport(ok=True, codex_installed=True)
    d = report.to_dict()
    assert "codex_version" not in d
    assert "detail" not in d
