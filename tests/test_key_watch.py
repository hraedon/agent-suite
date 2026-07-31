"""Unit tests for the key_watch module — key rotation age + store growth checks.

All tests use stubbed runners and installed checks — no live infra.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Mapping
from datetime import UTC

import pytest

from agent_suite.key_watch import (
    KEY_WATCH_REMEDY,
    KeyAgeStatus,
    KeyInfo,
    KeyRotationResult,
    ProjectGrowth,
    StoreGrowthResult,
    StoreGrowthStatus,
    check_key_rotation,
    check_store_growth,
    format_key_rotation_text,
    format_store_growth_text,
    principal_list_argv,
    subcommand_absent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=(), returncode=returncode, stdout=stdout, stderr=stderr)


class StubRunner:
    def __init__(self, outputs: Mapping[str, subprocess.CompletedProcess[str] | Exception]) -> None:
        self._outputs = outputs

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        out = self._outputs[cmd[0]]
        if isinstance(out, Exception):
            raise out
        return out


# ---------------------------------------------------------------------------
# Key rotation age check
# ---------------------------------------------------------------------------


def _principal_json(principals: list[dict[str, object]]) -> str:
    return json.dumps(principals)


def _key(valid_from: str, key_id: str = "k1", valid_to: str | None = None) -> dict[str, object]:
    k: dict[str, object] = {"key_id": key_id, "valid_from": valid_from}
    if valid_to:
        k["valid_to"] = valid_to
    return k


def test_key_rotation_ok_when_keys_within_cadence() -> None:
    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=_principal_json([
            {"principal_id": "alice", "keys": [_key(recent)]},
        ])),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert result.ok is True
    assert len(result.keys) == 1
    assert result.keys[0].age_days >= 9


def test_key_rotation_approaching_warns() -> None:
    from datetime import datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=85)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=_principal_json([
            {"principal_id": "alice", "keys": [_key(old)]},
        ])),
    })
    result = check_key_rotation(
        runner=runner, installed=lambda _: True, cadence_days=90, warn_threshold_pct=80
    )
    assert result.status is KeyAgeStatus.APPROACHING
    assert result.ok is True  # approaching is a warning, not a failure


def test_key_rotation_expired_fails() -> None:
    from datetime import datetime, timedelta

    expired = (datetime.now(UTC) - timedelta(days=100)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=_principal_json([
            {"principal_id": "alice", "keys": [_key(expired)]},
        ])),
    })
    result = check_key_rotation(
        runner=runner, installed=lambda _: True, cadence_days=90
    )
    assert result.status is KeyAgeStatus.EXPIRED
    assert result.ok is False  # expired makes the check fail


def test_key_rotation_skips_windowed_out_keys() -> None:
    from datetime import datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=200)).isoformat()
    valid_to = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=_principal_json([
            {"principal_id": "alice", "keys": [_key(old, valid_to=valid_to)]},
        ])),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert len(result.keys) == 0  # windowed-out key is skipped


def test_key_rotation_unreachable_when_regista_not_installed() -> None:
    result = check_key_rotation(runner=StubRunner({}), installed=lambda _: False)
    assert result.status is KeyAgeStatus.UNREACHABLE
    assert result.ok is True  # unreachable is not a failure


def test_key_rotation_unsupported_only_when_the_parser_rejects_the_verb() -> None:
    """The real signal: argparse names the subcommand as an invalid choice.

    The previous version of this test fed ``"unknown command: principal"`` — a
    string regista never emits — so it proved nothing about the CLI it was
    guarding (WI-049).
    """
    runner = StubRunner({
        "regista": _completed(
            returncode=2,
            stderr=(
                "regista: error: argument command: invalid choice: 'principal' "
                "(choose from workflow, work-item, events)"
            ),
        ),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.UNSUPPORTED
    assert result.ok is True
    assert result.checked is False


def test_key_rotation_option_usage_error_is_not_a_component_limitation() -> None:
    """WI-049's headline defect, reproduced verbatim.

    ``regista principal list --json`` puts a *global* option after the
    subcommand, so argparse exits 2 with ``unrecognized arguments: --json``. The
    old prose scan matched ``"unrecognized"`` and told every operator on the
    qualification host that regista "does not support 'principal list'" — a
    claim about the component, made from the suite's own bad argv.
    """
    runner = StubRunner({
        "regista": _completed(
            returncode=2, stderr="regista: error: unrecognized arguments: --json"
        ),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.UNREACHABLE
    assert "does not support" not in result.detail
    assert result.checked is False


def test_key_rotation_missing_key_path_is_not_a_component_limitation() -> None:
    """The other half: ``[UNKNOWN_KEY_ID]`` matched the old scan's ``"unknown"``."""
    runner = StubRunner({
        "regista": _completed(
            returncode=1, stderr="[UNKNOWN_KEY_ID] hmac_key_path is required"
        ),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.UNREACHABLE
    assert "hmac_key_path is required" in result.detail
    assert KEY_WATCH_REMEDY in result.detail


def test_probe_puts_regista_global_options_before_the_subcommand() -> None:
    """regista declares --json/--project/--hmac-key-path on the TOP-LEVEL parser.

    Anything after the subcommand is an ``unrecognized arguments`` usage error,
    so this ordering is the difference between a check that runs and one that
    cannot.
    """
    argv = principal_list_argv(project="qual_linux", key_path="/etc/agent-suite/keys.json")
    assert argv[0] == "regista"
    verb = argv.index("principal")
    assert "--json" in argv[:verb]
    assert "--project" in argv[:verb]
    assert "--hmac-key-path" in argv[:verb]
    assert argv[verb:] == ("principal", "list")


def test_probe_passes_the_resolved_project_and_key_path() -> None:
    seen: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return _completed(stdout="[]")

    check_key_rotation(
        project="qual_linux",
        key_path="/etc/agent-suite/keys.json",
        runner=runner,
        installed=lambda _: True,
    )
    assert seen == [
        (
            "regista",
            "--json",
            "--project",
            "qual_linux",
            "--hmac-key-path",
            "/etc/agent-suite/keys.json",
            "principal",
            "list",
        )
    ]


def test_key_rotation_error_on_bad_json() -> None:
    runner = StubRunner({
        "regista": _completed(stdout="not json"),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.ERROR
    assert result.ok is True


def test_key_rotation_handles_list_format() -> None:
    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps([
            {"principal_id": "alice", "keys": [_key(recent)]},
            {"principal_id": "bob", "keys": [_key(recent, "k2")]},
        ])),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert len(result.keys) == 2


def test_key_rotation_handles_dict_with_principals_key() -> None:
    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps({
            "principals": [
                {"principal_id": "alice", "keys": [_key(recent)]},
            ],
        })),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert len(result.keys) == 1


def test_key_rotation_reads_registas_actual_flat_shape() -> None:
    """``principal list --json`` emits one object per *key*, not per principal.

    The module read a nested ``{"principal_id": …, "keys": [...]}`` shape regista
    has never emitted, so a probe that succeeded still found zero keys and
    reported an empty registry (WI-049). This is the shape
    ``PrincipalKeyEntry.to_dict`` actually produces.
    """
    from datetime import datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps([
            {
                "principal_id": "qual-agent",
                "key_id": "pk_1a9a62650acd4457",
                "scheme": "ed25519",
                "status": "active",
                "valid_from": recent,
                "valid_to": None,
                "fingerprint": "ed25519:sha256:e",
            },
            {
                "principal_id": "suite-service",
                "key_id": "pk_35c46039b8594fcf",
                "scheme": "ed25519",
                "status": "active",
                "valid_from": recent,
                "valid_to": None,
                "fingerprint": "ed25519:sha256:7",
            },
        ])),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert result.checked is True
    assert [k.principal_id for k in result.keys] == ["qual-agent", "suite-service"]
    assert [k.key_id for k in result.keys] == [
        "pk_1a9a62650acd4457",
        "pk_35c46039b8594fcf",
    ]


def test_key_rotation_skips_revoked_keys_in_the_flat_shape() -> None:
    from datetime import datetime, timedelta

    stale = (datetime.now(UTC) - timedelta(days=400)).isoformat()
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps([
            {"principal_id": "a", "key_id": "old", "status": "revoked", "valid_from": stale},
        ])),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    # A revoked key past cadence must not red the check: nobody signs with it.
    assert result.status is KeyAgeStatus.OK
    assert result.keys == []
    assert result.checked is True


