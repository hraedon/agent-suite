"""Tests for the Plan 009 v1 feature-matrix generator."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "feature-matrix.py"
PROBES_SCRIPT_PATH = REPO_ROOT / "scripts" / "feature-probes.py"
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

    Ignores ``generated_at`` (timestamp) and ``observed_revisions`` (git HEAD
    revs / package versions captured at probe-run time) — these are run-time
    observations, not structural properties of the matrix.

    ``status_source`` is also ignored in the comparison because regenerating
    without siblings produces ``mixed-probe-and-hand`` while the committed
    file has ``probe-emitted``. A separate assertion verifies the committed
    value is ``probe-emitted`` — see
    :func:`test_committed_status_source_is_probe_emitted`.
    """
    committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    matrix = feature_matrix._matrix()
    generated = json.loads(feature_matrix._matrix_to_json(matrix))
    ignored = {"generated_at", "observed_revisions", "status_source"}
    for key in ignored:
        committed.pop(key, None)
        generated.pop(key, None)
    assert committed == generated, "Committed data/v1-feature-matrix.json is out of sync with scripts/feature-matrix.py; run python3 scripts/feature-matrix.py"


def test_committed_status_source_is_probe_emitted() -> None:
    """The committed matrix must be fully probe-emitted (Plan 015 WI-0.1 AC).

    A status_source of 'mixed-probe-and-hand' or 'hand-assessed' means some
    rows were not mechanically verified — the gate would false-green
    (Sol round-3 finding #1).
    """
    committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert committed["status_source"] == "probe-emitted", (
        f"Committed matrix status_source is '{committed['status_source']}' — "
        "expected 'probe-emitted'. Run with sibling checkouts to regenerate."
    )


def test_committed_observed_revisions_are_populated() -> None:
    """Every component must have a non-None observed revision.

    A None revision means the probe could not identify the component's
    release identity — the matrix would not be 'reproduced by a named probe
    against an identified revision set' (Plan 015 WI-0.1 AC).
    """
    committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    revisions = committed.get("observed_revisions", {})
    expected_components = {
        "agent-suite", "regista", "agent-notes", "dossier",
        "agent-provenance", "agent-capability-broker", "agent-wake",
    }
    assert set(revisions.keys()) == expected_components, (
        f"observed_revisions components mismatch: {set(revisions.keys())} "
        f"vs expected {expected_components}"
    )
    for component, rev in revisions.items():
        assert rev is not None, (
            f"observed_revisions['{component}'] is None — the probe could "
            "not identify this component's release identity."
        )


def test_feature_probe_strict_behavior() -> None:
    """--strict fails when probes return HAND_ASSESSED (Sol round-3 finding #1).

    With siblings available: --check --strict exits 0 (all probes ran).
    Without siblings: --check --strict exits 1 (HAND_ASSESSED present).
    """
    result = subprocess.run(
        [sys.executable, str(PROBES_SCRIPT_PATH), "--check", "--strict"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    if result.returncode == 0:
        committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        assert committed["status_source"] == "probe-emitted"
    else:
        assert "HAND_ASSESSED" in result.stderr or "STRICT" in result.stderr, (
            f"--strict exited {result.returncode} but stderr doesn't mention "
            f"HAND_ASSESSED or STRICT:\n{result.stderr}"
        )


def test_feature_probe_check_detects_proof_drift(tmp_path: Path) -> None:
    """--check detects proof changes, not just status changes (Sol round-3 #1).

    Modifies an agent-suite row's proof (probes always run for agent-suite)
    and verifies the check reports proof drift.
    """
    import copy
    committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(committed)
    for row in tampered["rows"]:
        if row["component"] == "agent-suite":
            row["proof"] = "tampered-proof-for-test"
            break
    tampered_path = tmp_path / "tampered-matrix.json"
    tampered_path.write_text(json.dumps(tampered, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(PROBES_SCRIPT_PATH), "--check", "--data", str(tampered_path)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode != 0, "--check should exit non-zero on proof drift"
    assert "DRIFT" in result.stderr
    assert "proof changed" in result.stderr


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
