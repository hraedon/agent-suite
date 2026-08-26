# Phase 0B substrate and anchor bake-off plan

Status: kickoff plan. Phase 0A has exited and `plans/025-0a/BAKEOFF-RUBRIC.md` is frozen. This plan operationalises that rubric; it does not change a predicate, weight, workload, scale, or candidate.

Normative inputs:

- `plans/025-0a/EXIT-0A.md`
- `plans/025-0a/BAKEOFF-RUBRIC.md`
- `plans/025-0a/DECISIONS-0A.md`, especially D-0A-4, D-0A-5, D-0A-9, and D-0A-11
- `plans/025-0a/TRUST-MODEL.md` sections 6, 8, and 9
- `plans/025-provenance-security-remediation.md` sections 5, 6, and 8
- `plans/025-0a/MATRIX.csv`

Frozen-rubric identification at plan drafting:

| Field | Value |
|---|---|
| Repository revision | `f4d3f63e92a8176bd1b8e778a5d2d4eec8429935` |
| Rubric path | `plans/025-0a/BAKEOFF-RUBRIC.md` |
| Rubric SHA-256 | `45a5d9c9a698dc21e0c8548288e19d892bf34d44e2982ebf47d49afd5bde8985` |
| Frozen by | `plans/025-0a/EXIT-0A.md`, declared 2026-08-26 00:00 MST |

The executor lineage is openai/gpt-5.6-sol. Review is assigned to Fable, Opus, and minimax as independent review lineages. This plan assigns no actor id, records no gate transition, and authorizes no scored measurement until the pre-flight checklist in section 6 is complete.

## 1. Host and witness allocation

### 1.1 Candidate placement

Run all three candidates in parallel, one writer/database candidate per host, as required by D-0A-9.

| Candidate | Writer/database host | Candidate boundary | Witness 1 | Witness 2 |
|---|---|---|---|---|
| A | `mvmcc03` | PostgreSQL projection plus signed append-only log and witnessed checkpoints | `mvmcc02` | `mvmcitest01` |
| B | `mvmcitest01` | SQL Server 2022 Ledger plus independently retained digest witnesses | `mvmcc03` | `mvmcc02` |
| C | `mvmcc02` | immudb in Docker plus independent witnesses and any required projection integration | `mvmcc03` | `mvmcitest01` |

`ASSUMPTION:` `mvmcc03` is Ubuntu with 6 vCPU, 16 GB RAM, PostgreSQL available, Docker 29, and Docker Compose; the repository documents only the 6-vCPU/16-GB contention concern and prior PostgreSQL use indirectly.

`ASSUMPTION:` `mvmcc02` is a second Ubuntu development host with 6 vCPU, 17 GB RAM, Docker support, and repositories under `/projects/`; the repository confirms prior 0A execution on this host but not all capacity and path details.

`ASSUMPTION:` `mvmcitest01` is the Windows lab host in `ad.hraedon.com`, can run SQL Server 2022 Developer edition, and is reachable from both Linux hosts. Repository files confirm it is a disposable Windows Server lab host used for Windows exercises, but do not establish the domain, SQL installation, capacity, or current reachability.

### 1.2 Independence matrix

Host separation alone does not pass `INV-016`. For each candidate, both witnesses must have distinct operators, signing keys and custody, admin accounts, hosts, and persistence planes, and neither may share the candidate writer/DBA admin realm or credentials. No single person, entity, directory administrator, secret-backend administrator, or platform administrator may be able to alter both quorum members.

| Candidate | Writer/DBA failure domain excluded | Witness location | Required distinct operator/admin realm | Required distinct custody and persistence |
|---|---|---|---|---|
| A | `mvmcc03`, PostgreSQL/log admins, writer credentials, writer backup plane | `mvmcc02` | A-W1 operator and admin account, not an A writer/DBA admin | A-W1-only key custody and retained-state plane |
| A | same | `mvmcitest01` | A-W2 operator and admin account, distinct from A-W1 and A writer/DBA admins | A-W2-only key custody and retained-state plane, not the A backup plane |
| B | `mvmcitest01`, SQL Server/Windows/cluster admins, DBA credentials, SQL backup and DBA management plane, directory/IdP administrator realm (`ADV-30`), secret-backend administrator (`ADV-31`)s | `mvmcc03` | B-W1 operator and Linux admin realm outside SQL/Windows/AD DBA control | B-W1-only key custody and retained digest plane |
| B | same | `mvmcc02` | B-W2 operator and admin account, distinct from B-W1 and all B DBA dependencies | B-W2-only key custody and retained digest plane, not the SQL backup plane |
| C | `mvmcc02`, immudb/container admins, writer credentials, candidate backup plane | `mvmcc03` | C-W1 operator and admin account, not a C writer/store admin | C-W1-only key custody and retained-state plane |
| C | same | `mvmcitest01` | C-W2 operator and admin account, distinct from C-W1 and C writer/store admins | C-W2-only key custody and retained-state plane, not the C backup plane |

Witness state for different candidates may share a physical host only when candidate-specific service identities, keys, storage, logs, and administration are separated. A fault injection against one candidate must not stop or mutate another candidate's witness. Resource telemetry must distinguish writer/database, verifier, and each witness.

`OPEN:` The owner must name the six witness operator assignments, their admin realms, key custodians, persistence owners, monitoring owners, and collusion assumptions. If the available people or management planes cannot satisfy the literal `INV-016` predicate, the affected candidate is security-disqualified; documenting three hostnames cannot cure that failure.

`OPEN:` Confirm that cross-host firewall, name resolution, authenticated transport, clock sources, and failure injection can isolate each candidate without disrupting the other two parallel runs.

## 2. Shared harness specification

The harness is a language-neutral specification, fixtures, orchestration manifest, and evidence contract. Candidate adapters may differ, but they must consume the same logical fixture and emit the same evidence-package and result-record forms. A candidate-specific adapter may translate the fixture into native calls; it may not weaken a denial case, omit a field, reinterpret a predicate, or supply a centralized verdict where local verification is required.

### 2.1 Common fixture

