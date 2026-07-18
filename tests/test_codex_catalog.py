"""Unit tests for the Codex plugin catalog and add/remove composition.

All tests use stubbed runners and installed checks modelling the *real* Codex
CLI 0.144.5 surface (``codex plugin add/remove/list``, the
``{"installed": [...], "available": [...]}`` list envelope, ``name@marketplace``
selectors).  A live end-to-end proof against the real binary lives in
``tests/test_codex_live.py``.
"""

from __future__ import annotations

import json
import subprocess
from typing import Mapping

import pytest

from agent_suite.codex_catalog import (
    CODEX_PLUGIN_CATALOG,
    SUITE_MARKETPLACE,
    CodexPluginEntry,
    CodexPluginId,
    CodexPluginInstallResult,
    CodexPluginProfile,
    PluginStepResult,
    PluginStepStatus,
    _plugin_names,
    catalog_by_plugin_id,
    catalog_for_profile,
    format_install_text,
    index_by_identity,
    install_codex_plugins,
    parse_plugin_list,
    plugin_add_argv,
    plugin_list_argv,
    plugin_remove_argv,
    uninstall_codex_plugins,
    with_marketplace,
)

MKT = SUITE_MARKETPLACE
# the pinned version per plugin name, so test fixtures satisfy the version pin
_PIN_VERSION = {e.plugin_name: e.version for e in CODEX_PLUGIN_CATALOG}


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    """Returns canned output keyed by command prefix."""

    def __init__(
        self,
        outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str] | Exception],
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                return out
        return _completed(stdout='{"ok": true}', returncode=0)


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _list_json(installed: list[dict], available: list[dict]) -> str:
    return json.dumps({"installed": installed, "available": available})


def _inst(
    name: str,
    *,
    enabled: bool = True,
    version: str | None = None,
    marketplace: str = MKT,
) -> dict:
    version = version if version is not None else _PIN_VERSION.get(name, "0.1.0")
    return {
        "pluginId": f"{name}@{marketplace}",
        "name": name,
        "marketplaceName": marketplace,
        "version": version,
        "installed": True,
        "enabled": enabled,
    }


def _avail(name: str, marketplace: str = MKT, *, version: str | None = None) -> dict:
    version = version if version is not None else _PIN_VERSION.get(name, "0.1.0")
    return {
        "pluginId": f"{name}@{marketplace}",
        "name": name,
        "marketplaceName": marketplace,
        "version": version,
        "installed": False,
        "enabled": False,
    }


_CATALOG_IDS = (
    CodexPluginId.AGENT_NOTES,
    CodexPluginId.CAIRN,
    CodexPluginId.ACB,
    CodexPluginId.AGENT_WAKE,
)
_CATALOG_NAMES = ("agent-notes", "cairn", "acb", "agent-wake")

# every pinned plugin is publishable from the suite marketplace
_ALL_AVAILABLE = [_avail(n) for n in _CATALOG_NAMES]
_ALL_INSTALLED = [_inst(n) for n in _CATALOG_NAMES]

_OK_ADD = _completed(stdout=json.dumps({"pluginId": "x", "name": "x"}))
_OK_REMOVE = _completed(stdout=json.dumps({"pluginId": "x", "name": "x"}))
_FAIL_ADD = _completed(returncode=1, stderr="plugin not found in marketplace")
_FAIL_REMOVE = _completed(returncode=1, stderr="plugin not removable")


def _list_stub(installed: list[dict], available: list[dict]) -> StubRunner:
    return StubRunner(
        {
            ("codex", "plugin", "list"): _completed(stdout=_list_json(installed, available)),
            ("codex", "plugin", "add"): _OK_ADD,
            ("codex", "plugin", "remove"): _OK_REMOVE,
        }
    )


def _status_by_plugin(result: CodexPluginInstallResult) -> dict[CodexPluginId, PluginStepStatus]:
    return {r.plugin_id: r.status for r in result.results}


def _detail_by_plugin(result: CodexPluginInstallResult) -> dict[CodexPluginId, str]:
    return {r.plugin_id: r.detail for r in result.results}


# --- catalog metadata --------------------------------------------------------


def test_catalog_has_four_plugins() -> None:
    assert len(CODEX_PLUGIN_CATALOG) == 4


