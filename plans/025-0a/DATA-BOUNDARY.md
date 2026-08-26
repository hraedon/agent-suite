# DATA-BOUNDARY - 0A-4 internal draft v0.2, 2026-08-25 (second review: minimax-m3; D-0A-1 alignment applied)

This system attests agent development work on code and artifacts. Patient data is not an accepted content class, and the provenance kernel is not a PHI repository. This design is layered risk reduction, not a guarantee that PHI will never be captured. It refines `TRUST-MODEL.md` section 11 and remains subject to its section 12 residuals.

`ASSUMPTION:` Producers can retain development artifacts in systems governed for their actual content; the provenance path needs identity, digests, policy context, proofs, and bounded metadata rather than artifact bodies. `OPEN:` The 0A-4 owner must finalize the schema, numeric limits, retention schedule, and incident roles below before implementation or production data admission.

## 1. Allowed content and draft schema

Admission is allowlist-based. Unknown fields, unknown schema versions, disallowed content classes, malformed encodings, and values over a limit are refused before retention. A clean scan cannot convert a disallowed class into an allowed class (`INV-044`, `INV-045`, `INV-046`).

### Allowed metadata classes

| Class | Allowed values | Draft cap | Notes |
|---|---|---:|---|
| Protocol identifiers | schema/claim/event type, protocol version, algorithm id, domain, action, reason/status codes | 64 ASCII bytes each; 32 fields/event | Registered enums or constrained identifiers only; no free-form fallback. |
| Object identifiers | event, claim, project/tenant pseudonym, entity, action, policy, key, checkpoint, witness, decision, incident, and correlation ids | 128 ASCII bytes each; 40 fields/event | Opaque identifiers; no patient, MRN, encounter, account, email, hostname, path, or human name in an id. |
| Principals and roles | pseudonymous principal/key id, service role id, organizational authority id, lineage id | 128 ASCII bytes each; 16 entries/event | Human display names and email addresses remain in the authoritative identity system, referenced by opaque id. |
| Digests and signatures | algorithm-tagged subject/evidence/file/root/predecessor/policy digests; signatures; public-key or certificate references | 128 bytes/digest; 16 KiB aggregate cryptographic material/event | No artifact bytes. Certificate bodies are admitted only if a later schema explicitly allows and bounds them; references/digests are preferred. |
| Positions and bounds | log position, range boundaries, counts, nonce/idempotency number, sizes, parser-limit profile id | unsigned 64-bit values; 32 values/event | Range/count fields must reconcile; integer text is not free-form metadata. |
| Time and lifecycle | non-authoritative issued-at, accepted TSA time, bounded expiry/not-before, revocation positions, key state | RFC 3339 UTC text up to 32 ASCII bytes or signed integer representation | Caller time never establishes authority; accepted time requires policy-selected evidence (`INV-010`). |
| Policy and verification results | policy id/version/digest; Q1/Q2/Q3 enums; scope; warning/degraded/legacy codes | 64 codes/event; 4 KiB aggregate | Structured codes only. Human explanations live outside authoritative evidence and are referenced by digest when needed. |
| Proof and checkpoint material | inclusion/consistency paths, checkpoint roots/signatures, witness observations | 256 path nodes and 64 KiB aggregate/event | Pre-allocation count and byte limits apply (`INV-045`). |
| Approved short text — **CONDITIONAL, dropped under D-0A-1 default (a)** | change title, review summary, approval rationale, denial/refusal category — admitted only if signed policy selects D-0A-1 option (b) redactable-by-construction | UTF-8; 256 bytes/field, 1 KiB aggregate/event | Plain text only; no markup, URLs, code, logs, prompts, transcript excerpts, stack traces, secrets, or artifact snippets. Scanned before retention. |
| Opaque artifact descriptor | digest, declared media-type enum, byte size, source-system class, external retention reference id | 8 descriptors/event; 2 KiB aggregate | Descriptor only; body is never admitted (`INV-047`). |

`OPEN:` Finalize whether approved short text is needed at all. The safer default is structured reason codes plus an external record digest. If retained, select the permitted fields, vocabulary, Unicode normalization, scanner set, and retention period.

### Event envelope caps

