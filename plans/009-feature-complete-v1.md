# Plan 009 — Feature-complete v1: shared work, knowledge, evidence, and operations

**Status:** In Progress — Phase 0 started 2026-07-11.  
**Author:** GPT-5.6 Sol.  
**Release coordination:** Plan 015 makes Profile B the supported 1.0 SKU and
sequences these golden journeys into executable release gates. This plan
remains authoritative for feature scope and journey semantics.
**Strategic role:** Define the bounded product surface that fulfills the suite's
actual goals. Plan 008 defines how the product becomes robust, deployable, and
defensible; this plan defines **what the product must do** before it may call
itself feature-complete.

## 1. Product thesis

The suite is feature-complete when a small team can use humans and coding
agents as accountable participants in one durable workflow:

- work is created and advanced through a shared signed state machine;
- agent and human actions are attributable to real principals and sessions;
- institutional knowledge is captured and readable from the appropriate face;
- review and acceptance are separation-of-duties operations, not informal chat;
- tool activity can be inspected and independently verified within a declared
  coverage boundary;
- agents receive the capabilities and signals the estate intentionally grants;
- an operator can install, understand, protect, and evolve the whole system as
  one versioned suite.

This is a focused accountability and coordination product. It is not a general
agent runtime, project-management platform, SIEM, knowledge-management suite,
or workflow automation engine.

## 2. Relationship to Plan 008

The two plans answer different questions:

| Plan | Question |
|------|----------|
| **009 — feature-complete v1** | Are all warranted user and operator jobs possible end to end? |
| **008 — robust end state** | Are those features reproducible, secure, resilient, supportable, and independently defensible? |

A feature may satisfy this plan before it satisfies Plan 008's release-grade
assurance. The suite must not label a public release “supported” until both the
relevant feature gate here and the relevant qualification gate in Plan 008 are
green.

## 3. Intended users and jobs

### 3.1 Agent operator

The operator needs to:

- deploy a selected suite profile;
- configure projects, identity, harnesses, secrets, and policy;
- onboard and offboard people and agent identities;
- see whether the suite and its evidence path are healthy;
- upgrade, back up, restore, rotate keys, and investigate failures;
- export evidence for review without exposing production secrets.

### 3.2 Agent participant

An agent needs to:

- understand the current project, instructions, work queue, and relevant
  knowledge;
- create or claim work without colliding with another participant;
- record progress, blockers, decisions, and reusable knowledge;
- link work to sessions, files, prior knowledge, and dependent work;
- submit work for review and respond to requested changes;
- use approved capabilities without receiving raw credentials;
- receive relevant signals when its harness supports the requested delivery
  mode.

### 3.3 Human collaborator

A human needs to:

- authenticate as a stable principal;
- create, assign, prioritize, defer, review, accept, reject, and search work;
- see what agents are doing and why without reading database rows or raw event
  JSON;
- read agent-produced knowledge and follow links back to work and evidence;
- distinguish verified activity, degraded capture, and unsupported coverage;
- receive actionable notifications for review and operational events.

### 3.4 Reviewer or auditor

A reviewer needs to:

- identify who acted, through which harness/session/delegation, and on whose
  behalf;
- inspect the relevant work, tool, file, review, identity, and key history;
- verify exported evidence without private signing keys;
- see gaps and residual limitations as clearly as successful verification;
- reproduce a report suitable for a human decision.

## 4. Feature-complete deployment profiles

Plan 009 uses Plan 008's profiles, with product—not assurance—requirements.

### Profile A — Provenance core

Feature-complete when an agent can perform the work and knowledge journeys,
with attributable harness activity and verifiable export, entirely through CLI
and skills.

Required components: regista, agent-notes, agent-provenance, agent-suite.

### Profile B — Team workflow

Feature-complete when a human and agent can complete the same journeys through
their respective faces, including review, activity inspection, knowledge
reading, and identity/key operations.

Required components: Profile A plus dossier.

### Profile C — Operated full suite

Feature-complete when declared capabilities can be reconciled and injected, and
work/health/review signals can be routed to agents or humans with honest
delivery semantics.

Required components: Profile B plus agent-capability-broker and agent-wake.

Profile A and B are the v1 product core. Profile C is a supported extension,
not a reason to hold the shared-work product indefinitely before v1.

## 5. The golden journeys

These journeys are the source of truth for feature scope. A proposed feature
belongs in v1 only if it closes a named gap in one of them or is necessary to
operate them safely.

### GJ-1 — Start a project

