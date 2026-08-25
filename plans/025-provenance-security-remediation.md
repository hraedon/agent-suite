# Plan 025 — Provenance-Security Remediation (estate-wide)

- **Status:** DRAFT for review (Sol cross-lineage review + owner decision)
- **Author:** Claude Fable (mvmcc03)
- **Date:** 2026-08-25
- **Provenance of the finding:** whole-estate Daybreak Blue (`gpt-daybreak-blue-latest`) deep security review, 2026-08-25, run per component against the current mains; every regista trust-log finding independently reproduced by a Claude Opus probe-executor. Raw reports: `~/wi337-collision-evidence/daybreak-*.txt`; verified regista findings tracked as WI-342, WI-351..WI-362; consolidated inventory: `~/wi337-collision-evidence/CONSOLIDATED-INVENTORY.md`.
- **Decision this plan asks for:** (1) patch-in-place vs. rebuild the verification layer; (2) substrate — stay on PostgreSQL vs. move store-integrity into the platform (SQL Server 2022 Ledger / immudb); (3) whether cutover is gated on the whole program or a Critical+High subset.

---

## 0. TL;DR

The deep review did not find a list of bugs. It found **one architectural mistake, repeated in every component**: the estate implements its core trust primitive — *"given some events/rows/artifacts, decide what is authentic and who holds authority"* — many times, ad hoc, and each implementation **trusts unverified state**, **lets retired keys keep authority**, and **fails open**. **147 findings across all seven components (7 Critical, 73 High)** are symptoms of that one mistake; 97 of them fall into just four classes (§2).

Two structural fixes collapse most of them:

1. **Build the trust primitive once.** A single hardened *verified-evidence core*: it takes raw events/artifacts and returns a typed **`Verified<T>`** result only after checking signatures, reconciling row-vs-signed-envelope, resolving **current** key authority, and validating chain integrity. Every gate/verifier/UI/writer consumes it; the ~70 ad-hoc "trust the row" call-sites are deleted. This fixes the app-logic classes (C2/C3/C4) and half of C1.
2. **Move store-integrity into the substrate.** The single largest class (C1: *an operator/process with DB write forges rows the verifier trusts*) is not reliably closable in application code — the review proves that after four rounds of hardening it was still open. A **tamper-evident append-only store** (SQL Server 2022 Ledger tables, or immudb) makes "DB write ≠ undetectable forgery" a *platform* guarantee, using the exact digest-anchoring pattern the estate already hand-rolls in regista.