- Maximum canonical event envelope: 128 KiB, including proofs and signatures.
- Maximum nesting depth: 8; maximum array items: 256; maximum object fields: 128.
- Maximum decompressed input: none for event admission because compressed envelopes are refused. Bundle verification uses a separately signed parser-limit profile and never admits bundle bodies to the kernel.
- Maximum opaque artifact size represented by one descriptor: 16 GiB; this bounds declared metadata and processing policy, not retained content. `OPEN:` Validate this cap against the 0B/0C workload.
- Maximum bundle manifest: 1 MiB and 10,000 digest-only subjects under a separately bounded bundle schema. `OPEN:` Confirm representative workload and denial-of-service limits before 0C protocol acceptance.

These are draft engineering limits, not settled protocol constants. Parsers must enforce byte, count, depth, path, read, decompression, and time budgets before allocation, filesystem access, or expensive proof work (`INV-045`).

### Explicitly disallowed content

The provenance path refuses patient records and clinical data; source or binary artifact bodies; source trees; patches/diffs; arbitrary files; screenshots/images/audio/video; logs and stack traces; model prompts, responses, tool output, and transcripts; test fixtures containing realistic patient data; database exports; email/message bodies; secrets, credentials, tokens, connection strings, and private keys; arbitrary URLs or paths; encoded payloads; archives and compressed event envelopes; and encrypted content. A digest and bounded descriptor may identify an external artifact without admitting its body (`INV-044`, `INV-047`).

## 2. Data minimization

- Collect only fields required to answer Q1 authentication, Q2 authorization-at-position, Q3 completeness/non-equivocation, enforce a policy, or audit the resulting decision. Optional fields are absent, not populated with source-system text (`INV-019`, `INV-044`).
- Represent people, systems, projects, and external records by opaque ids resolved only in their authoritative systems. Do not duplicate names, email addresses, workstation names, paths, ticket bodies, or organization directory attributes in the kernel.
- Represent every development artifact by an algorithm-tagged digest, byte size, constrained type, and opaque external reference. Do not retain the body merely to make later display convenient (`INV-044`, `INV-047`).
- Use registered enums for actions, outcomes, warnings, reasons, scopes, and policy states. Under the recommended D-0A-1 default (a) free text is **forbidden at admission**; only if the owner selects option (b) does a bounded, scanned, redactable text class exist, and it is excluded from security decisions.
- Separate authoritative evidence from human display metadata. Display systems may retrieve content from its owning system under that system's access controls; the kernel stores only the evidence linkage and digest.
- Set retention by field class. Cryptographic events may require long retention, while refusal telemetry and quarantine indexes should use the shortest incident/legal period. `OPEN:` The records/privacy owner must approve the retention and legal-hold schedule for each class.

These rules primarily implement `INV-044`; their parser bounds implement `INV-045`, and digest-only artifact treatment implements `INV-047`.

## 3. Scanning and refusal

Scanning is defense in depth after schema/allowlist validation and before durable event, projection, queue, diagnostic, or cache retention. It never widens the allowlist and never supports a claim that PHI is absent (`INV-046`).

The pre-retention path scans:

- Every allowed short-text value after strict UTF-8 decoding and normalization.
- Identifier values for prohibited identifier patterns and accidental direct identifiers.
- Media-type declarations, external-reference labels, and source metadata for attempts to smuggle free text.
- The decoded canonical event envelope for secrets and recognizable patient-data patterns, while excluding cryptographic bytes from semantic classification.
- Producer-side source fields before transformation, when the producer has access to them; this catches accidental mapping before disallowed fields are discarded. Producer scanning does not authorize transmission of those source fields to the kernel.

`ASSUMPTION:` (conditional control — inactive under D-0A-1 default (a); active only if signed policy admits textual retention, per INV-046) The scanner set will combine deterministic secret/direct-identifier patterns with a target-approved PHI detection service operating within the same approved data boundary. `OPEN:` The privacy/security owner must approve scanner products, update cadence, thresholds, test corpus, false-positive handling, and whether scanning may occur outside the originating host.

On disallowed schema/content or a scan finding, admission fails closed. The refusal audit event contains only:

- refusal event id and correlation id;
- authenticated producer principal/service id and project pseudonym;
- proposed event type/schema version;
- refusal category code such as `schema-disallowed`, `limit-exceeded`, `suspected-phi`, or `suspected-secret`;
- scanner/rule-set id and version, but not rule match text;
- attempted byte count and bounded field-name code, but no field value, snippet, digest of detected content, source path, or artifact body;
- non-authoritative receipt time, policy version, and disposition/escalation code.

