# 0A-1 TRUST-MODEL.md — reviewer 2 notes (Claude Opus, security-focused, 2026-08-26, on v0.1-draft)

## VERDICT

**rework** — bounded, not foundational.

The twelve-section structure, the asset/flow/zone decomposition, the three-question split and roughly forty of the fifty invariants should survive intact. But three things this document exists to produce are not yet sound: (1) the **§8 adversary columns are internally self-contradictory in at least fourteen rows** — and plan §8 (line 186) makes exactly those columns the cutover gate's input; (2) the **§5 revocation state machine is not well-defined** — its retroactive-effect rule has no fixpoint and no propagation rule, which reintroduces SEC-01 at the model layer; (3) the **§7 claim-by-adversary "matrix" is not a matrix** — every claim leaves 4–8 of the 29 adversaries unclassified and ADV-08 is classified in none of them. Add three genuinely missing invariant families (pinned-input acquisition, submission-inclusion promise, key custody) and the §9 laundering/renewal paths, and this becomes acceptable.

I checked ten-plus citation sets against the inventory: **no fabricated citations, and the citation quality is high** (details in NON-BLOCKING §N9). The problems here are in the model, not the evidence handling.

Where I disagree with reviewer 1: Fable's finding #2 (checkpoint-distribution channel) is not editorial — it is B5 below, and it has an uncited High as direct evidence. Fable's #1 likewise has uncited evidence (an-2). Fable's headline "accept as draft, none blocking" does not survive the §8 column audit or §5.

---

## BLOCKING

### B1 — §8 registry: fourteen invariants list the same adversary in both the "Resists" and "Does not resist" columns

**Location:** lines 161–210. Literal same-id contradictions: INV-013 (line 173), INV-015 (175), INV-017 (177), INV-018 (178), INV-019 (179), INV-021 (181), INV-023 (183), INV-049 (209). Range-implied contradictions: INV-004 (164), INV-011 (171), INV-012 (172), INV-020 (180), INV-022 (182), INV-045 (205), INV-050 (210).

**Defect:** the shorthand `ADV-01..ADV-13` (or `..ADV-14`) is applied mechanically, then the non-resist column excludes members of that same range.

- INV-049 (line 209): resists `ADV-01..ADV-13`, does not resist `ADV-06/08/17/19/25`. **ADV-06 is in both columns.**
- INV-013 (line 173): resists `ADV-01..ADV-13`, does not resist `ADV-06/17, …`. Same.
- INV-019/021/023 (179/181/183): resist `ADV-01..ADV-13(/14)`, do not resist `ADV-04/…`. **ADV-04 is the compromised verifier and these are all verifier-owned invariants.**
- INV-015 (line 175): resists `ADV-01..ADV-14`, does not resist `ADV-05, ADV-16, ADV-23 for that witness`. **ADV-05 is in both.**
- INV-004 (line 164): resists `ADV-01..ADV-13`, does not resist "compromised consuming boundary or its host". The consuming boundaries *are* ADV-04, ADV-06, ADV-07, ADV-09, ADV-10 — all inside the asserted range. Same shape in INV-011 ("enforcing boundary" = ADV-03/06/07/11), INV-012 and INV-020 ("verifier/consumer" = ADV-04), INV-022 ("deciding boundary" = ADV-04/06/07), INV-045 ("parser boundary" = ADV-09/10), INV-050 ("kernel boundary" = ADV-03/04).

That INV-024/025/026/034/039 (lines 184–186, 194, 199) get this exactly right — enumerating `ADV-01..ADV-05, ADV-09..ADV-13` and excluding the owning boundary's own id — proves the range shorthand is the bug, not the intent.

**Why blocking:** plan §8 (line 186) gates cutover on "every `TRUST-MODEL.md` invariant for its **enabled** components holds under the stated adversaries." An invariant whose stated adversaries are contradictory cannot be evaluated at a gate, and 0A-3's `invariant_ids` column inherits the contradiction into all 147 matrix rows.

**Required change:** replace every `ADV-nn..ADV-mm` range with an explicit enumeration; mechanically assert `resists ∩ does-not-resist = ∅` and `resists ∪ does-not-resist = all 29` for every row; express every non-resist as an ADV id (see B14) rather than prose like "compromised consuming boundary".

---

### B2 — §5: the retroactive-revocation rule has no fixpoint, no propagation rule, and does not say whether `S_p` changes

**Location:** lines 77–87 (esp. 83, 85); INV-013 (line 173).

Three distinct defects in one paragraph:

**(a) Mutual revocation has no defined outcome.** Bob at position `r2` issues R2 revoking Alice with `effect_from = 0`. Alice at `r1 > r2` issues R1 revoking Bob with `effect_from = 0`. Both are authorized at acceptance (each against `S_(r−1)`), so both are accepted. Now at cut `c > r1`: R2's range covers `r1`, so Q2(R1) = revoked; R1's range covers `r2`, so Q2(R2) = revoked; if R2 is revoked its effect lapses, un-revoking R1, which re-revokes R2. The document's only guard — "A range cannot alter the validity of the revocation event itself" (line 85) — protects each event from *its own* range, not from the other's. Q2 at cut `c` is therefore not a function of the evidence, contradicting line 83's "A verifier result at cut `c` is a function of the evidence."

