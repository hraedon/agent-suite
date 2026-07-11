# Plan 011 — Sealed session evidence without employee surveillance

**Status:** Proposed 2026-07-11.  
**Author:** GPT-5.6 Sol.  
**Depends:** Plan 008, Plan 009, Plan 010.  
**Strategic role:** Turn the suite's existing digest-to-encrypted-content privacy
model into an implementable, abuse-resistant evidence escrow. This plan defines
when session inputs and outputs may be retained, how they remain unavailable to
ordinary operations, and how a narrowly scoped investigation can disclose them
without creating an employee-surveillance product.

## 1. Decision

The suite will support full session input/output retention, but it will **not**
make full content the ordinary event record or a routinely searchable product
surface.

The default remains attributable session and tool evidence without conversational
content. An operator may enable **sealed evidence** for an explicitly designated
project, use case, or session class. Sealed content is encrypted before durable
ingest, held outside the ordinary event and projection paths, and disclosed only
through a case-bound, minimum-necessary, dual-controlled workflow.

This is an evidence-escrow capability, not a general transcript archive:

- capture is visible and purpose-limited;
- ordinary managers and application administrators cannot browse it;
- the system provides no employee transcript search, ranking, sentiment,
  productivity, attendance, or behavioral analytics;
- every preservation, access, disclosure, and destruction action is itself a
  signed event;
- a new use requires a policy change, privacy review, notice, and corresponding
  technical controls—not merely a broader query.

## 2. Why tool calls alone are not enough

Tool evidence is necessary and remains the default high-value record. It can
answer what operation was attempted, against which target, with what result, and
under which session and authority. It cannot reliably establish:

- what the human requested or authorized;
- which instructions or retrieved context influenced the action;
- whether prompt injection or misleading context preceded it;
- whether the assistant's account of a tool result was accurate;
- what consequential advice was produced without a tool call;
- why the agent declined, stopped, or took no action.

Full content can close those gaps during a specific investigation. It also
creates a concentrated collection of possible health information, credentials,
personnel information, privileged communications, source code, and personal
material. The suite therefore treats content availability and content access as
separate decisions.

Tool arguments and outputs are content too. A `tool_call` label does not make
their bodies safe: the same capture, classification, encryption, and retention
policy applies to them.

## 3. Surveillance boundary

For this product, **employee surveillance** means systematic collection or use
of identifiable worker activity to observe, evaluate, compare, predict, or
influence workers, whether that is the original purpose or a later secondary
use.

Retention is still monitoring and must be disclosed honestly. The suite keeps
assurance from becoming surveillance through enforceable purpose and access
boundaries:

| Permitted assurance use | Permanently excluded use |
|-------------------------|--------------------------|
| Reconstruct a named incident | Routine manager browsing by employee |
| Investigate a reported security or safety failure | Productivity, engagement, or responsiveness scoring |
| Preserve specifically scoped evidence under legal hold | Sentiment, personality, loyalty, or behavior profiling |
| Verify a disputed agent action or representation | Comparative ranking or attendance inference |
| Conduct a pre-approved, bounded safety review | Exploratory disciplinary fishing |
| Produce minimum-necessary evidence for an authorized case | Training models or building employee dossiers |

Prohibited uses are enforced in schemas, authorization, query surfaces, export
policy, derived-data controls, tests, and operator documentation. A warning
banner alone is not a control.

## 4. Capture modes

Every deployment and project declares one mode. Missing or invalid policy fails
closed to `standard`.

### 4.1 Standard — default

Retain:

- session, turn, principal, delegation, harness, model/configuration, work, and
  policy identifiers;
- tool name, lifecycle, timing, result class, target classification, and the
  privacy-safe fields explicitly allowed by policy;
- ciphertext/blob digests, coverage status, sizes, and capture failures;
- message role, ordering, byte count, and policy decision;
- no user or assistant message body.

Tool argument/output bodies default to digest-only or allowed structured fields.
This mode supports normal activity views and most assurance questions.

### 4.2 Sealed evidence — explicit

Additionally retain encrypted user, assistant, system/context, and tool content
for a named purpose. Enabling it requires:

- a signed policy version and owner;
- allowed projects/session classes and capture fields;
- a visible participant notice;
- a retention period and key class;
- allowed case types and approval rules;
- documented data classes and prohibited sources;
- successful escrow, destruction, and negative-access qualification.

