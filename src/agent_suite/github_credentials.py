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
from typing import Literal, Protocol, assert_never

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
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError):
        raise gate.GateError("GITHUB_STATE_INVALID") from None
    if not isinstance(value, dict):
        raise gate.GateError("GITHUB_STATE_INVALID")
    if "fingerprint_key" in value:
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


def _hosts_has_github(path: Path) -> bool:
    """Read gh's top-level host mapping; uncertainty is credential evidence.

    gh removes the last user's host entry, but can leave an empty hosts.yml.
    Recognize the block mapping gh writes, quoted keys, and JSON mappings.
    Unsupported/malformed YAML is unverified, never proof of absence.
    """
    try:
        text = gate.read_regular(path).decode("utf-8-sig")
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    if not text.strip():
        return False
    if text.lstrip().startswith("{"):
        try:
            mapping = json.loads(text)
        except ValueError:
            return True
        return not isinstance(mapping, dict) or any(
            str(key).casefold() == "github.com" for key in mapping
        )
    host_seen = False
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or line in {"---", "..."}:
            continue
        if line[0].isspace():
            if not host_seen or "\t" in line or ":" not in line:
                return True
            continue
        match = re.fullmatch(r'''(?:'((?:[^']|'')+)'|"([^"\\]+)"|([\w.-]+))\s*:\s*.*''', line)
        if match is None:
            return True
        host_seen = True
        key = next(value for value in match.groups() if value is not None).replace("''", "'")
        if key.casefold() == "github.com":
            return True
    return False


def _credential_present(
    home: Path, repositories: tuple[Path, ...], *, require_git: bool = False,
) -> bool:
    override = os.environ.get("GH_CONFIG_DIR")
    xdg = os.environ.get("XDG_CONFIG_HOME")
    appdata = os.environ.get("APPDATA")
    config_home = (
        Path(override) if override else
        Path(xdg) / "gh" if xdg else
        Path(appdata) / "GitHub CLI" if _GH_WINDOWS and appdata else
        home / ".config/gh"
    )
    if _hosts_has_github(config_home / "hosts.yml") or any(
        os.environ.get(name) for name in ("GH_TOKEN", "GITHUB_TOKEN")
    ):
        return True
    # Missing PATH must never use a platform's implicit system search path.
    search_path = os.environ.get("PATH", "")
    if not search_path or shutil.which("git", path=search_path) is None:
        if require_git:
            raise gate.GateError("GITHUB_CREDENTIAL_CONFIG_UNVERIFIED")
        return False
    targets = repositories or (home,)
    for repo in targets:
        result = subprocess.run(
            ["git", "-C", str(repo), "config", "--get-regexp",
             r"credential\..*helper|credential\.helper"],
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return True
        if result.returncode not in {0, 1}:
            raise gate.GateError("GITHUB_CREDENTIAL_CONFIG_UNVERIFIED")
    return False


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
        recorded = value.get("token_fingerprint", value.get("token_sha256"))
        if recorded is None and value["phase"] in {"removed", "replaced"}:
            return value
        if not isinstance(recorded, str) or re.fullmatch(r"[0-9a-f]{64}", recorded) is None:
            raise ValueError
        if "token_fingerprint" in value:
            _fingerprint(value, b"")
        for name in ("failure_code", "recovery_error"):
            if name in value and not _named_code(value[name]):
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
    _host_key(state, ownership)
    state.pop("token_sha256", None)
    if phase in {"removed", "replaced"}:
        ownership.pop("token_sha256", None)
    ownership["phase"] = phase
    # Persist recovery evidence before touching the mutable health state.
    _write_ownership(directory, ownership)
    state["credential_phase"] = phase
    if "token_fingerprint" in ownership:
        state["token_fingerprint"] = ownership["token_fingerprint"]
    _write_state(directory, state)


def _rollback(
    directory: Path, state: dict[str, object], ownership: dict[str, object], runner: SecretRunner,
    home: Path, config: GitHubCredentialConfig,
) -> None:
    ownership["phase"] = "rollback_pending"
    _write_ownership(directory, ownership)
    try:
        _phase(directory, state, ownership, "rollback_pending")
    except (ValueError, OSError):
        # A damaged health file must not prevent independently proven removal.
        pass
    disposition, token = _observe_ownership(runner, ownership, home, config)
    if disposition == "owned":
        assert token is not None
        _key_token(directory, state, ownership, token)
        _remove_owned(runner)
        _phase(directory, state, ownership, "removed")
    elif disposition == "removed" or disposition == "replaced":
        _phase(directory, state, ownership, disposition)
    else:
        assert_never(disposition)


def _host_key(state: dict[str, object], ownership: dict[str, object]) -> None:
    key = ownership.get("fingerprint_key", state.get("fingerprint_key", secrets.token_hex(32)))
    _fingerprint({"fingerprint_key": key}, b"")
    state["fingerprint_key"] = ownership["fingerprint_key"] = key


def _matches_token(ownership: dict[str, object], token: str) -> bool:
    if "token_fingerprint" in ownership:
        return hmac.compare_digest(
            _fingerprint(ownership, b"github-token\0" + token.encode()),
            str(ownership["token_fingerprint"]),
        )
    # Read legacy SHA only to establish the old transaction's ownership.
    return hmac.compare_digest(gate.digest(token.encode()), str(ownership.get("token_sha256")))


def _key_token(
    directory: Path, state: dict[str, object], ownership: dict[str, object], token: str,
) -> None:
    _host_key(state, ownership)
    ownership["token_fingerprint"] = _fingerprint(ownership, b"github-token\0" + token.encode())
    ownership.pop("token_sha256", None)
    _phase(directory, state, ownership, str(ownership["phase"]))


def _named_code(value: object) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"(?:GITHUB|GATE|SECRET)_[A-Z0-9_]+", value) is not None
    )


