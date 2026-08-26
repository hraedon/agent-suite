# Plan 025 mechanism taxonomy

Status: DRAFT. This taxonomy partitions the 147 filed findings by failed security mechanism. C1-C5 remain triage classes, not mechanisms. A finding has exactly one primary mechanism even when it has secondary effects.

## Selection semantics

- Effective severity for selection is `verified_severity` when present and Daybreak severity otherwise, ordered `Critical > High > Medium-High > Medium > Low-Medium > Low`. Thus SEC-01 is High, not Critical.
- Component counts use the inventory's ten report-level component names. `ASSUMPTION:` for a count tie, choose the component containing the highest-effective-severity finding, then a verified finding, then the component order `trustlog, crypto, regista-cli, persist, cairn, dossier, agent-suite, agent-notes, agent-wake, acb`; choose a finding within a component by the same severity/verification rules and then lexical finding id.
- `ASSUMPTION:` "a second component" means a different logical product where possible. The four Regista reports are one logical product for diversity, even though they remain distinct component values for counting and traceability.
- A mandatory Critical may also satisfy the dominant-component or second-component obligation for its mechanism. Suspected findings remain in counts.
- `OPEN:` The owner should confirm the tie-break and report-component counting rules before probes are commissioned; changing either rule requires recomputing the reproduction set.

## Mechanisms

Each entry gives the stable slug, definition and closing control shape, owning boundary under the target decomposition, and its complete finding membership.

### Authenticated authority and evidence

- **`row-envelope-reconciliation`.** Mutable rows or projections are treated as signed authority. Close it by authenticating the envelope, recomputing stored digests, and reconciling every decision-bearing field at each authoritative read. Owning boundary: kernel for evidence reads and gate-engine for admission reads; dossier/agent-notes must consume claims rather than rows. Findings: `SEC-11`, `persist-2`, `persist-4`, `persist-9`, `dossier-2`, `dossier-4`, `an-8`.
- **`canonical-subject-reconciliation`.** Caller or child-record subject fields override canonical identity or lifecycle state. Close it by deriving kind, principal, project, and status from authenticated canonical records. Owning boundary: kernel for principal claims; bootstrap-root for provisioning. Findings: `SEC-08`, `as-9`.
- **`queued-row-ingress-authenticity`.** A durable queue row can bypass authenticated ingress. Close it by MAC/signature-verifying queued content and its routing context before dispatch. Owning boundary: transport. Findings: `aw-7`.
- **`signed-policy-as-authority`.** Enforcement uses mutable policy state rather than the signed registration. Close it by verifying the policy object and binding every decision to its digest/version. Owning boundary: gate-engine. Findings: `persist-1`.
- **`signature-before-admission`.** Unsigned events affect workflow admission or precedence. Close it by authenticating the event and its chain position before any authority use. Owning boundary: gate-engine with kernel claim input. Findings: `persist-8`.
- **`imported-state-authenticity`.** Imported lifecycle state affects local authority without provenance checks. Close it with authenticated import, lineage/lifecycle validation, and legacy quarantine. Owning boundary: kernel at migration ingestion; agent-notes only projects admitted events. Findings: `an-7`, `an-15`.
- **`verifier-suppression-input-authenticity`.** Unverified evidence suppresses a real integrity violation. Close it by allowing only authenticated, policy-admissible evidence to suppress findings. Owning boundary: kernel. Findings: `cairn-05`.
- **`expected-witness-roster-pinning`.** The submitted artifact chooses the witnesses against which it is judged. Close it by pinning the expected roster and threshold in trusted policy. Owning boundary: kernel. Findings: `cairn-06`.
- **`externally-anchored-root-required`.** Missing or self-selected roots satisfy verification. Close it by requiring a policy-pinned, independently witnessed checkpoint and explicit failure on absence. Owning boundary: kernel. Findings: `cairn-08`.
- **`checked-evidence-required-for-pass`.** Unchecked or indeterminate evidence contributes to PASS. Close it with a typed aggregate in which every required result is positively verified. Owning boundary: kernel. Findings: `cairn-16`.
- **`event-pairing-completeness`.** An orphan end event is displayed as a completed execution. Close it by proving required begin/end structure before issuing or rendering completion. Owning boundary: app:dossier, consuming a kernel claim. Findings: `dossier-1`.
- **`artifact-trust-root-authenticity`.** Self-hashes or caller-supplied manifests are mistaken for trusted baselines. Close it with a signed subject-to-digest binding rooted in pinned policy and owner checks. Owning boundary: bootstrap-root for suite artifacts and broker for capability manifests. Findings: `as-2`, `as-4`, `acb-1`.
- **`release-content-pinning`.** Package or registry content is installed without a cryptographic release binding. Close it by resolving immutable content digests from signed release metadata. Owning boundary: bootstrap-root for suite packages and broker for capability packages. Findings: `as-8`, `acb-9`.
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
- **`canonical-actor-recording`.** The resolved actor is discarded and raw unresolved caller input is recorded. Close it by recording the authenticated canonical actor only. Owning boundary: kernel claim production. Findings: `an-5`.
- **`signed-project-actor-context`.** Outbox signatures omit project, actor, kind, role, or lineage. Close it by signing the complete typed dispatch context. Owning boundary: app:agent-notes. Findings: `an-9`.
- **`transport-identity-source-binding`.** Trigger/source/reply identity is outside the MAC or authenticated connection. Close it by MAC-binding identity and source and correlating replies to the authenticated delivery. Owning boundary: transport. Findings: `aw-1`, `aw-3`, `aw-6`.
- **`replay-freshness-binding`.** Timestamp, nonce, event/reply id, or idempotency key is unsigned or not consumed. Close it by signing all freshness fields and atomically recording nonce use. Owning boundary: transport. Findings: `aw-2`, `aw-13`.
- **`dedupe-security-domain-binding`.** Deduplication is global rather than scoped to authenticated source. Close it by keying dedupe on source/security domain plus event id. Owning boundary: transport. Findings: `aw-14`.