**(b) A revocation may destroy the authority derivation of an already-accepted event, including an earlier revocation.** Line 85 protects the revocation *event*; it does not protect the delegation chain that conferred the issuer's revocation authority. R can name `effect_from` earlier than the position of delegation D that granted R's issuer their revocation authority. Q2(D) = revoked ⇒ the issuer never had authority ⇒ R's protection is by fiat over a destroyed basis. This is the exact ambiguity the temporal model was introduced to eliminate.

**(c) Does `S_p` change retroactively?** Line 77 defines `S_p` over "accepted events"; line 85 says revocation "changes Q2 and does not erase … prior verifier knowledge." Read literally, `S_p` is unchanged — which means **a retroactively revoked key's delegations remain in authority state, and every action the delegate took after `p` stays authorized.** That is precisely SEC-01 ("revoked/superseded key mints new action-delegation authority", inventory line 204), the verified High that motivates the whole temporal model, reappearing as a modelling choice. The alternative reading (recompute `S_p` without revoked events) cascades non-monotonically through every downstream delegation and is not described either. INV-013's phrase "deterministic retroactive Q2 effect" (line 173) is therefore not achievable as specified — this invariant is untestable and its TA family cannot be written.

**Required change:** specify the evaluation as a single ordered pass in position order over accepted events; state explicitly and normatively that (i) *acceptance* is immutable and established once against `S_(p-1)`; (ii) whether retroactive Q2 revocation propagates transitively to authority conferred within the effect range — pick one and record the cost; (iii) that an accepted event's authority-derivation chain is exempt from retroactive Q2 effect (or give the termination rule if it is not). Then rewrite INV-013 to state the chosen rule in falsifiable terms.

---

### B3 — §7 is not a claim-by-adversary matrix; ADV-08 is classified by no claim

**Location:** lines 133–140; charter README line 23 ("claim-by-adversary matrix") and line 27 ("every claim names resisting and non-resisting adversaries").

Counting the six rows against the 29 adversaries in §6:

| Claim | resists | non-resists | classified | **unclassified** |
|---|--:|--:|--:|---|
| `IndependentReviewAttestation` | 12 | 13 | 25 | ADV-07, 08, 16, 18 |
| `TamperEvidentChangeRecord` | 13 | 10 | 23 | ADV-06, 07, 08, 17, 18, 20 |
| `AttributableAuthorship` | 12 | 9 | 21 | ADV-06, 07, 08, 16, 17, 18, 20, 27 |
| `TrustedTimestamp` | 12 | 11 | 23 | ADV-06, 07, 08, 17, 18, 20 |
| `CapabilityGrant` | 12 | 12 | 24 | ADV-08, 14, 16, 20 |
| `ExternallyAuthenticatedBundle` | 12 | 11 | 23 | ADV-06, 07, 08, 17, 18, 20 |

**ADV-08 (compromised bootstrap-root component) appears in no cell of any claim** — neither resisted nor non-resisted — even though ADV-19 and ADV-25 (its host root and its operator) appear in all six non-resist lists, and INV-009/035/036/037 (lines 169, 195–197) each name ADV-08 as non-resisted. Since the bootstrap root provisions trust roots and policy (§3 line 57), ADV-08 defeats every claim in the table; its absence is the single most consequential omission in §7.

A second structural defect: **no claim row cites any invariant id.** Line 131 defines "resists" as "the claim remains sound … when all cited invariants hold," but only the common-fields paragraph (line 129) cites anything (INV-019..023). The resists column is therefore unfalsifiable per claim, and 0A-3's rule that "cutover gates and the matrix reference invariants by id only" (README line 25) cannot be satisfied from §7.

**Required change:** make §7 a complete 6×29 matrix with every cell one of resists / does-not-resist / not-applicable-with-reason; add a per-claim `invariant_ids` column.

---

### B4 — Undetectable event censorship by ADV-03 / ADV-12 / ADV-13 / ADV-26, all of which §7 lists as resisted

**Location:** claim rows lines 135–136; INV-005 (line 165), INV-006 (line 166); §2 flow line 33.

**Attack (ADV-03, ADV-12, ADV-13, ADV-26).** A compromised writer (or DB writer, or DBA) accepts a submission — most damagingly a *revocation* event for a reviewer or signer key — returns success to the submitter, and simply never chains it. Every subsequent checkpoint is internally consistent, freshly witnessed, and passes INV-014/015/016/017/018. Q3 reports "complete for the declared scope"; the scope is what the log contains. Q2 for the subject's later actions returns **authorized**, because the revocation is not known at any cut. Nothing in the model ever surfaces the omission, because the *submitter holds no evidence that its event was accepted* — §2 line 33 explicitly says "the writer stores but does not self-attest validity", and no invariant gives the appender an inclusion promise.

