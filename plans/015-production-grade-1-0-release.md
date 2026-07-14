# Plan 015 — Production-grade 1.0 release closure

**Status:** In Progress — Gate 0 execution started 2026-07-14. WI-0.1 (executable
probes) complete; WI-0.2 (state reconciliation) in progress (SUITE.lock updated,
identifier gate replaced, inventory CLI pending); WI-0.3 (support matrix) updated
with ratified platforms (linux/k8s/Windows/docker, PostgreSQL 18+, Python
3.12/3.13/3.14, Chrome/Edge/Safari/Firefox); WI-0.4 (release board) in progress.
**Owner:** agent-suite coordinates the release; each constituent owns its
domain; dossier owns the normal human interface.
**Depends:** agent-suite Plans 008, 009, 013, and 014; dossier Plans 015 and
018–024; regista Plan 031; the corresponding agent-notes, cairn, ACB, and wake
provider/qualification plans.
**Strategic role:** Convert the feature and robustness roadmaps into one bounded,
evidence-producing release train. This plan does not add a new capability or
move component logic into agent-suite. It decides what 1.0 means, orders the
remaining work, and defines the evidence required to publish and support it.

## 1. Release decision

### 1.1 The supported 1.0 product is Profile B

The first production-grade 1.0 release supports **Profile B — Team workflow**:

- regista;
- agent-notes;
- agent-provenance (`cairn`);
- dossier;
- agent-suite.

This is the smallest product that fulfills the suite thesis: a human and an
agent use the same signed work and knowledge record, agent activity is
inspectable and independently verifiable within a declared coverage boundary,
and an operator can deploy, protect, upgrade, and recover the system as one
versioned release.

Profile A remains a supported subset for CLI-first/single-operator use.

Profile C adds agent-capability-broker and agent-wake. The 1.0 lock pins them and
the release may ship them, but their incomplete provider/durability modes are
labelled **preview** until their own Profile C gates pass. Profile C work cannot
delay Profile B 1.0 unless Profile B has acquired an undeclared runtime
dependency on it. Dossier notifications may use wake when deployed, but the
canonical work/review path remains correct and visible when delivery is absent.

### 1.2 Dossier is the human product

Dossier is the sole normal browser interface for 1.0. Its six areas are the
human information architecture:

1. Work;
2. Knowledge;
3. Activity;
4. Evidence;
5. Operations;
6. Administration.

Component CLIs remain supported for agents, automation, expert diagnosis, and
break-glass recovery. Cairn's static evidence report remains the independent
offline artifact. Agent Suite Setup is the narrow Windows host surface before
dossier is reachable; it is not a second suite console.

### 1.3 Production-grade is a release property

No component version, test count, or live dogfood deployment independently
makes the suite production-grade. A 1.0 candidate is releasable only when:

- the exact artifacts under test are the artifacts to be published;
- every required Profile B journey passes through public surfaces;
- supported security and recovery claims have positive and adversarial proof;
- a clean supported environment and the existing dogfood estate both converge
  to the same green release identity;
- known failures, unsupported modes, and residual risks are visible and scoped;
- installation, upgrade, rollback/forward recovery, backup, restore, and
  decommission are operator-supported workflows.

## 2. Relationship to existing plans

This plan is the **release index and gate sequence**, not a replacement for
domain plans:

| Source plan | Remains authoritative for | Plan 015 consumes |
|---|---|---|
| agent-suite 008 | robustness, assurance, operations, supportability | qualification gates and claims discipline |
| agent-suite 009 | v1 golden journeys and feature boundary | executable Profile A/B journey results |
| agent-suite 013 | two-surface human product and Windows-first posture | dossier/Setup ownership and shared contracts |
| agent-suite 014 | Windows executor, dual control, Entra/JWKS, packaging | qualified host setup primitives |
| dossier 015 | key lifecycle and custody UX | supported identity/key administration journey |
| dossier 018–019 | daily work views and durable notifications | review queue, my work, activity, preferences, delivery state |
| dossier 020 | Entra/OIDC and step-up | workplace sign-in and protected-operation authentication |
| dossier 021 | evidence review and accessibility | case-bound review, disclosure, WCAG qualification |
| dossier 022 | safe web administration | provider registry, draft/diff/approval/apply/receipt loop |
| dossier 023 | central-service dogfood deployment | one real shared-service convergence target, not a k8s requirement |
| dossier 024 | suite console shell and provider seams | the six-area browser product and its completion gate |

