"""Install and inspect the immutable suite gate release artifact."""
from __future__ import annotations

import hashlib
import json
import os
import re
import runpy
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from agent_suite.config import GitHubCredentialConfig

PIN = "5233019143546395b13ee2219045dace75587fb3"
LOCK_SHA256 = "38e68959fcb7cc1354fe31fc8d27b0c6dec71b919373cf1f78fddbb499e261d4"
DATA = Path(__file__).parent / "data"
DENYLIST_VAR = "AGENT_SUITE_FORBIDDEN_IDENTIFIERS"


class GateError(ValueError):
    """A named refusal with no external diagnostics or secret material."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git(repo: Path, *args: str, optional: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args], capture_output=True, text=True,
            timeout=30, check=False,
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
        # Stable generic display name; existing denylist variable is preserved.
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
                self.payload[source].replace(b"@@DENYLIST_VAR@@", variable.encode()).replace(
                    b"@@REPO_NAME@@", b"suite-repository",
                ), mode,
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
            payload, manifest, lock["canonical_gate_hash"],
            hashes("KNOWN_GATE_HASHES"), hashes("VARIANTS"),
        )
    except GateError:
        raise
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise GateError("GATE_TEMPLATE_INVALID") from None


def validate_denylist(template: GateTemplate, value: str) -> None:
    # Execute the pinned parser, rather than approximating its quoting/filtering.
    del template  # load_template verified the executable bytes before this edge.
    try:
        namespace = runpy.run_path(str(DATA / "gate-template" / PIN[:7]
                                       / "check_committed_identifiers.py"))
        parser = cast(Callable[[str], frozenset[str]], namespace["parse_identifier_set"])
        if not parser(value):
            raise GateError("GITHUB_DENYLIST_INVALID")
    except (ValueError, OSError):
        raise GateError("GITHUB_DENYLIST_INVALID") from None


def normalized_gate_hash(value: bytes) -> str:
    return digest(re.sub(rb"[A-Z][A-Z0-9_]*_FORBIDDEN_IDENTIFIERS", b"XX", value))[:16]


def repository_inventory(config: GitHubCredentialConfig) -> tuple[Path, ...]:
    candidates = list(config.repositories)
    for root in config.roots:
        if not root.is_dir():
            raise GateError("GATE_INVENTORY_ROOT_MISSING")

        def unreadable(error: OSError) -> None:
            raise GateError("GATE_INVENTORY_UNREADABLE") from error

        for directory, directories, files in os.walk(root, onerror=unreadable):
            if ".git" in directories or ".git" in files:
                repo = Path(directory)
                remotes = git(repo, "remote", "-v")
                if any(_github_remote(line.split()[1]) for line in remotes.splitlines()):
                    candidates.append(repo)
                    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
                        if line.startswith("worktree "):
                            candidates.append(Path(line[9:]))
            directories[:] = [name for name in directories if name != ".git"]
    repositories: list[Path] = []
    for candidate in candidates:
        repo = Path(git(candidate, "rev-parse", "--show-toplevel")).resolve()
        if repo not in repositories:
            repositories.append(repo)
    return tuple(repositories)


def _github_remote(value: str) -> bool:
    if re.match(r"^(?:[^/@:]+@)?github\.com:", value, re.IGNORECASE):
        return True
    return urlsplit(value).hostname == "github.com"


def gate_state(repo: Path, template: GateTemplate) -> str:
    gate = repo / "scripts/check_committed_identifiers.py"
    if not gate.is_file() or gate.is_symlink():
        return "missing"
    value = normalized_gate_hash(gate.read_bytes())
    if value == template.canonical_hash or value == "827fd9bcf64237dd":
        expected = template.render(repo)
        if all(
            (repo / path).is_file() and not (repo / path).is_symlink()
            and (repo / path).read_bytes() == content
            for path, (content, _) in expected.items() if path != "githooks/pre-push"
        ):
            return "canonical-at-pin"
        return "unknown"
    if value in template.variants:
        return "accepted variant"
    if value in template.known:
        return "stale"
    return "unknown"


def hook_ok(repo: Path, template: GateTemplate) -> bool:
    path = repo / "githooks/pre-push"
    expected, _ = template.render(repo)["githooks/pre-push"]
    configured = git(repo, "config", "--get", "core.hooksPath", optional=True)
    # Relative hooksPath is relative to the worktree for pre-push (non-bare).
    target = Path(configured) if configured else Path(".git/hooks")
    if not target.is_absolute():
        target = repo / target
    return (
        path.is_file() and not path.is_symlink() and path.read_bytes() == expected
        and os.access(path, os.X_OK) and target.resolve() == path.parent.resolve()
    )


def install_gate(repo: Path, template: GateTemplate, *, force: bool = False) -> None:
    state = gate_state(repo, template)
    if state in {"unknown", "accepted variant"} and not force:
        raise GateError("GATE_OVERWRITE_REFUSED")
    for destination, (content, mode) in template.render(repo).items():
        if destination == "githooks/pre-push":
            continue
        path = repo / destination
        if not path.is_file() or path.read_bytes() != content:
            atomic_write(path, content, mode)


def install_hook(repo: Path, template: GateTemplate) -> None:
    content, mode = template.render(repo)["githooks/pre-push"]
    atomic_write(repo / "githooks/pre-push", content, mode)
    # Worktree-local configuration when enabled, otherwise Git's local config.
    scope = "--worktree" if git(
        repo, "config", "--get", "extensions.worktreeConfig", optional=True,
    ) == "true" else "--local"
    # A relative path also works across worktrees sharing the common config.
    git(repo, "config", scope, "core.hooksPath", "githooks")
