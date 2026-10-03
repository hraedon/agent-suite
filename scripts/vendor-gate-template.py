#!/usr/bin/env python3
"""Vendor a clean, committed gate template; never read payloads from its worktree."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

FILES = (
    "MANIFEST",
    "KNOWN_GATE_HASHES",
    "VARIANTS",
    "PROVENANCE",
    "check_committed_identifiers.py",
    "check_publication_plumbing.py",
    "pre-push",
    "sync-identifier-gate.sh",
    "test_identifier_gate.py",
    "test_identifier_gate_visibility.py",
)


def vendor(source: Path, commit: str, destination: Path) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("a full commit SHA is required")

    def git(*args: str) -> bytes:
        return subprocess.run(
            ["git", "--no-optional-locks", "--no-replace-objects", "-C", str(source), *args],
            capture_output=True,
            check=True,
        ).stdout

    if git("for-each-ref", "--format=%(refname)", "refs/replace").strip():
        raise ValueError("template replace refs refused")
    grafts = Path(git("rev-parse", "--git-path", "info/grafts").decode().strip())
    if not grafts.is_absolute():
        grafts = source / grafts
    if grafts.exists() or grafts.is_symlink():
        raise ValueError("template grafts refused")
    if git("status", "--porcelain", "--untracked-files=all").strip():
        raise ValueError("dirty template source refused")
    if git("rev-parse", f"{commit}^{{commit}}").decode().strip() != commit:
        raise ValueError("source must be a commit")
    if git("symbolic-ref", "--short", "HEAD").decode().strip() != "main":
        raise ValueError("template source must be on main")
    ancestry = subprocess.run(
        ["git", "--no-optional-locks", "--no-replace-objects", "-C", str(source), "merge-base",
         "--is-ancestor", commit, "refs/heads/main"],
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ValueError("template commit must be an ancestor of main HEAD")
    blobs: dict[str, str] = {}
    for name in FILES:
        entry = git("ls-tree", commit, "--", name).decode().split()
        if len(entry) < 3 or entry[0] not in {"100644", "100755"} or entry[1] != "blob":
            raise ValueError("template payload must be a regular blob")
        blobs[name] = entry[2]
    payload = {name: git("show", f"{commit}:{name}") for name in FILES}
    if any(payload[name] != git("cat-file", "blob", blobs[name]) for name in FILES):
        raise ValueError("template blob readback mismatch")
    rendered = payload["check_committed_identifiers.py"].replace(
        b"@@DENYLIST_VAR@@",
        b"PIN_FORBIDDEN_IDENTIFIERS",
    )
    normalized = re.sub(rb"[A-Z][A-Z0-9_]*_FORBIDDEN_IDENTIFIERS", b"XX", rendered)
    gate_hash = hashlib.sha256(normalized).hexdigest()[:16]
    if not any(
        row.startswith(gate_hash + " ") and "current canonical" in row
        for row in payload["KNOWN_GATE_HASHES"].decode().splitlines()
    ):
        raise ValueError("unrecognized template digest refused")
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}
    lock = {
        "revision": commit,
        "files": hashes,
        "canonical_gate_hash": gate_hash,
        "review_provenance": "PR review of the lock change",
    }
    snapshot = destination / "gate-template" / commit[:7]
    snapshot.mkdir(parents=True, exist_ok=True)
    for name, data in payload.items():
        (snapshot / name).write_bytes(data)
    (destination / "gate-template.lock.json").write_bytes(
        (json.dumps(lock, sort_keys=True, indent=2) + "\n").encode("utf-8")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("commit")
    parser.add_argument(
        "--destination",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "src/agent_suite/data",
    )
    args = parser.parse_args()
    try:
        vendor(args.source, args.commit, args.destination)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"vendor refused: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
