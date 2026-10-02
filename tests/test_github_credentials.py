"""AC-58 transaction tests: isolated HOME, Git config and executable fake gh."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_suite import github_credentials as credentials
from agent_suite import identifier_gate as gate
from agent_suite.config import GitHubCredentialConfig


@dataclass
class Sandbox:
    home: Path
    repo: Path
    config: GitHubCredentialConfig
    denylist: str
    token: str
    fake: Path

    def resolve(self, ref: str) -> str:
        if ref == self.config.denylist_ref:
            return self.denylist
        if ref == self.config.token_ref:
            return self.token
        raise ValueError("unexpected ref")

    def provision(self, **kwargs: object) -> dict[str, object]:
        return credentials.provision_github_credential(
            self.config, home=self.home, resolver=self.resolve, **kwargs,  # type: ignore[arg-type]
        )

    def health(self) -> credentials.GitHubHealth:
        return credentials.check_github_health(
            self.config, home=self.home, resolver=self.resolve, gh_installed=True,
        )

    def calls(self) -> list[list[str]]:
        log = self.fake / "calls"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def working(self) -> bool:
        return (self.fake / "active").exists()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    for key in list(os.environ):
        if key in {"GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GIT_CONFIG_COUNT",
                   "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE"} or (
            "FORBIDDEN_IDENTIFIERS" in key or key.startswith("AGENT_SUITE_GITHUB_")
            or key.startswith("GIT_CONFIG_KEY_") or key.startswith("GIT_CONFIG_VALUE_")
        ):
            monkeypatch.delenv(key)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home / ".config"))
    monkeypatch.setenv("GH_CONFIG_DIR", str(home / ".config/gh"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("AGENT_SUITE_CONFIG", str(home / "suite.env"))
    fake = tmp_path / "fake"
    fake.mkdir()
    token = "throwaway-token-" + uuid.uuid4().hex
    denylist = "throwaway-identifier-" + uuid.uuid4().hex
    (fake / "secret-input").write_text(token)
    (fake / "gh").write_text(f"#!{sys.executable}\n" + '''
import hashlib
import json
import pathlib
import sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps(args) + "\\n")
active = root / "active"
if args[:2] == ["auth", "login"]:
    value = sys.stdin.read().strip()
    if value != (root / "secret-input").read_text():
        sys.exit(1)
    active.write_text(hashlib.sha256(value.encode()).hexdigest())
    print(value)
    print(value, file=sys.stderr)
    if (root / "fail-login").exists():
        sys.exit(1)
elif args[:2] == ["auth", "logout"]:
    active.unlink(missing_ok=True)
elif args[:2] == ["auth", "token"]:
    if not active.exists():
        sys.exit(1)
    print((root / "secret-input").read_text())
elif args[:2] == ["auth", "status"]:
    if not active.exists():
        sys.exit(1)
    print("Token scopes: 'repo', 'workflow'")
else:
    sys.exit(2)
''')
    (fake / "gh").chmod(0o755)
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + os.environ["PATH"])
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Example Author")
    git(repo, "config", "user.email", "author@example.invalid")
    git(repo, "remote", "add", "origin", "https://github.com/example/repository.git")
    config = GitHubCredentialConfig("env:TEST_GITHUB_TOKEN", "env:TEST_GATE_DENYLIST",
                                    repositories=(repo,))
    return Sandbox(home, repo, config, denylist, token, fake)


def test_ac58_1_fresh_host_and_rerun(sandbox: Sandbox) -> None:
    assert sandbox.provision()["credential"] == "installed"
    assert sandbox.health().status == "ok"
    assert sandbox.health().repositories[0]["gate"] == "canonical-at-pin"
    directory = sandbox.home / ".config/agent-suite"
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ("forbidden-identifiers", "github-credential-state.json"):
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert sandbox.provision()["credential"] == "ambient; not adopted"
    assert sum(call[:2] == ["auth", "login"] for call in sandbox.calls()) == 1


@pytest.mark.parametrize("step", credentials.PLAN)
def test_ac58_2_failure_after_each_step_and_convergence(sandbox: Sandbox, step: str) -> None:
    visited: list[str] = []

    def fail(current: str) -> None:
        visited.append(current)
        if current == step:
            raise RuntimeError(sandbox.token + sandbox.denylist)

    with pytest.raises(gate.GateError, match="GITHUB_PROVISIONING_FAILED"):
        sandbox.provision(inject=fail)
    assert visited == list(credentials.PLAN[:credentials.PLAN.index(step) + 1])
    assert not sandbox.working()
    if step == "credential":
        assert ["auth", "logout", "--hostname", "github.com"] in sandbox.calls()
    sandbox.provision()
    assert sandbox.health().status == "ok"


def test_partial_failed_login_is_removed(sandbox: Sandbox) -> None:
    (sandbox.fake / "fail-login").touch()
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_INSTALL_FAILED"):
        sandbox.provision()
    assert not sandbox.working()


def test_crash_recovery_before_next_transaction(sandbox: Sandbox) -> None:
    sandbox.provision()
    state_path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    state = json.loads(state_path.read_text())
    state["credential_phase"] = "installing"
    state_path.write_text(json.dumps(state))
    sandbox.provision()
    assert sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


def test_ambient_credential_is_never_adopted_or_revoked(sandbox: Sandbox) -> None:
    (sandbox.fake / "active").write_text("ambient")
    with pytest.raises(gate.GateError):
        sandbox.provision(inject=lambda _: (_ for _ in ()).throw(ValueError("fail")))
    assert sandbox.working()
    assert not any(call[:2] in (["auth", "login"], ["auth", "logout"])
                   for call in sandbox.calls())
    assert sandbox.provision()["credential"] == "ambient; not adopted"
    state_path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    state = json.loads(state_path.read_text())
    assert "token_sha256" not in state


def test_dry_run_has_only_plan_and_no_mutations(sandbox: Sandbox) -> None:
    before = {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}
    assert sandbox.provision(dry_run=True) == {
        "ok": True, "dry_run": True, "plan": list(credentials.PLAN),
    }
    assert before == {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}
    assert sandbox.calls() == []
    assert not (sandbox.repo / "scripts").exists()


@pytest.mark.parametrize("adapter", ["app-token", "deploy-key", "ssh-key"])
def test_unsupported_adapters_refuse(sandbox: Sandbox, adapter: str) -> None:
    from dataclasses import replace
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_ADAPTER_UNSUPPORTED"):
        credentials.provision_github_credential(replace(sandbox.config, adapter=adapter))
    assert sandbox.calls() == []


@pytest.mark.parametrize("value", ["", "abc", '"unterminated'])
def test_pinned_parser_refuses_empty_short_or_invalid_denylist(
    sandbox: Sandbox, value: str,
) -> None:
    sandbox.denylist = value
    with pytest.raises(gate.GateError, match="GITHUB_DENYLIST_INVALID"):
        sandbox.provision()
    assert not sandbox.working()


def test_ac58_8_all_suite_surfaces_do_not_leak(
    sandbox: Sandbox, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    from agent_suite.cli import main
    from agent_suite.doctor import SuiteReport, format_text
    monkeypatch.setattr(credentials, "resolve_secret_value", sandbox.resolve)
    monkeypatch.setenv("AGENT_SUITE_GITHUB_TOKEN_REF", sandbox.config.token_ref or "")
    monkeypatch.setenv("AGENT_SUITE_GITHUB_DENYLIST_REF", sandbox.config.denylist_ref or "")
    monkeypatch.setenv("AGENT_SUITE_GITHUB_REPOSITORIES", json.dumps([str(sandbox.repo)]))
    # The default argument was bound at import, so use the real reference resolver
    # through a fake regista executable returning only this fixture's values.
    monkeypatch.setenv("TEST_GITHUB_TOKEN", sandbox.token)
    monkeypatch.setenv("TEST_GATE_DENYLIST", sandbox.denylist)
    (sandbox.fake / "regista").write_text(f"#!{sys.executable}\n" + '''
import os
import sys
print(os.environ[sys.argv[-1].split(":", 1)[1]])
''')
    (sandbox.fake / "regista").chmod(0o755)
    documents: list[str] = []
    for flags in (["--dry-run"], ["--dry-run", "--json"], [], ["--json"]):
        assert main(["bootstrap", "--github-credential", *flags]) == 0
        captured = capsys.readouterr()
        documents.extend([captured.out, captured.err])
    from agent_suite import doctor
    health = sandbox.health()
    monkeypatch.setattr(doctor, "aggregate", lambda **_: doctor.SuiteReport(
        True, [], github_health=health,
    ))
    for flags in ([], ["--json"]):
        assert main(["doctor", *flags]) == 0
        captured = capsys.readouterr()
        documents.extend([captured.out, captured.err])
    (sandbox.fake / "active").unlink()
    (sandbox.fake / "fail-login").touch()
    for flags in ([], ["--json"]):
        assert main(["bootstrap", "--github-credential", *flags]) == 1
        captured = capsys.readouterr()
        documents.extend([captured.out, captured.err])
    documents.append(json.dumps(health.to_dict()))
    documents.append(format_text(SuiteReport(True, [], github_health=health)))
    documents.append(json.dumps(sandbox.calls()))
    documents.extend(p.read_text() for p in (sandbox.home / ".config/agent-suite").glob("*state*"))
    for surface in documents:
        assert sandbox.token not in surface
        assert sandbox.denylist not in surface
    assert ["auth", "login", "--hostname", "github.com", "--with-token"] in sandbox.calls()


def test_rollback_refuses_to_revoke_replaced_ambient_credential(sandbox: Sandbox) -> None:
    def replaced(step: str) -> None:
        if step == "credential":
            (sandbox.fake / "secret-input").write_text("different-ambient-credential")
            raise RuntimeError("fail after credential replaced")

    with pytest.raises(gate.GateError, match="GITHUB_ROLLBACK_OWNERSHIP_MISMATCH"):
        sandbox.provision(inject=replaced)
    assert sandbox.working()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


def test_readonly_scope_and_unknown_capability_are_named(sandbox: Sandbox) -> None:
    import subprocess

    for output, detail in (("Token scopes: 'read_org'", "push scope unavailable"),
                           ("authenticated", "push capability unverified")):
        health = credentials.check_github_health(
            sandbox.config, home=sandbox.home, gh_installed=True,
            runner=lambda argv, stdin=None: subprocess.CompletedProcess(argv, 0, output, ""),
        )
        assert detail in health.credential
        assert health.status == "MISPROVISIONED"


def test_native_windows_install_refuses_without_acl_delivery(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credentials.sys, "platform", "win32")
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_PLATFORM_UNSUPPORTED"):
        sandbox.provision()
    assert sandbox.calls() == []


def test_shared_isolation_uses_fake_gh_and_clean_config() -> None:
    import shutil

    executable = shutil.which("gh", path=os.environ["PATH"])
    assert executable is not None
    assert Path(executable).parent.name == "isolated-bin"
    assert Path.home().name == "isolated-home"
    assert not any(key.startswith(("GH_", "GITHUB_")) and key != "GH_CONFIG_DIR"
                   for key in os.environ)
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    assert Path(os.environ["GIT_CONFIG_GLOBAL"]).parent == Path.home()
    assert Path(os.environ["GH_CONFIG_DIR"]).is_relative_to(Path.home())
    assert Path(os.environ["AGENT_SUITE_CONFIG"]).is_relative_to(Path.home())
    assert credentials.check_github_health().status == "absent"


def test_guard_refuses_real_gh_before_process_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import HostConfigGuard

    # This executable is a synthetic stand-in for the real host binary. Its
    # marker proves the guard rejects process creation, not just the verdict.
    outside = tmp_path / "outside-test-isolation"
    outside.mkdir()
    executable = outside / "gh"
    marker = outside / "executed"
    executable.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n"
                          f"Path({str(marker)!r}).touch()\n")
    executable.chmod(0o755)
    guard = HostConfigGuard(tmp_path / "allowed", (), active=True)
    sys.addaudithook(guard.audit)
    try:
        with pytest.raises(pytest.fail.Exception, match="blocked real gh execution"):
            subprocess.run([str(executable), "auth", "status"], check=False)
        monkeypatch.setenv("PATH", str(outside))
        with pytest.raises(pytest.fail.Exception, match="blocked real gh execution"):
            credentials.check_github_health()
        assert not marker.exists()
    finally:
        guard.active = False


def test_guard_refuses_operator_config_access(host_config_guard: object) -> None:
    from tests.conftest import HostConfigGuard

    assert isinstance(host_config_guard, HostConfigGuard)
    protected = host_config_guard.protected_paths[0] / "hosts.yml"
    with pytest.raises(pytest.fail.Exception, match="blocked real gh/git/agent-suite config"):
        protected.read_text()


def test_missing_path_never_falls_back_to_system_gh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PATH")
    assert credentials.check_github_health().status == "absent"
    with pytest.raises(gate.GateError, match="GITHUB_CLI_UNREACHABLE"):
        credentials.run(("gh", "auth", "status", "--hostname", "github.com"))


def test_sparse_child_env_keeps_git_and_gh_config_isolated(tmp_path: Path) -> None:
    script = (
        "import json, os; print(json.dumps({key: os.environ[key] for key in "
        "('HOME', 'GH_CONFIG_DIR', 'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', "
        "'GIT_CONFIG_NOSYSTEM')}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], env={"HOME": str(tmp_path)},
        capture_output=True, text=True, check=True,
    )
    child = json.loads(result.stdout)
    assert child["HOME"] == str(tmp_path)
    assert child["GIT_CONFIG_NOSYSTEM"] == "1"
    for key in ("GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        assert Path(child[key]).is_relative_to(Path.home())
