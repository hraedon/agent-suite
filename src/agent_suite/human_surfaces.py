"""Typed validation for the suite human-surface registry.

The JSON fixture is the cross-repository source of truth.  This module keeps
agent-suite's validation stdlib-only and gives consumers closed vocabularies
without making agent-suite a UI implementation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import assert_never


class SurfaceArea(Enum):
    WORK = "work"
    KNOWLEDGE = "knowledge"
    ACTIVITY = "activity"
    EVIDENCE = "evidence"
    OPERATIONS = "operations"
    ADMINISTRATION = "administration"


class HumanRole(Enum):
    COLLABORATOR = "collaborator"
    REVIEWER = "reviewer"
    AUDITOR = "auditor"
    SECURITY_ADMINISTRATOR = "security_administrator"
    SUITE_OPERATOR = "suite_operator"


class SurfaceRisk(Enum):
    READ_ONLY = "read_only"
    ROUTINE_MUTATION = "routine_mutation"
    PROTECTED_MUTATION = "protected_mutation"
    HOST_AUTHORITY = "host_authority"


class SupportLevel(Enum):
    SUPPORTED = "supported"
    PROTOTYPE = "prototype"
    PLANNED = "planned"
    EXTERNAL_ARTIFACT = "external_artifact"


STATUS_VOCABULARY: tuple[str, ...] = (
    "ok",
    "warning",
    "failed",
    "unknown",
    "unsupported",
    "unreachable",
    "not_configured",
)


@dataclass(frozen=True)
class SurfaceRoute:
    ident: str
    area: SurfaceArea
    path: str
    roles: frozenset[HumanRole]
    owning_component: str
    provider_operation: str
    risk: SurfaceRisk
    support: SupportLevel
    proof: str


@dataclass(frozen=True)
class HumanSurfaceRegistry:
    version: str
    routes: tuple[SurfaceRoute, ...]


def _enum_value(enum_type: type[Enum], raw: object, field: str) -> Enum:
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be a string")
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ValueError(f"{field} has unknown value {raw!r}") from exc


def _nonempty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _parse_route(raw: object, index: int) -> SurfaceRoute:
    if not isinstance(raw, dict):
        raise ValueError(f"routes[{index}] must be an object")
    roles_raw = raw.get("roles")
    if not isinstance(roles_raw, list) or not roles_raw:
        raise ValueError(f"routes[{index}].roles must be a non-empty array")
    roles: set[HumanRole] = set()
    for role_index, role in enumerate(roles_raw):
        parsed = _enum_value(HumanRole, role, f"routes[{index}].roles[{role_index}]")
        if not isinstance(parsed, HumanRole):
            raise AssertionError("HumanRole parser returned the wrong enum")
        roles.add(parsed)
    area = _enum_value(SurfaceArea, raw.get("area"), f"routes[{index}].area")
    risk = _enum_value(SurfaceRisk, raw.get("risk"), f"routes[{index}].risk")
    support = _enum_value(SupportLevel, raw.get("support"), f"routes[{index}].support")
    if not isinstance(area, SurfaceArea):
        raise AssertionError("SurfaceArea parser returned the wrong enum")
    if not isinstance(risk, SurfaceRisk):
        raise AssertionError("SurfaceRisk parser returned the wrong enum")
    if not isinstance(support, SupportLevel):
        raise AssertionError("SupportLevel parser returned the wrong enum")
    path = _nonempty_string(raw.get("path"), f"routes[{index}].path")
    if not path.startswith("/"):
        raise ValueError(f"routes[{index}].path must start with '/'")
    return SurfaceRoute(
        ident=_nonempty_string(raw.get("id"), f"routes[{index}].id"),
        area=area,
        path=path,
        roles=frozenset(roles),
        owning_component=_nonempty_string(
            raw.get("owning_component"), f"routes[{index}].owning_component"
        ),
        provider_operation=_nonempty_string(
            raw.get("provider_operation"), f"routes[{index}].provider_operation"
        ),
        risk=risk,
        support=support,
        proof=_nonempty_string(raw.get("proof"), f"routes[{index}].proof"),
    )


def load_registry(path: Path) -> HumanSurfaceRegistry:
    """Load and validate a human-surface registry fixture."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot load human-surface registry: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError("human-surface registry root must be an object")
    version = _nonempty_string(raw.get("version"), "version")
    statuses = raw.get("status_vocabulary")
    if statuses != list(STATUS_VOCABULARY):
        raise ValueError("status_vocabulary does not match the suite vocabulary")
    routes_raw = raw.get("routes")
    if not isinstance(routes_raw, list) or not routes_raw:
        raise ValueError("routes must be a non-empty array")
    routes = tuple(_parse_route(route, index) for index, route in enumerate(routes_raw))
    ids = [route.ident for route in routes]
    if len(ids) != len(set(ids)):
        raise ValueError("route ids must be unique")
    paths = [route.path for route in routes]
    if len(paths) != len(set(paths)):
        raise ValueError("route paths must be unique")
    covered = {route.area for route in routes}
    if covered != set(SurfaceArea):
        missing = sorted(area.value for area in set(SurfaceArea) - covered)
        raise ValueError(f"registry must cover every suite area; missing={missing}")
    return HumanSurfaceRegistry(version=version, routes=routes)


def area_label(area: SurfaceArea) -> str:
    """Return the navigation label for a closed-set area."""
    match area:
        case SurfaceArea.WORK:
            return "Work"
        case SurfaceArea.KNOWLEDGE:
            return "Knowledge"
        case SurfaceArea.ACTIVITY:
            return "Activity"
        case SurfaceArea.EVIDENCE:
            return "Evidence"
        case SurfaceArea.OPERATIONS:
            return "Operations"
        case SurfaceArea.ADMINISTRATION:
            return "Administration"
        case _ as unreachable:
            assert_never(unreachable)
