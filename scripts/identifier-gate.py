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
    ("hraedon/", "internal GitHub org prefix"),
    ("hraedon", "internal GitHub org name"),
    ("regista_app", "internal DB service account"),
    ("agent_notes_app", "internal DB service account"),
    ("itadmin", "OS username as principal_id"),
    # --- F-4: deployment evidence identifiers (2026-07-10) ---
    ("mvmhermes01", "internal hostname"),
    ("192.168.1.90", "internal IP address"),
    ("192.168.1.22", "internal IP address"),
    ("hermes-agent", "internal principal name"),
    ("regista_service", "internal DB service account"),
    ("notes_service", "internal DB service account"),
    ("pk_be8ebbac", "key-ID prefix"),
    ("pk_6c345369", "key-ID prefix"),
    # "operator" is a common English word used throughout the docs (e.g.,
    # "the operator should fix DNS"). It cannot be added as a bare
    # identifier without false positives. Scoped to the path pattern where
    # it appeared as a real OS username in the deployment evidence:
    ("/home/operator", "OS username in home directory path"),
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
        if str(rel) == "docs/publication-review.md":
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
