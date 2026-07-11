# Plan 008 — Robust end state: complete product, reproducible deployment, defensible assurance

**Status:** In Progress — **Phase 0 and Phase 1 COMPLETE (closed out 2026-07-11)**; Phases 2–6 not started (Phase 2+ scope coordinates with Plan 009).  
**Author:** GPT-5.6 Sol, following the holistic suite review and first blocker-remediation pass.  
**Strategic role:** Define the bounded end state at which the suite is a
complete, operable, security-reviewable product rather than a collection of
promising mechanisms. This is the integration roadmap above the constituent
plans; it does not move component logic into agent-suite.

## 1. What “robust” means

The end state is not “every possible feature exists.” It is:

1. **The daily workflows are complete.** An agent and a human can create,
   advance, review, understand, and audit the same work without using a hidden
   side channel.
2. **A new environment is reproducible.** A supported release can be installed,
   configured through secret references, verified, upgraded, restored, and
   removed without source-tree knowledge or hand-edited harness configuration.
3. **Failures are bounded and visible.** Every component has a declared
   fail/degrade behavior, health contract, recovery action, and evidence that
   the behavior works.
4. **Security claims are narrower than—or equal to—the evidence.** Integrity,
   attribution, completeness, confidentiality, authorization, and recovery
   claims each point to executable positive and adversarial proofs.
5. **An independent reviewer can verify the record.** Audit evidence can be
   exported and checked offline without production database access or private
   signing keys.
6. **The suite remains thin.** The OS manages services, Postgres stores durable
   truth, components own their domains, and agent-suite owns composition,
   compatibility, operations, documentation, and cross-component proof.

## 2. Permanent boundaries

This plan does **not** authorize:

- a bespoke control plane or long-running suite supervisor;
- a SaaS or mandatory Kubernetes deployment;
- AI/model calls in provisioning, health classification, verification, policy
  enforcement, or any other truth path;
- a second copy of component business logic in agent-suite;
- plaintext secrets in committed files, generated plans, logs, evidence, or
  harness configuration;
- “green by inference” when a required signal is missing or unrecognized;
- support claims for a harness, platform, backend, or deployment profile that
  has not passed its conformance proof.

## 3. Supported deployment profiles

Robustness requires explicit profiles so an intentionally absent optional
component is not confused with a failed required component.

### Profile A — Provenance core

Required:

- regista;
- agent-notes;
- agent-provenance;
- agent-suite.

Provides signed durable work/knowledge state, the agent face, harness capture,
offline verification, bootstrap, lock, doctor, backup, and upgrade operations.

### Profile B — Team workflow

Profile A plus dossier. Provides authenticated human work/review views,
knowledge reading, session/tool trails, key operations, and human acceptance
flows.

### Profile C — Operated full suite

Profile B plus agent-capability-broker and agent-wake. Provides declared
capability parity, credential injection, external signaling, human delivery,
and health/assurance alerting.

Each profile has its own required-component set, health policy, install proof,
resource sizing, and support statement. `doctor` classifies against the selected
profile; it never silently assumes all optional components are required or that
an absent required component is acceptable.

## 4. End-state feature contract

### 4.1 Durable truth and identity — regista

The store must provide:

- append-only, replay-verifiable event and global chains;
- explicit schema/workflow/envelope compatibility;
- per-principal asymmetric signing, enrollment, rotation, revocation, and
  signer/principal binding;
- delegation and session identity sufficient to attribute subagent work;
- generic work, note, session, and provenance entity semantics without
  harness-specific branches;
- transactional migrations and idempotent provisioning;
- retention/archival that preserves verification across active and archived
  segments;
- content-committing external anchoring with independently recomputable
  receipts;
- encrypted sensitive content with explicit key-loss and unavailable-key
  behavior;
- an auditor-facing export that does not require production credentials.

### 4.2 Agent and human faces — agent-notes and dossier

Both faces operate on the same signed record. The end-to-end workflow includes:

- project onboarding with an optional but plainly reported founding spec;
- work creation, assignment/claim, progress, deferral, review, rejection,
  acceptance, and closure;
- separation-of-duties and cross-lineage review where policy requires it;
- signed breadcrumbs, memories, and reflections with links to work, files,
  sessions, and other notes;
- equivalent lifecycle state and identifiers in both faces;
- human views for queues, assigned work, agent activity, sessions, tool trails,
  files touched, verification state, and institutional knowledge;
- accessible, server-rendered core flows that do not require JavaScript for
  security-sensitive actions;
- clear read-only behavior during store or key unavailability; no divergent
  fallback store presented as canonical truth.

### 4.3 Provenance — agent-provenance

The recorder and verifier provide:

- session start/resume/stop and supported tool begin/end capture;
- stable correlation under concurrent tools and subagents;
- principal, model lineage, harness version, session, turn, delegation, and
  work-item binding;
- reproducible argument/output digest semantics with truncation described
  separately from the digest preimage;
- durable degradation evidence when capture cannot reach the store;
- versioned per-harness coverage matrices naming unsupported paths;
- “wired but silent,” orphan begin/end, missing window, and content-coverage
  findings;
- privacy modes ranging from digest-only to authorized encrypted content
  capture, with retention and redaction policies;
- offline bundle verification and a human-readable verification report.

No harness is described as completely captured unless every in-scope action
surface has a tested interception point. Unobservable paths remain named
residual risks.

### 4.4 Capabilities — agent-capability-broker

The broker provides deterministic, secret-safe parity for the capabilities the
estate declares:

- read-only inspect/doctor and dry-run plan paths;
- apply only with explicit authorization, backup, ownership, and no-clobber;
- secret injection into a child process without returning the value to model
  context;
- normalized harness adapters with exact supported-surface boundaries;
- stable credential and browser/E2E providers proven through live tasks;
- provenance for every acting operation;
- explicit unknown/unsupported status for plugin- or harness-owned state the
  broker cannot deterministically resolve.

### 4.5 Signaling — agent-wake

The signaling layer provides:

- authenticated ingress, sender authorization, replay protection, durable
  deduplication, routing, acknowledgement, retry, and dead-letter visibility;
- explicit `live_wake`, `silent_inject`, `next_session`, and
  `managed_session` capability names rather than treating them as equivalent;
- per-principal and per-session routing with broadcast disabled by default;
- human webhook/email delivery for review, health, integrity, and recovery
  events;
- prompt-injection framing and content-size controls;
- provenance correlation from ingress through delivery and resulting work;
- an honest unsupported result when a harness has no external turn-injection
  surface.

## 5. Deployment and operational contract

### 5.1 Release artifacts

Every release produces:

- versioned Python wheels and, where applicable, container images;
- checksums, dependency lock, SBOM, license inventory, and build provenance;
- signed or otherwise verifiable release metadata;
- a committed `SUITE.lock` naming exact component revisions, package versions,
  schema/workflow/envelope versions, and supported profiles/platforms;
- changelogs and migration notes that distinguish compatible, migration-bound,
  and rollback-incompatible changes.

A release is built from a clean tagged tree in CI. Operator machines do not
build production artifacts from mutable local checkouts.

### 5.2 Installation

`agent-suite deploy` (or a deliberately equivalent script) owns the operator
flow:

1. preflight platform, storage, database, secret backend, clock, DNS/TLS, and
   harness prerequisites;
2. select profile, substrate, harnesses, secret backend, and identity source;
3. render a plan with no secret values;
4. install pinned artifacts;
5. provision in documented order;
6. install component-owned harness wiring;
7. verify ownership/trust state;
8. generate/validate the lock;
9. run doctor and the selected-profile smoke proof.

The command is idempotent, supports non-interactive automation, never waits for
confirmation in that mode, and writes an evidence manifest describing actions
without sensitive values. It refuses destructive replacement and offers a
separate explicit repair path.

### 5.3 Supported substrates