**Invariants that should have covered it:** INV-005 claims "no silent duplicate, **deletion**, insertion, or entity-filter suppression"; INV-006 claims an "omitted/unverified count". Neither can detect the omission of something the log never admitted. Consistency proofs prove append-only extension, not that any particular submission was included.

This directly falsifies `IndependentReviewAttestation` resisting ADV-03/ADV-12/ADV-13/ADV-26 (line 135) and `TamperEvidentChangeRecord` resisting ADV-12/ADV-13/ADV-26 (line 136). Plan §6 line 131 already names the mechanism — "omission before anchor" — and the trust model does not carry it forward.

**Required change:** add an invariant (FW + TA) requiring a signed append acknowledgement binding submission digest, promised position and a **maximum merge delay**, plus a submitter duty to verify inclusion within that delay and a defined failure action; state the residual that censorship of a *never-acknowledged* submission remains undetectable. Then requalify the four claims' resists entries. Add a companion residual in §12 — there is currently no residual for selective censorship at all (§12 line 253 covers forks, line 259 covers availability; neither is this).

---

### B5 — No invariant governs how a verifier acquires its pinned inputs (trust root, expected cut, witness roster)

**Location:** §3 line 53 (verifier "may never be trusted for choosing trust roots/cuts from request data"); §5 line 79 (`S_0` "separately authenticated genesis state"); INV-009 (line 169); INV-017 (line 177, "locally retained/pinned prior cuts"); plan §5 line 119 ("`trust_root` and `at_cut` derive from pinned project policy, never from request data").

Three load-bearing guarantees state that pinned inputs exist. **No invariant establishes how they are obtained, by whom, or against which adversaries.** INV-036 (line 196) covers provisioning *of a deployment we control* from signed bootstrap inputs; it does not cover a relying party's first contact. INV-017 presupposes a retained prior cut; a first-contact verifier has none. INV-009 says genesis is "admitted once" — but a genesis fork produces two logs each with exactly one genesis, so "once" is not a detectable property without an out-of-band pin.

**Attack (ADV-03 + ADV-13, i.e. ADV-26 — listed as resisted by five of six claims).** Present a fresh verifier with a complete, self-consistent alternative history: its own genesis, its own root, its own checkpoint chain, and a witness roster it selects. Everything verifies. **The evidence for this is already in the inventory and uncited by any invariant:** cairn-06 (High) — "Witness coverage roster is attacker-controlled; pinned keys don't establish expected roster" (inventory line 179).

**Why this is the sharpest gap in the document:** plan §1 line 17 says the relying party is a security function that "will red-team the claims exactly as Daybreak did." That relying party is, by construction, a first-contact verifier with nothing retained. The model's strongest protections (INV-017's rollback rejection, INV-009's genesis uniqueness) are the ones that do not apply to them.

**Required change:** add an invariant (PV + FW) covering initial pin acquisition and pin update — who publishes the root/genesis/witness-roster digest, over what independent channel, how a client detects equivocation between the pin channel and the log, and what a first-contact verifier may conclude with no retained state — with its own resists/does-not-resist columns. This subsumes and upgrades reviewer 1's finding #2 from editorial to blocking.

---

### B6 — ADV-09 is listed as resisted by all six claims, but agent-notes signs governance events and INV-039 explicitly does not resist ADV-09; there is no key-custody invariant anywhere

**Location:** §7 lines 135–140 (all six rows list ADV-09 under Resists); INV-039 line 199 (does not resist `ADV-06/09/…`); §1 line 19 ("under stated custody assumptions"); §12 line 251.

**Attack (ADV-09, compromised agent-notes).** §6 line 91 grants an adversary "its ordinary process credentials," and agent-notes is where lifecycle/review events are composed and **signed** — that is the direct subject of an-5, an-6 ("native ops default to NullSigner"), an-9 ("outbox signature carries no project identity"). So ADV-09 is a signing-key holder for governance events. It can (i) present subject X to the reviewing agent and submit a review event binding digest(Y); (ii) sign lifecycle transitions directly. `IndependentReviewAttestation` and `AttributableAuthorship` cannot resist that. INV-041 (line 201) supplies the equivalent protection on the *human* path — "human approval binds the exact rendered subject digest" — and correctly does not resist ADV-10/ADV-20. There is no analogue for the *agent* review path, which is the product's differentiator.

**The root cause is broader:** §1 line 19 makes key custody an asset property "under stated custody assumptions" and **those assumptions are never stated anywhere in the document.** No invariant assigns which zone may hold which key material. Yet the entire §7 resists column depends on it — the same gap makes `TamperEvidentChangeRecord`'s "ADV-14 if signer key is on writer host" (line 137, in AttributableAuthorship) a conditional the model cannot evaluate.

