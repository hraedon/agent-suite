# Handoff — Plan 019 B2-generalize (the last coupling-tax piece)

**Written 2026-07-21** after B3 retrofits 1–3 merged. This is the operational
handoff for **B2-generalize**, the only remaining item in the Plan 019
coupling-tax initiative. Read `plans/019-reduce-cross-member-coupling-tax.md`,
`docs/b3-cli-contract-audit.md`, and the prior `handoff-plan019-b2b3.md` for the
full arc; this doc is the concrete to-do.

## Where this sits (what's already done)

Plan 019 = the *coupling-tax* track (finish-the-polyrepo), parallel to Plan 018
P2's *contract-tax* track.

- **B0** — `scripts/agent-worktree` per-agent worktree helper + convention. Landed.
- **B1** — the conformance kit published as a versioned PyPI wheel
  (`agent-suite-conformance==1.0.0`). Landed. Siblings consume it as a normal dep.
- **B2 pilot** — "develop against the locked substrate" on **agent-notes**
  (PR #13, origin `0bb9edb`). Landed. **This is the template to generalize.**
- **B3 audit** — `docs/b3-cli-contract-audit.md` (PR #41). Landed.
- **B3 retrofits 1–3** — the §3 error-envelope + kit adoption in **acb (PR #17)**,
  **dossier (PR #4)**, **cairn (PR #7)**. **All MERGED 2026-07-21, CI green.**
  (Qwen reviewed all three = Merge.)

**B2-generalize is the last piece:** roll the agent-notes develop-against-lock
machinery to the remaining members, and add the **cross-repo lock-agreement
check** the pilot explicitly deferred.

## The template to replicate — agent-notes B2 pilot (origin `0bb9edb`, PR #13)

Files the pilot added/changed (read them on agent-notes `origin/main`):

| File | Role |
| --- | --- |
| `SUITE.lock` | face-local lock in **TOML `[spine]`** shape, made the in-repo source of truth; `[spine].version="0.5.3"`, `distribution="regista-hraedon"`, `sha=9718b94`, `describe=v0.5.3`, `pyproject_floor`. Must equal the umbrella `[components.regista]`. |
| `scripts/suite_lock.py` (140 LOC) | resolver — reads `[spine].version` → a pip requirement, honouring `DEV_AGAINST`. |
| `scripts/dev-install.py` (97 LOC) | the paved path: installs regista at the locked version; `DEV_AGAINST=main\|<ref>\|sibling` escape hatch. |
| `.github/workflows/ci.yml` | both lanes call `python scripts/dev-install.py` instead of a hardcoded `pip install regista-hraedon==<x>`. |
| `Makefile` | `make dev` → `python scripts/dev-install.py`. |
| `tests/test_develop_against_lock.py` (135 LOC) | **mechanical control** — fails on a hardcoded pin or an unguarded `git+@ref` in CI. This is the guard that catches the `0.5.1`-vs-`0.5.3` drift class. |
| `docs/develop-against-lock.md`, `AGENTS.md` | the convention, written down. |

The pilot fixed a *live* drift while doing this (CI hardcoded `regista-hraedon==0.5.1`
while the umbrella lock said `0.5.3`). The remaining members have the same drift.

## Per-member work + complications

### cairn (agent-provenance) — do FIRST, it's the cleanest
- **No Dockerfile / no image job.** CI is already on **regista 0.5.3** and
  **py 3.13/3.14** (I bumped both in PR #7). So there is no residual drift to fix.
- Port the machinery: face-local `SUITE.lock` `[spine]`, `scripts/suite_lock.py`
  + `scripts/dev-install.py`, `Makefile` `make dev`, `ci.yml` → `dev-install.py`
  (replacing the current hardcoded `pip install regista-hraedon==0.5.3`),
  `tests/test_develop_against_lock.py`, `docs/develop-against-lock.md`, `AGENTS.md`.
- Proves the port pattern on the least-entangled member.

### dossier — the hard one (multi-artifact alignment)
dossier's regista pinning is spread across several artifacts that must be aligned
to `0.5.3` (sha `9718b94`) as ONE coherent unit — this is why the B3 retrofit
(PR #4) *deferred* the pin bump (bumping only CI test pins would create
test-vs-image skew). On **`origin/main`** the state is:
1. `.github/workflows/ci.yml` — two `pip install "regista-hraedon==0.5.1"` steps
   (main test job + windows job) → bump to `0.5.3`.
2. `Dockerfile` — **git+SHA** install (`ARG REGISTA_REF=dd22197`,
   `pip install "regista @ git+…@${REGISTA_REF}"`). It *works* today, but the
   intended direction is a **PyPI switch** (install `regista-hraedon==<version>`),
   which already exists on the **`origin/deploy/k8s-and-pypi`** branch — except
   that branch's version carries a `python3 -c` monkeypatch (for regista < 0.5.2's
   broken `importlib.metadata.version("regista")` lookup) written as an `if/else`
   one-liner = **SyntaxError**. Since 0.5.3 has the dual-name fix, adopt the PyPI
   switch **without** the monkeypatch: `pip install "regista-hraedon==0.5.3"`,
   nothing more. Also fix a latent mismatch: the image job greps
   `ARG REGISTA_VERSION=` from the Dockerfile while origin/main declares
   `ARG REGISTA_REF=` (the build-arg is silently ignored, default SHA used) —
   unify on one ARG name.
3. `SUITE.lock` — a **face-local lock in a DIFFERENT shape**: YAML `regista_ref`
   (container-focused: `regista.ref` SHA + `container` image), *not* the TOML
   `[spine]` shape agent-notes uses. **Decision needed:** either (a) convert
   dossier's lock to the TOML `[spine]` shape (uniform, `dev-install.py` reads it
   directly) and fold the container-pin info elsewhere, or (b) keep the YAML shape
   and teach `dev-install.py`/`suite_lock.py` to read `regista.ref`/a version from
   it. (a) is cleaner long-term; (b) is less churn. The image job reads this file,
   so whichever is chosen, the image build must stay green.
- **`88d14a1` / `origin/deploy/k8s-and-pypi` — status (2026-07-21, resolved):**
  this was NOT a "broken stray commit" (my earlier framing was wrong) — it is the
  **owner's own real work**: an 18-file branch with the PyPI rename **and** a full
  k8s deployment set (`deploy/k8s/*`, `scripts/gen-k8s-secret.py`, plan 023). Per
  the owner's Option-B decision it was **split**: the branch is now **pushed to
  origin** (`deploy/k8s-and-pypi`, no longer local-only); the name reconciliation
  landed as **dossier PR #5** (`[project].name` → `dossier-hraedon`, already on
  `origin/main`); the **k8s manifests** are their own future reviewed PR (plan
  023); and the **Dockerfile PyPI switch + regista-pin cleanup above is this B2
  pass's job** — cherry-pick the good Dockerfile intent from
  `origin/deploy/k8s-and-pypi`, drop the monkeypatch, pin `0.5.3`. Still: **branch
  B2 work from `origin/main`** (use `scripts/agent-worktree`), and treat
  `deploy/k8s-and-pypi` as a reference for the Dockerfile/k8s intent, not a base to
  merge wholesale.

### acb (agent-capability-broker) — DECISION: cross-repo-check only
- acb's **CI does not install or pin regista at all** (it installs `.[dev]` and
  stubs regista via `FakeResolver` in tests; the `suite-secrets` extra pins
  `regista-hraedon>=0.5.1,<0.6` but CI never installs it). So acb has **no
  develop-against-main drift** — the `dev-install.py` regista-resolution machinery
  doesn't apply.
- **Recommendation:** give acb a face-local `SUITE.lock` `[spine]` (or a minimal
  marker) purely so the **cross-repo lock-agreement check** can include it, but do
  NOT port `dev-install.py` (there's nothing for it to resolve). Judgment call —
  could also leave acb out entirely and document why.

## The cross-repo lock-agreement check (the piece the pilot deferred)

The pilot made each face-local lock the in-repo SoT and synced it to the umbrella
`agent-suite/SUITE.lock` **by convention only**. B2-generalize adds a **mechanical**
check that each face-local `[spine].version`/`sha` **equals** the umbrella
`[components.regista].version`/`revision`.

- **Where:** recommend **agent-suite-side**, alongside the existing `feature-probes`
  job (single enforcement point; feature-probes already checks out each sibling at
  its lock revision). It would additionally read each sibling's face-local lock and
  assert agreement with `[components.regista]`. Alternative: per-sibling CI fetches
  the umbrella lock and asserts — more copies, weaker single-source guarantee.
- The per-repo `test_develop_against_lock.py` (from the pilot) stays as the local
  mechanical control (no hardcoded pin / no unguarded `git+@ref`); the cross-repo
  agreement is the NEW enforcement on top.

## Also needs doing while here (umbrella lock maintenance)

The umbrella `agent-suite/SUITE.lock` component **revisions are now stale** after
the B3 merges — they still point at pre-merge SHAs:
`[components.agent-capability-broker].revision = 9610aef` (now `2b47391`),
`[components.agent-provenance].revision = e29236c` (now `86b038d`),
`[components.dossier].revision = a4a6056` (now `f218172`).
`feature-probes` checks siblings out at these revisions with `--check --strict`;
bump them to the post-merge tips as part of the B2-generalize lock work (mind
`test_interop_ci_pins_match_suite_lock`, which couples lock revisions to the
`<COMPONENT>_SHA` env pins in agent-suite `ci.yml`).

## Recommended sequencing

1. **cairn** — port the machinery (no drift to fix; proves the pattern).
2. **dossier** — the 3-artifact alignment (CI + Dockerfile + face-lock), remove the
   dead monkeypatch, resolve the lock-shape decision. Branch from `origin/main`.
3. **acb** — cross-repo-check inclusion only (or documented exclusion).
4. **agent-suite** — the cross-repo lock-agreement check (+ bump the stale umbrella
   component revisions; keep `test_interop_ci_pins_match_suite_lock` green).

## Discipline / landmines checklist

- **Branch from `origin/main`, not local `main`** — dossier's k8s/publish work
  lives on `origin/deploy/k8s-and-pypi` (now pushed; the rename half already landed
  as PR #5), so a stale local `main` can still drag in unmerged pieces; agent-suite's
  local main was behind origin at handoff time. Use `scripts/agent-worktree` (B0).
- **Validate on CI early** — the dossier `image` failure only surfaced at PR CI,
  not locally. Push and watch, especially the Docker build job.
- **Kit needs py ≥ 3.12** — any member CI still on 3.11 must bump (cairn already
  done in #7; check the rest as you touch them).
- Reproduce regista-writing paths hermetically (leaked prod `REGISTA_DSN` via
  `suite.env` bit the agent-notes smoke work — see the project memory).

## Reference values (authoritative as of 2026-07-21)

- Umbrella `[components.regista]`: **version `0.5.3`**, **revision `9718b94`**
  (`regista_library_version = "0.5.3"`). All face-local `[spine]` locks must match.
- Pilot: agent-notes **PR #13 / origin `0bb9edb`** (file list above).
- Merged B3 retrofits: acb #17 (`2b47391`), dossier #4 (`f218172`), cairn #7 (`86b038d`).

## NOT part of B2-generalize (separate follow-up)

acb's **act-path operational exit-code reclassification** — `exec` /
`install-harness` / `reconcile` / `register` still return exit 2 on operational
errors (the B3 retrofit deliberately fixed only the read-only `doctor` path). The
load-bearing `install-harness --dry-run` = 2 signal must be preserved. Needs
**live cred-skill validation** (`exec` is the live `cred-*` skill path), so it's
its own careful pass, not part of the coupling-tax work.