1. An operator selects a profile and project slug.
2. The suite validates external dependencies and configuration.
3. Regista provisions the project, roles, workflow, and principals.
4. An optional founding spec is validated and signed as event zero; absence is
   allowed but visibly marks the project spec-unanchored.
5. Agent and human faces discover the same project.
6. Selected harnesses are wired idempotently for the relevant components.
7. Doctor reports the project/profile ready or provides an actionable reason.

**Feature-complete result:** no component-specific Python call, direct SQL, or
manual JSON/TOML edit is required.

### GJ-2 — Plan and execute work

1. A human or agent creates a work item with type, title, description,
   priority, links, and optional scheduling/dependency metadata.
2. Another participant can discover, claim/assign, and begin it without a race.
3. The worker records progress, decisions, blockers, files, and related work.
4. Claims expire or release honestly; deferral preserves why and until when.
5. Completion moves to the configured review state rather than bypassing
   policy.

**Feature-complete result:** both faces render the same identifier, lifecycle,
actor, claim, links, and current state.

### GJ-3 — Capture and reuse knowledge

1. An agent files a breadcrumb, memory, or reflection from its normal workflow.
2. The record is signed, project-scoped, searchable, and linked to relevant
   work/files/sessions/knowledge.
3. Duplicate suggestions are advisory and do not silently discard a new fact.
4. A human can browse and read the same canonical record in dossier.
5. A future agent can find it through skills/CLI and understand its provenance.

**Feature-complete result:** the suite has one canonical knowledge record with
two faces; embeddings/search indexes remain projections.

### GJ-4 — Review with separation of duties

1. A worker submits an item with a summary and evidence links.
2. An eligible reviewer sees it in a review queue.
3. Policy evaluates principal, role, lineage, delegation, and required review
   note.
4. The reviewer accepts, rejects, or requests changes.
5. The worker sees requested changes and can resubmit.
6. Final acceptance produces a signed, attributable terminal transition.

**Feature-complete result:** same-principal or policy-prohibited self-review is
blocked; a degraded/offline path cannot silently manufacture acceptance.

**Single-operator posture:** in a solo deployment the operator, human
collaborator, and reviewer are one person. A relaxed review gate is a
legitimate configured policy, not a failure: qualification proves the
enforcement path with two synthetic principals, and a deployment running the
relaxed policy reports that posture honestly rather than simulating a
separation of duties it does not have.

### GJ-5 — Understand agent activity

1. A human opens a work item, agent, or session view.
2. The view shows session identity, harness/model, delegation, tool timeline,
   files touched, linked work, and verification status.
3. Tool arguments/output appear according to the configured privacy mode.
4. Missing, delayed, degraded, or unsupported capture is visually distinct
   from verified capture.
5. The human can navigate from activity to the corresponding work and
   knowledge record.

**Feature-complete result:** a human can answer “what did the agent do, for
which work, and how trustworthy is this record?” without a CLI-only forensic
exercise.

### GJ-6 — Supply an approved capability

1. An operator declares a capability and intended harnesses.
2. ACB inspects each harness and reports absent, healthy, broken, unknown, or
   unsupported.
3. Dry-run shows the exact non-secret wiring changes.
4. Apply backs up and creates only owned entries.
5. An agent invokes the capability through `acb exec`; credentials enter only
   the child environment/file boundary.
6. Cairn records the acting operation without recording the credential.

**Feature-complete result:** credential and browser/E2E providers each have one
real supported journey; plugin-derived state is not falsely claimed if it
cannot be resolved deterministically.

### GJ-7 — Deliver a signal

1. An authorized source submits an idempotent event for a principal, session,
   project, or policy-approved label.
2. Wake authenticates, authorizes, deduplicates, queues, routes, and records it.
3. The selected adapter delivers through a named mode: live wake, silent
   inject, next session, managed session, webhook, or email.
4. Delivery is acknowledged or retried; exhaustion is visible.
5. The resulting session/work can retain the source event correlation.

**Feature-complete result:** at least one agent delivery and one human delivery
are supported end to end; unsupported harness modes are explicit.

### GJ-8 — Investigate and export evidence

1. A reviewer selects a project, work item, session, principal, or time range.
2. The suite exports the relevant events, workflows/spec, keys/public material,
   receipts, coverage statement, and manifest.
3. The verifier checks format, signatures, principal binding, entity/global
   chains, delegation, gaps, timestamps/anchors, and bundle linkage.
4. It emits machine JSON plus a self-contained human report.
5. The report names failures, unknowns, excluded content, and residual coverage.

