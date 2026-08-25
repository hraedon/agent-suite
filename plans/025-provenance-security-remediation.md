# Plan 025 — Provenance-Security Remediation (estate-wide)

- **Status:** DRAFT v2 (revised after Sol cross-lineage plan review; incorporates owner decisions 2026-08-25)
- **Author:** Claude Fable (mvmcc03) · **Plan reviewer:** GPT-5.6 Sol (cross-lineage), verdict *needs-rework* on v1 — this v2 folds in that critique
- **Date:** 2026-08-25
- **Provenance of the finding:** whole-estate Daybreak Blue deep security review, 2026-08-25, per component against current mains; the 13 regista trust-log findings independently reproduced by a Claude Opus probe-executor. Raw reports `~/wi337-collision-evidence/daybreak-*.txt`; consolidated inventory `~/wi337-collision-evidence/CONSOLIDATED-INVENTORY.md`; Sol's v1 review `~/wi337-collision-evidence/sol-plan025-review.md`; verified regista findings WI-342, WI-351..362.
- **Decisions this plan asks for:** (1) rebuild-vs-patch posture; (2) substrate, via a threat-modelled **bake-off** (not a pre-picked lead); (3) cutover gate defined by **named security invariants**, not severity alone; (4) verification depth on the 134 unverified findings.
- **Owner decisions already taken (2026-08-25):**
  - **No emergency containment track.** The suite is not deployed in production anywhere; there is no incremental risk from the live findings, so we go straight to the rebuild rather than patching exploitable paths in parallel. (Sol recommended a stabilize-now track; declined on the not-in-prod basis.)
  - **Substrate is a bake-off, decided with operational eyes open.** The operational burden a substrate/architecture imposes **on adopters** (who must run witnesses, custody anchor keys, operate the store, run fail-closed recovery) is a **first-class security criterion**, not a footnote — a guarantee that depends on operational discipline an adopter won't sustain is a false guarantee. MSSQL Ledger's heavier operational burden is a real weakness to weigh openly and possibly accept knowingly.
  - **All design decisions are on the table; component *shapes* are malleable.** To a first approximation nothing about the current structure is fixed. Each component has a fixed *purpose* — regista = trust log/event store; cairn = provenance verification; agent-notes = work-item tracking + governance record; agent-suite = orchestration/gate; agent-wake = wake channel; acb = capability brokering; dossier = human surface — but its *shape* is not. Component boundaries, project decomposition, and whether a purpose is best served by merging, splitting, absorbing, or re-drawing projects are **all in scope**. Do not treat the seven-project split as a constraint: the right structure for a *verify-always* provenance system may differ from what exists (e.g., the verified-evidence core may subsume much of cairn; the trust log and its verifier may belong together; gate logic scattered across agent-suite/agent-notes may consolidate). Reason from purpose to structure, not from the current structure.

---

## 0. TL;DR

The deep review found **one architectural posture applied everywhere: "verify sometimes, trust the input."** For a *provable-provenance* system that is the wrong default. 147 findings across all seven components (7 Critical, 73 High) are its symptoms.

The strategic direction is sound and unchanged from v1: **verification must be structurally required, not optional; signed evidence must be separated from mutable projections; every trust decision must flow through one hardened implementation.** Sol's review did not dispute that — it corrected the *rigor of the mechanism*, and this v2 is the corrected version. The four substantive corrections:

