"""Closed harness-target contract tests (Plan 007 WI-1.2)."""

from __future__ import annotations

import pytest

from agent_suite.harness import (
    STABLE_HARNESS_TARGETS,
    HarnessTarget,
    expand_harness_target,
    normalize_harness_target,
)


@pytest.mark.parametrize("target", list(HarnessTarget))
def test_expand_harness_target_is_exhaustive(target: HarnessTarget) -> None:
    expanded = expand_harness_target(target)
    if target is HarnessTarget.ALL:
        assert expanded == (
            HarnessTarget.CLAUDE,
            HarnessTarget.OPENCODE,
        )
    else:
        assert expanded == (target,)


def test_stable_all_excludes_component_private_targets() -> None:
    assert STABLE_HARNESS_TARGETS == expand_harness_target(HarnessTarget.ALL)
    assert {target.value for target in STABLE_HARNESS_TARGETS} == {
        "claude",
        "opencode",
    }


def test_normalize_rejects_unknown_target() -> None:
    with pytest.raises(ValueError):
        normalize_harness_target("hermes")
