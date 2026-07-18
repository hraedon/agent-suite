"""Live end-to-end proof of the Codex plugin path against the *real* binary.

Sol's review: "non-functional despite passing mocked tests."  These tests close
that gap — they drive the actual ``codex`` CLI (0.144.x) through a local fixture
marketplace in an isolated ``CODEX_HOME``, proving install → idempotent re-install
→ health → uninstall → idempotent re-uninstall against reality, not stubs.

Skipped where ``codex`` is not on PATH (e.g. CI), so the suite stays hermetic.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_suite.codex_catalog import (
    CodexPluginEntry,
    CodexPluginId,
    CodexPluginProfile,
    PluginStepStatus,
    catalog_for_profile,
    install_codex_plugins,
    uninstall_codex_plugins,
)
from agent_suite.codex_health import CodexPluginHealthStatus, check_codex_health

pytestmark = pytest.mark.skipif(
    shutil.which("codex") is None,
    reason="codex CLI not installed — live Codex proof is skipped",
)

FIXTURE_MARKETPLACE = "suite-fixture"
FIXTURE_PLUGIN = "hello-suite"

_WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
_CORE_COMPONENT_PLUGINS = {
    "agent-notes": _WORKSPACE_ROOT / "agent-notes" / "plugins" / "agent-notes",
    "cairn": _WORKSPACE_ROOT / "agent-provenance" / "plugins" / "cairn",
}
_CREDENTIALED_COMPONENT_PLUGINS = {
    **_CORE_COMPONENT_PLUGINS,
    "acb": _WORKSPACE_ROOT / "agent-capability-broker" / "plugins" / "acb",
}

# A single-entry catalog pointing at the fixture plugin.  Reuses an existing
# closed-enum id for reporting; the plugin_name/marketplace drive the CLI.
_FIXTURE_CATALOG: tuple[CodexPluginEntry, ...] = (
    CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_NOTES,
        component_ident="fixture",
        plugin_name=FIXTURE_PLUGIN,
        marketplace=FIXTURE_MARKETPLACE,
        version="0.0.1",
    ),
)


def _write_fixture_marketplace(
    root: Path,
    *,
    marketplace: str = FIXTURE_MARKETPLACE,
    plugin: str = FIXTURE_PLUGIN,
    version: str = "0.0.1",
) -> Path:
    """Create a minimal local marketplace publishing one no-auth plugin."""
    (root / ".agents" / "plugins").mkdir(parents=True)
    (root / "plugins" / plugin / ".codex-plugin").mkdir(parents=True)
    (root / ".agents" / "plugins" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": marketplace,
                "interface": {"displayName": marketplace},
                "plugins": [
                    {
                        "name": plugin,
                        "source": {"source": "local", "path": f"./plugins/{plugin}"},
                        "policy": {"installation": "AVAILABLE", "authentication": "ON_USE"},
                        "category": "Developer Tools",
                    }
                ],
            }
        )
    )
    (root / "plugins" / plugin / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": plugin,
                "version": version,
                "description": "Fixture plugin proving the suite install path live.",
                "license": "MIT",
            }
        )
    )
    return root


def _marketplace_add(path: Path, expected_name: str) -> None:
    """Configure a marketplace via the real CLI (stderr may carry a /tmp warning)."""
    proc = subprocess.run(
        ("codex", "plugin", "marketplace", "add", str(path), "--json"),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["marketplaceName"] == expected_name


def _write_component_marketplace(
    root: Path, marketplace: str, plugins: dict[str, Path]
) -> Path:
    """Expose the real sibling component bundles without vendoring them."""
    plugins_dir = root / "plugins"
    plugins_dir.mkdir(parents=True)
    entries: list[dict[str, object]] = []
    for plugin_name, source in plugins.items():
        (plugins_dir / plugin_name).symlink_to(source, target_is_directory=True)
        entries.append(
            {
                "name": plugin_name,
                "source": {
                    "source": "local",
                    "path": f"./plugins/{plugin_name}",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_USE",
                },
                "category": "Developer Tools",
            }
        )
    catalog_dir = root / ".agents" / "plugins"
    catalog_dir.mkdir(parents=True)
    (catalog_dir / "marketplace.json").write_text(
        json.dumps(
            {
                "name": marketplace,
                "interface": {"displayName": "Agent Suite component proof"},
                "plugins": entries,
            }
        )
    )
    return root


@pytest.fixture()
def codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated CODEX_HOME with the fixture marketplace configured."""
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))
    mkt = _write_fixture_marketplace(tmp_path / "fixture-mkt")
    _marketplace_add(mkt, FIXTURE_MARKETPLACE)
    return home


