# Plan 023 — Target architecture

**Status: RATIFIED** (2026-08-03). Owner authorization, recorded
verbatim: *"I am pausing all other work on the agent-suite, so once you
consolidate and review what's on mvmcc02 you are welcome to begin plan
023 with any modifications you choose to add"* — with the qualifier
that *"expanded scope [is] potentially permissible if it serves a
genuine learning goal."* The modifications taken under that authority
are §12. One act stays owner-gated: the RC3 release-board declaration
and tag (a release declaration is an authorization record; an agent
must not sign it as the owner).

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

**R-23 — Scope expands only toward learning.** This estate is a lab;
its purpose includes what building it teaches. An expansion beyond the
minimal design is permissible when it (a) names a genuine learning
objective the minimal path would not exercise, (b) preserves R-01..R-06
untouched, and (c) carries an explicit evaluation or sunset criterion
so it cannot silently become load-bearing scope creep. Commodity
feature surface — boards, comments, notifications, rich search — is
exactly the expansion that teaches nothing; R-17/R-18 therefore stand
unrelaxed. The learning-permissible direction is depth in the evidence
and identity layers (transparency-log operation, workload attestation,
verification tooling), not breadth in the coordination layer.

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

Six, of which two are substantial.

| # | Component | Charter |
|---|---|---|
| C1 | **Evidence collector** (cairn) | harness interception, session capture, completeness and degradation detection, content encryption, actor-boundary signing, delegation binding |
| C2 | **Attestation service** (regista, reduced) | Postgres state; work items, transitions, claims with TTL/heartbeat; review gates; DSSE/in-toto statement emission; transparency-log client; offline verification |
| C3 | **Evidence + coordination UI** (dossier, reduced) | one surface joining evidence to work items; deliberately minimal |
| C4 | **Agent workflow surface** (agent-notes, reduced) | CLI and skills that make the process followable; a client, not a service |
| C5 | **Credential broker** (acb) | scoped, short-lived credential issuance where Vault Agent or workload identity cannot provide it |
| C6 | **Operator CLI** (agent-suite, reduced) | bootstrap, onboard/offboard, backup/restore/verify-restore, schedule/services, doctor aggregation, release manifests. Its repo-coordination purpose (locks, spine pins, cross-repo release reconciliation) evaporates with consolidation; what survives is "the thing an operator runs", not "the thing that holds seven repos together" (ratified in Plan 022 §A3) |

**Adopted, not built:** Postgres, Vault, AD, GitHub (Git/PR/CI),
hindsight (memory), and a self-hosted transparency log (Tessera or
immudb).

