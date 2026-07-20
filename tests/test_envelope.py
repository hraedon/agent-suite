"""Unit tests for the error envelope builder/validator (CLI contract v1 §3)."""

from __future__ import annotations

import json

import pytest

from agent_suite.conformance import build_envelope, emit_error, validate_envelope


def test_build_envelope_minimal() -> None:
    env = build_envelope("THING_MISSING", "the thing is missing")
    assert validate_envelope(env) == []
    assert env["ok"] is False
    assert env["error"]["code"] == "THING_MISSING"
    assert env["error"]["retryable"] is False
    assert env["error"]["detail"] is None
    assert env["error"]["partial"] is None


def test_build_envelope_rejects_non_screaming_snake() -> None:
    with pytest.raises(ValueError):
        build_envelope("thing-missing", "nope")


def test_build_envelope_partial() -> None:
    env = build_envelope(
        "BATCH_PARTIAL",
        "2 of 5 items failed",
        retryable=True,
        partial={"succeeded": 3, "failed": 2},
    )
    assert validate_envelope(env) == []


@pytest.mark.parametrize(
    ("document", "fragment"),
    [
        ("not a dict", "not a JSON object"),
        ({"ok": True, "error": {}}, "'ok' is not false"),
        ({"ok": False}, "'error' is not an object"),
        (
            {"ok": False, "error": {"code": "lower", "message": "m", "retryable": False}},
            "SCREAMING_SNAKE",
        ),
        (
            {"ok": False, "error": {"code": "C", "message": 3, "retryable": False}},
            "'message' is not a string",
        ),
        (
            {"ok": False, "error": {"code": "C", "message": "m", "retryable": "yes"}},
            "'retryable' is not a boolean",
        ),
        (
            {
                "ok": False,
                "error": {
                    "code": "C",
                    "message": "m",
                    "retryable": False,
                    "partial": {"succeeded": -1, "failed": 0},
                },
            },
            "non-negative",
        ),
        (
            {
                "ok": False,
                "error": {"code": "C", "message": "m", "retryable": False, "extra": 1},
            },
            "unknown fields",
        ),
    ],
)
def test_validate_envelope_catches(document: object, fragment: str) -> None:
    violations = validate_envelope(document)
    assert violations, "expected violations"
    assert any(fragment in v for v in violations), violations


def test_emit_error_json_mode(capsys: pytest.CaptureFixture[str]) -> None:
    code = emit_error("DSN_MISSING", "no DSN", detail="set REGISTA_DSN", json_mode=True)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == ""
    document = json.loads(captured.out)
    assert validate_envelope(document) == []
    assert document["error"]["code"] == "DSN_MISSING"


def test_emit_error_human_mode(capsys: pytest.CaptureFixture[str]) -> None:
    code = emit_error("DSN_MISSING", "no DSN", detail="set REGISTA_DSN", json_mode=False)
    captured = capsys.readouterr()
    assert code == 1
    assert captured.out == ""
    assert "error: no DSN" in captured.err
    assert "set REGISTA_DSN" in captured.err