### Authentication, authorization, and gates

- **`genesis-proof-consumed-by-first-write`.** A genesis boolean/verdict is not authenticated and atomically consumed by the first write. Close it with a scoped gate decision bound to that action. Owning boundary: gate-engine. Findings: `SEC-05`, `as-13`.
- **`authenticated-approval-and-sod`.** Caller strings or permissive defaults stand in for authenticated approval and separation of duties. Close it with authenticated roles, explicit policy, distinct principals, and default DENY. Owning boundary: gate-engine. Findings: `SEC-10`, `persist-7`, `as-12`, `an-1`.
- **`operator-action-authorization`.** An operator-only action has no operator authorization boundary. Close it by authenticating the caller and evaluating operator policy. Owning boundary: gate-engine. Findings: `an-10`.
- **`scope-entitlement-enforcement`.** Declared workflow or harness scope is not enforced at use. Close it by checking the authenticated caller against the exact requested scope on every route/execution. Owning boundary: gate-engine for workflows and broker for harnesses. Findings: `cli-1`, `acb-2`.
- **`privileged-mutation-authorization`.** Ordinary callers can perform administrative mutation or mint project-authoritative artifacts. Close it with authenticated project-admin policy and attributable signing. Owning boundary: gate-engine. Findings: `cli-2`, `an-3`.
- **`stored-secret-access-control`.** Ordinary bearer tokens can retrieve stored delivery credentials. Close it with least-privilege secret-reference use and non-disclosure APIs. Owning boundary: kernel-side service edge. Findings: `cli-3`.
- **`lease-scope-and-expiry`.** A caller leases unauthorized work or holds it indefinitely. Close it with pre-reservation scope checks and bounded leases. Owning boundary: gate-engine. Findings: `cli-6`.
- **`verification-head-completeness`.** A truncated prefix is reported as fully valid without an expected head. Close it with a pinned cut/head or an explicit partial-verification result. Owning boundary: kernel. Findings: `cli-7`.
- **`network-endpoint-authentication`.** Sensitive records or diagnostics are exposed when authentication configuration is absent. Close it with authentication and least disclosure by default. Owning boundary: kernel service edge for regista and app:agent-notes for its viewer. Findings: `cli-11`, `an-14`.
- **`local-peer-authentication`.** A local socket peer self-asserts routing identity. Close it by binding OS peer credentials to authorized adapter/destination identity. Owning boundary: transport. Findings: `aw-5`.
- **`missing-bootstrap-identity-deny`.** Missing project identity grants a write window. Close it by making absent bootstrap identity deny all ordinary inserts. Owning boundary: gate-engine. Findings: `persist-13`.
- **`filtered-verification-preserves-global-failures`.** Filtering deletes global integrity failures. Close it by separating presentation filtering from full-chain verdict computation. Owning boundary: kernel. Findings: `cairn-01`.
- **`aggregate-verdict-completeness`.** PASS omits unverified counts, halted replay, warnings, or inconsistent totals. Close it with exhaustive typed aggregation requiring all expected checks. Owning boundary: kernel for claims; dossier renders that claim. Findings: `cairn-02`, `dossier-3`.
- **`authenticated-coverage-receipt`.** Signatureless or un-MACed coverage evidence counts as verified. Close it by rejecting absent/invalid authenticators and legacy downgrade. Owning boundary: kernel. Findings: `cairn-07`, `cairn-12`.
- **`transition-role-default-deny`.** Unknown roles, workflow-version drift, or shortcut transitions satisfy a gate. Close it with versioned transition policy and exhaustive default DENY. Owning boundary: gate-engine. Findings: `cairn-15`, `as-14`, `an-4`.
- **`probe-evidence-not-fixture-pass`.** Synthetic fixtures yield a gating PASS without inspecting the installation. Close it with environment-bound probe evidence and explicit unavailable status. Owning boundary: kernel conformance surface. Findings: `cairn-20`.
- **`revocation-authz-consistency`.** Optional lifecycle configuration removes actor or dual-control checks. Close it with one invariant revocation policy across modes. Owning boundary: gate-engine. Findings: `dossier-13`.
- **`config-permission-completeness`.** Security config checks omit group write permissions. Close it by enforcing owner/group/world policy on the opened file. Owning boundary: app:dossier. Findings: `dossier-14`.
- **`typed-gate-result-and-exit-semantics`.** Truthy strings, ignored child status, warnings, or opt-in flags turn failure into exit 0. Close it with strict result types and unconditional nonzero blocked/unhealthy exits. Owning boundary: bootstrap-root for suite and broker for capability health. Findings: `as-3`, `as-16`, `acb-6`.
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
- **`html-output-encoding`.** Untrusted artifact metadata is inserted into HTML without contextual escaping. Close it with safe templates and browser regression tests. Owning boundary: app:dossier. Findings: `cairn-18`.

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

