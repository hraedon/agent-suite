"""Behavioral deny-tests for the pre-push publication plumbing guard (WI-019).

The content denylist answers "may these bytes be published". This guard answers
"may this repository be published *here*, by *this* identity, at *this*
visibility" — the plumbing accident class that content scanning cannot see.

Every test here plants a known-bad plumbing state and asserts the guard REFUSES.
A guard is only worth its runtime if there is a test proving it blocks; the
alternative is the failure mode this whole work item came from — a correct-looking
gate returning success on a state it was supposed to stop.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_publication_plumbing.py"

_DECLARATION = """
[publication]
remote_owner = "expected-owner"
author_email = "expected@example.com"
visibility = "public"
"""


def _make_repo(repo: Path, *, email: str = "expected@example.com") -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", email], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "f.md").write_text("content\n")
    subprocess.run(["git", "-C", str(repo), "add", "f.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True)


def _run(
    repo: Path, remote_url: str, *, rev_range: str | None = None
) -> subprocess.CompletedProcess[str]:
    argv = [sys.executable, str(_SCRIPT), "--remote-url", remote_url, "--repo-root", str(repo)]
    if rev_range:
        argv += ["--rev-range", rev_range]
    return subprocess.run(
        argv, cwd=repo, capture_output=True, text=True, timeout=30, check=False
    )


def test_missing_declaration_is_a_noop(tmp_path: Path) -> None:
    """No publication.toml -> skip. Must not brick a repo that has not opted in."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    result = _run(repo, "https://github.com/anyone/anything.git")
    assert result.returncode == 0
    assert "skipping" in result.stderr


def test_wrong_remote_owner_is_refused(tmp_path: Path) -> None:
    """Pushing to an owner other than the declared one must be refused.

    This is the "pushed the private repo to the wrong account" accident.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(_DECLARATION)

    result = _run(repo, "https://github.com/someone-else/repo.git")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "remote owner mismatch" in result.stderr
    assert "someone-else" in result.stderr


def test_expected_remote_owner_passes(tmp_path: Path) -> None:
    """The happy path must actually pass, or the guard would just block everything."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(_DECLARATION)

    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:expected-owner/repo.git",
        "ssh://git@github.com/expected-owner/repo.git",
        "https://github.com/expected-owner/repo",
        "https://github.com/expected-owner/repo.git",
    ],
)
def test_owner_parsed_from_every_remote_url_shape(tmp_path: Path, url: str) -> None:
    """ssh, scp-style, and https remotes must all resolve to the same owner.

    A parser that only understands https would silently skip the check for an ssh
    remote — a fails-open that looks identical to a pass.
    """
    from scripts.check_publication_plumbing import parse_remote_owner

    assert parse_remote_owner(url) == "expected-owner"


