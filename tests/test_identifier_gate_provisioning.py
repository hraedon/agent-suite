"""AC-58 artifact, inventory, drift, and read-only health integration."""
from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from agent_suite import identifier_gate as gate
from agent_suite.config import GitHubCredentialConfig
from tests.test_github_credentials import Sandbox, git
from tests.test_github_credentials import sandbox as sandbox  # pytest fixture


@pytest.mark.parametrize("removed", ["denylist", "hook", "gate", "unknown", "hooksPath"])
def test_ac58_3_working_auth_missing_guard_is_misprovisioned(
    sandbox: Sandbox, removed: str,
) -> None:
    sandbox.provision()
    if removed == "denylist":
        (sandbox.home / ".config/agent-suite/forbidden-identifiers").unlink()
    elif removed == "hook":
        (sandbox.repo / "githooks/pre-push").unlink()
    elif removed == "gate":
        (sandbox.repo / "scripts/check_committed_identifiers.py").unlink()
    elif removed == "unknown":
        (sandbox.repo / "scripts/check_committed_identifiers.py").write_text("unknown")
    else:
        git(sandbox.repo, "config", "core.hooksPath", "other-hooks")
    before = {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}
    health = sandbox.health()
    assert health.status == "MISPROVISIONED"
    assert not health.ok
    assert sandbox.working()
    assert before == {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}


def test_empty_inventory_is_misprovisioned_and_cannot_install(sandbox: Sandbox) -> None:
    sandbox.config = replace(sandbox.config, repositories=())
    with pytest.raises(gate.GateError, match="GITHUB_GATE_INVENTORY_EMPTY"):
        sandbox.provision()
    (sandbox.fake / "active").touch()
    assert sandbox.health().issues == ["no gate repository inventory", "denylist absent or unsafe"]
    assert sandbox.health().status == "MISPROVISIONED"


@pytest.mark.parametrize("artifact", ["denylist", "parent", "state"])
def test_unsafe_permissions_are_misprovisioned(sandbox: Sandbox, artifact: str) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    path = {"denylist": directory / "forbidden-identifiers", "parent": directory,
            "state": directory / "github-credential-state.json"}[artifact]
    path.chmod(0o755 if artifact == "parent" else 0o644)
    assert sandbox.health().status == "MISPROVISIONED"


def test_installed_and_secret_digest_rotation(sandbox: Sandbox) -> None:
    sandbox.provision()
    sandbox.denylist += "-rotated"
    assert "denylist stale digest" in sandbox.health().issues
    sandbox.provision()
    assert sandbox.health().status == "ok"
    path = sandbox.home / ".config/agent-suite/forbidden-identifiers"
    path.write_text(sandbox.denylist + "-tampered")
    assert "denylist recorded digest mismatch" in sandbox.health().issues


def test_absent_vs_unverified_helper_and_token_file(sandbox: Sandbox) -> None:
    assert sandbox.health().status == "absent"
    git(sandbox.repo, "config", "credential.helper", "example-helper")
    assert sandbox.health().status == "unverified"
    with pytest.raises(gate.GateError, match="GITHUB_AMBIENT_CREDENTIAL_UNVERIFIED"):
        sandbox.provision()
    git(sandbox.repo, "config", "--unset", "credential.helper")
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text("placeholder")
    assert sandbox.health().status == "unverified"


