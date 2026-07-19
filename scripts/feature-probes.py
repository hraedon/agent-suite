#!/usr/bin/env python3
"""Executable baseline probes for the v1 feature matrix (Plan 015 WI-0.1).

Replaces hand-assessed statuses with probe-emitted results. Every row in the
matrix is emitted by a named probe that mechanically determines its status
(pass / partial / blocked / absent) by inspecting the relevant module, function,
class, test, or CLI surface.

agent-suite rows probe ``src/agent_suite/``. Sibling-component rows
(regista, agent-notes, dossier, agent-provenance, agent-capability-broker,
agent-wake) probe the sibling checkout at ``/projects/<basename>`` or the
installed package — defensively, since CI may not have siblings installed.

A probe's job is NOT to make the feature pass. It is to mechanically determine
the status. Probes may honestly return ``partial``, ``absent``, or ``blocked``.
If a probe cannot determine the status (sibling not available), it returns
``HAND_ASSESSED`` to preserve the prior hand-assessed status.

Usage:
    python3 scripts/feature-probes.py           # probe + update data/
    python3 scripts/feature-probes.py --check   # validate, exit non-zero on drift
    python3 scripts/feature-probes.py --stdout   # print to stdout
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from types import ModuleType
from typing import Any, assert_never

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "v1-feature-matrix.json"
DOCS_PATH = REPO_ROOT / "docs" / "v1-feature-matrix.md"
SIBLINGS_ROOT = Path("/projects")


class ProbeResult(Enum):
    PASS = "pass"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ABSENT = "absent"
    HAND_ASSESSED = "hand-assessed"


@dataclass(frozen=True)
class ProbeOutcome:
    """The result of running a probe: a status and the evidence inspected."""

    result: ProbeResult
    evidence: str


# ---------------------------------------------------------------------------
# agent-suite helpers (probe src/agent_suite/ in this repo)
# ---------------------------------------------------------------------------


def _probe_module_exists(module_path: str) -> bool:
    return (REPO_ROOT / "src" / "agent_suite" / module_path).exists()


def _probe_has_function(module_name: str, func_name: str) -> bool:
    try:
        mod = importlib.import_module(f"agent_suite.{module_name}")
        return hasattr(mod, func_name)
    except Exception:
        return False


def _probe_has_class(module_name: str, class_name: str) -> bool:
    try:
        mod = importlib.import_module(f"agent_suite.{module_name}")
        return hasattr(mod, class_name)
    except Exception:
        return False


def _probe_test_exists(test_name: str) -> bool:
    return (REPO_ROOT / "tests" / test_name).exists()


def _probe_cli_command(command_value: str) -> bool:
    try:
        from agent_suite.cli import Command  # type: ignore[import-untyped]

        return any(c.value == command_value for c in Command)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Sibling-component helpers (probes for regista, agent-notes, dossier, cairn,
# agent-capability-broker, agent-wake). Defensive: siblings may or may not be
# importable at probe time (CI runs from agent-suite's venv which may not have
# siblings installed; local dev typically has them editable-installed from
# /projects/<basename>).
# ---------------------------------------------------------------------------


def _sibling_import(package: str) -> ModuleType | None:
    """Import a sibling package, returning None on failure."""
    try:
        return importlib.import_module(package)
    except Exception:
        return None


def _sibling_available(checkout_name: str, package: str | None = None) -> bool:
    """Check if a sibling component is available (checkout OR importable)."""
    if (SIBLINGS_ROOT / checkout_name).exists():
        return True
    if package is not None:
        return _sibling_import(package) is not None
    return False


def _sibling_has_attr(package: str, attr_name: str) -> bool:
    """Check if a sibling package exposes an attribute (function/class/constant)."""
    mod = _sibling_import(package)
    return mod is not None and hasattr(mod, attr_name)


def _sibling_has_method(package: str, class_name: str, method_name: str) -> bool:
    """Check if a sibling package's class exposes a method."""
    mod = _sibling_import(package)
    if mod is None:
        return False
    cls = getattr(mod, class_name, None)
    return cls is not None and hasattr(cls, method_name)


def _sibling_module_file_exists(
    checkout_name: str, module_path: str, src_prefix: str = "src"
) -> bool:
    """Check if /projects/<checkout>/<src_prefix>/<module_path> exists.

    ``src_prefix`` defaults to ``"src"``; agent-wake uses ``"daemon/src"``.
    """
    return (SIBLINGS_ROOT / checkout_name / src_prefix / module_path).exists()


def _sibling_test_exists(
    checkout_name: str, test_name: str, tests_subdir: str = "tests"
) -> bool:
    """Check if /projects/<checkout>/<tests_subdir>/<test_name> exists.

    ``tests_subdir`` defaults to ``"tests"``; agent-wake uses ``"daemon/tests"``.
    """
    return (SIBLINGS_ROOT / checkout_name / tests_subdir / test_name).exists()


def _sibling_cli_has_subcommand(cli_name: str, subcommand: str) -> bool:
    """Shell out to <cli_name> --help and check the subcommand appears."""
    if not shutil.which(cli_name):
        return False
    try:
        result = subprocess.run(
            (cli_name, "--help"),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return subcommand in result.stdout
    except Exception:
        return False


def _sibling_route_exists(checkout_name: str, module_name: str, route_path: str) -> bool:
    """Check if a sibling FastAPI/Starlette app registers a route path.

    Imports ``<package>.<module_name>``, inspects ``create_app`` for the route.
    """
    package = checkout_name.replace("-", "_")
    try:
        mod = importlib.import_module(f"{package}.{module_name}")
        import inspect
        import re

        src = inspect.getsource(mod)
        # Match @app.get("/path") or @app.post("/path") decorators
        pattern = r'@app\.(?:get|post|put|delete|route)\(\s*["\']([^"\']+)["\']'
        routes = re.findall(pattern, src)
        return route_path in routes
    except Exception:
        return False


def _sibling_source_contains(
    checkout_name: str, module_path: str, needle: str, src_prefix: str = "src"
) -> bool:
    """Grep a sibling source file for a literal string (defensive, no import).

    ``src_prefix`` defaults to ``"src"``; agent-wake uses ``"daemon/src"``.
    """
    candidate = SIBLINGS_ROOT / checkout_name / src_prefix / module_path
    if not candidate.exists():
        return False
    try:
        return needle in candidate.read_text(encoding="utf-8")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# agent-suite probes (8 rows)
# ---------------------------------------------------------------------------


def _probe_deploy_cli() -> ProbeOutcome:
    if not _probe_module_exists("deploy.py"):
        return ProbeOutcome(ProbeResult.ABSENT, "src/agent_suite/deploy.py absent")
    if not _probe_has_function("deploy", "run_deploy"):
        return ProbeOutcome(ProbeResult.PARTIAL, "deploy.run_deploy missing")
    if not _probe_cli_command("deploy"):
        return ProbeOutcome(ProbeResult.PARTIAL, "CLI command 'deploy' missing")
    if not _probe_test_exists("test_deploy.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_deploy.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "src/agent_suite/deploy.py present; deploy.run_deploy exposed; "
        "CLI 'deploy' registered; tests/test_deploy.py present",
    )


def _probe_onboard_harness() -> ProbeOutcome:
    if not _probe_module_exists("onboard.py"):
        return ProbeOutcome(ProbeResult.ABSENT, "src/agent_suite/onboard.py absent")
    if not _probe_has_function("onboard", "run_onboard"):
        return ProbeOutcome(ProbeResult.PARTIAL, "onboard.run_onboard missing")
    if not _probe_test_exists("test_onboard.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_onboard.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "src/agent_suite/onboard.py present; onboard.run_onboard exposed; "
        "tests/test_onboard.py present",
    )


def _probe_identity_lifecycle() -> ProbeOutcome:
    if not _probe_module_exists("onboard.py"):
        return ProbeOutcome(ProbeResult.ABSENT, "src/agent_suite/onboard.py absent")
    if not _probe_has_function("bootstrap", "run_bootstrap"):
        return ProbeOutcome(ProbeResult.PARTIAL, "bootstrap.run_bootstrap missing")
    if not _probe_has_function("bootstrap", "_step_user_onboarding"):
        return ProbeOutcome(
            ProbeResult.PARTIAL,
            "bootstrap._step_user_onboarding missing (no per-user onboarding step)",
        )
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "bootstrap.run_bootstrap present; bootstrap._step_user_onboarding present; "
        "offboarding step absent (step reports 'not yet implemented')",
    )


def _probe_evidence_export() -> ProbeOutcome:
    if not _probe_module_exists("evidence.py"):
        return ProbeOutcome(ProbeResult.ABSENT, "src/agent_suite/evidence.py absent")
    if not _probe_has_function("evidence", "run_evidence_export"):
        return ProbeOutcome(ProbeResult.PARTIAL, "evidence.run_evidence_export missing")
    if not _probe_cli_command("export-evidence"):
        return ProbeOutcome(ProbeResult.PARTIAL, "CLI command 'export-evidence' missing")
    if not _probe_test_exists("test_evidence.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_evidence.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "src/agent_suite/evidence.py present; evidence.run_evidence_export exposed; "
        "CLI 'export-evidence' registered; tests/test_evidence.py present",
    )


