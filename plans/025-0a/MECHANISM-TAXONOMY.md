# Plan 025 mechanism taxonomy

Version: v0.2-draft, 2026-08-26.

Status: DRAFT. This taxonomy partitions the 147 filed findings by failed security mechanism and is a strict refinement of the inventory's C1-C5 triage classes: 102 of 103 mechanisms remain wholly within one C-class, so inherited C-class assignments were not independently re-adjudicated. A finding has exactly one primary mechanism even when it has secondary effects.

## Selection semantics

- Effective severity for selection is `verified_severity` when present and Daybreak severity otherwise, ordered `Critical > High > Medium-High > Medium > Low-Medium > Low`. Thus SEC-01 is High, not Critical. For the inventory's four-column tally, the pinned mapping is `Critical -> Critical`, `High` or `Medium-High -> High`, `Medium` or `Low-Medium -> Medium`, and `Low -> Low`.
- **High-bearing** means a mechanism whose maximum effective severity is `High` or `Critical`, i.e. effective severity `>= High`; it includes Critical-only mechanisms even when they contain no finding literally rated High. `OPEN:` The owner must confirm this interpretation of the charter before probes are commissioned.
- Component counts use the inventory's ten report-level component names. `ASSUMPTION:` for a count tie, choose the component containing the highest-effective-severity finding, then a verified finding, then the component order `trustlog, crypto, regista-cli, persist, cairn, dossier, agent-suite, agent-notes, agent-wake, acb`; choose a finding within a component by the same severity/verification rules and then lexical finding id.
- `ASSUMPTION:` "a second component" means a different logical product where possible. The four Regista reports are one logical product for diversity, even though they remain distinct component values for counting and traceability. For mechanisms spanning three or four components, choose the second logical product by highest effective severity, then verified status, then the component order above; choose its finding by the same finding tie-break. This makes the `authenticated-approval-and-sod` choice of `an-1` derivable.
- A mandatory Critical may also satisfy the dominant-component or second-component obligation for its mechanism. Suspected findings remain in counts.
- `OPEN:` The owner should confirm the tie-break, report-component counting rules, and either accept approximately 78 probes or direct a pre-selection merge of near-synonymous singletons before probes are commissioned; changing any rule requires recomputing the reproduction set. Candidate merges/questions are `checked-evidence-required-for-pass` + `aggregate-verdict-completeness`; placing `as-10` under `network-endpoint-authentication` + `typed-gate-result-and-exit-semantics` rather than widening `subprocess-result-authenticity`; and coarsening `preallocation-parser-limits`, `read-to-eof-path-denial`, `query-and-batch-budget`, and `application-request-work-budget` toward the charter's `unbounded-parse` example. No merge is made in this draft.

## Mechanisms

Each entry gives the stable slug, definition and closing control shape, owning boundary under the target decomposition, and its complete finding membership.

### Authenticated authority and evidence