1. **The trust model comes first (§3), before any substrate or API.** Define which adversary can compromise which layer, and the *temporal* authority semantics — because "retired ⇒ not authoritative" is wrong for historical evidence and would invalidate valid history after every rotation.
2. **The verified-evidence core returns scoped, policy-bearing claims — not a boolean (§4).** A generic `Verified[T]` re-creates the green-badge problem; consumers must request a specific claim (`HumanAcceptanceEvidence`) carrying trust-root, policy version, cut, completeness scope, and proof status. And it is *not* unforgeable across process boundaries — it needs authenticated verification **receipts**. Verification happens at **ingestion + checkpoints**, not on every read (verify-every-read is an availability attack).
3. **The substrate is a bake-off, not a lead (§5–§6).** A database ledger is tamper-*evident*, not forgery-*prevention*; the real trust boundary is **external anchoring + independent witnesses**, and the operational burden that imposes on adopters is a first-class criterion. Candidates: hardened Postgres + a witnessed transparency log; SQL Server Ledger + witnesses; a purpose-built immutable store (immudb).
4. **Rebuild incrementally via vertical slices (§7–§8), not "core first, consumers later."** Prove one end-to-end verified claim against production-like history before estate-wide adoption; map every finding to a concrete control; treat data/protocol migration and legacy-evidence containment as explicit phases; gate cutover on named invariants.

We are not shipping the current design. Provable provenance is the entire value; a verifier with holes in every component is worse than no release, and — the owner's framing — the suite is **not in production anywhere**, so we have the rare freedom to fix the foundation properly before anyone depends on it.

---

## 1. What the review found

**147 findings** — 13 verified (crown-jewel, Opus-reproduced) + 134 Daybreak-rated (unverified). Full deduped list: `CONSOLIDATED-INVENTORY.md`.

| Component | Crit | High | Med | Low | Total |
|---|--:|--:|--:|--:|--:|
| regista trust-log (crown jewel, **verified**) | 0 | 5 | 5 | 3 | 13 |
| regista crypto/signing | 0 | 4 | 2 | 1 | 7 |
| regista CLI/sidecar | 0 | 3 | 6 | 2 | 11 |
| regista persistence/governance | **4** | 6 | 3 | 3 | 16 |
| agent-provenance — **cairn** | **2** | 13 | 6 | 1 | 22 |
| dossier | 0 | 5 | 9 | 3 | 17 |
| agent-suite (gate/orchestrator) | 0 | 9 | 7 | 0 | 16 |
| agent-notes (tracker + gate store) | 0 | 9 | 4 | 2 | 15 |
| agent-wake | 0 | 9 | 5 | 0 | 14 |
| agent-capability-broker (acb) | **1** | 10 | 4 | 1 | 16 |
| **Total** | **7** | **73** | **51** | **16** | **147** |

**Evidence maturity caveat (Sol):** only 13/147 are reproduced. Exact counts, class-collapse claims, and the cutover map must NOT be locked on unreproduced model classifications. **Before the architecture is frozen we reproduce every Critical and a representative High from each systemic class**, and every finding gets a row in the finding→control matrix (§2).

---

## 2. Systemic classes — as triage categories, not four root causes

The four classes are the **map for where to look and what to build shared**, but (Sol, correctly) they are taxonomic buckets that still bundle problems needing distinct controls. C4 mixes endpoint authorization, permissive defaults, exit-code semantics, missing project isolation, and unsigned operations; C1 mixes mutable projections, unsigned manifests, PATH/executable substitution, and supply-chain integrity. A shared "deny by default" or "reconcile row vs envelope" helps many, but not all.

- **C1 — Trust the unverified input** (28: 4C/18H/5M/1L) — the row/envelope-reconciliation class; the largest *closable-by-one-invariant* subset (the SEC-11 collision recurs in ≥7 components: SEC-11, persist-2/9, dossier-2/4, an-8, aw-7).
- **C2 — Retired/rotated/revoked keys retain authority** (11: 9H/2M) — needs the temporal authority model of §3, not a naive "current authority" flag.
- **C3 — Signatures/authorizations not bound to context** (20: 14H/4M/2L) — needs shared envelope *framing + domain-separation*, but per-principal semantics (Ed25519 events, HMAC webhooks, executable identity, package digests, Vault grants are not one envelope).
- **C4 — Fail-open gates / missing authorization boundary** (38, the largest: 2C/22H/12M/2L) — a "default DENY" principle plus *component-specific* authorization controls (endpoint identity, socket-peer identity, project-admin boundary, capability enforcement).
- **C5 — Other** (50: DoS/resource-limits, TOCTOU races, SSRF/injection, attribution-only, crypto-primitive confusion) — mostly Medium/Low, individually patched.

