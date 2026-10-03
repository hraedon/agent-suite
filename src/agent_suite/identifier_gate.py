"""Install and inspect the immutable suite gate release artifact."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent_suite.config import GitHubCredentialConfig

PIN = "5233019143546395b13ee2219045dace75587fb3"
LOCK_SHA256 = "1198f6d76bf04840c06201c7f4ebe0923d820459afb5639d671d48fb70068cd8"
DATA = Path(__file__).parent / "data"
DENYLIST_VAR = "AGENT_SUITE_FORBIDDEN_IDENTIFIERS"


class GateError(ValueError):
    """A named refusal with no external diagnostics or secret material."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str, optional: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        raise GateError("GATE_REPOSITORY_UNREACHABLE") from None
    if result.returncode != 0 and not optional:
        raise GateError("GATE_REPOSITORY_INVALID")
    return result.stdout.strip() if result.returncode == 0 else ""


def atomic_write(path: Path, data: bytes, mode: int) -> None:
    """Replace atomically; never follow a destination or parent symlink."""
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise GateError("GATE_SYMLINK_REFUSED")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".suite-gate-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.chmod(name, mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@dataclass(frozen=True)
class GateTemplate:
    payload: dict[str, bytes]
    manifest: tuple[tuple[str, str, int], ...]
    canonical_hash: str
    known: frozenset[str]
    variants: frozenset[str]

    def render(self, repo: Path) -> dict[str, tuple[bytes, int]]:
        # Match the pinned sync script: actual repo name and existing variable.
        # The name also appears inside Bash strings and comments. Keep it data.
        if repo.name in {".", ".."} or re.fullmatch(r"[A-Za-z0-9_.-]+", repo.name) is None:
            raise GateError("GATE_REPOSITORY_NAME_UNSAFE")
        variable = DENYLIST_VAR
        gate = repo / "scripts/check_committed_identifiers.py"
        if gate.is_file():
            found = re.findall(
                rb'environ\.get\(\s*[\'"]([A-Z0-9_]*FORBIDDEN_IDENTIFIERS)[\'"]',
                gate.read_bytes(),
            )
            if len(set(found)) == 1:
                variable = found[0].decode("ascii")
        return {
            destination: (
                self.payload[source]
                .replace(b"@@DENYLIST_VAR@@", variable.encode())
                .replace(
                    b"@@REPO_NAME@@",
                    repo.name.encode(),
                ),
                mode,
            )
            for source, destination, mode in self.manifest
        }


def load_template(data: Path = DATA) -> GateTemplate:
    try:
        lock_bytes = (data / "gate-template.lock.json").read_bytes()
        if digest(lock_bytes) != LOCK_SHA256:
            raise GateError("GATE_TEMPLATE_LOCK_INVALID")
        lock = json.loads(lock_bytes)
        if lock["revision"] != PIN:
            raise GateError("GATE_TEMPLATE_PIN_INVALID")
        snapshot = data / "gate-template" / PIN[:7]
        payload = {name: (snapshot / name).read_bytes() for name in lock["files"]}
        if any(digest(value) != lock["files"][name] for name, value in payload.items()):
            raise GateError("GATE_TEMPLATE_DIGEST_MISMATCH")
        manifest = tuple(
            (fields[0], fields[1], int(fields[2], 8))
            for line in payload["MANIFEST"].decode().splitlines()
            if (fields := line.split()) and not line.startswith("#")
        )

        def hashes(name: str) -> frozenset[str]:
            return frozenset(
                match.group(1)
                for line in payload[name].decode().splitlines()
                if (match := re.match(r"^([0-9a-f]{16})\s", line))
            )

        return GateTemplate(
            payload,
            manifest,
            lock["canonical_gate_hash"],
            hashes("KNOWN_GATE_HASHES"),
            hashes("VARIANTS"),
        )
    except GateError:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise GateError("GATE_TEMPLATE_INVALID") from None


def validate_denylist(template: GateTemplate, value: str) -> None:
    # Execute only verified in-memory bytes. dataclasses requires a module.
    name = "_suite_gate_parser_" + uuid.uuid4().hex
    module = types.ModuleType(name)
    sys.modules[name] = module
    try:
        exec(
            compile(
                template.payload["check_committed_identifiers.py"],
                "<verified-pinned-identifier-parser>",
                "exec",
            ),
            module.__dict__,
        )
        parser = cast(Callable[[str], frozenset[str]], module.__dict__["parse_identifier_set"])
        if not parser(value):
            raise GateError("GITHUB_DENYLIST_INVALID")
    except (ValueError, OSError):
        raise GateError("GITHUB_DENYLIST_INVALID") from None
    finally:
        del sys.modules[name]


