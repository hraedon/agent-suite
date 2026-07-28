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

import os
import uuid
from pathlib import Path

import pytest

from tests.conftest import (
    RegistaProject,
    _can_run,
    _generate_hmac_key,
)

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


# The face-level test skips locally when faces aren't importable OR the spine
# prerequisites aren't met, but in CI (INTEROP_REQUIRE_FACES=1) it must not
# skip — a missing face or missing DSN is a packaging/CI regression, not an
# optional proof. _face_test_should_skip is False in CI so the test runs and
# fails loudly via the guard inside it (faces) or the interop_dsn fixture (DSN).
_face_test_should_skip = (not _faces_available() or not _can_run()) and not _REQUIRE_FACES


# ---------------------------------------------------------------------------
# The interop test
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _can_run(), reason=_SKIP_REASON)
def test_drive_work_item_across_workflow_to_done(regista_project: RegistaProject) -> None:
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
    sub = regista_project.sub
    agent = regista_project.agent
    reviewer = regista_project.reviewer
    acceptor = regista_project.acceptor
    agent_meta = regista_project.agent_meta
    human_meta = regista_project.human_meta

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


# ---------------------------------------------------------------------------
# Per-principal Ed25519 interop — the non-repudiation proof (CL-002)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _can_run(), reason=_SKIP_REASON)
def test_drive_work_item_per_principal_ed25519_to_done(
    interop_dsn: str, tmp_path: Path
) -> None:
    """Drive one work-item to ``done`` with every event signed per-principal.

    The spine- and face-level interop tests above sign with a *shared* HMAC key:
    the chain is tamper-evident but the actor field is self-asserted — anyone
    holding the shared key could have written any event. This test closes that
    gap (claims ledger CL-002): each principal signs with its **own** Ed25519
    key, so "principal X did Y" is cryptographically provable (non-repudiation).

    The project is created with ``strict_asymmetric=True`` so the store
    **rejects any HMAC fallback** — a per-principal Ed25519 key bound to the
    acting principal is mandatory for every event. The matching public keys are
    registered in the principal_keys registry so that both verification layers
    are exercised:

    * per-event ``verify_event_principal_binding`` (signature + actor↔signer
      binding against the registry);
    * chain-level ``replay(verify_principal_binding=True)`` (zero drift, zero
      binding failures);
    * independent verification under the exported public key (and rejection
      under the wrong principal's key);
    * revocation detection — once a principal's key is revoked, its past events
      fail binding with ``key-revoked`` (also strengthens CL-010).
    """
    pytest.importorskip("nacl.signing")

    import base64

    import regista as regista_pkg
    from regista import Regista
    from regista.testing import drop_project_schema

    from tests.conftest import _generate_per_principal_ed25519_keys

    agent = "test-agent"
    reviewer = "test-reviewer"
    acceptor = "test-acceptor"
    agent_meta = {"role": "agent"}
    human_meta = {"role": "human"}

    project = f"ed25519_{uuid.uuid4().hex[:8]}"
    key_path = tmp_path / "ed25519_keys.json"
    material = _generate_per_principal_ed25519_keys(
        key_path, [agent, reviewer, acceptor]
    )

    # Constructed inside the try so the schema is dropped even if create_project
    # or registration raises (no orphaned schema).
    sub = None
    try:
        sub = Regista.create_project(
            interop_dsn, project, str(key_path), strict_asymmetric=True
        )
        sub.register_workflow(regista_pkg.canonical_workflow_yaml())
        sub.register_actor_role(agent, "agent")
        sub.register_actor_role(reviewer, "human")
        sub.register_actor_role(acceptor, "human")

        # Register each principal's public key in the registry under the SAME
        # key_id the key-set file uses, so signing and binding verification
        # agree on the key identity.
        for pid in (agent, reviewer, acceptor):
            sub.principals.register(
                pid, material[pid]["public"], scheme="ed25519",
                key_id=f"ed-{pid}", registered_by="interop-test",
            )

        # --- Drive the canonical workflow (agent files + works; humans review
        #     and accept), exactly as the spine-level HMAC test does ---
        wi, create_evt = sub.create_work_item(
            workflow_name="canonical",
            work_item_type="bug",
            actor_id=agent,
            actor_kind="agent",
            actor_metadata=agent_meta,
            custom_fields={"title": "Interop per-principal Ed25519"},
        )
        assert create_evt.scheme_id == "ed25519"
        sub.transition(
            wi.work_item_id, "start", agent,
            actor_kind="agent", actor_metadata=agent_meta,
        )
        sub.transition(
            wi.work_item_id, "submit_for_review", agent,
            actor_kind="agent", actor_metadata=agent_meta,
        )
        sub.transition(
            wi.work_item_id, "adversarial_pass", reviewer,
            actor_kind="human", actor_metadata=human_meta,
            payload={"review_note": "cross-lineage review: looks correct."},
        )
        sub.transition(
            wi.work_item_id, "accept", acceptor,
            actor_kind="human", actor_metadata=human_meta,
            payload={"review_note": "Accepting after adversarial pass."},
        )
        assert sub.get_work_item(wi.work_item_id).current_state == "done"

        events = sub.read_events(work_item_id=wi.work_item_id)
        by_transition = {e.transition: e for e in events}

        # --- (1) Every event is signed per-principal with Ed25519 ---
        assert all(e.scheme_id == "ed25519" for e in events), (
            f"schemes: {[e.scheme_id for e in events]}"
        )
        # Each transition must be signed by the principal who performed it —
        # asserted per-transition (not merely as a key_id set) so a mis-signed
        # event cannot be masked by an aggregate check.
        expected_signer = {
            "created": agent,
            "start": agent,
            "submit_for_review": agent,
            "adversarial_pass": reviewer,
            "accept": acceptor,
        }
        assert set(by_transition) >= set(expected_signer), (
            f"missing transitions: {set(expected_signer) - set(by_transition)}"
        )
        for transition_name, principal in expected_signer.items():
            evt = by_transition[transition_name]
            assert evt.actor_id == principal, (
                f"{transition_name}: actor_id={evt.actor_id!r}, "
                f"expected {principal!r}"
            )
            assert evt.key_id == f"ed-{principal}", (
                f"{transition_name}: key_id={evt.key_id!r}, "
                f"expected ed-{principal}"
            )
        # Three distinct principals => three distinct signing keys.
        assert len({e.key_id for e in events}) == 3

        # --- (2) Per-event principal binding verifies (strong, per-event) ---
        # This is the load-bearing non-repudiation check: verify_event_principal
        # _binding fails with unregistered-signer / signature-verification-failed
        # if the registry or signature is wrong, so the loop is meaningful even
        # though replay's binding pass silently skips unregistered actors.
        for e in events:
            result = sub.verify_event_principal_binding(e)
            assert result["verified"] is True, (
                f"{e.transition}: binding failed: {result['error']}"
            )
            assert result["principal_id"] == e.actor_id
            assert result["key_id"] == e.key_id, (
                f"{e.transition}: registry key_id={result['key_id']!r} != "
                f"event key_id={e.key_id!r}"
            )

        # --- (3) Chain-level replay with binding: zero drift, zero failures ---
        report = sub.replay(verify_principal_binding=True)
        assert report.replayed_drift == 0, f"drift: {report.replayed_drift}"
        assert report.halted == 0, f"halted: {report.halted}"
        assert report.principal_binding_failures == 0, (
            f"binding failures: {report.principal_binding_failures}"
        )

        # --- (4) Independent verification under the exported public keys:
        #     every event verifies under its OWN principal's key and under NO
        #     other principal's key (attribution is non-transferable) ---
        pubs = {
            k["principal_id"]: base64.b64decode(k["public_key"])
            for k in sub.export_public_keys()
        }
        for e in events:
            assert sub.verify_event_signature(
                e, public_key=pubs[e.actor_id]
            ) is True, f"{e.transition} must verify under {e.actor_id}'s key"
            for other_principal, other_key in pubs.items():
                if other_principal == e.actor_id:
                    continue
                assert sub.verify_event_signature(
                    e, public_key=other_key
                ) is False, (
                    f"{e.transition} (signed by {e.actor_id}) must NOT verify "
                    f"under {other_principal}'s key"
                )

        # --- (5) Revocation detection: revoke the acceptor's key, its past
        #     event must now fail binding with key-revoked (CL-010) ---
        accept_evt = by_transition["accept"]
        sub.principals.revoke(
            acceptor, f"ed-{acceptor}", reason="interop revocation proof"
        )
        revoked_result = sub.verify_event_principal_binding(accept_evt)
        assert revoked_result["verified"] is False, (
            "binding must fail once the signing key is revoked"
        )
        assert "key-revoked" in str(revoked_result.get("error", "")), (
            f"expected key-revoked, got: {revoked_result.get('error')}"
        )
        # Chain-level replay must also surface the revoked key as a binding
        # failure (replay-level revocation detection). The revoked entry is
        # still present in the registry, so replay's binding pass runs and
        # flags it — unlike an unregistered actor, which it silently skips.
        revoked_report = sub.replay(
            work_item_id=wi.work_item_id, verify_principal_binding=True
        )
        assert revoked_report.principal_binding_failures >= 1, (
            "replay must flag the revoked acceptor key as a binding failure"
        )
    finally:
        if sub is not None:
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
def test_drive_work_item_across_real_faces_to_done(
    interop_dsn: str, tmp_path: Path
) -> None:
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
    from agent_notes.core.actor import Actor as AgentActor
    from agent_notes.core.regista_face import RegistaFace
    from dossier.actors import Actor as HumanActor
    from dossier.gateway import RegistaGateway
    from regista.testing import drop_project_schema

    project = f"faces_{uuid.uuid4().hex[:8]}"

    key_path = tmp_path / "hmac_keys.json"
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


