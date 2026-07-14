"""Unit tests for the release artifacts module — support matrix and release board."""

from __future__ import annotations

import json
from pathlib import Path

from agent_suite.release_artifacts import ReleaseBoard, SupportMatrix

_REPO_ROOT = Path(__file__).resolve().parent.parent


# --- SupportMatrix tests -----------------------------------------------------


def test_support_matrix_default_validates() -> None:
    matrix = SupportMatrix.default()
    assert matrix.validate() is True


def test_support_matrix_to_dict_has_keys() -> None:
    matrix = SupportMatrix.default()
    d = matrix.to_dict()
    expected_keys = {
        "release",
        "python_versions",
        "postgres_version",
        "reference_linux",
        "docker",
        "windows_versions",
        "browsers",
        "identity_backends",
        "secret_backends",
        "profiles",
        "availability",
        "compatibility_window",
        "excluded_surfaces",
    }
    assert expected_keys <= set(d)


def test_support_matrix_from_json_roundtrip() -> None:
    matrix = SupportMatrix.default()
    d = matrix.to_dict()
    text = json.dumps(d)
    restored = SupportMatrix.from_json(text)
    assert restored.validate() is True
    assert restored.release == matrix.release
    assert restored.python_versions == matrix.python_versions
    assert restored.postgres_version == matrix.postgres_version
    assert len(restored.browsers) == len(matrix.browsers)
    assert len(restored.identity_backends) == len(matrix.identity_backends)
    assert len(restored.secret_backends) == len(matrix.secret_backends)
    assert len(restored.profiles) == len(matrix.profiles)


# --- ReleaseBoard tests ------------------------------------------------------


def test_release_board_default_validates() -> None:
    board = ReleaseBoard.default()
    assert board.validate() is True


def test_release_board_to_dict_has_keys() -> None:
    board = ReleaseBoard.default()
    d = board.to_dict()
    expected_keys = {"release", "feature_matrix_ref", "claims_ledger_ref", "gates"}
    assert expected_keys <= set(d)


def test_release_board_from_json_roundtrip() -> None:
    board = ReleaseBoard.default()
    d = board.to_dict()
    text = json.dumps(d)
    restored = ReleaseBoard.from_json(text)
    assert restored.validate() is True
    assert restored.release == board.release
    assert len(restored.gates) == len(board.gates)


def test_release_board_has_all_gates() -> None:
    board = ReleaseBoard.default()
    gate_numbers = [g.number for g in board.gates]
    assert gate_numbers == [0, 1, 2, 3, 4, 5]


def test_release_board_wi_ids_unique() -> None:
    board = ReleaseBoard.default()
    all_ids: list[str] = []
    for gate in board.gates:
        for wi in gate.work_items:
            all_ids.append(wi.id)
    assert len(all_ids) == len(set(all_ids))


def test_support_matrix_json_no_fields_lost_on_roundtrip() -> None:
    """Loading data/support-matrix.json and re-serializing must not drop fields.

    The JSON file is the canonical artifact. If from_json + to_dict drops
    fields, the dataclass is incomplete and the proof command doesn't
    validate the actual file.
    """
    json_path = _REPO_ROOT / "data" / "support-matrix.json"
    raw = json.loads(json_path.read_text())
    matrix = SupportMatrix.from_json(json_path.read_text())
    restored = matrix.to_dict()

    raw_keys = set(raw.keys())
    restored_keys = set(restored.keys())
    missing = raw_keys - restored_keys
    assert not missing, (
        f"SupportMatrix.to_dict() drops keys from the JSON file: {missing}"
    )

    for key in ("browsers", "identity_backends", "secret_backends", "profiles"):
        for raw_item, rest_item in zip(raw[key], restored[key]):
            missing_nested = set(raw_item.keys()) - set(rest_item.keys())
            assert not missing_nested, (
                f"SupportMatrix roundtrip drops nested keys in {key}: "
                f"{missing_nested}"
            )

    raw_avail = set(raw["availability"].keys())
    rest_avail = set(restored["availability"].keys())
    missing_avail = raw_avail - rest_avail
    assert not missing_avail, (
        f"SupportMatrix roundtrip drops availability keys: {missing_avail}"
    )


def test_release_board_json_no_fields_lost_on_roundtrip() -> None:
    """Loading data/release-board.json and re-serializing must not drop fields."""
    json_path = _REPO_ROOT / "data" / "release-board.json"
    raw = json.loads(json_path.read_text())
    board = ReleaseBoard.from_json(json_path.read_text())
    restored = board.to_dict()

    raw_top = set(raw.keys())
    restored_top = set(restored.keys())
    missing_top = raw_top - restored_top
    assert not missing_top, (
        f"ReleaseBoard.to_dict() drops top-level keys: {missing_top}"
    )

    for raw_gate, rest_gate in zip(raw["gates"], restored["gates"]):
        raw_wi_keys_per_item = [
            set(wi.keys()) for wi in raw_gate["work_items"]
        ]
        rest_wi_keys_per_item = [
            set(wi.keys()) for wi in rest_gate["work_items"]
        ]
        for i, (raw_keys, rest_keys) in enumerate(
            zip(raw_wi_keys_per_item, rest_wi_keys_per_item)
        ):
            missing = raw_keys - rest_keys
            wi_id = raw_gate["work_items"][i].get("id", "?")
            assert not missing, (
                f"WorkItem {wi_id} in gate {raw_gate['number']} "
                f"loses keys on roundtrip: {missing}"
            )
