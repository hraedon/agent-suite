"""Plan 009 WI-0.2 — Shared contract conformance fixture tests.

Validates that the versioned contract fixtures in ``data/contracts/`` are
well-formed and that their declared enums are accurate.

**Cross-references** (health contract): declared enums are compared against
live Python enums in the agent-suite codebase. This catches semantic drift
within agent-suite's own code.

**Snapshot assertions** (lifecycle, identity, install-harness, notification):
declared enums are compared against hardcoded expected values. The owning
components (regista, cairn, agent-wake) are not installed in the lint-and-test
CI job, so real cross-references require the interop CI job. The snapshot
assertions still document the expected values and fail if the fixture drifts.

These tests are stdlib-only and run in the standard ``lint-and-test`` CI job
(no Postgres, no Docker, no component installs required).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS_DIR = REPO_ROOT / "data" / "contracts"

REQUIRED_META_FIELDS = (
    "contract",
    "version",
    "description",
    "owned_by",
    "consumers",
    "invariants",
)

EXPECTED_CONTRACTS = (
    "lifecycle",
    "identity",
    "health",
    "evidence-export",
    "install-harness",
    "knowledge",
    "notification",
)


def _load_fixture(name: str) -> dict[str, object]:
    path = CONTRACTS_DIR / f"{name}.json"
    assert path.exists(), f"contract fixture missing: {path}"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"contract fixture {name}: root must be a JSON object"
    return data


def _enum_values(enum_cls: object) -> set[str]:
    return {e.value for e in enum_cls}  # type: ignore[attr-defined]


def test_all_expected_contracts_exist() -> None:
    discovered = {p.stem for p in CONTRACTS_DIR.glob("*.json")}
    assert discovered == set(EXPECTED_CONTRACTS), (
        f"Contract fixture set mismatch — "
        f"discovered={sorted(discovered)}, expected={sorted(EXPECTED_CONTRACTS)}"
    )


@pytest.mark.parametrize("name", EXPECTED_CONTRACTS)
def test_fixture_well_formed(name: str) -> None:
    fixture = _load_fixture(name)
    for field in REQUIRED_META_FIELDS:
        assert field in fixture, f"{name}: missing required meta-field '{field}'"
    version = fixture["version"]
    assert isinstance(version, str) and version.count(".") >= 2, (
        f"{name}: version should be semver (got {version!r})"
    )
    consumers = fixture["consumers"]
    assert isinstance(consumers, list) and len(consumers) > 0, (
        f"{name}: consumers must be a non-empty list"
    )
    invariants = fixture["invariants"]
    assert isinstance(invariants, list) and len(invariants) > 0, (
        f"{name}: invariants must be a non-empty list"
    )


# ---------------------------------------------------------------------------
# Cross-references — health contract against live agent-suite Python enums
# ---------------------------------------------------------------------------


def test_health_component_status_matches_code() -> None:
    from agent_suite.doctor import ComponentStatus

    fixture = _load_fixture("health")
    contract_statuses = set(fixture["component_status_values"])  # type: ignore[arg-type]
    code_statuses = _enum_values(ComponentStatus)
    assert contract_statuses == code_statuses, (
        f"component_status_values mismatch — "
        f"contract={sorted(contract_statuses)}, code={sorted(code_statuses)}"
    )


def test_health_tier_values_match_code() -> None:
    from agent_suite.components import Tier

    fixture = _load_fixture("health")
    contract_tiers = set(fixture["tier_values"])  # type: ignore[arg-type]
    code_tiers = _enum_values(Tier)
    assert contract_tiers == code_tiers, (
        f"tier_values mismatch — "
        f"contract={sorted(contract_tiers)}, code={sorted(code_tiers)}"
    )


def test_health_drift_kind_values_match_code() -> None:
    from agent_suite.lock import DriftKind

    fixture = _load_fixture("health")
    contract_drift_kinds = set(fixture["drift_kind_values"])  # type: ignore[arg-type]
    code_drift_kinds = _enum_values(DriftKind)
    assert contract_drift_kinds == code_drift_kinds, (
        f"drift_kind_values mismatch — "
        f"contract={sorted(contract_drift_kinds)}, code={sorted(code_drift_kinds)}"
    )


def test_health_verify_restore_status_matches_code() -> None:
    from agent_suite.verify_restore import ProjectVerifyStatus

    fixture = _load_fixture("health")
    contract_statuses = set(fixture["verify_restore_status_values"])  # type: ignore[arg-type]
    code_statuses = _enum_values(ProjectVerifyStatus)
    assert contract_statuses == code_statuses, (
        f"verify_restore_status_values mismatch — "
        f"contract={sorted(contract_statuses)}, code={sorted(code_statuses)}"
    )


def test_health_key_age_status_matches_code() -> None:
    from agent_suite.key_watch import KeyAgeStatus

    fixture = _load_fixture("health")
    contract_statuses = set(fixture["key_age_status_values"])  # type: ignore[arg-type]
    code_statuses = _enum_values(KeyAgeStatus)
    assert contract_statuses == code_statuses, (
        f"key_age_status_values mismatch — "
        f"contract={sorted(contract_statuses)}, code={sorted(code_statuses)}"
    )


def test_health_store_growth_status_matches_code() -> None:
    from agent_suite.key_watch import StoreGrowthStatus

    fixture = _load_fixture("health")
    contract_statuses = set(fixture["store_growth_status_values"])  # type: ignore[arg-type]
    code_statuses = _enum_values(StoreGrowthStatus)
    assert contract_statuses == code_statuses, (
        f"store_growth_status_values mismatch — "
        f"contract={sorted(contract_statuses)}, code={sorted(code_statuses)}"
    )


# ---------------------------------------------------------------------------
# Snapshot assertions — lifecycle, identity, install-harness, notification
# (owning components not installed in lint-and-test CI job)
# ---------------------------------------------------------------------------


def test_lifecycle_states_match_canonical_workflow() -> None:
    fixture = _load_fixture("lifecycle")
    contract_states = set(fixture["states"])  # type: ignore[arg-type]
    expected_states = {
        "open", "in_progress", "blocked", "deferred",
        "in_review", "in_human_review", "done",
    }
    assert contract_states == expected_states, (
        f"lifecycle states mismatch — "
        f"contract={sorted(contract_states)}, expected={sorted(expected_states)}"
    )


def test_lifecycle_roles_match_canonical_workflow() -> None:
    fixture = _load_fixture("lifecycle")
    contract_roles = set(fixture["roles"])  # type: ignore[arg-type]
    expected_roles = {"human", "agent", "system"}
    assert contract_roles == expected_roles, (
        f"lifecycle roles mismatch — "
        f"contract={sorted(contract_roles)}, expected={sorted(expected_roles)}"
    )


def test_lifecycle_terminal_states() -> None:
    fixture = _load_fixture("lifecycle")
    terminal = set(fixture["terminal_states"])  # type: ignore[arg-type]
    assert terminal == {"done"}, (
        f"lifecycle terminal_states should be ['done'], got {sorted(terminal)}"
    )


def test_lifecycle_transitions_referential_integrity() -> None:
    """Every transition's from/to must be in states, allowed_roles in roles."""
    fixture = _load_fixture("lifecycle")
    states = set(fixture["states"])  # type: ignore[arg-type]
    roles = set(fixture["roles"])  # type: ignore[arg-type]
    seen: set[tuple[str, str, str]] = set()
    for t in fixture["transitions"]:  # type: ignore[index]
        assert isinstance(t, dict), f"transition is not a dict: {t!r}"
        name = t.get("name", "")  # type: ignore[union-attr]
        from_state = t.get("from", "")  # type: ignore[union-attr]
        to_state = t.get("to", "")  # type: ignore[union-attr]
        key = (name, from_state, to_state)
        assert key not in seen, f"duplicate transition {key!r}"
        seen.add(key)
        assert from_state in states, (
            f"transition {name!r} has invalid 'from': {from_state!r}"
        )
        assert to_state in states, (
            f"transition {name!r} has invalid 'to': {to_state!r}"
        )
        for role in t.get("allowed_roles", []):  # type: ignore[union-attr]
            assert role in roles, (
                f"transition {name!r} has invalid role: {role!r}"
            )