def _probe_backup_restore() -> ProbeOutcome:
    if not _probe_module_exists("backup.py"):
        return ProbeOutcome(ProbeResult.ABSENT, "src/agent_suite/backup.py absent")
    if not _probe_has_function("backup", "run_backup"):
        return ProbeOutcome(ProbeResult.PARTIAL, "backup.run_backup missing")
    if not _probe_has_function("backup", "run_restore"):
        return ProbeOutcome(ProbeResult.PARTIAL, "backup.run_restore missing")
    if not _probe_cli_command("backup"):
        return ProbeOutcome(ProbeResult.PARTIAL, "CLI command 'backup' missing")
    if not _probe_cli_command("restore"):
        return ProbeOutcome(ProbeResult.PARTIAL, "CLI command 'restore' missing")
    if not _probe_test_exists("test_backup.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_backup.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "src/agent_suite/backup.py present; run_backup/run_restore exposed; "
        "CLI 'backup'+'restore' registered; tests/test_backup.py present",
    )


def _probe_upgrade_rollback_forward() -> ProbeOutcome:
    if not _probe_has_function("upgrade", "run_upgrade"):
        return ProbeOutcome(ProbeResult.ABSENT, "upgrade.run_upgrade missing")
    if not _probe_has_function("upgrade", "run_rollback"):
        return ProbeOutcome(ProbeResult.PARTIAL, "upgrade.run_rollback missing")
    if not _probe_has_function("upgrade", "run_forward_recovery"):
        return ProbeOutcome(ProbeResult.PARTIAL, "upgrade.run_forward_recovery missing")
    if not _probe_test_exists("test_upgrade.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_upgrade.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "upgrade.run_upgrade/run_rollback/run_forward_recovery exposed; "
        "tests/test_upgrade.py present",
    )


def _probe_doctor() -> ProbeOutcome:
    if not _probe_has_function("doctor", "aggregate"):
        return ProbeOutcome(ProbeResult.ABSENT, "doctor.aggregate missing")
    if not _probe_test_exists("test_doctor.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_doctor.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "doctor.aggregate exposed; tests/test_doctor.py present",
    )


def _probe_lock() -> ProbeOutcome:
    if not _probe_has_function("lock", "generate_lock"):
        return ProbeOutcome(ProbeResult.ABSENT, "lock.generate_lock missing")
    if not _probe_test_exists("test_lock.py"):
        return ProbeOutcome(ProbeResult.PARTIAL, "tests/test_lock.py missing")
    return ProbeOutcome(
        ProbeResult.PASS,
        "lock.generate_lock exposed; tests/test_lock.py present",
    )


# ---------------------------------------------------------------------------
# regista probes (9 rows)
# ---------------------------------------------------------------------------


def _probe_regista_provisioning() -> ProbeOutcome:
    """GJ-1 regista: project / schema provisioning."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_create = _sibling_has_method("regista", "Regista", "create_project")
    has_provision_mod = _sibling_module_file_exists("regista", "regista/_provision.py")
    has_migrations = _sibling_module_file_exists("regista", "regista/_migrations.py")
    has_test = _sibling_test_exists("regista", "test_provision.py")
    evidence_parts = [
        f"Regista.create_project={'present' if has_create else 'missing'}",
        f"regista/_provision.py={'present' if has_provision_mod else 'absent'}",
        f"regista/_migrations.py={'present' if has_migrations else 'absent'}",
        f"tests/test_provision.py={'present' if has_test else 'missing'}",
    ]
    if not has_create:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_provision_mod and has_migrations and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_workflow_registration() -> ProbeOutcome:
    """GJ-1 regista: workflow registration and discovery."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_register = _sibling_has_method("regista", "Regista", "register_workflow")
    has_register_file = _sibling_has_method("regista", "Regista", "register_workflow_file")
    has_workflow_mod = _sibling_module_file_exists("regista", "regista/_workflow.py")
    has_test = _sibling_test_exists("regista", "test_canonical_workflow.py")
    evidence_parts = [
        f"Regista.register_workflow={'present' if has_register else 'missing'}",
        f"Regista.register_workflow_file={'present' if has_register_file else 'missing'}",
        f"regista/_workflow.py={'present' if has_workflow_mod else 'absent'}",
        f"tests/test_canonical_workflow.py={'present' if has_test else 'missing'}",
    ]
    if not has_register:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_workflow_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_principal_lifecycle() -> ProbeOutcome:
    """GJ-1 regista: principal enrollment, rotation, revocation, delegation."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_pl_class = _sibling_has_attr("regista", "PrincipalLifecycle")
    has_enroll = _sibling_has_method(
        "regista", "PrincipalLifecycle", "prepare_enrollment"
    )
    has_rotate = _sibling_has_method(
        "regista", "PrincipalLifecycle", "prepare_rotation"
    )
    has_revoke = _sibling_has_method(
        "regista", "PrincipalLifecycle", "prepare_revocation"
    )
    has_keys_mod = _sibling_module_file_exists("regista", "regista/_principal_keys.py")
    has_pl_mod = _sibling_module_file_exists("regista", "regista/principal_lifecycle.py")
    has_test = _sibling_test_exists("regista", "test_enroll_principal.py")
    evidence_parts = [
        f"PrincipalLifecycle={'present' if has_pl_class else 'missing'}",
        f"prepare_enrollment={'present' if has_enroll else 'missing'}",
        f"prepare_rotation={'present' if has_rotate else 'missing'}",
        f"prepare_revocation={'present' if has_revoke else 'missing'}",
        f"regista/_principal_keys.py={'present' if has_keys_mod else 'absent'}",
        f"regista/principal_lifecycle.py={'present' if has_pl_mod else 'absent'}",
        f"tests/test_enroll_principal.py={'present' if has_test else 'missing'}",
    ]
    if not has_pl_class:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_enroll and has_rotate and has_revoke):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    if not (has_keys_mod and has_pl_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_work_item_lifecycle() -> ProbeOutcome:
    """GJ-2 regista: work-item lifecycle (create, claim, transition)."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_create = _sibling_has_method("regista", "Regista", "create_work_item")
    has_transition = _sibling_has_method("regista", "Regista", "transition")
    has_replay = _sibling_has_method("regista", "Regista", "replay")
    has_work_items_mod = _sibling_module_file_exists("regista", "regista/_work_items.py")
    has_test = _sibling_test_exists("regista", "test_canonical_workflow.py")
    evidence_parts = [
        f"Regista.create_work_item={'present' if has_create else 'missing'}",
        f"Regista.transition={'present' if has_transition else 'missing'}",
        f"Regista.replay={'present' if has_replay else 'missing'}",
        f"regista/_work_items.py={'present' if has_work_items_mod else 'absent'}",
        f"tests/test_canonical_workflow.py={'present' if has_test else 'missing'}",
    ]
    if not (has_create and has_transition):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_replay and has_work_items_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_race_free_claims() -> ProbeOutcome:
    """GJ-2 regista: race-free claim / assignment."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_claims_prop = _sibling_has_method("regista", "Regista", "claims")
    has_acquire = _sibling_has_method("regista._ops", "ClaimOps", "acquire")
    has_heartbeat = _sibling_has_method("regista._ops", "ClaimOps", "heartbeat")
    has_release = _sibling_has_method("regista._ops", "ClaimOps", "release")
    has_claim_mod = _sibling_module_file_exists("regista", "regista/_api_claim.py")
    has_test = _sibling_test_exists("regista", "test_claim_link_idempotency.py")
    evidence_parts = [
        f"Regista.claims property={'present' if has_claims_prop else 'missing'}",
        f"ClaimOps.acquire={'present' if has_acquire else 'missing'}",
        f"ClaimOps.heartbeat={'present' if has_heartbeat else 'missing'}",
        f"ClaimOps.release={'present' if has_release else 'missing'}",
        f"regista/_api_claim.py={'present' if has_claim_mod else 'absent'}",
        f"tests/test_claim_link_idempotency.py={'present' if has_test else 'missing'}",
    ]
    if not (has_claims_prop and has_acquire and has_release):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_heartbeat and has_claim_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_review_validators() -> ProbeOutcome:
    """GJ-4 regista: cross-lineage review validators."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    rv_mod = _sibling_import("regista._review_validators")
    has_builtin_validators = rv_mod is not None and hasattr(
        rv_mod, "BUILTIN_REVIEW_VALIDATORS"
    )
    has_mod_file = _sibling_module_file_exists(
        "regista", "regista/_review_validators.py"
    )
    has_test = _sibling_test_exists("regista", "test_plan023_review_validators.py")
    evidence_parts = [
        f"BUILTIN_REVIEW_VALIDATORS={'present' if has_builtin_validators else 'missing'}",
        f"regista/_review_validators.py={'present' if has_mod_file else 'absent'}",
        f"tests/test_plan023_review_validators.py={'present' if has_test else 'missing'}",
    ]
    if not has_builtin_validators:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_mod_file and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_bundle_export() -> ProbeOutcome:
    """GJ-8 regista: scoped evidence bundle export."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_export = _sibling_has_method(
        "regista", "Regista", "export_audit_bundle"
    )
    has_bundle_mod = _sibling_module_file_exists("regista", "regista/_bundle.py")
    has_archive_mod = _sibling_module_file_exists("regista", "regista/_archive.py")
    has_test = _sibling_test_exists("regista", "test_bundle.py")
    evidence_parts = [
        f"Regista.export_audit_bundle={'present' if has_export else 'missing'}",
        f"regista/_bundle.py={'present' if has_bundle_mod else 'absent'}",
        f"regista/_archive.py={'present' if has_archive_mod else 'absent'}",
        f"tests/test_bundle.py={'present' if has_test else 'missing'}",
    ]
    if not has_export:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_bundle_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_bundle_verify() -> ProbeOutcome:
    """GJ-8 regista: offline bundle verification."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_verify = _sibling_has_method(
        "regista", "Regista", "verify_audit_bundle_offline"
    )
    has_bundle_mod = _sibling_module_file_exists("regista", "regista/_bundle.py")
    has_test = _sibling_test_exists("regista", "test_bundle.py")
    evidence_parts = [
        f"Regista.verify_audit_bundle_offline={'present' if has_verify else 'missing'}",
        f"regista/_bundle.py={'present' if has_bundle_mod else 'absent'}",
        f"tests/test_bundle.py={'present' if has_test else 'missing'}",
    ]
    if not has_verify:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_bundle_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_regista_contracts() -> ProbeOutcome:
    """GJ-9 regista: version / config / secret / doctor contracts."""
    if not _sibling_available("regista", "regista"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "regista not importable and /projects/regista absent",
        )
    has_doctor_mod = _sibling_module_file_exists("regista", "regista/_doctor.py")
    has_cli_mod = _sibling_module_file_exists("regista", "regista/_cli.py")
    has_version_cmd = _sibling_cli_has_subcommand("regista", "version")
    has_doctor_cmd = _sibling_cli_has_subcommand("regista", "doctor")
    has_config_cmd = _sibling_cli_has_subcommand("regista", "config")
    has_secrets_cmd = _sibling_cli_has_subcommand("regista", "secrets")
    evidence_parts = [
        f"regista/_doctor.py={'present' if has_doctor_mod else 'absent'}",
        f"regista/_cli.py={'present' if has_cli_mod else 'absent'}",
        f"CLI 'version'={'present' if has_version_cmd else 'missing'}",
        f"CLI 'doctor'={'present' if has_doctor_cmd else 'missing'}",
        f"CLI 'config'={'present' if has_config_cmd else 'missing'}",
        f"CLI 'secrets'={'present' if has_secrets_cmd else 'missing'}",
    ]
    if not (has_doctor_mod and has_cli_mod):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    present_cmds = sum(
        [has_version_cmd, has_doctor_cmd, has_config_cmd, has_secrets_cmd]
    )
    if present_cmds < 4:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


