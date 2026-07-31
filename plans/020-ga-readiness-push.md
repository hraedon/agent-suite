# Plan 020 — GA readiness push

**Status: ACTIVE** (opened 2026-07-31). Goal: the suite is deployable the day
the work environment is ready. This plan is the single ordered list of what
stands between 1.0.0-rc.2 and that. It supersedes ad-hoc tracking in session
handoffs; each lane names its owning work items so progress is visible in the
tracker rather than in prose.

## Where the line is

RC2 (`1.0.0-rc.2`) pins all six components at reviewed, merged mains and is
deployed from artifacts to both dev hosts. Both hosts' components report
healthy; the estate's remaining gaps are **not** "does the software run" but
"has it been proven on a clean host, under real custody, with operations and
multi-user lifecycle exercised." Those are Lanes C–F.

Two structural defect classes surfaced during RC2 and shape this plan:

1. **Unbounded work on routine paths.** cairn `doctor` replayed the whole
   chain (WI-030); dossier `/healthz` replayed every project's chain per
   request (dossier WI-034, ~2 GiB/probe, OOM). Both are fixed. The lesson is
   a review question, now standing: *does this endpoint's cost grow with
   production history?* Anything answering yes must not sit on a health,
   probe, or startup path.
2. **Set-but-unverified configuration.** The estate's one production `vault:`
   ref was broken three ways at once (wrong mount, `#field` syntax that never
   resolved, missing `hvac` so the provider never registered) while doctors
   reported healthy, because they check that a ref is *set*. Verification, not
   presence, is the contract (agent-suite WI-034, WI-036).

## Lanes

Lanes A/B/D/E are code work and run in parallel. Lanes C/F are estate
exercises that depend on nothing but time and hosts, and are the real GA
gate — do not let code lanes crowd them out.

### Lane A — replay is safe to call repeatedly (regista WI-217)
Full replay retains ~2 GiB per invocation and never releases it (measured:
102 MiB → 2.09 GiB → 4.07 GiB over two rounds in one process). Health paths
no longer call it, but every on-demand path does: dossier's
operations/evidence integrity views, `agent-suite verify-restore`, and
`cairn integrity` on a schedule. Until this is fixed, no long-lived process
may run replay twice. **Exit:** steady-state memory after N replays is flat;
tracemalloc evidence in the work item.

### Lane B — honest doctor on artifact installs (agent-suite WI-036, WI-035)
Wheel-installed components carry no VCS revision by construction, so lock
checking must degrade to version-only *and* gain the artifact-era
strengthening: verify installed wheel hashes against the release manifest's
`wheel_sha256` (Gate 2 now records all six). Also decide `--profile`
semantics: a Profile-B host with unconfigured C-tier CLIs present can never
be green today. Plus umbrella-wheel attestation and version alignment.
**Exit:** `agent-suite doctor --exit-code` green on a wheel-only host with
manifest-verified artifacts; `--profile` scopes `suite_ok`.

### Lane C — platform qualification (task #4; the largest GA gap)
Fresh **artifact-only** deployments, each passing: dry-run → first bootstrap
→ idempotent rerun → reboot/service recovery → `doctor --exit-code` →
`lock --check` → one signed end-to-end work-item flow.
- **Linux:** clean systemd host (LXD is initialized on mvmcc03; a system
  container gives real systemd and survives reboot testing).
- **Windows:** clean native host in the documented dedicated-VM posture
  (mvmcitest01, disposable). Known hazard: AD cmdlets cannot authenticate
  from an SSH session there (S4U double-hop).
Custody per host: distinct principal, Vault-backed, independently revocable —
per `docs/secrets-instantiation.md`. Qualification must assert every `vault:`
ref *resolves*, that AppRole hosts carry no `VAULT_TOKEN`, and that
cross-principal reads are denied.

### Lane D — agent-wake delivery hardening, redone (agent-wake WI-001)
The local branch failed review with 3 majors: it fails its own uv-lock CI
gate; the new `human_delivery` dead-letter kind cannot be listed or
redriven; the dead-letter write races daemon shutdown and loses exactly the
alerts it claims to preserve. The lint/format commits in that branch are
verified pure, so they are a sound base. The SSRF guard is config-load-time
only — DNS rebinding at delivery time is unmitigated. **Exit:** majors
closed, tests exercising the dead-letter and redirect paths, CI green.

### Lane E — acb declared onboarding, redone (acb WI-015)
Failed review with 8 majors, including a reopened path-traversal class on a
*write* path (arbitrary file clobber + secret material planted at arbitrary
paths), `--check` exiting 0 when admin auth fails, ambient `VAULT_TOKEN`
pickup contradicting its own contract, and non-idempotent apply minting a
new SecretID every run. Several tests are tautological. Treat as a rewrite
against the contract, not a patch. **Exit:** majors closed, no-secrets
property actually asserted, conformance cases for the new verb.

### Lane F — operations and multi-user lifecycle (tasks #5, #6)
On a disposable restore target: scheduled backup → restore →
`verify-restore` → forced red health → alert delivery → recovery
notification. Then onboard two humans and two agents, verify attribution and
key separation in the signed chain, and perform one offboarding with
dual-control revocation. Lane F also extends `agent-suite offboard` to
destroy the AppRole SecretID accessor and assert auth+signing failure (the
target state named in `docs/secrets-instantiation.md` §4).

## Standing review questions (apply to every lane)

- Does this path's cost grow with production history? If yes, it is not a
  health, probe, or startup path.
- Does this check verify, or merely observe presence?
- Can this credential be revoked alone, without collateral damage?
- If this fails at 3am, does a human learn about it — and can they redrive it?

## Sequencing

Lanes A, B, D, E in parallel now. Lane C starts as soon as Lane B lands
(qualification should exercise the artifact-era doctor, not the pre-fix one).
Lane F follows C on the same hosts. GA is called when C and F are both
evidenced and the release board's gates are met — the tag push and any
publication remain owner-gated.