The pinned fixture manifest contains the following, each with a schema version, byte length, media type, SHA-256 digest, and deterministic generation description:

| Fixture part | Required content |
|---|---|
| Canonical events | Exact canonical bytes for valid appends; repeated event ids and nonces; predecessor mismatch; mutable-row mismatch; absent, unknown, retired, and wrong-domain authentication; malformed/unknown schema and algorithm cases; bounded oversized proof/parser cases; no free text or secret values. |
| Genesis and pins | Separately authenticated signed genesis policy, root digest, witness roster and quorum, independently acquired pin-channel record, predecessor/version chain, and a no-pin first-contact variant. |
| Authority history | Initial authority; ordinary grant/delegation; rotation with explicit bounded overlap; post-rotation use of the old key; historical verification before and after rotation; policy transition; authority cache invalidation points. |
| Revocation history | Authorized dual-control revocation issued at position `r`, effective from earlier position `e` through finite position `t`; before/inside/after-range events; cuts before and after `r`; malformed, unauthorized, timestamp-based, self-covering, and out-of-policy attempts. D-0A-3 applies: bootstrap-root operator plus security approver, unbounded lookback, finite `effect_through` allowed, and denial until policy is selected. |
| Checkpoint schedule | Fixed event-count and elapsed-time cadence, checkpoint identity and chain fields, witness quorum, retention policy, one withheld witness, one false observation, one stale observation, and a verifier-pinned pre-attack cut stored outside writer/DBA/witness failure domains. |
| Acknowledgement cases | One valid signed acknowledgement with submission digest, promised position, receipt id, policy and merge deadline followed by delayed merge; one submission for which acknowledgement is withheld entirely. |
| Proof cases | First, middle, and last inclusion proofs; consistency between retained cuts; tampered leaf/path/size/root/range count/filter/schema/proof bytes; partial and filtered evidence presented both honestly and falsely as complete. |
| Concurrency schedules | Deterministic barrier schedules and seeds for cancel/approve/commit, rotation/authorization, checkpoint publication, policy-check/credential issuance, and expected-state lifecycle updates; stale-cache and losing-writer variants. |
| Recovery cases | Old database plus old checkpoint rollback; clean-host backup restore; corrupted/deleted projection; anchor outage below and above the signed maximum; re-anchoring and permanent unanchored-range disclosure; premature-resume attempts. |
| Break-glass cases | Distinct approvers; one allowed action; prohibited action; same-set renewal; incident-id reset; cumulative 60-minute per-incident and 120-minute rolling-24-hour cross-incident overruns; expiry, reconciliation, closure, and ordinary-operation attempts before and after closure. |
| Adversary scripts | Exact injections for every rubric section 5 scenario, compromised zones and credentials, expected must-PASS set, expected residual set, and reset boundary. |
| Read mix | Frozen query classes and percentages, healthy/stale-checkpoint/witness-outage/post-rotation/post-revocation states, sampled and policy-required local proof checks, Windows and Linux client runs, and concurrency. |
| Scale and limits | Event count, payload-size distribution, normal/burst append rates, read volume/concurrency, parser/proof limits, resource envelope, recovery targets, cadence, quorum, staleness floors, clock-skew maximum, and external time references. |
| Session reference | At most a session id, digest, and bounded descriptor suitable for D-0A-11. Transcript content remains outside the kernel in a separately access-controlled, non-trust-bearing session-capture store and is not needed to score the substrate. |

D-0A-4 supplies 0B ceilings and costing assumptions: `PERMISSION_NOW_MAX_STALENESS` may not exceed 15 minutes, `UNANCHORED_WINDOW_MAX` may not exceed 60 minutes, and `WITNESS_RETENTION_MIN` is costed at 7 years. Stricter per-action floors, checkpoint age, witness clock skew, external time references, and actual cadence remain part of the scale-profile approval.

`OPEN:` The owner must approve the complete frozen scale profile required by rubric section 3: event count, payload-size distribution, read concurrency and mix, checkpoint cadence, witness quorum, resource envelope, RPO/RTO, `PERMISSION_NOW_MAX_STALENESS`, every stricter per-action floor, `CHECKPOINT_MAX_AGE`, `WITNESS_CLOCK_SKEW_MAX`, and external time-reference set.

### 2.2 Evidence-package schema

Each candidate emits a self-contained directory or archive whose manifest is canonical and digest-addresses every member. The conceptual schema is language-neutral; JSON, CBOR, or another encoding is acceptable only if the encoding and canonicalization are pinned before measurement.

| Object | Required fields |
|---|---|
| `manifest` | package schema/version; candidate id; run id; start/end in UTC and local offset; frozen rubric revision/date/reviewers/owner approval; fixture/config/scale digests; ordered member path, media type, byte length, digest; package digest; deviations; secret-redaction declaration. |
| `environment` | product, OS, driver, verifier, schema/protocol, witness and policy versions; exact topology; CPU/RAM/storage limits; licenses; installed artifact/configuration digests; clock sources; network boundaries; operator and failure-domain labels. |
| `pins` | genesis/root/roster bytes or references and digests; publisher; authenticated channel; predecessor/version; acquisition time; custody; independently retained pre-attack cut; pinned and no-pin first-contact outputs. |
| `fixture-use` | source fixture digest; candidate translation mapping; canonical input bytes/digests; authority positions; revocation `e`, `r`, and `t`; checkpoint cadence; read-mix and scale values; deterministic seeds. |
| `workload-results` | one entry for every rubric section 4 row: row id/name; ordered commands or API transcripts; inputs; pre/post cuts and roots; timestamps; expected predicate; observed structured output; measurement fields required by the rubric; artifact references; verdict; cited invariants; deviation and retry history. |
| `adversary-results` | one entry for every rubric section 5 scenario: adversary id; compromised credentials/zones; exact injection; before/after cuts and digests; expected and observed result; detection/refusal time; alerts; operator action; must-PASS verdicts; expected residuals; artifact references. |
| `proofs` | canonical event/claim bytes; signed acknowledgements; inclusion/consistency/completeness proofs; checkpoints; witness observations; input/output digests; parser-limit results; external-verifier command/version and structured output. |
| `witness-custody` | witness identity; operator; admin realm; host; key/custody; persistence plane; monitoring and retention; observations; quorum calculation; independence attestation and supporting inventory. |
| `faults-and-recovery` | injected fault; exact time/cut; old/new artifacts; denied operations; alerts; RPO/RTO; operator touch time; restore/replay/rebuild/reconciliation steps; first safe write; unanchored marker; closure evidence. |
| `telemetry` | p50/p95/p99 latency; throughput; errors/denials; CPU, memory, disk, storage growth, and network; proof/cache rates; checkpoint age; collection interval and tool version. |
| `operations` | setup, verify, incident, backup, restore, break-glass, patch/upgrade, version-skew and witness runbook references; command log; operator elapsed time; manual decisions. |
| `premises` | symmetric A/B/C dependency ledger entries with assertion, status `EVIDENCED`, `FAILED`, or `OPEN`, owner, evidence reference, and affected criterion; candidate B checklist entries additionally keyed to rubric section 8. |
| `licenses` | product/edition/features used; installed-edition output; terms/contract/source identity and retrieval date; target-use restriction; support lifecycle; reviewer conclusion; unresolved licensing questions. |
| `observer` | observer name/role; independence statement; observation windows; witnessed setup/fault/reset/custody events; evidence received directly; package digest; discrepancies; signed or otherwise authenticated attestation. |