- **`row-envelope-reconciliation`.** Mutable rows or projections are treated as signed authority. Close it by authenticating the envelope, recomputing stored digests, and reconciling every decision-bearing field at each authoritative read. Owning boundary: kernel for evidence reads and gate-engine for admission reads; dossier/agent-notes must consume claims rather than rows. Findings: `SEC-11`, `persist-2`, `persist-4`, `dossier-2`, `dossier-4`, `an-8`.
- **`unique-chain-head-binding`.** A mutable chain-head pointer can select a validly signed fork instead of the unique accepted predecessor chain. Close it by binding the named head to the authenticated unique-position chain and refusing competing descendants under `INV-005`. Owning boundary: kernel. Findings: `persist-9`.
- **`canonical-subject-reconciliation`.** Caller or child-record subject fields override canonical identity or lifecycle state. Close it by deriving kind, principal, project, and status from authenticated canonical records. Owning boundary: kernel for principal claims; bootstrap-root for provisioning. Findings: `SEC-08`, `as-9`.
- **`queued-row-ingress-authenticity`.** A durable queue row can bypass authenticated ingress. Close it by MAC/signature-verifying queued content and its routing context before dispatch. Owning boundary: transport. Findings: `aw-7`. `ASSUMPTION:` This deliberately diverges from the inventory's INV-004-style row/envelope dedup: the pending row has no authenticated envelope to reconcile, so the primary failure is unauthenticated durable ingress; `INV-004` remains a secondary consumer obligation.
- **`signed-policy-as-authority`.** Enforcement uses mutable policy state rather than the signed registration. Close it by verifying the policy object and binding every decision to its digest/version. Owning boundary: gate-engine. Findings: `persist-1`.
- **`signature-before-admission`.** Unsigned events affect workflow admission or precedence. Close it by authenticating the event and its chain position before any authority use. Owning boundary: gate-engine with kernel claim input. Findings: `persist-8`.
- **`imported-state-authenticity`.** Imported lifecycle state affects local authority without provenance checks. Close it with authenticated import, lineage/lifecycle validation, and legacy quarantine. Owning boundary: kernel at migration ingestion; agent-notes only projects admitted events. Findings: `an-7`, `an-15`.
- **`verifier-suppression-input-authenticity`.** Unverified evidence suppresses a real integrity violation. Close it by allowing only authenticated, policy-admissible evidence to suppress findings. Owning boundary: kernel. Findings: `cairn-05`.
- **`expected-witness-roster-pinning`.** The submitted artifact chooses the witnesses against which it is judged. Close it by pinning the expected roster and threshold in trusted policy. Owning boundary: kernel. Findings: `cairn-06`.
- **`externally-anchored-root-required`.** Missing or self-selected roots satisfy verification. Close it by requiring a policy-pinned, independently witnessed checkpoint and explicit failure on absence. Owning boundary: kernel. Findings: `cairn-08`.
- **`checked-evidence-required-for-pass`.** Unchecked or indeterminate evidence contributes to PASS. Close it with a typed aggregate in which every required result is positively verified. Owning boundary: kernel. Findings: `cairn-16`.
- **`event-pairing-completeness`.** An orphan end event is displayed as a completed execution. Close it by proving required begin/end structure before issuing or rendering completion. Owning boundary: app:dossier, consuming a kernel claim. Findings: `dossier-1`.
- **`artifact-trust-root-authenticity`.** Self-hashes or caller-supplied manifests are mistaken for trusted baselines. Close it with a signed subject-to-digest binding rooted in pinned policy and owner checks. Owning boundary: bootstrap-root for suite artifacts and broker for capability manifests. Findings: `as-2`, `as-4`, `acb-1`.
- **`release-content-pinning`.** Package or registry content is installed without a cryptographic release binding. Close it by resolving immutable content digests from signed release metadata. Owning boundary: bootstrap-root for both suite and capability packages under `INV-035`; the broker consumes the installed binding at execution. Findings: `as-8`, `acb-9`.
- **`subprocess-result-authenticity`.** Parsed child or remote output is accepted despite process/transport failure. Close it by coupling typed output to a successful exit and authenticated channel. Owning boundary: bootstrap-root. Findings: `as-6`, `as-10`.
- **`executable-identity-binding`.** A pathname or substring stands in for executable identity. Close it with content digest, ownership/mode checks, symlink-safe resolution, and descriptor-bound execution. Owning boundary: bootstrap-root for suite execution and broker for capability execution. Findings: `as-1`, `acb-5`, `acb-7`.

### Temporal authority and credentials

- **`retired-key-rejected-for-new-action`.** Historical key acceptance is reused as current authority to create a new action. Close it by resolving current authority at an authenticated log position and separating historical verification from permission-now. Owning boundary: kernel. Findings: `SEC-01`, `crypto-2`.
- **`offline-key-validity-window-enforcement`.** Replay/offline verification drops key validity windows. Close it with one temporal state machine and online/offline differential tests. Owning boundary: kernel. Findings: `SEC-03`.
- **`legacy-envelope-key-retirement`.** Retired roots can forge newly created legacy evidence that claims an old date/version. Close it by rejecting or quarantining legacy evidence and resolving retirement against authenticated history. Owning boundary: kernel migration path. Findings: `SEC-06`, `cairn-10`.
- **`canonical-revocation-time-comparison`.** Lexical timestamp comparison bypasses revocation. Close it by parsing canonical instants and evaluating authority at chain position. Owning boundary: kernel. Findings: `cairn-11`.
- **`active-key-selection-for-integrity-marker`.** Integrity verification chooses the first historical key rather than an authorized active key. Close it with policy- and position-aware key selection. Owning boundary: kernel. Findings: `cairn-13`.
- **`session-authority-revalidation`.** A session remains authoritative after account or group revocation. Close it with short sessions plus revocation/version checks on privileged actions. Owning boundary: app:dossier. Findings: `dossier-12`.
- **`runtime-credential-revocation`.** Removing a credential does not invalidate the daemon's loaded copy. Close it with acknowledged reload or process replacement and immediate denial after removal. Owning boundary: transport. Findings: `aw-4`.
- **`rotation-overlap-expiry`.** A previous transport key remains authoritative indefinitely after rotation. Close it with bounded overlap and an immediate-revocation path. Owning boundary: transport. Findings: `aw-9`.
- **`external-credential-revocation-assurance`.** Best-effort external revocation leaves a retired credential valid. Close it by failing rotation unless retirement is confirmed or otherwise constraining old authority. Owning boundary: broker. Findings: `acb-12`.

