"""Verify a restored store is cryptographically intact and unaltered.

Implements Plan 001 WI-4.2. ``agent-suite verify-restore`` runs ``regista
replay`` across every project's event chain and reports whether the restored
Postgres store is cryptographically intact — turning "we restored a backup"
into "we restored a *provably unaltered* backup."

Design (AGENTS.md): thin orchestration — shells regista's own CLI, never
reimplements replay logic. Injectable runner + installed check (same pattern
as ``doctor.py``) so tests drive verification against stubbed commands with
no real binaries or live infra. ``assert_never`` over the status enum so a
newly added status can't slip through ungated. stdlib-only core.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, assert_never


class ProjectVerifyStatus(Enum):
    """The closed set of per-project verification outcomes.

    ``assert_never`` is used over this enum so a newly added status can't be
    silently unhandled in the aggregation or formatting logic.
    """

    VERIFIED = "verified"
    DRIFT_DETECTED = "drift"
    WARNINGS_DETECTED = "warnings"
    UNREACHABLE = "unreachable"
    ERROR = "error"


class Runner(Protocol):
    """Run a command and return the completed process (matches doctor.Runner)."""

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    """Detect whether a component's CLI is installed (matches shutil.which)."""

    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


@dataclass
class ProjectVerifyResult:
    """One project's replay verification outcome."""

    project: str
    status: ProjectVerifyStatus
    replayed_ok: int = 0
    replayed_drift: int = 0
    halted: int = 0
    warnings: int = 0
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "status": self.status.value,
            "replayed_ok": self.replayed_ok,
            "replayed_drift": self.replayed_drift,
            "halted": self.halted,
            "warnings": self.warnings,
            "detail": self.detail,
        }


@dataclass
class VerifyRestoreResult:
    """The outcome of verifying a restored store across all projects.

    ``ok`` is True only if every project verified with zero drift, zero
    halted, and zero warnings. Warnings indicate chain-link tampering
    (e.g. a forged ``prev_event_hash``) that regista's replay surfaces
    without halting — a restored store carrying such warnings is not
    cryptographically intact.
    """

    ok: bool
    projects: list[ProjectVerifyResult]
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "projects": [p.to_dict() for p in self.projects],
            "note": self.note,
        }


_REGISTA_DOCTOR_CMD: tuple[str, ...] = ("regista", "doctor", "--json")


def _discover_projects(
    *,
    runner: Runner,
    installed: Installed,
) -> list[str] | None:
    """Discover project slugs via ``regista doctor --json``.

    regista's doctor reports the configured project(s) in its ``regista``
    sub-object. Returns ``None`` if discovery fails (regista doctor errors,
    times out, or emits unparseable output) so the caller can distinguish
    "discovery failed" from "no projects configured." Returns an empty list
    if discovery succeeds but no projects are reported. Never raises.
    """
    if not installed("regista"):
        return None

    try:
        result = runner(_REGISTA_DOCTOR_CMD)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None

    if result.returncode != 0:
        return None

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    regista_info = data.get("regista")
    if not isinstance(regista_info, dict):
        return None

    project = regista_info.get("project")
    if isinstance(project, str) and project:
        return [project]
    if isinstance(project, list):
        return [str(p) for p in project if isinstance(p, str) and p]

    return []


def _replay_cmd(dsn: str, project: str) -> tuple[str, ...]:
    return ("regista", "replay", "--dsn", dsn, "--project", project, "--json")


def _verify_one(
    project: str,
    *,
    dsn: str,
    runner: Runner,
) -> ProjectVerifyResult:
    """Shell ``regista replay`` for one project and parse the result.

    Never raises — a command failure, timeout, or malformed output is a named
    status (UNREACHABLE or ERROR), not a traceback.
    """
    cmd = _replay_cmd(dsn, project)

    try:
        result = runner(cmd)
    except FileNotFoundError:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.UNREACHABLE,
            detail="regista not found at run time",
        )
    except subprocess.TimeoutExpired:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.UNREACHABLE,
            detail="regista replay timed out",
        )
    except OSError as exc:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.UNREACHABLE,
            detail=f"regista replay could not run: {exc}",
        )

    if result.returncode != 0:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.UNREACHABLE,
            detail=(
                f"regista replay exit {result.returncode}: "
                f"{result.stderr.strip() or 'no stderr'}"
            ),
        )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.ERROR,
            detail="regista replay emitted non-JSON stdout",
        )

    if not isinstance(data, dict):
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.ERROR,
            detail=(
                f"regista replay emitted JSON but not a dict "
                f"(got {type(data).__name__})"
            ),
        )

    try:
        replayed_ok = int(data.get("replayed_ok", 0))
        replayed_drift = int(data.get("replayed_drift", 0))
        halted = int(data.get("halted", 0))
        warnings = int(data.get("warnings", 0))
    except (TypeError, ValueError):
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.ERROR,
            detail="regista replay emitted malformed replay counts",
        )

    if replayed_drift > 0 or halted > 0:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.DRIFT_DETECTED,
            replayed_ok=replayed_ok,
            replayed_drift=replayed_drift,
            halted=halted,
            warnings=warnings,
            detail=f"drift detected: {replayed_drift} drift, {halted} halted",
        )

    if warnings > 0:
        return ProjectVerifyResult(
            project=project,
            status=ProjectVerifyStatus.WARNINGS_DETECTED,
            replayed_ok=replayed_ok,
            replayed_drift=replayed_drift,
            halted=halted,
            warnings=warnings,
            detail=f"warnings detected: {warnings} warnings (possible chain-link tampering)",
        )

    return ProjectVerifyResult(
        project=project,
        status=ProjectVerifyStatus.VERIFIED,
        replayed_ok=replayed_ok,
        replayed_drift=replayed_drift,
        halted=halted,
        warnings=warnings,
        detail=f"verified: {replayed_ok} events replayed ok",
    )


