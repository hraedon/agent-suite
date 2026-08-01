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

---

# Execution plan — getting the team onto the backlog

The suite is moving from an ad-hoc single-operator toolset to a
multi-user, attestation-bearing product for a more sensitive environment.
Missteps on that road are expected and are mostly already filed against
ourselves; the job now is to hand the team a backlog they can trust and a
division of labor that doesn't funnel everything through one operator.

## Workstream 0 — state hygiene (COMPLETED 2026-07-31 evening)

Executed by delegated reconciliation sweeps (commit-verified per item)
with all tracker mutations applied by one actor:

- **31 items closed** with commit evidence: agent-suite WI-039..045/051/
  052 (PRs #8/#9), agent-notes WI-022/023/041/042/047 (+5 debris/dupes),
  dossier WI-025/026 (dup pair), regista WI-225, acb WI-001/008/009/011,
  agent-wake BC-WAKE-004/009/011 + WI-005 (its asked-for backlog walk was
  this sweep).
- **All 13 June-era regista review-queue items verified RESOLVED** with
  file:line evidence and review-passed. They now sit `in_human_review`
  along with the WI-231/WI-040/WI-232 fix items and four PR-fixed regista
  items — the tracker's two-stage independence gates (adversarial_review:
  no self-review; human_gate: accepter must differ from reviewer) held
  correctly against single-actor processing, so **final acceptance is the
  owner's bulk action**, by design.
- Three new items filed from sweep findings: regista WI-233 (mypy strict
  burndown, ~74 quarantined modules), regista WI-234 (dead 64KB metadata
  validator), agent-wake WI-007 (doctor green with zero subscribers —
  live_only wakes drop silently; observe-vs-verify in agent-wake).
- regista WI-232 fixed on branch agent/wi-232-test-hermeticity (ccbbb8a);
  the whole suite is now hermetic against a configured host's Vault plane
  (verified with all nine plane variables set to junk).
- Everything not closed was verified STILL OPEN with a one-line reason —
  the remaining open lists are now trustworthy input for the team.

**A structural note on the drift** (owner concurs): when the tracker
itself misbehaves, agents improvise item creation, and the improvisations
diverge. The countermeasure is not agent discipline, it is making the
paved path cheaper than improvisation. That makes the agent-notes UX
cluster — WI-049 (init derives a broken slug), WI-052 (find --text
silently incomplete), WI-027 (reconcile false-positives), WI-048
(--version crash), cross-host path registration — an *early* team lane,
not a cleanup afterthought: tracker trust gates every other lane's
coordination.

## Workstream 1 — land, release, cut (mostly owner-gated)

1. Push and open PRs for the three ready branches (owner: these sit
   local-only per the no-push rule):
   - regista `agent/wi-231-key-encoding` (f6f4458)
   - agent-provenance `agent/wi-040-cipher-probe` (c279253)
   - regista `agent/wi-232-test-hermeticity` (ccbbb8a)
   Also owner: bulk-accept the `in_human_review` queue (single
   `agent-notes work-item review accept` per item; the reviewer evidence
   is in each item's body and pass note).
2. Cross-lineage review of the pair (NOT claude-lineage — implementer).
3. regista 0.5.5 to PyPI; SUITE.lock spine bumps across components;
   estate venv reinstalls. Exit: estate doctor green through the cipher
   probe from released artifacts.
4. RC3 cut per the rc-build recipe (interop tests, feature probes,
   lock --check, release-manifest build). RC2's tag must never ship.

## Workstream 2 — team lanes, by claim

Once Workstreams 0–1 land, the team works the five claims in the review
scope above. Suggested lane assignments (one reviewer-owner per claim,
never the claim's implementer):

- **Custody:** acb + regista `_secrets` surfaces; includes executing the
  deferred DSN/keys.json → `vault:` migration *after* the design note
  (below) is reviewed.
- **Attribution:** the WI-055 principal_id unification is the entry task —
  it blocks everything else in the claim; then WI-052 onboarding binding,
  regista WI-215/214/224 lineage cluster.
- **Confidentiality:** BC-016 witness signature verification is the
  largest unstarted item; then the bundle cluster (WI-020/021/022), then
  the WI-035 severity decision (owner decides; team implements).
- **Honesty:** Lane J audit sweep — every doctor check in every component
  classified verify/observe, with WI-038's env-split as a seeded case.
- **Artifact integrity:** wheel-hash verification (Lane B strengthening),
  acb WI-013 dependency fix, conformance gates.

## Division of labor — what I (the assisting agent) keep personally

Reserved to me, with reasons:

- **Tracker state surgery** — transitions, dedup closes, forced repairs.
  The CLI's lifecycle is non-idempotent and path-registration differs per
  host; I have the working map, and parallel mutation by many agents is
  how the drift happened.
- **RC3 assembly and SUITE.lock regeneration** — the rc-build harness has
  documented sharp edges (SUITE_WORKSPACE_ROOT, the PyPI `cairn`
  shadowing, editable umbrella for release identity). One operator, one
  recipe, reproducibly.
- **Estate credential work** — the DSN/keys.json Vault migration and any
  policy widening. It touches live credentials with real blast radius;
  it should be one pair of hands with owner review, not a team lane. I
  will write the migration design note first (policy diff, rollback,
  per-ref sequencing) for review before any change.
- **The regista secrets provider text/bytes contract note** — the WI-231
  follow-on. `resolve()` returns "UTF-8 of whatever text was there" while
  `store()` base64-encodes; the provider contract needs one written
  decision so the next binary secret doesn't re-create WI-231. I authored
  the encoding contract and can keep it coherent — but its *review* must
  be another lineage.
- **Plan curation** — keeping 020/021 truthful as lanes close.

Explicitly NOT mine:

- Adversarial review of Claims 2 and 3 — they contain my own WI-231 and
  WI-040 code. Cross-lineage means someone else.
- The WI-035 default-encryption severity decision — owner's call.
- Tag pushes, PyPI publication, repository visibility — owner-gated.

## Sequencing

Workstream 0 completes now. Workstream 1 steps 1–2 are unblocked
immediately; 3–4 follow review. Workstream 2's agent-notes UX lane and
the WI-055 principal_id task can start in parallel with Workstream 1 —
they don't depend on the release. Claim reviews start on RC3 artifacts.
