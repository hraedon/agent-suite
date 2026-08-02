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

For the 54 stray tracker events: **do not correct them in place.** An
earlier draft proposed exactly that, and the cross-lineage review
(Sol, 2026-08-01) correctly refused it — rewriting signed history is a
demonstration of the very operator-forgery problem this plan now
addresses in D9. Append signed correction events, rebuild the derived
view, or archive and reset those chains too.

**This is the whole argument of the plan.** The identity model was
retrofitted after data existed, and nearly all of that data is
self-observation. Discarding it converts a permanent compatibility
burden into a one-time export.

**Freeze an archive verifier.** D1 deletes older envelope readers from
live services, which would leave nothing able to validate the retained
evidence — the exit criterion below would be unsatisfiable. Before the
reset, build and tag a **frozen verifier artifact**: source,
dependencies, schemas, keys, test vectors, and a reproducible container.
Legacy handling is removed from live services, never from the only
software that can read the archive.

**Pre-truncation gate (all required; "the export command succeeded" is
not one of them):** immutable database snapshot; deterministic bundles;
verification by the production verifier *and* an independent
implementation; a restore-and-verify drill on a different host;
preservation of keys, revocation state, schemas, binaries and build
inputs; externally anchored manifest hashes; then a cooling-off period
before anything is deleted.

**Exit:** the identity specification has no "legacy" section; a fresh
`agent_provenance` chain begins under one grammar; the archived bundle
verifies standalone under the frozen verifier.

## Part A — Structural changes, now cheap under the mandate

### A1. One identity specification, no compatibility model

With Part 0 done, this collapses from "a spec plus a legacy regime" to a
spec. Define the dimensions once — acting principal, execution kind,
delegation — with grammar `kind:subject`, enforced everywhere a
principal is created or an event is appended, and derive everything
else. Lineage capture (regista WI-214), delegation (WI-008) and witness
enrollment (WI-238) become implementations of it rather than parallel
designs.

**AD/LDAP is in scope, not hypothetical** (owner, 2026-08-01): this
estate already runs AD. Entra may follow and is deferred; an AD-to-Entra
path is desirable but not required.

The cross-lineage review sharpened the model in a way that **amends the
ratified WI-055 decision, and the owner should confirm it**: the
envelope's actor subject should be an **immutable internal
`principal_id`**, not `kind:subject` and not any directory attribute.
The `kind:subject` grammar remains the human-facing addressing and
display form; external identities attach as **typed,
authority-qualified signed binding records** carrying `authority`,
`subject_type`, an opaque binary-safe `subject_value`, a validity
interval, and evidence. Rebinding is then a signed event, not a new
envelope version.

For AD, bind **`objectGUID` plus a stable forest/issuer identifier**.
`sAMAccountName` and `userPrincipalName` are mutable; `distinguishedName`
changes on rename or OU move; `objectSID` is domain-relative and
reissued on domain migration (`sIDHistory` is transitional evidence, not
identity). `objectGUID` survives rename, OU move and ordinary
same-forest domain moves — but **not** cross-forest recreation, which is
why issuer qualification and signed rebinding are mandatory rather than
optional. For a later Entra move, bind the same internal principal to
Entra's immutable tenant-qualified object ID; retain
`msDS-ConsistencyGuid`/`onPremisesImmutableId` as migration evidence if
AD Connect exposes it, but do not let today's envelope depend on a
particular sync configuration.

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

**Migration shape:** `git subtree`-style imports preserving each
component's history into `packages/<name>/`, one root `pyproject.toml`
workspace, one CI with path filters, one identifier gate, one
conformance harness; archive the old repos read-only with a pointer.

*Atomic release does not mean one enormous PR* — an earlier draft
conflated the two. Build ordered, individually reviewable commits on an
integration branch, rehearse the deployment, then cut **one**
incompatible release. What must be atomic is the release and the
estate's end state, not the code review.

