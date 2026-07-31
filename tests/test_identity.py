"""Unit tests for the per-user identity lifecycle — joining and leaving.

All tests use stubbed runners and installed checks — no live regista, no live
store (AGENTS.md: no live infra in CI). The regista verbs are stubbed at the
argv level so the tests also pin the exact commands the suite shells.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_suite.identity import (
    IdentityAction,
    IdentityOutcome,
    IdentityStep,
    aggregate_outcome,
    format_result,
    outcome_is_success,
    overlay_values,
    render_overlay,
    run_user_offboarding,
    run_user_onboarding,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


class StubRegista:
    """Answer regista principal verbs from canned data, recording every call."""

    def __init__(
        self,
        *,
        enroll: subprocess.CompletedProcess[str] | Exception | None = None,
        active_keys: list[dict[str, object]] | None = None,
        revoke: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
        list_result: subprocess.CompletedProcess[str] | None = None,
        delete: Callable[[str], subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self._enroll = enroll
        self._active_keys = active_keys or []
        self._revoke = revoke
        self._list_result = list_result
        self._delete = delete
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        if "secrets" in cmd:
            ref = cmd[cmd.index("--ref") + 1]
            if self._delete is not None:
                return self._delete(ref)
            return _completed(stdout=json.dumps({"ref": ref, "outcome": "deleted"}))
        # argv is `regista --json [--hmac-key-path P] principal <verb> ...`
        verb = cmd[cmd.index("principal") + 1] if "principal" in cmd else ""
        if verb == "enroll":
            if isinstance(self._enroll, Exception):
                raise self._enroll
            assert self._enroll is not None, "enroll not stubbed"
            return self._enroll
        if verb == "list":
            if self._list_result is not None:
                return self._list_result
            return _completed(stdout=json.dumps(self._active_keys))
        if verb == "revoke":
            key_id = cmd[cmd.index("--key-id") + 1]
            if self._revoke is not None:
                return self._revoke(key_id)
            return _completed(stdout=json.dumps({"key_id": key_id}))
        raise AssertionError(f"unexpected regista command: {cmd}")


def _installed(present: bool = True) -> Callable[[str], bool]:
    return lambda _cli: present


ENROLLED = _completed(
    stdout=json.dumps(
        {
            "principal_id": "alice",
            "key_id": "key-1",
            "fingerprint": "ff" * 16,
            "scheme": "ed25519",
            "already_existed": False,
            "secret_backend": "vault",
        }
    )
)

ALREADY_ENROLLED = _completed(
    stdout=json.dumps(
        {
            "principal_id": "alice",
            "key_id": "key-1",
            "fingerprint": "ff" * 16,
            "scheme": "ed25519",
            "already_existed": True,
            "secret_backend": "vault",
        }
    )
)


def _users_file(tmp_path, username: str = "alice", **extra: object) -> Path:
    """A dossier local-backend users file — the identity source WI-052 binds."""
    entry: dict[str, object] = {
        "stable_id": "4814fec5-7b84-4f61-ae43-99a91dc76a63",
        "username": username,
        "display_name": username.title(),
        "password": "scrypt:redacted",
    }
    entry.update(extra)
    path = tmp_path / "users.json"
    path.write_text(json.dumps([entry], indent=2))
    return path


def _env(users: Path | None = None) -> dict[str, str]:
    """A resolved suite environment; tests never read the developer's own."""
    return {} if users is None else {"DOSSIER_USERS_PATH": str(users)}


def _step(result, name: str) -> IdentityStep:
    return next(s for s in result.steps if s.name == name)


# ---------------------------------------------------------------------------
# Outcome algebra
# ---------------------------------------------------------------------------


def test_aggregate_outcome_takes_the_worst_step() -> None:
    steps = (
        IdentityStep("a", IdentityOutcome.DONE, ""),
        IdentityStep("b", IdentityOutcome.MANUAL, ""),
        IdentityStep("c", IdentityOutcome.ALREADY_DONE, ""),
    )
    assert aggregate_outcome(steps) is IdentityOutcome.MANUAL


def test_aggregate_outcome_failed_beats_manual() -> None:
    steps = (
        IdentityStep("a", IdentityOutcome.MANUAL, ""),
        IdentityStep("b", IdentityOutcome.FAILED, ""),
    )
    assert aggregate_outcome(steps) is IdentityOutcome.FAILED


