# Plan 025 finding-control-test matrix schema

Version: v0.2-draft, 2026-08-26 (third-lineage delta review: minimax-m3, 2026-08-25). Status: DRAFT. The initial rows are deliberately provisional. This schema describes the exact 16-column charter schema; parenthetical constraints in the charter are not literal header text.

```csv
finding_id,component,reviewed_ref,mechanism,class,daybreak_severity,verified_severity,reproduction_ref,disposition,owning_boundary,control_id,invariant_ids,regression_test_ref,phase,profile_gate,notes
```

## Columns

| Column | Definition | Allowed values / format |
|---|---|---|
| `finding_id` | Filed inventory identifier; duplicates remain separate filed rows. | One exact inventory id, unique in this CSV. |
| `component` | Inventory report subsystem, not future ownership. | `trustlog`, `crypto`, `regista-cli`, `persist`, `cairn`, `dossier`, `agent-suite`, `agent-notes`, `agent-wake`, `acb`. |
| `reviewed_ref` | Commit at which the finding was reviewed, never silently replaced by a fix ref. | Lowercase seven-character git ref from the fixed component map below. |
| `mechanism` | Exactly one primary stable slug from `MECHANISM-TAXONOMY.md`. | A declared taxonomy slug. |
| `class` | Broad inventory triage class; not a mechanism. | `C1`, `C2`, `C3`, `C4`, `C5`. |
| `daybreak_severity` | Original Daybreak rating, preserved after reproduction. | `Critical`, `High`, `Medium`, `Low`. |
| `verified_severity` | Corrected severity from reviewed executable reproduction. | Blank, `Critical`, `High`, `Medium-High`, `Medium`, `Low-Medium`, `Low`. Only SEC-01 through SEC-13 are populated initially. |
| `reproduction_ref` | Stable repository-relative reference to executable probe and result. | Blank initially; later a path/ref at the reviewed commit. |
| `disposition` | Provisional or final remediation route, not proof of closure. Initial values are provisional. | `fully-closed-by-kernel`, `partially-mitigated`, `independently-patched`, `invalidated`, `deferred-profile`. |
| `owning_boundary` | Boundary accountable for the complete closing control. Initial values are provisional target-decomposition assignments, not ownership transfers. | `kernel`, `gate-engine`, `broker`, `bootstrap-root`, `app:regista-cli`, `app:agent-notes`, `app:dossier`, `app:cairn`, `transport`. Never blank. |
| `control_id` | Stable id of the accepted concrete control. | Blank initially; later `CTRL-nnn`. `ASSUMPTION:` this format requires owner confirmation. |
| `invariant_ids` | Accepted trust-model invariants established by the control. | Blank initially; later one or more `INV-nnn` values separated by `;`. |
| `regression_test_ref` | Stable repository-relative test proving the control. | Blank initially; later a path plus test node/name where applicable. |
| `phase` | Provisional planned phase in which the owning control becomes implemented and regression-tested. | `Phase 1`, `Phase 2`, `Phase 3`, `Phase 4`, `Phase 5`, `Phase 6`, `Migration`. |
| `profile_gate` | Provisional deployment-profile family whose enabled graph requires closure. | `core`, `capability`, `transport`. |
| `notes` | Concise provenance, uncertainty, dedup, residual, and provisional-state information. | Start with `sub_boundary=<slug>` so the accountable surface is derivable without changing the charter's 16-column header; then use `ASSUMPTION:` for assumptions and `OPEN:` for owner questions. For a residual use `residual_owner=<boundary>`. |

Fixed reviewed refs: all four Regista-family components use `7707c81`; cairn `74471ad`; dossier `d775b6d`; agent-suite `a153213`; agent-notes `235c2b6`; agent-wake `f6a0eed`; acb `f2df972`.

## Rules

