"""Installed-runtime provenance is exact, conservative, and fail-closed."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_suite.components import Component, Locality, Tier
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
