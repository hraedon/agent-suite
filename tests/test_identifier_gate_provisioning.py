"""AC-58 artifact, inventory, drift, and read-only health integration."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from agent_suite import github_credentials as credentials
from agent_suite import identifier_gate as gate
from agent_suite.config import GitHubCredentialConfig
from tests.test_github_credentials import Sandbox, git
from tests.test_github_credentials import sandbox as sandbox  # pytest fixture


@pytest.mark.parametrize("removed", ["denylist", "hook", "gate", "unknown", "hooksPath"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_3_working_auth_missing_guard_is_misprovisioned(
    sandbox: Sandbox,
    removed: str,
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_empty_inventory_is_misprovisioned_and_cannot_install(sandbox: Sandbox) -> None:
    sandbox.config = replace(sandbox.config, repositories=())
    with pytest.raises(gate.GateError, match="GITHUB_GATE_INVENTORY_EMPTY"):
        sandbox.provision()
    (sandbox.fake / "active").touch()
    assert sandbox.health().issues == [
        "no gate repository inventory", "GITHUB_STATE_REPROVISION_REQUIRED",
        "denylist absent or unsafe",
    ]
    assert sandbox.health().status == "MISPROVISIONED"


@pytest.mark.parametrize("artifact", ["denylist", "parent", "state"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_unsafe_permissions_are_misprovisioned(sandbox: Sandbox, artifact: str) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    path = {
        "denylist": directory / "forbidden-identifiers",
        "parent": directory,
        "state": directory / "github-credential-state.json",
    }[artifact]
    path.chmod(0o755 if artifact == "parent" else 0o644)
    assert sandbox.health().status == "MISPROVISIONED"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_installed_and_secret_digest_rotation(sandbox: Sandbox) -> None:
    sandbox.provision()
    sandbox.denylist += "-rotated"
    assert "denylist stale digest" in sandbox.health().issues
    sandbox.provision()
    assert sandbox.health().status == "ok"
    path = sandbox.home / ".config/agent-suite/forbidden-identifiers"
    path.write_text(sandbox.denylist + "-tampered")
    assert "denylist recorded digest mismatch" in sandbox.health().issues


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_absent_vs_unverified_helper_and_token_file(sandbox: Sandbox) -> None:
    assert sandbox.health().status == "absent"
    git(sandbox.repo, "config", "credential.helper", "example-helper")
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok
    assert sandbox.provision()["ok"]
    assert "git credential helper not inspected" in " ".join(sandbox.health().notes)
    credentials.run(("gh", "auth", "logout", "--hostname", "github.com"))
    git(sandbox.repo, "config", "--unset", "credential.helper")
    (sandbox.home / ".config/agent-suite/forbidden-identifiers").unlink()
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder")
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_7_canonical_variant_stale_unknown_missing(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()
    template = gate.load_template()
    assert gate.gate_state(sandbox.repo, template) == "canonical-at-pin"
    for name, value in (
        ("accepted variant (not the pinned canonical)", next(iter(template.variants))),
        ("stale", "93dec6f49825a3c2"),
        ("unknown", "a" * 16),
    ):
        with monkeypatch.context() as patch:
            # Classification uses the shipped known sets. Collision fixtures
            # inject only the digest function; rendered behavior is tested elsewhere.
            patch.setattr(gate, "normalized_gate_hash", lambda _, value=value: value)
            assert gate.gate_state(sandbox.repo, template) == name
            assert sandbox.health().status == (
                "ok" if name == "accepted variant (not the pinned canonical)" else "MISPROVISIONED"
            )
            if name in {"accepted variant (not the pinned canonical)", "unknown"}:
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
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_4a_unknown_or_mismatched_template_refused(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    target: str,
) -> None:
    data = tmp_path / "data"
    shutil.copytree(gate.DATA, data)
    path = data / (
        "gate-template.lock.json" if target == "lock" else "gate-template/5233019/pre-push"
    )
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(gate.GateError):
        gate.load_template(data)
    loader = gate.load_template
    monkeypatch.setattr(gate, "load_template", lambda: loader(data))
    with pytest.raises(gate.GateError):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_template_invalid_health_with_working_auth(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()

    def invalid() -> gate.GateTemplate:
        raise gate.GateError("GATE_TEMPLATE_INVALID")

    monkeypatch.setattr(gate, "load_template", invalid)
    assert sandbox.health().status == "MISPROVISIONED"
    with pytest.raises(gate.GateError, match="GATE_TEMPLATE_INVALID"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_roots_enumerate_github_repos_and_external_worktrees(
    sandbox: Sandbox,
    tmp_path: Path,
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


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_host_lock_prevents_overlapping_transactions(sandbox: Sandbox) -> None:
    failures: list[str] = []

    def overlap(_: str) -> None:
        try:
            sandbox.provision()
        except gate.GateError as exc:
            failures.append(str(exc))

    sandbox.provision(inject=overlap)
    assert failures == ["GITHUB_PROVISIONING_LOCKED"] * 5
    assert sandbox.working()


def test_config_paths_with_spaces_and_invalid_inventory(sandbox: Sandbox) -> None:
    config = GitHubCredentialConfig.from_env(
        {
            "AGENT_SUITE_GITHUB_REPOSITORIES": json.dumps([str(sandbox.repo / "with spaces")]),
        }
    )
    assert config.repositories == (sandbox.repo / "with spaces",)
    with pytest.raises(ValueError):
        GitHubCredentialConfig.from_env({"AGENT_SUITE_GITHUB_REPOSITORIES": "not json"})


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_provisioning_refuses_existing_readable_denylist(sandbox: Sandbox) -> None:
    denylist = sandbox.home / ".config/agent-suite/forbidden-identifiers"
    denylist.parent.mkdir(parents=True, mode=0o700)
    denylist.write_text(sandbox.denylist)
    denylist.chmod(0o644)
    with pytest.raises(gate.GateError, match="GITHUB_DENYLIST_PERMISSIONS_INVALID"):
        sandbox.provision()
    assert not sandbox.working()


def test_malformed_inventory_with_working_auth_is_misprovisioned(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite.github_credentials import check_github_health

    (sandbox.fake / "active").touch()
    monkeypatch.setenv("AGENT_SUITE_GITHUB_REPOSITORIES", "not json")
    assert check_github_health(home=sandbox.home).status == "MISPROVISIONED"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_explicit_repo_includes_linked_worktree_and_effective_hook(
    sandbox: Sandbox,
    tmp_path: Path,
) -> None:
    git(sandbox.repo, "commit", "--allow-empty", "-qm", "initial")
    worktree = tmp_path / "linked-worktree"
    git(sandbox.repo, "worktree", "add", "-qb", "linked", str(worktree))
    assert gate.repository_inventory(sandbox.config) == (sandbox.repo, worktree)
    sandbox.provision()
    assert (worktree / "githooks/pre-push").is_file()
    (worktree / "githooks/pre-push").unlink()
    assert not sandbox.health().ok
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_local_denylist_shadow_must_equal_host(sandbox: Sandbox) -> None:
    sandbox.provision()
    local = sandbox.repo / ".identifiers-denylist.local"
    local.write_text("decoy-only-identifier")
    assert not sandbox.health().ok
    with pytest.raises(gate.GateError, match="VERIFICATION_FAILED"):
        sandbox.provision()
    assert not sandbox.working()
    local.write_text(sandbox.denylist)
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_stub_venv_python_is_not_a_healthy_hook(sandbox: Sandbox) -> None:
    sandbox.provision()
    interpreter = sandbox.repo / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("#!/bin/sh\nexit 0\n")
    interpreter.chmod(0o755)
    assert not sandbox.health().ok
    with pytest.raises(gate.GateError, match="VERIFICATION_FAILED"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.parametrize(
    "remote",
    [
        "git@github-work:example/repo.git",
        "ssh://git@ssh.github.com:443/example/repo",
        "https://www.github.com/example/repo",
        "https://github.com./example/repo",
        "https://example.invalid/repo",
    ],
)
def test_roots_include_any_remote_strictly(sandbox: Sandbox, remote: str) -> None:
    git(sandbox.repo, "remote", "set-url", "origin", remote)
    config = replace(sandbox.config, repositories=(), roots=(sandbox.repo,))
    assert gate.repository_inventory(config) == (sandbox.repo,)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_existing_canonical_uses_actual_repository_name_and_variable(sandbox: Sandbox) -> None:
    template = gate.load_template()
    for source, destination, mode in template.manifest:
        content = template.payload[source].replace(b"@@REPO_NAME@@", sandbox.repo.name.encode())
        content = content.replace(b"@@DENYLIST_VAR@@", b"EXAMPLE_FORBIDDEN_IDENTIFIERS")
        gate.atomic_write(sandbox.repo / destination, content, mode)
    git(sandbox.repo, "config", "core.hooksPath", "githooks")
    assert gate.gate_state(sandbox.repo, template) == "canonical-at-pin"
    assert gate.hook_ok(sandbox.repo, template)
    before = (sandbox.repo / "githooks/pre-push").read_bytes()
    sandbox.provision()
    assert (sandbox.repo / "githooks/pre-push").read_bytes() == before


def test_denylist_parser_uses_verified_in_memory_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    template = gate.load_template()
    monkeypatch.setattr(gate, "DATA", Path("/nonexistent-template"))
    gate.validate_denylist(template, "example-denied-identifier")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_accepted_variant_requires_canonical_supporting_payloads(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()
    template = gate.load_template()
    variant = sandbox.repo / "scripts/check_committed_identifiers.py"
    variant.write_bytes(variant.read_bytes() + b"\n# fixture variant\n")
    template = replace(
        template, variants=frozenset({gate.normalized_gate_hash(variant.read_bytes())})
    )
    monkeypatch.setattr(gate, "load_template", lambda: template)
    health = sandbox.health()
    assert health.ok
    assert health.repositories[0]["gate"] == "accepted variant (not the pinned canonical)"
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        gate.install_gate(sandbox.repo, template)
    (sandbox.repo / "scripts/check_publication_plumbing.py").write_text("tampered")
    assert not sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_private_state_reads_use_nofollow_descriptor(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from agent_suite import github_credentials as credentials

    sandbox.provision()
    observed: list[int] = []
    original = os.open

    def record(path: object, flags: int, *args: object, **kwargs: object) -> int:
        observed.append(flags)
        return original(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", record)
    credentials._read_state(sandbox.home / ".config/agent-suite")
    assert any(flags & os.O_NOFOLLOW for flags in observed)


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX hook/denylist delivery",
)
def test_other_user_home_requires_own_denylist(sandbox: Sandbox, tmp_path: Path) -> None:
    from agent_suite import github_credentials as credentials

    sandbox.provision()
    other = tmp_path / "other-user-home"
    other.mkdir()
    health = credentials.check_github_health(
        sandbox.config, home=other, resolver=sandbox.resolve, gh_installed=True,
    )
    assert not health.ok
    assert "denylist absent or unsafe" in health.issues


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX hook/denylist delivery",
)
def test_unverified_credential_still_inspects_complete_guard(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import subprocess

    from agent_suite import github_credentials as credentials

    sandbox.provision()
    monkeypatch.setenv("GH_TOKEN", sandbox.token)
    health = credentials.check_github_health(
        sandbox.config, home=sandbox.home, resolver=sandbox.resolve, gh_installed=True,
        runner=lambda argv, stdin=None: subprocess.CompletedProcess(argv, 1, "", ""),
    )
    assert health.credential == "unverified"
    assert health.repositories and all(repo["ok"] for repo in health.repositories)
    assert health.ok


@pytest.mark.parametrize("kind", ["no-remote", "symlink", "nested"])
def test_r2_inventory_includes_every_push_capable_worktree(
    sandbox: Sandbox, tmp_path: Path, kind: str,
) -> None:
    root = tmp_path / "inventory"
    root.mkdir()
    extra = (tmp_path / "external" if kind == "symlink" else
             sandbox.repo / "module" if kind == "nested" else root / "no-remote")
    extra.mkdir()
    git(extra, "init", "-q")
    if kind == "symlink":
        if os.name == "nt":
            subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "linked"), str(extra)],
                           check=True, capture_output=True)
        else:
            (root / "linked").symlink_to(extra, target_is_directory=True)
    config = replace(sandbox.config, roots=(root,))
    assert extra.resolve() in gate.repository_inventory(config)


def test_r2_inventory_refuses_bare_repository(sandbox: Sandbox, tmp_path: Path) -> None:
    root = tmp_path / "inventory"
    root.mkdir()
    git(root, "init", "--bare", "-q", "bare.git")
    config = replace(sandbox.config, roots=(root,))
    with pytest.raises(gate.GateError, match="GATE_BARE_REPOSITORY_UNSUPPORTED"):
        gate.repository_inventory(config)


@pytest.mark.parametrize("autocrlf", ["true", "false", "input"])
def test_r2_template_checkout_is_byte_exact_with_any_autocrlf(
    tmp_path: Path, autocrlf: str,
) -> None:
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    git(checkout, "init", "-q")
    git(checkout, "config", "user.name", "Example")
    git(checkout, "config", "user.email", "author@example.invalid")
    git(checkout, "config", "core.autocrlf", autocrlf)
    git(checkout, "config", "core.safecrlf", "false")
    source = Path(__file__).parents[1]
    shutil.copyfile(source / ".gitattributes", checkout / ".gitattributes")
    data = checkout / "src/agent_suite/data"
    data.mkdir(parents=True)
    shutil.copyfile(gate.DATA / "gate-template.lock.json", data / "gate-template.lock.json")
    shutil.copytree(gate.DATA / "gate-template", data / "gate-template")
    git(checkout, "add", ".")
    git(checkout, "commit", "-qm", "fixture snapshot")
    for path in data.rglob("*"):
        if path.is_file():
            path.unlink()
    git(checkout, "checkout", "--", "src/agent_suite/data")
    assert gate.load_template(data).payload == gate.load_template().payload


def test_r2_explicit_repository_includes_initialized_submodule(
    sandbox: Sandbox, tmp_path: Path,
) -> None:
    source = tmp_path / "module-source"
    source.mkdir()
    git(source, "init", "-q")
    git(source, "config", "user.name", "Example")
    git(source, "config", "user.email", "author@example.invalid")
    (source / "README").write_text("fixture")
    git(source, "add", ".")
    git(source, "commit", "-qm", "module fixture")
    git(sandbox.repo, "-c", "protocol.file.allow=always", "submodule", "add",
        str(source), "modules/example")
    module = (sandbox.repo / "modules/example").resolve()
    assert module in gate.repository_inventory(sandbox.config)
    (sandbox.fake / "active").touch()
    health = sandbox.health()
    assert health.status == "MISPROVISIONED"
    assert any(repo["repository"] == str(module) and not repo["ok"]
               for repo in health.repositories)


def test_r2_inventory_directory_cycle_terminates(sandbox: Sandbox) -> None:
    root = sandbox.repo
    if os.name == "nt":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(root / "cycle"), str(root)],
                       check=True, capture_output=True)
    else:
        (root / "cycle").symlink_to(root, target_is_directory=True)
    assert gate.repository_inventory(replace(sandbox.config, roots=(root,))) == (root,)


@pytest.mark.parametrize(
    "entry", ["shlex.py", "argparse", "tomllib.pyi", "shlex.pyc", "__pycache__"],
)
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_script_shadow_or_bytecode_reds_health_and_provisioning(
    sandbox: Sandbox, entry: str,
) -> None:
    sandbox.provision()
    path = sandbox.repo / "scripts" / entry
    if entry in {"argparse", "__pycache__"}:
        path.mkdir()
    else:
        path.write_text("unused fixture")
    health = sandbox.health()
    assert health.status == "MISPROVISIONED"
    assert "GATE_SCRIPT_IMPORT_SHADOW" in json.dumps(health.to_dict())
    with pytest.raises(gate.GateError, match="GITHUB_GATE_VERIFICATION_FAILED"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_symlinked_githooks_directory_is_not_healthy(sandbox: Sandbox) -> None:
    sandbox.provision()
    hooks = sandbox.repo / "githooks"
    target = sandbox.repo / "actual-hooks"
    hooks.rename(target)
    hooks.symlink_to(target, target_is_directory=True)
    assert not gate.hook_ok(sandbox.repo, gate.load_template())
    assert not sandbox.health().ok


@pytest.mark.parametrize("hook", ["pre-push", "pre-commit"])
def test_r3_default_active_hooks_require_force(sandbox: Sandbox, hook: str) -> None:
    hooks = Path(git(sandbox.repo, "rev-parse", "--git-path", "hooks"))
    if not hooks.is_absolute():
        hooks = sandbox.repo / hooks
    path = hooks / hook
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    template = gate.load_template()
    with pytest.raises(gate.GateError, match="GATE_HOOK_OVERWRITE_REFUSED"):
        gate.check_hook_overwrite(sandbox.repo, template)
    gate.check_hook_overwrite(sandbox.repo, template, force=True)
    path.unlink()
    gate.check_hook_overwrite(sandbox.repo, template)


def test_r3_template_local_main_review_boundary_is_documented() -> None:
    contract = (Path(__file__).parents[1] / "docs/bootstrap-contract.md").read_text()
    assert "template repository has no remote" in contract
    assert "local main" in contract


@pytest.mark.parametrize("entry", ["json.md", "stat.sh", "shlex.txt", "utility.py"])
def test_r3_non_module_data_files_do_not_shadow_stdlib(sandbox: Sandbox, entry: str) -> None:
    scripts = sandbox.repo / "scripts"
    scripts.mkdir()
    (scripts / entry).write_text("unused fixture")
    assert gate.script_imports_ok(sandbox.repo)


@pytest.mark.parametrize("name", ["two words", "quoted'name", "dollar$name", "line\nname"])
def test_r4_render_refuses_unsafe_repository_name(sandbox: Sandbox, name: str) -> None:
    # Pure rendering: invalid Windows filenames need not exist on disk.
    with pytest.raises(gate.GateError, match="GATE_REPOSITORY_NAME_UNSAFE"):
        gate.load_template().render(sandbox.repo.parent / name)
