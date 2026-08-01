# Plan 022 — Reduce the tax; reset what only costs

**Status: DRAFT** (2026-08-01, for owner review; revised the same day
after the owner ratified a clean-slate mandate — *"if it makes sense to
temporarily suspend correctness to arrive more painlessly at a good end
state, that is acceptable… I would rather come out of this with
something whose architecture is defensible than something with a hundred
migrations and a novella of technical explainers about why."*)

Plans 020 and 021 ask whether the suite is correct. This one asks
whether it is worth its own overhead — and, given the mandate, which of
its costs exist only to preserve things that are not worth preserving.

## The measurement that reframes everything

The estate holds **263,646 events**. Of those, **246,378 carry the
identity conflict** that Plan 021's WI-055 work was designed around
(`actor_id` with a `kind:` prefix while `actor_kind` says otherwise).

The distribution is not uniform. It is this:

| Scope | Events | Conflicted |
|---|---|---|
| `agent_provenance` (cairn session capture) | 259,004 | 246,324 |
| All 24 other projects combined | 4,642 | **54** |

**99.98% of the identity problem is capture telemetry — the suite
watching itself get built over two months.** The entire compatibility
apparatus we specified for it (a `principal_kind_conflict` state, a
`legacy_conflated` classification, an N-hop identity linkage record,
per-project strict-mode activation, a pre-v5 unsigned-metadata caveat,
and the standing rule that grammar must never be enforced at verify) is
machinery to protect that telemetry. Its content has no downstream
consumer; its value was demonstrating that capture works, and it has
done that.

Fifty-four stray events sit in the tracker projects. Fifty-four is not
an architecture problem.

## Part 0 — The reset (do this first; everything else shrinks)

**Archive the `agent_provenance` capture corpus and restart it under the
new identity model.** Export it as a signed bundle, store it as
historical evidence outside the live plane, truncate the project, and
begin clean.

What this deletes from the design, permanently:

- No legacy branch in the identity specification.
- No `principal_kind_conflict` state to compute, surface, or explain.
- No `legacy_conflated` classification.
- No N-hop old-to-new linkage record, and no signed cutover record.
- No per-project strict activation — **every project is strict from day
  one**, grammar enforced at enrollment *and* append.
- No pre-v5 envelope caveat: require v5, drop the older reader path.
- `actor_kind` becomes derivable from the principal kind instead of a
  separately-stored field that can contradict it.

For the 54 tracker events: correct them in place as part of the cutover.
They are individually inspectable.

**This is the whole argument of the plan.** The identity model was
retrofitted after data existed, and nearly all of that data is
self-observation. Discarding it converts a permanent compatibility
burden into a one-time export.

**Exit:** the identity specification has no "legacy" section; a fresh
`agent_provenance` chain begins under one grammar; the archived bundle
verifies standalone.

## Part A — Structural changes, now cheap under the mandate

### A1. One identity specification, no compatibility model

With Part 0 done, this collapses from "a spec plus a legacy regime" to a
spec. Define the dimensions once — acting principal, execution kind,
delegation — with grammar `kind:subject`, enforced everywhere a
principal is created or an event is appended, and derive everything
else. Lineage capture (regista WI-214), delegation (WI-008) and witness
enrollment (WI-238) become implementations of it rather than parallel
designs.

Still design for a **third** model: an IdP subject will eventually
replace today's locally-minted one. But "designed for" now means a
stable subject field and a documented re-issue path — not a live mapping
table.

### A2. Delete agent-notes' dual write path

`_native.py` (902 lines) and `_regista.py` (483) both implement
work-item mutation, and the degrade path is the larger. BC-027, WI-020
and WI-021 are drift between them. Under the mandate: **delete
`_native` outright**, no reconciliation, no migration. Degrade means
refuse-and-say-so, which is the principle already ratified for content
(cairn WI-035) applied to state.

### A3. Consolidate into one workspace — RATIFIED

The deciding question was whether any component is meant to be
independently published. **Owner's answer (2026-08-01): publication
needs do not outrank ease of use or development — the suite's value as a
portfolio artifact is stronger if the suite itself works well.** That
removes the only argument for the current topology.

**Measured coordination surface, today:**

| Machinery | Count |
|---|---|
| CI workflow files | 9 across 7 repos |
| `SUITE.lock` files | 6, each a hand-synced copy of umbrella data |
| `dev-install.py` / `suite_lock.py` copies | 4 repos × 2 |
| Identifier-gate script copies | 7 |
| CLI-conformance harness copies | 7 |
| **Total coordination surface** | **~6,300 lines** |

Plus `agent_suite/lock.py` (996 lines) and `release_manifest.py` (737),
whose central job is reconciling versions *between repositories*.

Most of that is six near-identical copies of the same three ideas. In a
single uv workspace:

- 9 workflows → 1 (plus agent-wake's, if it stays out per A5).
- 6 `SUITE.lock` files → **0**. There is no spine to pin when regista is
  in-tree; the lock's cross-repo revision pairing becomes vacuous. (The
  artifact-era half — verifying installed wheel hashes against the
  release manifest on a deployed host — is real and survives, so
  `lock.py` shrinks rather than vanishing.)
- `dev-install.py` / `suite_lock.py` → 0. "Develop against the lock" is
  just "develop against the tree."
- 7 identifier gates and 7 conformance harnesses → 1 each.
- Cross-component changes become **one atomic PR** instead of N PRs with
  merge-order constraints. Tonight's four-PR spine bump becomes a
  one-line edit.
- **This also subsumes the previous draft's "stop vendoring the spine
  pin" item** — there is nothing left to vendor.

**Scope:** one workspace repo containing `regista`,
`agent-provenance`, `agent-notes`, `agent-suite`, `dossier` and `acb`
as independently-versioned packages. `dossier` being a deployable
service is not a reason to split — a monorepo builds a container from a
subdirectory with a path filter. **`agent-wake` stays separate**, not
for publication reasons but because A6 descopes it: keeping an
experimental component out of the GA repo's CI is the point.

**What agent-suite becomes.** A substantial part of the umbrella's
purpose is coordinating repositories, and that purpose evaporates. What
remains is genuinely valuable and should be stated as its new charter:
the operator CLI — bootstrap, onboard/offboard, backup/restore/
verify-restore, schedule/services, doctor aggregation, release
manifests. It stops being "the thing that holds seven repos together"
and becomes "the thing an operator runs."

**Migration shape (one pass, no interim state):** `git subtree`-style
imports preserving each component's history into `packages/<name>/`, one
root `pyproject.toml` workspace, one CI with path filters, one
identifier gate, one conformance harness; archive the old repos
read-only with a pointer. Do it in a single change — a partially
consolidated estate is worse than either endpoint.

### A4. Tracker admin plane

The gates deadlocked twice this week: nine items could not leave a false
state because `adversarial_review` demanded a lineage fact the history
lacked, and the only bypass would write a false assertion into a signed
chain. Add a **signed admin-correction transition**, typed as a
correction, recording actor, reason and the state it overrides. This
adds a path; it removes no check.

### A5. Descope agent-wake from the GA gate

Roughly a quarter of the estate's open items, the youngest component,
and not on the critical path for multi-user attested work. Mark it
experimental and non-GA-gating. Clearest single cost/benefit lever
available.

## Part B — Mechanical fixes

- **B1. Verified `implemented_by`.** Items in a review state must carry
  a commit or PR reference that resolves. Eight regista items sat in
  review this week with no code anywhere; nothing detected it.
- **B2. Baseline-diff CI gating.** Record main's failure set; a PR fails
  only when it *adds* to it. Restores CI's information content.
- **B3. Health checks name the action they performed.** A machine-
  readable `action_performed` field; a check that cannot name an
  executed action is definitionally an observation, and the conformance
  kit can fail it mechanically. Six observe-vs-verify defects in a
  month — including inside fixes for that class — shows discipline is
  not the fix.
- **B4. Docs assert machine-checkable claims.** Four silent
  doc/reality divergences this week alone.
- **B5. Record merge provenance,** not orphaned pre-squash SHAs.

## Part C — What the mandate does *not* license

- **No gate is weakened.** A5 adds a correction path; it removes no
  check. The gates firing against their own maintainer this week is the
  strongest evidence the suite works, and that property is the reason
  the suite exists.
- **No fail-open.** "Suspend correctness" means *discard data whose only
  value is that it exists*; it never means ship a check that reports
  success it did not establish.
- **No half-migrations.** The point of the mandate is to avoid
  accumulating compatibility layers. A reset that leaves a legacy reader
  path behind has bought nothing.
- **The archive is real.** Part 0 exports and verifies before it
  truncates. Discarding without a verified archive is not the same
  decision.

## Sequencing

Part 0 first — it is a day's work and it deletes most of A1's
complexity. A4 and B1 next, so the tracker stops accumulating false
state. B2 next, because it makes everything after it cheaper to review.
A5 is a scope call available immediately. Then A3 (the consolidation) as
one pass, and A2 and A1 land inside or just after it — both are far
cheaper once there is a single tree to change atomically. B3–B5 fold into whatever touches them.

## The metric to watch

The ratio of events describing work *on* the suite to events describing
work the suite *witnessed*. Today it is 93.5% the former, which is what
Part 0 is about. If that has not moved materially within a few months of
real users, the suite has become the product rather than the tooling.
