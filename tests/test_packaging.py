from __future__ import annotations

import filecmp
import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import tomllib
import venv
import zipfile
from pathlib import Path
from typing import Any

import pytest

from agent_suite.conformance import KIT_VERSION

REPO_ROOT = Path(__file__).parent.parent
CONFORMANCE_DIR = REPO_ROOT / "packaging" / "conformance"
CONFORMANCE_PKG = CONFORMANCE_DIR / "pyproject.toml"
BUILD_HOOK = CONFORMANCE_DIR / "hatch_build.py"
SOURCE_OF_TRUTH = REPO_ROOT / "src" / "agent_suite" / "conformance"

# Modules the kit is made of — the source of truth and every artifact must agree.
KIT_MODULES = ("__init__.py", "envelope.py", "kit.py")

# The packaging BUILD tests are mandatory wherever their declared dev dependency
# should exist: CI installs the [dev] extra (which declares `build` + `hatchling`)
# before running pytest, so the toolchain is always present there. Failing at
# collection — instead of silently skipping per test — means a missing/broken dev
# extra is a loud red build, not a green run that quietly enforced nothing (the
# same fails-open hazard the suite guards against in conftest.py's
# INTEROP_REQUIRE_FACES and the WI-026 meta-guard). The pure-config tests above
# the build section do not need the toolchain and run regardless.
_MISSING_TOOLCHAIN = [
    name
    for name in ("build", "hatchling")
    if importlib.util.find_spec(name) is None
]
if _MISSING_TOOLCHAIN:
    pytest.fail(
        "packaging build tests are mandatory but the declared [dev] dependency "
        f"is missing: {', '.join(_MISSING_TOOLCHAIN)}. Install the dev extra "
        "(`uv sync --extra dev`). A silent skip here would hide a release-path "
        "regression."
    )


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
    """The standalone package must ship the shared source subtree — not a copy —
    so there is exactly one kit (Plan 018 WI-2 'never copied').

    The source is force-included by the custom build hook (hatch_build.py), which
    reads the canonical monorepo subtree at build time. Assert the hook is wired
    up, that the targets keep bypass-selection (so nothing auto-detected broadens
    the artifact), and that no agent_suite/__init__.py is force-included (the PEP
    420 namespace must hold on consumers).
    """
    data = _conformance_pkg()
    hooks = data["tool"]["hatch"]["build"]["hooks"]
    assert hooks["custom"]["path"] == "hatch_build.py", (
        "the conformance source must be force-included by the custom build hook"
    )
    assert BUILD_HOOK.is_file(), "packaging/conformance/hatch_build.py must exist"
    for target in ("wheel", "sdist"):
        assert data["tool"]["hatch"]["build"]["targets"][target]["bypass-selection"] is True, (
            f"{target} must keep bypass-selection so only the hook's force-include ships"
        )
    assert data["project"]["dependencies"] == []  # stdlib-only, by design


def test_conformance_build_uses_hook_not_symlink() -> None:
    """Mechanical proof that no symlink is used or required (the Git-for-Windows
    core.symlinks=false hazard): nothing under packaging/conformance is a symlink,
    and the build hook is a regular file. The build is driven entirely by
    hatch_build.py reading the canonical source, so a checkout that cannot
    represent symlinks builds identically.
    """
    symlinks = [p for p in CONFORMANCE_DIR.rglob("*") if p.is_symlink()]
    assert not symlinks, (
        f"packaging/conformance must not rely on symlinks (core.symlinks=false "
        f"breaks them); found: {symlinks}"
    )
    # The old in-project link location must not exist in any form.
    assert not (CONFORMANCE_DIR / "agent_suite" / "conformance").exists(), (
        "the old agent_suite/conformance link location must be gone; the hook "
        "supplies the source at build time"
    )
    assert BUILD_HOOK.is_file() and not BUILD_HOOK.is_symlink()


