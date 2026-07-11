# Plan 010 — Full product horizon: every warranted suite capability

**Status:** Proposed (exploratory product horizon), proposed 2026-07-10.  
**Author:** GPT-5.6 Sol.  
**Strategic role:** Describe the complete set of features that make sense for
the suite if time and adoption justify them. Unlike Plan 009, this is not a v1
scope or release gate. Unlike Plan 008, it is not primarily an assurance and
deployment plan. It is the product north star from which future plans may be
selected.

## 1. How to use this plan

This document is a **menu with architecture**, not a commitment to build every
item. A feature graduates into an implementation plan only when it:

1. closes an observed user, operator, reviewer, or auditor problem;
2. has a clear owning component;
3. preserves the suite's thin composition and deterministic truth paths;
4. has an authorization, privacy, degradation, and evidence story;
5. can be proven without relying on model narration;
6. does not duplicate a mature external system better integrated through an
   adapter;
7. earns its operational and maintenance cost.

Plan 009 remains the feature-complete v1 boundary. Plan 008 remains the robust
qualification boundary. Plan 010 begins after those scopes are protected.

## 2. Product north star

The mature suite is a **human–agent accountability and evidence fabric** for
small teams and regulated organizations.

It should make these questions easy to answer:

- What work exists, who owns it, and what state is it in?
- What did a human or agent do, in which session, through which tools, and on
  whose authority?
- What knowledge and decisions did the work produce?
- What evidence supports review, acceptance, and an external assurance claim?
- Which capabilities, credentials, networks, and data sources was an agent
  allowed to use?
- Which signals reached which participants, and what happened afterward?
- Is the deployed system healthy, protected, current, and operating within its
  declared policy?
- Can an independent reviewer verify the record without trusting the operator's
  narrative?

The mature product should answer them through one signed graph of work,
knowledge, identity, sessions, capabilities, signals, controls, and evidence—
with purpose-built human, agent, operator, and auditor views.

## 3. Permanent exclusions

Even at full horizon, the suite should not become:

- a clinical decision-support, diagnosis, treatment, or patient-record system;
- a default repository for protected health information or other sensitive
  business content;
- employee productivity scoring, covert monitoring, keystroke capture, screen
  recording, or behavioral surveillance;
- an autonomous approver for high-impact decisions;
- a general-purpose project-management, CRM, ERP, chat, email, document-editing,
  or business-intelligence platform;
- a SIEM, EDR, identity provider, secrets manager, browser farm, workflow
  scheduler, or database replacement;
- a proprietary agent runtime that launches and supervises every agent;
- a bespoke service/fleet control plane;
- a mandatory SaaS, Kubernetes, public-cloud, blockchain, or model-provider
  dependency;
- a system that describes probabilistic model output as verified evidence.

Integrate with those categories where useful; do not absorb them.

## 4. Product domains

The full horizon is grouped into eleven domains:

1. work and policy;
2. knowledge and decisions;
3. identity, delegation, and human oversight;
4. session and tool provenance;
5. evidence and assurance;
6. capabilities and execution boundaries;
7. signaling, approvals, and escalation;
8. human experience;
9. agent experience;
10. operations and administration;
11. ecosystem and interoperability.

## 5. Work and policy horizon

### 5.1 Policy packs

Versioned policy packs compose workflow, roles, validators, review rules,
retention, evidence requirements, notification rules, and assurance targets for
a class of project.

Examples:

- ordinary software maintenance;
- security-sensitive change;
- infrastructure change;
- incident remediation;
- publication/release review;
- regulated evidence collection.

Policy packs are signed and pinned per project. Updating a pack is an explicit
version transition; it never silently changes the rules governing historical
work.

### 5.2 Evidence-aware work items

Work types can declare evidence requirements such as:

- tests and their results;
- reviewer note;
- file/diff digest;
- provenance coverage level;
- restore or deployment proof;
- approval by a role or distinct principal;
- external receipt or control mapping.

The workflow evaluates presence and validity deterministically. A model may
suggest missing evidence but cannot mark it satisfied.

