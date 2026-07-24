"""CLI contract v1 conformance kit — re-export layer (Plan 019 B1).

The canonical source is the standalone ``agent-suite-conformance`` package.
This module re-exports it so agent-suite's own code and tests can keep using
``from agent_suite.conformance import ...`` without change.
"""

from agent_suite_conformance import (
    CLI_CONTRACT_VERSION,
    KIT_VERSION,
    BrokenPipeCase,
    ErrorCase,
    Framing,
    SuccessCase,
    UsageCase,
    build_envelope,
    emit_error,
    run_broken_pipe_case,
    run_error_case,
    run_success_case,
    run_usage_case,
    validate_envelope,
)

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
