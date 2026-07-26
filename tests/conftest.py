"""Shared fixtures and helpers for agent-suite integration tests."""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest

# ---------------------------------------------------------------------------
# Prerequisite gating — building blocks for module-level skip decisions
# ---------------------------------------------------------------------------


def _regista_available() -> bool:
    try:
        import regista  # noqa: F401

        return True
    except ImportError:
        return False


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _dsn_available() -> bool:
    return bool(os.environ.get("INTEROP_DSN"))


def _can_run() -> bool:
    return _regista_available() and (_docker_available() or _dsn_available())


# ---------------------------------------------------------------------------
# Ephemeral Postgres via Docker
# ---------------------------------------------------------------------------


def _free_port() -> str:
    """Ask the kernel for an unused TCP port on the loopback interface.

    The port is released as soon as the socket closes, so the caller must bind
    it promptly and be prepared for the race — see ``_EphemeralPostgres.start``.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


class _EphemeralPostgres:
    """Start/stop an ephemeral Postgres container for integration tests.

    The published port is allocated dynamically. A fixed port collides with
    any long-lived container the operator happens to be running (the suite's
    own ``agent-suite-smoke-pg`` sits on 5433), which failed the integration
    modules with a Docker exit-125 rather than a skip.
    """

    def __init__(self, container_name_prefix: str) -> None:
        self._container = f"{container_name_prefix}-{uuid.uuid4().hex[:8]}"
        self._port = _free_port()
        self._db = "interop"
        self._user = "interop"
        self._password = "interop_pw"

    @property
    def dsn(self) -> str:
        return (
            f"postgresql://{self._user}:{self._password}"
            f"@localhost:{self._port}/{self._db}"
        )

    def start(self, *, attempts: int = 5) -> None:
        """Run the container, re-drawing the port if the bind loses a race.

        ``_free_port`` closes the socket before Docker binds it, so another
        process can claim it in between. Docker exits 125 on that collision;
        retry with a fresh port rather than failing the whole module.
        """
        last_stderr = ""
        for attempt in range(attempts):
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--name",
                    self._container,
                    "-e",
                    f"POSTGRES_DB={self._db}",
                    "-e",
                    f"POSTGRES_USER={self._user}",
                    "-e",
                    f"POSTGRES_PASSWORD={self._password}",
                    "-p",
                    f"127.0.0.1:{self._port}:5432",
                    "postgres:16-alpine",
                ],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                self._wait_ready(timeout=30)
                return
            last_stderr = result.stderr.strip()
            # A failed `docker run --name` can still leave the name claimed.
            self.stop()
            if attempt < attempts - 1:
                self._port = _free_port()
        raise RuntimeError(
            f"Could not start {self._container} after {attempts} attempts: "
            f"{last_stderr}"
        )

    def _wait_ready(self, *, timeout: int = 30) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            r = subprocess.run(
                ["docker", "exec", self._container, "pg_isready", "-U", self._user],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                return
            time.sleep(0.5)
        raise RuntimeError(
            f"Postgres container {self._container} did not become ready within {timeout}s"
        )

    def stop(self) -> None:
        subprocess.run(
            ["docker", "rm", "-f", self._container],
            capture_output=True,
            text=True,
        )


# ---------------------------------------------------------------------------
# DSN helpers
# ---------------------------------------------------------------------------


class _InteropDsn:
    """Wrap a DSN string and expose host/port/db/user/password for pg_dump."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        parsed = urlparse(dsn)
        self.host = parsed.hostname or "localhost"
        self.port = str(parsed.port or 5432)
        self.db = parsed.path.lstrip("/") or "interop"
        self.user = parsed.username or "interop"
        self.password = parsed.password or "interop_pw"


# ---------------------------------------------------------------------------
# HMAC key generation
# ---------------------------------------------------------------------------


def _generate_hmac_key(path: Path, key_id: str = "test-hmac-key") -> None:
    """Write a minimal HMAC key-set JSON file for the test project."""
    key_data = {
        "keys": [
            {
                "key_id": key_id,
                "secret": base64.b64encode(secrets.token_bytes(32)).decode(),
                "status": "active",
            }
        ]
    }
    path.write_text(json.dumps(key_data))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def interop_dsn() -> Generator[str, None, None]:
    """Provide a DSN to a Postgres instance for integration tests.

    If ``INTEROP_DSN`` is set (e.g. by a CI service container), use that.
    Otherwise stand up an ephemeral Docker container on a dynamically
    allocated port and tear it down after the module.
    """
    env_dsn = os.environ.get("INTEROP_DSN")
    if env_dsn:
        yield env_dsn
        return

    if not _can_run():
        pytest.skip(
            "Integration prerequisites not met — need regista + Docker or INTEROP_DSN"
        )

    pg = _EphemeralPostgres(container_name_prefix="agent-suite-interop")
    pg.start()
    try:
        yield pg.dsn
    finally:
        pg.stop()


@dataclass
class RegistaProject:
    """A provisioned regista project with the canonical workflow and roles."""

    sub: Any  # regista.Regista — imported lazily to keep conftest loadable
    project: str
    key_path: str
    agent: str
    reviewer: str
    acceptor: str
    agent_meta: dict[str, str]
    human_meta: dict[str, str]
    dsn: str


@pytest.fixture
def regista_project(interop_dsn: str, tmp_path: Path) -> Generator[RegistaProject, None, None]:
    """Create a fresh regista project with the canonical workflow + 3 roles."""
    if not _regista_available():
        # In CI (INTEROP_REQUIRE_FACES=1) a missing spine is an install
        # regression, not an optional proof — fail instead of skipping, so the
        # adversarial corpus cannot silently regress to a skip (Plan 002 WI-2).
        if os.environ.get("INTEROP_REQUIRE_FACES", "").strip().lower() in {"1", "true", "yes"}:
            pytest.fail(
                "INTEROP_REQUIRE_FACES=1 is set but regista is not importable — "
                "verify the spine-install step in CI."
            )
        pytest.skip("regista is not installed")

    import regista as regista_pkg
    from regista import Regista
    from regista.testing import drop_project_schema

    project = f"conftest_{uuid.uuid4().hex[:8]}"
    agent = "test-agent"
    reviewer = "test-reviewer"
    acceptor = "test-acceptor"

    key_path = tmp_path / "hmac_keys.json"
    _generate_hmac_key(key_path)
    key_path_str = str(key_path)

    sub = Regista.create_project(interop_dsn, project, key_path_str)
    try:
        sub.register_workflow(regista_pkg.canonical_workflow_yaml())
        sub.register_actor_role(agent, "agent")
        sub.register_actor_role(reviewer, "human")
        sub.register_actor_role(acceptor, "human")

        yield RegistaProject(
            sub=sub,
            project=project,
            key_path=key_path_str,
            agent=agent,
            reviewer=reviewer,
            acceptor=acceptor,
            agent_meta={"role": "agent"},
            human_meta={"role": "human"},
            dsn=interop_dsn,
        )
    finally:
        sub.close()
        drop_project_schema(interop_dsn, project)
