"""Suite-interop CI: tamper-detection negative test.

Implements Plan 001 WI-2.3. Stands up an ephemeral Postgres, provisions a
project, drives one work-item through the canonical workflow to ``done``,
verifies the clean chain, then injects four independent tampered events
directly into the events table and confirms ``regista replay`` catches each
with a distinct, named failure.

The four tamper scenarios stay four distinct findings, but WI-077 re-anchored
two of them on regista 0.6.0's v6 envelope, where several row columns that used
to be unsigned are now committed to by the signature:

* **Mutated event body** — the ``payload`` column is edited without touching
  ``canonical_envelope`` or ``signature``.  v5: the envelope still verified and
  only the replayed state diverged (``replayed_drift > 0``).  **v6: the row is
  reconciled against the signed envelope, so the tamper is caught at
  verification** → ``halted > 0`` with ``reasons=row_field_mismatch`` naming
  ``payload``.  Strictly stronger: refused rather than noticed afterwards.

* **Spoofed ``actor_id``** — the ``actor_id`` column is changed and
  ``canonical_envelope`` is nulled so verification cannot fall back to the
  stored envelope.  Replay halts → ``halted > 0`` with
  ``reasons=envelope_absent``.  (Unchanged in kind by the cutover.)

* **Forged ``prev_event_hash``** — the hash-chain link is corrupted.  v5: an
  unsigned column, so an advisory ``warnings > 0``.  **v6: the link lives in the
  signed envelope (``chain.previous_entity_event_hash``), so it is both a
  verification failure and a structural verdict** → ``chain_breaks > 0`` and
  ``halted > 0``.  ``chain_breaks`` is what keeps this case distinct from the
  other three halts.

* **Forged ``signature``** — the ``signature`` column is replaced with
  garbage bytes (without nulling ``canonical_envelope``).  The signature no
  longer matches the stored envelope, verification fails, and replay halts →
  ``halted > 0`` with ``reasons=signature_invalid``.

Gated on the component contracts existing: skips cleanly if the regista
package or Docker (for ephemeral Postgres) are unavailable, or if
``INTEROP_DSN`` is neither set nor satisfiable.  A green run is what makes a
lock a release (docs/bootstrap-contract.md §5-6).
"""

from __future__ import annotations

from tests.conftest import RegistaProject

# ---------------------------------------------------------------------------
# Prerequisite gating — skip cleanly until the component contracts exist
# ---------------------------------------------------------------------------
#
# No module-level ``pytestmark = pytest.mark.skipif(not _can_run(), ...)``
# here (WI-084 item 1): that marker skips at collection time, unconditionally,
# before any fixture runs — so it silently overrode the interop lane's
# fail-closed promise regardless of INTEROP_REQUIRE_FACES. ``regista_project``
# (via its own ``_regista_available()`` check and its ``interop_dsn``
# dependency) already routes a missing prerequisite through conftest's
# ``_fail_or_skip``, so the gating lives there instead of being re-decided
# here, inconsistently, at collection time.


# ---------------------------------------------------------------------------
# The tamper-detection test
# ---------------------------------------------------------------------------


def test_tamper_detection(regista_project: RegistaProject) -> None:
    """Inject forged events into the store and confirm replay catches each.

    Drives a work-item through the canonical workflow to ``done``, verifies
    the clean chain, then applies four independent tamper scenarios to
    events in the Postgres events table.  Each scenario is restored before
    the next so the chain is clean between runs.

    Inside the v6 epoch all four scenarios halt replay, so "halted > 0" alone
    would no longer tell them apart. Each therefore asserts its own signature:
    ``reasons=row_field_mismatch`` naming ``payload`` (mutation),
    ``reasons=envelope_absent`` (identity spoofing), ``chain_breaks`` plus a
    mismatch naming ``prev_event_hash`` (hash-chain forgery), and
    ``reasons=signature_invalid`` (signature forgery). See the module docstring
    for what changed at the cutover and why each move is a strengthening.
    """
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier
    from psycopg.types.json import Jsonb

    sub = regista_project.sub
    project = regista_project.project
    agent = regista_project.agent
    reviewer = regista_project.reviewer
    acceptor = regista_project.acceptor
    agent_meta = regista_project.agent_meta
    human_meta = regista_project.human_meta

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

    # The shared fixture uses one producer lineage and acknowledges that fact.
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
    conn = psycopg.connect(regista_project.dsn)
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
            # WI-077 / v6: the detection signal MOVED, and strengthened. Under
            # v5 the row's ``payload`` column was outside what the stored
            # envelope committed to, so the signature still verified and the
            # tamper only showed up as replayed_drift — a *state* divergence
            # discovered after the event had been accepted. In the v6 epoch the
            # row is reconciled field-by-field against the signed canonical
            # envelope, so the mutation is caught at verification and replay
            # HALTS with reasons=row_field_mismatch naming ``payload``. The
            # reason string is asserted, not just ``halted > 0``, so this
            # scenario keeps its discriminating power against the other three.
            assert report.halted > 0, (
                f"Mutated payload not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
            detail = " ".join(e.detail or "" for e in report.entries)
            assert "row_field_mismatch" in detail, (
                f"expected a row/envelope reconciliation failure, got: {detail}"
            )
            assert "payload" in detail, (
                f"the mismatch must name the mutated column, got: {detail}"
            )
            assert report.replayed_drift == 0, (
                "the tamper is refused at verification, so replay never gets far "
                f"enough to compute drift: {report.replayed_drift}"
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
    conn = psycopg.connect(regista_project.dsn)
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
            # Distinct from the other three halts: nulling the envelope leaves
            # nothing to verify against, which is its own named reason.
            detail = " ".join(e.detail or "" for e in report.entries)
            assert "envelope_absent" in detail, (
                f"expected an absent-envelope refusal, got: {detail}"
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
    conn = psycopg.connect(regista_project.dsn)
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
            # WI-077 / v6: same movement as scenario 1, one step further. Under
            # v5 ``prev_event_hash`` was an unsigned row column, so corrupting it
            # was an advisory ``warnings`` finding. In v6 the chain link is inside
            # the signed envelope (``chain.previous_entity_event_hash``), so the
            # forgery is BOTH a verification failure (halt, reasons=
            # row_field_mismatch naming prev_event_hash) and a structural
            # chain-break verdict. ``chain_breaks`` is the field that makes this
            # scenario distinguishable from scenarios 1/2/4, all of which also
            # halt — asserting it is what keeps the four cases four cases.
            assert report.chain_breaks > 0, (
                f"Forged prev_event_hash not detected as a chain break: "
                f"chain_breaks={report.chain_breaks}, halted={report.halted}, "
                f"warnings={report.warnings}, drift={report.replayed_drift}"
            )
            assert report.halted > 0, (
                "a signed chain link that disagrees with its row must also fail "
                f"verification: halted={report.halted}"
            )
            detail = " ".join(e.detail or "" for e in report.entries)
            assert "row_field_mismatch" in detail and "prev_event_hash" in detail, (
                f"the mismatch must name the forged column, got: {detail}"
            )
            assert report.replayed_drift == 0, (
                f"Forged hash produced unexpected drift: {report.replayed_drift}"
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
    conn = psycopg.connect(regista_project.dsn)
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
            # Distinct from the other three halts: the envelope is intact and
            # reconciles with the row; only the signature over it is wrong.
            detail = " ".join(e.detail or "" for e in report.entries)
            assert "signature_invalid" in detail, (
                f"expected a signature-invalid refusal, got: {detail}"
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
