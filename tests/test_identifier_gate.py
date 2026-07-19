"""Regression: the committed-identifier gate is demonstrably blocking.

Sol's review finding #4 (2026-07-19) flagged that "the local identifier gate
currently skips when its environment inputs are absent." That is by design —
the canonical denylist is operator-secret and is wired in via the
``AGENT_SUITE_FORBIDDEN_IDENTIFIERS`` CI secret. These tests prove that when
the secret IS present, the gate fails loudly on any forbidden token, in any
tracked text file, in any line of the tree. They use synthetic tokens that
are guaranteed absent from the real denylist so they cannot mask real
drift.

These tests do NOT depend on the real denylist. They construct their own
forbidden set, write a fake tracked file containing the token, run the
scanner, and assert a non-zero exit. This is the "demonstrably blocking"
evidence Sol asked for.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_committed_identifiers.py"


def test_scan_text_flags_a_forbidden_token() -> None:
    """scan_text emits a Violation for any line containing a forbidden token."""
    from scripts.check_committed_identifiers import scan_text

    violations = list(
        scan_text("this line has ZZZ-FORIDDEN-TOKEN-XYZ in it", frozenset({"zzz-foridden-token-xyz"}))
    )
    assert len(violations) == 1
    assert violations[0].identifier == "zzz-foridden-token-xyz"


def test_scan_text_is_case_insensitive() -> None:
    """A forbidden token matches regardless of case."""
    from scripts.check_committed_identifiers import scan_text

    violations = list(scan_text("Token ZZQ-FORBIDDEN-ABC here", frozenset({"zzq-forbidden-abc"})))
    assert len(violations) == 1


def test_scan_text_returns_nothing_when_denylist_empty() -> None:
    """No forbidden tokens configured -> no violations (the no-op behavior)."""
    from scripts.check_committed_identifiers import scan_text

    assert list(scan_text("anything goes", frozenset())) == []


def test_gate_fails_on_forbidden_token_in_tracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end: the gate exits non-zero when a tracked file has a forbidden token.

    Simulates a CI run where the secret is set and someone committed a file
    containing a forbidden identifier. Constructs a synthetic token, writes a
    file in a real (throwaway) git repo, runs the script, asserts non-zero exit
    + the token in the report.
    """
    import os

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    # Initialize a real git repo and add a file containing the forbidden token.
    subprocess.run(["git", "init", "-q", str(fake_repo)], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "config", "user.name", "t"], check=True)
    leaked = fake_repo / "notes.md"
    leaked.write_text("the secret token ZZX-FORBIDDEN-TOKEN-999 appears here\n")
    subprocess.run(["git", "-C", str(fake_repo), "add", "notes.md"], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "commit", "-q", "-m", "test"], check=True)

    env = {
        **dict(os.environ),
        "AGENT_SUITE_FORBIDDEN_IDENTIFIERS": "ZZX-FORBIDDEN-TOKEN-999",
    }
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=fake_repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode != 0, (
        f"gate must fail when a forbidden token is present; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ZZX-FORBIDDEN-TOKEN-999".lower() in (result.stdout + result.stderr).lower()


def test_gate_passes_when_no_forbidden_token_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inverse: with the secret set but no violations, the gate passes."""
    import os

    fake_repo = tmp_path / "repo"
    fake_repo.mkdir()
    subprocess.run(["git", "init", "-q", str(fake_repo)], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "config", "user.name", "t"], check=True)
    (fake_repo / "notes.md").write_text("clean content with no forbidden tokens\n")
    subprocess.run(["git", "-C", str(fake_repo), "add", "notes.md"], check=True)
    subprocess.run(["git", "-C", str(fake_repo), "commit", "-q", "-m", "test"], check=True)

    env = {
        **dict(os.environ),
        "AGENT_SUITE_FORBIDDEN_IDENTIFIERS": "ZZX-FORBIDDEN-TOKEN-999",
    }
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        cwd=fake_repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"gate must pass when no forbidden token is present; got rc={result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_current_tree_is_clean_against_canonical_denylist() -> None:
    """The current agent-suite tree must be clean against the canonical denylist.

    This is the live-application regression: it reads the canonical denylist
    from the operator's config (~/.config/agent-suite/forbidden-identifiers)
    if present, scans every tracked file in this repo, and asserts zero
    violations. If the operator config is absent (e.g. CI without the secret
    mounted as a file), the test SKIPS — it cannot judge what it cannot read.
    The CI gate (scripts/check_committed_identifiers.py) is the authoritative
    blocking check; this test is the local-development mirror.
    """
    denylist_path = Path.home() / ".config" / "agent-suite" / "forbidden-identifiers"
    if not denylist_path.is_file():
        pytest.skip("canonical denylist not present locally; CI gate is authoritative")
    raw = denylist_path.read_text(encoding="utf-8")
    from scripts.check_committed_identifiers import parse_identifier_set, collect_tracked_paths, scan_files

    identifiers = parse_identifier_set(raw)
    if not identifiers:
        pytest.skip("canonical denylist is empty")
    paths = collect_tracked_paths()
    violations = scan_files(identifiers, paths)
    assert not violations, (
        f"canonical denylist violation(s) in tracked files: "
        f"{[(v.path, v.line_number, v.identifier) for v in violations[:5]]}"
    )