def test_ac58_7_canonical_variant_stale_unknown_missing(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()
    template = gate.load_template()
    assert gate.gate_state(sandbox.repo, template) == "canonical-at-pin"
    for name, value in (("accepted variant", next(iter(template.variants))),
                        ("stale", "93dec6f49825a3c2"), ("unknown", "a" * 16)):
        with monkeypatch.context() as patch:
            # Classification uses the shipped known sets. Collision fixtures
            # inject only the digest function; rendered behavior is tested elsewhere.
            patch.setattr(gate, "normalized_gate_hash", lambda _, value=value: value)
            assert gate.gate_state(sandbox.repo, template) == name
            assert sandbox.health().status == ("ok" if name == "accepted variant"
                                               else "MISPROVISIONED")
            if name in {"accepted variant", "unknown"}:
                before = (sandbox.repo / "scripts/check_committed_identifiers.py").read_bytes()
                with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
                    gate.install_gate(sandbox.repo, template)
                gate_path = sandbox.repo / "scripts/check_committed_identifiers.py"
                assert gate_path.read_bytes() == before
    path = sandbox.repo / "scripts/check_committed_identifiers.py"
    path.write_text("unknown")
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        sandbox.provision()
    sandbox.provision(force=True)
    assert sandbox.health().status == "ok"
    path.unlink()
    assert gate.gate_state(sandbox.repo, template) == "missing"


@pytest.mark.parametrize("target", ["lock", "snapshot"])
def test_ac58_4a_unknown_or_mismatched_template_refused(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str,
) -> None:
    data = tmp_path / "data"
    shutil.copytree(gate.DATA, data)
    path = data / ("gate-template.lock.json" if target == "lock"
                   else "gate-template/5233019/pre-push")
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(gate.GateError):
        gate.load_template(data)
    loader = gate.load_template
    monkeypatch.setattr(gate, "load_template", lambda: loader(data))
    with pytest.raises(gate.GateError):
        sandbox.provision()
    assert not sandbox.working()


def test_template_invalid_health_with_working_auth(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()

    def invalid() -> gate.GateTemplate:
        raise gate.GateError("GATE_TEMPLATE_INVALID")

    monkeypatch.setattr(gate, "load_template", invalid)
    with pytest.raises(gate.GateError, match="GATE_TEMPLATE_INVALID"):
        sandbox.provision()
    assert sandbox.health().status == "MISPROVISIONED"


def test_roots_enumerate_github_repos_and_external_worktrees(
    sandbox: Sandbox, tmp_path: Path,
) -> None:
    (sandbox.repo / "file").write_text("safe")
    git(sandbox.repo, "add", "file")
    git(sandbox.repo, "commit", "-qm", "initial")
    worktree = tmp_path / "external-worktree"
    git(sandbox.repo, "worktree", "add", "-qb", "test-branch", str(worktree))
    # Keep inventory discovery scoped to the root repo; registered worktrees
    # outside that root are still included and receive their own hooksPath.
    sandbox.config = replace(sandbox.config, repositories=(), roots=(sandbox.repo,))
    assert gate.repository_inventory(sandbox.config) == (sandbox.repo, worktree)
    sandbox.provision()
    assert len(sandbox.health().repositories) == 2
    assert sandbox.health().status == "ok"


def test_host_lock_prevents_overlapping_transactions(sandbox: Sandbox) -> None:
    failures: list[str] = []

    def overlap(_: str) -> None:
        try:
            sandbox.provision()
        except gate.GateError as exc:
            failures.append(str(exc))

    sandbox.provision(inject=overlap)
    assert failures == ["GITHUB_PROVISIONING_FAILED"] * 5
    assert sandbox.working()


def test_config_paths_with_spaces_and_invalid_inventory(sandbox: Sandbox) -> None:
    config = GitHubCredentialConfig.from_env({
        "AGENT_SUITE_GITHUB_REPOSITORIES": json.dumps([str(sandbox.repo / "with spaces")]),
    })
    assert config.repositories == (sandbox.repo / "with spaces",)
    with pytest.raises(ValueError):
        GitHubCredentialConfig.from_env({"AGENT_SUITE_GITHUB_REPOSITORIES": "not json"})


def test_provisioning_refuses_existing_readable_denylist(sandbox: Sandbox) -> None:
    sandbox.provision()
    (sandbox.fake / "active").unlink()
    denylist = sandbox.home / ".config/agent-suite/forbidden-identifiers"
    denylist.chmod(0o644)
    with pytest.raises(gate.GateError, match="GITHUB_DENYLIST_PERMISSIONS_INVALID"):
        sandbox.provision()
    assert not sandbox.working()


def test_malformed_inventory_with_working_auth_is_misprovisioned(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite.github_credentials import check_github_health
    (sandbox.fake / "active").touch()
    monkeypatch.setenv("AGENT_SUITE_GITHUB_REPOSITORIES", "not json")
    assert check_github_health(home=sandbox.home).status == "MISPROVISIONED"
