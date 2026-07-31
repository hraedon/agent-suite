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

**Linux leg RESULT (2026-07-31): DOES NOT PASS.** Evidence:
`rc-build/qual-linux-evidence/README.md`. Passed: dry-run acts on nothing
(byte-identical state fingerprint), idempotent rerun, reboot recovery with
zero intervention, `doctor --exit-code` 0, `lock --check` clean. Failed: the
signed end-to-end flow is only partially per-actor (the *human* leg used the
shared store HMAC key — dossier WI-035), `--require-artifact-binding` cannot
be reached with the documented install, and reaching a running suite at all
took five undocumented steps, two of them hard artifact-only blockers. 28
work items filed across five repos. Custody DID qualify: a scoped policy and
AppRole with response-wrapped SecretID delivery proven single-use, and
cross-principal reads denied — but an AppRole-only host is currently
impossible because regista's `VaultProvider` supports only `VAULT_TOKEN`.
Re-qualification is gated on Lanes I and H below.
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

### Lane G — signing integrity (regista WI-223, dossier WI-035)
The suite's core claim is attributable, non-repudiable action, and
qualification found the claim unverified. A work item's entire chain can be
signed by a key its project never registered while **four** surfaces report
green — `replay` (`principal_binding_failures=0`, an affirmative claim),
`cairn integrity`, `regista doctor`, `agent-suite doctor` — and only
`bundle verify` catches it. Separately, a human's acceptance transition
silently fell back to the shared store HMAC key, so the one signature
representing human judgement is the one that cannot be attributed to a
person; `bootstrap-contract.md` §5 requires otherwise. **Exit:** a
cross-project key fails binding verification on every surface that reports
on it, HMAC-only deployments stay green, and a mixed human+agent chain
verifies per-actor end to end with no silent downgrade path.

### Lane H — bootstrap honesty (agent-suite WI-039..WI-043)
`bootstrap: OK` is not currently evidence of a working install: step 0
reported "secret backend reachable" with the host's only `vault:` ref
provably 403, and bootstrap reported OK over a provision that never created
the service role, because `regista provision --json` exits 0 with an `error`
body. The `CAIRN_PROJECT` schema is never provisioned and agent-notes'
projection database is never migrated. Docs and `suite.env.example` also
print a `vault:` ref shape that cannot resolve. One lane because every item
is the same failure mode. **Exit:** bootstrap fails when a step failed, and
every claim it prints is verified rather than attempted.

### Lane I — artifact-only packaging (agent-notes WI-047, agent-suite WI-044/WI-045)
The blockers that make the Linux leg fail rather than partially pass:
agent-notes' wheel ships zero `schema/*.sql`, so `agent-notes-migrate` can
never run from an artifact; no wheel ships any systemd unit and no
`dossier.service` exists despite `install-linux.md` §7 telling operators to
enable it; and all three agent-suite units fail `203/EXEC` because
`ExecStart` is unqualified and systemd's fixed search path never includes
`~/.local/bin` — which means the weekly chain-integrity timer added in PR #1
has never fired on any host. Two review rounds missed that; qualification
caught it by installing and starting the units. **Exit:** a documented
artifact-only install reaches a running, scheduled suite with no
undocumented steps.

### Lane J — doctor honesty audit (cairn WI-034 generalised)
Four independent instances in one week of checks that observe presence
rather than verifying behaviour: a `vault:` ref set but unresolvable,
`--require-artifact-binding` passing vacuously, cairn hooks wired but
non-executable (all session attestation silently absent), and principal
binding reporting `0` failures on a chain the verifier rejects. The pattern
is systematic, not incidental. **Exit:** every doctor check in every
component is audited against the first standing question below, and each
either verifies or states plainly that it does not.

## Standing review questions (apply to every lane)

- Does this path's cost grow with production history? If yes, it is not a
  health, probe, or startup path.
- Does this check verify, or merely observe presence?
- Can this credential be revoked alone, without collateral damage?
- If this fails at 3am, does a human learn about it — and can they redrive it?

## Sequencing

Lanes A, B, D, E in parallel now. Lane C starts as soon as Lane B lands
(qualification should exercise the artifact-era doctor, not the pre-fix one).
Lane F follows C on the same hosts. Lanes G, H and I gate a Linux re-qualification; C and F follow. GA is
called when C and F are both evidenced and the release board's gates are
met — the tag push and any publication remain owner-gated.

**The GA review gate is cross-lineage.** When the suite reaches a state its
maintainer is willing to defend, it goes through successive independent
review rounds — Opus, Sol, and Qwen — iterating until a round returns no
major-or-above findings. This matters because same-lineage review shares the
implementer's blind spots by construction: the reviews run during this push
were all same-lineage (`--same-lineage-acknowledged`) and, while they found
real majors including four working exploits, the defect class they kept
missing until qualification ran — checks that observe presence rather than
verify — is precisely the kind a different lineage is likelier to see.
Iteration is the mechanism; a round with no big findings is the signal.