def _compute_ok(results: list[ProjectVerifyResult]) -> bool:
    """True only if every project is VERIFIED.

    The ``assert_never`` in the default arm keeps the status enum closed — a
    newly added status can't slip through ungated.
    """
    for r in results:
        match r.status:
            case ProjectVerifyStatus.VERIFIED:
                continue
            case (
                ProjectVerifyStatus.DRIFT_DETECTED
                | ProjectVerifyStatus.WARNINGS_DETECTED
                | ProjectVerifyStatus.UNREACHABLE
                | ProjectVerifyStatus.ERROR
            ):
                return False
            case other:
                assert_never(other)
    return True


def verify_restore(
    *,
    dsn: str,
    projects: list[str] | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> VerifyRestoreResult:
    """Run ``regista replay`` across every project and report integrity.

    If ``projects`` is None, discovers project slugs via ``regista doctor
    --json``. Both ``runner`` and ``installed`` are injectable so tests drive
    verification against stubbed commands with no real binaries or live infra.
    """
    if not installed("regista"):
        return VerifyRestoreResult(
            ok=False,
            projects=[],
            note=(
                "regista is not installed — "
                "install regista to verify the restored store"
            ),
        )

    if projects is None:
        discovered = _discover_projects(runner=runner, installed=installed)
        if discovered is None:
            return VerifyRestoreResult(
                ok=False,
                projects=[],
                note=(
                    "project discovery failed — regista doctor did not report "
                    "project info; pass --projects explicitly or check regista health"
                ),
            )
        projects = discovered

    if not projects:
        return VerifyRestoreResult(
            ok=True,
            projects=[],
            note=(
                "no projects to verify — "
                "pass --project explicitly or ensure regista reports project info"
            ),
        )

    results = [_verify_one(p, dsn=dsn, runner=runner) for p in projects]

    ok = _compute_ok(results)
    return VerifyRestoreResult(
        ok=ok,
        projects=results,
        note="ok" if ok else "one or more projects failed verification",
    )


def format_text(result: VerifyRestoreResult) -> str:
    """Human-readable summary for ``verify-restore`` without --json."""
    lines: list[str] = []
    for p in result.projects:
        match p.status:
            case ProjectVerifyStatus.VERIFIED:
                lines.append(
                    f"  {p.project:<24} verified     "
                    f"{p.replayed_ok} ok, {p.replayed_drift} drift, {p.halted} halted"
                )
            case ProjectVerifyStatus.DRIFT_DETECTED:
                lines.append(
                    f"  {p.project:<24} drift        "
                    f"{p.replayed_ok} ok, {p.replayed_drift} drift, {p.halted} halted"
                )
            case ProjectVerifyStatus.WARNINGS_DETECTED:
                lines.append(
                    f"  {p.project:<24} warnings     "
                    f"{p.replayed_ok} ok, {p.replayed_drift} drift, "
                    f"{p.halted} halted, {p.warnings} warnings"
                )
            case ProjectVerifyStatus.UNREACHABLE:
                lines.append(f"  {p.project:<24} unreachable   {p.detail}")
            case ProjectVerifyStatus.ERROR:
                lines.append(f"  {p.project:<24} error         {p.detail}")
            case other:
                assert_never(other)
    lines.append("")
    lines.append(f"verify-restore: {'OK' if result.ok else 'NOT OK'}")
    if result.note:
        lines.append(f"  {result.note}")
    return "\n".join(lines)