The release matrix contains, at minimum:

- one reference Linux distribution with native services;
- Docker/Compose;
- native Windows services and scheduled tasks.

Each supported substrate passes install, reboot, upgrade, backup, restore,
uninstall, path/permission, and harness-wiring conformance. WSL may be documented
as a development convenience but is not evidence for native Windows support.

### 5.4 Upgrade and rollback

An upgrade is an evidence-producing transition from one lock to another:

- stage artifacts and validate compatibility before mutation;
- back up config and data before migration;
- apply component and schema changes in dependency order;
- run doctor, replay, and the profile smoke proof before declaring success;
- automatically restore prior binaries/config when no irreversible migration
  occurred;
- refuse “rollback” across an irreversible schema boundary and run the
  documented forward-recovery procedure instead;
- preserve prior locks and evidence for audit.

### 5.5 Backup, restore, retention, and decommission

The operator can demonstrate:

- stated RPO/RTO objectives for each supported profile;
- scheduled encrypted backups with retention and access policy;
- periodic isolated restore plus replay, signature, chain, archive, and anchor
  verification;
- key backup/recovery or documented intentional non-recoverability by key class;
- retention and legal-hold behavior for events, content, logs, and evidence;
- principal offboarding, key revocation, harness unwiring, secret revocation,
  service removal, and data disposition;
- no committed or generated artifact retains credentials after uninstall.

## 6. Security end state

### 6.1 Claims ledger and threat model

Maintain one suite claims ledger. For every claim, record:

- protected asset and threat actor;
- trust boundary and assumptions;
- enforcing component;
- positive proof;
- adversarial/failure proof;
- residual risk;
- supported profiles/platforms/harness versions;
- last verified release.

The threat model covers at least a malicious or compromised agent, untrusted
repository content, compromised harness plugin/hook, stolen user credential,
stolen signing key, malicious operator/database administrator, network attacker,
dependency compromise, backup theft, rollback attack, and denial of service.

### 6.2 Identity and authorization

- Human identity originates in the configured IdP and is bound to a regista
  principal; request bodies never choose the authenticated actor.
- Agent sessions receive explicit principal/delegation identity and cannot
  self-assert a more privileged role.
- Database roles, Vault/AKV/native-secret policies, services, and delivery
  routes use least privilege per component/project/profile.
- Enrollment, rotation, revocation, recovery, break-glass, and offboarding are
  signed operations with separation of duties where configured.
- Authorization tests include horizontal project access, role escalation,
  confused deputy, stale/revoked key, and delegated self-review attacks.

### 6.3 Confidentiality and data minimization

- Secret references are resolved only at the consuming edge; secrets are never
  emitted through doctor, plan, logs, provenance, reports, or model context.
- Sensitive captured content is encrypted before persistence with versioned
  key IDs and authenticated metadata.
- Digest-only is the default provenance mode unless content capture is
  explicitly enabled with retention, authorization, redaction, and key custody.
- Reports and exports enforce authorization and minimize content by purpose.
- Temporary files, state directories, backups, and hook/plugin data use
  restrictive permissions and bounded retention.

### 6.4 Integrity and independent verification

- Event signatures, principal binding, entity chains, global chains, archive
  seals, bundle links, timestamp tokens, and external anchors are verified by
  one documented auditor path.
- External anchors commit to content, sequence, project, and format—not merely
  identifiers—and verification recomputes the commitment from exported events.
- The offline verifier fails closed on unknown algorithms, versions, missing
  keys, malformed receipts, gaps, duplicates, and unsupported critical fields.
- A verifier build can be reproduced or independently inspected without
  importing the mutable production service stack.

### 6.5 Supply chain and platform security

- CI actions and base images are digest/SHA pinned and dependency updates are
  reviewed.
- Releases include dependency audit, secret/identifier scan, static analysis,
  test evidence, SBOM, and artifact provenance.
- Installers verify artifacts before execution and never curl-to-shell an
  unpinned mutable payload in the production path.