**Required change:** add a key-custody invariant (owning boundary: bootstrap root; families PV, MP) fixing, per key class (event-signing, checkpoint, witness, receipt, transport, release, bootstrap root), which zone may hold it, whether it must be non-exportable/HSM-backed, and purpose separation — then re-derive the §7 resists columns from it. Remove ADV-09 from the resists column of `IndependentReviewAttestation` and `AttributableAuthorship`, or add an invariant that governance-event signing keys are unavailable to the app process.

---

### B7 — §9 authority cache: the TTL bounds the wrong quantity, is renewable, and the row contradicts itself

**Location:** lines 214, 218; INV-011 (line 171).

Line 218 permits a new authority-bearing write/gate action/capability release from cache "when its key exactly matches evidence digest, trust-root digest, authority-policy version, **and cut**, and its age is within `AUTHORITY_CACHE_TTL`", then asserts "**No stale cache extends permission-now**". The rule and the assertion are inconsistent: a cache entry is by definition state older than now, and the rule authorizes new actions from it.

Two concrete abuses:

1. **The TTL bounds cache-entry age, not cut age.** With `CHECKPOINT_MAX_AGE` at its 60-minute hard maximum (line 214), a cut may be 59 minutes old while a cache entry derived from it is 1 minute old and thus "fresh". The binding constraint on permission-now staleness is therefore 60 minutes, not the 15-minute `AUTHORITY_CACHE_TTL` hard maximum the reader is led to believe.
2. **The entry is trivially renewable.** The cache key is `(evidence digest, root digest, policy version, cut)` — all four are retained locally. Nothing forbids re-deriving an identical entry from the same retained evidence the instant the old one expires. A 5-minute TTL over re-derivable inputs is not a bound at all.

**Consequence:** a rotated, superseded or revoked credential retains permission-now for up to an hour by design. That is C2 — the class INV-011 exists to close, citing SEC-01, SEC-03, crypto-2, aw-4, aw-9, acb-12 (line 171). The document never states this window as a residual (§12 has no bullet for revocation-propagation latency).

**Required change:** define cache-entry age from the **witnessed observation time of the cut**, not from entry creation; forbid re-derivation from extending the window (bind the entry to a first-authentication timestamp); collapse the two parameters into one stated maximum permission-now staleness; require a per-action criticality floor (revocation-sensitive actions demand a cut newer than the revocation-publication bound); and add the revocation-propagation-latency residual to §12.

---

### B8 — §9 break-glass: indefinitely renewable, can roll back policy, and its offline record has no non-equivocation property

**Location:** lines 225, 227; INV-049 (line 209).

**(a) The 60-minute cap is per-invocation, not per-incident.** Line 225 sets "expiry no greater than 60 minutes". Nothing forbids the same two operators issuing a fresh emergency-policy event at minute 59, indefinitely. There is no cumulative cap, no cooldown, no requirement that an extension use a different approver, no maximum count. This does not even require collusion — it requires the same two people the design already assumes, so INV-049's non-resist "both emergency approvers colluding" does not cover it.

**(b) "Restore pinned configuration" (line 227) is a policy-rollback primitive.** Break-glass is delivered as "an offline signed emergency-policy event"; INV-036 accepts signed pinned bootstrap inputs. Restoring an *older* signed configuration can reinstate a smaller witness quorum, an earlier trust root containing a since-revoked key, or a weaker authority policy. Line 227's prose forbids "reduce witness quorum" — **no invariant enforces it, and no monotonicity requirement on policy versions exists anywhere in the document.**

**(c) The offline emergency record is not tamper-evident against its own issuers.** Line 227: if the kernel cannot append, "the independently signed emergency record is held by both operators and must be the first reconciled event after recovery." Two operators can produce N such records, present one and destroy the others; there is no per-incident monotonic counter, no predecessor binding, no pre-issued position reservation. The one path in the system that legitimately bypasses the log has none of the log's non-equivocation properties.

**(d) The exclusion list is under-specified.** Line 225 excludes the requester, the signer of the affected action, the DBA, the verifier operator and the *sole* witness operator — so an operator of one witness out of three qualifies as the second approver, and ADV-19 (bootstrap-zone host root) is not excluded at all.

**Required change:** cumulative per-incident cap with mandatory escalation to a different approver set for any extension, expressed as a counter INV-049's TA family can falsify; an explicit policy-version monotonicity invariant (no signed input may lower witness quorum, retire-list coverage or algorithm floor without a distinct non-emergency ceremony); a chained/pre-numbered emergency-record format; tighten the exclusion list.

---

### B9 — §9: "provisional local capture" is laundered into tamper-evident history by the ordinary recovery procedure

**Location:** line 219 ("Anchor unavailable"); §7 `TamperEvidentChangeRecord` (line 136).

Line 219 permits the writer to "retain explicitly provisional local capture" and forbids representing it as tamper-evident. Recovery is: "Publish pending checkpoint(s); verify consistency from the last externally accepted cut; obtain witness quorum; reissue claims at the recovered cut."

