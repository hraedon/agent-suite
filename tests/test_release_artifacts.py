"""Unit tests for the release artifacts module — support matrix and release board."""

from __future__ import annotations

import json

from agent_suite.release_artifacts import ReleaseBoard, SupportMatrix


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
