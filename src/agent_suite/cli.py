"""agent-suite command-line front door.

Charter-stage skeleton: the argument surface and closed-set dispatch are in place
(with `assert_never` so a new command can't be silently unhandled); the command
bodies land in Plan 001 as the component contracts they compose become real.
"""

from __future__ import annotations

import argparse
import os
from enum import Enum
from typing import assert_never


class Command(Enum):
    DOCTOR = "doctor"
    LOCK = "lock"
    BOOTSTRAP = "bootstrap"
    ONBOARD = "onboard"
    VERIFY_RESTORE = "verify-restore"
    UPGRADE = "upgrade"
    SCHEDULE = "schedule"
    ALERT_CHECK = "alert-check"


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
    doctor.add_argument(
        "--verify-restore",
        action="store_true",
        help="run post-restore chain verification (regista replay across all projects)",
    )
    doctor.add_argument(
        "--restore-dsn",
        help="Postgres DSN for --verify-restore (or REGISTA_DSN); errors if --verify-restore is set and neither is provided",
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
    onboard = sub.add_parser(
        Command.ONBOARD.value,
        help="onboard a project: spec -> provision -> sign event-zero -> wire harness",
    )
    onboard.add_argument("slug", help="project slug to onboard")
    onboard.add_argument(
        "--spec", help="path to spec.yaml (founding spec to sign as event-zero)"
    )
    onboard.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    onboard.add_argument(
        "--harness",
        choices=["claude", "opencode", "all"],
        default="all",
        help="which harness to wire (default: all — dual-target)",
    )
    onboard.add_argument(
        "--principal", help="principal ID for provisioning (default: suite-service)"
    )
    onboard.add_argument("--json", action="store_true", help="emit the result as JSON")
    verify_restore = sub.add_parser(
        Command.VERIFY_RESTORE.value,
        help="verify a restored store is cryptographically intact (post-restore check)",
    )
    verify_restore.add_argument("--dsn", help="Postgres DSN (or REGISTA_DSN)")
    verify_restore.add_argument(
        "--projects", nargs="*", help="project slugs to verify (default: discover from regista)"
    )
    verify_restore.add_argument("--json", action="store_true", help="emit the result as JSON")

    upgrade = sub.add_parser(
        Command.UPGRADE.value,
        help="advance SUITE.lock: upgrade components, gate on interop, rewrite lock",
    )
    upgrade.add_argument(
        "--component", help="advance only this component (by ident, e.g. 'regista')"
    )
    upgrade.add_argument(
        "--check",
        action="store_true",
        help="report available advancements without acting (read-only)",
    )
    upgrade.add_argument(
        "--to",
        dest="to_ref",
        help="roll back to a prior committed lock at this git ref (e.g. HEAD~1, a tag)",
    )
    upgrade.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    upgrade.add_argument("--json", action="store_true", help="emit the result as JSON")

    schedule = sub.add_parser(
        Command.SCHEDULE.value,
        help="install/remove OS-scheduled operations (systemd timers / Windows tasks)",
    )
    schedule.add_argument(
        "action", choices=["install", "remove", "list"], help="install, remove, or list schedules"
    )
    schedule.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    schedule.add_argument("--json", action="store_true", help="emit the result as JSON")

    alert_check = sub.add_parser(
        Command.ALERT_CHECK.value,
        help="run doctor + emit alert on state change (for scheduled execution)",
    )
    alert_check.add_argument(
        "--wake-url", help="agent-wake ingress URL (or AGENT_WAKE_INGRESS_URL env)"
    )
    alert_check.add_argument(
        "--state-file",
        default="/var/lib/agent-suite/last-doctor-state.json",
        help="path to the state file for debouncing",
    )
    alert_check.add_argument("--json", action="store_true", help="emit the result as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    command = Command(args.command)
    match command:
        case Command.DOCTOR:
            from agent_suite.doctor import aggregate, format_text
            import json as _json
            import sys

            verify_restore_dsn: str | None = None
            if getattr(args, "verify_restore", False):
                verify_restore_dsn = getattr(args, "restore_dsn", None) or os.environ.get(
                    "REGISTA_DSN"
                )
                if verify_restore_dsn is None:
                    print(
                        "agent-suite doctor --verify-restore: no DSN provided. "
                        "Use --restore-dsn or set REGISTA_DSN.",
                        file=sys.stderr,
                    )
                    return 1
            report = aggregate(verify_restore_dsn=verify_restore_dsn)
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
        case Command.ONBOARD:
            from pathlib import Path

            from agent_suite.onboard import format_text as _fmt_ob, run_onboard

            spec_path = Path(args.spec) if args.spec else None
            ob_result = run_onboard(
                project=args.slug,
                spec_path=spec_path,
                dry_run=args.dry_run,
                harness=args.harness,
                principal=args.principal,
            )
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(ob_result.to_dict(), indent=2, default=str))
            else:
                print(_fmt_ob(ob_result))
            return 0 if ob_result.ok else 1
        case Command.VERIFY_RESTORE:
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
        case Command.UPGRADE:
            from agent_suite.upgrade import (
                format_advancement_text,
                format_rollback_text,
                format_upgrade_text,
                run_rollback,
                run_upgrade,
            )

            if args.to_ref:
                rb_result = run_rollback(to_ref=args.to_ref)
                if getattr(args, "json", False):
                    import json as _json

                    print(_json.dumps(rb_result.to_dict(), indent=2, default=str))
                else:
                    print(format_rollback_text(rb_result))
                return 0 if rb_result.ok else 1

            up_result = run_upgrade(
                component=args.component,
                check_only=args.check,
                dry_run=args.dry_run,
            )
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(up_result.to_dict(), indent=2, default=str))
            elif args.check:
                from agent_suite.upgrade import check_advancements

                adv_report = check_advancements(component=args.component)
                print(format_advancement_text(adv_report))
            else:
                print(format_upgrade_text(up_result))
            return 0 if up_result.ok else 1
        case Command.SCHEDULE:
            from agent_suite.schedule import (
                SCHEDULES,
                format_schedule_report,
                install_schedules,
                remove_schedules,
            )

            if args.action == "list":
                if getattr(args, "json", False):
                    import json as _json

                    schedules_data = [
                        {
                            "kind": s.kind.value,
                            "name": s.name,
                            "description": s.description,
                            "on_calendar": s.on_calendar,
                            "command": s.command,
                        }
                        for s in SCHEDULES
                    ]
                    print(_json.dumps(schedules_data, indent=2, default=str))
                else:
                    print("Scheduled operations:")
                    for s in SCHEDULES:
                        print(f"  {s.name:<28} {s.kind.value:<16} {s.on_calendar:<10} {s.command}")
                return 0

            if args.action == "install":
                sched_report = install_schedules(dry_run=args.dry_run)
            else:
                sched_report = remove_schedules(dry_run=args.dry_run)

            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(sched_report.to_dict(), indent=2, default=str))
            else:
                print(format_schedule_report(sched_report, args.action))
            all_ok = all(
                r.status.value in ("installed", "already_installed", "removed", "not_installed")
                for r in sched_report.results
            )
            return 0 if all_ok else 1
        case Command.ALERT_CHECK:
            from pathlib import Path

            from agent_suite.alerting import format_alert_text, run_alert_check

            alert_result = run_alert_check(
                wake_url=args.wake_url,
                state_path=Path(args.state_file),
            )
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(alert_result.to_dict(), indent=2, default=str))
            else:
                print(format_alert_text(alert_result))
            return 0 if alert_result.suite_ok else 1
    assert_never(command)


if __name__ == "__main__":
    raise SystemExit(main())
