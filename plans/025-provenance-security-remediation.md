# Plan 025 — Provenance-Security Remediation: kernel, gate engine, and one sound vertical slice

- **Status:** v3.1 (supersedes v2). Sol round-3 review of v3: *sound-with-changes* — "the security model and four-boundary architecture have converged; Phase 0A may start"; its five blocking items are folded in here (`plans/025-evidence/sol-plan025-rereview3.md`). **D1 (structural pivot) and D2 (Phase 0A go) APPROVED by owner 2026-08-25.** D3 decided: stage 1 now (informal, opportunistic), stage 2 deferred (§9).
- **Author:** Claude Fable (mvmcc03) · **Plan reviewer:** GPT-5.6 Sol (cross-lineage). v1 → *needs-rework*; v2 → *sound-with-changes*, "I no longer consider the provenance mechanism itself fundamentally underspecified." Reviews: `plans/025-evidence/sol-plan025-review.md`, `plans/025-evidence/sol-plan025-rereview2.md`.
- **Date:** 2026-08-25
- **Provenance of the finding:** whole-estate Daybreak Blue deep security review (2026-08-24/25), per component against current mains; the 13 regista trust-log findings (SEC-01..13) independently reproduced by a Claude Opus probe-executor. Inventory: `plans/025-evidence/CONSOLIDATED-INVENTORY.md` (147 findings: 7 Critical, 73 High, 51 Medium, 16 Low). Raw reports, probes, reviews and transcripts versioned in the `plan-025-evidence` git repo (`~/projects/personal/plan-025-evidence/` on mvmcc03; local only until the owner OKs a remote). Verified regista findings tracked as WI-342, WI-351..362.
- **Reviewed refs:** regista family `7707c81`; cairn `74471ad`; dossier `d775b6d`; agent-suite `a153213`; agent-notes `235c2b6`; agent-wake `f6a0eed`; acb `f2df972`.

---

## 0. TL;DR

The deep review found **one architectural posture applied everywhere — "verify sometimes, trust the input"** — in a system whose entire value is *provable* provenance. 147 findings across all seven components are its symptoms. Sol and Fable now agree on the security model (v2 §3–§4 carried forward below), and on a structural conclusion v2 did not reach: **the seven mutually-trusting projects should collapse into four trust-bearing boundaries plus non-trust-bearing apps**, because the duplication between them (two lifecycle interpretations, two PASS aggregations, two gate implementations, mutable governance rows as source of truth) *is* the root of the finding classes.

The owner's 2026-08-25 answers fix the target and therefore the scope:

- **The relying party is real:** a HIPAA-regulated, mostly on-prem-hybrid, almost-entirely-Windows work environment that wants to adopt agents but cannot yet trust the evidence. The cryptographic provenance layer ("C" in §1) is therefore **the moat, not overhead** — and its soundness is existential, because that environment's security function will red-team the claims exactly as Daybreak did.
- **The environment is not built yet and there is no time pressure.** So the provenance system and its deployment environment are **co-designed**, the operational burden that made heavy substrates unattractive (witnesses, anchor custody, ledger ops) becomes designed-in infrastructure rather than a retrofit, and we build **soundly, vertical-slice-first**, with no cutover until a red team fails to forge the slice.
- **Auditor requirements are unknowable in advance**, so the plan does not try to elicit them. It makes the evidence **isomorphic to forms auditors already accept** (HIPAA §164.312 technical safeguards, SLSA/in-toto/sigstore attestations, ITGC change-control and segregation-of-duties records, RFC 3161 timestamping, chain-of-custody) as *hypotheses* that the target environment's compliance owners then validate in stages (§7, D3) — precedent narrows the acceptance problem; it does not settle it. This replaces the unanswerable "gather auditor requirements up front" workstream.

**The plan in one line:** write the trust model and choose the decomposition first (Phase 0A), run a time-boxed substrate/anchor bake-off against it with SQL Server Ledger as the leading candidate *for this environment* (0B), decide (0C); then build **one** end-to-end governed, reviewable, verifiable agent workflow on the new structure — provenance kernel + governance/gate engine + review surface + credible anchor — attack it, and only then expand; map every one of the 147 findings to a control and a regression test; gate cutover on named invariants per deployment profile. Sol implements per phase; Fable reviews; Daybreak re-confirms gate code with two independent reviewers.