- Services run without root where possible, with narrow filesystem/network
  access and platform-native hardening.
- Outbound network destinations are allowlisted by function; URL-consuming
  components enforce TLS, redirect, DNS-rebinding, and SSRF protections.

## 7. Reliability and observability end state

- Define service objectives for availability, capture freshness, hook delivery,
  backup age, restore verification age, alert delivery, key age, and anchor age.
- Every doctor check has a stable name, severity, evidence, remediation, and
  profile applicability. Unknown contract shapes fail honestly.
- Health distinguishes component absence, unsupported capability, degraded
  optional behavior, unhealthy required behavior, and unreachable dependency.
- Metrics/logs carry correlation IDs but no sensitive payloads; clock skew and
  version drift are visible.
- Capacity guidance covers event rate, connection pools, hook backlog, archive
  growth, content storage, backup size, and verifier memory/runtime.
- Fault tests cover database restart, secret backend outage, network partition,
  disk full, corrupt config, expired/revoked key, provider timeout, duplicate
  delivery, process crash, and partial upgrade.
- Recovery alerts fire on state change and include an all-clear; stable failures
  do not spam indefinitely.

## 8. Implementation phases

### Phase 0 — Freeze the product and assurance contract

#### WI-0.1 — Profile and feature matrix

Publish a machine-readable and human-readable matrix of features, required
components, supported platforms/harnesses/backends, and maturity state
(`experimental`, `supported`, `deprecated`, `unsupported`).

**AC:** doctor, deploy, docs, and release metadata consume or validate against
one source; there is no independent hard-coded list per surface.

#### WI-0.2 — Claims ledger

Create the suite claims ledger described in §6.1, seeded from specs, threat
models, publication reviews, and the holistic review.

**AC:** every security/assurance statement on the README and operator docs maps
to a ledger entry; unsupported claims are removed or marked provisional.

#### WI-0.3 — Plan/status index

Add a cross-repository plan index with plan number, status, owner, dependencies,
supersedes, implementation commits, proof artifact, and last review.

**AC:** duplicate numbers within a repository and “implemented but Proposed”
drift are detected in CI.

### Phase 1 — Truth and independent assurance

**Progress (2026-07-11):** F-1 (Critical, regista anchoring content commitment), F-2 (Critical, agent-provenance live proof session binding), F-3 (High, regista receipt concurrency), F-5 (High, agent-notes DSN fallback), and F-6 (High, doctor honest health) are fixed and committed. F-4 (High, deployment identifiers) was already fixed. Adversarial review of regista anchoring found and fixed 3 additional issues (ambiguous binding serialization, hardcoded SHA-256 in verify, failure_count reset). Claims ledger CL-007/CL-008/CL-012/CL-013 updated. **WI-1.1 implemented:** regista `_bundle.py` adds `export_audit_bundle` (events + anchor receipts + segments as self-contained JSON) and `verify_audit_bundle_offline` (recomputes content anchors, verifies chains without DB); `_archive_segments.py` adds `verify_archive_chain` (cross-segment head_hash → first_event_prev_hash linkage); CLI `regista bundle export|verify` and `regista archive verify-chain`. Adversarial review found and fixed: CRITICAL (since_seq anchor slice), HIGH (constant-time hash, silent exception swallowing, None sort, format_version validation, null checks). **WI-1.2 implemented:** agent-provenance `test_proof_wiring.py` adds SQL fidelity + subprocess path tests for `_query_events`, `_run_canonical_verifier`, `_parse_verifier_report`. Adversarial review found and fixed: CRITICAL (missing file write before verifier), HIGH (sys.path fragility → importlib.util, datetime convention, NULL on_behalf_of SQL verification). **WI-1.3 implemented:** agent-suite `tests/conftest.py` extracts shared fixtures; `tests/test_adversarial_corpus.py` parameterizes 8 mutation types + secret_exposure test. Adversarial review found and fixed: CRITICAL (tautological unauthorized_project_access), HIGH (documented deferred mutations, removed dead code, added post-restore verification). All three repos green CI.

