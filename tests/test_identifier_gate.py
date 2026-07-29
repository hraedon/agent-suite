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

WI-018 extends this to every branch of the guard whose broken state fails
*open* — the always-on ``samples/`` guard (no secret required), the
``--staged`` pre-commit path, the first-component-only matching, and the
denylist parser. A gate is only as good as the test that proves it blocks;
each new case plants known-bad input and asserts a nonzero exit, so a
refactor that silently disables a branch fails this file rather than failing
open in production.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_committed_identifiers.py"


def _combined(result: subprocess.CompletedProcess) -> str:
    """stdout+stderr with backslashes normalized to forward slashes.

    The gate emits OS-native path separators (backslashes on Windows); these
    tests assert forward-slash paths so they pass on both platforms.
    """
    return (result.stdout + result.stderr).replace("\\", "/")


def test_scan_text_flags_a_forbidden_token() -> None:
    """scan_text emits a Violation for any line containing a forbidden token."""
    from scripts.check_committed_identifiers import scan_text

    violations = list(
        scan_text(
            "this line has ZZZ-FORIDDEN-TOKEN-XYZ in it",
            frozenset({"zzz-foridden-token-xyz"}),
        )
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
        check=False,
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
        check=False,
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
    from scripts.check_committed_identifiers import (
        collect_tracked_paths,
        parse_identifier_set,
        scan_files,
    )

    identifiers = parse_identifier_set(raw)
    if not identifiers:
        pytest.skip("canonical denylist is empty")
    paths = collect_tracked_paths()
    violations = scan_files(identifiers, paths)
    assert not violations, (
        f"canonical denylist violation(s) in tracked files: "
        f"{[(v.path, v.line_number, v.identifier) for v in violations[:5]]}"
    )


def test_ci_refuses_an_unconfigured_denylist_secret() -> None:
    """CI must not turn a missing publication policy into a green skip."""
    ci = (_SCRIPT.parents[1] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert '${AGENT_SUITE_FORBIDDEN_IDENTIFIERS//[[:space:]]/}' in ci
    assert "AGENT_SUITE_FORBIDDEN_IDENTIFIERS must be configured" in ci


# ---------------------------------------------------------------------------
# WI-018 — fixture-driven tests for the fails-open branches.
#
# Each case below covers a branch of the gate whose broken state would pass
# silently: the always-on samples/ guard, the --staged pre-commit path, the
# first-component-only matcher, and the denylist parser. A refactor that
# disables any of these must turn one of these tests red, not fail open.
# ---------------------------------------------------------------------------


def _make_repo(repo: Path) -> None:
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)


def _run_gate(
    repo: Path, env_secret: str | None, *, staged: bool = False
) -> subprocess.CompletedProcess[str]:
    import os

    argv = [sys.executable, str(_SCRIPT)]
    if staged:
        argv.append("--staged")
    env = {**dict(os.environ)}
    if env_secret is not None:
        env["AGENT_SUITE_FORBIDDEN_IDENTIFIERS"] = env_secret
    else:
        env.pop("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", None)
    return subprocess.run(
        argv, cwd=repo, env=env, capture_output=True, text=True, timeout=30, check=False,
    )


def test_always_on_samples_guard_blocks_without_secret(tmp_path: Path) -> None:
    """The samples/ guard fires with NO secret configured.

    This is the always-on branch that runs before the secret-driven scan. If a
    refactor makes ``leaked_tracked_files`` return [], a force-add of real
    identifier-bearing data under samples/ would slip through with exit 0 —
    silent failure. Planting a tracked samples/ file and asserting nonzero exit
    is the proof it still blocks.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "samples").mkdir()
    (repo / "samples" / "leaked.md").write_text("any content\n")
    subprocess.run(["git", "-C", str(repo), "add", "samples/leaked.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret=None)  # NO secret: the always-on path only
    assert result.returncode != 0, (
        f"always-on samples/ guard must block without the secret; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "samples/leaked.md" in _combined(result)


def test_always_on_guard_matches_first_path_component_only() -> None:
    """Unit: leaked_tracked_files guards root-level samples/ but not a nested
    code dir that happens to be named samples (e.g. tests/samples/).

    A matcher that flipped to a ``in parts`` test would flag nested legitimate
    code dirs (false positives); a matcher that flipped to never-match would
    let root samples/ through (fail open). Pin the exact semantics.
    """
    from scripts.check_committed_identifiers import leaked_tracked_files

    guarded = frozenset({"samples"})
    paths = [
        Path("samples/real.md"),        # guarded — root component
        Path("tests/samples/legit.md"), # NOT guarded — nested code dir
        Path("a/b/samples/deep.md"),    # NOT guarded — not a root component
    ]
    leaked = leaked_tracked_files(paths, guarded)
    assert leaked == [Path("samples/real.md")], (
        f"only root-level samples/ must be guarded; got {leaked}"
    )


def test_nested_samples_dir_is_scanned_not_guarded(tmp_path: Path) -> None:
    """A leak inside tests/samples/ is caught by the SCAN, not skipped as
    guarded — so the first-component matcher can't silently widen to skip it.

    If ``leaked_tracked_files`` (or the skip filter) ever treated nested
    samples/ as guarded, this forbidden token would be missed. Asserting
    nonzero exit proves nested samples/ is still scanned.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "tests" / "samples").mkdir(parents=True)
    (repo / "tests" / "samples" / "fixture.md").write_text(
        "token ZZN-NESTED-TOKEN-777 here\n"
    )
    subprocess.run(["git", "-C", str(repo), "add", "tests/samples/fixture.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret="ZZN-NESTED-TOKEN-777")
    assert result.returncode != 0, (
        f"nested tests/samples/ must be scanned, not skipped; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "tests/samples/fixture.md" in _combined(result)


def test_staged_path_blocks_a_forbidden_staged_file(tmp_path: Path) -> None:
    """The --staged pre-commit path blocks a forbidden file that is staged but
    NOT yet committed.

    ``collect_staged_paths`` (``git diff --cached``) is a distinct code path
    from ``collect_tracked_paths`` (``git ls-files``) with no prior coverage.
    A refactor breaking it would let a leak reach the index in the pre-commit
    hook. Plant a staged file and assert nonzero exit on ``--staged``.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "staged.md").write_text("token ZZW-STAGED-TOKEN-555 here\n")
    subprocess.run(["git", "-C", str(repo), "add", "staged.md"], check=True)
    # Intentionally NO commit: the file is only staged.

    result = _run_gate(repo, env_secret="ZZW-STAGED-TOKEN-555", staged=True)
    assert result.returncode != 0, (
        f"--staged must block a staged forbidden file; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "staged.md" in _combined(result)


def test_staged_path_passes_when_index_clean(tmp_path: Path) -> None:
    """Inverse: --staged with nothing staged passes (no false positive)."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "committed.md").write_text("clean\n")
    subprocess.run(["git", "-C", str(repo), "add", "committed.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret="ZZW-STAGED-TOKEN-555", staged=True)
    assert result.returncode == 0, (
        f"--staged must pass with a clean index; got rc={result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_parse_identifier_set_strips_comments() -> None:
    """A human-maintained denylist may document itself with # comments; comment
    words must NOT become forbidden tokens. A parser regression here either
    over-blocks (comment words flagged) or, if stripping is dropped, makes the
    denylist uneditable. Pin the documented behavior.
    """
    from scripts.check_committed_identifiers import parse_identifier_set

    raw = (
        "# This is a comment line\n"
        "real-host.example  # trailing comment words here\n"
        "\n"
        "svc-real-account\n"
    )
    identifiers = parse_identifier_set(raw)
    assert identifiers == frozenset({"real-host.example", "svc-real-account"}), identifiers
    # Comment words are not tokens.
    assert "comment" not in identifiers
    assert "trailing" not in identifiers


def test_parse_identifier_set_drops_short_tokens() -> None:
    """Tokens shorter than MIN_IDENTIFIER_LENGTH are dropped to avoid flagging
    short common substrings. Pin the minimum-length filter so it can't silently
    widen (flag everything) or vanish (flag 2-letter words).
    """
    from scripts.check_committed_identifiers import MIN_IDENTIFIER_LENGTH, parse_identifier_set

    identifiers = parse_identifier_set("ab  xyz  host.example")
    # "ab" (2) and "xyz" (3) are below the minimum (4); only host.example survives.
    assert identifiers == frozenset({"host.example"}), identifiers
    assert MIN_IDENTIFIER_LENGTH == 4


def test_binary_file_is_skipped_no_false_positive(tmp_path: Path) -> None:
    """A binary file (NUL byte, no text BOM) is skipped, not scanned — so a
    forbidden-looking byte sequence inside one can't produce a false positive,
    and a regression in the binary heuristic can't crash the scan.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    binary = repo / "blob.bin"
    # Forbidden token as text + a NUL byte -> classified binary and skipped.
    binary.write_bytes(b"ZZV-BIN-TOKEN-333\x00\x01\x02more bytes")
    subprocess.run(["git", "-C", str(repo), "add", "blob.bin"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret="ZZV-BIN-TOKEN-333")
    assert result.returncode == 0, (
        f"binary file must be skipped (no false positive); got rc={result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_utf16_file_with_forbidden_token_is_caught(tmp_path: Path) -> None:
    """A UTF-16 (BOM) file containing a forbidden token MUST be detected, not
    silently skipped.

    UTF-16 encodes ASCII as NUL-padded bytes, so without the BOM sniff the
    null-byte binary heuristic would misclassify it as binary and the scan would
    skip it — a forbidden identifier leaking past the gate undetected. This is a
    real fails-open path for forbidden content (Windows tooling commonly emits
    UTF-16). Planting the token and asserting nonzero exit pins the BOM sniff.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    leaked = repo / "windows_export.txt"
    # Encoding="utf-16" writes a BOM; the token is real text inside it.
    leaked.write_text("leaked ZZY-UTF16-TOKEN-111 here\n", encoding="utf-16")
    subprocess.run(["git", "-C", str(repo), "add", "windows_export.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret="ZZY-UTF16-TOKEN-111")
    assert result.returncode != 0, (
        f"UTF-16 file with a forbidden token must be caught; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "windows_export.txt" in _combined(result)
