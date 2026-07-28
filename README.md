# agent-suite

**Deploy the agent suite as one system, not six installs.**

`agent-suite` is the thin orchestration layer that turns six independently-useful
tools — [regista](https://github.com/hraedon/regista) (the store),
[dossier](https://github.com/hraedon/dossier) (human face),
[agent-notes](https://github.com/hraedon/agent-notes) (agent face),
[agent-provenance](https://github.com/hraedon/agent-provenance) (`cairn`,
attestation), [agent-capability-broker](https://github.com/hraedon/agent-capability-broker)
(`acb`, capability parity), and [agent-wake](https://github.com/hraedon/agent-wake)
(signaling) — into a suite that deploys, checks out, and versions as a unit.

It owns five things and no more:

1. **A bootstrap** (`agent-suite bootstrap`) that runs the documented install
   order idempotently: secret backend → Postgres → `regista provision` (schemas +
   service roles + per-actor keys) → faces → provenance → capabilities → signaling.
2. **A compatibility lock** (`SUITE.lock`) pinning each component to a git SHA and
   the regista schema/workflow/envelope versions the set is tested against — plus a
   suite-interop CI that proves the pinned set drives one work-item across the human
   and agent faces to `done`.
3. **A health umbrella** (`agent-suite doctor`) that aggregates each component's
   `doctor --json` into one "is the suite healthy on this box" answer.
4. **The operator docs** — per-backend secret runbooks (Vault / Azure Key Vault /
   Windows-native), install guides for Linux / Docker / Windows, and the multi-user
   onboarding flow.
5. **Operations** (`agent-suite upgrade`, `agent-suite schedule`, `agent-suite
   alert-check`) — advance the lock as an evidence-based transition, roll back to a
   prior lock, schedule backups with verify-restore and health checks on a cadence,
   and route red-doctor alerts to a human via agent-wake.

## Why this exists

On a developer's machine the six tools accrete: each installed its own way, named
the same config three different ways, pinned the store loosely, and reported its
health in its own dialect. That is fine for one operator and unacceptable for a
team deployment — especially a regulated one, where the whole point is a small,
legible, auditable footprint. `agent-suite` is the single place a new operator
clones to stand the whole thing up, and the single artifact that says "these
versions of these tools are known to work together."

It is **not** a new capability. It adds no store, no face, no detector. It is
orchestration and documentation over the six components, deliberately thin — if a
component needs a feature, that feature belongs in the component, not here.

## Scope

**In scope:** the bootstrap, the lock + interop test, the doctor umbrella, the
secret-backend runbooks, the install/onboarding docs, and the per-user overlay
flow for a shared Postgres backend.

**Out of scope (belongs in a component):** any store/face/detector logic; the
per-component `provision`/`install-harness`/`doctor` commands (this layer *calls*
them); the crypto (regista owns per-actor Ed25519 signing).

**Non-goals (ever):** a control plane / daemon that manages the running suite (the
components run under the OS's own service manager — systemd / Windows Services /
Docker — not a bespoke orchestrator); a SaaS; a Kubernetes dependency (a cluster
is deliberately not required — an optional manifest may exist for shops that
already run one, but it is never the path).

## Substrate

**Linux, Docker, and Windows.** Each deployable component ships a container image
and a native install (systemd unit / Windows Service); CLIs install via
`pip`/`pipx`. No Kubernetes requirement — see the blueprint for the rationale.

## Status

Active development. The strategic blueprint and per-component cohesion plans
exist (regista 025/026, dossier 013/014, agent-notes 017, agent-provenance 008,
acb 005, agent-wake 004). This repo's Plan 001 implements the suite-level layer:

**Implemented:**
- `agent-suite doctor` — health umbrella aggregating each component's
  `doctor --json` into one report, with key-rotation and store-growth
  checks (WI-1.1, WI-2.2)
- `agent-suite lock` — `SUITE.lock` compatibility manifest with drift detection
  (WI-2.1)
- Suite-interop CI — drives one work-item across both faces to `done` and verifies
  the mixed chain with `regista replay` (WI-2.2)
- Tamper-detection negative test — proves forged events, spoofed actors, and
  mutated bodies are each detected with a distinct, named failure (WI-2.3)
- `agent-suite bootstrap` — ordered idempotent install with `--dry-run`,
  `--tier`, and `--user` (WI-3.1)
- `agent-suite verify-restore` — proves a restored store is cryptographically
  intact (WI-4.2); wired into `doctor --verify-restore` as a post-restore check
- `agent-suite upgrade` — advance `SUITE.lock` as an evidence-based transition
  with `--check`, `--component`, `--dry-run`, and `--to` rollback (Plan 005 WI-1.1,
  WI-1.2)
- `agent-suite schedule` — install/remove OS-scheduled backups with
  verify-restore and doctor+alerting via systemd timers / Windows Scheduled Tasks
  (Plan 005 WI-2.1, WI-3.1)
- `agent-suite alert-check` — run doctor, emit state-change alerts to agent-wake
  with debounce (Plan 005 WI-3.1)
- Key-rotation age + store-growth watch in doctor (Plan 005 WI-2.2)
- Operator docs — secret-backend runbooks, install guides, multi-user onboarding,
  key-operations policy, DR runbook, operating-the-suite runbook (WI-4.1, WI-5.1,
  WI-5.2, Plan 005)

**Contract-gated (scaffolded, awaiting component CLIs):** the bootstrap composes
the components via their documented CLIs; it can only be fully completed as the
component `provision`/`install-harness` contracts land.

## Relationship to the blueprint

`/projects/agent-suite-blueprint.md` is the *strategy* (tiers, contracts,
decisions, sequencing, the operator's external dependencies). This repo is the
*implementation* of the suite-level layer that blueprint calls for. The blueprint
is the target; this is the tool that reaches it.
