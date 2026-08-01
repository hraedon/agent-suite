# Plan 022 — Reduce the tax before the users arrive

**Status: DRAFT** (2026-08-01, for owner review). Plans 020 and 021 answer
"is the suite correct?" This one answers a different question: **is the
suite worth its own overhead, and which of its costs are structural
rather than incidental?** It is deliberately scheduled *before* real
users, because every change here gets harder once someone outside the
maintainer depends on the current shape.

## The cost equation, measured

One data point from 2026-08-01, chosen because it is the smallest
possible change: publishing regista 0.5.5 — a version bump — required
**four consumer PRs**, a k8s image-tag fix, a Windows TOML-escaping fix,
six CI re-runs, and about four hours of wall clock. Nothing went wrong;
that is the *happy path* cost of moving the spine.

Three structural sources, in order of contribution:

1. **The spine pin is vendored four times.** Each component's
   `SUITE.lock` carries a copy of the umbrella's `[components.regista]`
   pin, explicitly so components need not clone agent-suite. Four copies
   that must be manually synced is four PRs per spine move, with
   merge-order constraints and a window where the estate disagrees with
   itself.
2. **agent-notes maintains two implementations of the same mutations.**
   `_native.py` (902 lines) and `_regista.py` (483 lines) both implement
   work-item writes; the degrade path is the *larger* one. BC-027,
   WI-020 and WI-021 are all drift between them. This is a permanent
   bug generator, not a backlog.
3. **Red main is normal.** Reviewers spend real effort classifying
   pre-existing versus new on every PR. That is the most corrosive cost
   because it degrades the reviewer rather than the machine: after two
   days of red, "CI failed" carries no information.

The suite's benefit — attributable, replayable, independently-reviewed
work — is real and was demonstrated repeatedly this week (the gates
refused a self-review, a false lineage assertion, and a mismatched
lock). But the benefit accrues at multi-user scale while the cost is
paid per-change today. The goal of this plan is to move the break-even
point left.

## Part A — Structural changes (do these first; they get harder later)

### A1. One identity model, specified once (highest value)

Five partial mechanisms currently answer "who did this": the WI-055
grammar, `actor_kind`, `on_behalf_of`, lineage capture (regista WI-214),
delegation (regista WI-008, unimplemented), and witness enrollment
(regista WI-238). They were designed at different times and disagree —
which is why ~231k events assert both a `human:` prefix and
`actor_kind='agent'`.

Write **one identity specification** that defines the dimensions, their
grammar, which are signed, which are derivable, and what each proves.
Everything else derives from it. The WI-055 decision record is the
seed; this promotes it to the normative document, and the other items
become implementations of it rather than independent designs.

Design the cutover assuming **there will be a third model** — the
current one is already the second, and an IdP subject will force a
third. That means an N-hop linkage record, not a one-shot mapping.

**Exit:** one document; every identity-related work item references it;
no component defines identity semantics locally.

### A2. Collapse agent-notes' dual write path

Delete `_native.py` as a mutation path. Make agent-notes strictly a
regista client, with degrade meaning *refuse to write* rather than
*write differently*. This deletes an entire class of defect (three open
items today, more later) and removes ~900 lines whose only job is to
disagree subtly with the other 483.

The counter-argument is availability: today agent-notes works with
regista down. Weigh honestly — a tracker that silently writes to a
different substrate during an outage, then reconciles imperfectly, is a
worse failure than one that refuses and says so. This is the same
"availability may fail open to digests, never to plaintext" principle
the suite already ratified for content (cairn WI-035), applied to state.

**Exit:** one mutation path; degrade is a refusal with a clear message;
BC-027/WI-020/WI-021 close as obsolete rather than fixed.

### A3. Stop vendoring the spine pin

The four component `SUITE.lock` copies exist to avoid cloning the
umbrella. Replace vendoring with consumption: publish the umbrella lock
as a versioned artifact (a tiny `agent-suite-lock` package, or a release
asset fetched by `dev-install.py`), and have components read the pin
from it. A spine move then becomes **one** change plus a dependency
resolution, not four synchronized PRs.

This is the smaller sibling of "should this be a monorepo." A uv
workspace monorepo would eliminate more tax (one CI, one lock, atomic
cross-component changes) but costs the per-repo publication gates,
independent release cadence, and the "each component is independently
useful" thesis. **Recommendation: do A3 now, and re-evaluate the
monorepo question only if the tax remains high afterwards** — A3
captures most of the benefit at a fraction of the disruption.

