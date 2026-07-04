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
    VERIFY_RESTORE = "verify-restore"


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
    lock = sub.add_parser(
        Command.LOCK.value, help="generate / check the SUITE.lock compatibility manifest"
    )
    lock.add_argument(
        "--check",
        action="store_true",
        help="compare installed versions against the existing lock; exit non-zero on drift",
    )
    lock.add_argument(
        "--json", action="store_true", help="emit the lock or drift report as JSON"
    )
    bootstrap = sub.add_parser(Command.BOOTSTRAP.value, help="run the ordered idempotent install")
    bootstrap.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    bootstrap.add_argument(
        "--tier", choices=["0-1", "all"], default="0-1", help="which tiers to install (default: 0-1)"
    )
    bootstrap.add_argument("--user", help="onboard a per-user overlay for this principal ID")
    bootstrap.add_argument("--json", action="store_true", help="emit the result as JSON")
    verify_restore = sub.add_parser(
        Command.VERIFY_RESTORE.value,
        help="verify a restored store is cryptographically intact (post-restore check)",
    )
    verify_restore.add_argument("--dsn", help="Postgres DSN (or REGISTA_DSN)")
    verify_restore.add_argument(
        "--projects", nargs="*", help="project slugs to verify (default: discover from regista)"
    )
    verify_restore.add_argument("--json", action="store_true", help="emit the result as JSON")
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
            import sys

            from agent_suite.doctor import aggregate
            from agent_suite.lock import (
                check_drift,
                generate_lock,
                load_lock_file,
                read_regista_quad,
                serialize_lock,
                write_lock_file,
            )

            report = aggregate()
            component_versions: dict[str, str | None] = {
                r.component: r.version for r in report.components
            }
            current_quad = read_regista_quad()

            if args.check:
                try:
                    existing = load_lock_file()
                except ValueError as exc:
                    print(f"agent-suite lock --check: {exc}", file=sys.stderr)
                    return 1
                drift_result = check_drift(
                    existing,
                    current_quad=current_quad,
                    component_versions=component_versions,
                )
                if getattr(args, "json", False):
                    import json as _json

                    print(_json.dumps(drift_result.to_dict(), indent=2, default=str))
                else:
                    from agent_suite.lock import format_drift_text

                    print(format_drift_text(drift_result))
                return 0 if drift_result.matches else 1
            else:
                lock = generate_lock(
                    component_versions=component_versions,
                )
                if getattr(args, "json", False):
                    import json as _json

                    print(_json.dumps(lock.to_dict(), indent=2, default=str))
                else:
                    print(serialize_lock(lock))
                write_lock_file(lock)
                return 0
        case Command.BOOTSTRAP:
            import os

            from agent_suite.bootstrap import format_text as _fmt_bs, run_bootstrap

            bs_result = run_bootstrap(
                dry_run=args.dry_run,
                tier=args.tier,
                user=args.user,
                project=os.environ.get("REGISTA_PROJECT"),
                dsn=os.environ.get("REGISTA_DSN"),
            )
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(bs_result.to_dict(), indent=2, default=str))
            else:
                print(_fmt_bs(bs_result))
            return 0 if bs_result.ok else 1
        case Command.VERIFY_RESTORE:
            import os

            from agent_suite.verify_restore import format_text as _fmt_vr, verify_restore

            vr_result = verify_restore(
                dsn=args.dsn or os.environ.get("REGISTA_DSN", ""),
                projects=args.projects,
            )
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(vr_result.to_dict(), indent=2, default=str))
            else:
                print(_fmt_vr(vr_result))
            return 0 if vr_result.ok else 1
    assert_never(command)


if __name__ == "__main__":
    raise SystemExit(main())
