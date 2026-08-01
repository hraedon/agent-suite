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
    unreadable: list[Path] = []
    violations = scan_files(identifiers, paths, unreadable=unreadable)
    assert not violations, (
        f"canonical denylist violation(s) in tracked files: "
        f"{[(v.path, v.line_number, v.identifier) for v in violations[:5]]}"
    )
    assert not unreadable, f"tracked files the gate could not read: {unreadable[:5]}"


def test_ci_refuses_an_unconfigured_denylist_secret() -> None:
    """CI must not turn a missing publication policy into a green skip."""
    ci = (_SCRIPT.parents[1] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert '${AGENT_SUITE_FORBIDDEN_IDENTIFIERS//[[:space:]]/}' in ci
    assert "AGENT_SUITE_FORBIDDEN_IDENTIFIERS must be configured" in ci


def test_canonical_denylist_forbids_only_work_domain_identifiers() -> None:
    """The denylist must NOT contain the published identity or lab identifiers.

    Guards the *inverse* error, which has actually happened here: an earlier
    hand-rolled gate carried ``hraedon`` — the published author identity — in its
    denylist, and a later over-redaction pass clobbered legitimate lab references
    that had to be restored in a follow-up commit (``905f0bb``).

    Policy: the canonical denylist holds work-domain identifiers ONLY. Lab
    topology and the published identity are deliberately allowed in public repos,
    so an entry matching them would make the gate over-block — blocking honest
    work rather than protecting anything. Skips when the operator denylist is not
    present, since it cannot judge what it cannot read.
    """
    denylist_path = Path.home() / ".config" / "agent-suite" / "forbidden-identifiers"
    if not denylist_path.is_file():
        pytest.skip("canonical denylist not present locally")

    from scripts.check_committed_identifiers import parse_identifier_set

    identifiers = parse_identifier_set(denylist_path.read_text(encoding="utf-8"))
    # Substrings that mark an entry as lab/published-identity rather than work.
    allowed_markers = ("hraedon", "mvm")
    offenders = [
        i for i in identifiers if any(marker in i.lower() for marker in allowed_markers)
    ]
    assert not offenders, (
        "the canonical denylist contains allowed identifiers, which makes the gate "
        f"over-block: {offenders}. Lab topology and the published author identity "
        "are permitted in public repos; the denylist is work-domain-only."
    )


def test_ci_scans_commit_messages() -> None:
    """CI must scan commit messages, not only tracked file content.

    A mechanical control, in the spirit of the existing secret check: the message
    channel was unguarded everywhere until a public repo was found carrying
    work-domain identifiers in three commit messages. If the message-gate job is
    ever dropped or renamed away, this fails instead of the gap reopening
    silently. The full-history checkout is part of the contract — a shallow clone
    cannot resolve the push range.
    """
    ci = (_SCRIPT.parents[1] / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    assert "message-gate:" in ci, "the commit-message gate job must exist"
    assert "--rev-range" in ci, "CI must invoke the message-scanning mode"
    assert "fetch-depth: 0" in ci, "the message scan needs full history"


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


# ---------------------------------------------------------------------------
# Multi-word identifiers.
#
# The parser used to split unconditionally on whitespace, so a multi-word
# identifier could not be EXPRESSED: its halves became short tokens that the
# length filter dropped, and the denylist silently contained nothing. A real
# two-word work-domain name sat undetected in sixteen repositories — eight of
# them public — for months because of that. These tests pin both halves of the
# fix: the parser must keep a quoted phrase whole, and the matcher must catch
# every spelling a phrase turns up in.
# ---------------------------------------------------------------------------


def test_parse_identifier_set_keeps_quoted_phrase_whole() -> None:
    """A double-quoted entry survives as ONE multi-word identifier."""
    from scripts.check_committed_identifiers import parse_identifier_set

    identifiers = parse_identifier_set('"two words"  single-token')
    assert identifiers == frozenset({"two words", "single-token"}), identifiers


def test_unquoted_multiword_entry_still_splits() -> None:
    """Unquoted whitespace still separates tokens (the CI-secret form).

    Pins the compatibility half: the secret is a whitespace-separated list, and
    quoting is what opts an entry into phrase semantics. If this ever changed,
    every existing single-token denylist would silently become one long phrase
    that matches nothing.
    """
    from scripts.check_committed_identifiers import parse_identifier_set

    assert parse_identifier_set("host.example svc-account") == frozenset(
        {"host.example", "svc-account"}
    )


@pytest.mark.parametrize(
    "spelling",
    [
        "zzq phrase",  # as written
        "ZZQ Phrase",  # capitalized — the form that walked past the old gate
        "zzq-phrase",  # hyphenated
        "zzq_phrase",  # underscored
        "zzq.phrase",  # dotted
        "zzq  phrase",  # double-spaced
        "zzq\nphrase",  # wrapped across a line break by prose reflow
    ],
)
def test_phrase_matches_every_separator_spelling(spelling: str) -> None:
    """One phrase entry must catch every separator a phrase gets written with.

    The real leak survived a history scan because it appeared hyphenated in one
    place and capitalized in another. A matcher that only handles the literal
    spelling is a matcher that misses.
    """
    from scripts.check_committed_identifiers import parse_identifier_set, scan_text

    identifiers = parse_identifier_set('"zzq phrase"')
    violations = list(scan_text(f"prefix {spelling} suffix", identifiers))
    assert len(violations) == 1, f"{spelling!r} must match; got {violations}"
    assert violations[0].identifier == "zzq phrase"


def test_phrase_in_tracked_file_blocks_end_to_end(tmp_path: Path) -> None:
    """End-to-end: a phrase in a tracked file exits non-zero.

    The unit tests above prove the parser and matcher; this proves the wiring,
    because the leak's actual failure mode was a correct-looking gate that
    returned 0 on a tree containing the identifier.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "notes.md").write_text("the work-domain (Zzq Phrase) is named here\n")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    result = _run_gate(repo, env_secret='"zzq phrase"')
    assert result.returncode != 0, (
        f"phrase in a tracked file must block; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "notes.md" in _combined(result)


def test_unparseable_denylist_fails_closed() -> None:
    """An unbalanced quote must fail the gate, not silently drop entries.

    A denylist we cannot parse is a publication policy we cannot apply. Degrading
    to a partial token set would be the worst outcome: a green gate enforcing
    less than the operator declared.
    """
    from scripts.check_committed_identifiers import main, parse_identifier_set

    with pytest.raises(ValueError):
        parse_identifier_set('"unbalanced')

    import os

    os.environ["AGENT_SUITE_FORBIDDEN_IDENTIFIERS"] = '"unbalanced'
    try:
        assert main([]) == 1
    finally:
        os.environ.pop("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", None)


# ---------------------------------------------------------------------------
# WI-027 — the residual fails-open branches.
# ---------------------------------------------------------------------------


def test_unreadable_tracked_file_is_reported_not_skipped(tmp_path: Path) -> None:
    """An unreadable tracked file must fail the gate, not be silently skipped.

    Skipping means a file the gate could not read — which may contain a
    forbidden identifier — passes. The gate must never clear a tree it could not
    fully scan. Uses monkeypatched open rather than chmod 000, which is flaky
    under root and on Windows.
    """
    from scripts.check_committed_identifiers import scan_files

    target = tmp_path / "secret.md"
    target.write_text("harmless\n")

    def _boom(*_a: object, **_k: object) -> object:
        raise PermissionError("denied")

    import unittest.mock

    unreadable: list[Path] = []
    with unittest.mock.patch.object(Path, "open", _boom):
        violations = scan_files(frozenset({"zzq-token-abc"}), [target], unreadable=unreadable)
    assert violations == []
    assert unreadable == [target], "an unreadable file must be reported"


def test_symlink_target_is_scanned_not_followed(tmp_path: Path) -> None:
    """A tracked symlink's target string is scanned; the link is not followed.

    Two bugs in one: following a link either leaves the repo (scanning the wrong
    bytes) or fails on a broken link and reports a false "unreadable". And the
    target path itself can carry a forbidden identifier, so it must be scanned
    rather than skipped. Found live — a broken tracked symlink in a sibling repo
    surfaced as an unreadable-file failure.
    """
    from scripts.check_committed_identifiers import scan_files

    link = tmp_path / "link"
    link.symlink_to("../elsewhere/zzq-token-abc/skill")  # deliberately broken

    unreadable: list[Path] = []
    violations = scan_files(frozenset({"zzq-token-abc"}), [link], unreadable=unreadable)
    assert unreadable == [], "a broken symlink is not an unreadable file"
    assert len(violations) == 1, "a forbidden identifier in a symlink target must be caught"
    assert violations[0].path == link


def test_symlink_readlink_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OSError from os.readlink on a symlink must fail closed, not traceback.

    The symlink branch calls os.readlink, which can raise OSError (e.g.
    permission denied on the link inode). Before the fix this escaped as an
    unhandled traceback. The fix feeds the path through the same unreadable
    collector / GateError semantics as ordinary files.
    """
    from scripts.check_committed_identifiers import GateError, scan_files

    link = tmp_path / "link"
    link.symlink_to("target")

    def _deny_readlink(_path: object) -> str:
        raise OSError("denied")

    monkeypatch.setattr("os.readlink", _deny_readlink)
    with pytest.raises(GateError, match="could not be read"):
        scan_files(frozenset({"zzq-token-abc"}), [link])


def test_git_failure_exits_clean_not_traceback(tmp_path: Path) -> None:
    """A git command failure must exit 1 with a readable reason, not a traceback.

    Running the gate outside a work tree makes ``git ls-files`` fail. A CI gate
    that dies with CalledProcessError reads as broken infrastructure, which
    invites a re-run or a bypass; it must read as a blocked check.
    """
    result = _run_gate(tmp_path, env_secret="zzq-token-abc")
    assert result.returncode == 1, f"expected clean exit 1; got {result.returncode}"
    combined = _combined(result)
    assert "Traceback" not in combined, combined
    assert "identifier gate could not complete" in combined, combined


def test_staged_deletion_only_index_passes(tmp_path: Path) -> None:
    """A deletion-only index yields no paths and passes.

    ``--diff-filter=ACM`` excludes deletions because there is nothing to scan.
    That is correct, but it is also indistinguishable from a broken path
    collector, so pin it: removing a file must not be blocked by the gate.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "doomed.md").write_text("harmless content\n")
    subprocess.run(["git", "-C", str(repo), "add", "doomed.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)
    subprocess.run(["git", "-C", str(repo), "rm", "-q", "doomed.md"], check=True)

    result = _run_gate(repo, env_secret="zzq-token-abc", staged=True)
    assert result.returncode == 0, (
        f"deletion-only index must pass; got rc={result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_empty_and_short_denylist_messages_are_explicit(tmp_path: Path) -> None:
    """The two no-op branches must SAY they are skipping.

    Both return 0. If the message ever disappears, an unconfigured or unusable
    denylist becomes an invisible green pass — the exact failure the CI
    fail-closed wrapper exists to catch. Assert the operator-visible text.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "f.md").write_text("content\n")
    subprocess.run(["git", "-C", str(repo), "add", "f.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "t"], check=True)

    empty = _run_gate(repo, env_secret="   ")
    assert empty.returncode == 0
    assert "is empty or unset; skipping identifier gate" in _combined(empty)

    short = _run_gate(repo, env_secret="ab xyz")
    assert short.returncode == 0
    assert "no usable identifiers" in _combined(short)


def test_scan_files_returns_a_plain_list_for_copied_script_compat() -> None:
    """scan_files must return a LIST, not a tuple.

    This script is copied into every repo in the estate and several of them test
    scan_files directly. Returning a tuple to carry the unreadable-file list broke
    seven repositories' suites at once (`assert len(violations) == 1` became
    `assert 2 == 1`). The unreadable collector is an optional keyword out-param
    precisely so this signature stays stable; pin it.
    """
    from scripts.check_committed_identifiers import scan_files

    result = scan_files(frozenset({"zzq-token-abc"}), [])
    assert isinstance(result, list), f"scan_files must return a list, got {type(result)}"


def test_scan_files_fails_closed_when_unreadable_omitted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scan_files without unreadable= must raise GateError on an unreadable path.

    Before WI-027's fail-closed default, omitting the collector silently skipped
    unreadable files — a forbidden identifier inside one would pass undetected.
    The fix: scan_files owns an internal collector and raises GateError after
    scanning if it is non-empty. Callers that supply their own list (the CLI)
    still receive the paths without an exception.

    Uses monkeypatched Path.open rather than chmod 000 (flaky under root and on
    Windows).
    """
    from scripts.check_committed_identifiers import GateError, scan_files

    target = tmp_path / "secret.md"
    target.write_text("harmless\n")

    def _boom(*_a: object, **_k: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", _boom)
    with pytest.raises(GateError, match="could not be read"):
        scan_files(frozenset({"zzq-token-abc"}), [target])


def test_scan_files_caller_owned_collector_does_not_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Supplying unreadable= preserves the old contract: collect, don't raise.

    The CLI passes its own list so it can emit a detailed report. That path must
    NOT raise — the caller is responsible for acting on the collected paths.
    """
    from scripts.check_committed_identifiers import scan_files

    target = tmp_path / "secret.md"
    target.write_text("harmless\n")

    def _boom(*_a: object, **_k: object) -> object:
        raise PermissionError("denied")

    monkeypatch.setattr(Path, "open", _boom)
    unreadable: list[Path] = []
    violations = scan_files(frozenset({"zzq-token-abc"}), [target], unreadable=unreadable)
    assert violations == []
    assert unreadable == [target]


# ---------------------------------------------------------------------------
# WI-031 — the --staged scan must judge the index, not the working tree.
#
# A commit records the index. The pre-commit path used to collect staged PATHS
# from git but then read the worktree FILES at those paths, so any staged/
# worktree divergence (git add -p, staging then editing, deleting the worktree
# copy) made the gate judge bytes that were not being committed — hiding a
# staged forbidden blob behind a clean unstaged copy, and blocking clean
# commits behind a dirty one. Each case below plants a divergence and asserts
# the gate's verdict tracks the index side of it.
# ---------------------------------------------------------------------------


def test_staged_forbidden_blob_blocks_despite_clean_worktree(tmp_path: Path) -> None:
    """THE WI-031 bypass: stage forbidden content, overwrite the file with clean
    content, commit. The old gate scanned the clean worktree copy and passed the
    forbidden blob into history. The gate must judge what git will record."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    leaked = repo / "notes.md"
    leaked.write_text("token ZZS-INDEX-TOKEN-444 here\n")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)
    # Hide it: the worktree copy is clean, the index still holds the token.
    leaked.write_text("perfectly clean content\n")

    result = _run_gate(repo, env_secret="ZZS-INDEX-TOKEN-444", staged=True)
    assert result.returncode != 0, (
        f"a forbidden STAGED blob must block even when the worktree copy is clean; "
        f"got rc=0.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "notes.md" in _combined(result)


def test_clean_staged_blob_passes_despite_forbidden_worktree_edit(tmp_path: Path) -> None:
    """Inverse divergence: clean content staged, forbidden content in an
    UNSTAGED worktree edit. Nothing forbidden is being committed, so the gate
    must pass — blocking here is the over-block half of scanning the wrong tree."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "notes.md").write_text("perfectly clean content\n")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)
    # The forbidden token exists only in the worktree, not in the index.
    (repo / "notes.md").write_text("token ZZS-INDEX-TOKEN-444 here\n")

    result = _run_gate(repo, env_secret="ZZS-INDEX-TOKEN-444", staged=True)
    assert result.returncode == 0, (
        f"a clean index must pass regardless of unstaged worktree edits; "
        f"got rc={result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_staged_forbidden_blob_blocks_when_worktree_copy_is_deleted(tmp_path: Path) -> None:
    """Staged file deleted from the worktree: the blob is still committed, so it
    must still be scanned and blocked — not reported as an unreadable file."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "notes.md").write_text("token ZZS-INDEX-TOKEN-444 here\n")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)
    (repo / "notes.md").unlink()

    result = _run_gate(repo, env_secret="ZZS-INDEX-TOKEN-444", staged=True)
    assert result.returncode != 0
    combined = _combined(result)
    assert "ZZS-INDEX-TOKEN-444".lower() in combined.lower(), (
        f"the staged token must be reported as a violation, not an unreadable file:\n"
        f"{combined}"
    )


def test_clean_staged_blob_passes_when_worktree_copy_is_deleted(tmp_path: Path) -> None:
    """The other half of the deleted-worktree case: a CLEAN staged file whose
    worktree copy is gone must pass. The old gate failed it as unreadable —
    blocking a commit over a file it could in fact read from the index."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "notes.md").write_text("perfectly clean content\n")
    subprocess.run(["git", "-C", str(repo), "add", "notes.md"], check=True)
    (repo / "notes.md").unlink()

    result = _run_gate(repo, env_secret="ZZS-INDEX-TOKEN-444", staged=True)
    assert result.returncode == 0, (
        f"a clean staged blob must pass even with the worktree copy deleted; "
        f"got rc={result.returncode}.\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_staged_utf16_blob_with_forbidden_token_is_caught(tmp_path: Path) -> None:
    """The BOM sniff must apply to index blobs exactly as it does to files —
    UTF-16 staged content must not be misclassified binary and skipped."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "export.txt").write_text("leaked ZZS-UTF16-INDEX-222 here\n", encoding="utf-16")
    subprocess.run(["git", "-C", str(repo), "add", "export.txt"], check=True)
    # Divergence too: hide the worktree copy behind clean ASCII.
    (repo / "export.txt").write_text("clean\n")

    result = _run_gate(repo, env_secret="ZZS-UTF16-INDEX-222", staged=True)
    assert result.returncode != 0, (
        f"a UTF-16 staged blob with a forbidden token must be caught; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "export.txt" in _combined(result)


def test_staged_binary_blob_is_skipped_no_false_positive(tmp_path: Path) -> None:
    """The binary heuristic must apply to index blobs: a NUL-bearing staged blob
    is skipped, not scanned into a false positive or a crash."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "blob.bin").write_bytes(b"ZZS-BIN-INDEX-888\x00\x01\x02more bytes")
    subprocess.run(["git", "-C", str(repo), "add", "blob.bin"], check=True)

    result = _run_gate(repo, env_secret="ZZS-BIN-INDEX-888", staged=True)
    assert result.returncode == 0, (
        f"a binary staged blob must be skipped; got rc={result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_staged_symlink_target_scanned_from_index(tmp_path: Path) -> None:
    """A staged symlink's index blob is its target string and must be scanned —
    even when the worktree entry has been swapped for a clean regular file."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    link = repo / "link"
    link.symlink_to("../elsewhere/zzs-link-token-666/skill")
    subprocess.run(["git", "-C", str(repo), "add", "link"], check=True)
    # Swap the worktree entry: the index still records the symlink blob.
    link.unlink()
    link.write_text("clean regular file\n")

    result = _run_gate(repo, env_secret="zzs-link-token-666", staged=True)
    assert result.returncode != 0, (
        f"a forbidden identifier in a STAGED symlink target must block; got rc=0.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "zzs-link-token-666" in _combined(result)


def test_scan_staged_blobs_fails_closed_when_blob_unreadable(tmp_path: Path) -> None:
    """A staged path whose blob cannot be read must fail closed, matching the
    scan_files contract: collected when a list is supplied, GateError otherwise."""
    import os

    from scripts.check_committed_identifiers import GateError, scan_staged_blobs

    repo = tmp_path / "repo"
    _make_repo(repo)
    cwd = Path.cwd()
    os.chdir(repo)
    try:
        ghost = Path("never-staged.md")  # no such index entry: git show fails
        unreadable: list[Path] = []
        violations = scan_staged_blobs(
            frozenset({"zzq-token-abc"}), [ghost], unreadable=unreadable
        )
        assert violations == []
        assert unreadable == [ghost], "an unreadable staged blob must be reported"
        with pytest.raises(GateError, match="could not be read"):
            scan_staged_blobs(frozenset({"zzq-token-abc"}), [ghost])
    finally:
        os.chdir(cwd)


def test_gate_script_fits_100_cols_with_the_longest_fleet_env_var() -> None:
    """The script must stay under 100 columns AFTER per-repo substitution.

    ``sync-identifier-gate.sh`` rewrites ``AGENT_SUITE_FORBIDDEN_IDENTIFIERS``
    into a per-repo name, and some are much longer — 52 characters for
    ``SYSADMIN_COMPETENCE_EVALUATION_...`` against 33 canonical. That +19 pushed
    two message lines past the limit and reddened repositories whose CI lints the
    whole tree, even though the canonical file was clean. A template distributed
    by textual substitution has to budget for the longest substitution.
    """
    src = (_SCRIPT.parents[1] / "scripts" / "check_committed_identifiers.py").read_text(
        encoding="utf-8"
    )
    longest = "SYSADMIN_COMPETENCE_EVALUATION_FORBIDDEN_IDENTIFIERS"
    assert len(longest) >= 52, "keep this at least as long as the real worst case"
    substituted = src.replace("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", longest)
    over = [
        (n, len(line))
        for n, line in enumerate(substituted.splitlines(), start=1)
        if len(line) > 100
    ]
    assert not over, f"lines exceed 100 cols after substitution: {over}"
