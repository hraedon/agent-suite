# Plan 023 — Target architecture

**Status: DRAFT for owner ratification** (2026-08-02).

This is the **specification to build from**. Plan 022 is the decision
record behind it — read it for *why*, never for *what*. Where the two
disagree, this document wins.

Requirements carry stable IDs (`R-nn`). Every work item must trace to
one requirement and one verification method.

---

## 1. Scope, goals, non-goals

**Goal.** Produce evidence that answers one question, verifiably and
offline: *for a given unit of work — who authorised it, which workload
executed it, in which session, producing which commits, reviewed by
whom, and what proves each of those claims?*

**In scope.** Capture of agent sessions; the authorisation and execution
chain behind them; attested review; work coordination for a small team;
an evidence surface for humans.

**Non-goals.** A general-purpose issue tracker. A wiki. A notification
platform. A transparency-log implementation. An identity provider. A
secrets manager. Per-agent isolation beyond what the authorisation model
requires.

**Environment constraints.** No new runtime SaaS. Low cost. Self-hosted
Postgres, Vault, and AD already exist. GitHub is sanctioned for Git,
PRs, and CI. Entra may follow AD; the design must not preclude it.

---

## 2. Invariants

These hold everywhere. A change that violates one is wrong regardless of
its other merits.

- **R-01 — Never claim more than was established.** A check reports what
  it *executed*, not what it observed to be configured. Any check that
  cannot name an action it performed is an observation and must say so.
- **R-02 — Fail closed, to digests, never to plaintext.** Availability
  problems may degrade evidence to digest-only. They may never emit
  unprotected content, and never silent success.
- **R-03 — Attest, never mirror.** The attestation store holds signed
  claims that *reference* coordination records by opaque ID. It never
  holds a copy of their mutable state.
- **R-04 — Possession is not authorship.** A signature proves a
  credential was used. Authorship, authorisation, execution, observation
  and log ordering are five distinct facts and are recorded separately.
- **R-05 — No bespoke cryptographic infrastructure.** Merkle trees,
  inclusion proofs, timestamping and log consistency are adopted, not
  implemented.
- **R-06 — One system of record per fact.** No field exists solely to
  reconcile two stores. A `pending_sync` column is a design failure.

---

## 3. Trust model

The correction that reshapes the rest of this document: **an "agent" is
not a stable, independently attributable security principal.** A
signature made with an agent-labelled credential proves only that some
process obtained that credential. An orchestrator, tool runner,
prompt-injected workload, delegated subagent, administrator or
compromised host all act through the same boundary.

**R-07.** The principal model is built on **workload instances and
authorisation chains**, not agent names.

**R-08.** Every claim binds, as separately-evidenced fields:

| Fact | Bound by | Answers |
|---|---|---|
| Authorisation | human/service authority identity, delegation record | who permitted this |
| Execution | orchestrator + isolated workload instance identity | what ran it |
| Authorship | model id/version, policy, prompt/input digest | what produced the content |
| Observation | capture-harness identity, completeness markers | who witnessed it, and what was missed |
| Ordering | transparency-log receipt | when it was committed, and immutably since |

**R-09.** Credentials are short-lived and workload-attested. Per-agent
credential isolation is necessary for containment but is explicitly
**not** evidence of authorship (R-04).

**R-10.** Signing happens at the actor boundary. No service holds a
keyset able to sign as arbitrary principals. *(Current violation:
`regista/_events.py` resolves the actor's key server-side and signs on
their behalf. This is the first correctness fix.)*

**R-11.** Actors sign **claims only** — never server-assigned sequence
numbers, timestamps or previous-head values. Ordering and log receipts
are recorded by the service, separately, and verified separately.

---

## 4. Components

Five, of which two are substantial.

| # | Component | Charter |
|---|---|---|
| C1 | **Evidence collector** (cairn) | harness interception, session capture, completeness and degradation detection, content encryption, actor-boundary signing, delegation binding |
| C2 | **Attestation service** (regista, reduced) | Postgres state; work items, transitions, claims with TTL/heartbeat; review gates; DSSE/in-toto statement emission; transparency-log client; offline verification |
| C3 | **Evidence + coordination UI** (dossier, reduced) | one surface joining evidence to work items; deliberately minimal |
| C4 | **Agent workflow surface** (agent-notes, reduced) | CLI and skills that make the process followable; a client, not a service |
| C5 | **Credential broker** (acb) | scoped, short-lived credential issuance where Vault Agent or workload identity cannot provide it |