def read_regular(path: Path, *, private: bool = False) -> bytes:
    """Check and read the same descriptor, refusing nonregular files/symlink swaps."""
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        raise GateError("GATE_SYMLINK_REFUSED")
    flags = (os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
             | getattr(os, "O_BINARY", 0))
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        mode = os.fstat(stream.fileno()).st_mode
        if not stat.S_ISREG(mode) or (private and stat.S_IMODE(mode) & 0o077):
            raise GateError("GATE_FILE_PERMISSIONS_INVALID")
        return stream.read()


def normalized_gate_hash(value: bytes) -> str:
    return digest(re.sub(rb"[A-Z][A-Z0-9_]*_FORBIDDEN_IDENTIFIERS", b"XX", value))[:16]


def repository_inventory(config: GitHubCredentialConfig) -> tuple[Path, ...]:
    candidates = list(config.repositories)
    visited: set[Path] = set()

    def unreadable(error: OSError) -> None:
        raise GateError("GATE_INVENTORY_UNREADABLE") from error

    def discover(root: Path) -> None:
        if not root.is_dir():
            raise GateError("GATE_INVENTORY_ROOT_MISSING")
        # Follow directory links, tracking resolved paths to terminate cycles.
        # No remote is necessary for `git push URL`.
        for directory, directories, files in os.walk(
            root, onerror=unreadable, followlinks=True,
        ):
            repo = Path(directory).resolve()
            if repo in visited:
                directories.clear()
                continue
            visited.add(repo)
            if ".git" in directories or ".git" in files:
                candidates.append(repo)
            elif "HEAD" in files and "objects" in directories:
                if git(repo, "rev-parse", "--is-bare-repository", optional=True) == "true":
                    raise GateError("GATE_BARE_REPOSITORY_UNSUPPORTED")
                if git(repo, "rev-parse", "--git-dir", optional=True):
                    candidates.append(repo)
            directories[:] = [name for name in directories if name != ".git"]

    for root in (*config.repositories, *config.roots):
        discover(root)
    repositories: list[Path] = []
    for candidate in candidates:
        if git(candidate, "rev-parse", "--is-bare-repository") == "true":
            raise GateError("GATE_BARE_REPOSITORY_UNSUPPORTED")
        repo = Path(git(candidate, "rev-parse", "--show-toplevel")).resolve()
        if repo not in repositories:
            repositories.append(repo)
            linked = tuple(
                Path(field[9:])
                for field in git(repo, "worktree", "list", "--porcelain", "-z").split("\0")
                if field.startswith("worktree ")
            )
            candidates.extend(linked)
            # Initialized submodules/nested repos in every linked worktree count.
            for worktree in linked:
                discover(worktree)
    return tuple(repositories)


def gate_state(repo: Path, template: GateTemplate) -> str:
    gate = repo / "scripts/check_committed_identifiers.py"
    if not gate.is_file() or gate.is_symlink():
        return "missing"
    value = normalized_gate_hash(gate.read_bytes())
    if value == template.canonical_hash:
        expected = template.render(repo)
        if all(
            (repo / path).is_file()
            and not (repo / path).is_symlink()
            and (repo / path).read_bytes() == content
            for path, (content, _) in expected.items()
            if path != "githooks/pre-push"
        ):
            return "canonical-at-pin"
        return "unknown"
    if value in template.variants:
        expected = template.render(repo)
        if all(
            (repo / path).is_file()
            and not (repo / path).is_symlink()
            and (repo / path).read_bytes() == content
            for path, (content, _) in expected.items()
            if path not in {"githooks/pre-push", "scripts/check_committed_identifiers.py"}
        ):
            return "accepted variant (not the pinned canonical)"
        return "unknown"
    if value in template.known:
        return "stale"
    return "unknown"


def effective_hooks(repo: Path) -> Path:
    """Ask Git to expand and resolve hooksPath for this particular worktree."""
    path = Path(git(repo, "rev-parse", "--git-path", "hooks"))
    return path if path.is_absolute() else repo / path


def hooks_directory_matches(repo: Path) -> bool:
    try:
        return os.path.samefile(effective_hooks(repo), repo / "githooks")
    except OSError:
        return False


def hook_config_included(repo: Path) -> bool:
    """Inspect all declared includes, including currently inactive includeIf files.

    Git parses the files and expands path values; conditional applicability can
    change later, so an included hooksPath cannot be certified statically.
    """
    pattern = r"^(include|includeif\..*)\.path$"
    pending = [git(repo, "config", "--null", "--show-origin", "--type=path",
                   "--get-regexp", pattern, optional=True)]
    seen: set[Path] = set()
    while pending:
        entries = pending.pop().split("\0")
        for index in range(0, len(entries) - 1, 2):
            origin, entry = entries[index:index + 2]
            if not origin.startswith("file:") or "\n" not in entry:
                return True
            source = Path(origin.removeprefix("file:"))
            if not source.is_absolute():
                source = repo / source
            included = Path(entry.split("\n", 1)[1])
            if not included.is_absolute():
                included = source.parent / included
            included = included.absolute()
            if included in seen:
                continue
            seen.add(included)
            if not included.exists():
                # A missing conditional file can acquire hook settings later.
                return True
            git(repo, "config", "--file", str(included), "--no-includes", "--list")
            if git(repo, "config", "--file", str(included), "--no-includes",
                   "--get-regexp", r"^core\.hookspath$", optional=True):
                return True
            pending.append(git(repo, "config", "--file", str(included), "--no-includes",
                               "--null", "--show-origin", "--type=path",
                               "--get-regexp", pattern, optional=True))
    return False


