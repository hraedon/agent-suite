# Phase 0B scale-profile proposal

Status: coordinator proposal for owner ratification. This profile closes the concrete-number `OPEN:` in the frozen `BAKEOFF-RUBRIC.md` section 3 without changing its workloads or predicates. Every proposed scale value below is frozen identically for candidates A, B, and C after approval.

## 1. Representative estate

`ASSUMPTION:` The estate is currently a lab estate with hundreds to low thousands of regista events per project. No production census has been supplied.

`ASSUMPTION:` The representative target is a small regulated development team with 20 active agents, 200 work items per month, 10 projects, and a 12-month online verification horizon. The event count deliberately includes lifecycle, authority, checkpoint, and negative-test events rather than deriving one event per work item.

| Quantity | Value | Status |
|---|---:|---|
| Baseline canonical history | 20,000 accepted events plus the fixed denied-input cases, approximately 1,000 events per active agent and 8.3 accepted events per work item over 12 months | `PROPOSED (D-0B-2)` |
| Stress canonical history | 200,000 accepted events plus the same proportional denied-input cases | `PROPOSED (D-0B-2)` |
| Read-volume multiplier | 10x baseline: 200,000 logical reads per state, 1,000,000 total across the five required read states | `PROPOSED (D-0B-2)` |
| Normal append rate | 1 event/second for 20 minutes | `PROPOSED (D-0B-2)` |
| Burst append rate | 20 events/second for 5 minutes | `PROPOSED (D-0B-2)` |

The baseline history is used for every mandatory security row. The 200,000-event history is used for the stress replay and the 10x representative-read row; it does not replace the identical baseline falsification history.

## 2. Payload distribution and parser bounds

Payloads are deterministic canonical envelopes containing structured fields only. Free text, artifact bodies, source, patches, logs, prompts, responses, transcripts, secrets, patient data, compressed envelopes, arbitrary paths, and arbitrary URLs remain forbidden by D-0A-1 and `DATA-BOUNDARY.md`.

| Share of accepted events | Canonical envelope size | Intended case | Status |
|---:|---:|---|---|
| 50% | 2 KiB | Ordinary lifecycle event | `PROPOSED (D-0B-2)` |
| 35% | 8 KiB | Authority or claim event with signatures and digests | `PROPOSED (D-0B-2)` |
| 14% | 32 KiB | Proof-bearing or multi-principal event | `PROPOSED (D-0B-2)` |
| 1% | 96 KiB | Large valid proof/checkpoint event below the envelope cap | `PROPOSED (D-0B-2)` |

| Limit | Value | Status |
|---|---:|---|
| Maximum canonical event envelope | 128 KiB | `PROPOSED (D-0B-2)` |
| Aggregate proof/checkpoint material per event | 64 KiB and 256 path nodes | `PROPOSED (D-0B-2)` |
| Aggregate cryptographic material per event | 16 KiB | `PROPOSED (D-0B-2)` |
| Nesting / arrays / object fields | depth 8 / 256 items / 128 fields | `PROPOSED (D-0B-2)` |
| Bundle manifest | 1 MiB and 10,000 digest-only subjects | `PROPOSED (D-0B-2)` |
| Compressed event envelopes | Refused; no decompression budget applies at event admission | `PROPOSED (D-0B-2)` |

Every distribution includes exact-boundary valid inputs and one-byte/count-over-limit denials. These values remain within the draft `DATA-BOUNDARY.md` caps and do not settle those caps as production protocol constants.

## 3. Authority history

Each baseline and stress run uses the same transition positions as percentages of the accepted history so candidate results remain comparable.

| Transition | Concrete fixture | Status |
|---|---|---|
| Initial authority | 20 agent principals, 4 service principals, 2 bootstrap/security governance principals, and 40 active signing keys | `PROPOSED (D-0B-2)` |
| Ordinary changes | 40 grants, 20 delegations, 10 role removals, and 10 policy-version transitions per run | `PROPOSED (D-0B-2)` |
| Agent-key rotations | 20 rotations per run, one per agent, with a 100-position bounded overlap; test the old key immediately inside and outside the overlap | `PROPOSED (D-0B-2)` |
| Writer/checkpoint-key rotations | 2 rotations per run, at 33% and 67% of the accepted history, with a one-checkpoint bounded overlap | `PROPOSED (D-0B-2)` |
| Revocation with effect range | Exactly 1 authorized dual-control revocation issued at 75% of the history, `effect_from` at 60%, and finite `effect_through` at 70%; include 10 directly affected events and a three-level delegation chain | `PROPOSED (D-0B-2)` |
| Revocation controls | One each: malformed, unauthorized, timestamp-based, self-covering, and out-of-policy attempt | `PROPOSED (D-0B-2)` |