**Adopted, not built:** Postgres, Vault, AD, GitHub (Git/PR/CI),
hindsight (memory), and a self-hosted transparency log (Tessera or
immudb).

**Deleted:** agent-wake; regista's bespoke transparency layer (Merkle,
singleton global chain, witness delivery, RFC 3161 batching, archive
segmentation, bespoke bundle format); regista's server-side signing;
agent-notes' work-item store, outbox, projection, `pending_sync`,
convergence migration, and link subsystem; the second database.

---

## 5. Data and ownership boundaries

- **R-12.** Work items, transitions, claims and review verdicts live in
  C2 and nowhere else.
- **R-13.** Captured session content lives in C2's store, encrypted, and
  is written only by C1.
- **R-14.** Agent memory lives in hindsight, scoped per principal, and
  inherits the content-encryption posture of R-02/R-13.
- **R-15.** Group knowledge is repo markdown plus decision records,
  rendered by C3. It is not a separate store.
- **R-16.** The coordination layer is kept **Jira-shaped**: work items
  map cleanly onto Jira issues, so coordination can migrate if adoption
  outgrows C3. The attestation layer is the deliberate exception and
  travels with us. Coupling between them obeys R-03.

**Tracker scope cap (R-17).** C3's work-item surface is limited to:
title, description, typed state, claim lease, review verdict, evidence
references. **Not** in scope: boards, swimlanes, comments, mentions,
arbitrary custom fields, notification rules, mobile, rich search.

**Revisit triggers (R-18).** Any of these means C3 has outgrown its
scope and coordination should move to Jira: a request for boards,
swimlanes, comment threads, or mobile; **or** tracker work consuming
more effort than capture and verification for two consecutive
iterations.

---

## 6. Wire format

- **R-19.** Attestations are **DSSE envelopes carrying in-toto
  statements** with suite-specific predicate types. No bespoke envelope
  version.
- **R-20.** Statement digests are submitted to the transparency log;
  receipts and inclusion proofs are stored with the evidence.
- **R-21.** Offline verification requires only: the statement, its
  signature, the public key material, and the log receipt. It must not
  require the live service.
- **R-22.** Predicates distinguish the five facts of R-08 explicitly.
  One predicate type per fact class; do not overload a single "event".

---

## 7. Migration

Ordered. Each step is independently verifiable and leaves a working
estate.

| Step | Action | Exit condition |
|---|---|---|
| M1 | Freeze mutation-producing development. Snapshot and export the corpus; build the frozen verifier. **Do not truncate.** | **Partially met 2026-08-02** — see below |
| M2 | Consolidate to one uv-workspace monorepo (six components; agent-wake deleted) | One CI, one identifier gate, one conformance harness; all suites at baseline |
| M3 | **R-10 + R-09 together** — actor-boundary signing and per-agent credential isolation as one security boundary | No service can sign as another principal; one agent revocable alone; test proves token A cannot use token B's capability |
| M4 | Adopt DSSE/in-toto and the transparency log; retire the bespoke transparency layer | Offline verification per R-21 passes; bespoke Merkle/witness code deleted |
| M5 | Reset the `agent_provenance` corpus under the new model | First event of the new chain satisfies R-08 and R-10 |
| M6 | Unify the work-item store into C2; delete C4's duplicate | No `pending_sync`; one system of record |
| M7 | AD binding: `objectGUID` + forest/issuer as signed binding records | A principal resolves to a directory subject without any envelope change |

**M3 precedes M5 deliberately.** Resetting first would begin the
"clean" corpus under server-forged signatures and require a second
cutover.

**M1 status (2026-08-02).** Executed: `/home/itadmin/estate-archive/`
holds a 265,747-event full dump, an `agent_provenance` schema dump, a
full-corpus bundle, and a frozen verifier built from the `v0.5.5` tag
(25 exact pins, CPython 3.14.4, key *references* only — no private
bytes). Reconstituted from scratch and re-verified: dump restores clean,
`replay` reports `halted: 0` / `replayed_drift: 0`, all **261,105
signatures verified**, and an independent SQL recomputation of the
global chain found 0 breaks, 0 forks, 1 genesis.

**M1 is NOT complete, and M5 is blocked on four things** (agent-suite
WI-060, regista WI-240/241/242):