**Recommendation:** rebuild the verification layer (not patch), and adopt a tamper-evident substrate, phased so the **verifier core lands first** because everything downstream trusts it, and **cairn** (the provenance *verifier* — the estate's weakest link) is remediated first among consumers. Cutover is held until at least all Critical + High are closed; provable provenance is the product's entire value, and shipping a verifier with holes is worse than not shipping.

This is expensive. It is also the cheap option relative to shipping the current design and discovering these post-cutover or via an adversary — and relative to maintaining 70 hand-rolled copies of a primitive that should exist once.

---

## 1. What the review found

**147 findings** — **13 verified** (regista trust-log crown jewel, Opus-reproduced) + **134 Daybreak-rated** (unverified, pending triage-by-severity reproduction). Full deduped list: `~/wi337-collision-evidence/CONSOLIDATED-INVENTORY.md`.

By component (crown-jewel row at *verified* severity, rest Daybreak-stated):

| Component | Crit | High | Med | Low | Total |
|---|--:|--:|--:|--:|--:|
| regista — trust-log (crown jewel, **verified**) | 0 | 5 | 5 | 3 | 13 |
| regista — crypto/signing | 0 | 4 | 2 | 1 | 7 |
| regista — CLI/sidecar | 0 | 3 | 6 | 2 | 11 |
| regista — persistence/governance | **4** | 6 | 3 | 3 | 16 |
| agent-provenance — **cairn** | **2** | 13 | 6 | 1 | 22 |
| dossier | 0 | 5 | 9 | 3 | 17 |
| agent-suite (gate/orchestrator) | 0 | 9 | 7 | 0 | 16 |
| agent-notes (tracker + gate store) | 0 | 9 | 4 | 2 | 15 |
| agent-wake (the channel) | 0 | 9 | 5 | 0 | 14 |
| agent-capability-broker (acb) | **1** | 10 | 4 | 1 | 16 |
| **Total** | **7** | **73** | **51** | **16** | **147** |

By systemic class (§2):

| Class | Crit | High | Med | Low | Total |
|---|--:|--:|--:|--:|--:|
| C1 — trust unverified input | 4 | 18 | 5 | 1 | **28** |
| C2 — retired-key authority | 0 | 9 | 2 | 0 | **11** |
| C3 — unbound signatures | 0 | 14 | 4 | 2 | **20** |
| C4 — fail-open / missing authz | 2 | 22 | 12 | 2 | **38** |
| C5 — other (DoS/TOCTOU/injection/attribution/crypto-confusion) | 1 | 10 | 28 | 11 | **50** |

**C1–C4 account for 97 of 147 findings; C4 (38) and C1 (28) carry the high-severity mass** (the 7 Criticals are all C1 or C4). C5 is a Medium/Low DoS-and-races long tail. ≈2.4M review tokens across the estate.

The 7 Criticals: regista-persist ×4 (workflow enforcement trusts mutable registry JSON; review gates consume unverified evidence; durable lifecycle rows are mutable authority with digest never recomputed; commit finalizes a cancelled op), cairn ×2, acb ×1. Only the 13 crown-jewel findings are verified; the other 134 need triage-by-severity reproduction. **Note:** regista-crypto/cli/persist scanned the same commit (`7707c81`) as the crown jewel, so several of their rows re-discover SEC-* findings; the inventory §5 documents the dedups (each still listed as filed).

---

## 2. The four systemic classes

Nearly every finding is one of four root causes. This grouping is the plan's central claim: **fix the class, not the instance.** C4 (38) and C1 (28) are the largest classes and hold all 7 Criticals; `CONSOLIDATED-INVENTORY.md` lists the exact finding-IDs per class and the cross-component collisions — e.g. the "trust-the-rows" defect (SEC-11) recurs across ≥7 components (SEC-11, persist-2/9, dossier-2/4, an-8, aw-7), so *one* row↔envelope reconciliation invariant closes all of them at once.

### C1 — Trust the unverified input
A verifier / gate / UI / writer trusts a mutable DB row, projection, imported artifact, header, or manifest **without** verifying its signature, reconciling the row against its signed envelope, or requiring replay success.
- regista: assurance reads mutable columns (SEC-11/WI-355); persist Criticals (workflow trusts mutable registry JSON; gates consume unverified evidence; lifecycle rows are mutable authority).
- agent-notes: projection rows trusted as governance state; native verifier accepts unsigned ops by default; cross-project interchange strips signatures.
- dossier: renders `human-accepted` / `chain intact` / `completed tool-call` over unverified or tampered rows.
- cairn: integrity marker accepts un-MACed "legacy" verdicts as verified; filtered mode trusts unverified out-of-window attestations.
- agent-suite: genesis gate trusts forgeable probe reports.
**One fix:** nothing consumes a raw row/artifact; everything consumes `Verified<T>` from the core (§4).

### C2 — Retired / rotated / revoked keys retain authority
A key rotated out, revoked, or superseded can still authenticate, sign, or forge; or old signatures replay.
- regista: SEC-01 delegation fail-open (WI-351); WI-347/348/349 (already fixed in trust-log, but the *pattern* recurs); crypto "retired legacy keys forge accepted history."
- cairn: retired keys forge historical events; retired first key forges integrity-marker MACs.
- agent-wake: rotation "leaves the previous key fully authoritative without expiry."
- acb: retired AppRole SecretIDs remain valid indefinitely after "successful" rotation.
**One fix:** a single **current-authority resolver** — "is key K authoritative *at cut C*?" — that every verifier calls, and that treats revoked/superseded/expired/rotated-out as **not current**. (The regista WI-347/348/349 work is the template; it must become shared and universal.)

### C3 — Signatures / authorizations not bound to context
A signature verifies but binds too little — not the event id/seq/predecessor/nonce, source identity, project, actor, idempotency key, or executable identity — enabling replay, relabeling, or substitution.
- regista: SEC-02 root signatures bind no event context → threshold→one-root replay (WI-352); SEC-13 rotated-root signer_id unbound (WI-362).
- agent-wake: trigger identity outside the HMAC; a signed request relabeled to another source when sources share a key; outbound replies don't bind the idempotency key.
- acb: `trusted_argv` authenticates a *pathname*, not the executable's content identity.
**One fix:** a canonical **signing envelope** whose signed bytes bind the full context (domain-separated, length-framed, including id/seq/predecessor/nonce/project/actor as applicable), used everywhere. regista's `root_signature_input` and the v6 envelope are the starting point; the gap is that not all authorizations use it.

### C4 — Fail-open gates / missing authorization boundary
A gate or authorization defaults permissive, is bypassable, or a missing/invalid input grants broad rather than zero authority.
- agent-notes: lineage validation fails open; native mode has no project/admin authorization boundary; `open→done` is a general completion bypass.
- acb: detected rogue capabilities do not fail the gate; missing manifest → broad capability.
- agent-suite: `--exit-code` gate is opt-in (a naive call exits 0 when it should BLOCK).
- regista: SEC-10 default approval verifier is `None` (permissive) (WI-360).
**One fix:** gates fail **closed** by construction — the default of every gate is DENY; a missing/unverifiable input is a refusal, never a pass; authorization boundaries are mandatory, not optional.

### C5 — Other (independent, still real)
DoS/resource limits (SEC-12/WI-361; cairn/regista/dossier parser limits), SSRF (regista-cli, agent-notes wake URLs), TOCTOU (SEC-09/WI-359 lifecycle cancel race; sign-genesis symlink), crypto-primitive confusion (Ed25519-as-HMAC), attribution-only forgery (SEC-13, dossier on_behalf_of impersonation). These do not collapse into C1-C4 and get individual fixes, but most are Low/Medium.

---

## 3. Root-cause diagnosis

The estate was built with a **"trust the input, verify sometimes"** posture. That is the correct posture for a *convenience* tool. It is the wrong posture for a system whose entire value proposition is **provable provenance**, which requires **"verify always, trust nothing unverified, and trust no retired key."**

Two conflations made this pervasive:

1. **Signing vs. store-integrity are treated as one job.** "Is this authentic?" actually asks two independent questions: *who authored it and did they have authority?* (a signing/authority question) and *was the stored record altered after the fact?* (a storage-integrity question). The estate answers both in application code, per-component, and gets both wrong in places. They should be **separated**: signatures answer authorship/authority (verify always); a tamper-evident substrate answers storage-integrity (platform guarantee). See §5.
2. **Verification is a step callers may skip, not a type they must hold.** Because `read_events()` returns raw `Event`s and `verify()` is a separate optional call, every consumer is an opportunity to forget. The fix is to make *unverified* data unrepresentable at the boundary consumers use.

---

## 4. Proposal — the verified-evidence core

A single library (in regista, exported to every consumer) that owns the trust primitive.

**Shape (illustrative, not final API):**

```
verify_evidence(raw_events | artifact, *, trust_root, at_cut) -> Verified[T] | Refusal
```

`Verified[T]` is a typed, un-forgeable-by-construction result (constructed *only* inside the core, never by a caller — closing the WI-337 "caller-constructible verification object" footgun estate-wide). It is produced only after ALL of:

- **Signature verification** over the canonical, context-bound envelope (§C3), domain-separated.
- **Row ↔ signed-envelope reconciliation** — every field a consumer reads (transition, actor, kind, lineage, status, timestamps) must equal the signed envelope; any divergence is a hard refusal (kills C1 at the source; note regista already *has* `_reconcile_v6` — the fix is that assurance/gates/UI don't call it).
- **Current-authority resolution** (§C2) — every key/principal/registrar/root resolved to its status *at the relevant cut*; revoked/superseded/expired/rotated-out ⇒ not authoritative.
- **Chain integrity** — replay must succeed (no `halted`/`chain_breaks`; drift alone is not "intact" — closes the dossier "halted treated as intact" class).
- **Validity windows** enforced (closes SEC-03/WI-353) — online and offline paths use the *same* core, ending the online/offline divergence.

**Consumption contract:** assurance, the review/human gates, cairn's bundle/witness verifier, dossier's display, agent-suite's genesis gate, and agent-notes' lifecycle gate **only** accept `Verified[T]`. The raw-row code paths are deleted, not deprecated. `gate_permits_done`, "human-accepted," "chain verified," "externally authenticated," and "capability granted" become functions of `Verified[T]` and nothing else.

**Why this collapses the inventory:** C1 (trust-the-row) and much of C2/C3/C4 are *the same call-site bug* in seventy places; one core + a deletion pass fixes them together, and — critically — makes the *next* consumer safe by default instead of one refactor away from the seventy-first instance.

---

## 5. Substrate decision (owner: PostgreSQL "not set in stone")

The largest class, C1, has a sub-class the review shows is **not reliably closable in application code**: *an operator or process with database write access forges rows that a verifier later trusts.* regista's answer is app-layer hash-chaining + external digest anchoring — and after four hardening rounds it was still bypassable (SEC-11, the persist Criticals, all of dossier's Highs). This is the strongest argument for moving store-integrity into the platform.

**The reframe:** the estate already publishes trust-domain / genesis / checkpoint digests to an external immutable location (a public git repo) so that tampering is *detectable*. A tamper-evident database does exactly this, engine-enforced, for the whole store.

### Option A — Hardened PostgreSQL (status quo substrate)
- Keep Postgres; build the verified-evidence core (§4); tamper-evidence stays an **application** responsibility (append-only via constraints/triggers + the existing hash-chain + external digest anchoring).
- **Pro:** no migration; current investment, drivers, ops, backups, `regista` test harness all intact; team fluency.
- **Con:** the operator-forgery sub-class of C1 remains an *app* guarantee — i.e., exactly the thing that was repeatedly bypassed. Mitigated but never structurally closed. We would be betting the product's core claim on getting hand-rolled tamper-evidence right where we have four rounds of evidence that it is hard.

### Option B — SQL Server 2022 Ledger tables (recommended lead)
- **Append-only ledger tables** (engine-enforced insert-only) for the event store + trust log; Merkle-hashed into a blockchain; periodic **database digests anchored to external WORM/immutable storage** (on-prem WORM, Azure Blob immutability, or the existing public-repo pattern); `sys.sp_verify_database_ledger` detects any post-hoc mutation.
- **Pro:** "DB write ≠ undetectable forgery" becomes a *platform* guarantee → collapses the operator-forgery C1 sub-class outright; fits a Windows/AD shop (we already run an AD domain + a Windows lab box); full T-SQL; Microsoft-maintained maturity; Python via `pyodbc`. Aligns with the estate's existing digest-anchoring instinct.
- **Con:** migration off Postgres is significant (storage layer, `psycopg`→`pyodbc`, SQL migrations, the whole `regista` test harness, dev-env parity); licensing for a production instance (Developer edition is free for non-prod; Standard/Enterprise or Azure SQL for prod — **cost to verify**); Ledger is tamper-*evident* at verify time, not tamper-*proof* at write (an admin can drop ledger/table, but the act is itself detectable + the anchored digest proves the break). Some ORM/feature parity work.
- **Due-diligence items (before committing):** exact prod licensing cost; `pyodbc`/driver ergonomics on Linux app hosts; digest-anchoring cadence + storage; whether append-only ledger semantics fit the projection-rebuild pattern (projections are derived, can be non-ledger regular tables recomputed from the ledger event store — likely fine); backup/restore + the ledger verification story; migration tooling (Postgres→MSSQL is not turnkey).

### Option C — immudb (purpose-built immutable DB)
- Zero-trust, append-only, cryptographic proof **per transaction** (tamper-*proof* at write, stronger than Ledger's verify-time model); KV + SQL; open-source (Codenotary) with commercial support; HIPAA/compliance-oriented; 1.11 added immutable audit logging (who/when).
- **Pro:** the product's *entire purpose* is exactly our requirement; strongest write-time guarantee; open-source + on-prem; no per-core licensing.
- **Con:** smaller ecosystem and operational maturity than Postgres/MSSQL; a less complete SQL surface (feature-parity risk for regista's queries); a newer bet to run in production; smaller hiring/knowledge base; migration effort comparable to Option B.

### Substrate recommendation
**Lead with Option B (SQL Server Ledger)**, pending the due-diligence items, because it closes the operator-forgery class with the maturity and Windows/AD fit this estate has, while keeping a full SQL surface. **Keep Option C (immudb) as a serious alternative** if MSSQL licensing or Linux-driver ergonomics prove painful — its write-time proof model is technically superior and it is purpose-built for this. **Option A only if** the migration cost is judged to outweigh structurally closing C1 — but be honest that Option A leaves the product's core claim resting on the app layer the review just spent a day breaking.

**Crucial scoping note:** whichever substrate, it **only** addresses the operator-forgery sub-class of C1. C2 (retired keys), C3 (context-binding), C4 (fail-open), and the rest of C1 (a validly-signed-but-authority-laundered event is stored *faithfully* by a tamper-evident store) are **app-logic** and require the verified-evidence core regardless. The substrate is a force-multiplier, not a replacement for §4.

---

## 6. Patch-in-place vs. rebuild

**Patch-in-place** (fix ~140 findings where they are): lowest immediate disruption, but (a) it is ~140 discrete gate-code fixes each needing dual-lineage review — plausibly *more* total effort than the rebuild; (b) it leaves the systemic posture intact, so the 141st call-site reintroduces the class; (c) it does not resolve the signing/store-integrity conflation. Patching is how we got four rounds deep on WI-337 and still had SEC-01 waiting one subsystem over.

**Rebuild the verification layer** (§4 + §5): higher up-front cost, but it converts ~70 of the findings into "delete the raw-row path, route through the core," makes the estate safe-by-construction, and gives *one* place to audit instead of seventy. The event model, the v6 envelope, the WI-347/348/349 authority work, and the digest-anchoring pattern are all **reusable** — this is a rebuild of the *verification and trust-decision layer*, not a from-scratch rewrite of regista.

**Recommendation:** **rebuild the verification layer; reuse the event/envelope/crypto foundations; adopt a tamper-evident substrate.** Treat "start fully fresh" as *not* warranted — the primitives (Ed25519 signing, JCS canonicalization, the v6 envelope, the trust-log model, digest anchoring) largely *held up* in the review ("controls that held" lists are substantial); the failure is in how they are *consumed*, which is the layer we replace.

---

## 7. Phased sequence

Ordered by "what everything else trusts," so we never build on unverified ground:

- **Phase 0 — Substrate decision + spike.** Resolve §5 due-diligence; a thin spike proving the event store + trust log on the chosen substrate with digest anchoring and a passing `regista` interop subset. Gate: owner sign-off on substrate.
- **Phase 1 — The verified-evidence core (regista).** Build `verify_evidence`/`Verified[T]`, the shared current-authority resolver, the canonical context-bound signing envelope, and fail-closed gate defaults. Land behind the existing regista test discipline (epoch-debt manifest, two-reviewer ceremony, Daybreak re-confirm). Nothing consumes it yet.
- **Phase 2 — cairn first.** The provenance *verifier* is the weakest link and everything downstream (dossier, attestation) trusts it. Re-point cairn's bundle/witness/integrity-marker verification at the core; delete its ad-hoc trust paths; fix the witness-root circularity and retired-key classes. Daybreak re-confirm cairn specifically.
- **Phase 3 — regista consumers.** assurance, the review/human gates, the persistence Criticals — route through the core; delete the mutable-row trust; enforce validity windows; bind root signatures to context (SEC-02); fix the lifecycle TOCTOU (SEC-09).
- **Phase 4 — agent-notes + agent-suite gates.** Lineage/review gates and the genesis gate consume `Verified[T]`; fail-closed defaults; close the open→done and fail-open classes.
- **Phase 5 — dossier.** Display becomes a pure function of `Verified[T]`; no green badge without it; fix on_behalf_of impersonation.
- **Phase 6 — agent-wake + acb.** Context-bound signing (trigger identity in the HMAC), key-rotation expiry, capability grants that fail closed and pin executable identity, retired-SecretID revocation.
- **Cross-cutting, any phase:** the C5 items (parser resource limits, SSRF, symlink TOCTOU) as they touch each component.

Each phase: **Sol implements against this plan; Fable reviews/advises; Daybreak re-confirms the gate code.** Cutover is held until Phases 1–4 (Critical + High) are closed at minimum; Med/Low may trail into a follow-up if the owner chooses (§8 decision 3).

---

## 8. Effort, risk, and open decisions

- **Effort:** large — a multi-phase program, not a sprint. The rebuild front-loads cost (Phases 0–1) then *accelerates* (Phases 2–6 are largely "route through the core + delete") relative to 140 discrete patches. Substrate migration (if B/C) is the single biggest line item and the main schedule risk.
- **Risk:** (1) substrate migration underestimated — mitigated by the Phase-0 spike gating the decision; (2) the core's API is load-bearing — it gets the full two-reviewer + Daybreak ceremony; (3) scope creep — the C1-C4 grouping is the guardrail (if a proposed fix isn't collapsing a class, question it).
- **Open decisions for owner + Sol:**
  1. **Patch vs. rebuild** — recommendation: rebuild the verification layer (§6).
  2. **Substrate** — recommendation: SQL Server Ledger (Option B), immudb (C) as live alternative, pending Phase-0 due-diligence (§5).
  3. **Cutover gate** — whole program vs. Critical+High-then-trail. Recommendation: gate on Critical+High (Phases 1–4); track Med/Low to a named follow-up.
  4. **Verification depth on the ~127 unverified findings** — reproduce all vs. triage-by-severity. Recommendation: reproduce Critical/High with rigor (they drive the fix wave); batch-assess Med/Low from the reports.

---

## 9. Recommendation (one paragraph)

Do not ship the current design; provable provenance is the whole value and the verifier has holes in every component. **Rebuild the verification layer around a single hardened verified-evidence core** that everything consumes, **separate signing from store-integrity**, and **move store-integrity into a tamper-evident substrate — SQL Server 2022 Ledger as the lead, immudb as the alternative — decided behind a Phase-0 spike.** Sequence verifier-core-first and cairn-first. Reuse regista's crypto/envelope/event foundations (they held up); replace the consumption layer (it did not). Hold cutover until Critical + High are closed. Sol implements per phase against this plan; Fable reviews; Daybreak re-confirms the gate code.