### Context binding

- **`event-position-and-replay-binding`.** Detached signatures omit event id, sequence, predecessor, or nonce and can be transplanted. Close it with a domain-separated canonical envelope binding all position/replay fields. Owning boundary: kernel. Findings: `SEC-02`.
- **`authority-at-chain-position`.** Caller-supplied payload time determines authority or coverage. Close it by resolving authority and scope at authenticated log positions, not claimed timestamps. Owning boundary: kernel. Findings: `SEC-04`, `SEC-07`, `cairn-03`.
- **`signer-identity-binding`.** A verified key can assert an arbitrary signer id. Close it by deriving signer identity from canonical key authority and binding it into the signed context. Owning boundary: kernel. Findings: `SEC-13`.
- **`signature-domain-separation`.** A signing client signs attacker-chosen cross-protocol bytes. Close it with typed request construction, domain separation, and refusal of raw signing. Owning boundary: kernel. Findings: `crypto-3`.
- **`entity-namespace-binding`.** Reads or claims bind an id without its entity kind. Close it by binding and filtering on `(entity_kind, entity_id)`. Owning boundary: kernel for event reads and app:dossier for rendering. Findings: `persist-3`, `dossier-9`.
- **`attestation-subject-and-issuer-binding`.** An attestation omits the session/principal subject or authorized issuer relation. Close it by signing the full subject tuple and checking issuer authority. Owning boundary: kernel. Findings: `cairn-04`.
- **`delegation-authorization-binding`.** A signed `on_behalf_of` value is accepted without representation authority. Close it by binding delegator/delegate/subject/scope and checking delegated authority. Owning boundary: app:dossier with gate-engine authorization. Findings: `dossier-5`.
- **`project-key-isolation`.** One signing identity spans every project. Close it with project-scoped keys or explicitly scoped claims rooted in project policy. Owning boundary: bootstrap-root provisioning. Findings: `as-11`.
- **`canonical-actor-recording`.** The resolved actor is discarded and raw unresolved caller input is recorded. Close it by recording the authenticated canonical actor only. Owning boundary: app:agent-notes at command ingress, consuming a kernel identity/authority claim. Findings: `an-5`.
- **`signed-project-actor-context`.** Outbox signatures omit project, actor, kind, role, or lineage. Close it by signing the complete typed dispatch context. Owning boundary: app:agent-notes. Findings: `an-9`.
- **`transport-identity-source-binding`.** Trigger/source/reply identity is outside the MAC or authenticated connection. Close it by MAC-binding identity and source and correlating replies to the authenticated delivery. Owning boundary: transport. Findings: `aw-1`, `aw-3`, `aw-6`.
- **`replay-freshness-binding`.** Timestamp, nonce, event/reply id, or idempotency key is unsigned or not consumed. Close it by signing all freshness fields and atomically recording nonce use. Owning boundary: transport. Findings: `aw-2`, `aw-13`.
- **`dedupe-security-domain-binding`.** Deduplication is global rather than scoped to authenticated source. Close it by keying dedupe on source/security domain plus event id. Owning boundary: transport. Findings: `aw-14`.

### Authentication, authorization, and gates