### 5.3 Dependency and change-impact graph

Typed links grow into a useful impact graph across work, projects, services,
files, controls, incidents, releases, and knowledge.

Features:

- upstream/downstream dependency views;
- “what is blocked by this?” queries;
- stale evidence when a depended-on artifact changes;
- affected-work suggestions from file/service changes;
- cross-project links with explicit authorization;
- cycle and invalid-link detection.

The suite should avoid pretending to infer perfect impact from embeddings. All
automatic suggestions remain reviewable links until accepted.

### 5.4 Change sets and release trains

Group related work, evidence, approvals, and deployments into a signed change
set or release:

- immutable membership snapshot at approval time;
- per-item and aggregate assurance state;
- release notes derived from signed work, then reviewed by a human;
- deployment/rollback evidence linked back to the change set;
- comparison between candidate and deployed state.

This is not a general CI/CD engine; it records and verifies the change while
integrating with external build/deploy systems.

### 5.5 Incidents and exceptions

Add narrow first-class work types for:

- incident response timeline and actions;
- policy exception with owner, rationale, compensating control, and expiry;
- risk acceptance with explicit approver and claim-language impact;
- break-glass action with mandatory after-action review;
- recurring finding/remediation linkage.

Do not build alert detection or case management that belongs in an external
SIEM/ITSM. The suite owns accountability for work performed after a signal.

### 5.6 Reusable workflow library

Provide reviewed workflow/policy examples and a conformance linter:

- semantic validation beyond schema validity;
- unreachable states and transitions;
- missing rejection/recovery paths;
- separation-of-duties weaknesses;
- terminal-state and recurrence mistakes;
- evidence rule contradictions;
- visualization and diff between versions.

## 6. Knowledge and decision horizon

### 6.1 Decision records as signed entities

Decisions deserve a first-class schema distinct from free-form memories:

- question/context;
- considered options;
- decision and rationale;
- constraints and assumptions;
- decider/reviewers;
- effective and review dates;
- supersedes/superseded-by links;
- supporting evidence and affected work.

A decision can become stale when a named assumption or linked artifact changes.

### 6.2 Knowledge quality lifecycle

Knowledge notes gain optional states:

- draft;
- active;
- disputed;
- superseded;
- expired;
- archived.

Features include owner, review cadence, confidence source, contradiction links,
and a human curation queue. Agents may propose merges/supersession; canonical
changes require the configured review policy.

### 6.3 Evidence-backed synthesis

Generate orientation briefs, project summaries, handoff packets, and release
narratives from signed records, with every statement linked to its source.

The generated narrative is explicitly a projection:

- source links are mandatory;
- unsupported assertions are highlighted;
- regenerating does not mutate source records;
- a human may sign an accepted narrative when it becomes an official artifact.

### 6.4 Semantic and structured search

Combine:

- exact identifiers and typed filters;
- full-text search;
- embeddings as a replaceable projection;
- graph traversal;
- time/principal/project/assurance filters;
- “why did this match?” explanations based on fields/links, not model claims.

Search access is evaluated before retrieval; an embedding index must not leak
the existence or similarity of unauthorized content.

### 6.5 Knowledge import/export adapters

Import references or approved content from existing document systems without
making the suite a second document store:

- store source identity, version, digest, access policy, and selected excerpt or
  summary;
- refresh explicitly or on a controlled schedule;
- identify stale/broken external references;
- export signed decisions/knowledge in portable Markdown/JSON.

### 6.6 Cross-project institutional knowledge

Allow deliberately shared knowledge spaces with:

- explicit publication from project-private to shared;
- redaction/review gate;
- provenance back to the source project without exposing private content;
- versioning and revocation;
- audience/role policy.

No note becomes organization-wide merely because an embedding search found it
useful.

## 7. Identity, delegation, and oversight horizon

### 7.1 Enterprise identity federation

Support OIDC/SAML/LDAP adapters through one principal-binding contract:

- immutable external-subject binding;
- display-name changes separated from identity;
- group/role synchronization with explicit mapping;
- disabled-user and offboarding propagation;
- step-up authentication for key, policy, export, and break-glass operations;
- session age and reauthentication policy.

