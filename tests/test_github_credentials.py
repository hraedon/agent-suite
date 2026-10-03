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
            self.config,
            home=self.home,
            resolver=self.resolve,
            **kwargs,  # type: ignore[arg-type]
        )

    def health(self) -> credentials.GitHubHealth:
        return credentials.check_github_health(
            self.config,
            home=self.home,
            resolver=self.resolve,
            gh_installed=True,
        )

    def calls(self) -> list[list[str]]:
        log = self.fake / "calls"
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def working(self) -> bool:
        return (self.fake / "active").exists()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sandbox:
    for key in list(os.environ):
        if key in {
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_CONFIG_DIR",
            "GIT_CONFIG_COUNT",
            "GIT_CONFIG_PARAMETERS",
            "GIT_DIR",
            "GIT_WORK_TREE",
        } or (
            "FORBIDDEN_IDENTIFIERS" in key
            or key.startswith("AGENT_SUITE_GITHUB_")
            or key.startswith("GIT_CONFIG_KEY_")
            or key.startswith("GIT_CONFIG_VALUE_")
        ):
            monkeypatch.delenv(key)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
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
    script = fake / ("gh.py" if os.name == "nt" else "gh")
    script.write_text(
        f"#!{sys.executable}\n"
        + """
import hashlib
import json
import os
import pathlib
import sys
root = pathlib.Path(__file__).parent
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(json.dumps(args) + "\\n")
active = root / "active"
hosts = pathlib.Path(os.environ["GH_CONFIG_DIR"]) / "hosts.yml"
if args[:2] == ["auth", "login"]:
    value = sys.stdin.read().strip()
    if value != (root / "secret-input").read_text():
        sys.exit(1)
    active.write_text(hashlib.sha256(value.encode()).hexdigest())
    hosts.parent.mkdir(parents=True, exist_ok=True)
    hosts.write_text("github.com: {}\\n")
    print(value)
    print(value, file=sys.stderr)
    if (root / "fail-login").exists():
        sys.exit(1)
elif args[:2] == ["auth", "logout"]:
    active.unlink(missing_ok=True)
    hosts.parent.mkdir(parents=True, exist_ok=True)
    hosts.write_text("{}\\n")
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
"""
    )
    script.chmod(0o755)
    if os.name == "nt":
        (fake / "gh.cmd").write_text(f'@"{sys.executable}" "{script}" %*\n')
    monkeypatch.setenv("PATH", str(fake) + os.pathsep + os.environ["PATH"])
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Example Author")
    git(repo, "config", "user.email", "author@example.invalid")
    git(repo, "remote", "add", "origin", "https://github.com/example/repository.git")
    config = GitHubCredentialConfig(
        "env:TEST_GITHUB_TOKEN", "env:TEST_GATE_DENYLIST", repositories=(repo,)
    )
    return Sandbox(home, repo, config, denylist, token, fake)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_1_fresh_host_and_rerun(sandbox: Sandbox) -> None:
    assert sandbox.provision()["credential"] == "installed"
    assert sandbox.health().status == "ok"
    assert sandbox.health().repositories[0]["gate"] == "canonical-at-pin"
    directory = sandbox.home / ".config/agent-suite"
    assert directory.stat().st_mode & 0o777 == 0o700
    for name in ("forbidden-identifiers", "github-credential-state.json",
                 "github-credential-ownership.json"):
        assert (directory / name).stat().st_mode & 0o777 == 0o600
    assert sandbox.provision()["credential"] == "suite-owned; already installed"
    assert sum(call[:2] == ["auth", "login"] for call in sandbox.calls()) == 1


@pytest.mark.parametrize("step", credentials.PLAN)
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_2_failure_after_each_step_and_convergence(sandbox: Sandbox, step: str) -> None:
    visited: list[str] = []

    def fail(current: str) -> None:
        visited.append(current)
        if current == step:
            raise RuntimeError(sandbox.token + sandbox.denylist)

    with pytest.raises(gate.GateError, match="GITHUB_PROVISIONING_FAILED"):
        sandbox.provision(inject=fail)
    assert visited == list(credentials.PLAN[: credentials.PLAN.index(step) + 1])
    assert not sandbox.working()
    if step == "credential":
        assert ["auth", "logout", "--hostname", "github.com"] in sandbox.calls()
    sandbox.provision()
    assert sandbox.health().status == "ok"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_partial_failed_login_is_removed(sandbox: Sandbox) -> None:
    (sandbox.fake / "fail-login").touch()
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_INSTALL_FAILED"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_crash_recovery_before_next_transaction(sandbox: Sandbox) -> None:
    sandbox.provision()
    state_path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    state = json.loads(state_path.read_text())
    state["credential_phase"] = "installing"
    state_path.write_text(json.dumps(state))
    sandbox.provision()
    assert sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ambient_credential_is_never_adopted_or_revoked(sandbox: Sandbox) -> None:
    (sandbox.fake / "active").write_text("ambient")
    with pytest.raises(gate.GateError):
        sandbox.provision(inject=lambda _: (_ for _ in ()).throw(ValueError("fail")))
    assert sandbox.working()
    assert not any(call[:2] in (["auth", "login"], ["auth", "logout"]) for call in sandbox.calls())
    assert sandbox.provision()["credential"] == "ambient; not adopted"
    state_path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    state = json.loads(state_path.read_text())
    assert "token_sha256" not in state


def test_dry_run_has_only_plan_and_no_mutations(sandbox: Sandbox) -> None:
    before = {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}
    assert sandbox.provision(dry_run=True) == {
        "ok": True,
        "dry_run": True,
        "plan": list(credentials.PLAN),
    }
    assert before == {p: p.read_bytes() for p in sandbox.home.rglob("*") if p.is_file()}
    assert sandbox.calls() == []
    assert not (sandbox.repo / "scripts").exists()
    assert not (sandbox.home / ".config/agent-suite").exists()


