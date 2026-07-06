"""Suite-interop CI: drive one work-item across both faces to done.

Implements Plan 001 WI-2.2. Two levels of assurance:

1. **Spine-level** (``test_drive_work_item_across_workflow_to_done``): drives
   regista's canonical workflow directly, labelling the transitions "agent
   face" / "human face". Proves the *workflow* composes — always runnable
   wherever regista is installed.
2. **Face-level** (``test_drive_work_item_across_real_faces_to_done``): drives
   the **actual** face packages — agent-notes' ``RegistaFace`` and dossier's
   ``RegistaGateway`` — over one shared regista project. This is the proof the
   blueprint §2.2 asks for: that the two real client packages interoperate, not
   merely that the spine does. Runs whenever both faces are importable.

Both stand up an ephemeral Postgres, provision a project, drive one work-item
through the canonical workflow — an agent files and works it, a human reviews
and accepts it — and verify the mixed human+agent event chain with
``regista replay``.

**Skip vs. fail gating (Plan 002):** each test carries its own skip guard (no
module-level ``pytestmark``) so the face-level test's require logic is
independent of the spine-level prerequisites. Locally, both tests skip cleanly
when their prerequisites aren't met. In CI, ``INTEROP_REQUIRE_FACES=1`` makes
the face-level test **fail** (not skip) when the face packages aren't
importable — closing the "skip looks like pass" hole so a face-packaging
regression surfaces as a red run, not a silent skip. A green run is what
makes a lock a release (docs/bootstrap-contract.md §5).
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

# When set (CI), the face-level interop test must not skip — it fails instead,
# so a face-packaging regression is a red run, not a silent skip (Plan 002 WI-2).
_REQUIRE_FACES = os.environ.get("INTEROP_REQUIRE_FACES", "").strip().lower() in {
    "1", "true", "yes",
}


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


# The exact modules the face-level test imports — checking these (not a subset)
# ensures the availability probe and the test body cannot drift apart.
_FACE_MODULES = [
    "agent_notes.core.actor",
    "agent_notes.core.regista_face",
    "dossier.actors",
    "dossier.gateway",
]


def _missing_face_modules() -> list[str]:
    """Return face modules that cannot be imported, or ``[]`` if all are available."""
    missing: list[str] = []
    for mod in _FACE_MODULES:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return missing


def _faces_available() -> bool:
    """True when all face modules the test needs are importable.

    Checks the exact imports the test body uses (not a subset) so that a broken
    ``agent_notes.core.actor`` or ``dossier.actors`` is caught here, not as a
    raw ``ImportError`` mid-test.
    """
    return not _missing_face_modules()


def _can_run() -> bool:
    return _regista_available() and (_docker_available() or _dsn_available())


# The face-level test skips locally when faces aren't importable OR the spine
# prerequisites aren't met, but in CI (INTEROP_REQUIRE_FACES=1) it must not
# skip — a missing face or missing DSN is a packaging/CI regression, not an
# optional proof. _face_test_should_skip is False in CI so the test runs and
# fails loudly via the guard inside it (faces) or the interop_dsn fixture (DSN).
_face_test_should_skip = (not _faces_available() or not _can_run()) and not _REQUIRE_FACES


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


@pytest.mark.skipif(not _can_run(), reason=_SKIP_REASON)
def test_drive_work_item_across_workflow_to_done(interop_dsn: str) -> None:
    """Spine-level: drive one work-item through the canonical workflow to ``done``.

    Drives regista directly (no face packages), labelling the transitions by the
    face that would own them: an agent files and works the item
    (open -> in_progress -> in_review); a human reviewer does the adversarial
    pass (in_review -> in_human_review); a human acceptor accepts it
    (in_human_review -> done).

    The mixed human+agent event chain must verify with ``regista replay``
    (zero drift). The companion ``test_drive_work_item_across_real_faces_to_done``
    proves the actual face packages compose over the same workflow. This is what
    makes a SUITE.lock a release.
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