The refusal event itself passes the same allowlist. Application logs expose the event id and category only; diagnostics, exceptions, traces, metrics labels, and dead-letter queues must not include rejected values. If audit append is unavailable, refusal remains a denial and only a bounded in-memory counter is kept; content is not queued for retry (`INV-045`, `INV-046`).

## 4. Opaque and encrypted artifacts

Opaque, encrypted, binary, compressed, image, archive, and otherwise non-inspectable artifacts are digest-only by default (`INV-047`). The producer computes an approved algorithm-tagged digest without sending the body to the kernel. The kernel accepts only the digest, byte size, constrained media-type enum, source-system class, and opaque external reference id within the draft caps.

The provenance system does not decrypt, unpack, transcode, render, index, thumbnail, content-scan, cache, or retain these bodies. Verification establishes equality to a digest, not safety or content. If an artifact cannot be safely hashed at its owning boundary, admission is refused rather than uploaded for kernel-side hashing. Any future content-bearing exception requires a new signed schema/policy, threat and privacy review, explicit retention and deletion design, and protocol acceptance; scanner success alone cannot create an exception.

## 5. Accidental-capture procedure

`OPEN:` Replace these placeholders with named organizational roles before production use: `[REPORTER]`, `[PRIVACY/SECURITY INCIDENT OWNER]`, `[KERNEL CUSTODIAN]`, `[SYSTEM OWNER]`, `[LEGAL/RECORDS OWNER]`, `[BACKUP OWNER]`, `[DOWNSTREAM OWNER]`, and `[NOTIFICATION AUTHORITY]`.

1. **Report and restrict.** `[REPORTER]` records only an incident id and affected evidence ids through the approved incident channel. `[KERNEL CUSTODIAN]` immediately restricts access to the suspected record and derived projections without copying content into the ticket or chat. Ordinary claims and displays mark the item unavailable; no PHI-absence claim is issued (`INV-048`).
2. **Preserve minimal incident evidence.** `[PRIVACY/SECURITY INCIDENT OWNER]` records discoverer, discovery time, affected system/evidence ids, access-control changes, known recipients, and cryptographic digests where approved. Suspected content is viewed only by authorized responders in an access-restricted quarantine; no general-purpose quarantine copy is created.
3. **Contain propagation.** `[SYSTEM OWNER]` stops affected ingestion routes, invalidates projections and caches, suspends exports/bundles, and identifies queues, replicas, search indexes, observability systems, recipient systems, and external references by id. Existing recipient access is restricted where possible.
4. **Assess obligations.** `[PRIVACY/SECURITY INCIDENT OWNER]` and `[LEGAL/RECORDS OWNER]` determine whether PHI was involved, disclosure scope, required preservation, risk assessment, contractual/regulatory notification, and whether deletion is legally permitted. A classifier result does not settle this assessment.
5. **Delete or retain under authority.** On written authorization from `[LEGAL/RECORDS OWNER]`, `[KERNEL CUSTODIAN]` deletes or cryptographically erases ordinary-store and projection copies where the selected substrate permits (`OPEN:` cryptographic erasure presupposes encryption-at-rest with key shredding — the 0B/0C substrate record must state whether the chosen substrate provides it; otherwise this reduces to overwriting side-store copies), while retaining only the minimum authorized incident record. If a legal hold or immutable medium prevents deletion, access remains restricted and the exception, scope, authority, and expiry/review date are recorded.
6. **Handle downstream copies.** `[DOWNSTREAM OWNER]` confirms disposition for each export, bundle, replica, queue, cache, report, and recipient system. Deletion is not declared complete from the primary-store result alone. Unreachable or third-party copies remain explicit incident residuals.
7. **Handle backups.** `[BACKUP OWNER]` identifies affected backup sets, restricts restore access, records natural-expiry dates or authorized purge, and attaches a restore-intercept rule. Any restore re-quarantines or deletes the affected ids before ordinary service and records the result. Backup expiration is not represented as retroactive proof of deletion.
8. **Notify and close.** `[NOTIFICATION AUTHORITY]` performs required escalation/notification. `[PRIVACY/SECURITY INCIDENT OWNER]` closes only after containment, copy inventory, legal disposition, owner attestations, control correction, and lessons/tests are recorded. The kernel disposition event contains incident id, affected evidence ids, role ids, action/status codes, policy version, and digests of external authorizations, never captured content (`INV-048`).

Quarantine is an incident-control state, not an accepted artifact class or a route around the allowlist. Access is deny-by-default, time-bounded, individually authenticated, and audited. `OPEN:` The owner must define quarantine technology and location, access quorum, maximum duration, deletion mechanics per substrate, notification timelines, and evidence needed to close an incident.