**Phase 1 close-out (2026-07-11, review pass):** An independent review of the Phase 1 work found and fixed four deficiencies, then closed the remaining exit criteria:

- **WI-1.3 corpus never ran in CI** — the interop job (the only job with Postgres + regista) didn't include `test_adversarial_corpus.py`, and the unit jobs have no regista, so every mutation silently skipped. Fixed: corpus added to the interop invocation with a hard-fail guard under `INTEROP_REQUIRE_FACES=1`; 13 tests now run and pass in CI.
- **ANCHOR_MISMATCH mutation was dead code and wrong-layer** — nothing ever triggered anchoring (permanent skip), and it asserted detection via `replay`, which never consults anchor receipts. Rewritten to trigger real anchoring (FileAnchorProvider) and assert `verify_anchor_receipt` returns `failed`.
- **WI-1.2 live proof RUN and PASSED (2026-07-11)** against a real Claude Code 2.1.207 session on the live operator store, with concurrent events from another session in the proof window. The first run caught two real defects fixture tests could not see: a stale install-time harness-version pin (session attestation claimed 2.1.206 while 2.1.207 ran; now live-detected at session start) and a `cairn export --since` crash (regista requires start+end together; open half-window now completed). Both fixed in agent-provenance.
- **WI-1.1 signer-binding gap closed (bundle format v2)** — `verify_audit_bundle_offline` previously verified chain hashes and anchor roots but not event signatures, so a bundle with consistent hashes and forged signatures passed (the WI-1.1 AC names "signer binding"). regista bundle v2 exports the principal public-key registry and verifies asymmetric-scheme event signatures offline, including principal↔signer binding and key validity/revocation windows; HMAC events are counted `signatures_unverifiable` (secret deliberately not exported), unknown schemes fail closed, v1 bundles verify with an explicit `skipped_v1_bundle` report. The money test: forging the LAST event's signature and rehashing the bundle passes every chain check and is caught only by the signature check. Also fixed: `export_audit_bundle` swallowed anchor-receipt/segment enumeration failures (fail-open in an audit tool) — now only a missing table is tolerated and recorded in the manifest (`principal_key_registry`, `anchor_receipts_available`, `segments_available`).

Residuals converted to tracked work items: regista WI-206 (anchoring watermark/doctor visibility, `committed` status), WI-207 (non-SHA-256 anchoring test), WI-208 (envelope v5: sign actor_kind/actor_metadata); agent-provenance WI-028 (extract e2e_proof helpers); agent-suite WI-001 (5 deferred corpus mutations needing agent-wake/ACB/live hooks). Claims ledger CL-012/CL-013 updated with the new evidence.

#### WI-1.1 — Close integrity proof end to end

Complete content-committing anchoring, receipt state/concurrency, archive-chain
verification, and offline bundle recomputation in the owning projects.

**AC:** an exported bundle plus public verification material independently
proves content, order, signer binding, archive continuity, timestamp/anchor, and
format version; single-field tampering fails with a named reason.

#### WI-1.2 — Provenance completeness contract

Finish recorded-reality fixtures and session-correlated live proofs for each
supported harness, including concurrency, subagents, compaction/resume, bridge
outage, and explicitly unsupported surfaces.

**AC:** a proof cannot be satisfied by stale or concurrent decoy events; silence
and missing begin/end events are findings; coverage claims match the matrix.

#### WI-1.3 — Suite adversarial corpus

Create shared synthetic fixtures for forged actor, revoked key, payload change,
chain gap/reorder, anchor mismatch, unauthorized project access, secret
exposure, hook omission, replayed wake event, capability clobber, and corrupted
backup.

**AC:** each mutation fails at the correct owning layer and the suite umbrella
reports the same named failure without exposing sensitive values.

### Phase 2 — Complete the daily product

#### WI-2.1 — Cross-face workflow parity

