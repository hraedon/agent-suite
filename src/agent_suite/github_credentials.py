"""BR-50: reference-only GitHub token installation after gate verification."""

from __future__ import annotations

import errno
import hashlib
import hmac
import json
import os
import re
import secrets
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
_GH_WINDOWS = sys.platform == "win32"
Resolver = Callable[[str], str]
FailureInjector = Callable[[str], None]


class SecretRunner(Protocol):
    def __call__(
        self,
        argv: tuple[str, ...],
        stdin: str | None = None,
    ) -> subprocess.CompletedProcess[str]: ...


def run(argv: tuple[str, ...], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    # No value is passed through argv, diagnostics, or a newly created env var.
    if argv and argv[0] == "gh":
        search_path = os.environ.get("PATH", "")
        executable = shutil.which("gh", path=search_path) if search_path else None
        if executable is None:
            raise gate.GateError("GITHUB_CLI_UNREACHABLE")
        argv = (executable, *argv[1:])
    return subprocess.run(
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _gh(
    runner: SecretRunner,
    *args: str,
    stdin: str | None = None,
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
    denylist_fingerprint: str | None = None
    notes: list[str] = field(default_factory=lambda: [
        "ssh credential not inspected", "Python startup customization not inspected",
    ])

    @property
    def ok(self) -> bool:
        return self.status != "MISPROVISIONED"

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "credential": self.credential,
            "ok": self.ok,
            "issues": self.issues,
            "repositories": self.repositories,
            "denylist_fingerprint": self.denylist_fingerprint,
            "notes": self.notes,
        }


def _directory(home: Path) -> Path:
    return home / ".config/agent-suite"


def _read_state(directory: Path) -> dict[str, object]:
    path = directory / "github-credential-state.json"
    try:
        raw = gate.read_regular(path, private=True)
    except FileNotFoundError:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise gate.GateError("GITHUB_STATE_INVALID")
    _fingerprint(value, b"")
    return value


def _write_state(directory: Path, state: dict[str, object]) -> None:
    gate.atomic_write(
        directory / "github-credential-state.json",
        (json.dumps(state, sort_keys=True) + "\n").encode(),
        0o600,
    )


def _fingerprint(state: dict[str, object], value: bytes) -> str:
    key = state.get("fingerprint_key")
    if not isinstance(key, str) or re.fullmatch(r"[0-9a-f]{64}", key) is None:
        raise gate.GateError("GITHUB_FINGERPRINT_KEY_INVALID")
    return hmac.new(bytes.fromhex(key), value, hashlib.sha256).hexdigest()


def _credential_present(home: Path, repositories: tuple[Path, ...]) -> bool:
    override = os.environ.get("GH_CONFIG_DIR")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    appdata = os.environ.get("APPDATA")
    config_home = (
        Path(override) if override else
        Path(xdg) / "gh" if xdg else
        Path(appdata) / "GitHub CLI" if _GH_WINDOWS and appdata else
        home / ".config/gh"
    )
    if (config_home / "hosts.yml").exists() or any(
        os.environ.get(name) for name in ("GH_TOKEN", "GITHUB_TOKEN")
    ):
        return True
    # Missing PATH must never use a platform's implicit system search path.
    search_path = os.environ.get("PATH", "")
    if not search_path or shutil.which("git", path=search_path) is None:
        return False
    targets = repositories or (home,)
    return any(
        gate.git(
            repo, "config", "--get-regexp",
            r"credential\..*helper|credential\.helper", optional=True,
        )
        for repo in targets
    )


def _read_ownership(directory: Path) -> dict[str, object]:
    try:
        raw = gate.read_regular(directory / "github-credential-ownership.json", private=True)
    except FileNotFoundError:
        return {}
    try:
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("phase") not in {
            "installing", "installed", "rollback_pending", "removed", "replaced",
        }:
            raise ValueError
        token_digest = value.get("token_sha256")
        if not isinstance(token_digest, str) or re.fullmatch(r"[0-9a-f]{64}", token_digest) is None:
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise gate.GateError("GITHUB_OWNERSHIP_JOURNAL_INVALID") from None


def _write_ownership(directory: Path, ownership: dict[str, object]) -> None:
    gate.atomic_write(
        directory / "github-credential-ownership.json",
        (json.dumps(ownership, sort_keys=True) + "\n").encode(), 0o600,
    )


def _phase(
    directory: Path, state: dict[str, object], ownership: dict[str, object], phase: str,
) -> None:
    ownership["phase"] = phase
    # Persist recovery evidence before touching the mutable health state.
    _write_ownership(directory, ownership)
    state["credential_phase"] = phase
    state["token_sha256"] = ownership["token_sha256"]
    state.setdefault("fingerprint_key", secrets.token_hex(32))
    _write_state(directory, state)


def _rollback(
    directory: Path, state: dict[str, object], ownership: dict[str, object], runner: SecretRunner,
) -> None:
    ownership["phase"] = "rollback_pending"
    _write_ownership(directory, ownership)
    try:
        _phase(directory, state, ownership, "rollback_pending")
    except (ValueError, OSError):
        # A damaged health file must not prevent independently proven removal.
        pass
    token_digest = ownership["token_sha256"]
    assert isinstance(token_digest, str)
    _remove_owned(runner, token_digest)
    _phase(directory, state, ownership, "removed")


def _environment_inputs_ok(state: dict[str, object], denylist: bytes) -> bool:
    expected = _fingerprint(state, denylist)
    return all(
        not value or _fingerprint(state, value.encode()) == expected
        for name, value in os.environ.items() if name.endswith("FORBIDDEN_IDENTIFIERS")
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
    config: GitHubCredentialConfig | None = None,
    *,
    home: Path | None = None,
    runner: SecretRunner = run,
    resolver: Resolver = resolve_secret_value,
    gh_installed: bool | None = None,
) -> GitHubHealth:
    """Read-only host and per-repository health. Never emit child output."""
    home = Path.home() if home is None else home
    report = GitHubHealth()
    authenticated = False
    credential_present = False
    try:
        present = (
            bool(os.environ.get("PATH"))
            and shutil.which("gh", path=os.environ["PATH"]) is not None
            if gh_installed is None
            else gh_installed
        )
        if present:
            try:
                authenticated, report.credential = _probe(runner)
            except (ValueError, OSError, subprocess.SubprocessError):
                report.notes.append("GitHub authentication probe unverified")
        config = GitHubCredentialConfig.from_env() if config is None else config
        repositories = gate.repository_inventory(config)
        directory = _directory(home)
        ownership = _read_ownership(directory)
        credential_present = _credential_present(home, repositories) or bool(
            ownership.get("phase") in {"installing", "installed", "rollback_pending"}
        )
        if not authenticated and not credential_present:
            report.credential = "absent"
            return report
        report.status = "ok" if authenticated else "unverified"
        if not authenticated:
            report.credential = "unverified"
        template = gate.load_template()
        if not repositories:
            report.issues.append("no gate repository inventory")
        directory = _directory(home)
        state = _read_state(directory)
        if (state.get("credential_phase") in {"installing", "rollback_pending"}
                or ownership.get("phase") in {"installing", "rollback_pending"}):
            report.issues.append("credential transaction interrupted; recovery required")
        path = directory / "forbidden-identifiers"
        denylist: bytes | None = None
        if (
            path.is_symlink()
            or not path.is_file()
            or any(parent.is_symlink() for parent in path.parents)
        ):
            report.issues.append("denylist absent or unsafe")
        elif stat.S_IMODE(directory.stat().st_mode) & 0o077:
            report.issues.append("denylist parent permissions invalid")
        else:
            try:
                denylist = gate.read_regular(path, private=True)
                value = denylist.decode("utf-8")
                gate.validate_denylist(template, value)
                report.denylist_fingerprint = _fingerprint(state, denylist)
                if not _environment_inputs_ok(state, denylist):
                    report.issues.append("denylist environment override mismatch")
                if report.denylist_fingerprint != state.get("denylist_fingerprint"):
                    report.issues.append("denylist recorded digest mismatch")
                if config.denylist_ref:
                    try:
                        current = resolver(config.denylist_ref)
                    except (ValueError, OSError, subprocess.SubprocessError):
                        report.issues.append("denylist secret resolution unverified")
                    else:
                        gate.validate_denylist(template, current)
                        if _fingerprint(state, current.encode()) != report.denylist_fingerprint:
                            report.issues.append("denylist stale digest")
            except (ValueError, OSError):
                report.issues.append("denylist invalid or unsafe")
        for repo in repositories:
            state_name = gate.gate_state(repo, template)
            hook = gate.hook_ok(repo, template)
            inputs = denylist is not None and gate.hook_inputs_ok(repo, denylist)
            ok = (
                state_name
                in {
                    "canonical-at-pin",
                    "accepted variant (not the pinned canonical)",
                }
                and hook
                and inputs
            )
            report.repositories.append(
                {
                    "repository": str(repo),
                    "gate": state_name,
                    "hook_ok": hook,
                    "denylist_ok": inputs,
                    "ok": ok,
                }
            )
            if not ok:
                report.issues.append("repository gate or hook misprovisioned")
    except (ValueError, OSError, subprocess.SubprocessError):
        report.issues.append("GitHub gate verification failed")
        if not authenticated:
            report.credential = "unverified"
    if report.issues:
        report.status = "MISPROVISIONED"
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
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN}:
                raise gate.GateError("GITHUB_PROVISIONING_LOCKED") from None
            raise gate.GateError("GITHUB_PROVISIONING_LOCK_FAILED") from None
        yield
    finally:
        # Closing the descriptor releases the advisory lock, including on crash.
        os.close(descriptor)


def _remove_owned(runner: SecretRunner, token_digest: str) -> None:
    actual = _gh(runner, "auth", "token", "--hostname", "github.com")
    if actual.returncode != 0:
        raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED")
    if gate.digest(actual.stdout.strip().encode()) != token_digest:
        raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_MISMATCH")
    if _gh(runner, "auth", "logout", "--hostname", "github.com").returncode != 0:
        raise gate.GateError("GITHUB_ROLLBACK_FAILED")
    if (_gh(runner, "auth", "token", "--hostname", "github.com").returncode == 0
            or _probe(runner)[0]):
        raise gate.GateError("GITHUB_ROLLBACK_FAILED")


def provision_github_credential(
    config: GitHubCredentialConfig,
    *,
    dry_run: bool = False,
    force: bool = False,
    home: Path | None = None,
    runner: SecretRunner = run,
    resolver: Resolver = resolve_secret_value,
    inject: FailureInjector | None = None,
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
    if dry_run:
        gate.load_template()
        return {"ok": True, "dry_run": True, "plan": list(PLAN)}
    if sys.platform == "win32":
        raise gate.GateError("GITHUB_CREDENTIAL_PLATFORM_UNSUPPORTED")
    home = Path.home() if home is None else home
    directory = _directory(home)
    try:
        with _locked(directory):
            state: dict[str, object] = {}
            ownership: dict[str, object] = {}
            try:
                ownership = _read_ownership(directory)
                state = _read_state(directory)
                # Migrate existing suite-owned state, never an ambient login.
                if not ownership and state.get("credential_phase") in {
                    "installing", "installed", "rollback_pending",
                }:
                    token_digest = state.get("token_sha256")
                    if (not isinstance(token_digest, str)
                            or re.fullmatch(r"[0-9a-f]{64}", token_digest) is None):
                        raise gate.GateError("GITHUB_STATE_INVALID")
                    ownership = {"phase": state["credential_phase"], "token_sha256": token_digest}
                    _write_ownership(directory, ownership)
                if (ownership.get("phase") in {"installing", "rollback_pending"}
                        or (ownership.get("phase") == "installed"
                            and state.get("credential_phase") in {
                                "installing", "rollback_pending",
                            })):
                    _rollback(directory, state, ownership, runner)
                elif ownership.get("phase") == "installed":
                    actual = _gh(runner, "auth", "token", "--hostname", "github.com")
                    if actual.returncode != 0:
                        raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED")
                    if gate.digest(actual.stdout.strip().encode()) != ownership["token_sha256"]:
                        _phase(directory, state, ownership, "replaced")
                template = gate.load_template()
                repositories = gate.repository_inventory(config)
                ambient = _probe(runner)[0]
                if not ambient and _credential_present(home, repositories):
                    raise gate.GateError("GITHUB_AMBIENT_CREDENTIAL_UNVERIFIED")
                if not repositories:
                    raise gate.GateError("GITHUB_GATE_INVENTORY_EMPTY")
                for repo in repositories:
                    gate.check_hook_overwrite(repo, template, force=force)
                denylist_path = directory / "forbidden-identifiers"
                if denylist_path.exists() and stat.S_IMODE(denylist_path.stat().st_mode) & 0o077:
                    raise gate.GateError("GITHUB_DENYLIST_PERMISSIONS_INVALID")
                denylist = resolver(config.denylist_ref)
                gate.validate_denylist(template, denylist)
                state.setdefault("fingerprint_key", secrets.token_hex(32))
                state.pop("denylist_sha256", None)
                state["denylist_fingerprint"] = _fingerprint(state, denylist.encode())
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
                    gate.install_hook(repo, template, force=force)
                checkpoint("hook")
                if any(
                    gate.gate_state(repo, template) != "canonical-at-pin"
                    or not gate.hook_ok(repo, template)
                    or not gate.hook_inputs_ok(repo, denylist.encode())
                    for repo in repositories
                ):
                    raise gate.GateError("GITHUB_GATE_VERIFICATION_FAILED")
                if not _environment_inputs_ok(state, denylist.encode()):
                    raise gate.GateError("GITHUB_DENYLIST_ENVIRONMENT_MISMATCH")
                installed = directory / "forbidden-identifiers"
                if (
                    _fingerprint(state, gate.read_regular(installed, private=True))
                    != state["denylist_fingerprint"]
                    or stat.S_IMODE(installed.stat().st_mode) != 0o600
                ):
                    raise gate.GateError("GITHUB_DENYLIST_VERIFICATION_FAILED")
                checkpoint("verify")
                if ambient:
                    return {
                        "ok": True,
                        "dry_run": False,
                        "credential": (
                            "suite-owned; already installed"
                            if state.get("credential_phase") == "installed"
                            else "ambient; not adopted"
                        ),
                        "plan": list(PLAN),
                    }
                token = resolver(config.token_ref)
                if not token.strip() or "\n" in token or "\r" in token:
                    raise gate.GateError("GITHUB_TOKEN_INVALID")
                token_digest = gate.digest(token.encode())
                ownership = {"token_sha256": token_digest, "phase": "installing"}
                _phase(directory, state, ownership, "installing")
                result = _gh(
                    runner, "auth", "login", "--hostname", "github.com", "--with-token",
                    stdin=token + "\n",
                )
                if result.returncode != 0 or not _probe(runner)[0]:
                    raise gate.GateError("GITHUB_CREDENTIAL_INSTALL_FAILED")
                readback = _gh(runner, "auth", "token", "--hostname", "github.com")
                if (readback.returncode != 0
                        or gate.digest(readback.stdout.strip().encode()) != token_digest):
                    raise gate.GateError("GITHUB_CREDENTIAL_READBACK_FAILED")
                checkpoint("credential")
                _phase(directory, state, ownership, "installed")
                return {"ok": True, "dry_run": False, "credential": "installed", "plan": list(PLAN)}
            except Exception:
                if ownership.get("phase") in {"installing", "installed", "rollback_pending"}:
                    _rollback(directory, state, ownership, runner)
                raise
    except gate.GateError:
        raise
    except Exception:
        # Resolver, injected and OS exceptions may contain secret values.
        raise gate.GateError("GITHUB_PROVISIONING_FAILED") from None
