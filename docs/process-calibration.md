# Process calibration — evidence-gated tooling decisions

**Status:** Adopted 2026-07-19 (owner: "we already do a version of 'test
this and if it is bad drop it or rethink,' we just don't do it
rigorously" — this document is the rigorous version). Pattern adapted
from PropterMalone/PropterMaltwo and NineAngel (MIT), specifically the
shape of their ADR-01, which retired a feature of their own review
tooling on metered evidence with a written falsifier.

## What this governs

Decisions about our **process tooling**: skills, review batteries and
reviewer lineups, orchestration modes, session rituals, hooks and
gates. The products already have gates; this closes the same loop
around the machinery that builds them. Not in scope: product
architecture decisions (those have their own plans/ADRs) and one-off
judgment calls.

## The contract

### 1. Tooling decisions get decision records with falsifiers

A change to how we work — adding a reviewer lineage, adopting or
retiring a skill mode, changing a gate's posture — gets a short
decision record (in the owning repo's `docs/decisions/` or plan file)
with these sections, none optional:

- **Decision** — one sentence.
- **Evidence** — what was measured or observed, with numbers where the
  harness exposes them (token cost, wall time, findings kept/lost).
  "It felt better" is not evidence; say instead "not yet measured" and
  mark the decision provisional.
- **Rejected alternative** — and why more data would not change the
  call.
- **Could-be-wrong-if** — a concrete falsifier a hostile reader could
  check: what to observe, how, and the threshold that reopens the
  decision. The vague-phrase class ("if issues arise", "if assumptions
  are wrong") fails review.
- **How to apply** — what changes operationally, in one paragraph.

### 2. Review passes record dispositions

Every adversarial/review pass's findings get a recorded disposition:
`accepted` / `accepted-modified` / `rejected-noise` /
`rejected-wrong`. The disposition is the precision signal — without
it, "does this reviewer lineage earn its slot?" is unanswerable and
every lineup decision is vibes. Destination: regista events carrying
reviewer lineage (model family + harness), per regista WI-211; until
that lands, dispositions go in the review record itself (PR comment
resolution or the WI body — recorded beats perfect).

### 3. Provisional until it earns the slot; retired on evidence

New process machinery (a reviewer persona, a skill mode, an
orchestration pattern) enters **provisional**, with its graduation
criterion stated at introduction ("earns default-on if, over N uses,
it produces ≥1 accepted Important+ finding not caught by the rest of
the lineup" — that shape). Machinery that fails its criterion is
retired with a §1 record, not left running because removing it feels
wasteful. Sunk cost is not a section.

### 4. Enforcement lives in harness-independent layers

The upstream pattern enforces doctrine in Claude Code hooks; we can't
— cross-harness support is a requirement, not a preference. Our
enforcement points, in order of authority:

1. **the store** (regista validators/gates — binds every face),
2. **CI** (binds every contributor and harness),
3. **git hooks** (`githooks/` — binds every local commit/push),
4. **harness hooks** (convenience and ergonomics only; nothing is
   *guaranteed* by a layer only one harness runs).

A process rule that exists only in a CLAUDE.md/AGENTS.md sentence or a
single harness's hook is a request, not a control. Say which layer
enforces each rule; "layer 4 only" is an honest and sometimes correct
answer, but it must be said.

### 5. Guards get behavioral deny-tests

A guard broken by a refactor fails **open** and looks identical to a
working one. Every gate/guard therefore ships fixture-driven tests
that prove it still *denies*: synthetic bad input → nonzero exit /
refusal, plus the inverse pass case. Exemplar:
`tests/test_identifier_gate.py` in this repo. Rollout tracked as
agent-suite WI-018; a live instance of the failure class is
agent-notes WI-026 (an error path that exits 0).

## Related standing doctrine

- **The permission layer is not a security boundary.** (Framing
  borrowed verbatim from the upstream repo, kept because it is the
  crispest statement of something our threat model implies:) harness
  permission prompts and allow/deny lists are speed bumps for common
  footguns. Actual safety on an operator box = model judgment +
  layer-1/2/3 enforcement above. Never treat "the permission system
  allowed it" as evidence an action is safe, and never present a
  layer-4 control as a boundary in compliance conversations — the
  suite's whole pitch is that the *store* is the boundary of record.

## Bootstrap state (2026-07-19)

Adopted with: regista WI-211 (disposition events), agent-suite WI-018
(guard deny-tests rollout), agent-suite WI-019 (plumbing pre-push
guard in publication-prep). First candidates for a §1 retro-fit
record: the reviewer lineup used for suite gates (kimi review /
GLM-Sol gates / Fable advisor — currently undocumented as a
*decision*), and the adversarial-review skill's pass-count doctrine.