**Exit:** a spine release requires one human action; no file contains a
hand-synced copy of another file's version.

### A4. Give the tracker an admin plane

The gates deadlocked twice this week: nine items could not be moved out
of a false state because the `adversarial_review` validator required a
lineage fact the history did not contain, and the only bypass would have
written a false assertion into a signed chain. The correct action was
blocked by a control designed to prevent an incorrect one.

Add an **admin-correction transition**, signed and typed *as a
correction* rather than as a review, recording actor, reason, and the
state it overrides. This does not weaken the gates: a correction is
visibly a correction in the chain, which is exactly what an auditor
wants to see. Every durable system needs an out-of-band path; the
absence of one is why prose warnings ended up stamped into item bodies
as a substitute control.

**Exit:** a false item state is fixable without lying; corrections are
distinguishable from reviews in replay.

### A5. Descope agent-wake from the GA gate

agent-wake has 24 open items, is the youngest component, and is not on
the critical path for multi-user attested work. Mark it **experimental,
not GA-gated**. It continues to be developed; it stops contributing to
the release matrix, the conformance sweep, and the reviewer load. If it
matures, it re-enters.

This is the plan's clearest cost/benefit lever: one component's backlog
is roughly a quarter of the estate's open items and none of it blocks
the stated goal.

**Exit:** the GA gate names five components; agent-wake ships on its own
cadence.

## Part B — Friction fixes (mechanical, high leverage)

### B1. `implemented_by`, verified

Work items in a review state must carry a commit or PR reference that
**resolves**. Eight regista items sat in `in_review` with no branch, no
commit and no PR anywhere; nothing detected it and it was found by
grepping `git log`. A verified field makes that state impossible to
create. *This is the single highest-value mechanical fix.*

### B2. Baseline-diff CI gating

Record main's current failure set per repo. A PR fails only when it
**adds** to that set. This restores CI's information content and deletes
the per-PR "pre-existing or new?" investigation that consumed hours this
week. Pair it with a visible, decaying baseline so red main stays
embarrassing rather than becoming furniture.

### B3. Health checks must name the action they performed

Six observe-vs-verify defects in a month, including instances inside
*fixes for that class*. Discipline is not working, because the doctor is
always written by the feature's author, who checks what they know can
break. Make the health contract require a machine-readable
`action_performed` field: a check that cannot name an action it executed
is definitionally an observation, and the conformance kit — which
already exists — can fail it mechanically.

### B4. Docs assert machine-checkable claims

Four silent doc/reality divergences this week: promised Vault audit
correlation with no audit device enabled, a runbook `secret_id_ttl=24h`
against a live `0`, an install layout the new gate refuses, and witness
documentation that now instructs the reader to reintroduce a hole just
closed. agent-suite already has doc-claim tests; generalize the pattern
so operational documents carry testable assertions.

### B5. Record merge provenance, not commit SHAs

Squash-merge permanently orphans the original commits, so a tracker
claiming "this item's code is in main" cannot rely on SHAs surviving.
Record the merge commit, or content digests, on the work item.

## Part C — What not to do

- **Do not start the monorepo migration** until A3 has been measured.
- **Do not add features to agent-wake** while it is being descoped.
- **Do not fix BC-027/WI-020/WI-021 individually** — A2 deletes them.
- **Do not weaken any gate to unblock workflow.** A4 adds a path; it
  does not remove a check. The gates firing against their own maintainer
  this week is the strongest evidence the suite works.

## Sequencing

A4 and B1 first — they are small and they stop the tracker from
accumulating more false state while the rest proceeds. B2 next, because
it makes every subsequent change cheaper to review. Then A5 (a
scope decision, not code), A3, A2, and A1 in parallel as capacity
allows; A1 is the longest and least urgent in wall-clock terms but the
most consequential, so it should start early even if it lands late.
B3–B5 fold into whatever touches their surface.

## The metric to watch

Track the ratio of **events describing work on the suite** to **events
describing work the suite witnessed**. Today it is dominated by the
former, which is expected for infrastructure under construction. If it
has not moved materially within a few months of real users, the suite
has become the product rather than the tooling — and that is the signal
to stop building and start using.