1. The file has exactly 147 data rows and each inventory finding id appears exactly once. Deduplication never removes a row.
2. `mechanism`, provisional `disposition`, provisional `owning_boundary`, provisional `phase`, and provisional `profile_gate` are nonempty on every initial row. All remain proposals while `control_id` and `regression_test_ref` are blank; 0A freezes no component ownership.
3. A `fully-closed-by-kernel` row MUST cite at least one accepted `INV-nnn`; the kernel alone must close the complete exploit under that invariant's stated adversaries. Until then use `partially-mitigated` and name residual ownership in notes.
4. `independently-patched` names the intended non-kernel remediation route; it does not assert implementation. Closure additionally requires `control_id`, applicable `invariant_ids`, and `regression_test_ref`.
5. `deferred-profile` is a per-finding determination, never a component default. Notes MUST name the signed profile (`profile=<stable-id>`) and state the finding-specific structural-unreachability proof: no deployed code, route/service/executable, identity, secret/grant/plugin/network edge, or enabled-principal invocation edge, plus the negative reachability test. It must change before a profile enabling that surface cuts over. An existing developer-host path is not profile-deferrable.
6. `invalidated` requires an attempted reproduction whose reviewed verdict is `invalidated`; `not-reproducible` alone never invalidates a row. The charter has no reproduction-verdict column, so the verdict remains in the referenced reproduction record and is summarized in notes.
7. A nonempty `verified_severity` requires reviewed reproduction evidence. The initial exception is documentary rather than substantive: SEC-01 through SEC-13 cite the already completed Opus verdicts summarized by the inventory; later work fills their `reproduction_ref` with stable evidence-repo references.
8. Preserve `daybreak_severity`; derive effective severity as `verified_severity` when nonempty and `daybreak_severity` otherwise. Never overwrite one with the other.
9. Shared mechanisms may later share controls, invariants, and tests, but each filed finding retains an independently auditable row and its dedup note.
10. Standard RFC 4180 CSV quoting applies. Quote every field containing a comma, quote, CR, or LF; represent a literal quote by doubling it.
11. `profile_gate` is applicability, not current readiness. `core` includes provenance, governance, bootstrap, and app surfaces; `capability` covers broker-enabled profiles; `transport` covers agent-wake-enabled profiles.
12. Phase means control-delivery phase under plan section 8, not discovery or reproduction phase. Phase 1 rows are the minimum vertical-slice controls; Phase 2 completes kernel paths; Phase 3 completes governance/agent-notes; Phase 4 dossier; Phase 5 broker/transport; Phase 6 bootstrap; `Migration` handles legacy/history boundaries.
13. Every row's `owning_boundary` and leading `sub_boundary=<slug>` MUST be derivable from its taxonomy mechanism entry. A mechanism with split ownership must state the per-finding split. The sub-boundary token is metadata inside `notes`, not a seventeenth column.
14. The six-level effective scale maps to the inventory's four-column summary as follows: `Critical -> Critical`; `High` and `Medium-High -> High`; `Medium` and `Low-Medium -> Medium`; `Low -> Low`. Selection continues to use all six levels.

## Reproduction updates

1. Run the probe against the row's immutable `reviewed_ref`; do not change that field when main advances.
2. Set `reproduction_ref` to the committed probe/result record after an attempt. That record carries observed outcome, one of `confirmed`, `confirmed-at-different-severity`, `not-reproducible`, or `invalidated`, corrected severity reasoning, and second-lineage review.
3. Populate or correct `verified_severity` only from that reviewed result. Record severity/reachability caveats in notes.
4. Change `disposition` only when the result or accepted design changes the remediation route. `confirmed` does not by itself prove closure; `not-reproducible` does not imply `invalidated`.
5. When a control lands, populate `control_id`, accepted `invariant_ids`, and `regression_test_ref` together as applicable, then reassess owning boundary, phase, disposition, and profile applicability.
6. If taxonomy membership or verified severity changes which mechanisms are High-bearing, recompute and document representative-High coverage before the 0A freeze gate.

## Provisional decisions

- `ASSUMPTION:` The inventory's report-level component labels are normative for matrix rows and mechanism counting; logical products are used for cross-component probe diversity.
- `ASSUMPTION:` No initial row is `fully-closed-by-kernel` because no accepted concrete control and regression test has yet been cited.
- `ASSUMPTION:` `Phase 1` membership marks controls required by the first vertical slice, not reuse of the vulnerable implementation.
- `ASSUMPTION:` Existing acb and agent-wake developer-host paths remain reachable and therefore use `partially-mitigated` with broker/transport residual ownership; future truly absent surfaces may use `deferred-profile` only under rule 5.
- `OPEN:` Confirm the proposed `CTRL-nnn` namespace and semicolon encoding for multiple invariant ids.
- `OPEN:` Confirm whether phase/profile values should later become signed-manifest identifiers rather than the coarse families used in 0A.
