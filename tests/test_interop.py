"""Suite-interop CI: drive one work-item across both faces to done.

Implements Plan 001 WI-2.2. Stands up an ephemeral Postgres, provisions a
project, drives one work-item through the canonical workflow — an agent files
and works it, a human reviews and accepts it — and verifies the mixed
human+agent event chain with ``regista replay``.

Gated on the component contracts existing: skips cleanly if the regista package
or Docker (for ephemeral Postgres) are unavailable, or if ``INTEROP_DSN`` is
neither set nor satisfiable. A green run is what makes a lock a release
(docs/bootstrap-contract.md §5).
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
    "Interop prerequisites not met — need regista + (Docker or INTEROP_DSN env). "
    "Expected until component contracts are fully landed (Plan 001 WI-2.2)."
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
    """Start/stop an ephemeral Postgres container for the interop test.

    Uses port 5433 to avoid colliding with a locally-installed Postgres on 5432.
    """

    def __init__(self) -> None:
        self._container = f"agent-suite-interop-{uuid.uuid4().hex[:8]}"
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
                "key_id": "interop-hmac-key",
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
    """Provide a DSN to a Postgres instance for the interop test.

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
# The interop test
# ---------------------------------------------------------------------------


def test_drive_work_item_across_both_faces_to_done(interop_dsn: str) -> None:
    """Drive one work-item through the canonical workflow to ``done``.

    An agent files and works the item (open -> in_progress -> in_review);
    a human reviewer does the adversarial pass (in_review -> in_human_review);
    a human acceptor accepts it (in_human_review -> done).

    The mixed human+agent event chain must verify with ``regista replay``
    (zero drift). This is what makes a SUITE.lock a release.
    """
    from regista import Regista
    import regista as regista_pkg
    from regista.testing import drop_project_schema

    project = f"interop_{uuid.uuid4().hex[:8]}"
    agent = "interop-agent"
    reviewer = "interop-reviewer"
    acceptor = "interop-acceptor"

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "hmac_keys.json"
        _generate_hmac_key(key_path)
        key_path_str = str(key_path)

        # --- Provision: schema + canonical workflow + actor roles ---
        sub = Regista.create_project(interop_dsn, project, key_path_str)
        try:
            sub.register_workflow(regista_pkg.canonical_workflow_yaml())
            sub.register_actor_role(agent, "agent")
            sub.register_actor_role(reviewer, "human")
            sub.register_actor_role(acceptor, "human")

            agent_meta = {"role": "agent"}
            human_meta = {"role": "human"}

            # --- Agent face: file and work the item ---
            wi, create_evt = sub.create_work_item(
                workflow_name="canonical",
                work_item_type="bug",
                actor_id=agent,
                actor_kind="agent",
                actor_metadata=agent_meta,
                custom_fields={"title": "Interop test: cross-face work-item"},
            )
            assert wi.current_state == "open"
            assert create_evt.transition == "created"

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

            # --- Human face: adversarial review pass ---
            sub.transition(
                wi.work_item_id,
                "adversarial_pass",
                reviewer,
                actor_kind="human",
                actor_metadata=human_meta,
                payload={"review_note": "Cross-lineage review: looks correct."},
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "in_human_review"

            # --- Human face: accept (-> done) ---
            sub.transition(
                wi.work_item_id,
                "accept",
                acceptor,
                actor_kind="human",
                actor_metadata=human_meta,
                payload={"review_note": "Accepting after adversarial pass."},
            )
            assert sub.get_work_item(wi.work_item_id).current_state == "done"

            # --- Verify the mixed chain ---
            report = sub.replay()
            assert report.replayed_drift == 0, (
                f"Chain drift detected: {report.replayed_drift} drift, "
                f"{report.halted} halted"
            )
            assert report.halted == 0
            assert report.replayed_ok >= 1

            # --- Assert the chain is mixed (agent + human actors) ---
            events = sub.read_events(work_item_id=wi.work_item_id)
            actor_ids = {e.actor_id for e in events}
            assert agent in actor_ids, "agent actor missing from event chain"
            assert reviewer in actor_ids or acceptor in actor_ids, (
                "human actor missing from event chain — chain is not mixed"
            )

            transitions = [e.transition for e in events]
            assert "created" in transitions
            assert "start" in transitions
            assert "submit_for_review" in transitions
            assert "adversarial_pass" in transitions
            assert "accept" in transitions

        finally:
            sub.close()
            drop_project_schema(interop_dsn, project)
