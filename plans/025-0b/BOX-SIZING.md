# Phase 0B five-day-box sizing proposal

Status: coordinator proposal for owner ratification under D-0B-3. All values are elapsed hours for one candidate's assigned Sol executor run unless stated otherwise. The candidate box is 5 engineer-days = 40 hours; a mandatory-core `INCOMPLETE` at expiration remains disqualifying.

## 1. Estimation basis

`ASSUMPTION:` A Sol executor remains available continuously during its assigned run, so executor effort translates directly to wall-clock while commands are running or evidence is being checked. An estimate of 1.00 hour for a Sol-run activity means approximately 1.00 elapsed wall-clock hour, not a human staffing day.

`ASSUMPTION:` The common harness, fixtures, schemas, host access, installation media/images, independent pin path, witness accounts, and observer protocol are complete before candidate Day 1. The rubric's two shared engineer-days cover common harness preparation and final cross-candidate analysis and are outside each 40-hour candidate box.

`ASSUMPTION:` Row setup includes candidate-specific installation and adapter/configuration work. Candidate A's PostgreSQL/log setup, Candidate B's SQL Server 2022-on-Windows Ledger and external-verifier setup, and Candidate C's immudb/container setup are charged primarily to `Append`; they are not hidden pre-work.

`ASSUMPTION:` Adversary rows may reuse an earlier workload injection only when the exact injection, credentials/zones, before/after cuts, timestamps, alerts, and residuals were captured. The adversary estimate is the incremental validation and packaging cost; otherwise the full source row must be rerun and the estimate is no longer valid.

`ASSUMPTION:` Reset/recovery is the time to return to the pinned clean boundary and retain fault evidence. Packaging is incremental manifesting, digesting, and result-record work, including each row's share of final sealing.

All table values and totals are `PROPOSED (D-0B-3)`.

## 2. Candidate A: PostgreSQL, signed log, and witnessed checkpoints

| Mandatory-core row | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| Append | 2.50 | 1.50 | 0.25 | 0.50 | 4.75 | `PROPOSED (D-0B-3)` |
| Rotation | 0.25 | 1.00 | 0.25 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Revocation with effect range | 0.25 | 1.25 | 0.25 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Inclusion and consistency proof | 0.50 | 1.25 | 0.25 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Checkpoint and witness | 0.75 | 1.00 | 0.25 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Fork | 0.25 | 0.75 | 0.50 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Rollback: old DB plus old checkpoint | 0.25 | 0.75 | 0.75 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Restore security predicate | 0.50 | 1.00 | 1.25 | 0.50 | 3.25 | `PROPOSED (D-0B-3)` |
| Projection rebuild | 0.25 | 0.75 | 0.50 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Concurrency / TOCTOU | 0.50 | 1.25 | 0.25 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Unanchored outage and recovery | 0.25 | 1.00 | 0.50 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Break-glass | 0.50 | 1.25 | 0.50 | 0.50 | 2.75 | `PROPOSED (D-0B-3)` |
| **Mandatory-workload subtotal** | **6.75** | **12.75** | **5.50** | **3.75** | **28.75** | `PROPOSED (D-0B-3)` |