@pytest.mark.parametrize("adapter", ["app-token", "deploy-key", "ssh-key"])
def test_unsupported_adapters_refuse(sandbox: Sandbox, adapter: str) -> None:
    from dataclasses import replace

    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_ADAPTER_UNSUPPORTED"):
        credentials.provision_github_credential(replace(sandbox.config, adapter=adapter))
    assert sandbox.calls() == []


@pytest.mark.parametrize("value", ["", "abc", '"unterminated'])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_pinned_parser_refuses_empty_short_or_invalid_denylist(
    sandbox: Sandbox,
    value: str,
) -> None:
    sandbox.denylist = value
    with pytest.raises(gate.GateError, match="GITHUB_DENYLIST_INVALID"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_ac58_8_all_suite_surfaces_do_not_leak(
    sandbox: Sandbox,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
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
    (sandbox.fake / "regista").write_text(
        f"#!{sys.executable}\n"
        + """
import os
import sys
print(os.environ[sys.argv[-1].split(":", 1)[1]])
"""
    )
    (sandbox.fake / "regista").chmod(0o755)
    documents: list[str] = []
    for flags in (["--dry-run"], ["--dry-run", "--json"], [], ["--json"]):
        assert main(["bootstrap", "--github-credential", *flags]) == 0
        captured = capsys.readouterr()
        documents.extend([captured.out, captured.err])
    from agent_suite import doctor

    health = sandbox.health()
    monkeypatch.setattr(
        doctor,
        "aggregate",
        lambda **_: doctor.SuiteReport(
            True,
            [],
            github_health=health,
        ),
    )
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
    documents.extend(p.read_text() for p in (sandbox.home / ".config/agent-suite").glob("*.json"))
    for surface in documents:
        assert sandbox.token not in surface
        assert sandbox.denylist not in surface
    assert ["auth", "login", "--hostname", "github.com", "--with-token"] in sandbox.calls()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_rollback_refuses_to_revoke_replaced_ambient_credential(sandbox: Sandbox) -> None:
    def replaced(step: str) -> None:
        if step == "credential":
            (sandbox.fake / "secret-input").write_text("different-ambient-credential")
            raise RuntimeError("fail after credential replaced")

    with pytest.raises(gate.GateError, match="GITHUB_PROVISIONING_FAILED"):
        sandbox.provision(inject=replaced)
    assert sandbox.working()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


def test_readonly_scope_and_unknown_capability_are_named(sandbox: Sandbox) -> None:
    import subprocess

    for output, detail in (
        ("Token scopes: 'read_org'", "push scope unavailable"),
        ("authenticated", "push capability unverified"),
    ):
        health = credentials.check_github_health(
            sandbox.config,
            home=sandbox.home,
            gh_installed=True,
            runner=lambda argv, stdin=None: subprocess.CompletedProcess(argv, 0, output, ""),
        )
        assert detail in health.credential
        assert health.status == "MISPROVISIONED"


def test_native_windows_install_refuses_without_acl_delivery(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
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
    assert Path.home().name == "isolated-home" or os.name == "nt"
    assert not any(
        key.startswith(("GH_", "GITHUB_")) and key != "GH_CONFIG_DIR" for key in os.environ
    )
    assert os.environ["GIT_CONFIG_NOSYSTEM"] == "1"
    assert Path(os.environ["GIT_CONFIG_GLOBAL"]).parent == Path.home()
    assert Path(os.environ["GH_CONFIG_DIR"]).is_relative_to(Path.home())
    assert Path(os.environ["AGENT_SUITE_CONFIG"]).is_relative_to(Path.home())
    assert credentials.check_github_health().status == "absent"


def test_guard_refuses_real_gh_before_process_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.conftest import HostConfigGuard

    # This executable is a synthetic stand-in for the real host binary. Its
    # marker proves the guard rejects process creation, not just the verdict.
    outside = tmp_path / "outside-test-isolation"
    outside.mkdir()
    executable = outside / ("gh.cmd" if os.name == "nt" else "gh")
    marker = outside / "executed"
    executable.write_text(
        f'@echo executed > "{marker}"\n' if os.name == "nt" else
        f"#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).touch()\n"
    )
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
        [sys.executable, "-c", script],
        env={"HOME": str(tmp_path)},
        capture_output=True,
        text=True,
        check=True,
    )
    child = json.loads(result.stdout)
    assert child["HOME"] == str(tmp_path)
    assert child["GIT_CONFIG_NOSYSTEM"] == "1"
    for key in ("GH_CONFIG_DIR", "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM"):
        assert Path(child[key]).is_relative_to(Path.home())


@pytest.mark.parametrize("presence", ["hosts", "GH_TOKEN", "GITHUB_TOKEN", "helper"])
@pytest.mark.parametrize("probe", ["failure", "timeout", "missing"])
def test_unverified_credential_without_guard_reds_doctor(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    presence: str,
    probe: str,
) -> None:
    from agent_suite import doctor
    from agent_suite.cli import main

    if presence == "hosts":
        path = sandbox.home / ".config/gh/hosts.yml"
        path.parent.mkdir(parents=True)
        path.write_text("github.com: {}")
    elif presence == "helper":
        git(sandbox.repo, "config", "credential.helper", "example-helper")
    else:
        monkeypatch.setenv(presence, sandbox.token)

    def failed(argv: tuple[str, ...], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        if probe == "timeout":
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.CompletedProcess(argv, 1, "", "")

    health = credentials.check_github_health(
        sandbox.config,
        home=sandbox.home,
        runner=failed,
        gh_installed=probe != "missing",
    )
    assert health.credential == "unverified"
    assert not health.ok
    assert health.repositories
    report = doctor.aggregate(
        components=(doctor.COMPONENTS[0],),
        installed=lambda _: False,
        key_watch_checks=False,
        memory_provider_checks=False,
        codex_health_checks=False,
        lock_checks=False,
        github_health=health,
    )
    assert not report.suite_ok
    monkeypatch.setattr(doctor, "aggregate", lambda **_: report)
    for flags in ([], ["--json"]):
        assert main(["doctor", *flags]) == 1
        captured = capsys.readouterr()
        assert sandbox.token not in captured.out + captured.err


@pytest.mark.parametrize("step", ["denylist", "gate", "hook", "verify"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_failed_rerun_removes_suite_owned_credential(sandbox: Sandbox, step: str) -> None:
    sandbox.provision()

    def fail(current: str) -> None:
        if current == step:
            raise RuntimeError("injected rerun failure")

    with pytest.raises(gate.GateError):
        sandbox.provision(inject=fail)
    assert not sandbox.working()
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_failed_rerun_unknown_gate_removes_owned_login(sandbox: Sandbox) -> None:
    sandbox.provision()
    path = sandbox.repo / "scripts/check_committed_identifiers.py"
    path.write_text("edited unknown gate")
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        sandbox.provision()
    assert not sandbox.working()
    sandbox.provision(force=True)
    assert sandbox.health().ok


@pytest.mark.parametrize("tamper", ["hook", "executable", "sibling", "denylist"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_verify_blocks_post_install_tampering(sandbox: Sandbox, tamper: str) -> None:
    def damage(step: str) -> None:
        if step != "hook":
            return
        if tamper == "denylist":
            (sandbox.home / ".config/agent-suite/forbidden-identifiers").write_text("decoy-only")
        elif tamper == "sibling":
            (sandbox.repo / "scripts/check_publication_plumbing.py").write_text("decoy")
        elif tamper == "executable":
            (sandbox.repo / "githooks/pre-push").chmod(0o600)
        else:
            (sandbox.repo / "githooks/pre-push").unlink()

    with pytest.raises(gate.GateError, match="VERIFICATION_FAILED"):
        sandbox.provision(inject=damage)
    assert not sandbox.working()
    assert not any(call[:2] == ["auth", "login"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_verify_blocks_effective_hooks_path_override(
    sandbox: Sandbox,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.hooksPath")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(sandbox.repo / "disabled-hooks"))
    with pytest.raises(gate.GateError, match="GITHUB_GATE_VERIFICATION_FAILED"):
        sandbox.provision(force=True)
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_sigint_login_marker_reds_doctor_and_next_run_recovers(sandbox: Sandbox) -> None:
    def interrupted(step: str) -> None:
        if step == "credential":
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        sandbox.provision(inject=interrupted)
    assert sandbox.working()
    assert not sandbox.health().ok
    sandbox.provision()
    assert sandbox.health().ok
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_denylist_fingerprint_is_keyed_and_never_exposes_raw_hash(sandbox: Sandbox) -> None:
    sandbox.provision()
    output = json.dumps(sandbox.health().to_dict())
    state = (sandbox.home / ".config/agent-suite/github-credential-state.json").read_text()
    assert gate.digest(sandbox.denylist.encode()) not in output + state
    metadata = json.loads(state)
    assert len(metadata["fingerprint_key"]) == 64
    assert metadata["fingerprint_key"] not in output
    assert metadata["denylist_fingerprint"] in output


def test_windows_audit_handles_none_executable_and_checks_argv(tmp_path: Path) -> None:
    from tests.conftest import HostConfigGuard

    guard = HostConfigGuard(tmp_path / "allowed", (), active=True)
    fake = tmp_path / "allowed/gh.cmd"
    environment = dict(os.environ)
    guard.audit("subprocess.Popen", (None, [str(fake), "auth", "status"], None, environment))
    guard.audit("subprocess.Popen", (None, f'"{fake}" auth status', None, environment))
    real = tmp_path / "outside/gh.exe"
    for argv in ([str(real)], f'"{real}" auth status'):
        with pytest.raises(pytest.fail.Exception, match="blocked real gh execution"):
            guard.audit("subprocess.Popen", (None, argv, None, environment))


def test_windows_refusal_does_not_need_posix_sandbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(credentials.sys, "platform", "win32")
    config = GitHubCredentialConfig("env:EXAMPLE_TOKEN", "env:EXAMPLE_DENYLIST")
    before = set(tmp_path.iterdir())
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_PLATFORM_UNSUPPORTED"):
        credentials.provision_github_credential(config, home=tmp_path)
    assert set(tmp_path.iterdir()) == before


def test_doctor_names_uninspected_ssh_gap() -> None:
    report = json.dumps(credentials.check_github_health().to_dict())
    assert "ssh credential not inspected" in report
    assert "Python startup customization not inspected" in report


@pytest.mark.parametrize("value", ["value-with-spaces  ", "first\nsecond\n", '"quoted phrase"\n'])
def test_regista_resolution_preserves_secret_bytes_and_uses_raw_cli(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    from agent_suite.secret_refs import resolve_secret_value

    calls: list[tuple[str, ...]] = []

    def resolved(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, value + "\n", "")

    monkeypatch.setattr(subprocess, "run", resolved)
    assert resolve_secret_value("env:EXAMPLE_SECRET") == value
    assert calls == [("regista", "secrets", "--ref", "env:EXAMPLE_SECRET")]


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_token_readback_is_required_before_success(sandbox: Sandbox) -> None:
    reads = 0

    def different_first_read(
        argv: tuple[str, ...],
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal reads
        if argv[1:3] == ("auth", "token"):
            reads += 1
            if reads == 1:
                return subprocess.CompletedProcess(argv, 0, "wrong-token\n", "")
        return credentials.run(argv, stdin)

    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_READBACK_FAILED"):
        sandbox.provision(runner=different_first_read)
    assert not sandbox.working()


def test_windows_adapter_dependencies_have_explicit_skip_reasons() -> None:
    from tests import test_ac58_pinned_gate, test_identifier_gate_provisioning

    for function in (
        test_ac58_1_fresh_host_and_rerun,
        test_ac58_8_all_suite_surfaces_do_not_leak,
        test_identifier_gate_provisioning.test_explicit_repo_includes_linked_worktree_and_effective_hook,
        test_ac58_pinned_gate.test_ac58_5_missing_denylist_not_satisfied_at_pin_5233019,
    ):
        assert any(mark.name == "skipif" and "Windows adapter" in mark.kwargs.get("reason", "")
                   for mark in getattr(function, "pytestmark", []))


@pytest.mark.parametrize("location", ["xdg", "appdata"])
def test_r2_unverified_credential_uses_platform_gh_config(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, location: str,
) -> None:
    monkeypatch.delenv("GH_CONFIG_DIR")
    monkeypatch.delenv("XDG_CONFIG_HOME")
    if location == "xdg":
        directory = sandbox.home / "other-xdg/gh"
        monkeypatch.setenv("XDG_CONFIG_HOME", str(directory.parent))
    else:
        directory = sandbox.home / "other-appdata/GitHub CLI"
        monkeypatch.setenv("APPDATA", str(directory.parent))
        monkeypatch.setattr(credentials, "_GH_WINDOWS", True)
    directory.mkdir(parents=True)
    (directory / "hosts.yml").write_text("github.com: {}")
    health = sandbox.health()
    assert health.credential == "unverified"
    assert health.status == "MISPROVISIONED"
    assert health.repositories and not health.ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_unreadable_owned_token_retains_recovery_and_reds_doctor(sandbox: Sandbox) -> None:
    sandbox.provision()

    def unavailable(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[1:3] in {("auth", "token"), ("auth", "status")}:
            return subprocess.CompletedProcess(argv, 1, "", "")
        return credentials.run(argv, stdin)

    with pytest.raises(gate.GateError, match="GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED"):
        sandbox.provision(runner=unavailable, inject=lambda _: (_ for _ in ()).throw(ValueError()))
    path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    state = json.loads(path.read_text())
    assert state["credential_phase"] == "rollback_pending"
    assert sandbox.working() and not sandbox.health().ok
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.parametrize("damage", ["permissions", "json", "invalid-key"])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_corrupt_health_state_cannot_bypass_owned_rollback(
    sandbox: Sandbox, damage: str,
) -> None:
    sandbox.provision()
    path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    if damage == "permissions":
        path.chmod(0o644)
    elif damage == "json":
        path.write_text("{")
    else:
        value = json.loads(path.read_text())
        value["fingerprint_key"] = "invalid"
        path.write_text(json.dumps(value))
    with pytest.raises(gate.GateError):
        sandbox.provision()
    assert not sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    if damage == "invalid-key":
        # Round 5 requires manual reconciliation of disagreeing keys, even
        # after the independently proven credential has been removed.
        with pytest.raises(gate.GateError, match="GITHUB_FINGERPRINT_KEY_INVALID"):
            sandbox.provision()
        journal = credentials._read_ownership(path.parent)
        repaired = json.loads(path.read_text())
        repaired["fingerprint_key"] = journal["fingerprint_key"]
        path.write_text(json.dumps(repaired))
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_denylist_environment_override_is_misprovisioned(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()
    for name in ("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", "OTHER_FORBIDDEN_IDENTIFIERS"):
        monkeypatch.setenv(name, "decoy-only")
        health = sandbox.health()
        assert health.status == "MISPROVISIONED"
        assert "denylist environment override mismatch" in health.issues
        assert "decoy-only" not in json.dumps(health.to_dict())
        monkeypatch.setenv(name, sandbox.denylist)
        assert sandbox.health().ok
        monkeypatch.setenv(name, "")
        assert sandbox.health().ok
        monkeypatch.delenv(name)


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_existing_hooks_require_explicit_force(sandbox: Sandbox) -> None:
    path = sandbox.repo / "githooks/pre-push"
    path.parent.mkdir()
    path.write_text("operator hook")
    git(sandbox.repo, "config", "core.hooksPath", ".husky")
    with pytest.raises(gate.GateError, match="GATE_HOOK_OVERWRITE_REFUSED"):
        sandbox.provision()
    assert path.read_text() == "operator hook"
    assert git(sandbox.repo, "config", "core.hooksPath") == ".husky"
    assert not sandbox.working()
    sandbox.provision(force=True)
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_replaced_ambient_login_is_not_owned_and_preserves_gate_error(sandbox: Sandbox) -> None:
    sandbox.provision()
    (sandbox.fake / "secret-input").write_text("replacement-token")
    (sandbox.fake / "active").write_text(gate.digest(b"replacement-token"))
    assert sandbox.provision()["credential"] == "ambient; not adopted"
    (sandbox.repo / "scripts/check_committed_identifiers.py").write_text("unknown")
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        sandbox.provision()
    assert sandbox.working()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r2_post_login_status_is_required_even_with_readable_token(sandbox: Sandbox) -> None:
    def no_status(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ("auth", "status"):
            return subprocess.CompletedProcess(argv, 1, "", "")
        return credentials.run(argv, stdin)
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_INSTALL_FAILED"):
        sandbox.provision(runner=no_status)
    assert not sandbox.working()


@pytest.mark.parametrize("key", ["00", "x" * 64, 123, None])
def test_r2_fingerprint_key_shape_is_load_bearing(key: object) -> None:
    with pytest.raises(gate.GateError, match="GITHUB_FINGERPRINT_KEY_INVALID"):
        credentials._fingerprint({"fingerprint_key": key}, b"throwaway")


def test_r2_windows_audit_reads_only_the_executable_not_python_code(tmp_path: Path) -> None:
    from tests.conftest import HostConfigGuard
    guard = HostConfigGuard(tmp_path, (), active=True)
    argv = subprocess.list2cmdline([sys.executable, "-c", 'exec("abc \' def")'])
    guard.audit("subprocess.Popen", (None, argv, None, dict(os.environ)))


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_failed_login_without_credential_converges(sandbox: Sandbox) -> None:
    def rejected(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ("auth", "login"):
            return subprocess.CompletedProcess(argv, 1, "", "rejected")
        return credentials.run(argv, stdin)
    with pytest.raises(gate.GateError):
        sandbox.provision(runner=rejected)
    assert not sandbox.working()
    assert sandbox.provision()["credential"] == "installed"
    assert sandbox.health().ok


@pytest.mark.parametrize("phase", ["installing", "rollback_pending", "installed"])
@pytest.mark.parametrize("replacement", [False, True])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_recovery_after_logout_or_replacement_converges(
    sandbox: Sandbox, phase: str, replacement: bool,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    journal_path = directory / "github-credential-ownership.json"
    journal = json.loads(journal_path.read_text())
    journal["phase"] = phase
    journal_path.write_text(json.dumps(journal))
    if replacement:
        (sandbox.fake / "secret-input").write_text("different-operator-token")
    else:
        credentials.run(("gh", "auth", "logout", "--hostname", "github.com"))
    result = sandbox.provision()
    assert result["credential"] == ("ambient; not adopted" if replacement else "installed")
    assert sandbox.health().ok
    if replacement:
        assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.parametrize("hosts", ["", "{}\n", "example.invalid: {}\n",
                                   "example.invalid:\n    user: example\n"])
def test_r3_empty_or_other_host_config_is_not_github_credential(
    sandbox: Sandbox, hosts: str,
) -> None:
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(hosts)
    assert sandbox.health().credential == "absent"


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_rollback_preserves_first_failure_and_records_cleanup_failure(sandbox: Sandbox) -> None:
    def failed(argv: tuple[str, ...], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ("auth", "logout"):
            return subprocess.CompletedProcess(argv, 1, "", sandbox.token)
        return credentials.run(argv, stdin)
    (sandbox.fake / "fail-login").touch()
    with pytest.raises(gate.GateError, match=r"^GITHUB_CREDENTIAL_INSTALL_FAILED$"):
        sandbox.provision(runner=failed)
    journal_path = sandbox.home / ".config/agent-suite/github-credential-ownership.json"
    journal = json.loads(journal_path.read_text())
    assert journal["phase"] == "rollback_pending"
    assert journal["recovery_error"] == "GITHUB_ROLLBACK_FAILED"
    assert "GITHUB_ROLLBACK_FAILED" in json.dumps(sandbox.health().to_dict())
    assert sandbox.token not in json.dumps(journal)


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_corrupt_state_has_actionable_first_error(sandbox: Sandbox) -> None:
    sandbox.provision()
    (sandbox.home / ".config/agent-suite/github-credential-state.json").write_text("{")
    with pytest.raises(gate.GateError, match=r"^GITHUB_STATE_INVALID$"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_missing_fingerprint_key_is_named_and_reprovisioned(sandbox: Sandbox) -> None:
    sandbox.provision()
    path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    value = json.loads(path.read_text())
    value.pop("fingerprint_key")
    path.write_text(json.dumps(value))
    before = path.read_bytes()
    health = sandbox.health()
    assert "GITHUB_STATE_REPROVISION_REQUIRED" in health.issues
    assert not health.ok and path.read_bytes() == before
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_token_metadata_is_keyed_and_legacy_journal_migrates(sandbox: Sandbox) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    for name in ("github-credential-state.json", "github-credential-ownership.json"):
        value = json.loads((directory / name).read_text())
        assert "token_fingerprint" in value and "token_sha256" not in value
        assert gate.digest(sandbox.token.encode()) not in json.dumps(value)
    journal = directory / "github-credential-ownership.json"
    journal.write_text(json.dumps({"phase": "installed",
                                   "token_sha256": gate.digest(sandbox.token.encode())}))
    sandbox.provision()
    assert "token_sha256" not in journal.read_text()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_residual_matching_credential_is_named_without_adoption(sandbox: Sandbox) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    journal = directory / "github-credential-ownership.json"
    metadata = json.loads(journal.read_text())
    metadata["phase"] = "removed"
    journal.write_text(json.dumps(metadata))
    state = directory / "github-credential-state.json"
    metadata = json.loads(state.read_text())
    metadata["credential_phase"] = "removed"
    state.write_text(json.dumps(metadata))
    assert "residual credential matches prior transaction" in str(sandbox.provision()["credential"])
    assert sandbox.working()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


def test_r3_failed_probe_without_config_is_unverified(sandbox: Sandbox) -> None:
    def unreachable(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        raise OSError("unreachable")
    health = credentials.check_github_health(sandbox.config, home=sandbox.home,
                                             runner=unreachable, gh_installed=True)
    assert health.credential == "unverified"
    assert health.status == "MISPROVISIONED"
    assert health.notes and health.repositories


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_provisioning_denylist_override_refuses_before_login(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", "decoy-only")
    with pytest.raises(gate.GateError, match=r"^GITHUB_DENYLIST_ENVIRONMENT_MISMATCH$"):
        sandbox.provision()
    assert not any(call[:2] == ["auth", "login"] for call in sandbox.calls())
    monkeypatch.setenv("AGENT_SUITE_FORBIDDEN_IDENTIFIERS", sandbox.denylist)
    assert sandbox.provision()["ok"]


@pytest.mark.parametrize("hosts", [
    "  example.invalid: {}\n  github.com: {}\n",
    "'github.com': {}\n", '"github.com": {}\n',
    "{github.com: {}}\n", "malformed yaml",
])
def test_r3_host_mapping_never_proves_false_absence(sandbox: Sandbox, hosts: str) -> None:
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(hosts)
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok


@pytest.mark.parametrize("phase", ["removed", "replaced"])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_legacy_terminal_state_drops_plain_token_digest(
    sandbox: Sandbox, phase: str,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    (directory / "github-credential-ownership.json").unlink()
    path = directory / "github-credential-state.json"
    state = json.loads(path.read_text())
    state.pop("token_fingerprint")
    state["token_sha256"] = gate.digest(sandbox.token.encode())
    state["credential_phase"] = phase
    path.write_text(json.dumps(state))
    result = sandbox.provision()
    assert "residual credential matches prior transaction" in str(result["credential"])
    for name in ("github-credential-state.json", "github-credential-ownership.json"):
        assert gate.digest(sandbox.token.encode()) not in (directory / name).read_text()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_empty_health_state_is_named_and_repaired(sandbox: Sandbox) -> None:
    sandbox.provision()
    path = sandbox.home / ".config/agent-suite/github-credential-state.json"
    path.write_text("{}")
    assert "GITHUB_STATE_REPROVISION_REQUIRED" in sandbox.health().issues
    sandbox.provision()
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r3_outer_token_whitespace_refuses_before_login(sandbox: Sandbox) -> None:
    sandbox.token = " " + sandbox.token + " "
    with pytest.raises(gate.GateError, match="GITHUB_TOKEN_INVALID"):
        sandbox.provision()
    assert not any(call[:2] == ["auth", "login"] for call in sandbox.calls())


@pytest.mark.parametrize("damage", ["directory", "symlink", "state-write", "journal-write"])
@pytest.mark.parametrize("phase", ["installed", "installing"])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_metadata_damage_cannot_prevent_owned_logout(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, damage: str, phase: str,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    journal = directory / "github-credential-ownership.json"
    value = json.loads(journal.read_text())
    value["phase"] = phase
    journal.write_text(json.dumps(value))
    state = directory / "github-credential-state.json"
    if damage == "directory":
        state.unlink()
        state.mkdir()
    elif damage == "symlink":
        target = directory / "state-backup.json"
        state.rename(target)
        state.symlink_to(target)
    else:
        original_writer = getattr(credentials, (
            "_write_state" if damage == "state-write" else "_write_ownership"
        ))
        def unwritable(*args: object, **kwargs: object) -> None:
            raise PermissionError("simulated unavailable metadata storage")
        name = "_write_state" if damage == "state-write" else "_write_ownership"
        monkeypatch.setattr(credentials, name, unwritable)
    with pytest.raises(gate.GateError):
        sandbox.provision()
    assert not sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    if damage == "journal-write":
        assert credentials._read_state(directory)["credential_phase"] == "removed"
    if damage == "directory":
        state.rmdir()
    elif damage == "symlink":
        state.unlink()
    else:
        monkeypatch.setattr(credentials, name, original_writer)
    assert sandbox.provision()["ok"]
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_rollback_logs_out_before_metadata_writes(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    state = credentials._read_state(directory)
    ownership = credentials._read_ownership(directory)
    events: list[str] = []
    original_state = credentials._write_state
    original_journal = credentials._write_ownership

    def write_state(path: Path, value: dict[str, object]) -> None:
        events.append("state")
        original_state(path, value)

    def write_journal(path: Path, value: dict[str, object]) -> None:
        events.append("journal")
        original_journal(path, value)

    def observed(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ("auth", "logout"):
            events.append("logout")
        return credentials.run(argv, stdin)

    monkeypatch.setattr(credentials, "_write_state", write_state)
    monkeypatch.setattr(credentials, "_write_ownership", write_journal)
    credentials._rollback(directory, state, ownership, observed, sandbox.home, sandbox.config)
    assert events[0] == "logout"
    assert not sandbox.working()


@pytest.mark.parametrize("logged_out", [False, True])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_key_loss_without_journal_never_poisons_recovery(
    sandbox: Sandbox, logged_out: bool,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    path = directory / "github-credential-state.json"
    original = json.loads(path.read_text())
    damaged = dict(original)
    damaged.pop("fingerprint_key")
    path.write_text(json.dumps(damaged))
    journal = directory / "github-credential-ownership.json"
    journal.unlink()
    (sandbox.repo / "scripts/check_committed_identifiers.py").write_text("unknown gate")
    if logged_out:
        credentials.run(("gh", "auth", "logout", "--hostname", "github.com"))
        with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
            sandbox.provision()
    else:
        before = path.read_bytes()
        for _ in range(2):
            with pytest.raises(gate.GateError, match="GITHUB_STATE_REPROVISION_REQUIRED"):
                sandbox.provision()
            assert path.read_bytes() == before
            assert not journal.exists()
        # Restore the actual original key, never a newly invented key.
        path.write_text(json.dumps(original))
        with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
            sandbox.provision()
    assert not sandbox.working()
    assert sandbox.provision(force=True)["ok"]
    assert sandbox.health().ok


@pytest.mark.parametrize("phase", ["removed", "replaced"])
@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_matching_terminal_credential_is_removed_on_failure(
    sandbox: Sandbox, phase: str,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    journal = directory / "github-credential-ownership.json"
    value = json.loads(journal.read_text())
    value["phase"] = phase
    journal.write_text(json.dumps(value))
    (sandbox.repo / "scripts/check_committed_identifiers.py").write_text("unknown gate")
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        sandbox.provision()
    assert not sandbox.working()


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_current_readback_mismatch_retains_unverified_recovery(sandbox: Sandbox) -> None:
    def raced(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        if argv[1:3] == ("auth", "token"):
            return subprocess.CompletedProcess(argv, 0, "different-active-account-token", "")
        return credentials.run(argv, stdin)
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_READBACK_FAILED"):
        sandbox.provision(runner=raced)
    directory = sandbox.home / ".config/agent-suite"
    journal = json.loads((directory / "github-credential-ownership.json").read_text())
    assert journal["phase"] == "rollback_pending"
    assert journal["recovery_error"] == "GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED"
    assert not sandbox.health().ok
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    # The matching account becomes active again; recovery removes it and retries.
    assert sandbox.provision()["ok"]
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())


@pytest.mark.skipif(
    sys.platform == "win32", reason="Windows adapter refuses POSIX token/denylist delivery",
)
def test_r4_helper_path_is_reported_and_does_not_block_provisioning(sandbox: Sandbox) -> None:
    git(sandbox.repo, "config", "credential.helper", "example-helper")
    assert not sandbox.health().ok
    visited: list[str] = []

    def ordered(step: str) -> None:
        visited.append(step)
        assert sandbox.working() == (step == "credential")

    outcome = sandbox.provision(inject=ordered)
    assert visited == list(credentials.PLAN)
    assert git(sandbox.repo, "config", "credential.helper") == "example-helper"
    assert "git credential helper not inspected" in str(outcome)
    assert sandbox.health().ok
    assert "git credential helper not inspected" in " ".join(sandbox.health().notes)
    credentials.run(("gh", "auth", "logout", "--hostname", "github.com"))
    health = sandbox.health()
    assert health.credential == "unverified" and health.ok
    assert sandbox.provision()["ok"]


def test_r4_missing_scripts_has_accurate_health_label(sandbox: Sandbox) -> None:
    (sandbox.fake / "active").touch()
    health = sandbox.health()
    assert not health.ok
    assert "GATE_SCRIPTS_MISSING" in health.issues
    assert "GATE_SCRIPT_IMPORT_SHADOW" not in health.issues


@pytest.mark.parametrize("failure", ["missing-git", "invalid-config"])
def test_r4_recovery_requires_verified_git_configuration(
    sandbox: Sandbox, monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    if failure == "missing-git":
        monkeypatch.setenv("PATH", "")
    else:
        (sandbox.home / ".gitconfig").write_text("[unterminated")
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_CONFIG_UNVERIFIED"):
        credentials._credential_present(sandbox.home, (sandbox.repo,), require_git=True)


def test_r4_failed_token_command_with_stdout_is_not_absence(sandbox: Sandbox) -> None:
    ownership: dict[str, object] = {"phase": "installed", "fingerprint_key": "00" * 32}
    ownership["token_fingerprint"] = credentials._fingerprint(
        ownership, b"github-token\0" + sandbox.token.encode(),
    )
    def failed(
        argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1,
                                           sandbox.token if argv[1:3] == ("auth", "token") else "",
                                           "")
    with pytest.raises(gate.GateError, match="GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED"):
        credentials._observe_ownership(failed, ownership, sandbox.home, sandbox.config)


@pytest.mark.parametrize("hosts", [
    "example.invalid: {\n", "example.invalid: foo: bar\n",
    "example.invalid:\n    user: 'unterminated\n",
    'example.invalid:\n    user: "unterminated\n',
    "example.invalid:\n    - user: example\n",
    "example.invalid: {}\nexample.invalid: {}\n",
])
def test_r4_malformed_yaml_never_proves_absence(sandbox: Sandbox, hosts: str) -> None:
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(hosts)
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok


def test_r4_contract_limits_key_loss_recovery() -> None:
    contract = (Path(__file__).parents[1] / "docs/bootstrap-contract.md").read_text()
    assert "both the journal and original fingerprint key are lost" in contract
    assert "Generating a new key cannot prove prior token ownership" in contract


@pytest.mark.parametrize("hosts", [
    '{"example.invalid": {"user": "example"}}',
    "---\nexample.invalid:\n    user: 'example'\n    git_protocol: https\n"
    "    users:\n        example:\n            oauth_token: example-token\n...\n",
])
def test_r4_supported_other_host_mapping_is_absent(sandbox: Sandbox, hosts: str) -> None:
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(hosts)
    assert sandbox.health().credential == "absent"


@pytest.mark.parametrize("hosts", [
    '{"example.invalid": []}', '{"example.invalid": null}',
    '{"example.invalid": {}, "example.invalid": {}}',
    '{"example.invalid": {"user": "example", "user": "other"}}',
    '{"example.invalid": {"user": NaN}}',
    '{"example.invalid": ' + '{"nested":' * 1100 + '{}' + '}' * 1100 + '}',
], ids=["array", "null", "duplicate-host", "duplicate-field", "non-finite", "deep"])
def test_r4_unsupported_host_json_is_unverified(sandbox: Sandbox, hosts: str) -> None:
    path = sandbox.home / ".config/gh/hosts.yml"
    path.parent.mkdir(parents=True)
    path.write_text(hosts)
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok


def test_r4_corrupt_terminal_journal_never_emits_untrusted_diagnostics(sandbox: Sandbox) -> None:
    directory = sandbox.home / ".config/agent-suite"
    directory.mkdir(parents=True, mode=0o700)
    credentials._write_state(directory, {
        "fingerprint_key": "00" * 32, "credential_phase": "rollback_pending",
    })
    credentials._write_ownership(directory, {"phase": "removed", "recovery_error": sandbox.token})
    (sandbox.fake / "active").touch()
    health = sandbox.health()
    assert not health.ok
    assert sandbox.token not in json.dumps(health.to_dict())


@pytest.mark.parametrize("damaged", [
    "journal", "state", "malformed-journal", "malformed-state",
])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_r5_divergent_keys_refuse_preserve_evidence_and_remove_proven_token(
    sandbox: Sandbox, damaged: str,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    state_path = directory / "github-credential-state.json"
    journal_path = directory / "github-credential-ownership.json"
    target = state_path if damaged in {"state", "malformed-state"} else journal_path
    record = json.loads(target.read_text())
    record["fingerprint_key"] = "not-a-key" if damaged.startswith("malformed") else "ab" * 32
    target.write_text(json.dumps(record))
    before = (state_path.read_bytes(), journal_path.read_bytes())
    health = sandbox.health()
    assert not health.ok
    assert "GITHUB_OWNERSHIP_KEY_UNVERIFIED" in health.issues
    code = ("GITHUB_FINGERPRINT_KEY_INVALID" if damaged == "malformed-state"
            else "GITHUB_OWNERSHIP_KEY_UNVERIFIED")
    with pytest.raises(gate.GateError, match=code):
        sandbox.provision()
    assert not sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    assert before == (state_path.read_bytes(), journal_path.read_bytes())
    assert not sandbox.health().ok
    # Restoring the damaged record permits convergence after the proven logout.
    record["fingerprint_key"] = json.loads(
        (journal_path if target == state_path else state_path).read_text()
    )["fingerprint_key"]
    target.write_text(json.dumps(record))
    assert sandbox.provision()["ok"]
    assert sandbox.health().ok


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_r5_divergent_keys_never_revoke_an_unproven_ambient_token(sandbox: Sandbox) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    journal_path = directory / "github-credential-ownership.json"
    journal = json.loads(journal_path.read_text())
    journal["fingerprint_key"] = "ab" * 32
    journal_path.write_text(json.dumps(journal))
    (sandbox.fake / "secret-input").write_text("operator-ambient-token")
    before = journal_path.read_bytes()
    with pytest.raises(gate.GateError, match="GITHUB_OWNERSHIP_KEY_UNVERIFIED"):
        sandbox.provision()
    assert sandbox.working()
    assert not any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
    assert journal_path.read_bytes() == before
    assert not sandbox.health().ok


@pytest.mark.parametrize("ref_kind", ["denylist", "token"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_r5_resolver_named_failure_is_preserved(sandbox: Sandbox, ref_kind: str) -> None:
    failed_ref = sandbox.config.denylist_ref if ref_kind == "denylist" else sandbox.config.token_ref
    def resolve(ref: str) -> str:
        if ref == failed_ref:
            raise ValueError("SECRET_RESOLUTION_FAILED")
        return sandbox.resolve(ref)
    with pytest.raises(gate.GateError, match=r"^SECRET_RESOLUTION_FAILED$"):
        credentials.provision_github_credential(sandbox.config, home=sandbox.home, resolver=resolve)
    assert not sandbox.working()


def test_r5_unconfigured_authenticated_host_has_actionable_remediation(sandbox: Sandbox) -> None:
    (sandbox.fake / "active").touch()
    health = credentials.check_github_health(GitHubCredentialConfig(), home=sandbox.home,
                                             gh_installed=True)
    assert not health.ok
    assert any("AGENT_SUITE_GITHUB_REPOSITORIES" in note and
               "bootstrap --github-credential" in note for note in health.notes)


@pytest.mark.parametrize("value", ["12345", "true", "null", "1.5", "0xFF", "2026-10-03"])
def test_r5_yaml_non_string_scalars_are_unverified(sandbox: Sandbox, value: str) -> None:
    hosts = sandbox.home / ".config/gh/hosts.yml"
    hosts.parent.mkdir(parents=True)
    hosts.write_text(f"example.invalid:\n    user: {value}\n")
    assert sandbox.health().credential == "unverified"
    assert not sandbox.health().ok


def test_r5_contract_does_not_certify_unverified_authentication() -> None:
    contract = (Path(__file__).parents[1] / "docs/bootstrap-contract.md").read_text()
    assert "unverified is not proof of authentication or push capability" in contract


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_r5_either_key_can_prove_the_retained_ownership_fingerprint(sandbox: Sandbox) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    state_path = directory / "github-credential-state.json"
    journal_path = directory / "github-credential-ownership.json"
    state = json.loads(state_path.read_text())
    state.pop("token_fingerprint")  # Health metadata lost this duplicate, but retained its key.
    state_path.write_text(json.dumps(state))
    journal = json.loads(journal_path.read_text())
    journal["fingerprint_key"] = "ab" * 32
    journal_path.write_text(json.dumps(journal))
    before = (state_path.read_bytes(), journal_path.read_bytes())
    with pytest.raises(gate.GateError, match="GITHUB_OWNERSHIP_KEY_UNVERIFIED"):
        sandbox.provision()
    assert not sandbox.working()
    assert before == (state_path.read_bytes(), journal_path.read_bytes())


def test_r5_resolver_diagnostic_that_looks_like_a_code_cannot_leak() -> None:
    secret_diagnostic = "SECRET_THROWAWAY_IDENTIFIER_CANARY"
    assert credentials._error_code(ValueError(secret_diagnostic)) == "GITHUB_PROVISIONING_FAILED"


@pytest.mark.parametrize("phase", ["installed", "removed", "replaced"])
@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows adapter refuses POSIX hook/denylist delivery until ACL support",
)
def test_r5_state_ownership_proof_survives_journal_disposition(
    sandbox: Sandbox, phase: str,
) -> None:
    sandbox.provision()
    directory = sandbox.home / ".config/agent-suite"
    path = directory / "github-credential-ownership.json"
    journal = json.loads(path.read_text())
    journal.update(phase=phase, token_fingerprint="00" * 32)
    path.write_text(json.dumps(journal))
    (sandbox.repo / "scripts/check_committed_identifiers.py").write_text("unknown gate")
    with pytest.raises(gate.GateError, match="GATE_OVERWRITE_REFUSED"):
        sandbox.provision()
    assert not sandbox.working()
    assert any(call[:2] == ["auth", "logout"] for call in sandbox.calls())
