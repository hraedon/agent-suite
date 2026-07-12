#!/usr/bin/env python3
"""Download and verify the WinSW binary from its official GitHub release.

Usage: python3 scripts/install-winsw.py [--dest PATH] [--dry-run]

Downloads WinSW.exe, verifies its SHA-256 checksum, and places it at
C:/ProgramData/agent-suite/bin/winsw.exe (or --dest). Idempotent — if
the binary already exists with the correct checksum, it's a no-op.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

WINSW_URL = "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe"

# SHA-256 of WinSW-x64.exe v2.12.0.
# PLACEHOLDER — must be verified against the official release before use:
#   https://github.com/winsw/winsw/releases/tag/v2.12.0
EXPECTED_SHA256 = "sha256:PLACEHOLDER_VERIFY_BEFORE_RELEASE"

DEFAULT_DEST = Path("C:/ProgramData/agent-suite/bin/winsw.exe")

CHUNK_SIZE = 65536


def _compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            out.write(chunk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help=f"Destination path (default: {DEFAULT_DEST})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be done without acting",
    )
    args = parser.parse_args(argv)
    dest: Path = args.dest
    dry_run: bool = args.dry_run

    expected_hash = EXPECTED_SHA256.removeprefix("sha256:")

    if sys.platform != "win32":
        print(
            "WARNING: not running on Windows — only --dry-run is meaningful here.",
            file=sys.stderr,
        )
        if not dry_run:
            return 1

    if dest.exists():
        actual = _compute_sha256(dest)
        if actual == expected_hash:
            print(f"already installed: {dest}")
            return 0
        print(
            f"ERROR: {dest} exists but checksum mismatch "
            f"(expected {expected_hash}, got {actual}) — refusing to overwrite.",
            file=sys.stderr,
        )
        return 1

    if dry_run:
        print(f"[dry-run] would download {WINSW_URL} -> {dest}")
        print(f"[dry-run] would verify SHA-256 == {expected_hash}")
        return 0

    print(f"downloading {WINSW_URL} -> {dest}")
    _download(WINSW_URL, dest)
    actual = _compute_sha256(dest)
    if actual != expected_hash:
        dest.unlink(missing_ok=True)
        print(
            f"ERROR: checksum mismatch after download "
            f"(expected {expected_hash}, got {actual}) — removed file.",
            file=sys.stderr,
        )
        return 1

    print(f"installed: {dest} (SHA-256 verified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
