"""Tests for the Plan 009 v1 feature-matrix generator."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "feature-matrix.py"
DATA_PATH = REPO_ROOT / "data" / "v1-feature-matrix.json"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("feature_matrix", SCRIPT_PATH)
    assert spec is not None
    loader = spec.loader
    assert loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["feature_matrix"] = module
    loader.exec_module(module)
    return module


feature_matrix = _load_script()


def test_matrix_data_file_exists_and_is_valid_json() -> None:
    assert DATA_PATH.exists(), f"{DATA_PATH} was not generated"
    payload = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == "v1"
    assert set(payload["profiles"]) == {"A", "B", "C"}
    assert len(payload["golden_journeys"]) == 9
    rows = payload["rows"]
    assert len(rows) == 46, f"expected 46 matrix rows, got {len(rows)}"
    statuses = {row["status"] for row in rows}
    assert statuses <= {"pass", "partial", "blocked", "absent"}


def test_matrix_rows_have_required_fields() -> None:
    matrix = feature_matrix._matrix()
    required = {"journey", "component", "surface", "profile", "status", "dependency", "proof", "excluded", "notes"}
    for row in matrix.rows:
        row_dict = row.__dict__
        assert required <= row_dict.keys()
        assert row.journey in matrix.golden_journeys
        assert row.profile in matrix.profiles
        assert row.status in feature_matrix._allowed_statuses()


def test_matrix_has_no_duplicate_rows() -> None:
    matrix = feature_matrix._matrix()
    keys = [(row.journey, row.component, row.surface) for row in matrix.rows]
    assert len(keys) == len(set(keys))


def test_matrix_validation_passes() -> None:
    matrix = feature_matrix._matrix()
    errors = feature_matrix._validate(matrix)
    assert errors == []


def test_matrix_generator_main_runs_cleanly(tmp_path: Path) -> None:
    data_out = tmp_path / "v1-feature-matrix.json"
    docs_out = tmp_path / "v1-feature-matrix.md"
    assert feature_matrix.main(["--data", str(data_out), "--docs", str(docs_out)]) == 0
    assert data_out.exists()
    assert docs_out.exists()
    payload = json.loads(data_out.read_text(encoding="utf-8"))
    assert payload["version"] == "v1"
    assert "generated_at" in payload
    markdown = docs_out.read_text(encoding="utf-8")
    assert "# v1 Feature Matrix" in markdown
    assert "| Journey | Profile |" in markdown


def test_matrix_check_mode_passes() -> None:
    assert feature_matrix.main(["--check"]) == 0


def test_committed_json_matches_generator() -> None:
    """The committed JSON must be in sync with _matrix().

    Ignores ``generated_at`` (timestamp), ``observed_revisions`` (git HEAD
    revs / package versions captured at probe-run time), and ``status_source``
    (derived from which probes could run — environment-dependent: CI may not
    have sibling checkouts installed). These are run-time observations, not
    structural properties of the matrix. Row-level ``status`` and ``proof``
    are preserved when a probe returns HAND_ASSESSED, so they stay stable
    across environments.
    """
    committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    matrix = feature_matrix._matrix()
    generated = json.loads(feature_matrix._matrix_to_json(matrix))
    ignored = {"generated_at", "observed_revisions", "status_source"}
    for key in ignored:
        committed.pop(key, None)
        generated.pop(key, None)
    assert committed == generated, "Committed data/v1-feature-matrix.json is out of sync with scripts/feature-matrix.py; run python3 scripts/feature-matrix.py"


def test_validation_catches_errors() -> None:
    matrix = feature_matrix._matrix()
    bad_status_row = feature_matrix.MatrixRow(
        journey="GJ-1",
        component="regista",
        surface="bad-status-test",
        profile="A",
        status="bad",
        dependency="—",
        proof="—",
        excluded="—",
        notes="test",
    )
    bad_journey_row = feature_matrix.MatrixRow(
        journey="GJ-X",
        component="regista",
        surface="bad-journey-test",
        profile="A",
        status="pass",
        dependency="—",
        proof="—",
        excluded="—",
        notes="test",
    )
    bad_profile_row = feature_matrix.MatrixRow(
        journey="GJ-1",
        component="regista",
        surface="bad-profile-test",
        profile="D",
        status="pass",
        dependency="—",
        proof="—",
        excluded="—",
        notes="test",
    )
    for bad_row in (bad_status_row, bad_journey_row, bad_profile_row):
        bad_matrix = feature_matrix.Matrix(
            version=matrix.version,
            generated_at=matrix.generated_at,
            status_source=matrix.status_source,
            observed_revisions=matrix.observed_revisions,
            profiles=matrix.profiles,
            golden_journeys=matrix.golden_journeys,
            rows=[*matrix.rows, bad_row],
        )
        errors = feature_matrix._validate(bad_matrix)
        assert any(str(bad_row.surface) in e for e in errors), errors


def test_validation_catches_duplicate_rows() -> None:
    matrix = feature_matrix._matrix()
    duplicate = matrix.rows[0]
    bad_matrix = feature_matrix.Matrix(
        version=matrix.version,
        generated_at=matrix.generated_at,
        status_source=matrix.status_source,
        observed_revisions=matrix.observed_revisions,
        profiles=matrix.profiles,
        golden_journeys=matrix.golden_journeys,
        rows=[*matrix.rows, duplicate],
    )
    errors = feature_matrix._validate(bad_matrix)
    assert any("duplicate" in e for e in errors)


def test_cli_check_mode_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check"],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0


def test_cli_stdout_outputs_markdown() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--stdout"],
        capture_output=True,
        text=True,
        check=True,
        env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0
    assert "# v1 Feature Matrix" in result.stdout
    assert "| Journey | Profile |" in result.stdout