**Do not deploy the current suite to anyone before the rebuild.** The live estate cutover (0.6.0 program) stays **held**.

---

## 1. Why this system, and why C earns its cost (owner-settled 2026-08-25)

What the estate bundles is three separable capabilities:

- **A — Enforced governance/review.** Work cannot reach "done" without an independent *different-lineage* adversarial review and a human gate. Active enforcement. (This program itself is the proof A is valuable: two-reviewer discipline caught real, exploitable bugs.)
- **B — Capture, digest, replay.** Passive observability of what agents did. Table stakes and commoditising; the labs and startups already ship it.
- **C — Cryptographic, attributable, tamper-evident provenance under named assumptions.** Signed events, verifiable trust log, external anchoring, the verifier. (Not "non-repudiable" in the absolute sense: signatures are evidence under stated key-custody and compromise assumptions; they do not establish human intent.) C motivates the program and holds most of the high-severity mass; but the 147 also include governance-authorisation, capability/secret-release, transport, supply-chain and parser/DoS defects that are not cryptographic-provenance bugs and get their own controls in the matrix. The operational burden on adopters lives in C.

C buys exactly one thing A+B cannot: **verifiability by a relying party who must not trust the operator, the agents, or the log store.** The owner confirmed that relying party exists and is the venture's thesis — a high-scrutiny environment adopting agents. So **A + C is the differentiated product**; B is supporting. Consequences: (i) soundness is a feature, not gold-plating — "we found 147 holes and closed them provably" is the evidence the guarantees are real; (ii) scope is a **minimal genuinely-sound proof-of-thesis first**, then estate-wide hardening — not seven components hardened to production before the core claim has survived a skeptic.

**PHI boundary (HIPAA-load-bearing, stated non-goal).** This system attests *agent development work* — provenance of what agents did to code and artifacts. It is designed not to ingest, retain, or attest patient data. A provenance store that becomes a PHI store is a compliance liability, not an asset. The trust model records this as an explicit non-goal backed by a *layered* data-boundary design, not a single classifier (Sol round-3: "must never ingest" exceeds what content classification can guarantee — PHI can arrive in source, logs, screenshots, binaries, encoded payloads or model transcripts, and classifiers have false negatives). Required elements: (i) an **allowed-content definition and data minimisation** — what artifact kinds and fields the kernel accepts at all; (ii) **scanning + refusal as defence-in-depth**, with an audit event; (iii) explicit treatment of **opaque/encrypted artifacts** (digest-only by default, never content); (iv) a **quarantine, deletion and incident-handling procedure** for PHI captured despite the controls — accidental capture does not cancel HIPAA incident obligations; (v) a recorded **residual statement** that the absence of PHI cannot be cryptographically inferred from the log.

---

## 2. What the review found

**147 findings** — 13 verified (crown-jewel, Opus-reproduced) + 134 Daybreak-rated (unverified). Full deduped list with dedup notes: `plans/025-evidence/CONSOLIDATED-INVENTORY.md`.

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

**Evidence-maturity rule.** Only 13/147 are reproduced. Counts, collapse claims and the cutover map are **not** locked on unreproduced model classifications. Reproducing every Critical and a representative High *per distinct mechanism* (not merely per C-class), plus a provisional control-owner for all 147 rows, is a **Phase-0 architecture-freeze gate** (§8), not a later nicety.

### Systemic classes — triage categories, not root causes

- **C1 Trust the unverified input** (28) — the row↔envelope reconciliation class; the SEC-11 collision recurs in ≥7 components. Largest single-invariant-closable subset, but also holds unsigned manifests, PATH/executable substitution, package integrity, which it does not close.
- **C2 Retired/rotated/revoked keys retain authority** (11) — needs the temporal authority model (§4), not a "current authority" flag.
- **C3 Signatures/authorisations not bound to context** (20) — shared framing + domain separation; per-principal semantics stay distinct.
- **C4 Fail-open gates / missing authorisation boundary** (38, the largest) — default-DENY plus component-specific authz controls (endpoint identity, socket peer, project-admin boundary, capability enforcement).
- **C5 Other** (50) — DoS/resource limits, TOCTOU, SSRF/injection, attribution-only, crypto-primitive confusion (incl. Ed25519-as-HMAC). Mostly Medium/Low; patched as each component is touched.