def test_live_install_health_uninstall_roundtrip(codex_home: Path) -> None:
    # 1. install from the fixture marketplace
    installed = install_codex_plugins(catalog=_FIXTURE_CATALOG)
    assert installed.ok is True, installed.to_dict()
    assert installed.results[0].status is PluginStepStatus.INSTALLED

    # 2. re-install is an idempotent no-op
    again = install_codex_plugins(catalog=_FIXTURE_CATALOG)
    assert again.ok is True
    assert again.results[0].status is PluginStepStatus.ALREADY_INSTALLED

    # 3. health sees it installed & enabled (real `codex plugin list --json`)
    health = check_codex_health(catalog=_FIXTURE_CATALOG)
    assert health.ok is True
    assert health.codex_installed is True
    assert health.plugins[0].status is CodexPluginHealthStatus.INSTALLED_ENABLED

    # 4. uninstall, then idempotent re-uninstall
    removed = uninstall_codex_plugins(catalog=_FIXTURE_CATALOG)
    assert removed.ok is True
    assert removed.results[0].status is PluginStepStatus.REMOVED

    removed_again = uninstall_codex_plugins(catalog=_FIXTURE_CATALOG)
    assert removed_again.ok is True
    assert removed_again.results[0].status is PluginStepStatus.ALREADY_ABSENT

    # 5. health after removal: absent, still ok
    health_after = check_codex_health(catalog=_FIXTURE_CATALOG)
    assert health_after.ok is True
    assert health_after.plugins[0].status is CodexPluginHealthStatus.PLUGIN_ABSENT


@pytest.mark.skipif(
    not all(
        (root / ".codex-plugin" / "plugin.json").is_file()
        for root in _CORE_COMPONENT_PLUGINS.values()
    ),
    reason="sibling agent-notes and Cairn component plugins are not checked out",
)
def test_live_real_core_component_plugins_compose(tmp_path: Path, monkeypatch) -> None:
    """Install the actual notes+Cairn bundles together through the real CLI."""
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    marketplace = "agent-suite-component-proof"
    marketplace_root = _write_component_marketplace(
        tmp_path / "component-marketplace", marketplace, _CORE_COMPONENT_PLUGINS
    )
    _marketplace_add(marketplace_root, marketplace)

    core = catalog_for_profile(CodexPluginProfile.CORE)
    installed = install_codex_plugins(marketplace=marketplace, catalog=core)
    assert installed.ok is True, installed.to_dict()
    assert all(r.status is PluginStepStatus.INSTALLED for r in installed.results)

    health = check_codex_health(
        catalog=tuple(
            CodexPluginEntry(
                plugin_id=entry.plugin_id,
                component_ident=entry.component_ident,
                plugin_name=entry.plugin_name,
                marketplace=marketplace,
                version=entry.version,
            )
            for entry in core
        )
    )
    assert health.ok is True
    assert health.ready is True
    assert all(
        plugin.status is CodexPluginHealthStatus.INSTALLED_ENABLED
        for plugin in health.plugins
    )

    removed = uninstall_codex_plugins(marketplace=marketplace, catalog=core)
    assert removed.ok is True, removed.to_dict()