The evidence package must contain commands, configuration digests, timestamps, structured verifier output, proof/checkpoint bytes or digests, witness observations, resource telemetry, and operator elapsed time. It must exclude secret values. Missing, malformed, stale, partial, warning, contradictory, or unverifiable evidence is denial or `INCOMPLETE`, never PASS.

Candidate B must include the external verifier command/version, independently retained digest source and custody, input/output digests, and tampered-instance negative test. Verification performed only inside SQL Server is insufficient.

### 2.3 Result-record schema

The result record is a summary indexed entirely by evidence-package references. It contains:

| Field | Type and rule |
|---|---|
| `record_schema` | Pinned identifier and version. |
| `candidate` | `A`, `B`, or `C`; exact candidate description. |
| `rubric` | Frozen revision, SHA-256, freeze date, concurring reviewers, owner approval. |
| `fixture` | Fixture, scale-profile, topology, policy, and configuration digests. |
| `environment` | Candidate versions, topology, resources, licenses, operators, trust/failure domains, and deviations. |
| `rows` | Exactly one record for each section 4 workload and section 5 adversary row with `PASS`, `FAIL`, or `INCOMPLETE`, cited invariants, evidence references, duration, and notes. |
| `invariant_gate` | One record for every tested applicable `INV-*`: `PASS`, `FAIL`, or `INCOMPLETE`; harness check ids; reproduction references; applicability rationale. Any applicable FAIL or mandatory-core INCOMPLETE disqualifies. |
| `operations` | Completed operational-requirements row from rubric section 6 with measured facts, named roles, dependencies, and runbook/evidence references. |
| `premises` | Symmetric A/B/C premise ledger; B's completed section 8 checklist; each entry `EVIDENCED`, `FAILED`, or `OPEN`. |
| `eligibility` | `ELIGIBLE`, `DISQUALIFIED`, or `PENDING`; exact rubric section 7.1 reason and failed/incomplete invariants. No weighted total for `DISQUALIFIED` or `PENDING`. |
| `weighted_criteria` | Present only after an eligible invariant gate; criterion, fixed weight, raw score 0-5, evidence anchor, calculation, and `UNSCORED` reason where a premise remains open. No total while any required environment-fit criterion is unscored. |
| `residuals` | Malicious valid appends, never-acknowledged censorship, full witness-quorum compromise, bootstrap-policy compromise, availability loss, and candidate-specific residuals. |
| `time` | Engineer time, wall time, setup/measurement/recovery/package split, unfinished work, and time-box overruns. |
| `decisions` | Every owner decision and assumption used, without changing the frozen rubric. |
| `evidence_package` | Package digest, location, verification procedure, observer attestation reference. |

### 2.4 Directory layout

The harness deliverable is specified by this layout; this plan does not select an implementation language or provide code.

```text
0b-harness/
  SPEC.md
  schemas/
    fixture.schema
    evidence-package.schema
    result-record.schema
    verifier-output.schema
  fixtures/
    manifest
    canonical-events/
    genesis-and-pins/
    authority/
    revocation/
    checkpoints/
    proofs-and-malformations/
    concurrency-schedules/
    recovery/
    break-glass/
    read-mix/
    scale-profile/
  scenarios/
    workload-04/
    adversaries-05/
    matrix-coverage/
  candidates/
    A/ADAPTER-SPEC.md
    B/ADAPTER-SPEC.md
    C/ADAPTER-SPEC.md
  runs/
    A/<run-id>/
    B/<run-id>/
    C/<run-id>/
  results/
    A.result
    B.result
    C.result
  reviews/
```

### 2.5 Invariant-to-check map

Every invariant cited by the rubric maps to at least one named harness check. An invariant may require several checks; passing one row does not imply the invariant globally. `INV-053`, `INV-056`, and `INV-059` are explicitly outside substrate scoring under rubric section 7, so the harness records capabilities or applicability without implying PASS.