def test_unparseable_remote_url_is_refused(tmp_path: Path) -> None:
    """An unrecognized remote shape must refuse, not guess."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(_DECLARATION)

    result = _run(repo, "not-a-url")
    assert result.returncode == 1
    assert "could not parse an owner" in result.stderr


def test_wrong_author_email_is_refused(tmp_path: Path) -> None:
    """A commit authored by an unexpected identity must be refused.

    The multi-identity-box accident: right code, wrong signature, published
    permanently.
    """
    repo = tmp_path / "repo"
    _make_repo(repo, email="wrong-identity@example.com")
    (repo / "publication.toml").write_text(_DECLARATION)

    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "author identity mismatch" in result.stderr
    assert "wrong-identity@example.com" in result.stderr


def test_author_check_covers_every_commit_in_range(tmp_path: Path) -> None:
    """A wrong-identity commit buried mid-branch must be caught, not just HEAD.

    Checking only the tip would miss it, and it gets published just the same.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(_DECLARATION)
    base = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    # A bad-identity commit, then a good one on top.
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "sneaky@example.com"], check=True
    )
    (repo / "mid.md").write_text("mid\n")
    subprocess.run(["git", "-C", str(repo), "add", "mid.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "mid"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "expected@example.com"], check=True
    )
    (repo / "tip.md").write_text("tip\n")
    subprocess.run(["git", "-C", str(repo), "add", "tip.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "tip"], check=True)

    result = _run(repo, "https://github.com/expected-owner/repo.git", rev_range=f"{base}..HEAD")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "sneaky@example.com" in result.stderr


def test_malformed_declaration_fails_closed(tmp_path: Path) -> None:
    """An unparseable declaration must fail the push, not be ignored.

    Distinct from a MISSING declaration (a deliberate no-op): a present but
    broken declaration means the operator intended a policy we cannot read.
    """
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text("[publication\nbroken = ")

    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 1
    assert "Traceback" not in result.stderr
    assert "could not be parsed" in result.stderr


def test_declaration_missing_keys_fails_closed(tmp_path: Path) -> None:
    """A partial declaration must refuse rather than check only what is present."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text('[publication]\nremote_owner = "expected-owner"\n')

    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 1
    assert "missing" in result.stderr


def test_invalid_visibility_value_fails_closed(tmp_path: Path) -> None:
    """An unknown visibility state must refuse; the set is closed by design."""
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(
        '[publication]\nremote_owner = "expected-owner"\n'
        'author_email = "expected@example.com"\nvisibility = "sort-of-private"\n'
    )

    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 1
    assert "expected one of" in result.stderr


def _declare(repo: Path, visibility: str) -> None:
    (repo / "publication.toml").write_text(
        '[publication]\nremote_owner = "expected-owner"\n'
        f'author_email = "expected@example.com"\nvisibility = "{visibility}"\n'
    )


def test_private_until_review_refuses_a_public_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The headline case: a private-until-review repo must not go to a public remote.

    Exercised in-process with the visibility lookup patched, rather than by
    stubbing a `gh` executable on PATH. The stub approach only worked on POSIX —
    a shell-script stub is not executable on Windows, so `gh` resolved to nothing,
    the guard took its "cannot verify" path, and the test passed vacuously on
    Linux while failing on Windows. Patching the seam tests the actual decision on
    every platform.
    """
    import scripts.check_publication_plumbing as plumbing

    repo = tmp_path / "repo"
    _make_repo(repo)
    _declare(repo, "private-until-review")
    monkeypatch.setattr(plumbing, "remote_visibility", lambda owner, name: "PUBLIC")

    problems = plumbing.check(repo, "https://github.com/expected-owner/repo.git", None)
    assert any("visibility mismatch" in p for p in problems), problems


def test_private_until_review_allows_a_private_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same declaration must PASS when the remote really is private."""
    import scripts.check_publication_plumbing as plumbing

    repo = tmp_path / "repo"
    _make_repo(repo)
    _declare(repo, "private-until-review")
    monkeypatch.setattr(plumbing, "remote_visibility", lambda owner, name: "PRIVATE")

    assert plumbing.check(repo, "https://github.com/expected-owner/repo.git", None) == []


def test_public_declaration_skips_the_visibility_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A repo declared public must not be blocked by a public remote.

    Pins the other half of the match: were the arms ever swapped, an already-public
    repo would refuse every push.
    """
    import scripts.check_publication_plumbing as plumbing

    repo = tmp_path / "repo"
    _make_repo(repo)
    _declare(repo, "public")

    def _boom(owner: str, name: str) -> str:
        raise AssertionError("visibility must not be consulted for a public declaration")

    monkeypatch.setattr(plumbing, "remote_visibility", _boom)
    assert plumbing.check(repo, "https://github.com/expected-owner/repo.git", None) == []


def test_unverifiable_visibility_warns_and_allows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With visibility unverifiable the guard must SAY so, and allow the push.

    Blocking would make every offline push impossible; passing silently would be a
    guard that lies. It must pass loudly.
    """
    import scripts.check_publication_plumbing as plumbing

    repo = tmp_path / "repo"
    _make_repo(repo)
    _declare(repo, "private-until-review")
    monkeypatch.setattr(plumbing, "remote_visibility", lambda owner, name: None)

    assert plumbing.check(repo, "https://github.com/expected-owner/repo.git", None) == []
    assert "could not verify remote visibility" in capsys.readouterr().err


def test_remote_visibility_returns_none_without_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    """The lookup itself degrades to None when gh is absent, rather than raising."""
    import scripts.check_publication_plumbing as plumbing

    monkeypatch.setattr(plumbing.shutil, "which", lambda name: None)
    assert plumbing.remote_visibility("owner", "repo") is None


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="githooks/pre-push is a bash script; git invokes it via Git-Bash, "
    "but pytest cannot exec it directly on Windows (WinError 193). The logic it "
    "wraps is covered cross-platform by the rev-range tests above.",
)
def test_pre_push_hook_survives_a_rewritten_remote_sha(tmp_path: Path) -> None:
    """A force-push after a history rewrite must not be blocked forever.

    After git-filter-repo (or a rebase/amend) the remote's sha is no longer
    reachable locally, so ``<remote_sha>..<local_sha>`` is an invalid range and
    the scanners fail closed — refusing every force-push. A publication scrub is
    precisely when force-pushing must still work, so an unreachable remote sha is
    treated like a new branch.

    Found by dogfooding: this hook blocked the first real scrub push.
    """
    repo_root = _SCRIPT.parents[1]
    repo = tmp_path / "repo"
    _make_repo(repo)
    (repo / "publication.toml").write_text(_DECLARATION)
    for name in ("check_committed_identifiers.py", "check_publication_plumbing.py"):
        (repo / "scripts").mkdir(exist_ok=True)
        (repo / "scripts" / name).write_text((repo_root / "scripts" / name).read_text())
    (repo / "githooks").mkdir(exist_ok=True)
    hook = repo / "githooks" / "pre-push"
    hook.write_text((repo_root / "githooks" / "pre-push").read_text())
    hook.chmod(0o755)

    local_sha = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    # A syntactically valid sha that does not exist in this repo — exactly what a
    # rewritten remote head looks like from the client's side.
    unreachable = "1" * 40

    result = subprocess.run(
        [str(hook), "origin", "https://github.com/expected-owner/repo.git"],
        cwd=repo,
        input=f"refs/heads/main {local_sha} refs/heads/main {unreachable}\n",
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, (
        "an unreachable remote sha must not block the push\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "Invalid revision range" not in result.stderr


def test_this_repo_declares_publication_plumbing() -> None:
    """agent-suite itself must carry a valid declaration.

    Dogfood: the guard is worthless if the repo shipping it has not declared its
    own expected plumbing.
    """
    from scripts.check_publication_plumbing import load_declaration

    declaration = load_declaration(_SCRIPT.parents[1])
    assert declaration is not None, "agent-suite must have a publication.toml"
    assert declaration.remote_owner == "hraedon"
    assert declaration.author_emails, "at least one author identity must be declared"


def test_multiple_declared_author_identities_are_all_accepted(tmp_path: Path) -> None:
    """author_email may be a list, and every listed identity must pass.

    Not a convenience: a repo with real history legitimately carries several
    identities (a web-UI commit lands as <user>@users.noreply.github.com). A
    single-identity field forces either a false refusal on honest history or no
    check at all. Found live — the guard refused a real scrub push over a
    second, legitimate identity.
    """
    repo = tmp_path / "repo"
    _make_repo(repo, email="web-ui@users.noreply.github.com")
    (repo / "publication.toml").write_text(
        '[publication]\nremote_owner = "expected-owner"\n'
        'author_email = ["expected@example.com", "web-ui@users.noreply.github.com"]\n'
        'visibility = "public"\n'
    )
    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 0, result.stdout + result.stderr


def test_identity_outside_the_declared_list_is_still_refused(tmp_path: Path) -> None:
    """Widening to a list must not weaken the check into a no-op."""
    repo = tmp_path / "repo"
    _make_repo(repo, email="stranger@example.com")
    (repo / "publication.toml").write_text(
        '[publication]\nremote_owner = "expected-owner"\n'
        'author_email = ["a@example.com", "b@example.com"]\n'
        'visibility = "public"\n'
    )
    result = _run(repo, "https://github.com/expected-owner/repo.git")
    assert result.returncode == 1, result.stdout + result.stderr
    assert "stranger@example.com" in result.stderr