**Required artifact (Sol): the finding→control matrix.** Every one of the 147 gets classified as: *fully closed by the core* / *partially mitigated* / *independently patched* / *invalidated after reproduction*, with its regression test. The v1 claim "97 collapse" is replaced by this matrix — collapse is a hypothesis the matrix must *demonstrate*, per finding, not an artifact of counting the buckets.

---

## 3. The trust model (do this FIRST)

Sol's single biggest correction: the plan cannot choose a substrate or an API before the trust model is written. Provenance answers **three** questions, not the two v1 conflated:

1. **Authentication** — did key K produce these exact bytes? (signature over a context-bound envelope)
2. **Authorization at position** — was K authorized for this action *at the relevant log position / policy version*? (the temporal authority question)
3. **Completeness & non-equivocation** — is the evidence complete, ordered, durable, and free of forked/omitted history? (the store/anchor question)

A valid signature answers only (1); an immutable row answers only part of (3); neither establishes (2). The core (§4) must resolve all three, separately and explicitly.

**Temporal authority semantics (the C2 fix, done right).** "Retired ⇒ not authoritative" is wrong: a key that validly signed an event *before* retirement remains valid evidence of that historical act. The model must distinguish:
- **authority at event/log position** (was K authorized *then*, at an authenticated position — not caller-asserted `occurred_at`),
- **permission to author a new event now** (is K current authority *today*),
- **verifier knowledge at a later cut** (what a verifier at checkpoint C can establish),
- **retroactive invalidation after compromise** (an explicit, signed revocation-with-effect-range, distinct from ordinary rotation).

Authority is resolved against an **authenticated log position / checkpoint**, never a caller-supplied timestamp (this is what makes SEC-04 backdating and SEC-07 caller-controlled validity un-exploitable *by construction*).

