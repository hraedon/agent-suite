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
    PREFLIGHT = "preflight"
    SETUP_INSTALL = "setup-install"
    DUAL_CONTROL = "dual-control"


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
    doctor.add_argument(
        "--profile",
        choices=["A", "B", "C"],
        help="classify the installation against a deployment profile (Plan 008 §3)",
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
    preflight = sub.add_parser(
        Command.PREFLIGHT.value,
        help="read-only Windows host preflight check (Plan 013 WI-0.3)",
    )
    preflight.add_argument("--json", action="store_true", help="emit the report as JSON")
    preflight.add_argument(
        "--profile",
        choices=["A", "B", "C"],
        default="B",
        help="deployment profile to evaluate against (default: B)",
    )
    preflight.add_argument(
        "--postgres-host", default="localhost", help="Postgres host to probe"
    )
    preflight.add_argument(
        "--postgres-port", type=int, default=5432, help="Postgres port to probe"
    )
    preflight.add_argument(
        "--dns-hostname", default="suite-db.example", help="hostname for DNS probe"
    )
    preflight.add_argument(
        "--tls-host", default="suite-db.example", help="hostname for TLS probe"
    )
    preflight.add_argument(
        "--tls-port", type=int, default=443, help="port for TLS probe"
    )
    preflight.add_argument(
        "--release-file", help="path to release identity file"
    )
    preflight.add_argument(
        "--lock-file", help="path to SUITE.lock file for lock identity"
    )
    preflight.add_argument(
        "--install-dir", help="path to check for existing installation"
    )
    setup_install = sub.add_parser(
        Command.SETUP_INSTALL.value,
        help="execute a Windows setup plan (Plan 014 WI-1.2)",
    )
    setup_install.add_argument("--dry-run", action="store_true", help="print the plan; act on nothing")
    setup_install.add_argument(
        "--apply", action="store_true", help="execute the plan (default: dry-run)"
    )
    setup_install.add_argument(
        "--profile",
        choices=["A", "B", "C"],
        default="B",
        help="deployment profile (default: B)",
    )
    setup_install.add_argument("--json", action="store_true", help="emit the receipt as JSON")
    setup_install.add_argument(
        "--postgres-host", default="localhost", help="Postgres host to probe"
    )
    setup_install.add_argument(
        "--postgres-port", type=int, default=5432, help="Postgres port to probe"
    )
    setup_install.add_argument(
        "--dns-hostname", default="suite-db.example", help="hostname for DNS probe"
    )
    setup_install.add_argument(
        "--tls-host", default="suite-db.example", help="hostname for TLS probe"
    )
    setup_install.add_argument(
        "--tls-port", type=int, default=443, help="port for TLS probe"
    )
    setup_install.add_argument(
        "--release-file", help="path to release identity file"
    )
    setup_install.add_argument(
        "--lock-file", help="path to SUITE.lock file for lock identity"
    )
    setup_install.add_argument(
        "--install-dir", help="path to check for existing installation"
    )
    dual_control = sub.add_parser(
        Command.DUAL_CONTROL.value,
        help="dual control request/approve/execute (Plan 014 WI-2.3)",
    )
    dual_control.add_argument(
        "action",
        choices=["request", "approve", "list", "execute"],
        help="create, approve, list, or execute a dual control request",
    )
    dual_control.add_argument("--operation", help="protected operation (for request)")
    dual_control.add_argument("--token", help="authentication token")
    dual_control.add_argument("--request-id", help="dual control request ID")
    default_dc_store = (
        os.path.join(
            os.environ.get("ProgramData", r"C:\ProgramData"), "agent-suite", "dual-control.json"
        )
        if os.name == "nt"
        else "/var/lib/agent-suite/dual-control.json"
    )
    dual_control.add_argument(
        "--store-path",
        default=default_dc_store,
        help="path to the dual control state store file",
    )
    dual_control.add_argument("--json", action="store_true", help="emit the result as JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    from agent_suite.config import load_suite_env_into_environ

    load_suite_env_into_environ()
    args = _build_parser().parse_args(argv)
    command = Command(args.command)
    match command:
        case Command.DOCTOR:
            from agent_suite.doctor import aggregate, format_text
            from agent_suite.profiles import Profile
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
            profile: Profile | None = None
            profile_arg: str | None = getattr(args, "profile", None)
            if profile_arg is not None:
                profile = Profile(profile_arg)
            # Build shared-service endpoints from suite.env / process env
            # (Plan 004 WI-1.6): each shared-service component declares its
            # endpoint env var in the Component descriptor.
            from agent_suite.components import shared_service_components

            shared_endpoints: dict[str, str] = {}
            for comp in shared_service_components():
                url = os.environ.get(comp.endpoint_env_var)
                if url:
                    shared_endpoints[comp.ident] = url
            from agent_suite.config import MemoryProviderConfig

            report = aggregate(
                verify_restore_dsn=verify_restore_dsn,
                profile=profile,
                shared_endpoints=shared_endpoints or None,
                memory_provider_config=MemoryProviderConfig.from_env(),
            )
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
                from agent_suite.config import memory_provider_config

                mp_engine = str(memory_provider_config()["engine"])
                lock = generate_lock(
                    component_versions=component_versions,
                    memory_engine=mp_engine,
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
            from agent_suite.config import memory_provider_config

            mp_config = memory_provider_config()
            bs_result = run_bootstrap(
                dry_run=args.dry_run,
                tier=args.tier,
                user=args.user,
                project=os.environ.get("REGISTA_PROJECT"),
                dsn=os.environ.get("REGISTA_DSN"),
                memory_engine=str(mp_config["engine"]),
                hindsight_url=(
                    mp_config["hindsight_url"]
                    if isinstance(mp_config["hindsight_url"], str)
                    else None
                ),
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
        case Command.PREFLIGHT:
            from pathlib import Path

            from agent_suite.profiles import Profile
            from agent_suite.windows_observation import format_preflight_text, observe_host
            from agent_suite.windows_setup import (
                PreflightState,
                SetupRequest,
                profile_operations,
                run_preflight,
            )

            release_file = Path(args.release_file) if args.release_file else None
            lock_file = Path(args.lock_file) if args.lock_file else None
            install_dir = Path(args.install_dir) if args.install_dir else None

            observation = observe_host(
                postgres_host=args.postgres_host,
                postgres_port=args.postgres_port,
                dns_hostname=args.dns_hostname,
                tls_host=args.tls_host,
                tls_port=args.tls_port,
                release_file=release_file,
                lock_file=lock_file,
                install_dir=install_dir,
            )
            profile = Profile(args.profile)
            request = SetupRequest(
                profile=profile,
                target_release_identity=observation.artifact_release_identity,
                target_lock_identity=observation.artifact_lock_identity,
                operations=profile_operations(profile),
            )
            preflight_report = run_preflight(observation, request)
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(preflight_report.to_dict(), indent=2, default=str))
            else:
                print(format_preflight_text(preflight_report))
            return 0 if preflight_report.state is PreflightState.READY else 1
        case Command.SETUP_INSTALL:
            from pathlib import Path

            from agent_suite.profiles import Profile
            from agent_suite.windows_observation import observe_host
            from agent_suite.windows_setup import (
                ReceiptState,
                SetupRequest,
                apply_plan,
                build_plan,
                profile_operations,
            )

            release_file = Path(args.release_file) if args.release_file else None
            lock_file = Path(args.lock_file) if args.lock_file else None
            install_dir = Path(args.install_dir) if args.install_dir else None

            observation = observe_host(
                postgres_host=args.postgres_host,
                postgres_port=args.postgres_port,
                dns_hostname=args.dns_hostname,
                tls_host=args.tls_host,
                tls_port=args.tls_port,
                release_file=release_file,
                lock_file=lock_file,
                install_dir=install_dir,
            )
            profile = Profile(args.profile)
            request = SetupRequest(
                profile=profile,
                target_release_identity=observation.artifact_release_identity,
                target_lock_identity=observation.artifact_lock_identity,
                operations=profile_operations(profile),
            )
            plan = build_plan(request, observation)
            try:
                receipt = apply_plan(plan, dry_run=not args.apply)
            except ValueError as exc:
                import sys

                print(f"agent-suite setup-install: {exc}", file=sys.stderr)
                return 1
            if getattr(args, "json", False):
                import json as _json

                print(_json.dumps(receipt.to_dict(), indent=2, default=str))
            else:
                print(f"Setup receipt: {receipt.state.value}")
                for action in receipt.actions:
                    print(f"  {action.ident:<30} {action.state.value}")
                print(f"  Detail: {receipt.detail}")
            return 0 if receipt.state in (ReceiptState.APPLIED, ReceiptState.DRY_RUN, ReceiptState.NO_OP) else 1
        case Command.DUAL_CONTROL:
            from pathlib import Path

            from agent_suite.dual_control import (
                ProtectedOperation,
                create_approval,
                create_request,
                evaluate_approval,
            )
            from agent_suite.dual_control_store import DualControlStore
            from agent_suite.dual_control import ValidatedToken, StepUpLevel, _hash_token
            import json as _json
            import time as _time

            store_path = Path(args.store_path)
            store = DualControlStore(store_path)

            if args.action == "list":
                pending = store.list_pending()
                if getattr(args, "json", False):
                    records = [
                        {
                            "request_id": r.request.request_id,
                            "operation": r.request.operation.value,
                            "requester": r.request.requester_principal,
                            "created_at": r.created_at,
                            "expires_at": r.request.expires_at,
                        }
                        for r in pending
                    ]
                    print(_json.dumps(records, indent=2, default=str))
                else:
                    if not pending:
                        print("No pending dual control requests.")
                    for r in pending:
                        print(
                            f"  {r.request.request_id:<36} "
                            f"{r.request.operation.value:<20} "
                            f"by {r.request.requester_principal}"
                        )
                return 0

            if args.action == "request":
                if not args.operation or not args.token:
                    import sys

                    print(
                        "dual-control request requires --operation and --token",
                        file=sys.stderr,
                    )
                    return 1
                operation = ProtectedOperation(args.operation)
                token_hash = _hash_token(args.token)
                token = ValidatedToken(
                    principal_id="cli-requester",
                    step_up_level=StepUpLevel.MULTI_FACTOR,
                    validated_at=_time.time(),
                    expires_at=_time.time() + 300,
                    token_hash=token_hash,
                )
                dc_request = create_request(
                    operation=operation,
                    requester_token=token,
                    operation_params={"source": "cli"},
                )
                store.create(dc_request)
                if getattr(args, "json", False):
                    print(
                        _json.dumps(
                            {
                                "request_id": dc_request.request_id,
                                "operation": dc_request.operation.value,
                                "state": "pending",
                            },
                            indent=2,
                        )
                    )
                else:
                    print(f"Created request: {dc_request.request_id}")
                    print(f"  Operation: {dc_request.operation.value}")
                    print("  State: pending")
                return 0

            if args.action == "approve":
                if not args.request_id or not args.token:
                    import sys

                    print(
                        "dual-control approve requires --request-id and --token",
                        file=sys.stderr,
                    )
                    return 1
                record = store.get(args.request_id)
                if record is None:
                    print(f"Request not found: {args.request_id}")
                    return 1
                token_hash = _hash_token(args.token)
                approver_token = ValidatedToken(
                    principal_id="cli-approver",
                    step_up_level=StepUpLevel.MULTI_FACTOR,
                    validated_at=_time.time(),
                    expires_at=_time.time() + 300,
                    token_hash=token_hash,
                )
                approval = create_approval(record.request, approver_token)
                decision = evaluate_approval(
                    record.request,
                    approval,
                    approver_token,
                    store=store,
                )
                if getattr(args, "json", False):
                    print(_json.dumps(decision.to_dict(), indent=2, default=str))
                else:
                    print(f"Decision: {decision.state.value}")
                    print(f"  Detail: {decision.detail}")
                return 0 if decision.is_approved else 1

            if args.action == "execute":
                if not args.request_id:
                    import sys

                    print("dual-control execute requires --request-id", file=sys.stderr)
                    return 1
                from agent_suite.dual_control import mark_executed

                decision = mark_executed(args.request_id, store)
                if getattr(args, "json", False):
                    print(_json.dumps(decision.to_dict(), indent=2, default=str))
                else:
                    print(f"Decision: {decision.state.value}")
                    print(f"  Detail: {decision.detail}")
                return 0 if decision.state.value == "executed" else 1
            assert_never(args.action)
    assert_never(command)


if __name__ == "__main__":
    raise SystemExit(main())
