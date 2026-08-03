"""Tests for the workspace-root resolution contract (WI-058).

Two env vars name the workspace/siblings root (``SUITE_WORKSPACE_ROOT``,
``AGENT_SUITE_SIBLINGS_ROOT``). They must resolve through one implementation
with a fixed precedence: canonical > alias > caller default. See
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


def test_default_returned_when_neither_var_set(tmp_path: Path) -> None:
    default = tmp_path / "projects"
    assert resolve_workspace_root(default) == default.resolve()


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


def test_whitespace_canonical_falls_through_to_valid_alias(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A whitespace-only canonical value is treated as unset, so a valid alias
    # must then win rather than the default.
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", "   ")
    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path / "alias"))
    assert resolve_workspace_root(Path("/projects")) == (tmp_path / "alias").resolve()


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_whitespace_only_values_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, value: str
) -> None:
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", value)
    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", value)
    default = tmp_path / "projects"
    assert resolve_workspace_root(default) == default.resolve()


def test_expanduser_applied_to_env_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITE_WORKSPACE_ROOT", "~")
    assert resolve_workspace_root(Path("/projects")) == Path("~").expanduser().resolve()


def test_result_is_absolute_even_for_relative_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # A relative default must resolve to an absolute path — the M-5 contract
    # resolve_workspace_root upholds for every caller. resolve() is CWD-based,
    # so pin the CWD to make the expectation exact.
    monkeypatch.chdir(tmp_path)
    result = resolve_workspace_root(Path("relative/root"))
    assert result.is_absolute()
    assert result == tmp_path / "relative" / "root"


def test_default_search_roots_honor_alias_back_compat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # _default_search_roots delegates to resolve_workspace_root, so the
    # back-compat alias must also steer `agent-suite lock` checkout discovery.
    from agent_suite.lock import _default_search_roots

    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path))
    assert _default_search_roots() == (tmp_path.resolve(),)


def test_read_candidate_revisions_steered_by_alias_end_to_end(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The WI-058 drift scenario, end to end: an operator who sets only the
    # alias (as CI does) must have lock checkout discovery follow it.
    import subprocess

    from agent_suite.components import Tier, _component
    from agent_suite.lock import read_candidate_revisions

    checkout = tmp_path / "fake-suite-comp"
    checkout.mkdir()
    subprocess.run(
        ("git", "init", "-q", str(checkout)), check=True, capture_output=True
    )
    subprocess.run(
        ("git", "-C", str(checkout), "commit", "-q", "--allow-empty", "-m", "x"),
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example",
            "HOME": str(tmp_path),
        },
    )
    head = subprocess.run(
        ("git", "-C", str(checkout), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    monkeypatch.setenv("AGENT_SUITE_SIBLINGS_ROOT", str(tmp_path))
    comp = _component("fake", "owner/fake-suite-comp", Tier.SPINE, ("fake", "doctor"))
    assert read_candidate_revisions(components=(comp,))["fake"] == head