SCIM-style provisioning may be added as an adapter; regista remains the signed
authorization history, not the enterprise identity source.

### 7.2 Ephemeral agent session identities

Each agent session can hold an ephemeral key or capability grant signed by its
human/service principal:

- session start/end and expiry;
- allowed projects/roles/capabilities;
- parent delegation and maximum depth;
- revocation;
- binding to harness instance/version and optional environment attestation;
- no reuse across sessions unless policy explicitly permits it.

This reduces reliance on long-lived agent credentials and strengthens
delegation evidence.

### 7.3 Delegation policy engine

Deterministic rules govern:

- which principals may delegate;
- allowed roles/capabilities;
- maximum depth and duration;
- whether redelegation is allowed;
- review independence across a chain;
- inherited vs narrowed scope;
- revocation propagation.

### 7.4 Human-oversight contracts

Projects can declare which operations require:

- notification only;
- human confirmation;
- distinct-principal approval;
- two-person control;
- time-delayed execution/cooling-off;
- after-action review.

The suite records the oversight event; it does not automate away the human
decision.

### 7.5 Conflict-of-interest and independence checks

Extend review policy beyond model lineage:

- same human principal;
- delegation ancestry;
- shared service identity;
- prior authorship or approval in the change set;
- policy-defined organizational role conflict.

Keep the rule inputs explicit. Do not infer personal relationships or employee
performance characteristics.

## 8. Session and provenance horizon

### 8.1 Unified session model

Normalize local, IDE, app, managed, cloud, and subagent sessions into one
versioned model while retaining surface-specific details:

- parent/child sessions;
- turns and compaction/resume boundaries;
- model/provider/harness and configuration digests;
- cwd/project/work bindings;
- permission/sandbox/network posture;
- start/end reason and outcome;
- capture coverage and degradation windows.

### 8.2 File and change provenance

Link tool calls to:

- files read/written/deleted;
- before/after digests;
- structured patch or diff digest;
- repository/commit/worktree state;
- generated vs hand-authored classification;
- build/test artifacts produced afterward.

Large content remains external or encrypted; provenance stores commitments and
authorized references.

### 8.3 Environment and scope attestation

At session start, attest the declared environment:

- harness/model version;
- enabled hook/plugin/skill/MCP manifest digests;
- relevant policy/config digests;
- sandbox/approval/network mode;
- repository revision and dirty-state digest;
- supported interception matrix.

This is evidence of declared/observed configuration, not proof that the host is
uncompromised. Hardware-backed attestation remains conditional research.

### 8.4 Content policy engine

Per project/event/tool, decide:

- digest only;
- structured metadata;
- redacted excerpt;
- encrypted full content;
- prohibited capture.

Policy includes size limits, field selectors, retention, export permission, and
key class. Redaction is best-effort and must never be marketed as a guarantee
that sensitive information is absent.

### 8.5 Coverage probes and canaries

Supported harness adapters periodically or on demand run safe synthetic probes
for every claimed hook surface:

- verify hook fires;
- correlate begin/end;
- confirm store reachability;
- check output shape/version drift;
- age out stale coverage evidence.

Probe events are unmistakably synthetic and excluded from ordinary work views.

### 8.6 Provenance queries and comparisons

Add reviewer-facing operations:

- compare two sessions/change attempts;
- show tool/file/evidence differences;
- trace one artifact back to its producing session and work;
- identify work completed during degraded capture;
- list unsupported actions within a scope;
- find configuration/version drift across sessions.

### 8.7 Multi-witness transparency

Support multiple independent witnesses/anchors:

- public timestamp/anchor;
- organization-controlled WORM store;
- partner/auditor witness;
- signed receipt quorum policy;
- witness health and equivocation detection;
- portable receipt verification.

No single public network is mandatory.

## 9. Evidence and assurance horizon

### 9.1 Claims ledger product surface

Turn Plan 008's claims ledger into a useful operator/reviewer feature:

