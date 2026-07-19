# Gate 0 Ratification — inputs for the owner

**Status:** Drafted 2026-07-19 by GLM-5.2 to surface the Workstream 4 owner decisions Sol called out. The agent has prepared the inputs; the owner makes the calls.

## Summary

Gate 0 closes when the machine-readable status is complete, reproducible from a clean checkout, and the four WI-0.x acceptance criteria are met. WS1, WS2, WS3 are landed. WS4 needs three owner decisions, captured below.

## Decision 1 — Ratify the support matrix values (or label as targets)

`data/support-matrix.json` currently declares:

| Surface | Status today | Question for owner |
|---------|--------------|--------------------|
| Python 3.12/3.13/3.14 | supported | Ratify, or downgrade 3.14 to target until CI is green on 3.14? |
| Postgres 18+ | supported | Ratify. |
| Docker | supported | Ratify. |
| Kubernetes | optional | Ratify (stays optional). |
| Windows 10/11/Server 2022 | `unit_tests_only` qualification | Keep as documented, or downgrade to target until Gate 4? |
| Chrome / Firefox / Safari / Edge | `not_qualified` | Keep as `not_qualified` until Gate 1 WI-1.6? |
| Identity: LOCAL | supported | Ratify (CI-tested via interop). |
| Identity: ENTRA_OIDC | `not_qualified` | Keep as `not_qualified` until dossier Plan 020? |
| Secret: VAULT / AKV / WINDOWS_NATIVE | `not_qualified` | Keep until backend CI-qualified? |
| Profile A release_status | `in_qualification` | Stay until Gate 0 closes? |
| Profile B release_status | `in_qualification` | Stay until Gate 0 closes? |
| Profile C release_status | `preview` | Stay until core closes? |
| Availability objectives | targets | Ratify as targets or downgrade? |

**Default action if no owner ruling:** leave the values as documented; they already honestly distinguish "supported" from "not_qualified" and "in_qualification." WI-0.3 is satisfied by the matrix validating against its schema — the values themselves are ratification input, not blocker.

## Decision 2 — Record dogfood deployed versions

The committed `data/candidate-inventory.json` was untracked because committing a live-state snapshot is self-stale (Sol round-2 finding #2). The inventory CLI now reads `*_DEPLOYED_VERSION` env vars per constituent; the operator can record deployed versions in suite.env and the live inventory will report them.

**Action for owner:** add the following to `~/.config/agent-suite/suite.env` on the dogfood host (real values to be filled in by the operator):

```
AGENT_SUITE_DEPLOYED_VERSION=1.0.0-dev
REGISTA_DEPLOYED_VERSION=0.5.1
DOSSIER_DEPLOYED_VERSION=0.0.1
AGENT_NOTES_DEPLOYED_VERSION=1.0.0
AGENT_PROVENANCE_DEPLOYED_VERSION=0.1.0
AGENT_CAPABILITY_BROKER_DEPLOYED_VERSION=0.1.0
AGENT_WAKE_DEPLOYED_VERSION=0.1.0
```

**Default action if no owner ruling:** the inventory continues to report `deployed_version: null` per constituent. WI-0.2's broader AC ("record deployed version per constituent") is partially met — schema landed, dogfood data not yet recorded.

## Decision 3 — Git history publication policy

One historical Git object still contains the deleted proof path (`golden/local/convergence-proof-20260718T232221Z.md`). The current tree is clean; the issue is in history only.

The canonical identifier denylist (`~/.config/agent-suite/forbidden-identifiers`) forbids el-rio (work-domain) identifiers only. Lab identifiers (`hraedon`, `mvm*`, `itadmin`, `mvmpostgres01.ad.hraedon.com`, `hindsight-api.k8s.hraedon.com`) are ALLOWED in public repos per the publication-prep skill. The repo is currently private.

**Three options:**

1. **No action.** The repo stays private; lab identifiers are allowed in public repos anyway; no public flip is imminent. The tracked tree is clean.
2. **Scrub history via `git filter-repo`.** Remove the path from every historical object. Rewrites all SHAs and requires force-push. Owner-gated per the publication-prep skill. Use `--replace-text` AND `--replace-message`.
3. **Quarantine the sensitive commit.** Mark a specific commit as publication-blocked; do not flip public until that commit is at least N releases behind HEAD.

**Recommendation:** Option 1 today (the repo is private). If/when the owner decides to flip public, re-evaluate against the canonical denylist at that time. Option 2 only if the denylist rules at that future time require it.

## Reconciliation — constituent plan statuses

The inventory reads each constituent's newest plan status. They are:

| Constituent | Latest plan status |
|-------------|-------------------|
| agent-suite | Proposed (Plan 017 — planning baseline) |
| regista | In Progress (Phase 0 non-durable public contract foundation) |
| dossier | Proposed 2026-07-18 |
| agent-notes | Proposed 2026-07-18 |
| agent-provenance | Core adapter + plugin + honest doctor landed |
| agent-capability-broker | Proposed 2026-07-18 (WI-011) |
| agent-wake | In Progress — human delivery landed; operational loop remains |

These statuses are honest. The next-plan-status read is best-effort; if the owner wants a specific plan to be the canonical status source, the inventory's `_probe_plan_status` can be pointed at it.

## WI-0.x acceptance status

| WI | Acceptance criterion | Status | Notes |
|----|----------------------|--------|-------|
| WI-0.1 | Every feature-matrix row emitted by a named probe | **MET** | `status_source: probe-emitted`; proof command `python3 scripts/feature-probes.py --check` exits 0. |
| WI-0.2 | Record the state of every constituent; do not publish from dirty/ahead workspace | **PARTIALLY MET** | Schema complete (origin, ahead, behind, dirty, plan, deployed, umbrella, source_tree_converged fail-closed); proof command validates. Deployed versions for the dogfood estate are unrecorded (Decision 2). |
| WI-0.3 | Ratify the 1.0 support matrix | **MET (pending owner ratification)** | `SupportMatrix.default().validate()` passes; canonical JSON loads cleanly. The matrix *values* are Decision 1 input. |
| WI-0.4 | Establish the release board | **MET** | `ReleaseBoard.default().validate()` passes; canonical JSON loads cleanly. |

**Owner action:** if the owner ratifies Decisions 1 and 2 (or accepts the default actions), WI-0.1, WI-0.3, and WI-0.4 can be marked complete. WI-0.2 requires Decision 2 (recording deployed versions) before its broader AC is fully met.