When this plan and an older status line disagree about release sequencing, this
plan controls sequencing; the older plan continues to control its domain
contract. Work is closed in the owning repository and reflected here by
evidence, not reimplemented here.

## 3. Supported-release boundary to freeze in Gate 0

The release matrix must name, rather than imply:

- required and optional components for Profiles A, B, and C;
- reference server substrate(s), native Windows client/setup support, database
  versions, Python versions, browsers, and harness adapters;
- supported identity and secret/custody backends;
- required availability, backup, restore, and upgrade objectives;
- supported versus preview assurance claims;
- compatibility and support windows (including N-1 upgrade input);
- explicitly excluded surfaces, deployment modes, and provider capabilities.

The recommended minimum 1.0 lanes are one reference Linux central-service
deployment, native Windows client/setup, and the documented container path.
Gate 0 must either ratify this matrix or narrow it explicitly. A platform is not
supported merely because unit tests import on it.

Kubernetes may qualify dossier Plan 023's dogfood deployment but remains an
optional substrate. It is not a suite dependency or the only supported path.

## 4. Gate 0 — Reconcile truth and freeze the release candidate contract

### WI-0.1 — Replace hand assessment with executable baseline probes

Finish agent-suite Plan 009 WI-0.3. Each feature-matrix row must be emitted by a
named probe against an identified revision set. A probe reports `pass`,
`partial`, `blocked`, or `absent`, plus evidence location and observed release
identity. Hand-authored status remains commentary only.

**AC:** regenerating `data/v1-feature-matrix.json` from a clean checkout
reproduces every status; stale rows that conflict with landed dossier or suite
work are corrected; every failing Profile B row maps to exactly one owning WI.

### WI-0.2 — Reconcile plans, source state, and dogfood state

Record the state of every constituent: origin revision, local-only commits,
uncommitted work, package version, schema/workflow/envelope versions, plan
status, and deployed version. Publish no candidate from a mixed dirty/ahead
workspace.

Close or amend stale plan status lines rather than creating duplicate work.
Plan 014's implementation foundations, for example, are distinct from live
Windows qualification and must be recorded that way.

**AC:** one generated candidate inventory names all seven repositories and the
deployed estate; no release input is `main`, an uncommitted tree, an unpushed
commit, or an unidentified local artifact.

### WI-0.3 — Ratify the 1.0 support matrix and objectives

Choose exact supported versions/platforms and measurable objectives. At
minimum, define backup cadence, maximum acceptable recovery-point loss,
restore-time target, health/alert cadence, key-rotation policy, and the duration
of the release-candidate soak.

**AC:** CI lanes, install docs, doctor profile rules, and release metadata are
generated from or mechanically checked against the same support matrix.

### WI-0.4 — Establish the release board

Create a machine-readable release ledger containing gate, WI, owner repository,
blocking dependency, status, proof command/artifact, and candidate revision.
The feature matrix, claims ledger, and release ledger cross-reference stable
IDs; they do not become three competing status systems.

**Gate 0 exit:** scope is frozen; every remaining Profile B gap has an owner and
proof; optional Profile C work is visibly separated; all candidate inputs are
clean and identifiable.

## 5. Gate 1 — Complete the Profile B product through dossier

### WI-1.1 — Freeze versioned provider contracts

Complete the provider seams named by dossier Plan 024: work, knowledge,
activity/evidence, operations, identity/key, configuration, capability, and
delivery. Each owning component exposes a public, versioned describe/read/plan/
apply/receipt surface appropriate to its domain.

Dossier consumes contracts; it does not import component-private modules, query
private tables, recompute cryptographic verdicts, or gain host/service-manager
authority. Unknown contract versions and values fail closed into explicit
`unknown` or `unsupported` states.

**AC:** shared fixtures exercise every status/error; architecture tests reject
private production imports and direct private-store access; dossier can render
synthetic unavailable, stale, partial, and incompatible providers.

