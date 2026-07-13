"""Suite-level evidence export orchestration.

Implements Plan 009 WI-2.3 / GJ-8. Components export individually; this module
composes regista's audit-bundle export and agent-provenance's (cairn) provenance
export into one suite-level evidence export with a unified manifest.

The flow:
1. Discover projects via ``regista doctor --json``.
2. For each project, export the regista audit bundle.
3. For each project, export the cairn provenance bundle.
4. Verify each regista bundle offline.
5. Write a suite-level manifest listing all artifacts and verification status.

Design (AGENTS.md): thin orchestration — shells component CLIs, never
reimplements export or verification logic. Injectable runner + installed check
(same pattern as ``bootstrap.py``). ``assert_never`` over the status enum.
stdlib-only core.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol


class Runner(Protocol):
    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]: ...


class Installed(Protocol):
    def __call__(self, cli_name: str) -> bool: ...


def _default_runner(cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=300)


def _default_installed(cli_name: str) -> bool:
    return shutil.which(cli_name) is not None


_REGISTA_DOCTOR_CMD: tuple[str, ...] = ("regista", "doctor", "--json")


@dataclass
class ProjectExportResult:
    project: str
    regista_bundle_path: str | None = None
    provenance_bundle_path: str | None = None
    verified: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "regista_bundle_path": self.regista_bundle_path,
            "provenance_bundle_path": self.provenance_bundle_path,
            "verified": self.verified,
            "detail": self.detail,
        }


@dataclass
class EvidenceExportResult:
    ok: bool
    output_dir: str
    projects: list[ProjectExportResult] = field(default_factory=list)
    manifest_path: str | None = None
    note: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "output_dir": self.output_dir,
            "projects": [p.to_dict() for p in self.projects],
            "manifest_path": self.manifest_path,
            "note": self.note,
        }


def _discover_projects(
    *,
    runner: Runner,
    installed: Installed,
) -> list[str] | None:
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


def _export_regista_bundle(
    project: str,
    output_dir: Path,
    *,
    runner: Runner,
    installed: Installed,
) -> tuple[str | None, str]:
    if not installed("regista"):
        return None, "regista not installed"
    cmd: tuple[str, ...] = (
        "regista", "bundle", "export",
        "--project", project,
        "--output", str(output_dir),
        "--json",
    )
    try:
        result = runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, f"export failed: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return None, f"regista bundle export failed: {stderr or 'no detail'}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "regista bundle export emitted non-JSON stdout"
    if isinstance(data, dict):
        path = data.get("bundle_path") or data.get("output_path")
        if isinstance(path, str):
            return path, f"exported regista bundle for {project}"
    return None, "regista bundle export did not report a path"


def _export_provenance_bundle(
    project: str,
    output_dir: Path,
    *,
    runner: Runner,
    installed: Installed,
) -> tuple[str | None, str]:
    if not installed("cairn"):
        return None, "cairn not installed (skipped)"
    cmd: tuple[str, ...] = (
        "cairn", "export",
        "--project", project,
        "--output", str(output_dir),
        "--json",
    )
    try:
        result = runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return None, f"cairn export failed: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return None, f"cairn export failed: {stderr or 'no detail'}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, "cairn export emitted non-JSON stdout"
    if isinstance(data, dict):
        path = data.get("export_path") or data.get("output_path")
        if isinstance(path, str):
            return path, f"exported cairn bundle for {project}"
    return None, "cairn export did not report a path"


def _verify_regista_bundle(
    bundle_path: str,
    *,
    runner: Runner,
    installed: Installed,
) -> tuple[bool, str]:
    if not installed("regista"):
        return False, "regista not installed — cannot verify"
    cmd: tuple[str, ...] = ("regista", "bundle", "verify", bundle_path, "--json")
    try:
        result = runner(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, f"verify failed: {exc}"
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return False, f"verify failed: {stderr or 'non-zero exit'}"
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False, "verify emitted non-JSON stdout"
    if isinstance(data, dict):
        ok = data.get("ok")
        if isinstance(ok, bool):
            return ok, "verified" if ok else "verification failed"
    return False, "verify did not report ok field"


def run_evidence_export(
    *,
    output_dir: Path,
    projects: list[str] | None = None,
    dsn: str | None = None,
    runner: Runner = _default_runner,
    installed: Installed = _default_installed,
) -> EvidenceExportResult:
    """Compose component evidence exports into one suite-level export.

    Discovers projects (if not provided), exports regista audit bundles and
    cairn provenance bundles per project, verifies each regista bundle, and
    writes a suite-level manifest.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    if projects is None:
        discovered = _discover_projects(runner=runner, installed=installed)
        if discovered is None:
            return EvidenceExportResult(
                ok=False,
                output_dir=str(output_dir),
                note="project discovery failed — regista doctor did not report project info",
            )
        projects = discovered

    if not projects:
        return EvidenceExportResult(
            ok=True,
            output_dir=str(output_dir),
            projects=[],
            note="no projects to export",
        )

    all_ok = True
    results: list[ProjectExportResult] = []

    for project in projects:
        details: list[str] = []
        regista_path: str | None = None
        provenance_path: str | None = None
        verified = False

        regista_path, regista_msg = _export_regista_bundle(
            project, output_dir, runner=runner, installed=installed,
        )
        details.append(regista_msg)
        if regista_path is None:
            all_ok = False

        provenance_path, prov_msg = _export_provenance_bundle(
            project, output_dir, runner=runner, installed=installed,
        )
        details.append(prov_msg)

        if regista_path is not None:
            verified, verify_msg = _verify_regista_bundle(
                regista_path, runner=runner, installed=installed,
            )
            details.append(verify_msg)
            if not verified:
                all_ok = False
        else:
            details.append("skipped verify — no regista bundle")

        results.append(ProjectExportResult(
            project=project,
            regista_bundle_path=regista_path,
            provenance_bundle_path=provenance_path,
            verified=verified,
            detail="; ".join(details),
        ))

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "output_dir": str(output_dir),
        "projects": [r.to_dict() for r in results],
        "dsn_provided": dsn is not None,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return EvidenceExportResult(
        ok=all_ok,
        output_dir=str(output_dir),
        projects=results,
        manifest_path=str(manifest_path),
        note="ok" if all_ok else "one or more projects failed export or verification",
    )


def format_text(result: EvidenceExportResult) -> str:
    lines: list[str] = []
    lines.append("agent-suite export-evidence")
    lines.append(f"  output: {result.output_dir}")
    for p in result.projects:
        reg = p.regista_bundle_path or "—"
        prov = p.provenance_bundle_path or "—"
        vfy = "verified" if p.verified else "NOT verified"
        lines.append(f"  {p.project:<24} {vfy:<14} regista={reg} cairn={prov}")
    if result.manifest_path:
        lines.append(f"  manifest: {result.manifest_path}")
    lines.append("")
    lines.append(f"export-evidence: {'OK' if result.ok else 'NOT OK'}")
    if result.note:
        lines.append(f"  {result.note}")
    return "\n".join(lines)
