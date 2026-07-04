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

_CORE_MODULES = ("cli", "components", "doctor", "lock", "bootstrap", "verify_restore")
_FORBIDDEN_PREFIXES = (
    "hvac",  # Vault
    "azure",  # Azure Key Vault
    "win32",  # pywin32 / DPAPI
    "regista",  # compose via CLI, never import a component
    "dossier",
    "agent_notes",
    "cairn",
    "acb",
    "agent_wake",
)


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