**Required artifact: the finding→control matrix.** Every finding is classified *fully closed by the kernel / partially mitigated / independently patched / invalidated after reproduction*, with its regression test named. Collapse is a hypothesis the matrix demonstrates per finding.

---

## 3. Target structure — four trust boundaries (DECISION D1 — APPROVED 2026-08-25)

Sol's greenfield decomposition, which Fable endorses without reservation. Each existing component keeps its *purpose*; its *shape* changes. "One project" never means "trust the server's self-verdict": writer, verifier and witness remain separate trust **zones**; clients verify proofs locally.

| # | Boundary | Absorbs | Owns | Does not own |
|---|---|---|---|---|
| 1 | **Provenance kernel** | trust-bearing parts of **regista + cairn** | canonical event/envelope protocol; append-only log interface + authenticated checkpoints; temporal key/authority state machine; inclusion/consistency/completeness proof verification; scoped claim production; local verifier SDK/CLI; optional receipt issuer; legacy-evidence quarantine + migration tooling | endpoint identity, OS enforcement, gate policy |
| 2 | **Governance & gate engine** | gate logic from **agent-suite** (genesis/release) + **agent-notes** (review/lifecycle) + dual-control checks | accepts only scoped kernel claims + authenticated caller identity; deterministic versioned policy; context-bound decision events atomically bound to the admitted action; default-DENY, separation-of-duties, transition and policy-version semantics | tracking UX, orchestration |
| 3 | **Capability enforcement broker** | **acb**, kept separate | consumes `CapabilityGrant` claims and independently enforces caller/harness identity; executable identity by **content digest + ownership + symlink/TOCTOU-safe resolution** (acb-7: a pathname is not an identity); environment restrictions; short-lived credentials + revocation; fail-closed execution | anything cryptographic beyond claim consumption (keeps Vault/subprocess code out of the crypto TCB) |
| 4 | **Minimal bootstrap/update root** | slimmed **agent-suite** | an **offline/control-plane** TCB: signed lock + artifact verification; trusted executable resolution; **trust-root provisioning**; **trusted policy/configuration selection**; deterministic provisioning; rollback/restore verification | any runtime gate semantics |

**Non-trust-bearing:** **agent-notes** becomes a domain app over the gate engine (commands + projections rebuildable from authenticated governance events; no NullSigner mode; no local transition interpretation). **dossier** is a pure human surface (renders scoped claims and explicitly-untrusted metadata; cannot mint a *machine-consumable* trusted claim — but a compromised UI can still mis-render what a human believes they approved, so browser/session security and render-integrity remain real, matrix-tracked controls). **agent-wake** is non-authoritative transport (transport auth, replay control, peer binding, limits — but a wake message never authorises a transition, secret release, or gate pass; the receiver re-authorises through boundary 2 or 3).

Rationale: this eliminates duplicate lifecycle interpretation, duplicate PASS aggregation, mutable governance sources of truth, and scattered fail-open gate code — the mechanisms behind C1/C2/C4. It does **not** eliminate endpoint authentication, OS enforcement, parser safety or supply-chain controls; those remain explicit per-boundary controls in the matrix. A **separate differential verifier** is retained for testing and audit (independent semantic cross-check of the authoritative implementation) — never as a second production interpretation.

**Build forward, don't migrate in place.** The new structure is created by the first vertical slice (§8 Phase 1), not by refactoring seven repos into four. Existing mains remain frozen reference/evidence until the slice supersedes them. Repository and process boundaries (one repo vs. several, sidecar vs. SDK) are a Phase-0C decision; the *logical* decomposition above is what D1 ratifies.

**Language/stack question (criteria in 0A, decision in 0C — Sol round-3).** The target is almost entirely Windows. Python-on-Windows is viable; aligning the production kernel to the environment's .NET/SQL-Server-native stack is a legitimate operability criterion. Choosing in 0A would pre-decide substrate and deployment outcomes 0B is meant to discover, so 0A fixes the *criteria* (portability, Windows operations, FIPS/HSM integration, deployment, staffing) and 0C selects the stack with bake-off evidence in hand. Whichever way, the protocol is specified language-neutrally with **one authoritative implementation** and a conformance suite (Sol: "one protocol, one authoritative implementation" — not "one library", which couples languages and turns a package version into a distributed trust boundary).

