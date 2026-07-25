"""Self-tests for the conformance kit's meta-guard helper (WI-026).

``assert_cases_declared`` is the kit's structural cure for the "declared zero
cases for a dimension" half of the fails-open class. These tests pin its
behavior and — per process-calibration §5 — include a deny-case proving the
guard actually rejects short groups rather than being a no-op over ``len()``.
"""

from __future__ import annotations

import pytest

from agent_suite.conformance import (
    ConformanceGateError,
    ErrorCase,
    SuccessCase,
    UsageCase,
    assert_cases_declared,
)

_OK_SUCCESS = [SuccessCase(name="x", argv=("python", "-c", "pass"))]
_OK_ERROR = [ErrorCase(name="y", argv=("python", "-c", "fail"))]


def test_all_non_empty_groups_pass() -> None:
    assert_cases_declared(success=_OK_SUCCESS, error=_OK_ERROR) is None


def test_minimum_one_is_the_default() -> None:
    """No explicit minimum still requires >=1 per group."""
    assert_cases_declared(success=_OK_SUCCESS) is None
    with pytest.raises(ConformanceGateError, match="success"):
        assert_cases_declared(success=[])


def test_empty_group_is_named_in_the_error() -> None:
    with pytest.raises(ConformanceGateError) as exc:
        assert_cases_declared(success=_OK_SUCCESS, usage=[])
    msg = str(exc.value)
    assert "usage (0)" in msg
    assert "success" not in msg.split(";")[0]  # the non-empty group is not flagged
    assert "WI-026" in msg


def test_multiple_empty_groups_are_all_listed() -> None:
    with pytest.raises(ConformanceGateError) as exc:
        assert_cases_declared(success=[], error=[])
    msg = str(exc.value)
    assert "error (0)" in msg
    assert "success (0)" in msg


def test_minimum_above_one_raises_when_short() -> None:
    """A higher minimum catches a dimension that declared *some* but too few."""
    with pytest.raises(ConformanceGateError, match="usage"):
        assert_cases_declared(minimum=2, usage=[UsageCase(name="only-one", argv=())])


def test_minimum_above_one_passes_when_met() -> None:
    assert_cases_declared(
        minimum=2,
        usage=[UsageCase(name="a", argv=()), UsageCase(name="b", argv=())],
    ) is None


def test_no_groups_is_an_error() -> None:
    """Calling the guard with no groups is a mistake — it should not silently pass."""
    with pytest.raises(ConformanceGateError):
        assert_cases_declared()


def test_invalid_minimum_raises_value_error() -> None:
    with pytest.raises(ValueError, match="minimum"):
        assert_cases_declared(minimum=0, success=_OK_SUCCESS)


def test_error_is_an_assertion_error_subclass() -> None:
    """It must read as an assertion failure in pytest while staying grep-able."""
    assert issubclass(ConformanceGateError, AssertionError)


def test_guard_is_not_a_tautology() -> None:
    """Deny case: if the guard's comparison were inverted/removed, this fails."""
    flag = True
    try:
        assert_cases_declared(broken_pipe=[])  # must raise
        flag = False  # guard did not fire -> broken
    except ConformanceGateError:
        flag = True
    assert flag, "assert_cases_declared did not reject an empty group"
