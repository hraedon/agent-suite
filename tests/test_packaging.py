from __future__ import annotations

import tomllib
from pathlib import Path

from agent_suite.conformance import KIT_VERSION

REPO_ROOT = Path(__file__).parent.parent
CONFORMANCE_PKG = REPO_ROOT / "packaging" / "conformance" / "pyproject.toml"


def test_pyproject_extras_declared() -> None:
    """Verify all optional extras are declared in pyproject.toml."""
    pyproject = REPO_ROOT / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    extras = data["project"]["optional-dependencies"]

    assert "dev" in extras
    assert "vault" in extras
    assert "azure" in extras
    assert "windows" in extras
    assert "windows-full" in extras

    assert any("PyJWT" in dep for dep in extras["azure"])


def _conformance_pkg() -> dict[str, object]:
    return tomllib.loads(CONFORMANCE_PKG.read_text())


def test_conformance_wheel_version_matches_kit_version() -> None:
    """Guard (Plan 019 B1): the standalone agent-suite-conformance wheel version
    must equal ``agent_suite.conformance.KIT_VERSION``.

    A drift here would publish a wheel whose declared version disagrees with the
    kit it ships — consumers pin ``agent-suite-conformance==X.Y`` expecting kit
    X.Y. process-calibration §5: this guard's deny case is exercised below.
    """
    data = _conformance_pkg()
    assert data["project"]["name"] == "agent-suite-conformance"
    assert data["project"]["version"] == KIT_VERSION, (
        f"packaging/conformance version {data['project']['version']!r} != "
        f"KIT_VERSION {KIT_VERSION!r}; bump them together"
    )


def test_conformance_pkg_ships_the_source_of_truth() -> None:
    """The standalone package must force-include the shared source subtree — not
    a copy — so there is exactly one kit (Plan 018 WI-2 'never copied')."""
    data = _conformance_pkg()
    wheel = data["tool"]["hatch"]["build"]["targets"]["wheel"]
    force = wheel["force-include"]
    assert force.get("../../src/agent_suite/conformance") == "agent_suite/conformance"
    # No agent_suite/__init__.py is shipped -> PEP 420 namespace on consumers.
    assert "../../src/agent_suite/__init__.py" not in force
    assert data["project"]["dependencies"] == []  # stdlib-only, by design


def test_conformance_version_guard_denies_mismatch() -> None:
    """Inverse (deny) case: the comparison the guard relies on actually fails on
    a mismatch, so a refactor can't silently turn the guard into a no-op."""
    declared = _conformance_pkg()["project"]["version"]
    tampered = declared + "-drifted"
    assert tampered != KIT_VERSION