**Attack (ADV-03, ADV-13, ADV-26).** During the outage there is no external observer, so the writer/DBA composes the pending range at will — content, ordering, timestamps. At recovery it publishes a checkpoint consistent with the last externally accepted cut. Consistency proves append-only extension from the old root; it proves **nothing about when, or in what order, the appended entries were actually created.** Witnesses endorse the recovered cut. From that moment the once-provisional entries carry inclusion proofs under a witnessed checkpoint and are byte-indistinguishable from continuously anchored history.

**The "provisional" label is never committed into the chain.** §7's common fields carry "warnings/degraded/legacy flags" per claim at issuance; a claim issued later at the recovered cut carries no warning, because nothing in the log records which positions were captured unanchored. INV-018 (line 178) blocks a *fresh positive Q3 during* the outage — it says nothing about Q3 *after* recovery over the same range.

**Required change:** recovery must append a signed unanchored-range marker binding `[last_anchored_position, first_reanchored_position]`, the outage duration, and the degraded-entry event id, and this must be part of the chain, not an operational note. Any Q3 result or claim whose range intersects an unanchored window must permanently disclose it. Make the maximum unanchored window a signed policy parameter with a hard maximum, alongside `CHECKPOINT_MAX_AGE`. Add the corresponding residual to §12.

---

### B10 — Critical `persist-5` / verified `SEC-09` has no invariant, and none of the eight mandatory test families can catch a race

**Location:** §8 test-family list (lines 146–155); charter README line 25 ("no invariant without a named test family").

I checked every finding id cited anywhere in the document against the inventory. **`persist-5` is the only one of the seven Criticals cited by no invariant**, and its verified twin `SEC-09` is likewise uncited. Both are the same defect: `commit()` locks the row but decides on a cached `APPROVED`, finalizing a cancelled lifecycle operation (inventory lines 288, 300, 356–358). Its relatives persist-6 and persist-10 are also uncited.

INV-027 (line 187) is the nearest fit — "commit atomically or through a fail-closed, replay-safe protocol" — but it is owned by "gate engine + action owner" and cites nothing; the defect is inside the kernel's principal-lifecycle path. More seriously, **the eight mandatory families (TA, PF, DO, DG, FW, PV, PR, MP) contain no concurrency, race or TOCTOU family**, while the inventory holds ten-plus TOCTOU findings including a Critical (persist-5), a verified finding (SEC-09), and cli-9, cli-10, as-15, acb-13, acb-14, aw-8, persist-6. `MP` is a discipline for probes, not a family that exercises interleavings.

**Required change:** add an invariant for authority-affecting state transitions (expected-state predicates, no decision on cached state across a lock boundary, no check/use gap) citing SEC-09, persist-5/6/10, and add a concurrency/TOCTOU test family. Note that adding a family requires reconciling with plan §8 line 184, which enumerates the mandatory families — flag this for the plan, not just for 0A-1. Without it, 0A-3 cannot give persist-5 a `fully-closed-by-kernel` disposition with an `INV-` id.

---

### B11 — §11/§12: append-only witnessed history versus HIPAA deletion is never stated, and INV-048 promises a deletion that is structurally impossible

**Location:** INV-048 (line 208); §11 element 4 (line 244); §12 lines 260–261.

INV-048 promises "authorized deletion from ordinary projections/store where legally permitted." §11 element 4 promises "legally authorized deletion, backups/caches/downstream copies, and audited disposition."

**If PHI arrives inside an accepted event field** — §11 element 1 admits "small approved textual governance metadata" — it is canonicalized, signed, chained by predecessor digest, committed into a checkpoint, and witnessed externally by parties outside the operator's control. Deleting it either breaks the chain or is impossible. Deleting it from projections leaves it in the log; deleting it from the log destroys the product. Witnesses retain checkpoints that commit to it regardless.

§12 line 260 says quarantine "cannot undo prior PHI disclosure or guarantee removal from every backup" — that is a much weaker statement than the truth, which is that **the kernel's core property makes deletion of admitted event content structurally impossible, by design, forever.** For a HIPAA-regulated relying party whose security function will red-team these claims (plan §1 line 17), that is the most consequential residual in the document and it is absent. It also directly undercuts plan §1 line 37's framing that the data boundary keeps the provenance store from becoming "a compliance liability."

**Required change:** state the residual plainly in §12 and §11 element 5. Then close it architecturally: require that any admitted free-text/metadata field be **redactable by construction** — the event commits to a salted per-field digest, with the plaintext held in a separately deletable side store — so that deletion is possible without breaking the chain. Alternatively forbid free text in the allowed-content schema entirely. Either way this is a 0A-1 decision that constrains the 0A-4 schema, not a 0A-4 detail. Correct INV-048's statement to match whichever is chosen.

---

### B12 — Five of six claims resist ADV-05 and ADV-23 unconditionally, but there is no minimum witness quorum; and `TrustedTimestamp`'s must-not-issue rule has no invariant

**Location:** §7 lines 135–140; INV-016 (line 176); §9 line 214.

