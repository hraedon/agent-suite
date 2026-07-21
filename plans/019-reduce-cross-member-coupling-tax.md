# Plan 019 — Reduce the cross-member coupling tax (finish the polyrepo model)

**Status:** Proposed 2026-07-20.
**Owner:** agent-suite owns the conventions and the shared helpers (worktree
helper, `make dev` install shape, the kit-as-artifact release); each component
owns adopting them in its own repo. This plan tracks the umbrella; per-component
adoption is filed against each repo.
**Depends:** Plan 018 (CLI contract v1 + conformance kit + version-gated skill
sweep) — this plan builds on the same SUITE.lock-as-source-of-truth mechanism
Plan 018 proved, and its B3 leg *is* the remainder of Plan 018's WI-4/WI-3-P2.
**Origin:** owner handoff 2026-07-20 ("reduce the cross-member coupling tax"),
authored as the parallel, longer-horizon track to the Plan 018 P2 skill sweep.
That track finishes the **contract tax** (skills working around tool
misbehavior). This one attacks the **coupling tax**: the friction of doing
feature work on *one* suite member when it is entangled with the others and the
release path.

## 0. Diagnosis — the coupling tax is the cost of an 80%-finished model

The suite is a **polyrepo of tightly-coupled components released together**:
independent repos behind versioned contracts, held compatible by `SUITE.lock`.
That model was chosen deliberately over a monorepo and it is right — it
preserves independent publishability and the component boundaries we built. But
it is implemented ~80%, and the gap surfaces as a recurring tax whenever a
member is touched. Concrete evidence, all from the **2026-07-20 regista 0.5.3
release session** (one session, four distinct hits):

