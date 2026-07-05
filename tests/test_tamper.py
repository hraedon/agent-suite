"""Suite-interop CI: tamper-detection negative test.

Implements Plan 001 WI-2.3. Stands up an ephemeral Postgres, provisions a
project, drives one work-item through the canonical workflow to ``done``,
verifies the clean chain, then injects four independent tampered events
directly into the events table and confirms ``regista replay`` catches each
with a distinct, named failure.

The four tamper scenarios map to four distinct ReplayReport categories:

* **Mutated event body** — the ``payload`` column is edited without touching
  ``canonical_envelope`` or ``signature``.  The stored envelope still
  verifies, so the signature check passes, but the replayed state
  (computed from the mutated payload) diverges from the live projection →
  ``replayed_drift > 0``.

* **Spoofed ``actor_id``** — the ``actor_id`` column is changed and
  ``canonical_envelope`` is nulled so verification cannot fall back to the
  stored envelope.  The candidate envelopes are rebuilt with the spoofed
  actor, the HMAC no longer matches, and replay halts → ``halted > 0``.

* **Forged ``prev_event_hash``** — the hash-chain link is corrupted.  The
  signature still verifies (envelope unchanged), but
  ``_verify_hash_chain`` detects the mismatch → ``warnings > 0``.

* **Forged ``signature``** — the ``signature`` column is replaced with
  garbage bytes (without nulling ``canonical_envelope``).  The signature
  no longer matches any candidate envelope, verification fails, and
  replay halts → ``halted > 0``.

Gated on the component contracts existing: skips cleanly if the regista
package or Docker (for ephemeral Postgres) are unavailable, or if
``INTEROP_DSN`` is neither set nor satisfiable.  A green run is what makes a
lock a release (docs/bootstrap-contract.md §5-6).
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

# ---------------------------------------------------------------------------
# Prerequisite gating — skip cleanly until the component contracts exist
# ---------------------------------------------------------------------------

_SKIP_REASON = (
    "Tamper-detection prerequisites not met — need regista + (Docker or "
    "INTEROP_DSN env). Expected until component contracts are fully landed "
    "(Plan 001 WI-2.3)."
)


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


pytestmark = pytest.mark.skipif(not _can_run(), reason=_SKIP_REASON)


# ---------------------------------------------------------------------------
# Ephemeral Postgres via Docker
# ---------------------------------------------------------------------------


class _EphemeralPostgres:
    """Start/stop an ephemeral Postgres container for the tamper test.

    Uses port 5433 to avoid colliding with a locally-installed Postgres on 5432.
    """

    def __init__(self) -> None:
        self._container = f"agent-suite-tamper-{uuid.uuid4().hex[:8]}"
        self._port = "5433"
        self._db = "interop"
        self._user = "interop"
        self._password = "interop_pw"

    @property
    def dsn(self) -> str:
        return f"postgresql://{self._user}:{self._password}@localhost:{self._port}/{self._db}"

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


# ---------------------------------------------------------------------------
# HMAC key generation
# ---------------------------------------------------------------------------


def _generate_hmac_key(path: Path) -> None:
    """Write a minimal HMAC key-set JSON file for the test project."""
    key_data = {
        "keys": [
            {
                "key_id": "tamper-hmac-key",
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
    """Provide a DSN to a Postgres instance for the tamper test.

    If ``INTEROP_DSN`` is set (e.g. by a CI service container), use that.
    Otherwise stand up an ephemeral Docker container and tear it down after.
    """
    env_dsn = os.environ.get("INTEROP_DSN")
    if env_dsn:
        yield env_dsn
        return

    pg = _EphemeralPostgres()
    pg.start()
    yield pg.dsn
    pg.stop()


# ---------------------------------------------------------------------------
# The tamper-detection test
# ---------------------------------------------------------------------------


def test_tamper_detection(interop_dsn: str) -> None:
    """Inject forged events into the store and confirm replay catches each.

    Drives a work-item through the canonical workflow to ``done``, verifies
    the clean chain, then applies four independent tamper scenarios to
    events in the Postgres events table.  Each scenario is restored before
    the next so the chain is clean between runs.

    The four tamper scenarios produce distinct ReplayReport categories:
    ``replayed_drift``, ``halted``, ``warnings``, and ``halted`` — proving
    the chain catches mutation, identity spoofing, hash-chain forgery,
    and signature forgery respectively.
    """
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier
    from psycopg.types.json import Jsonb
    from regista import Regista
    import regista as regista_pkg
    from regista.testing import drop_project_schema

    project = f"tamper_{uuid.uuid4().hex[:8]}"
    agent = "tamper-agent"
    reviewer = "tamper-reviewer"
    acceptor = "tamper-acceptor"

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "hmac_keys.json"
        _generate_hmac_key(key_path)
        key_path_str = str(key_path)

        sub = Regista.create_project(interop_dsn, project, key_path_str)
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
                custom_fields={"title": "Tamper-detection test work-item"},
            )
            assert wi.current_state == "open"

            sub.transition(
                wi.work_item_id, "start", agent,
                actor_kind="agent", actor_metadata=agent_meta,
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "in_progress"

            sub.transition(
                wi.work_item_id, "submit_for_review", agent,
                actor_kind="agent", actor_metadata=agent_meta,
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "in_review"

            sub.transition(
                wi.work_item_id,
                "adversarial_pass",
                reviewer,
                actor_kind="human",
                actor_metadata=human_meta,
                payload={"review_note": "Cross-lineage review: looks correct."},
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "in_human_review"

            sub.transition(
                wi.work_item_id,
                "accept",
                acceptor,
                actor_kind="human",
                actor_metadata=human_meta,
                payload={"review_note": "Accepting after adversarial pass."},
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "done"

            report = sub.replay(work_item_id=wi.work_item_id)
            assert report.replayed_drift == 0, (
                f"Clean chain has drift: {report.replayed_drift}"
            )
            assert report.halted == 0
            assert report.replayed_ok >= 1
            assert report.warnings == 0

            set_path = SQL("SET search_path TO {}, public").format(Identifier(project))

            # --- Scenario 1: Mutated event body (payload) → replayed_drift ---
            #
            # Edit the ``payload`` JSONB of the ``created`` event without
            # touching ``canonical_envelope`` or ``signature``.  The stored
            # envelope still verifies, but the replayed ``custom_fields``
            # (read from the mutated payload) diverges from the live
            # projection.
            conn = psycopg.connect(interop_dsn)
            conn.row_factory = dict_row
            try:
                conn.execute(set_path)
                row = conn.execute(
                    "SELECT payload FROM events "
                    "WHERE work_item_id = %s AND event_seq = 1",
                    [wi.work_item_id],
                ).fetchone()
                original_payload = row["payload"]
                tampered_payload = dict(original_payload)
                tampered_payload["custom_fields"] = {"title": "TAMPERED-BODY"}
                conn.execute(
                    "UPDATE events SET payload = %s "
                    "WHERE work_item_id = %s AND event_seq = 1",
                    [Jsonb(tampered_payload), wi.work_item_id],
                )
                conn.commit()
                try:
                    report = sub.replay(work_item_id=wi.work_item_id)
                    assert report.replayed_drift > 0, (
                        f"Mutated payload not detected: "
                        f"drift={report.replayed_drift}, halted={report.halted}, "
                        f"warnings={report.warnings}"
                    )
                    assert report.halted == 0, (
                        f"Mutated payload produced unexpected halt: {report.halted}"
                    )
                    assert report.warnings == 0, (
                        f"Mutated payload produced unexpected warnings: {report.warnings}"
                    )
                finally:
                    conn.execute(
                        "UPDATE events SET payload = %s "
                        "WHERE work_item_id = %s AND event_seq = 1",
                        [Jsonb(original_payload), wi.work_item_id],
                    )
                    conn.commit()
            finally:
                conn.close()

            report = sub.replay(work_item_id=wi.work_item_id)
            assert report.replayed_drift == 0
            assert report.halted == 0
            assert report.warnings == 0

            # --- Scenario 2: Spoofed actor_id → halted ---
            #
            # Change ``actor_id`` and null ``canonical_envelope`` so
            # verification cannot fall back to the stored envelope.  The
            # rebuilt candidate envelopes carry the spoofed actor, the HMAC
            # no longer matches, and replay halts.
            conn = psycopg.connect(interop_dsn)
            conn.row_factory = dict_row
            try:
                conn.execute(set_path)
                row = conn.execute(
                    "SELECT actor_id, canonical_envelope FROM events "
                    "WHERE work_item_id = %s AND event_seq = 2",
                    [wi.work_item_id],
                ).fetchone()
                original_actor_id = row["actor_id"]
                original_envelope = (
                    bytes(row["canonical_envelope"])
                    if row["canonical_envelope"] is not None
                    else None
                )
                conn.execute(
                    "UPDATE events SET actor_id = %s, canonical_envelope = NULL "
                    "WHERE work_item_id = %s AND event_seq = 2",
                    ["spoofed-actor", wi.work_item_id],
                )
                conn.commit()
                try:
                    report = sub.replay(work_item_id=wi.work_item_id)
                    assert report.halted > 0, (
                        f"Spoofed actor_id not detected: halted={report.halted}, "
                        f"drift={report.replayed_drift}, warnings={report.warnings}"
                    )
                    assert report.replayed_drift == 0, (
                        f"Spoofed actor_id produced unexpected drift: {report.replayed_drift}"
                    )
                    assert report.warnings == 0, (
                        f"Spoofed actor_id produced unexpected warnings: {report.warnings}"
                    )
                finally:
                    conn.execute(
                        "UPDATE events SET actor_id = %s, canonical_envelope = %s "
                        "WHERE work_item_id = %s AND event_seq = 2",
                        [original_actor_id, original_envelope, wi.work_item_id],
                    )
                    conn.commit()
            finally:
                conn.close()

            report = sub.replay(work_item_id=wi.work_item_id)
            assert report.replayed_drift == 0
            assert report.halted == 0
            assert report.warnings == 0

            # --- Scenario 3: Forged prev_event_hash → warnings ---
            #
            # Corrupt the per-work-item hash-chain link.  The signature
            # still verifies (envelope unchanged), but
            # ``_verify_hash_chain`` detects the mismatch and emits a
            # warning.
            conn = psycopg.connect(interop_dsn)
            conn.row_factory = dict_row
            try:
                conn.execute(set_path)
                row = conn.execute(
                    "SELECT prev_event_hash FROM events "
                    "WHERE work_item_id = %s AND event_seq = 2",
                    [wi.work_item_id],
                ).fetchone()
                original_hash = (
                    bytes(row["prev_event_hash"])
                    if row["prev_event_hash"] is not None
                    else None
                )
                conn.execute(
                    "UPDATE events SET prev_event_hash = %s "
                    "WHERE work_item_id = %s AND event_seq = 2",
                    [b"\x00" * 32, wi.work_item_id],
                )
                conn.commit()
                try:
                    report = sub.replay(work_item_id=wi.work_item_id)
                    assert report.warnings > 0, (
                        f"Forged prev_event_hash not detected: "
                        f"warnings={report.warnings}, drift={report.replayed_drift}, "
                        f"halted={report.halted}"
                    )
                    assert report.replayed_drift == 0, (
                        f"Forged hash produced unexpected drift: {report.replayed_drift}"
                    )
                    assert report.halted == 0, (
                        f"Forged hash produced unexpected halt: {report.halted}"
                    )
                finally:
                    conn.execute(
                        "UPDATE events SET prev_event_hash = %s "
                        "WHERE work_item_id = %s AND event_seq = 2",
                        [original_hash, wi.work_item_id],
                    )
                    conn.commit()
            finally:
                conn.close()

            report = sub.replay(work_item_id=wi.work_item_id)
            assert report.replayed_drift == 0
            assert report.halted == 0
            assert report.warnings == 0

            # --- Scenario 4: Forged signature → halted ---
            #
            # Replace the ``signature`` column with garbage bytes (without
            # nulling ``canonical_envelope``).  The signature no longer
            # matches any candidate envelope, verification fails, and
            # replay halts.
            conn = psycopg.connect(interop_dsn)
            conn.row_factory = dict_row
            try:
                conn.execute(set_path)
                row = conn.execute(
                    "SELECT signature FROM events "
                    "WHERE work_item_id = %s AND event_seq = 3",
                    [wi.work_item_id],
                ).fetchone()
                original_signature = bytes(row["signature"])
                forged_signature = b"\xff" * len(original_signature)
                conn.execute(
                    "UPDATE events SET signature = %s "
                    "WHERE work_item_id = %s AND event_seq = 3",
                    [forged_signature, wi.work_item_id],
                )
                conn.commit()
                try:
                    report = sub.replay(work_item_id=wi.work_item_id)
                    assert report.halted > 0, (
                        f"Forged signature not detected: halted={report.halted}, "
                        f"drift={report.replayed_drift}, warnings={report.warnings}"
                    )
                    assert report.replayed_drift == 0, (
                        f"Forged signature produced unexpected drift: {report.replayed_drift}"
                    )
                    assert report.warnings == 0, (
                        f"Forged signature produced unexpected warnings: {report.warnings}"
                    )
                finally:
                    conn.execute(
                        "UPDATE events SET signature = %s "
                        "WHERE work_item_id = %s AND event_seq = 3",
                        [original_signature, wi.work_item_id],
                    )
                    conn.commit()
            finally:
                conn.close()

            report = sub.replay(work_item_id=wi.work_item_id)
            assert report.replayed_drift == 0
            assert report.halted == 0
            assert report.warnings == 0

        finally:
            sub.close()
            drop_project_schema(interop_dsn, project)
