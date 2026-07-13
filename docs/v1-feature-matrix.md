# v1 Feature Matrix (Plan 009 WI-0.1)

**Version:** v1  
**Generated:** 2026-07-13T06:49:40.115288Z  
**Status source:** mixed-probe-and-hand
**Status values:** pass / partial / blocked / absent

Status values are hand-assessed from cross-project review. The WI-0.3 baseline run will replace them with probe-emitted statuses.

## Golden journeys

- **GJ-1** — Start a project
- **GJ-2** — Plan and execute work
- **GJ-3** — Capture and reuse knowledge
- **GJ-4** — Review with separation of duties
- **GJ-5** — Understand agent activity
- **GJ-6** — Supply an approved capability
- **GJ-7** — Deliver a signal
- **GJ-8** — Investigate and export evidence
- **GJ-9** — Operate and recover

## Matrix

| Journey | Profile | Component | Surface | Status | Dependency | Proof | Excluded | Notes |
|---|---|---|---|---|---|---|---|---|
| GJ-1 | A | agent-suite | profile-aware bootstrap / deploy CLI | pass | Plan 008 WI-3.2, Plan 009 WI-4.1 | src/agent_suite/deploy.py; tests/test_deploy.py; probe: _probe_deploy_cli -> pass | SaaS, Kubernetes operator, fleet remote management | Deploy front door composes preflight → bootstrap → onboard → lock → doctor. |
| GJ-1 | A | agent-suite | project onboarding and harness selection | pass | Plan 009 WI-1.3, Plan 009 WI-4.1 | src/agent_suite/onboard.py; tests/test_onboard.py; probe: _probe_onboard_harness -> pass | — | Suite-level onboard: spec → provision → sign event-zero → wire harness. |
| GJ-1 | A | regista | project / schema provisioning | pass | — | Regista.create_project, regista provision; tests/test_provision.py | Multi-region active/active replication | PostgreSQL schema + roles created idempotently. |
| GJ-1 | A | regista | workflow registration and discovery | pass | — | Regista.register_workflow, regista workflow validate | General saga / workflow execution engine | Canonical workflow is versioned and stored per project. |
| GJ-1 | A | agent-notes | project discovery from cwd and per-user identity | partial | agent-notes WI-013 | src/agent_notes/core/face_factory.py | — | Per-project RegistaFace exists but write-through is gated. |
| GJ-1 | B | dossier | authenticated project switcher | partial | dossier WI-017 | src/dossier/app.py:149-175, src/dossier/authz.py | — | Authz implementation exists but defaults to flat-open. |
| GJ-1 | A | regista | principal enrollment, rotation, revocation, delegation | pass | — | src/regista/_principal_keys.py; regista principal revoke CLI | — | Asymmetric principal key registry with validity windows and revocation. |
| GJ-1 | A | agent-suite | identity lifecycle / onboarding / offboarding | partial | Plan 009 WI-1.3, Plan 009 WI-2.2 | src/agent_suite/bootstrap.py (_step_user_onboarding); probe: _probe_identity_lifecycle -> partial | — | Per-user onboarding step exists but reports 'not yet implemented'; offboarding absent. |
| GJ-2 | A | regista | work-item lifecycle (create, claim, transition) | pass | — | Regista.create_work_item / transition / replay; adversarial corpus | — | Canonical workflow covers start, submit, review, accept, done. |
| GJ-2 | A | agent-notes | work-item skills / CLI | pass | — | src/agent_notes/cli/work_items.py | — | Full create / claim / transition / review CLI surface. |
| GJ-2 | B | dossier | work queues, detail, transition, review forms | pass | — | src/dossier/app.py:779-1028 | Sprint planning, time tracking, billing | Web create/edit/transition/review flows are present. |
| GJ-2 | A | regista | race-free claim / assignment | pass | — | src/regista/_api_claim.py; tests/test_claims.py | — | Lease-based claims with expiry and heartbeat. |
| GJ-2 | B | dossier | separation-of-duties enforcement in review | pass | — | src/dossier/assurance.py | — | Assurance fail-open fixed (dossier WI-014); separation-of-duties now enforced. |
| GJ-3 | A | agent-notes | breadcrumb / memory / reflection skills and CLI | pass | — | skills/file-breadcrumb/SKILL.md, skills/add-memory/SKILL.md, skills/reflect/SKILL.md; src/agent_notes/cli/memory.py | General wiki / document authoring | Skills and CLI both present. |
| GJ-3 | A | agent-notes | signed note write-through to regista | partial | agent-notes WI-013, dossier Plan 009 | src/agent_notes/core/note_model.py, src/agent_notes/core/memory_model.py | — | Write-through implemented but gated; dossier has no note read surface. |
| GJ-3 | B | dossier | knowledge read / browse / search | absent | dossier Plan 009 | — | — | No routes or templates for note / knowledge entities. |
| GJ-3 | A | agent-notes | search across breadcrumbs, memories, links | pass | — | src/agent_notes/cli/search.py | — | CLI search covers all three entity kinds. |
| GJ-4 | A | agent-notes | review CLI (pass, accept, reject, request-changes) | pass | — | src/agent_notes/cli/work_items.py:1053-1131 | — | Adversarial-review skill consumes the same surface. |
| GJ-4 | B | dossier | review queue and verdict forms | pass | — | src/dossier/app.py:629-665, :923-1028 | — | Accept/reject/request-changes supported in web UI. |
| GJ-4 | A | regista | cross-lineage review validators | pass | — | regista canonical workflow; adversarial corpus unauthorized_project_access | — | Workflow enforces distinct actor roles. |
| GJ-4 | B | dossier | honest assurance level / independent-review signal | partial | dossier WI-012 | src/dossier/assurance.py | — | Assurance fail-open fixed (WI-014); computation remains home-grown rather than delegated to regista (WI-012). |
| GJ-5 | A | agent-provenance | session and tool begin/end capture | pass | — | src/cairn/_claude_hook.py; live proof passed 2026-07-11 | Covert monitoring of unsanctioned harnesses, screen recording | Claude and OpenCode hooks are proven; Hermes is provisional. |
| GJ-5 | A | agent-provenance | principal / delegation / work binding | pass | — | src/cairn/adapter.py:744-782; CairnClient.tool_call work_item_id | — | Subagent attribution and on_behalf_of are captured. |
| GJ-5 | B | dossier | session / tool / file activity views | partial | dossier Plan 017/018 | src/dossier/app.py:563-625, src/dossier/provenance.py | — | Session list/detail and tool trail exist; verification UX is partial. |
| GJ-5 | B | dossier | degraded / unsupported capture rendered honestly | partial | dossier WI-012 | src/dossier/assurance.py | — | Assurance level no longer fails open (WI-014 fixed); delegation to regista still pending (WI-012). |
| GJ-6 | C | agent-capability-broker | manifest, reconcile, exec, install-harness | partial | acb Plan 006 WI-1.2 | src/agent_capability_broker/cli.py:448-505; tests/test_doctor_conformance.py | Credential marketplace, device management | Core verbs exist; e2e exec is NotImplementedError. |
| GJ-6 | C | agent-capability-broker | credential provider with secret-safe injection | partial | acb Plan 006 WI-1.2 | src/agent_capability_broker/providers.py:352-494; tests/test_exec.py | — | Provider injection works and is unit-tested; full end-to-end `acb exec` invocation is NotImplementedError. |
| GJ-6 | C | agent-capability-broker | browser / E2E provider and live proof | partial | acb Plan 006 WI-1.2, Plan 007 | src/agent_capability_broker/providers.py:118-258; tests/test_e2e.py | — | E2eProvider.inspect exists; exec is not implemented; Codex deferred. |
| GJ-6 | C | agent-capability-broker | rogue / clobbered capability detection | absent | agent-suite WI-001 capability_clobber | — | — | Doctor only inspects manifest-listed capabilities. |
| GJ-7 | C | agent-wake | authenticated HTTP ingress | pass | — | daemon/src/agent_waked/ingest.py:140-182 | Universal wake protocol | HMAC-SHA256 per-source auth. |
| GJ-7 | C | agent-wake | durable dedup / retry / outbox / dead-letter | partial | agent-wake BC-WAKE-004, BC-WAKE-012 | daemon/src/agent_waked/ingest.py:57-73; tests/test_ingest.py:93-108 | Exactly-once delivery across external systems | Dedup is in-memory FIFO; no durable inbox or dead-letter visibility. |
| GJ-7 | C | agent-wake | live_wake (Claude, OpenCode) | pass | — | adapters/opencode/src/wake.ts:88-157; adapters/claude/src/agent_wake_claude/channel.py | — | Both adapters can deliver live prompts. |
| GJ-7 | C | agent-wake | silent_inject | partial | agent-wake Plan 006 | adapters/opencode/src/wake.ts:125-126 | — | OpenCode supports silent inject; Claude adapter drops silent events. |
| GJ-7 | C | agent-wake | next_session / managed_session delivery | absent | agent-wake Plan 006 | — | — | Design exists; no implementation. |
| GJ-7 | C | agent-wake | human webhook and email delivery | pass | — | daemon/src/agent_waked/channels/webhook.py; daemon/src/agent_waked/channels/email.py | Replacing chat/email providers | Signed webhook and SMTP email channels implemented. |
| GJ-7 | C | agent-wake | replayed event rejection | partial | agent-wake BC-WAKE-004, BC-WAKE-012 | daemon/src/agent_waked/ingest.py:209-210; tests/test_ingest.py:93-108; tests/test_e2e.py:309-343 | — | Duplicate event_id rejected while daemon is running; in-memory dedup is lost on restart, so post-restart replay is not prevented. |
| GJ-7 | B | dossier | notification preferences and review/recovery deep links | absent | Plan 009 WI-3.3, dossier Plan 018 | — | Replacing chat/email providers | No notification preference UI or deep-link routing exists. |
| GJ-8 | A | regista | scoped evidence bundle export | pass | — | Regista.export_audit_bundle; src/regista/_bundle.py:71 | — | Self-contained JSON with events, receipts, segments, public keys. |
| GJ-8 | A | regista | offline bundle verification | pass | — | Regista.verify_audit_bundle_offline; src/regista/_bundle.py:230 | — | v2 verifies ed25519 signatures; v1 reports skipped honestly. |
| GJ-8 | A | agent-provenance | bundle export, diff/chain verify, human report | pass | — | src/cairn/_cli.py:318-750; src/cairn/proof.py | — | cairn verify, verify-chain, export, diff, portal all present. |
| GJ-8 | A | agent-suite | suite-level evidence export orchestration | pass | Plan 009 WI-2.3 | src/agent_suite/evidence.py; tests/test_evidence.py; probe: _probe_evidence_export -> pass | — | Composes regista bundle export + cairn export + verify into one suite-level manifest. |
| GJ-9 | A | agent-suite | profile-aware doctor aggregation | pass | — | src/agent_suite/doctor.py; tests/test_doctor.py | — | Honest health reporting for required/optional components. |
| GJ-9 | A | agent-suite | compatibility lock and drift check | pass | — | src/agent_suite/lock.py; tests/test_lock.py | — | SUITE.lock parsing and drift detection implemented. |
| GJ-9 | A | agent-suite | backup / restore / disaster recovery orchestration | pass | Plan 008 WI-4.1, Plan 009 WI-4.2 | src/agent_suite/backup.py; tests/test_backup.py; probe: _probe_backup_restore -> pass | — | Suite-level backup: doctor → pg_dump → verify → evidence export → manifest. |
| GJ-9 | A | agent-suite | upgrade / rollback / forward-recovery gates | pass | Plan 008 WI-3.4, Plan 009 WI-4.2 | src/agent_suite/upgrade.py (run_upgrade, run_rollback, run_forward_recovery); tests/test_upgrade.py; probe: _probe_upgrade_rollback_forward -> pass | — | Staged upgrade with interop gate, rollback across schema boundaries refused, forward-recovery completes partial upgrades. |
| GJ-9 | A | regista | version / config / secret / doctor contracts | pass | — | regista doctor --json; src/regista/_cli.py doctor commands | — | Doctor, version, and config contracts are exposed. |
