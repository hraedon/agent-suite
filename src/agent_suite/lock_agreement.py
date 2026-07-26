"""Cross-repo lock-agreement check (Plan 019 B2-generalize).

Each suite member that develops against the spine vendors a face-local
``SUITE.lock`` with a ``[spine]`` block pinning the released regista version it
composes with. The B2 pilot made each face-local lock the in-repo source of
truth but synced it to the umbrella ``agent-suite/SUITE.lock`` *by convention
only*. This module is the deferred **mechanical** enforcement: every member's
``[spine]`` must AGREE with the umbrella ``[components.regista]`` — same
``version``, same ``revision`` (the SHA the release was cut from).

Additionally validates member identity: a face-local lock's ``[component]``
name and version must match the umbrella's ``[components.<member>]`` entry.

Pure + stdlib-only (``tomllib``), per the thin-orchestration charter: all lock
text is passed in; no I/O, no git shelling. ``scripts/check-lock-agreement.py``
is the thin wrapper that reads the umbrella lock + the checked-out siblings and
calls :func:`check_all`.

A member with no ``SUITE.lock`` or no ``[spine]`` (e.g. agent-wake, which has no
regista dependency) is reported ``no-spine`` — informational, not a failure,
unless ``strict`` mode is enabled and the member is in the umbrella's
``[components]`` table (meaning it is expected to carry a lock). The spine
itself (regista) is never checked against itself.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import Enum


class AgreementStatus(Enum):
    """The closed set of per-member agreement outcomes."""

    AGREE = "agree"
    DISAGREE = "disagree"
    NO_SPINE = "no-spine"
    MISSING_LOCK = "missing-lock"
    IDENTITY_MISMATCH = "identity-mismatch"


@dataclass(frozen=True)
class SpineAgreement:
    """One member's agreement with the umbrella spine pin.

    ``status`` is ``DISAGREE`` only when a ``[spine]`` exists but its version or
    sha differs from the umbrella ``[components.regista]``. ``NO_SPINE`` means no
    lock / no ``[spine]`` — not a failure. ``MISSING_LOCK`` means the member is
    expected to carry a lock (it appears in the umbrella ``[components]``) but
    none was found. ``IDENTITY_MISMATCH`` means the face-local ``[component]``
    name or version disagrees with the umbrella entry.
    """

    member: str
    status: AgreementStatus
    detail: str


def umbrella_regista_pin(umbrella_lock_text: str) -> tuple[str, str]:
    """Return the umbrella ``[components.regista]`` ``(version, revision)``.

    Raises ``ValueError`` if the umbrella lock has no regista component or it
    lacks a version/revision — a suite lock without a pinned spine is invalid.
    """
    data = tomllib.loads(umbrella_lock_text)
    regista = data.get("components", {}).get("regista")
    if not isinstance(regista, dict):
        raise ValueError("umbrella SUITE.lock has no [components.regista]")
    version = regista.get("version")
    revision = regista.get("revision")
    if not isinstance(version, str) or not isinstance(revision, str):
        raise ValueError(
            "umbrella [components.regista] must have a string version and revision"
        )
    return version, revision


def _umbrella_component_pins(
    umbrella_lock_text: str,
) -> dict[str, dict[str, str]]:
    """Return the umbrella ``[components]`` table as ``{name: {version, revision}}``."""
    data = tomllib.loads(umbrella_lock_text)
    components = data.get("components", {})
    result: dict[str, dict[str, str]] = {}
    for name, entry in components.items():
        if isinstance(entry, dict):
            result[name] = {
                k: v for k, v in entry.items() if isinstance(v, str)
            }
    return result


def spine_from_text(lock_text: str) -> tuple[str, str] | None:
    """Return a face-local ``[spine]`` ``(version, sha)``, or ``None`` if absent."""
    data = tomllib.loads(lock_text)
    spine = data.get("spine")
    if not isinstance(spine, dict):
        return None
    version = spine.get("version")
    sha = spine.get("sha")
    if not isinstance(version, str) or not isinstance(sha, str):
        return None
    return version, sha


def _component_identity_from_text(lock_text: str) -> tuple[str, str] | None:
    """Return a face-local ``[component]`` ``(name, version)``, or ``None``."""
    data = tomllib.loads(lock_text)
    component = data.get("component")
    if not isinstance(component, dict):
        return None
    name = component.get("name")
    version = component.get("version")
    if not isinstance(name, str) or not isinstance(version, str):
        return None
    return name, version


def check_member(
    member: str,
    umbrella_version: str,
    umbrella_revision: str,
    member_lock_text: str | None,
    *,
    umbrella_component: dict[str, str] | None = None,
    strict: bool = False,
) -> SpineAgreement:
    """Compare one member's face-local ``[spine]`` to the umbrella regista pin.

    When ``umbrella_component`` is provided, also validates that the face-local
    ``[component]`` name and version match the umbrella entry. When ``strict``
    is True, a missing lock for a member that appears in the umbrella
    ``[components]`` table is reported as ``MISSING_LOCK`` (a failure) instead
    of ``NO_SPINE`` (informational).
    """
    if member_lock_text is None:
        if strict and umbrella_component is not None:
            return SpineAgreement(
                member,
                AgreementStatus.MISSING_LOCK,
                "no SUITE.lock (member is in the umbrella [components] table)",
            )
        return SpineAgreement(member, AgreementStatus.NO_SPINE, "no SUITE.lock")

    if umbrella_component is not None:
        identity = _component_identity_from_text(member_lock_text)
        if identity is not None:
            local_name, local_version = identity
            identity_problems: list[str] = []
            if local_name != member:
                identity_problems.append(
                    f"[component].name {local_name!r} != expected {member!r}"
                )
            umbrella_version_for_member = umbrella_component.get("version")
            if (
                umbrella_version_for_member is not None
                and local_version != umbrella_version_for_member
            ):
                identity_problems.append(
                    f"[component].version {local_version} != umbrella "
                    f"{umbrella_version_for_member}"
                )
            if identity_problems:
                return SpineAgreement(
                    member,
                    AgreementStatus.IDENTITY_MISMATCH,
                    "; ".join(identity_problems),
                )

    spine = spine_from_text(member_lock_text)
    if spine is None:
        return SpineAgreement(
            member, AgreementStatus.NO_SPINE, "SUITE.lock has no [spine]"
        )
    version, sha = spine
    problems: list[str] = []
    if version != umbrella_version:
        problems.append(f"version {version} != umbrella {umbrella_version}")
    if sha != umbrella_revision:
        problems.append(f"sha {sha[:8]} != umbrella revision {umbrella_revision[:8]}")
    if problems:
        return SpineAgreement(member, AgreementStatus.DISAGREE, "; ".join(problems))
    return SpineAgreement(
        member, AgreementStatus.AGREE, f"regista {version} @ {sha[:8]}"
    )


def check_all(
    umbrella_lock_text: str,
    member_locks: dict[str, str | None],
    *,
    strict: bool = False,
) -> list[SpineAgreement]:
    """Check every member's ``[spine]`` against the umbrella regista pin.

    ``member_locks`` maps member ident → its face-local ``SUITE.lock`` text (or
    ``None`` if the member has no lock). The spine (regista) is skipped if
    present — it is never checked against itself. Results are sorted by member.

    When ``strict`` is True, also validates member identity (``[component]``
    name/version against the umbrella ``[components]`` entry) and reports
    missing locks for umbrella-listed members as ``MISSING_LOCK`` failures.
    """
    umbrella_version, umbrella_revision = umbrella_regista_pin(umbrella_lock_text)
    component_pins = _umbrella_component_pins(umbrella_lock_text)
    results: list[SpineAgreement] = []
    for member in sorted(member_locks):
        if member == "regista":
            continue
        results.append(
            check_member(
                member,
                umbrella_version,
                umbrella_revision,
                member_locks[member],
                umbrella_component=component_pins.get(member),
                strict=strict,
            )
        )
    return results


def has_disagreement(results: list[SpineAgreement]) -> bool:
    """True if any member's ``[spine]`` disagrees with the umbrella."""
    return any(r.status is AgreementStatus.DISAGREE for r in results)