@pytest.mark.parametrize("outcome", list(IdentityOutcome))
def test_every_outcome_is_classified(outcome: IdentityOutcome) -> None:
    """assert_never guards the dispatch; this proves no member is unreachable."""
    assert isinstance(outcome_is_success(outcome), bool)


def test_manual_is_not_success() -> None:
    """The whole point of MANUAL: automation must not read it as done."""
    assert outcome_is_success(IdentityOutcome.MANUAL) is False


# ---------------------------------------------------------------------------
# The overlay
# ---------------------------------------------------------------------------


def test_overlay_values_omit_unset_optionals() -> None:
    assert overlay_values("alice") == {"REGISTA_PRINCIPAL_ID": "alice"}


def test_overlay_values_carry_project_and_projects() -> None:
    values = overlay_values("alice", project="proj", projects=("proj", "other"))
    assert values["AGENT_NOTES_PROJECT"] == "proj"
    assert values["DOSSIER_PROJECTS"] == "proj,other"


def test_render_overlay_is_stable() -> None:
    values = {"B": "2", "A": "1"}
    assert render_overlay(values) == render_overlay(dict(reversed(values.items())))


def test_onboarding_writes_the_overlay(tmp_path) -> None:
    users = _users_file(tmp_path)
    path = tmp_path / "suite.env"
    result = run_user_onboarding(
        principal="alice",
        overlay_path=path,
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    assert result.action is IdentityAction.ONBOARD
    assert result.outcome is IdentityOutcome.DONE
    assert "REGISTA_PRINCIPAL_ID=alice" in path.read_text()


def test_onboarding_is_idempotent(tmp_path) -> None:
    path = tmp_path / "suite.env"
    users = _users_file(tmp_path)
    kwargs = dict(
        principal="alice",
        overlay_path=path,
        env=_env(users),
        installed=_installed(),
    )
    first = run_user_onboarding(runner=StubRegista(enroll=ENROLLED), **kwargs)
    body = path.read_text()
    second = run_user_onboarding(runner=StubRegista(enroll=ALREADY_ENROLLED), **kwargs)

    assert first.outcome is IdentityOutcome.DONE
    assert second.outcome is IdentityOutcome.ALREADY_DONE
    assert path.read_text() == body, "re-running rewrote the overlay"
    assert _step(second, "user_overlay").outcome is IdentityOutcome.ALREADY_DONE


def test_onboarding_preserves_keys_the_suite_does_not_own(tmp_path) -> None:
    users = _users_file(tmp_path)
    path = tmp_path / "suite.env"
    path.write_text("OPERATOR_SETTING=keep-me\nREGISTA_PRINCIPAL_ID=stale\n")
    run_user_onboarding(
        principal="alice",
        overlay_path=path,
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    body = path.read_text()
    assert "OPERATOR_SETTING=keep-me" in body
    assert "REGISTA_PRINCIPAL_ID=alice" in body
    assert "stale" not in body


def test_onboarding_dry_run_touches_nothing(tmp_path) -> None:
    users = _users_file(tmp_path)
    path = tmp_path / "suite.env"
    runner = StubRegista(enroll=ENROLLED)
    result = run_user_onboarding(
        principal="alice",
        overlay_path=path,
        dry_run=True,
        runner=runner,
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.PENDING
    assert not path.exists()
    assert runner.calls == [], "dry-run shelled regista anyway"


# ---------------------------------------------------------------------------
# Key custody on the way in
# ---------------------------------------------------------------------------


def test_onboarding_shells_the_documented_enroll_verb(tmp_path) -> None:
    users = _users_file(tmp_path)
    runner = StubRegista(enroll=ENROLLED)
    run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        secret_backend="vault",
        runner=runner,
        env=_env(users),
        installed=_installed(),
    )
    # Pins argv exactly, including that `--json` precedes the subcommand —
    # regista's `principal` verbs rely on the global flag and reject a
    # trailing one. A stub that accepts anything hid this until the CLI was
    # driven for real.
    assert runner.calls == [
        (
            "regista", "--json", "principal", "enroll",
            "--principal", "alice",
            "--secret-backend", "vault",
        )
    ]


def test_onboarding_reports_refusal_rather_than_clobbering(tmp_path) -> None:
    """A refusal is read off the error *code*, not off the word "refuse".

    WI-051: classifying a hard stop by substring-matching the child's prose put
    regista's wording inside this contract, and failed toward green — a refusal
    whose message happened to contain "already" was recorded as success.
    """
    users = _users_file(tmp_path)
    runner = StubRegista(
        enroll=_completed(
            returncode=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "PRINCIPAL_KEY_ALREADY_EXISTS",
                        # Wording that the old parser would have read as
                        # "already provisioned", i.e. a completed step.
                        "message": "principal alice already has a key that exists",
                        "detail": None,
                        "retryable": False,
                        "partial": None,
                    },
                }
            ),
        )
    )
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=runner,
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.REFUSED
    assert result.ok is False


