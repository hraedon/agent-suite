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

### A3. Stop vendoring the spine pin

Four `SUITE.lock` copies of the umbrella's regista pin is why a version
bump cost four PRs. Publish the umbrella lock as a consumable artifact;
components read the pin rather than carrying a hand-synced copy. No
back-compat shim needed.

### A4. Repo topology — the one genuinely open question

The strongest available argument: **agent-suite largely exists to manage
the consequences of there being seven repos.** Lock generation, spine
pinning, release manifests, cross-component doctors, bootstrap
orchestration — a substantial fraction of the umbrella's purpose is
coordination overhead that a single workspace would not create.

Consolidating is cheap now and expensive once anyone external depends on
the current shape, so this is close to now-or-never. The deciding factor
is one thing only the owner knows: **is any component intended to be
independently published or open-sourced?** If yes, keep it separate. If
no, it is paying repo overhead for an option nobody will exercise.

Recommendation, pending that answer: merge `regista`, `agent-notes`,
`agent-provenance` and `agent-suite` into one uv-workspace repo with
independently versioned packages; keep `dossier` (a deployable service),
`acb`, and `agent-wake` separate. That removes most of the tax while
preserving the genuinely separable things. If A3 lands first and the
remaining friction is tolerable, this can still be declined — but it
should be declined deliberately, not by default.

### A5. Tracker admin plane

The gates deadlocked twice this week: nine items could not leave a false
state because `adversarial_review` demanded a lineage fact the history
lacked, and the only bypass would write a false assertion into a signed
chain. Add a **signed admin-correction transition**, typed as a
correction, recording actor, reason and the state it overrides. This
adds a path; it removes no check.

### A6. Descope agent-wake from the GA gate

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
complexity. A5 and B1 next, so the tracker stops accumulating false
state. B2 next, because it makes everything after it cheaper to review.
Then A4 as a decision (not code), followed by A3, A2, A1. A6 is a scope
call available immediately. B3–B5 fold into whatever touches them.

## The metric to watch

The ratio of events describing work *on* the suite to events describing
work the suite *witnessed*. Today it is 93.5% the former, which is what
Part 0 is about. If that has not moved materially within a few months of
real users, the suite has become the product rather than the tooling.