def _load_hook_module() -> Any:
    """Load packaging/conformance/hatch_build.py without importing the package
    (it lives outside any installed distribution)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_conformance_hatch_build", BUILD_HOOK)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conformance_hook_canonical_resolves_to_source_of_truth() -> None:
    """Adjudication guard: the hook resolves its canonical source relative to the
    PROJECT dir (packaging/conformance — hatchling's ``self.root``), not the
    monorepo root. Load the hook's own ``_CANONICAL_SOURCE`` constant, resolve it
    against CONFORMANCE_DIR, and assert it lands exactly on the source of truth.

    This is the executable falsifier for the review claim that ``self.root`` is
    the monorepo root: if it were, ``<root>/../../src/...`` would resolve to the
    repo's GRANDPARENT and miss the source — this assertion would fail. It ties
    to the hook's real constant (not a re-derivation), so editing the constant
    wrongly reddens the test. The live root value itself is confirmed by the
    source-tree builds the other tests run (they only pass if root is the project
    dir, since the canonical path is relative to it).
    """
    hook = _load_hook_module()
    resolved = Path(os.path.normpath(os.path.join(CONFORMANCE_DIR, hook._CANONICAL_SOURCE)))
    assert resolved == SOURCE_OF_TRUTH, (
        f"hook canonical source resolves to {resolved}, expected {SOURCE_OF_TRUTH}; "
        "the hook must resolve relative to the project dir (self.root)"
    )
    # The constant must be relative (os.path.join semantics) so it composes with
    # whatever self.root is — never an absolute path that ignores root.
    assert not os.path.isabs(hook._CANONICAL_SOURCE), (
        "the hook's canonical source must be a relative path composed onto self.root"
    )


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
    dev dep) so the test needs no network. The build toolchain's presence is
    enforced at module collection (see the mandatory-dependency guard above)."""
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(dest), str(CONFORMANCE_DIR)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"conformance wheel build failed:\n{proc.stderr[-2000:]}")
    wheels = list(dest.glob("agent_suite_conformance-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def _build_conformance_sdist(dest: Path) -> Path:
    """Build the conformance sdist into ``dest``; return the sdist path."""
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--sdist", "--no-isolation",
         "--outdir", str(dest), str(CONFORMANCE_DIR)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"conformance sdist build failed:\n{proc.stderr[-2000:]}")
    sdists = list(dest.glob("agent_suite_conformance-*.tar.gz"))
    assert len(sdists) == 1, f"expected exactly one sdist, got {sdists}"
    return sdists[0]


def _build_wheel_from_sdist(sdist: Path, dest: Path) -> Path:
    """Build a wheel FROM ``sdist`` into ``dest`` — the release path that
    ``python -m build`` exercises (sdist, then wheel-from-sdist). ``build`` takes
    a source *directory*, so this extracts the sdist to a temp dir and builds
    from there, exactly as ``python -m build`` does internally. This is the step
    that fails when the sdist is not self-contained (missing hook or source)."""
    extract = dest / "_sdist_extract"
    extract.mkdir()
    with tarfile.open(sdist) as tf:
        tf.extractall(extract, filter="data")
    roots = [p for p in extract.iterdir() if p.is_dir()]
    assert len(roots) == 1, f"expected one extracted sdist root, got {roots}"
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(dest), str(roots[0])],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            "wheel-from-sdist build failed (the release path is broken):\n"
            f"{proc.stderr[-2000:]}"
        )
    wheels = list(dest.glob("agent_suite_conformance-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    return wheels[0]


def _wheel_source_names(wheel: Path) -> list[str]:
    """The shipped source entries of ``wheel`` (everything outside .dist-info)."""
    names = zipfile.ZipFile(wheel).namelist()
    return [n for n in names if "dist-info/" not in n]


def test_conformance_wheel_builds_with_correct_layout(tmp_path: Path) -> None:
    """Build the real wheel and assert its LAYOUT (the guard the config-string
    tests can't give): agent_suite/conformance/ present as a PEP 420 namespace
    (no agent_suite/__init__.py), the three modules shipped, and no byte-cache.
    This catches a broken force-include / bypass-selection interaction that the
    pyproject-text guards would miss (opencode review follow-up)."""
    wheel = _build_conformance_wheel(tmp_path)
    src = _wheel_source_names(wheel)

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


def _assert_namespace_layout(src_names: list[str], artifact: str) -> None:
    """Shared layout assertion for a built artifact's source entries."""
    for module in KIT_MODULES:
        assert f"agent_suite/conformance/{module}" in src_names, (
            f"{artifact} is missing agent_suite/conformance/{module}"
        )
    assert "agent_suite/__init__.py" not in src_names, (
        f"{artifact} ships agent_suite/__init__.py — breaks the PEP 420 namespace"
    )
    assert not any(
        n.endswith((".pyc", ".pyo")) or "__pycache__" in n for n in src_names
    ), f"{artifact} contains byte-cache artifacts: {src_names}"


def test_conformance_sdist_builds_minimal_and_self_contained(tmp_path: Path) -> None:
    """The sdist must be minimal and self-contained: exactly the conformance
    subtree (at the path the wheel reads from) plus the build hook and metadata —
    NOT the rest of agent_suite. A hook that force-included too much would broaden
    the sdist; this guard fails if that recurs. It also asserts the source is
    materialized as real files (no link entries) and that hatch_build.py ships,
    since the wheel-from-sdist step must be able to run the hook."""
    sdist = _build_conformance_sdist(tmp_path)
    with tarfile.open(sdist) as tf:
        members = tf.getmembers()
        names = sorted(m.name for m in members)
        # No symlink entries: the source must be materialized, or a consumer
        # building from the sdist would hit a dangling link.
        symlinks = [m.name for m in members if m.issym() or m.islnk()]
        assert not symlinks, f"sdist carries link entries (not self-contained): {symlinks}"

    prefix = f"agent_suite_conformance-{KIT_VERSION}/"
    relative = sorted(n[len(prefix):] for n in names if n.startswith(prefix))
    # The three modules, at the path the wheel-from-sdist build reads from.
    for module in KIT_MODULES:
        assert f"agent_suite/conformance/{module}" in relative, (
            f"sdist missing agent_suite/conformance/{module}; has {relative}"
        )
    # Minimal: no module of agent_suite outside the conformance subtree leaked in.
    leaked = [
        n for n in relative
        if n.startswith("agent_suite/") and not n.startswith("agent_suite/conformance/")
    ]
    assert not leaked, f"sdist broadened beyond the conformance subtree: {leaked}"
    # No byte-cache.
    assert not any(n.endswith((".pyc", ".pyo")) or "__pycache__" in n for n in relative)
    # Self-containment: the hook and metadata the wheel-from-sdist step needs.
    assert "hatch_build.py" in relative, "sdist must ship the build hook"
    assert "pyproject.toml" in relative
    assert "PKG-INFO" in relative


def test_conformance_wheel_builds_from_sdist(tmp_path: Path) -> None:
    """Regression for the release-blocking defect: ``python -m build`` builds an
    sdist and then rebuilds the wheel FROM that sdist. This requires the sdist to
    be self-contained — it must carry both the materialized conformance subtree
    and the build hook that force-includes it. Build the sdist, build a wheel from
    it, and assert the wheel has the correct PEP 420 namespace layout."""
    sdist_dir = tmp_path / "sdist"
    wheel_dir = tmp_path / "wheel"
    sdist_dir.mkdir()
    wheel_dir.mkdir()
    sdist = _build_conformance_sdist(sdist_dir)
    wheel = _build_wheel_from_sdist(sdist, wheel_dir)
    _assert_namespace_layout(_wheel_source_names(wheel), "wheel-from-sdist")


def test_conformance_sdist_source_matches_source_of_truth(tmp_path: Path) -> None:
    """Drift guard: the conformance modules shipped in the sdist must be
    byte-identical to the source of truth at src/agent_suite/conformance/. The
    build hook reads that one maintained subtree, so the published kit cannot
    diverge from it; if a future change introduced a copy, this fails CI
    (Plan 018 WI-2 'never copied')."""
    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()
    sdist = _build_conformance_sdist(sdist_dir)
    extract = tmp_path / "extract"
    extract.mkdir()
    with tarfile.open(sdist) as tf:
        tf.extractall(extract, filter="data")
    shipped_root = (
        extract / f"agent_suite_conformance-{KIT_VERSION}" / "agent_suite" / "conformance"
    )
    for module in KIT_MODULES:
        shipped = shipped_root / module
        original = SOURCE_OF_TRUTH / module
        assert shipped.is_file(), f"sdist did not ship agent_suite/conformance/{module}"
        assert filecmp.cmp(shipped, original, shallow=False), (
            f"shipped agent_suite/conformance/{module} differs from the source of "
            f"truth at {original} — the kit has drifted"
        )


def test_conformance_wheel_exposes_public_api(tmp_path: Path) -> None:
    """The built wheel must import standalone (PEP 420 namespace) and expose the
    full public surface a consumer pins — including the 1.1.0 meta-guard.

    Isolation matters: agent-suite is commonly installed editable (a *regular*
    ``agent_suite`` package that shadows the namespace), so the probe runs with
    ``PYTHONNOUSERSITE=1`` and ``PYTHONPATH`` pointed only at the extracted wheel,
    and asserts ``agent_suite.conformance.__file__`` actually resolves inside the
    wheel — proving the public surface came from the artifact, not a shadow.
    """
    wheel = _build_conformance_wheel(tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(site)
    probe = (
        "import os, agent_suite.conformance as c;"
        "site = os.environ['_PROBE_SITE'];"
        "assert c.__file__ and c.__file__.startswith(site), "
        "'import shadowed, not from wheel: ' + str(c.__file__);"
        "print(c.KIT_VERSION);"
        "print(','.join(sorted(c.__all__)))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True, text=True, check=False,
        cwd=tmp_path,
        env={
            "PYTHONPATH": str(site),
            "PYTHONNOUSERSITE": "1",
            "_PROBE_SITE": str(site),
            "PATH": os.environ.get("PATH", os.defpath),
        },
    )
    if proc.returncode != 0:
        pytest.fail(f"wheel import probe failed:\n{proc.stderr[-2000:]}")
    lines = proc.stdout.strip().splitlines()
    assert lines[0] == KIT_VERSION, f"wheel KIT_VERSION {lines[0]!r} != {KIT_VERSION!r}"
    exported = set(lines[1].split(","))
    required = {
        "KIT_VERSION", "CLI_CONTRACT_VERSION",
        "SuccessCase", "ErrorCase", "UsageCase", "BrokenPipeCase", "Framing",
        "run_success_case", "run_error_case", "run_usage_case", "run_broken_pipe_case",
        "build_envelope", "validate_envelope", "emit_error",
        "assert_cases_declared", "ConformanceGateError",
    }
    missing = required - exported
    assert not missing, f"wheel __all__ is missing public API: {sorted(missing)}"


def test_conformance_build_survives_windows_core_symlinks_false(tmp_path: Path) -> None:
    """Simulate Git for Windows with ``core.symlinks=false``: that checkout mode
    materializes a committed symlink as a plain text file holding the link target.
    The previous (rejected) design committed a symlink at
    ``agent_suite/conformance``; on such a checkout it would become a regular file
    and the build would silently ship nothing.

    This test replicates the monorepo layout in a temp tree, plants a REGULAR FILE
    (with the old link text) at exactly that location, and proves the hook-driven
    build still produces a correct wheel — i.e. the design needs no symlink and is
    immune to the Windows materialization. The hook treats the stray file as "not
    a usable local subtree" and falls through to the canonical source.
    """
    repo = tmp_path / "repo"
    pkg = repo / "packaging" / "conformance"
    (pkg / "agent_suite").mkdir(parents=True)
    # Canonical source of truth, reachable from the package dir as ../../src/...
    shutil.copytree(SOURCE_OF_TRUTH, repo / "src" / "agent_suite" / "conformance")
    # The packaging project files (the hook + its config + readme).
    for name in ("pyproject.toml", "hatch_build.py", "README.md"):
        shutil.copy(CONFORMANCE_DIR / name, pkg / name)
    # The core.symlinks=false artifact: a regular file where a symlink would be.
    stray = pkg / "agent_suite" / "conformance"
    stray.write_text("../../../src/agent_suite/conformance\n")
    assert stray.is_file() and not stray.is_dir()

    out = tmp_path / "dist"
    out.mkdir()
    proc = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation",
         "--outdir", str(out), str(pkg)],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            "build failed with a core.symlinks=false-style regular file at the old "
            f"link location — the design must not depend on symlinks:\n"
            f"{proc.stderr[-2000:]}"
        )
    wheels = list(out.glob("agent_suite_conformance-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    _assert_namespace_layout(_wheel_source_names(wheels[0]), "wheel (symlinks=false sim)")


def _venv_python(venv_dir: Path) -> Path:
    """The interpreter inside ``venv_dir`` (cross-platform)."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _venv_site_packages(venv_dir: Path) -> str:
    """The site-packages dir of the venv, queried from its own interpreter."""
    proc = subprocess.run(
        [str(_venv_python(venv_dir)), "-c", "import site; print(site.getsitepackages()[0])"],
        capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, f"could not resolve venv site-packages: {proc.stderr}"
    return proc.stdout.strip()


# pip stderr markers that mean "this environment cannot run an isolated editable
# build right now" (no network / no cached build deps) — as opposed to a real
# defect in the package, which must stay a hard failure.
_ENV_LIMITED_MARKERS = (
    "could not find a version",
    "no matching distribution",
    "failed to establish a new connection",
    "temporary failure in name resolution",
    "network is unreachable",
    "connectionerror",
    "timed out",
    "resolution-too-deep",
)


def test_conformance_editable_install_pep660(tmp_path: Path) -> None:
    """PEP 660 editable-install falsifier: ``pip install -e packaging/conformance``
    in an isolated venv must (a) not crash the build hook (its editable handling)
    and (b) leave ``agent_suite.conformance`` importable with the current
    KIT_VERSION, resolving into the venv (not the operator's user-site shadow).

    The editable build runs the hook with the real source tree present, so the
    canonical branch fires and hatchling materializes the force-included source;
    the import check verifies that materialization. This guards the editable
    permissiveness — if the hook ever raised on an editable build, ``pip install
    -e`` would fail and this test would redden (only then should the editable
    logic change). The build needs hatchling+editables; when the environment
    cannot supply them (no network, empty pip cache) the test skips with a clear
    reason rather than silently passing — but a genuine build/import failure is a
    hard fail.
    """
    venv_dir = tmp_path / "editvenv"
    try:
        venv.EnvBuilder(system_site_packages=True, with_pip=True).create(venv_dir)
    except Exception as exc:
        pytest.skip(f"cannot create a venv here ({exc}); editable proof skipped")
    py = _venv_python(venv_dir)
    if not py.is_file():
        pytest.skip("venv has no interpreter; editable proof skipped")

    proc = subprocess.run(
        [str(py), "-m", "pip", "install", "--no-deps", "-e", str(CONFORMANCE_DIR)],
        capture_output=True, text=True, check=False, timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stdout + proc.stderr).lower()
        if any(marker in err for marker in _ENV_LIMITED_MARKERS):
            pytest.skip(
                "editable build needs hatchling/editables via network or pip cache, "
                "unavailable in this environment; editable proof skipped"
            )
        pytest.fail(f"editable install failed (not an env limitation):\n{proc.stderr[-2500:]}")

    # Verify the import resolves into the venv site (our editable install), with
    # the user-site shadow removed so we measure THIS install, and the venv site
    # placed first so it wins over any inherited system-site namespace portion.
    site = _venv_site_packages(venv_dir)
    probe = (
        "import importlib.util, os, sys;"
        f"sys.path.insert(0, {site!r});"
        "spec = importlib.util.find_spec('agent_suite.conformance');"
        "assert spec and spec.origin, 'no spec for agent_suite.conformance';"
        f"assert spec.origin.startswith({site!r}), 'not from editable install: ' + spec.origin;"
        "import agent_suite.conformance as c;"
        f"assert c.__file__.startswith({site!r}), 'import shadowed: ' + c.__file__;"
        "print(c.KIT_VERSION)"
    )
    check = subprocess.run(
        [str(py), "-c", probe],
        capture_output=True, text=True, check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    if check.returncode != 0:
        pytest.fail(f"editable import probe failed:\n{check.stderr[-2000:]}")
    assert check.stdout.strip() == KIT_VERSION, (
        f"editable install exposes KIT_VERSION {check.stdout.strip()!r}, "
        f"expected {KIT_VERSION!r}"
    )


def test_conformance_wheel_from_sdist_isolated_release_path(tmp_path: Path) -> None:
    """The consumer-facing release path with hatchling's DEFAULT build isolation
    (no ``--no-isolation``): build the sdist offline, then build a wheel from it
    the way a consumer / ``python -m build`` does — hatchling resolves its own
    backend in an isolated env. The other wheel-from-sdist test pins
    ``--no-isolation`` for offline determinism; this one proves the normal
    isolated path also works. It requires network (or a warm pip cache) only for
    the isolated wheel build, so it skips — never silently passes — when that is
    unavailable; the sdist step stays offline."""
    sdist_dir = tmp_path / "sdist"
    sdist_dir.mkdir()
    sdist = _build_conformance_sdist(sdist_dir)  # offline (--no-isolation)

    extract = tmp_path / "extract"
    extract.mkdir()
    with tarfile.open(sdist) as tf:
        tf.extractall(extract, filter="data")
    roots = [p for p in extract.iterdir() if p.is_dir()]
    assert len(roots) == 1, f"expected one extracted sdist root, got {roots}"

    out = tmp_path / "wheel"
    out.mkdir()
    proc = subprocess.run(
        # NOTE: deliberately NO --no-isolation — this is the isolated consumer path.
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(out), str(roots[0])],
        capture_output=True, text=True, check=False, timeout=300,
    )
    if proc.returncode != 0:
        err = (proc.stdout + proc.stderr).lower()
        if any(marker in err for marker in _ENV_LIMITED_MARKERS):
            pytest.skip(
                "isolated wheel build needs hatchling via network or pip cache, "
                "unavailable in this environment; isolated release-path proof skipped"
            )
        pytest.fail(
            "isolated wheel-from-sdist failed (not an env limitation):\n"
            f"{proc.stderr[-2500:]}"
        )
    wheels = list(out.glob("agent_suite_conformance-*.whl"))
    assert len(wheels) == 1, f"expected exactly one wheel, got {wheels}"
    _assert_namespace_layout(_wheel_source_names(wheels[0]), "wheel (isolated release path)")
