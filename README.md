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

It owns four things and no more:

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

Charter stage. The strategic blueprint (`/projects/agent-suite-blueprint.md`) and
the per-component cohesion plans (regista 025/026, dossier 013/014, agent-notes
017, agent-provenance 008, acb 005, agent-wake 004) exist. This repo's Plan 001
turns the bootstrap contract (`docs/bootstrap-contract.md`) into the `bootstrap`,
`doctor`, and `lock` commands. It composes the components; it does not reimplement
them, so it can only be completed as their cohesion plans land.

## Relationship to the blueprint

`/projects/agent-suite-blueprint.md` is the *strategy* (tiers, contracts,
decisions, sequencing, the operator's external dependencies). This repo is the
*implementation* of the suite-level layer that blueprint calls for. The blueprint
is the target; this is the tool that reaches it.
