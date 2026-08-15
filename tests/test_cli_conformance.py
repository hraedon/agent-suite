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
    assert_cases_declared,
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
    SuccessCase(
        name="invariant-probes-json-report",
        argv=(*_CLI, "invariant-probes", "--json"),
        env=_HERMETIC_ENV,
        unset_env=("REGISTA_DSN",),
    ),
    SuccessCase(
        name="genesis-gate-json-report",
        argv=(*_CLI, "genesis-gate", "--json"),
        env=_HERMETIC_ENV,
        unset_env=("REGISTA_DSN",),
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
        name="doctor-verify-restore-no-dsn-human",
        argv=(*_CLI, "doctor", "--verify-restore"),
        json_mode=False,
        env=_HERMETIC_ENV,
        unset_env=("REGISTA_DSN",),
    ),
    # WI-071 L3: the scheduled-protection env-indirection codes (WI-068/069),
    # each through the real CLI. The DSN-handling paths carry the kit's
    # sentinel-secret redaction property — a DSN value in error output is a
    # violation, not just a style problem.
    ErrorCase(
        name="backup-dir-env-unset-flag-missing",
        argv=(*_CLI, "backup", "--dir-env", "AGENT_SUITE_BACKUP_DIR", "--json"),
        expect_code="FLAG_MISSING",
        env=_HERMETIC_ENV,
        unset_env=("AGENT_SUITE_BACKUP_DIR",),
    ),
    ErrorCase(
        name="restore-dsn-and-dsn-env-conflict",
        argv=(
            *_CLI,
            "restore",
            "--dir",
            "/nonexistent/backups",
            "--dsn",
            "postgresql://u@h/db",
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ),
        expect_code="FLAG_CONFLICT",
        env=_HERMETIC_ENV,
    ),
    ErrorCase(
        name="restore-dsn-env-invalid-name",
        argv=(
            *_CLI,
            "restore",
            "--dir",
            "/nonexistent/backups",
            "--dsn-env",
            "not a valid env name",
            "--json",
        ),
        expect_code="FLAG_INVALID",
        env=_HERMETIC_ENV,
    ),
    ErrorCase(
        name="restore-dsn-env-unset",
        argv=(
            *_CLI,
            "restore",
            "--dir",
            "/nonexistent/backups",
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ),
        expect_code="DSN_MISSING",
        env=_HERMETIC_ENV,
        unset_env=("AGENT_SUITE_VERIFY_RESTORE_DSN",),
    ),
    ErrorCase(
        name="restore-dsn-not-dedicated-redacts",
        argv=(
            *_CLI,
            "restore",
            "--dir",
            "/nonexistent/backups",
            "--dsn-env",
            "AGENT_SUITE_VERIFY_RESTORE_DSN",
            "--json",
        ),
        expect_code="DSN_NOT_DEDICATED",
        env=_HERMETIC_ENV,
        # Both DSNs planted as the sentinel: string-equal → NOT_DEDICATED,
        # and neither value may surface in the error output.
        secret_env_names=("REGISTA_DSN", "AGENT_SUITE_VERIFY_RESTORE_DSN"),
    ),
]

USAGE_CASES = [
    UsageCase(name="unknown-verb", argv=(*_CLI, "no-such-verb")),
    UsageCase(name="no-verb", argv=_CLI),
    # WI-071 L3/L4: the --dir/--dir-env group is parser-enforced, so omitting
    # both (or passing both) is a usage error (exit 2, usage text), not an
    # envelope path — the 1/2 boundary ratified in cli-contract.md §2.
    UsageCase(name="backup-no-dir", argv=(*_CLI, "backup", "--json")),
    UsageCase(
        name="restore-dir-and-dir-env",
        argv=(
            *_CLI,
            "restore",
            "--dir",
            "/nonexistent/backups",
            "--dir-env",
            "AGENT_SUITE_BACKUP_DIR",
            "--json",
        ),
    ),
]

BROKEN_PIPE_CASES = [
    BrokenPipeCase(
        name="schedule-list-json-headed",
        argv=(*_CLI, "schedule", "list", "--json"),
        env=_HERMETIC_ENV,
    ),
]

# WI-026 meta-guard: fail collection loudly if any contract dimension empties.
# A zero-case dimension enforces nothing and — because this module is the
# kit-importing surface — would be indistinguishable from a pass in green CI.
# (The whole-module-skip class is covered by test_conformance_meta_guard.py.)
assert_cases_declared(
    minimum=1,
    success=SUCCESS_CASES,
    error=ERROR_CASES,
    usage=USAGE_CASES,
    broken_pipe=BROKEN_PIPE_CASES,
)


@pytest.mark.parametrize("case", SUCCESS_CASES, ids=lambda c: c.name)
def test_success_conformance(case: SuccessCase) -> None:
    assert run_success_case(case) == []


@pytest.mark.parametrize("case", ERROR_CASES, ids=lambda c: c.name)
def test_error_conformance(case: ErrorCase) -> None:
    assert run_error_case(case) == []


def test_dual_control_store_unwritable_conformance(tmp_path: Path) -> None:
    """Store-directory failure maps to STORE_UNAVAILABLE, not a traceback.

    The unwritable path is a child of a regular *file* so directory
    creation fails on every platform (a bare ``/nonexistent`` is happily
    creatable as ``C:\\nonexistent`` on Windows runners).
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")
    case = ErrorCase(
        name="dual-control-store-path-unwritable",
        argv=(
            *_CLI,
            "dual-control",
            "list",
            "--store-path",
            str(blocker / "sub" / "dual-control.json"),
            "--json",
        ),
        expect_code="STORE_UNAVAILABLE",
        env=_HERMETIC_ENV,
    )
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
