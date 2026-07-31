"""Installed-runtime provenance is exact, conservative, and fail-closed."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_suite.components import COMPONENTS, Component, Locality, Tier
from agent_suite.runtime_provenance import (
    ArtifactSource,
    InstallMode,
    probe_runtime_provenance,
    read_runtime_revisions,
)


def _component(*, locality: Locality = Locality.PER_BOX) -> Component:
    return Component(
        ident="example",
        repo="example/example",
        tier=Tier.FACE,
        doctor_cmd=("example", "doctor", "--json"),
        upgrade_package="example-canonical",
        distribution_names=("example-canonical", "example-legacy"),
        locality=locality,
    )


def _completed(
    *, stdout: str = "", stderr: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess((), returncode, stdout, stderr)


class ProbeRunner:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, command: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if command[:3] == ("pipx", "list", "--json"):
            return _completed(returncode=1)
        if command[:3] == ("uv", "tool", "dir"):
            return _completed(returncode=1)
        if "-c" in command:
            return _completed(stdout=json.dumps(self.payload))
        return _completed(returncode=1)


def _payload(tmp_path: Path, **overrides: object) -> dict[str, object]:
    user_site = tmp_path / "user-site"
    values: dict[str, object] = {
        "ok": True,
        "distribution": "example-canonical",
        "version": "1.2.3",
        "interpreter": "/usr/bin/python3",
        "prefix": "/usr",
        "base_prefix": "/usr",
        "location": str(user_site / "example"),
        "scripts": str(tmp_path / "bin"),
        "user_sites": [str(user_site)],
        "pep668": True,
        "source": "unrecorded",
        "revision": None,
        "source_path": None,
    }
    values.update(overrides)
    return values


def test_probe_uses_only_cli_shebang_interpreter(tmp_path: Path) -> None:
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    runner = ProbeRunner(_payload(tmp_path))

    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )

    assert record.mode is InstallMode.PIP_USER
    assert record.interpreter == "/usr/bin/python3"
    metadata_calls = [call for call in runner.calls if "-c" in call]
    assert len(metadata_calls) == 1
    assert metadata_calls[0][0] == "/usr/bin/python3"
    assert record.pep668 is True


def test_non_python_wrapper_is_not_attributed_to_ambient_python(tmp_path: Path) -> None:
    cli = tmp_path / "example"
    cli.write_text("#!/bin/sh\nexec something-else\n")
    runner = ProbeRunner(_payload(tmp_path))

    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else "/ambient/python",
    )

    assert record.mode is InstallMode.UNKNOWN
    assert not any("-c" in call for call in runner.calls)


def test_editable_revision_requires_clean_exact_checkout(tmp_path: Path) -> None:
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    source = tmp_path / "source"
    source.mkdir()
    runner = ProbeRunner(
        _payload(tmp_path, source="editable", source_path=str(source))
    )

    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )

    assert record.mode is InstallMode.EDITABLE
    assert record.source is ArtifactSource.EDITABLE
    assert record.revision is None
    assert "Git" in record.detail


def test_shared_service_never_uses_local_cli_revision(tmp_path: Path) -> None:
    revision = "a" * 40
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    runner = ProbeRunner(_payload(tmp_path, source="vcs", revision=revision))

    revisions = read_runtime_revisions(
        components=(_component(locality=Locality.SHARED_SERVICE),),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )
    assert revisions == {"example": None}


def test_invalid_metadata_result_fails_closed(tmp_path: Path) -> None:
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    runner = ProbeRunner({"ok": False, "detail": "ambiguous"})

    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )

    assert record.mode is InstallMode.UNKNOWN
    assert record.version is None


def test_path_shadow_script_is_not_misattributed_by_module_ownership(
    tmp_path: Path,
) -> None:
    shadow = tmp_path / "pytest"
    shadow.write_text(f"#!{sys.executable}\nraise SystemExit(0)\n")
    comp = Component(
        ident="pytest-shadow",
        repo="pytest-dev/pytest",
        tier=Tier.FACE,
        doctor_cmd=("pytest", "--version"),
        upgrade_package="pytest",
        distribution_names=("pytest",),
    )

    record = probe_runtime_provenance(
        comp,
        which=lambda name: str(shadow) if name == "pytest" else None,
    )

    assert record.mode is InstallMode.UNKNOWN
    assert record.distribution is None


def test_uv_tool_detected_when_interpreter_is_symlink(tmp_path):
    """A uv tool venv's bin/python is usually a symlink to the base
    interpreter; containment must be judged on the path as invoked, not
    its resolved target, or every uv tool reads UNKNOWN and the strict
    provenance probe fails the whole doctor (WI-036)."""
    from agent_suite.runtime_provenance import _path_within, _path_within_lexical

    uv_root = tmp_path / "uv" / "tools"
    venv_bin = uv_root / "some-tool" / "bin"
    venv_bin.mkdir(parents=True)
    base = tmp_path / "usr" / "bin" / "python3.14"
    base.parent.mkdir(parents=True)
    base.write_text("")
    interp = venv_bin / "python"
    interp.symlink_to(base)

    assert _path_within(interp, uv_root) is False  # the resolving check misses
    assert _path_within_lexical(interp, uv_root) is True


# --- artifact-era fields (WI-036) --------------------------------------------


def test_archive_install_carries_dist_info_and_archive_url(tmp_path: Path) -> None:
    """A wheel install must expose what it *can* be attested against."""
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    dist_info = tmp_path / "site-packages" / "example_canonical-1.2.3.dist-info"
    runner = ProbeRunner(
        _payload(
            tmp_path,
            source="archive",
            dist_info=str(dist_info),
            archive_url="file:///wheels/example_canonical-1.2.3-py3-none-any.whl",
            archive_sha256=None,
        )
    )

    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )

    assert record.source is ArtifactSource.ARCHIVE
    assert record.revision is None  # by construction: archives carry no revision
    assert record.dist_info_path == str(dist_info)
    assert record.archive_url.endswith("example_canonical-1.2.3-py3-none-any.whl")
    assert record.archive_sha256 is None
    payload = record.to_dict()
    assert payload["dist_info_path"] == str(dist_info)
    assert payload["archive_sha256"] is None


def test_recorded_archive_sha256_is_carried_when_valid(tmp_path: Path) -> None:
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    digest = "b" * 64
    runner = ProbeRunner(
        _payload(tmp_path, source="archive", archive_sha256=digest)
    )
    record = probe_runtime_provenance(
        _component(),
        runner=runner,
        which=lambda name: str(cli) if name == "example" else None,
    )
    assert record.archive_sha256 == digest


def test_malformed_archive_sha256_is_dropped_not_trusted(tmp_path: Path) -> None:
    """A non-hex or wrong-length digest must not be passed off as a hash."""
    cli = tmp_path / "example"
    cli.write_text("#!/usr/bin/python3\n")
    for bogus in ("not-a-hash", "abc", "z" * 64, ""):
        runner = ProbeRunner(
            _payload(tmp_path, source="archive", archive_sha256=bogus)
        )
        record = probe_runtime_provenance(
            _component(),
            runner=runner,
            which=lambda name: str(cli) if name == "example" else None,
        )
        assert record.archive_sha256 is None, bogus


def test_probe_reads_pep610_archive_hashes_from_a_real_dist(tmp_path: Path) -> None:
    """Exercise the in-process probe source itself against a synthetic dist.

    The probe is a string executed by another interpreter, so it is otherwise
    only covered by stubs. This runs it for real against a dist-info tree
    carrying ``archive_info.hashes``, which is the one PEP 610 field that
    cryptographically binds an install to a wheel.
    """
    from agent_suite.runtime_provenance import _METADATA_PROBE

    site = tmp_path / "site-packages"
    dist_info = site / "example_canonical-1.2.3.dist-info"
    dist_info.mkdir(parents=True)
    (site / "example_canonical.py").write_text("def main() -> None:\n    pass\n")
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: example-canonical\nVersion: 1.2.3\n"
    )
    (dist_info / "entry_points.txt").write_text(
        "[console_scripts]\nexample = example_canonical:main\n"
    )
    digest = "c" * 64
    (dist_info / "direct_url.json").write_text(
        json.dumps(
            {
                "url": "https://example.invalid/example_canonical-1.2.3.whl",
                "archive_info": {"hashes": {"sha256": digest}},
            }
        )
    )
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "example"
    cli.write_text("#!/usr/bin/python3\n")
    # RECORD paths are relative to site-packages; the console script sits
    # outside it, exactly as a real install records it.
    (dist_info / "RECORD").write_text(
        "../bin/example,,\n"
        "example_canonical.py,,\n"
        f"{dist_info.name}/METADATA,,\n"
        f"{dist_info.name}/RECORD,,\n"
    )

    result = subprocess.run(
        [
            sys.executable, "-c", _METADATA_PROBE,
            "example", str(cli), "example-canonical",
        ],
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": str(site), "PATH": "/usr/bin:/bin"},
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True, payload
    assert payload["source"] == "archive"
    assert payload["archive_sha256"] == digest
    assert payload["archive_url"].endswith("example_canonical-1.2.3.whl")
    assert Path(payload["dist_info"]) == dist_info.resolve()


def test_umbrella_provenance_is_probed_alongside_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WI-036 review MAJOR-2: the umbrella must be probeable.

    ``agent-suite`` is not one of COMPONENTS, so a component-only probe left the
    one distribution the operator runs ``doctor`` FROM with no provenance record
    at all — and the manifest's umbrella entry therefore unattestable on every
    host.
    """
    from agent_suite.runtime_provenance import (
        UMBRELLA_COMPONENT,
        read_runtime_provenance_with_umbrella,
    )

    assert all(c.ident != UMBRELLA_COMPONENT.ident for c in COMPONENTS)
    probed: list[str] = []

    def _which(name: str) -> str | None:
        probed.append(name)
        return None

    records = read_runtime_provenance_with_umbrella(
        components=(), runner=lambda cmd: _completed(returncode=1), which=_which
    )
    assert set(records) == {"agent-suite"}
    assert records["agent-suite"].mode is InstallMode.ABSENT
    assert "agent-suite" in probed


def test_umbrella_component_declares_its_distribution_name() -> None:
    from agent_suite.release_manifest import UMBRELLA_IDENT
    from agent_suite.runtime_provenance import UMBRELLA_COMPONENT

    assert UMBRELLA_COMPONENT.ident == UMBRELLA_IDENT
    assert UMBRELLA_COMPONENT.distribution_names == ("agent-suite",)
    assert UMBRELLA_COMPONENT.doctor_cmd[0] == "agent-suite"
