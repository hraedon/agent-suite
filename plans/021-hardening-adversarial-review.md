# Plan 021 — Hardening pass and focused adversarial review

**Status: DRAFT** (2026-07-31, for owner review). Successor to Plan 020's
review gate: it defines the entry criteria for the cross-lineage review
rounds Plan 020 §"The GA review gate" promises, and organizes the review by
*claim* rather than by component. Lanes C (re-qualification) and F
(operations / multi-user lifecycle) remain owned by Plan 020 and run after
the first review round, on RC3 artifacts.

## Why now

As of 2026-07-31, every code lane Plan 020 opened has landed on GitHub
mains: Lane A (regista #13), Lane B (agent-suite #6), Lane D (agent-wake
#9–#11), Lane E (acb #20–#21), Lane G (regista #15, dossier #12), Lane H
(agent-suite #8), Lane I (agent-notes #15, agent-suite #9, dossier #13),
and the qualification mediums (agent-suite #10). The content-encryption
pair that closes the last confidentiality gap (regista WI-231, cairn
WI-040) is implemented and awaiting review. What stands between here and
the review phase is not code volume — it is state hygiene and a stable
target.

## Entry criteria — the "reasonable point"

0. **Tracker reconciliation.** The tracker lags the repos by a full
   lane-cycle: agent-suite WI-039..045, agent-notes WI-047, and the regista
   Lane C items read open while their fixes are merged. Reconcile every
   component against its GitHub main (the `breadcrumb reconcile` mechanism,
   run where the projects are path-registered), so the review queue holds
   only real surface. A review aimed at a stale backlog audits noise.
1. **Merge the in-flight confidentiality pair** — regista
   `agent/wi-231-key-encoding`, agent-provenance `agent/wi-040-cipher-probe`
   — then release regista (0.5.5) to PyPI and bump SUITE.lock spines.
   Exit: the estate doctor reports content encryption green from released
   artifacts, via the cipher probe, with AppRole auth and no `VAULT_TOKEN`.
2. **Cut RC3** per the rc-build recipe. Every lane moved component
   revisions; the RC2 tag must not ship (its dossier pin predates the
   /healthz OOM fix). Review targets RC3's pinned SHAs — a moving target
   invalidates findings.
3. **Reviewers can run the suites.** regista WI-232: five WI-228 tests fail
   on any host with `VAULT_ENV_FILE` set — i.e., on every host configured
   per `docs/secrets-instantiation.md`. Fix before review, or every
   reviewer rediscovers it.
4. **Triage the review queue** (33 items in `in_review`/`in_human_review`
   across the estate). Three populations, three dispositions:
   evidence-backed closes from reconciliation (confirm and close);
   June-era pre-`WI-` items (regista 027/030/037/202/204/205/208/209 —
   re-validate against today's code, refile what still reproduces, close
   the rest); genuinely awaiting first review (the in-flight pair and
   friends — these feed the review phase itself).

## The review — five claims, not seven components

Same-lineage review kept missing the observe-vs-verify class until
qualification ran (Plan 020 §gate). The counter-structure: review the
suite's *claims*, cross-lineage, with each claim's surfaces gathered from
every component that carries it. A component-by-component pass re-creates
the implementer's frame; a claim-by-claim pass re-creates the operator's.

For each claim: independent reviewers per lineage (Opus, Sol, Qwen —
iterate until a round returns no major-or-above findings), Plan 020's
standing questions applied, every finding adversarially verified before it
is accepted.

### Claim 1 — Custody
*"Secret material is never plaintext at rest, never in the process table,
and every credential is revocable alone."*
Surfaces: regista `_secrets` (AppRole path, provider contract), acb
provisioning + `--check`, vault.env / scoped policies / response-wrapped
SecretID delivery, `agent-suite offboard`'s accessor destruction (Lane F
overlap). Seeded known-unmet items: `settings.json` Postgres DSNs and
`regista keys.json` are plaintext-at-rest (0600, deliberately deferred —
this review decides the `vault:` migration, which needs a policy widening
done deliberately). Standing question: can this credential be revoked
alone?

### Claim 2 — Attribution
*"Every event is bound to a real principal; humans and agents sign with
their own keys; no silent downgrade."*
Surfaces: regista principal binding (WI-223's verify-not-report), dossier
per-human signing (WI-035 fix), onboard's identity binding (agent-suite
WI-052 — open), the three incompatible principal_id conventions (WI-055 —
open, likely blocks this claim's review), lineage as asserted-vs-signed
(regista WI-215/214/224). This is the suite's core value proposition and
qualification found it unverified once already; expect the majors here.

### Claim 3 — Confidentiality
*"Session content is encrypted or withheld — never silently plaintext."*
Surfaces: the WI-231 + WI-040 pair (first through the gate), the WI-035
default-on-without-a-key decision (warn today; the exit code blesses
plaintext capture), witness receipt signatures never cryptographically
verified (agent-provenance BC-016, high), the bundle-verification cluster
already in review (WI-020 filtered bundles skip TSA, WI-021 zip-bomb,
WI-022 cross-bundle chain).

### Claim 4 — Honesty
*"Doctors, bootstrap, lock, and health verify what they claim, and their
view is the operator's view."*
Surfaces: Lane J's audit (every check: verify, or say plainly it does
not), bootstrap honesty (#8) re-reviewed by a different lineage, scheduled
doctor-alert's root/stripped-PATH environment split (agent-suite WI-038 —
the doctor's view is env-relative and the suite treats "the host" as one
thing), dossier session-secret custody contradiction (WI-036).

### Claim 5 — Artifact integrity
*"What installs is what was reviewed, and it works without a checkout."*
Surfaces: wheel-hash verification against the release manifest (Lane B's
strengthening), Lane I's packaging fixes re-exercised (units, schema,
`dossier.service`), acb's unsatisfiable `regista` distribution dependency
(WI-013, in review), release identity from wheels (the 0.0.1 fallback
class), conformance gates across all six components.

## Exit

Each claim reaches a review round with zero major-or-above findings from a
lineage that did not implement the surface. Then Lane C re-qualification
and Lane F run on RC3 artifacts, and the release board's gates decide GA.
Tag pushes and publication remain owner-gated throughout.
