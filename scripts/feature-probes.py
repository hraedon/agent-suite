#!/usr/bin/env python3
"""Executable baseline probes for the v1 feature matrix (Plan 015 WI-0.1).

Replaces hand-assessed statuses with probe-emitted results for agent-suite-
owned rows. Probes check whether the module exists, imports successfully,
exposes the expected public API (functions/classes), and has tests.

For rows owned by other components (regista, agent-notes, dossier, etc.),
statuses remain hand-assessed — those repos must run their own probes.

Usage:
    python3 scripts/feature-probes.py           # probe + update data/
    python3 scripts/feature-probes.py --check   # validate, exit non-zero on drift
    python3 scripts/feature-probes.py --stdout   # print to stdout
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import assert_never

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "v1-feature-matrix.json"
DOCS_PATH = REPO_ROOT / "docs" / "v1-feature-matrix.md"


class ProbeResult(Enum):
    PASS = "pass"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ABSENT = "absent"
    HAND_ASSESSED = "hand-assessed"


@dataclass(frozen=True)
class Probe:
    row_journey: str
    row_component: str
    row_surface: str
    probe_fn: str


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
        from agent_suite.cli import Command

        return any(c.value == command_value for c in Command)
    except Exception:
        return False


def _probe_deploy_cli() -> ProbeResult:
    if not _probe_module_exists("deploy.py"):
        return ProbeResult.ABSENT
    if not _probe_has_function("deploy", "run_deploy"):
        return ProbeResult.PARTIAL
    if not _probe_cli_command("deploy"):
        return ProbeResult.PARTIAL
    if not _probe_test_exists("test_deploy.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_onboard_harness() -> ProbeResult:
    if not _probe_module_exists("onboard.py"):
        return ProbeResult.ABSENT
    if not _probe_has_function("onboard", "run_onboard"):
        return ProbeResult.PARTIAL
    if not _probe_test_exists("test_onboard.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_identity_lifecycle() -> ProbeResult:
    if not _probe_module_exists("onboard.py"):
        return ProbeResult.ABSENT
    if not _probe_has_function("bootstrap", "run_bootstrap"):
        return ProbeResult.PARTIAL
    if not _probe_has_function("bootstrap", "_step_user_onboarding"):
        return ProbeResult.PARTIAL
    return ProbeResult.PARTIAL


def _probe_evidence_export() -> ProbeResult:
    if not _probe_module_exists("evidence.py"):
        return ProbeResult.ABSENT
    if not _probe_has_function("evidence", "run_evidence_export"):
        return ProbeResult.PARTIAL
    if not _probe_cli_command("export-evidence"):
        return ProbeResult.PARTIAL
    if not _probe_test_exists("test_evidence.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_backup_restore() -> ProbeResult:
    if not _probe_module_exists("backup.py"):
        return ProbeResult.ABSENT
    if not _probe_has_function("backup", "run_backup"):
        return ProbeResult.PARTIAL
    if not _probe_has_function("backup", "run_restore"):
        return ProbeResult.PARTIAL
    if not _probe_cli_command("backup"):
        return ProbeResult.PARTIAL
    if not _probe_cli_command("restore"):
        return ProbeResult.PARTIAL
    if not _probe_test_exists("test_backup.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_upgrade_rollback_forward() -> ProbeResult:
    if not _probe_has_function("upgrade", "run_upgrade"):
        return ProbeResult.ABSENT
    if not _probe_has_function("upgrade", "run_rollback"):
        return ProbeResult.PARTIAL
    if not _probe_has_function("upgrade", "run_forward_recovery"):
        return ProbeResult.PARTIAL
    if not _probe_test_exists("test_upgrade.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_doctor() -> ProbeResult:
    if not _probe_has_function("doctor", "aggregate"):
        return ProbeResult.ABSENT
    if not _probe_test_exists("test_doctor.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


def _probe_lock() -> ProbeResult:
    if not _probe_has_function("lock", "generate_lock"):
        return ProbeResult.ABSENT
    if not _probe_test_exists("test_lock.py"):
        return ProbeResult.PARTIAL
    return ProbeResult.PASS


PROBES: dict[tuple[str, str, str], str] = {
    ("GJ-1", "agent-suite", "profile-aware bootstrap / deploy CLI"): "_probe_deploy_cli",
    ("GJ-1", "agent-suite", "project onboarding and harness selection"): "_probe_onboard_harness",
    ("GJ-1", "agent-suite", "identity lifecycle / onboarding / offboarding"): "_probe_identity_lifecycle",
    ("GJ-8", "agent-suite", "suite-level evidence export orchestration"): "_probe_evidence_export",
    ("GJ-9", "agent-suite", "backup / restore / disaster recovery orchestration"): "_probe_backup_restore",
    ("GJ-9", "agent-suite", "upgrade / rollback / forward-recovery gates"): "_probe_upgrade_rollback_forward",
    ("GJ-9", "agent-suite", "profile-aware doctor aggregation"): "_probe_doctor",
    ("GJ-9", "agent-suite", "compatibility lock and drift check"): "_probe_lock",
}


def _run_probes(matrix_data: dict) -> dict:
    probed_count = 0
    hand_count = 0
    for row in matrix_data["rows"]:
        key = (row["journey"], row["component"], row["surface"])
        if key in PROBES:
            probe_fn_name = PROBES[key]
            probe_fn = globals()[probe_fn_name]
            result = probe_fn()
            match result:
                case ProbeResult.PASS | ProbeResult.PARTIAL | ProbeResult.BLOCKED | ProbeResult.ABSENT:
                    row["status"] = result.value
                case ProbeResult.HAND_ASSESSED:
                    pass
                case other:
                    assert_never(other)
            row["proof"] = f"probe: {probe_fn_name} -> {result.value}"
            probed_count += 1
        else:
            hand_count += 1

    if probed_count > 0 and hand_count == 0:
        matrix_data["status_source"] = "probe-emitted"
    elif probed_count > 0:
        matrix_data["status_source"] = "mixed-probe-and-hand"
    else:
        matrix_data["status_source"] = "hand-assessed"

    matrix_data["generated_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return matrix_data


def _matrix_to_markdown(matrix_data: dict) -> str:
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
            "This matrix is emitted by the WI-0.3 baseline run; do not hand-edit the status column."
        )
    elif matrix_data["status_source"] == "mixed-probe-and-hand":
        lines.append(
            "agent-suite-owned rows are probe-emitted; other-component rows are hand-assessed. "
            "Each repo must run its own probes for full coverage."
        )
    else:
        lines.append(
            "Status values are hand-assessed from cross-project review. "
            "The WI-0.3 baseline run will replace them with probe-emitted statuses."
        )
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
    parser = argparse.ArgumentParser(description="Run executable probes for the v1 feature matrix.")
    parser.add_argument("--data", type=Path, default=DATA_PATH, help="Path to the JSON matrix artifact")
    parser.add_argument("--docs", type=Path, default=DOCS_PATH, help="Path to write the Markdown matrix")
    parser.add_argument("--check", action="store_true", help="Validate and exit non-zero on errors")
    parser.add_argument("--stdout", action="store_true", help="Print Markdown to stdout")
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
        probed = _run_probes(matrix_data)
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

    matrix_data = _run_probes(matrix_data)

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
