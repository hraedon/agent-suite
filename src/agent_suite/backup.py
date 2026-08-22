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

WI-054 — a non-zero ``pg_restore`` is never DONE
------------------------------------------------

This module used to downgrade a non-zero ``pg_restore`` to ``DONE`` when its
stderr contained ``"already exists"`` or ``"no matching"``. That is the same
string-scanning-instead-of-classifying defect Lane H removed from the
provisioning path (WI-040/WI-051) — a step that did not succeed being read as
success — except ``pg_restore`` has no JSON envelope to classify on, so the fix
differs in kind.

Three things make the old tolerance indefensible rather than merely ugly:

* The restore runs ``--clean --if-exists``, so ``DROP … IF EXISTS`` precedes
  every ``CREATE``. Neither tolerated condition is one this command should
  produce: ``already exists`` comes from restoring *without* ``--clean``, and
  ``no matching`` comes from ``-t``/``-n`` filters this command never passes. The
  tolerance covered situations that, if they occurred, meant something the
  operator needed to know about.
* The match was on prose. ``already exists`` appears in the message for a
  *table* that could not be dropped as readily as for a benign duplicate index,
  and a restore that failed to load a single row can say it.
* ``pg_restore`` is invoked without ``--exit-on-error``, so it continues past
  failures and exits 1 having *skipped objects*. Its exit code therefore already
  carries exactly the fact worth reporting: at least one object did not restore.

**The decision:** classify on the exit code, which is the only structured signal
``pg_restore`` emits, and let ``verify_restore`` be the authority on whether the
restored store is usable. A non-zero exit is :attr:`BackupStatus.PARTIAL` —
neither DONE nor FAILED — carrying the count ``pg_restore`` itself reports
(``errors ignored on restore: N``) when it emits one. The step no longer returns
early, so ``verify_restore`` always runs and the operator gets the state of the
store they are now sitting on rather than only the fact that ``pg_restore``
complained. ``PARTIAL`` makes the overall result NOT OK, so nothing fails open:
``verify_restore`` passing cannot green a restore that skipped objects (it
replays the chain, and a chain can verify while an unrelated table is missing),
and it failing tells the operator the damage is real.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Protocol, assert_never
from urllib.parse import unquote, urlsplit, urlunsplit

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
    #: The step ran and did not do all of it (WI-054). Distinct from FAILED
    #: because the pipeline continues — the following verification is what tells
    #: the operator whether the shortfall matters — and distinct from DONE
    #: because it is not success. It makes the overall result NOT OK.
    PARTIAL = "partial"


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


_DOCTOR_CMD: tuple[str, ...] = ("agent-suite", "doctor", "--json")

#: ``pg_restore``'s own summary of what it skipped. This is the closest thing it
#: has to structured output: a count it computed, not prose describing one
#: condition. It is read to *quantify* a failure already established by the exit
#: code — never to excuse one.
_ERRORS_IGNORED_RE = re.compile(r"errors ignored on restore:\s*(\d+)", re.IGNORECASE)

#: Named so the step detail, the docs and the tests cannot drift.
RESTORE_PARTIAL_REMEDY = (
    "pg_restore skipped at least one object; verify_restore below reports whether "
    "the restored store is usable, and `pg_restore --exit-on-error` reproduces the "
    "first failure in isolation"
)


@dataclass(frozen=True)
class PgRestoreVerdict:
    """What ``pg_restore``'s exit code says about the restore.

    ``pg_restore`` emits no JSON, so the exit code is the whole structured
    signal: 0 means every archive entry was applied, and non-zero means it
    continued past at least one failure and skipped objects (it is not invoked
    with ``--exit-on-error``). ``errors_ignored`` is the count ``pg_restore``
    itself reports, when it reports one.
    """

    status: BackupStatus
    errors_ignored: int | None
    detail: str