def has_failure(results: list[SpineAgreement]) -> bool:
    """True if any member has a failing status (disagreement, missing lock,
    or identity mismatch)."""
    return any(
        r.status
        in (
            AgreementStatus.DISAGREE,
            AgreementStatus.MISSING_LOCK,
            AgreementStatus.IDENTITY_MISMATCH,
        )
        for r in results
    )


def format_report(
    results: list[SpineAgreement], umbrella_version: str, umbrella_revision: str
) -> str:
    """Human-readable agreement report."""
    lines = [
        "cross-repo lock-agreement (Plan 019 B2-generalize)",
        f"umbrella [components.regista]: {umbrella_version} @ {umbrella_revision[:8]}",
        "",
    ]
    for r in results:
        mark = {
            AgreementStatus.AGREE: "ok  ",
            AgreementStatus.DISAGREE: "FAIL",
            AgreementStatus.NO_SPINE: "n/a ",
            AgreementStatus.MISSING_LOCK: "FAIL",
            AgreementStatus.IDENTITY_MISMATCH: "FAIL",
        }[r.status]
        lines.append(f"  [{mark}] {r.member:<28} {r.detail}")
    if has_failure(results):
        lines.append("")
        lines.append("FAILURE: one or more members disagree with the umbrella lock.")
    return "\n".join(lines)