| Invariant | Harness check(s) |
|---|---|
| `INV-001` | `APPEND-CANONICAL-SIGNATURE`, `APPEND-DOMAIN-SEPARATION`: exact bytes/domain/algorithm/type bind; wrong-domain and unknown authentication deny. |
| `INV-002` | `APPEND-ENVELOPE-BINDING`: id, position, predecessor, project, entity, actor/key, action, policy, and nonce changes deny. Exercises fully-closed rows SEC-02, SEC-13, and persist-3. |
| `INV-003` | `PROOF-UNKNOWN-DENY`, `APPEND-AUTH-ABSENT-DENY`: unknown/ambiguous/mismatched/retired algorithms or schemas and absent auth deny. Exercises cairn-07, crypto-5, and cairn-17. |
| `INV-004` | `PROJECTION-BYTE-RECONCILIATION`, `ADV-03-WRITER`, `ADV-12-DB-WRITER`, `ADV-26-COLLUSION`: mutable mismatch cannot grant authority or PASS. |
| `INV-005` | `CHAIN-UNIQUE-ORDER`, `FORK-REJECT`, `PROOF-CONSISTENCY`: deletion/insertion/duplicate/filter suppression and inconsistent descendants deny. Exercises persist-9 and cairn-01. |
| `INV-006` | `PROOF-SCOPE-COUNTS`, `PARTIAL-AS-COMPLETE-DENY`: range/filter/bounds/count omissions deny. Exercises cairn-09 and ADV-03/12/13/26. |
| `INV-007` | `ONLINE-OFFLINE-FILTER-DIFFERENTIAL`, `PROJECTION-REBUILD-EQUIVALENCE`: identical evidence/policy/cut has identical semantics. Exercises cairn-01 and cairn-17. |
| `INV-008` | `AUTHORITY-PRIOR-POSITION`, `ROTATION-HISTORY`: no self-authorization; acceptance uses `S_(p-1)`. Exercises SEC-13. |
| `INV-009` | `GENESIS-FIRST-WRITE`: first write consumes exactly one independently pinned bootstrap policy and admission result. |
| `INV-010` | `AUTHORITY-NO-CALLER-TIME`, `ROTATION-POSITION`: authority/expiry derives from authenticated position and policy clocks. Exercises cairn-11, SEC-04, SEC-07, and cairn-03. |
| `INV-011` | `ROTATION-PERMISSION-NOW`, `READ-STALE-CUT-DENY`, `ROLLBACK-OLD-PAIR`: retired authority and over-age cuts deny. |
| `INV-012` | `AUTHORITY-CACHE-INVALIDATION`, `REVOCATION-REPLAY`, `READ-POST-TRANSITION`: results bind their knowledge cut and do not refresh cut age. |
| `INV-013` | `REVOCATION-EFFECT-RANGE`: deterministic finite-range, dual-control, exemption, overlap, propagation, and invalid-policy denial. |
| `INV-014` | `CHECKPOINT-FIELD-SIGNATURE`, `CHECKPOINT-ROTATION`, `FORK-SPLIT-VIEW`: checkpoint fields and effective signing key bind. |
| `INV-015` | `WITNESS-MONOTONIC-RETENTION`, `WITNESS-FALSE-OBSERVATION`: signed identity/time/state retention and expiry behavior. |
| `INV-016` | `WITNESS-QUORUM-INDEPENDENCE`, `ADV-23-ONE-WITNESS`, `ADV-27-DBA-ONE-WITNESS`: at least two independently operated domains are required; one operator cannot satisfy quorum. |
| `INV-017` | `FORK-TERMINAL`, `ROLLBACK-OLD-PAIR`, `RESTORE-EXTERNAL-CUT`: retained prior cuts expose inconsistency and no branch is selected. |
| `INV-018` | `STALE-QUORUM-DENY`, `ROLLBACK-Q3-DENY`, `OUTAGE-Q3-DENY`, `RESTORE-WITNESS-RECONCILE`: stale/unavailable/forked evidence suppresses positive Q3 and dependent actions. |
| `INV-019` | `CLAIM-COMMON-FIELDS`, `LOCAL-VERIFY-PACKAGE`: all required claim fields bind in locally verifiable evidence. |
| `INV-020` | `Q1-Q2-SEPARATION`, `ROTATION-OLD-KEY-DENY`, `REVOCATION-AUTHORITY`: signature-valid is never treated as authorized. |
| `INV-021` | `CLAIM-SCOPE-NO-OVERSTATEMENT`, `PARTIAL-AS-COMPLETE-DENY`, `FORK-OUTPUT`: partial/filter/stale scope cannot imply wider completeness. |
| `INV-022` | `AGGREGATE-FAIL-CLOSED`: false, absent, null, warning, halted, contradictory, or unverified prerequisite cannot aggregate to PASS. |
| `INV-023` | `LOCAL-VERIFY-PACKAGE`, `RECEIPT-DECLARED-RESIDUAL`: local verification is default; any selected receipt binds fields/lifecycle/freshness and declares trust residuals. |
| `INV-024` | `ADV-12-UNSIGNED-PASS-DENY`: raw mutable rows and app flags cannot supply authority to the measured decision path. |
| `INV-026` | `CT-DECISION-FIELD-BINDING`: concurrent decision binds caller, subject/action, target, claims/cuts, policy, nonce, expected state, and result. |
| `INV-027` | `CT-CHECK-COMMIT-ATOMICITY`: losing and replayed schedules cannot reuse a decision for another or later action. |
| `INV-028` | `REVOCATION-DUAL-CONTROL`: authenticated distinct principals and policy authority are required; strings and self-approval deny. |
| `INV-035` | `RESTORE-ARTIFACT-PROFILE`, `VERSION-PIN-INSTALL`: restored/installed artifacts bind digest, version, source, and safe executable resolution. Exercises acb-9. |
| `INV-036` | `PINNED-SIGNED-POLICY-CONFIG`: root, witness/authority policy, and configuration come from independently pinned purpose-separated inputs. |
| `INV-037` | `RESTORE-PROFILE-COMPLETE`: restored profile derives the complete enabled topology and disabled paths remain absent for the test deployment. |
| `INV-038` | `RESTORE-FULL-RECONCILIATION`, `ROLLBACK-NONEMPTY-HISTORY`, `PROJECTION-REBUILD`: no operation before artifact/profile, external-cut, authority, witness, and projection checks complete. |
| `INV-039` | `PROJECTION-REBUILD-EQUIVALENCE`, `ADV-12-PROJECTION-CORRUPTION`: fresh replay at the same cut/policy exactly equals canonical projection. |
| `INV-045` | `PROOF-PARSER-LIMITS`, `READ-BOUNDED-PROOF`: byte/count/depth/decompression/path/read/time limits apply before expensive work. |
| `INV-049` | `BREAK-GLASS-CAPS-CHAIN-CLOSURE`, `RESTORE-PREMATURE-RESUME`, `ROLLBACK-Q3-DENY`: chained records, cumulative caps, reconciliation, and closure precede ordinary operation. |
| `INV-051` | `APPEND-ACK-DEADLINE-CENSORSHIP`: signed ack binds required fields; missed merge deadline stops action and publishes evidence; no-ack case is recorded as residual. Exercises MATRIX row SEC-01. |
| `INV-052` | `PIN-FIRST-CONTACT`, `PIN-UPDATE-EQUIVOCATION`: authenticated independent pin permits trust; no-pin run issues no trusted Q2/Q3/claim. Exercises cairn-06 and cairn-08. |
| `INV-053` | `KEY-CUSTODY-CAPABILITY-RECORD`, `CRYPTO-4-WINDOWS`: record purpose separation, HSM/platform-keystore mode, non-exportability and argv/diagnostic handling. Rubric section 7 excludes profile qualification from scoring; no substrate PASS is implied. |
| `INV-054` | `CT-LOCK-REREAD-CAS`: deterministic schedules prove post-lock re-read, expected version, bound commit, and deny/retry on stale state. Exercises SEC-09, persist-5, persist-6, persist-10, persist-15, and acb-13. |
| `INV-055` | `POLICY-FLOOR-MONOTONIC`, `OUTAGE-HARD-MAX`, `BREAK-GLASS-CAP-NONWEAKENING`: rollback/runtime/emergency inputs cannot weaken minima or raise maxima. |
| `INV-056` | `UNSELECTED-CLAIM-POLICY-DENY`: capture whether an unselected/invalid prerequisite suppresses claim issuance. Rubric section 7 places claim-type application policy outside substrate scoring; no substrate PASS is implied. |
| `INV-057` | `MIXED-VERSION-DOWNGRADE-DENY`: below-minimum component/claim/protocol cannot obtain PASS; record in version-skew evidence. |
| `INV-058` | `UNANCHORED-MARKER-PERMANENCE`: recovery marker binds exact range/times/positions/policy/reconciliation and all intersecting claims remain `unanchored=true`. No MATRIX row currently cites `INV-058`; the dedicated rubric row supplies the exercise. |
| `INV-059` | `REVIEW-SUBJECT-BINDING-CAPABILITY`: record candidate support needed by future review admission, but do not score it; rubric section 7 places app/gate/signer exact-subject admission outside this substrate bake-off. |