def test_onboarding_unknown_error_code_is_failed_not_done(tmp_path) -> None:
    """An error code the suite does not recognise is a failure, never "done"."""
    users = _users_file(tmp_path)
    runner = StubRegista(
        enroll=_completed(
            returncode=1,
            stdout=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "KEY_LOAD_ERROR",
                        "message": "vault: authentication failed",
                        "detail": None,
                        "retryable": False,
                        "partial": None,
                    },
                }
            ),
        )
    )
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=runner,
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.FAILED
    assert "KEY_LOAD_ERROR" in _step(result, "principal_key").detail


def test_onboarding_fails_without_regista(tmp_path) -> None:
    users = _users_file(tmp_path)
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(),
        env=_env(users),
        installed=_installed(False),
    )
    assert result.outcome is IdentityOutcome.FAILED
    assert "not installed" in _step(result, "principal_key").detail


def test_onboarding_rejects_non_json_enroll_output(tmp_path) -> None:
    """A CLI that prints prose on --json must not be read as success."""
    users = _users_file(tmp_path)
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=_completed(stdout="Enrolled principal alice")),
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.FAILED


# ---------------------------------------------------------------------------
# The leaver process
# ---------------------------------------------------------------------------


ACTIVE_KEYS = [
    {"principal_id": "alice", "key_id": "key-1", "secret_ref": "vault:secret/alice#key"},
    {"principal_id": "alice", "key_id": "key-2", "secret_ref": "vault:secret/alice2#key"},
]


def test_offboarding_revokes_every_active_key(tmp_path) -> None:
    path = tmp_path / "suite.env"
    path.write_text("REGISTA_PRINCIPAL_ID=alice\n")
    runner = StubRegista(active_keys=ACTIVE_KEYS)
    result = run_user_offboarding(
        principal="alice",
        reason="leaver",
        overlay_path=path,
        runner=runner,
        env=_env(),
        installed=_installed(),
    )
    revoked = [c for c in runner.calls if c[3] == "revoke"]
    assert [c[c.index("--key-id") + 1] for c in revoked] == ["key-1", "key-2"]
    assert all("--reason" in c and c[c.index("--reason") + 1] == "leaver" for c in revoked)
    assert _step(result, "revoke_keys").outcome is IdentityOutcome.DONE
    assert not path.exists(), "the leaver's overlay was left behind"


def test_offboarding_deletes_the_custodied_keys(tmp_path) -> None:
    """Revocation alone leaves the private key fetchable; deletion closes it."""
    runner = StubRegista(active_keys=ACTIVE_KEYS)
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=runner,
        env=_env(),
        installed=_installed(),
    )
    deleted_refs = [
        c[c.index("--ref") + 1] for c in runner.calls if "secrets" in c
    ]
    assert deleted_refs == ["vault:secret/alice#key", "vault:secret/alice2#key"]
    backend = _step(result, "secret_backend")
    assert backend.outcome is IdentityOutcome.DONE
    assert result.outcome is IdentityOutcome.DONE
    assert result.ok is True


def test_offboarding_reports_an_inline_ref_as_manual(tmp_path) -> None:
    """A `windows:`/`literal:` ref carries the key — discarding it is the deletion."""

    def delete(ref: str) -> subprocess.CompletedProcess[str]:
        return _completed(stdout=json.dumps({"ref": ref, "outcome": "inline_ref"}))

    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=ACTIVE_KEYS, delete=delete),
        env=_env(),
        installed=_installed(),
    )
    backend = _step(result, "secret_backend")
    assert backend.outcome is IdentityOutcome.MANUAL
    assert "carry the key inline" in backend.detail
    assert result.ok is False, "an incomplete offboarding reported as success"