- **`genesis-proof-consumed-by-first-write`.** A genesis boolean/verdict is not authenticated and atomically consumed by the first write, or absent bootstrap identity opens an ordinary-write window. Close it with an independently pinned signed bootstrap policy and a scoped admission decision atomically consumed by that action. Owning boundary: bootstrap-root + kernel under `INV-009`; suite is the bootstrap-side caller. Findings: `SEC-05`, `as-13`, `persist-13`.
- **`authenticated-approval-and-sod`.** Caller strings or permissive defaults stand in for authenticated approval and separation of duties. Close it with authenticated roles, explicit policy, distinct principals, and default DENY. Owning boundary: gate-engine. Findings: `SEC-10`, `persist-7`, `as-12`, `an-1`.
- **`operator-action-authorization`.** An operator-only action has no operator authorization boundary. Close it by authenticating the caller and evaluating operator policy. Owning boundary: gate-engine. Findings: `an-10`.
- **`scope-entitlement-enforcement`.** Declared workflow or harness scope is not enforced at use. Close it by checking the authenticated caller against the exact requested scope on every route/execution. Owning boundary: gate-engine for workflows and broker for harnesses. Findings: `cli-1`, `acb-2`.
- **`privileged-mutation-authorization`.** Ordinary callers can perform administrative mutation or mint project-authoritative artifacts. Close it with authenticated project-admin policy and attributable signing. Owning boundary: gate-engine. Findings: `cli-2`, `an-3`.
- **`stored-secret-access-control`.** Ordinary bearer tokens can retrieve stored delivery credentials. Close it with least-privilege secret-reference use and non-disclosure APIs. Owning boundary: app:regista-cli. Findings: `cli-3`.
- **`lease-scope-and-expiry`.** A caller leases unauthorized work or holds it indefinitely. Close it with pre-reservation scope checks and bounded leases. Owning boundary: gate-engine. Findings: `cli-6`.
- **`verification-head-completeness`.** A truncated prefix is reported as fully valid without an expected head. Close it with a pinned cut/head or an explicit partial-verification result. Owning boundary: kernel. Findings: `cli-7`.
- **`network-endpoint-authentication`.** Sensitive records or diagnostics are exposed when authentication configuration is absent. Close it with authentication and least disclosure by default. Owning boundary: kernel service edge for regista and app:agent-notes for its viewer. Findings: `cli-11`, `an-14`.
- **`local-peer-authentication`.** A local socket peer self-asserts routing identity. Close it by binding OS peer credentials to authorized adapter/destination identity. Owning boundary: transport. Findings: `aw-5`.
- **`filtered-verification-preserves-global-failures`.** Filtering hides a global integrity failure. Close it by separating presentation filtering from the full-chain verdict. Owning boundary: kernel under `INV-005`. Findings: `cairn-01`.
- **`aggregate-verdict-completeness`.** PASS omits unverified counts, halted replay, warnings, or inconsistent totals. Close it with exhaustive typed aggregation requiring all expected checks. Owning boundary: kernel for claims; dossier renders that claim. Findings: `cairn-02`, `dossier-3`.
- **`authenticated-coverage-receipt`.** Signatureless or un-MACed coverage evidence counts as verified. Close it by rejecting absent/invalid authenticators and legacy downgrade. Owning boundary: kernel. Findings: `cairn-07`, `cairn-12`.
- **`transition-role-default-deny`.** Unknown roles, workflow-version drift, or shortcut transitions satisfy a gate. Close it with versioned transition policy and exhaustive default DENY. Owning boundary: gate-engine. Findings: `cairn-15`, `as-14`, `an-4`.
- **`probe-evidence-not-fixture-pass`.** Synthetic fixtures yield a gating PASS without inspecting the installation. Close it with environment-bound probe evidence and explicit unavailable status. Owning boundary: kernel conformance surface. Findings: `cairn-20`.
- **`revocation-authz-consistency`.** Optional lifecycle configuration removes actor or dual-control checks. Close it with one invariant revocation policy across modes. Owning boundary: gate-engine. Findings: `dossier-13`.
- **`config-permission-completeness`.** Security config checks omit group write permissions. Close it by enforcing owner/group/world policy on the opened independently pinned configuration. Owning boundary: bootstrap-root under `INV-036`; dossier consumes verified configuration. Findings: `dossier-14`.
- **`typed-gate-result-and-exit-semantics`.** Truthy strings, ignored child status, warnings, or opt-in flags turn failure into exit 0. Close it with strict result types and unconditional nonzero blocked/unhealthy exits. Owning boundary: bootstrap-root for both suite CLI findings (`as-3`, `as-16`) and broker for capability health (`acb-6`). Findings: `as-3`, `as-16`, `acb-6`.
- **`artifact-revision-required`.** Missing revision provenance skips revision pinning. Close it by requiring immutable revision plus digest or failing verification. Owning boundary: bootstrap-root. Findings: `as-7`.
- **`dependency-validation-failure-deny`.** A failed lineage/dependency lookup is interpreted as validation success. Close it with explicit unavailable/invalid states that deny admission. Owning boundary: gate-engine. Findings: `an-2`.
- **`unsigned-operation-rejection`.** Null-signed operations satisfy lifecycle policy. Close it by removing NullSigner and requiring authenticated governance events. Owning boundary: app:agent-notes at command ingress and gate-engine for admission. Findings: `an-6`.
- **`authority-plane-binding`.** Caller environment substitutes another Vault authorization plane. Close it by deriving the plane from authenticated capability policy and scrubbing overrides. Owning boundary: broker. Findings: `acb-3`.
- **`audit-surface-completeness`.** Doctor/audit ignores classes of grants. Close it with an exhaustive provider registry and default failure for unknown surfaces. Owning boundary: broker. Findings: `acb-4`.
- **`execution-environment-confinement`.** Loader/interpreter environment bypasses executable authorization. Close it with an allowlisted reconstructed environment and OS-level confinement. Owning boundary: broker. Findings: `acb-8`.