def test_identity_actor_kinds_match_lifecycle_roles() -> None:
    identity = _load_fixture("identity")
    lifecycle = _load_fixture("lifecycle")
    actor_kinds = set(identity["actor_kinds"])  # type: ignore[arg-type]
    roles = set(lifecycle["roles"])  # type: ignore[arg-type]
    assert actor_kinds == roles, (
        f"identity actor_kinds must match lifecycle roles — "
        f"identity={sorted(actor_kinds)}, lifecycle={sorted(roles)}"
    )


def test_identity_signing_schemes() -> None:
    fixture = _load_fixture("identity")
    schemes = set(fixture["signing_schemes"])  # type: ignore[arg-type]
    expected = {"hmac", "ed25519"}
    assert schemes == expected, (
        f"identity signing_schemes mismatch — "
        f"contract={sorted(schemes)}, expected={sorted(expected)}"
    )


def test_install_harness_hook_events() -> None:
    fixture = _load_fixture("install-harness")
    hook_events = set(fixture["hook_events"])  # type: ignore[arg-type]
    expected = {"SessionStart", "SessionStop", "ToolBegin", "ToolEnd"}
    assert hook_events == expected, (
        f"install-harness hook_events mismatch — "
        f"contract={sorted(hook_events)}, expected={sorted(expected)}"
    )