@pytest.mark.skipif(
    not all(
        (root / ".codex-plugin" / "plugin.json").is_file()
        for root in _CREDENTIALED_COMPONENT_PLUGINS.values()
    ),
    reason="sibling notes, Cairn, and ACB component plugins are not checked out",
)
def test_live_real_credentialed_component_plugins_compose(
    tmp_path: Path, monkeypatch
) -> None:
    """The stronger notes+Cairn+ACB plugin slice also composes as one set."""
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    marketplace = "agent-suite-credentialed-proof"
    marketplace_root = _write_component_marketplace(
        tmp_path / "component-marketplace",
        marketplace,
        _CREDENTIALED_COMPONENT_PLUGINS,
    )
    _marketplace_add(marketplace_root, marketplace)

    credentialed = catalog_for_profile(CodexPluginProfile.CREDENTIALED)
    installed = install_codex_plugins(
        marketplace=marketplace, catalog=credentialed
    )
    assert installed.ok is True, installed.to_dict()

    pinned = tuple(
        CodexPluginEntry(
            plugin_id=entry.plugin_id,
            component_ident=entry.component_ident,
            plugin_name=entry.plugin_name,
            marketplace=marketplace,
            version=entry.version,
        )
        for entry in credentialed
    )
    health = check_codex_health(catalog=pinned)
    assert health.ok is True
    assert health.ready is True

    removed = uninstall_codex_plugins(
        marketplace=marketplace, catalog=credentialed
    )
    assert removed.ok is True, removed.to_dict()


def test_live_unpublished_plugin_is_unsupported(codex_home: Path) -> None:
    """A plugin no configured marketplace publishes fails closed, never green."""
    ghost = (
        CodexPluginEntry(
            plugin_id=CodexPluginId.CAIRN,
            component_ident="fixture",
            plugin_name="does-not-exist",
            marketplace=FIXTURE_MARKETPLACE,
            version="0.0.0",
        ),
    )
    result = install_codex_plugins(catalog=ghost)
    assert result.ok is False
    assert result.results[0].status is PluginStepStatus.UNSUPPORTED


def test_live_same_name_wrong_identity_is_not_false_green(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sol's repro, proven live: a twin plugin installed from another marketplace
    at another version must not satisfy a pin — no false already_installed /
    installed_enabled, and the wrong-version same-marketplace case is a mismatch.
    """
    home = tmp_path / "codex-home"
    home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(home))

    # market-a really publishes and installs `twin` at v9.9.9
    mkt_a = _write_fixture_marketplace(
        tmp_path / "market-a", marketplace="market-a", plugin="twin", version="9.9.9"
    )
    _marketplace_add(mkt_a, "market-a")
    proc = subprocess.run(
        ("codex", "plugin", "add", "twin@market-a", "--json"),
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    def _pin(marketplace: str, version: str) -> tuple[CodexPluginEntry, ...]:
        return (
            CodexPluginEntry(
                plugin_id=CodexPluginId.AGENT_NOTES,
                component_ident="fixture",
                plugin_name="twin",
                marketplace=marketplace,
                version=version,
            ),
        )

    # (a) pin the *same name* from a different marketplace -> not a false green
    other_market = _pin("market-b", "9.9.9")
    install_b = install_codex_plugins(catalog=other_market)
    assert install_b.results[0].status is PluginStepStatus.UNSUPPORTED
    assert install_b.ok is False
    health_b = check_codex_health(catalog=other_market)
    assert health_b.plugins[0].status is CodexPluginHealthStatus.PLUGIN_ABSENT

    # (b) pin the same marketplace but a different version -> version mismatch
    wrong_version = _pin("market-a", "1.0.0")
    install_v = install_codex_plugins(catalog=wrong_version)
    assert install_v.results[0].status is PluginStepStatus.VERSION_MISMATCH
    assert install_v.ok is False
    health_v = check_codex_health(catalog=wrong_version)
    assert health_v.plugins[0].status is CodexPluginHealthStatus.VERSION_MISMATCH