# ---------------------------------------------------------------------------
# Face-level interop — the real client packages, not just the spine
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    _face_test_should_skip,
    reason=(
        "Face packages (agent-notes RegistaFace + dossier RegistaGateway) not "
        "importable — install both to run the face-level interop proof. "
        "(Set INTEROP_REQUIRE_FACES=1 to make this a hard failure in CI.)"
    ),
)
def test_drive_work_item_across_real_faces_to_done(interop_dsn: str) -> None:
    """Face-level: drive ONE work-item across the two real face packages to ``done``.

    Unlike the spine-level test, this constructs agent-notes' ``RegistaFace`` and
    dossier's ``RegistaGateway`` — the actual client packages the suite ships —
    over one shared regista project, and drives a single work-item through the
    canonical workflow with each face owning its half:

      * agent face (agent-notes): file the item, start it, submit for review;
      * a cross-lineage agent reviewer passes the adversarial gate;
      * human face (dossier): accept it to ``done``;
      * read the mixed agent+human chain back through dossier's read path and
        verify the regista hash chain (zero drift).

    Promotes ``dossier/scripts/convergence_e2e_proof.py`` (previously a manual
    proof, last run 2026-06-29) into a gated CI test. This is the proof the
    blueprint §2.2 requires: the two real faces interoperate, not just the spine.
    """
    missing = _missing_face_modules()
    if missing:
        pytest.fail(
            "INTEROP_REQUIRE_FACES=1 is set but the following face modules "
            f"are not importable: {', '.join(missing)}. Install both packages "
            "(agent-notes and dossier) — or, in CI, verify the face-install step."
        )

    import regista
    from regista.testing import drop_project_schema

    from agent_notes.core.actor import Actor as AgentActor
    from agent_notes.core.regista_face import RegistaFace
    from dossier.actors import Actor as HumanActor
    from dossier.gateway import RegistaGateway

    project = f"faces_{uuid.uuid4().hex[:8]}"

    with tempfile.TemporaryDirectory() as tmpdir:
        key_path = Path(tmpdir) / "hmac_keys.json"
        _generate_hmac_key(key_path)
        key_path_str = str(key_path)

        # Bootstrap: one shared project + the canonical workflow.
        boot = regista.Regista.create_project(interop_dsn, project, key_path_str)
        boot.register_workflow(regista.canonical_workflow_yaml())
        boot.close()

        # Two independent faces, two independent connections, ONE project.
        agent_face = RegistaFace(regista.Regista(interop_dsn, project, key_path_str))
        human_face = RegistaGateway(regista.Regista(interop_dsn, project, key_path_str))

        # Two agents of different model lineage + one human.
        worker = AgentActor(
            actor_id="faces-agent", actor_kind="agent",
            display_name="agent worker", role="agent", model_lineage="claude",
        )
        reviewer = AgentActor(
            actor_id="faces-reviewer", actor_kind="agent",
            display_name="cross-lineage reviewer", role="agent", model_lineage="glm",
        )
        human = HumanActor(actor_id="faces-human", actor_kind="human", display_name="operator")

        try:
            # --- Agent face: file + work the item ---
            wid, state = agent_face.create_breadcrumb(
                actor=worker,
                title="Interop: cross-face work-item via real faces",
                description="one item, both real faces",
                kind="task",
            )
            assert state == "open", f"expected open, got {state!r}"
            state = agent_face.transition_breadcrumb(worker, wid, "start")
            assert state == "in_progress", f"expected in_progress, got {state!r}"
            state = agent_face.transition_breadcrumb(worker, wid, "submit_for_review")
            assert state == "in_review", f"expected in_review, got {state!r}"

            # --- Agent face: cross-lineage adversarial review (reviewer != worker) ---
            state = agent_face.transition_breadcrumb(
                reviewer, wid, "adversarial_pass",
                payload={"review_note": "independent cross-lineage review: sound"},
            )
            assert state == "in_human_review", f"expected in_human_review, got {state!r}"

            # --- Human face: accept to done ---
            human_face.transition(
                actor=human, work_item_id=wid, transition_name="accept",
                payload={"review_note": "human sign-off"},
            )
            item = human_face.get_issue(wid)
            assert item is not None
            assert item.current_state == "done", f"expected done, got {item.current_state!r}"
            assert item.workflow_name == "canonical"

            # --- Read the mixed chain back through dossier's read path ---
            events = human_face.history(wid)
            kinds = {e.actor_kind for e in events}
            assert {"agent", "human"} <= kinds, f"chain not mixed: {sorted(kinds)}"
            actor_ids = {e.actor_id for e in events}
            assert {worker.actor_id, reviewer.actor_id, human.actor_id} <= actor_ids

            # --- Verify the hash chain (zero drift) ---
            report = human_face.integrity()
            assert report.replayed_drift == 0, f"chain drift: {report.replayed_drift}"
            assert report.halted == 0
            assert report.replayed_ok >= 1
        finally:
            agent_face.close()
            human_face.close()
            drop_project_schema(interop_dsn, project)