def test_catalog_profiles_are_progressive_and_wake_is_full_only() -> None:
    core = catalog_for_profile(CodexPluginProfile.CORE)
    credentialed = catalog_for_profile(CodexPluginProfile.CREDENTIALED)
    full = catalog_for_profile(CodexPluginProfile.FULL)
    assert {entry.plugin_id for entry in core} == {
        CodexPluginId.AGENT_NOTES,
        CodexPluginId.CAIRN,
    }
    assert {entry.plugin_id for entry in credentialed} == {
        CodexPluginId.AGENT_NOTES,
        CodexPluginId.CAIRN,
        CodexPluginId.ACB,
    }
    assert tuple(full) == CODEX_PLUGIN_CATALOG


def test_catalog_plugin_ids_are_the_pinned_set() -> None:
    ids = tuple(entry.plugin_id for entry in CODEX_PLUGIN_CATALOG)
    assert ids == _CATALOG_IDS


def test_catalog_plugin_ids_are_unique() -> None:
    ids = [entry.plugin_id for entry in CODEX_PLUGIN_CATALOG]
    assert len(set(ids)) == len(ids)


def test_catalog_entries_have_expected_metadata() -> None:
    expected = {
        CodexPluginId.AGENT_NOTES: ("agent-notes", "agent-notes", "1.0.0"),
        CodexPluginId.CAIRN: ("agent-provenance", "cairn", "0.1.0"),
        CodexPluginId.ACB: ("agent-capability-broker", "acb", "0.1.0"),
        CodexPluginId.AGENT_WAKE: ("agent-wake", "agent-wake", "0.1.0"),
    }
    for entry in CODEX_PLUGIN_CATALOG:
        ident, name, version = expected[entry.plugin_id]
        assert entry.component_ident == ident
        assert entry.plugin_name == name
        assert entry.version == version


def test_catalog_entries_use_suite_marketplace() -> None:
    for entry in CODEX_PLUGIN_CATALOG:
        assert entry.marketplace == SUITE_MARKETPLACE


def test_selector_is_name_at_marketplace() -> None:
    entry = catalog_by_plugin_id(CodexPluginId.AGENT_NOTES)
    assert entry.selector == f"agent-notes@{SUITE_MARKETPLACE}"


def test_catalog_entry_is_frozen_dataclass() -> None:
    entry = CODEX_PLUGIN_CATALOG[0]
    with pytest.raises((AttributeError, Exception)):
        setattr(entry, "plugin_name", "mutated")


@pytest.mark.parametrize("plugin_id", list(CodexPluginId))
def test_catalog_by_plugin_id_known(plugin_id: CodexPluginId) -> None:
    entry = catalog_by_plugin_id(plugin_id)
    assert entry.plugin_id is plugin_id


def test_catalog_by_plugin_id_missing_from_catalog_raises() -> None:
    catalog_without_wake = tuple(
        e for e in CODEX_PLUGIN_CATALOG if e.plugin_id is not CodexPluginId.AGENT_WAKE
    )
    with pytest.raises(KeyError, match="plugin not in catalog"):
        catalog_by_plugin_id(CodexPluginId.AGENT_WAKE, catalog=catalog_without_wake)


def test_catalog_by_plugin_id_empty_catalog_raises() -> None:
    with pytest.raises(KeyError):
        catalog_by_plugin_id(CodexPluginId.AGENT_NOTES, catalog=())


def test_with_marketplace_overrides_every_entry() -> None:
    overridden = with_marketplace(CODEX_PLUGIN_CATALOG, "suite-fixture")
    assert all(e.marketplace == "suite-fixture" for e in overridden)
    # names, ids, versions unchanged
    assert tuple(e.plugin_name for e in overridden) == _CATALOG_NAMES
    assert overridden[0].selector == "agent-notes@suite-fixture"


# --- argv builders -----------------------------------------------------------


def test_plugin_add_argv_with_json() -> None:
    assert plugin_add_argv("agent-notes@agent-suite") == (
        "codex",
        "plugin",
        "add",
        "agent-notes@agent-suite",
        "--json",
    )


def test_plugin_add_argv_without_json() -> None:
    assert plugin_add_argv("cairn@agent-suite", json_output=False) == (
        "codex",
        "plugin",
        "add",
        "cairn@agent-suite",
    )


def test_plugin_remove_argv_with_json() -> None:
    assert plugin_remove_argv("acb@agent-suite") == (
        "codex",
        "plugin",
        "remove",
        "acb@agent-suite",
        "--json",
    )