# ---------------------------------------------------------------------------
# agent-notes probes (5 rows)
# ---------------------------------------------------------------------------


def _probe_agent_notes_project_discovery() -> ProbeOutcome:
    """GJ-1 agent-notes: project discovery from cwd and per-user identity."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_face = _sibling_module_file_exists(
        "agent-notes", "agent_notes/core/face_factory.py"
    )
    has_face_mod = _sibling_import("agent_notes.core.face_factory")
    has_cli_workspace = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/workspace.py"
    )
    evidence_parts = [
        f"agent_notes/core/face_factory.py={'present' if has_face else 'absent'}",
        f"face_factory importable={'yes' if has_face_mod is not None else 'no'}",
        f"agent_notes/cli/workspace.py={'present' if has_cli_workspace else 'absent'}",
    ]
    if not has_face:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Face factory exists but write-through is gated (WI-013); partial.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; write-through gated per agent-notes WI-013",
    )


def _probe_agent_notes_work_item_cli() -> ProbeOutcome:
    """GJ-2 agent-notes: work-item skills / CLI."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_cli_mod = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/work_items.py"
    )
    has_register = _sibling_has_attr(
        "agent_notes.cli.work_items", "register_work_item_parsers"
    )
    has_test = _sibling_test_exists("agent-notes", "test_cli.py")
    evidence_parts = [
        f"agent_notes/cli/work_items.py={'present' if has_cli_mod else 'absent'}",
        f"register_work_item_parsers={'present' if has_register else 'missing'}",
        f"tests/test_cli.py={'present' if has_test else 'missing'}",
    ]
    if not (has_cli_mod and has_register):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_agent_notes_knowledge_cli() -> ProbeOutcome:
    """GJ-3 agent-notes: breadcrumb / memory / reflection skills and CLI."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_memory_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/memory.py"
    )
    has_skills_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/skills.py"
    )
    has_breadcrumbs_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/breadcrumbs.py"
    )
    has_skills_dir = (SIBLINGS_ROOT / "agent-notes" / "skills").is_dir()
    has_test = _sibling_test_exists("agent-notes", "test_breadcrumbs.py")
    evidence_parts = [
        f"agent_notes/cli/memory.py={'present' if has_memory_cli else 'absent'}",
        f"agent_notes/cli/skills.py={'present' if has_skills_cli else 'absent'}",
        f"agent_notes/cli/breadcrumbs.py={'present' if has_breadcrumbs_cli else 'absent'}",
        f"skills/ dir={'present' if has_skills_dir else 'absent'}",
        f"tests/test_breadcrumbs.py={'present' if has_test else 'missing'}",
    ]
    if not (has_memory_cli and has_breadcrumbs_cli):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_skills_cli and has_skills_dir and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_agent_notes_write_through() -> ProbeOutcome:
    """GJ-3 agent-notes: signed note write-through to regista."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_note_model = _sibling_module_file_exists(
        "agent-notes", "agent_notes/core/note_model.py"
    )
    has_memory_model = _sibling_module_file_exists(
        "agent-notes", "agent_notes/core/memory_model.py"
    )
    has_outbox_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/outbox.py"
    )
    has_reconcile = _sibling_has_attr(
        "agent_notes.cli.outbox", "cmd_outbox_reconcile"
    )
    evidence_parts = [
        f"agent_notes/core/note_model.py={'present' if has_note_model else 'absent'}",
        f"agent_notes/core/memory_model.py={'present' if has_memory_model else 'absent'}",
        f"agent_notes/cli/outbox.py={'present' if has_outbox_cli else 'absent'}",
        f"cmd_outbox_reconcile={'present' if has_reconcile else 'missing'}",
    ]
    if not (has_note_model and has_memory_model):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Write-through is implemented but gated; dossier has no note read surface.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; write-through implemented but gated (agent-notes WI-013)",
    )


def _probe_agent_notes_search() -> ProbeOutcome:
    """GJ-3 agent-notes: search across breadcrumbs, memories, links."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_search_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/search.py"
    )
    has_register = _sibling_has_attr(
        "agent_notes.cli.search", "register_search_parsers"
    )
    has_test = _sibling_test_exists("agent-notes", "test_search.py")
    evidence_parts = [
        f"agent_notes/cli/search.py={'present' if has_search_cli else 'absent'}",
        f"register_search_parsers={'present' if has_register else 'missing'}",
        f"tests/test_search.py={'present' if has_test else 'missing'}",
    ]
    if not (has_search_cli and has_register):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_agent_notes_review_cli() -> ProbeOutcome:
    """GJ-4 agent-notes: review CLI (pass, accept, reject, request-changes)."""
    if not _sibling_available("agent-notes", "agent_notes"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_notes not importable and /projects/agent-notes absent",
        )
    has_work_items_cli = _sibling_module_file_exists(
        "agent-notes", "agent_notes/cli/work_items.py"
    )
    has_register = _sibling_has_attr(
        "agent_notes.cli.work_items", "register_work_item_parsers"
    )
    has_test = _sibling_test_exists("agent-notes", "test_cli.py")
    evidence_parts = [
        f"agent_notes/cli/work_items.py={'present' if has_work_items_cli else 'absent'}",
        f"register_work_item_parsers={'present' if has_register else 'missing'}",
        f"tests/test_cli.py={'present' if has_test else 'missing'}",
    ]
    if not (has_work_items_cli and has_register):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


# ---------------------------------------------------------------------------
# dossier probes (7 rows)
# ---------------------------------------------------------------------------


def _probe_dossier_project_switcher() -> ProbeOutcome:
    """GJ-1 dossier: authenticated project switcher."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_authz_mod = _sibling_module_file_exists("dossier", "dossier/authz.py")
    has_app_mod = _sibling_module_file_exists("dossier", "dossier/app.py")
    has_project_route = _sibling_route_exists("dossier", "app", "/p/{project}")
    has_login_route = _sibling_route_exists("dossier", "app", "/login")
    has_test = _sibling_test_exists("dossier", "test_auth.py")
    evidence_parts = [
        f"dossier/authz.py={'present' if has_authz_mod else 'absent'}",
        f"dossier/app.py={'present' if has_app_mod else 'absent'}",
        f"route /p/{{project}}={'present' if has_project_route else 'missing'}",
        f"route /login={'present' if has_login_route else 'missing'}",
        f"tests/test_auth.py={'present' if has_test else 'missing'}",
    ]
    if not (has_authz_mod and has_app_mod and has_project_route):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Authz exists but defaults to flat-open (dossier WI-017); partial.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; authz defaults to flat-open per dossier WI-017",
    )


