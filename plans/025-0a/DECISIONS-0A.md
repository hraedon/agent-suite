# Phase 0A — owner decision list

Consolidated from the `OPEN:` markers in `TRUST-MODEL.md` v0.3 (accepted by three lineages:
Sol draft → Fable + Opus review → minimax third-lineage verdict *accept*), `DATA-BOUNDARY.md`,
`MECHANISM-TAXONOMY.md`, and `BAKEOFF-RUBRIC.md`. Each item carries the drafters' recommended
default so a one-word answer suffices. None blocks drafting; all block **0A exit**.

| # | Decision | Recommended default | Where it bites |
|---|---|---|---|
| D-0A-1 | **Free text in kernel events** — (a) forbid entirely, or (b) redactable-by-construction (salted per-field digest in chain, plaintext in a deletable side store). | **(a) forbid.** Ties directly to the PHI non-goal; (b) consciously narrows that non-goal and creates incident liability. | `TRUST-MODEL.md` §11.5, INV-046/048 (inactive under (a)); `DATA-BOUNDARY.md` §1 "approved short text" class is then dropped. |
| D-0A-2 | **Legacy v1–v5 evidence** — reject / quarantine-as-unverifiable / one-time re-anchor. Must be decided before the first slice admits any legacy evidence. | **quarantine-as-unverifiable**, converting to rejection after a dated compatibility window. | `TRUST-MODEL.md` §10, INV-050; migration phase entry gate. |
| D-0A-3 | **Retroactive revocation policy** — issuer roles, maximum lookback, dual-control roles, whether finite `effect_through` is allowed. | Deny issuance until set (current behaviour); propose: bootstrap-root operator + security approver as dual control; lookback unbounded; finite effect-through allowed. | §5, INV-013, INV-028. |
| D-0A-4 | **Staleness / cadence parameters** — `PERMISSION_NOW_MAX_STALENESS`, per-action floors, `CHECKPOINT_MAX_AGE`, `WITNESS_CLOCK_SKEW_MAX`, `UNANCHORED_WINDOW_MAX`, `WITNESS_RETENTION_MIN`, external time-reference set. | Defer to **0C** with 0B evidence; keep v0.3's proposed hard maxima (15 min / 60 min) as the ceiling the bake-off must meet. Propose `WITNESS_RETENTION_MIN` = 7 years (development artifacts, non-PHI) for 0B costing. | §9, INV-011/012/015/055/058. |
| D-0A-5 | **Break-glass** — organisational roles for the two approvers; `BREAK_GLASS_INCIDENT_MAX` (proposed 60 min cumulative/incident) and `BREAK_GLASS_CROSS_INCIDENT_MAX` (proposed 120 min per rolling 24 h, same approver set). | Accept proposed caps for 0B costing; name roles at 0C. | §9, INV-049/055. |
| D-0A-6 | **Data-boundary incident roles** — incident owner, notification path, deletion authority, retention/legal-hold policy. | Placeholders until the target environment exists; must be named before any production data. | `DATA-BOUNDARY.md` §5, INV-048. |
| D-0A-7 | **Reproduction-set size** — accept ~78 probes (72 of the 80 ≥High findings, all 7 Criticals) or merge near-synonymous singleton mechanisms first. | **Accept 78.** Owner posture is "no rush, do it right"; 90 % of severe findings reproduced before freeze is the point. | `MECHANISM-TAXONOMY.md` selection semantics; `REPRODUCTIONS.md`; 0A-2 executor budget (Opus + Daybreak on mvmcc02). |
| D-0A-8 | **Taxonomy tie-break and "High-bearing = effective severity ≥ High" definitions** (changing either recomputes the set). | Accept as written. | `MECHANISM-TAXONOMY.md` §Selection semantics. |
| D-0A-9 | **Bake-off time box** — size the box against the mandatory security core before the rubric freeze (v0.3 rubric proposes 5 engineer-days/candidate, flagged as likely short by Opus B18). | Decide after Sol's round-2 rubric lands; expect to widen. | `BAKEOFF-RUBRIC.md` §3, §1.6. |
| D-0A-10 | **Control-id namespace** — `CTRL-nnn` format for the matrix `control_id` column and the taxonomy `OPEN:` on counting/tie-break rules (overlapping OPENs in `MATRIX-SCHEMA.md` and `MECHANISM-TAXONOMY.md`). | Accept `CTRL-nnn`; counting rules as written (see D-0A-8). | `MATRIX-SCHEMA.md` §Columns; `MECHANISM-TAXONOMY.md` §Selection semantics. |

Already decided (2026-08-25): D1 four-boundary decomposition; D2 Phase-0A go; D3 compliance
validation stage 1 only (informal, opportunistic), stage 2 deferred.

Sign-off record: `TRUST-MODEL.md` v0.3 — owner: ______ date: ______
