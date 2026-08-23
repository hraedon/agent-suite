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

import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Generator
from pathlib import Path

import pytest

from tests.conftest import (
    _docker_available,
    _dsn_available,
    _EphemeralPostgres,
    _fail_or_skip,
    _InteropDsn,
    _regista_available,
)

_SKIP_REASON = (
    "Restore-drill prerequisites not met — need regista + pg_dump + psql + "
    "(Docker or INTEROP_DSN env). Expected until component contracts are fully "
    "landed (Plan 001 WI-4.2)."
)


def _regista_cli_available() -> bool:
    return shutil.which("regista") is not None


def _pg_tools_available() -> bool:
    return shutil.which("pg_dump") is not None and shutil.which("psql") is not None


def _can_run() -> bool:
    return (
        _regista_available()
        and _regista_cli_available()
        and _pg_tools_available()
        and (_docker_available() or _dsn_available())
    )


# No module-level ``pytestmark = pytest.mark.skipif(not _can_run(), ...)``
# here (WI-084 item 1): that marker skips at collection time, unconditionally,
# regardless of INTEROP_REQUIRE_FACES, which silently overrode the interop
# lane's fail-closed promise. The equivalent check now lives in the
# ``interop_dsn`` fixture below (for the no-``INTEROP_DSN`` branch) and at the
# top of ``test_restore_drill_verifies_intact`` (for the case where
# ``INTEROP_DSN`` is set but regista, its CLI, or the pg tools are not — a gap
# the fixture's early return would otherwise miss), both routed through
# conftest's shared ``_fail_or_skip``.


@pytest.fixture(scope="module")
def interop_dsn() -> Generator[_InteropDsn, None, None]:
    """Provide a DSN to a Postgres instance for the restore drill.

    If ``INTEROP_DSN`` is set (e.g. by a CI service container), use that.
    Otherwise stand up an ephemeral Docker container on port 5434 and tear it
    down after the module.
    """
    env_dsn = os.environ.get("INTEROP_DSN")
    if env_dsn:
        yield _InteropDsn(env_dsn)
        return

    if not _can_run():
        _fail_or_skip(_SKIP_REASON)

    # No fixed port: _EphemeralPostgres allocates one dynamically and retries
    # on a bind race. The old ``port="5434"`` argument was removed from that
    # class when it gained dynamic allocation, so this fixture raised TypeError
    # for anyone whose environment took this branch (pg_dump present and
    # INTEROP_DSN unset) — never CI, which always sets INTEROP_DSN, which is
    # why it went unnoticed.
    pg = _EphemeralPostgres(container_name_prefix="agent-suite-restore")
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


def test_restore_drill_verifies_intact(
    interop_dsn: _InteropDsn, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Dump the store, restore to a fresh database, and verify-restore.

    Drives a work-item through the canonical workflow to ``done``, dumps the
    project schema with ``pg_dump``, restores it into a fresh ``restored_db``
    database on the same server, and runs ``verify_restore`` against the
    restored DSN — proving the restored backup is cryptographically intact.

    WI-077: provisioning now opens a v6 epoch, because regista 0.6.0 refuses an
    ordinary write before genesis. See ``conftest``'s "v6 epoch provisioning"
    section for what that entails. The drill's own claim is unchanged, and is
    strictly better exercised: what gets dumped and restored is now a chain
    whose row columns are covered by the signed envelope, so a restore that
    survives ``verify_restore`` is a stronger statement than it was under v5.
    """
    # WI-084 item 1: when ``INTEROP_DSN`` is set, the ``interop_dsn`` fixture
    # returns before checking regista/CLI/pg-tool availability at all, so a
    # missing prerequisite in that branch must be caught here instead.
    if not _can_run():
        _fail_or_skip(_SKIP_REASON)

    import psycopg
    import regista as regista_pkg
    from regista import Regista
    from regista.testing import drop_project_schema

    from tests.conftest import (
        V6_ACCEPTOR_PRINCIPAL,
        V6_AGENT_MODEL,
        V6_AGENT_MODEL_LINEAGE,
        V6_AGENT_PRINCIPAL,
        V6_BOOTSTRAP_PRINCIPAL,
        V6_REVIEWER_MODEL,
        V6_REVIEWER_MODEL_LINEAGE,
        V6_REVIEWER_PRINCIPAL,
        _generate_v6_keyset,
        _open_v6_epoch,
        _set_v6_producer_env,
    )

    project = f"restore_{uuid.uuid4().hex[:8]}"
    agent = V6_AGENT_PRINCIPAL
    reviewer = V6_REVIEWER_PRINCIPAL
    acceptor = V6_ACCEPTOR_PRINCIPAL
    actors = (agent, reviewer, acceptor)
    restored_db = f"restored_{uuid.uuid4().hex[:8]}"

    _set_v6_producer_env(
        monkeypatch,
        model=V6_AGENT_MODEL,
        model_lineage=V6_AGENT_MODEL_LINEAGE,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        keyset = _generate_v6_keyset(
            Path(tmpdir), (V6_BOOTSTRAP_PRINCIPAL, *actors)
        )
        key_path_str = keyset.path
        dump_path = Path(tmpdir) / "store_dump.sql"

        sub = Regista.create_project(interop_dsn.dsn, project, key_path_str)
        try:
            # Genesis before register_workflow: post-genesis the registration is
            # a signed event, not just a registry row (V6-ENVELOPE.md §1.9).
            _open_v6_epoch(sub, keyset, principals=actors)
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
            sub.transition(
                wi.work_item_id, "start", agent,
                actor_kind="agent", actor_metadata=agent_meta,
            )
            sub.transition(
                wi.work_item_id, "submit_for_review", agent,
                actor_kind="agent", actor_metadata=agent_meta,
            )
            _set_v6_producer_env(
                monkeypatch,
                model=V6_REVIEWER_MODEL,
                model_lineage=V6_REVIEWER_MODEL_LINEAGE,
            )
            sub.transition(
                wi.work_item_id, "adversarial_pass", reviewer,
                actor_kind="human", actor_metadata=human_meta,
                payload={"review_note": "Restore drill: looks correct."},
            )
            _set_v6_producer_env(monkeypatch)
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
            r = subprocess.run(dump_cmd, capture_output=True, text=True, env=pg_env, check=False)
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
            r = subprocess.run(create_cmd, capture_output=True, text=True, env=pg_env, check=False)
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
                r = subprocess.run(
                    restore_cmd, capture_output=True, text=True, env=pg_env, check=False
                )
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
                    key_path=key_path_str,
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
                subprocess.run(drop_db_cmd, capture_output=True, text=True, env=pg_env, check=False)

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
