# Plan 001 — bootstrap, doctor, lock (the suite-level layer)

**Status:** Proposed 2026-07-02 (project initiation)
**Author:** Claude (Fable 5)
**Strategic role:** Turn the bootstrap contract (`docs/bootstrap-contract.md`) into
the three commands that make the suite deployable as a unit: `bootstrap` (the
ordered idempotent install), `doctor` (the health umbrella), and `lock` (the
compatibility manifest + its interop test). This is the implementation of the
suite-level layer the blueprint (`/projects/agent-suite-blueprint.md`) calls for.

## Ground truth at time of writing

- The blueprint and every per-component cohesion plan exist (regista 025/026,
  dossier 013/014, agent-notes 017, cairn 008, acb 005, wake 004). **None are
  implemented yet.** agent-suite composes those commands, so it can be *scaffolded
  and specified* now but can only be *completed* as the component contracts land —
  chiefly regista Plan 025 (config/secrets/provision/doctor-shape/version) and 026
  (per-actor keys).
- The homelab converged store (mvmpostgres01, ~16 schemas) is the first real
  bootstrap target; work is the eventual one.

## Principles this plan must hold

- **Thin: compose, never reimplement.** Every step shells a component CLI. If a
  step needs logic no component exposes, file it against that component — do not
  grow it here (AGENTS.md hard rule).
- **Idempotent + ordered + dry-runnable.** Re-running a completed step is a no-op;
  the order is the contract's; `--dry-run` acts on nothing; an irreversible step
  refuses to clobber.
- **Stdlib core; SDKs at the edge.** Ordering/idempotency/aggregation/lock-parsing
  are stdlib + subprocess. Vault/Azure/Windows SDKs live behind extras, imported
  only at the secret edge (via regista's resolver where possible) — architecture
  test enforces the boundary.
- **mypy --strict + `assert_never`** on every closed-set dispatch (step kind,
  backend kind, component id, doctor status, OS target) from day one.

---

## Phase 0 — Skeleton (project initiation)

### WI-0.1 — Buildable skeleton + CI
- `pyproject.toml` (stdlib core; extras `[dev]`, `[vault]`, `[azure]`, `[windows]`;
  console script `agent-suite = agent_suite.cli:main`), the module skeleton
  (`cli`, `bootstrap`, `doctor`, `lock`, `config`, plus a `components` descriptor),
  `.gitignore`, MIT `LICENSE`, and CI (ruff, mypy --strict, pytest on 3.12/3.13,
  identifier-gate, pip-audit; actions pinned by SHA).
- **AC:** `ruff check`, `mypy --strict src`, `pytest -q` clean on the skeleton; the
  architecture test asserts the core imports no backend SDK and no component code.

## Phase 1 — `doctor` (safe first; read-only)

### WI-1.1 — Component descriptor + doctor aggregation
- A declarative descriptor of the six components (id, tier, the `doctor --json`
  invocation, install-detection). `agent-suite doctor [--json]` shells each
  installed component's doctor, folds them into the umbrella shape
  (`docs/bootstrap-contract.md` §3), marks absent components `absent` (not failed),
  and `--exit-code` gates.
- **AC:** against a fixture of stubbed component doctors, the umbrella aggregates
  correctly; an absent Tier-2 component is `absent`, an unreachable installed one
  is a failure; the command mutates nothing; `assert_never` over the status enum.

## Phase 2 — `lock` (versioning the set)

### WI-2.1 — `SUITE.lock` generate + drift-check
- `agent-suite lock` writes/updates `SUITE.lock` from the currently-pinned revs +
  the regista version quad (`regista version --json`, Plan 025 WI-4.1); `doctor`
  gains a `lock` section comparing installed versions to the lock and reporting
  drift.
- **AC:** `lock` round-trips the manifest; a version mismatch shows as named drift;
  the quad is read from regista, not hardcoded.

### WI-2.2 — Suite-interop CI
- Wire the interop test (`docs/bootstrap-contract.md` §5) on regista's published
  fixture (Plan 025 WI-4.2): ephemeral Postgres → bootstrap Tier 0–1 at locked revs
  → drive one work-item across both faces to `done` → `regista verify` confirms the
  mixed chain verifies with per-actor signatures (Plan 026). A green run is what
  makes a lock a release.
- **AC:** the job is gated on the component contracts existing (skips cleanly until
  then); when they exist, it drives the cross-face work-item and verifies.

## Phase 3 — `bootstrap` (the acting command; last, because it acts)

### WI-3.1 — The ordered idempotent bootstrap
- `agent-suite bootstrap [--dry-run] [--tier 0-1|all] [--user]`: runs the install
  order (`docs/bootstrap-contract.md` §1), each step idempotent and gated, calling
  the component CLIs. `--dry-run` prints the plan; a step that would clobber a key
  or a populated schema refuses; `--user` writes a per-user overlay without
  touching shared state (order step 7).
- **AC:** against an ephemeral target, `bootstrap --tier 0-1` produces a running
  core; a second run is a no-op and says so; `--dry-run` acts on nothing; a
  key-clobber is refused; a missing external dependency (backend/Postgres) fails
  with a named, actionable message, not a traceback. Ordering/idempotency unit-tested
  with stubbed component CLIs (no live infra in CI).

## Phase 4 — Operator docs

### WI-4.1 — Secret-backend runbooks + install guides
- `docs/secrets-vault.md`, `docs/secrets-akv.md`, `docs/secrets-windows.md` (each:
  set up the backend, store the DSN password + principal keys, reference them from
  `suite.env`), plus `docs/install-linux.md`, `docs/install-docker.md`,
  `docs/install-windows.md`, and `docs/multi-user-onboarding.md`. Placeholders only;
  no work-domain identifiers.
- **AC:** an operator can follow one secrets runbook + one install guide to stand up
  the Tier 0–1 core; the identifier-gate stays green.

## Sequencing & notes

- **Order is deliberate: doctor → lock → bootstrap.** doctor is read-only and
  useful immediately (even against a hand-installed suite); lock versions the set;
  bootstrap acts and lands last, because an acting deployer is the highest-risk
  surface and benefits most from the read-only pieces existing first.
- **This plan is contract-gated.** It can be scaffolded and its doctor/lock shells
  written against stubs now, but a real `bootstrap` needs the component
  `provision`/`install-harness` commands to exist. Track that dependency honestly —
  don't claim a working bootstrap before the components it calls are real.
- **First real target is the homelab** converged store; a green Tier 0–1 bootstrap
  + interop lock there is the proof before the work pilot (blueprint Phase F).
