"""Unit tests for the evidence export module."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Mapping

from agent_suite.evidence import (
    EvidenceExportResult,
    format_text,
    run_evidence_export,
)


def _completed(
    stdout: str = "", returncode: int = 0, stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


class StubRunner:
    def __init__(
        self, outputs: Mapping[tuple[str, ...], subprocess.CompletedProcess[str]]
    ) -> None:
        self._outputs = outputs
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, cmd: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
        self.calls.append(cmd)
        for prefix, out in self._outputs.items():
            if cmd[: len(prefix)] == prefix:
                return out
        return _completed(stdout="{}", returncode=0)


def _installed_all(_cli: str) -> bool:
    return True


def _installed_none(_cli: str) -> bool:
    return False


def _installed_except(*missing: str):
    def check(cli: str) -> bool:
        return cli not in missing
    return check


_REGISTA_DOCTOR_OK = _completed(
    stdout=json.dumps(
        {
            "component": "regista",
            "version": "1.0.0",
            "ok": True,
            "regista": {"reachable": True, "project": "test-project", "chain_ok": True},
            "checks": [],
        }
    )
)

_REGISTA_DOCTOR_NO_PROJECT = _completed(
    stdout=json.dumps(
        {
            "component": "regista",
            "version": "1.0.0",
            "ok": True,
            "regista": {"reachable": True, "chain_ok": True},
            "checks": [],
        }
    )
)

_REGISTA_BUNDLE_EXPORT_OK = _completed(
    stdout=json.dumps({"bundle_path": "/tmp/evidence/regista-test-project.bundle"})
)

_REGISTA_BUNDLE_VERIFY_OK = _completed(
    stdout=json.dumps({"ok": True})
)

_REGISTA_BUNDLE_VERIFY_FAIL = _completed(
    stdout=json.dumps({"ok": False})
)

_REGISTA_BUNDLE_EXPORT_FAIL = _completed(returncode=1, stderr="export error")

_CAIRN_EXPORT_OK = _completed(
    stdout=json.dumps({"export_path": "/tmp/evidence/cairn-test-project.bundle"})
)


# --- tests -------------------------------------------------------------------


def test_evidence_export_no_regista(tmp_path: Path) -> None:
    result = run_evidence_export(
        output_dir=tmp_path,
        installed=_installed_none,
        runner=StubRunner({}),
    )
    assert result.ok is False
    assert "discovery failed" in result.note


def test_evidence_export_no_projects(tmp_path: Path) -> None:
    runner = StubRunner({("regista", "doctor"): _REGISTA_DOCTOR_NO_PROJECT})
    result = run_evidence_export(
        output_dir=tmp_path,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert "no projects" in result.note
    assert result.projects == []


def test_evidence_export_success(tmp_path: Path) -> None:
    runner = StubRunner({
        ("regista", "doctor"): _REGISTA_DOCTOR_OK,
        ("regista", "bundle", "export"): _REGISTA_BUNDLE_EXPORT_OK,
        ("regista", "bundle", "verify"): _REGISTA_BUNDLE_VERIFY_OK,
        ("cairn", "export"): _CAIRN_EXPORT_OK,
    })
    result = run_evidence_export(
        output_dir=tmp_path,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is True
    assert len(result.projects) == 1
    proj = result.projects[0]
    assert proj.project == "test-project"
    assert proj.regista_bundle_path is not None
    assert proj.provenance_bundle_path is not None
    assert proj.verified is True
    assert result.manifest_path is not None
    assert Path(result.manifest_path).exists()


def test_evidence_export_regista_failure(tmp_path: Path) -> None:
    runner = StubRunner({
        ("regista", "doctor"): _REGISTA_DOCTOR_OK,
        ("regista", "bundle", "export"): _REGISTA_BUNDLE_EXPORT_FAIL,
        ("cairn", "export"): _CAIRN_EXPORT_OK,
    })
    result = run_evidence_export(
        output_dir=tmp_path,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    assert len(result.projects) == 1
    assert result.projects[0].regista_bundle_path is None


def test_evidence_export_verify_failure(tmp_path: Path) -> None:
    runner = StubRunner({
        ("regista", "doctor"): _REGISTA_DOCTOR_OK,
        ("regista", "bundle", "export"): _REGISTA_BUNDLE_EXPORT_OK,
        ("regista", "bundle", "verify"): _REGISTA_BUNDLE_VERIFY_FAIL,
        ("cairn", "export"): _CAIRN_EXPORT_OK,
    })
    result = run_evidence_export(
        output_dir=tmp_path,
        runner=runner,
        installed=_installed_all,
    )
    assert result.ok is False
    assert len(result.projects) == 1
    assert result.projects[0].verified is False


def test_evidence_export_cairn_not_installed(tmp_path: Path) -> None:
    runner = StubRunner({
        ("regista", "doctor"): _REGISTA_DOCTOR_OK,
        ("regista", "bundle", "export"): _REGISTA_BUNDLE_EXPORT_OK,
        ("regista", "bundle", "verify"): _REGISTA_BUNDLE_VERIFY_OK,
    })
    result = run_evidence_export(
        output_dir=tmp_path,
        runner=runner,
        installed=_installed_except("cairn"),
    )
    assert result.ok is True
    assert len(result.projects) == 1
    assert result.projects[0].provenance_bundle_path is None
    assert result.projects[0].verified is True


def test_evidence_format_text() -> None:
    result = EvidenceExportResult(
        ok=True,
        output_dir="/tmp/evidence",
        projects=[],
        manifest_path="/tmp/evidence/manifest.json",
        note="ok",
    )
    text = format_text(result)
    assert len(text) > 0
    assert "export-evidence" in text


def test_evidence_result_to_dict() -> None:
    result = EvidenceExportResult(
        ok=True,
        output_dir="/tmp/evidence",
        projects=[],
        manifest_path="/tmp/evidence/manifest.json",
        note="ok",
    )
    d = result.to_dict()
    assert "ok" in d
    assert "output_dir" in d
    assert "projects" in d
    assert "manifest_path" in d
    assert "note" in d
