#!/usr/bin/env python3
"""Validate Plan 009 WI-0.2 shared contract conformance fixtures.

Loads each JSON fixture in ``data/contracts/`` and validates:

1. **Meta-structure** — each fixture has contract, version, description,
   owned_by, consumers, and invariants fields.

2. **Cross-references** (health contract only) — declared enums are compared
   against live Python enums in the agent-suite codebase. This catches
   semantic drift: if someone adds a ComponentStatus value in code but forgets
   to update the health contract fixture (or vice versa), this fails.

3. **Snapshot assertions** (lifecycle, identity, install-harness, notification)
   — declared enums are compared against hardcoded expected values. These are
   NOT live cross-references because the owning components (regista, cairn,
   agent-wake) are not installed in the lint-and-test CI job. Real
   cross-references for these contracts require the interop CI job where the
   components are installed. The snapshot assertions still provide value: they
   document the expected values and fail if someone changes the fixture without
   updating the assertion.

4. **Referential integrity** (lifecycle) — transition from/to values are
   validated against the states list, and allowed_roles against the roles list.

5. **Partition validation** (notification) — supported/partial/absent delivery
   mode sub-lists are validated to partition the full delivery_modes set.

Stdlib-only (AGENTS.md: deterministic, stdlib-first core).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

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
    "memory-provider",
    "human-surfaces",
    "windows-setup",
)


def _load_fixture(name: str) -> dict[str, Any]:
    path = CONTRACTS_DIR / f"{name}.json"
    if not path.exists():
        raise ValueError(f"contract fixture missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"contract fixture {name}: invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"contract fixture {name}: root must be a JSON object")
    return data


def _validate_meta(name: str, fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in REQUIRED_META_FIELDS:
        if field not in fixture:
            errors.append(f"{name}: missing required meta-field '{field}'")
    if "version" in fixture:
        v = fixture["version"]
        if not isinstance(v, str) or v.count(".") < 2:
            errors.append(f"{name}: version should be semver (got {v!r})")
    if "consumers" in fixture:
        c = fixture["consumers"]
        if not isinstance(c, list) or not c:
            errors.append(f"{name}: consumers must be a non-empty list")
    if "invariants" in fixture:
        inv = fixture["invariants"]
        if not isinstance(inv, list) or not inv:
            errors.append(f"{name}: invariants must be a non-empty list")
    return errors


def _enum_values(enum_cls: Any) -> set[str]:
    return {e.value for e in enum_cls}


# ---------------------------------------------------------------------------
# Cross-references — health contract against live agent-suite Python enums
# ---------------------------------------------------------------------------


def _cross_reference_health(fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    from agent_suite.doctor import ComponentStatus
    from agent_suite.components import Locality, Tier
    from agent_suite.key_watch import KeyAgeStatus, StoreGrowthStatus
    from agent_suite.lock import DriftKind
    from agent_suite.verify_restore import ProjectVerifyStatus

    contract_statuses = set(fixture.get("component_status_values", []))
    code_statuses = _enum_values(ComponentStatus)
    if contract_statuses != code_statuses:
        errors.append(
            f"health: component_status_values mismatch — "
            f"contract={sorted(contract_statuses)}, code={sorted(code_statuses)}"
        )

    contract_tiers = set(fixture.get("tier_values", []))
    code_tiers = _enum_values(Tier)
    if contract_tiers != code_tiers:
        errors.append(
            f"health: tier_values mismatch — "
            f"contract={sorted(contract_tiers)}, code={sorted(code_tiers)}"
        )

    contract_localities = set(fixture.get("locality_values", []))
    code_localities = _enum_values(Locality)
    if contract_localities != code_localities:
        errors.append(
            f"health: locality_values mismatch — "
            f"contract={sorted(contract_localities)}, code={sorted(code_localities)}"
        )

    contract_drift_kinds = set(fixture.get("drift_kind_values", []))
    code_drift_kinds = _enum_values(DriftKind)
    if contract_drift_kinds != code_drift_kinds:
        errors.append(
            f"health: drift_kind_values mismatch — "
            f"contract={sorted(contract_drift_kinds)}, code={sorted(code_drift_kinds)}"
        )

    contract_verify_statuses = set(fixture.get("verify_restore_status_values", []))
    code_verify_statuses = _enum_values(ProjectVerifyStatus)
    if contract_verify_statuses != code_verify_statuses:
        errors.append(
            f"health: verify_restore_status_values mismatch — "
            f"contract={sorted(contract_verify_statuses)}, code={sorted(code_verify_statuses)}"
        )

    contract_key_age = set(fixture.get("key_age_status_values", []))
    code_key_age = _enum_values(KeyAgeStatus)
    if contract_key_age != code_key_age:
        errors.append(
            f"health: key_age_status_values mismatch — "
            f"contract={sorted(contract_key_age)}, code={sorted(code_key_age)}"
        )

    contract_store_growth = set(fixture.get("store_growth_status_values", []))
    code_store_growth = _enum_values(StoreGrowthStatus)
    if contract_store_growth != code_store_growth:
        errors.append(
            f"health: store_growth_status_values mismatch — "
            f"contract={sorted(contract_store_growth)}, code={sorted(code_store_growth)}"
        )

    return errors


# ---------------------------------------------------------------------------
# Snapshot assertions — validate against documented expected values
# (owning components not installed in lint-and-test CI job)
# ---------------------------------------------------------------------------


def _snapshot_lifecycle(fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    contract_states = set(fixture.get("states", []))
    expected_states = {
        "open", "in_progress", "blocked", "deferred",
        "in_review", "in_human_review", "done",
    }
    if contract_states != expected_states:
        errors.append(
            f"lifecycle: states mismatch — "
            f"contract={sorted(contract_states)}, expected={sorted(expected_states)}"
        )

    contract_roles = set(fixture.get("roles", []))
    expected_roles = {"human", "agent", "system"}
    if contract_roles != expected_roles:
        errors.append(
            f"lifecycle: roles mismatch — "
            f"contract={sorted(contract_roles)}, expected={sorted(expected_roles)}"
        )

    terminal = set(fixture.get("terminal_states", []))
    if terminal != {"done"}:
        errors.append(f"lifecycle: terminal_states should be ['done'], got {sorted(terminal)}")

    # Referential integrity — transition from/to must be in states,
    # allowed_roles must be in roles.
    states = set(fixture.get("states", []))
    roles = set(fixture.get("roles", []))
    seen: set[tuple[str, str, str]] = set()
    for t in fixture.get("transitions", []):
        if not isinstance(t, dict):
            errors.append(f"lifecycle: transition is not a dict: {t!r}")
            continue
        name = t.get("name", "")
        from_state = t.get("from", "")
        to_state = t.get("to", "")
        key = (name, from_state, to_state)
        if key in seen:
            errors.append(f"lifecycle: duplicate transition {key!r}")
        seen.add(key)
        if from_state not in states:
            errors.append(
                f"lifecycle: transition {name!r} has invalid 'from': {from_state!r}"
            )
        if to_state not in states:
            errors.append(
                f"lifecycle: transition {name!r} has invalid 'to': {to_state!r}"
            )
        for role in t.get("allowed_roles", []):
            if role not in roles:
                errors.append(
                    f"lifecycle: transition {name!r} has invalid role: {role!r}"
                )

    return errors


def _snapshot_identity(fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    actor_kinds = set(fixture.get("actor_kinds", []))
    expected = {"human", "agent", "system"}
    if actor_kinds != expected:
        errors.append(
            f"identity: actor_kinds mismatch — "
            f"contract={sorted(actor_kinds)}, expected={sorted(expected)}"
        )

    signing_schemes = set(fixture.get("signing_schemes", []))
    expected_schemes = {"hmac", "ed25519"}
    if signing_schemes != expected_schemes:
        errors.append(
            f"identity: signing_schemes mismatch — "
            f"contract={sorted(signing_schemes)}, expected={sorted(expected_schemes)}"
        )

    key_statuses = set(fixture.get("principal_key_statuses", []))
    expected_statuses = {"active", "revoked"}
    if key_statuses != expected_statuses:
        errors.append(
            f"identity: principal_key_statuses mismatch — "
            f"contract={sorted(key_statuses)}, expected={sorted(expected_statuses)}"
        )

    return errors


def _snapshot_install_harness(fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    hook_events = set(fixture.get("hook_events", []))
    expected_hooks = {"SessionStart", "SessionStop", "ToolBegin", "ToolEnd"}
    if hook_events != expected_hooks:
        errors.append(
            f"install-harness: hook_events mismatch — "
            f"contract={sorted(hook_events)}, expected={sorted(expected_hooks)}"
        )

    return errors


def _snapshot_notification(fixture: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    delivery_modes = set(fixture.get("delivery_modes", []))
    expected = {
        "live_wake", "silent_inject", "next_session",
        "managed_session", "webhook", "email",
    }
    if delivery_modes != expected:
        errors.append(
            f"notification: delivery_modes mismatch — "
            f"contract={sorted(delivery_modes)}, expected={sorted(expected)}"
        )

    # Partition validation — supported + partial + absent must equal delivery_modes
    all_modes = set(fixture.get("delivery_modes", []))
    categorized = (
        set(fixture.get("supported_delivery_modes", []))
        | set(fixture.get("partial_delivery_modes", []))
        | set(fixture.get("absent_delivery_modes", []))
    )
    if all_modes != categorized:
        missing_from_subs = all_modes - categorized
        extra_in_subs = categorized - all_modes
        if missing_from_subs:
            errors.append(
                f"notification: delivery modes not in any sub-list: "
                f"{sorted(missing_from_subs)}"
            )
        if extra_in_subs:
            errors.append(
                f"notification: sub-lists contain modes not in delivery_modes: "
                f"{sorted(extra_in_subs)}"
            )

    # No mode should appear in two sub-lists
    supported = set(fixture.get("supported_delivery_modes", []))
    partial = set(fixture.get("partial_delivery_modes", []))
    absent = set(fixture.get("absent_delivery_modes", []))
    overlap_sp = supported & partial
    overlap_sa = supported & absent
    overlap_pa = partial & absent
    if overlap_sp:
        errors.append(f"notification: modes in both supported and partial: {sorted(overlap_sp)}")
    if overlap_sa:
        errors.append(f"notification: modes in both supported and absent: {sorted(overlap_sa)}")
    if overlap_pa:
        errors.append(f"notification: modes in both partial and absent: {sorted(overlap_pa)}")

    return errors


def _cross_reference_human_surfaces(fixture: dict[str, Any]) -> list[str]:
    from agent_suite.human_surfaces import (
        HumanRole,
        STATUS_VOCABULARY,
        SupportLevel,
        SurfaceArea,
        SurfaceRisk,
        load_registry,
    )

    errors: list[str] = []
    expected = {
        "area_values": _enum_values(SurfaceArea),
        "role_values": _enum_values(HumanRole),
        "risk_values": _enum_values(SurfaceRisk),
        "support_values": _enum_values(SupportLevel),
    }
    for field, code_values in expected.items():
        contract_values = set(fixture.get(field, []))
        if contract_values != code_values:
            errors.append(
                f"human-surfaces: {field} mismatch — "
                f"contract={sorted(contract_values)}, code={sorted(code_values)}"
            )
    if fixture.get("status_vocabulary") != list(STATUS_VOCABULARY):
        errors.append("human-surfaces: status_vocabulary mismatch")
    try:
        load_registry(CONTRACTS_DIR / "human-surfaces.json")
    except ValueError as exc:
        errors.append(f"human-surfaces: {exc}")
    return errors


def _cross_reference_windows_setup(fixture: dict[str, Any]) -> list[str]:
    from agent_suite.windows_setup import (
        PROTOCOL_VERSION,
        ActionState,
        PlanState,
        PreflightState,
        ProbeState,
        ReceiptState,
        SetupOperation,
    )
    from agent_suite.profiles import Profile

    errors: list[str] = []
    expected = {
        "profile_values": _enum_values(Profile),
        "probe_state_values": _enum_values(ProbeState),
        "preflight_state_values": _enum_values(PreflightState),
        "operation_values": _enum_values(SetupOperation),
        "plan_state_values": _enum_values(PlanState),
        "action_state_values": _enum_values(ActionState),
        "receipt_state_values": _enum_values(ReceiptState),
    }
    for field, code_values in expected.items():
        contract_values = set(fixture.get(field, []))
        if contract_values != code_values:
            errors.append(
                f"windows-setup: {field} mismatch — "
                f"contract={sorted(contract_values)}, code={sorted(code_values)}"
            )
    if fixture.get("protocol_version") != PROTOCOL_VERSION:
        errors.append("windows-setup: protocol_version mismatch")
    return errors


_VALIDATORS = {
    "health": _cross_reference_health,
    "lifecycle": _snapshot_lifecycle,
    "identity": _snapshot_identity,
    "install-harness": _snapshot_install_harness,
    "notification": _snapshot_notification,
    "human-surfaces": _cross_reference_human_surfaces,
    "windows-setup": _cross_reference_windows_setup,
}


def main(argv: list[str] | None = None) -> int:
    args = argv or []
    if args and args != ["--check"]:
        print(f"Unknown arguments: {args}", file=sys.stderr)
        return 2

    errors: list[str] = []

    discovered = {p.stem for p in CONTRACTS_DIR.glob("*.json")}
    missing = set(EXPECTED_CONTRACTS) - discovered
    extra = discovered - set(EXPECTED_CONTRACTS)
    if missing:
        errors.append(f"missing contract fixtures: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected contract fixtures: {sorted(extra)}")

    for name in EXPECTED_CONTRACTS:
        if name not in discovered:
            continue
        fixture = _load_fixture(name)
        errors.extend(_validate_meta(name, fixture))

        validator = _VALIDATORS.get(name)
        if validator is not None:
            errors.extend(validator(fixture))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Contract validation: PASS — {len(EXPECTED_CONTRACTS)} fixtures validated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
