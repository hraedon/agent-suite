# Claims ledger index

**Plan 008 §6.1 / WI-0.2**

Quick-reference index for [`claims-ledger.md`](claims-ledger.md). A reviewer
can see at a glance what is proven vs. provisional.

## Maturity summary

| ID | Title | Maturity | Enforcing component | Holistic review |
|----|-------|----------|---------------------|------------------|
| CL-001 | Event integrity | supported | regista | — |
| CL-002 | Per-principal attribution | experimental | regista | — |
| CL-003 | Tamper detection | supported | agent-suite + regista | — |
| CL-004 | Cross-face interop | supported | agent-suite | — |
| CL-005 | Post-restore integrity | supported | agent-suite | — |
| CL-006 | Idempotent bootstrap | supported | agent-suite | — |
| CL-007 | Honest health | experimental | agent-suite | F-6 |
| CL-008 | Secret safety | experimental | agent-suite + regista | F-4 |
| CL-009 | Lock integrity | supported | agent-suite | — |
| CL-010 | Key rotation safety | experimental | regista | — |
| CL-011 | Delegation chain | experimental | regista | — |
| CL-012 | External anchoring | experimental | regista | F-1, F-3 |
| CL-013 | Offline verification | experimental | agent-provenance | F-2 |
| CL-014 | Upgrade safety | supported | agent-suite | — |

## Maturity counts

| Maturity | Count | Claims |
|----------|-------|--------|
| supported | 7 | CL-001, CL-003, CL-004, CL-005, CL-006, CL-009, CL-014 |
| experimental | 7 | CL-002, CL-007, CL-008, CL-010, CL-011, CL-012, CL-013 |
| provisional | 0 | |

## Holistic review findings mapped to claims

| Finding | Severity | Claim | Status |
|---------|----------|-------|--------|
| F-1 | Critical | CL-012 | Experimental — anchor commits to content; bundle v2 export + offline verification incl. event signatures |
| F-2 | Critical | CL-013 | Experimental — live proof PASSED against a real Claude Code session 2026-07-11 |
| F-3 | High | CL-012 | Experimental — receipt concurrency safe; cross-segment chain verification implemented |
| F-4 | High | CL-008 | Experimental — deployment evidence contains identifiers |
| F-5 | High | — (agent-notes) | Not a suite-level claim; tracked in agent-notes |
| F-6 | High | CL-007 | Experimental — fail-honest fix applied but legacy path remains |

## README Status section mapping

Every claim in the README "Status" section maps to a ledger entry:

| README claim | Ledger entry |
|--------------|--------------|
| `doctor` — health umbrella with key-rotation and store-growth checks | CL-007 |
| `lock` — `SUITE.lock` compatibility manifest with drift detection | CL-009 |
| Suite-interop CI — drives one work-item across both faces, verifies mixed chain | CL-004 |
| Tamper-detection negative test — forged events, spoofed actors, mutated bodies detected | CL-003 |
| `bootstrap` — ordered idempotent install | CL-006 |
| `verify-restore` — proves a restored store is cryptographically intact | CL-005 |
| `upgrade` — evidence-based transition with rollback | CL-014 |
| `schedule` — OS-scheduled backups with verify-restore and doctor+alerting | CL-005, CL-007 |
| `alert-check` — run doctor, emit state-change alerts | CL-007 |
| Key-rotation age + store-growth watch in doctor | CL-007, CL-010 |
| Operator docs — secret-backend runbooks | CL-008 |

## Deployment profiles

| Profile | Description | Required components |
|---------|-------------|---------------------|
| **A** | Provenance core | regista, agent-notes, agent-provenance, agent-suite |
| **B** | Team workflow | Profile A + dossier |
| **C** | Operated full suite | Profile B + agent-capability-broker, agent-wake |

See Plan 008 §3 for the full profile definitions.