1. **PyPI publish broke** on a cross-member dev dep: the conformance kit was a
   `git+SHA` reference in regista's metadata, and PyPI rejects direct-URL deps
   in uploaded wheels. Worked around by moving the kit from `pyproject` to a
   dedicated CI-install step (regista PR #11, agent-notes PR #11) — a workaround,
   not a fix. Live today: both repos carry
   `pip install "agent-suite @ git+https://github.com/hraedon/agent-suite.git@<SHA>"`
   as a CI step (`regista/.github/workflows/ci.yml`,
   `agent-notes/.github/workflows/ci.yml`).
2. **agent-notes CI went red from a rename bug** surfaced only at integration
   time — the class of bug you catch by developing against the artifact the
   suite composes, not against a sibling's `main`.
3. **Bumping one member meant editing SUITE.lock + four CI SHA interop pins**,
   kept in sync by a mechanical test. (The bump itself is clean and surgical —
   PR #37 — but the fan-out is real.)
4. **Two agents (me + glm) collided in one working tree** — the session's
   scariest moment, averted only by reaching for `git worktree` ad hoc.

None of these means the model is wrong. They are the cost of the model
**finished incompletely**. The fix is to *finish the chosen model + add two
cheap conventions* — not adopt a new paradigm.

## 1. Outcome

Feature work on a single suite member happens **in isolation, against a stable
substrate**, with cross-member coupling touched only on a deliberate,
already-proven-surgical lock bump. Concretely, when this plan lands:

- Concurrent agents never share a working tree by default (B0).
- No suite CLI carries a `git+SHA` install hack for the conformance kit; it is a
  normal pinned version dependency (B1).
- A member's dev + CI environment installs its siblings **from the released
  versions pinned in SUITE.lock**, so you develop against what the suite ships,
  not against `main` (B2) — which is the direct mechanism for "feature work
  without the workarounds," and catches the rename-bug class (evidence #2) at
  its source.

## 2. The work, sequenced

Legend for who enforces (per `docs/process-calibration.md` §4): **store /
CI / githooks / harness**. A convention that lives only in a doc sentence is a
request, not a control — each item below names its enforcement layer.

### B0 — Isolated dev environments as the default (do first; cheap; protective)

Make per-agent `git worktree`s (or per-agent clones) the **standard** way
concurrent agents operate on a repo — not an ad-hoc rescue. Evidence #4: this
session only avoided clobbering glm's uncommitted work because I isolated by
hand.

- **Deliverable:** `docs/agent-worktrees.md` (convention) + a helper
  `scripts/agent-worktree <repo> [<name>]` that creates/attaches a per-agent
  worktree under a conventional path and prints the path to `cd` into. A note in
  each repo's AGENTS.md pointing at the convention.
- **Enforcement:** harness (convenience) + githooks. Realistically B0 is
  layer-3/4 — you cannot force a foreign harness to use a worktree. The
  *protection* against the specific failure (clobbering another agent's
  uncommitted work) is already partly enforced by the standing rule **never
  `git add -A` in a shared tree**; B0 removes the shared tree so the rule has
  less to defend. Consider a pre-commit assertion that warns when committing in
  the canonical clone while other worktrees hold uncommitted changes (advisory,
  not blocking).
- **Cost:** near-zero. **Why first:** removes an entire failure mode and
  protects the Plan 018 P2 sweep and all future multi-agent work. Land it first
  or in parallel with everything else.
- **Non-goal:** no orchestrator that *assigns* worktrees to agents; the operator
  (me) drives which agent works where. This is a helper + a habit, not a system.

### B1 — Conformance kit as a versioned artifact

The `git+SHA`-in-`pyproject` kit is what broke regista's publish (evidence #1)
and forced the CI-install workaround now live in regista/agent-notes CI. Replace
it with a **normal pinned version dependency** so members depend on it like any
other dep — no direct-URL hack, no CI-install gymnastics, publishable wheels by
default.

- **Options (decide at execution, recommendation first):**
  - **(a, recommended) Split the kit into its own tiny PyPI package**
    `agent-suite-conformance`, versioned independently, depending on nothing
    heavy. Members add `agent-suite-conformance==X.Y` to their dev extra.
    Cleanest; matches how the family already consumes the identifier gate as a
    pinned thing; keeps agent-suite (the orchestration package, `dependencies =
    []` stdlib-only core) from acquiring a public-package release obligation it
    doesn't otherwise want.
  - **(b) Publish agent-suite itself to PyPI** with a `conformance` extra.
    Rejected unless we want agent-suite public+released for other reasons — it is
    private, pre-1.0, and stdlib-only by charter; releasing the whole
    orchestration layer to distribute one test kit is over-scoped.
  - **(c) Vendable single-file runner** distributed by a `sync-conformance`
    script with a version stamp the kit checks at runtime (the identifier-gate
    distribution pattern). Viable if we want zero PyPI footprint, but a copied
    kit risks divergent copies (the exact anti-pattern Plan 018 WI-2 called out:
    "not copy-or-import"). Only if (a) is blocked.
- **Deliverable:** kit published/vendable as a **pinned version**; regista and
  agent-notes drop the `git+SHA` CI step and gain a normal dev-dependency line;
  agent-suite's own CI (dogfood) consumes it the same way; the kit's version
  recorded where SUITE.lock or `data/cli-conformance.json` already tracks
  kit-version-per-component (Plan 018 WI-2 accept criteria).
- **Enforcement:** CI (each consumer's conformance job) + the packaging itself
  (a version dep is honest by construction where a git+SHA-in-metadata is not).
- **Coordinate:** touches the exact CI install steps the Plan 018 P2/kit work
  touches (`regista/.github/workflows/ci.yml:49`,
  `agent-notes/.github/workflows/ci.yml:48,101`). B1 and the remaining P2 sweep
  must not fight over those files — sequence B1's CI edit *after* a given
  component's P2 rows land, or do them in the same PR per component.

### B2 — "Develop against locked versions" convention (the payoff)

**The direct mechanism for "feature development on a member without the
workarounds."** Today, developing member X pulls siblings in as editable
checkouts / `git+SHA`, so you test against *main*, not against *what the suite
ships*. Change it: member X's dev + CI installs its suite dependencies **from the
pinned released versions in SUITE.lock** (e.g. regista from PyPI at the locked
`0.5.3`).

- **Effects:**
  - feature work on X happens in isolation against a **stable substrate**;
  - cross-member coupling is touched **only** on a deliberate lock bump — which
    we proved is clean and surgical (PR #37: `REGISTA_SHA` + pip pin, interop +
    feature-probes green end-to-end);
  - integration surprises (the rename-bug class, evidence #2) get caught because
    you develop against the same artifact the suite composes.
- **Deliverable:** a small per-repo `make dev` / `scripts/dev-install` that
  reads SUITE.lock (single source of truth) and installs each sibling at its
  locked version; the same install shape used in that repo's default CI lane;
  documentation naming **SUITE.lock as the single source of truth for "what to
  develop against."** An explicit, documented **escape hatch** for the deliberate
  lock-bump workflow: `DEV_AGAINST=main` (or equivalent) installs siblings from
  `main`/a branch when you are *intentionally* doing cross-member work, so the
  convention channels the coupling to one obvious switch instead of forbidding it.
- **Enforcement:** CI (the default lane installs from the lock; a job that
  installs a sibling from `main` without the escape hatch fails) + convention.
- **Reads best last:** B2 is the culmination and is clearest once the contract is
  enforced across members (B3) — developing against a locked substrate is only as
  good as that substrate's contract discipline. Land B2 after B3 has raised the
  floor.

### B3 — Finish the contract loop (tracked in Plan 018)

= the remaining Plan 018 P2 skill sweep **+** converting cairn / acb / agent-wake
/ dossier to CLI contract v1 (**agent-suite WI-023**, filed 2026-07-20). Retires
the *contract* tax permanently and raises the quality of the substrate B2
develops against. **Tracked in Plan 018 / WI-023, not re-opened here** — listed so
the whole picture is in one place. This plan does not duplicate that work; it
consumes its output.

## 3. Decision record — polyrepo-finished, not monorepo (process-calibration §1)

- **Decision:** Keep the polyrepo-behind-versioned-contracts model and *finish*
  it (B0–B3); do **not** migrate to a monorepo.
- **Evidence:** four coupling-tax hits in the 2026-07-20 session (§0). Each is a
  *finish-the-model* gap (a git+SHA where a version dep belongs; a missing
  develop-against-lock convention; a missing worktree habit), not a *wrong-model*
  symptom. The one clean operation in that session — the lock bump (PR #37) — is
  the model working as designed. Cost of B0–B2 is measured in helper scripts and
  conventions, not a system: not yet quantified in wall-time, marked provisional
  on that axis.
- **Rejected alternative — monorepo:** would erase the coupling tax outright but
  sacrifices independent publishability (regista and adcs-lens ship to PyPI under
  a real name; agent-notes/dossier are private) and the component boundaries
  deliberately built, and the migration cost is enormous for a solo pre-1.0
  suite. More data would not change this: the boundaries are a *product*
  requirement (attestation, independent release, cross-harness reuse), not a
  performance guess a benchmark could overturn.
- **Rejected alternative — full IaC for Vault / a release orchestrator:** the
  Vault policy bug (WI-020) was a one-off glob error, not a structural gap; a
  mechanical test already keeps SUITE.lock and the interop pins honest. Premature
  automation for one operator pre-1.0.
- **Could-be-wrong-if:** after B0–B2 land, a *new* cross-member release session
  still incurs ≥2 distinct coupling-tax hits of the finish-the-model class (new
  direct-URL deps appearing, integration bugs that develop-against-lock would
  have caught, or another shared-tree collision) that the conventions did not
  prevent. Observe: the next two full lock-bump/release sessions after B2 lands;
  count coupling-tax incidents in each session's reflection. Threshold that
  reopens the monorepo question: ≥2 such hits per session across two consecutive
  sessions despite B0–B2 being in force. Below that, the finished polyrepo is
  vindicated.
- **How to apply:** treat SUITE.lock as the single source of truth for "what to
  develop against"; add the kit as a version dep; default concurrent agents into
  worktrees. Cross-member coupling is expressed *only* through a deliberate lock
  bump, which stays a surgical PR.

## 4. Non-goals (explicit)

- **Monorepo.** See §3. No.
- **Full IaC for Vault / a release orchestrator.** See §3. No.
- **An agent-assignment orchestrator** (B0 is a helper + habit, not a scheduler).
- **New verbs or behavior changes to any component CLI.** This plan changes *how
  members are developed and released against each other*, not what they do.

## 5. Sequencing (both handoffs together)

```
now ─┬─ B0  isolated dev environments        (cheap, protective — do first/parallel)
     │
     ├─ P2  skill de-workaround sweep          (Plan 018 WI-4; needs the version-gate)
     │
     ├─ B1  kit as a versioned artifact        (de-hacks the CI-install P2 relies on)
     │
     └─ B2  develop-against-locked-versions    (the payoff; builds on the contract done)
              └─ B3  finish contract for the other 4 (WI-023; feeds B2's substrate)
```

B0 first (protects everything). P2 and B1 run in parallel and touch overlapping
CI install steps — coordinate per §B1 so they don't fight. B2 is the culmination
and reads best once the contract is enforced across members (B3), so it lands
last.

## 6. Landmines (carried from the Plan 018 P2 handoff)

- `acb` at `/home/itadmin/.local/bin/acb`, **not** the venv one.
- Python **3.13 / 3.14** for CI (family Python-version policy).
- **Never `git add -A` in a shared tree** — the rule B0 makes easier to keep.
- Kit CI steps to coordinate with: `regista/.github/workflows/ci.yml:49`,
  `agent-notes/.github/workflows/ci.yml:48` and `:101`.

## 7. First concrete steps (this plan's own next actions)

1. Socialize/adopt this plan (owner review).
2. **B0**: write `docs/agent-worktrees.md` + `scripts/agent-worktree`, add the
   AGENTS.md pointer. (Cheapest, protective, unblocks nothing else so it can go
   immediately.)
3. **B1**: pick option (a) vs (c), file per-repo WIs for the kit-as-artifact
   swap, coordinate the CI-step edit with each component's remaining P2 rows.
4. **B2** after B3 has raised the substrate floor: per-repo `make dev` reading
   SUITE.lock + the documented `DEV_AGAINST=main` escape hatch.