### WI-1.2 — Work and knowledge journeys

Close agent-suite GJ-1 through GJ-4 for Profile B using dossier Plans 018 and
024 plus the agent-notes knowledge provider:

- project discovery/onboarding and stable principal binding;
- work creation, claim/assignment, transition, dependency, review, requested
  changes, acceptance, and search;
- signed knowledge browse/search/detail/link from dossier;
- identical canonical identifiers, lifecycle, actors, and verification state
  in dossier and agent-notes;
- fail-closed review assurance when lineage, delegation, role, or policy data is
  missing.

**AC:** two synthetic principals complete the strict review journey; same-
principal, same-lineage, missing-lineage, expired-claim, stale-form, and
unauthorized-project cases fail for the intended reason. A configured solo
policy remains possible and is labelled honestly.

### WI-1.3 — Activity and evidence journeys

Complete dossier Plans 021 and 024 for GJ-5 and GJ-8:

- session/tool/file/work timelines sourced from cairn public providers;
- visible coverage boundary, degradation, freshness, verification span, and
  unsupported capture;
- scoped case/export planning and independent approval where policy requires;
- offline bundle plus self-contained human report;
- protected disclosure without giving the ordinary dossier process plaintext
  evidence authority.

**AC:** a reviewer answers who acted, for which work, through which session and
delegation, with what verified coverage, without a CLI. Concurrent decoy,
missing event, wrong key, altered content, unavailable provider, and stale proof
cases remain visibly non-green.

### WI-1.4 — Identity, keys, and protected administration

Complete the supported portions of dossier Plans 015, 020, and 022:

- workplace sign-in bound to immutable identity claims;
- session lifecycle and offboarding behavior;
- public regista principal-lifecycle API only;
- no private key material in browser or ordinary dossier process;
- step-up bound to a frozen action digest;
- genuine second-principal approval for protected actions;
- project-scoped enrollment/rotation/revocation with durable partial-result
  repair;
- effective-use proof before declaring a new key active for its intended client.

**AC:** private-import, secret/page-source, approval replay, changed-scope,
same-principal dual-control, disabled-user, partial-project, custody outage, and
historical-verification tests all pass.

### WI-1.5 — Daily operation and notifications

Complete dossier Plans 018–019 at the product boundary. Review and operational
intent is committed durably after the authoritative transition. Delivery state,
retry, exhaustion, preferences, digests, and authorization-checked deep links
are visible in dossier.

Wake may provide the delivery leg, but a missing preview delivery provider does
not lose or corrupt canonical work. If durable wake semantics are not qualified
for 1.0, dossier must label the delivery mode preview and retain a supported
human notification path or an explicit queue-only posture.

### WI-1.6 — Console and accessibility qualification

Finish dossier Plan 024's six-area shell using the shared page contract. Core
security-sensitive journeys work without JavaScript. Qualify authorization
below templates and WCAG 2.2 AA for the agreed browser matrix, including
keyboard, screen reader, 200% zoom, high contrast, reduced motion, narrow
viewport, print/PDF, slow provider, and malicious attested strings.

**Gate 1 exit:** every applicable Profile B product row is probe-emitted pass;
dossier is the sole normal browser surface; no journey requires direct SQL,
component-private Python, raw event JSON, or manual harness/config editing.

## 6. Gate 2 — Make candidate artifacts immutable and reproducible

### WI-2.1 — Replace the current compatibility lock

`SUITE.lock` must pin every constituent by repository, immutable revision,
package version, and artifact digest. It also records the regista compatibility
quad, provider protocol versions/extensions, required/optional status per
profile, supported platform matrix identity, and lock format version.

Lock generation refuses to certify an absent required component, an
unpublished/local revision, a version/revision mismatch, or an artifact without
a digest. A partial developer lock is a different explicitly named artifact and
cannot be promoted.

### WI-2.2 — Test the lock, not moving branches

Interop and golden-journey CI build/install exclusively from the candidate
lock. Remove `@main` installs. Pin Actions and service images by immutable SHA or
digest. Profile A/B jobs are hard gates; preview Profile C jobs may be
non-blocking only when the release metadata says preview.