def test_offboarding_reports_a_failed_delete_as_manual(tmp_path) -> None:
    """A backend that refuses must not be read as a closed fetch path."""

    def delete(ref: str) -> subprocess.CompletedProcess[str]:
        return _completed(returncode=1, stderr="env: cannot delete")

    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=ACTIVE_KEYS, delete=delete),
        env=_env(),
        installed=_installed(),
    )
    backend = _step(result, "secret_backend")
    assert backend.outcome is IdentityOutcome.MANUAL
    assert "could not delete" in backend.detail
    assert result.ok is False


def test_offboarding_a_principal_with_no_active_keys_is_already_done(tmp_path) -> None:
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=[]),
        env=_env(),
        installed=_installed(),
    )
    assert _step(result, "revoke_keys").outcome is IdentityOutcome.ALREADY_DONE
    assert result.outcome is IdentityOutcome.ALREADY_DONE
    assert result.ok is True


def test_offboarding_reports_a_partial_revocation(tmp_path) -> None:
    """Half-revoked is the state an operator must never mistake for clean."""

    def revoke(key_id: str) -> subprocess.CompletedProcess[str]:
        if key_id == "key-2":
            return _completed(returncode=1, stderr="store unreachable")
        return _completed(stdout=json.dumps({"key_id": key_id}))

    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=ACTIVE_KEYS, revoke=revoke),
        env=_env(),
        installed=_installed(),
    )
    step = _step(result, "revoke_keys")
    assert step.outcome is IdentityOutcome.FAILED
    assert "1/2" in step.detail
    assert result.ok is False


def test_offboarding_dry_run_revokes_nothing(tmp_path) -> None:
    path = tmp_path / "suite.env"
    path.write_text("REGISTA_PRINCIPAL_ID=alice\n")
    runner = StubRegista(active_keys=ACTIVE_KEYS)
    result = run_user_offboarding(
        principal="alice",
        overlay_path=path,
        dry_run=True,
        runner=runner,
        env=_env(),
        installed=_installed(),
    )
    assert [c for c in runner.calls if c[3] == "revoke"] == []
    assert path.exists()
    assert _step(result, "revoke_keys").outcome is IdentityOutcome.PENDING


def test_offboarding_keep_overlay_leaves_the_file(tmp_path) -> None:
    path = tmp_path / "suite.env"
    path.write_text("REGISTA_PRINCIPAL_ID=alice\n")
    run_user_offboarding(
        principal="alice",
        overlay_path=path,
        keep_overlay=True,
        runner=StubRegista(active_keys=[]),
        env=_env(),
        installed=_installed(),
    )
    assert path.exists()


def test_offboarding_fails_without_regista(tmp_path) -> None:
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(),
        env=_env(),
        installed=_installed(False),
    )
    assert result.outcome is IdentityOutcome.FAILED


def test_offboarding_rejects_non_json_list_output(tmp_path) -> None:
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(list_result=_completed(stdout="alice key-1 ed25519 active")),
        env=_env(),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.FAILED


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def test_result_dict_is_json_serialisable(tmp_path) -> None:
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=ACTIVE_KEYS),
        env=_env(),
        installed=_installed(),
    )
    payload = json.loads(json.dumps(result.to_dict()))
    assert payload["ok"] is True
    assert payload["action"] == "offboard"
    assert {s["name"] for s in payload["steps"]} == {
        "revoke_keys",
        "secret_backend",
        "dossier_binding",
        "user_overlay",
    }


def test_format_result_names_every_step(tmp_path) -> None:
    users = _users_file(tmp_path)
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    text = format_result(result)
    for step in result.steps:
        assert step.name in text


def test_enroll_passes_the_configured_key_path(tmp_path) -> None:
    """`principal enroll` needs the key file named explicitly.

    On the qualification host, `REGISTA_KEY_PATH` lives in `suite.env` and
    `regista --json principal enroll` still failed with
    `[UNKNOWN_KEY_ID] hmac_key_path is required`; the same command with
    `--hmac-key-path` returned `already_existed: true`. The suite knows the path,
    so it passes it.
    """
    users = _users_file(tmp_path)
    runner = StubRegista(enroll=ENROLLED)
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=runner,
        env={
            "DOSSIER_USERS_PATH": str(users),
            "REGISTA_KEY_PATH": "/etc/agent-suite/keys.json",
        },
        installed=_installed(),
    )
    assert result.ok is True
    enroll_call = next(c for c in runner.calls if "enroll" in c)
    assert "--hmac-key-path" in enroll_call
    assert enroll_call[enroll_call.index("--hmac-key-path") + 1] == (
        "/etc/agent-suite/keys.json"
    )
    # The global flags still precede the subcommand.
    assert enroll_call.index("--hmac-key-path") < enroll_call.index("principal")


