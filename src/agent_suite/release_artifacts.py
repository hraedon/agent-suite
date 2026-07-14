"""Machine-readable support matrix and release board for the 1.0 release.

Plan 015 §3 (WI-0.3) requires a support matrix that names exact platforms,
versions, and objectives. Plan 015 §4 (WI-0.4) requires a release board
ledger with gates, work items, owner repositories, blocking dependencies,
status, and proof command/artifact. CI, install docs, doctor profile rules,
and release metadata consume these artifacts — they are the single source
of truth for what 1.0 supports and what remains to close.

stdlib-only; ``assert_never`` over every closed-set enum.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import assert_never

from agent_suite.profiles import (
    PROFILE_DESCRIPTIONS,
    PROFILE_REQUIREMENTS,
    Profile,
)


class IdentityBackendKind(Enum):
    """Supported identity backend kinds.

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in any dispatch.
    """

    ENTRA_OIDC = "entra_oidc"
    LOCAL = "local"


class SecretBackendKind(Enum):
    """Supported secret/custody backend kinds.

    ``assert_never`` is used over this enum so a newly added kind can't be
    silently unhandled in any dispatch.
    """

    VAULT = "vault"
    AKV = "akv"
    WINDOWS_NATIVE_FILE = "windows_native_file"


class WIStatus(Enum):
    """Work item status in the release board.

    ``assert_never`` is used over this enum so a newly added status can't
    be silently unhandled in any dispatch.
    """

    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    BLOCKED = "blocked"


def identity_backend_label(kind: IdentityBackendKind) -> str:
    match kind:
        case IdentityBackendKind.ENTRA_OIDC:
            return "Entra ID / OIDC"
        case IdentityBackendKind.LOCAL:
            return "Local"
        case other:
            assert_never(other)


def secret_backend_label(kind: SecretBackendKind) -> str:
    match kind:
        case SecretBackendKind.VAULT:
            return "HashiCorp Vault"
        case SecretBackendKind.AKV:
            return "Azure Key Vault"
        case SecretBackendKind.WINDOWS_NATIVE_FILE:
            return "Windows-native / file"
        case other:
            assert_never(other)


def wi_status_label(status: WIStatus) -> str:
    match status:
        case WIStatus.NOT_STARTED:
            return "not started"
        case WIStatus.IN_PROGRESS:
            return "in progress"
        case WIStatus.COMPLETE:
            return "complete"
        case WIStatus.BLOCKED:
            return "blocked"
        case other:
            assert_never(other)


@dataclass(frozen=True)
class BrowserTarget:
    """One browser in the supported browser matrix."""

    name: str
    version: str
    status: str = "not_qualified"

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "version": self.version, "status": self.status}


@dataclass(frozen=True)
class IdentityBackend:
    """One supported identity backend with its support status."""

    kind: IdentityBackendKind
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "name": identity_backend_label(self.kind),
            "status": self.status,
        }


@dataclass(frozen=True)
class SecretBackend:
    """One supported secret/custody backend with its support status."""

    kind: SecretBackendKind
    status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "name": secret_backend_label(self.kind),
            "status": self.status,
        }


@dataclass(frozen=True)
class ProfileSupport:
    """One deployment profile with its required and optional components."""

    profile: Profile
    required_components: tuple[str, ...]
    optional_components: tuple[str, ...]
    release_status: str

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "description": PROFILE_DESCRIPTIONS[self.profile],
            "required_components": list(self.required_components),
            "optional_components": list(self.optional_components),
            "release_status": self.release_status,
        }


@dataclass(frozen=True)
class AvailabilityObjectives:
    """Measurable availability and recovery objectives for the 1.0 release."""

    backup_cadence: str
    max_rpo: str
    rto: str
    health_check_cadence: str
    key_rotation: str
    rc_soak_days: int

    def to_dict(self) -> dict[str, object]:
        return {
            "backup_cadence": self.backup_cadence,
            "max_rpo": self.max_rpo,
            "rto": self.rto,
            "health_check_cadence": self.health_check_cadence,
            "key_rotation": self.key_rotation,
            "rc_soak_days": self.rc_soak_days,
        }


@dataclass(frozen=True)
class SupportMatrix:
    """Machine-readable support matrix for the 1.0 release (Plan 015 §3, WI-0.3).

    Names exact supported platforms, versions, and objectives. Consumed by
    CI, install docs, doctor profile rules, and release metadata.
    """

    release: str
    python_versions: tuple[str, ...]
    python_versions_note: str
    postgres_version: str
    reference_linux: str
    docker: str
    kubernetes: str
    kubernetes_note: str
    windows_versions: tuple[str, ...]
    browsers: tuple[BrowserTarget, ...]
    identity_backends: tuple[IdentityBackend, ...]
    secret_backends: tuple[SecretBackend, ...]
    profiles: tuple[ProfileSupport, ...]
    availability: AvailabilityObjectives
    compatibility_window: str
    compatibility_window_note: str
    excluded_surfaces: tuple[str, ...]
    windows_qualification: str
    windows_qualification_note: str
    browsers_qualification_note: str
    identity_backends_note: str
    secret_backends_note: str
    availability_note: str

    def to_dict(self) -> dict[str, object]:
        return {
            "release": self.release,
            "python_versions": list(self.python_versions),
            "python_versions_note": self.python_versions_note,
            "postgres_version": self.postgres_version,
            "reference_linux": self.reference_linux,
            "docker": self.docker,
            "kubernetes": self.kubernetes,
            "kubernetes_note": self.kubernetes_note,
            "windows_versions": list(self.windows_versions),
            "browsers": [b.to_dict() for b in self.browsers],
            "identity_backends": [
                b.to_dict() for b in self.identity_backends
            ],
            "secret_backends": [
                b.to_dict() for b in self.secret_backends
            ],
            "profiles": [p.to_dict() for p in self.profiles],
            "availability": self.availability.to_dict(),
            "compatibility_window": self.compatibility_window,
            "compatibility_window_note": self.compatibility_window_note,
            "excluded_surfaces": list(self.excluded_surfaces),
            "windows_qualification": self.windows_qualification,
            "windows_qualification_note": self.windows_qualification_note,
            "browsers_qualification_note": self.browsers_qualification_note,
            "identity_backends_note": self.identity_backends_note,
            "secret_backends_note": self.secret_backends_note,
            "availability_note": self.availability_note,
        }

    @classmethod
    def from_json(cls, text: str) -> SupportMatrix:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("support matrix: expected a JSON object")

        release = raw.get("release")
        if not isinstance(release, str):
            raise ValueError("support matrix: release must be a string")

        py_raw = raw.get("python_versions")
        if not isinstance(py_raw, list):
            raise ValueError(
                "support matrix: python_versions must be a list"
            )
        python_versions = tuple(
            v for v in py_raw if isinstance(v, str)
        )

        postgres_version = raw.get("postgres_version")
        if not isinstance(postgres_version, str):
            raise ValueError(
                "support matrix: postgres_version must be a string"
            )

        reference_linux = raw.get("reference_linux")
        if not isinstance(reference_linux, str):
            raise ValueError(
                "support matrix: reference_linux must be a string"
            )

        docker = raw.get("docker")
        if not isinstance(docker, str):
            raise ValueError("support matrix: docker must be a string")

        kubernetes = raw.get("kubernetes", "")
        if not isinstance(kubernetes, str):
            raise ValueError("support matrix: kubernetes must be a string")

        kubernetes_note = raw.get("kubernetes_note", "")
        if not isinstance(kubernetes_note, str):
            raise ValueError(
                "support matrix: kubernetes_note must be a string"
            )

        py_note = raw.get("python_versions_note", "")
        if not isinstance(py_note, str):
            raise ValueError(
                "support matrix: python_versions_note must be a string"
            )

        win_raw = raw.get("windows_versions")
        if not isinstance(win_raw, list):
            raise ValueError(
                "support matrix: windows_versions must be a list"
            )
        windows_versions = tuple(
            v for v in win_raw if isinstance(v, str)
        )

        browsers_raw = raw.get("browsers")
        if not isinstance(browsers_raw, list):
            raise ValueError("support matrix: browsers must be a list")
        browsers: list[BrowserTarget] = []
        for b in browsers_raw:
            if not isinstance(b, dict):
                raise ValueError(
                    "support matrix: browser entry must be an object"
                )
            bname = b.get("name")
            bversion = b.get("version")
            if not isinstance(bname, str) or not isinstance(bversion, str):
                raise ValueError(
                    "support matrix: browser must have name and version"
                )
            bstatus = b.get("status", "not_qualified")
            if not isinstance(bstatus, str):
                raise ValueError(
                    "support matrix: browser status must be a string"
                )
            browsers.append(
                BrowserTarget(name=bname, version=bversion, status=bstatus)
            )

        id_raw = raw.get("identity_backends")
        if not isinstance(id_raw, list):
            raise ValueError(
                "support matrix: identity_backends must be a list"
            )
        identity_backends: list[IdentityBackend] = []
        for ib in id_raw:
            if not isinstance(ib, dict):
                raise ValueError(
                    "support matrix: identity backend must be an object"
                )
            kind_str = ib.get("kind")
            status = ib.get("status")
            if not isinstance(kind_str, str) or not isinstance(status, str):
                raise ValueError(
                    "support matrix: identity backend needs kind and status"
                )
            try:
                kind = IdentityBackendKind(kind_str)
            except ValueError as exc:
                raise ValueError(
                    f"support matrix: unknown identity backend: {kind_str}"
                ) from exc
            identity_backends.append(
                IdentityBackend(kind=kind, status=status)
            )

        sec_raw = raw.get("secret_backends")
        if not isinstance(sec_raw, list):
            raise ValueError(
                "support matrix: secret_backends must be a list"
            )
        secret_backends: list[SecretBackend] = []
        for sb in sec_raw:
            if not isinstance(sb, dict):
                raise ValueError(
                    "support matrix: secret backend must be an object"
                )
            sec_kind_str = sb.get("kind")
            status = sb.get("status")
            if not isinstance(sec_kind_str, str) or not isinstance(status, str):
                raise ValueError(
                    "support matrix: secret backend needs kind and status"
                )
            try:
                sec_kind = SecretBackendKind(sec_kind_str)
            except ValueError as exc:
                raise ValueError(
                    f"support matrix: unknown secret backend: {sec_kind_str}"
                ) from exc
            secret_backends.append(
                SecretBackend(kind=sec_kind, status=status)
            )

        profiles_raw = raw.get("profiles")
        if not isinstance(profiles_raw, list):
            raise ValueError("support matrix: profiles must be a list")
        profiles: list[ProfileSupport] = []
        for p in profiles_raw:
            if not isinstance(p, dict):
                raise ValueError(
                    "support matrix: profile entry must be an object"
                )
            profile_str = p.get("profile")
            if not isinstance(profile_str, str):
                raise ValueError(
                    "support matrix: profile entry must have profile"
                )
            try:
                profile = Profile(profile_str)
            except ValueError as exc:
                raise ValueError(
                    f"support matrix: unknown profile: {profile_str}"
                ) from exc
            req_raw = p.get("required_components")
            if not isinstance(req_raw, list):
                raise ValueError(
                    "support matrix: required_components must be a list"
                )
            required = tuple(v for v in req_raw if isinstance(v, str))
            opt_raw = p.get("optional_components")
            if not isinstance(opt_raw, list):
                raise ValueError(
                    "support matrix: optional_components must be a list"
                )
            optional = tuple(v for v in opt_raw if isinstance(v, str))
            release_status = p.get("release_status")
            if not isinstance(release_status, str):
                raise ValueError(
                    "support matrix: release_status must be a string"
                )
            profiles.append(
                ProfileSupport(
                    profile=profile,
                    required_components=required,
                    optional_components=optional,
                    release_status=release_status,
                )
            )

        avail_raw = raw.get("availability")
        if not isinstance(avail_raw, dict):
            raise ValueError(
                "support matrix: availability must be an object"
            )
        backup_cadence = avail_raw.get("backup_cadence")
        if not isinstance(backup_cadence, str):
            raise ValueError(
                "support matrix: availability.backup_cadence must be str"
            )
        max_rpo = avail_raw.get("max_rpo")
        if not isinstance(max_rpo, str):
            raise ValueError(
                "support matrix: availability.max_rpo must be str"
            )
        rto = avail_raw.get("rto")
        if not isinstance(rto, str):
            raise ValueError("support matrix: availability.rto must be str")
        health_check_cadence = avail_raw.get("health_check_cadence")
        if not isinstance(health_check_cadence, str):
            raise ValueError(
                "support matrix: availability.health_check_cadence must be str"
            )
        key_rotation = avail_raw.get("key_rotation")
        if not isinstance(key_rotation, str):
            raise ValueError(
                "support matrix: availability.key_rotation must be str"
            )
        rc_soak_raw = avail_raw.get("rc_soak_days")
        if not isinstance(rc_soak_raw, int) or isinstance(
            rc_soak_raw, bool
        ):
            raise ValueError(
                "support matrix: availability.rc_soak_days must be int"
            )
        availability = AvailabilityObjectives(
            backup_cadence=backup_cadence,
            max_rpo=max_rpo,
            rto=rto,
            health_check_cadence=health_check_cadence,
            key_rotation=key_rotation,
            rc_soak_days=rc_soak_raw,
        )

        compatibility_window = raw.get("compatibility_window")
        if not isinstance(compatibility_window, str):
            raise ValueError(
                "support matrix: compatibility_window must be a string"
            )

        compatibility_window_note = raw.get("compatibility_window_note", "")
        if not isinstance(compatibility_window_note, str):
            raise ValueError(
                "support matrix: compatibility_window_note must be a string"
            )

        windows_qualification = raw.get("windows_qualification", "")
        if not isinstance(windows_qualification, str):
            raise ValueError(
                "support matrix: windows_qualification must be a string"
            )

        windows_qualification_note = raw.get("windows_qualification_note", "")
        if not isinstance(windows_qualification_note, str):
            raise ValueError(
                "support matrix: windows_qualification_note must be a string"
            )

        browsers_qualification_note = raw.get("browsers_qualification_note", "")
        if not isinstance(browsers_qualification_note, str):
            raise ValueError(
                "support matrix: browsers_qualification_note must be a string"
            )

        identity_backends_note = raw.get("identity_backends_note", "")
        if not isinstance(identity_backends_note, str):
            raise ValueError(
                "support matrix: identity_backends_note must be a string"
            )

        secret_backends_note = raw.get("secret_backends_note", "")
        if not isinstance(secret_backends_note, str):
            raise ValueError(
                "support matrix: secret_backends_note must be a string"
            )

        availability_note = raw.get("availability_note", "")
        if not isinstance(availability_note, str):
            raise ValueError(
                "support matrix: availability_note must be a string"
            )

        excl_raw = raw.get("excluded_surfaces")
        if not isinstance(excl_raw, list):
            raise ValueError(
                "support matrix: excluded_surfaces must be a list"
            )
        excluded_surfaces = tuple(
            v for v in excl_raw if isinstance(v, str)
        )

        return cls(
            release=release,
            python_versions=python_versions,
            python_versions_note=py_note,
            postgres_version=postgres_version,
            reference_linux=reference_linux,
            docker=docker,
            kubernetes=kubernetes,
            kubernetes_note=kubernetes_note,
            windows_versions=windows_versions,
            browsers=tuple(browsers),
            identity_backends=tuple(identity_backends),
            secret_backends=tuple(secret_backends),
            profiles=tuple(profiles),
            availability=availability,
            compatibility_window=compatibility_window,
            compatibility_window_note=compatibility_window_note,
            excluded_surfaces=excluded_surfaces,
            windows_qualification=windows_qualification,
            windows_qualification_note=windows_qualification_note,
            browsers_qualification_note=browsers_qualification_note,
            identity_backends_note=identity_backends_note,
            secret_backends_note=secret_backends_note,
            availability_note=availability_note,
        )

    @classmethod
    def default(cls) -> SupportMatrix:
        all_components = PROFILE_REQUIREMENTS[Profile.C]
        profiles = tuple(
            ProfileSupport(
                profile=p,
                required_components=tuple(
                    sorted(PROFILE_REQUIREMENTS[p])
                ),
                optional_components=tuple(
                    sorted(all_components - PROFILE_REQUIREMENTS[p])
                ),
                release_status=(
                    "in_qualification"
                    if p in (Profile.A, Profile.B)
                    else "preview"
                ),
            )
            for p in (Profile.A, Profile.B, Profile.C)
        )
        return cls(
            release="1.0.0-dev",
            python_versions=("3.12", "3.13", "3.14"),
            python_versions_note="Windows native support may require 3.14 for latest stdlib improvements; 3.12/3.13 are the baseline for Linux/Docker.",
            postgres_version="18+",
            reference_linux="Ubuntu 22.04+",
            docker="supported",
            kubernetes="optional",
            kubernetes_note="An optional manifest may exist for shops that already run k8s; it is never the required path. No k8s operator is produced.",
            windows_versions=("10", "11", "Server 2022"),
            browsers=(
                BrowserTarget(name="Chrome", version="latest-1", status="not_qualified"),
                BrowserTarget(name="Firefox", version="latest-1", status="not_qualified"),
                BrowserTarget(name="Safari", version="latest-1", status="not_qualified"),
                BrowserTarget(name="Edge", version="latest-1", status="not_qualified"),
            ),
            identity_backends=(
                IdentityBackend(
                    kind=IdentityBackendKind.ENTRA_OIDC,
                    status="not_qualified",
                ),
                IdentityBackend(
                    kind=IdentityBackendKind.LOCAL,
                    status="supported",
                ),
            ),
            secret_backends=(
                SecretBackend(
                    kind=SecretBackendKind.VAULT,
                    status="not_qualified",
                ),
                SecretBackend(
                    kind=SecretBackendKind.AKV,
                    status="not_qualified",
                ),
                SecretBackend(
                    kind=SecretBackendKind.WINDOWS_NATIVE_FILE,
                    status="not_qualified",
                ),
            ),
            profiles=profiles,
            availability=AvailabilityObjectives(
                backup_cadence="daily",
                max_rpo="24h",
                rto="4h",
                health_check_cadence="15min",
                key_rotation="90 days",
                rc_soak_days=14,
            ),
            compatibility_window="N-1 upgrade supported",
            compatibility_window_note="Upgrade/rollback logic is unit-tested with stubbed runners; live N-1 upgrade proof is Gate 4 WI-4.3.",
            excluded_surfaces=(
                "Kubernetes operator (k8s is an optional substrate, not a required dependency)",
                "SaaS",
                "Multi-region active/active",
                "Fleet management",
            ),
            windows_qualification="unit_tests_only",
            windows_qualification_note="agent-suite unit tests pass on windows-latest CI; native Windows qualification (Setup, DPAPI, WinSW, dual-control) is Gate 4 WI-4.2 and not yet started.",
            browsers_qualification_note="No browser CI lane exists; dossier WCAG/accessibility qualification is Gate 1 WI-1.6 and not yet started.",
            identity_backends_note="Local identity is CI-tested via interop. Entra/OIDC qualification is dossier Plan 020 and not yet started.",
            secret_backends_note="Secret resolver design is documented; no backend is CI-qualified. Backend SDKs live behind extras and are imported only at the secret-resolution edge.",
            availability_note="Objectives are targets for Gate 0 WI-0.3 ratification, not yet proven by qualification.",
        )

    def validate(self) -> bool:
        if not self.python_versions:
            return False
        if not self.postgres_version:
            return False
        if not self.reference_linux:
            return False
        if not self.docker:
            return False
        if not self.windows_versions:
            return False
        if not self.browsers:
            return False
        if not self.identity_backends:
            return False
        if not self.secret_backends:
            return False
        profile_values = {p.profile for p in self.profiles}
        if profile_values != {Profile.A, Profile.B, Profile.C}:
            return False
        if self.availability.rc_soak_days <= 0:
            return False
        if not self.excluded_surfaces:
            return False
        for p in self.profiles:
            required = frozenset(p.required_components)
            if required != PROFILE_REQUIREMENTS[p.profile]:
                return False
        return True


@dataclass(frozen=True)
class WorkItem:
    """One release work item with owner, dependency, status, and proof."""

    id: str
    title: str
    owner_repo: str
    blocking_dependency: str
    status: WIStatus
    proof_command: str
    proof_artifact: str
    status_note: str = ""

    def to_dict(self) -> dict[str, object]:
        d: dict[str, object] = {
            "id": self.id,
            "title": self.title,
            "owner_repo": self.owner_repo,
            "blocking_dependency": self.blocking_dependency,
            "status": self.status.value,
            "proof_command": self.proof_command,
            "proof_artifact": self.proof_artifact,
        }
        if self.status_note:
            d["status_note"] = self.status_note
        return d


@dataclass(frozen=True)
class Gate:
    """One release gate with its work items."""

    number: int
    name: str
    work_items: tuple[WorkItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "number": self.number,
            "name": self.name,
            "work_items": [wi.to_dict() for wi in self.work_items],
        }


@dataclass(frozen=True)
class ReleaseBoard:
    """Machine-readable release ledger (Plan 015 §4, WI-0.4).

    Contains all six gates (0-5) with their work items. Each work item
    names its owner repository, blocking dependency, status, and proof
    command/artifact. Cross-references the feature matrix and claims
    ledger by stable IDs — they do not become three competing status
    systems.
    """

    release: str
    feature_matrix_ref: str
    claims_ledger_ref: str
    gates: tuple[Gate, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "release": self.release,
            "feature_matrix_ref": self.feature_matrix_ref,
            "claims_ledger_ref": self.claims_ledger_ref,
            "gates": [g.to_dict() for g in self.gates],
        }

    @classmethod
    def from_json(cls, text: str) -> ReleaseBoard:
        raw = json.loads(text)
        if not isinstance(raw, dict):
            raise ValueError("release board: expected a JSON object")

        release = raw.get("release")
        if not isinstance(release, str):
            raise ValueError("release board: release must be a string")

        feature_matrix_ref = raw.get("feature_matrix_ref")
        if not isinstance(feature_matrix_ref, str):
            raise ValueError(
                "release board: feature_matrix_ref must be a string"
            )

        claims_ledger_ref = raw.get("claims_ledger_ref")
        if not isinstance(claims_ledger_ref, str):
            raise ValueError(
                "release board: claims_ledger_ref must be a string"
            )

        gates_raw = raw.get("gates")
        if not isinstance(gates_raw, list):
            raise ValueError("release board: gates must be a list")
        gates: list[Gate] = []
        for g in gates_raw:
            if not isinstance(g, dict):
                raise ValueError(
                    "release board: gate entry must be an object"
                )
            number = g.get("number")
            if not isinstance(number, int) or isinstance(number, bool):
                raise ValueError(
                    "release board: gate number must be an integer"
                )
            name = g.get("name")
            if not isinstance(name, str):
                raise ValueError("release board: gate name must be a string")
            wis_raw = g.get("work_items")
            if not isinstance(wis_raw, list):
                raise ValueError(
                    "release board: work_items must be a list"
                )
            work_items: list[WorkItem] = []
            for wi in wis_raw:
                if not isinstance(wi, dict):
                    raise ValueError(
                        "release board: work item must be an object"
                    )
                wi_id = wi.get("id")
                if not isinstance(wi_id, str):
                    raise ValueError(
                        "release board: work item id must be a string"
                    )
                title = wi.get("title")
                if not isinstance(title, str):
                    raise ValueError(
                        "release board: work item title must be a string"
                    )
                owner_repo = wi.get("owner_repo")
                if not isinstance(owner_repo, str):
                    raise ValueError(
                        "release board: work item owner_repo must be str"
                    )
                blocking_dep = wi.get("blocking_dependency")
                if not isinstance(blocking_dep, str):
                    raise ValueError(
                        "release board: blocking_dependency must be str"
                    )
                status_str = wi.get("status")
                if not isinstance(status_str, str):
                    raise ValueError(
                        "release board: work item status must be a string"
                    )
                try:
                    status = WIStatus(status_str)
                except ValueError as exc:
                    raise ValueError(
                        f"release board: unknown status: {status_str}"
                    ) from exc
                proof_command = wi.get("proof_command")
                if not isinstance(proof_command, str):
                    raise ValueError(
                        "release board: proof_command must be a string"
                    )
                proof_artifact = wi.get("proof_artifact")
                if not isinstance(proof_artifact, str):
                    raise ValueError(
                        "release board: proof_artifact must be a string"
                    )
                status_note = wi.get("status_note", "")
                if not isinstance(status_note, str):
                    raise ValueError(
                        "release board: status_note must be a string"
                    )
                work_items.append(
                    WorkItem(
                        id=wi_id,
                        title=title,
                        owner_repo=owner_repo,
                        blocking_dependency=blocking_dep,
                        status=status,
                        proof_command=proof_command,
                        proof_artifact=proof_artifact,
                        status_note=status_note,
                    )
                )
            gates.append(
                Gate(
                    number=number,
                    name=name,
                    work_items=tuple(work_items),
                )
            )

        return cls(
            release=release,
            feature_matrix_ref=feature_matrix_ref,
            claims_ledger_ref=claims_ledger_ref,
            gates=tuple(gates),
        )

    @classmethod
    def default(cls) -> ReleaseBoard:
        return cls(
            release="1.0.0-dev",
            feature_matrix_ref="data/v1-feature-matrix.json",
            claims_ledger_ref="data/claims-ledger.json",
            gates=(
                Gate(
                    number=0,
                    name=(
                        "Reconcile truth and freeze the release "
                        "candidate contract"
                    ),
                    work_items=(
                        WorkItem(
                            id="WI-0.1",
                            title=(
                                "Replace hand assessment with executable "
                                "baseline probes"
                            ),
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Plan 009 WI-0.3",
                            status=WIStatus.COMPLETE,
                            proof_command=(
                                "python3 scripts/feature-probes.py --check"
                            ),
                            proof_artifact="data/v1-feature-matrix.json",
                        ),
                        WorkItem(
                            id="WI-0.2",
                            title=(
                                "Reconcile plans, source state, and "
                                "dogfood state"
                            ),
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="\u2014",
                            status=WIStatus.IN_PROGRESS,
                            status_note=(
                                "SUITE.lock updated with real SHAs; "
                                "identifier gate replaced with canonical "
                                "script; plan status lines reconciled. "
                                "Inventory CLI (agent-suite inventory) not "
                                "yet implemented."
                            ),
                            proof_command="agent-suite inventory --json",
                            proof_artifact="data/candidate-inventory.json",
                        ),
                        WorkItem(
                            id="WI-0.3",
                            title=(
                                "Ratify the 1.0 support matrix and "
                                "objectives"
                            ),
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-0.2",
                            status=WIStatus.IN_PROGRESS,
                            proof_command=(
                                "python -c \"from agent_suite."
                                "release_artifacts import SupportMatrix; "
                                "assert SupportMatrix.default()."
                                "validate()\""
                            ),
                            proof_artifact="data/support-matrix.json",
                        ),
                        WorkItem(
                            id="WI-0.4",
                            title="Establish the release board",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-0.3",
                            status=WIStatus.IN_PROGRESS,
                            proof_command=(
                                "python -c \"from agent_suite."
                                "release_artifacts import ReleaseBoard; "
                                "assert ReleaseBoard.default()."
                                "validate()\""
                            ),
                            proof_artifact="data/release-board.json",
                        ),
                    ),
                ),
                Gate(
                    number=1,
                    name=(
                        "Complete the Profile B product through dossier"
                    ),
                    work_items=(
                        WorkItem(
                            id="WI-1.1",
                            title="Freeze versioned provider contracts",
                            owner_repo="hraedon/dossier",
                            blocking_dependency="Gate 0",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_provider_contracts.py"
                            ),
                            proof_artifact="data/contracts/",
                        ),
                        WorkItem(
                            id="WI-1.2",
                            title="Work and knowledge journeys",
                            owner_repo="hraedon/dossier",
                            blocking_dependency="WI-1.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_golden_journeys.py "
                                "-k 'GJ-1 or GJ-2 or GJ-3 or GJ-4'"
                            ),
                            proof_artifact="golden/gj-1-through-4.json",
                        ),
                        WorkItem(
                            id="WI-1.3",
                            title="Activity and evidence journeys",
                            owner_repo="hraedon/dossier",
                            blocking_dependency="WI-1.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_golden_journeys.py "
                                "-k 'GJ-5 or GJ-8'"
                            ),
                            proof_artifact="golden/gj-5-gj-8.json",
                        ),
                        WorkItem(
                            id="WI-1.4",
                            title=(
                                "Identity, keys, and protected "
                                "administration"
                            ),
                            owner_repo="hraedon/dossier",
                            blocking_dependency="WI-1.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_identity_keys.py"
                            ),
                            proof_artifact="golden/identity-keys.json",
                        ),
                        WorkItem(
                            id="WI-1.5",
                            title="Daily operation and notifications",
                            owner_repo="hraedon/dossier",
                            blocking_dependency="WI-1.2, WI-1.4",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_notifications.py"
                            ),
                            proof_artifact="golden/notifications.json",
                        ),
                        WorkItem(
                            id="WI-1.6",
                            title=(
                                "Console and accessibility qualification"
                            ),
                            owner_repo="hraedon/dossier",
                            blocking_dependency=(
                                "WI-1.2, WI-1.3, WI-1.4, WI-1.5"
                            ),
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_accessibility.py"
                            ),
                            proof_artifact="golden/a11y-report.json",
                        ),
                    ),
                ),
                Gate(
                    number=2,
                    name=(
                        "Make candidate artifacts immutable and "
                        "reproducible"
                    ),
                    work_items=(
                        WorkItem(
                            id="WI-2.1",
                            title="Replace the current compatibility lock",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gate 1",
                            status=WIStatus.NOT_STARTED,
                            proof_command="agent-suite lock --certify",
                            proof_artifact="SUITE.lock",
                        ),
                        WorkItem(
                            id="WI-2.2",
                            title="Test the lock, not moving branches",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-2.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command="pytest tests/test_lock_ci.py",
                            proof_artifact="ci/lock-build.yml",
                        ),
                        WorkItem(
                            id="WI-2.3",
                            title="Publish one release bundle",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-2.2",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite bundle --publish"
                            ),
                            proof_artifact="dist/agent-suite-1.0.0/",
                        ),
                        WorkItem(
                            id="WI-2.4",
                            title="Supply-chain and publication gates",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-2.3",
                            status=WIStatus.NOT_STARTED,
                            proof_command="agent-suite bundle --audit",
                            proof_artifact="dist/audit-report.json",
                        ),
                    ),
                ),
                Gate(
                    number=3,
                    name=(
                        "Close or narrow the production assurance "
                        "claims"
                    ),
                    work_items=(
                        WorkItem(
                            id="WI-3.1",
                            title="Required supported claims",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gate 2",
                            status=WIStatus.NOT_STARTED,
                            proof_command="pytest tests/test_claims.py",
                            proof_artifact="data/claims-ledger.json",
                        ),
                        WorkItem(
                            id="WI-3.2",
                            title=(
                                "Optional claims are qualified or "
                                "excluded"
                            ),
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-3.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "pytest tests/test_claims_optional.py"
                            ),
                            proof_artifact="data/claims-ledger.json",
                        ),
                        WorkItem(
                            id="WI-3.3",
                            title="Security and privacy review",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gate 2",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite security-review --json"
                            ),
                            proof_artifact="data/security-review.json",
                        ),
                    ),
                ),
                Gate(
                    number=4,
                    name=(
                        "Qualify deployment, migration, and recovery"
                    ),
                    work_items=(
                        WorkItem(
                            id="WI-4.1",
                            title="Hermetic clean-install convergence",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gate 2",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite doctor --clean-install --json"
                            ),
                            proof_artifact="golden/clean-install.json",
                        ),
                        WorkItem(
                            id="WI-4.2",
                            title="Native Windows proof",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gate 2",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite doctor --windows --json"
                            ),
                            proof_artifact=(
                                "golden/windows-qualification.json"
                            ),
                        ),
                        WorkItem(
                            id="WI-4.3",
                            title="Schema and release transition proof",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-4.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite upgrade --dry-run --from N-1 "
                                "--json"
                            ),
                            proof_artifact="golden/upgrade-proof.json",
                        ),
                        WorkItem(
                            id="WI-4.4",
                            title=(
                                "Protection and disaster recovery proof"
                            ),
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-4.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite restore --verify --json"
                            ),
                            proof_artifact="golden/restore-proof.json",
                        ),
                        WorkItem(
                            id="WI-4.5",
                            title="Existing-estate convergence",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-4.1, WI-4.3",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite upgrade --estate --json"
                            ),
                            proof_artifact=(
                                "golden/estate-convergence.json"
                            ),
                        ),
                    ),
                ),
                Gate(
                    number=5,
                    name="Release candidate, soak, and publication",
                    work_items=(
                        WorkItem(
                            id="WI-5.1",
                            title="Cut RC1 and freeze inputs",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="Gates 0-4",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite release cut --rc 1"
                            ),
                            proof_artifact="releases/1.0.0-rc1/",
                        ),
                        WorkItem(
                            id="WI-5.2",
                            title="Operate the candidate",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-5.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite soak --report --json"
                            ),
                            proof_artifact="golden/soak-report.json",
                        ),
                        WorkItem(
                            id="WI-5.3",
                            title="Documentation and support readiness",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-5.1",
                            status=WIStatus.NOT_STARTED,
                            proof_command="agent-suite docs --check",
                            proof_artifact="docs/",
                        ),
                        WorkItem(
                            id="WI-5.4",
                            title="Final release review",
                            owner_repo="hraedon/agent-suite",
                            blocking_dependency="WI-5.2, WI-5.3",
                            status=WIStatus.NOT_STARTED,
                            proof_command=(
                                "agent-suite release promote --final"
                            ),
                            proof_artifact="releases/1.0.0/",
                        ),
                    ),
                ),
            ),
        )

    def validate(self) -> bool:
        all_ids: list[str] = []
        for gate in self.gates:
            if not gate.work_items:
                return False
            for wi in gate.work_items:
                all_ids.append(wi.id)
        if len(all_ids) != len(set(all_ids)):
            return False
        gate_numbers = [g.number for g in self.gates]
        if gate_numbers != list(range(len(self.gates))):
            return False
        if not self.feature_matrix_ref:
            return False
        if not self.claims_ledger_ref:
            return False
        return True