def _error_code(error: Exception) -> str:
    if isinstance(error, gate.GateError) and _named_code(str(error)):
        return str(error)
    return "GITHUB_PROVISIONING_FAILED"


def _observe_ownership(
    runner: SecretRunner, ownership: dict[str, object], home: Path, config: GitHubCredentialConfig,
) -> tuple[Literal["owned", "removed", "replaced"], str | None]:
    actual = _gh(runner, "auth", "token", "--hostname", "github.com")
    token = actual.stdout.strip()
    if actual.returncode == 0 and token:
        return ("owned" if _matches_token(ownership, token) else "replaced"), token
    if not _probe(runner)[0] and not _credential_present(
        home, gate.repository_inventory(config), require_git=True,
    ):
        return "removed", None
    raise gate.GateError("GITHUB_ROLLBACK_OWNERSHIP_UNVERIFIED")


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
    probe_failed = False
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
                probe_failed = True
                report.notes.append("GitHub authentication probe unverified")
        config = GitHubCredentialConfig.from_env() if config is None else config
        repositories = gate.repository_inventory(config)
        directory = _directory(home)
        ownership = _read_ownership(directory)
        credential_present = _credential_present(home, repositories) or bool(
            ownership.get("phase") in {"installing", "installed", "rollback_pending"}
        )
        if not authenticated and not credential_present and not probe_failed:
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
        needs_reprovision = "fingerprint_key" not in state
        if needs_reprovision:
            report.issues.append("GITHUB_STATE_REPROVISION_REQUIRED")
        if (state.get("credential_phase") in {"installing", "rollback_pending"}
                or ownership.get("phase") in {"installing", "rollback_pending"}):
            report.issues.append("credential transaction interrupted; recovery required")
            if "recovery_error" in ownership:
                report.issues.append(str(ownership["recovery_error"]))
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
                if needs_reprovision:
                    raise gate.GateError("GITHUB_STATE_REPROVISION_REQUIRED")
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
            if not gate.script_imports_ok(repo):
                report.issues.append("GATE_SCRIPT_IMPORT_SHADOW")
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


