"""Tests for the plan-index script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "plan-index.py"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("plan_index", SCRIPT_PATH)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["plan_index"] = module
    spec.loader.exec_module(module)
    return module


plan_index = _load_script()


def _write_plan(tmp_path: Path, filename: str, content: str) -> Path:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)
    path = plans_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_standard_plan_file(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        "001-test-plan.md",
        "# Plan 001 — Test Plan\n\n**Status:** Complete 2026-07-10.\n"
        "**Depends:** 002, 003\n**Supersedes:** old-plan.md\n",
    )
    entry = plan_index.parse_plan_file(path)
    assert entry is not None
    assert entry.number == 1
    assert entry.title == "Plan 001 — Test Plan"
    assert entry.status == "Complete"
    assert entry.filepath == str(path)
    assert entry.dependencies == ["002", "003"]
    assert entry.supersedes == "old-plan.md"


def test_parse_plan_without_status_defaults_to_unknown(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        "002-no-status.md",
        "# Plan 002 — No Status\n\nSome content without a status line.\n",
    )
    entry = plan_index.parse_plan_file(path)
    assert entry is not None
    assert entry.status == "unknown"


def test_detect_duplicate_plan_numbers(tmp_path: Path) -> None:
    _write_plan(tmp_path, "001-first.md", "# First\n\n**Status:** Proposed\n")
    _write_plan(tmp_path, "001-second.md", "# Second\n\n**Status:** Proposed\n")
    entries, _warnings = plan_index.scan_repo(tmp_path)
    issues = plan_index.validate_entries(entries)
    errors = [i for i in issues if i.kind == "error"]
    assert len(errors) == 1
    assert "duplicate plan number 1" in errors[0].message


def test_detect_status_drift(tmp_path: Path) -> None:
    path = _write_plan(
        tmp_path,
        "001-drift.md",
        "# Plan 001 — Drift\n\n**Status:** Proposed\n\n"
        "## Implementation\n\nThis plan is Complete.\n",
    )
    entry = plan_index.parse_plan_file(path)
    assert entry is not None
    assert entry.status == "Proposed"
    issues = plan_index.validate_entries([entry])
    warnings = [i for i in issues if i.kind == "warning"]
    assert len(warnings) == 1
    assert "body claims Complete/Implemented but Status line says 'Proposed'" in warnings[0].message


def test_check_exit_code_clean(tmp_path: Path) -> None:
    _write_plan(tmp_path, "001-clean.md", "# Clean\n\n**Status:** Proposed\n")
    assert plan_index.main(["--repo", str(tmp_path), "--check"]) == 0


def test_check_exit_code_on_duplicate(tmp_path: Path) -> None:
    _write_plan(tmp_path, "001-first.md", "# First\n\n**Status:** Proposed\n")
    _write_plan(tmp_path, "001-second.md", "# Second\n\n**Status:** Proposed\n")
    assert plan_index.main(["--repo", str(tmp_path), "--check"]) == 1


def test_check_exit_code_on_drift(tmp_path: Path) -> None:
    _write_plan(
        tmp_path,
        "001-drift.md",
        "# Drift\n\n**Status:** Proposed\n\nThis plan is Implemented.\n",
    )
    assert plan_index.main(["--repo", str(tmp_path), "--check"]) == 1


def test_multiple_repos(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo-a"
    repo_b = tmp_path / "repo-b"
    _write_plan(repo_a, "001-a.md", "# A\n\n**Status:** Proposed\n")
    _write_plan(repo_b, "001-b.md", "# B\n\n**Status:** Complete\n")
    assert plan_index.main(["--repo", str(repo_a), "--repo", str(repo_b), "--check"]) == 0
    entries, _warnings = plan_index.scan_repo(repo_a)
    entries_b, _warnings_b = plan_index.scan_repo(repo_b)
    assert len(entries) == 1
    assert entries[0].number == 1
    assert len(entries_b) == 1
    assert entries_b[0].number == 1


def test_main_outputs_json(tmp_path: Path) -> None:
    _write_plan(tmp_path, "001-json.md", "# JSON\n\n**Status:** Proposed\n")
    assert plan_index.main(["--repo", str(tmp_path), "--json"]) == 0


def test_main_outputs_table(tmp_path: Path) -> None:
    _write_plan(tmp_path, "001-table.md", "# Table\n\n**Status:** Proposed\n")
    assert plan_index.main(["--repo", str(tmp_path)]) == 0


def test_empty_plans_directory(tmp_path: Path) -> None:
    plans_dir = tmp_path / "plans"
    plans_dir.mkdir()
    entries, warnings = plan_index.scan_repo(tmp_path)
    assert entries == []
    assert warnings == []


def test_skip_non_numeric_markdown_file(tmp_path: Path) -> None:
    _write_plan(tmp_path, "README.md", "# README\n")
    _write_plan(tmp_path, "001-valid.md", "# Valid\n\n**Status:** Proposed\n")
    entries, warnings = plan_index.scan_repo(tmp_path)
    assert len(entries) == 1
    assert entries[0].number == 1
    assert any("README.md" in w for w in warnings)