def test_binding_refuses_to_rebind_an_identity_to_a_different_principal(
    tmp_path,
) -> None:
    """Rebinding changes the id a human signs under; that is an explicit choice."""
    users = _users_file(tmp_path, principal_id="someone-else")
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.REFUSED
    step = _step(result, "dossier_binding")
    assert "already bound to principal 'someone-else'" in step.detail
    assert json.loads(users.read_text())[0]["principal_id"] == "someone-else"


def test_binding_is_idempotent(tmp_path) -> None:
    users = _users_file(tmp_path, principal_id="alice")
    before = users.read_text()
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ALREADY_ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    assert result.ok is True
    assert _step(result, "dossier_binding").outcome is IdentityOutcome.ALREADY_DONE
    assert users.read_text() == before


def test_binding_reports_manual_action_for_the_ldap_backend(tmp_path) -> None:
    """The suite cannot write to a directory, and must not exit clean pretending to."""
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env={"DOSSIER_AUTH_BACKEND": "ldap"},
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.MANUAL
    assert result.ok is False
    step = _step(result, "dossier_binding")
    assert "DOSSIER_LDAP_PRINCIPAL_ID_ATTR" in step.detail


def test_binding_names_the_username_mismatch(tmp_path) -> None:
    users = _users_file(tmp_path, username="ahughes")
    result = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.MANUAL
    assert "no dossier identity with username 'alice'" in _step(
        result, "dossier_binding"
    ).detail

    bound = run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        dossier_user="ahughes",
        installed=_installed(),
    )
    assert bound.ok is True
    assert json.loads(users.read_text())[0]["principal_id"] == "alice"


def test_binding_rejects_an_invalid_principal_id(tmp_path) -> None:
    """dossier fails at *load* on a bad principal_id — writing one is worse than failing."""
    users = _users_file(tmp_path, username="alice")
    result = run_user_onboarding(
        principal="alice smith",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(users),
        installed=_installed(),
    )
    assert result.outcome is IdentityOutcome.FAILED
    assert "principal_id" in _step(result, "dossier_binding").detail
    assert "principal_id" not in json.loads(users.read_text())[0]


def test_binding_preserves_file_mode_and_other_entries(tmp_path) -> None:
    """The users file carries password hashes; do not widen or narrow its mode."""
    import os
    import stat

    path = tmp_path / "users.json"
    path.write_text(
        json.dumps(
            [
                {
                    "stable_id": "id-1",
                    "username": "alice",
                    "display_name": "Alice",
                    "password": "scrypt:aaa",
                    "groups": ["admins"],
                },
                {
                    "stable_id": "id-2",
                    "username": "bob",
                    "display_name": "Bob",
                    "password": "scrypt:bbb",
                },
            ],
            indent=2,
        )
    )
    os.chmod(path, 0o640)
    run_user_onboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(enroll=ENROLLED),
        env=_env(path),
        installed=_installed(),
    )
    written = json.loads(path.read_text())
    assert written[0]["principal_id"] == "alice"
    assert written[0]["groups"] == ["admins"]
    assert written[1] == {
        "stable_id": "id-2",
        "username": "bob",
        "display_name": "Bob",
        "password": "scrypt:bbb",
    }
    assert stat.S_IMODE(path.stat().st_mode) == 0o640


def test_offboarding_removes_a_stale_binding(tmp_path) -> None:
    """A binding pointing at a revoked principal reads as a provisioning failure."""
    users = _users_file(tmp_path, principal_id="alice")
    result = run_user_offboarding(
        principal="alice",
        overlay_path=tmp_path / "suite.env",
        runner=StubRegista(active_keys=ACTIVE_KEYS),
        env=_env(users),
        installed=_installed(),
    )
    assert result.ok is True
    assert _step(result, "dossier_binding").outcome is IdentityOutcome.DONE
    assert "principal_id" not in json.loads(users.read_text())[0]