**AC:** changing an upstream branch after candidate creation cannot change the
candidate build; rebuilding the same lock produces byte-identical artifacts or
a named, investigated reproducibility variance.

### WI-2.3 — Publish one release bundle

CI produces, from clean signed/tagged trees:

- wheels and supported container/Windows artifacts;
- the certified `SUITE.lock` and support matrix;
- SHA-256 checksums and signatures/attestations;
- dependency locks, SBOMs, license inventory, and vulnerability report;
- migration and rollback/forward-recovery metadata;
- generated release notes and sanitized proof manifest.

Package metadata must contain the real release version, ownership, repository,
and support links. No placeholder organization metadata remains in published
artifacts.

### WI-2.4 — Supply-chain and publication gates

Run dependency audit, secret/identifier scan, license policy, artifact-content
inspection, and provenance verification over the built bundle. Publication
review applies to the exact candidate tree and artifacts, not an older clean
snapshot.

**Gate 2 exit:** one immutable bundle can be installed without a source checkout
or network resolution of mutable branches; CI proves exactly that bundle.

## 7. Gate 3 — Close or narrow the production assurance claims

### WI-3.1 — Required supported claims

For Profile B 1.0, the following must be `supported` in the claims ledger with
positive and adversarial proof:

- event integrity and tamper detection;
- per-principal Ed25519 attribution and binding;
- cross-face interoperability;
- honest profile health and lock drift;
- secret and private-key boundary safety;
- idempotent install/onboard/repair;
- upgrade and migration safety;
- backup, post-restore integrity, and historical verification;
- delegation/review enforcement used by the supported workflow;
- offline export verification within the declared coverage boundary.

### WI-3.2 — Optional claims are qualified or excluded

External anchoring, encrypted session content, advanced disclosure, preview
harnesses, and other non-core assurances either pass their full adversarial
qualification or remain explicitly experimental/excluded from the 1.0 support
statement. Mechanism presence is not a supported claim.

### WI-3.3 — Security and privacy review

Threat-model the composed release, not only individual components. Review authn,
authz, CSRF/CSP/session posture, signing authority, custody, secret references,
SSRF, prompt-injection framing, export disclosure, support bundles, logs,
installer privilege boundaries, dual control, and supply chain.

Every critical/high finding is fixed, explicitly accepted by the owner with a
bounded release statement, or removes the affected feature from the supported
surface. Critical findings cannot be accepted into 1.0.

**Gate 3 exit:** the claims ledger, UI wording, documentation, and actual proof
agree; no supported assurance sentence depends on an approximation test.

## 8. Gate 4 — Qualify deployment, migration, and recovery

### WI-4.1 — Hermetic clean-install convergence

From the candidate bundle, run preflight → install → onboard → doctor →
golden journeys → reinstall/no-op → reboot/restart → uninstall on every
supported lane. Use isolated HOME/config roots, synthetic identities/secrets,
fresh databases, and no ambient harness state.

### WI-4.2 — Native Windows proof

Qualify Agent Suite Setup on a clean native Windows target: artifact
verification, DPAPI user/machine locality, service account/profile behavior,
WinSW lifecycle, scheduled tasks, harness wiring, signed receipts, dual-control
replay protection, repair, upgrade, and uninstall. Unit tests on
`windows-latest` are necessary but not sufficient.

### WI-4.3 — Schema and release transition proof

Prove supported N-1 → 1.0 upgrade against realistic data and every required
schema. Stage and back up before migration, apply in dependency order, preserve
old verification material, and distinguish rollback-safe from
forward-recovery-only boundaries.

Inject failure before migration, during component upgrade, after one schema,
after binary replacement, and during post-upgrade proof. No partial transition
may report green.

### WI-4.4 — Protection and disaster recovery proof

Run scheduled backup and restore into an independently provisioned target.
Verify events, global/entity chains, principals/keys/public material, workflow,
knowledge, provenance, configuration revisions, and notification intents.
Measure the Gate 0 recovery objectives. Exercise corrupted, incomplete, stale,
wrong-key, and unavailable-backend cases.

### WI-4.5 — Existing-estate convergence

