"""Tests for the workspace-root resolution contract (WI-058).

Two env vars name the workspace/siblings root (``SUITE_WORKSPACE_ROOT``,
``AGENT_SUITE_SIBLINGS_ROOT``). They must resolve through one implementation
with a fixed precedence: canonical > alias > default. See
``agent_suite.lock.resolve_workspace_root``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_suite.lock import resolve_workspace_root


@pytest.fixture(autouse=True)
def _clear_workspace_root_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # The surrounding test env may carry either var; clear both so each test
    # asserts against a known baseline.
    monkeypatch.delenv("SUITE_WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("AGENT_SUITE_SIBLINGS_ROOT", raising=False)


def test_default_returned_when_neither_var_set() -> None:
    expected = Path("/projects").expanduser().resolve()
    assert resolve_workspace_root(Path("/projects")) == expected


def test_canonical_var_alone_is_honored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", str(tmp_path / "canonical"))
    assert resolve_workspace_root(Path("/projects")) == (tmp_path / "canonical").resolve()


def test_alias_var_alone_is_honored_back_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path / "alias"))
    assert resolve_workspace_root(Path("/projects")) == (tmp_path / "alias").resolve()


def test_canonical_wins_when_both_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", str(tmp_path / "canonical"))
    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path / "alias"))
    assert resolve_workspace_root(Path("/projects")) == (tmp_path / "canonical").resolve()


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_whitespace_only_values_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", value)
    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", value)
    expected = Path("/projects").expanduser().resolve()
    assert resolve_workspace_root(Path("/projects")) == expected


def test_result_is_absolute_even_for_relative_default() -> None:
    # A relative default must resolve to an absolute path — the M-5 contract
    # resolve_workspace_root upholds for every caller.
    result = resolve_workspace_root(Path("relative/root"))
    assert result.is_absolute()
    assert result == Path("relative/root").expanduser().resolve()


def test_default_search_roots_honor_alias_back_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # _default_search_roots delegates to resolve_workspace_root, so the
    # back-compat alias must also steer `agent-suite lock` checkout discovery.
    from agent_suite.lock import _default_search_roots

    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path))
    assert _default_search_roots() == (tmp_path.resolve(),)