`TrustedTimestamp` (line 138) correctly qualifies: "ADV-05 **if required time quorum is one**". The other five claims list ADV-05 and ADV-23 as resisted with no such qualifier — yet their resistance rests on exactly the same condition. **Nothing in the document sets a minimum witness quorum ≥ 2.** INV-016 says "one witness/operator cannot satisfy a multi-witness quorum," which is vacuous when the signed policy sets quorum = 1: a quorum of one is satisfied by one witness, and INV-016 holds. §9 line 214 lists witness quorum as an `ASSUMPTION`/`OPEN` value with no floor.

**Attack (ADV-05 or ADV-23 or ADV-16, all listed as resisted).** Deploy under a profile whose signed policy sets quorum = 1 — the operationally obvious first configuration, and exactly what plan §6 line 139 warns adopters will do when the burden is high. Every claim's resistance to ADV-05/ADV-16/ADV-23 evaporates while INV-016 still "holds."

Separately, line 138 states "absent an accepted TSA/time policy this claim must not issue" — a hard prohibition with **no invariant**. Since §12 line 258 says no accepted TSA is selected yet, `TrustedTimestamp` is currently un-issuable and nothing enforces that.

**Required change:** set a normative minimum quorum (≥ 2 with a stated independence criterion, see N4) or propagate the "if quorum is one" qualifier to all five remaining claims; add an invariant that a claim type whose prerequisite policy (accepted TSA, witness set, receipt policy) is unselected must not issue, fail-closed, with a DG/PV family.

---

### B13 — §6 catalogue is missing the adversaries that own the target environment's identity and secret planes

**Location:** §6 lines 93–124; INV-033 (line 193), INV-031/032 (191–192), INV-035/036/037 (195–197).

Four entities appear as non-resist entries in §8 **with no ADV id**, so no claim in §7 can name them: "secret-backend admin" (INV-033), "OS/kernel compromise" (INV-031, INV-032), "release-signing quorum compromise" (INV-035/036/037), "both emergency approvers colluding" (INV-049). Prose non-resists are untraceable through 0A-3 and unusable at the cutover gate.

Worse, one major adversary is absent entirely: **the directory / identity-provider administrator.** The target is an almost-entirely-Windows, AD-based environment (plan §1 line 17). `IndependentReviewAttestation` binds "authenticated human identity; role and **organizational authority**; conflict/independence declarations" (line 135) and INV-028 (line 188) requires "authenticated distinct principals, roles, organizational authority, conflicts". None of that lives in the kernel — it comes from the directory. A directory admin can grant an attacker-controlled principal the organizational authority and conflict-free status that makes a review "independent," then let it review legitimately. dossier-12 (session authoritative after revocation, inventory line 211) and WI-055's three incompatible `principal_id` conventions are the same seam. The `AttributableAuthorship` residual (§12 line 251) covers key theft, not directory-mediated identity binding.

Note also that ADV-24 is qualified only as "when reviewer key is held" for `IndependentReviewAttestation` (line 135), whereas `CapabilityGrant` correctly writes "ADV-24 **when grant-authority key is held**" (line 139). The role-granting key is a distinct and more powerful position than the reviewer key: holding it mints reviewers.

**Required change:** add ADV ids for directory/IdP administrator, secret-backend administrator, OS/platform (kernel) compromise, and release/root signing-quorum compromise; convert all prose non-resists in §8 to ids; requalify ADV-24 in the `IndependentReviewAttestation` row to cover the role-granting key.

---

### B14 — Process: the second review is same-lineage, which the charter forbids for this specific work product

**Location:** charter README line 15 ("Second reviewer on anything that becomes a gate: **a third lineage** (deepseek/glm/kimi…); the WI-008 two-reviewer rule applies to **0A-1's invariant registry**"); REVIEW-0A1-fable.md lines 25–26 ("reviewer 2 to be anthropic Opus … Two lineages in the loop").

Drafter: GPT-5.6 Sol (OpenAI). Reviewer 1: Claude Fable (Anthropic). Reviewer 2: me, Claude Opus (Anthropic). Charter line 17's weaker rule ("no work product is accepted on the drafter's lineage alone") is satisfied; **charter line 15's specific rule for the invariant registry is not.** Fable's lineage note asserts sufficiency against the charter's own text.

The irony is load-bearing rather than decorative: this document's INV-028 (line 188) and §12 line 263 both state that "lineage difference alone does not satisfy independence." Accepting 0A-1 on a two-lineage pass would be the first application of the standard the document itself rejects — and `IndependentReviewAttestation` is the product's differentiator (plan §7 line 151).

**Required change:** route the revised draft to a third lineage before owner sign-off, or obtain an explicit owner waiver recorded against charter line 15. My review does not close criterion 6.

---

## NON-BLOCKING

**N1 — INV-017 and INV-018 are near-duplicates** (lines 177–178). INV-018 is INV-017's stale/unavailable case plus a freshness clause; their resists and non-resists columns are nearly identical and both are FW/MP. Merge, or make INV-018 strictly about the *positive-result-suppression* obligation.