### Cryptography, injection, and disclosure

- **`algorithm-key-type-binding`.** Attacker-selected HMAC consumes public-key bytes as a symmetric secret. Close it by binding algorithm, envelope version, and key type in policy. Owning boundary: kernel migration verifier. Findings: `crypto-1`.
- **`secret-reference-strict-parsing`.** Malformed secret references fall through to predictable key bytes. Close it with a closed parser and fatal unknown/malformed schemes. Owning boundary: kernel. Findings: `crypto-5`.
- **`private-key-material-non-disclosure`.** Private key material or decryptable blobs appear in argv/output. Close it with handle/reference-based secret transfer and redacted diagnostics. Owning boundary: kernel signing edge and bootstrap-root. Findings: `crypto-4`, `as-5`.
- **`outbound-destination-policy`.** Attacker-controlled URLs permit SSRF and response exfiltration. Close it with scheme/host/IP policy, redirect/rebinding checks, and bounded responses. Owning boundary: kernel service edge and app:agent-notes transport client. Findings: `cli-4`, `an-13`.
- **`structured-config-safe-serialization`.** Hand-quoted TOML permits table injection. Close it with a conforming serializer and schema validation. Owning boundary: broker. Findings: `acb-10`.
- **`generated-shim-input-validation`.** Unescaped identifiers inject generated shims. Close it with strict identifiers or context-correct encoding. Owning boundary: broker. Findings: `acb-11`.
- **`html-output-encoding`.** Untrusted artifact metadata is inserted into HTML without contextual escaping. Close it with safe templates and browser regression tests. Owning boundary: app:cairn for the current portal. `ASSUMPTION:` A later consolidation may transfer rendering to dossier, but 0A does not transfer this live defect. Findings: `cairn-18`.

### Resource and parser controls