`ASSUMPTION:` This set applies the selection semantics above to this taxonomy. It is a probe plan only; no probe was run or written here. The reviewed refs are `7707c81` for Regista-family components, `74471ad` cairn, `d775b6d` dossier, `a153213` agent-suite, `235c2b6` agent-notes, `f6a0eed` agent-wake, and `f2df972` acb.

The union contains 78 findings: all seven effective Criticals and the dominant/second-component selections for 59 High-bearing mechanisms. Some rule-selected examples are below High because the charter chooses within the most-populated component and requires a second component; effective severity does not override those placement rules.

| Finding | Component | Reviewed ref | Selection basis and one-line probe sketch |
|---|---|---|---|
| `persist-1` | persist | `7707c81` | Critical + representative: mutate registry policy without changing its signed registration and demonstrate an otherwise admitted transition follows the mutation. |
| `persist-2` | persist | `7707c81` | Critical + representative: alter row-only review fields and demonstrate a gate accepts evidence whose signed envelope says something else. |
| `persist-4` | persist | `7707c81` | Critical: alter a durable approved lifecycle row without recomputing its digest and demonstrate rehydration emits authority for the substituted subject. |
| `persist-5` | persist | `7707c81` | Critical + representative: race cancellation against commit and demonstrate cached APPROVED state commits after the locked row is cancelled. |
| `cairn-01` | cairn | `74471ad` | Critical + representative: delete an in-window event and demonstrate filtered verification suppresses the resulting global-chain violation. |
| `cairn-02` | cairn | `74471ad` | Critical + representative: supply signature-valid but referent-missing events and demonstrate merged verification returns PASS while omitting unverified counts. |
| `acb-1` | acb | `f2df972` | Critical + second component: replace the unsigned capability manifest and demonstrate an attacker-selected executable receives an attacker-selected secret reference. |
| `SEC-08` | trustlog | `7707c81` | Second component: register a conflicting payload principal kind and demonstrate replay/claims use it instead of canonical enrollment. |
| `persist-8` | persist | `7707c81` | Representative: submit an unsigned workflow registration and demonstrate it influences admission or precedence. |
| `cairn-05` | cairn | `74471ad` | Representative: place unverified out-of-window attestations and demonstrate they suppress a genuine gap finding. |
| `cairn-06` | cairn | `74471ad` | Representative: choose an attacker-controlled witness roster and demonstrate verification reports sufficient coverage against it. |
| `cairn-08` | cairn | `74471ad` | Representative: omit an externally pinned bundle/chain root and demonstrate `all_ok` still succeeds. |
| `dossier-1` | dossier | `d775b6d` | Representative: provide an orphan tool-call end and demonstrate dossier renders a completed chain-verified execution. |
| `dossier-2` | dossier | `d775b6d` | Second component: flip mutable actor/transition columns and demonstrate a human-accepted or independent-review badge without matching signed evidence. |
| `as-1` | agent-suite | `a153213` | Second component: place a forged component earlier on PATH and demonstrate genesis executes it as a required probe. |
| `as-2` | agent-suite | `a153213` | Representative: create an unsigned lock baseline and demonstrate doctor/deploy accepts or creates it as trusted. |
| `as-6` | agent-suite | `a153213` | Representative: return forged replay JSON from a failing subprocess and demonstrate restore verification accepts it. |
| `as-8` | agent-suite | `a153213` | Representative: substitute same-version package content and demonstrate upgrade/rollback installs it without digest rejection. |
| `as-9` | agent-suite | `a153213` | Representative: substitute principal/project fields in child provisioning records and demonstrate provisioning or offboarding acts on them. |
| `an-7` | agent-notes | `235c2b6` | Representative: import unsigned cross-project lifecycle state and demonstrate it becomes local governance state. |
| `aw-7` | agent-wake | `f6a0eed` | Representative: insert a forged pending DB row directly and demonstrate dispatch bypasses HTTP authentication and ingress checks. |
| `acb-5` | acb | `f2df972` | Representative: supply an attacker executable whose text/path contains `playwright` and demonstrate reverse-surface qualification blesses it. |
| `acb-9` | acb | `f2df972` | Second component: alter registry-resolved package content at the accepted name/version and demonstrate reconciliation executes it without a content pin. |
| `SEC-01` | trustlog | `7707c81` | Representative: use a revoked/superseded issuer key to mint a new delegation and demonstrate current-status resolution is bypassed. |
| `SEC-03` | trustlog | `7707c81` | Representative: verify an expired status-active key online and offline and demonstrate only the offline path accepts it. |
| `SEC-06` | trustlog | `7707c81` | Second component: invoke the library legacy catalog path with a removed root and demonstrate it accepts evidence the CLI refuses. |
| `crypto-2` | crypto | `7707c81` | Second component: resolve a retired legacy key through `KeySetResolver` and demonstrate newly forged history authenticates. |
| `cairn-10` | cairn | `74471ad` | Representative: forge a new v1-v4 event with a retired key and demonstrate default legacy verification accepts it as historical. |
| `cairn-11` | cairn | `74471ad` | Representative: use equivalent offset timestamps whose lexical order differs and demonstrate a post-revocation event bypasses the check. |
| `cairn-13` | cairn | `74471ad` | Representative: forge the integrity marker with the retired first key in a key file and demonstrate doctor reports green. |
| `aw-4` | agent-wake | `f6a0eed` | Representative: remove the active key while the daemon runs and demonstrate requests signed with it remain accepted before restart. |
| `aw-9` | agent-wake | `f6a0eed` | Representative: rotate keys and demonstrate the previous key remains fully authoritative beyond any declared overlap. |
| `acb-12` | acb | `f2df972` | Representative: force best-effort SecretID revocation to fail and demonstrate rotation reports success while the old credential still authenticates. |
| `SEC-02` | trustlog | `7707c81` | Representative: replay stored root signatures at a new event id/sequence and demonstrate threshold governance accepts the transplant. |
| `SEC-04` | trustlog | `7707c81` | Representative: insert a backdated event with a registrar key and demonstrate caller time revives expired authority. |
| `crypto-3` | crypto | `7707c81` | Representative: feed a cross-protocol framed message to the rotation client and demonstrate it returns a usable Ed25519 signature. |
| `persist-3` | persist | `7707c81` | Representative: collide entity ids across kinds and demonstrate a per-item read includes another kind's event. |
| `cairn-03` | cairn | `74471ad` | Second component: submit a retroactive/cross-session attestation and demonstrate payload time expands its coverage beyond authenticated position. |
| `cairn-04` | cairn | `74471ad` | Representative: substitute session/principal subject fields and demonstrate a valid signature attests the wrong entity or actor. |
| `dossier-5` | dossier | `d775b6d` | Representative: sign an `on_behalf_of` claim as an unauthorized principal and demonstrate dossier treats it as delegated attribution. |
| `dossier-9` | dossier | `d775b6d` | Second component: use a non-note UUID and demonstrate it renders as a verified knowledge note. |
| `an-5` | agent-notes | `235c2b6` | Representative: omit/spoof actor input and demonstrate the event records raw `null`/spoofed identity rather than resolved actor. |
| `an-9` | agent-notes | `235c2b6` | Representative: alter project/actor metadata outside the outbox signature and demonstrate reconciliation accepts the relabeled operation. |
| `aw-1` | agent-wake | `f6a0eed` | Representative: alter `X-AgentWake-Identity` while retaining a valid body MAC and demonstrate forged trigger identity is stamped. |
| `aw-2` | agent-wake | `f6a0eed` | Representative: replay a captured body with unsigned event id/freshness metadata and demonstrate a second accepted wake. |
| `SEC-05` | trustlog | `7707c81` | Representative: call public genesis initialization with a completed envelope and bare true gate flag and demonstrate epoch creation. |
| `cli-1` | regista-cli | `7707c81` | Representative: use a token outside its allowed workflow on a non-hook route and demonstrate the request succeeds. |
| `cli-2` | regista-cli | `7707c81` | Representative: use a non-admin token to register malicious workflow content and demonstrate it is signed as project identity. |
| `cli-3` | regista-cli | `7707c81` | Representative: query witness/webhook configuration with an ordinary bearer and demonstrate stored authorization credentials are returned. |
| `persist-7` | persist | `7707c81` | Representative: omit an approval verifier or supply forged approver evidence and demonstrate separation-of-duties admission. |
| `cairn-07` | cairn | `74471ad` | Representative: submit a signatureless HMAC receipt and demonstrate it counts toward witness coverage. |
| `cairn-15` | cairn | `74471ad` | Representative: use operator/unknown role on an actor-only transition and demonstrate the role gate passes. |
| `dossier-3` | dossier | `d775b6d` | Second component: provide replay output with halted events/warnings and demonstrate dossier labels the chain intact. |
| `as-3` | agent-suite | `a153213` | Representative: return string `false` and a contradictory failing exit status and demonstrate doctor reports healthy. |
| `as-7` | agent-suite | `a153213` | Representative: provide same-version wheel provenance without revision and demonstrate lock verification skips the revision pin. |
| `as-13` | agent-suite | `a153213` | Second component: produce a genesis verdict then perform first write without presenting it and demonstrate admission succeeds. |
| `an-1` | agent-notes | `235c2b6` | Second component: self-review with caller-selected actor and acknowledgment flag and demonstrate completion without operator authority. |
| `an-2` | agent-notes | `235c2b6` | Representative: exercise the pinned registry lookup failure and demonstrate missing lineage validation is treated as success. |
| `an-3` | agent-notes | `235c2b6` | Second component: invoke native force/admin switches as an ordinary caller and demonstrate privileged mutation succeeds. |
| `an-4` | agent-notes | `235c2b6` | Second component: use open-to-done shortcut and demonstrate normal completion gates are bypassed. |
| `an-6` | agent-notes | `235c2b6` | Representative: create a NullSigner operation and demonstrate verifier accepts `keyid:null` under lifecycle policy. |
| `aw-5` | agent-wake | `f6a0eed` | Representative: connect as same-UID rogue peer claiming an adapter/destination and demonstrate wake hijack. |
| `acb-2` | acb | `f2df972` | Second component: check out a capability from a harness absent from `cap.harnesses` and demonstrate secret release. |
| `acb-3` | acb | `f2df972` | Representative: override `ACB_VAULT_ENV` and demonstrate one capability accesses another authorization plane. |
| `acb-4` | acb | `f2df972` | Representative: install a rogue non-Playwright MCP grant and demonstrate doctor remains green. |
| `acb-6` | acb | `f2df972` | Second component: create a detected rogue capability and demonstrate doctor returns `ok=True`/exit 0. |
| `acb-8` | acb | `f2df972` | Representative: inject `LD_PRELOAD` or equivalent while preserving trusted argv and demonstrate attacker code runs before the target. |
| `SEC-09` | trustlog | `7707c81` | Second component: use two process caches to cancel then commit and demonstrate locked durable state is ignored. |
| `crypto-1` | crypto | `7707c81` | Representative: label a v5 event HMAC-SHA256 using known Ed25519 public bytes and demonstrate full authentication without a private key. |
| `crypto-4` | crypto | `7707c81` | Representative: invoke Windows public-identity flow and demonstrate a machine-scope decryptable private-key blob reaches argv/output. |
| `persist-6` | persist | `7707c81` | Representative: race possession/approval against cancellation and demonstrate a stale transition resurrects the operation. |
| `persist-11` | persist | `7707c81` | Representative: run migration 027 with a nonempty archive and demonstrate it drops audit evidence without refusal. |
| `persist-12` | persist | `7707c81` | Representative: upgrade existing history and demonstrate deletion of pre-upgrade events does not break the new suffix chain. |
| `cairn-09` | cairn | `74471ad` | Representative: export more than 10,000 events and demonstrate a truncated bundle is hashed/labeled complete. |
| `cairn-14` | cairn | `74471ad` | Representative: place `/dev/zero` or a FIFO in artifact file paths and demonstrate verifier reads indefinitely. |
| `as-5` | agent-suite | `a153213` | Second component: provision with inline private-key reference and demonstrate secret material appears in argv or diagnostics. |
| `aw-8` | agent-wake | `f6a0eed` | Representative: use an attacker-controlled socket parent/rebind and demonstrate clients connect to a fake server. |
| `acb-10` | acb | `f2df972` | Representative: register a quote/new-table payload and demonstrate generated TOML grants a forged capability. |

## Suspected mechanisms

The inventory marks the following findings "suspected, needs reproduction"; therefore their mechanisms remain suspected to the extent indicated:

- `row-envelope-reconciliation`: `persist-9`
- `imported-state-authenticity`: `an-15`
- `signed-project-actor-context`: `an-9`
- `replay-freshness-binding`: `aw-13`
- `dedupe-security-domain-binding`: `aw-14`
- `missing-bootstrap-identity-deny`: `persist-13`
- `genesis-proof-consumed-by-first-write`: `as-13`
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