**Feature-complete result:** the export is useful without live database access
and cannot report verified when required material is absent.

### GJ-9 — Operate and recover

1. Doctor evaluates the selected profile and projects.
2. The operator upgrades through a candidate lock and compatibility proof.
3. Scheduled backup and restore verification run without manual prompting.
4. Key age, store growth, capture freshness, delivery backlog, and protection
   age are visible.
5. A component failure produces an actionable alert; recovery produces an
   all-clear.
6. A prior backup can rebuild a verified suite.

**Feature-complete result:** normal operations use suite commands/runbooks, not
component internals or tribal knowledge.

## 6. Required feature surface by component

### 6.1 regista — warranted v1 surface

Required:

- project/schema provisioning and discovery;
- versioned workflow registration and composition;
- work-item lifecycle, claims, scheduling/defer, typed links, and recurrence;
- generic signed entities for knowledge, session, and provenance records;
- replay, global/entity chain verification, archive continuity, and evidence
  export;
- principal enrollment, role assignment, rotation, revocation, delegation, and
  cross-lineage review validators;
- version/config/secret/doctor contracts;
- encryption and content-committing timestamp/anchor receipts where enabled.

Not required for v1 feature completeness:

- arbitrary user-defined query language;
- a general workflow execution/saga engine;
- distributed consensus beyond Postgres;
- multi-region active/active replication;
- a generic blob/document store;
- billing, tenancy metering, or SaaS administration.

### 6.2 agent-notes — warranted v1 surface

Required:

- harness-neutral skills and CLI for orient/start/end, work, breadcrumbs,
  memories, reflections, links, search, review, and reconciliation;
- canonical regista write-through for shared entities;
- explicit local projections/outbox with honest degraded behavior;
- project resolution from cwd and per-user identity/config;
- install-harness, uninstall, doctor, and source/wheel asset support;
- Codex, Claude, and OpenCode behavior for harnesses marked supported.

Not required:

- a second human web application;
- general document authoring or wiki page layout;
- autonomous planning/orchestration of agents;
- hidden long-term personalization outside signed/project-scoped knowledge.

### 6.3 dossier — warranted v1 surface

Required:

- authenticated project switcher and person-scoped authorization;
- work queues, detail, search, create/edit/transition/review flows;
- verified event history and integrity/assurance indicators;
- agent activity/session/tool/file views;
- read/browse/search for canonical knowledge notes;
- principal/key enrollment and status UX; rotation and revocation may be
  CLI-backed for v1 with a UI readout of current state;
- notification deep links for warranted event classes; preference management
  may be config/CLI-backed for v1;
- accessible server-rendered security-sensitive actions.

Not required:

- a general-purpose dashboard builder;
- rich collaborative document editing;
- chat/messaging;
- sprint planning, time tracking, billing, or portfolio management;
- replacing an enterprise IdP or secret backend.

### 6.4 agent-provenance — warranted v1 surface

Required:

- session, tool begin/end, failure, supported subagent, and stop/resume capture;
- deterministic digests, correlation, degradation, and coverage reporting;
- install/uninstall/doctor for supported harnesses;
- work/session/principal/delegation binding;
- bundle export, offline verify, diff/chain verify, and static human report;
- digest-only default plus explicitly authorized encrypted content capture.

Not required:

- covert monitoring of unsanctioned harnesses;
- endpoint detection/response or full host activity monitoring;
- screen/video recording;
- claiming completeness for tools the harness does not expose;
- a separate authenticated portal when dossier is the human face.

### 6.5 agent-capability-broker — warranted v1 surface

Required:

- manifest, normalized adapter protocol, doctor, shims, reconcile, exec, and
  install-harness;
- credential and browser/E2E providers;
- secret-safe injection, backup/no-clobber, dry-run/apply, and provenance;
- adapters for harnesses marked supported by the suite.

Not required:

- storing credentials or browser sessions;
- arbitrary package/plugin marketplace management;
- generalized device management;
- automatically resolving undocumented effective state;
- a model-driven capability recommendation engine.

### 6.6 agent-wake — warranted v1 surface

Required:

- authenticated HTTP/queue ingress and portable event schema;
- durable dedup, retry/outbox, dead-letter visibility, routing, and identity;
- live/silent delivery for harnesses whose supported APIs provide it;
- next-session or managed-session delivery where that is the honest boundary;
- human webhook and email delivery;
- subscription labels, acknowledgements/replies where supported, doctor, and
  install/uninstall;
