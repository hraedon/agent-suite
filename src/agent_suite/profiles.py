"""Deployment profiles and the feature matrix — the single source of truth.

Plan 008 §3 defines three cumulative deployment profiles (A, B, C). Plan 008 §4
defines the end-state feature contract. This module is the one place that
enumerates profiles, their required components, and the feature matrix —
``doctor``, ``deploy``, docs, and release metadata all consume or validate
against it (WI-0.1 AC: no independent hard-coded list per surface).

``assert_never`` over every closed-set enum (Profile, Maturity). stdlib-only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import assert_never


class Profile(Enum):
    """Deployment profile — a named tier of required components (Plan 008 §3)."""

    A = "A"
    B = "B"
    C = "C"


class Maturity(Enum):
    """Feature maturity state (Plan 008 §4 / WI-0.1).

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in any dispatch.
    """

    EXPERIMENTAL = "experimental"
    SUPPORTED = "supported"
    DEPRECATED = "deprecated"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Feature:
    """One row of the feature matrix — what it is, how mature, which profiles,
    and which components provide it.

    ``profiles`` is the minimum profile where the feature is available.
    Since profiles are cumulative (B ⊇ A, C ⊇ B), a feature assigned to
    Profile A is also available in B and C.
    """

    name: str
    description: str
    maturity: Maturity
    profiles: frozenset[Profile]
    providing_components: frozenset[str]


@dataclass(frozen=True)
class ProfileClassification:
    """Result of classifying a doctor snapshot against the profile matrix.

    ``profile`` is the highest profile whose requirements are fully satisfied
    (or ``None`` if even Profile A is not met). ``missing_required`` are
    required components for the reference profile that are absent.
    ``extra_optional`` are installed components not required by the reference
    profile.
    """

    profile: Profile | None
    missing_required: list[str]
    extra_optional: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value if self.profile is not None else None,
            "missing_required": list(self.missing_required),
            "extra_optional": list(self.extra_optional),
        }


PROFILE_DESCRIPTIONS: dict[Profile, str] = {
    Profile.A: (
        "Provenance core: signed durable work/knowledge state, the agent face, "
        "harness capture, offline verification, bootstrap, lock, doctor, "
        "backup, and upgrade operations."
    ),
    Profile.B: (
        "Team workflow: Profile A plus authenticated human work/review views, "
        "knowledge reading, session/tool trails, key operations, and human "
        "acceptance flows."
    ),
    Profile.C: (
        "Operated full suite: Profile B plus declared capability parity, "
        "credential injection, external signaling, human delivery, and "
        "health/assurance alerting."
    ),
}


PROFILE_REQUIREMENTS: dict[Profile, frozenset[str]] = {
    Profile.A: frozenset({"regista", "agent-notes", "agent-provenance"}),
    Profile.B: frozenset({"regista", "agent-notes", "agent-provenance", "dossier"}),
    Profile.C: frozenset(
        {
            "regista",
            "agent-notes",
            "agent-provenance",
            "dossier",
            "agent-capability-broker",
            "agent-wake",
        }
    ),
}


FEATURE_MATRIX: tuple[Feature, ...] = (
    Feature(
        name="Durable event log and replay verification",
        description=(
            "Append-only, replay-verifiable event and global chains with "
            "explicit schema/workflow/envelope compatibility."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"regista"}),
    ),
    Feature(
        name="Per-principal asymmetric signing",
        description=(
            "Enrollment, rotation, revocation, and signer/principal binding "
            "with delegation and session identity."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"regista"}),
    ),
    Feature(
        name="Agent face (CLI)",
        description=(
            "Agent face for work creation, assignment, progress, deferral, "
            "review, and knowledge."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"agent-notes"}),
    ),
    Feature(
        name="Harness capture and attestation",
        description=(
            "Session start/resume/stop and tool begin/end capture with stable "
            "correlation under concurrent tools and subagents."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"agent-provenance"}),
    ),
    Feature(
        name="Offline bundle verification",
        description=(
            "Offline bundle verification with a human-readable verification "
            "report and independent recomputation."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"agent-provenance"}),
    ),
    Feature(
        name="Bootstrap, lock, doctor",
        description=(
            "Ordered idempotent install, compatibility lock, health umbrella, "
            "backup, and upgrade operations."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.A}),
        providing_components=frozenset({"agent-suite"}),
    ),
    Feature(
        name="Human web face",
        description=(
            "Authenticated human work and review views with server-rendered "
            "core flows and knowledge reading."
        ),
        maturity=Maturity.SUPPORTED,
        profiles=frozenset({Profile.B}),
        providing_components=frozenset({"dossier"}),
    ),
    Feature(
        name="Review queues and human acceptance",
        description=(
            "Review queues, assigned-work views, and human acceptance flows "
            "with separation-of-duties enforcement."
        ),
        maturity=Maturity.EXPERIMENTAL,
        profiles=frozenset({Profile.B}),
        providing_components=frozenset({"dossier"}),
    ),
    Feature(
        name="Capability parity and credential injection",
        description=(
            "Declared capability parity with secret-safe credential injection "
            "and provenance for every acting operation."
        ),
        maturity=Maturity.EXPERIMENTAL,
        profiles=frozenset({Profile.C}),
        providing_components=frozenset({"agent-capability-broker"}),
    ),
    Feature(
        name="External signaling and delivery",
        description=(
            "Authenticated ingress, routing, and human webhook/email delivery "
            "with replay protection and dead-letter visibility."
        ),
        maturity=Maturity.EXPERIMENTAL,
        profiles=frozenset({Profile.C}),
        providing_components=frozenset({"agent-wake"}),
    ),
)


def profile_label(profile: Profile) -> str:
    """Human-readable short label for a Profile (used in doctor text output)."""
    match profile:
        case Profile.A:
            return "A (Provenance core)"
        case Profile.B:
            return "B (Team workflow)"
        case Profile.C:
            return "C (Operated full suite)"
        case other:
            assert_never(other)


def maturity_label(maturity: Maturity) -> str:
    """Human-readable label for a Maturity (used in feature-matrix rendering)."""
    match maturity:
        case Maturity.EXPERIMENTAL:
            return "experimental"
        case Maturity.SUPPORTED:
            return "supported"
        case Maturity.DEPRECATED:
            return "deprecated"
        case Maturity.UNSUPPORTED:
            return "unsupported"
        case other:
            assert_never(other)


def profile_for_components(installed_idents: set[str]) -> Profile | None:
    """Return the highest profile whose requirements are all satisfied, or None.

    Profiles are cumulative (B ⊇ A, C ⊇ B), so iterating from C down to A and
    returning the first match yields the highest satisfied profile.
    """
    for profile in (Profile.C, Profile.B, Profile.A):
        if PROFILE_REQUIREMENTS[profile] <= installed_idents:
            return profile
    return None


def classify_doctor(
    component_statuses: dict[str, str],
    *,
    reference_profile: Profile | None = None,
) -> ProfileClassification:
    """Classify a doctor snapshot against the profile matrix.

    ``component_statuses`` maps component idents to their doctor status strings
    (e.g. ``"ok"``, ``"absent"``, ``"remote"``, ``"not_configured"``). A
    component is considered installed when its status indicates the component
    is actually available — ``"ok"``, ``"degraded"``, ``"remote"``, or
    ``"unreachable"`` (the last is installed but broken, not absent).
    ``"absent"`` and ``"not_configured"`` (Plan 004 WI-1.6) mean the component
    is not available for profile purposes.

    When ``reference_profile`` is provided (e.g. from ``--profile C``), the
    classification uses that profile as the reference: ``missing_required``
    lists the reference profile's required components that are absent, and
    ``extra_optional`` lists installed components beyond the reference. When
    ``reference_profile`` is ``None``, the reference is auto-detected (the
    highest profile whose requirements are satisfied, or Profile A if none).
    """
    unavailable = {"absent", "not_configured"}
    installed = {
        ident for ident, status in component_statuses.items() if status not in unavailable
    }
    profile = profile_for_components(installed)
    reference = reference_profile if reference_profile is not None else (profile if profile is not None else Profile.A)
    required = PROFILE_REQUIREMENTS[reference]
    missing_required = sorted(required - installed)
    extra_optional = sorted(installed - required)
    return ProfileClassification(
        profile=profile,
        missing_required=missing_required,
        extra_optional=extra_optional,
    )
