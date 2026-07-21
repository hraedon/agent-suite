# Handoff — finish the coupling-tax initiative (B2 pilot → B3 → B2 generalize)

**Relationship to prior work:** this continues Plan 019
(`plans/019-reduce-cross-member-coupling-tax.md`). **B0** (per-agent worktrees)
and **B1** (the conformance kit as a published wheel) are **done and merged**.
What remains is **B3** (finish the CLI contract across the other four
components) and **B2** (the "develop against locked versions" convention — the
plan's payoff). This handoff recommends the order to take them in, and why it is
**not** a strict `B3 → B2`.

## Why this exists (diagnosis, sharpened by the 2026-07-21 session)

Plan 019 sequenced B2 *after* B3 on the reasoning that developing against a
locked substrate is only as good as that substrate's contract discipline. That
is true for the **generalization** of B2 across all members — but it over-orders
the **pilot**. Two facts learned since:

1. **The substrate B2 cares about most is already contract-clean.** B2 =
   "member X's dev + CI installs its siblings from the pinned released versions
   in SUITE.lock." The sibling that nearly everything builds against is
   **regista** (the spine), and regista is already CLI-contract-v1 and locked
   (0.5.3, from PyPI). The four components B3 targets
   (cairn / acb / agent-wake / dossier) are mostly *leaf* tools, not the
   substrate members develop against. So a B2 **pilot** has a clean substrate
   **today**, without waiting for B3.

2. **The session produced a live, painful proof of B2's value.** The interop
   job on `main` was red because the Plan 018 P2 skill-smoke suite was developed
   against a *newer agent-notes than SUITE.lock pinned* — the locked SHA
   predated the P0 error envelope, so the suite asserted contract behavior the
   locked component didn't emit. That is exactly the develop-against-`main` bug
   class B2 exists to kill. Fixing it took a two-DSN diagnosis **and** a lock
   bump (agent-suite PR #39). Encode the prevention (develop-against-lock) while
   the lesson is concrete — the same "cheap + protective, so do it first"
   logic that put B0 first.

Conclusion: **split B2 into a pilot and a generalization.** The pilot does not
need B3; the generalization does.

## The work, sequenced

### Step 1 — B2 pilot on `agent-notes` (do first; small; protective)

agent-notes is the repo that just got bitten, so it is the honest place to prove
the fix.

- **Deliverable:** `scripts/dev-install` (or `make dev`) in agent-notes that
  reads the suite's `SUITE.lock` and installs its siblings at the **locked**
  versions — regista from PyPI at the locked version (`regista-hraedon==<locked>`),
  any other sibling at its locked SHA — instead of editable checkouts / `@main`.
  The **same install shape** backs that repo's default CI lane. Document
  `SUITE.lock` as the single source of truth for "what to develop against."
- **Escape hatch (required):** a documented `DEV_AGAINST=main` (or
  `DEV_AGAINST=<ref>`) that installs siblings from `main`/a branch for *deliberate*
  cross-member work — so the coupling is channeled to one obvious switch, not
  forbidden. A CI job that installs a sibling from `main` **without** the hatch
  fails.
- **Acceptance (make it concrete):** show this would have caught the 2026-07-21
  skew — develop agent-notes against the locked regista and run the skill-smoke
  path; a divergence between locked and `main` sibling behavior is visible before
  integration, not at interop time.
- **Enforcement:** CI (the default lane installs from the lock) + convention.
  Near-zero cost, immediately useful.

### Step 2 — B3: finish the contract for the other four (the grind)

Tracked as **agent-suite WI-023**: contract audit + kit adoption for
**cairn (agent-provenance), acb, agent-wake, dossier**.

- **This is far cheaper now than when Plan 019 was written.** B1 made the kit a
  normal dependency: per-component adoption is
  `agent-suite-conformance==1.0.0` in the dev/test extra + run it in that repo's
  CI — **no git+SHA gymnastics, no CI-install workaround.** That ease is the
  payoff B1 was for; spend it here.
- Per component: add the kit, run the conformance suite, expect it to surface
  real contract violations (that is the point), file per-repo WIs, fix, land.
- Sequence by dependency — regista-adjacent components first.
- As each becomes contract-clean, it raises the quality of the substrate B2
  develops against.

### Step 3 — B2 generalize (the culmination)

Roll the `make dev` / develop-against-lock convention from the agent-notes pilot
out to the remaining members, once B3 has raised their contract floor. This is
the point at which "develop against the locked substrate" is uniformly safe,
because the locked substrate is uniformly contract-v1.

## Non-goals (unchanged from Plan 019 §4)

- **Monorepo.** The coupling tax is the cost of the polyrepo finished
  incompletely, not evidence the model is wrong. Finishing it (B2/B3) is the fix.
- **Full IaC for Vault / a release orchestrator.** Premature for one operator
  pre-1.0; a mechanical test already keeps the lock and CI pins honest.
- **An agent-assignment orchestrator, or new component verbs.** B2/B3 change how
  members are developed and contract-checked against each other, not what they do.

## Sequencing

```
now ─┬─ B2-pilot   develop-against-lock on agent-notes   (cheap, protective — first)
     │
     ├─ B3         contract + kit for cairn/acb/wake/dossier (WI-023; grind, now cheap)
     │
     └─ B2-general roll the convention to all members     (culmination; after B3)
```

The pilot does not block on B3 and encodes this session's lesson immediately.
B3 is the multi-repo grind, unblocked and de-risked by B1. B2-general lands last,
once the whole substrate is contract-v1.

## First concrete step

Start with the **B2 pilot on agent-notes** (Step 1). It is small, needs nothing
from B3, and would have prevented the interop break this initiative just spent a
session fixing. Do it before the B3 grind, mirroring how B0 went first.

## Grounding / where to look

- **The plan:** `plans/019-reduce-cross-member-coupling-tax.md` (diagnosis,
  B0–B2, the monorepo-rejection decision record + falsifier).
- **The live proof of B2's value:** agent-suite PR #39 (interop unbreak) — the
  smoke suite was developed against newer agent-notes than `SUITE.lock` pinned;
  fix = two-DSN separation + lock bump `496914709 → be6ae6b`. The 2026-07-21
  `project-agent-suite` memory blocks narrate the whole diagnosis.
- **What B1 delivered (makes B3 cheap):** `agent-suite-conformance` 1.0.0 on
  PyPI; regista/agent-notes now consume it as a pinned version dep (regista #12,
  agent-notes #12). Copy that adoption shape for the other four.
- **The clean lock-bump precedent (surgical, not full-regenerate):** PR #37 and
  the agent-notes bump in PR #39 — bump `SUITE.lock` + the coupled ci.yml SHA
  pins together (the mechanical `test_interop_ci_pins_match_suite_lock` enforces
  it).
- **Landmines:** `acb` lives at `/home/itadmin/.local/bin/acb` (not the venv
  one); Python 3.13/3.14 for CI; never `git add -A` in a shared tree — and
  `scripts/agent-worktree` (B0) is the paved path if multiple agents work
  concurrently; the smoke DB schema step now fetches the exact `AGENT_NOTES_SHA`
  and fails loud — do not reintroduce a `|| true` fallback.