Finish the coordinated regista/agent-notes/dossier work for lifecycle, review,
knowledge entities, agent activity, files touched, and verified history.

**AC:** a mixed human/agent work item and linked knowledge record can be created,
worked, reviewed by a distinct principal/lineage, accepted, rendered in both
faces, exported, and verified as one record.

#### WI-2.2 — Identity lifecycle

Complete real IdP binding and per-principal onboarding/offboarding across store,
faces, harness wiring, keys, capabilities, wake routes, and audit history.

**AC:** onboarding grants exactly the selected profile/project access;
offboarding revokes future action and delivery while historical verification
continues to work.

#### WI-2.3 — Actionable human operations

Finish review queues, assigned-work views, integrity/health views, notification
preferences, deep links, and key/identity operations.

**AC:** a human can operate the normal and failure workflows without direct SQL,
editing config files, or invoking component-internal Python APIs.

#### WI-2.4 — Harness and capability support

Complete Plan 007 and the component Codex plans; keep Claude/OpenCode regression
proofs green; promote other harnesses only through the profile matrix. Finish
ACB's credential/E2E proof and wake's honest delivery modes.

**AC:** every supported harness passes clean install, coexistence, live task,
provenance, failure, re-run, and uninstall tests in an isolated profile.

### Phase 3 — Productize deployment

#### WI-3.1 — Release pipeline and artifact trust

Implement §5.1 and the supply-chain controls in §6.5.

**AC:** a release candidate is installable using only verified published
artifacts and its lock; rebuilding from the tag produces equivalent artifacts
or a documented reproducibility report.

#### WI-3.2 — One deployment front door

Implement the profile-driven deploy flow in §5.2, composing component CLIs.

**AC:** clean install and idempotent re-run require only documented external
dependencies and operator choices; generated files contain placeholders or
secret references, never secret values.

#### WI-3.3 — Platform conformance

Build automated or repeatable native Linux, Docker, and Windows conformance
runs.

**AC:** two consecutive clean runs per platform complete install, reboot,
doctor, smoke, upgrade, backup/restore, and uninstall without an undocumented
manual step.

#### WI-3.4 — Upgrade/migration safety

Finish staged upgrade, compatibility gates, rollback/forward-recovery, and
evidence capture.

**AC:** injected failure at every transition boundary leaves either the old
healthy release or an explicit recoverable state; no partial success is green.

### Phase 4 — Operate for time, failure, and scale

#### WI-4.1 — Data-protection proof

Set profile RPO/RTO targets, automate encrypted backup/retention, and run
scheduled isolated restore verification.

**AC:** a “disaster day” rebuilds a clean environment from documented artifacts
and backup within the declared targets, with chain/anchor verification green.

#### WI-4.2 — Failure and recovery matrix

Implement the fault cases in §7 and record component/profile behavior.

**AC:** required failures turn the profile red, optional failures degrade by
policy, alerts and recovery notices arrive once, and runbooks restore health.

#### WI-4.3 — Capacity, retention, and archive

Benchmark representative small-team and sustained-load datasets; finish archive
movement/restore and resource guidance.

**AC:** published limits and alert thresholds come from measured runs; archive
and restore preserve offline verification.

#### WI-4.4 — Operational lifecycle

Prove key rotation, certificate/TLS renewal, principal offboarding,
decommission, and evidence retention.

**AC:** each recurring operation is schedulable, observable, reversible where
appropriate, and documented with a dry-run or preview.

### Phase 5 — Security and release acceptance

#### WI-5.1 — Cross-component adversarial review

Run independent reviews by trust boundary rather than only by repository:
identity, crypto/integrity, content confidentiality, harness interception,
capability/secret injection, signaling, web authorization, supply chain, and
operations.

**AC:** all critical/high findings are fixed or explicitly accepted with owner,
expiry, compensating control, and reduced claim language.

#### WI-5.2 — Hermetic release qualification