def test_plugin_list_argv_variants() -> None:
    assert plugin_list_argv() == ("codex", "plugin", "list", "--json")
    assert plugin_list_argv(available=True) == (
        "codex",
        "plugin",
        "list",
        "--available",
        "--json",
    )
    assert plugin_list_argv(json_output=False) == ("codex", "plugin", "list")


def test_argv_uses_add_remove_not_install_uninstall() -> None:
    # regression: the CLI verb is add/remove, never install/uninstall
    assert plugin_add_argv("x@y")[2] == "add"
    assert plugin_remove_argv("x@y")[2] == "remove"


# --- parse_plugin_list -------------------------------------------------------


def test_parse_plugin_list_real_envelope() -> None:
    stdout = _list_json([_inst("agent-notes")], [_avail("cairn")])
    parsed = parse_plugin_list(stdout)
    assert parsed is not None
    installed, available = parsed
    assert _plugin_names(installed) == {"agent-notes"}
    assert set(index_by_identity(available)) == {("cairn", MKT)}


def test_parse_plugin_list_empty_envelope() -> None:
    parsed = parse_plugin_list(json.dumps({"installed": [], "available": []}))
    assert parsed == ([], [])


def test_parse_plugin_list_empty_string_is_no_plugins() -> None:
    assert parse_plugin_list("") == ([], [])
    assert parse_plugin_list("   \n ") == ([], [])


def test_parse_plugin_list_malformed_is_none() -> None:
    assert parse_plugin_list("not json") is None
    assert parse_plugin_list('{"installed": [') is None


def test_parse_plugin_list_non_object_is_none() -> None:
    assert parse_plugin_list(json.dumps([1, 2, 3])) is None
    assert parse_plugin_list(json.dumps(42)) is None


def test_parse_plugin_list_missing_keys_defaults_empty() -> None:
    assert parse_plugin_list(json.dumps({})) == ([], [])
    assert parse_plugin_list(json.dumps({"installed": [_inst("acb")]})) == (
        [_inst("acb")],
        [],
    )


def test_parse_plugin_list_filters_non_dict_entries() -> None:
    stdout = json.dumps({"installed": [_inst("acb"), "x", 3], "available": [None]})
    parsed = parse_plugin_list(stdout)
    assert parsed is not None
    installed, available = parsed
    assert len(installed) == 1
    assert available == []


def test_plugin_names_ignores_missing_name() -> None:
    assert _plugin_names([{"name": "a"}, {"noname": True}, {"name": 3}]) == {"a"}


def test_index_by_identity_requires_both_fields() -> None:
    entries = [
        {"name": "a", "marketplaceName": "m"},
        {"name": "b"},
        {"marketplaceName": "m"},
    ]
    assert set(index_by_identity(entries)) == {("a", "m")}


# --- install: dry-run --------------------------------------------------------


def test_install_dry_run_prints_plan_no_commands() -> None:
    runner = StubRunner({})
    result = install_codex_plugins(dry_run=True, runner=runner, installed=_installed_all)
    assert result.ok is True
    assert result.dry_run is True
    assert result.action == "install"
    assert len(runner.calls) == 0
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.PENDING
    for r in result.results:
        assert "would run" in r.detail
        assert "codex plugin add" in r.detail
        assert "@" in r.detail  # marketplace selector, not a dir path


def test_install_dry_run_does_not_check_codex_installed() -> None:
    runner = StubRunner({})
    result = install_codex_plugins(dry_run=True, runner=runner, installed=_installed_none)
    assert result.ok is True
    assert len(runner.calls) == 0


# --- install: full success ---------------------------------------------------


def test_install_full_success_when_all_available() -> None:
    runner = _list_stub(installed=[], available=_ALL_AVAILABLE)
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.INSTALLED
    add_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")]
    assert len(add_cmds) == 4
    for cmd in add_cmds:
        assert cmd[-1] == "--json"
        assert cmd[3].endswith(f"@{MKT}")  # name@marketplace selector


def test_install_emits_single_list_check() -> None:
    runner = _list_stub(installed=[], available=_ALL_AVAILABLE)
    install_codex_plugins(runner=runner, installed=_installed_all)
    list_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "list")]
    assert len(list_cmds) == 1
    assert "--available" in list_cmds[0]


def test_install_add_uses_marketplace_selector_not_path() -> None:
    runner = _list_stub(installed=[], available=_ALL_AVAILABLE)
    install_codex_plugins(runner=runner, installed=_installed_all)
    selectors = {c[3] for c in runner.calls if c[:3] == ("codex", "plugin", "add")}
    assert selectors == {f"{n}@{MKT}" for n in _CATALOG_NAMES}


