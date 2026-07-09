"""The six suite components, as a declarative descriptor.

This is the single place that enumerates what the suite is made of. `doctor`,
`lock`, `bootstrap`, and `upgrade` all read this rather than hardcoding component
names, so adding or retiring a component is one edit here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import assert_never


class Tier(Enum):
    """Deployment tier — decides bootstrap ordering and whether absence is a failure."""

    SPINE = "spine"  # regista — the store everything else is a client of
    FACE = "face"  # dossier, agent-notes, cairn — the irreducible auditable core
    PLUMBING = "plumbing"  # acb, agent-wake — optional for a first deployment


class UpgradeKind(Enum):
    """How a component is upgraded (Plan 005 WI-1.1).

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in the upgrade dispatch.
    """

    PIPX = "pipx"  # pip/pipx-installed CLI — upgraded via ``pipx upgrade``
    DOCKER = "docker"  # container image — upgraded via ``docker pull``


@dataclass(frozen=True)
class Component:
    """One suite member. `doctor_cmd` is the invocation whose --json output the
    umbrella aggregates; `repo` is the pin target recorded in SUITE.lock;
    ``upgrade_kind`` / ``upgrade_package`` declare how the component is advanced
    (Plan 005 WI-1.1); ``service_unit`` names the OS service to restart after an
    upgrade (empty string if the component is not a long-running service)."""

    ident: str
    repo: str
    tier: Tier
    doctor_cmd: tuple[str, ...]
    upgrade_kind: UpgradeKind = UpgradeKind.PIPX
    upgrade_package: str = ""
    service_unit: str = ""


def _component(
    ident: str,
    repo: str,
    tier: Tier,
    doctor_cmd: tuple[str, ...],
    *,
    upgrade_kind: UpgradeKind = UpgradeKind.PIPX,
    upgrade_package: str = "",
    service_unit: str = "",
) -> Component:
    """Build a Component, defaulting upgrade_package to the CLI name (doctor_cmd[0])."""
    if not upgrade_package:
        upgrade_package = doctor_cmd[0]
    return Component(
        ident=ident,
        repo=repo,
        tier=tier,
        doctor_cmd=doctor_cmd,
        upgrade_kind=upgrade_kind,
        upgrade_package=upgrade_package,
        service_unit=service_unit,
    )


COMPONENTS: tuple[Component, ...] = (
    _component("regista", "hraedon/regista", Tier.SPINE, ("regista", "doctor", "--json")),
    _component(
        "dossier", "hraedon/dossier", Tier.FACE, ("dossier", "doctor", "--json"),
        service_unit="dossier",
    ),
    _component(
        "agent-notes", "hraedon/agent-notes", Tier.FACE, ("agent-notes", "doctor", "--json"),
        service_unit="agent-notes",
    ),
    _component(
        "agent-provenance",
        "hraedon/agent-provenance",
        Tier.FACE,
        ("cairn", "doctor", "--json"),
    ),
    _component(
        "agent-capability-broker",
        "hraedon/agent-capability-broker",
        Tier.PLUMBING,
        ("acb", "doctor", "--json"),
    ),
    _component(
        "agent-wake", "hraedon/agent-wake", Tier.PLUMBING, ("agent-wake", "doctor", "--json")
    ),
)


def component_by_ident(ident: str, components: tuple[Component, ...] = COMPONENTS) -> Component:
    """Look up a component by its identifier. Raises ``KeyError`` if not found."""
    for c in components:
        if c.ident == ident:
            return c
    raise KeyError(f"unknown component: {ident}")


def upgrade_kind_label(kind: UpgradeKind) -> str:
    """Human-readable label for an UpgradeKind (used in upgrade plan output)."""
    match kind:
        case UpgradeKind.PIPX:
            return "pipx"
        case UpgradeKind.DOCKER:
            return "docker"
        case other:
            assert_never(other)