### A4. Tracker admin plane

The gates deadlocked twice this week: nine items could not leave a false
state because `adversarial_review` demanded a lineage fact the history
lacked, and the only bypass would write a false assertion into a signed
chain. Add a **signed admin-correction transition**, typed as a correction,
recording actor, reason and the state it overrides. This adds a path; it
removes no check.

It is nonetheless a **privileged bypass** and must be built as one: a
dedicated capability rather than ambient authority, an exact target
event/state (never a broad "fix this item"), append-only semantics, a
mandatory reason, and independent approval for integrity-sensitive
transitions. A correction path that is easier to use than the gate it
bypasses will become the default route.

### A6. Work items live in regista only — the duplication above A2

**This is the largest simplification available and we all missed it,
including two rounds of review, because we were reasoning inside the
existing component boundaries.**

regista already has first-class work items: `_work_items.py`,
`_work_items_api.py`, `_transition.py`, `_claims.py`. agent-notes
implements a **second, parallel** work-item system — ~4,200 lines across
`work_item_model.py` and `core/work_item/` — with its own Postgres
tables, and then a convergence layer to keep the two in agreement:
`regista_work_item_id` and `pending_sync` columns, a dedicated
`810_regista_convergence.sql` migration, an outbox (551 lines), a
projection (274 lines), and 38 references to the foreign id.

A2 deletes the duplication *inside* agent-notes (`_native` vs
`_regista`). This deletes the duplication *between* agent-notes and
regista — the one that produced it. `pending_sync` is a column that
exists solely because there are two truths.

