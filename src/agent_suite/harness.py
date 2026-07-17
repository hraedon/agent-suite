"""Closed suite harness-target contract.

The suite intentionally exposes only stable, cross-component targets.  A
component may support additional private targets, but those targets never enter
the suite's ``all`` expansion implicitly.
"""

from __future__ import annotations

from enum import StrEnum
from typing import assert_never


class HarnessTarget(StrEnum):
    """Harness targets accepted by suite-owned orchestration surfaces."""

    CLAUDE = "claude"
    OPENCODE = "opencode"
    CODEX = "codex"
    ALL = "all"


STABLE_HARNESS_TARGETS: tuple[HarnessTarget, ...] = (
    HarnessTarget.CLAUDE,
    HarnessTarget.OPENCODE,
)


def expand_harness_target(target: HarnessTarget) -> tuple[HarnessTarget, ...]:
    """Expand ``all`` to the stable suite targets in deterministic order."""

    match target:
        case HarnessTarget.CLAUDE:
            return (HarnessTarget.CLAUDE,)
        case HarnessTarget.OPENCODE:
            return (HarnessTarget.OPENCODE,)
        case HarnessTarget.CODEX:
            return (HarnessTarget.CODEX,)
        case HarnessTarget.ALL:
            return STABLE_HARNESS_TARGETS
        case other:
            assert_never(other)


def normalize_harness_target(target: HarnessTarget | str) -> HarnessTarget:
    """Validate a programmatic target before orchestration performs any action."""

    return target if isinstance(target, HarnessTarget) else HarnessTarget(target)