**Adversary model (Sol).** Define, separately, what each can do and which layer each can compromise — and design each guarantee against a named adversary: ordinary user, service principal, compromised component, DB *writer*, DB *administrator*, host root, verifier operator, anchor/witness operator, signer-key holder, and colluding combinations. Every claim the system makes ("externally authenticated", "human-accepted", "chain intact") must name the adversaries it does and does **not** defend against. (This extends the estate's existing OPERATOR-FORGERY residual-threat doc, WI-007, from regista to the whole stack.)

Deliverable: a `TRUST-MODEL.md` — adversaries, the three questions, temporal semantics, and the claim-by-adversary matrix. Phase 0 output; gates everything after it.

---

## 4. The verified-evidence core

One library (in regista, consumed by every component) that owns the trust primitive — but shaped per Sol's corrections.

**Scoped, policy-bearing claims (not a boolean).** No generic `Verified[T]` that consumers reinterpret. The core issues *specific claims* — `HumanAcceptanceEvidence`, `ExternallyAuthenticatedBundle`, `CapabilityGrant`, `WitnessCoSignature` — each carrying:

- the normalized claims actually verified (and, explicitly, those *not* verified),
- evidence/artifact digest; trust-root identifier **and digest**; authority-policy **version**;
- verification **cut/checkpoint**; chain range + completeness scope;
- signature/signer result; **authorization** result (the §3 Q2 answer); storage/transparency **proof** result;
- warnings / unsupported-legacy-semantics; **verifier version**.

A consumer asks for the claim it needs; it may not infer authorization from a signature-valid result.

**Trust & deployment model — receipts, not "unforgeable by construction."** Across dossier/cairn/agent-notes/CLI process boundaries, once a verified result is serialized to JSON a caller can fabricate it. Two acceptable models, chosen in §3/Phase 0: (a) every consumer invokes the core **locally** against pinned inputs; or (b) the core issues **authenticated verification receipts** signed by a separately-custodied *verifier identity*. Pick one explicitly; "hidden constructor" is not a security boundary.

**Inputs are trust boundaries.** `trust_root` and `at_cut` must come from **pinned project policy**, never ordinary request data — else a caller verifies under an attacker-chosen root or a stale cut.

**Authoritative claims ≠ display metadata.** "Every field a consumer reads must be signed" was both too broad (titles/display fields are legitimately mutable) and too narrow (a signed field can still be unauthorized/stale). The core distinguishes *authoritative claims* (must be verified) from *untrusted display metadata* (rendered as such, never as a verdict). UI preserves the distinction (kills the dossier "green badge over unverified data" class *and* avoids over-signing).

**Verify at ingestion + checkpoints, not every read.** Full replay per page/gate is impractical and a DoS vector. Design: verify at ingestion; incremental **authenticated checkpoints**; **verified projections** keyed by (evidence digest, policy version, trust-root digest, cut) with invalidation on authority/policy change; bounded proof verification on reads; periodic full-replay audit. Without this, teams add the performance bypasses that created the current mess.

**Fail-closed with an operational design.** Default DENY; a missing/unverifiable input is a refusal. But if the authority resolver / anchor / verifier is unavailable, gates stop — so the plan owes explicit **degraded-state behavior, cache-freshness rules, recovery procedures, and an audited break-glass** (§6). "Fail closed" without this becomes "add a hidden bypass later."

**What the core does NOT close (Sol).** It does not establish endpoint caller identity, project-admin authority, socket-peer identity, harness membership, environment safety, or process exit semantics — those are component-specific C4 controls. The core is necessary, not sufficient; the finding→control matrix (§2) is where "necessary vs sufficient" is made honest per finding.

---

## 5. Substrate — a threat-modelled bake-off (owner-confirmed)

The split (signing = §3-Q1/Q2, store-integrity = §3-Q3) is right; v1's "SQL Server lead unless cost is painful" was not. **Run a three-way spike, each tested against the same adversary scenarios** (§3): malicious *valid* writer, DB admin, host compromise, rollback (old DB + old checkpoint), fork/equivocation, anchor compromise, restore, projection rebuild, and realistic read volume. A database ledger only helps Q3, and only *tamper-evidence* (detect history rewrite vs. a trusted external digest) — it does **not** stop an authorized writer appending semantically fraudulent rows (that is Q1/Q2), nor omission-before-anchor, stale reads, or app-level bypass.

**The real trust boundary is anchoring, and it is not free.** Ledger/transparency-log verification is only worth anything if an attacker cannot rewrite *both* the store *and* the accepted checkpoint history. The design must specify: **who publishes digests, who signs them, where the signing keys live, who witnesses them, how clients learn the latest expected checkpoint, how rollback/equivocation is detected, and anchor cadence/retention.** *A public Git repo is not inherently immutable — a repo admin can rewrite it unless independent witnesses retain and monitor checkpoints.* Anchoring/witness design is therefore part of the substrate decision, not a downstream detail.

Candidates for the spike:

- **A. Hardened PostgreSQL as projection/query store + a signed append-only log as source of truth + externally-witnessed checkpoints (transparency-log design: Trillian/Rekor-style consistency + inclusion proofs, or a smaller purpose-built equivalent).** Preserves the Postgres investment; moves integrity *outside* mutable app tables without migrating all relational storage. Strong candidate.
- **B. SQL Server 2022 Ledger tables + independent digest witnesses.** Engine-enforced append-only + Merkle + external digest; Windows/AD fit; full T-SQL. Tamper-evident at verify-time. **Operational burden is its main weakness (§6).**
- **C. Purpose-built immutable store (immudb) + witnesses.** Per-transaction consistency/inclusion proofs (stronger than Ledger, but still only *detectable* to clients retaining trusted state — a compromised server can rollback/fork/deny unless witnessed); open-source, no per-core licensing; smaller ecosystem + SQL/operational maturity risk — needs a real workload spike, not a feature comparison.

Each option is scored on: security against the §3 adversaries; **operational requirements imposed on adopters (§6, first-class)**; migration cost + schema/query compatibility; HA/backup/restore + the *verification* runbook; Linux developer experience + driver ergonomics; licensing; monitoring/incident-recovery. Recommendation is deferred to the spike results — no presumptive lead.

---

## 6. Operational requirements imposed on adopters (first-class, owner-directed)

Every security guarantee here is also an **operational obligation on whoever deploys the suite** (recall the tertiary "deploy-at-work" goal — real adopters inherit this). We decide the architecture *with these costs explicit*, because a guarantee an adopter can't operationally sustain is a false guarantee. The plan must, per substrate/architecture option, enumerate and weigh:

- **Witness operation** — how many independent witnesses, run by whom, monitored how? (The strongest anti-rollback/equivocation guarantees need genuinely independent parties; a single-operator "witness" is theatre. For a small adopter this may be the single heaviest ask — and a reason to prefer a design that minimizes required witnesses, or a shared/public transparency-log with existing witness infrastructure.)
- **Anchor-signing key custody** — where the checkpoint/digest signing keys live (HSM / Vault / offline), rotation, and recovery.
- **Checkpoint distribution** — how clients/verifiers learn the current expected checkpoint out-of-band, and how that channel is itself trusted.
- **Substrate operations** — B: SQL Server licensing + admin skills + the ledger-verify runbook + Linux driver ergonomics; C: operating a less-common DB + proof retention; A: operating the transparency log + its witnesses.
- **Fail-closed recovery / break-glass** — documented degraded mode, cache-freshness policy, and an *audited* break-glass, so "fail closed" doesn't become a covert bypass.
- **Backup/restore + verification** — restore must not silently roll back the ledger/anchor; the restore runbook includes re-verification.
- **Version-skew & policy governance** — behavior when components run different core versions; and how verification *policy* changes without silently altering *historical* verdicts.

Explicit output: an **"operational requirements per option" table** produced by the spike, so decision 2 is made knowing exactly what we ask of every future deployer. The owner's stance: MSSQL's burden may be worth accepting — but only decided this way.

---

## 7. Rebuild vs. patch — stabilize-declined, incremental vertical slices

**Owner decision:** no separate emergency-containment track (suite not in production; no incremental risk). So we do **not** run parallel exploit-patching; we go to the incremental rebuild. (Had it been deployed, Sol's stabilize-now track would be mandatory — recorded for the deploy-at-work moment: *do not deploy the current suite to anyone before the rebuild.*)

**Rebuild the verification/consumption layer incrementally — not a big-bang core, and not a from-scratch rewrite of regista.** v1's rebuild-vs-patch binary was false; the model is *replace the consumption layer via vertical slices*, reusing lower layers **only after a fresh audit accepts each**:

- **Reuse boundary needs a crypto-protocol re-audit.** "The foundations held" is too optimistic — the inventory contains algorithm confusion (Ed25519-as-HMAC), a raw signing oracle, legacy-key-status loss, context-unbound signatures, and online/offline divergence. Reusing Ed25519 + JCS + the v6 envelope is likely fine, but only after each primitive and format at the *cryptographic protocol boundary* is explicitly re-accepted, not assumed.
- **Legacy v1–v5 containment is a required decision.** A secure v7 core that keeps accepting unsafe legacy evidence *by default* has not solved the problem. Decide: reject / quarantine-as-unverifiable / one-time re-anchor.

---

## 8. Phasing — vertical slices, with the corrections

- **Phase 0 — Trust model + anchor design + substrate spike.** Deliver `TRUST-MODEL.md` (§3); the anchoring/witness design (§5); the three-way spike scored incl. operational requirements (§6). **Gate:** owner picks substrate + trust/deployment model (local-verify vs receipts). *No architecture is frozen before this.*
- **Phase 1 — First vertical slice, end to end.** The smallest complete path that exercises the whole design: one authoritative event flow → one key lifecycle (incl. a rotation, to prove the §3 temporal model) → one checkpoint/anchor → one cairn decision → one gate → one projection/UI claim. Built on the chosen substrate with the scoped-claim core (§4). **Shadow it against production-like history; attack it (Daybreak + Opus); measure read performance.** Expand only after it survives. This replaces v1's risky "core lands, nothing consumes it."
- **Phase 2 — cairn, delivered *with* its authority source.** cairn is the weakest link and everything trusts it — but pointing it at a still-mutable regista authority source proves nothing (Sol). So cairn + the authoritative-state integrity it depends on ship as one vertical slice: witness-root circularity, retired-key classes (§3), and filtered/bundle PASS laundering closed against a *verified* authority base.
- **Phase 3 — regista consumers.** assurance, review/human gates, the persistence Criticals → scoped claims; delete mutable-row trust; context-bind root signatures (SEC-02); fix the lifecycle TOCTOU (SEC-09).
- **Phase 4 — agent-notes + agent-suite gates.** lineage/review + genesis gates consume claims; default-DENY; close open→done and the fail-open class.
- **Phase 5 — dossier.** display = pure function of a scoped claim; no badge without one; fix on_behalf_of impersonation.
- **Phase 6 — agent-wake + acb.** context-bound signing (trigger identity inside the HMAC), rotation expiry, capability grants that fail closed and pin *executable* identity, retired-SecretID revocation. **NOTE:** acb-1 is Critical and lives here — so cutover (below) cannot precede Phase 6.
- **Data/protocol migration — an explicit cross-cutting phase** (Sol): inventory historical envelope versions; classify unverifiable legacy history; dual-read/shadow verification; rebuild projections; checkpoint the migration boundary; compatibility with already-published bundles; rollback plan; then disable legacy verification.
- **Cross-cutting:** C5 items (parser limits, SSRF, symlink TOCTOU) as each component is touched.

**Cutover gate = named security invariants + supported attack surfaces, not severity alone (Sol).** A Medium that exhausts the verifier or breaks proof completeness can outweigh a nominal High in a disabled feature. Cutover requires: every named invariant in `TRUST-MODEL.md` holds under its stated adversaries; all reproduced Critical/High closed *with a matrix row + regression test*; the migration boundary checkpointed; the operational runbooks (§6) written. Because acb-1 (Critical) is Phase 6, **cutover is a whole-program gate**, not "after Phase 4" — v1's phrasing was internally contradictory and is corrected.

Each phase: **Sol implements against this plan; Fable reviews/advises; Daybreak re-confirms the gate code; two-reviewer ceremony on the core and each gate.**

---

## 9. Open decisions & recommendation

- **Open decisions for owner + Sol:**
  1. **Rebuild posture** — recommendation: incremental vertical-slice rebuild of the consumption/verification layer (§7), reuse lower layers only after re-audit. *No parallel containment* (owner-decided). *Do not deploy the current suite to anyone before the rebuild.*
  2. **Substrate + trust/deployment model** — decided by the Phase-0 spike scored incl. operational burden (§5/§6). No presumptive lead; Option A (Postgres + witnessed transparency log) and B (MSSQL Ledger) and C (immudb) are live.
  3. **Cutover gate** — recommendation: named-invariant gate (§8), whole-program (acb-1 is Critical in Phase 6).
  4. **Verification depth** — recommendation: reproduce every Critical + a representative High per class before freezing the architecture; batch-assess the rest into the finding→control matrix.
- **Biggest program risk (Sol):** the trust model being underspecified — which is why §3 is Phase 0 and gates everything.
- **Recommendation (one paragraph):** Do not ship or deploy the current design. Write the trust model and anchor/witness design first; build a single verified-evidence core that issues *scoped, policy-bearing claims* (with receipts across process boundaries) and verifies *at ingestion + checkpoints*; decide the substrate via a threat-modelled bake-off that treats the **operational burden on adopters as a first-class security criterion**; rebuild the consumption layer as incremental vertical slices, cairn-with-its-authority-source first, reusing lower layers only after a crypto-protocol re-audit and a legacy-containment decision; map every one of the 147 findings to a concrete control + regression test; and gate cutover on named security invariants holding under a named adversary model. Sol implements per phase; Fable reviews; Daybreak re-confirms.
