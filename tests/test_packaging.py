from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_extras_declared() -> None:
    """Verify all optional extras are declared in pyproject.toml."""
    pyproject = Path(__file__).parent.parent / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text())
    extras = data["project"]["optional-dependencies"]

    assert "dev" in extras
    assert "vault" in extras
    assert "azure" in extras
    assert "windows" in extras
    assert "windows-full" in extras

    assert any("PyJWT" in dep for dep in extras["azure"])
