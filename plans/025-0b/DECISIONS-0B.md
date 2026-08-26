# Phase 0B — owner decision list

From `0B-PLAN.md` `OPEN:` items, filtered by the reviewer (minimax) into what is genuinely the owner's. Coordinator-decidable items (harness layout, encoding, adapter shape, day ordering, resource envelope proposals, conformance-suite shape) are handled by Fable without a pause.

| # | Decision | Recommended default | Where it bites |
|---|---|---|---|
| D-0B-1 | **INV-016 witness-independence posture for the bake-off.** (i) name six distinct operator/admin/custody/persistence assignments, or (ii) simulated-independence declaration (design-supports measured; single operator an explicit residual; real independence a deployment-profile requirement at cutover). | **(ii)** — tests the substrate property honestly without pretending the lab has three organisations; consistent with "few waves". | `0B-PLAN.md` §1.2, §6 item 0; rubric §7.1 INV-016 gate is recorded as *design-supports*, not PASS. |
| D-0B-2 | **Scale profile** — event count, payload distribution, read concurrency/mix, checkpoint cadence, witness quorum (=2), resource envelope, RPO/RTO targets; the D-0A-4 maxima as ceilings. | Coordinator proposes concrete numbers in `0b-harness/scale-profile.md` for a one-word approval. | Rubric §3 `OPEN`; all measurements. |
| D-0B-3 | **Five-engineer-day box per candidate** — approve after the coordinator records expected hours per mandatory-core row. | Expect approval; executors are Sol runs, so the constraint is wall-clock and host access, not people. | Rubric §1.6; `0B-PLAN.md` §4. |
| D-0B-4 | **Candidate B licensing** — Developer edition is lab-only; name the production-licensable SQL Server 2022 edition/entitlement for the target environment, or record as unknown until the environment exists. | Record as `OPEN` until the environment exists; B's environment-fit weight stays withheld. | Rubric §8; `0B-PLAN.md` §5. |
| D-0B-5 | **mvmcitest01 access for candidate B and crypto-4** — confirm the Windows host is available for ~1 week of SQL Server + probe work, and a fallback date if not. | Confirm; fallback = sequence B after A/C. | `0B-PLAN.md` §1.1, §8. |
| D-0B-6 | **Break-glass approver pool for the INV-049/055 exercises** — lab-only role names (two distinct identities) so the harness can exercise the flow; production roles remain a 0C item (D-0A-5). | Coordinator names two lab identities (`bg-operator`, `bg-approver`) — owner ratifies. | `0B-PLAN.md` §2.5; TRUST-MODEL §9. |

Already decided: D-0A-9 parallel one-candidate-per-host; D-0A-4/5 maxima as ceilings.
