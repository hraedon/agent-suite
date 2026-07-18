"""Build a local Codex marketplace from component-owned plugin bundles.

The generated marketplace is a development and release-preparation artifact.
It contains symlinks to sibling component checkouts; agent-suite owns only the
composition metadata and never copies or republishes component assets.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from agent_suite.codex_catalog import CodexPluginEntry, CodexPluginProfile


_OWNER_FILE = ".agent-suite-marketplace.json"
_MARKETPLACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")

_COMPONENT_PLUGIN_PATHS: dict[str, tuple[str, ...]] = {
    # A repository-root plugin path is not safe for local composition: Codex
    # may copy unrelated checkout state such as .venv. Every source here is a
    # dedicated, component-owned distribution bundle.
    "agent-notes": ("agent-notes", "plugins", "agent-notes"),
    "agent-provenance": ("agent-provenance", "plugins", "cairn"),
    "agent-capability-broker": (
        "agent-capability-broker",
        "plugins",
        "acb",
    ),
    "agent-wake": ("agent-wake", "plugins", "agent-wake"),
}


@dataclass(frozen=True)
class MarketplaceBuildStep:
    """One component source selected for the generated marketplace."""

    plugin: str
    source: str
    status: str
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "plugin": self.plugin,
            "source": self.source,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class MarketplaceBuildResult:
    """Result of validating and optionally writing a local marketplace."""

    ok: bool
    dry_run: bool
    profile: str
    marketplace: str
    output: str
    steps: list[MarketplaceBuildStep] = field(default_factory=list)
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "profile": self.profile,
            "marketplace": self.marketplace,
            "output": self.output,
            "steps": [step.to_dict() for step in self.steps],
            "detail": self.detail,
        }


def default_workspace_root() -> Path:
    """Return the constellation root containing agent-suite and its siblings."""
    return Path(__file__).resolve().parents[3]


def _plugin_source(workspace_root: Path, entry: CodexPluginEntry) -> Path | None:
    parts = _COMPONENT_PLUGIN_PATHS.get(entry.component_ident)
    return workspace_root.joinpath(*parts) if parts is not None else None


def _validate_plugin(source: Path, entry: CodexPluginEntry) -> str | None:
    manifest = source / ".codex-plugin" / "plugin.json"
    if not manifest.is_file():
        return f"component plugin manifest is missing: {manifest}"
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"component plugin manifest is unreadable: {type(exc).__name__}"
    if not isinstance(payload, dict):
        return "component plugin manifest must be a JSON object"
    if payload.get("name") != entry.plugin_name:
        return (
            f"component plugin name {payload.get('name')!r} does not match "
            f"catalog pin {entry.plugin_name!r}"
        )
    if payload.get("version") != entry.version:
        return (
            f"component plugin version {payload.get('version')!r} does not match "
            f"catalog pin {entry.version!r}"
        )
    return None


def _existing_output_is_owned(output: Path) -> bool:
    marker = output / _OWNER_FILE
    if not marker.is_file():
        return False
    try:
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(payload, dict) and payload.get("owner") == "agent-suite"


def build_local_marketplace(
    *,
    output: Path,
    workspace_root: Path,
    marketplace: str,
    profile: CodexPluginProfile,
    catalog: tuple[CodexPluginEntry, ...],
    dry_run: bool = False,
) -> MarketplaceBuildResult:
    """Compose validated sibling plugins into an explicitly located marketplace.

    Existing directories are touched only when they carry this builder's owner
    marker. Foreign output and non-symlink plugin paths fail closed.
    """
    output = output.expanduser().resolve()
    workspace_root = workspace_root.expanduser().resolve()
    result = MarketplaceBuildResult(
        ok=False,
        dry_run=dry_run,
        profile=profile.value,
        marketplace=marketplace,
        output=str(output),
    )
    if not _MARKETPLACE_RE.fullmatch(marketplace):
        result.detail = "marketplace name must use lowercase letters, digits, and hyphens"
        return result
    if output.exists() and not output.is_dir():
        result.detail = "output exists and is not a directory"
        return result
    if output.exists() and any(output.iterdir()) and not _existing_output_is_owned(output):
        result.detail = "refusing to modify a non-empty marketplace not owned by agent-suite"
        return result

    validated: list[tuple[CodexPluginEntry, Path]] = []
    for entry in catalog:
        source = _plugin_source(workspace_root, entry)
        if source is None:
            result.steps.append(
                MarketplaceBuildStep(
                    plugin=entry.plugin_name,
                    source="",
                    status="unsupported",
                    detail=f"no component plugin source mapping for {entry.component_ident}",
                )
            )
            continue
        error = _validate_plugin(source, entry)
        if error is not None:
            result.steps.append(
                MarketplaceBuildStep(entry.plugin_name, str(source), "invalid", error)
            )
            continue
        validated.append((entry, source.resolve()))
        result.steps.append(
            MarketplaceBuildStep(
                entry.plugin_name,
                str(source.resolve()),
                "validated" if dry_run else "linked",
                f"component-owned plugin v{entry.version}",
            )
        )

    if len(validated) != len(catalog):
        result.detail = "one or more required component plugins are unavailable or invalid"
        return result
    if dry_run:
        result.ok = True
        result.detail = "marketplace validated; dry-run wrote nothing"
        return result

    expected_names = {entry.plugin_name for entry, _source in validated}
    existing_plugins = output / "plugins"
    if existing_plugins.is_dir():
        for child in existing_plugins.iterdir():
            if not child.is_symlink():
                result.detail = f"refusing to modify unowned plugin path: {child}"
                return result
            if child.name in expected_names:
                expected_source = next(
                    source for entry, source in validated if entry.plugin_name == child.name
                )
                if child.resolve() != expected_source and not _existing_output_is_owned(output):
                    result.detail = f"refusing to replace unowned plugin link: {child}"
                    return result

    plugins_dir = output / "plugins"
    catalog_dir = output / ".agents" / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)
    catalog_dir.mkdir(parents=True, exist_ok=True)

    for child in plugins_dir.iterdir():
        if child.name not in expected_names:
            child.unlink()

    entries: list[dict[str, object]] = []
    for entry, source in validated:
        target = plugins_dir / entry.plugin_name
        if target.is_symlink():
            if target.resolve() != source:
                target.unlink()
                target.symlink_to(source, target_is_directory=True)
        elif target.exists():
            result.detail = f"refusing to replace non-symlink plugin path: {target}"
            return result
        else:
            target.symlink_to(source, target_is_directory=True)
        entries.append(
            {
                "name": entry.plugin_name,
                "source": {"source": "local", "path": f"./plugins/{entry.plugin_name}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Developer Tools",
            }
        )

    marketplace_payload = {
        "name": marketplace,
        "interface": {"displayName": "Agent Suite local component marketplace"},
        "plugins": entries,
    }
    owner_payload = {
        "owner": "agent-suite",
        "format": 1,
        "profile": profile.value,
        "marketplace": marketplace,
        "workspace_root": str(workspace_root),
        "plugins": [entry.plugin_name for entry, _source in validated],
    }
    (catalog_dir / "marketplace.json").write_text(
        json.dumps(marketplace_payload, indent=2) + "\n", encoding="utf-8"
    )
    (output / _OWNER_FILE).write_text(
        json.dumps(owner_payload, indent=2) + "\n", encoding="utf-8"
    )
    result.ok = True
    result.detail = "local marketplace composed from component-owned plugins"
    return result


def format_marketplace_build_text(result: MarketplaceBuildResult) -> str:
    """Format a marketplace build result for an operator."""
    lines = [
        f"agent-suite Codex marketplace ({result.profile})",
        f"  output: {result.output}",
        f"  marketplace: {result.marketplace}",
    ]
    for step in result.steps:
        lines.append(f"  {step.plugin:<22} {step.status:<12} {step.detail}")
    lines.append(f"  result: {'OK' if result.ok else 'NOT OK'} — {result.detail}")
    return "\n".join(lines)
