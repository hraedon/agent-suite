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

import json
import uuid
from pathlib import Path

import pytest

from agent_suite.signature_assurance import bundle_verdict
from tests.conftest import (
    RegistaProject,
    _can_run,
    _fail_or_skip,
    _require_interop,
)

# ---------------------------------------------------------------------------
# Prerequisite gating — skip cleanly until the component contracts exist
# ---------------------------------------------------------------------------

_SKIP_REASON = (
    "Interop prerequisites not met — need regista + (Docker or INTEROP_DSN env). "
    "Expected until component contracts are fully landed (Plan 001 WI-2.2)."
)

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
# ``_require_interop`` is conftest's single definition of what the flag means
# (WI-084 item 1) — this module used to keep its own copy of the same check,
# which is exactly the kind of duplicated literal that can quietly drift.
_face_test_should_skip = (not _faces_available() or not _can_run()) and not _require_interop()


# ---------------------------------------------------------------------------
# The interop test
# ---------------------------------------------------------------------------


# No ``@pytest.mark.skipif(not _can_run(), ...)`` here on purpose (WI-084 item
# 1): that marker skips at collection time, unconditionally, before any
# fixture runs — so it silently overrode the interop lane's fail-closed
# promise regardless of INTEROP_REQUIRE_FACES. ``regista_project`` (via its own
# ``_regista_available()`` check and its ``interop_dsn`` dependency) already
# routes a missing prerequisite through conftest's ``_fail_or_skip``, so the
# gating lives there instead — one decision point, not two disagreeing ones.
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
    # The shared fixture uses one synthetic producer lineage throughout, so the
    # payload explicitly acknowledges the same-lineage review.
    sub.transition(
        wi.work_item_id,
        "adversarial_pass",
        reviewer,
        actor_kind="human",
        actor_metadata=human_meta,
        payload=regista_project.review_payload(
            "Cross-lineage review: looks correct."
        ),
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


def test_drive_work_item_per_principal_ed25519_to_done(
    interop_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drive one work-item to ``done`` with every event signed per-principal.

    The spine-level interop test above signs each event with the acting
    principal's own key too, but this test is the *dedicated* non-repudiation
    proof (claims ledger CL-002): it owns the store configuration that makes a
    shared secret impossible, and it verifies attribution four independent ways.

    ``strict_asymmetric=True`` is retained deliberately even though the v6
    keyset holds no HMAC key at all: the flag is the store's own refusal of an
    HMAC fallback, and asserting the property by construction (there is no such
    key) is weaker than also asking the store to refuse it.

    **WI-077 — what the 0.6.0 cutover did to this test.** The v5 version
    registered each public key in the ``principal_keys`` table via
    ``sub.principals.register`` and verified attribution against that table.
    regista 0.6.0 removes that mechanism root and branch:

    * ``principals.register`` / ``.revoke`` are refused with
      ``PRINCIPAL_KEYS_PROJECTION_WRITE_REFUSED``: the table is a projection of
      signed events, and writing it directly while emitting none is the S6
      defect the cutover exists to close (``TRUST-DOMAIN.md`` §5.9).
    * ``verify_event_principal_binding`` refuses to answer for a v6 event at
      all — §5.9 rule 1, "no verifier resolves a key from this table for a v6
      event".

    So the registry-based leg is not re-plumbed, it is **inverted**: this test
    now pins the refusal, because a future release that silently started
    answering from the projection again would be a regression in exactly the
    property 0.6.0 bought. The attribution claim itself is carried by the three
    legs that survive the cutover intact, all of which are stronger under v6:

    * per-transition signer identity — each event names the acting principal
      and is signed by *that principal's* key (the v6 writer refuses an
      actor/signer mismatch outright, ``ACTOR_SIGNER_MISMATCH``);
    * chain-level ``replay(verify_principal_binding=True)`` — zero drift, zero
      binding failures, and ``principal_binding_verified`` True, which inside a
      v6 epoch means the §5.10 acceptance-chain check actually ran (a zero
      failure count is only an affirmative claim when it did);
    * independent verification under each exported public key, and
      **non**-verification under every other principal's key — attribution is
      non-transferable.

    The revocation leg (CL-010) moved to
    ``test_adversarial_corpus.py::test_adversarial_mutation[REVOKED_KEY]``,
    which exercises the v6 mechanism (a signed
    ``principal_key_acceptance_revoked`` and its write-time refusal). It is not
    duplicated here.
    """
    # WI-084 item 1: this test only depends on ``interop_dsn``, which lets a
    # caller-supplied ``INTEROP_DSN`` short-circuit past its own
    # ``_can_run()`` check without ever importing regista — so an
    # uninstalled ``regista`` here would previously surface as a raw
    # ``ImportError`` from the ``import regista_pkg`` below rather than a
    # controlled skip/fail. Route it through the same ``_fail_or_skip`` the
    # ``regista_project`` fixture already uses, so a missing prerequisite
    # fails (not skips) under ``INTEROP_REQUIRE_FACES=1``.
    if not _can_run():
        _fail_or_skip(_SKIP_REASON)

    pytest.importorskip("nacl.signing")

    import base64

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

    agent = V6_AGENT_PRINCIPAL
    reviewer = V6_REVIEWER_PRINCIPAL
    acceptor = V6_ACCEPTOR_PRINCIPAL
    agent_meta = {"role": "agent"}
    human_meta = {"role": "human"}
    actors = (agent, reviewer, acceptor)

    project = f"ed25519_{uuid.uuid4().hex[:8]}"
    # Own keyset and own epoch rather than the shared ``regista_project``
    # fixture: this test owns the strict_asymmetric store configuration, which
    # is part of what it proves.
    _set_v6_producer_env(
        monkeypatch,
        model=V6_AGENT_MODEL,
        model_lineage=V6_AGENT_MODEL_LINEAGE,
    )
    keyset = _generate_v6_keyset(tmp_path, (V6_BOOTSTRAP_PRINCIPAL, *actors))

    # Constructed inside the try so the schema is dropped even if create_project
    # or provisioning raises (no orphaned schema).
    sub = None
    try:
        sub = Regista.create_project(
            interop_dsn, project, keyset.path, strict_asymmetric=True
        )
        _open_v6_epoch(sub, keyset, principals=actors)
        sub.register_workflow(regista_pkg.canonical_workflow_yaml())
        sub.register_actor_role(agent, "agent")
        sub.register_actor_role(reviewer, "human")
        sub.register_actor_role(acceptor, "human")

        # --- Drive the canonical workflow (agent files + works; humans review
        #     and accept), exactly as the spine-level test does ---
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
        _set_v6_producer_env(
            monkeypatch,
            model=V6_REVIEWER_MODEL,
            model_lineage=V6_REVIEWER_MODEL_LINEAGE,
        )
        sub.transition(
            wi.work_item_id, "adversarial_pass", reviewer,
            actor_kind="human", actor_metadata=human_meta,
            payload={"review_note": "cross-lineage review: looks correct."},
        )
        _set_v6_producer_env(monkeypatch)
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
            # Compared against the keyset's own key id rather than a literal, so
            # the key-id derivation stays in one place.
            assert evt.key_id == keyset.key_for(principal).key_id, (
                f"{transition_name}: key_id={evt.key_id!r}, expected "
                f"{keyset.key_for(principal).key_id!r}"
            )
        # Three distinct principals => three distinct signing keys.
        assert len({e.key_id for e in events}) == 3

        # --- (2) The registry path is REFUSED for a v6 event (§5.9 rule 1) ---
        # Pinned as a refusal, not skipped: this is the property the cutover
        # bought, and a release that quietly started answering from the
        # projection again must turn this run red.
        for e in events:
            result = sub.verify_event_principal_binding(e)
            assert result["verified"] is False, (
                f"{e.transition}: the principal_keys projection must not decide "
                f"a v6 event's key binding, but it returned {result}"
            )
            assert "v6-binding-not-decided-by-registry" in str(result["error"]), (
                f"{e.transition}: expected the named §5.9 rule 1 refusal, got "
                f"{result['error']!r}"
            )

        # --- (3) Chain-level binding: zero drift, zero failures, check RAN ---
        report = sub.replay(verify_principal_binding=True)
        assert report.replayed_drift == 0, f"drift: {report.replayed_drift}"
        assert report.halted == 0, f"halted: {report.halted}"
        assert report.chain_breaks == 0, f"chain breaks: {report.chain_breaks}"
        assert report.principal_binding_failures == 0, (
            f"binding failures: {report.principal_binding_failures}"
        )
        # Load-bearing: a zero failure count means nothing unless the check ran.
        assert report.principal_binding_verified is True, (
            "the acceptance-chain binding check did not run, so zero failures "
            "is 'not checked', not 'passed' (regista WI-223)"
        )

        # --- (4) Independent verification under the exported public keys:
        #     every event verifies under its OWN principal's key and under NO
        #     other principal's key (attribution is non-transferable) ---
        pubs = {
            k["principal_id"]: base64.b64decode(k["public_key"])
            for k in sub.export_public_keys()
        }
        # The exported material must be the key material actually on file —
        # otherwise leg (4) would verify against whatever the store chose to
        # publish rather than against the signer's real key.
        for principal in actors:
            assert pubs[principal] == keyset.key_for(principal).public_key, (
                f"exported public key for {principal} does not match the keyset"
            )
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
    interop_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    from tests.conftest import (
        V6_BOOTSTRAP_PRINCIPAL,
        _generate_v6_keyset,
        _open_v6_epoch,
        _set_v6_producer_env,
    )

    worker_id = "agent:faces-worker"
    reviewer_id = "agent:faces-reviewer"
    human_id = "human:faces-operator"
    actors = (worker_id, reviewer_id, human_id)
    project = f"faces_{uuid.uuid4().hex[:8]}"
    _set_v6_producer_env(monkeypatch)
    keyset = _generate_v6_keyset(
        tmp_path,
        (V6_BOOTSTRAP_PRINCIPAL, *actors),
        filename="faces_v6_keys.json",
    )

    # Actors carry canonical principal identity only. Model provenance is the
    # process-level producer identity and is switched truthfully before each
    # model's actions below.
    worker = AgentActor(
        actor_id=worker_id, actor_kind="agent",
        display_name="agent worker", role="agent",
    )
    reviewer = AgentActor(
        actor_id=reviewer_id, actor_kind="agent",
        display_name="cross-lineage reviewer", role="agent",
    )
    human = HumanActor(actor_id=human_id, actor_kind="human", display_name="operator")

    boot = agent_face = human_face = None
    try:
        # The real faces must run over the same v6 recipe as the spine fixture:
        # genesis first, then one signed project-local acceptance per actor.
        boot = regista.Regista.create_project(
            interop_dsn, project, keyset.path, strict_asymmetric=True
        )
        _open_v6_epoch(boot, keyset, principals=actors)
        boot.register_workflow(regista.canonical_workflow_yaml())
        boot.register_actor_role(worker_id, "agent")
        boot.register_actor_role(reviewer_id, "agent")
        boot.register_actor_role(human_id, "human")
        boot.close()
        boot = None

        # Two independent face connections, one accepted per-principal keyset.
        agent_face = RegistaFace(
            regista.Regista(
                interop_dsn, project, keyset.path, strict_asymmetric=True
            )
        )
        human_face = RegistaGateway(
            regista.Regista(
                interop_dsn, project, keyset.path, strict_asymmetric=True
            )
        )

        # --- Agent face: file + work the item ---
        _set_v6_producer_env(
            monkeypatch,
            model="claude-opus-test-worker",
            model_lineage="claude-opus",
        )
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
        _set_v6_producer_env(
            monkeypatch,
            model="glm-test-reviewer",
            model_lineage="glm",
        )
        state = agent_face.transition_breadcrumb(
            reviewer, wid, "adversarial_pass",
            payload={
                "review_note": "independent cross-lineage review: sound",
            },
        )
        assert state == "in_human_review", f"expected in_human_review, got {state!r}"

        # --- Human face: accept to done ---
        _set_v6_producer_env(monkeypatch)
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
        for handle in (boot, agent_face, human_face):
            if handle is not None:
                handle.close()
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
    interop_dsn: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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

    from tests.conftest import (
        V6_BOOTSTRAP_PRINCIPAL,
        _generate_v6_keyset,
        _open_v6_epoch,
        _set_v6_producer_env,
    )

    worker_id = "agent:faces-agent"
    reviewer_id = "agent:faces-reviewer"
    human_id = "human:faces-human"
    actors = (worker_id, reviewer_id, human_id)

    project = f"faces_ed_{uuid.uuid4().hex[:8]}"
    _set_v6_producer_env(monkeypatch)
    keyset = _generate_v6_keyset(
        tmp_path,
        (V6_BOOTSTRAP_PRINCIPAL, *actors),
        filename="faces_ed25519_keys.json",
    )

    worker = AgentActor(
        actor_id=worker_id, actor_kind="agent",
        display_name="agent worker", role="agent",
    )
    # The adversarial reviewer is deliberately a SECOND agent of a different
    # model lineage (glm vs claude) — the canonical workflow's adversarial_pass
    # enforces cross-lineage separation, not actor_kind, matching the existing
    # face-level interop test above.
    reviewer = AgentActor(
        actor_id=reviewer_id, actor_kind="agent",
        display_name="cross-lineage reviewer", role="agent",
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
            interop_dsn, project, keyset.path, strict_asymmetric=True
        )
        _open_v6_epoch(boot, keyset, principals=actors)
        boot.register_workflow(regista.canonical_workflow_yaml())
        boot.register_actor_role(worker_id, "agent")
        boot.register_actor_role(reviewer_id, "agent")
        boot.register_actor_role(human_id, "human")
        # Release the bootstrap connection before the faces open theirs; clear
        # the handle so the finally loop does not redundantly re-close it
        # (Regista.close() is idempotent, but this makes the intent explicit).
        boot.close()
        boot = None

        # Two faces + one independent verifier, all on the same per-principal
        # key file, all with HMAC fallback forbidden.
        agent_face = RegistaFace(
            regista.Regista(
                interop_dsn, project, keyset.path, strict_asymmetric=True
            )
        )
        human_face = RegistaGateway(
            regista.Regista(
                interop_dsn, project, keyset.path, strict_asymmetric=True
            )
        )
        verifier = regista.Regista(
            interop_dsn, project, keyset.path, strict_asymmetric=True
        )

        # --- Agent face: file + work the item ---
        _set_v6_producer_env(
            monkeypatch,
            model="claude-opus-test-worker",
            model_lineage="claude-opus",
        )
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
        _set_v6_producer_env(
            monkeypatch,
            model="glm-test-reviewer",
            model_lineage="glm",
        )
        state = agent_face.transition_breadcrumb(
            reviewer, wid, "adversarial_pass",
            payload={
                "review_note": "independent cross-lineage review: sound",
            },
        )
        assert state == "in_human_review", f"expected in_human_review, got {state!r}"

        # --- Human face: accept to done ---
        _set_v6_producer_env(monkeypatch)
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
            expected_key_id = keyset.key_for(principal).key_id
            assert evt.key_id == expected_key_id, (
                f"{transition_name}: key_id={evt.key_id!r}, "
                f"expected {expected_key_id}"
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

        # --- (3) The projection registry path is refused for v6 (§5.9) ---
        for e in events:
            result = verifier.verify_event_principal_binding(e)
            assert result["verified"] is False, (
                f"{e.transition}: v6 binding must not be decided by principal_keys"
            )
            assert "v6-binding-not-decided-by-registry" in str(result["error"]), (
                f"{e.transition}: expected the named §5.9 refusal, got {result}"
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
        # A zero failure count only means anything when the check ran (WI-051).
        assert binding_report.principal_binding_verified is True
        assert binding_report.principal_binding_failures == 0, (
            f"binding failures: {binding_report.principal_binding_failures}"
        )

        # --- (7) The §5 lock assertion: EVERY signature is per-actor ---
        #
        # `bootstrap-contract.md` §5 requires the mixed human+agent chain to
        # verify "with per-actor signatures". The Lane C qualification passed
        # that lock while producing "4 signatures verified, 1 unverifiable
        # (symmetric scheme)" — the human leg, signed with the shared store HMAC
        # key. "The bundle verified" is not the requirement, so assert the
        # requirement: zero unverifiable, and the check enforced (WI-052 ask 4).
        bundle_path = str(tmp_path / "interop-bundle.json")
        verifier.export_audit_bundle(bundle_path)
        payload = regista.Regista.verify_audit_bundle_offline(bundle_path)
        verdict = bundle_verdict(payload)
        # This fixture intentionally has no external trust-policy pin, so v6
        # reports genesis applicability as unresolved. That is not a symmetric
        # signature and must not be mislabeled as one. Prove the per-actor
        # property directly over every bundled event, including bootstrap and
        # key-acceptance events, then pin the one expected trust limitation.
        bundle = json.loads(Path(bundle_path).read_text(encoding="utf-8"))
        expected_keys = {
            principal: keyset.key_for(principal).key_id
            for principal in (V6_BOOTSTRAP_PRINCIPAL, *actors)
        }
        assert all(event["scheme_id"] == "ed25519" for event in bundle["events"])
        for event in bundle["events"]:
            assert event["key_id"] == expected_keys[event["actor_id"]]
        assert payload["verified"] is True
        assert payload["signatures_verified"] == payload["event_count"] - 1
        assert payload["signatures_unverifiable"] == 1
        assert len(payload["unverifiable_details"]) == 1
        assert "bootstrap_external_authority" in payload["unverifiable_details"][0]
        assert verdict.ok is False
        assert "symmetric" not in verdict.detail
    finally:
        for handle in (agent_face, human_face, verifier, boot):
            if handle is not None:
                handle.close()
        drop_project_schema(interop_dsn, project)