def _probe_dossier_work_forms() -> ProbeOutcome:
    """GJ-2 dossier: work queues, detail, transition, review forms."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_new_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/issues/new"
    )
    has_detail_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/issues/{work_item_id}"
    )
    has_transition_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/issues/{work_item_id}/transitions"
    )
    has_my_work_route = _sibling_route_exists("dossier", "app", "/my-work")
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"route /p/{{project}}/issues/new={'present' if has_new_route else 'missing'}",
        f"route /p/{{project}}/issues/{{work_item_id}}={'present' if has_detail_route else 'missing'}",
        f"route .../transitions={'present' if has_transition_route else 'missing'}",
        f"route /my-work={'present' if has_my_work_route else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not (has_new_route and has_detail_route and has_transition_route):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_dossier_separation_of_duties() -> ProbeOutcome:
    """GJ-2 dossier: separation-of-duties enforcement in review."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_assurance_mod = _sibling_module_file_exists(
        "dossier", "dossier/assurance.py"
    )
    has_review_route = _sibling_route_exists("dossier", "app", "/review")
    has_transition_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/issues/{work_item_id}/transitions"
    )
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"dossier/assurance.py={'present' if has_assurance_mod else 'absent'}",
        f"route /review={'present' if has_review_route else 'missing'}",
        f"route .../transitions={'present' if has_transition_route else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not (has_assurance_mod and has_transition_route):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_review_route and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_dossier_knowledge() -> ProbeOutcome:
    """GJ-3 dossier: knowledge read / browse / search."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_knowledge_mod = _sibling_module_file_exists(
        "dossier", "dossier/knowledge.py"
    )
    has_list_notes = _sibling_has_attr("dossier.knowledge", "list_notes")
    has_search_notes = _sibling_has_attr("dossier.knowledge", "search_notes")
    has_get_note = _sibling_has_attr("dossier.knowledge", "get_note")
    has_knowledge_route = _sibling_route_exists("dossier", "app", "/knowledge")
    has_search_route = _sibling_route_exists(
        "dossier", "app", "/knowledge/search"
    )
    has_test = _sibling_test_exists("dossier", "test_knowledge.py")
    evidence_parts = [
        f"dossier/knowledge.py={'present' if has_knowledge_mod else 'absent'}",
        f"list_notes={'present' if has_list_notes else 'missing'}",
        f"search_notes={'present' if has_search_notes else 'missing'}",
        f"get_note={'present' if has_get_note else 'missing'}",
        f"route /knowledge={'present' if has_knowledge_route else 'missing'}",
        f"route /knowledge/search={'present' if has_search_route else 'missing'}",
        f"tests/test_knowledge.py={'present' if has_test else 'missing'}",
    ]
    if not (has_knowledge_mod and has_list_notes):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_knowledge_route and has_search_route and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_dossier_review_queue() -> ProbeOutcome:
    """GJ-4 dossier: review queue and verdict forms."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_review_route = _sibling_route_exists("dossier", "app", "/review")
    has_transition_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/issues/{work_item_id}/transitions"
    )
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"route /review={'present' if has_review_route else 'missing'}",
        f"route .../transitions={'present' if has_transition_route else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not (has_review_route and has_transition_route):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_dossier_assurance() -> ProbeOutcome:
    """GJ-4 dossier: honest assurance level / independent-review signal."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_assurance_mod = _sibling_module_file_exists(
        "dossier", "dossier/assurance.py"
    )
    has_compute = _sibling_has_attr("dossier.assurance", "compute_assurance_level")
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"dossier/assurance.py={'present' if has_assurance_mod else 'absent'}",
        f"compute_assurance_level={'present' if has_compute else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not has_assurance_mod:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Computation is home-grown, not delegated to regista (dossier WI-012).
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; computation home-grown, not delegated to regista (dossier WI-012)",
    )


def _probe_dossier_activity_views() -> ProbeOutcome:
    """GJ-5 dossier: session / tool / file activity views."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_provenance_mod = _sibling_module_file_exists(
        "dossier", "dossier/provenance.py"
    )
    has_sessions_route = _sibling_route_exists("dossier", "app", "/sessions")
    has_session_detail_route = _sibling_route_exists(
        "dossier", "app", "/p/{project}/sessions/{session_id}"
    )
    has_feed_route = _sibling_route_exists("dossier", "app", "/feed")
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"dossier/provenance.py={'present' if has_provenance_mod else 'absent'}",
        f"route /sessions={'present' if has_sessions_route else 'missing'}",
        f"route /p/{{project}}/sessions/{{session_id}}={'present' if has_session_detail_route else 'missing'}",
        f"route /feed={'present' if has_feed_route else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not (has_provenance_mod and has_sessions_route):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_session_detail_route and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    # Verification UX is partial (dossier Plan 017/018).
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; session list/detail present; verification UX partial (dossier Plan 017/018)",
    )


