from __future__ import annotations

import json
from pathlib import Path

from agent_suite.codex_catalog import CodexPluginEntry, CodexPluginId, CodexPluginProfile
from agent_suite.codex_marketplace import build_local_marketplace


def _entry(component: str, name: str, version: str = "1.0.0") -> CodexPluginEntry:
    return CodexPluginEntry(
        plugin_id=CodexPluginId.AGENT_NOTES,
        component_ident=component,
        plugin_name=name,
        marketplace="local-proof",
        version=version,
    )


def _plugin(root: Path, relative: tuple[str, ...], name: str, version: str = "1.0.0") -> Path:
    plugin = root.joinpath(*relative)
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": name, "version": version}))
    return plugin


def test_builds_owned_marketplace_with_links_to_component_assets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = _plugin(workspace, ("agent-notes", "plugins", "agent-notes"), "agent-notes")
    output = tmp_path / "marketplace"

    result = build_local_marketplace(
        output=output,
        workspace_root=workspace,
        marketplace="local-proof",
        profile=CodexPluginProfile.CORE,
        catalog=(_entry("agent-notes", "agent-notes"),),
    )

    assert result.ok is True
    link = output / "plugins" / "agent-notes"
    assert link.is_symlink()
    assert link.resolve() == source.resolve()
    payload = json.loads((output / ".agents/plugins/marketplace.json").read_text())
    assert payload["name"] == "local-proof"
    assert payload["plugins"][0]["source"] == {
        "source": "local",
        "path": "./plugins/agent-notes",
    }
    assert json.loads((output / ".agent-suite-marketplace.json").read_text())["owner"] == "agent-suite"


def test_build_is_idempotent_and_dry_run_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _plugin(workspace, ("agent-notes", "plugins", "agent-notes"), "agent-notes")
    output = tmp_path / "marketplace"
    kwargs = {
        "output": output,
        "workspace_root": workspace,
        "marketplace": "local-proof",
        "profile": CodexPluginProfile.CORE,
        "catalog": (_entry("agent-notes", "agent-notes"),),
    }
    assert build_local_marketplace(**kwargs).ok is True
    before = (output / ".agents/plugins/marketplace.json").read_bytes()
    assert build_local_marketplace(**kwargs).ok is True
    assert (output / ".agents/plugins/marketplace.json").read_bytes() == before

    planned = tmp_path / "planned"
    dry = build_local_marketplace(**{**kwargs, "output": planned}, dry_run=True)
    assert dry.ok is True
    assert not planned.exists()


def test_fails_closed_for_foreign_output_and_pin_mismatch(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _plugin(
        workspace,
        ("agent-notes", "plugins", "agent-notes"),
        "agent-notes",
        version="2.0.0",
    )
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("owned elsewhere")

    foreign_result = build_local_marketplace(
        output=foreign,
        workspace_root=workspace,
        marketplace="local-proof",
        profile=CodexPluginProfile.CORE,
        catalog=(_entry("agent-notes", "agent-notes", version="2.0.0"),),
    )
    assert foreign_result.ok is False
    assert (foreign / "keep.txt").read_text() == "owned elsewhere"

    mismatch = build_local_marketplace(
        output=tmp_path / "mismatch",
        workspace_root=workspace,
        marketplace="local-proof",
        profile=CodexPluginProfile.CORE,
        catalog=(_entry("agent-notes", "agent-notes", version="1.0.0"),),
    )
    assert mismatch.ok is False
    assert mismatch.steps[0].status == "invalid"
    assert not (tmp_path / "mismatch").exists()


def test_full_profile_fails_honestly_when_wake_bundle_is_absent(tmp_path: Path) -> None:
    result = build_local_marketplace(
        output=tmp_path / "marketplace",
        workspace_root=tmp_path / "workspace",
        marketplace="local-proof",
        profile=CodexPluginProfile.FULL,
        catalog=(
            CodexPluginEntry(
                plugin_id=CodexPluginId.AGENT_WAKE,
                component_ident="agent-wake",
                plugin_name="agent-wake",
                marketplace="local-proof",
                version="0.1.0",
            ),
        ),
    )
    assert result.ok is False
    assert result.steps[0].status == "invalid"
    assert "missing" in result.steps[0].detail
