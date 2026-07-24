"""CLI contract v1 conformance kit (Plan 018 WI-2, Plan 019 B1).

One centrally versioned package, owned by agent-suite, consumed pinned by
every component — never copied, so there is exactly one kit to drift from.

``KIT_VERSION`` identifies the kit in recorded conformance results
(``data/cli-conformance.json``); ``CLI_CONTRACT_VERSION`` is the contract
revision the kit enforces (``docs/cli-contract.md`` in agent-suite).
"""

from agent_suite_conformance.envelope import (
    build_envelope,
    emit_error,
    validate_envelope,
)
from agent_suite_conformance.kit import (
    BrokenPipeCase,
    ErrorCase,
    Framing,
    SuccessCase,
    UsageCase,
    run_broken_pipe_case,
    run_error_case,
    run_success_case,
    run_usage_case,
)

KIT_VERSION = "1.0.0"
CLI_CONTRACT_VERSION = 1

__all__ = [
    "KIT_VERSION",
    "CLI_CONTRACT_VERSION",
    "BrokenPipeCase",
    "ErrorCase",
    "Framing",
    "SuccessCase",
    "UsageCase",
    "build_envelope",
    "emit_error",
    "run_broken_pipe_case",
    "run_error_case",
    "run_success_case",
    "run_usage_case",
    "validate_envelope",
]
