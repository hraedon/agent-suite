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


def test_interop_ci_derives_origins_and_revisions_from_suite_lock() -> None:
    """The interop job must take BOTH the repository origin and the revision of
    every Profile B component from SUITE.lock — the single source of truth —
    not from literal SHAs or hard-coded origins (release-truth / Sol CI finding).

    The durable design resolves ``<NAME>_REPO`` and ``<NAME>_SHA`` from
    SUITE.lock at run time and installs from
    ``git+https://github.com/${<NAME>_REPO}.git@${<NAME>_SHA}``, so there is no
    second literal to drift and no work-domain origin for the identifier gate to
    flag. This test enforces that design:

    1. no ``<NAME>_SHA: <hex>`` literal assignment survives in ci.yml;
    2. no bare 40-hex literal equals a SUITE.lock component revision;
    3. no SUITE.lock repository origin appears as a hard-coded literal (the
       origin must come from a ``${..._REPO}`` variable);
    4. for every Profile B required component, ci.yml resolves BOTH its repo
       and its revision from the lock and consumes both.
    """
    lock = tomllib.loads(LOCK_PATH.read_text(encoding="utf-8"))
    lock_components = lock["components"]
    lock_revisions = {n: i["revision"] for n, i in lock_components.items()}
    lock_repos = {n: i["repo"] for n, i in lock_components.items()}
    ci_text = CI_PATH.read_text(encoding="utf-8")

    # (1) No literal "<NAME>_SHA: <hex>" assignment (the old brittle design).
    literal_pin = re.search(r"\b[A-Z][A-Z0-9_]*_SHA:\s*[0-9a-fA-F]{7,}", ci_text)
    assert literal_pin is None, (
        "ci.yml carries a literal component-revision pin "
        f"({literal_pin.group(0)!r}). SUITE.lock is the single source of "
        "truth: resolve revisions from the lock at run time instead."
    )

    # (2) No bare 40-hex literal that equals a lock revision (a literal
    #     reintroduced in any other shape). Action-pin SHAs are 40-hex too, so
    #     compare against the lock revisions specifically rather than banning
    #     all 40-hex literals.
    for hex_literal in re.findall(r"\b[0-9a-f]{40}\b", ci_text):
        offenders = [
            name
            for name, rev in lock_revisions.items()
            if rev == hex_literal
        ]
        assert not offenders, (
            f"ci.yml hardcodes the SUITE.lock revision for {offenders} "
            f"({hex_literal[:8]}). Resolve it from SUITE.lock at run time."
        )

    # (3) No hard-coded origin. No SUITE.lock ``repo`` (e.g. "org/name") may
    #     appear as a literal anywhere in ci.yml — the origin must be supplied
    #     via a ${..._REPO} variable read from the lock. This keeps the
    #     identifier gate satisfied (no work-domain org literal in the file).
    for component, repo in lock_repos.items():
        assert repo not in ci_text, (
            f"ci.yml hard-codes the origin for {component} ({repo!r}); the "
            "origin must be resolved from SUITE.lock via a ${..._REPO} variable."
        )

    # (4) Every interop Profile B component derives repo + revision from the
    #     lock AND consumes both — the interop set must BE the locked candidate
    #     (Plan 015 WI-2.2). The resolve step exists...
    assert "Resolve pinned origins and revisions from SUITE.lock" in ci_text, (
        "ci.yml must resolve interop component origins and revisions from "
        "SUITE.lock (the single source of truth) at run time."
    )

    # ...and covers every Profile B required component. Deriving the set from
    # the support matrix means a newly required component fails this test until
    # it is wired into the interop job (no silent shrinkage).
    matrix = _load_support_matrix()
    profile_b = next(
        p for p in matrix["profiles"] if p["profile"] == "B"
    )
    required = set(profile_b["required_components"])

    # Component -> env-var prefix carrying its lock-derived origin + revision.
    # (agent-provenance's package/CLI name is cairn, hence the CAIRN prefix.)
    interop_prefix = {
        "regista": "REGISTA",
        "agent-notes": "AGENT_NOTES",
        "agent-provenance": "CAIRN",
        "dossier": "DOSSIER",
    }
    missing_mapping = required - set(interop_prefix)
    assert not missing_mapping, (
        f"Profile B required component(s) {sorted(missing_mapping)} have no "
        "interop pin mapping — extend interop_prefix and wire them into the "
        "interop job so the interop set stays the locked candidate."
    )

    for component in sorted(required):
        prefix = interop_prefix[component]
        repo_var = f"{prefix}_REPO"
        sha_var = f"{prefix}_SHA"
        # Both origin and revision are resolved from the lock...
        assert f"comp['{component}']['repo']" in ci_text, (
            f"ci.yml resolve step does not read the {component} repo (origin) "
            "from SUITE.lock — it must derive it from the lock, not hard-code it."
        )
        assert f"comp['{component}']['revision']" in ci_text, (
            f"ci.yml resolve step does not read the {component} revision from "
            "SUITE.lock — it must derive it from the lock, not a literal."
        )
        # ...and both are consumed by an install/fetch step.
        assert re.search(rf"\$\{{?{repo_var}\}}?", ci_text), (
            f"ci.yml does not consume the {repo_var} resolved from SUITE.lock — "
            f"the {component} origin must be the lock-derived repository."
        )
        assert re.search(rf"\$\{{?{sha_var}\}}?", ci_text), (
            f"ci.yml does not consume the {sha_var} resolved from SUITE.lock — "
            f"the {component} install must use the lock-derived revision."
        )

    # The spine must install from the locked source revision, not a
    # version-only PyPI wheel (a PyPI version can be built from a commit other
    # than the pinned revision — defeating the tested-candidate freeze).
    assert re.search(r"\$\{\{?REGISTA_SHA\}\}?", ci_text), (
        "regista must be installed from the lock-derived REGISTA_SHA source "
        "revision, not a version-only PyPI wheel."
    )
    assert "regista-hraedon==" not in ci_text, (
        "the interop job must not install regista from a version-only PyPI "
        "wheel; install the exact SUITE.lock source revision instead."
    )


def test_interop_remote_installs_ignore_local_development_sources() -> None:
    """Pinned Git installs must not resolve sibling-only ``tool.uv.sources``.

    A remote agent-notes build previously interpreted its development mapping
    to ``../regista`` relative to uv's Git checkout and failed before interop
    could run. The spine is installed explicitly from SUITE.lock, so remote face
    and provenance installs must resolve only their publishable metadata.
    """
    ci_text = CI_PATH.read_text(encoding="utf-8")
    assert re.search(
        r"uv pip install --no-sources\s+\\?\s*"
        r'"git\+https://github\.com/\$\{AGENT_NOTES_REPO\}'
        r"\.git@\$\{AGENT_NOTES_SHA\}",
        ci_text,
    )
    assert (
        'uv pip install --no-sources "git+https://github.com/'
        '${CAIRN_REPO}.git@${CAIRN_SHA}"'
    ) in ci_text