def _remove_owned(runner: SecretRunner) -> None:
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
                    "installing", "installed", "rollback_pending", "removed", "replaced",
                }:
                    token_digest = state.get("token_fingerprint", state.get("token_sha256"))
                    if (not isinstance(token_digest, str)
                            or re.fullmatch(r"[0-9a-f]{64}", token_digest) is None):
                        raise gate.GateError("GITHUB_STATE_INVALID")
                    ownership = {"phase": state["credential_phase"]}
                    if "token_fingerprint" in state:
                        ownership.update(token_fingerprint=token_digest,
                                         fingerprint_key=state.get("fingerprint_key"))
                    else:
                        ownership["token_sha256"] = token_digest
                if (ownership.get("phase") in {"installing", "rollback_pending"}
                        or (ownership.get("phase") == "installed"
                            and state.get("credential_phase") in {
                                "installing", "rollback_pending",
                            })):
                    _rollback(directory, state, ownership, runner, home, config)
                elif ownership.get("phase") == "installed":
                    disposition, actual_token = _observe_ownership(runner, ownership, home, config)
                    if disposition == "owned":
                        assert actual_token is not None
                        _key_token(directory, state, ownership, actual_token)
                    elif disposition == "removed" or disposition == "replaced":
                        _phase(directory, state, ownership, disposition)
                    else:
                        assert_never(disposition)
                residual = False
                if ownership.get("phase") in {"removed", "replaced"}:
                    actual = _gh(runner, "auth", "token", "--hostname", "github.com")
                    residual = actual.returncode == 0 and _matches_token(
                        ownership, actual.stdout.strip(),
                    )
                    if residual:
                        _key_token(directory, state, ownership, actual.stdout.strip())
                    else:
                        _phase(directory, state, ownership, str(ownership["phase"]))
                _host_key(state, ownership)
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
                    label = (
                        "suite-owned; already installed"
                        if state.get("credential_phase") == "installed"
                        else "ambient; not adopted"
                    )
                    if residual:
                        label += "; residual credential matches prior transaction"
                    return {
                        "ok": True,
                        "dry_run": False,
                        "credential": label,
                        "plan": list(PLAN),
                    }
                token = resolver(config.token_ref)
                if not token.strip() or token != token.strip() or "\n" in token or "\r" in token:
                    raise gate.GateError("GITHUB_TOKEN_INVALID")
                ownership = {"fingerprint_key": state["fingerprint_key"], "phase": "installing"}
                token_fingerprint = _fingerprint(ownership, b"github-token\0" + token.encode())
                ownership["token_fingerprint"] = token_fingerprint
                _phase(directory, state, ownership, "installing")
                result = _gh(
                    runner, "auth", "login", "--hostname", "github.com", "--with-token",
                    stdin=token + "\n",
                )
                if result.returncode != 0 or not _probe(runner)[0]:
                    raise gate.GateError("GITHUB_CREDENTIAL_INSTALL_FAILED")
                readback = _gh(runner, "auth", "token", "--hostname", "github.com")
                if (readback.returncode != 0
                        or not _matches_token(ownership, readback.stdout.strip())):
                    raise gate.GateError("GITHUB_CREDENTIAL_READBACK_FAILED")
                checkpoint("credential")
                _phase(directory, state, ownership, "installed")
                return {"ok": True, "dry_run": False, "credential": "installed", "plan": list(PLAN)}
            except Exception as error:
                first_code = _error_code(error)
                if ownership.get("phase") in {"installing", "installed", "rollback_pending"}:
                    ownership.setdefault("failure_code", first_code)
                    try:
                        _rollback(directory, state, ownership, runner, home, config)
                    except Exception as recovery_error:
                        ownership["recovery_error"] = _error_code(recovery_error)
                        try:
                            _write_ownership(directory, ownership)
                        except (ValueError, OSError):
                            pass  # Keep the first cause; earlier journal writes retain recovery.
                raise gate.GateError(first_code) from None
    except gate.GateError:
        raise
    except Exception:
        # Resolver, injected and OS exceptions may contain secret values.
        raise gate.GateError("GITHUB_PROVISIONING_FAILED") from None
