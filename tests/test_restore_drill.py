"""Suite-interop CI: post-restore verification drill.

Implements Plan 001 WI-4.2 (the CI restore drill AC). Stands up an ephemeral
Postgres, provisions a project, drives one work-item through the canonical
workflow to ``done``, dumps the store with ``pg_dump``, restores it into a
fresh database, and runs ``agent-suite verify-restore`` (which shells
``regista replay``) against the restored store — proving the restored backup
is cryptographically intact, not just reachable.

A green run closes the WI-4.2 AC: "a clean restore verifies intact; the drill
runs in CI against the ephemeral store."

Gated on the component contracts existing: skips cleanly if the regista
package, ``pg_dump``/``psql`` CLI tools, or Docker (for ephemeral Postgres)
are unavailable, or if ``INTEROP_DSN`` is neither set nor satisfiable.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

_SKIP_REASON = (
    "Restore-drill prerequisites not met — need regista + pg_dump + psql + "
    "(Docker or INTEROP_DSN env). Expected until component contracts are fully "
    "landed (Plan 001 WI-4.2)."
)


def _regista_available() -> bool:
    try:
        import regista  # noqa: F401

        return True
    except ImportError:
        return False


def _regista_cli_available() -> bool:
    return shutil.which("regista") is not None


def _pg_tools_available() -> bool:
    return shutil.which("pg_dump") is not None and shutil.which("psql") is not None


def _docker_available() -> bool:
    return shutil.which("docker") is not None


def _dsn_available() -> bool:
    return bool(os.environ.get("INTEROP_DSN"))


def _can_run() -> bool:
    return (
        _regista_available()
        and _regista_cli_available()
        and _pg_tools_available()
        and (_docker_available() or _dsn_available())
    )


pytestmark = pytest.mark.skipif(not _can_run(), reason=_SKIP_REASON)


class _EphemeralPostgres:
    """Start/stop an ephemeral Postgres container for the restore drill.

    Uses port 5434 to avoid colliding with locally-installed Postgres (5432)
    or the interop/tamper tests (5433).
    """

    def __init__(self) -> None:
        self._container = f"agent-suite-restore-{uuid.uuid4().hex[:8]}"
        self._port = "5434"
        self._db = "interop"
        self._user = "interop"
        self._password = "interop_pw"

    @property
    def dsn(self) -> str:
        return f"postgresql://{self._user}:{self._password}@localhost:{self._port}/{self._db}"

    @property
    def user(self) -> str:
        return self._user

    @property
    def password(self) -> str:
        return self._password

    @property
    def host(self) -> str:
        return "localhost"

    @property
    def port(self) -> str:
        return self._port

    @property
    def db(self) -> str:
        return self._db

    def start(self) -> None:
        subprocess.run(
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
                f"{self._port}:5432",
                "postgres:16-alpine",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        self._wait_ready(timeout=30)

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


def _generate_hmac_key(path: Path) -> None:
    key_data = {
        "keys": [
            {
                "key_id": "restore-hmac-key",
                "secret": base64.b64encode(secrets.token_bytes(32)).decode(),
                "status": "active",
            }
        ]
    }
    path.write_text(json.dumps(key_data))


class _InteropDsn:
    """Wraps the DSN source and exposes host/port/db/user/password for pg_dump."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        from urllib.parse import urlparse

        parsed = urlparse(dsn)
        self.host = parsed.hostname or "localhost"
        self.port = str(parsed.port or 5432)
        self.db = parsed.path.lstrip("/") or "interop"
        self.user = parsed.username or "interop"
        self.password = parsed.password or "interop_pw"


@pytest.fixture(scope="module")
def interop_dsn() -> Generator[_InteropDsn, None, None]:
    """Provide a DSN to a Postgres instance for the restore drill.

    If ``INTEROP_DSN`` is set (e.g. by a CI service container), use that.
    Otherwise stand up an ephemeral Docker container and tear it down after.
    """
    env_dsn = os.environ.get("INTEROP_DSN")
    if env_dsn:
        yield _InteropDsn(env_dsn)
        return

    pg = _EphemeralPostgres()
    pg.start()
    try:
        yield _InteropDsn(pg.dsn)
    finally:
        pg.stop()


def _pg_env(dsn_info: _InteropDsn) -> dict[str, str]:
    """Build env for pg_dump/psql with PGPASSWORD set."""
    env = dict(os.environ)
    env["PGPASSWORD"] = dsn_info.password
    return env


