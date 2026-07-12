from __future__ import annotations

import socket
import ssl
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from agent_suite.windows_observation import (
    format_preflight_text,
    observe_host,
    probe_artifact_identity,
    probe_dns,
    probe_elevation,
    probe_os,
    probe_ownership,
    probe_postgres,
    probe_powershell,
    probe_python,
    probe_secret_provider,
    probe_service_account,
    probe_tls,
)
from agent_suite.windows_setup import ProbeState


def test_probe_os_returns_windows_on_windows() -> None:
    os_name, state = probe_os()
    if sys.platform == "win32":
        assert os_name.lower() == "windows"
        assert state is ProbeState.AVAILABLE
    else:
        assert state is ProbeState.UNSUPPORTED


def test_probe_python_returns_version_string() -> None:
    version = probe_python()
    parts = version.split(".")
    assert len(parts) == 3
    assert all(p.isdigit() for p in parts)


def test_probe_powershell_unsupported_on_non_windows() -> None:
    if sys.platform != "win32":
        assert probe_powershell() is ProbeState.UNSUPPORTED


def test_probe_elevation_unsupported_on_non_windows() -> None:
    if sys.platform != "win32":
        assert probe_elevation() is ProbeState.UNSUPPORTED


def test_probe_service_account_unsupported_on_non_windows() -> None:
    if sys.platform != "win32":
        assert probe_service_account() is ProbeState.UNSUPPORTED


def test_probe_postgres_available_on_open_port() -> None:
    mock_socket = pytest.MonkeyPatch()
    mock_socket.setattr(socket, "create_connection", lambda *a, **kw: type("Sock", (), {"__enter__": lambda s: s, "__exit__": lambda *a: None})())
    assert probe_postgres("localhost", 5432) is ProbeState.AVAILABLE
    mock_socket.undo()


def test_probe_postgres_unavailable_on_closed_port() -> None:
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        assert probe_postgres("localhost", 9999) is ProbeState.UNAVAILABLE


def test_probe_postgres_unavailable_on_timeout() -> None:
    with patch("socket.create_connection", side_effect=socket.timeout):
        assert probe_postgres("localhost", 5432) is ProbeState.UNAVAILABLE


def test_probe_dns_available_for_localhost() -> None:
    assert probe_dns("localhost") is ProbeState.AVAILABLE


def test_probe_dns_unavailable_for_bad_hostname() -> None:
    with patch("socket.getaddrinfo", side_effect=socket.gaierror):
        assert probe_dns("nonexistent.invalid") is ProbeState.UNAVAILABLE


def test_probe_tls_unavailable_on_connection_error() -> None:
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        assert probe_tls("localhost", 443) is ProbeState.UNAVAILABLE


def test_probe_tls_unavailable_on_ssl_error() -> None:
    with patch("socket.create_connection", side_effect=ssl.SSLError("bad cert")):
        assert probe_tls("localhost", 443) is ProbeState.UNAVAILABLE


def test_probe_secret_provider_returns_a_state() -> None:
    state = probe_secret_provider()
    assert state in (ProbeState.AVAILABLE, ProbeState.UNAVAILABLE)


def test_probe_artifact_identity_reads_release_file(tmp_path: Path) -> None:
    release_file = tmp_path / "release.txt"
    release_file.write_text("release:1.2.3\n", encoding="utf-8")
    lock_file = tmp_path / "SUITE.lock"
    lock_file.write_text(
        '[suite]\nrelease = "1.2.3"\nregista_schema_version = "42"\n',
        encoding="utf-8",
    )
    release_id, lock_id = probe_artifact_identity(release_file, lock_file)
    assert release_id == "release:1.2.3"
    assert lock_id == "1.2.3"


def test_probe_artifact_identity_returns_empty_for_missing_files(tmp_path: Path) -> None:
    release_id, lock_id = probe_artifact_identity(
        tmp_path / "missing.txt", tmp_path / "missing.lock"
    )
    assert release_id == ""
    assert lock_id == ""


def test_probe_ownership_detects_marker(tmp_path: Path) -> None:
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    assert probe_ownership(install_dir) is False
    (install_dir / ".agent-suite-installed").write_text("installed", encoding="utf-8")
    assert probe_ownership(install_dir) is True


def test_observe_host_assembles_all_probes() -> None:
    observation = observe_host(
        postgres_host="localhost",
        postgres_port=5432,
        dns_hostname="localhost",
        tls_host="localhost",
        tls_port=443,
    )
    assert observation.os_name
    assert observation.python_version
    assert observation.powershell in ProbeState
    assert observation.elevation in ProbeState
    assert observation.service_account in ProbeState
    assert observation.postgres in ProbeState
    assert observation.dns in ProbeState
    assert observation.tls in ProbeState
    assert observation.secret_provider in ProbeState
    assert observation.artifact_release_identity == ""
    assert observation.artifact_lock_identity == ""
    assert observation.ownership_conflict is False


def test_observe_host_with_artifact_files(tmp_path: Path) -> None:
    release_file = tmp_path / "release.txt"
    release_file.write_text("release:test-1", encoding="utf-8")
    lock_file = tmp_path / "SUITE.lock"
    lock_file.write_text('[suite]\nrelease = "test-1"\n', encoding="utf-8")
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / ".agent-suite-installed").write_text("yes", encoding="utf-8")

    observation = observe_host(
        release_file=release_file,
        lock_file=lock_file,
        install_dir=install_dir,
    )
    assert observation.artifact_release_identity == "release:test-1"
    assert observation.artifact_lock_identity == "test-1"
    assert observation.ownership_conflict is True


def test_format_preflight_text_contains_state_and_checks() -> None:
    from agent_suite.windows_setup import (
        HostObservation,
        SetupRequest,
        SetupOperation,
        run_preflight,
    )
    from agent_suite.profiles import Profile

    observation = HostObservation(
        os_name="Windows",
        python_version="3.12.4",
        powershell=ProbeState.AVAILABLE,
        elevation=ProbeState.AVAILABLE,
        service_account=ProbeState.AVAILABLE,
        postgres=ProbeState.AVAILABLE,
        dns=ProbeState.AVAILABLE,
        tls=ProbeState.AVAILABLE,
        secret_provider=ProbeState.AVAILABLE,
        artifact_release_identity="release:test",
        artifact_lock_identity="sha256:" + "a" * 64,
        ownership_conflict=False,
    )
    request = SetupRequest(
        profile=Profile.B,
        target_release_identity="release:test",
        target_lock_identity="sha256:" + "a" * 64,
        operations=frozenset({SetupOperation.WIRE_HARNESSES}),
    )
    report = run_preflight(observation, request)
    text = format_preflight_text(report)
    assert "agent-suite preflight" in text
    assert report.state.value in text
