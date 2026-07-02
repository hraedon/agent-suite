"""agent-suite command-line front door.

Charter-stage skeleton: the argument surface and closed-set dispatch are in place
(with `assert_never` so a new command can't be silently unhandled); the command
bodies land in Plan 001 as the component contracts they compose become real.
"""

from __future__ import annotations

import argparse
from enum import Enum
from typing import assert_never


class Command(Enum):
    DOCTOR = "doctor"
    LOCK = "lock"
    BOOTSTRAP = "bootstrap"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-suite", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    doctor = sub.add_parser(
        Command.DOCTOR.value, help="aggregate each component's health into one report"
    )
    doctor.add_argument("--json", action="store_true", help="emit the umbrella report as JSON")
    doctor.add_argument(
        "--exit-code",
        action="store_true",
        help="exit non-zero when the suite is not ok (for monitoring)",
    )
    sub.add_parser(
        Command.LOCK.value, help="generate / check the SUITE.lock compatibility manifest"
    )
    bootstrap = sub.add_parser(Command.BOOTSTRAP.value, help="run the ordered idempotent install")
    bootstrap.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = Command(args.command)
    match command:
        case Command.DOCTOR:
            from agent_suite.doctor import aggregate, format_text
            import json as _json

            report = aggregate()
            if getattr(args, "json", False):
                print(_json.dumps(report.to_dict(), indent=2, default=str))
            else:
                print(format_text(report))
            return 1 if (getattr(args, "exit_code", False) and not report.suite_ok) else 0
        case Command.LOCK:
            print("agent-suite lock: not yet implemented (Plan 001 WI-2.1)")
            return 0
        case Command.BOOTSTRAP:
            print("agent-suite bootstrap: not yet implemented (Plan 001 WI-3.1)")
            return 0
    assert_never(command)


if __name__ == "__main__":
    raise SystemExit(main())