- provenance correlation.

Not required:

- starting arbitrary user-managed sessions through UI automation;
- becoming a workflow scheduler;
- replacing chat/email providers;
- guaranteeing exactly-once delivery across external systems;
- inventing a universal wake protocol ahead of stable harness support.

### 6.7 agent-suite — warranted v1 surface

Required:

- profile-aware bootstrap/deploy, project onboarding, per-user onboarding, and
  harness selection;
- compatibility lock, drift check, upgrade/rollback/forward-recovery gates;
- profile-aware doctor with actionable remediation;
- suite interop, tamper, install/reinstall/uninstall, and deployed-set proofs;
- scheduled backup/verify-restore, health alerts, key/growth/capture watches;
- Linux, Docker, and Windows operator paths with honest support status;
- one coherent operator, security, recovery, and auditor documentation set.

Not required:

- reimplementing component installers or business logic;
- a daemon/control plane;
- Kubernetes operators or mandatory cloud resources;
- fleet-wide remote management;
- a graphical suite administration console for v1.

## 7. Cross-cutting product decisions to freeze

### 7.1 Canonical lifecycle vocabulary

One machine-readable workflow contract owns states, transitions, roles, review
semantics, terminality, and deferral. Both faces and all proofs consume it.

### 7.2 Canonical identity vocabulary

`principal_id`, `actor_id`, `session_id`, `turn_id`, `agent_id`, delegation,
model lineage, harness name/version, project, and work-item binding each have one
definition and serialization.

### 7.3 Canonical knowledge split

Breadcrumbs with lifecycle remain work items if their state is meaningful;
memories/reflections are signed note entities. This split is an unresolved
design decision, not settled documentation: it is frozen in Phase 0 (WI-0.2
contract fixtures) with a named owner before WI-1.2 begins, and known
divergent stores (e.g., legacy file-based breadcrumbs invisible to the CLI/DB
path) are explicitly migrated or declared out of scope at the same time.

### 7.4 Privacy modes

At minimum:

- **digest-only** — default, no prompt/response content;
- **selected content** — configured event/content classes, encrypted;
- **session content** — explicit high-sensitivity mode with authorization,
  redaction, retention, and visible deployment posture.

### 7.5 Harness support levels

- **Supported:** install, live positive/negative proof, coverage matrix, doctor,
  coexistence, and uninstall pass at qualification time against a recorded
  harness version, plus a drift signal: a doctor-level coverage probe verifies
  the claimed hook surfaces still fire and ages out stale coverage evidence.
  Self-updating harnesses make a standing version-range warranty
  unmaintainable; support means "proven at qualification and monitored for
  drift," never a promise about unreleased harness versions.
- **Experimental:** adapter exists; gaps are expected and clearly surfaced.
- **Unsupported:** no success/no-op simulation.

`all` expands only to suite-supported harnesses for the release. Experimental
targets remain explicit.

## 8. Implementation phases

**Known concrete blockers.** The 2026-07-10 holistic review findings F-1–F-6
(`docs/2026-07-10-holistic-suite-review.md`) were resolved by Plan 008 Phase 1
(2026-07-11). They are retained below for context; the current state is reflected
in the WI-0.1 matrix. Two were foundations, not polish: harness capture was
non-functional (hooks unwired, and the hook read `tool_output` where the harness
sent `tool_response`) and the provenance live proof could pass against decoy
events (F-2). Both were fixed before Plan 008 Phase 1 closed, but Phase 2 work
must still verify that capture remains functional as the face code evolves.

### Phase 0 — Freeze v1 scope and golden-journey contracts

#### WI-0.1 — Feature matrix, generated from the baseline

Turn §§5–7 into a cross-repository matrix: journey, owning component, public
surface, status, dependency, proof, and excluded adjacent features. The status
column is **emitted by the WI-0.3 baseline run**, not hand-maintained: one
artifact, machine-written, registered with the plan index (Plan 008 WI-0.3
tooling). Two parallel matrices — one aspirational, one observed — would drift
immediately.

**AC:** every open v1 work item maps to a golden journey; anything that does not
map is deferred or justified as required operational/security support; the
matrix's status column is reproducible by re-running the baseline.

#### WI-0.2 — Shared contract artifacts

Freeze lifecycle, identity, knowledge, evidence/export, health, install-harness,
and notification contracts as versioned conformance fixtures.

**AC:** consumers validate fixtures in CI; no face or adapter maintains a
semantically divergent copy.

