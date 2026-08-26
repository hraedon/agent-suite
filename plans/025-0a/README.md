# Plan 025 — Phase 0A charter: work products, owners, acceptance criteria

- **Parent:** `plans/025-provenance-security-remediation.md` v3.1 §8 (0A). D1/D2 approved 2026-08-25.
- **Purpose of this file:** the "startup inputs" Sol's round-3 review required before 0A-1 begins — so the implementer never has to infer scope, owner, or done-ness.
- **Raw evidence:** `~/projects/personal/plan-025-evidence/` (local git repo; mirror to mvmcc02 before any 0A-2 work runs there). Inventory copy: `plans/025-evidence/CONSOLIDATED-INVENTORY.md`.

## Roles

| Role | Who | Notes |
|---|---|---|
| Owner (decisions, gates) | Paul | signs each 0A work product |
| Drafter | GPT-5.6 Sol (codex/opencode headless) | writes 0A-1, 0A-3, 0A-4 first drafts; cross-lineage to reviewer |
| Reviewer / coordinator | Claude Fable (mvmcc03) | reviews every draft; owns 0A-2 orchestration; reconciles |
| Reproduction executors | Claude Opus probe-executors + Daybreak Blue | 0A-2; each reproduction is an executable probe, not prose |
| Second reviewer on anything that becomes a gate | a third lineage (deepseek/glm/kimi, whichever completes) | the WI-008 two-reviewer rule applies to 0A-1's invariant registry and 0A-3's matrix schema |

Lineage rule: no work product is accepted on the drafter's lineage alone.

## Work products

### 0A-1 — Trust model + invariant registry → `plans/025-0a/TRUST-MODEL.md`

Content (template in §"Trust-model template" below): assets; data flows; trust zones (writer / verifier / witness / gate engine / broker / bootstrap root / apps); the three provenance questions (authentication, authorisation-at-position, completeness/non-equivocation); temporal authority semantics incl. revocation-with-effect-range; adversary catalogue with capabilities and colluding combinations; claim-by-adversary matrix; degraded-state + freshness semantics; break-glass authority (who may invoke, how audited); legacy v1–v5 evidence decision (reject / quarantine / re-anchor); PHI data-boundary design (§1 of the plan, five required elements); residuals.

**Invariant registry:** every guarantee gets a stable id `INV-nnn`, a statement, the adversaries it resists and does not, the boundary that owns it, and the test family that will prove it. Cutover gates and the matrix reference invariants by id only.

**Acceptance:** every adversary in plan §4 has an entry; every claim names resisting and non-resisting adversaries; no invariant without a named test family; legacy decision recorded; PHI section covers all five elements; two-reviewer pass (Sol draft → Fable → third lineage); owner sign-off.

### 0A-2 — Reproductions + mechanism taxonomy → `plans/025-0a/REPRODUCTIONS.md` + probes in the evidence repo

**Mechanism taxonomy:** each of the 147 findings is tagged with a *mechanism* (finer than C1–C5), e.g. `row-vs-envelope-unreconciled`, `caller-supplied-time-as-authority`, `retired-key-accepted-for-historical-verify`, `retired-credential-accepted-for-new-action`, `pathname-as-executable-identity`, `signature-missing-context-binding:<field>`, `truthy-exit-code`, `unsigned-op-default`, `unbounded-parse`, `toctou-lifecycle`, … The taxonomy is written *before* selection and committed.

**Selection rule for representative Highs:** for every mechanism that contains ≥1 High, reproduce the highest-severity finding in that mechanism *in the component with the most findings of that mechanism*; if the mechanism spans components, additionally reproduce one in a second component. All 7 Criticals are reproduced unconditionally.

**Each reproduction:** an executable probe (pytest or script) at the reviewed ref, its observed outcome, the verdict `confirmed / confirmed-at-different-severity / not-reproducible / invalidated`, and the corrected severity with reasoning. Non-reproducible ≠ invalidated: state which.

**Acceptance:** all Criticals attempted; every High-bearing mechanism has ≥1 attempted reproduction; probes committed and re-runnable; verdicts reviewed by a second lineage; inventory severities updated with a `verified` column.

### 0A-3 — Finding→control→test matrix → `plans/025-0a/MATRIX.csv` (+ schema in `MATRIX-SCHEMA.md`)