- **`preallocation-parser-limits`.** Published artifacts are read/parsed before byte, count, or depth limits. Close it with streaming enforcement before allocation and parser fuzzing. Owning boundary: kernel. Findings: `SEC-12`, `crypto-6`, `cli-8`, `cairn-21`.
- **`read-to-eof-path-denial`.** Artifact-supplied paths read arbitrary files/devices/FIFOs to EOF. Close it by prohibiting ambient path dereference or using bounded, rooted, descriptor-safe reads. Owning boundary: kernel. Findings: `cairn-14`.
- **`query-and-batch-budget`.** Unbounded limits, fetches, or signing batches exhaust resources. Close it with hard pagination/work budgets. Owning boundary: kernel service edge. Findings: `cli-5`.
- **`malformed-input-contained-error`.** Malformed wrappers or auxiliary sections crash verification. Close it with total parsing into bounded invalid-artifact results. Owning boundary: kernel. Findings: `crypto-7`, `cairn-22`.
- **`application-request-work-budget`.** Request bodies or replay pages have no application work budget. Close it with body, time, row, and replay limits. Owning boundary: app:dossier. Findings: `dossier-7`.
- **`rate-limit-before-body-buffering`.** Bodies are buffered before rate limiting. Close it with streaming caps and pre-body admission. Owning boundary: transport. Findings: `aw-12`.
- **`handshake-timeout-and-preauth-quota`.** Pending handshakes evade connection limits. Close it with deadlines and pre-auth quotas. Owning boundary: transport. Findings: `aw-10`.
- **`security-domain-rate-partition`.** Unrelated local principals share one exhaustible rate bucket. Close it with authenticated-principal partitioning plus global safeguards. Owning boundary: transport. Findings: `aw-11`.
- **`multi-axis-login-throttling`.** Login throttling keys only on claimed identifier. Close it with source, account, and global budgets. Owning boundary: app:dossier. Findings: `dossier-15`.
- **`numeric-input-range-validation`.** Hostile numeric values overflow a shared database cast. Close it with boundary validation and contained per-request failure. Owning boundary: app:dossier. Findings: `dossier-8`.

### Completeness, races, migration, and hardening

- **`complete-export-or-explicit-partial`.** A truncated export is emitted and hashed as complete. Close it by completing the export or signing an explicit range/partial status. Owning boundary: kernel. Findings: `cairn-09`.
- **`authoritative-scan-not-window-truncated`.** Latest-N scans can be flood-evicted to bypass validators. Close it with checkpointed complete relevant history and explicit cut semantics. Owning boundary: gate-engine. Findings: `an-11`.
- **`version-aware-chain-hash`.** Cross-bundle links use the wrong version's hash construction. Close it with protocol-version dispatch and downgrade/differential tests. Owning boundary: kernel. Findings: `cairn-17`.
- **`transcript-coverage-binding`.** An attestation digest covers one hook payload rather than the intended transcript. Close it by defining and hashing the complete canonical subject. Owning boundary: kernel. Findings: `cairn-19`.
- **`readiness-blocker-semantics`.** Readiness omits blocker states and link mutation lacks authorization. Close it with versioned blocker policy and authorized link commands. Owning boundary: gate-engine. Findings: `an-12`.
- **`locked-state-revalidation-at-commit`.** Commit uses cached approval after locking a cancelled row. Close it by rereading locked state and conditionally committing. Owning boundary: kernel temporal state machine. Findings: `SEC-09`, `persist-5`.
- **`lifecycle-transition-cas`.** Stale lifecycle writers resurrect or overwrite newer state. Close it with expected-state predicates/row locks and monotonic transitions. Owning boundary: kernel temporal state machine. Findings: `persist-6`, `persist-10`.
- **`atomic-exclusive-file-creation`.** Check-then-write races permit symlink replacement. Close it with `O_EXCL`/`O_NOFOLLOW`, safe parents, and atomic replacement. Owning boundary: kernel CLI edge and broker. Findings: `cli-9`, `acb-14`.
- **`descriptor-bound-containment`.** A pathname is validated and later reopened after substitution. Close it by validating and consuming one opened descriptor. Owning boundary: gate-engine CLI edge. Findings: `cli-10`.
- **`immutable-ref-through-execution`.** A base ref changes between validation and privileged execution. Close it by resolving and retaining an immutable commit object. Owning boundary: bootstrap-root. Findings: `as-15`.
- **`socket-path-anti-hijack`.** An untrusted parent permits local socket rebinding. Close it with parent owner/mode validation and safe bind/reconnect behavior. Owning boundary: transport. Findings: `aw-8`.
- **`policy-check-and-issuance-binding`.** Vault policy checks race SecretID issuance. Close it with transactional binding or immediate revalidation at issuance. Owning boundary: broker. Findings: `acb-13`.
- **`transaction-savepoint-recovery`.** Recovery queries run inside an aborted transaction. Close it with savepoint rollback before idempotency recovery. Owning boundary: kernel persistence. Findings: `persist-14`.
- **`concurrent-idempotent-insert`.** Check-then-insert races turn idempotent registration into DoS. Close it with uniqueness and atomic upsert/conflict handling. Owning boundary: gate-engine. Findings: `persist-15`.
- **`nonempty-evidence-drop-guard`.** A migration silently drops a nonempty evidence table. Close it by refusing destructive migration without verified transfer and explicit ceremony. Owning boundary: kernel migration. Findings: `persist-11`.
- **`migration-chain-continuity`.** Upgrade starts a new chain at NULL and leaves prior history unauthenticated. Close it with an authenticated migration-boundary checkpoint linking both histories. Owning boundary: kernel migration. Findings: `persist-12`.
- **`schema-qualified-migration-introspection`.** Cross-schema objects interfere with migration probes. Close it with schema-qualified introspection and least-privilege migration identity. Owning boundary: kernel persistence. Findings: `persist-16`.
- **`health-data-minimization`.** Public health output exposes internal topology and identities. Close it with coarse public status and authenticated diagnostics. Owning boundary: app:dossier. Findings: `dossier-6`.
- **`anti-clickjacking-policy`.** State-changing UI can be framed. Close it with CSP `frame-ancestors` or equivalent and UI tests. Owning boundary: app:dossier. Findings: `dossier-10`.
- **`canonical-identity-mapping`.** Lifecycle actions use inconsistent principal identifiers. Close it with one canonical identifier and explicit mapping validation. Owning boundary: app:dossier. Findings: `dossier-11`.
- **`collision-resistant-identity-filenames`.** Lossy filename normalization aliases principals. Close it with injective encoding or digest-based names. Owning boundary: app:dossier. Findings: `dossier-16`.
- **`browser-security-header-baseline`.** The web surface lacks coherent CSP/HSTS/referrer/MIME/framing policy. Close it with a tested response-header baseline. Owning boundary: app:dossier. Findings: `dossier-17`.
- **`backup-mode-preservation`.** Backups of secret-bearing config inherit unsafe modes. Close it by preserving or tightening source permissions atomically. Owning boundary: broker. Findings: `acb-15`.
- **`authenticated-provenance-attribution`.** Environment variables redirect and forge unsigned provenance. Close it with signed broker events and policy-derived identity/state location. Owning boundary: broker. Findings: `acb-16`.

