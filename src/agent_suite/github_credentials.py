"""BR-50: reference-only GitHub token installation after gate verification."""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from agent_suite import identifier_gate as gate
from agent_suite.config import GitHubCredentialConfig
from agent_suite.secret_refs import resolve_secret_value

PLAN = ("denylist", "gate", "hook", "verify", "credential")
Resolver = Callable[[str], str]
FailureInjector = Callable[[str], None]


class SecretRunner(Protocol):
    def __call__(
        self, argv: tuple[str, ...], stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def run(argv: tuple[str, ...], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    # No value is passed through argv, diagnostics, or a newly created env var.
    if argv and argv[0] == "gh":
        executable = shutil.which("gh", path=os.environ.get("PATH", ""))
        if executable is None:
            raise gate.GateError("GITHUB_CLI_UNREACHABLE")
        argv = (executable, *argv[1:])
    return subprocess.run(
        argv, input=stdin, capture_output=True, text=True, timeout=30, check=False,
    )


def _gh(
    runner: SecretRunner, *args: str, stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(("gh", *args), stdin)
    except Exception:
        raise gate.GateError("GITHUB_CLI_UNREACHABLE") from None


@dataclass
class GitHubHealth:
    status: str = "absent"
    credential: str = "absent"
    issues: list[str] = field(default_factory=list)
    repositories: list[dict[str, object]] = field(default_factory=list)
    denylist_sha256: str | None = None

    @property
    def ok(self) -> bool:
        return self.status != "MISPROVISIONED"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status, "credential": self.credential, "ok": self.ok,
            "issues": self.issues, "repositories": self.repositories,
            "denylist_sha256": self.denylist_sha256,
        }


def _directory(home: Path) -> Path:
    return home / ".config/agent-suite"


def _read_state(directory: Path) -> dict[str, object]:
    path = directory / "github-credential-state.json"
    if not path.exists():
        return {}
    if path.is_symlink() or stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise gate.GateError("GITHUB_STATE_PERMISSIONS_INVALID")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise gate.GateError("GITHUB_STATE_INVALID")
    return value


def _write_state(directory: Path, state: dict[str, object]) -> None:
    gate.atomic_write(
        directory / "github-credential-state.json",
        (json.dumps(state, sort_keys=True) + "\n").encode(), 0o600,
    )


def _credential_present(home: Path, repositories: tuple[Path, ...]) -> bool:
    config_home = Path(os.environ.get("GH_CONFIG_DIR", str(home / ".config/gh")))
    if (config_home / "hosts.yml").exists() or any(
        os.environ.get(name) for name in ("GH_TOKEN", "GITHUB_TOKEN")
    ):
        return True
    # Read effective Git config; no writes and no helper execution.
    targets = repositories or (home,)
    return any(
        gate.git(repo, "config", "--get-regexp", r"credential\..*helper|credential\.helper",
                 optional=True)
        for repo in targets
    )


def _probe(runner: SecretRunner) -> tuple[bool, str]:
    result = _gh(runner, "auth", "status", "--hostname", "github.com")
    if result.returncode != 0:
        return False, "unverified"
    # Classic-token scope readback is available in auth status. Fine-grained
    # tokens do not expose classic scopes, so unknown capability stays named.
    scopes = re.search(r"Token scopes:\s*([^\n]+)", result.stdout + result.stderr)
    if scopes is not None:
        names = set(re.findall(r"[a-z_]+", scopes.group(1)))
        if not names.intersection({"repo", "public_repo"}):
            return True, "authenticated; push scope unavailable"
        return True, "authenticated; push scope confirmed"
    return True, "authenticated; push capability unverified"


def check_github_health(
    config: GitHubCredentialConfig | None = None, *, home: Path | None = None,
    runner: SecretRunner = run, resolver: Resolver = resolve_secret_value,
    gh_installed: bool | None = None,
) -> GitHubHealth:
    """Read-only host and per-repository health. Never emit child output."""
    home = Path.home() if home is None else home
    report = GitHubHealth()
    authenticated = False
    try:
        present = (
            shutil.which("gh", path=os.environ.get("PATH", "")) is not None
            if gh_installed is None else gh_installed
        )
        if present:
            authenticated, report.credential = _probe(runner)
        config = GitHubCredentialConfig.from_env() if config is None else config
        if not authenticated:
            if _credential_present(home, config.repositories):
                report.status = report.credential = "unverified"
            elif present:
                report.credential = "absent"
            return report
        report.status = "ok"
        template = gate.load_template()
        repositories = gate.repository_inventory(config)
        if not repositories:
            report.issues.append("no gate repository inventory")
        directory = _directory(home)
        state = _read_state(directory)
        path = directory / "forbidden-identifiers"
        if (path.is_symlink() or not path.is_file()
                or any(parent.is_symlink() for parent in path.parents)):
            report.issues.append("denylist absent or unsafe")
        elif stat.S_IMODE(path.stat().st_mode) & 0o077:
            report.issues.append("denylist group/world readable")
        elif stat.S_IMODE(directory.stat().st_mode) & 0o077:
            report.issues.append("denylist parent permissions invalid")
        else:
            value = path.read_text(encoding="utf-8")
            gate.validate_denylist(template, value)
            report.denylist_sha256 = gate.digest(value.encode())
            if report.denylist_sha256 != state.get("denylist_sha256"):
                report.issues.append("denylist recorded digest mismatch")
            if config.denylist_ref:
                try:
                    current = resolver(config.denylist_ref)
                except (ValueError, OSError, subprocess.SubprocessError):
                    report.issues.append("denylist secret resolution unverified")
                else:
                    gate.validate_denylist(template, current)
                    if gate.digest(current.encode()) != report.denylist_sha256:
                        report.issues.append("denylist stale digest")
        for repo in repositories:
            state_name = gate.gate_state(repo, template)
            hook = gate.hook_ok(repo, template)
            ok = state_name in {"canonical-at-pin", "accepted variant"} and hook
            report.repositories.append({"repository": str(repo), "gate": state_name,
                                        "hook_ok": hook, "ok": ok})
            if not ok:
                report.issues.append("repository gate or hook misprovisioned")
    except (ValueError, OSError, subprocess.SubprocessError):
        report.issues.append("GitHub gate verification failed")
        if not authenticated:
            report.credential = "unverified"
    if report.issues:
        report.status = "MISPROVISIONED" if authenticated else "unverified"
    return report


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise gate.GateError("GITHUB_STATE_SYMLINK_REFUSED")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    lock = directory / "github-provision.lock"
    if lock.is_symlink():
        raise gate.GateError("GITHUB_LOCK_SYMLINK_REFUSED")
    descriptor = os.open(lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        # Closing the descriptor releases the advisory lock, including on crash.
        os.close(descriptor)


def _remove_owned(runner: SecretRunner, token_digest: str) -> None:
    actual = _gh(runner, "auth", "token", "--hostname", "github.com")
    if actual.returncode != 0:
        if _probe(runner)[0]:
            raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED")
        return
    if gate.digest(actual.stdout.strip().encode()) != token_digest:
        raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_MISMATCH")
    if _gh(runner, "auth", "logout", "--hostname", "github.com").returncode != 0:
        raise gate.GateError("GITHUB_ROLLBACK_FAILED")
    if _probe(runner)[0]:
        raise gate.GateError("GITHUB_ROLLBACK_FAILED")


def provision_github_credential(
    config: GitHubCredentialConfig, *, dry_run: bool = False, force: bool = False,
    home: Path | None = None, runner: SecretRunner = run,
    resolver: Resolver = resolve_secret_value, inject: FailureInjector | None = None,
) -> dict[str, object]:
    """Denylist -> gate -> hook -> verify -> credential, under one host lock."""
    if config.adapter != "token":
        raise gate.GateError("GITHUB_CREDENTIAL_ADAPTER_UNSUPPORTED")
    if not config.token_ref or not config.denylist_ref:
        raise gate.GateError("GITHUB_SECRET_REF_REQUIRED")
    # Check shapes without ever displaying a ref (windows refs carry ciphertext).
    from agent_suite.secret_refs import ref_static_problem, scheme_of

    for ref in (config.token_ref, config.denylist_ref):
        if scheme_of(ref) not in {"vault", "azure", "windows", "file", "env"}:
            raise gate.GateError("GITHUB_SECRET_REF_INVALID")
        if ref_static_problem(ref) is not None:
            raise gate.GateError("GITHUB_SECRET_REF_INVALID")
    template = gate.load_template()
    if dry_run:
        return {"ok": True, "dry_run": True, "plan": list(PLAN)}
    if sys.platform == "win32":
        raise gate.GateError("GITHUB_CREDENTIAL_PLATFORM_UNSUPPORTED")
    home = Path.home() if home is None else home
    directory = _directory(home)
    try:
        with _locked(directory):
            state = _read_state(directory)
            # Recover an interrupted login only when its recorded digest still
            # proves ownership; never adopt or revoke a different ambient login.
            if state.get("credential_phase") == "installing":
                owned_digest = state.get("token_sha256")
                if not isinstance(owned_digest, str):
                    raise gate.GateError("GITHUB_STATE_INVALID")
                _remove_owned(runner, owned_digest)
                state["credential_phase"] = "removed"
                _write_state(directory, state)
            ambient = _probe(runner)[0]
            if not ambient and _credential_present(home, config.repositories):
                raise gate.GateError("GITHUB_AMBIENT_CREDENTIAL_UNVERIFIED")
            repositories = gate.repository_inventory(config)
            if not repositories:
                raise gate.GateError("GITHUB_GATE_INVENTORY_EMPTY")
            denylist_path = directory / "forbidden-identifiers"
            if denylist_path.exists() and stat.S_IMODE(denylist_path.stat().st_mode) & 0o077:
                raise gate.GateError("GITHUB_DENYLIST_PERMISSIONS_INVALID")
            denylist = resolver(config.denylist_ref)
            gate.validate_denylist(template, denylist)
            state["denylist_sha256"] = gate.digest(denylist.encode())
            state["template_revision"] = gate.PIN
            gate.atomic_write(directory / "forbidden-identifiers", denylist.encode(), 0o600)
            _write_state(directory, state)

            def checkpoint(step: str) -> None:
                if inject is not None:
                    inject(step)

            checkpoint("denylist")
            for repo in repositories:
                gate.install_gate(repo, template, force=force)
            checkpoint("gate")
            for repo in repositories:
                gate.install_hook(repo, template)
            checkpoint("hook")
            if any(gate.gate_state(repo, template) != "canonical-at-pin"
                   or not gate.hook_ok(repo, template) for repo in repositories):
                raise gate.GateError("GITHUB_GATE_VERIFICATION_FAILED")
            installed = directory / "forbidden-identifiers"
            if (gate.digest(installed.read_bytes()) != state["denylist_sha256"]
                    or stat.S_IMODE(installed.stat().st_mode) != 0o600):
                raise gate.GateError("GITHUB_DENYLIST_VERIFICATION_FAILED")
            checkpoint("verify")
            if ambient:
                return {"ok": True, "dry_run": False, "credential": "ambient; not adopted",
                        "plan": list(PLAN)}
            token = resolver(config.token_ref)
            if not token.strip() or "\n" in token or "\r" in token:
                raise gate.GateError("GITHUB_TOKEN_INVALID")
            token_digest = gate.digest(token.encode())
            state.update(token_sha256=token_digest, credential_phase="installing")
            _write_state(directory, state)
            try:
                result = _gh(runner, "auth", "login", "--hostname", "github.com",
                             "--with-token", stdin=token + "\n")
                if result.returncode != 0 or not _probe(runner)[0]:
                    raise gate.GateError("GITHUB_CREDENTIAL_INSTALL_FAILED")
                readback = _gh(runner, "auth", "token", "--hostname", "github.com")
                if (readback.returncode != 0
                        or gate.digest(readback.stdout.strip().encode()) != token_digest):
                    raise gate.GateError("GITHUB_CREDENTIAL_READBACK_FAILED")
                checkpoint("credential")
                state["credential_phase"] = "installed"
                _write_state(directory, state)
            except Exception:
                _remove_owned(runner, token_digest)
                state["credential_phase"] = "removed"
                _write_state(directory, state)
                raise
            return {"ok": True, "dry_run": False, "credential": "installed",
                    "plan": list(PLAN)}
    except gate.GateError:
        raise
    except Exception:
        # Resolver, injected and OS exceptions may contain secret values.
        raise gate.GateError("GITHUB_PROVISIONING_FAILED") from None
