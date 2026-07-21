from __future__ import annotations

import importlib.util
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

from agent_suite.conformance import KIT_VERSION

REPO_ROOT = Path(__file__).parent.parent
CONFORMANCE_DIR = REPO_ROOT / "packaging" / "conformance"
CONFORMANCE_PKG = CONFORMANCE_DIR / "pyproject.toml"


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


def _assert_version_aligned(data: dict[str, object], kit_version: str) -> None:
    """The real guard: the conformance package version must equal the kit's.

    Factored out so the deny-test below can invoke it on tampered input — a
    genuine deny case, not a tautology (process-calibration §5).
    """
    project = data["project"]  # type: ignore[index]
    assert project["name"] == "agent-suite-conformance"
    assert project["version"] == kit_version, (
        f"packaging/conformance version {project['version']!r} != "
        f"KIT_VERSION {kit_version!r}; bump them together"
    )


def test_conformance_wheel_version_matches_kit_version() -> None:
    """Guard (Plan 019 B1): the standalone agent-suite-conformance wheel version
    must equal ``agent_suite.conformance.KIT_VERSION`` — consumers pin
    ``agent-suite-conformance==X.Y`` expecting kit X.Y."""
    _assert_version_aligned(_conformance_pkg(), KIT_VERSION)


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
    """Deny case: the REAL guard (``_assert_version_aligned``) must reject a
    version that disagrees with KIT_VERSION. Invokes the guard on tampered
    input, so inverting/removing the guard's comparison fails this test — not a
    tautology over string ``!=`` (process-calibration §5)."""
    tampered = _conformance_pkg()
    tampered["project"]["version"] = f"{KIT_VERSION}-drifted"  # type: ignore[index]
    with pytest.raises(AssertionError):
        _assert_version_aligned(tampered, KIT_VERSION)


def _build_conformance_wheel(dest: Path) -> Path:
    """Build the conformance wheel into ``dest``; return the wheel path.

    ``--no-isolation`` uses the already-installed build backend (hatchling is a
    dev dep) so the test needs no network. Skips cleanly if the build toolchain
    is absent (e.g. a minimal local checkout)."""
    if importlib.util.find_spec("build") is None:
        pytest.skip("`build` not installed (dev extra); wheel build-test skipped")
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(dest), str(CONFORMANCE_DIR)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        pytest.fail(f"conformance wheel build failed:\n{proc.stderr[-2000:]}")
    wheels = list(dest.glob("agent_suite_conformance-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def test_conformance_wheel_builds_with_correct_layout(tmp_path: Path) -> None:
    """Build the real wheel and assert its LAYOUT (the guard the config-string
    tests can't give): agent_suite/conformance/ present as a PEP 420 namespace
    (no agent_suite/__init__.py), the three modules shipped, and no byte-cache.
    This catches a broken force-include / bypass-selection interaction that the
    pyproject-text guards would miss (opencode review follow-up)."""
    wheel = _build_conformance_wheel(tmp_path)
    names = zipfile.ZipFile(wheel).namelist()
    src = [n for n in names if not n.endswith(".dist-info") and "dist-info/" not in n]

    assert "agent_suite/conformance/__init__.py" in src
    assert "agent_suite/conformance/envelope.py" in src
    assert "agent_suite/conformance/kit.py" in src
    # PEP 420 namespace: the top-level package marker must NOT be shipped, or a
    # regular agent_suite package would shadow the namespace on a consumer.
    assert "agent_suite/__init__.py" not in src, (
        "wheel ships agent_suite/__init__.py — breaks the PEP 420 namespace"
    )
    # No byte-caches in the published artifact.
    assert not any(n.endswith((".pyc", ".pyo")) or "__pycache__" in n for n in src), (
        f"wheel contains byte-cache artifacts: {src}"
    )