**Progress (2026-07-11):** Seven versioned JSON fixtures created in
`data/contracts/` (lifecycle, identity, health, evidence-export,
install-harness, knowledge, notification). `scripts/validate-contracts.py`
validates fixture meta-structure, cross-references health-contract enums
against live Python enums in the codebase (ComponentStatus, Tier, DriftKind,
ProjectVerifyStatus, KeyAgeStatus, StoreGrowthStatus), and validates
snapshot assertions plus referential integrity and partition constraints
for the other contracts. `tests/test_contracts.py` provides 26 tests
running in CI. The contract check runs in both the `lint-and-test` and
`windows-test` CI jobs.

#### WI-0.3 — Baseline and gap burn-down

Run every golden journey against current `main` and write the sanitized status
(pass, partial, blocked, absent) into the WI-0.1 matrix — the baseline
produces the matrix's observed state rather than a second document.

**AC:** the remaining plan contains only observed gaps; stale proposed work that
already landed is marked complete rather than reimplemented.

**Progress (2026-07-11):** WI-0.1 initial matrix created in `data/v1-feature-matrix.json` with generator `scripts/feature-matrix.py` and rendered human-readable matrix `docs/v1-feature-matrix.md`. The matrix covers all nine golden journeys, seven components, and forty-six public surfaces, using statuses pass/partial/blocked/absent with source noted as `hand-assessed`. WI-0.3 probe automation is stubbed; current statuses will be replaced by executable probes as Phase 0 continues.

### Phase 1 — Complete shared work and knowledge

#### WI-1.1 — Work lifecycle parity

Close creation, claim/assignment, progress, links, dependency/defer, review,
requested changes, acceptance, and search gaps across regista, agent-notes, and
dossier.

**AC:** GJ-2 and GJ-4 pass from both faces against the same record, including
concurrent claim and prohibited-self-review negatives.

#### WI-1.2 — Knowledge parity

Finish signed memory/reflection write-through, links, search projection, and
dossier read/browse surfaces.

**AC:** GJ-3 passes; deleting/rebuilding the search projection does not alter
canonical records.

#### WI-1.3 — Project and identity onboarding

Complete project founding, principal binding, user overlay, key enrollment, and
harness wiring through suite commands.

**AC:** GJ-1 passes for a new project and two distinct principals without a
manual component config edit.

### Phase 2 — Complete evidence and human legibility

#### WI-2.1 — Session/tool/delegation record

**Depends on:** agent-provenance Plan 009 (capture repair) and holistic-review
F-2 (session-correlated proof). Until both land, this WI is blocked, not
partially done.

Finish supported lifecycle capture, correlation, degradation, and work binding
for the supported harness matrix.

**AC:** GJ-5 passes for normal, concurrent-subagent, tool-failure, and bridge-
outage sessions; unsupported actions remain visible gaps.

#### WI-2.2 — Human activity and assurance views

This is the largest single build in the plan — most of a new product surface
over a dossier that today has none of these views. It requires its own
decomposition plan in the dossier repository before implementation begins; it
must not be picked up as one work item.

Finish dossier session/activity/tool/file/integrity views and link navigation.

**AC:** a human completes GJ-5 without invoking the verifier CLI, while the UI
never upgrades unknown/degraded evidence to verified.

#### WI-2.3 — Evidence export and report

**Depends on:** holistic-review F-1 (content-committing anchoring) and F-3
(receipt state machine and concurrency).

Finish scoped export, offline verification, bundle linkage, and self-contained
human report.

**AC:** GJ-8 passes with no production credentials; stale-session and tamper
decoys fail.

### Phase 3 — Complete optional full-suite capabilities

#### WI-3.1 — Capability parity

Close credential and E2E provider journeys plus supported harness adapters.

**AC:** GJ-6 passes for one synthetic credential and one browser task in every
suite-supported harness; secret scans remain clean.

#### WI-3.2 — Agent signaling

Close supported live/silent/next/managed delivery modes with routing,
deduplication, retry, acknowledgement, and provenance.

**AC:** the agent half of GJ-7 passes for each claimed mode; unavailable native
wake is reported unsupported rather than emulated unsafely.

#### WI-3.3 — Human delivery

Finish review, failure, recovery, and digest notification events through webhook
and email.

**AC:** the human half of GJ-7 passes with deep link, identity authorization,
retry, deduplication, and recovery notice.

### Phase 4 — Complete the operator product

#### WI-4.1 — One front door

Finish profile-aware deploy/bootstrap, onboard, harness selection, lock, doctor,
and removal flows.