The ordinary UI shows that sealed content exists, its coverage and expiry, and
its integrity state. It does not show or search the content.

### 4.3 Case hold and disclosure

A hold is not another capture mode. It is a signed, precisely scoped override of
scheduled destruction for already captured evidence. A disclosure is a separate,
time-limited authorization to decrypt specified fields into an isolated case
workspace or export.

## 5. Data architecture

```text
harness adapter
  |  classify + capture-policy decision
  |  encrypt content with per-session data key
  +----> signed regista event: metadata, policy, coverage, opaque blob digest
  |
  +----> encrypted blob store: ciphertext only
                         |
                    wrapped data key
                         |
                 evidence-escrow key backend
                         |
             case-bound disclosure service
                         |
              isolated case workspace/export
```

### 5.1 Ordinary signed event

Regista stores the authoritative content manifest, not plaintext content:

- `content_record_id`, project, session, turn, role, and sequence;
- capture mode and signed policy-pack digest;
- capture time, adapter, harness, and coverage status;
- content/media class and original/ciphertext byte sizes;
- blob locator identifier, ciphertext digest, encryption scheme, and key ID;
- retention class, disposition time, and hold state;
- classification/redaction decisions and named failures;
- links to work, tools, files, delegation, and later case actions.

The locator is opaque and never a directly fetchable public URL. The signed event
can prove that a particular ciphertext was committed at a particular point even
after policy-driven content destruction.

### 5.2 Encrypted content store

- Encrypt each session with a random data-encryption key; permit finer per-turn
  keys where a connector requires selective destruction.
- Use authenticated encryption and bind project, session, turn, role, sequence,
  policy digest, and record ID as associated data.
- Wrap data keys using a dedicated evidence-escrow key outside the normal
  application/runtime credential set.
- Do not give regista, cairn's normal ingest process, dossier's ordinary web
  process, agents, managers, or database administrators unwrap authority.
- Support filesystem/object storage initially through a narrow blob-store
  protocol; do not place large ciphertext bodies in signed event JSON.
- Back up ciphertext and wrapped keys under the same retention and restore proof
  as the manifest without expanding ordinary backup-reader access.

Plaintext must not cross an unencrypted queue or land in debug logs, exception
messages, temporary files, crash dumps, metrics, or tracing systems. Adapters
must bound input size and stream where the harness permits it.

### 5.3 Commitment privacy

Do not store a bare digest of transcript plaintext outside the ciphertext. Common
or low-entropy messages are vulnerable to guessing and equality correlation.
Store a public digest of the ciphertext for integrity. If later proof needs a
plaintext commitment, place it inside the encrypted envelope or use a
domain-separated keyed commitment whose key is held by evidence escrow and whose
verification material is disclosed only with the case.

This requires a session-content envelope distinct from regista's existing
general field-encryption shape, whose visible plaintext digest is suitable for
other evidence but not for confidential transcripts.

### 5.4 No content projections

Sealed content is excluded from:

- ordinary Postgres projections and replicas;
- full-text and semantic indexes;
- embeddings and model-training datasets;
- caches, snippets, previews, notifications, and activity feeds;
- telemetry labels and organization/person-level analytics;
- routine export and support bundles.

No API accepts an employee/principal identifier and returns matching sealed
content. Case construction begins from a reported event, work item, session,
incident, or bounded time window and records why each scope expansion is needed.

## 6. Case-bound access workflow

### 6.1 Case request

An authorized requester creates a signed case containing:

- case type and externally meaningful reference;
- specific question and permitted purpose;
- requested projects, sessions, records, fields, and time window;
- why standard/tool evidence is insufficient;
- expected data classes and affected participants;
- requested access duration and output form;
- notification posture and reason for any delayed notice;
- hold request, if distinct preservation is required.

The workflow rejects open-ended requests such as “all activity by this person,”
“anything concerning,” or an unset end date.

### 6.2 Approval

Policy maps case type to independent approver roles. At least two distinct
principals approve content disclosure, with privacy/security/legal/records roles
chosen by organizational policy. The requester cannot satisfy both approvals,
and the employee's ordinary manager is never sufficient authority.

Approvers see metadata and the requested scope, not transcript content. Approval
binds the exact query/record-set digest; expanding scope creates a new approval.
Break-glass access, if enabled at all, still requires two principals, expires
quickly, triggers immediate independent notice, and requires after-action review.

