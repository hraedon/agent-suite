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
from pathlib import Path
from typing import assert_never

from agent_suite.profiles import (
    PROFILE_DESCRIPTIONS,
    PROFILE_REQUIREMENTS,
    Profile,
)


def _canonical_data_path(filename: str) -> Path:
    """Resolve ``data/<filename>`` relative to the package root.

    Sol Gate 0 Workstream 1: the committed JSON files under ``data/`` are
    the canonical source of truth for the release artifacts.
    ``Path(__file__).resolve().parents[2]`` walks from
    ``src/agent_suite/release_artifacts.py`` up to the package root
    (``src/agent_suite/`` -> ``src/`` -> ``<pkg-root>``). Editable installs,
    wheel installs, and frozen apps all resolve consistently because the
    ``data/`` directory is shipped with the package (or, for editable
    installs, lives at the repo root as it does today).
    """
    return Path(__file__).resolve().parents[2] / "data" / filename


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
        """Load and validate the canonical ``data/support-matrix.json``.

        Sol Gate 0 Workstream 1: the committed JSON is the sole source of
        truth. The prior hardcoded data table is removed; this loader is the
        only path. Raises ``FileNotFoundError`` if the canonical file is
        absent and ``ValueError`` if it fails to validate.

        Backwards-compat: callers that previously did
        ``SupportMatrix.default().validate()`` keep working — the load
        already validates, and ``validate()`` re-checks on the loaded
        instance.
        """
        path = _canonical_data_path("support-matrix.json")
        text = path.read_text(encoding="utf-8")
        matrix = cls.from_json(text)
        if not matrix.validate():
            raise ValueError(f"{path}: canonical support-matrix.json failed validation")
        return matrix

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
        """Load and validate the canonical ``data/release-board.json``.

        Sol Gate 0 Workstream 1: the committed JSON is the sole source of
        truth. The prior hardcoded data table (Gates 0-5, every WI, every
        proof_artifact) is removed; this loader is the only path. Raises
        ``FileNotFoundError`` if the canonical file is absent and
        ``ValueError`` if it fails to validate.

        Backwards-compat: callers that previously did
        ``ReleaseBoard.default().validate()`` keep working — the load
        already validates, and ``validate()`` re-checks on the loaded
        instance.
        """
        path = _canonical_data_path("release-board.json")
        text = path.read_text(encoding="utf-8")
        board = cls.from_json(text)
        if not board.validate():
            raise ValueError(
                f"{path}: canonical release-board.json failed validation"
            )
        return board


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