The 15 `fully-closed-by-kernel` MATRIX rows are explicitly exercised by the checks above: persist-9, acb-9, cairn-11, SEC-02, SEC-04, SEC-07, SEC-13, crypto-3, persist-3, cairn-03, cairn-01, cairn-07, crypto-5, cairn-09, and cairn-17. The special carried rows are also reachable: SEC-01 for `INV-051`; cairn-06 and cairn-08 for `INV-052`; SEC-09, persist-5, persist-6, persist-10, persist-15, and acb-13 for `INV-054`; and the dedicated unanchored recovery scenario for `INV-058` because no current MATRIX row cites it.

## 3. Execution protocol

### 3.1 Roles and result isolation

- One Sol executor run is assigned to each candidate and host. The three runs start from the same pinned harness and execute in parallel. No actor id is created or inferred.
- One independent observer owns direct receipt of fixture/configuration digests, witnesses the pre-flight and destructive fault boundaries, receives witness evidence independently of each candidate executor, and authenticates each final package digest. The observer does not implement candidate adapters, repair candidate failures, or convert warnings into PASS.
- Fable, Opus, and minimax review the completed evidence/result records. They do not alter measurements or the frozen rubric. Review discrepancies append review evidence; they do not overwrite raw results.
- A candidate executor and its setup helpers may not see another candidate's measurements, verdicts, telemetry, security failures, or package before that candidate's own security core is complete and its package digest is delivered to the observer. Shared fixture errata are disclosed symmetrically. A correction that affects a predicate, workload, or fixture requires the rubric's complete affected rerun rule.

`OPEN:` Name the independent observer and confirm that one observer can cover three parallel fault boundaries. If not, name independent delegates under one observer protocol without creating candidate-specific evidence standards.

### 3.2 Per-candidate order

Each candidate follows the same order. Candidate-specific setup is recorded but does not change row order or predicates.

1. **Pin and baseline.** Verify package inputs, environment and versions; acquire genesis/root/roster through the independent channel; execute pinned and no-pin first contact; establish the independently retained pre-attack cut.
2. **Append and authority.** Run section 4 `Append`, `Rotation`, and `Revocation with effect range`, including acknowledgements, boundary cuts, cache invalidation, dual control, and invalid cases.
3. **Proof and witness foundation.** Run `Inclusion and consistency proof` and `Checkpoint and witness`, then confirm local Windows and Linux verification paths before fault injection.
4. **Concurrency.** Run `Concurrency / TOCTOU` deterministic schedules against the established authority/checkpoint history.
5. **Fork and rollback.** Run `Fork`, then reset from a recorded clean boundary and run `Rollback: old DB plus old checkpoint`.
6. **Unanchored state.** Reset, run `Unanchored outage and recovery`, and preserve the permanent intersecting-claim disclosures.
7. **Projection and restore.** Run `Projection rebuild`, then `Restore` onto clean infrastructure, including premature-resume denial and first safe write.
8. **Break-glass.** Run `Break-glass` only after ordinary recovery is proven, including prohibited action, reset, renewal, cap, expiry, reconciliation, closure, and resume cases.
9. **Adversary sweep.** Complete and package every section 5 scenario: `ADV-03`, `ADV-12`, `ADV-13`, `ADV-14`, `ADV-23`, `ADV-26`, `ADV-27`, and `ADV-34`. Reuse evidence from an earlier row only when the exact injection and all scenario fields were captured; otherwise rerun. Expected residuals are recorded, not treated as failures.
10. **Extended row and operations.** Run `Representative read volume`, both client platforms, version-skew, licensing/support, staffing, routine operations and cost evidence as time allows. `INCOMPLETE` handling follows section 4 of this plan.
11. **Seal.** Executor validates manifest membership and digests, emits the result record, transfers the package digest to the observer, and receives the observer discrepancy/attestation record. Results remain embargoed from the other candidate teams until their security-core packages are sealed.