Create one qualification job that consumes published candidate artifacts and a
fresh isolated environment—not source-tree imports or ambient user config.

**AC:** profile A and B qualify on every release; profile C and each harness/
platform qualify before their support flag is set. Negative corpus and restore
proof are part of the gate.

#### WI-5.3 — Independent audit handoff

Give a reviewer the threat model, claims ledger, SBOM/provenance, lock, public
keys, sanitized evidence bundle, verifier, and runbooks without production
access.

**AC:** the reviewer can reproduce the documented integrity result, identify
coverage limitations, and trace every supported claim to evidence.

#### WI-5.4 — Release-candidate pilot

Operate the candidate for a defined soak period with real daily workflows,
scheduled protection, alerts, key rotation, upgrade, and one disaster exercise.

**AC:** no unresolved critical/high issue, no unexplained red health, no silent
capture gap, no missed protection job, and no undocumented operator intervention
during the acceptance window.

### Phase 6 — Sustainable maintenance

#### WI-6.1 — Release and deprecation policy

Define support windows, schema/API compatibility, security-fix handling,
deprecation notice, and migration ownership.

#### WI-6.2 — Documentation as a tested interface

Consolidate quickstart, deployment, operations, security, troubleshooting, and
auditor paths. Execute command examples against fixtures or smoke environments.

**AC:** a new operator and an independent reviewer each complete their path
without reading source or historical plans.

#### WI-6.3 — Recurring assurance

Schedule dependency review, threat-model review, restore proof, key-policy
review, platform/harness compatibility, and adversarial regression.

**AC:** the release/status page names last-success times and turns stale proof
into a visible finding.

## 9. Sequencing and parallelism

The critical path is:

```
Phase 0 contract
    → Phase 1 truth/assurance
    → Phase 2 daily-product closure
    → Phase 3 deployable artifacts
    → Phase 4 operational proof
    → Phase 5 release acceptance
    → Phase 6 maintenance
```

Allowed parallelism:

- WI-0.1/0.2/0.3 may run together.
- After the claims ledger freezes vocabulary, regista integrity work and
  provenance completeness can run in parallel.
- Human-face, agent-face, identity, and harness work can run in parallel only
  against shared conformance fixtures.
- Release pipeline work may start during Phase 2, but no supported artifact is
  declared until Phase 1 and the relevant feature proof are green.
- Platform conformance may run in parallel by substrate after the deploy
  contract freezes.

Phase 5 is deliberately not parallelized away: the qualified candidate must be
the exact set that passed the earlier gates.

## 10. Definition of done

Plan 008 is complete only when:

1. Profile A and B are supported on the reference Linux and Docker substrates;
   native Windows is supported or explicitly remains experimental with honest
   documentation. Profile C is supported only where both optional components
   pass qualification.
2. A clean operator can deploy, verify, operate, upgrade, restore, and remove a
   profile from published artifacts and documentation.
3. A human and agent complete the mixed workflow and knowledge path through the
   same signed record.
4. Every supported harness passes its live correlated provenance and coexistence
   proof; unsupported action surfaces are named.
5. A malicious single-field event mutation, chain rewrite, signer spoof,
   receipt substitution, session-decoy attempt, unauthorized access, replayed
   signal, capability clobber, and corrupted backup each fail visibly.
6. An offline reviewer verifies a sanitized evidence bundle using public
   material and can identify its scope and residual risks.
7. Backup/restore, key rotation, offboarding, upgrade, and disaster recovery
   have current recorded proofs.
8. Release artifacts carry lock, SBOM, provenance, checksums, migrations,
   support matrix, and changelog.
9. No critical/high finding remains unresolved without formal, time-bounded
   acceptance and reduced claim language.
10. The suite can truthfully replace “active development” with a versioned
    support statement for each qualified profile.

## 11. Success criterion

The suite has reached the robust end state when a new operator, a daily user,
and an independent auditor can each complete their job through a documented,
tested path—and when the evidence continues to hold under tampering, outage,
upgrade, restore, and time.