## Reproduction set

The executor hand-off is `REPRODUCTIONS.md`. It is derived from this taxonomy and the selection semantics above at the frozen pre-selection digest `sha256:5918f63a261ebdca466df0a5f7e97d2ac73455b4eb6c5f1b6a6ef0eb309b0651`; this v0.2 revision changes ownership and moves `persist-9` within the INV-005 family but does not alter the verified 78-finding selection. The union remains all seven effective Criticals plus dominant/second-component selections for 59 High-bearing mechanisms.

`ASSUMPTION:` The digest records evidentiary ordering because taxonomy and selection were not separated into commits. No probe execution or verdict is claimed here.

## Suspected mechanisms

The inventory marks the following findings "suspected, needs reproduction"; therefore their mechanisms remain suspected to the extent indicated:

- `unique-chain-head-binding`: `persist-9`
- `imported-state-authenticity`: `an-15`
- `signed-project-actor-context`: `an-9`
- `replay-freshness-binding`: `aw-13`
- `dedupe-security-domain-binding`: `aw-14`
- `genesis-proof-consumed-by-first-write`: `persist-13`, `as-13`
- `private-key-material-non-disclosure`: `crypto-4`
- `descriptor-bound-containment`: `cli-10`
- `lifecycle-transition-cas`: `persist-6`, `persist-10`
- `migration-chain-continuity`: `persist-12`
- `transaction-savepoint-recovery`: `persist-14`
- `concurrent-idempotent-insert`: `persist-15`
- `preallocation-parser-limits`: `cairn-21`
- `application-request-work-budget`: `dossier-7`
- `anti-clickjacking-policy`: `dossier-10`
- `collision-resistant-identity-filenames`: `dossier-16`
- `immutable-ref-through-execution`: `as-15`
- `authoritative-scan-not-window-truncated`: `an-11`
- `socket-path-anti-hijack`: `aw-8`
- `rate-limit-before-body-buffering`: `aw-12`
- `generated-shim-input-validation`: `acb-11`
- `policy-check-and-issuance-binding`: `acb-13`
- `atomic-exclusive-file-creation`: `acb-14`