Look at how much of the current backlog is this one fact: WI-020
(non-atomic close in agent-notes' own transaction), WI-021 (agent-notes'
own fold resurrecting tombstoned items), BC-027 (change_log written on
one path, not the other), WI-052 (`find --text` incomplete against
agent-notes' own index), the dual identifier space that makes D2
necessary, the second database that makes D3 necessary, and the review
gate deadlocking because lineage lives in regista events while items
live in agent-notes.

**Decision: work items, transitions, claims and reviews live in regista
and nowhere else.** agent-notes keeps what is genuinely its own —
memories, breadcrumbs, links, vocabulary, workspaces/projects, the
skills, and the CLI — and becomes a *client*, not a second system of
record.

Consequences, all reductions:

- The outbox, projection, convergence migration and `pending_sync`
  disappear. So does the sync-drift bug class, permanently.
- **D3 becomes almost trivial** — most of what the `agent_notes`
  database holds is the duplicate.
- **D2 gets simpler**: one identifier space to renumber, not two that
  must stay correlated.
- A2 is subsumed: deleting `_native` is moot when neither path remains.
- The gate deadlock's root cause is removed — items and their signed
  events become the same records.

Cost: this is the single biggest change in the plan, and it should be
sequenced first among the code changes, because A2, D2 and D3 all shrink
behind it. Doing it after them means doing parts of them twice.

### A5. Descope agent-wake from the GA gate

Roughly a quarter of the estate's open items, the youngest component,
and not on the critical path for multi-user attested work. Mark it
experimental and non-GA-gating. Clearest single cost/benefit lever
available. Constraint from the cross-lineage review: **notification
delivery must never become part of attestation correctness** — if a
missed wake can change what the chain asserts, the descope is unsafe.

## Part B — Mechanical fixes

- **B1. Verified `implemented_by`.** Items in a review state must carry
  a commit or PR reference that resolves. Eight regista items sat in
  review this week with no code anywhere; nothing detected it.
- **B2. Baseline-diff CI gating.** Record main's failure set; a PR fails
  only when it *adds* to it. Restores CI's information content —
  **but must never baseline a security or integrity failure.** Only
  explicitly classified legacy failures may be baselined, each with a
  named owner and an expiry date, or the suite normalises broken gates,
  which is worse than the noise it replaces (cross-lineage review).
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
older reader path from live services (Part 0 keeps a frozen verifier for
the archive). The corpus that would have forced back-compat is being
archived anyway.

**It must carry six distinguishable identity dimensions, or D8 forces a
second envelope revision** (cross-lineage review, Sol): stable
principal, agent instance, execution/session, delegating principal *and*
delegation scope, signing key, and credential-issuance record. An
envelope encoding only `kind:subject` + `key_id` cannot express
per-agent authority later.

**And it must carry the anchoring hooks D9 needs:** domain-separated
chain commitments, explicit hash-algorithm identifiers, log/witness
identifiers, and extensible receipt references. Omitting these
guarantees another bundle-format change and possibly another envelope
change — exactly what this item exists to prevent.

Never place reusable Vault tokens or accessors in an envelope; sign a
stable *issuance-record identifier* instead.

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

### D4. Collapse regista's migration history to a post-reset baseline

Schema version 44 means a fresh install replays 44 migrations and CI
carries the test surface for all of them. Collapse to a single baseline.
**Do not renumber it "v1"** — that collides with real historical
version 1 and makes every future conversation ambiguous; use a clearly
identified post-reset baseline version, and retain the old migrations
under an archival tag. Migration *count* alone is not operational debt;
the test matrix and the replay path are. Exit is a proven
current-schema restore, not a smaller number.

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

### D8. Per-agent credential isolation — PULLED IN

An earlier draft deferred this to "when a second human appears." The
owner rejected that and the cross-lineage review agreed, with the
decisive reasoning: **waiting for a second human confuses human tenancy
with agent isolation.** Several independently-acting security principals
already exist on this host today. Host-wide AppRole sharing defeats
actor-level attestation outright — an event names one agent while any
process holding the shared credential could have performed it, which
makes the suite's core claim unsupportable rather than merely weak.

Minimum defensible implementation in this pass:

- A distinct Vault entity per agent instance, with short-lived, narrowly
  scoped tokens.
- acb authenticates the host bootstrap identity, then mints
  per-agent/session credentials from explicit capability policy.
- An auditable issuance record binding `principal_id`,
  `agent_instance_id`, `session_id`, credential lease/entity, and
  delegated authority.
- Agents cannot mint peers' credentials.
- One agent is revocable without affecting the host or other agents.
- Tests proving token A cannot exercise token B's capabilities.

Cost estimate: 1–2 engineering weeks across acb provisioning, Vault
policy layout, operator-CLI lifecycle, schema/events, migration and
isolation tests — materially cheaper now, while D1, D7, identity,
delegation and the consolidation are all already open.

This also retires the transitional host-boundary profile and the
"expires when a second human appears" clause in the credential-migration
note, and collapses that note's unit structure further.

### D9. Operator-forgery defense — PULLED IN, bounded

The earlier deferral was half right and half wrong. Right: signatures
controlled by one operator cannot prevent that operator fabricating
history. Wrong: that this justifies doing nothing. **Independent
anchoring provides meaningful post-publication rewrite detection now.**

Minimum defensible implementation:

- Periodically commit chain heads into a Merkle tree.
- Submit checkpoints to an independently administered append-only
  service (public transparency log or trusted timestamp authority).
- Store signed checkpoint receipts and inclusion proofs in evidence
  bundles.
- Verification distinguishes `locally_valid`, `externally_anchored`, and
  `anchored_before <time>` as separate states.
- **State the limitation in the product, not just the plan:** this
  detects rewriting *after* anchoring; it cannot prove pre-anchor events
  were truthful.

Cost estimate: ~1 engineering week. If no acceptable external service
exists, ship the commitment and receipt *interfaces* now and anchor to
owner-controlled offline media as an interim — but in that case **do not
claim operator-forgery resistance**. The interfaces are what keep this
out of a future envelope revision; the external service can arrive
later.

### Explicitly NOT in scope, even now

Being able to break things is not a reason to. These stay deferred with
their existing rationale:

- **Entra ID integration.** Deferred, but A1's binding-record design
  must not preclude it — an AD-to-Entra path is desirable and, per the
  owner, not a calamity if unreachable. AD/LDAP itself is *in* scope
  (A1); it was previously excluded on the false premise that no
  directory existed.
- **Full workload identity** (SPIFFE-style attestation replacing the
  AppRole bootstrap). D8 delivers per-agent isolation on top of the
  existing bootstrap; replacing the bootstrap mechanism itself is a
  separate, later change with its own trigger.
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
A5 is a scope call available immediately. **A6 comes first among the
code changes** — A2, D2 and D3 all shrink behind it, and doing them
first means doing parts of them twice. Then A3 (the consolidation) as
one pass, with A1 landing inside or just after it.

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

## Part E — Settled decisions revisited under explicit leave

The owner granted explicit leave to reopen anything, including ratified
decisions, on the grounds that anchoring to prior choices is itself a
cost. Four, beyond A6:

**E1. Drop the `kind:subject` grammar from the data model.** Once the
signed subject is an immutable internal `principal_id` (A1, per Sol),
the grammar is a *display and addressing* convention — so stop treating
it as a contract. Keeping it as one means parsing at three layers,
enforcement at enrollment and append, a prefix collision question, and
the Azure Key Vault problem we already found (AKV secret names forbid
`:`, so the grammar needs an escaping rule that exists only because the
grammar exists). Instead: principals carry a `kind` field and a display
name; the CLI may *render* `agent:foo` for humans; nothing parses it.
This deletes the grammar-enforcement work from A1 rather than
implementing it.

**E2. Right-size the archive ceremony.** Sol's pre-truncation gate
(independent verifier implementation, cross-host restore drill,
externally anchored manifest hashes, cooling-off) is correct for
production evidence — but Part 0's corpus is two months of the suite
watching itself, already judged to have no downstream consumer. Applying
production-evidence ceremony to it contradicts the judgement that
justified discarding it. Proportionate gate: immutable database
snapshot, deterministic export, verification by the frozen verifier,
recorded checksums, cooling-off. Skip the independent reimplementation
and the external anchoring *for this corpus*; those belong to D9 and to
real evidence going forward.

**E3. Consider deleting agent-wake rather than descoping it.** It has
~24 open items, no consumer outside its own tests and one wake this
session, and its function — notify a session or a human — is a webhook
plus a queue. Descoping keeps a component alive that nobody depends on;
deleting it and re-adding ~200 lines when a real requirement appears may
be cheaper than carrying it. Owner's call, since it is his build.

**E4. Do not manage this rewrite inside the thing being rewritten.**
A6, D2 and D3 renumber identifiers, merge databases and move the
work-item system — while the tracker is the coordination mechanism for
doing so. Freeze the tracker for the duration and run the rewrite from a
plain checklist in the repo, then re-enter tracked work once the new
system of record is live. This is a bootstrapping hazard, not a process
preference.

## Review record

Cross-lineage review by `openai/gpt-5.6-sol` (2026-08-01, run on
mvmcc02) adjudicated the two contested deferrals in the owner's favour
and corrected four things in the draft: rewriting the 54 stray events in
place would have demonstrated the very forgery problem under discussion;
deleting old readers would have left the archive unverifiable; "atomic
release" was conflated with "one enormous PR"; and baseline-diff CI
gating could normalise broken security gates. All are incorporated
above. One item needs owner confirmation: A1 now proposes an immutable
internal `principal_id` as the signed subject with `kind:subject` as the
addressing form, which **amends** the previously ratified WI-055
decision.

## The metric to watch

The ratio of events describing work *on* the suite to events describing
work the suite *witnessed*. Today it is 93.5% the former, which is what
Part 0 is about. If that has not moved materially within a few months of
real users, the suite has become the product rather than the tooling.