Upgrade the existing dogfood estate from its recorded lock/schema state to the
candidate without manual source-tree fixes. Dossier Plan 023 supplies one real
central-service target. Sanitize evidence before committing it.

**Gate 4 exit:** clean and existing environments converge to the same green
lock/doctor/profile result; restore and forward recovery meet the ratified
objectives; every deviation is fixed or removes a support label.

## 9. Gate 5 — Release candidate, soak, and publication

### WI-5.1 — Cut RC1 and freeze inputs

Tag all candidate constituent revisions, generate the lock and bundle in CI,
and permit only reviewed release-blocker fixes. Every fix produces RC2+ and
reruns affected lower gates; no artifact is replaced in place.

### WI-5.2 — Operate the candidate

Run the ratified soak (recommended minimum: 14 consecutive days) with scheduled
doctor/alerts, backup, at least one restore rehearsal, ordinary human/agent
work, key/identity observation, and delivery/provider failure observation.
Record SLO results and every manual intervention.

### WI-5.3 — Documentation and support readiness

Publish job-oriented install, onboarding, daily use, administration, evidence,
upgrade, backup/restore, troubleshooting, security, privacy, and decommission
documentation. Define support channels, severity policy, vulnerability
reporting, compatibility window, and patch-release process.

Historical plans and reflections remain design history; they are not required
reading for an operator.

### WI-5.4 — Final release review

The release owner reviews the exact bundle against the checklist below, records
accepted residual risks and preview features, and promotes without rebuilding.

**Gate 5 exit:** the soaked, reviewed RC artifact is promoted unchanged to
1.0.0; installation and verification instructions begin from that immutable
artifact.

## 10. Ownership and critical path

| Workstream | Primary owner | Critical Profile B dependency |
|---|---|---|
| Compatibility, release bundle, cross-suite CI | agent-suite | all gates |
| Durable truth, migrations, public lifecycle, signing | regista | Gates 1, 3, 4 |
| Agent work/knowledge provider and harness UX | agent-notes | Gate 1 |
| Human console, auth, review, admin, accessibility | dossier | Gate 1 critical path |
| Capture, provider summaries, export/verifier | agent-provenance | Gates 1 and 3 |
| Capability provider | ACB | Profile C preview; must not block Profile B |
| Delivery provider | agent-wake | notification support choice; Profile C preview |

The likely critical path is:

1. Gate 0 executable baseline and support decision;
2. public provider contracts;
3. dossier Profile B journey closure;
4. immutable lock/release pipeline;
5. assurance and migration/recovery qualification;
6. native Windows + existing-estate convergence;
7. RC soak and publication.

Optional feature expansion stops when it competes with this path.

## 11. Final 1.0 release checklist

A release owner may promote 1.0 only when all are true:

- [ ] Profile A and B feature-matrix rows are probe-emitted pass.
- [ ] Dossier completes the six applicable human areas through public providers.
- [ ] The candidate lock identifies every constituent and artifact immutably.
- [ ] CI, clean installs, and dogfood use the same lock and bundle.
- [ ] No required CI proof installs from a moving branch or mutable image tag.
- [ ] Required claims are supported; preview/excluded claims are named.
- [ ] No open critical/high security or correctness finding affects supported scope.
- [ ] Native Windows and every other supported lane pass their qualification.
- [ ] N-1 upgrade, injected-failure recovery, backup, and independent restore pass.
- [ ] Identifier, secret, dependency, license, SBOM, and artifact scans pass.
- [ ] Published metadata contains no placeholders and all repos are clean/tagged.
- [ ] The candidate completes the ratified soak without unexplained manual repair.
- [ ] Operator and support documentation is complete and tested by task.
- [ ] The reviewed RC bundle is promoted byte-for-byte as 1.0.0.

## 12. Definition of done

A new operator can take one immutable 1.0 bundle and deploy Profile B on a clean
supported environment; onboard two principals and a project; complete work,
knowledge, strict review, activity inspection, and evidence export through
agent-notes and dossier; upgrade from the supported prior version; restore into
an independent environment; verify the record offline; and obtain the expected
green lock and profile-aware doctor result without source-tree knowledge,
component-private calls, direct SQL, raw secret handling, or hand-edited harness
configuration.