The revocation is authorized by the accepted D-0A-3 policy: bootstrap-root operator plus distinct security approver, unbounded permitted lookback, and finite `effect_through`.

## 4. Checkpoints, witnesses, and time

| Control | Run value | Status |
|---|---|---|
| Checkpoint production cadence | Every 100 accepted events or 5 elapsed minutes, whichever occurs first; also checkpoint immediately after each authority transition used by a test | `PROPOSED (D-0B-2)` |
| Positive-Q3 witness quorum | 2 of 2 independently configured witnesses | `PROPOSED (D-0B-2)` |
| Witness retention for costing | 7 years | `PROPOSED (D-0B-2)` |
| `PERMISSION_NOW_MAX_STALENESS` | 5 minutes | `PROPOSED (D-0B-2)` |
| Ordinary non-authority read floor | 5 minutes | `PROPOSED (D-0B-2)` |
| New append and ordinary lifecycle mutation floor | 2 minutes | `PROPOSED (D-0B-2)` |
| Grant, delegation, rotation, revocation, policy, credential issuance, and break-glass floor | 60 seconds | `PROPOSED (D-0B-2)` |
| `CHECKPOINT_MAX_AGE` | 15 minutes | `PROPOSED (D-0B-2)` |
| `WITNESS_CLOCK_SKEW_MAX` | 30 seconds | `PROPOSED (D-0B-2)` |
| `UNANCHORED_WINDOW_MAX` | 60 minutes | `PROPOSED (D-0B-2)` |
| `BREAK_GLASS_INCIDENT_MAX` | 60 cumulative minutes per incident | `PROPOSED (D-0B-2)` |
| `BREAK_GLASS_CROSS_INCIDENT_MAX` | 120 cumulative minutes per rolling 24 hours for the same approver set and affected boundary | `PROPOSED (D-0B-2)` |
| External time-reference set | Two independently administered NTS sources: `time.cloudflare.com` and `nts.netnod.se`; retain endpoint identity, synchronization result, and comparison time in evidence | `PROPOSED (D-0B-2)` |

`ASSUMPTION:` The run values are test-profile values, not final deployment values. `PERMISSION_NOW_MAX_STALENESS` is 5 minutes against the accepted 15-minute hard maximum; `CHECKPOINT_MAX_AGE` is 15 minutes against the accepted 60-minute hard maximum; `UNANCHORED_WINDOW_MAX` is 60 minutes against its accepted 60-minute hard maximum. D-0A-5's accepted break-glass maxima remain 60 minutes per incident and 120 minutes per rolling 24 hours; witness quorum remains the accepted floor of 2.

`ASSUMPTION:` Both proposed NTS services are reachable from all three hosts and can be treated as independently administered references. Pre-flight must pin the client configuration and capture successful authenticated synchronization; inability to authenticate either source suppresses trusted time and positive Q3 for that observation.

## 5. Read concurrency and claim mix

Run each query class in healthy, stale-checkpoint, one-witness-outage, post-rotation, and post-revocation states. The baseline is 20,000 logical reads per state; the stress row is 200,000 logical reads per state. Both use the same deterministic order and proportions.

| Claim/query class | Mix | Local proof policy | Status |
|---|---:|---|---|
| `AttributableAuthorship` / Q1+Q2 by event or subject | 30% | Verify locally on every policy-required read and a deterministic 10% sample otherwise | `PROPOSED (D-0B-2)` |
| `TamperEvidentChangeRecord` / Q3 range and completeness | 25% | Verify locally on every read | `PROPOSED (D-0B-2)` |
| `IndependentReviewAttestation` / review subject and authority | 15% | Verify locally on every read | `PROPOSED (D-0B-2)` |
| `ExternallyAuthenticatedBundle` / filtered and bundle scope | 10% | Verify locally on every read | `PROPOSED (D-0B-2)` |
| `TrustedTimestamp` / checkpoint observation | 10% | Verify witness observations locally on every read | `PROPOSED (D-0B-2)` |
| `CapabilityGrant` / permission-now | 10% | Verify locally on every read using the 60-second action floor | `PROPOSED (D-0B-2)` |
| Baseline concurrency | 8 clients: 4 Linux and 4 Windows; at most 8 outstanding reads | `PROPOSED (D-0B-2)` |
| Stress concurrency | 32 clients: 16 Linux and 16 Windows; at most 32 outstanding reads | `PROPOSED (D-0B-2)` |

The five-state stress row therefore performs 1,000,000 logical reads. Cache hits are allowed but are measured; they do not refresh a cut's witnessed observation age or bypass required local verification.