| Adversary scenario | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| `ADV-03` compromised provenance writer | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-12` DB writer | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-13` DB administrator | 0.25 | 0.50 | 0.50 | 0.25 | 1.50 | `PROPOSED (D-0B-3)` |
| `ADV-14` writer-zone host root | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-23` one anchor/witness operator | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| `ADV-26` writer + DBA collusion | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-27` DBA + one witness operator | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-34` emergency approver collusion | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| **Adversary subtotal** | **0.75** | **2.75** | **1.75** | **2.00** | **7.25** | `PROPOSED (D-0B-3)` |
| **Candidate A total** | **7.50** | **15.50** | **7.25** | **5.75** | **36.00** | `PROPOSED (D-0B-3)` |

Candidate A has 4.00 hours of contingency. Its principal risk rows are `Restore`, `Checkpoint and witness`, `ADV-13`, and `ADV-14`; custom log/proof integration or a slow clean-host reset can consume the margin.

## 3. Candidate B: SQL Server 2022 Ledger on Windows

| Mandatory-core row | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| Append, including SQL Server/Ledger/external-verifier setup | 3.00 | 1.50 | 0.25 | 0.50 | 5.25 | `PROPOSED (D-0B-3)` |
| Rotation | 0.50 | 1.00 | 0.25 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Revocation with effect range | 0.50 | 1.25 | 0.25 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Inclusion and consistency proof | 0.75 | 1.50 | 0.25 | 0.50 | 3.00 | `PROPOSED (D-0B-3)` |
| Checkpoint and witness | 1.00 | 1.00 | 0.25 | 0.50 | 2.75 | `PROPOSED (D-0B-3)` |
| Fork | 0.25 | 0.75 | 0.75 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Rollback: old DB plus old checkpoint | 0.25 | 0.75 | 1.00 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Restore security predicate | 0.75 | 1.25 | 1.50 | 0.50 | 4.00 | `PROPOSED (D-0B-3)` |
| Projection rebuild | 0.25 | 0.75 | 0.50 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Concurrency / TOCTOU | 0.75 | 1.25 | 0.50 | 0.25 | 2.75 | `PROPOSED (D-0B-3)` |
| Unanchored outage and recovery | 0.25 | 1.00 | 0.75 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Break-glass | 0.50 | 1.25 | 0.50 | 0.50 | 2.75 | `PROPOSED (D-0B-3)` |
| **Mandatory-workload subtotal** | **8.75** | **13.25** | **6.75** | **4.25** | **33.00** | `PROPOSED (D-0B-3)` |

| Adversary scenario | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| `ADV-03` compromised provenance writer | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-12` DB writer | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-13` DB administrator | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-14` writer-zone host root | 0.25 | 0.25 | 0.25 | 0.25 | 1.00 | `PROPOSED (D-0B-3)` |
| `ADV-23` one anchor/witness operator | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| `ADV-26` writer + DBA collusion | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-27` DBA + one witness operator | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-34` emergency approver collusion | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| **Adversary subtotal** | **0.75** | **2.50** | **1.50** | **2.00** | **6.75** | `PROPOSED (D-0B-3)` |
| **Candidate B total** | **9.50** | **15.75** | **8.25** | **6.25** | **39.75** | `PROPOSED (D-0B-3)` |

Candidate B has 0.25 hour of nominal contingency and is at risk. The 3.00-hour setup estimate assumes the Windows host, SQL Server installation media or approved image, privileges, networking, and restart window are ready before Day 1. SQL installation/reboots, Ledger digest adaptation, independent external verification, clean-host SQL restore, Windows fault injection, `ADV-13`, or `ADV-27` can overrun the box. Candidate B remains credible only as a tightly managed run with pre-flight host readiness; it is not credible if SQL Server must be acquired, licensed for production, or debugged from an unknown Windows baseline inside Day 1.

## 4. Candidate C: immudb and independent witnesses

| Mandatory-core row | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| Append, including immudb/container setup | 3.50 | 1.50 | 0.25 | 0.50 | 5.75 | `PROPOSED (D-0B-3)` |
| Rotation | 0.25 | 1.00 | 0.25 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Revocation with effect range | 0.25 | 1.25 | 0.25 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Inclusion and consistency proof | 0.75 | 1.50 | 0.25 | 0.25 | 2.75 | `PROPOSED (D-0B-3)` |
| Checkpoint and witness | 1.00 | 1.00 | 0.25 | 0.25 | 2.50 | `PROPOSED (D-0B-3)` |
| Fork | 0.25 | 0.75 | 0.50 | 0.25 | 1.75 | `PROPOSED (D-0B-3)` |
| Rollback: old DB plus old checkpoint | 0.25 | 0.75 | 0.75 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Restore security predicate | 0.75 | 1.25 | 1.25 | 0.50 | 3.75 | `PROPOSED (D-0B-3)` |
| Projection rebuild | 0.50 | 0.75 | 0.50 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Concurrency / TOCTOU | 0.50 | 1.25 | 0.25 | 0.25 | 2.25 | `PROPOSED (D-0B-3)` |
| Unanchored outage and recovery | 0.25 | 1.00 | 0.50 | 0.25 | 2.00 | `PROPOSED (D-0B-3)` |
| Break-glass | 0.50 | 1.25 | 0.50 | 0.50 | 2.75 | `PROPOSED (D-0B-3)` |
| **Mandatory-workload subtotal** | **8.75** | **13.25** | **5.50** | **3.75** | **31.25** | `PROPOSED (D-0B-3)` |