### 6.3 Disclosure

- Resolve the approved record-set manifest and re-check authorization at use.
- Decrypt only approved records and fields into an isolated, non-indexed case
  workspace with no general application navigation.
- Make grants short-lived, non-transferable, and purpose/case bound.
- Record every view, decryption, failed access, annotation, and export as a signed
  case event.
- Mark exports with case ID, scope, recipient, creation time, manifest digest,
  and handling restrictions; never export an escrow unwrap key.
- Prefer reviewed extracts over bulk transcript export where they answer the
  approved question.

The workflow is deliberately consequential, but not arbitrarily inconvenient:
the friction comes from independent authorization, exact scope, and durable
accountability rather than slow user experience or security-through-obscurity.

### 6.4 Notice and participant rights

The suite provides configurable templates and signed records for:

- notice before sealed capture begins;
- a persistent in-session indication of capture posture;
- policy, purpose, retention, and contact information;
- notice that content was accessed, unless a documented rule delays it;
- correction/context statements attached by an affected participant without
  rewriting the original evidence;
- a report of capture and access metadata available under organization policy.

Employment, labor, privacy, records, healthcare, and privilege requirements vary
by jurisdiction and use. Deployment approval requires organizational counsel and
privacy/security owners to review the local policy; the product does not encode
one jurisdiction's legal conclusion as universal.

## 7. Retention, hold, and destruction

- Every content record has a disposition time at creation. “Indefinite” and
  missing retention are invalid for sealed content.
- Ship a short example retention profile, but require the deploying organization
  to select and document its period rather than presenting a product default as
  a legal rule.
- Expiry destroys the relevant wrapped data key or per-record key material and
  deletes ciphertext according to the backend's verifiable lifecycle.
- Preserve only the signed manifest, ciphertext digest, policy, disposition
  evidence, and minimum operational metadata after destruction.
- A legal/case hold names exact records or a deterministic bounded query, has an
  owner and review date, and prevents only those records' disposition.
- Holds do not silently broaden future capture and cannot resurrect already
  destroyed content.
- Backups honor disposition through documented key destruction and bounded
  backup expiry; restore cannot make expired plaintext decryptable again.
- A scheduled reconciliation proves that live blobs, manifests, wrapped keys,
  holds, and destruction receipts agree, reporting every orphan or mismatch.

## 8. Component ownership

| Component | Responsibility |
|-----------|----------------|
| **regista** | Signed policy, content manifests, case/approval/hold/access/disposition entities and transitions; authorization and separation-of-duties invariants; keyed commitment/envelope primitives where warranted |
| **agent-provenance / cairn** | Harness capture, field classification, immediate encryption, coverage/failure events, bounded streaming, and adapter conformance fixtures |
| **dossier** | Capture posture and coverage views; case request/approval workspace; isolated disclosure surface; notice and access-history views |
| **agent-notes** | Agent-visible capture posture and policy explanation; session/work linking; no transcript retrieval surface |
| **agent-capability-broker** | Optional time-limited grant of the disclosure capability to the isolated service; never delivery of unwrap keys to an agent or ordinary child process |
| **agent-wake** | Metadata-only approval/expiry/hold notifications; no transcript bodies or excerpts in signals |
| **agent-suite** | Profile configuration, escrow/blob backend composition, doctor aggregation, retention jobs, backup/restore behavior, qualification, and operator runbooks |

The agent-suite repository remains thin: it composes these contracts and proves
their deployment posture; it does not implement another vault, case store, or
authorization engine.

## 9. Work plan

### Phase 0 — Governance and threat model

#### WI-0.1 — Purpose and prohibited-use policy

**Owner:** agent-suite, with organizational privacy/security/legal approval.  
Publish the capture modes, permitted case types, role matrix, notice text,
retention classes, prohibited derived uses, and policy-change process. Include
employee and manager misuse in the threat model.

**AC:** policy fixtures reject routine performance review, person-wide fishing,
single-manager approval, unset retention, silent sealed capture, model training,
and unapproved purpose expansion.

#### WI-0.2 — Data-flow and compromise analysis

**Owner:** cairn + regista + dossier.  
Map plaintext from harness callback through encryption, storage, disclosure, and
destruction. Threat-model compromised harnesses, application/DB/blob operators,
malicious managers, colluding approvers, backup readers, forged case scope,
plaintext-digest guessing, export leakage, and orphaned keys/blobs.

