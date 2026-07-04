#!/usr/bin/env python3
"""CI identifier-gate: fail if known personal/internal identifiers appear in tracked files.

Run as a pre-publication gate and in CI to prevent re-introduction of
identifiers that were scrubbed before the repo went public.

Usage::

    python3 scripts/identifier-gate.py

Exit 0 if clean, 1 if identifiers found.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

IDENTIFIERS: list[tuple[str, str]] = [
    ("plm@hraedon.com", "personal email"),
    ("Paul Merritt", "real name"),
    ("mvmpostgres01", "internal hostname"),
    ("hraedon.com", "internal domain (non-GitHub)"),
    ("hraedon", "GitHub organization name"),
]

EXCLUDE_DIRS = {".git", "node_modules", ".venv", "__pycache__", ".mypy_cache", ".claude"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}


def check_file(path: Path) -> list[tuple[str, int, str, str]]:
    findings: list[tuple[str, int, str, str]] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for needle, label in IDENTIFIERS:
        idx = text.find(needle)
        while idx >= 0:
            line_no = text.count("\n", 0, idx) + 1
            findings.append((str(path), line_no, needle, label))
            idx = text.find(needle, idx + 1)
    return findings


def main() -> int:
    findings: list[tuple[str, int, str, str]] = []
    for path in REPO_ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in EXCLUDE_DIRS for part in path.parts):
            continue
        if path.suffix in EXCLUDE_SUFFIXES:
            continue
        rel = path.relative_to(REPO_ROOT)
        if str(rel).startswith(".github"):
            continue
        if str(rel) == "scripts/identifier-gate.py":
            continue
        findings.extend(check_file(path))

    if findings:
        print("Identifier gate: FAIL — known identifiers found in tracked files:")
        for fpath, line, needle, label in findings:
            print(f"  {fpath}:{line}  '{needle}' ({label})")
        return 1

    print("Identifier gate: PASS — no known identifiers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
