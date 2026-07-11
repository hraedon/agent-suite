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


_INTEGRATION_MUTATIONS = list(MutationKind)

_DEFERRED_MUTATIONS = [
    "revoked_key — requires regista Plan 026 principal key registry at suite level",
    "hook_omission — requires agent-provenance hook wiring in a live session",
    "replayed_wake_event — requires agent-wake component",
    "capability_clobber — requires agent-capability-broker component",
    "corrupted_backup — requires live pg_dump/restore cycle (partially in test_restore_drill)",
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
    import psycopg
    from psycopg.sql import SQL, Identifier

    wi_id = _drive_to_done(proj)
    _assert_clean_chain(proj.sub, wi_id)

    set_path = SQL("SET search_path TO {}, public").format(Identifier(proj.project))
    conn = psycopg.connect(proj.dsn)
    try:
        conn.execute(set_path)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = %s AND table_name = 'anchor_receipts')",
                [proj.project],
            )
            has_anchor = cur.fetchone()[0]
        if not has_anchor:
            pytest.skip("anchor_receipts table not present — anchoring unavailable")

        with conn.cursor() as cur:
            cur.execute("SELECT merkle_root FROM anchor_receipts LIMIT 1")
            row = cur.fetchone()
        if row is None:
            pytest.skip("anchor_receipts is empty — no anchor to tamper")
        original_root = bytes(row[0])
        conn.execute(
            "UPDATE anchor_receipts SET merkle_root = %s "
            "WHERE merkle_root = %s",
            [b"\x00" * len(original_root), original_root],
        )
        conn.commit()
        try:
            report = proj.sub.replay(work_item_id=wi_id)
            assert report.halted > 0 or report.warnings > 0, (
                f"Anchor mismatch not detected: halted={report.halted}, "
                f"drift={report.replayed_drift}, warnings={report.warnings}"
            )
        finally:
            conn.execute(
                "UPDATE anchor_receipts SET merkle_root = %s WHERE merkle_root = %s",
                [original_root, b"\x00" * len(original_root)],
            )
            conn.commit()
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