## 6. Resource envelope

Apply OS, container, database, or job-object limits as appropriate. Resource telemetry separates the writer/database group, verifier, telemetry, and each witness. Raw performance is comparable only while these caps hold.

| Host role / process group | CPU cap | RAM cap | Writable-disk cap | Status |
|---|---:|---:|---:|---|
| Candidate A writer, PostgreSQL, log, and verifier on `mvmcc03` | 4 vCPU | 8 GiB | 40 GiB | `PROPOSED (D-0B-2)` |
| Candidate B SQL Server Ledger, adapter, and external verifier on `mvmcitest01` | 4 vCPU | 8 GiB | 40 GiB | `PROPOSED (D-0B-2)` |
| Candidate C immudb, adapter/projection, and verifier on `mvmcc02` | 4 vCPU | 8 GiB | 40 GiB | `PROPOSED (D-0B-2)` |
| Each candidate-specific witness process group | 0.5 vCPU | 512 MiB | 5 GiB | `PROPOSED (D-0B-2)` |
| Telemetry/evidence capture per writer host | 0.5 vCPU | 512 MiB | 10 GiB | `PROPOSED (D-0B-2)` |
| Per-host aggregate during parallel measurement | 5.5 vCPU | 9.5 GiB | 60 GiB | `PROPOSED (D-0B-2)` |

`ASSUMPTION:` Each host has at least 6 vCPU, 16 GiB RAM, and 60 GiB free writable disk for the run. Pre-flight must inventory actual Windows capacity and storage performance. A host that cannot enforce the envelope or materially differs requires a documented equal-resource rerun before raw throughput comparison.

## 7. Recovery objectives

| Objective | Target | Measurement rule | Status |
|---|---:|---|---|
| Anchored-event RPO | No acknowledged event loss; no more than 100 accepted events or 5 minutes of uncheckpointed history | Measure against independently retained acknowledgement and checkpoint evidence | `PROPOSED (D-0B-2)` |
| Backup-only infrastructure RPO | 15 minutes maximum before authenticated replay from retained external evidence | Record backup cut and first fully reconciled cut | `PROPOSED (D-0B-2)` |
| Rollback/fork detection | 2 minutes from first attempted verification or operation | Require durable operator-visible refusal | `PROPOSED (D-0B-2)` |
| Projection rebuild RTO | 30 minutes at the 200,000-event stress size | End at byte/digest-equivalent projection | `PROPOSED (D-0B-2)` |
| Clean-host restore RTO | 60 minutes from clean-host start to first safe write | Includes artifact/profile checks, replay, external-cut consistency, witness reconciliation, and projection equivalence | `PROPOSED (D-0B-2)` |
| Witness/anchor outage recovery RTO | 30 minutes after service restoration | End at reconciled quorum and committed unanchored-range marker; no positive Q3 before completion | `PROPOSED (D-0B-2)` |

Failing a target is operational evidence, not permission to resume unsafely. The frozen security predicates still require fail-closed reconciliation regardless of elapsed time.

## 8. Lab break-glass identities

| Identity | Lab function and custody | Status |
|---|---|---|
| `bg-operator` | Bootstrap-root emergency operator using a dedicated lab account and a dedicated non-shared signing key | `PROPOSED (D-0B-6)` |
| `bg-approver` | Distinct security/governance approver using a different lab account, signing key, credential store, and session | `PROPOSED (D-0B-6)` |

The two identities may not share an account, private key, credential, session, or approval action. For the affected exercise, neither identity may also be the requester, affected-action signer, DBA, verifier operator, any required witness operator, directory/IdP administrator, secret-backend administrator, bootstrap-host administrator, release/root signer for the affected policy, or operator of the affected boundary. This is the complete `TRUST-MODEL.md` section 9 exclusion list.

`ASSUMPTION:` These are synthetic lab identities only. They do not name production people or satisfy the production organizational-role decision deferred to 0C.

`OPEN:` Owner: approve D-0B-2 and D-0B-6 as written, or identify the specific value that must change before the profile is frozen.

## 9. Summary

The proposed common run uses 20,000 baseline events and a 200,000-event stress history, bounded structured envelopes, deterministic authority transitions, checkpoints every 100 events or 5 minutes, two required witnesses, an 8-client baseline and 32-client stress read mix, equal 4-vCPU/8-GiB candidate caps, and fail-closed recovery targets. Its staleness, checkpoint, clock-skew, unanchored, retention, and break-glass values stay within the accepted 0A ceilings. Lab break-glass uses distinct `bg-operator` and `bg-approver` accounts and keys under the full section 9 exclusion list.