**AC:** every plaintext boundary and privileged principal is named; mitigations,
residual risks, and fail-closed behavior are testable and linked to claims.

### Phase 1 — Policy and evidence substrate

#### WI-1.1 — Signed content-policy schema

**Owner:** regista.  
Implement versioned capture policy and deterministic evaluation for mode, fields,
classification, size, encryption, retention, export, notice, and case rules.

**AC:** the same inputs produce the same signed decision; unknown mode/version,
missing retention, or unavailable encryption resolves to no content capture and a
named coverage failure—not plaintext fallback.

#### WI-1.2 — Transcript-safe encrypted envelope and blob protocol

**Owner:** regista + cairn.  
Define the manifest/envelope, associated data, streaming interface, per-session
key lifecycle, ciphertext commitment, and backend-neutral blob contract. Provide
at least filesystem and one organization-grade object-store implementation.

**AC:** tampering, swapping across project/session/turn, truncation, replay,
oversize input, missing key backend, backend outage, and plaintext-digest guessing
have executable negative tests. Searches of DB, logs, temp paths, and ordinary
backups find no fixture plaintext.

#### WI-1.3 — Case, approval, hold, and disposition state machines

**Owner:** regista.  
Add generic signed entities and transitions with distinct-principal approval,
exact scope binding, expiry, revocation, delayed-notice reason, and immutable
access history.

**AC:** no disclosure token can be produced without the configured approvals;
scope mutation invalidates approval; holds and destruction are race-safe and
idempotent; replay reconstructs the same result.

### Phase 2 — Capture and ordinary experience

#### WI-2.1 — Harness capture adapters

**Owner:** cairn.  
Add sealed capture to each supported harness using recorded-real fixtures.
System/context, user, assistant, and tool bodies declare independent coverage;
partial support is reported rather than generalized.

**AC:** live proofs correlate encrypted content with session, turn, principal,
delegation, work, and tool events; subagents, compaction, retries, cancellation,
stream interruption, and unsupported hooks produce honest coverage states.

#### WI-2.2 — Posture, notice, and coverage UX

**Owner:** dossier + agent-notes.  
Show capture mode before and during a session; render retained categories,
coverage gaps, expiry/hold state, policy version, and access history without
offering content browsing.

**AC:** a human and an agent can tell whether content is absent, sealed, held,
expired, destroyed, partially captured, or disclosure-authorized. No ordinary
route, API, CLI, template, or accessibility representation contains plaintext.

### Phase 3 — Escrowed disclosure

#### WI-3.1 — Isolated disclosure service

**Owner:** dossier, using regista authorization.  
Implement a separately deployed process/credential boundary for approved case
access. Keep the ordinary dossier process unable to unwrap content.

**AC:** two distinct case approvals produce an exact, expiring grant; revocation
and expiry stop an active workflow; unauthorized, stale, replayed, and
scope-modified grants fail and emit signed attempts.

#### WI-3.2 — Minimum-necessary review and export

**Owner:** dossier + cairn verifier.  
Provide sequential case review, field/record selection, context annotations, and
signed evidence packets with an offline-verifiable manifest.

**AC:** the verifier proves disclosed content against the authorized manifest,
names omissions and destroyed/unavailable records, and needs public verification
material rather than signing or escrow master keys.

#### WI-3.3 — Hold, disposition, and reconciliation jobs

**Owner:** regista + agent-suite.  
Implement scheduled expiry, crypto-shredding/backend deletion, hold reconciliation,
orphan detection, retry/dead-letter behavior, and operator alerts.

**AC:** qualification proves expiry through backup/restore, exact hold survival,
eventual cleanup after hold release, no resurrection, and honest partial failure.

### Phase 4 — Suite qualification

#### WI-4.1 — Deployment profiles and doctor contract

**Owner:** agent-suite.  
Add explicit `standard` and `sealed-evidence` profile posture. Doctor checks policy
validity, backend reachability, key separation, unwrap denial from ordinary
services, retention scheduler, orphan state, pending/expired grants, notice
configuration, and restore compatibility without accessing content.

**AC:** sealed mode cannot report healthy when ordinary services can unwrap,
retention is unset, notice is absent, or a required backend/job is unavailable.

#### WI-4.2 — Adversarial qualification

