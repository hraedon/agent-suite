"""The six suite components, as a declarative descriptor.

This is the single place that enumerates what the suite is made of. `doctor`,
`lock`, and `bootstrap` all read this rather than hardcoding component names, so
adding or retiring a component is one edit here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Tier(Enum):
    """Deployment tier — decides bootstrap ordering and whether absence is a failure."""

    SPINE = "spine"  # regista — the store everything else is a client of
    FACE = "face"  # dossier, agent-notes, cairn — the irreducible auditable core
    PLUMBING = "plumbing"  # acb, agent-wake — optional for a first deployment


@dataclass(frozen=True)
class Component:
    """One suite member. `doctor_cmd` is the invocation whose --json output the
    umbrella aggregates; `repo` is the pin target recorded in SUITE.lock."""

    ident: str
    repo: str
    tier: Tier
    doctor_cmd: tuple[str, ...]


COMPONENTS: tuple[Component, ...] = (
    Component("regista", "hraedon/regista", Tier.SPINE, ("regista", "doctor", "--json")),
    Component("dossier", "hraedon/dossier", Tier.FACE, ("dossier", "doctor", "--json")),
    Component("agent-notes", "hraedon/agent-notes", Tier.FACE, ("agent-notes", "doctor", "--json")),
    Component(
        "agent-provenance",
        "hraedon/agent-provenance",
        Tier.FACE,
        ("cairn", "doctor", "--json"),
    ),
    Component(
        "agent-capability-broker",
        "hraedon/agent-capability-broker",
        Tier.PLUMBING,
        ("acb", "doctor", "--json"),
    ),
    Component(
        "agent-wake", "hraedon/agent-wake", Tier.PLUMBING, ("agent-wake", "doctor", "--json")
    ),
)
