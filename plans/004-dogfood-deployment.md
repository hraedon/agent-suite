# Plan 004 — Dogfood deployment: the suite actually deployed as a suite

**Status:** Proposed 2026-07-07.
**Author:** Claude (Fable 5), from the 2026-07-07 suite v2 gaps review
**Strategic role:** Every suite mechanism now exists — bootstrap, lock, doctor
umbrella, interop CI — and none of it has ever been *exercised on a real box*.
On the operator's own machine (the only deployment in existence), `agent-suite
doctor` reports **five of six components failed and no SUITE.lock**, while the
components demonstrably work — because they run on bespoke legacy env
(`AGENT_NOTES_*` vars in harness settings), not the suite config contract, and
the bootstrap has never been run. The gap between "green in CI" and "green on a
box" is exactly the gap the suite exists to close. v2's keystone: deploy the
suite to its own home, then to a clean machine, and make the umbrella's answer
true and legible.

## Ground truth (verified 2026-07-07)

- `agent-suite doctor` on the operator box: regista `failed` ("No DSN
  provided"), dossier/agent-notes `failed` (doctor exit 1, empty detail),
  agent-provenance `failed` (unconfigured + unwired), acb `failed` (its own
  contract drift — acb Plan 006 WI-1.1), agent-wake `degraded`. No
  `~/.config/agent-suite/suite.env`; no SUITE.lock generated.
- Meanwhile the components work daily via legacy config: agent-notes writes
  through regista from harness env vars under their pre-contract names; wake's
  daemon is healthy; acb's cred shims are load-bearing.
- Diagnosability gap: for three of the five failures the umbrella shows an
  empty or unhelpful `detail` — an operator staring at `failed: no stderr`
  has nothing to act on.
- Plan 001's bootstrap WIs were contract-gated on component CLIs that have
  since landed (regista 025 `provision`, faces' install steps, cairn
  `install-harness`); the gate is open, the composition unexercised.

## Principles

- **The home box is deployment #1, not a special case.** If the suite can't
  converge the machine it was built on — with live data it must not disturb —
  it won't converge a work machine.
- **Idempotent means provably idempotent over live state.** Every bootstrap
  step runs `--dry-run` first against the real store; nothing in this plan may
  mutate existing project schemas beyond what `provision` documents as
  idempotent.
- **A red doctor must say why.** Illegible failure is a usability defect of
  the umbrella, not the operator's problem.

---

## Phase 1 — Converge the home box

### WI-1.1 — suite.env + legacy-var migration
- Write the box's system `suite.env` (canonical `REGISTA_*`, secret-backend
  refs into the existing Vault) and the per-user overlay (principal, default
  project). Migrate harness settings off the legacy var names via each
  component's documented alias window; remove the raw DSN/password literals
  from harness settings in favor of the contract's resolution path.
- **AC:** every component's doctor resolves config from suite.env alone
  (process-env overrides unset); the legacy names appear nowhere in live
  harness config; agent-notes' regista writes keep working (verified before
  and after with a real breadcrumb write).

### WI-1.2 — Run the bootstrap against the live backend
- `agent-suite bootstrap --dry-run` first; review the step plan; then run for
  real: secret backend check → Postgres reachability → `regista provision`
  (idempotent over the existing schemas + principal enrollment per Plan 026)
  → faces → provenance (`cairn install-harness`, gated on agent-provenance
  Plan 009 Phase 1 so we don't wire a broken recorder) → capabilities →
  signaling.
- **AC:** bootstrap completes; re-run is a no-op (asserted, not assumed);
  live data untouched (event counts + chain heads per project identical
  before/after, modulo events the run itself legitimately wrote).

### WI-1.3 — Generate and commit SUITE.lock
- `agent-suite lock` against the deployed set; commit; wire drift detection so
  CI and doctor both flag a component moved off its pin.
- **AC:** SUITE.lock exists in-repo with real SHAs; deliberately advancing one
  component locally produces a named drift finding in `doctor`.

### WI-1.4 — Suite doctor green, and legible when not
- Close the diagnosability gap found in the review: a component failure must
  carry the component's own detail (capture stderr/stdout from the child
  doctor; never render `no stderr`), and the umbrella gains a human-readable
  (non-JSON) output mode: red-first ordering, one line per component, a
  remediation hint per known failure class.
- **AC:** `agent-suite doctor` on the converged box: all six components `ok`
  (wake's identity warn resolved by wake Plan 005 WI-1.1 or explicitly
  accepted; dossier via the WI-1.6 shared-service check, not a local install);
  breaking a component's config yields a failure a newcomer can act
  on without reading source.

### WI-1.6 — Shared-service locality for the doctor and profiles
- Ratified 2026-07-11: components have a **locality** — per-box (agent-notes,
  cairn, acb, wake) or shared service (dossier; regista's Postgres already
  implicitly is). dossier deploys centrally as the team URL (dossier Plan 023,
  k8s namespace on the operator's cluster; the suite itself stays
  k8s-agnostic — systemd/Windows profiles remain the documented alternative).
  The umbrella therefore checks a shared-service component by **endpoint**:
  reachability + `/healthz` + lock-compatibility against the configured URL
  from suite.env, rendering `remote: ok @ <version>` instead of `absent`.
  Update the doctor contract doc + Plan 008/009 profile language so Profile B
  does not imply a per-box dossier install.
- **AC:** with a dossier endpoint configured, doctor on a box with no local
  dossier reports it `remote: ok @ <version>`; with the endpoint down, a
  legible failure naming the URL; with none configured, an explicit
  `not configured (shared service)` state distinct from failure; contract doc
  updated and the check covered by a test against a stub endpoint.

### WI-1.5 — Record deployment #1
- A dated deployment record in `docs/deployments/` : what was run, what
  deviated from the docs, every gap found (each becomes a WI or a doc fix).
  This record is the template for the work pilot's evidence trail.
- **AC:** the record exists; every deviation it lists has a tracked follow-up.

## Phase 2 — Prove it cold

### WI-2.1 — Clean-machine bootstrap
- A fresh Linux VM/container (no homelab state): follow the install docs
  verbatim — clone, bootstrap, doctor. Every manual step not in the docs is a
  defect. Then the same on the Windows path (composes with Plan 003's tail).
- **AC:** a clean box reaches all-green doctor using only documented steps +
  the §4 external dependencies (Postgres, secret backend); the doc-gap list
  from the run is empty on a second attempt by re-following the amended docs.

### WI-2.2 — Interop proof against the deployed set
- Run the suite-interop proof (one work item across both faces to `done`,
  mixed chain verified) against the *deployed* home-box store rather than the
  ephemeral CI Postgres — the convergence E2E rerun on real infrastructure,
  plus the provenance live proof (agent-provenance 009 WI-2.2) in the same
  session.
- **AC:** both proofs pass on the deployed suite; results appended to the
  WI-1.5 deployment record.

---

## Sequencing

WI-1.1 → 1.2 → 1.3 → 1.4 in order; 1.5 alongside. Phase 2 after the home box
is green. Coordinate WI-1.2's provenance step with agent-provenance Plan 009
(fix capture before wiring) and WI-1.4's acb classification with acb Plan 006
WI-1.1. This plan closes agent-suite Plan 001's contract-gated tail.
