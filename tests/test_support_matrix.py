"""Mechanical check that CI lanes, install docs, and release metadata are
consistent with the support matrix (Plan 015 WI-0.3 AC).

The support matrix (data/support-matrix.json) is the single source of truth
for supported platforms, versions, and qualification status. This test
verifies that CI lanes, install docs, and release metadata do not drift
out of sync with it.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SUPPORT_MATRIX_PATH = REPO_ROOT / "data" / "support-matrix.json"
CI_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"
LOCK_PATH = REPO_ROOT / "SUITE.lock"
INSTALL_WINDOWS_PATH = REPO_ROOT / "docs" / "install-windows.md"
INSTALL_LINUX_PATH = REPO_ROOT / "docs" / "install-linux.md"
SECRETS_WINDOWS_PATH = REPO_ROOT / "docs" / "secrets-windows.md"

_INSTALL_DOCS_WITH_VERSIONS = [INSTALL_WINDOWS_PATH, INSTALL_LINUX_PATH]
_ALL_DOCS = [INSTALL_WINDOWS_PATH, INSTALL_LINUX_PATH, SECRETS_WINDOWS_PATH]


def _load_support_matrix() -> dict[str, Any]:
    return json.loads(SUPPORT_MATRIX_PATH.read_text(encoding="utf-8"))


def test_support_matrix_has_required_fields() -> None:
    matrix = _load_support_matrix()
    required = {
        "release", "python_versions", "postgres_version",
        "reference_linux", "docker", "kubernetes",
        "windows_versions", "windows_qualification",
        "profiles", "availability", "compatibility_window",
        "excluded_surfaces",
    }
    missing = required - set(matrix.keys())
    assert not missing, f"support-matrix.json missing required fields: {missing}"


def test_ci_python_versions_match_support_matrix() -> None:
    """CI lint-and-test job must test all Python versions in the support matrix."""
    matrix = _load_support_matrix()
    expected = set(matrix["python_versions"])
    ci_text = CI_PATH.read_text(encoding="utf-8")
    match = re.search(r'python-version:\s*\[([^\]]+)\]', ci_text)
    assert match is not None, "Could not find python-version matrix in ci.yml"
    ci_versions = {v.strip().strip('"') for v in match.group(1).split(",")}
    assert ci_versions == expected, (
        f"CI Python versions {ci_versions} do not match support matrix {expected}"
    )


def test_ci_postgres_version_matches_support_matrix() -> None:
    """CI Postgres service version must match the support matrix."""
    matrix = _load_support_matrix()
    expected_major = str(matrix["postgres_version"]).rstrip("+")
    ci_text = CI_PATH.read_text(encoding="utf-8")
    match = re.search(r'image:\s*(?:pgvector/pgvector:pg|postgres:)(\d+)', ci_text)
    assert match is not None, "Could not find postgres image in ci.yml"
    ci_major = match.group(1)
    assert ci_major == expected_major, (
        f"CI Postgres {ci_major} does not match support matrix {expected_major}"
    )


def test_kubernetes_not_labeled_as_supported() -> None:
    """Kubernetes must not be labeled as 'supported' (Sol round-3 finding #4).

    A platform is not supported merely because unit tests import on it.
    Until a k8s qualification lane exists, it is 'dogfood' or 'target'.
    """
    matrix = _load_support_matrix()
    k8s_status = str(matrix["kubernetes"])
    assert k8s_status not in ("supported", "optional"), (
        f"Kubernetes status is '{k8s_status}' — should be 'dogfood' or 'target' "
        "until a qualification lane exists"
    )
    note = str(matrix.get("kubernetes_note", ""))
    assert "genuinely supported" not in note, (
        "Kubernetes note still says 'genuinely supported'"
    )


def test_suite_lock_release_matches_support_matrix() -> None:
    """SUITE.lock release must match the support matrix release."""
    matrix = _load_support_matrix()
    lock_text = LOCK_PATH.read_text(encoding="utf-8")
    match = re.search(r'release\s*=\s*"([^"]+)"', lock_text)
    assert match is not None, "Could not find release in SUITE.lock"
    lock_release = match.group(1)
    matrix_release = str(matrix["release"])
    assert lock_release == matrix_release, (
        f"SUITE.lock release '{lock_release}' does not match "
        f"support matrix '{matrix_release}'"
    )


def test_install_docs_python_versions_match_support_matrix() -> None:
    """Install docs must reference all Python versions from the support matrix."""
    matrix = _load_support_matrix()
    expected_versions = matrix["python_versions"]
    for doc_path in _INSTALL_DOCS_WITH_VERSIONS:
        if not doc_path.exists():
            continue
        doc_text = doc_path.read_text(encoding="utf-8")
        for version in expected_versions:
            assert version in doc_text, (
                f"{doc_path.name} does not reference Python {version} "
                f"(support matrix requires {expected_versions})"
            )


def test_install_docs_postgres_version_matches_support_matrix() -> None:
    """Install docs must reference the same Postgres version as the support matrix."""
    matrix = _load_support_matrix()
    expected = str(matrix["postgres_version"])
    for doc_path in _INSTALL_DOCS_WITH_VERSIONS:
        if not doc_path.exists():
            continue
        doc_text = doc_path.read_text(encoding="utf-8")
        assert expected in doc_text, (
            f"{doc_path.name} does not reference Postgres {expected} "
            f"(support matrix requires {expected})"
        )


def test_install_docs_do_not_reference_dropped_platforms() -> None:
    """Install docs must not reference dropped platforms."""
    matrix = _load_support_matrix()
    dropped = ["Windows 10", "Server 2019", "Postgres 14"]
    for doc_path in _ALL_DOCS:
        if not doc_path.exists():
            continue
        doc_text = doc_path.read_text(encoding="utf-8")
        for dropped_ref in dropped:
            assert dropped_ref not in doc_text, (
                f"{doc_path.name} references '{dropped_ref}' which conflicts "
                f"with the support matrix (windows_versions={matrix['windows_versions']}, "
                f"postgres_version={matrix['postgres_version']})"
            )


def test_interop_ci_pins_match_suite_lock() -> None:
    """Interop CI env vars must match SUITE.lock revisions (Sol round-3 #2).

    A durable tested-candidate freeze requires a single source of truth for
    revisions. The interop CI pins and SUITE.lock must not drift.
    """
    lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock_revisions = {
        name: info["revision"]
        for name, info in lock["components"].items()
    }
    ci_text = CI_PATH.read_text(encoding="utf-8")
    interop_vars = {
        "regista": "REGISTA_SHA",
        "agent-notes": "AGENT_NOTES_SHA",
        "dossier": "DOSSIER_SHA",
        "agent-provenance": "CAIRN_SHA",
    }
    for component, env_var in interop_vars.items():
        match = re.search(rf'{env_var}:\s*(\w+)', ci_text)
        assert match is not None, f"Could not find {env_var} in ci.yml"
        ci_rev = match.group(1)
        lock_rev = lock_revisions.get(component, "")
        assert ci_rev == lock_rev, (
            f"Interop CI {env_var} ({ci_rev[:8]}) does not match "
            f"SUITE.lock {component} ({lock_rev[:8]}) — reconcile by "
            "updating SUITE.lock or the interop CI env vars"
        )