Reset operations must restore the same pinned baseline and must be represented in the evidence package. A reset may not erase an observed fork, censorship event, unanchored disclosure, or other evidence from the package.

### 3.3 Evidence custody

- The executor captures candidate commands, outputs, telemetry, configuration digests, and operator time.
- Witness evidence flows directly to independently controlled retention and to the observer; the writer/DBA-provided copy is comparison evidence only.
- The observer captures pre-fault cuts/digests, fault start/stop, direct witness observations, reset authorization, and the final package digest.
- Secret values, private keys, DSN passwords, transcript content, and production data are excluded. Redaction must preserve field presence, digest continuity, and enough structure to reproduce the result.
- Host clocks record UTC and local offset. Witness trusted-time claims also record the frozen external-reference comparison and skew result.
- Raw failures are immutable inputs to analysis. A rerun receives a new run id and links its predecessor; it does not replace the failed package.

## 4. Time box and wall-clock proposal

The frozen rubric's time box remains at most **5 engineer-days per candidate**, including setup, mandatory workload, adversary injection, recovery, packaging, and runbooks: **15 candidate-days total**. Shared harness preparation and final analysis retain the rubric's **2 additional engineer-days**, for **17 engineer-days total**. D-0A-9 parallelizes the candidate-days; it does not reduce work or permit omitted security rows.

### 4.1 Mandatory security core

The following must complete reproducibly inside each candidate's five-day box. A `FAIL` of an applicable invariant or `INCOMPLETE` in this set disqualifies the candidate:

- Append
- Rotation
- Revocation with effect range
- Inclusion and consistency proof
- Checkpoint and witness
- Fork
- Rollback: old DB plus old checkpoint
- Restore security predicate
- Projection rebuild
- Concurrency / TOCTOU
- Unanchored outage and recovery
- Break-glass
- Every rubric section 5 adversary scenario

### 4.2 INCOMPLETE-tolerant work

The following extended evidence may be `INCOMPLETE` without security disqualification: representative read volume, cross-platform ergonomics, performance percentiles, licensing, staffing, and operational-cost measurements. An incomplete row receives no favorable evidence or score, and the corresponding criterion remains unscored. This tolerance does not turn a demonstrated invariant failure into incompleteness, does not make candidate B's licensing premise true, and does not permit a weighted total while a required environment-fit premise remains open.

### 4.3 Parallel week

| Working day | A on `mvmcc03` | B on `mvmcitest01` | C on `mvmcc02` | Shared/observer activity |
|---|---|---|---|---|
| Pre-measurement | Provision and pin | Provision, validate premises, and pin | Provision and pin | One shared harness-preparation day; complete pre-flight before scores |
| Day 1 | Baseline, append, authority | Baseline, append, authority | Baseline, append, authority | Observe pin/custody and starts |
| Day 2 | Proofs, witnesses, concurrency | Proofs, witnesses, concurrency | Proofs, witnesses, concurrency | Observe direct witness evidence |
| Day 3 | Fork, rollback, adversaries | Fork, rollback, adversaries | Fork, rollback, adversaries | Observe fault boundaries |
| Day 4 | Outage, rebuild, restore, break-glass | Outage, rebuild, restore, break-glass | Outage, rebuild, restore, break-glass | Observe recovery and closure |
| Day 5 | Remaining adversaries, extended row, package | Remaining adversaries, extended row, package | Remaining adversaries, extended row, package | Seal package digests and lift embargo when all cores are sealed |
| Post-measurement | Review support only | Review support only | Review support only | One shared analysis day; produce symmetric records for 0C |

The candidate execution collapses to approximately one working week when provisioned hosts, fixtures, observers, and witness paths are ready before Day 1. The full calendar includes shared pre-measurement preparation and post-measurement analysis; these may bracket the week rather than consume candidate measurement time.

`OPEN:` The owner must size and approve the five-engineer-day box against expected duration for every mandatory-core row before measurement. Record expected setup, execution, reset, recovery, and packaging hours per row. If the box is not credible, revise and re-freeze the rubric before any scored run; do not solve the mismatch with universal `INCOMPLETE`.

`OPEN:` The owner must approve whether the proposed approximately one-week wall clock is adequately staffed for three Sol executor runs, Windows access, witness operators, and the observer, or set a later common start date while preserving parallel execution.

## 5. Candidate B premise validation

Candidate B runs on `mvmcitest01`, but no environment-fit score is available until the actual target-environment premises in rubric section 8 are evidenced. The following checks occur before B environment-fit scoring; security measurements may proceed while a non-security premise is open, but witness-independence failure disqualifies B.

