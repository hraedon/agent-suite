from __future__ import annotations

import sys

import pytest

from agent_suite.dpapi import DPAPIError, is_available, protect, unprotect


def test_is_available_returns_bool() -> None:
    result = is_available()
    assert isinstance(result, bool)


def test_protect_raises_on_non_windows() -> None:
    if sys.platform != "win32":
        with pytest.raises(DPAPIError, match="DPAPI requires Windows"):
            protect(b"test data")


def test_unprotect_raises_on_non_windows() -> None:
    if sys.platform != "win32":
        with pytest.raises(DPAPIError, match="DPAPI requires Windows"):
            unprotect(b"test blob")


def test_protect_error_on_non_windows() -> None:
    if sys.platform != "win32":
        with pytest.raises(DPAPIError, match="DPAPI requires Windows"):
            protect(b"test data")


def test_is_available_false_on_non_windows() -> None:
    if sys.platform != "win32":
        assert is_available() is False


@pytest.mark.skipif(sys.platform == "win32", reason="Windows-only test for non-Windows behavior")
def test_all_dpapi_functions_fail_gracefully_on_non_windows() -> None:
    assert is_available() is False
    with pytest.raises(DPAPIError):
        protect(b"data")
    with pytest.raises(DPAPIError):
        unprotect(b"blob")