- claim, scope, assumptions, owner, policy source;
- supporting controls and evidence queries;
- positive/negative proof status;
- last verified release/time;
- accepted residual risk and expiry;
- automatically stale when inputs change.

This is not automatic compliance certification. It is traceable evidence for a
human assurance decision.

### 9.2 Control framework mappings

Map claims/evidence to organization-selected control catalogs through adapters
or data packs, for example:

- NIST AI RMF functions and profiles;
- NIST Cybersecurity Framework outcomes;
- healthcare-sector cybersecurity goals;
- organization policies and audit controls;
- OSCAL-compatible control/evidence references where practical.

Mappings are versioned interpretations reviewed by humans, not claims that the
suite makes an organization compliant.

### 9.3 Assurance levels and evidence freshness

Extend assurance levels with explicit dimensions rather than one opaque score:

- identity strength;
- signer/key status;
- chain/bundle verification;
- capture coverage;
- review independence;
- external timestamp/anchor;
- content availability/confidentiality mode;
- proof freshness.

Views may summarize them, but reviewers can always inspect the dimensions.

### 9.4 Audit cases and evidence packets

A reviewer can create a scoped audit case containing:

- questions/claims;
- selected projects/work/sessions/releases;
- evidence snapshots and query definitions;
- reviewer annotations;
- exceptions and remediation work;
- export manifest and verification report;
- final signed conclusion.

The suite supports the evidence workflow without becoming a general GRC suite.

### 9.5 Continuous control evidence

Scheduled evidence queries can detect:

- stale restore proof;
- overdue key rotation;
- missing review independence;
- unsupported harness drift;
- unverified release/deployment;
- expired risk acceptance;
- degraded capture during protected work;
- stale policy pack.

Findings create work or notifications; deterministic queries decide status.

### 9.6 Selective disclosure and scoped export

Allow an organization to prove relevant claims without exporting unrelated
content:

- project/time/entity filtering with preserved chain context;
- redacted/encrypted content placeholders;
- public keys and receipts only as needed;
- disclosed-field commitments;
- manifest naming omissions and verification limits.

Cryptographic selective-disclosure schemes are research-gated; honest scoped
bundles are the baseline.

## 10. Capability and execution horizon

### 10.1 Capability taxonomy

Expand beyond credential and browser while keeping providers concrete:

- credential/secret lease;
- browser/E2E;
- MCP/tool server;
- approved CLI/binary;
- network destination/egress;
- data-source read or write access;
- temporary filesystem/workspace;
- build/deploy runner;
- signing/approval operation;
- human escalation channel.

Each capability declares risk, secret/data class, allowed identities,
harnesses, expiry, evidence requirements, and revocation behavior.

### 10.2 Short-lived capability grants

Issue time-, project-, work-, and session-scoped grants:

- least privilege;
- explicit purpose/work binding;
- one-time or renewable leases;
- step-up/human approval where required;
- immediate revocation;
- child-process-only injection;
- provenance from grant through use.

The external backend remains the source of the actual credential/token.

### 10.3 Policy-aware execution wrapper

`acb exec` can enforce deterministic preconditions:

- principal/session/work binding;
- capability grant active;
- command/tool allowlist;
- cwd/project scope;
- environment minimization;
- network policy handoff;
- output secret scanning/redaction boundary;
- post-use lease cleanup.

This is not a general sandbox; it composes with harness/OS/container controls.

### 10.4 Effective plugin/extension resolution

Where harnesses expose stable metadata, inspect the effective enabled state of:

- plugins/extensions;
- skills/commands;
- MCP servers/apps;
- hooks;
- policy/permission files.

Unknown or version-dependent resolution remains explicit. A marketplace entry
or cache directory alone is not evidence of enablement.

### 10.5 Capability simulation and preflight

Before starting protected work, show:

- required capabilities;
- current harness availability;
- broken/expired grants;
- expected secret/data/network boundaries;
- predicted non-secret wiring changes;
- whether provenance covers the planned invocation path.

### 10.6 Capability usage review