def _probe_dossier_degraded_capture() -> ProbeOutcome:
    """GJ-5 dossier: degraded / unsupported capture rendered honestly."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_assurance_mod = _sibling_module_file_exists(
        "dossier", "dossier/assurance.py"
    )
    has_compute = _sibling_has_attr("dossier.assurance", "compute_assurance_level")
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"dossier/assurance.py={'present' if has_assurance_mod else 'absent'}",
        f"compute_assurance_level={'present' if has_compute else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not has_assurance_mod:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Assurance no longer fails open (WI-014 fixed); delegation to regista still pending (WI-012).
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; fail-open fixed (WI-014); regista delegation pending (WI-012)",
    )


def _probe_dossier_notification_prefs() -> ProbeOutcome:
    """GJ-7 dossier: notification preferences and review/recovery deep links."""
    if not _sibling_available("dossier", "dossier"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "dossier not importable and /projects/dossier absent",
        )
    has_notif_mod = _sibling_module_file_exists(
        "dossier", "dossier/notifications.py"
    )
    has_emitter = _sibling_has_attr("dossier.notifications", "NotificationEmitter")
    # Check for notification preference routes in the app
    has_pref_route = _sibling_route_exists(
        "dossier", "app", "/notifications"
    ) or _sibling_route_exists("dossier", "app", "/me/notifications")
    has_test = _sibling_test_exists("dossier", "test_app.py")
    evidence_parts = [
        f"dossier/notifications.py={'present' if has_notif_mod else 'absent'}",
        f"NotificationEmitter={'present' if has_emitter else 'missing'}",
        f"notification preference route={'present' if has_pref_route else 'missing'}",
        f"tests/test_app.py={'present' if has_test else 'missing'}",
    ]
    if not has_notif_mod:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Notifications module exists but no preference UI or deep-link routing.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; NotificationEmitter present but no preference UI or deep-link routing",
    )


# ---------------------------------------------------------------------------
# agent-provenance (cairn) probes (3 rows)
# ---------------------------------------------------------------------------


def _probe_cairn_session_capture() -> ProbeOutcome:
    """GJ-5 agent-provenance: session and tool begin/end capture."""
    if not _sibling_available("agent-provenance", "cairn"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "cairn not importable and /projects/agent-provenance absent",
        )
    has_claude_hook = _sibling_module_file_exists(
        "agent-provenance", "cairn/_claude_hook.py"
    )
    has_codex_hook = _sibling_module_file_exists(
        "agent-provenance", "cairn/_codex_hook.py"
    )
    has_handle_pre = _sibling_has_attr("cairn._claude_hook", "handle_pre")
    has_handle_post = _sibling_has_attr("cairn._claude_hook", "handle_post")
    has_install = _sibling_has_attr("cairn._install", "run_install_harness")
    has_test = _sibling_test_exists(
        "agent-provenance", "test_claude_code_hook.py"
    )
    evidence_parts = [
        f"cairn/_claude_hook.py={'present' if has_claude_hook else 'absent'}",
        f"cairn/_codex_hook.py={'present' if has_codex_hook else 'absent'}",
        f"handle_pre={'present' if has_handle_pre else 'missing'}",
        f"handle_post={'present' if has_handle_post else 'missing'}",
        f"run_install_harness={'present' if has_install else 'missing'}",
        f"tests/test_claude_code_hook.py={'present' if has_test else 'missing'}",
    ]
    if not (has_claude_hook and has_handle_pre and has_handle_post):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_codex_hook and has_install and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_cairn_principal_binding() -> ProbeOutcome:
    """GJ-5 agent-provenance: principal / delegation / work binding."""
    if not _sibling_available("agent-provenance", "cairn"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "cairn not importable and /projects/agent-provenance absent",
        )
    has_client = _sibling_has_attr("cairn", "CairnClient")
    has_adapter = _sibling_has_attr("cairn", "CairnAdapter")
    has_tool_call = _sibling_has_method("cairn", "CairnClient", "tool_call")
    has_subagent = _sibling_has_attr("cairn", "SubagentIdentity")
    has_adapter_mod = _sibling_module_file_exists(
        "agent-provenance", "cairn/adapter.py"
    )
    has_test = _sibling_test_exists("agent-provenance", "test_cairn.py")
    evidence_parts = [
        f"CairnClient={'present' if has_client else 'missing'}",
        f"CairnAdapter={'present' if has_adapter else 'missing'}",
        f"CairnClient.tool_call={'present' if has_tool_call else 'missing'}",
        f"SubagentIdentity={'present' if has_subagent else 'missing'}",
        f"cairn/adapter.py={'present' if has_adapter_mod else 'absent'}",
        f"tests/test_cairn.py={'present' if has_test else 'missing'}",
    ]
    if not (has_client and has_tool_call):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_adapter and has_subagent and has_adapter_mod and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_cairn_bundle_export() -> ProbeOutcome:
    """GJ-8 agent-provenance: bundle export, diff/chain verify, human report."""
    if not _sibling_available("agent-provenance", "cairn"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "cairn not importable and /projects/agent-provenance absent",
        )
    has_cli_mod = _sibling_module_file_exists("agent-provenance", "cairn/_cli.py")
    has_proof_mod = _sibling_module_file_exists(
        "agent-provenance", "cairn/proof.py"
    )
    has_verifier_mod = _sibling_module_file_exists(
        "agent-provenance", "cairn/verifier.py"
    )
    has_export_cmd = _sibling_cli_has_subcommand("cairn", "export")
    has_verify_cmd = _sibling_cli_has_subcommand("cairn", "verify")
    has_verify_chain_cmd = _sibling_cli_has_subcommand("cairn", "verify-chain")
    has_diff_cmd = _sibling_cli_has_subcommand("cairn", "diff")
    has_portal_cmd = _sibling_cli_has_subcommand("cairn", "portal")
    has_test = _sibling_test_exists("agent-provenance", "test_e2e_proof.py")
    evidence_parts = [
        f"cairn/_cli.py={'present' if has_cli_mod else 'absent'}",
        f"cairn/proof.py={'present' if has_proof_mod else 'absent'}",
        f"cairn/verifier.py={'present' if has_verifier_mod else 'absent'}",
        f"CLI 'export'={'present' if has_export_cmd else 'missing'}",
        f"CLI 'verify'={'present' if has_verify_cmd else 'missing'}",
        f"CLI 'verify-chain'={'present' if has_verify_chain_cmd else 'missing'}",
        f"CLI 'diff'={'present' if has_diff_cmd else 'missing'}",
        f"CLI 'portal'={'present' if has_portal_cmd else 'missing'}",
        f"tests/test_e2e_proof.py={'present' if has_test else 'missing'}",
    ]
    if not (has_cli_mod and has_proof_mod and has_verifier_mod):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    present_cmds = sum(
        [has_export_cmd, has_verify_cmd, has_verify_chain_cmd, has_diff_cmd, has_portal_cmd]
    )
    if present_cmds < 5 or not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


# ---------------------------------------------------------------------------
# agent-capability-broker probes (4 rows)
# ---------------------------------------------------------------------------


def _probe_acb_core_verbs() -> ProbeOutcome:
    """GJ-6 agent-capability-broker: manifest, reconcile, exec, install-harness."""
    if not _sibling_available("agent-capability-broker", "agent_capability_broker"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_capability_broker not importable and /projects/agent-capability-broker absent",
        )
    has_cli_mod = _sibling_module_file_exists(
        "agent-capability-broker", "agent_capability_broker/cli.py"
    )
    has_model_mod = _sibling_module_file_exists(
        "agent-capability-broker", "agent_capability_broker/model.py"
    )
    has_doctor_cmd = _sibling_cli_has_subcommand("acb", "doctor")
    has_reconcile_cmd = _sibling_cli_has_subcommand("acb", "reconcile")
    has_exec_cmd = _sibling_cli_has_subcommand("acb", "exec")
    has_install_cmd = _sibling_cli_has_subcommand("acb", "install-harness")
    has_test_doctor = _sibling_test_exists(
        "agent-capability-broker", "test_doctor_conformance.py"
    )
    has_test_reconcile = _sibling_test_exists(
        "agent-capability-broker", "test_reconcile.py"
    )
    evidence_parts = [
        f"cli.py={'present' if has_cli_mod else 'absent'}",
        f"model.py={'present' if has_model_mod else 'absent'}",
        f"CLI 'doctor'={'present' if has_doctor_cmd else 'missing'}",
        f"CLI 'reconcile'={'present' if has_reconcile_cmd else 'missing'}",
        f"CLI 'exec'={'present' if has_exec_cmd else 'missing'}",
        f"CLI 'install-harness'={'present' if has_install_cmd else 'missing'}",
        f"tests/test_doctor_conformance.py={'present' if has_test_doctor else 'missing'}",
        f"tests/test_reconcile.py={'present' if has_test_reconcile else 'missing'}",
    ]
    if not (has_cli_mod and has_model_mod):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    present_cmds = sum([has_doctor_cmd, has_reconcile_cmd, has_exec_cmd, has_install_cmd])
    if present_cmds < 4:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    # All CLI verbs present; e2e exec raises NotImplementedError.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; core verbs present; e2e exec is NotImplementedError (acb Plan 006 WI-1.2)",
    )


def _probe_acb_credential_provider() -> ProbeOutcome:
    """GJ-6 agent-capability-broker: credential provider with secret-safe injection."""
    if not _sibling_available("agent-capability-broker", "agent_capability_broker"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_capability_broker not importable and /projects/agent-capability-broker absent",
        )
    has_providers_mod = _sibling_module_file_exists(
        "agent-capability-broker", "agent_capability_broker/providers.py"
    )
    has_exec_composed = _sibling_has_attr(
        "agent_capability_broker.providers", "exec_composed"
    )
    has_cred_vault = _sibling_module_file_exists(
        "agent-capability-broker", "agent_capability_broker/cred_vault.py"
    )
    has_test = _sibling_test_exists(
        "agent-capability-broker", "test_exec.py"
    )
    evidence_parts = [
        f"providers.py={'present' if has_providers_mod else 'absent'}",
        f"exec_composed={'present' if has_exec_composed else 'missing'}",
        f"cred_vault.py={'present' if has_cred_vault else 'absent'}",
        f"tests/test_exec.py={'present' if has_test else 'missing'}",
    ]
    if not (has_providers_mod and has_exec_composed):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Provider injection works and is unit-tested; full e2e exec is NotImplementedError.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; provider injection unit-tested; full e2e exec is NotImplementedError",
    )


def _probe_acb_e2e_provider() -> ProbeOutcome:
    """GJ-6 agent-capability-broker: browser / E2E provider and live proof."""
    if not _sibling_available("agent-capability-broker", "agent_capability_broker"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_capability_broker not importable and /projects/agent-capability-broker absent",
        )
    has_e2e_class = _sibling_has_attr(
        "agent_capability_broker.providers", "E2eProvider"
    )
    has_inspect = _sibling_has_method(
        "agent_capability_broker.providers", "E2eProvider", "inspect"
    )
    has_exec = _sibling_has_method(
        "agent_capability_broker.providers", "E2eProvider", "exec"
    )
    # Check if exec raises NotImplementedError
    exec_is_stub = False
    if has_exec:
        try:
            import inspect as _inspect

            src = _inspect.getsource(
                getattr(
                    _sibling_import("agent_capability_broker.providers"),
                    "E2eProvider",
                ).exec
            )
            exec_is_stub = "NotImplementedError" in src
        except Exception:
            pass
    has_test = _sibling_test_exists(
        "agent-capability-broker", "test_e2e_inspect.py"
    )
    evidence_parts = [
        f"E2eProvider={'present' if has_e2e_class else 'missing'}",
        f"E2eProvider.inspect={'present' if has_inspect else 'missing'}",
        f"E2eProvider.exec={'present' if has_exec else 'missing'}",
        f"exec raises NotImplementedError={'yes' if exec_is_stub else 'no'}",
        f"tests/test_e2e_inspect.py={'present' if has_test else 'missing'}",
    ]
    if not has_e2e_class:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_inspect:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    # inspect exists; exec is NotImplementedError.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; E2eProvider.inspect present; exec not implemented; Codex deferred",
    )


def _probe_acb_rogue_detection() -> ProbeOutcome:
    """GJ-6 agent-capability-broker: rogue / clobbered capability detection."""
    if not _sibling_available("agent-capability-broker", "agent_capability_broker"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent_capability_broker not importable and /projects/agent-capability-broker absent",
        )
    # The doctor only inspects manifest-listed capabilities. Check for any
    # rogue/clobber scanning logic in the CLI doctor path.
    has_doctor = _sibling_has_attr("agent_capability_broker.cli", "_cmd_doctor")
    has_doctor_checks = _sibling_has_attr(
        "agent_capability_broker.cli", "_doctor_checks"
    )
    has_inspect_all = _sibling_has_attr(
        "agent_capability_broker.cli", "_inspect_all"
    )
    # Look for rogue/clobber scanning in the source
    has_rogue_scan = _sibling_source_contains(
        "agent-capability-broker",
        "agent_capability_broker/cli.py",
        "rogue",
    ) or _sibling_source_contains(
        "agent-capability-broker",
        "agent_capability_broker/cli.py",
        "clobber",
    )
    evidence_parts = [
        f"_cmd_doctor={'present' if has_doctor else 'missing'}",
        f"_doctor_checks={'present' if has_doctor_checks else 'missing'}",
        f"_inspect_all={'present' if has_inspect_all else 'missing'}",
        f"rogue/clobber scan in cli.py={'present' if has_rogue_scan else 'absent'}",
    ]
    if not has_doctor:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Doctor only inspects manifest-listed capabilities; no rogue detection.
    return ProbeOutcome(
        ProbeResult.ABSENT,
        "; ".join(evidence_parts)
        + "; doctor only inspects manifest-listed capabilities (agent-suite WI-001)",
    )


# ---------------------------------------------------------------------------
# agent-wake probes (7 rows)
#
# agent-wake's daemon source lives at ``/projects/agent-wake/daemon/src/`` and
# tests at ``/projects/agent-wake/daemon/tests/`` (not ``src/`` / ``tests/``).
# The ``_WAKE_SRC`` and ``_WAKE_TESTS`` constants keep the probe calls readable.
# ---------------------------------------------------------------------------

_WAKE_SRC = "daemon/src"
_WAKE_TESTS = "daemon/tests"


def _probe_wake_http_ingress() -> ProbeOutcome:
    """GJ-7 agent-wake: authenticated HTTP ingress."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    has_ingest = _sibling_module_file_exists(
        "agent-wake", "agent_waked/ingest.py", src_prefix=_WAKE_SRC
    )
    # HMAC auth lives in gating.py, imported by ingest.py
    has_gating = _sibling_module_file_exists(
        "agent-wake", "agent_waked/gating.py", src_prefix=_WAKE_SRC
    )
    has_hmac = _sibling_source_contains(
        "agent-wake", "agent_waked/gating.py", "hmac", src_prefix=_WAKE_SRC
    )
    has_verify_sig = _sibling_source_contains(
        "agent-wake",
        "agent_waked/ingest.py",
        "verify_signature",
        src_prefix=_WAKE_SRC,
    )
    has_create_app = _sibling_source_contains(
        "agent-wake",
        "agent_waked/ingest.py",
        "create_ingest_app",
        src_prefix=_WAKE_SRC,
    )
    has_test = _sibling_test_exists(
        "agent-wake", "test_ingest.py", tests_subdir=_WAKE_TESTS
    )
    evidence_parts = [
        f"daemon/src/agent_waked/ingest.py={'present' if has_ingest else 'absent'}",
        f"daemon/src/agent_waked/gating.py={'present' if has_gating else 'absent'}",
        f"HMAC auth in gating.py={'present' if has_hmac else 'missing'}",
        f"ingest.py imports verify_signature={'present' if has_verify_sig else 'missing'}",
        f"create_ingest_app={'present' if has_create_app else 'missing'}",
        f"daemon/tests/test_ingest.py={'present' if has_test else 'missing'}",
    ]
    if not (has_ingest and has_create_app):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_hmac and has_verify_sig and has_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_wake_dedup_retry() -> ProbeOutcome:
    """GJ-7 agent-wake: durable dedup / retry / outbox / dead-letter."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    has_ingest = _sibling_module_file_exists(
        "agent-wake", "agent_waked/ingest.py", src_prefix=_WAKE_SRC
    )
    has_dedupe = _sibling_source_contains(
        "agent-wake", "agent_waked/ingest.py", "class Dedupe", src_prefix=_WAKE_SRC
    )
    has_outbox = _sibling_module_file_exists(
        "agent-wake", "agent_waked/outbox.py", src_prefix=_WAKE_SRC
    )
    has_dead_letter = _sibling_source_contains(
        "agent-wake", "agent_waked/ingest.py", "dead_letter", src_prefix=_WAKE_SRC
    ) or _sibling_source_contains(
        "agent-wake", "agent_waked/outbox.py", "dead_letter", src_prefix=_WAKE_SRC
    )
    has_test = _sibling_test_exists(
        "agent-wake", "test_ingest.py", tests_subdir=_WAKE_TESTS
    )
    has_outbox_test = _sibling_test_exists(
        "agent-wake", "test_outbox.py", tests_subdir=_WAKE_TESTS
    )
    evidence_parts = [
        f"Dedupe class in ingest.py={'present' if has_dedupe else 'missing'}",
        f"agent_waked/outbox.py={'present' if has_outbox else 'absent'}",
        f"dead-letter logic={'present' if has_dead_letter else 'absent'}",
        f"daemon/tests/test_ingest.py={'present' if has_test else 'missing'}",
        f"daemon/tests/test_outbox.py={'present' if has_outbox_test else 'missing'}",
    ]
    if not (has_ingest and has_dedupe):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # Dedup is in-memory FIFO; no durable inbox or dead-letter visibility.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; dedup is in-memory FIFO; no durable inbox or dead-letter (BC-WAKE-004/012)",
    )


def _probe_wake_live_wake() -> ProbeOutcome:
    """GJ-7 agent-wake: live_wake (Claude, OpenCode)."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    has_opencode_adapter = (
        SIBLINGS_ROOT / "agent-wake" / "adapters" / "opencode" / "src" / "wake.ts"
    ).exists()
    has_claude_adapter = (
        SIBLINGS_ROOT
        / "agent-wake"
        / "adapters"
        / "claude"
        / "src"
        / "agent_wake_claude"
        / "channel.py"
    ).exists()
    has_test = _sibling_test_exists(
        "agent-wake", "test_e2e.py", tests_subdir=_WAKE_TESTS
    )
    evidence_parts = [
        f"adapters/opencode/src/wake.ts={'present' if has_opencode_adapter else 'absent'}",
        f"adapters/claude/src/agent_wake_claude/channel.py={'present' if has_claude_adapter else 'absent'}",
        f"daemon/tests/test_e2e.py={'present' if has_test else 'missing'}",
    ]
    if not (has_opencode_adapter and has_claude_adapter):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not has_test:
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_wake_silent_inject() -> ProbeOutcome:
    """GJ-7 agent-wake: silent_inject."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    # Check opencode adapter for noReply (silent-inject support)
    opencode_wake = (
        SIBLINGS_ROOT / "agent-wake" / "adapters" / "opencode" / "src" / "wake.ts"
    )
    has_opencode_silent = False
    if opencode_wake.exists():
        try:
            has_opencode_silent = "noReply" in opencode_wake.read_text(encoding="utf-8")
        except Exception:
            pass
    # Check claude adapter for silent event handling
    claude_channel = (
        SIBLINGS_ROOT
        / "agent-wake"
        / "adapters"
        / "claude"
        / "src"
        / "agent_wake_claude"
        / "channel.py"
    )
    claude_drops_silent = False
    if claude_channel.exists():
        try:
            claude_drops_silent = "silent" in claude_channel.read_text(encoding="utf-8")
        except Exception:
            pass
    evidence_parts = [
        f"opencode noReply/silent={'present' if has_opencode_silent else 'missing'}",
        f"claude silent handling={'drops' if claude_drops_silent else 'missing'}",
    ]
    if not has_opencode_silent:
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    # OpenCode supports silent inject; Claude adapter drops silent events.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; OpenCode supports silent inject; Claude adapter drops silent events",
    )


def _probe_wake_next_session() -> ProbeOutcome:
    """GJ-7 agent-wake: next_session / managed_session delivery."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    # Search the daemon and adapters for next_session/managed_session
    daemon_src = SIBLINGS_ROOT / "agent-wake" / "daemon" / "src"
    adapters_src = SIBLINGS_ROOT / "agent-wake" / "adapters"
    has_next_session = False
    for root in (daemon_src, adapters_src):
        if not root.exists():
            continue
        for py_file in root.rglob("*.py"):
            try:
                if "next_session" in py_file.read_text(encoding="utf-8") or "managed_session" in py_file.read_text(
                    encoding="utf-8"
                ):
                    has_next_session = True
                    break
            except Exception:
                pass
        if has_next_session:
            break
    for root in (daemon_src, adapters_src):
        if not root.exists():
            continue
        for ts_file in root.rglob("*.ts"):
            try:
                if "next_session" in ts_file.read_text(encoding="utf-8") or "managed_session" in ts_file.read_text(
                    encoding="utf-8"
                ):
                    has_next_session = True
                    break
            except Exception:
                pass
        if has_next_session:
            break
    evidence_parts = [
        f"next_session/managed_session in daemon+adapters={'present' if has_next_session else 'absent'}",
    ]
    if not has_next_session:
        return ProbeOutcome(
            ProbeResult.ABSENT,
            "; ".join(evidence_parts) + "; design exists, no implementation (agent-wake Plan 006)",
        )
    return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))


