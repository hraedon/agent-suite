"""Suite adversarial corpus: tamper mutations and negative scenarios.

Implements Plan 008 WI-1.3. Stands up ephemeral Postgres, provisions a project,
drives a work-item through the canonical workflow to ``done``, and applies a
parameterized set of adversarial mutations. Each mutation is restored so the
next case starts from a clean chain.

Mutations that require live regista + Postgres skip cleanly when prerequisites
are missing. The ``secret_exposure`` scenario runs without live infra using the
StubRunner pattern.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from enum import Enum
from pathlib import Path
from typing import Any, assert_never

import pytest

from tests.conftest import RegistaProject


class MutationKind(Enum):
    """Closed set of adversarial mutations testable at the suite level."""

    FORGED_ACTOR = "forged_actor"
    PAYLOAD_CHANGE = "payload_change"
    FORGED_PREV_EVENT_HASH = "forged_prev_event_hash"
    FORGED_SIGNATURE = "forged_signature"
    CHAIN_GAP = "chain_gap"
    CHAIN_REORDER = "chain_reorder"
    ANCHOR_MISMATCH = "anchor_mismatch"
    UNAUTHORIZED_PROJECT_ACCESS = "unauthorized_project_access"
    REVOKED_KEY = "revoked_key"


_INTEGRATION_MUTATIONS = list(MutationKind)

_DEFERRED_MUTATIONS = [
    "hook_omission — deferred from the parameterized integration path; "
    "test_hook_omission covers the doctor-level detection path, but "
    "live-session hook firing requires a running Claude Code session",
    "corrupted_backup — has standalone test test_corrupted_backup; not in "
    "MutationKind because it needs pg_dump/psql, not just Postgres",
    "replayed_wake_event — has standalone test test_replayed_wake_event; "
    "not in MutationKind because it exercises agent-wake's in-process dedup "
    "logic, not a Postgres-backed event chain",
    "capability_clobber — has standalone test test_capability_clobber; "
    "not in MutationKind because it exercises ACB's inspect detection path "
    "against a config file, not a Postgres-backed event chain",
]


def _drive_to_done(proj: RegistaProject) -> str:
    """Drive a work-item through the canonical workflow to ``done``."""
    sub = proj.sub
    wi, _ = sub.create_work_item(
        workflow_name="canonical",
        work_item_type="bug",
        actor_id=proj.agent,
        actor_kind="agent",
        actor_metadata=proj.agent_meta,
        custom_fields={"title": "Adversarial corpus work-item"},
    )
    sub.transition(
        wi.work_item_id, "start", proj.agent,
        actor_kind="agent", actor_metadata=proj.agent_meta,
    )
    sub.transition(
        wi.work_item_id, "submit_for_review", proj.agent,
        actor_kind="agent", actor_metadata=proj.agent_meta,
    )
    sub.transition(
        wi.work_item_id,
        "adversarial_pass",
        proj.reviewer,
        actor_kind="human",
        actor_metadata=proj.human_meta,
        payload={"review_note": "Cross-lineage review: looks correct."},
    )
    sub.transition(
        wi.work_item_id,
        "accept",
        proj.acceptor,
        actor_kind="human",
        actor_metadata=proj.human_meta,
        payload={"review_note": "Accepting after adversarial pass."},
    )
    assert sub.get_work_item(wi.work_item_id).current_state == "done"
    return wi.work_item_id


def _assert_clean_chain(sub: Any, work_item_id: str) -> None:
    report = sub.replay(work_item_id=work_item_id)
    assert report.replayed_drift == 0
    assert report.halted == 0
    assert report.warnings == 0


def _mutate_forged_actor(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        row = conn.execute(
            "SELECT actor_id, canonical_envelope FROM events "
            "WHERE work_item_id = %s AND event_seq = 2",
            [wi_id],
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
            ["spoofed-actor", wi_id],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.halted > 0, (
                f"Forged actor not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
            assert report.replayed_drift == 0
            assert report.warnings == 0
        finally:
            conn.execute(
                "UPDATE events SET actor_id = %s, canonical_envelope = %s "
                "WHERE work_item_id = %s AND event_seq = 2",
                [original_actor_id, original_envelope, wi_id],
            )
            conn.commit()
    finally:
        conn.close()


def _mutate_payload_change(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier
    from psycopg.types.json import Jsonb

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        row = conn.execute(
            "SELECT payload FROM events WHERE work_item_id = %s AND event_seq = 1",
            [wi_id],
        ).fetchone()
        original_payload = row["payload"]
        tampered_payload = dict(original_payload)
        tampered_payload["custom_fields"] = {"title": "TAMPERED-BODY"}
        conn.execute(
            "UPDATE events SET payload = %s "
            "WHERE work_item_id = %s AND event_seq = 1",
            [Jsonb(tampered_payload), wi_id],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.replayed_drift > 0, (
                f"Payload change not detected: drift={report.replayed_drift}, "
                f"halted={report.halted}, warnings={report.warnings}"
            )
            assert report.halted == 0
            assert report.warnings == 0
        finally:
            conn.execute(
                "UPDATE events SET payload = %s "
                "WHERE work_item_id = %s AND event_seq = 1",
                [Jsonb(original_payload), wi_id],
            )
            conn.commit()
    finally:
        conn.close()


def _mutate_forged_prev_event_hash(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        row = conn.execute(
            "SELECT prev_event_hash FROM events "
            "WHERE work_item_id = %s AND event_seq = 2",
            [wi_id],
        ).fetchone()
        original_hash = (
            bytes(row["prev_event_hash"])
            if row["prev_event_hash"] is not None
            else None
        )
        conn.execute(
            "UPDATE events SET prev_event_hash = %s "
            "WHERE work_item_id = %s AND event_seq = 2",
            [b"\x00" * 32, wi_id],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.warnings > 0, (
                f"Forged prev_event_hash not detected: "
                f"warnings={report.warnings}, drift={report.replayed_drift}, "
                f"halted={report.halted}"
            )
            assert report.replayed_drift == 0
            assert report.halted == 0
        finally:
            conn.execute(
                "UPDATE events SET prev_event_hash = %s "
                "WHERE work_item_id = %s AND event_seq = 2",
                [original_hash, wi_id],
            )
            conn.commit()
    finally:
        conn.close()


def _mutate_forged_signature(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        row = conn.execute(
            "SELECT signature FROM events WHERE work_item_id = %s AND event_seq = 3",
            [wi_id],
        ).fetchone()
        original_signature = bytes(row["signature"])
        forged_signature = b"\xff" * len(original_signature)
        conn.execute(
            "UPDATE events SET signature = %s "
            "WHERE work_item_id = %s AND event_seq = 3",
            [forged_signature, wi_id],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.halted > 0, (
                f"Forged signature not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
            assert report.replayed_drift == 0
            assert report.warnings == 0
        finally:
            conn.execute(
                "UPDATE events SET signature = %s "
                "WHERE work_item_id = %s AND event_seq = 3",
                [original_signature, wi_id],
            )
            conn.commit()
    finally:
        conn.close()


def _mutate_chain_gap(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        conn.execute(
            "UPDATE events SET event_seq = 999 "
            "WHERE work_item_id = %s AND event_seq = 2",
            [wi_id],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.halted > 0, (
                f"Chain gap not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
        finally:
            conn.execute(
                "UPDATE events SET event_seq = 2 "
                "WHERE work_item_id = %s AND event_seq = 999",
                [wi_id],
            )
            conn.commit()
        _assert_clean_chain(proj.sub, wi_id)
    finally:
        conn.close()


def _mutate_chain_reorder(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.rows import dict_row
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    conn.row_factory = dict_row
    try:
        conn.execute(set_path)
        rows = conn.execute(
            "SELECT event_seq, global_seq FROM events "
            "WHERE work_item_id = %s AND event_seq IN (2, 3)",
            [wi_id],
        ).fetchall()
        original_pairs = {r["event_seq"]: (r["event_seq"], r["global_seq"]) for r in rows}
        if len(original_pairs) != 2:
            pytest.skip("Need at least two events to reorder")
        orig_event_seq_2, orig_global_seq_2 = original_pairs[2]
        orig_event_seq_3, orig_global_seq_3 = original_pairs[3]
        # Swap both event_seq and global_seq using temporary negative values
        # to avoid unique-constraint collisions during the swap.
        conn.execute(
            "UPDATE events SET event_seq = %s, global_seq = %s "
            "WHERE work_item_id = %s AND event_seq = 2",
            [-orig_event_seq_2, -orig_global_seq_2, wi_id],
        )
        conn.execute(
            "UPDATE events SET event_seq = %s, global_seq = %s "
            "WHERE work_item_id = %s AND event_seq = 3",
            [-orig_event_seq_3, -orig_global_seq_3, wi_id],
        )
        conn.execute(
            "UPDATE events SET event_seq = %s, global_seq = %s "
            "WHERE work_item_id = %s AND event_seq = %s",
            [orig_event_seq_3, orig_global_seq_3, wi_id, -orig_event_seq_2],
        )
        conn.execute(
            "UPDATE events SET event_seq = %s, global_seq = %s "
            "WHERE work_item_id = %s AND event_seq = %s",
            [orig_event_seq_2, orig_global_seq_2, wi_id, -orig_event_seq_3],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.halted > 0 or report.warnings > 0, (
                f"Chain reorder not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
        finally:
            conn.execute(
                "UPDATE events SET event_seq = %s, global_seq = %s "
                "WHERE work_item_id = %s AND event_seq = %s",
                [-orig_event_seq_2, -orig_global_seq_2, wi_id, orig_event_seq_3],
            )
            conn.execute(
                "UPDATE events SET event_seq = %s, global_seq = %s "
                "WHERE work_item_id = %s AND event_seq = %s",
                [-orig_event_seq_3, -orig_global_seq_3, wi_id, orig_event_seq_2],
            )
            conn.execute(
                "UPDATE events SET event_seq = %s, global_seq = %s "
                "WHERE work_item_id = %s AND event_seq = %s",
                [orig_event_seq_2, orig_global_seq_2, wi_id, -orig_event_seq_2],
            )
            conn.execute(
                "UPDATE events SET event_seq = %s, global_seq = %s "
                "WHERE work_item_id = %s AND event_seq = %s",
                [orig_event_seq_3, orig_global_seq_3, wi_id, -orig_event_seq_3],
            )
            conn.commit()
        _assert_clean_chain(proj.sub, wi_id)
    finally:
        conn.close()


def _mutate_anchor_mismatch(proj: RegistaProject) -> None:
    """Tamper a real anchor receipt and assert the anchoring layer detects it.

    Anchor mismatch is owned by regista's anchor verification
    (``verify_anchor_receipt`` → ``verify_content_anchor``), not by ``replay``
    — replay never consults anchor receipts. The corpus therefore creates a
    real receipt (file provider over the driven chain), tampers its
    ``merkle_root``, and asserts verification fails, then passes again after
    restore.
    """
    import tempfile

    import psycopg
    from psycopg.sql import SQL, Identifier

    try:
        from regista._anchoring import FileAnchorProvider
    except ImportError:
        pytest.skip("regista has no anchoring support (pre-Plan-019 spine)")

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    with tempfile.TemporaryDirectory() as anchor_dir:
        proj.sub.anchoring.set_provider(FileAnchorProvider(anchor_dir))
        receipt = proj.sub.trigger_anchoring()
        assert receipt is not None, (
            "anchoring produced no receipt over a non-empty event chain"
        )
        assert proj.sub.verify_anchor_receipt(receipt.receipt_id) != "failed"

        set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
        conn = psycopg.connect(proj.dsn)
        try:
            conn.execute(set_path)
            original_root = bytes(receipt.merkle_root)
            conn.execute(
                "UPDATE anchor_receipts SET merkle_root = %s WHERE receipt_id = %s",
                [b"\x00" * len(original_root), receipt.receipt_id],
            )
            conn.commit()
            try:
                status = proj.sub.verify_anchor_receipt(receipt.receipt_id)
                assert status == "failed", (
                    f"Anchor mismatch not detected: verify returned {status!r}"
                )
            finally:
                conn.execute(
                    "UPDATE anchor_receipts SET merkle_root = %s WHERE receipt_id = %s",
                    [original_root, receipt.receipt_id],
                )
                conn.commit()
            assert proj.sub.verify_anchor_receipt(receipt.receipt_id) != "failed"
        finally:
            conn.close()


def _mutate_unauthorized_project_access(proj: RegistaProject) -> None:
    import psycopg
    from psycopg.sql import SQL, Identifier
    from regista import Regista
    import regista as regista_pkg
    from regista.testing import drop_project_schema

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    project_b = f"corpus_b_{uuid.uuid4().hex[:8]}"
    sub_b = Regista.create_project(proj.dsn, project_b, proj.key_path)
    try:
        sub_b.register_workflow(regista_pkg.canonical_workflow_yaml())
    finally:
        sub_b.close()

    conn = psycopg.connect(proj.dsn)
    try:
        set_b = SQL("SET search_path TO {}, public").format(Identifier(project_b))
        conn.execute(set_b)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events WHERE work_item_id = %s", [wi_id])
            count_b = cur.fetchone()[0]
            assert count_b == 0, "Cross-project read returned rows from project B schema"

        set_a = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
        conn.execute(set_a)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM events WHERE work_item_id = %s", [wi_id])
            count_a = cur.fetchone()[0]
            assert count_a > 0, "Same-project read returned no rows — setup is broken"
    finally:
        conn.close()
        drop_project_schema(proj.dsn, project_b)


def _mutate_revoked_key(proj: RegistaProject) -> None:
    """Revoke a principal's Ed25519 key and verify detection.

    Generates an Ed25519 keypair, registers the public key in the principal
    key registry, creates an Ed25519-signed event (in memory), verifies the
    principal binding passes, revokes the key, and verifies the binding now
    fails with ``key-revoked``.

    The owning layer is ``verify_event_principal_binding`` (regista Plan 026),
    not ``replay`` — replay verifies HMAC envelope integrity, not asymmetric
    principal binding.  This mirrors how ``anchor_mismatch`` tests
    ``verify_anchor_receipt`` rather than ``replay``.
    """
    import nacl.signing
    from datetime import UTC, datetime

    from regista import Event
    from regista._events import sign_event
    from regista._signing_scheme import Ed25519Scheme

    pytest.importorskip("nacl.signing")

    _drive_to_done(proj)

    signing_key = nacl.signing.SigningKey.generate()
    private_key_bytes = bytes(signing_key)
    public_key_bytes = bytes(signing_key.verify_key)

    principal_id = f"revoked-key-test-{uuid.uuid4().hex[:8]}"

    reg_result = proj.sub.principals.register(
        principal_id, public_key_bytes, scheme="ed25519",
        registered_by="test",
    )
    key_id = reg_result["key_id"]

    event_id = uuid.uuid4()
    work_item_id = uuid.uuid4()
    timestamp = datetime.now(UTC)
    payload = {"note": "Ed25519 signed test event"}
    transition = "note"

    signature, canonical_hash, envelope = sign_event(
        event_id=event_id,
        work_item_id=work_item_id,
        actor_id=principal_id,
        key_id=key_id,
        event_seq=99,
        workflow_name="canonical",
        workflow_version=1,
        timestamp=timestamp,
        transition=transition,
        payload=payload,
        key=private_key_bytes,
        scheme=Ed25519Scheme(),
        entity_kind="work_item",
        hash_alg="sha-256",
    )

    event = Event(
        event_id=event_id,
        work_item_id=work_item_id,
        event_seq=99,
        actor_id=principal_id,
        actor_kind="agent",
        actor_metadata=None,
        key_id=key_id,
        workflow_name="canonical",
        workflow_version=1,
        timestamp=timestamp,
        transition=transition,
        payload=payload,
        payload_canonical_hash=canonical_hash,
        signature=signature,
        canonical_envelope=envelope,
        scheme_id="ed25519",
        entity_kind="work_item",
        entity_id=work_item_id,
        hash_alg="sha-256",
    )

    result = proj.sub.verify_event_principal_binding(event)
    assert result["verified"] is True, (
        f"Binding should pass with active key: {result}"
    )

    proj.sub.principals.revoke(principal_id, key_id, reason="test revocation")

    result = proj.sub.verify_event_principal_binding(event)
    assert result["verified"] is False, (
        f"Binding should fail with revoked key: {result}"
    )
    assert "key-revoked" in str(result.get("error", "")), (
        f"Expected key-revoked error, got: {result}"
    )


# ---------------------------------------------------------------------------
# Secret exposure (no live infra — uses StubRunner pattern)
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _ok_json(component: str, version: str = "1.0.0") -> str:
    return json.dumps(
        {
            "component": component,
            "version": version,
            "ok": True,
            "regista": {"reachable": True, "project": "x", "chain_ok": True},
            "checks": [{"name": "regista", "status": "ok", "detail": ""}],
        }
    )


class StubRunner:
    """Returns canned `doctor --json` output per component CLI name."""

    def __init__(self, outputs: dict[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out = self._outputs[cmd[0]]
        if isinstance(out, Exception):
            raise out
        return out


class _PrefixRunner:
    """Routes stubbed output by matching command prefixes."""

    def __init__(
        self, outputs: dict[tuple[str, ...], subprocess.CompletedProcess[str] | Exception]
    ) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                if isinstance(out, Exception):
                    raise out
                return out
        return _completed(stdout='{"reachable": true, "ok": true}')


def _secret_key_file(path: Path, secret: str) -> None:
    path.write_text(
        json.dumps(
            {
                "keys": [
                    {
                        "key_id": "exposure-key",
                        "secret": secret,
                        "status": "active",
                    }
                ]
            }
        )
    )


def _bootstrap_runner() -> _PrefixRunner:
    return _PrefixRunner(
        {
            ("regista", "doctor"): _completed(stdout=_ok_json("regista")),
            ("regista", "provision"): _completed(
                stdout='[{"project": "exposure-proj", "schema_created": false}]'
            ),
            ("regista", "provision-principal"): _completed(
                stdout='{"principal_id": "suite-service", "key_id": "k1"}'
            ),
            ("regista", "secrets"): _completed(stdout="ok"),
            ("agent-notes",): _completed(
                stdout="already installed", returncode=1, stderr="already installed"
            ),
            ("cairn",): _completed(
                stdout="already installed", returncode=1, stderr="already installed"
            ),
        }
    )


# ---------------------------------------------------------------------------
# Parameterized integration test
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mutation", _INTEGRATION_MUTATIONS)
def test_adversarial_mutation(mutation: MutationKind, regista_project: RegistaProject) -> None:
    """Apply one adversarial mutation and assert the expected detection signal."""
    match mutation:
        case MutationKind.FORGED_ACTOR:
            _mutate_forged_actor(regista_project)
        case MutationKind.PAYLOAD_CHANGE:
            _mutate_payload_change(regista_project)
        case MutationKind.FORGED_PREV_EVENT_HASH:
            _mutate_forged_prev_event_hash(regista_project)
        case MutationKind.FORGED_SIGNATURE:
            _mutate_forged_signature(regista_project)
        case MutationKind.CHAIN_GAP:
            _mutate_chain_gap(regista_project)
        case MutationKind.CHAIN_REORDER:
            _mutate_chain_reorder(regista_project)
        case MutationKind.ANCHOR_MISMATCH:
            _mutate_anchor_mismatch(regista_project)
        case MutationKind.UNAUTHORIZED_PROJECT_ACCESS:
            _mutate_unauthorized_project_access(regista_project)
        case MutationKind.REVOKED_KEY:
            _mutate_revoked_key(regista_project)
        case other:
            assert_never(other)


# ---------------------------------------------------------------------------
# Secret-exposure test (no live infra)
# ---------------------------------------------------------------------------


def test_secret_exposure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``agent-suite doctor --json`` and ``bootstrap --dry-run`` never emit secrets."""
    secret = "s3cr3t-exposure-test-9x7z"
    dsn = f"postgresql://user:{secret}@suite-db.example/regista"
    key_path = tmp_path / "hmac_keys.json"
    _secret_key_file(key_path, secret)
    monkeypatch.setenv("REGISTA_DSN", dsn)
    monkeypatch.setenv("REGISTA_PROJECT", "exposure-proj")
    monkeypatch.setenv("REGISTA_KEY_PATH", str(key_path))

    suite_env = tmp_path / "suite.env"
    suite_env.write_text(f"REGISTA_DSN={dsn}\nREGISTA_KEY_PATH={key_path}\n")
    monkeypatch.setenv("AGENT_SUITE_CONFIG", str(suite_env))

    from agent_suite import bootstrap as bs
    from agent_suite import doctor
    from agent_suite.cli import main
    from agent_suite.components import COMPONENTS

    real_aggregate = doctor.aggregate

    def stub_aggregate(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault(
            "runner",
            StubRunner(
                {c.doctor_cmd[0]: _completed(stdout=_ok_json(c.ident)) for c in COMPONENTS}
            ),
        )
        kwargs.setdefault("installed", lambda _n: True)
        kwargs.setdefault("key_watch_checks", False)
        kwargs.setdefault("memory_provider_checks", False)
        return real_aggregate(*args, **kwargs)

    monkeypatch.setattr(doctor, "aggregate", stub_aggregate)

    real_bootstrap = bs.run_bootstrap

    def stub_bootstrap(*args: Any, **kwargs: Any) -> Any:
        kwargs.setdefault("runner", _bootstrap_runner())
        kwargs.setdefault("installed", lambda _n: True)
        return real_bootstrap(*args, **kwargs)

    monkeypatch.setattr(bs, "run_bootstrap", stub_bootstrap)

    main(["doctor", "--json"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret not in output, "doctor --json leaked a secret value"

    main(["bootstrap", "--dry-run", "--json"])
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret not in output, "bootstrap --dry-run leaked a secret value"


# ---------------------------------------------------------------------------
# Corrupted backup (needs pg_dump/psql — extends restore-drill pattern)
# ---------------------------------------------------------------------------


def test_corrupted_backup(regista_project: RegistaProject) -> None:
    """A corrupted backup is detected by verify_restore.

    Drives a work-item to ``done``, dumps the project schema with pg_dump,
    restores the clean dump to a fresh database, then corrupts a payload
    value via SQL UPDATE (simulating backup tampering).  Asserts
    ``verify_restore`` reports ``DRIFT_DETECTED`` — proving the restored
    backup is not silently accepted as intact.
    """
    import os
    import shutil
    import subprocess
    import tempfile

    import psycopg
    from psycopg.sql import SQL, Identifier

    from tests.conftest import _InteropDsn

    if not shutil.which("pg_dump") or not shutil.which("psql"):
        pytest.skip("pg_dump/psql not available")

    proj = regista_project
    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    dsn_info = _InteropDsn(proj.dsn)
    pg_env = dict(os.environ)
    pg_env["PGPASSWORD"] = dsn_info.password
    restored_db = f"corrupted_{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory() as tmpdir:
        dump_path = Path(tmpdir) / "store_dump.sql"

        dump_cmd = [
            "pg_dump",
            "--host", dsn_info.host,
            "--port", dsn_info.port,
            "--username", dsn_info.user,
            "--dbname", dsn_info.db,
            "--schema", proj.project,
            "--no-owner",
            "--no-privileges",
            "-f", str(dump_path),
        ]
        r = subprocess.run(dump_cmd, capture_output=True, text=True, env=pg_env)
        assert r.returncode == 0, f"pg_dump failed: {r.stderr}"

        create_cmd = [
            "psql",
            "--host", dsn_info.host,
            "--port", dsn_info.port,
            "--username", dsn_info.user,
            "--dbname", dsn_info.db,
            "-c", f'CREATE DATABASE "{restored_db}"',
        ]
        r = subprocess.run(create_cmd, capture_output=True, text=True, env=pg_env)
        assert r.returncode == 0, f"CREATE DATABASE failed: {r.stderr}"

        try:
            restore_cmd = [
                "psql",
                "--host", dsn_info.host,
                "--port", dsn_info.port,
                "--username", dsn_info.user,
                "--dbname", restored_db,
                "--set", "ON_ERROR_STOP=1",
                "-f", str(dump_path),
            ]
            r = subprocess.run(restore_cmd, capture_output=True, text=True, env=pg_env)
            assert r.returncode == 0, f"psql restore failed: {r.stderr}"

            restored_dsn = (
                f"postgresql://{dsn_info.user}:{dsn_info.password}"
                f"@{dsn_info.host}:{dsn_info.port}/{restored_db}"
            )

            set_schema = SQL("SET search_path TO {}, public").format(
                Identifier(proj.project)
            )
            conn = psycopg.connect(restored_dsn)
            try:
                conn.execute(set_schema)
                conn.execute(
                    "UPDATE events SET payload = jsonb_set("
                    "payload, '{custom_fields,title}', "
                    "'\"CORRUPTED-BACKUP-TEST\"'::jsonb) "
                    "WHERE event_seq = 1"
                )
                conn.commit()
            finally:
                conn.close()

            from agent_suite.verify_restore import ProjectVerifyStatus, verify_restore

            result = verify_restore(
                dsn=restored_dsn,
                projects=[proj.project],
                key_path=proj.key_path,
            )
            assert result.ok is False, (
                f"verify_restore should fail on corrupted backup: "
                f"ok={result.ok}, "
                f"projects={[(p.project, p.status.value, p.detail) for p in result.projects]}"
            )
            assert len(result.projects) == 1
            assert result.projects[0].status is ProjectVerifyStatus.DRIFT_DETECTED, (
                f"Expected DRIFT_DETECTED, got {result.projects[0].status.value}: "
                f"{result.projects[0].detail}"
            )
        finally:
            drop_cmd = [
                "psql",
                "--host", dsn_info.host,
                "--port", dsn_info.port,
                "--username", dsn_info.user,
                "--dbname", dsn_info.db,
                "-c", f'DROP DATABASE IF EXISTS "{restored_db}"',
            ]
            r = subprocess.run(drop_cmd, capture_output=True, text=True, env=pg_env)
            if r.returncode != 0:
                import warnings
                warnings.warn(
                    f"Failed to drop restored database {restored_db!r}: {r.stderr.strip()}",
                    stacklevel=2,
                )


# ---------------------------------------------------------------------------
# Hook omission (needs cairn — doctor-level detection path)
# ---------------------------------------------------------------------------


def test_hook_omission(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """cairn doctor detects missing hooks in the Claude settings file.

    Writes a settings.json with all cairn hook events present, verifies
    ``_check_harness_wired`` does not report a failure, removes one hook
    event, and verifies the doctor reports the omission as a failure.

    This covers the doctor-level detection path: the live-session hook
    firing path requires a running Claude Code session and is not testable
    in CI.
    """
    try:
        from cairn._doctor import _check_harness_wired
        from cairn._install import HOOK_EVENTS
    except ImportError:
        pytest.skip("cairn (agent-provenance) not available")

    def _make_hook_entry(event_name: str) -> dict[str, Any]:
        return {
            "hooks": [
                {
                    "type": "command",
                    "command": f"python3 -m cairn._claude_hook {HOOK_EVENTS[event_name]}",
                }
            ]
        }

    settings: dict[str, Any] = {
        "hooks": {event: [_make_hook_entry(event)] for event in HOOK_EVENTS},
        "env": {
            "REGISTA_DSN": "postgresql://user:pass@localhost/db",
            "CAIRN_PROJECT": "test-project",
        },
    }
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps(settings))
    monkeypatch.setenv("CAIRN_CLAUDE_SETTINGS", str(settings_path))

    result = _check_harness_wired(None)
    assert result["status"] != "fail", (
        f"Doctor should pass with all hooks present: {result}"
    )

    removed_event = next(iter(HOOK_EVENTS))
    del settings["hooks"][removed_event]
    settings_path.write_text(json.dumps(settings))

    result = _check_harness_wired(None)
    assert result["status"] == "fail", (
        f"Doctor should fail with missing hook: {result}"
    )
    assert "missing hooks" in result["detail"], (
        f"Expected 'missing hooks' in detail, got: {result}"
    )
    assert removed_event in result["detail"], (
        f"Expected {removed_event!r} in detail, got: {result['detail']!r}"
    )


# ---------------------------------------------------------------------------
# Replayed wake event (needs agent-wake — dedup logic, in-process)
# ---------------------------------------------------------------------------


def test_replayed_wake_event() -> None:
    """agent-wake's ingress rejects a duplicate ``event_id`` (replay protection).

    Exercises the ``Dedupe`` class from ``agent_waked.ingest`` directly — the
    in-memory FIFO dedup window that the HTTP ingress uses to reject replayed
    wake events.  A full end-to-end test would POST to the running daemon, but
    the dedup logic itself is pure and testable in-process (mirrors how
    ``test_hook_omission`` calls ``_check_harness_wired`` directly instead of
    spawning the full doctor).
    """
    try:
        from agent_waked.ingest import Dedupe
    except ImportError:
        pytest.skip("agent-wake not available")

    dedupe = Dedupe()
    event_id = str(uuid.uuid4())

    # First submission: not a duplicate → accepted.
    assert dedupe.check(event_id) is False, (
        "First submission of event_id should not be flagged as a duplicate"
    )

    # Replayed event_id: duplicate → rejected.
    assert dedupe.check(event_id) is True, (
        "Replayed event_id should be detected as a duplicate"
    )

    # A different event_id: not a duplicate → accepted.
    assert dedupe.check(str(uuid.uuid4())) is False, (
        "A different event_id should not be flagged as a duplicate"
    )


# ---------------------------------------------------------------------------
# Capability clobber (needs agent-capability-broker — inspect detection path)
# ---------------------------------------------------------------------------


def test_capability_clobber(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ACB detects a clobbered capability via ``inspect`` returning ``PRESENT_BROKEN``.

    Writes an opencode config with a working, pinned Playwright MCP server and
    browser binaries present, verifies ``E2eProvider.inspect`` returns
    ``PRESENT_OK``, then clobbers the config (disables the server) and verifies
    ``inspect`` now returns ``PRESENT_BROKEN`` — proving the doctor-level
    detection path catches a rogue/clobbered capability.
    """
    try:
        from agent_capability_broker.adapters import OpencodeAdapter
        from agent_capability_broker.model import Capability, Status
        from agent_capability_broker.providers import E2eProvider
    except ImportError:
        pytest.skip("agent-capability-broker not available")

    # Browser binaries present so inspect does not fail on the missing-binary axis.
    cache = tmp_path / "ms-playwright"
    (cache / "chromium-1223").mkdir(parents=True)
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(cache))

    config_path = tmp_path / "opencode.json"
    config_path.write_text(json.dumps({
        "mcp": {
            "playwright": {
                "type": "local",
                "enabled": True,
                "command": ["npx", "-y", "@playwright/mcp@1.43.0", "--headless"],
            }
        }
    }))

    adapter = OpencodeAdapter(config_path=config_path)
    cap = Capability(
        id="e2e:chromium",
        provider="e2e",
        harnesses=("opencode",),
        options={"pin": "1.43.0"},
    )

    # Baseline: capability is present and OK.
    verdict = E2eProvider().inspect(cap, "opencode", adapter)
    assert verdict.status is Status.PRESENT_OK, (
        f"Capability should be PRESENT_OK with valid config: {verdict}"
    )

    # Clobber: disable the Playwright server (rogue edit).
    config_path.write_text(json.dumps({
        "mcp": {
            "playwright": {
                "type": "local",
                "enabled": False,
                "command": ["npx", "-y", "@playwright/mcp@1.43.0", "--headless"],
            }
        }
    }))

    # Detection: inspect now reports PRESENT_BROKEN.
    verdict = E2eProvider().inspect(cap, "opencode", adapter)
    assert verdict.status is Status.PRESENT_BROKEN, (
        f"Clobbered capability should be detected as PRESENT_BROKEN: {verdict}"
    )
    assert "disabled" in verdict.detail, (
        f"Expected 'disabled' in detail, got: {verdict.detail}"
    )


# ---------------------------------------------------------------------------
# Deferred-mutations registry guard (prevents silent regression)
# ---------------------------------------------------------------------------

_EXPECTED_DEFERRED = {
    "hook_omission",
    "corrupted_backup",
    "replayed_wake_event",
    "capability_clobber",
}


def test_deferred_mutations_registry() -> None:
    """The _DEFERRED_MUTATIONS list must name every known deferred mutation.

    Without this guard, someone could silently delete an entry from the list
    and the mutation would vanish from the corpus without a trace. The test
    fails if any expected name is missing, ensuring that a deferred mutation
    is either implemented (and moved to MutationKind) or explicitly listed.
    """
    deferred_names = {entry.split(" — ")[0] for entry in _DEFERRED_MUTATIONS}
    assert deferred_names == _EXPECTED_DEFERRED, (
        f"_DEFERRED_MUTATIONS and _EXPECTED_DEFERRED have diverged: "
        f"extra in _DEFERRED_MUTATIONS: {deferred_names - _EXPECTED_DEFERRED}, "
        f"extra in _EXPECTED_DEFERRED: {_EXPECTED_DEFERRED - deferred_names}"
    )