| Adversary scenario | Setup | Execution | Reset/recovery | Packaging | Total | Status |
|---|---:|---:|---:|---:|---:|---|
| `ADV-03` compromised provenance writer | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-12` DB writer | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-13` DB administrator | 0.25 | 0.50 | 0.50 | 0.25 | 1.50 | `PROPOSED (D-0B-3)` |
| `ADV-14` writer-zone host root | 0.25 | 0.50 | 0.25 | 0.25 | 1.25 | `PROPOSED (D-0B-3)` |
| `ADV-23` one anchor/witness operator | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| `ADV-26` writer + DBA collusion | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-27` DBA + one witness operator | 0.00 | 0.25 | 0.25 | 0.25 | 0.75 | `PROPOSED (D-0B-3)` |
| `ADV-34` emergency approver collusion | 0.00 | 0.25 | 0.00 | 0.25 | 0.50 | `PROPOSED (D-0B-3)` |
| **Adversary subtotal** | **0.75** | **2.75** | **1.75** | **2.00** | **7.25** | `PROPOSED (D-0B-3)` |
| **Candidate C total** | **9.50** | **16.00** | **7.25** | **5.75** | **38.50** | `PROPOSED (D-0B-3)` |

Candidate C has 1.50 hours of contingency. Its at-risk rows are initial immudb adapter/proof setup, `Restore`, projection integration, `ADV-13`, and `ADV-14`. Unsupported proof export or an unfamiliar clean-host recovery path can consume the margin.

## 5. Box comparison and credibility

| Candidate | Setup | Execution | Reset/recovery | Packaging | Total | Margin to 40 h | Wall-clock at one Sol run | Status |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| A | 7.50 | 15.50 | 7.25 | 5.75 | 36.00 | 4.00 | 36.00 elapsed hours, approximately 4.5 eight-hour working days | `PROPOSED (D-0B-3)` |
| B | 9.50 | 15.75 | 8.25 | 6.25 | 39.75 | 0.25 | 39.75 elapsed hours, approximately 5 eight-hour working days | `PROPOSED (D-0B-3)` |
| C | 9.50 | 16.00 | 7.25 | 5.75 | 38.50 | 1.50 | 38.50 elapsed hours, approximately 4.8 eight-hour working days | `PROPOSED (D-0B-3)` |

`PROPOSED (D-0B-3):` The five-engineer-day box is credible for A and C with the stated pre-flight assumptions. It is narrowly credible for B only if SQL Server-on-Windows is ready to configure at run start and the external Ledger verifier path has been rehearsed synthetically. Host-access waiting, observer scheduling, witness-operator waiting, downloads, and unscheduled Windows reboots are elapsed calendar delays even when they consume no active Sol execution; they must be resolved in pre-flight rather than charged away.

The representative read-volume row, cross-platform ergonomics, full performance percentile analysis, licensing, staffing, and operational-cost measurements are extended evidence and are not included in these mandatory-core totals. They may use remaining margin but may not displace a mandatory row. At the proposed 10x stress volume, allocate up to 4 additional wall-clock hours per candidate only after its security core is sealed; expiration makes the extended row `INCOMPLETE`, not the core.

`OPEN:` Owner: approve the 40-hour box on these assumptions. If Candidate B cannot begin from a reachable Windows host with SQL Server media/image, required privileges, restart window, and an executable external-verification path, approve a later common start after pre-flight rather than treating its 0.25-hour margin as credible.

## 6. Summary

Every mandatory workload and all eight adversary scenarios are explicitly costed across setup, execution, reset/recovery, and packaging. Candidate A totals 36.00 hours, Candidate B 39.75 hours, and Candidate C 38.50 hours. The five-day box is credible for A and C and conditionally credible for B; SQL Server/Windows readiness, clean-host restore, external proof verification, and host-root/DBA fault recovery are the rows most likely to force an overrun.
