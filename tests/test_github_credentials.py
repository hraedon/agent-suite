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
    for name in ("forbidden-identifiers", "github-credential-state.json"):
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
    documents.extend(p.read_text() for p in (sandbox.home / ".config/agent-suite").glob("*state*"))
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

    with pytest.raises(gate.GateError, match="GITHUB_ROLLBACK_OWNERSHIP_MISMATCH"):
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
    assert Path.home().name == "isolated-home"
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
    executable = outside / "gh"
    marker = outside / "executed"
    executable.write_text(
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
        sandbox.provision()
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
    with pytest.raises(gate.GateError, match="GITHUB_CREDENTIAL_PLATFORM_UNSUPPORTED"):
        credentials.provision_github_credential(config, home=tmp_path)
    assert set(tmp_path.iterdir()) == {tmp_path / "isolated-home", tmp_path / "isolated-bin"}


def test_doctor_names_uninspected_ssh_gap() -> None:
    assert "ssh credential not inspected" in json.dumps(credentials.check_github_health().to_dict())


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