# ---------------------------------------------------------------------------
# Face-level per-principal Ed25519 — the shipped faces sign per-principal
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    _face_test_should_skip,
    reason=(
        "Face packages (agent-notes RegistaFace + dossier RegistaGateway) not "
        "importable — install both to run the face-level interop proof. "
        "(Set INTEROP_REQUIRE_FACES=1 to make this a hard failure in CI.)"
    ),
)
def test_drive_work_item_per_principal_ed25519_across_real_faces(
    interop_dsn: str, tmp_path: Path
) -> None:
    """Face-level companion to the spine per-principal proof (CL-002).

    The spine test proves the *store* signs and verifies per-principal. This
    test proves the two **shipped face packages** — agent-notes' ``RegistaFace``
    and dossier's ``RegistaGateway`` — produce per-principal Ed25519 signatures
    transparently: the faces only thread ``actor_id``; the spine resolves each
    actor's own Ed25519 key from the shared key-set file (``strict_asymmetric``
    forbids any HMAC fallback). A human reviewer can therefore trust that
    "agent X did Y" is non-repudiable straight from the dossier read path, with
    no CLI and no shared secret.
    """
    pytest.importorskip("nacl.signing")

    missing = _missing_face_modules()
    if missing:
        pytest.fail(
            "INTEROP_REQUIRE_FACES=1 is set but the following face modules "
            f"are not importable: {', '.join(missing)}. Install both packages "
            "(agent-notes and dossier) — or, in CI, verify the face-install step."
        )

    import base64

    import regista
    from agent_notes.core.actor import Actor as AgentActor
    from agent_notes.core.regista_face import RegistaFace
    from dossier.actors import Actor as HumanActor
    from dossier.gateway import RegistaGateway
    from regista.testing import drop_project_schema

    from tests.conftest import _generate_per_principal_ed25519_keys

    worker_id = "faces-agent"
    reviewer_id = "faces-reviewer"
    human_id = "faces-human"

    project = f"faces_ed_{uuid.uuid4().hex[:8]}"
    key_path = tmp_path / "ed25519_keys.json"
    material = _generate_per_principal_ed25519_keys(
        key_path, [worker_id, reviewer_id, human_id]
    )
    key_path_str = str(key_path)

    worker = AgentActor(
        actor_id=worker_id, actor_kind="agent",
        display_name="agent worker", role="agent", model_lineage="claude",
    )
    # The adversarial reviewer is deliberately a SECOND agent of a different
    # model lineage (glm vs claude) — the canonical workflow's adversarial_pass
    # enforces cross-lineage separation, not actor_kind, matching the existing
    # face-level interop test above.
    reviewer = AgentActor(
        actor_id=reviewer_id, actor_kind="agent",
        display_name="cross-lineage reviewer", role="agent", model_lineage="glm",
    )
    human = HumanActor(
        actor_id=human_id, actor_kind="human", display_name="operator"
    )

    # All handles are constructed and used inside this try so the schema is
    # dropped even if a constructor or a face import raises (no orphaned
    # schema). boot is closed before the faces open their own connections.
    boot = agent_face = human_face = verifier = None
    try:
        # Bootstrap: one shared per-principal project + canonical workflow + the
        # principal_keys registry (so binding verification is meaningful).
        boot = regista.Regista.create_project(
            interop_dsn, project, key_path_str, strict_asymmetric=True
        )
        boot.register_workflow(regista.canonical_workflow_yaml())
        for pid in (worker_id, reviewer_id, human_id):
            boot.principals.register(
                pid, material[pid]["public"], scheme="ed25519",
                key_id=f"ed-{pid}", registered_by="interop-test",
            )
        # Release the bootstrap connection before the faces open theirs; clear
        # the handle so the finally loop does not redundantly re-close it
        # (Regista.close() is idempotent, but this makes the intent explicit).
        boot.close()
        boot = None

        # Two faces + one independent verifier, all on the same per-principal
        # key file, all with HMAC fallback forbidden.
        agent_face = RegistaFace(
            regista.Regista(
                interop_dsn, project, key_path_str, strict_asymmetric=True
            )
        )
        human_face = RegistaGateway(
            regista.Regista(
                interop_dsn, project, key_path_str, strict_asymmetric=True
            )
        )
        verifier = regista.Regista(
            interop_dsn, project, key_path_str, strict_asymmetric=True
        )

        # --- Agent face: file + work the item ---
        wid, state = agent_face.create_breadcrumb(
            actor=worker,
            title="Interop: per-principal Ed25519 via real faces",
            description="one item, both real faces, per-principal signing",
            kind="task",
        )
        assert state == "open", f"expected open, got {state!r}"
        state = agent_face.transition_breadcrumb(worker, wid, "start")
        assert state == "in_progress", f"expected in_progress, got {state!r}"
        state = agent_face.transition_breadcrumb(worker, wid, "submit_for_review")
        assert state == "in_review", f"expected in_review, got {state!r}"

        # --- Agent face: cross-lineage adversarial review ---
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

        # --- (1) The dossier read path sees per-principal Ed25519 throughout ---
        events = human_face.history(wid)
        assert all(e.scheme_id == "ed25519" for e in events), (
            f"schemes: {[e.scheme_id for e in events]}"
        )
        by_transition = {e.transition: e for e in events}
        # Each transition signed by the principal who performed it — asserted
        # per-transition so a mis-signed event cannot hide behind set equality.
        expected_signer = {
            "created": worker_id,
            "start": worker_id,
            "submit_for_review": worker_id,
            "adversarial_pass": reviewer_id,
            "accept": human_id,
        }
        assert set(by_transition) >= set(expected_signer), (
            f"missing transitions: {set(expected_signer) - set(by_transition)}"
        )
        for transition_name, principal in expected_signer.items():
            evt = by_transition[transition_name]
            assert evt.actor_id == principal, (
                f"{transition_name}: actor_id={evt.actor_id!r}, "
                f"expected {principal!r}"
            )
            assert evt.key_id == f"ed-{principal}", (
                f"{transition_name}: key_id={evt.key_id!r}, "
                f"expected ed-{principal}"
            )
        kinds = {e.actor_kind for e in events}
        assert {"agent", "human"} <= kinds, f"chain not mixed: {sorted(kinds)}"

        # --- (2) Face-native signature + attribution proof (dossier verify_event) ---
        accept_evt = by_transition["accept"]
        info = human_face.verify_event(accept_evt)
        assert info["verified"] is True, f"verify_event: {info}"
        assert info["signature_valid"] is True
        assert info["signer_registered"] is True
        assert info["scheme"] == "ed25519"
        # dossier's verify_event resolves principal_id from the key-set file
        # export (keyed by key_id); the registry-binding proof is section (3).
        assert info["principal_id"] == human_id

        # --- (3) Registry binding proof (independent verifier handle) ---
        for e in events:
            result = verifier.verify_event_principal_binding(e)
            assert result["verified"] is True, (
                f"{e.transition}: binding failed: {result['error']}"
            )
            assert result["principal_id"] == e.actor_id
            assert result["key_id"] == e.key_id, (
                f"{e.transition}: registry key_id={result['key_id']!r} != "
                f"event key_id={e.key_id!r}"
            )

        # --- (4) Independent verification: each event verifies under its own
        #     principal's exported key and under no other principal's key ---
        pubs = {
            k["principal_id"]: base64.b64decode(k["public_key"])
            for k in verifier.export_public_keys()
        }
        for e in events:
            assert verifier.verify_event_signature(
                e, public_key=pubs[e.actor_id]
            ) is True, f"{e.transition} must verify under {e.actor_id}'s key"
            for other_principal, other_key in pubs.items():
                if other_principal == e.actor_id:
                    continue
                assert verifier.verify_event_signature(
                    e, public_key=other_key
                ) is False, (
                    f"{e.transition} (signed by {e.actor_id}) must NOT verify "
                    f"under {other_principal}'s key"
                )

        # --- (5) Chain integrity through the dossier read path (hash chain) ---
        report = human_face.integrity()
        assert report.replayed_drift == 0, f"chain drift: {report.replayed_drift}"
        assert report.halted == 0

        # --- (6) Chain-level principal-binding replay (the face's integrity()
        #     does not request binding verification, so run it on the independent
        #     verifier): zero drift, zero binding failures across the faces ---
        binding_report = verifier.replay(
            work_item_id=wid, verify_principal_binding=True
        )
        assert binding_report.replayed_drift == 0
        assert binding_report.halted == 0
        assert binding_report.principal_binding_failures == 0, (
            f"binding failures: {binding_report.principal_binding_failures}"
        )
    finally:
        for handle in (agent_face, human_face, verifier, boot):
            if handle is not None:
                handle.close()
        drop_project_schema(interop_dsn, project)