**AC:** GJ-1 can start from published artifacts and a clean profile; re-run is a
no-op and uninstall preserves unrelated state.

#### WI-4.2 — Operate and recover

Finish upgrade, rollback/forward recovery, scheduled protection, watches,
alerts, and restore orchestration.

**AC:** GJ-9 passes, including one injected upgrade failure and one corrupted-
backup negative.

#### WI-4.3 — Documentation by user job

Consolidate operator, agent, human reviewer, auditor, security, troubleshooting,
and recovery paths around the golden journeys.

**AC:** each persona completes its journey from the documentation without
reading source or historical plan rationale.

### Phase 5 — Feature-complete qualification

#### WI-5.1 — Hermetic golden-journey suite

Run GJ-1 through GJ-9 from pinned candidate artifacts in isolated homes,
databases, secrets, and harness profiles.

**AC:** Profile A and B pass all applicable journeys; Profile C passes its
additional journeys before being marked feature-complete.

#### WI-5.2 — Cross-platform and harness matrix

Run the journey subset affected by native Linux, Docker, Windows, and each
supported harness.

**AC:** support labels match evidence; a platform/harness may remain
experimental without blocking v1 if the published core profile has a supported
path.

#### WI-5.3 — Scope audit

Review the release against every “Not required” list in §6.

**AC:** no deferred adjacent product has become an undeclared dependency; no
required golden journey relies on an out-of-scope manual workaround.

## 9. Prioritization

The warranted order is:

1. shared work/review and knowledge parity;
2. truthful provenance plus human legibility;
3. project/identity onboarding and operator front door;
4. evidence export;
5. optional capability and signaling completeness;
6. final golden-journey qualification.

This order produces a useful Profile A/B product before polishing optional
Profile C extensions. Work may run in parallel only after the shared contracts
in Phase 0 freeze.

## 10. Feature-complete definition of done

The suite may call a profile feature-complete only when:

1. Every applicable golden journey passes through supported public surfaces.
2. Human and agent faces show the same canonical identifiers, lifecycle, links,
   actors, and verification state.
3. Review/acceptance enforces configured separation of duties.
4. Knowledge records are signed, searchable, linked, and readable from both
   appropriate faces.
5. Supported harness sessions and tool calls are correlated to principal,
   delegation, work, and coverage state.
6. Evidence export and offline verification complete without production
   credentials.
7. Profile deployment, onboarding, doctor, upgrade, protection, recovery, and
   uninstall have public suite-level paths.
8. Optional capability and delivery features are required only for Profile C,
   and every claimed mode/provider has a live proof.
9. Unknown, degraded, absent, and unsupported states are never presented as
   successful features.
10. No required journey depends on direct SQL, hand-edited harness config,
    component-internal Python, a mutable source checkout, or undocumented
    operator knowledge.
11. The feature matrix and documentation mark adjacent ambitions as deferred,
    preventing v1 scope from reopening by implication.
12. The pre-existing dogfood deployment upgrades in place into the
    feature-complete release without data loss; historical records on prior
    workflow/envelope versions remain readable and verifiable. The live estate
    is a qualification target, not only fresh hermetic profiles.
13. Plan 008 qualification determines whether the feature-complete profile is
    also robust and supported for release.

### 10.1 Intermediate milestone — v1-dogfood

The full definition of done above, combined with Plan 008's qualification bar,
is an audit-grade target that is months away for a solo-operated estate. Until
it is met, everything would truthfully be "not ready," which both mislabels
real progress and starves the plan index of a nameable state. Therefore one
intermediate milestone is defined:

**v1-dogfood** is declared when:

1. Profile A and B golden journeys pass on the live dogfood deployment — the
   real estate, not only hermetic fixtures;
2. Plan 008 Phases 0–2 are complete;
3. every capability beyond that evidence is phrased as provisional.

v1-dogfood is an honest intermediate label between "promising mechanisms" and
the release-grade bar. It carries no support statement and no external
assurance claim.

## 11. The warranted v1

The warranted v1 is deliberately modest in product category and ambitious in
cohesion:

- one signed workflow record;
- two fit-for-purpose faces;
- accountable agent sessions and tool activity;
- reusable signed knowledge;
- real review and acceptance;
- secret-safe capabilities;
- honest signaling;
- one operator surface;
- one independent evidence path.

If those pieces work together without hidden side channels, the suite is
feature-complete for its goals. Everything beyond them should earn its place by
closing a demonstrated journey gap rather than by making the suite look more
like a general platform.
