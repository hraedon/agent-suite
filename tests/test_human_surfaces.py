from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_suite.human_surfaces import (
    HumanRole,
    STATUS_VOCABULARY,
    SupportLevel,
    SurfaceArea,
    SurfaceRisk,
    area_label,
    load_registry,
)


REGISTRY = Path(__file__).resolve().parent.parent / "data" / "contracts" / "human-surfaces.json"


def test_registry_covers_closed_vocabularies() -> None:
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert set(raw["area_values"]) == {item.value for item in SurfaceArea}
    assert set(raw["role_values"]) == {item.value for item in HumanRole}
    assert set(raw["risk_values"]) == {item.value for item in SurfaceRisk}
    assert set(raw["support_values"]) == {item.value for item in SupportLevel}
    assert tuple(raw["status_vocabulary"]) == STATUS_VOCABULARY


def test_registry_loads_all_six_areas_with_unique_routes() -> None:
    registry = load_registry(REGISTRY)
    assert {route.area for route in registry.routes} == set(SurfaceArea)
    assert len({route.ident for route in registry.routes}) == len(registry.routes)
    assert len({route.path for route in registry.routes}) == len(registry.routes)
    assert {area_label(area) for area in SurfaceArea} == {
        "Work", "Knowledge", "Activity", "Evidence", "Operations", "Administration"
    }


def test_registry_rejects_unknown_role(tmp_path: Path) -> None:
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    raw["routes"][0]["roles"] = ["superuser"]
    bad = tmp_path / "registry.json"
    bad.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown value"):
        load_registry(bad)


def test_registry_does_not_overstate_unimplemented_surfaces() -> None:
    registry = load_registry(REGISTRY)
    planned = {route.ident for route in registry.routes if route.support is SupportLevel.PLANNED}
    assert "knowledge.index" in planned
    assert "operations.estate" in planned
    assert "evidence.cases" in planned


def test_registry_names_every_provider_and_keeps_host_authority_out_of_browser() -> None:
    registry = load_registry(REGISTRY)
    assert {route.owning_component for route in registry.routes} == {
        "agent-capability-broker",
        "agent-notes",
        "agent-provenance",
        "agent-suite",
        "agent-wake",
        "dossier",
        "regista",
    }
    assert all(route.risk is not SurfaceRisk.HOST_AUTHORITY for route in registry.routes)
