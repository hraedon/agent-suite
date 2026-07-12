"""Windows host observation adapters — read-only probes that populate HostObservation.

This module is stdlib-only and importable on both Linux and Windows. Windows-
specific probes use ``ctypes.windll`` (stdlib) guarded by ``sys.platform``
checks. On non-Windows, Windows-specific probes return ``ProbeState.UNSUPPORTED``.

No probe in this module mutates the host. No probe reads secret values. The
secret-provider probe checks *availability* only (is DPAPI present? is Vault
configured?) — it never resolves or returns a secret.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import ssl
import sys
from pathlib import Path
from agent_suite.windows_setup import HostObservation, ProbeState, SetupOperation


def probe_os() -> tuple[str, ProbeState]:
    """Return the OS name and whether it is a supported Windows host."""
    os_name = platform.system()
    state = ProbeState.AVAILABLE if os_name.lower() == "windows" else ProbeState.UNSUPPORTED
    return os_name, state


def probe_python() -> str:
    """Return the Python version string (major.minor.micro)."""
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def probe_powershell() -> ProbeState:
    """Check whether PowerShell is available on the host."""
    if sys.platform != "win32":
        return ProbeState.UNSUPPORTED
    if shutil.which("pwsh") is not None or shutil.which("powershell") is not None:
        return ProbeState.AVAILABLE
    return ProbeState.UNAVAILABLE


def probe_elevation() -> ProbeState:
    """Check whether the current process is elevated (administrator)."""
    if sys.platform != "win32":
        return ProbeState.UNSUPPORTED
    if not hasattr(ctypes, "windll"):
        return ProbeState.UNKNOWN
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return ProbeState.UNKNOWN
    return ProbeState.AVAILABLE if is_admin else ProbeState.UNAVAILABLE


def probe_service_account() -> ProbeState:
    """Best-effort check whether the process is running as a service account."""
    if sys.platform != "win32":
        return ProbeState.UNSUPPORTED
    session_name = os.environ.get("SESSIONNAME", "")
    if session_name and "Services" in session_name:
        return ProbeState.AVAILABLE
    username = os.environ.get("USERNAME", "")
    if username and username.lower().startswith("svc-"):
        return ProbeState.AVAILABLE
    return ProbeState.UNKNOWN


def probe_postgres(host: str, port: int, timeout: float = 3.0) -> ProbeState:
    """TCP connect check to a Postgres host:port."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return ProbeState.AVAILABLE
    except Exception:
        return ProbeState.UNAVAILABLE


def probe_dns(hostname: str) -> ProbeState:
    """Check whether a hostname resolves via DNS."""
    try:
        socket.getaddrinfo(hostname, None)
        return ProbeState.AVAILABLE
    except Exception:
        return ProbeState.UNAVAILABLE


def probe_tls(host: str, port: int = 443, timeout: float = 3.0) -> ProbeState:
    """Check whether a TLS handshake succeeds against host:port."""
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host):
                return ProbeState.AVAILABLE
    except Exception:
        return ProbeState.UNAVAILABLE


def probe_secret_provider() -> ProbeState:
    """Check whether a secret provider is available (non-secret availability check).

    On Windows, checks whether DPAPI is actually usable by attempting to import
    ``win32crypt`` via ``agent_suite.dpapi.is_available()``. This avoids a false
    positive when ``ctypes.windll`` exists but pywin32 is not installed.
    """
    if sys.platform == "win32":
        try:
            from agent_suite.dpapi import is_available as dpapi_available

            return ProbeState.AVAILABLE if dpapi_available() else ProbeState.UNAVAILABLE
        except Exception:
            return ProbeState.UNAVAILABLE
    if os.environ.get("VAULT_ADDR"):
        return ProbeState.AVAILABLE
    if os.environ.get("AZURE_CLIENT_ID") and os.environ.get("AZURE_TENANT_ID"):
        return ProbeState.AVAILABLE
    return ProbeState.UNAVAILABLE


def probe_artifact_identity(
    release_file: Path | None,
    lock_file: Path | None,
) -> tuple[str, str]:
    """Read release and lock identity strings from files.

    Returns empty strings for missing/unreadable files. Never raises.
    """
    release_identity = ""
    lock_identity = ""

    if release_file is not None:
        try:
            release_identity = release_file.read_text(encoding="utf-8").strip()
        except Exception:
            release_identity = ""

    if lock_file is not None:
        try:
            import tomllib

            lock_content = lock_file.read_text(encoding="utf-8")
            data = tomllib.loads(lock_content)
            suite = data.get("suite", {})
            if isinstance(suite, dict):
                lock_identity = str(suite.get("release", ""))
        except Exception:
            lock_identity = ""

    return release_identity, lock_identity


def probe_ownership(install_dir: Path) -> bool:
    """Return True if the install directory already contains a suite marker."""
    marker = install_dir / ".agent-suite-installed"
    return marker.exists()


def observe_host(
    *,
    postgres_host: str = "localhost",
    postgres_port: int = 5432,
    dns_hostname: str = "suite-db.example",
    tls_host: str = "suite-db.example",
    tls_port: int = 443,
    release_file: Path | None = None,
    lock_file: Path | None = None,
    install_dir: Path | None = None,
    satisfied_operations: frozenset[SetupOperation] = frozenset(),
) -> HostObservation:
    """Run all probes and assemble a HostObservation.

    This is the main entry point for the preflight CLI. It is read-only and
    never raises — probes that fail return ``ProbeState.UNAVAILABLE``.
    """
    os_name, _ = probe_os()
    python_version = probe_python()
    powershell = probe_powershell()
    elevation = probe_elevation()
    service_account = probe_service_account()
    postgres = probe_postgres(postgres_host, postgres_port)
    dns = probe_dns(dns_hostname)
    tls = probe_tls(tls_host, tls_port)
    secret_provider = probe_secret_provider()

    release_identity, lock_identity = probe_artifact_identity(release_file, lock_file)

    ownership_conflict = False
    if install_dir is not None:
        ownership_conflict = probe_ownership(install_dir)

    return HostObservation(
        os_name=os_name,
        python_version=python_version,
        powershell=powershell,
        elevation=elevation,
        service_account=service_account,
        postgres=postgres,
        dns=dns,
        tls=tls,
        secret_provider=secret_provider,
        artifact_release_identity=release_identity,
        artifact_lock_identity=lock_identity,
        ownership_conflict=ownership_conflict,
        satisfied_operations=satisfied_operations,
    )


def format_preflight_text(report: object) -> str:
    """Format a PreflightReport as human-readable text."""
    lines: list[str] = ["agent-suite preflight"]
    state_val = report.state.value if hasattr(report, "state") else "unknown"
    lines.append(f"  State: {state_val}")
    lines.append("")
    checks = getattr(report, "checks", ())
    for check in checks:
        name = getattr(check, "name", "?")
        state = getattr(check, "state", None)
        state_val = state.value if state else "unknown"
        required = getattr(check, "required", False)
        detail = getattr(check, "detail", "")
        req_marker = " (required)" if required else ""
        lines.append(f"  {name:<22} {state_val:<14}{req_marker}")
        if detail:
            lines.append(f"    {detail}")
    return "\n".join(lines)
