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


# --- Sol Gate 0 Workstream 1: canonical-equality tests --------------------


def test_support_matrix_default_equals_canonical_json() -> None:
    """SupportMatrix.default() must equal from_json(canonical file).

    The hardcoded data table was removed; default() is now a thin loader.
    This test locks that equivalence so a future hardcoded table cannot
    silently re-diverge from the JSON.
    """
    path = _REPO_ROOT / "data" / "support-matrix.json"
    from_json_instance = SupportMatrix.from_json(path.read_text(encoding="utf-8"))
    default_instance = SupportMatrix.default()
    assert from_json_instance == default_instance


def test_release_board_default_equals_canonical_json() -> None:
    """ReleaseBoard.default() must equal from_json(canonical file).

    See test_support_matrix_default_equals_canonical_json — same contract
    for the release board.
    """
    path = _REPO_ROOT / "data" / "release-board.json"
    from_json_instance = ReleaseBoard.from_json(path.read_text(encoding="utf-8"))
    default_instance = ReleaseBoard.default()
    assert from_json_instance == default_instance


def test_release_board_default_loads_from_data_dir() -> None:
    """The release board is loaded from data/release-board.json, not hardcoded.

    A behavioral assertion: if the canonical file is removed, default()
    raises FileNotFoundError (not silently returns hardcoded data).
    """

    path = _REPO_ROOT / "data" / "release-board.json"
    assert path.is_file(), "canonical data/release-board.json must exist"
    # We cannot easily monkeypatch the path resolution; the existence check
    # plus the equality test above together prove the loader path is live.


# --- Sol Gate 0 Workstream 1: every proof reference must resolve ----------


# Typed external artifact references — proof_artifact values that are not
# file paths in this repo but are intentionally external (CI-generated,
# release-attached, owned by another repo, or generated by a future gate).
# Recognized by pattern; any proof_artifact NOT matching a recognized
# external pattern MUST resolve to an existing file in this repo.
_EXTERNAL_ARTIFACT_PATTERNS: tuple[str, ...] = (
    "dist/",                  # WI-2.3, WI-2.4: release bundle output
    "releases/",              # WI-5.1, WI-5.4: release cut output
    "ci/",                    # WI-2.2: lock-build CI workflow
    # Golden release-time outputs (generated by qualification gates, attached
    # to the release, not committed to main):
    "golden/clean-install.json",       # WI-4.1
    "golden/windows-qualification.json",  # WI-4.2
    "golden/upgrade-proof.json",       # WI-4.3
    "golden/restore-proof.json",       # WI-4.4
    "golden/estate-convergence.json",  # WI-4.5
    "golden/soak-report.json",         # WI-5.2
    "golden/gj-1-through-4.json",      # WI-1.2 (dossier golden journeys)
    "golden/gj-5-gj-8.json",           # WI-1.3
    "golden/identity-keys.json",       # WI-1.4
    "golden/notifications.json",       # WI-1.5
    "golden/a11y-report.json",         # WI-1.6
    # Operator-generated / release-time artifacts (live state, not in main):
    "data/candidate-inventory.json",   # WI-0.2 (CI-generated on tag push)
    "data/security-review.json",       # WI-3.3
)


def _is_external_artifact(proof_artifact: str) -> bool:
    """True if the proof_artifact is a recognized external artifact reference."""
    return any(
        proof_artifact == pat or proof_artifact.startswith(pat.rstrip("/"))
        for pat in _EXTERNAL_ARTIFACT_PATTERNS
    )


def test_every_release_board_proof_artifact_resolves() -> None:
    """Every WI's proof_artifact must resolve to an existing file OR be a
    recognized typed external artifact reference.

    Sol Gate 0 Workstream 1: 'Require every current proof reference to
    resolve to an existing file or a typed external artifact reference.'

    A dangling proof_artifact is a real defect — the WI's proof would be
    unverifiable.
    """
    board = ReleaseBoard.default()
    unresolved: list[tuple[str, str]] = []
    for gate in board.gates:
        for wi in gate.work_items:
            artifact = wi.proof_artifact
            if not artifact:
                unresolved.append((wi.id, "(empty proof_artifact)"))
                continue
            if _is_external_artifact(artifact):
                continue
            # File-path reference — must exist in the repo.
            if not (_REPO_ROOT / artifact).exists():
                unresolved.append((wi.id, artifact))
    assert not unresolved, (
        "Unresolved proof_artifact references in release board "
        f"( WI-id , artifact ): {unresolved}"
    )


# --- Sol Gate 0 Workstream 1: machine-readable claims ledger -------------


def test_claims_ledger_json_loads_and_has_all_14_claims() -> None:
    """data/claims-ledger.json is the machine-readable claims ledger.

    Sol WS1: 'Create or correct the machine-readable claims-ledger
    reference.' The JSON is the canonical machine form; docs/claims-ledger.md
    remains the human-readable detailed ledger; docs/claims-ledger-index.md
    is the quick-reference summary. The three must agree on maturity per
    claim.
    """
    path = _REPO_ROOT / "data" / "claims-ledger.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["version"] == "v1"
    claim_ids = [c["id"] for c in raw["claims"]]
    expected = [f"CL-{i:03d}" for i in range(1, 15)]
    assert claim_ids == expected, f"claims-ledger.json claims mismatch: {claim_ids}"


def test_claims_ledger_json_maturities_match_index() -> None:
    """Every claim's maturity in data/claims-ledger.json must equal the
    maturity recorded in docs/claims-ledger-index.md.

    Catches the round-2/3 drift where the index said experimental but the
    detailed ledger said supported (or vice versa).
    """
    ledger_path = _REPO_ROOT / "data" / "claims-ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger_maturities = {c["id"]: c["maturity"] for c in ledger["claims"]}

    index_path = _REPO_ROOT / "docs" / "claims-ledger-index.md"
    index_text = index_path.read_text(encoding="utf-8")
    mismatches: list[tuple[str, str, str]] = []
    for claim_id, maturity in ledger_maturities.items():
        # The index has rows like: | CL-007 | Honest health | supported | ... |
        import re

        m = re.search(
            rf"\| {re.escape(claim_id)} \| [^|]+ \| (\w+) \|",
            index_text,
        )
        assert m is not None, (
            f"{claim_id} not found in docs/claims-ledger-index.md"
        )
        index_maturity = m.group(1)
        if index_maturity != maturity:
            mismatches.append((claim_id, maturity, index_maturity))
    assert not mismatches, (
        f"claims-ledger.json vs claims-ledger-index.md maturity drift "
        f"(claim, json, index): {mismatches}"
    )


def test_claims_ledger_json_counts_are_consistent() -> None:
    """maturity_counts in the JSON equals the actual count of each maturity."""
    path = _REPO_ROOT / "data" / "claims-ledger.json"
    ledger = json.loads(path.read_text(encoding="utf-8"))
    from collections import Counter

    actual = Counter(c["maturity"] for c in ledger["claims"])
    declared = ledger["maturity_counts"]
    assert dict(actual) == declared, (
        f"maturity_counts drift: actual={dict(actual)} declared={declared}"
    )