**N2 — INV-006 and INV-021 state one guarantee at two layers** (lines 166, 181): explicit scope with counts (kernel) vs. no implied estate-wide completeness (verifier). Keep both only if the owning boundaries genuinely differ in enforcement; otherwise INV-021 is a consumer-facing restatement.

**N3 — INV-046/047/048 put content classes, not adversary ids, in the Resists column** (lines 206–208): "accidental/plain detectable PHI from ADV-01/02/09/10", "ordinary accidental exposure and silent mishandling". These are column-type violations that break the registry's uniform schema and are unusable by 0A-3. INV-046 in particular resists *no adversary* — an adversary by definition obfuscates.

**N4 — INV-016's "independent failure domains" is untestable as written** (line 176). No criterion is given: different operator? different organization? different key custody? different cloud region? different from the DBA's authentication realm? FW/PV cannot falsify it. Give an operational predicate. (Related to B12.)

**N5 — INV-048 and INV-041's test families do not fit their statements.** INV-048 is an incident *process* (notification, escalation, legal-hold handling) assigned PR/MP; projection-rebuild equivalence cannot test a notification path. INV-031/032/033's TOCTOU and loader-injection content is assigned MP only. See B10.

**N6 — Checkpoint-signing authority during writer key rotation is unspecified.** §5 (line 79) says an event is authorized against `S_(p-1)`; a checkpoint covering position `p` is signed by the writer key whose authority lives in `S_p`. Which state authorizes a checkpoint that spans a rotation? INV-014 (line 174) does not say.

**N7 — ADV-10 (compromised dossier) is listed as resisted by five claims** (lines 136–140) while INV-040 (line 200) explicitly does not resist "ADV-10/20 for human deception." Both can be true only if the claims' resistance is scoped to machine consumers. Say so in the resists column; dossier is the human-facing surface for every one of these claims.

**N8 — Reviewer 1's finding #1 (version floor) has uncited evidence.** an-2 — "lineage registry validation fails open (`registry_families()` → `None`) under pinned regista 0.5.5" (inventory line 271) — is the exact mechanism, and it is currently cited under INV-029 (line 189) where it does not belong (INV-029 is about transition exemptions). Moving an-2 to a new version-floor invariant would both fix the mis-citation and give Fable's #1 its evidence. Same row: an-10 ("`attest-gate` no operator authz") is an authorization gap better owned by INV-024/INV-028 than by INV-029.

**N9 — Citation audit (ten-plus sets checked against the inventory).** No citation in the document names a finding that does not exist in the inventory. Verified sound: **INV-002** (SEC-02 ✓ no id/seq/predecessor/nonce; SEC-13 ✓ unbound `signer_id`; persist-3 ✓ `(entity_kind, entity_id)`; an-9 ✓ no project identity) — exact four-for-four against the invariant's own field list. **INV-004** (SEC-08, SEC-11, persist-1/2/4, dossier-2/4, an-8, aw-7, acb-1) — reproduces the inventory's own SEC-11 collision set (inventory lines 405–408) precisely. **INV-005** (persist-9 ✓ validly signed fork; cairn-01 ✓ — "entity-filter suppression" is literally cairn-01's mechanism). **INV-006** (cairn-02 ✓ `total==ok`; cairn-09 ✓ silent 10k truncation; cli-7 ✓ truncated prefix → VALID) — three distinct sub-mechanisms of one statement, all correct. **INV-009** (SEC-05 ✓ bare `gate_passed=True`; as-13 ✓ unconsumed verdict; persist-13 ✓ genesis visibility window) — matches inventory dedup line 417. **INV-010** (SEC-04, SEC-07, cairn-03, cairn-11 ✓ — cairn-11's lexicographic `-05:00` compare is exactly caller-timestamp-as-authority). **INV-011** (SEC-01, SEC-03, crypto-2, aw-4, aw-9, acb-12) — the complete C2 set, inventory lines 106–112. **INV-042** (aw-1/2/3/5/6/7/8/10/11/12/13/14) — all twelve verified individually; correctly omits aw-4/aw-9, which sit at INV-011. **INV-001** (crypto-3 ✓ raw Ed25519 signing oracle; crypto-1 ✓ though better placed at INV-003, where it is also cited).

Four weak or mis-directed citations:
- **SEC-10 at INV-022** (line 182): SEC-10 is permissive-by-default approval, whose home is INV-028 (line 188, where it is also cited). Defensible only under the "absent verifier ⇒ PASS" reading.
- **acb-9 at INV-031** (line 191): acb-9 is registry-artifact trust without content pinning — a supply-chain defect that exec-time digest/owner/symlink resolution does not close. Belongs at INV-035.
- **dossier-14 at INV-041** (line 201): a config loader checking only `S_IWOTH` has nothing to do with binding human approval to a rendered subject. Belongs at INV-036.
- **crypto-4 and as-5 at INV-033** (line 193): both are *signing private keys* in argv/diagnostics (regista, agent-suite); INV-033's subject is broker-released credentials, owner "capability broker + secret backend". Neither finding is in the broker's boundary. This is the missing key-custody invariant (B6) showing up as a mis-assignment.