| Premise | Who | Concrete check and evidence | Outcome rule |
|---|---|---|---|
| SQL Server edition/features available | B executor; observed by independent observer; validated by target licensing/SQL owner | Record OS inventory; SQL Server product version, edition, update level and installed Ledger/HA/backup/verification features using native server queries and setup inventory; execute Ledger creation, digest generation, external verification, backup and clean-host restore paths actually used by the candidate. | Missing required feature is `FAILED`; undocumented availability is `OPEN`. |
| Licensing and support | Target licensing/procurement owner with B executor evidence; reviewer cross-check | Attach authoritative Microsoft terms or target contract/license record with source, date, edition, permitted environment/use, HA/passive rights if used, support channel, and lifecycle. Map every measured feature and intended deployment mode to the evidence. | SQL Server Developer edition is not licensed for production use. Lab success therefore does not establish target production eligibility. `OPEN:` identify and approve a production-licensable SQL Server 2022 edition, entitlement, support model, and cost that includes every feature used. Until then B's licensing criterion is `UNSCORED` and B has no weighted total. |
| DBA capability and coverage | Target SQL operations owner | Name personnel/roles and coverage for Ledger configuration, security boundaries, patching, performance, incident response, digest operations and adversarial verification; attach on-call ownership, skills inventory, and training gaps; have the named role execute or observe the verify and restore runbooks. | Unsupported or absent committed capability is `FAILED` or `OPEN`; no favorable staffing evidence. |
| HA and clean-host recovery | Target SQL/Windows operations owner; B executor performs; observer witnesses | Inventory the intended HA design; restore a backup to clean infrastructure; verify artifact/profile, external retained digest, Ledger chain, authority replay, witnesses and projection; measure RPO/RTO and first safe write; attempt premature resume. | Unsafe resume is security FAIL under `INV-038`/`INV-049`; absent target commitment remains premise `OPEN`. |
| Digest operations | Named digest-management owner, distinct duties recorded | Execute digest generation, any signing/authentication, publication, cadence, retention, monitoring, alert, external verification, incident handling and recovery runbook. Record who can alter source, channel and expected digest. | Ordinary DBA familiarity is not imputed. Missing ownership/tooling remains `OPEN` and affected environment-fit criteria are unscored. |
| Witness independence | Owner names operators; observer verifies inventory and direct evidence | Prove both B witnesses on `mvmcc03` and `mvmcc02` are outside SQL Server, SQL host/cluster, backup platform, DBA credentials, DBA management plane, DBA reporting/failure domain, directory/IdP administration and secret-backend administration. Compare operators, accounts, admin realms, keys/custody, hosts, persistence, channels and monitoring; inject one-witness compromise and show it cannot satisfy quorum. | Any common control able to alter the required quorum is security `FAIL` under `INV-016`, not an operational deduction. |
| External verification | B executor runs; observer obtains digests directly from both witnesses | Run a pinned external verifier outside SQL Server against independently retained digests; record command/version, inputs/outputs and custody. Tamper with the live instance and show external verification refuses/detects without trusting SQL Server's verdict. | SQL-only verification or DBA-controlled expected digests fail the applicable local-verification/independence predicate. |
| Windows/Linux clients | B executor on `mvmcitest01` and one Linux host | Install pinned drivers/verifier; authenticate, connect, query, obtain evidence, verify locally, diagnose failure and exercise upgrade/version skew from both platforms. | Missing platform path affects integration evidence; a security-semantic divergence is an applicable invariant FAIL. |

`ASSUMPTION:` SQL Server 2022 Developer edition is the available lab edition on `mvmcitest01`. It is suitable for non-production development/testing but is not production-licensable; target licensing remains an owner premise, not an inferred benefit of the lab host.

`OPEN:` Name the target licensing/procurement owner, SQL operations owner, digest-management owner, HA/restore owner, and the two independently governed witness operators before B receives environment-fit weight.

The carried `crypto-4` Windows reproduction runs on `mvmcitest01` during pre-flight or B's extended evidence window. It captures whether private key material enters argv or diagnostics and records the Windows key-protection mode. It is evidence for future `INV-053` profile qualification and must complete before 0C protocol acceptance, but the rubric does not turn it into a substrate score.

## 6. Pre-flight checklist

**Item 0 (added after review, B1/N7):** the owner's INV-016 posture for this bake-off is recorded in `DECISIONS-0B.md` D-0B-1 BEFORE any scored measurement — either (i) six distinct operator/admin/custody/persistence assignments are named and evidenced, or (ii) a **simulated-independence declaration** is recorded: the bake-off measures whether each candidate's design *supports* independent witnesses (separate service identities, keys, storage, admin accounts, no shared credentials, fail-closed below quorum), the single human operator is an explicit residual, and real operator independence becomes a deployment-profile requirement verified at cutover. Under (ii) no candidate may be declared to *pass* INV-016; results are recorded as `INV-016: design-supports / operator-independence-not-demonstrated`.

No scored measurement starts until every mandatory item below is checked and the observer has the referenced digest or evidence.

- [ ] Frozen rubric repository revision, SHA-256, freeze date, concurring lineages, and owner approval recorded in the run manifest. The drafting values at the top of this plan are independently recomputed, not merely copied.
- [ ] Fixture manifest and every fixture member pinned by digest; candidate translation mappings reviewed for semantic equivalence.
- [ ] Result and evidence-package schemas pinned; local package verification procedure exercised on a synthetic package.
- [ ] Scale profile approved, closing the rubric section 3 `OPEN:` before measurement.
- [ ] Five-engineer-day box sized against every mandatory-core row and explicitly approved by the owner, or the rubric revised/re-frozen before measurement.
- [ ] Sol executor run assigned for A, B, and C; independent observer named; Fable, Opus, and minimax review availability recorded. No actor id is required or assigned.
- [ ] Candidate teams accept the cross-candidate result embargo through security-core package sealing.
- [ ] `mvmcc03`, `mvmcc02`, and `mvmcitest01` provisioned; OS, CPU, RAM, disk, container/runtime, database/product, client, driver and verifier versions inventoried.
- [ ] Candidate resource envelopes approved or differences documented with an equal-resource rerun rule; no raw throughput comparison across materially unequal resources.
- [ ] Six witness instances provisioned according to the matrix; distinct operators, keys/custody, admin realms, persistence, monitoring, retention and failure domains evidenced.
- [ ] Independent pin channel, signed genesis/witness policy, root/roster, external time-reference set, and verifier-pinned pre-attack storage provisioned.
- [ ] Cross-host authenticated connectivity, firewall paths, name resolution, clock comparison, telemetry and evidence transfer tested.
- [ ] Backup, clean-host restore, fault injection, reset and evidence-retention procedures rehearsed without erasing prior fault evidence.
- [ ] Candidate B premise evidence owners named; lab edition/features checked; production licensing remains explicitly open unless authoritative evidence closes it.
- [ ] Windows and Linux client paths available for every candidate.
- [ ] `crypto-4` Windows reproduction scheduled on `mvmcitest01` before 0C protocol acceptance.
- [ ] Secret-redaction and no-free-text controls checked; no production data or session transcript content enters the kernel fixture or evidence package.

## 7. 0B exit and 0C handoff

