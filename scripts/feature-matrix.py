#!/usr/bin/env python3
"""Generate and validate the Plan 009 v1 feature matrix.

Implements Plan 009 WI-0.1 / WI-0.3. The matrix defines the warranted v1 public
surface per golden journey and component. This script emits both the machine
JSON artifact and a human-readable Markdown table.

Status values (Plan 009 §8 baseline vocabulary):
  pass     — the surface works end-to-end against current main
  partial  — the surface exists but has a documented gap or gate
  blocked  — implementation is stopped on an unresolved dependency/defect
  absent   — not yet implemented
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, assert_never

# Load the probe layer (scripts/feature-probes.py) so _matrix() can apply
# probes during generation. This keeps feature-matrix.py as the source of
# truth for row structure while delegating status/proof determination to
# the named probes in feature-probes.py. Loaded via importlib because the
# scripts directory is not on sys.path when this file is loaded by tests.
_THIS_DIR = Path(__file__).resolve().parent
_PROBES_PATH = _THIS_DIR / "feature-probes.py"
_spec = importlib.util.spec_from_file_location("_feature_probes", _PROBES_PATH)
assert _spec is not None and _spec.loader is not None
_feature_probes = importlib.util.module_from_spec(_spec)
# Register before exec_module so dataclass decorators can resolve the module.
sys.modules["_feature_probes"] = _feature_probes
_spec.loader.exec_module(_feature_probes)


class Status(Enum):
    PASS = "pass"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    ABSENT = "absent"


@dataclass(frozen=True)
class MatrixRow:
    journey: str
    component: str
    surface: str
    profile: str
    status: str
    dependency: str
    proof: str
    excluded: str
    notes: str
    owning_wi: str = ""           # Sol Gate 0 WS3: WI that owns closing this row's gap
    release_status: str = ""      # Sol Gate 0 WS3: "in_qualification" | "preview" | "supported"


@dataclass(frozen=True)
class Matrix:
    version: str
    generated_at: str
    status_source: str
    observed_revisions: dict[str, str | None]
    profiles: list[str]
    golden_journeys: dict[str, str]
    rows: list[MatrixRow]
    wi_assignment_summary: dict[str, object] | None = None  # Sol Gate 0 WS3


REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = REPO_ROOT / "data" / "v1-feature-matrix.json"
DOCS_PATH = REPO_ROOT / "docs" / "v1-feature-matrix.md"


# Sol Gate 0 WS3 — owning WI per non-pass Profile B row. Each non-pass row in
# Profile A or B must have exactly one owning WI. Profile C rows are explicitly
# preview/deferred (do not need owning WIs at this gate). Update this mapping
# when WIs close (status moves to pass) or when a new gap surfaces.
_WI_ASSIGNMENTS: dict[tuple[str, str, str], str] = {
    ("GJ-1", "agent-notes", "project discovery from cwd and per-user identity"): "WI-010",
    ("GJ-1", "dossier", "authenticated project switcher"): "WI-011",
    ("GJ-1", "agent-suite", "identity lifecycle / onboarding / offboarding"): "WI-012",
    ("GJ-3", "agent-notes", "signed note write-through to regista"): "WI-013",
    ("GJ-4", "dossier", "honest assurance level / independent-review signal"): "WI-014",
    ("GJ-5", "dossier", "session / tool / file activity views"): "WI-015",
    ("GJ-5", "dossier", "degraded / unsupported capture rendered honestly"): "WI-016",
    ("GJ-7", "dossier", "notification preferences and review/recovery deep links"): "WI-017",
}


def _release_status_for_row(profile: str, journey: str, component: str) -> str:
    """Release-stage label per Sol Gate 0 WS3.

    Profile C rows are explicitly preview-stage (do not block core
    development). Profile A/B rows are in_qualification (the Gate 0/1
    target). Rows that have moved to pass could be labeled supported,
    but the matrix leaves that decision to the release board; here we
    only carry the stage label.
    """
    if profile == "C":
        return "preview"
    return "in_qualification"


def _wi_assignment_summary(rows: list[MatrixRow]) -> dict[str, object]:
    """Summary of WI assignments for the matrix payload."""
    profile_ab_non_pass = [
        r for r in rows if r.profile in ("A", "B") and r.status != "pass"
    ]
    assigned = [
        r for r in profile_ab_non_pass if r.owning_wi
    ]
    unassigned = [
        (r.journey, r.component, r.surface) for r in profile_ab_non_pass if not r.owning_wi
    ]
    wi_ids = sorted({r.owning_wi for r in assigned})
    return {
        "profile_b_non_pass_count": len(profile_ab_non_pass),
        "assigned_count": len(assigned),
        "unassigned": unassigned,
        "wi_ids": wi_ids,
        "profile_c_deferred": (
            "Profile C rows remain explicitly preview-stage per Sol Gate 0 "
            "WS3. They do not need owning WIs at this gate."
        ),
    }


def _allowed_statuses() -> set[str]:
    return {s.value for s in Status}


def _status_label(status: Status) -> str:
    match status:
        case Status.PASS:
            return "pass"
        case Status.PARTIAL:
            return "partial"
        case Status.BLOCKED:
            return "blocked"
        case Status.ABSENT:
            return "absent"
        case _:
            assert_never(status)


def _matrix_rows() -> list[MatrixRow]:
    """Static definition of the v1 warranted surface.

    The ``status`` and ``proof`` fields are placeholders that get overwritten
    by named probes in ``feature-probes.py`` via ``apply_probes()`` during
    ``_matrix()`` construction. Only the structural fields (journey, component,
    surface, profile, dependency, excluded, notes) are authoritative here.
    """
    return [
        # GJ-1 — Start a project
        MatrixRow(
            journey="GJ-1",
            component="agent-suite",
            surface="profile-aware bootstrap / deploy CLI",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="Plan 008 WI-3.2, Plan 009 WI-4.1",
            proof="src/agent_suite/deploy.py; tests/test_deploy.py; probe: _probe_deploy_cli -> pass",
            excluded="SaaS, Kubernetes operator, fleet remote management",
            notes="Deploy front door composes preflight → bootstrap → onboard → lock → doctor.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="agent-suite",
            surface="project onboarding and harness selection",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="Plan 009 WI-1.3, Plan 009 WI-4.1",
            proof="src/agent_suite/onboard.py; tests/test_onboard.py; probe: _probe_onboard_harness -> pass",
            excluded="—",
            notes="Suite-level onboard: spec → provision → sign event-zero → wire harness.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="regista",
            surface="project / schema provisioning",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="Regista.create_project, regista provision; tests/test_provision.py",
            excluded="Multi-region active/active replication",
            notes="PostgreSQL schema + roles created idempotently.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="regista",
            surface="workflow registration and discovery",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="Regista.register_workflow, regista workflow validate",
            excluded="General saga / workflow execution engine",
            notes="Canonical workflow is versioned and stored per project.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="agent-notes",
            surface="project discovery from cwd and per-user identity",
            profile="A",
            status=_status_label(Status.PARTIAL),
            dependency="agent-notes WI-013",
            proof="src/agent_notes/core/face_factory.py",
            excluded="—",
            notes="Per-project RegistaFace exists but write-through is gated.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="dossier",
            surface="authenticated project switcher",
            profile="B",
            status=_status_label(Status.PARTIAL),
            dependency="dossier WI-017",
            proof="src/dossier/app.py:149-175, src/dossier/authz.py",
            excluded="—",
            notes="Authz implementation exists but defaults to flat-open.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="regista",
            surface="principal enrollment, rotation, revocation, delegation",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/regista/_principal_keys.py; regista principal revoke CLI",
            excluded="—",
            notes="Asymmetric principal key registry with validity windows and revocation.",
        ),
        MatrixRow(
            journey="GJ-1",
            component="agent-suite",
            surface="identity lifecycle / onboarding / offboarding",
            profile="A",
            status=_status_label(Status.PARTIAL),
            dependency="Plan 009 WI-1.3, Plan 009 WI-2.2",
            proof="src/agent_suite/bootstrap.py (_step_user_onboarding); probe: _probe_identity_lifecycle -> partial",
            excluded="—",
            notes="Per-user onboarding step exists but reports 'not yet implemented'; offboarding absent.",
        ),
        # GJ-2 — Plan and execute work
        MatrixRow(
            journey="GJ-2",
            component="regista",
            surface="work-item lifecycle (create, claim, transition)",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="Regista.create_work_item / transition / replay; adversarial corpus",
            excluded="—",
            notes="Canonical workflow covers start, submit, review, accept, done.",
        ),
        MatrixRow(
            journey="GJ-2",
            component="agent-notes",
            surface="work-item skills / CLI",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/agent_notes/cli/work_items.py",
            excluded="—",
            notes="Full create / claim / transition / review CLI surface.",
        ),
        MatrixRow(
            journey="GJ-2",
            component="dossier",
            surface="work queues, detail, transition, review forms",
            profile="B",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/dossier/app.py:779-1028",
            excluded="Sprint planning, time tracking, billing",
            notes="Web create/edit/transition/review flows are present.",
        ),
        MatrixRow(
            journey="GJ-2",
            component="regista",
            surface="race-free claim / assignment",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/regista/_api_claim.py; tests/test_claims.py",
            excluded="—",
            notes="Lease-based claims with expiry and heartbeat.",
        ),
        MatrixRow(
            journey="GJ-2",
            component="dossier",
            surface="separation-of-duties enforcement in review",
            profile="B",
            status=_status_label(Status.PASS),
            dependency="\u2014",
            proof="src/dossier/assurance.py",
            excluded="\u2014",
            notes="Assurance fail-open fixed (dossier WI-014); separation-of-duties now enforced.",
        ),
        # GJ-3 — Capture and reuse knowledge
        MatrixRow(
            journey="GJ-3",
            component="agent-notes",
            surface="breadcrumb / memory / reflection skills and CLI",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="skills/file-breadcrumb/SKILL.md, skills/add-memory/SKILL.md, skills/reflect/SKILL.md; src/agent_notes/cli/memory.py",
            excluded="General wiki / document authoring",
            notes="Skills and CLI both present.",
        ),
        MatrixRow(
            journey="GJ-3",
            component="agent-notes",
            surface="signed note write-through to regista",
            profile="A",
            status=_status_label(Status.PARTIAL),
            dependency="agent-notes WI-013, dossier Plan 009",
            proof="src/agent_notes/core/note_model.py, src/agent_notes/core/memory_model.py",
            excluded="—",
            notes="Write-through implemented but gated; dossier has no note read surface.",
        ),
        MatrixRow(
            journey="GJ-3",
            component="dossier",
            surface="knowledge read / browse / search",
            profile="B",
            status=_status_label(Status.ABSENT),
            dependency="dossier Plan 009",
            proof="—",
            excluded="—",
            notes="No routes or templates for note / knowledge entities.",
        ),
        MatrixRow(
            journey="GJ-3",
            component="agent-notes",
            surface="search across breadcrumbs, memories, links",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/agent_notes/cli/search.py",
            excluded="—",
            notes="CLI search covers all three entity kinds.",
        ),
        # GJ-4 — Review with separation of duties
        MatrixRow(
            journey="GJ-4",
            component="agent-notes",
            surface="review CLI (pass, accept, reject, request-changes)",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/agent_notes/cli/work_items.py:1053-1131",
            excluded="—",
            notes="Adversarial-review skill consumes the same surface.",
        ),
        MatrixRow(
            journey="GJ-4",
            component="dossier",
            surface="review queue and verdict forms",
            profile="B",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/dossier/app.py:629-665, :923-1028",
            excluded="—",
            notes="Accept/reject/request-changes supported in web UI.",
        ),
        MatrixRow(
            journey="GJ-4",
            component="regista",
            surface="cross-lineage review validators",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="regista canonical workflow; adversarial corpus unauthorized_project_access",
            excluded="—",
            notes="Workflow enforces distinct actor roles.",
        ),
        MatrixRow(
            journey="GJ-4",
            component="dossier",
            surface="honest assurance level / independent-review signal",
            profile="B",
            status=_status_label(Status.PARTIAL),
            dependency="dossier WI-012",
            proof="src/dossier/assurance.py",
            excluded="\u2014",
            notes="Assurance fail-open fixed (WI-014); computation remains home-grown rather than delegated to regista (WI-012).",
        ),
        # GJ-5 — Understand agent activity
        MatrixRow(
            journey="GJ-5",
            component="agent-provenance",
            surface="session and tool begin/end capture",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/cairn/_claude_hook.py; live proof passed 2026-07-11",
            excluded="Covert monitoring of unsanctioned harnesses, screen recording",
            notes="Claude and OpenCode hooks are proven; Hermes is provisional.",
        ),
        MatrixRow(
            journey="GJ-5",
            component="agent-provenance",
            surface="principal / delegation / work binding",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/cairn/adapter.py:744-782; CairnClient.tool_call work_item_id",
            excluded="—",
            notes="Subagent attribution and on_behalf_of are captured.",
        ),
        MatrixRow(
            journey="GJ-5",
            component="dossier",
            surface="session / tool / file activity views",
            profile="B",
            status=_status_label(Status.PARTIAL),
            dependency="dossier Plan 017/018",
            proof="src/dossier/app.py:563-625, src/dossier/provenance.py",
            excluded="—",
            notes="Session list/detail and tool trail exist; verification UX is partial.",
        ),
        MatrixRow(
            journey="GJ-5",
            component="dossier",
            surface="degraded / unsupported capture rendered honestly",
            profile="B",
            status=_status_label(Status.PARTIAL),
            dependency="dossier WI-012",
            proof="src/dossier/assurance.py",
            excluded="—",
            notes="Assurance level no longer fails open (WI-014 fixed); delegation to regista still pending (WI-012).",
        ),
        # GJ-6 — Supply an approved capability
        MatrixRow(
            journey="GJ-6",
            component="agent-capability-broker",
            surface="manifest, reconcile, exec, install-harness",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="acb Plan 006 WI-1.2",
            proof="src/agent_capability_broker/cli.py:448-505; tests/test_doctor_conformance.py",
            excluded="Credential marketplace, device management",
            notes="Core verbs exist; e2e exec is NotImplementedError.",
        ),
        MatrixRow(
            journey="GJ-6",
            component="agent-capability-broker",
            surface="credential provider with secret-safe injection",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="acb Plan 006 WI-1.2",
            proof="src/agent_capability_broker/providers.py:352-494; tests/test_exec.py",
            excluded="—",
            notes="Provider injection works and is unit-tested; full end-to-end `acb exec` invocation is NotImplementedError.",
        ),
        MatrixRow(
            journey="GJ-6",
            component="agent-capability-broker",
            surface="browser / E2E provider and live proof",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="acb Plan 006 WI-1.2, Plan 007",
            proof="src/agent_capability_broker/providers.py:118-258; tests/test_e2e.py",
            excluded="—",
            notes="E2eProvider.inspect exists; exec is not implemented; Codex deferred.",
        ),
        MatrixRow(
            journey="GJ-6",
            component="agent-capability-broker",
            surface="rogue / clobbered capability detection",
            profile="C",
            status=_status_label(Status.ABSENT),
            dependency="agent-suite WI-001 capability_clobber",
            proof="—",
            excluded="—",
            notes="Doctor only inspects manifest-listed capabilities.",
        ),
        # GJ-7 — Deliver a signal
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="authenticated HTTP ingress",
            profile="C",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="daemon/src/agent_waked/ingest.py:140-182",
            excluded="Universal wake protocol",
            notes="HMAC-SHA256 per-source auth.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="durable dedup / retry / outbox / dead-letter",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="agent-wake BC-WAKE-004, BC-WAKE-012",
            proof="daemon/src/agent_waked/ingest.py:57-73; tests/test_ingest.py:93-108",
            excluded="Exactly-once delivery across external systems",
            notes="Dedup is in-memory FIFO; no durable inbox or dead-letter visibility.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="live_wake (Claude, OpenCode)",
            profile="C",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="adapters/opencode/src/wake.ts:88-157; adapters/claude/src/agent_wake_claude/channel.py",
            excluded="—",
            notes="Both adapters can deliver live prompts.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="silent_inject",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="agent-wake Plan 006",
            proof="adapters/opencode/src/wake.ts:125-126",
            excluded="—",
            notes="OpenCode supports silent inject; Claude adapter drops silent events.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="next_session / managed_session delivery",
            profile="C",
            status=_status_label(Status.ABSENT),
            dependency="agent-wake Plan 006",
            proof="—",
            excluded="—",
            notes="Design exists; no implementation.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="human webhook and email delivery",
            profile="C",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="daemon/src/agent_waked/channels/webhook.py; daemon/src/agent_waked/channels/email.py",
            excluded="Replacing chat/email providers",
            notes="Signed webhook and SMTP email channels implemented.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="agent-wake",
            surface="replayed event rejection",
            profile="C",
            status=_status_label(Status.PARTIAL),
            dependency="agent-wake BC-WAKE-004, BC-WAKE-012",
            proof="daemon/src/agent_waked/ingest.py:209-210; tests/test_ingest.py:93-108; tests/test_e2e.py:309-343",
            excluded="—",
            notes="Duplicate event_id rejected while daemon is running; in-memory dedup is lost on restart, so post-restart replay is not prevented.",
        ),
        MatrixRow(
            journey="GJ-7",
            component="dossier",
            surface="notification preferences and review/recovery deep links",
            profile="B",
            status=_status_label(Status.ABSENT),
            dependency="Plan 009 WI-3.3, dossier Plan 018",
            proof="—",
            excluded="Replacing chat/email providers",
            notes="No notification preference UI or deep-link routing exists.",
        ),
        # GJ-8 — Investigate and export evidence
        MatrixRow(
            journey="GJ-8",
            component="regista",
            surface="scoped evidence bundle export",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="Regista.export_audit_bundle; src/regista/_bundle.py:71",
            excluded="—",
            notes="Self-contained JSON with events, receipts, segments, public keys.",
        ),
        MatrixRow(
            journey="GJ-8",
            component="regista",
            surface="offline bundle verification",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="Regista.verify_audit_bundle_offline; src/regista/_bundle.py:230",
            excluded="—",
            notes="v2 verifies ed25519 signatures; v1 reports skipped honestly.",
        ),
        MatrixRow(
            journey="GJ-8",
            component="agent-provenance",
            surface="bundle export, diff/chain verify, human report",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/cairn/_cli.py:318-750; src/cairn/proof.py",
            excluded="—",
            notes="cairn verify, verify-chain, export, diff, portal all present.",
        ),
        MatrixRow(
            journey="GJ-8",
            component="agent-suite",
            surface="suite-level evidence export orchestration",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="Plan 009 WI-2.3",
            proof="src/agent_suite/evidence.py; tests/test_evidence.py; probe: _probe_evidence_export -> pass",
            excluded="—",
            notes="Composes regista bundle export + cairn export + verify into one suite-level manifest.",
        ),
        # GJ-9 — Operate and recover
        MatrixRow(
            journey="GJ-9",
            component="agent-suite",
            surface="profile-aware doctor aggregation",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/agent_suite/doctor.py; tests/test_doctor.py",
            excluded="—",
            notes="Honest health reporting for required/optional components.",
        ),
        MatrixRow(
            journey="GJ-9",
            component="agent-suite",
            surface="compatibility lock and drift check",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="src/agent_suite/lock.py; tests/test_lock.py",
            excluded="—",
            notes="SUITE.lock parsing and drift detection implemented.",
        ),
        MatrixRow(
            journey="GJ-9",
            component="agent-suite",
            surface="backup / restore / disaster recovery orchestration",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="Plan 008 WI-4.1, Plan 009 WI-4.2",
            proof="src/agent_suite/backup.py; tests/test_backup.py; probe: _probe_backup_restore -> pass",
            excluded="—",
            notes="Suite-level backup: doctor → pg_dump → verify → evidence export → manifest.",
        ),
        MatrixRow(
            journey="GJ-9",
            component="agent-suite",
            surface="upgrade / rollback / forward-recovery gates",
            profile="A",
            status=_status_label(Status.PARTIAL),
            dependency="Forward recovery retired pending shared transaction engine",
            proof="src/agent_suite/upgrade.py (run_upgrade, run_rollback, fail-closed run_forward_recovery); tests/test_upgrade.py; probe: _probe_upgrade_rollback_forward -> partial",
            excluded="—",
            notes="Upgrade and rollback are installation-aware transactions; legacy forward recovery is explicitly retired fail-closed.",
        ),
        MatrixRow(
            journey="GJ-9",
            component="regista",
            surface="version / config / secret / doctor contracts",
            profile="A",
            status=_status_label(Status.PASS),
            dependency="—",
            proof="regista doctor --json; src/regista/_cli.py doctor commands",
            excluded="—",
            notes="Doctor, version, and config contracts are exposed.",
        ),
    ]


def _matrix() -> Matrix:
    """Build the v1 feature matrix with probe-emitted statuses.

    Row structure (journey, component, surface, profile, dependency, excluded,
    notes) is defined statically in ``_matrix_rows()``. The ``status`` and
    ``proof`` fields are placeholders that get overwritten by the named probes
    in ``feature-probes.py`` via ``apply_probes()``. This keeps feature-matrix.py
    as the source of truth for row structure while delegating status/proof
    determination to the probe layer.

    In environments where sibling components are not installed (e.g. CI), probes
    return ``HAND_ASSESSED`` and preserve the prior ``status``/``proof``. To
    keep the committed JSON stable across environments, the prior values are
    seeded from the committed JSON file when it exists.
    """
    base_rows = _matrix_rows()
    # Build a dict payload, apply probes (which set status/proof/status_source/
    # observed_revisions), then reconstruct the Matrix dataclass.
    payload: dict[str, Any] = {
        "version": "v1",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status_source": "hand-assessed",
        "observed_revisions": {},
        "profiles": ["A", "B", "C"],
        "golden_journeys": {
            "GJ-1": "Start a project",
            "GJ-2": "Plan and execute work",
            "GJ-3": "Capture and reuse knowledge",
            "GJ-4": "Review with separation of duties",
            "GJ-5": "Understand agent activity",
            "GJ-6": "Supply an approved capability",
            "GJ-7": "Deliver a signal",
            "GJ-8": "Investigate and export evidence",
            "GJ-9": "Operate and recover",
        },
        "rows": [asdict(r) for r in base_rows],
    }
    # Seed status/proof from the committed JSON so that CI (without siblings)
    # produces output matching the committed file. apply_probes will overwrite
    # these in environments where siblings are available.
    if DATA_PATH.exists():
        try:
            committed = json.loads(DATA_PATH.read_text(encoding="utf-8"))
            committed_map: dict[tuple[str, str, str], dict[str, Any]] = {
                (r["journey"], r["component"], r["surface"]): r
                for r in committed.get("rows", [])
            }
            for row in payload["rows"]:
                key = (row["journey"], row["component"], row["surface"])
                if key in committed_map:
                    row["status"] = committed_map[key]["status"]
                    row["proof"] = committed_map[key]["proof"]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass  # Fall back to placeholders from _matrix_rows()
    payload = _feature_probes.apply_probes(payload)
    # Sol Gate 0 WS3: attach owning WI per row + release-stage label.
    for row in payload["rows"]:
        key = (row["journey"], row["component"], row["surface"])
        row["owning_wi"] = _WI_ASSIGNMENTS.get(key, "")
        row["release_status"] = _release_status_for_row(
            row["profile"], row["journey"], row["component"]
        )
    constructed_rows = [MatrixRow(**r) for r in payload["rows"]]
    return Matrix(
        version=payload["version"],
        generated_at=payload["generated_at"],
        status_source=payload["status_source"],
        observed_revisions=payload["observed_revisions"],
        profiles=payload["profiles"],
        golden_journeys=payload["golden_journeys"],
        rows=constructed_rows,
        wi_assignment_summary=_wi_assignment_summary(constructed_rows),
    )


def _validate(matrix: Matrix) -> list[str]:
    errors: list[str] = []
    allowed = _allowed_statuses()
    seen: set[tuple[str, str, str]] = set()
    for row in matrix.rows:
        key = (row.journey, row.component, row.surface)
        if key in seen:
            errors.append(f"duplicate row: {key}")
        seen.add(key)
        if row.status not in allowed:
            errors.append(
                f"invalid status {row.status!r} for {key}; expected one of {sorted(allowed)}"
            )
        if row.journey not in matrix.golden_journeys:
            errors.append(f"unknown journey {row.journey!r} for {key}")
        if row.profile not in matrix.profiles:
            errors.append(f"invalid profile {row.profile!r} for {key}")
    return errors


def _matrix_to_json(matrix: Matrix) -> str:
    payload = {
        "version": matrix.version,
        "generated_at": matrix.generated_at,
        "status_source": matrix.status_source,
        "observed_revisions": matrix.observed_revisions,
        "profiles": matrix.profiles,
        "golden_journeys": matrix.golden_journeys,
        "rows": [asdict(row) for row in matrix.rows],
    }
    if matrix.wi_assignment_summary is not None:
        payload["wi_assignment_summary"] = matrix.wi_assignment_summary
    return json.dumps(payload, indent=2) + "\n"


def _matrix_to_markdown(matrix: Matrix) -> str:
    lines: list[str] = []
    lines.append("# v1 Feature Matrix (Plan 009 WI-0.1)")
    lines.append("")
    lines.append(f"**Version:** {matrix.version}  ")
    lines.append(f"**Generated:** {matrix.generated_at}")
    lines.append(f"**Status source:** {matrix.status_source}")
    lines.append("**Status values:** pass / partial / blocked / absent")
    lines.append("")
    if matrix.status_source == "probe-emitted":
        lines.append(
            "This matrix is emitted by named probes; every row's status is "
            "mechanically determined. Do not hand-edit the status column."
        )
    elif matrix.status_source == "mixed-probe-and-hand":
        lines.append(
            "Most rows are probe-emitted; some probes returned HAND_ASSESSED "
            "(sibling component not available). Re-run with siblings installed "
            "for full coverage."
        )
    else:
        lines.append(
            "Status values are hand-assessed from cross-project review. "
            "The WI-0.3 baseline run will replace them with probe-emitted statuses."
        )
    lines.append("")
    if matrix.observed_revisions:
        lines.append("## Observed revisions")
        lines.append("")
        for component, rev in matrix.observed_revisions.items():
            lines.append(f"- **{component}**: {rev if rev else '(unavailable)'}")
        lines.append("")
    lines.append("## Golden journeys")
    lines.append("")
    for key, value in matrix.golden_journeys.items():
        lines.append(f"- **{key}** — {value}")
    lines.append("")
    lines.append("## Matrix")
    lines.append("")
    header = "| Journey | Profile | Component | Surface | Status | Dependency | Proof | Excluded | Notes |"
    separator = "|---|---|---|---|---|---|---|---|---|"
    lines.append(header)
    lines.append(separator)
    for row in matrix.rows:
        cells = [
            row.journey,
            row.profile,
            row.component,
            row.surface,
            row.status,
            row.dependency,
            row.proof,
            row.excluded,
            row.notes,
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the Plan 009 v1 feature matrix.")
    parser.add_argument(
        "--data",
        type=Path,
        default=DATA_PATH,
        help="Path to write the JSON matrix artifact",
    )
    parser.add_argument(
        "--docs",
        type=Path,
        default=DOCS_PATH,
        help="Path to write the Markdown matrix",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Validate and exit non-zero on errors",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print Markdown to stdout instead of writing files",
    )
    args = parser.parse_args(argv)

    matrix = _matrix()
    errors = _validate(matrix)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.check:
        return 0

    markdown = _matrix_to_markdown(matrix)
    if args.stdout:
        print(markdown)
        return 0

    args.data.parent.mkdir(parents=True, exist_ok=True)
    args.docs.parent.mkdir(parents=True, exist_ok=True)
    args.data.write_text(_matrix_to_json(matrix), encoding="utf-8")
    args.docs.write_text(markdown, encoding="utf-8")
    print(f"Wrote {args.data}")
    print(f"Wrote {args.docs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