Reviewers can see which capabilities were granted, actually used, unused,
denied, or expired during a session/work item. Do not turn usage into employee
productivity scoring.

## 11. Signaling, approvals, and escalation horizon

### 11.1 Durable multi-session inbox

Signals survive daemon/harness restart and route by:

- principal;
- session;
- project;
- work item;
- policy-approved label;
- role/on-call assignment.

Delivery modes remain explicit and adapter-specific.

### 11.2 Two-way replies

Where supported, a human/agent can reply to a signal:

- acknowledgement;
- structured answer;
- approval/denial;
- requested clarification;
- handoff/subscribe/unsubscribe.

Replies are authenticated and correlated. A chat/email reply never becomes an
approval merely because its text says “yes”; the adapter must bind structured
identity and decision semantics.

### 11.3 Approval relay

Relay harness permission requests to authorized humans:

- request details minimized by policy;
- expiring request ID;
- allow/deny with authenticated principal;
- optional command/input digest binding;
- no approval reuse after input change;
- signed decision and provenance.

This is a high-risk feature and requires step-up authentication plus strong
negative tests.

### 11.4 Escalation policies

Policy-driven escalation for:

- review overdue;
- protected work blocked;
- health/integrity red;
- restore/backup stale;
- signal delivery exhausted;
- key/certificate expiry;
- risk acceptance nearing expiry.

Escalation schedules/routing are configuration; wake does not become a general
workflow scheduler.

### 11.5 Quiet hours, digests, and preferences

Human delivery supports:

- severity/channel preferences;
- quiet hours with emergency override;
- immediate vs digest classes;
- deduplicated state-change notices;
- delegation/substitution during absence;
- accessible plain-text messages and durable deep links.

### 11.6 External event adapters

Provide narrow adapters for sources such as:

- source control/review events;
- CI/build/deployment status;
- monitoring/incident systems;
- scheduled suite operations;
- approved ticket/change systems.

Adapters normalize into the portable wake schema and are separately
authenticated; they do not import the external system's entire domain model.

## 12. Human experience horizon

### 12.1 Role-based home views

Purpose-built home views for:

- worker/agent operator;
- reviewer/approver;
- project owner;
- suite operator;
- security/audit reviewer.

Each view prioritizes actionable state, not vanity metrics.

### 12.2 Investigation workbench

One navigable surface for:

- work timeline;
- sessions and delegation tree;
- tool/file changes;
- knowledge and decisions;
- reviews/approvals;
- keys/identity events;
- capability grants/uses;
- signals/replies;
- verification and coverage gaps.

It is a projection over signed records; deep links retain stable identifiers.

### 12.3 Review workspace

Improve review quality with:

- changed-work/evidence summary;
- required evidence checklist;
- provenance coverage warning;
- side-by-side attempts or revisions;
- linked tests/diffs/reports;
- conflict-of-interest result;
- structured accept/reject/request-changes;
- review templates per policy pack.

Model-generated summaries are optional and source-linked.

### 12.4 Knowledge curation workspace

Humans can:

- browse/search/filter knowledge;
- review disputed/stale notes;
- merge/supersede with signed rationale;
- publish approved shared knowledge;
- inspect source links and usage;
- schedule review/expiry.

### 12.5 Operator console inside dossier

A read-mostly administrative section may surface:

- profile/component health;
- versions/lock drift;
- protection/restore age;
- key/certificate/anchor age;
- queue/backlog/capacity state;
- supported harness/capability matrix;
- runbook/deploy/upgrade links.

Acting operations remain explicit CLI/service actions or narrowly authorized
forms. The console must not become a hidden suite control plane.

### 12.6 Accessibility and low-bandwidth operation

- keyboard-complete workflows;
- semantic HTML and assistive-technology labels;
- clear status not conveyed by color alone;
- print/PDF-friendly evidence views;
- responsive layouts;
- core operations under degraded bandwidth;
- localization-ready text boundaries if adoption warrants it.

### 12.7 Saved views and subscriptions

Users can save scoped filters and subscribe to state changes without building a
general analytics/dashboard language.

## 13. Agent experience horizon

