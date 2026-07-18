"""Cross-component install-harness result conformance."""

from __future__ import annotations

import json

import pytest

from agent_suite.harness import HarnessTarget
from agent_suite.harness_install import (
    HarnessInstallStatus,
    evaluate_install_harness_result,
    install_harness_argv,
)


@pytest.mark.parametrize(
    ("payload", "expected_tool", "expected"),
    [
        (
            {
                "tool": "agent-notes",
                "harness": "codex",
                "status": "installed",
                "actions": [],
                "no_op": False,
            },
            "agent-notes",
            HarnessInstallStatus.INSTALLED,
        ),
        (
            [
                {
                    "tool": "cairn",
                    "harness": "codex",
                    "status": "unsupported",
                    "actions": [],
                    "no_op": False,
                }
            ],
            "cairn",
            HarnessInstallStatus.UNSUPPORTED,
        ),
        (
            {
                "tool": "acb",
                "harness": "codex",
                "status": "failed",
                "actions": [],
                "no_op": False,
            },
            "acb",
            HarnessInstallStatus.FAILED,
        ),
    ],
)
def test_component_json_shapes_are_consumed_fail_closed(
    payload: object,
    expected_tool: str,
    expected: HarnessInstallStatus,
) -> None:
    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
        expected_tool=expected_tool,
        expected_harness=HarnessTarget.CODEX,
        require_structured=True,
    )

    assert evaluation.status is expected
    assert evaluation.ok is (expected is HarnessInstallStatus.INSTALLED)


def test_nonzero_prose_never_becomes_success() -> None:
    evaluation = evaluate_install_harness_result(
        returncode=1,
        stdout="already installed",
        stderr="successful no-op",
        expected_tool="agent-wake",
        expected_harness=HarnessTarget.CLAUDE,
    )

    assert evaluation.ok is False
    assert evaluation.status is HarnessInstallStatus.FAILED
    assert "already installed" in evaluation.detail
    assert "successful no-op" in evaluation.detail


def test_degraded_fails_closed_without_explicit_tier_policy() -> None:
    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout=json.dumps(
            {
                "tool": "cairn",
                "harness": "codex",
                "status": "degraded",
                "actions": [],
                "no_op": False,
            }
        ),
        stderr="",
        expected_tool="cairn",
        expected_harness=HarnessTarget.CODEX,
        require_structured=True,
    )

    assert evaluation.ok is False
    assert evaluation.status is HarnessInstallStatus.DEGRADED


def test_structured_clis_keep_selector_positional() -> None:
    assert install_harness_argv("agent-notes", HarnessTarget.CODEX) == (
        "agent-notes",
        "install-harness",
        "codex",
        "--json",
    )


def test_agent_wake_now_uses_structured_positional_shape() -> None:
    assert install_harness_argv("agent-wake", HarnessTarget.CLAUDE) == (
        "agent-wake",
        "install-harness",
        "claude",
        "--json",
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "not json",
        "[]",
        "[{}]",
        '[{"status":"installed"}, 3]',
        '{"tool":"cairn","harness":"codex","status":"installed","no_op":false}',
    ],
)
def test_requested_json_fails_closed_on_malformed_or_incomplete_shape(
    stdout: str,
) -> None:
    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout=stdout,
        stderr="",
        expected_tool="cairn",
        expected_harness=HarnessTarget.CODEX,
        require_structured=True,
    )

    assert evaluation.ok is False
    assert evaluation.status is HarnessInstallStatus.FAILED


def test_unstructured_success_is_reserved_for_legacy_cli() -> None:
    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout="installed",
        stderr="",
        expected_tool="agent-wake",
        expected_harness=HarnessTarget.CLAUDE,
        require_structured=False,
    )

    assert evaluation.ok is True


@pytest.mark.parametrize(
    ("tool", "harness"),
    [
        ("agent-notes", "opencode"),
        ("cairn", "codex"),
        (3, "codex"),
        ("agent-notes", ["codex"]),
    ],
)
def test_structured_result_must_match_invoked_tool_and_harness(
    tool: object,
    harness: object,
) -> None:
    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout=json.dumps(
            {
                "tool": tool,
                "harness": harness,
                "status": "installed",
                "actions": [],
                "no_op": False,
            }
        ),
        stderr="",
        expected_tool="agent-notes",
        expected_harness=HarnessTarget.CODEX,
        require_structured=True,
    )

    assert evaluation.ok is False
    assert evaluation.status is HarnessInstallStatus.FAILED
    assert "mismatch" in evaluation.detail


def test_concrete_invocation_rejects_duplicate_matching_records() -> None:
    record = {
        "tool": "cairn",
        "harness": "codex",
        "status": "installed",
        "actions": [],
        "no_op": False,
    }

    evaluation = evaluate_install_harness_result(
        returncode=0,
        stdout=json.dumps([record, record]),
        stderr="",
        expected_tool="cairn",
        expected_harness=HarnessTarget.CODEX,
        require_structured=True,
    )

    assert evaluation.ok is False
    assert evaluation.status is HarnessInstallStatus.FAILED
    assert "exactly one record" in evaluation.detail