def test_notification_delivery_modes() -> None:
    fixture = _load_fixture("notification")
    delivery_modes = set(fixture["delivery_modes"])  # type: ignore[arg-type]
    expected = {
        "live_wake", "silent_inject", "next_session",
        "managed_session", "webhook", "email",
    }
    assert delivery_modes == expected, (
        f"notification delivery_modes mismatch — "
        f"contract={sorted(delivery_modes)}, expected={sorted(expected)}"
    )


def test_notification_delivery_mode_partition() -> None:
    """supported + partial + absent must partition delivery_modes with no overlap."""
    fixture = _load_fixture("notification")
    all_modes = set(fixture["delivery_modes"])  # type: ignore[arg-type]
    supported = set(fixture["supported_delivery_modes"])  # type: ignore[arg-type]
    partial = set(fixture["partial_delivery_modes"])  # type: ignore[arg-type]
    absent = set(fixture["absent_delivery_modes"])  # type: ignore[arg-type]
    categorized = supported | partial | absent
    assert all_modes == categorized, (
        f"delivery mode sub-lists don't partition delivery_modes — "
        f"uncategorized={sorted(all_modes - categorized)}, "
        f"extra={sorted(categorized - all_modes)}"
    )
    assert not (supported & partial), f"modes in both supported and partial: {sorted(supported & partial)}"
    assert not (supported & absent), f"modes in both supported and absent: {sorted(supported & absent)}"
    assert not (partial & absent), f"modes in both partial and absent: {sorted(partial & absent)}"


def test_knowledge_entity_kinds() -> None:
    fixture = _load_fixture("knowledge")
    entity_kinds = set(fixture["entity_kinds"])  # type: ignore[arg-type]
    expected = {"breadcrumb", "memory", "reflection"}
    assert entity_kinds == expected, (
        f"knowledge entity_kinds mismatch — "
        f"contract={sorted(entity_kinds)}, expected={sorted(expected)}"
    )


def test_evidence_export_envelope_versions() -> None:
    fixture = _load_fixture("evidence-export")
    envelope_versions = set(fixture["envelope_versions"])  # type: ignore[arg-type]
    expected = {1, 2}
    assert envelope_versions == expected, (
        f"evidence-export envelope_versions mismatch — "
        f"contract={sorted(envelope_versions)}, expected={sorted(expected)}"
    )


# ---------------------------------------------------------------------------
# Script invocation test (M4 — ensures the script itself works as a subprocess)
# ---------------------------------------------------------------------------


def test_validate_contracts_script_passes() -> None:
    """The validate-contracts.py script must exit 0 when fixtures are valid."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "validate-contracts.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"validate-contracts.py failed (exit {result.returncode}):\n{result.stderr}"
    )
    assert "PASS" in result.stdout, f"Expected PASS in stdout, got: {result.stdout}"