**N10 — 47 of the 147 findings are cited by no invariant**, including 1 Critical (persist-5), 1 verified finding (SEC-09), and roughly thirteen Highs: cli-1, cli-2, cli-3, persist-6, persist-8, cairn-05, cairn-06, cairn-08, cairn-13, cairn-15, as-9, an-5, acb-10. 0A-1 is not required to cite all 147 — that is 0A-3 — but two of these are load-bearing for findings above: **cairn-06** is the evidence for B5, and **persist-5** is B10. Worth a coverage sweep before 0A-3 starts, since a High with no invariant home tends to become a matrix row with no owner (README line 45 forbids that).

**N11 — `CapabilityGrant` resists ADV-01, but harness membership is explicitly not supplied by the kernel** (§12 line 257). INV-030 (line 190) requires "independently authenticated caller/harness membership at execution time"; §12 delegates that to platform controls with no invariant. On a shared service account — which as-11 shows is the estate's actual pattern ("one `suite-service` signing key across every host project") — an ordinary local user is same-UID with the harness, the aw-5 mechanism. Either name the platform precondition as an assumption in §7's row or qualify the ADV-01 resist.

**N12 — §12 line 254 understates bootstrap-root compromise.** "It cannot make old independently retained checkpoints disappear" is true only for parties who already retained them. A first-contact relying party — the auditor, i.e. the entire market — has retained nothing, so ADV-25 fully controls what they see. Restate the residual with that scope. (Same root as B5.)

**N13 — §5 does not define the verifier's behaviour under a detected fork.** §9 line 219 routes forks to "incident state, not automatic repair" — an operational answer to a semantic question. Which branch is `S_p` computed on? What happens to claims already issued at a cut on the losing branch? INV-012 (line 172) invalidates results only when "a later accepted authority/policy event can affect it," and a fork is not an authority event. Define fork as a terminal verification state with a defined effect on previously issued claims.

**N14 — Reviewer 1's finding #3 (break-glass two-person burden) is right to defer to 0B, but B8 changes the input:** the operational-requirements table should cost a two-person rule *with mandatory approver rotation for extensions*, which is materially heavier than what §9 currently describes.

---

## Charter acceptance criteria (README lines 25, 27)

| # | Criterion | Status |
|---|---|---|
| 1 | Every adversary in plan §4 has an entry | **met** — all ten plan-§4 categories present, expanded to 29 ids with collusions (§6 lines 93–124). Coverage gaps identified in B13 are beyond what plan §4 enumerates. |
| 2 | Every claim names resisting **and** non-resisting adversaries | **not met** — every claim leaves 4–8 of 29 adversaries unclassified; ADV-08 is classified by none; no claim cites invariant ids, so "resists" is unfalsifiable per line 131's own definition (**B3**). |
| 3 | Invariant registry: stable id · statement · **resists / does-not-resist** · owning boundary · test family | **not met** — ids, statements, boundaries and families are present for all 50, but ≥14 rows are self-contradictory across the two adversary columns (**B1**) and several non-resists are prose rather than ids (**B13**, **N3**). |
| 4 | No invariant without a named test family | **met (literal), defective** — all 50 name a family; several families cannot test their statement (**N5**) and no family covers the TOCTOU/race class that holds a Critical (**B10**). |
| 5 | Legacy decision recorded | **partially met** — §10 (lines 231–235) records a well-reasoned *recommendation* of quarantine-as-unverifiable, correctly marked `OPEN — OWNER DECISION REQUIRED`. That is the right drafter posture, but the criterion asks for the decision; it remains the owner's and is unmade. |
| 6 | PHI section covers all five elements | **met** — §11 elements 1–5 (lines 241–245) map cleanly onto plan §1 line 37 (i)–(v). Substantively defective on deletion vs. immutability (**B11**), but the five elements are present. |
| 7 | Two-reviewer pass (Sol draft → Fable → **third lineage**) | **not met** — reviewer 2 is the same lineage as reviewer 1; charter line 15 requires a third lineage specifically for the invariant registry (**B14**). |
| 8 | Owner sign-off | **not met** — pending; also gated on the seven `OPEN:` items the draft correctly flags (lines 87, 214, 225, 231, 241, 244, and §12 line 265). |

**Template conformance (README lines 67–87):** all twelve sections present and in order; assets, data flows, seven trust zones plus transport, Q1/Q2/Q3, temporal semantics, adversaries with collusions, claims, invariants, degraded state, legacy, data boundary, residuals. The scope discipline (`ASSUMPTION:` / `OPEN:` markers, explicit refusal to pre-decide 0B/0C questions, §12's honesty about the 134 unreproduced findings at line 264) is better than the charter asked for and should be preserved verbatim through the rework.
