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

## Part D — Breaking changes to take in the same pass

The owner has put deferred disruptive work in scope, explicitly
including breaking regista changes. The selection rule is not "what
could we break" but **"what will we otherwise pay for forever, and what
gets cheaper by being broken once alongside everything else?"** Each of
these is currently deferred *because* it breaks something; each is
cheapest now, with no external consumers, a corpus reset in flight, and
a single tree to change atomically.

### D1. One new envelope version — not five increments

Four deferred changes all edit the signed envelope: signed-vs-asserted
lineage (regista WI-215), the delegation chain (WI-008), deriving
`actor_kind` from the principal kind (WI-055), and pinning `key_id` on
the chain-opening event (WI-227). Shipped separately that is four
breaking versions and four reader paths.

Cut **one** new envelope version carrying all of them, and delete every
older reader path rather than keeping compatibility branches. Part 0
makes this nearly free: the corpus that would have forced back-compat is
being archived anyway. This is the single clearest instance of the
mandate — five migrations and their explainers collapse into one format.

### D2. Project-prefixed work-item identifiers

`WI-055` currently names three different items in three projects;
`WI-040` names two; `WI-038` names two. Every reference in prose, every
commit message and every review comment has to carry the project name to
disambiguate — a tax paid dozens of times in this session alone, and a
live source of misfiling. agent-notes WI-032 already proposes the fix.

Adopt per-project prefixes (`RG-231`, `AS-55`, `CN-40`, `DS-36`,
`AN-52`, `AB-17`) and renumber once. Breaking for anything that stored a
bare identifier, trivial at 4,642 tracker events, and permanently
unambiguous afterwards.

### D3. One database

The estate runs two: `regista` and `agent_notes`, on the same server,
with separate credentials, separate migration systems (agent-notes ships
14 SQL files of its own), and separate backup/restore paths. Once A2
makes agent-notes a regista client, its store is largely redundant.

Fold it in. Two DSNs become one, which also **collapses two of the four
rollout units in the credential-migration plan into one** — a direct
reduction in that plan's blast radius, not just its length.

### D4. Squash regista's migration history to a baseline

Schema version 44 means a fresh install replays 44 migrations and CI
carries the test surface for all of them. With the corpus reset, that
history has no live consumer. Collapse it to a single baseline schema at
v1. New installs run one migration; the migration test matrix collapses
with it. This is only safe while nothing external depends on
intermediate states — that window is now.

### D5. CLI contract v1, enforced atomically

acb and agent-wake still implement and test exit 2 where the ratified
contract says dry-run success is 0 (the sibling leg agent-suite WI-032
could not close). In seven repos that is a coordination problem; in one
workspace it is a single PR with one conformance run.

### D6. One bundle format change, not two

Bundle v3's registry⇄chain trust derivation (WI-209) and witness key
enrollment (WI-238) are the same trust model applied to two key kinds —
and WI-043 already ratified that witness keys must not get a second,
weaker mechanism. Ship them as one format change. While the format is
open, also prove hash agility end-to-end (WI-207) rather than
discovering at need that non-SHA-256 was never exercised.

### D7. Provider capability split

WI-235's breaking half: separate reader/writer/deleter capabilities
(`supports_write()` currently reports read-only providers writable),
reject non-string Vault values instead of coercing with `str()`, and add
`store_material()`. Small blast radius, and the coercion bug is a latent
repeat of WI-231.

### Explicitly NOT in scope, even now

Being able to break things is not a reason to. These stay deferred with
their existing rationale:

- **Per-agent credential isolation (Plan 017).** The host-as-boundary
  profile is ratified as transitional and expires when a second human
  principal appears. Build it then, against a real requirement.
- **Operator-forgery defense (WI-007).** Needs an external anchoring or
  witness ecosystem to mean anything; today's partial mitigations are
  the right posture.
- **IdP integration.** No IdP exists yet. A1 must not *preclude* it;
  building for it now would be speculative.
- **Any rewrite of the signing scheme itself.** It works, it is
  reviewed, and nothing about the reset argues for touching it.

### One-way doors — the discipline for this pass

Part 0, A3 and D1 together make this a v2 of the estate, so the
irreversible steps get explicit guards:

- **Verify before truncating.** The archived provenance bundle must
  verify standalone before the live project is cleared.
- **Old repos go read-only, not deleted.** The July publication
  remediation permanently lost 46 PR discussions; archive rather than
  repeat that.
- **One pass per change class.** A half-consolidated estate, or two
  envelope versions in flight, is worse than either endpoint.

## Sequencing

Part 0 first — it is a day's work and it deletes most of A1's
complexity. A4 and B1 next, so the tracker stops accumulating false
state. B2 next, because it makes everything after it cheaper to review.
A5 is a scope call available immediately. Then A3 (the consolidation) as
one pass, and A2 and A1 land inside or just after it — both are far
cheaper once there is a single tree to change atomically.

Part D rides the same passes rather than forming its own phase: D2, D3
and D4 belong to the consolidation change; D1 and D6 belong with A1's
identity specification, since they are its wire format; D5 and D7 are
small and land wherever their surface is already open. Nothing in Part D
should be shipped as a standalone breaking release — the point is that
they break once, together. B3–B5 fold into whatever touches them.

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

## The metric to watch

The ratio of events describing work *on* the suite to events describing
work the suite *witnessed*. Today it is 93.5% the former, which is what
Part 0 is about. If that has not moved materially within a few months of
real users, the suite has become the product rather than the tooling.