Committed schema (one row per finding):

`finding_id, component, reviewed_ref, mechanism, class(C1–C5), daybreak_severity, verified_severity, reproduction_ref, disposition (fully-closed-by-kernel | partially-mitigated | independently-patched | invalidated | deferred-profile), owning_boundary (kernel | gate-engine | broker | bootstrap-root | app:<name> | transport), control_id, invariant_ids, regression_test_ref, phase, profile_gate, notes`

**Acceptance:** 147 rows present with at least `mechanism`, `disposition (provisional)`, `owning_boundary`; every `fully-closed-by-kernel` row cites an `INV-` id; no row with an empty owner; schema reviewed by a second lineage (this schema is itself gate infrastructure).

### 0A-4 — Admissibility hypotheses + data-boundary analysis → `plans/025-0a/ADMISSIBILITY-MAP.md`, `plans/025-0a/DATA-BOUNDARY.md`

Per kernel claim (working names only; vocabulary finalised in 0C): the paradigm it hypothesises isomorphism to; the precedent citation; **the failure mode that would break the analogy** (e.g. `TrustedTimestamp` without an accepted TSA; lineage diversity mistaken for segregation of duties); the independence policy for review attestations; validation status (`internal-hypothesis` until D3 stage 2). `DATA-BOUNDARY.md`: allowed-content definition, minimisation, scanning/refusal, opaque-artifact handling, quarantine/deletion/incident procedure, residual statement.

**D3 posture (owner 2026-08-25):** stage 1 only — internal draft; an informal non-binding read *only if a low-friction opportunity arises*; formal review deferred. Every entry stays marked `internal-hypothesis` until then.

**Acceptance:** every claim has a failure mode and a validation status; no entry claims acceptance; Fable + Sol concur; owner sign-off.

### 0A-5 — 0B scoring rubric (frozen before any measurement) → `plans/025-0a/BAKEOFF-RUBRIC.md`

Candidates A/B/C; the falsification workload (append, rotation, proof, checkpoint, fork/rollback, restore, representative reads); the adversary scenarios from 0A-1 by invariant id; the operational-requirements table columns (plan §6); weights; and the **premise-validation checklist for B** (SQL Server edition/licensing, DBA capability, HA/restore practice, digest-management support, witness independence outside the SQL Server/DBA failure domain). Language/stack *criteria* (portability, Windows ops, FIPS/HSM, deployment, staffing) recorded here for 0C.

**Acceptance:** rubric committed before 0B starts; no candidate pre-scored; two lineages concur.

## 0A exit (freeze gate)

All five accepted; Criticals reproduced; every High-bearing mechanism attempted; matrix populated; rubric frozen. Then 0B. *No API, repo layout or component ownership is frozen by 0A.*

## Trust-model template (for 0A-1)

```
# TRUST-MODEL — <version>, <date>, <reviewed refs>

## 1. Assets            what is protected (events, authority state, checkpoints, claims, keys, policies, projections)
## 2. Data flows        producer → store → verifier → consumer, per flow; which zone each hop lives in
## 3. Trust zones       writer | verifier | witness | gate engine | broker | bootstrap root | apps | transport
                        for each: what it can assert, what it must prove, what it may never be trusted for
## 4. Questions         Q1 authentication · Q2 authorisation-at-position · Q3 completeness/non-equivocation
                        how each is answered, by which zone, against which pinned input
## 5. Temporal semantics authority-at-position · permission-now · verifier-knowledge-at-cut · revocation-with-effect-range
## 6. Adversaries       id, capabilities, zones compromised — user, service principal, compromised component,
                        DB writer, DB admin, host root, verifier operator, anchor/witness operator, signer-key holder,
                        collusions (enumerate)
## 7. Claims            per claim: fields, issuing zone, resists {adversary ids}, does NOT resist {adversary ids}
## 8. Invariants        INV-nnn · statement · owning boundary · resists / does-not-resist · test family
## 9. Degraded state    what happens when authority resolver / anchor / witness / verifier is unavailable;
                        cache freshness rules; recovery; break-glass authority + audit
## 10. Legacy evidence  v1–v5 decision and its boundary
## 11. Data boundary    PHI non-goal — the five elements
## 12. Residuals        what remains unprotected, stated plainly
```