### 13.1 Project/session briefing

At session start, produce a bounded, source-linked briefing:

- project identity/policy;
- assigned/claimable work;
- active blockers/dependencies;
- recent relevant decisions/knowledge;
- required review/evidence rules;
- capability and coverage posture;
- unresolved degradation from prior session.

No private cross-project memory leaks into the briefing.

### 13.2 Safe work resumption

An agent can resume work from a handoff packet containing:

- exact work and state;
- prior session/attempt links;
- files/commits and dirty state;
- decisions and unresolved questions;
- claims/capabilities still valid;
- tests/evidence remaining;
- provenance coverage caveats.

The packet is a projection; canonical state remains in the store/repository.

### 13.3 Structured handoff and delegation

Agents/humans can create a signed handoff:

- task and expected result;
- scope/bounds;
- context sources;
- allowed capabilities;
- deadline/claim;
- parent session/principal;
- return/evidence format.

Delegated work cannot silently widen scope or authority.

### 13.4 Work-aware tool wrappers

Skills and ACB shims automatically carry safe identifiers (project, work,
session, grant) so agents do not repeatedly type or invent them. Secret and
authorization decisions remain outside the prompt.

### 13.5 Knowledge feedback loop

When an agent uses a note/decision, it may:

- link usage to work;
- flag stale/incorrect/contradictory content;
- suggest a superseding record;
- request human curation;
- never silently rewrite the source.

### 13.6 Agent self-checks

Before submission, deterministic skills check:

- required tests/evidence;
- unresolved work children/blockers;
- dirty/untracked files;
- missing links/summary;
- provenance degradation;
- prohibited self-review;
- policy-specific release checks.

The model may explain results, but the checks decide pass/fail.

## 14. Operations and administration horizon

### 14.1 Profile and estate inventory

Maintain a signed/read-only inventory of:

- installations and selected profiles;
- component/artifact versions;
- projects and schemas;
- configured harnesses/adapters;
- secret backend references (never values);
- identity provider and principal counts;
- protection/restore/anchor status;
- support and proof freshness.

This is inventory and evidence, not remote lifecycle control.

### 14.2 Configuration compiler and drift

Compile profile/policy selections into component-owned plans, then detect:

- missing configuration;
- unsupported keys/versions;
- secret reference failure;
- harness ownership conflicts;
- live drift from the last accepted plan;
- manually changed generated files.

Repair remains explicit, previewed, and ownership-aware.

### 14.3 Migration rehearsal

Before an upgrade:

- restore a recent backup into scratch;
- apply candidate migrations;
- replay and verify;
- run profile golden journeys;
- estimate time/storage;
- produce a forward/rollback decision report.

### 14.4 Disaster and continuity exercises

Automate repeatable exercises for:

- lost host;
- lost database with backup available;
- secret backend outage;
- signing key loss/revocation;
- corrupted archive/anchor receipt;
- harness/provider outage;
- partial deployment;
- operator absence and break-glass.

### 14.5 Retention, legal hold, and disposition

Policy can distinguish:

- immutable integrity metadata;
- encrypted content;
- operational logs;
- temporary hook/plugin state;
- evidence exports;
- backups/archives.

Legal hold and disposition actions are authorized, signed, previewable, and
verification-aware. “Delete” must state what cryptographic commitments remain.

### 14.6 Air-gapped and constrained environments

Support offline artifact bundles, local package indexes, file/native secret
backends, no-network verification, deferred external anchoring, and manual
evidence transfer without weakening status language.

### 14.7 High availability through external primitives

Document/reference patterns for Postgres HA, load balancing, durable queues,
secret backend HA, and redundant delivery endpoints. Do not implement a suite
cluster manager.

### 14.8 Cost and resource visibility

Report non-sensitive operational facts:

- database/archive/content growth;
- backup size/time;
- verification runtime;
- embedding/index footprint;
- hook/delivery backlog;
- external provider usage counts;
- model/token cost only when supplied by the harness/provider and authorized.

No employee productivity ranking or covert per-person cost scoring.

## 15. Ecosystem and interoperability horizon

