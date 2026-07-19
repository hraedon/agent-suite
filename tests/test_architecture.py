"""Architecture guard: the core imports only the standard library and its own
modules — never a secret-backend SDK (those live behind extras at the edge) and
never a component's code (this layer composes components via their CLIs, not their
internals). This is the mechanical enforcement of AGENTS.md's "thin orchestration"
and "SDKs at the edge" rules.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

_CORE_MODULES = (
    "cli",
    "components",
    "config",
    "doctor",
    "lock",
    "bootstrap",
    "onboard",
    "verify_restore",
    "upgrade",
    "schedule",
    "alerting",
    "key_watch",
    "profiles",
    "windows_setup",
    "windows_observation",
    "winsw",
    "dual_control",
    "codex_catalog",
    "codex_health",
    "harness_install",
    "release_artifacts",
    "inventory",
    "release_manifest",
)
_FORBIDDEN_PREFIXES = (
    "hvac",  # Vault
    "azure",  # Azure Key Vault
    "win32",  # pywin32 / DPAPI
    "jwt",  # PyJWT (Entra edge adapter)
    "regista",  # compose via CLI, never import a component
    "dossier",
    "agent_notes",
    "cairn",
    "acb",
    "agent_wake",
)

_EDGE_MODULES = ("dpapi", "entra")


def _imports_of(module_name: str) -> set[str]:
    spec = importlib.util.find_spec(f"agent_suite.{module_name}")
    assert spec and spec.origin, f"cannot locate agent_suite.{module_name}"
    tree = ast.parse(Path(spec.origin).read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_core_imports_no_backend_sdk_or_component() -> None:
    for module_name in _CORE_MODULES:
        imported = _imports_of(module_name)
        for forbidden in _FORBIDDEN_PREFIXES:
            assert forbidden not in imported, (
                f"core module {module_name!r} imports forbidden {forbidden!r} — "
                "backend SDKs belong at the secret edge; components are composed via CLI"
            )


def test_edge_modules_are_not_in_core() -> None:
    for edge in _EDGE_MODULES:
        assert edge not in _CORE_MODULES, (
            f"{edge!r} is an edge module — it must not be in _CORE_MODULES"
        )


def test_core_does_not_import_edge_at_module_level() -> None:
    """Core modules must not import edge modules at module level (only lazily inside functions)."""
    for module_name in _CORE_MODULES:
        spec = importlib.util.find_spec(f"agent_suite.{module_name}")
        assert spec and spec.origin, f"cannot locate agent_suite.{module_name}"
        tree = ast.parse(Path(spec.origin).read_text())
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                for edge in _EDGE_MODULES:
                    assert edge not in node.module, (
                        f"core module {module_name!r} imports edge module {edge!r} at module level — "
                        "edge modules must only be imported lazily inside functions"
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    for edge in _EDGE_MODULES:
                        assert edge not in alias.name, (
                            f"core module {module_name!r} imports edge module {edge!r} at module level — "
                            "edge modules must only be imported lazily inside functions"
                        )