## 6. Backups, caches, and downstream copies

`INV-048` applies to every copy, not only the authoritative event store:

- **Backups and restore media:** maintain an index from evidence id/time range to backup sets; restrict affected restores; enforce restore-time re-quarantine/deletion before reconnecting services; preserve legal holds and record expiration or purge authority.
- **Projections and databases:** remove or mask affected values under authorized disposition, rebuild projections from corrected authoritative inputs, and verify rebuild equivalence. A tombstone may contain only ids, disposition code, policy version, and authorization digest.
- **Caches and local state:** invalidate by evidence id, subject digest, policy, and cut; purge browser/server/verifier caches and temporary files where supported; restart processes if bounded memory cannot be selectively cleared.
- **Queues, dead letters, logs, metrics, traces, and scanner systems:** content must never be emitted to these systems by design. During an incident, inspect access-controlled indexes and retention classes for unexpected copies without reproducing content in search results or tickets.
- **Bundles, reports, and exports:** suspend generation, revoke access where possible, enumerate recipients, issue corrected/replacement artifacts, and preserve an explicit list of copies whose deletion cannot be verified.
- **Downstream applications and external systems:** each integration must have an owner, copy inventory, deletion/restriction mechanism, retention rule, and incident callback before it is enabled. A downstream acknowledgment is operational evidence, not cryptographic proof that no copy remains.

`OPEN:` The system owner must maintain the authoritative copy/flow inventory and assign each downstream and backup owner before production use.

## 7. Invariant map

| Design element | Primary invariants | Required effect |
|---|---|---|
| Allowlist and draft schema | `INV-044`, `INV-045`; principally ADV-01, ADV-02, ADV-09 through ADV-13 | Admit only defined bounded fields and metadata classes; patient data and artifact bodies are not accepted classes; reject unknown or oversized structures before allocation/retention. |
| Data minimization | `INV-044`, `INV-047`; principally ADV-01, ADV-02, ADV-09, ADV-10 | Store only security-relevant structured fields, pseudonymous references, digests, and bounded descriptors; keep bodies and identity detail in their owning systems. |
| Scanning and content-free refusal | `INV-045`, `INV-046`; accidental/plain detectable content submitted through ADV-01, ADV-02, ADV-09, ADV-10 | Scan inspectable allowed input before retention as defense in depth; deny on findings; audit the refusal without content or secrets. |
| Opaque/encrypted artifacts | `INV-045`, `INV-047`; ADV-01, ADV-02, ADV-09, ADV-10 | Never decrypt or retain bodies; admit only bounded metadata and digest; enforce parser/resource limits. |
| Quarantine, deletion, incident response | `INV-048`; residual against ADV-13 through ADV-20 and ADV-25 where an administrator/root exceeds deletion authority | Restrict access, preserve minimal incident evidence, obtain legal authority, handle all copies, notify/escalate, and audit disposition without captured content. |
| Backups, caches, downstream copies | `INV-048`; especially ADV-13, ADV-20, and compromised downstream administrators outside the modeled boundary | Inventory and restrict every derivative copy; intercept restore; verify projection rebuild; record copies that cannot be deleted or verified. |
| Residual statement | `INV-044` through `INV-048`; compromised admission/scanner hosts and malicious administrators including ADV-13, ADV-14, ADV-19, ADV-20, ADV-25 | Never claim that scanning, digests, signatures, deletion, or the log cryptographically proves PHI absence. |

## 8. Residual statement

No signature, digest, checkpoint, schema allowlist, scanner result, refusal event, quarantine action, deletion record, backup expiry, or downstream attestation can prove that evidence contains no PHI. PHI may be hidden in allowed-looking text or identifiers, encoded values, source, logs, screenshots, binaries, encrypted artifacts, model transcripts, metadata, or external systems; classifiers and producer mappings have false negatives (`INV-044` through `INV-048`).

Digest-only handling authenticates equality, not content, safety, or PHI absence. A digest may itself permit confirmation attacks against guessable content. Quarantine and deletion cannot undo prior access or disclosure and may not reach legal holds, immutable backups, recipient copies, screenshots, compromised administrators/hosts, or systems outside deletion authority. An incident involving accidental capture retains all applicable assessment, preservation, notification, and remediation obligations. These residuals must be disclosed rather than converted into a positive PHI-free claim.
