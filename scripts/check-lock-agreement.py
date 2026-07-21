#!/usr/bin/env python3
"""Assert every member's face-local SUITE.lock [spine] agrees with the umbrella.

The single enforcement point for cross-repo spine agreement (Plan 019
B2-generalize). Reads the umbrella ``agent-suite/SUITE.lock`` and each sibling's
checked-out ``SUITE.lock`` (under ``AGENT_SUITE_SIBLINGS_ROOT``, the layout the
``feature-probes`` CI job already produces), and fails if any member's
``[spine]`` version/sha drifts from the umbrella ``[components.regista]``.

Members without a lock or without a ``[spine]`` (e.g. agent-wake) are reported
``n/a`` — informational, not a failure. Exit code: 0 when no member disagrees,
1 on any disagreement.

Usage:
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-lock-agreement.py
"""

from __future__ import annotations

import os
import sys
import tomllib
from pathlib import Path

from agent_suite.lock_agreement import (
    check_all,
    format_report,
    has_disagreement,
    umbrella_regista_pin,
)


def main(argv: list[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    umbrella_path = repo_root / "SUITE.lock"
    if not umbrella_path.is_file():
        print(f"check-lock-agreement: no umbrella SUITE.lock at {umbrella_path}", file=sys.stderr)
        return 2
    umbrella_text = umbrella_path.read_text(encoding="utf-8")

    siblings_root = Path(os.environ.get("AGENT_SUITE_SIBLINGS_ROOT", "/tmp/siblings"))

    # The members to check are the umbrella's components (minus regista, the
    # spine itself). Read each sibling's checked-out SUITE.lock if present.
    umbrella = tomllib.loads(umbrella_text)
    member_locks: dict[str, str | None] = {}
    for member in umbrella.get("components", {}):
        if member == "regista":
            continue
        sibling_lock = siblings_root / member / "SUITE.lock"
        member_locks[member] = (
            sibling_lock.read_text(encoding="utf-8") if sibling_lock.is_file() else None
        )

    results = check_all(umbrella_text, member_locks)
    version, revision = umbrella_regista_pin(umbrella_text)
    print(format_report(results, version, revision))
    return 1 if has_disagreement(results) else 0


if __name__ == "__main__":
    sys.exit(main())