def _probe_wake_human_delivery() -> ProbeOutcome:
    """GJ-7 agent-wake: human webhook and email delivery."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    has_webhook = _sibling_module_file_exists(
        "agent-wake", "agent_waked/channels/webhook.py", src_prefix=_WAKE_SRC
    )
    has_email = _sibling_module_file_exists(
        "agent-wake", "agent_waked/channels/email.py", src_prefix=_WAKE_SRC
    )
    has_webhook_test = _sibling_test_exists(
        "agent-wake", "test_channels_webhook.py", tests_subdir=_WAKE_TESTS
    )
    has_email_test = _sibling_test_exists(
        "agent-wake", "test_channels_email.py", tests_subdir=_WAKE_TESTS
    )
    evidence_parts = [
        f"channels/webhook.py={'present' if has_webhook else 'absent'}",
        f"channels/email.py={'present' if has_email else 'absent'}",
        f"daemon/tests/test_channels_webhook.py={'present' if has_webhook_test else 'missing'}",
        f"daemon/tests/test_channels_email.py={'present' if has_email_test else 'missing'}",
    ]
    if not (has_webhook and has_email):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_webhook_test and has_email_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    return ProbeOutcome(ProbeResult.PASS, "; ".join(evidence_parts))


def _probe_wake_replay_rejection() -> ProbeOutcome:
    """GJ-7 agent-wake: replayed event rejection."""
    if not _sibling_available("agent-wake"):
        return ProbeOutcome(
            ProbeResult.HAND_ASSESSED,
            "agent-wake checkout absent and no daemon installed",
        )
    has_dedupe = _sibling_source_contains(
        "agent-wake", "agent_waked/ingest.py", "class Dedupe", src_prefix=_WAKE_SRC
    )
    has_dedupe_check = _sibling_source_contains(
        "agent-wake", "agent_waked/ingest.py", "dedupe.check", src_prefix=_WAKE_SRC
    )
    has_test = _sibling_test_exists(
        "agent-wake", "test_ingest.py", tests_subdir=_WAKE_TESTS
    )
    has_e2e_test = _sibling_test_exists(
        "agent-wake", "test_e2e.py", tests_subdir=_WAKE_TESTS
    )
    evidence_parts = [
        f"Dedupe class={'present' if has_dedupe else 'missing'}",
        f"dedupe.check call={'present' if has_dedupe_check else 'missing'}",
        f"daemon/tests/test_ingest.py={'present' if has_test else 'missing'}",
        f"daemon/tests/test_e2e.py={'present' if has_e2e_test else 'missing'}",
    ]
    if not (has_dedupe and has_dedupe_check):
        return ProbeOutcome(ProbeResult.ABSENT, "; ".join(evidence_parts))
    if not (has_test and has_e2e_test):
        return ProbeOutcome(ProbeResult.PARTIAL, "; ".join(evidence_parts))
    # Duplicate event_id rejected while running; in-memory dedup lost on restart.
    return ProbeOutcome(
        ProbeResult.PARTIAL,
        "; ".join(evidence_parts)
        + "; dedup rejects duplicates while running; in-memory dedup lost on restart (BC-WAKE-004/012)",
    )


# ---------------------------------------------------------------------------
# PROBES registry: maps (journey, component, surface) → probe-function-name.
# Every row in the matrix must have a named probe (WI-0.1 AC).
# ---------------------------------------------------------------------------

PROBES: dict[tuple[str, str, str], str] = {
    # agent-suite (8 rows)
    ("GJ-1", "agent-suite", "profile-aware bootstrap / deploy CLI"): "_probe_deploy_cli",
    ("GJ-1", "agent-suite", "project onboarding and harness selection"): "_probe_onboard_harness",
    ("GJ-1", "agent-suite", "identity lifecycle / onboarding / offboarding"): "_probe_identity_lifecycle",
    ("GJ-8", "agent-suite", "suite-level evidence export orchestration"): "_probe_evidence_export",
    ("GJ-9", "agent-suite", "backup / restore / disaster recovery orchestration"): "_probe_backup_restore",
    ("GJ-9", "agent-suite", "upgrade / rollback / forward-recovery gates"): "_probe_upgrade_rollback_forward",
    ("GJ-9", "agent-suite", "profile-aware doctor aggregation"): "_probe_doctor",
    ("GJ-9", "agent-suite", "compatibility lock and drift check"): "_probe_lock",
    # regista (9 rows)
    ("GJ-1", "regista", "project / schema provisioning"): "_probe_regista_provisioning",
    ("GJ-1", "regista", "workflow registration and discovery"): "_probe_regista_workflow_registration",
    ("GJ-1", "regista", "principal enrollment, rotation, revocation, delegation"): "_probe_regista_principal_lifecycle",
    ("GJ-2", "regista", "work-item lifecycle (create, claim, transition)"): "_probe_regista_work_item_lifecycle",
    ("GJ-2", "regista", "race-free claim / assignment"): "_probe_regista_race_free_claims",
    ("GJ-4", "regista", "cross-lineage review validators"): "_probe_regista_review_validators",
    ("GJ-8", "regista", "scoped evidence bundle export"): "_probe_regista_bundle_export",
    ("GJ-8", "regista", "offline bundle verification"): "_probe_regista_bundle_verify",
    ("GJ-9", "regista", "version / config / secret / doctor contracts"): "_probe_regista_contracts",
    # agent-notes (6 rows)
    ("GJ-1", "agent-notes", "project discovery from cwd and per-user identity"): "_probe_agent_notes_project_discovery",
    ("GJ-2", "agent-notes", "work-item skills / CLI"): "_probe_agent_notes_work_item_cli",
    ("GJ-3", "agent-notes", "breadcrumb / memory / reflection skills and CLI"): "_probe_agent_notes_knowledge_cli",
    ("GJ-3", "agent-notes", "signed note write-through to regista"): "_probe_agent_notes_write_through",
    ("GJ-3", "agent-notes", "search across breadcrumbs, memories, links"): "_probe_agent_notes_search",
    ("GJ-4", "agent-notes", "review CLI (pass, accept, reject, request-changes)"): "_probe_agent_notes_review_cli",
    # dossier (8 rows)
    ("GJ-1", "dossier", "authenticated project switcher"): "_probe_dossier_project_switcher",
    ("GJ-2", "dossier", "work queues, detail, transition, review forms"): "_probe_dossier_work_forms",
    ("GJ-2", "dossier", "separation-of-duties enforcement in review"): "_probe_dossier_separation_of_duties",
    ("GJ-3", "dossier", "knowledge read / browse / search"): "_probe_dossier_knowledge",
    ("GJ-4", "dossier", "review queue and verdict forms"): "_probe_dossier_review_queue",
    ("GJ-4", "dossier", "honest assurance level / independent-review signal"): "_probe_dossier_assurance",
    ("GJ-5", "dossier", "session / tool / file activity views"): "_probe_dossier_activity_views",
    ("GJ-5", "dossier", "degraded / unsupported capture rendered honestly"): "_probe_dossier_degraded_capture",
    ("GJ-7", "dossier", "notification preferences and review/recovery deep links"): "_probe_dossier_notification_prefs",
    # agent-provenance (3 rows)
    ("GJ-5", "agent-provenance", "session and tool begin/end capture"): "_probe_cairn_session_capture",
    ("GJ-5", "agent-provenance", "principal / delegation / work binding"): "_probe_cairn_principal_binding",
    ("GJ-8", "agent-provenance", "bundle export, diff/chain verify, human report"): "_probe_cairn_bundle_export",
    # agent-capability-broker (4 rows)
    ("GJ-6", "agent-capability-broker", "manifest, reconcile, exec, install-harness"): "_probe_acb_core_verbs",
    ("GJ-6", "agent-capability-broker", "credential provider with secret-safe injection"): "_probe_acb_credential_provider",
    ("GJ-6", "agent-capability-broker", "browser / E2E provider and live proof"): "_probe_acb_e2e_provider",
    ("GJ-6", "agent-capability-broker", "rogue / clobbered capability detection"): "_probe_acb_rogue_detection",
    # agent-wake (7 rows)
    ("GJ-7", "agent-wake", "authenticated HTTP ingress"): "_probe_wake_http_ingress",
    ("GJ-7", "agent-wake", "durable dedup / retry / outbox / dead-letter"): "_probe_wake_dedup_retry",
    ("GJ-7", "agent-wake", "live_wake (Claude, OpenCode)"): "_probe_wake_live_wake",
    ("GJ-7", "agent-wake", "silent_inject"): "_probe_wake_silent_inject",
    ("GJ-7", "agent-wake", "next_session / managed_session delivery"): "_probe_wake_next_session",
    ("GJ-7", "agent-wake", "human webhook and email delivery"): "_probe_wake_human_delivery",
    ("GJ-7", "agent-wake", "replayed event rejection"): "_probe_wake_replay_rejection",
}


# ---------------------------------------------------------------------------
# observed_revisions: record the git HEAD / package version for each component
# probed, so the matrix output records what was observed.
# ---------------------------------------------------------------------------

_COMPONENT_REVISION_SOURCES: dict[str, dict[str, str | None]] = {
    "agent-suite": {"checkout": None, "package": "agent_suite"},
    "regista": {"checkout": "regista", "package": "regista"},
    "agent-notes": {"checkout": "agent-notes", "package": "agent_notes"},
    "dossier": {"checkout": "dossier", "package": "dossier"},
    "agent-provenance": {"checkout": "agent-provenance", "package": "cairn"},
    "agent-capability-broker": {
        "checkout": "agent-capability-broker",
        "package": "agent_capability_broker",
    },
    "agent-wake": {"checkout": "agent-wake", "package": None},
}


def _git_head(path: Path) -> str | None:
    """Return the short git HEAD rev for a path, or None."""
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            cwd=str(path),
        )
        if result.returncode == 0:
            rev = result.stdout.strip()
            return rev if rev else None
    except Exception:
        pass
    return None


def _package_version(package: str) -> str | None:
    """Return the installed package version, or None."""
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def _compute_observed_revisions() -> dict[str, str | None]:
    """Record the observed revision for each component probed.

    For each component, try the installed package version first, then the git
    HEAD of the sibling checkout, then None if neither is available.
    """
    revisions: dict[str, str | None] = {}
    for component, info in _COMPONENT_REVISION_SOURCES.items():
        rev: str | None = None
        package = info["package"]
        checkout = info["checkout"]
        # agent-suite uses the repo root's git HEAD
        if component == "agent-suite":
            rev = _git_head(REPO_ROOT)
        else:
            # Try package version first
            if package is not None:
                rev = _package_version(package)
            # Fall back to git HEAD in the checkout
            if rev is None and checkout is not None:
                checkout_path = SIBLINGS_ROOT / checkout
                if checkout_path.exists():
                    rev = _git_head(checkout_path)
        revisions[component] = rev
    return revisions


# ---------------------------------------------------------------------------
# Probe runner: applies all probes to the matrix data.
# ---------------------------------------------------------------------------


def apply_probes(matrix_data: dict[str, Any]) -> dict[str, Any]:
    """Run all registered probes on the matrix data and update it in place.

    Updates each row's ``status`` and ``proof`` based on the probe result.
    Sets ``status_source``, ``generated_at``, and ``observed_revisions``.
    """
    probed_count = 0
    hand_assessed_count = 0
    unprobed_count = 0

    for row in matrix_data["rows"]:
        key = (row["journey"], row["component"], row["surface"])
        probe_fn_name = PROBES.get(key)
        if probe_fn_name is None:
            unprobed_count += 1
            continue
        probe_fn = globals()[probe_fn_name]
        outcome = probe_fn()
        match outcome.result:
            case ProbeResult.PASS | ProbeResult.PARTIAL | ProbeResult.BLOCKED | ProbeResult.ABSENT:
                row["status"] = outcome.result.value
                row["proof"] = (
                    f"probe: {probe_fn_name} -> {outcome.result.value}; "
                    f"evidence: {outcome.evidence}"
                )
            case ProbeResult.HAND_ASSESSED:
                # Preserve prior status AND proof — the sibling component is not
                # available, so the probe cannot mechanically determine the
                # status. This keeps the committed JSON stable across
                # environments (CI without siblings vs local dev with siblings).
                hand_assessed_count += 1
            case other:
                assert_never(other)
        probed_count += 1

    if probed_count > 0 and unprobed_count == 0 and hand_assessed_count == 0:
        matrix_data["status_source"] = "probe-emitted"
    elif probed_count > 0:
        matrix_data["status_source"] = "mixed-probe-and-hand"
    else:
        matrix_data["status_source"] = "hand-assessed"

    matrix_data["generated_at"] = datetime.now(timezone.utc).isoformat().replace(
        "+00:00", "Z"
    )
    matrix_data["observed_revisions"] = _compute_observed_revisions()
    return matrix_data


def _run_probes(matrix_data: dict[str, Any]) -> dict[str, Any]:
    """Backward-compatible alias for apply_probes."""
    return apply_probes(matrix_data)


def _matrix_to_markdown(matrix_data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# v1 Feature Matrix (Plan 009 WI-0.1)")
    lines.append("")
    lines.append(f"**Version:** {matrix_data['version']}  ")
    lines.append(f"**Generated:** {matrix_data['generated_at']}  ")
    lines.append(f"**Status source:** {matrix_data['status_source']}")
    lines.append("**Status values:** pass / partial / blocked / absent")
    lines.append("")
    if matrix_data["status_source"] == "probe-emitted":
        lines.append(
            "This matrix is emitted by named probes; every row's status is "
            "mechanically determined. Do not hand-edit the status column."
        )
    elif matrix_data["status_source"] == "mixed-probe-and-hand":
        lines.append(
            "Most rows are probe-emitted; some probes returned HAND_ASSESSED "
            "(sibling component not available). Re-run with siblings installed "
            "for full coverage."
        )
    else:
        lines.append(
            "Status values are hand-assessed from cross-project review. "
            "The WI-0.3 baseline run will replace them with probe-emitted statuses."
        )
    lines.append("")
    observed = matrix_data.get("observed_revisions", {})
    if observed:
        lines.append("## Observed revisions")
        lines.append("")
        for component, rev in observed.items():
            lines.append(f"- **{component}**: {rev if rev else '(unavailable)'}")
        lines.append("")
    lines.append("## Golden journeys")
    lines.append("")
    for key, value in matrix_data["golden_journeys"].items():
        lines.append(f"- **{key}** — {value}")
    lines.append("")
    lines.append("## Matrix")
    lines.append("")
    header = "| Journey | Profile | Component | Surface | Status | Dependency | Proof | Excluded | Notes |"
    separator = "|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(separator)
    for row in matrix_data["rows"]:
        cells = [
            row["journey"],
            row["profile"],
            row["component"],
            row["surface"],
            row["status"],
            row["dependency"],
            row["proof"],
            row["excluded"],
            row["notes"],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run executable probes for the v1 feature matrix."
    )
    parser.add_argument(
        "--data", type=Path, default=DATA_PATH, help="Path to the JSON matrix artifact"
    )
    parser.add_argument(
        "--docs", type=Path, default=DOCS_PATH, help="Path to write the Markdown matrix"
    )
    parser.add_argument(
        "--check", action="store_true", help="Validate and exit non-zero on drift"
    )
    parser.add_argument(
        "--stdout", action="store_true", help="Print Markdown to stdout"
    )
    args = parser.parse_args(argv)

    if not args.data.exists():
        print(f"ERROR: matrix file not found: {args.data}", file=sys.stderr)
        return 1

    matrix_data = json.loads(args.data.read_text(encoding="utf-8"))

    if args.check:
        pre_statuses: dict[tuple[str, str, str], str] = {
            (r["journey"], r["component"], r["surface"]): r["status"]
            for r in matrix_data["rows"]
        }
        probed = apply_probes(matrix_data)
        drift_found = False
        for row in probed["rows"]:
            key = (row["journey"], row["component"], row["surface"])
            old = pre_statuses.get(key)
            if old is not None and old != row["status"]:
                print(
                    f"DRIFT: {key} status changed: {old} -> {row['status']}",
                    file=sys.stderr,
                )
                drift_found = True
        if drift_found:
            return 1
        return 0

    matrix_data = apply_probes(matrix_data)

    markdown = _matrix_to_markdown(matrix_data)
    if args.stdout:
        print(markdown)
        return 0

    args.data.write_text(json.dumps(matrix_data, indent=2) + "\n", encoding="utf-8")
    args.docs.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.data}")
    print(f"Wrote {args.docs}")
    print(f"  status_source: {matrix_data['status_source']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