def hook_ok(repo: Path, template: GateTemplate) -> bool:
    path = repo / "githooks/pre-push"
    expected, _ = template.render(repo)["githooks/pre-push"]
    return (
        path.is_file()
        and not path.is_symlink()
        and not any(parent.is_symlink() or parent.is_junction() for parent in path.parents)
        and path.read_bytes() == expected
        and os.access(path, os.X_OK)
        and hooks_directory_matches(repo)
        and hook_interpreter_ok(repo)
        and script_imports_ok(repo)
    )


def script_imports_ok(repo: Path) -> bool:
    """The pinned scripts directory must not override standard-library imports."""
    return script_import_issue(repo) is None


def script_import_issue(repo: Path) -> str | None:
    scripts = repo / "scripts"
    if not scripts.exists():
        return "GATE_SCRIPTS_MISSING"
    try:
        safe = all(
            entry.name != "__pycache__"
            and entry.suffix != ".pyc"
            and not (
                (entry.is_dir() or entry.suffix in {".py", ".pyi", ".so", ".pyd"})
                and entry.name.split(".", 1)[0] in sys.stdlib_module_names
            )
            for entry in scripts.iterdir()
        )
    except OSError:
        return "GATE_SCRIPTS_UNREADABLE"
    return None if safe else "GATE_SCRIPT_IMPORT_SHADOW"


def hook_inputs_ok(repo: Path, denylist: bytes) -> bool:
    """Local denylist overrides must equal the secret delivered to this host."""
    local = repo / ".identifiers-denylist.local"
    try:
        return (not local.exists() and not local.is_symlink()) or read_regular(local) == denylist
    except (OSError, ValueError):
        return False


def hook_interpreter_ok(repo: Path) -> bool:
    """Reject stubs without executing repository code.

    Accept a venv symlink or copy of the suite Python. Unknown executable
    interpreters require recreating the venv using the suite's Python.
    """
    interpreter = repo / ".venv/bin/python"
    if not os.access(interpreter, os.X_OK):
        return True
    try:
        return interpreter.resolve() == Path(sys.executable).resolve() or (
            digest(interpreter.read_bytes()) == digest(Path(sys.executable).read_bytes())
        )
    except OSError:
        return False


def install_gate(repo: Path, template: GateTemplate, *, force: bool = False) -> None:
    state = gate_state(repo, template)
    if state in {"unknown", "accepted variant (not the pinned canonical)"} and not force:
        raise GateError("GATE_OVERWRITE_REFUSED")
    for destination, (content, mode) in template.render(repo).items():
        if destination == "githooks/pre-push":
            continue
        path = repo / destination
        if not path.is_file() or path.read_bytes() != content:
            atomic_write(path, content, mode)


def check_hook_overwrite(repo: Path, template: GateTemplate, *, force: bool = False) -> None:
    if force:
        return
    if hook_config_included(repo):
        raise GateError("GATE_HOOK_CONFIG_UNVERIFIED")
    configured = git(repo, "config", "--get", "core.hooksPath", optional=True)
    if configured:
        if not hooks_directory_matches(repo):
            raise GateError("GATE_HOOK_OVERWRITE_REFUSED")
    else:
        hooks = effective_hooks(repo)
        if hooks.is_dir() and any(
            entry.is_file() and not entry.name.endswith(".sample") and os.access(entry, os.X_OK)
            for entry in hooks.iterdir()
        ):
            raise GateError("GATE_HOOK_OVERWRITE_REFUSED")
    path = repo / "githooks/pre-push"
    if path.exists() or path.is_symlink():
        expected, _ = template.render(repo)["githooks/pre-push"]
        if path.is_symlink() or not path.is_file() or path.read_bytes() != expected:
            raise GateError("GATE_HOOK_OVERWRITE_REFUSED")


def install_hook(repo: Path, template: GateTemplate, *, force: bool = False) -> None:
    check_hook_overwrite(repo, template, force=force)
    content, mode = template.render(repo)["githooks/pre-push"]
    atomic_write(repo / "githooks/pre-push", content, mode)
    # Worktree-local configuration when enabled, otherwise Git's local config.
    scope = (
        "--worktree"
        if git(
            repo,
            "config",
            "--get",
            "extensions.worktreeConfig",
            optional=True,
        )
        == "true"
        else "--local"
    )
    # A relative path also works across worktrees sharing the common config.
    git(repo, "config", scope, "core.hooksPath", "githooks")
    if not hooks_directory_matches(repo):
        raise GateError("GITHUB_GATE_VERIFICATION_FAILED")
