#!/usr/bin/env python3
"""Assert every member's face-local SUITE.lock [spine] agrees with the umbrella.

The single enforcement point for cross-repo spine agreement (Plan 019
B2-generalize). Reads the umbrella ``agent-suite/SUITE.lock`` and each sibling's
checked-out ``SUITE.lock`` (under ``AGENT_SUITE_SIBLINGS_ROOT``, the layout the
``feature-probes`` CI job already produces), and fails if any member's
``[spine]`` version/sha drifts from the umbrella ``[components.regista]``.

With ``--strict``, also validates member identity (``[component]`` name/version
against the umbrella ``[components]`` entry) and fails on missing locks for
members listed in the umbrella ``[components]`` table.

Members without a lock or without a ``[spine]`` (e.g. agent-wake) are reported
``n/a`` — informational, not a failure (unless ``--strict`` and the member is
in the umbrella ``[components]`` table). Exit code: 0 when no member disagrees,
1 on any failure, 2 when the check cannot run (no umbrella ``SUITE.lock``, or
the resolved siblings root holds no member lock to check — a check that found
nothing is not a pass).

Usage:
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-lock-agreement.py
    AGENT_SUITE_SIBLINGS_ROOT=/tmp/siblings python3 scripts/check-lock-agreement.py --strict

``SUITE_WORKSPACE_ROOT`` is the canonical spelling (precedence over the
``AGENT_SUITE_SIBLINGS_ROOT`` alias); both forms are accepted here.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from agent_suite.lock import resolve_workspace_root
from agent_suite.lock_agreement import (
    check_all,
    format_report,
    has_failure,
    umbrella_regista_pin,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cross-repo lock-agreement check (Plan 019 B2-generalize)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Also validate member identity/version and fail on missing locks "
        "for members listed in the umbrella [components] table.",
    )
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent
    umbrella_path = repo_root / "SUITE.lock"
    if not umbrella_path.is_file():
        print(f"check-lock-agreement: no umbrella SUITE.lock at {umbrella_path}", file=sys.stderr)
        return 2
    umbrella_text = umbrella_path.read_text(encoding="utf-8")

    siblings_root = resolve_workspace_root(Path("/tmp/siblings"))

    umbrella = tomllib.loads(umbrella_text)
    member_locks: dict[str, str | None] = {}
    for member in umbrella.get("components", {}):
        if member == "regista":
            continue
        sibling_lock = siblings_root / member / "SUITE.lock"
        member_locks[member] = (
            sibling_lock.read_text(encoding="utf-8") if sibling_lock.is_file() else None
        )

    # A check that found nothing to check is not a pass (honest health). With
    # WI-058 the root can be steered by either workspace-root env var; if the
    # resolved root holds no member checkouts, say so loudly instead of
    # reporting every member n/a and exiting green.
    if member_locks and all(lock_text is None for lock_text in member_locks.values()):
        print(
            "check-lock-agreement: no member SUITE.lock found under "
            f"{siblings_root} — nothing was checked (set SUITE_WORKSPACE_ROOT "
            "or AGENT_SUITE_SIBLINGS_ROOT to the directory holding the "
            "sibling checkouts).",
            file=sys.stderr,
        )
        return 2

    results = check_all(umbrella_text, member_locks, strict=args.strict)
    version, revision = umbrella_regista_pin(umbrella_text)
    print(format_report(results, version, revision))
    return 1 if has_failure(results) else 0


if __name__ == "__main__":
    sys.exit(main())
