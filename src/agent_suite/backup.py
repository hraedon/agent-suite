"""Backup / restore / disaster-recovery orchestration.

Implements Plan 008 WI-4.1 / Plan 009 WI-4.2 / GJ-9. Composes pg_dump,
verify-restore, and evidence export into one operator command. The backup
captures the database snapshot, verifies it, exports signed evidence bundles,
and writes a manifest with integrity hash. The restore loads a backup and
verifies post-restore integrity.

Design (AGENTS.md): thin orchestration — ``pg_dump`` and ``pg_restore`` are
OS-level operations, not component logic. Injectable runner + installed check
(same pattern as ``bootstrap.py``). ``assert_never`` over every closed-set enum.
stdlib-only core. No secrets in manifests — DSNs are masked.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never

from agent_suite.evidence import run_evidence_export
from agent_suite.verify_restore import verify_restore


class BackupStep(Enum):
    PRE_DOCTOR = "pre_doctor"
    PG_DUMP = "pg_dump"
    VERIFY_DUMP = "verify_dump"
    EVIDENCE_EXPORT = "evidence_export"
    MANIFEST = "manifest"


class RestoreStep(Enum):
    PRE_DOCTOR = "pre_doctor"
    PG_RESTORE = "pg_restore"
    VERIFY_RESTORE = "verify_restore"
    POST_DOCTOR = "post_doctor"


class BackupStatus(Enum):
    PENDING = "pending"
    DONE = "done"
    SKIPPED = "skipped"
    FAILED = "failed"


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


_DOCTOR_CMD: tuple[str, ...] = ("agent-suite", "doctor", "--json")


def _split_dsn_password(dsn: str) -> tuple[str, str | None]:
    if "://" in dsn:
        scheme, rest = dsn.split("://", 1)
        if "@" in rest:
            creds, host_part = rest.split("@", 1)
            password: str | None = None
            if ":" in creds:
                _, _, pw = creds.partition(":")
                password = pw
            safe_dsn = f"{scheme}://{host_part}"
            return safe_dsn, password
    elif "=" in dsn and " " in dsn:
        parts = dsn.split()
        password = None
        safe_parts: list[str] = []
        for part in parts:
            if "=" in part:
                key, _, value = part.partition("=")
                if key in ("password", "pass", "pwd"):
                    password = value
                    safe_parts.append(f"{key}=")
                else:
                    safe_parts.append(part)
            else:
                safe_parts.append(part)
        return " ".join(safe_parts), password
    return dsn, None


def _mask_dsn(dsn: str) -> str:
    masked = dsn
    if "://" in masked:
        scheme, rest = masked.split("://", 1)
        if "@" in rest:
            _, host_part = rest.split("@", 1)
            masked = f"{scheme}://***:***@{host_part}"
    elif "=" in masked and " " in masked:
        parts = masked.split()
        masked_parts: list[str] = []
        for part in parts:
            if "=" in part:
                key, _, value = part.partition("=")
                if key in ("password", "pass", "pwd"):
                    masked_parts.append(f"{key}=***")
                else:
                    masked_parts.append(part)
            else:
                masked_parts.append(part)
        masked = " ".join(masked_parts)
    return masked


def _sha256_file(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def _run_doctor_snapshot(
    *,
    runner: Runner,
) -> tuple[str | None, str]:
    try:
        result = runner(_DOCTOR_CMD)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, f"doctor failed: {exc}"
    if result.returncode != 0:
        return None, f"doctor exit {result.returncode}: {result.stderr.strip()}"
    return result.stdout, "doctor ok"


@dataclass
class BackupStepResult:
    step: BackupStep
    status: BackupStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class BackupResult:
    ok: bool
    dry_run: bool
    backup_dir: str
    steps: list[BackupStepResult] = field(default_factory=list)
    manifest_path: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "backup_dir": self.backup_dir,
            "steps": [s.to_dict() for s in self.steps],
            "manifest_path": self.manifest_path,
            "note": self.note,
        }


@dataclass
class RestoreStepResult:
    step: RestoreStep
    status: BackupStatus
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "step": self.step.value,
            "status": self.status.value,
            "detail": self.detail,
        }


@dataclass
class RestoreResult:
    ok: bool
    dry_run: bool
    backup_dir: str
    steps: list[RestoreStepResult] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "dry_run": self.dry_run,
            "backup_dir": self.backup_dir,
            "steps": [s.to_dict() for s in self.steps],
            "note": self.note,
        }


def _is_backup_terminal(status: BackupStatus) -> bool:
    match status:
        case BackupStatus.FAILED:
            return True
        case BackupStatus.DONE | BackupStatus.SKIPPED | BackupStatus.PENDING:
            return False
        case other:
            assert_never(other)


def _compute_backup_ok(steps: list[BackupStepResult]) -> bool:
    for s in steps:
        match s.status:
            case BackupStatus.FAILED:
                return False
            case BackupStatus.DONE | BackupStatus.SKIPPED | BackupStatus.PENDING:
                continue
            case other:
                assert_never(other)
    return True


def run_backup(
    *,
    backup_dir: Path,
    dsn: str | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> BackupResult:
    """Run a suite-level backup: doctor → pg_dump → verify → evidence → manifest.

    Each step is gated on the prior step's success. ``dry_run`` prints the plan
    without acting. The backup manifest contains no secrets — DSNs are masked.
    """
    resolved_dsn = dsn or os.environ.get("REGISTA_DSN", "")
    backup_dir.mkdir(parents=True, exist_ok=True)
    steps: list[BackupStepResult] = []

    snapshot, snap_detail = _run_doctor_snapshot(runner=runner)
    if snapshot is None:
        steps.append(BackupStepResult(BackupStep.PRE_DOCTOR, BackupStatus.FAILED, snap_detail))
        return BackupResult(
            ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
            note="pre-backup doctor failed",
        )
    steps.append(BackupStepResult(BackupStep.PRE_DOCTOR, BackupStatus.DONE, snap_detail))

    dump_path = backup_dir / "database.dump"
    if dry_run:
        steps.append(BackupStepResult(
            BackupStep.PG_DUMP, BackupStatus.PENDING,
            f"would run pg_dump to {dump_path}",
        ))
    else:
        if not resolved_dsn:
            steps.append(BackupStepResult(
                BackupStep.PG_DUMP, BackupStatus.FAILED,
                "no DSN configured — set REGISTA_DSN or pass --dsn",
            ))
            return BackupResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="no DSN for pg_dump",
            )
        if not installed("pg_dump"):
            steps.append(BackupStepResult(
                BackupStep.PG_DUMP, BackupStatus.FAILED,
                "pg_dump not found — install PostgreSQL client tools",
            ))
            return BackupResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="pg_dump not available",
            )
        safe_dsn, pg_password = _split_dsn_password(resolved_dsn)
        if pg_password:
            os.environ["PGPASSWORD"] = pg_password
        dump_cmd: tuple[str, ...] = (
            "pg_dump", safe_dsn, "--format=custom", f"--file={dump_path}",
        )
        try:
            result = runner(dump_cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            steps.append(BackupStepResult(
                BackupStep.PG_DUMP, BackupStatus.FAILED, f"pg_dump failed: {exc}",
            ))
            return BackupResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="pg_dump execution error",
            )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            steps.append(BackupStepResult(
                BackupStep.PG_DUMP, BackupStatus.FAILED,
                f"pg_dump failed: {stderr or 'no detail'}",
            ))
            return BackupResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="pg_dump failed",
            )
        steps.append(BackupStepResult(
            BackupStep.PG_DUMP, BackupStatus.DONE, f"dumped to {dump_path}",
        ))

    if dry_run:
        steps.append(BackupStepResult(
            BackupStep.VERIFY_DUMP, BackupStatus.PENDING,
            "would verify dump via verify-restore",
        ))
    else:
        vr = verify_restore(dsn=resolved_dsn, runner=runner, installed=installed)
        if vr.ok:
            steps.append(BackupStepResult(
                BackupStep.VERIFY_DUMP, BackupStatus.DONE,
                f"verified: {len(vr.projects)} projects ok",
            ))
        else:
            steps.append(BackupStepResult(
                BackupStep.VERIFY_DUMP, BackupStatus.FAILED,
                f"verify-restore failed: {vr.note}",
            ))
            return BackupResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="post-dump verification failed",
            )

    if dry_run:
        steps.append(BackupStepResult(
            BackupStep.EVIDENCE_EXPORT, BackupStatus.PENDING,
            f"would export evidence bundles to {backup_dir}",
        ))
    else:
        ev = run_evidence_export(
            output_dir=backup_dir, dsn=resolved_dsn,
            runner=runner, installed=installed,
        )
        if ev.ok:
            steps.append(BackupStepResult(
                BackupStep.EVIDENCE_EXPORT, BackupStatus.DONE,
                f"evidence exported: {len(ev.projects)} projects, manifest={ev.manifest_path}",
            ))
        else:
            steps.append(BackupStepResult(
                BackupStep.EVIDENCE_EXPORT, BackupStatus.FAILED,
                f"evidence export failed: {ev.note}",
            ))

    if dry_run:
        steps.append(BackupStepResult(
            BackupStep.MANIFEST, BackupStatus.PENDING,
            "would write backup manifest",
        ))
    else:
        dump_hash = _sha256_file(dump_path) if dump_path.exists() else None
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "backup_dir": str(backup_dir),
            "dsn_masked": _mask_dsn(resolved_dsn) if resolved_dsn else None,
            "database_snapshot": str(dump_path) if dump_path.exists() else None,
            "database_snapshot_sha256": dump_hash,
            "pre_doctor_snapshot": snapshot,
            "steps": [s.to_dict() for s in steps],
        }
        manifest_path = backup_dir / "backup-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        steps.append(BackupStepResult(
            BackupStep.MANIFEST, BackupStatus.DONE, f"manifest at {manifest_path}",
        ))

    ok = _compute_backup_ok(steps)
    return BackupResult(
        ok=ok, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
        manifest_path=str(manifest_path) if not dry_run else None,
        note="ok" if ok else "backup completed with errors",
    )


def run_restore(
    *,
    backup_dir: Path,
    dsn: str | None = None,
    dry_run: bool = False,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> RestoreResult:
    """Restore from a backup directory: doctor → pg_restore → verify → doctor.

    Each step is gated on the prior step's success. ``dry_run`` prints the plan
    without acting.
    """
    resolved_dsn = dsn or os.environ.get("REGISTA_DSN", "")
    steps: list[RestoreStepResult] = []

    pre_snapshot, pre_detail = _run_doctor_snapshot(runner=runner)
    if pre_snapshot is None:
        steps.append(RestoreStepResult(
            RestoreStep.PRE_DOCTOR, BackupStatus.FAILED, pre_detail,
        ))
        return RestoreResult(
            ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
            note="pre-restore doctor failed",
        )
    steps.append(RestoreStepResult(
        RestoreStep.PRE_DOCTOR, BackupStatus.DONE, pre_detail,
    ))

    dump_path = backup_dir / "database.dump"
    if dry_run:
        steps.append(RestoreStepResult(
            RestoreStep.PG_RESTORE, BackupStatus.PENDING,
            f"would run pg_restore from {dump_path}",
        ))
    else:
        if not resolved_dsn:
            steps.append(RestoreStepResult(
                RestoreStep.PG_RESTORE, BackupStatus.FAILED,
                "no DSN configured — set REGISTA_DSN or pass --dsn",
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="no DSN for pg_restore",
            )
        if not dump_path.exists():
            steps.append(RestoreStepResult(
                RestoreStep.PG_RESTORE, BackupStatus.FAILED,
                f"dump file not found: {dump_path}",
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="dump file missing",
            )
        if not installed("pg_restore"):
            steps.append(RestoreStepResult(
                RestoreStep.PG_RESTORE, BackupStatus.FAILED,
                "pg_restore not found — install PostgreSQL client tools",
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="pg_restore not available",
            )
        safe_dsn_r, pg_password_r = _split_dsn_password(resolved_dsn)
        if pg_password_r:
            os.environ["PGPASSWORD"] = pg_password_r
        restore_cmd: tuple[str, ...] = (
            "pg_restore", "--dbname", safe_dsn_r,
            "--clean", "--if-exists", str(dump_path),
        )
        try:
            result = runner(restore_cmd)
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            steps.append(RestoreStepResult(
                RestoreStep.PG_RESTORE, BackupStatus.FAILED, f"pg_restore failed: {exc}",
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="pg_restore execution error",
            )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if "already exists" in stderr.lower() or "no matching" in stderr.lower():
                steps.append(RestoreStepResult(
                    RestoreStep.PG_RESTORE, BackupStatus.DONE,
                    f"restored (with warnings): {stderr[:200]}",
                ))
            else:
                steps.append(RestoreStepResult(
                    RestoreStep.PG_RESTORE, BackupStatus.FAILED,
                    f"pg_restore failed: {stderr or 'no detail'}",
                ))
                return RestoreResult(
                    ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                    note="pg_restore failed",
                )
        else:
            steps.append(RestoreStepResult(
                RestoreStep.PG_RESTORE, BackupStatus.DONE,
                f"restored from {dump_path}",
            ))

    if dry_run:
        steps.append(RestoreStepResult(
            RestoreStep.VERIFY_RESTORE, BackupStatus.PENDING,
            "would verify restore via verify-restore",
        ))
    else:
        vr = verify_restore(dsn=resolved_dsn, runner=runner, installed=installed)
        if vr.ok:
            steps.append(RestoreStepResult(
                RestoreStep.VERIFY_RESTORE, BackupStatus.DONE,
                f"verified: {len(vr.projects)} projects ok",
            ))
        else:
            steps.append(RestoreStepResult(
                RestoreStep.VERIFY_RESTORE, BackupStatus.FAILED,
                f"verify-restore failed: {vr.note}",
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="post-restore verification failed",
            )

    if dry_run:
        steps.append(RestoreStepResult(
            RestoreStep.POST_DOCTOR, BackupStatus.PENDING,
            "would run post-restore doctor",
        ))
    else:
        post_snapshot, post_detail = _run_doctor_snapshot(runner=runner)
        if post_snapshot is None:
            steps.append(RestoreStepResult(
                RestoreStep.POST_DOCTOR, BackupStatus.FAILED, post_detail,
            ))
            return RestoreResult(
                ok=False, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
                note="post-restore doctor failed",
            )
        steps.append(RestoreStepResult(
            RestoreStep.POST_DOCTOR, BackupStatus.DONE, post_detail,
        ))

    ok = True
    for s in steps:
        match s.status:
            case BackupStatus.FAILED:
                ok = False
                break
            case BackupStatus.DONE | BackupStatus.SKIPPED | BackupStatus.PENDING:
                continue
            case other:
                assert_never(other)

    return RestoreResult(
        ok=ok, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
        note="ok" if ok else "restore completed with errors",
    )


def format_backup_text(result: BackupResult) -> str:
    lines: list[str] = []
    if result.dry_run:
        lines.append("agent-suite backup --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite backup")
    lines.append(f"  backup dir: {result.backup_dir}")
    lines.append("")
    for s in result.steps:
        lines.append(f"  {s.step.value:<18} {s.status.value:<14} {s.detail}")
    lines.append("")
    lines.append(f"backup: {'OK' if result.ok else 'NOT OK'}")
    if result.note:
        lines.append(f"  {result.note}")
    return "\n".join(lines)


def format_restore_text(result: RestoreResult) -> str:
    lines: list[str] = []
    if result.dry_run:
        lines.append("agent-suite restore --dry-run (plan, no actions taken)")
    else:
        lines.append("agent-suite restore")
    lines.append(f"  backup dir: {result.backup_dir}")
    lines.append("")
    for s in result.steps:
        lines.append(f"  {s.step.value:<18} {s.status.value:<14} {s.detail}")
    lines.append("")
    lines.append(f"restore: {'OK' if result.ok else 'NOT OK'}")
    if result.note:
        lines.append(f"  {result.note}")
    return "\n".join(lines)