def test_restore_drill_verifies_intact(interop_dsn: _InteropDsn) -> None:
    """Dump the store, restore to a fresh database, and verify-restore.

    Drives a work-item through the canonical workflow to ``done``, dumps the
    project schema with ``pg_dump``, restores it into a fresh ``restored_db``
    database on the same server, and runs ``verify_restore`` against the
    restored DSN — proving the restored backup is cryptographically intact.
    """
    import psycopg
    from regista import Regista
    import regista as regista_pkg
    from regista.testing import drop_project_schema

    project = f"restore_{uuid.uuid4().hex[:8]}"
    agent = "restore-agent"
    reviewer = "restore-reviewer"
    acceptor = "restore-acceptor"
    restored_db = f"restored_{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "hmac_keys.json"
        _generate_hmac_key(key_path)
        key_path_str = str(key_path)
        dump_path = Path(tmpdir) / "store_dump.sql"

        sub = Regista.create_project(interop_dsn.dsn, project, key_path_str)
        try:
            sub.register_workflow(regista_pkg.canonical_workflow_yaml())
            sub.register_actor_role(agent, "agent")
            sub.register_actor_role(reviewer, "human")
            sub.register_actor_role(acceptor, "human")

            agent_meta = {"role": "agent"}
            human_meta = {"role": "human"}

            wi, _ = sub.create_work_item(
                workflow_name="canonical",
                work_item_type="bug",
                actor_id=agent,
                actor_kind="agent",
                actor_metadata=agent_meta,
                custom_fields={"title": "Restore-drill test work-item"},
            )
            sub.transition(wi.work_item_id, "start", agent, actor_kind="agent", actor_metadata=agent_meta)
            sub.transition(
                wi.work_item_id, "submit_for_review", agent,
                actor_kind="agent", actor_metadata=agent_meta,
            )
            sub.transition(
                wi.work_item_id, "adversarial_pass", reviewer,
                actor_kind="human", actor_metadata=human_meta,
                payload={"review_note": "Restore drill: looks correct."},
            )
            sub.transition(
                wi.work_item_id, "accept", acceptor,
                actor_kind="human", actor_metadata=human_meta,
                payload={"review_note": "Accepting for restore drill."},
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "done"

            report = sub.replay()
            assert report.replayed_drift == 0
            assert report.halted == 0
            assert report.warnings == 0

            pg_env = _pg_env(interop_dsn)

            dump_cmd = [
                "pg_dump",
                "--host", interop_dsn.host,
                "--port", interop_dsn.port,
                "--username", interop_dsn.user,
                "--dbname", interop_dsn.db,
                "--schema", project,
                "--no-owner",
                "--no-privileges",
                "-f", str(dump_path),
            ]
            r = subprocess.run(dump_cmd, capture_output=True, text=True, env=pg_env)
            assert r.returncode == 0, (
                f"pg_dump failed (exit {r.returncode}): {r.stderr.strip()}"
            )
            assert dump_path.exists(), "pg_dump produced no dump file"

            create_cmd = [
                "psql",
                "--host", interop_dsn.host,
                "--port", interop_dsn.port,
                "--username", interop_dsn.user,
                "--dbname", interop_dsn.db,
                "-c", f'CREATE DATABASE "{restored_db}"',
            ]
            r = subprocess.run(create_cmd, capture_output=True, text=True, env=pg_env)
            assert r.returncode == 0, (
                f"CREATE DATABASE failed (exit {r.returncode}): {r.stderr.strip()}"
            )

            try:
                restore_cmd = [
                    "psql",
                    "--host", interop_dsn.host,
                    "--port", interop_dsn.port,
                    "--username", interop_dsn.user,
                    "--dbname", restored_db,
                    "-f", str(dump_path),
                ]
                r = subprocess.run(restore_cmd, capture_output=True, text=True, env=pg_env)
                assert r.returncode == 0, (
                    f"psql restore failed (exit {r.returncode}): {r.stderr.strip()}"
                )

                restored_dsn = (
                    f"postgresql://{interop_dsn.user}:{interop_dsn.password}"
                    f"@{interop_dsn.host}:{interop_dsn.port}/{restored_db}"
                )

                from agent_suite.verify_restore import ProjectVerifyStatus, verify_restore

                result = verify_restore(
                    dsn=restored_dsn,
                    projects=[project],
                )
                assert result.ok is True, (
                    f"verify-restore failed: ok={result.ok}, "
                    f"projects={[(p.project, p.status.value, p.detail) for p in result.projects]}"
                )
                assert len(result.projects) == 1
                assert result.projects[0].status is ProjectVerifyStatus.VERIFIED, (
                    f"Expected VERIFIED, got {result.projects[0].status.value}: "
                    f"{result.projects[0].detail}"
                )
                assert result.projects[0].replayed_ok >= 1
                assert result.projects[0].warnings == 0

            finally:
                drop_db_cmd = [
                    "psql",
                    "--host", interop_dsn.host,
                    "--port", interop_dsn.port,
                    "--username", interop_dsn.user,
                    "--dbname", interop_dsn.db,
                    "-c", f'DROP DATABASE IF EXISTS "{restored_db}"',
                ]
                subprocess.run(drop_db_cmd, capture_output=True, text=True, env=pg_env)

        finally:
            sub.close()
            try:
                drop_project_schema(interop_dsn.dsn, project)
            except Exception:
                conn = psycopg.connect(interop_dsn.dsn)
                try:
                    conn.autocommit = True
                    conn.execute(f'DROP SCHEMA IF EXISTS "{project}" CASCADE')
                finally:
                    conn.close()