"""Execute pin 5233019; open items assert observed behavior, never skip/xfail.

A future pin closing one of these gaps must fail the corresponding observation
and force this registry and the bootstrap contract to be updated.
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agent_suite import identifier_gate as gate
from tests.test_github_credentials import Sandbox, git
from tests.test_github_credentials import sandbox as sandbox  # pytest fixture

OPEN_AC58_ITEMS = {
    "4": "pre-push and range scanner miss outgoing diff, author name and committer identity; "
         "no CI full-range installer or scheduled full-history job is in the artifact",
    "5": "pre-push passes without denylist; GATE_ALLOW_NO_DENYLIST opt-out is not implemented",
    "6": "tracked .venv files are skipped by the tree scan",
    "8-template-diagnostics": "pinned scanners print denylisted values in diagnostics",
}


def setup_public(sandbox: Sandbox) -> None:
    template = gate.load_template()
    gate.install_gate(sandbox.repo, template)
    gate.install_hook(sandbox.repo, template)
    (sandbox.repo / "publication.toml").write_text(
        '[publication]\nremote_owner = "example"\n'
        'author_email = "author@example.invalid"\nvisibility = "public"\n',
    )
    (sandbox.repo / "safe.txt").write_text("safe\n")
    git(sandbox.repo, "add", ".")
    git(sandbox.repo, "commit", "-qm", "clean base")


def scan(sandbox: Sandbox, *args: str, denylist: bool = True) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if denylist:
        env[gate.DENYLIST_VAR] = sandbox.denylist
    return subprocess.run(
        [sys.executable, str(sandbox.repo / "scripts/check_committed_identifiers.py"), *args],
        cwd=sandbox.repo, env=env, capture_output=True, text=True, check=False,
    )


def push(sandbox: Sandbox, base: str, *, denylist: bool = True,
         opt_out: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if denylist:
        env[gate.DENYLIST_VAR] = sandbox.denylist
    if opt_out:
        env["GATE_ALLOW_NO_DENYLIST"] = "1"
    head = git(sandbox.repo, "rev-parse", "HEAD")
    return subprocess.run(
        ["bash", str(sandbox.repo / "githooks/pre-push"), "origin",
         "https://github.com/example/repository.git"],
        input=f"refs/heads/main {head} refs/heads/main {base}\n",
        cwd=sandbox.repo, env=env, capture_output=True, text=True, check=False,
    )


@pytest.mark.parametrize("surface", ["diff", "message", "author", "committer"])
def test_ac58_4_pre_push_observation_not_satisfied_at_pin_5233019(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, surface: str,
) -> None:
    setup_public(sandbox)
    base = git(sandbox.repo, "rev-parse", "HEAD")
    if surface == "diff":
        (sandbox.repo / "safe.txt").write_text(sandbox.denylist)
    else:
        (sandbox.repo / "safe.txt").write_text("safe change")
    if surface == "author":
        monkeypatch.setenv("GIT_AUTHOR_NAME", sandbox.denylist)
    if surface == "committer":
        monkeypatch.setenv("GIT_COMMITTER_NAME", sandbox.denylist)
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", sandbox.denylist + "@example.invalid")
    git(sandbox.repo, "add", ".")
    git(sandbox.repo, "commit", "-qm", sandbox.denylist if surface == "message" else "safe message")
    result = push(sandbox, base)
    assert result.returncode == (1 if surface == "message" else 0)
    # Execute the provided scanner on the full history: only messages are read.
    history = scan(sandbox, "--rev-range", "HEAD")
    assert history.returncode == (1 if surface == "message" else 0)


def test_ac58_4_removed_diff_ci_full_range_not_satisfied_at_pin_5233019(sandbox: Sandbox) -> None:
    setup_public(sandbox)
    (sandbox.repo / "safe.txt").write_text(sandbox.denylist)
    git(sandbox.repo, "add", ".")
    git(sandbox.repo, "commit", "-qm", "historical change")
    (sandbox.repo / "safe.txt").write_text("clean again")
    git(sandbox.repo, "add", ".")
    git(sandbox.repo, "commit", "-qm", "clean tree")
    assert scan(sandbox).returncode == 0
    assert scan(sandbox, "--rev-range", "HEAD").returncode == 0
    assert not any("workflow" in destination for _, destination, _ in gate.load_template().manifest)
    assert not any("schedule" in destination for _, destination, _ in gate.load_template().manifest)


@pytest.mark.parametrize("opt_out", [False, True])
def test_ac58_5_missing_denylist_not_satisfied_at_pin_5233019(
    sandbox: Sandbox, opt_out: bool,
) -> None:
    setup_public(sandbox)
    git(sandbox.repo, "commit", "--allow-empty", "-qm", "safe outgoing message")
    result = push(sandbox, "HEAD~1", denylist=False, opt_out=opt_out)
    assert result.returncode == 0
    assert "INACTIVE" in result.stderr
    assert "GATE_ALLOW_NO_DENYLIST" not in result.stderr
    # The scanner itself fails closed; the pinned hook does not call it.
    assert scan(sandbox, "--rev-range", "HEAD", denylist=False).returncode == 1


def test_ac58_6_tracked_venv_not_satisfied_at_pin_5233019(sandbox: Sandbox) -> None:
    setup_public(sandbox)
    directory = sandbox.repo / ".venv"
    directory.mkdir()
    (directory / "tracked.txt").write_text(sandbox.denylist)
    git(sandbox.repo, "add", "-f", ".venv/tracked.txt")
    assert ".venv/tracked.txt" in git(sandbox.repo, "ls-files")
    assert scan(sandbox).returncode == 0
    assert scan(sandbox, "--staged").returncode == 0


def test_ac58_8_template_diagnostics_not_satisfied_at_pin_5233019(sandbox: Sandbox) -> None:
    setup_public(sandbox)
    (sandbox.repo / "safe.txt").write_text(sandbox.denylist)
    git(sandbox.repo, "add", ".")
    git(sandbox.repo, "commit", "-qm", sandbox.denylist)
    for result in (scan(sandbox), scan(sandbox, "--rev-range", "HEAD"),
                   push(sandbox, "HEAD~1")):
        assert result.returncode == 1
        assert sandbox.denylist in result.stderr


@pytest.mark.parametrize(("visibility", "expected"), [
    ("public", 1), ("Public", 1), ("pubilc", 1), ("private-until-review", 0),
])
def test_ac58_9_visibility_probe_empty_home(
    sandbox: Sandbox, visibility: str, expected: int,
) -> None:
    setup_public(sandbox)
    (sandbox.repo / "publication.toml").write_text(
        f'[publication]\nvisibility = "{visibility}"\n',
    )
    assert scan(sandbox, denylist=False).returncode == expected


def test_ac58_4a_vendor_reads_commit_and_refuses_dirty_or_short_sha(
    tmp_path: Path,
) -> None:
    script = Path(__file__).parents[1] / "scripts/vendor-gate-template.py"
    spec = importlib.util.spec_from_file_location("vendor_gate", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Example")
    git(source, "config", "user.email", "author@example.invalid")
    payload = gate.load_template().payload
    for name, value in payload.items():
        (source / name).write_bytes(value)
    git(source, "add", ".")
    git(source, "commit", "-qm", "pinned template")
    commit = git(source, "rev-parse", "HEAD")
    destination = tmp_path / "vendored"
    module.vendor(source, commit, destination)
    for name, value in payload.items():
        assert (destination / "gate-template" / commit[:7] / name).read_bytes() == value
    with pytest.raises(ValueError, match="full commit SHA"):
        module.vendor(source, commit[:7], destination)
    (source / "pre-push").write_text("unreviewed")
    with pytest.raises(ValueError, match="dirty template"):
        module.vendor(source, commit, destination)
    git(source, "add", ".")
    git(source, "commit", "-qm", "new clean revision")
    # A different clean HEAD is permitted: payloads are still read at the COMMIT.
    module.vendor(source, commit, destination)
    vendored_hook = destination / "gate-template" / commit[:7] / "pre-push"
    assert vendored_hook.read_bytes() == payload["pre-push"]
    (source / "check_committed_identifiers.py").write_text("unrecognized gate")
    git(source, "add", ".")
    git(source, "commit", "-qm", "unknown digest")
    with pytest.raises(ValueError, match="unrecognized template digest"):
        module.vendor(source, git(source, "rev-parse", "HEAD"), destination)


@pytest.mark.parametrize("state", ["dirty", "unpinned", "not-git"])
def test_ac58_4a_pinned_sync_refuses_bad_template_source(
    sandbox: Sandbox, tmp_path: Path, state: str,
) -> None:
    source = tmp_path / "template"
    source.mkdir()
    for name, content in gate.load_template().payload.items():
        (source / name).write_bytes(content)
    if state != "not-git":
        git(source, "init", "-q")
        git(source, "config", "user.name", "Example")
        git(source, "config", "user.email", "author@example.invalid")
        git(source, "add", ".")
        git(source, "commit", "-qm", "clean template")
        if state == "dirty":
            (source / "pre-push").write_text("dirty hook")
        else:
            (source / "check_committed_identifiers.py").write_text("unknown digest")
            git(source, "add", ".")
            git(source, "commit", "-qm", "unpinned digest")
    result = subprocess.run(
        ["bash", str(source / "sync-identifier-gate.sh"), "--check", str(sandbox.repo)],
        env={**os.environ, "GATE_TEMPLATE_DIR": str(source)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 2
    message = {"dirty": "uncommitted", "unpinned": "not pinned", "not-git": "not a git"}
    assert message[state] in result.stderr
    assert sandbox.calls() == []