Additions after review (minimax N6): the 0C hand-off MUST include (a) **FIPS/HSM evidence per candidate** — availability and support status of validated cryptographic modules in the actual deployment mode, HSM/KMS/CNG/PKCS#11 integration path, and key non-exportability (`INV-053`); (b) **cross-platform conformance evidence** — the same canonical event bytes hashed/signed/verified on Windows and Linux clients produce byte-identical digests and identical verifier results (rubric §9 Portability), captured in the evidence package.

Phase 0B is complete when 0C receives all of the following without a rubric change hidden in analysis:

1. Three sealed evidence packages, one per candidate, each independently digest-verified and carrying observer evidence.
2. Three result records with every rubric section 4 workload and section 5 adversary row represented.
3. An invariant-gate table per candidate with every tested applicable invariant marked `PASS`, `FAIL`, or `INCOMPLETE` and linked to reproduction evidence.
4. A clear eligibility result per candidate. No weighted result exists for a security-disqualified candidate; no total exists while required environment-fit premises remain open.
5. Completed operational-requirements evidence for A, B, and C, with `UNKNOWN`, `OPEN`, and undocumented manual knowledge receiving no favorable score.
6. A symmetric A/B/C premise ledger and the formal candidate B premise checklist, including authoritative licensing status and witness independence.
7. Fixed-weight criterion evidence and arithmetic only for candidates eligible under rubric section 7.1.
8. Explicit residuals and trust assumptions, including malicious valid appends, never-acknowledged censorship, full witness-quorum compromise, bootstrap-policy compromise, unanchored ranges and availability loss.
9. Measured time, unfinished work, resource differences, deviations, reruns, operator touch time, RPO/RTO and runbook references.
10. A cross-candidate comparison prepared only after all security-core package digests were sealed, preserving raw evidence and ties.
11. The `crypto-4` Windows reproduction evidence or an explicit blocker that prevents 0C protocol acceptance.
12. 0C decision inputs for substrate, anchor/witness design, implementation stack, repository/process boundaries, final values below D-0A-4/5 maxima, version governance, local-verification policy, and D-0A-11 session-capture integration. The session-capture store remains non-trust-bearing and outside the kernel.

0B does not choose a language or stack, change the claim vocabulary, implement the D-0A-11 store, or select the winning substrate in this plan. It supplies falsification and operational evidence to 0C.

## 8. Risks and owner questions

| Risk | Consequence | Control or decision |
|---|---|---|
| Resource contention | Writers and witnesses for different candidates share the three hosts; parallel CPU, memory, disk or network pressure can distort latency or cause correlated outages. | Pin per-process limits, stagger destructive boundaries where needed without exposing results, capture host-level telemetry, and rerun performance under equal resources. Security denials remain valid evidence. `OPEN:` approve resource envelopes and any additional witness hardware needed. |
| Windows executor availability | Candidate B, Windows/Linux client coverage, and `crypto-4` depend on timely access to `mvmcitest01`. | Verify interactive/non-interactive access, SQL privileges, reboot windows, storage and observer access before Day 1. `OPEN:` name the Windows host owner and fallback measurement dates; do not move B onto a loaded Linux host merely to preserve schedule. |
| immudb maturity and operating knowledge | Candidate C may consume its box in proof semantics, backup/restore, version skew, or unsupported client workflows. | Pin supported versions, document product claims separately from reproduced evidence, rehearse setup before scoring, and mark unfinished extended work honestly. `OPEN:` name the C operations/support owner and accepted support source. |
| Cross-host witness network | Firewall, DNS, clock, packet loss or correlated network administration can make witnesses unavailable or undermine claimed independence. | Pre-test authenticated routes and independent evidence delivery; record network/admin domains; inject one-path loss; fail closed below quorum. `OPEN:` confirm whether one network administrator can alter both witnesses for any candidate and remediate if so. |
| Operator-independence scarcity | The lab may have three physical hosts but only one person or common admin plane, which cannot satisfy `INV-016`. | Treat the host matrix as proposed placement only; require named distinct operators/admin realms/custody/persistence before PASS. Add independent infrastructure/operators or disqualify. |
| Shared observer overload | One observer may miss simultaneous fault boundaries or rely on executor-provided evidence. | Schedule high-value fault starts in observable windows, automate direct evidence delivery without changing predicates, or use named independent delegates under one protocol. `OPEN:` approve observer coverage. |
| Candidate leakage | An executor could tune its security design after seeing another candidate's failure, invalidating symmetry. | Embargo results until all three mandatory cores are sealed; disclose only symmetric fixture errata. |
| Developer-edition premise | Candidate B can work in the lab but remain unusable in the target production environment. | Keep production licensing `OPEN`, attach authoritative terms/contract evidence, and withhold B's environment-fit weight and total until resolved. |
| Unequal hardware/OS | Raw throughput can favor a host rather than a substrate. | Record every difference, normalize only with declared method, and require equal-resource repetition for comparative raw throughput. |
| Evidence-package drift | Candidate adapters may omit required native evidence or substitute self-verdicts. | Pin schemas and adapter mappings before scoring; validate package completeness mechanically and by observer; missing evidence denies or is `INCOMPLETE`. |

## 9. Summary

Phase 0B runs A on `mvmcc03`, C on `mvmcc02`, and B on Windows host `mvmcitest01` in parallel under the unchanged frozen rubric. Each candidate uses two witnesses on the other two hosts, but passes `INV-016` only with distinct operators, admin realms, keys/custody, and persistence planes outside its writer/DBA domain. One language-neutral fixture and evidence contract drives every section 4 workload, every section 5 adversary, all rubric-cited invariants, the 15 fully-closed MATRIX rows, and the `INV-051`/`INV-052`/`INV-054`/`INV-058` exercises. The five-engineer-day candidate box remains intact; security-core incompleteness disqualifies, extended-row incompleteness receives no credit, and the proposed parallel wall clock is approximately one week once pre-flight is complete. Candidate B receives no environment-fit total until production licensing, DBA/digest/HA capability, and genuinely DBA-independent witnesses are evidenced. 0C receives sealed packages, invariant gates, operational requirements, premise ledgers, residuals, and eligible scoring evidence, not a preselected substrate.