def test_key_rotation_no_principals_says_the_registry_was_read() -> None:
    runner = StubRunner({
        "regista": _completed(stdout="[]"),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert result.checked is True
    assert "registry read" in result.detail


def test_an_empty_result_distinguishes_verified_from_not_looked_at() -> None:
    """``ok=True`` with zero keys must not read the same both ways.

    This is regista's ``principal_binding_failures=0`` defect in miniature: a
    count of zero is only meaningful next to the fact that something counted.
    """
    read = check_key_rotation(
        runner=StubRunner({"regista": _completed(stdout="[]")}), installed=lambda _: True
    )
    skipped = check_key_rotation(runner=StubRunner({}), installed=lambda _: False)

    assert read.ok is skipped.ok is True
    assert read.keys == skipped.keys == []
    assert read.checked is True
    assert skipped.checked is False
    assert read.to_dict()["checked"] is True
    assert skipped.to_dict()["checked"] is False
    assert "not checked" in format_key_rotation_text(skipped)
    assert "not checked" not in format_key_rotation_text(read)


# ---------------------------------------------------------------------------
# Store growth check
# ---------------------------------------------------------------------------


def test_store_growth_ok_with_projects() -> None:
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps([
            {"project": "proj-a", "event_count": 1000, "store_bytes": 50000},
            {"project": "proj-b", "event_count": 500, "store_bytes": 25000},
        ])),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.OK
    assert len(result.projects) == 2
    assert result.projects[0].event_count == 1000
    assert result.projects[0].store_bytes == 50000


def test_store_growth_unreachable_when_regista_not_installed() -> None:
    result = check_store_growth(runner=StubRunner({}), installed=lambda _: False)
    assert result.status is StoreGrowthStatus.UNREACHABLE
    assert result.ok is True


def test_store_growth_unsupported_only_when_the_parser_rejects_the_verb() -> None:
    """``regista stats`` really is absent — but for the *evidenced* reason now.

    Verified against regista main: ``regista --json stats`` exits 2 with
    ``invalid choice: 'stats'``. So this ``UNSUPPORTED`` is a true negative; it
    just used to be reached by a scan that would have said the same of a
    ``stats`` that existed and failed.
    """
    runner = StubRunner({
        "regista": _completed(
            returncode=2,
            stderr=(
                "regista: error: argument command: invalid choice: 'stats' "
                "(choose from workflow, work-item, events, principal)"
            ),
        ),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.UNSUPPORTED
    assert result.checked is False


def test_store_growth_command_failure_is_not_a_component_limitation() -> None:
    runner = StubRunner({
        "regista": _completed(returncode=1, stderr="connection refused"),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.UNREACHABLE
    assert "does not support" not in result.detail
    assert result.checked is False


def test_store_growth_probe_puts_json_before_the_subcommand() -> None:
    seen: list[tuple[str, ...]] = []

    def runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return _completed(stdout="[]")

    check_store_growth(runner=runner, installed=lambda _: True)
    assert seen == [("regista", "--json", "stats")]


def test_store_growth_error_on_bad_json() -> None:
    runner = StubRunner({
        "regista": _completed(stdout="not json"),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.ERROR


def test_store_growth_handles_dict_format() -> None:
    runner = StubRunner({
        "regista": _completed(stdout=json.dumps({
            "proj-a": {"event_count": 100, "store_bytes": 5000},
        })),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.OK
    assert len(result.projects) == 1
    assert result.projects[0].project == "proj-a"


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def test_format_key_rotation_text_with_keys() -> None:
    result = KeyRotationResult(
        ok=False,
        status=KeyAgeStatus.EXPIRED,
        keys=[
            KeyInfo(
                principal_id="alice", key_id="k1", valid_from="2026-01-01",
                age_days=100, status=KeyAgeStatus.EXPIRED, detail="expired",
            ),
        ],
        cadence_days=90,
    )
    text = format_key_rotation_text(result)
    assert "alice" in text
    assert "expired" in text
    assert "90" in text


def test_format_store_growth_text_with_projects() -> None:
    result = StoreGrowthResult(
        ok=True,
        status=StoreGrowthStatus.OK,
        projects=[
            ProjectGrowth(project="proj-a", event_count=1000, store_bytes=50000),
        ],
    )
    text = format_store_growth_text(result)
    assert "proj-a" in text
    assert "1000" in text


# ---------------------------------------------------------------------------
# Capability detection (WI-049)
# ---------------------------------------------------------------------------


def test_subcommand_absent_recognises_argparses_invalid_choice() -> None:
    stderr = (
        "regista: error: argument command: invalid choice: 'stats' "
        "(choose from workflow, work-item, events, principal)"
    )
    assert subcommand_absent(stderr, path=("stats",)) is True
    assert subcommand_absent(stderr, path=("principal", "list")) is False


@pytest.mark.parametrize(
    "stderr",
    [
        # The literal argv defect: a global option placed after the subcommand.
        "regista: error: unrecognized arguments: --json",
        # regista's own error envelope, which matched the old "unknown" scan.
        "[UNKNOWN_KEY_ID] hmac_key_path is required",
        # A verb that exists and could not reach its store.
        "Missing required config: --dsn or REGISTA_DSN, --project or REGISTA_PROJECT",
        "connection to server at 10.0.0.1 failed: no such host",
        "psycopg.OperationalError: connection refused",
        # An unrelated verb named as an invalid choice must not implicate ours.
        "regista: error: argument command: invalid choice: 'stats'",
    ],
)
def test_a_command_that_failed_is_never_read_as_absent(stderr: str) -> None:
    """Each of these matched at least one word of the old prose scan.

    ``"unknown"``, ``"not found"``, ``"no such"``, ``"unrecognized"`` and a bare
    ``"invalid choice"`` all appear in messages from commands that exist. Calling
    any of them a component limitation tells the operator there is nothing to fix.
    """
    assert subcommand_absent(stderr, path=("principal", "list")) is False