# --- install: idempotency ----------------------------------------------------


def test_install_already_installed_is_noop() -> None:
    runner = _list_stub(installed=_ALL_INSTALLED, available=[])
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.ALREADY_INSTALLED
    add_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")]
    assert add_cmds == []


def test_install_partial_already_installed() -> None:
    runner = _list_stub(
        installed=[_inst("agent-notes")],
        available=[_avail("cairn"), _avail("acb"), _avail("agent-wake")],
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    statuses = _status_by_plugin(result)
    assert statuses[CodexPluginId.AGENT_NOTES] is PluginStepStatus.ALREADY_INSTALLED
    for pid in (CodexPluginId.CAIRN, CodexPluginId.ACB, CodexPluginId.AGENT_WAKE):
        assert statuses[pid] is PluginStepStatus.INSTALLED
    add_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")]
    assert len(add_cmds) == 3


# --- install: fail-closed on unresolved marketplace (point 5) ----------------


def test_install_unpublished_plugin_is_unsupported_not_success() -> None:
    # no marketplace publishes any pinned plugin: neither installed nor available
    runner = _list_stub(installed=[], available=[])
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False  # fail-closed — never green when nothing is wired
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.UNSUPPORTED
    details = _detail_by_plugin(result)
    for pid in _CATALOG_IDS:
        assert "no configured marketplace" in details[pid]
    add_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")]
    assert add_cmds == []


def test_install_mixed_available_and_unsupported_is_not_ok() -> None:
    runner = _list_stub(
        installed=[],
        available=[_avail("agent-notes"), _avail("cairn")],  # acb, wake unpublished
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    statuses = _status_by_plugin(result)
    assert statuses[CodexPluginId.AGENT_NOTES] is PluginStepStatus.INSTALLED
    assert statuses[CodexPluginId.CAIRN] is PluginStepStatus.INSTALLED
    assert statuses[CodexPluginId.ACB] is PluginStepStatus.UNSUPPORTED
    assert statuses[CodexPluginId.AGENT_WAKE] is PluginStepStatus.UNSUPPORTED


def test_install_available_only_in_other_marketplace_is_unsupported() -> None:
    # agent-notes is published, but only by a marketplace other than the pin
    runner = _list_stub(installed=[], available=[_avail("agent-notes", "someone-else")])
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert _status_by_plugin(result)[CodexPluginId.AGENT_NOTES] is PluginStepStatus.UNSUPPORTED


def test_install_same_name_other_marketplace_not_false_green() -> None:
    # Sol's repro: agent-notes@other-market v9.9.9 is installed while the catalog
    # pins agent-notes@agent-suite v1.0.0.  This must NOT report already_installed.
    runner = _list_stub(
        installed=[_inst("agent-notes", marketplace="other-market", version="9.9.9")],
        available=[],
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    status = _status_by_plugin(result)[CodexPluginId.AGENT_NOTES]
    assert status is PluginStepStatus.UNSUPPORTED
    assert status is not PluginStepStatus.ALREADY_INSTALLED
    assert result.ok is False
    assert "different marketplace" in _detail_by_plugin(result)[CodexPluginId.AGENT_NOTES]
    # never shelled an add for the wrong-marketplace variant
    assert [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")] == []


def test_install_pinned_marketplace_wrong_version_is_mismatch() -> None:
    # right marketplace, wrong version -> version_mismatch, not a false green
    runner = _list_stub(
        installed=[_inst("agent-notes", version="9.9.9")],  # pin is 1.0.0
        available=[],
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    status = _status_by_plugin(result)[CodexPluginId.AGENT_NOTES]
    assert status is PluginStepStatus.VERSION_MISMATCH
    assert result.ok is False
    detail = _detail_by_plugin(result)[CodexPluginId.AGENT_NOTES]
    assert "v9.9.9" in detail and "1.0.0" in detail


def test_install_available_wrong_version_is_mismatch_no_add() -> None:
    # marketplace publishes the pinned selector but at the wrong version
    runner = _list_stub(
        installed=[],
        available=[_avail("agent-notes", version="9.9.9")],  # pin is 1.0.0
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert _status_by_plugin(result)[CodexPluginId.AGENT_NOTES] is PluginStepStatus.VERSION_MISMATCH
    assert result.ok is False
    assert [c for c in runner.calls if c[:3] == ("codex", "plugin", "add")] == []


# --- install: failures -------------------------------------------------------


def test_install_codex_not_installed_all_failed() -> None:
    runner = StubRunner({})
    result = install_codex_plugins(runner=runner, installed=_installed_none)
    assert result.ok is False
    assert len(runner.calls) == 0
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.FAILED
        assert "codex CLI not installed" in _detail_by_plugin(result)[pid]


def test_install_add_command_failure_marks_failed() -> None:
    runner = StubRunner(
        {
            ("codex", "plugin", "list"): _completed(stdout=_list_json([], _ALL_AVAILABLE)),
            ("codex", "plugin", "add"): _FAIL_ADD,
        }
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.FAILED
        assert "exited 1" in _detail_by_plugin(result)[pid]
        assert "plugin not found in marketplace" in _detail_by_plugin(result)[pid]


def test_install_add_raises_marks_failed() -> None:
    runner = StubRunner(
        {
            ("codex", "plugin", "list"): _completed(stdout=_list_json([], _ALL_AVAILABLE)),
            ("codex", "plugin", "add"): OSError("spawn failed"),
        }
    )
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    for r in result.results:
        assert r.status is PluginStepStatus.FAILED
        assert "add failed" in r.detail


def test_install_list_unavailable_fails_closed_as_unknown() -> None:
    # A broken state probe cannot prove either absence or marketplace support.
    runner = StubRunner({("codex", "plugin", "list"): _completed(returncode=2, stderr="boom")})
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.FAILED
        assert "exited 2" in _detail_by_plugin(result)[pid]


def test_uninstall_list_unavailable_does_not_claim_already_absent() -> None:
    runner = StubRunner({("codex", "plugin", "list"): _completed(returncode=2, stderr="boom")})
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    assert all(r.status is PluginStepStatus.FAILED for r in result.results)
    assert not any(r.status is PluginStepStatus.ALREADY_ABSENT for r in result.results)


# --- install: marketplace override ------------------------------------------


def test_install_marketplace_override_changes_selector() -> None:
    fixture_available = [_avail(n, "suite-fixture") for n in _CATALOG_NAMES]
    runner = _list_stub(installed=[], available=fixture_available)
    result = install_codex_plugins(
        marketplace="suite-fixture", runner=runner, installed=_installed_all
    )
    assert result.ok is True
    selectors = {c[3] for c in runner.calls if c[:3] == ("codex", "plugin", "add")}
    assert selectors == {f"{n}@suite-fixture" for n in _CATALOG_NAMES}


# --- uninstall ---------------------------------------------------------------


def test_uninstall_dry_run_prints_plan() -> None:
    runner = StubRunner({})
    result = uninstall_codex_plugins(dry_run=True, runner=runner, installed=_installed_all)
    assert result.ok is True
    assert result.dry_run is True
    assert result.action == "uninstall"
    assert len(runner.calls) == 0
    for r in result.results:
        assert "codex plugin remove" in r.detail


def test_uninstall_full_success() -> None:
    runner = _list_stub(installed=_ALL_INSTALLED, available=[])
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.REMOVED
    remove_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "remove")]
    assert len(remove_cmds) == 4
    selectors = {c[3] for c in remove_cmds}
    assert selectors == {f"{n}@{MKT}" for n in _CATALOG_NAMES}


def test_uninstall_already_absent_is_noop() -> None:
    runner = _list_stub(installed=[], available=[])
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.ALREADY_ABSENT
    remove_cmds = [c for c in runner.calls if c[:3] == ("codex", "plugin", "remove")]
    assert remove_cmds == []


def test_uninstall_partial_already_absent() -> None:
    runner = _list_stub(installed=[_inst("agent-notes")], available=[])
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is True
    statuses = _status_by_plugin(result)
    assert statuses[CodexPluginId.AGENT_NOTES] is PluginStepStatus.REMOVED
    for pid in (CodexPluginId.CAIRN, CodexPluginId.ACB, CodexPluginId.AGENT_WAKE):
        assert statuses[pid] is PluginStepStatus.ALREADY_ABSENT


def test_uninstall_leaves_other_marketplace_variant_alone() -> None:
    # only a same-name plugin from a different marketplace is installed; the
    # pinned uninstall must not touch it
    runner = _list_stub(
        installed=[_inst("agent-notes", marketplace="other-market", version="9.9.9")],
        available=[],
    )
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert _status_by_plugin(result)[CodexPluginId.AGENT_NOTES] is PluginStepStatus.ALREADY_ABSENT
    assert [c for c in runner.calls if c[:3] == ("codex", "plugin", "remove")] == []


def test_uninstall_command_failure_marks_failed() -> None:
    runner = StubRunner(
        {
            ("codex", "plugin", "list"): _completed(stdout=_list_json(_ALL_INSTALLED, [])),
            ("codex", "plugin", "remove"): _FAIL_REMOVE,
        }
    )
    result = uninstall_codex_plugins(runner=runner, installed=_installed_all)
    assert result.ok is False
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.FAILED
        assert "plugin not removable" in _detail_by_plugin(result)[pid]


def test_uninstall_codex_not_installed_all_failed() -> None:
    runner = StubRunner({})
    result = uninstall_codex_plugins(runner=runner, installed=_installed_none)
    assert result.ok is False
    assert len(runner.calls) == 0
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(result)[pid] is PluginStepStatus.FAILED


# --- roundtrip + serialization ----------------------------------------------


def test_install_then_uninstall_roundtrip() -> None:
    install_runner = _list_stub(installed=[], available=_ALL_AVAILABLE)
    install_result = install_codex_plugins(runner=install_runner, installed=_installed_all)
    assert install_result.ok is True

    uninstall_runner = _list_stub(installed=_ALL_INSTALLED, available=[])
    uninstall_result = uninstall_codex_plugins(runner=uninstall_runner, installed=_installed_all)
    assert uninstall_result.ok is True
    for pid in _CATALOG_IDS:
        assert _status_by_plugin(uninstall_result)[pid] is PluginStepStatus.REMOVED


def test_plugin_step_result_to_dict() -> None:
    r = PluginStepResult(CodexPluginId.AGENT_NOTES, PluginStepStatus.INSTALLED, "done")
    assert r.to_dict() == {
        "plugin_id": "agent-notes",
        "status": "installed",
        "detail": "done",
    }


def test_install_result_to_dict_roundtrip() -> None:
    runner = _list_stub(installed=[], available=_ALL_AVAILABLE)
    result = install_codex_plugins(runner=runner, installed=_installed_all)
    d = result.to_dict()
    assert d["ok"] is True
    assert d["action"] == "install"
    assert d["dry_run"] is False
    assert isinstance(d["results"], list)
    assert len(d["results"]) == 4
    for entry in d["results"]:
        assert set(entry.keys()) == {"plugin_id", "status", "detail"}


def test_install_result_default_empty_results() -> None:
    result = CodexPluginInstallResult(ok=True, dry_run=False, action="install")
    assert result.results == []


# --- formatting --------------------------------------------------------------


def test_format_install_text_dry_run() -> None:
    result = CodexPluginInstallResult(
        ok=True,
        dry_run=True,
        action="install",
        results=[
            PluginStepResult(
                CodexPluginId.AGENT_NOTES,
                PluginStepStatus.PENDING,
                "would run: codex plugin add agent-notes@agent-suite --json",
            ),
        ],
    )
    text = format_install_text(result)
    assert "codex-plugins install --dry-run" in text
    assert "(plan, no actions taken)" in text
    assert "agent-notes" in text
    assert "OK" in text


def test_format_install_text_not_ok_shows_unsupported() -> None:
    result = CodexPluginInstallResult(
        ok=False,
        dry_run=False,
        action="install",
        results=[
            PluginStepResult(CodexPluginId.CAIRN, PluginStepStatus.UNSUPPORTED, "no marketplace"),
        ],
    )
    text = format_install_text(result)
    assert "NOT OK" in text
    assert "unsupported" in text
    assert "cairn" in text


def test_format_install_text_uninstall_action() -> None:
    result = CodexPluginInstallResult(
        ok=True,
        dry_run=False,
        action="uninstall",
        results=[
            PluginStepResult(CodexPluginId.AGENT_WAKE, PluginStepStatus.REMOVED, "removed"),
        ],
    )
    text = format_install_text(result)
    assert "codex-plugins uninstall" in text
    assert "removed" in text
    assert "OK" in text


def test_entry_construction_and_selector() -> None:
    e = CodexPluginEntry(
        plugin_id=CodexPluginId.ACB,
        component_ident="agent-capability-broker",
        plugin_name="acb",
        marketplace="custom-mkt",
        version="9.9.9",
    )
    assert e.selector == "acb@custom-mkt"