def classify_pg_restore(
    *, returncode: int, stderr: str, dump_path: str
) -> PgRestoreVerdict:
    """Judge one ``pg_restore`` run from its exit code (WI-054).

    Nothing here reads the child's prose to decide the outcome. The previous
    implementation returned ``DONE`` whenever stderr contained ``"already
    exists"`` or ``"no matching"``, which meant a restore that dropped objects on
    the floor reported success as long as it phrased its complaint the right way.

    A non-zero exit is :attr:`BackupStatus.PARTIAL`: something did not restore.
    Whether that matters is ``verify_restore``'s question, not this function's,
    and it is answered in the same report.
    """
    if returncode == 0:
        return PgRestoreVerdict(
            status=BackupStatus.DONE,
            errors_ignored=0,
            detail=f"restored from {dump_path}",
        )
    match = _ERRORS_IGNORED_RE.search(stderr)
    errors_ignored = int(match.group(1)) if match else None
    counted = (
        f"{errors_ignored} object(s) skipped"
        if errors_ignored is not None
        else "object count not reported by pg_restore"
    )
    return PgRestoreVerdict(
        status=BackupStatus.PARTIAL,
        errors_ignored=errors_ignored,
        detail=(
            f"pg_restore exited {returncode} — {counted}; {RESTORE_PARTIAL_REMEDY}. "
            f"pg_restore said: {stderr.strip()[:300] or 'no detail'}"
        ),
    )


def _split_dsn_password(dsn: str) -> tuple[str, str | None]:
    if "://" in dsn:
        parsed = urlsplit(dsn)
        if parsed.password is not None:
            hostname = parsed.hostname or ""
            if ":" in hostname:
                hostname = f"[{hostname}]"
            if parsed.port is not None:
                hostname = f"{hostname}:{parsed.port}"
            netloc = hostname
            if parsed.username is not None:
                netloc = f"{parsed.username}@{netloc}"
            safe_dsn = urlunsplit(
                (parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)
            )
            return safe_dsn, unquote(parsed.password)
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
                key, _, _value = part.partition("=")
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
    """Whether this status stops the pipeline.

    ``PARTIAL`` does **not** (WI-054): the point of letting the pipeline run on
    is that the following verification is what tells the operator whether the
    shortfall matters. It still makes the overall result NOT OK — see
    :func:`_compute_backup_ok`.
    """
    match status:
        case BackupStatus.FAILED:
            return True
        case (
            BackupStatus.DONE
            | BackupStatus.SKIPPED
            | BackupStatus.PENDING
            | BackupStatus.PARTIAL
        ):
            return False
        case other:
            assert_never(other)


def _compute_backup_ok(steps: list[BackupStepResult]) -> bool:
    for s in steps:
        match s.status:
            case BackupStatus.FAILED | BackupStatus.PARTIAL:
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
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
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
        # WI-054: the exit code decides, and a non-zero exit is PARTIAL rather
        # than DONE or FAILED. The step deliberately does *not* return early:
        # verify_restore is the authority on the state of the restored store, and
        # an operator staring at a half-restored database needs its verdict more
        # than anyone. PARTIAL still makes the overall result NOT OK.
        verdict = classify_pg_restore(
            returncode=result.returncode,
            stderr=result.stderr,
            dump_path=str(dump_path),
        )
        steps.append(RestoreStepResult(
            RestoreStep.PG_RESTORE, verdict.status, verdict.detail,
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
    partial = False
    for s in steps:
        match s.status:
            case BackupStatus.FAILED:
                ok = False
                break
            case BackupStatus.PARTIAL:
                # WI-054: not a stop, but never a pass. A restore that skipped
                # objects is not a restore, whatever verify_restore made of the
                # chain that survived.
                ok = False
                partial = True
                continue
            case BackupStatus.DONE | BackupStatus.SKIPPED | BackupStatus.PENDING:
                continue
            case other:
                assert_never(other)

    if ok:
        note = "ok"
    elif partial:
        note = "restore incomplete — pg_restore skipped objects; see verify_restore above"
    else:
        note = "restore completed with errors"
    return RestoreResult(
        ok=ok, dry_run=dry_run, backup_dir=str(backup_dir), steps=steps,
        note=note,
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