### 15.1 Stable component SDKs and APIs

Provide narrow, versioned public interfaces for:

- store/work/entity operations;
- scoped evidence export/verify;
- agent-notes read/write/search;
- dossier external links/webhooks;
- capability provider/adapter protocol;
- wake source/delivery adapter protocol;
- harness provenance adapter protocol.

Internal Postgres structures remain private.

### 15.2 Conformance kit

An external adapter author receives:

- protocol/types/schema;
- synthetic fixtures;
- clean-profile harness;
- positive/negative tests;
- ownership/no-clobber tests;
- secret-leak checks;
- health/install/uninstall contract;
- coverage and support-level template.

### 15.3 Signed plugin/adapter packages

Package suite integrations with:

- manifest and compatibility range;
- checksums/provenance/SBOM;
- permissions and data/secret declaration;
- supported profiles/platforms/harness versions;
- install ownership;
- conformance evidence;
- revocation/deprecation path.

This is a curated extension mechanism, not necessarily a public marketplace.

### 15.4 Standard evidence formats

Where useful, support adapters for:

- DSSE/in-toto-style attestations;
- CycloneDX/SPDX SBOM references;
- SARIF findings;
- OpenTelemetry trace/log correlation;
- OSCAL evidence/control references;
- standard webhook/cloud-event envelopes;
- signed JSON/JSONL and portable HTML reports.

Native suite semantics remain explicit; standards mapping does not erase fields
or overstate equivalence.

### 15.5 External system links

Integrate rather than replace:

- source control and code review;
- CI/CD and artifact registries;
- ticket/change/incident systems;
- IdPs and secrets managers;
- monitoring/SIEM;
- document/knowledge systems;
- email/chat delivery;
- timestamp/witness services.

Each adapter has a narrow synchronization direction and conflict policy. The
suite avoids bi-directional “everything sync” unless one system is explicitly
canonical for each field.

## 16. Responsible AI governance horizon

### 16.1 AI use-case registry

Record organization-approved agent use cases:

- purpose and owner;
- affected users/data/systems;
- model/provider/harness;
- allowed capabilities;
- human oversight;
- evaluation and acceptance criteria;
- known limitations/risks;
- review and expiry;
- applicable policy/control mappings.

This governs suite use without turning regista into a model registry for every
organization system.

### 16.2 Model/harness change assessments

A model or harness upgrade can trigger:

- capability/coverage regression tests;
- behavior/evaluation suite;
- prompt/skill compatibility review;
- privacy/data-flow review;
- cost/performance observation;
- human approval for protected use cases;
- lock/evidence transition.

### 16.3 Evaluation records

Link externally run evaluations and internal golden tasks to:

- use case;
- model/harness/config digest;
- dataset/version and data authorization;
- rubric/metrics;
- results and reviewer;
- limitations;
- release/support decision.

The suite records evidence; specialized evaluation platforms perform the
model testing.

### 16.4 AI incident and near-miss records

Narrow signed templates for:

- unexpected harmful/unsafe action;
- authorization or data-boundary failure;
- misleading evidence/narration;
- provenance gap;
- model/harness regression;
- human-oversight failure;
- corrective work and changed policy/evaluation.

### 16.5 Transparency for affected users

Where agents participate in a process, provide configurable disclosure of:

- that an agent was used;
- its role and authority boundary;
- human oversight/review status;
- evidence availability;
- how to report a concern.

This is a policy/UI capability, not a claim that every internal tool action
requires external disclosure.

## 17. Research-gated possibilities

The following might make sense but must not enter the supported roadmap without
a successful spike and explicit threat/maintenance review.

### 17.1 Hardware-backed session and operator keys

WebAuthn/passkeys, TPM, smart card, or HSM-backed signing could strengthen key
custody. Feasibility depends on platform, automation, delegation, recovery, and
library support.

### 17.2 Remote/environment attestation

TPM/TEE or signed workload identity may improve evidence about where an agent
ran. It must be described as evidence of measured configuration, not proof of
correct behavior.

### 17.3 Cryptographic selective disclosure