**Deleted:** agent-wake — *with one operational caveat: agent-wake is
not dormant; it runs the live wake channel on mvmcc03 today (systemd
user unit, signed local callbacks). Deleting the component requires
absorbing or explicitly retiring that channel first; decommissioning
must not silently kill the estate's only wake path* —; regista's
bespoke transparency layer (Merkle,
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
| M2 | Consolidate to one uv-workspace monorepo (six components; agent-wake deleted) | **Rehearsed and proven 2026-08-02** — see below |
| M3 | **R-10 + R-09 together** — actor-boundary signing and per-agent credential isolation as one security boundary | No service can sign as another principal; one agent revocable alone; test proves token A cannot use token B's capability |
| M4 | Adopt DSSE/in-toto and the transparency log; retire the bespoke transparency layer | Offline verification per R-21 passes; bespoke Merkle/witness code deleted |
| M5 | Reset the `agent_provenance` corpus under the new model | First event of the new chain satisfies R-08 and R-10 |
| M6 | Unify the work-item store into C2; delete C4's duplicate | No `pending_sync`; one system of record |
| M7 | AD binding: `objectGUID` + forest/issuer as signed binding records | A principal resolves to a directory subject without any envelope change |

**M3 precedes M5 deliberately.** Resetting first would begin the
"clean" corpus under server-forged signatures and require a second
cutover.

**M2 status (2026-08-02).** Rehearsed end-to-end in a scratch tree
(agent-suite WI-061; procedure at `monorepo-rehearsal/PROCEDURE.md`,
~35 min to repeat). `git filter-repo --to-subdirectory-filter` gives
**exact `git log`/`--follow` parity with standalone on all six
packages**; `git subtree` was rejected on measurement, not preference —
it reduces per-file history to a single graft commit. Workspace
resolves, all wheels build, every force-include and the `__file__`-
relative release-board lookup survive, and five of six suites match
their standalone baselines exactly.

**Measured collapse: 9,510 → 2,175 hand-maintained lines (−77%)**
(17,967 → 5,268 including generated lockfiles).

The finding that settles the duplication argument: consolidating the
conformance meta-guard revealed **acb's copy carried two fixes the other
four never received**, and adopting any majority copy would have shipped
a gate that *fails open* — the exact failure that guard exists to
prevent. Six diverging copies with the correct one in the minority is
the cost made concrete.

**M2's blocking decision is SHA rewriting.** filter-repo rewrites all
942 SHAs, and this estate *stores* SHAs — `SUITE.lock` revisions,
release manifests, and cairn provenance attestations. Browsable
per-file history and stable SHAs are mutually exclusive. Recommendation:
take the rewrite. §9 already keeps the old repositories read-only, so
they remain the resolution target for historical SHAs and existing
attestations stay verifiable against the archive. The three mitigations
are filed work items with verification methods, and **all three block
the M2 cutover** (not the rehearsal): a signed old→new SHA map covering
all 942 rewritten commits (agent-suite **WI-062**); a live-reference
sweep that leaves zero unclassified SHA citations at cutover
(**WI-063**); and archive-aware SHA resolution in every tool that
assumes "resolve this SHA in the current repo", failing closed on
unknown SHAs (**WI-064**). Four smaller decisions are listed in WI-061.

**In-flight work at the M2 boundary.** This plan does not orphan the
work already in motion. The **0.5.5/RC3 release train finishes first**
in the current topology: regista 0.5.5 is on PyPI, all consumer spine
pins are advanced and every main is green (2026-08-02); what remains is
the owner-gated release-board rc.3 declaration and tag. RC3 is the last
multi-repo release — it becomes the frozen "before" state M2 consolidates,
and its release manifest is a named test article for WI-064's archive
resolution. **Plan 020 lanes C (platform qualification) and F
(operations and multi-user lifecycle) transfer to the post-M2 estate**:
both qualify *what ships to an operator*, and re-running them against
the consolidated tree is strictly less work than running them twice.
All other Plan 020 lanes are landed or subsumed by this plan's steps.

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
   unverifiable forever (WI-060). *Escrow leg closed 2026-08-02:
   two-leg escrow (Vault KV object + GPG ciphertext on a second host,
   passphrase held only in Vault), restore proven off-host by
   decrypt-and-parse with byte-identical sha256.* Still open on WI-060:
   zero anchors, zero sealed segments, no offsite **archive** copy, no
   cooling-off, and both escrow legs share Vault as a dependency.
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
  a distinctness requirement. *Fixed and verified 2026-08-03: regista
  PR #25 (f4fe6f8, WI-239) landed the prescribed three-state
  `LineageRelation` — SAME / DISTINCT / UNKNOWN — with UNKNOWN
  escalating exactly as SAME does in both the adversarial-review and
  human-gate paths.* (History: found 2026-08-02 — the human-gate
  escalation read `None` lineage as proven independence while
  `adversarial_review` was already fail-closed.)
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
- ~~**O-2.** Choose the transparency log (Tessera vs immudb).~~
  **Decided 2026-08-03 (direction; see §12): Tessera**, subject to a
  bounded operational spike at M4 entry. Rationale under R-23: Tessera
  is a true tile-based transparency log (Trillian's successor) whose
  artifacts verify with standard checkpoint/inclusion-proof tooling and
  whose POSIX storage backend fits this estate; operating one teaches
  CT-style log semantics that transfer. immudb is an immutable database
  with product-specific verification — less operational surface, but
  also less to learn and a proof format nothing else speaks. R-05
  intact: adopted, not implemented. Spike exit criterion: a Tessera
  instance on this estate holding real statement digests, an inclusion
  proof verified offline by an independent client, and measured
  steady-state cost; if the cost is disproportionate, fall back to
  immudb *before* M4 work begins.
- ~~**O-3.** Decide the workload-attestation mechanism for R-09.~~
  **Decided 2026-08-03 (see §12): two-phase.** M3 ships on acb-issued
  short-lived credentials — the broker exists, is reviewed, and the
  security boundary must not wait on new infrastructure. SPIFFE/SPIRE
  is deferred to learning lane L-1 (§12) and may *replace* acb issuance
  post-M4 only if its workload attestation proves materially stronger
  binding at acceptable operational cost on a two-node estate.
- ~~**O-4.** Confirm G-3 against current code.~~ **Closed 2026-08-02** —
  regista WI-239 filed; the defect is real but narrower and more
  composed than reported. **Fixed 2026-08-03** (regista #25). See G-3.

---

## 12. The 2026-08-03 reevaluation — ratification and learning-scope decisions

Recorded when the owner ratified the plan with delegated modification
authority and the R-23 qualifier. Changes made under that authority:

**R-23 added (§1).** The scope test is now explicit: depth in evidence
and identity layers is expandable for learning; breadth in the
coordination layer is not. The tracker scope cap (R-17) and revisit
triggers (R-18) were reconsidered under the expanded-scope permission
and deliberately retained — commodity tracker features are the
canonical expansion that serves no learning goal.

**Learning lane L-1 — SPIFFE/SPIRE workload attestation (post-M4,
optional).** Learning objective: workload identity as practiced beyond
this estate (SVID issuance, node/workload attestors, federation).
Evaluation criterion: a spike issuing SVIDs to two real workloads
(capture harness, review runner) and binding one R-08 execution fact to
an SVID; adopt into C5's issuance path only if the binding is
demonstrably stronger than acb's and the SPIRE server's operational
cost fits the estate. Sunset: if not adopted within one milestone of
completing M4, the lane closes with a written verdict either way.

**WI-061 decisions D2–D5** (D1, SHA rewriting, was decided in §7):

- **D2 — SUITE.lock survives; the develop-against-lock apparatus does
  not.** SUITE.lock remains the published-release pinning record
  (release manifests and RC verification need it after consolidation).
  `dev-install.py`, `suite_lock.py`'s sibling-checkout pairing, and the
  develop-against-lock CI apparatus retire at M2 cutover — the
  workspace makes cross-repo drift structurally impossible. The
  WI-057 spine-symbol gate (merged 2026-08-03, PR #16) is deliberate
  interim protection: its value window is now→cutover, and it retires
  with the apparatus it guards. Expected and accepted.
- **D3 — the 54 shape-asserting tests, by group at M2 execution:**
  publication_plumbing (27) and identifier-gate (16) are rewritten to
  the workspace shape (the invariants they check survive; the layout
  they assert does not); develop_against_lock (9) is deleted with its
  apparatus; matrix/artifact sibling-probe tests (6) are rewritten
  against the workspace probe source. The ~20 previously
  ImportError-skipped agent-suite tests that the shared venv un-skips
  are a win: the two failures get filed, including the genuine cairn
  defect the consolidation surfaced.
- **D4 — one `FORBIDDEN_IDENTIFIERS` secret.** The six per-repo copies
  merge at cutover. The gate fails closed, so a botched rename reddens
  everything loudly rather than silently passing anything — acceptable,
  and the failure mode is the safe one.
- **D5 — torch stays out of the default developer sync.** agent-notes'
  ~5 GB embedding stack moves behind an optional dependency group;
  features degrade explicitly when absent and doctor reports the
  absence as an observation (R-01). No developer pays 5 GB to work on
  an unrelated package.

**Execution begins with M1 completion**, because M1 gates the only
one-way door: regista WI-240 (chunked, capped bundle export — an
export its own verifier refuses must fail, not exit 0), WI-242
(verification must run against a read-only restore: replay stops
mutating, connect stops issuing DDL), WI-060 residuals (anchors,
offsite archive copy, cooling-off; both escrow legs currently share
Vault as a dependency), and WI-241 (cross-schema key scoping — decided
together with the O-1 identity predicates, not patched ad hoc, per the
item's own analysis). M2 cutover work (WI-062/063/064) follows; RC3
finishes first in the current topology and its declaration remains the
owner's signature.