---

## 4. Trust model (Phase 0A — gates everything)

Carried from v2, agreed by Sol. Provenance answers **three** questions, resolved separately and explicitly:

1. **Authentication** — did key K produce these exact bytes? (signature over a context-bound, domain-separated envelope)
2. **Authorisation at position** — was K authorised for this action *at the authenticated log position / policy version*?
3. **Completeness & non-equivocation** — is the evidence complete, ordered, durable, and free of forked/omitted history?

**Temporal authority semantics (the C2 fix).** Distinguish: authority at event/log position; permission to author now; verifier knowledge at a later cut; retroactive invalidation after compromise (an explicit signed revocation-with-effect-range, distinct from rotation). Authority resolves against an **authenticated log position/checkpoint**, never a caller-supplied timestamp — this makes SEC-04 backdating and SEC-07 caller-controlled validity unexploitable by construction, without invalidating valid history at every rotation.

**Adversary model.** Named separately, each with the layers it can compromise: ordinary user, service principal, compromised component, DB writer, DB administrator, host root, verifier operator, anchor/witness operator, signer-key holder, and colluding combinations. Every claim the system emits names the adversaries it does and does **not** resist. (Extends regista's OPERATOR-FORGERY residual-threat doc, WI-007, to the whole stack.)

**Also required as 0A outputs (Sol round-2):** deployment trust zones; degraded-state/freshness semantics and break-glass *authority* (who may invoke it, how it is audited) — these shape the trust model and cannot wait for cutover runbooks; the **legacy v1–v5 evidence decision** (reject / quarantine-as-unverifiable / one-time re-anchor) — must be made **before the first slice admits any legacy evidence**; the **PHI non-goal** and its enforcement control (§1).

Deliverable: `TRUST-MODEL.md` — adversaries, the three questions, temporal semantics, trust zones, claim-by-adversary matrix, legacy policy, degraded-state semantics, PHI boundary.

---

## 5. The kernel's verified-evidence contract

Carried from v2, agreed by Sol, with the round-2 corrections:

- **Scoped, policy-bearing claims, not a boolean.** Consumers request a specific claim; each carries the normalised claims verified (and those *not* verified), evidence digest, trust-root id + digest, authority-policy version, verification cut/checkpoint, chain range + completeness scope, separate authentication / authorisation / storage-proof results, warnings and legacy-semantics flags, verifier version. A consumer may not infer authorisation from a signature-valid result.
- **Claims named as auditor-recognised concepts (v3).** `IndependentReviewAttestation`, `TamperEvidentChangeRecord`, `AttributableAuthorship`, `TrustedTimestamp`, `CapabilityGrant`, `ExternallyAuthenticatedBundle` — each documented with the accepted-paradigm precedent it rides on (§7).
- **Local proof verification is the default; receipts are the exception (Sol).** A receipt authenticates *what a verifier said*, not that it was correct, and adds a high-value key, its lifecycle, revocation, freshness and a centralised availability dependency. Use receipts only where a consumer genuinely cannot host the verifier, and state which verifier-operator compromises they do not resist.
- **Inputs are trust boundaries.** `trust_root` and `at_cut` derive from pinned project policy, never from request data.
- **Authoritative claims ≠ display metadata.** UI preserves the distinction; no badge without a claim.
- **Verify at ingestion + checkpoints, not every read.** Incremental authenticated checkpoints; verified projections keyed by (evidence digest, policy version, trust-root digest, cut) with invalidation on authority/policy change; bounded proof verification on reads; periodic full-replay audit.
- **Fail closed, with an operational design** (degraded mode, cache freshness, recovery, audited break-glass) so "fail closed" never becomes a hidden bypass.
- **What the kernel does not close:** endpoint caller identity, project-admin authority, socket-peer identity, harness membership, environment safety, process exit semantics — per-boundary C4 controls, made honest in the matrix.

**Crypto-protocol re-audit before reuse.** Ed25519 + JCS + the v6 envelope are *likely* reusable, but the inventory contains algorithm confusion, a raw signing oracle, legacy-key-status loss, context-unbound signatures, and online/offline divergence. Each primitive and format at the protocol boundary is explicitly re-accepted, or replaced. Nothing is reused by assumption.

---

## 6. Substrate and anchoring — time-boxed bake-off, environment-informed (Phase 0B)

**The split stands:** signatures answer Q1/Q2 (authorship and authority); the store + anchor answer Q3 (it wasn't altered after the fact). A database ledger is tamper-**evident**, not forgery-prevention: it does not stop an authorised writer appending semantically fraudulent rows, omission before anchor, stale reads, or app-level bypass. **The real trust boundary is external anchoring + independent witnesses**, and the design must specify who publishes digests, who signs them, where those keys live, who witnesses, how clients learn the expected checkpoint, how rollback/equivocation is detected, and cadence/retention. A Git repo is not immutable unless independent witnesses retain and monitor checkpoints.

**Candidates:** **A.** hardened PostgreSQL as projection store + signed append-only log as source of truth + witnessed transparency-log checkpoints (Trillian/Rekor-style or a smaller equivalent), optionally WORM/object storage for signed segments. **B.** SQL Server 2022 Ledger tables + independent digest witnesses. **C.** purpose-built immutable store (immudb) + witnesses.

**Environment tilt (v3, owner-informed) — an operational-fit *hypothesis*, not a headline winner.** For an almost-entirely-Windows, on-prem-hybrid, HIPAA shop, **B is the current fit leader** — the ops burden that made it unattractive in the abstract likely folds into infrastructure the adopter already runs, and it is being designed in rather than retrofitted. Two honesty constraints (Sol round-3): (i) the premise "already operates SQL Server and AD with the relevant edition, DBA capability, HA/restore practice and digest-management support" is an **assumption to validate in 0B before it carries scoring weight**, not an established requirement; (ii) the **scoring rubric is fixed before measurements**, and witnesses must sit **outside the SQL Server/DBA failure domain**. Security soundness is unproven for all three candidates until the bake-off; A and C stay fully live. Phase 1 is ordered after 0C — the first slice is built on the *decided* substrate, not on whichever is fastest.

**Time-box (Sol):** not three prototypes — the minimum common workload that can *falsify* a candidate: append, rotation, proof, checkpoint, fork/rollback, restore, representative read volume; each run against the same adversary scenarios (malicious valid writer, DB admin, host compromise, rollback to old DB + old checkpoint, fork/equivocation, anchor compromise, restore, projection rebuild).

**Operational requirements on adopters are a first-class security criterion (owner-directed).** Output: an *operational-requirements-per-option* table — witness count/operators/monitoring, anchor-key custody + rotation + recovery, checkpoint distribution channel and its trust, substrate ops (licensing, skills, verify runbook, driver ergonomics), fail-closed recovery/break-glass, backup/restore with re-verification, version-skew and policy-governance behaviour. A guarantee that depends on operational discipline an adopter won't sustain is a false guarantee; the heavier option may be worth accepting, but only decided this way.

---

## 7. Admissibility by isomorphism (Phase 0A workstream, v3)

Nobody can say today what an auditor will require to accept agentic work; asking them is premature. The strategy — the one the original design already followed — is to make our evidence resemble artifacts auditors already trust in adjacent mature domains, so acceptance rides on precedent:

| Accepted paradigm | What we borrow | Claim(s) it grounds |
|---|---|---|
| HIPAA Security Rule technical safeguards (45 CFR §164.312 — access control, audit controls, integrity, person/entity authentication) | the safeguards themselves, instantiated for agent work | `TamperEvidentChangeRecord`, `AttributableAuthorship`, audit-trail completeness |
| Software supply-chain provenance (SLSA, in-toto, sigstore) | signed attestation forms; verifiable authorship/build provenance | `AttributableAuthorship`, `ExternallyAuthenticatedBundle` |
| ITGC / SOC 2 change-management and segregation-of-duties records | "independent party reviewed and approved this change; tamper-evident record" | `IndependentReviewAttestation` (the cross-lineage review + human gate — our differentiator in the auditor's native vocabulary) |
| RFC 3161 trusted timestamping; forensic chain-of-custody | the "when" and unbroken-custody claims | `TrustedTimestamp`, custody continuity |

**What this strategy is and is not (Sol round-3).** Isomorphism is *design guidance and a set of hypotheses to validate*, not acceptance "riding on precedent." §164.312 specifies safeguards, not an evidence format auditors automatically accept; SLSA, sigstore, RFC 3161, ITGC and SOC 2 address adjacent but different control objectives. The strategy fails when an analogy is merely syntactic — two named failure modes the map must confront: a `TrustedTimestamp` without an accepted TSA and validation policy is not RFC 3161 evidence; and **different model lineage is diversity, not ITGC segregation of duties** — `IndependentReviewAttestation` must bind reviewer identity, role, organisational authority, conflicts, the reviewed subject digest, policy version and the human approval, with an explicit **independence policy**. Final claim *vocabulary* is fixed in 0C, after validation, not in 0A.

Deliverable: `ADMISSIBILITY-MAP.md` — each kernel claim, the paradigm it hypothesises isomorphism to, the precedent citation, the failure mode that would break the analogy, and its validation status. Phase 0A drafts it internally; **claim naming and production acceptance require validation by the target environment's risk/compliance/control owners** (mandatory, staged — see D3 in §9). The §164.312 mapping is an engineering reading, not a compliance opinion, and the map says so.

---

## 8. Phasing

**Phase 0 — ordered gates (Sol round-2).**
- **0A — Model + decomposition**, run as **four independently reviewable work products** (Sol round-3): **(0A-1)** trust/adversary model + **invariant registry** with stable invariant identifiers (`TRUST-MODEL.md`, §4 — incl. trust zones, legacy-evidence decision, degraded-state + break-glass authority); **(0A-2)** finding reproduction + a **mechanism taxonomy** with a written representative-High selection rule; **(0A-3)** the provisional **finding→control→test matrix** (committed schema, 147 initial rows, provisional owner per row); **(0A-4)** admissibility hypotheses (§7) + the PHI/data-boundary analysis (§1). Also in 0A: language/stack *criteria* (§3). D1 is already ratified — what 0A fixes is the *logical* decomposition; repo/process boundaries stay open for 0C. **Freeze gate:** all Criticals and a representative High per distinct mechanism reproduced; matrix populated; the 0B scoring rubric frozen. *No API, repo or ownership is frozen before 0A closes.* **Startup inputs, committed before 0A-1 begins:** named owner + reviewer + acceptance criteria per work product; a trust-model template (assets, data flows, trust zones, claims, adversary capabilities, collusions, residuals, invariant ids); the raw Daybreak reports and reproducible probes versioned in the `plan-025-evidence` repo (done 2026-08-25). Charter: `plans/025-0a/README.md`.
- **0B — Substrate/anchor bake-off** against 0A's adversaries and workload (§6), producing the operational-requirements table.
- **0C — Decide:** substrate; anchoring/witness design; repo/process boundaries for the four TCBs; implementation stack/language; final claim vocabulary; local-verification vs. receipt policy (local by default); migration architecture; testing-family acceptance criteria (below).

**Phase 1 — The vertical slice: one codebase, two formally gated maturity states (Sol round-3).** Resolves v2's Phase-1/Phase-2 overlap without letting a spike drift into production by accumulated patches. **One** end-to-end path built on the new structure: one authoritative event flow → one key lifecycle including a rotation and a revocation-with-effect-range (proves the temporal model) → one anchored checkpoint with a real independent witness → one kernel claim → one gate-engine decision atomically bound to its action → one dossier rendering of a scoped claim a human can scrutinise.
- **State 1 — experimental shadow slice.** No production credentials or deployable data; shadowed against production-like history; attacked by Daybreak + an Opus probe-executor; read-performance measured. Purpose: learn and falsify.
- **Promotion gate (State 1 → State 2):** **protocol acceptance for every primitive and format the slice touches** (the §5 crypto-protocol re-audit is a *Phase-1 exit criterion*, not deferred — "Daybreak and Opus did not forge it" is evidence, not proof); removal of all test bypasses and experimental modes, with proof they are absent from the release artifact; threat-model reconciliation against `TRUST-MODEL.md` invariants; regression suite complete for every slice-touching finding (matrix row + test); **a fresh full security review after the last security-affecting hardening change**; signed release artifacts with clean provenance.
- **State 2 — releasable slice.** The proof-of-thesis artifact; the first thing eligible for a profile cutover (§8 gate).

**Phase 2 — Kernel completion.** Remaining claim types (cairn's provenance analysis as claim types/policy modules); bundle/offline path on the kernel; protocol re-audit for *newly introduced* formats and paths only (slice-used ones were accepted in Phase 1); legacy quarantine tooling.

**Phase 3 — Gate engine completion + agent-notes as app.** Review/lifecycle + genesis/release policies on one engine; default-DENY; close open→done and the fail-open class; agent-notes projections rebuilt from governance events; NullSigner removed.

**Phase 4 — Human surface.** dossier = pure function of scoped claims; on_behalf_of impersonation closed; explicit untrusted-metadata rendering.

**Phase 5 — Capability broker + transport (profile-gated).** acb: fail-closed grants, executable *content* identity, retired-SecretID revocation (acb-1 Critical lives here). agent-wake: trigger identity inside the MAC, rotation expiry, replay control. These enter a deployment profile only when that profile enables them.

**Phase 6 — Bootstrap/update root.** Slim agent-suite to signed locks + trusted executable resolution + provisioning + restore verification; delete runtime gate code.

**Migration — a scheduled phase with a named owner, an entry gate (the migration boundary checkpoint design accepted in 0C and the legacy-evidence decision recorded), per-consumer ordering (kernel → gate engine → agent-notes projections → dossier), and exit criteria (legacy writes impossible; compatibility window for published bundles expired on a dated schedule; quarantine converted to rejection).** Interleaved with Phases 2–4 in that order. Activities: inventory historical envelope versions; classify unverifiable legacy history per the 0A decision; dual-read/shadow verification; rebuild projections; **checkpoint the migration boundary**; compatibility window for already-published bundles; rollback constraints; **a point after which legacy *writes* are impossible**, then legacy verification disabled, then quarantine becomes permanent rejection.

**Testing families — mandatory acceptance criteria on the kernel and gate engine (Sol):** temporal-authority state-machine/property tests; parser and proof fuzzing with pre-allocation limits; online/offline differential verification; protocol-downgrade tests; fork, rollback, stale-checkpoint and witness fault injection; policy/version-skew tests; projection-rebuild equivalence tests; plus the existing mutation-tested probe discipline.

**Cutover gate — deployment-profile based (Sol), named invariants, not severity.** A profile (e.g. *provenance + tracking*, without capability release) may cut over when: every `TRUST-MODEL.md` invariant for its **enabled** components holds under the stated adversaries; disabled components are **structurally unreachable** — defined (Sol round-3) as: a **deployment profile is a signed manifest** from which CI derives the enabled code, routes/services/executables, identities, secret/credential bindings, policy grants, dynamic-plugin paths and network edges; a disabled feature has **none** of these deployed and **no invocation edge from any enabled principal**; activation requires a **signed profile transition**; and CI runs **negative reachability tests** under the profile's adversaries against the derived graph — never prose or configuration flags; no unsupported feature is represented as secure; all reproduced Critical/High in enabled components are closed with matrix row + regression test; the migration boundary is checkpointed; the §6 operational runbooks exist. The live estate's 0.6.0 cutover remains **held** until the first profile passes this gate.

**Ceremony per phase:** Sol implements against this plan; Fable reviews/advises; Daybreak re-confirms gate code; **two independent reviewers (one executing probes) + coordinator self-reproduction on the kernel and every gate** (the WI-008 lesson).

---

## 9. Decisions

**Taken (owner, 2026-08-25):** no emergency-containment track (suite not in production; old system must not be used with real credentials or deployable data during the rebuild); substrate by bake-off with operational burden first-class; all design decisions on the table, component shapes malleable; relying party is real (work HIPAA/Windows/on-prem-hybrid environment, not yet built, no time pressure); borrow auditor-accepted paradigms rather than elicit requirements.

**Approved (owner, 2026-08-25):**
- **D1 — Structural pivot (§3). APPROVED.** The logical four-boundary decomposition is the target; repo/process boundaries remain a 0C decision.
- **D2 — Phase-0A go. APPROVED.** Sol drafts the 0A work products; Fable reviews; Daybreak + Opus on reproductions.

**D3 — Compliance validation: mandatory and staged (resolved per Sol round-3; owner to confirm the touchpoints are approachable).** Sol's round-3 finding is that leaving this as "whether/when" contradicts §7's requirement that compliance bless the map; v3.1 therefore makes validation **mandatory before production acceptance** and stages *who* and *when*:
1. **0A — internal draft** of `ADMISSIBILITY-MAP.md` as hypotheses (Fable + Sol), each with its failure mode; plus an **informal, explicitly non-binding read** by the owner's work compliance/security contact if approachable — recorded as a sanity check, never as approval.
2. **0A→0B gate — formal review** of the map by a named risk/compliance/control owner of the target environment, before claim vocabulary or substrate decisions harden. If the environment is not yet defined enough for a ruling, the reviewer's annotations and open questions are recorded and the gate passes *provisionally* with those items carried as 0C inputs.
3. **After Phase-1 State 2 — external HIPAA/IT-audit specialist** evaluates the *artifact* (not the plan): "would this evidence be admissible to you as an auditor?" Positive answer is itself a selling artifact; production acceptance requires it or an equivalent internal audit sign-off.
**Owner decision 2026-08-25 (organisational context: minimise waves at the target organisation for now):** proceed with **stage 1 only** — internal hypothesis draft, plus an informal non-binding read of the one-pager *if and when a low-friction opportunity arises*; no formal ask is made. **Stage 2 (formal review) is deferred**, not cancelled: the 0A→0B gate passes *provisionally* on the internal reading, with the map's open questions carried as explicit 0C inputs and a standing item to convert to a formal review once the target environment and organisation have settled. Stage 3 timing is unchanged (after Phase-1 State 2). Consequence recorded honestly: until stage 2 happens, every admissibility claim in the plan is an *unvalidated engineering hypothesis*, and no production acceptance may rest on it.

**Recommendation (one paragraph):** Start 0A now (D1/D2 approved). Do not ship or deploy the current design. Write the trust model and admissibility map, reproduce the Criticals and representative Highs, and choose the decomposition before any API or repo is frozen; run the time-boxed bake-off with SQL Server Ledger as the environment-fit lead but security unproven; build one sound, witnessed, red-team-resistant vertical slice on the new four-boundary structure and let it — not a to-do list — decide readiness; map all 147 findings to controls and tests; cut over per deployment profile on named invariants. Unhurried, co-designed with the environment it will live in, done right.

---

## Appendix — v2 → v3 delta against Sol's convergence checklist

| Checklist item | v3 |
|---|---|
| Replace "library in regista" with a logical provenance-kernel decision | §3 boundary 1; D1 |
| Component-decomposition/TCB selection as explicit Phase-0 deliverable | §8 0A/0C |
| Split Phase 0 into 0A/0B/0C | §8 |
| Legacy reject/quarantine/re-anchor decided before the first slice | §4, §8 0A |
| Critical/representative-High reproduction + provisional 147-row matrix in the freeze gate | §2, §8 0A |
| Local proof verification default; justify every receipt boundary | §5 |
| Consolidate gate infrastructure, retain policy-specific schemas | §3 boundary 2 |
| agent-wake as non-authoritative transport | §3 |
| acb as separate enforcement TCB | §3 boundary 3 |
| Profile-based cutover, disabled features structurally unreachable | §8 |
| Resolve Phase-1/Phase-2 overlap | §8 Phase 1 (one build, spike hardened in place) |
| Schedule migration; add verification test families | §8 |
| *New in v3 (owner inputs):* relying-party settlement, PHI non-goal, Windows/HIPAA environment tilt, admissibility-by-isomorphism, language/stack question | §1, §3, §6, §7 |
| *v3.1 (Sol round-3 blocking):* protocol re-audit as Phase-1 exit criterion; two-state slice promotion gate; isomorphism = hypotheses + mandatory staged validation; layered PHI boundary; testable "structurally unreachable" | §8 Phase 1, §7, §1, §8 cutover |
| *v3.1 (Sol round-3 non-blocking):* acb executable identity incl. ownership/TOCTOU; bootstrap root owns trust-root provisioning + policy selection, offline posture; dossier mis-render risk retained; differential verifier retained; Ledger as fit hypothesis with premise validation + rubric-first; language decision moved to 0C; "non-repudiable" and "all 147 in C" corrected; independence policy for `IndependentReviewAttestation`; decision-state text reconciled; 0A as four work products + startup inputs; migration owner/entry/order/exit | §3, §6, §1, §7, §9, §8 |