Merkleized field commitments or advanced credentials could support proving
selected facts without disclosing full records. Complexity and verifier
interoperability must justify it.

### 17.4 Privacy-preserving aggregate analytics

Differential privacy or threshold aggregation may enable organization-level
trend reporting without exposing individuals. Do not implement until a real
analytics use case exists.

### 17.5 Standards-based external trigger protocol

If a stable MCP or other industry standard emerges for external agent events,
align wake adapters without changing the suite's durable event semantics.

### 17.6 Federated external witnesses

Multiple organizations or auditors could witness roots/receipts. Governance,
privacy, availability, and revocation need a concrete partnership before build.

### 17.7 Policy simulation

Safely replay historical metadata against a proposed workflow/policy pack to
estimate blocked/changed outcomes. Never mutate the historical record or
present simulation as a prediction of human behavior.

## 18. Feature selection scorecard

Before promoting a horizon feature, score it from 0–2 on:

| Dimension | 0 | 1 | 2 |
|-----------|---|---|---|
| User pain | speculative | occasional | repeated/measured |
| Charter fit | adjacent | supportive | central |
| Existing alternative | mature/easy | integration needed | real gap |
| Determinism | model-dependent truth | mixed | deterministic core |
| Privacy/security | unclear/high expansion | manageable | reduces risk |
| Cross-component value | one niche | two components | suite-wide |
| Proofability | subjective | partial | executable positive/negative |
| Operating cost | high/continuous | moderate | bounded |
| Reversibility | hard migration | manageable | adapter/projection |

Promotion guidance:

- **15–18:** strong candidate for the next roadmap;
- **11–14:** spike or defer until adoption evidence improves;
- **0–10:** do not build as a suite feature.

Security/privacy vetoes override the numeric total.

## 19. Suggested horizons

### Horizon 1 — Team value after v1

Prioritize:

- decision records;
- knowledge quality/curation;
- investigation and review workspaces;
- project/session briefing and safe resumption;
- evidence-aware work items;
- policy packs;
- two-way human notifications;
- claims ledger UI;
- migration rehearsal.

These deepen the daily human–agent workflow without changing the product
category.

### Horizon 2 — Regulated organization maturity

Prioritize when adoption warrants:

- enterprise identity federation and step-up auth;
- ephemeral session identities and capability grants;
- audit cases/evidence packets;
- continuous control evidence;
- control-framework mappings;
- legal hold/disposition;
- multi-witness transparency;
- AI use-case/evaluation/incident records;
- air-gapped deployment.

### Horizon 3 — Extensible ecosystem

Prioritize after the core contracts stabilize:

- public adapter/provider protocols;
- conformance kit;
- signed integration packages;
- standard evidence format adapters;
- narrow external system integrations;
- profile/policy pack library.

### Horizon 4 — Conditional research

Keep hardware attestation, cryptographic selective disclosure, federated
witnessing, privacy-preserving analytics, and emerging trigger protocols behind
explicit research gates.

## 20. Full-horizon definition of success

The full horizon has succeeded when the suite can support a regulated team's
human–agent work from policy and onboarding through execution, knowledge,
review, evidence, operation, and independent audit—while integrating with
external enterprise systems instead of replacing them, and while remaining
small enough that its trust boundaries can still be understood.

The most important measure is not the count of features. It is whether each
additional feature makes authority, evidence, knowledge, or recovery more
legible without making the suite itself ungovernable.

## 21. Planning references

These are alignment resources, not certifications or requirements automatically
conferred on a deployment:

- NIST AI Risk Management Framework and Generative AI Profile:
  https://www.nist.gov/itl/ai-risk-management-framework
- NIST AI RMF Playbook:
  https://www.nist.gov/itl/ai-risk-management-framework/nist-ai-rmf-playbook
- HHS Healthcare and Public Health Cybersecurity Performance Goals:
  https://hhscyber.hhs.gov/cybersecurity-performance-goals.html
- HRSA Health Center Program Compliance Manual:
  https://bphc.hrsa.gov/compliance/compliance-manual