**Owner:** cross-component.  
Run positive and negative journeys for capture, absence, partial coverage, case
approval, access, export, notice, hold, expiry, restore, and destruction. Include
malicious manager, compromised web process, DB reader, blob reader, one approver,
two colluding ordinary users, forged notification, and transcript-search attempts.

**AC:** an independent reviewer can reproduce all results from a pinned suite
release; failures are named and cannot be confused with “no matching evidence.”

#### WI-4.3 — Pilot exit review

**Owner:** operator and organizational governance owners.  
Pilot `standard` mode first. Enable sealed evidence for one bounded, non-production
or low-risk use case only after policy approval and qualification. Review actual
investigation value, false expectations, access frequency, employee feedback,
storage/operating cost, and whether standard evidence answered the same questions.

**AC:** a signed decision either retains, narrows, expands, or disables sealed
capture. Expansion to another use case is a new decision, not automatic rollout.

## 10. Release gates

Sealed session evidence is supported only when all are true:

1. ordinary tool/session evidence remains useful without transcript content;
2. capture mode and purpose are visible to affected participants;
3. plaintext is encrypted before durable ingest and absent from ordinary logs,
   events, projections, search, backups, and support bundles;
4. ordinary applications, agents, managers, and DB/blob operators cannot decrypt;
5. disclosure requires an exact case, independent dual approval, and an expiring
   scope-bound grant;
6. every access and export is signed, attributable, and reviewable;
7. disposition, hold, crypto-shredding, backup expiry, and restore are proven;
8. prohibited analytics and person-wide discovery have architectural and tested
   enforcement, not just policy prose;
9. every harness reports content coverage honestly;
10. organizational privacy/security/legal owners have approved the deployment's
    purpose, notice, role, and retention policy.

Failure of any gate leaves the feature experimental and disabled outside test.

## 11. Explicit non-goals

- General transcript recall, chat history, or knowledge search.
- Manager dashboards or employee-level activity summaries.
- Continuous quality sampling without a separately approved sampling design.
- Automatic discipline, risk scoring, sentiment analysis, or behavioral alerts.
- Capture outside supported, visibly enrolled agent sessions.
- Claiming redaction guarantees that sensitive data is absent.
- Replacing a legal hold, records, HR, incident, or eDiscovery platform.
- Encoding jurisdiction-specific legal advice into product defaults.

## 12. Plan 010 promotion scorecard

This plan promotes and narrows Plan 010 §§8.4, 9.4, 9.6, and the legal-hold
portion of Horizon 2.

| Dimension | Score | Reason |
|-----------|------:|--------|
| User pain | 2 | Tool-only evidence cannot reconstruct important instruction and response failures |
| Charter fit | 2 | Trustworthy reconstruction is central to accountable agent work |
| Existing alternative | 1 | External eDiscovery/GRC tools can receive exports but cannot enforce capture-time harness semantics |
| Determinism | 2 | Policy, encryption, approval, scope, and disposition have deterministic truth paths |
| Privacy/security | 1 | The design reduces access risk, but capturing content necessarily expands data risk |
| Cross-component value | 2 | Capture, store, human face, agent face, capabilities, signaling, and deployment all participate |
| Proofability | 2 | Positive and adversarial journeys are executable |
| Operating cost | 1 | Escrow custody, blob storage, retention jobs, and governance are material ongoing costs |
| Reversibility | 2 | Standard mode remains default; sealed capture is policy-scoped and can be disabled/destructed |
| **Total** | **15/18** | Strong candidate, subject to privacy veto and governance approval |

The score supports implementation because the reconstruction gap is real. It
does not support default-on deployment. Privacy review retains an unconditional
veto for any proposed use case.

## 13. Implementation-language decision

This plan does not require a language port. Its difficult properties are policy
semantics, key separation, authorization, truthful adapter coverage, and
cross-component proof—not Python memory management. Use mature audited crypto,
secret-backend, Postgres, and object-store libraries; isolate escrow authority in
a small separately deployed process; and measure its attack surface before
considering a rewrite.

A future Rust spike is warranted only for a narrow component if evidence shows a
specific gain, such as a single-file cross-platform harness bridge, streaming
capture under adversarial input, a long-lived network daemon exposed to untrusted
webhooks, or a minimal disclosure helper that can materially shrink the trusted
computing base. Any spike must preserve the signed wire contracts and prove
interop against the Python implementation. A whole-project rewrite is not an
accepted work item under this plan.
