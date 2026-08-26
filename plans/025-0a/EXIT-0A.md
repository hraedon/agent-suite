# Phase 0A — exit gate record

Declared: 2026-08-26 00:00 MST (coordinator: Claude Fable). Charter: `README.md` §"0A exit (freeze gate)".

| Freeze-gate criterion | Status | Evidence |
|---|---|---|
| All five work products accepted | **met** | 0A-1 TRUST-MODEL v0.3 (Sol → Fable + Opus → minimax third lineage: *accept*; owner-accepted 2026-08-25). 0A-2 taxonomy + REPRODUCTIONS (Opus rework → Sol → minimax *accept-with-changes*, applied). 0A-3 matrix (same chain; `invariant_ids` populated from v0.3, Fable scripted check clean). 0A-4 map + data boundary (minimax *accept-with-changes*, applied). 0A-5 rubric (Opus rework → Sol → minimax; Fable cross-check; frozen below). |
| All Criticals reproduced | **met** | 7/7 confirmed (`plan-025-evidence/probes/critical/`), second lineage CONCUR. |
| Every High-bearing mechanism attempted | **met** | 78-row set: 72 confirmed, 5 confirmed-at-different-severity, 1 not-reproducible (crypto-4, Windows DPAPI — pending Windows executor; not invalidation). 0 invalidated. Second lineage (minimax) CONCUR on all executed rows; 3 CONCUR-AT-DIFFERENT-SEVERITY (cairn-05→Medium, an-9→High, acb-9 High as property check). |
| Matrix populated | **met** | 147 rows; mechanism, provisional disposition, owning boundary, `invariant_ids` on every row; 15 fully-closed-by-kernel each citing owned invariants; `control_id`/`regression_test_ref` blank by design (filled per phase). |
| 0B scoring rubric frozen | **frozen at this commit** | `BAKEOFF-RUBRIC.md` at the revision of this record; two lineages (minimax + Fable check) concur; owner D-0A-9 = parallel candidates, one per host. Time box: owner to size against the mandatory security core before measurement starts (rubric §1.6 `OPEN` → to be closed in `0B-PLAN.md`). |
| Owner decisions | **met** | `DECISIONS-0A.md` D-0A-1..11 decided 2026-08-25. |

**Not frozen by 0A (by design):** API, repository layout, component ownership, implementation stack — all 0C.

**Carried forward:**
- crypto-4 Windows reproduction (mvmcitest01 or the target environment) — before 0C protocol acceptance.
- Opus confirmatory pass on TRUST-MODEL v0.3 and batch-1 Critical verdicts once the personal-account session limit resets (00:29 MST 2026-08-26) — advisory; the charter's lineage requirement is already met.
- D-0A-11 session-capture store — 0C design input; Phase-1 slice scope.
- Deployment values (staleness maxima, break-glass roles/caps, incident roles) — 0C, after 0B evidence.

Lineage record: drafter/executor **openai/gpt-5.6-sol**; reviewer 1 **anthropic/claude-fable** (mvmcc03); reviewer 2 **anthropic/claude-opus** (mvmcc02, on 0A-1 v0.1 and 0A-2/3/5 round 1); third lineage / verdict second lineage **ollama-cloud/minimax-m3**. kimi-k3 and deepseek-v4-flash stalled and produced no reviews.