1. **Bundle export produces bundles its own verifier refuses** — 803 MiB
   against a 512 MB cap, exit 0, and no `--until-seq` to chunk with
   (WI-240). Offline verification of the full corpus is therefore
   currently impossible.
2. **12,866 `agent_provenance` ed25519 events verify only against a key
   registered in `agent_notes`** (WI-241). Signatures are sound; the
   bundle ships the wrong key, so third-party offline verification of
   that slice fails. Interacts with R-07/R-08 and should be decided with
   the identity model, not patched.
3. **Verifiability depends on one host's 0600 plaintext keyfile.** Lose
   `~/.config/regista/keys.json` and 248,239 HMAC events are
   unverifiable forever (WI-060). Plus: zero anchors, zero sealed
   segments, no offsite copy, no cooling-off.
4. **`replay` mutates the store it verifies**, and `Regista.__init__`
   issues DDL on connect, so verification cannot run against a
   read-only restore (WI-242) — which R-21 requires.

This is the discipline working as designed: every one of these would
have been discovered *after* the source data was destroyed had the reset
run first.

---

## 8. Acceptance criteria and gates

- **G-1.** A single captured session yields evidence that verifies
  offline with the live service stopped.
- **G-2.** A cross-lineage review verdict verifies to a distinct
  workload instance, not merely a distinct agent name.
- **G-3.** Undeclared lineage **lowers** assurance; it never satisfies
  a distinctness requirement. *Verified 2026-08-02 (regista WI-239): the
  two paths currently disagree.* `adversarial_review` is fail-closed and
  correctly blocks an undeclared reviewer. But the human-gate escalation
  uses `same_lineage()`, which treats `None` as **independent** — so an
  undeclared-lineage reviewer who supplies `same_lineage_acknowledged`
  passes the first gate and then never triggers the human requirement,
  because unknown independence reads as proven independence. Fix:
  `same_lineage()` returns three states — SAME, DISTINCT, UNKNOWN — and
  UNKNOWN escalates exactly as SAME does.
- **G-4.** Revoking one agent's credentials leaves other agents and the
  host unaffected, proven by test.
- **G-5.** Every doctor check either names the action it performed or
  declares itself an observation (R-01), enforced by the conformance
  kit.
- **G-6.** No component holds a copy of another's mutable state (R-06),
  enforced by schema review.

---

## 9. Rollback and failure recovery

- Each migration step is revertible without data loss until M5. M5 is
  the one-way door and is gated on M1's verified archive plus a
  cooling-off period.
- The frozen verifier is retained indefinitely; live services may drop
  older readers, the archive verifier may not.
- Old repositories are archived read-only, never deleted.
- Rollback restores configuration pointers and restarts consumers; it
  never destroys newly created material.

---

## 10. Consequential rejected alternatives

- **Adopt Jira/Linear for coordination now.** Rejected: no new runtime
  SaaS, and the evidence UI must be built regardless, so the marginal
  cost of coordination in C3 is small while the join cost to an external
  tracker is permanent. Retained as the explicit off-ramp (R-16, R-18)
  since Jira is already in use organisationally.
- **Build our own transparency infrastructure.** Rejected: bespoke
  Merkle already produced a root covering UUIDs rather than event
  content. Adopted instead (R-05).
- **Keep the bespoke envelope and version it.** Rejected: DSSE/in-toto
  is verifiable by third-party tooling and avoids a second format
  change (R-19).
- **Defer per-agent isolation and forgery defence.** Rejected: waiting
  for a second human confuses human tenancy with agent isolation, and
  independent anchoring gives real post-publication rewrite detection
  now.
- **Keep work items in agent-notes.** Rejected: two systems of record
  with a sync layer (R-06).

---

## 11. Open — required before M3

- **O-1.** Design the R-08 predicate set concretely: field-level schema
  for each of the five facts, and what evidence backs each.
- **O-2.** Choose the transparency log (Tessera vs immudb) against
  operational cost on this estate.
- **O-3.** Decide the workload-attestation mechanism for R-09 (Vault
  Agent, SPIFFE/SPIRE, or acb-issued short-lived credentials).
- ~~**O-4.** Confirm G-3 against current code.~~ **Closed 2026-08-02** —
  regista WI-239 filed; the defect is real but narrower and more
  composed than reported. See G-3.
