"""Unit tests for the key_watch module — key rotation age + store growth checks.

All tests use stubbed runners and installed checks — no live infra.
"""

from __future__ import annotations

import json
import subprocess
from typing import Mapping


from agent_suite.key_watch import (
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
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
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
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=85)).isoformat()
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
    from datetime import datetime, timedelta, timezone

    expired = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
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
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()
    valid_to = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
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


def test_key_rotation_unsupported_when_command_unknown() -> None:
    runner = StubRunner({
        "regista": _completed(returncode=1, stderr="unknown command: principal"),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.UNSUPPORTED
    assert result.ok is True


def test_key_rotation_error_on_bad_json() -> None:
    runner = StubRunner({
        "regista": _completed(stdout="not json"),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.ERROR
    assert result.ok is True


def test_key_rotation_handles_list_format() -> None:
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
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
    from datetime import datetime, timedelta, timezone

    recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
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


def test_key_rotation_no_principals() -> None:
    runner = StubRunner({
        "regista": _completed(stdout="[]"),
    })
    result = check_key_rotation(runner=runner, installed=lambda _: True)
    assert result.status is KeyAgeStatus.OK
    assert "no principals" in result.detail


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


def test_store_growth_unsupported_when_command_unknown() -> None:
    runner = StubRunner({
        "regista": _completed(returncode=1, stderr="unknown command: stats"),
    })
    result = check_store_growth(runner=runner, installed=lambda _: True)
    assert result.status is StoreGrowthStatus.UNSUPPORTED


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
