# AGENTS.md

Conventions and quick reference for agents (and humans) working on agent-suite.

## What this is

The thin orchestration layer that deploys the six-component agent suite as one
system. It owns a bootstrap, a compatibility lock, a health umbrella, and the
operator docs — nothing else. See `README.md` for the charter and
`/projects/agent-suite-blueprint.md` for the strategy.

## Orient

1. **Read the bootstrap contract.** `docs/bootstrap-contract.md` — the ordered,
   idempotent install steps, the doctor-aggregation shape, the `SUITE.lock`
   format, and the per-user/multi-user model. It is the design spine: it dictates
   what `bootstrap`, `doctor`, and `lock` do.
2. **Read the blueprint.** `/projects/agent-suite-blueprint.md` — the four cohesion
   contracts (config, secrets, multi-user, health), the substrate + secret-backend
   decisions, and the sequencing. This repo implements the layer it describes.
3. **Know the boundary.** This layer *calls* each component's own
   `provision` / `install-harness` / `doctor`; it never reimplements them. A change
   that adds store/face/detector logic here is in the wrong repo.
4. **Know the CLI contract.** `docs/cli-contract.md` (contract v1) is normative
   for every suite CLI, this repo's included: stream discipline, exit-code
   taxonomy, the common error envelope, grammar conventions. The conformance kit
   lives at `src/agent_suite/conformance/`; per-component results in
   `data/cli-conformance.json`.
5. **Isolate before you edit concurrently.** If another agent (or a human) may
   touch this repo at the same time, work in your own `git worktree` — never
   share a working tree. `scripts/agent-worktree <repo> <task-slug>` is the paved
   path; see `docs/agent-worktrees.md` (Plan 019 B0).

## Hard rules

- **Thin orchestration, not reimplementation.** Compose the components via their
  documented CLIs and contracts. If a step needs logic a component doesn't expose,
  the fix is a feature request in that component, not code here. The temptation to
  "just do it here" is the thing that turns a thin layer into a second, divergent
  implementation.
- **This layer *acts* — so every action is idempotent, ordered, and re-runnable.**
  Unlike the read-only lens tools, `bootstrap` provisions databases, writes
  secrets, and installs services. Therefore: every step is idempotent (re-running
  changes nothing already done), the order is fixed and documented, a `--dry-run`
  prints the plan without acting, and a destructive or irreversible step
  (key creation, role grants) refuses rather than clobbers an existing artifact.
  `doctor` is strictly read-only.
- **Never hold a secret; resolve it.** `bootstrap` moves secrets from the operator's
  chosen backend (Vault / AKV / Windows-native) into place via regista's secret
  resolver; it never embeds, logs, or commits a secret value. No plaintext key or
  DSN password is written to a committed file, ever.
- **No work-domain identifiers in committed files.** Hostnames, domains, real
  principal ids, real project slugs → placeholders only (`suite-db.example`,
  `WORK-DOMAIN`, `svc-example`, `project-slug`). Real config lives in the operator's
  `suite.env` (gitignored) and the secret backend, never in the repo. A committed
  `suite.env.example` carries placeholders only.
- **Deterministic, stdlib-first core.** The orchestration logic (ordering,
  idempotency checks, doctor aggregation, lock parsing) is stdlib + subprocess to
  the component CLIs. Backend SDKs (Vault/Azure/Windows) live behind extras and are
  imported only at the secret-resolution edge, never in the core — enforce with an
  architecture import-boundary test. No AI in the deployment path.
- **Correctness by construction.** `mypy --strict` in CI from day one;
  `typing.assert_never()` in the default branch of every dispatch over a closed set
  (step kind, backend kind, component id, doctor status, OS target). The family's
  deliberate substitute for exhaustive-match checking — it matters most here because
  a missed case in a *deployment* tool fails on a real machine, not in a test.
- **Honest health.** `doctor` reports a component as unhealthy or unreachable
  plainly; it never smooths a missing component into "ok." A gap in the suite is a
  named state, not silence.

## Boundary vs. the components

| This repo does | A component does |
|----------------|------------------|
| Run the install steps in order, idempotently | Expose `provision` / `install-harness` / `doctor` |
| Aggregate `doctor --json` into one answer | Emit its own `doctor --json` |
| Pin + verify the version set (`SUITE.lock`) | Declare its own version (`regista version --json`) |
| Ship the secret-backend runbooks | Resolve a secret via `regista.secrets.resolve` |
| Document the multi-user onboarding | Enforce per-actor signing / attribution (regista) |

## Family conventions inherited

- No work-domain identifiers committed; `samples/`, `*.db`, `.env`, `suite.env`,
  secrets, venvs, and caches are gitignored.
- Private until a written `docs/publication-review.md` clears the tree — this repo
  will reference deployment topology, so the review bar is real.
- CI: ruff + mypy --strict + pytest on 3.12/3.13, an identifier-gate, pip-audit,
  actions pinned by SHA — mirroring the family.
