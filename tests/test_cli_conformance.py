"""agent-suite's own CLI run through the conformance kit (Plan 018 WI-2 dogfood).

The kit is the centrally versioned package at ``agent_suite.conformance``;
these cases are the component-side fixtures. Sibling components declare
the same shape against their own CLIs and consume the kit pinned.

Every case pins ``AGENT_SUITE_CONFIG`` to a nonexistent path and strips
the operator's live environment (``REGISTA_DSN``) so results don't depend
on the box's suite.env.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from agent_suite.conformance import (
    BrokenPipeCase,
    ErrorCase,
    SuccessCase,
    UsageCase,
    run_broken_pipe_case,
    run_error_case,
    run_success_case,
    run_usage_case,
)

_HERMETIC_ENV = {"AGENT_SUITE_CONFIG": "/nonexistent/suite.env"}
_CLI = (sys.executable, "-m", "agent_suite.cli")

SUCCESS_CASES = [
    SuccessCase(
        name="schedule-list-json",
        argv=(*_CLI, "schedule", "list", "--json"),
        env=_HERMETIC_ENV,
    ),
]

ERROR_CASES = [
    ErrorCase(
        name="doctor-verify-restore-no-dsn",
        argv=(*_CLI, "doctor", "--verify-restore", "--json"),
        expect_code="DSN_MISSING",
        env=_HERMETIC_ENV,
        unset_env=("REGISTA_DSN",),
    ),
    ErrorCase(
        name="upgrade-forward-recover-dry-run-conflict",
        argv=(*_CLI, "upgrade", "--forward-recover", "--dry-run", "--json"),
        expect_code="FLAG_CONFLICT",
        env=_HERMETIC_ENV,
        # The redaction fixture: a planted secret must never surface in
        # error output (contract §3), whatever env the CLI loads.
        secret_env_names=("DOSSIER_SESSION_SECRET",),
    ),
    ErrorCase(
        name="dual-control-execute-missing-request-id",
        argv=(*_CLI, "dual-control", "execute", "--json"),
        expect_code="FLAG_MISSING",
        env=_HERMETIC_ENV,
    ),
    ErrorCase(
        name="dual-control-store-path-unwritable",
        argv=(
            *_CLI,
            "dual-control",
            "list",
            "--store-path",
            "/nonexistent/dual-control.json",
            "--json",
        ),
        expect_code="STORE_UNAVAILABLE",
        env=_HERMETIC_ENV,
    ),
    ErrorCase(
        name="doctor-verify-restore-no-dsn-human",
        argv=(*_CLI, "doctor", "--verify-restore"),
        json_mode=False,
        env=_HERMETIC_ENV,
        unset_env=("REGISTA_DSN",),
    ),
]

USAGE_CASES = [
    UsageCase(name="unknown-verb", argv=(*_CLI, "no-such-verb")),
    UsageCase(name="no-verb", argv=_CLI),
]

BROKEN_PIPE_CASES = [
    BrokenPipeCase(
        name="schedule-list-json-headed",
        argv=(*_CLI, "schedule", "list", "--json"),
        env=_HERMETIC_ENV,
    ),
]


@pytest.mark.parametrize("case", SUCCESS_CASES, ids=lambda c: c.name)
def test_success_conformance(case: SuccessCase) -> None:
    assert run_success_case(case) == []


@pytest.mark.parametrize("case", ERROR_CASES, ids=lambda c: c.name)
def test_error_conformance(case: ErrorCase) -> None:
    assert run_error_case(case) == []


def test_dual_control_unknown_request_conformance(tmp_path: Path) -> None:
    """Unresolvable-reference fixture: writable store, unknown request id."""
    case = ErrorCase(
        name="dual-control-approve-unknown-request",
        argv=(
            *_CLI,
            "dual-control",
            "approve",
            "--request-id",
            "no-such-request",
            "--token",
            "tok",
            "--store-path",
            str(tmp_path / "dual-control.json"),
            "--json",
        ),
        expect_code="REQUEST_NOT_FOUND",
        env=_HERMETIC_ENV,
    )
    assert run_error_case(case) == []


@pytest.mark.parametrize("case", USAGE_CASES, ids=lambda c: c.name)
def test_usage_conformance(case: UsageCase) -> None:
    assert run_usage_case(case) == []


@pytest.mark.parametrize("case", BROKEN_PIPE_CASES, ids=lambda c: c.name)
def test_broken_pipe_conformance(case: BrokenPipeCase) -> None:
    assert run_broken_pipe_case(case) == []
