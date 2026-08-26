# 0A-1 TRUST-MODEL.md v0.2 — reviewer 3 notes (minimax-m3 via ollama-cloud, third lineage, 2026-08-25)

_Verdict: accept-with-changes. Full transcript (154 KB incl. hand walkthroughs) in plan-025-evidence repo; this file is the closure tables, verdict, new findings, and criteria._

## Closure table for B1–B13 (the 14 blocking items from Opus v0.1 review)

Line citations are to v0.2 `plans/025-0a/TRUST-MODEL.md`.

| # | Opus's v0.1 blocking finding | Status in v0.2 | Citation |
|---|---|---|---|
| **B1** | 14 invariants had same-id in Resists and Does-not-resist columns | **CLOSED** | §8 self-check at L217 asserts disjointness over the full 34-id set; spot-checks across INV-001/002/005/013/016/049/053/055/058 confirm disjointness and partition. |
| **B2** | §5 retroactive-revocation rule has no fixpoint, no propagation rule, no answer on `S_p` | **CLOSED** | §5 L73–89 supplies one ordered pass, immutable acceptance (L76), the Step 3 exemption as the termination rule (L77, L83), the chosen retroactivity rule (L83), and the mutual-revocation result (L85). Fixpoint established (see §5 walk-through below); `S_p` recomputed at cut `c` with retroactive Q2 propagation (L79). Sub-delegations *after* the original grant are not crisply addressed — see New NB-3. |
| **B3** | §7 not a matrix; ADV-08 unclassified; no invariant_ids per claim | **CLOSED** | §7 L138–145 is a literal 6×34 matrix; every cell is R/D/R*; ADV-08 is D in all six rows (verified); each row's invariant_ids column names 13–18 INV- ids. **But:** one residual cell-semantics problem remains — see New NB-1. |
| **B4** | Undetectable event censorship by ADV-03/12/13/26 | **CLOSED (one cell-omission nit)** | INV-051 (L207) added: signed ack, submitter duty, ack-publication to independent channel, failure action, never-acked residual; §12 L275 states the censorship residual. `IndependentReviewAttestation`, `TamperEvidentChangeRecord`, `AttributableAuthorship`, `TrustedTimestamp`, `ExternallyAuthenticatedBundle` cite INV-051 — but **`CapabilityGrant` (L144) does not cite INV-051**, leaving a row that resists writer censorship without owning the acked-submission invariant. See New NB-2. |
| **B5** | No invariant for verifier pin acquisition | **CLOSED** | INV-052 (L208) defines root/genesis/witness-roster pin publication, update path, and first-contact limits ("may verify internal consistency only and must not issue trusted Q2/Q3/claims"). Cited by all six claim rows. §12 L274 sharpened the first-contact residual. |
| **B6** | ADV-09 listed as resisted but no key-custody invariant | **CLOSED architecturally; §7 cell semantics still sloppy (see New NB-1)** | INV-053 (L209) added with per-key-class HSM/non-exportable/purpose-separation constraints. Re-derived `CapabilityGrant` cell for ADV-09 = R. `IndependentReviewAttestation` and `AttributableAuthorship` cells for ADV-09 = D — defensible if "the claim alone" doesn't resist, but reads inconsistently with INV-053 cited in the same row. |
| **B7** | §9 cache TTL bounds wrong quantity, renewable, contradicts itself | **CLOSED** | §9 L240 binds cache age to `decision_time − earliest_required_witness_observation_time(cut)`, forbids re-derivation extension, sets per-action criticality floors, and binds revocation-sensitive actions to a stricter floor than the global max. §12 L279 states the bounded-latency residual. |
| **B8** | §9 break-glass indefinitely renewable; offline record has no non-equivocation; can roll back policy | **CLOSED** | §9 L251 specifies cumulative per-incident cap, no same-set renewal, different pre-authorized approver set for extensions, pre-numbered/predecessor-chained records; L249 expanded exclusions to include ADV-19 bootstrap-host, ADV-30 IdP, ADV-31 secret-backend; L251 forbids reducing INV-055 floors. INV-055 (L211) supplies the monotonicity invariant. |
| **B9** | "Provisional local capture" laundered into tamper-evident history | **CLOSED** | INV-058 (L214) requires chain-committed marker binding last anchored/first reanchored, range, outage/observation times, degraded-entry id, policy, reconciliation evidence; permanent `unanchored=true` on intersecting Q3/claims; signed-policy hard maximum. §12 L280 states the residual honestly. The marker integrity depends on writer honesty (INV-058 does-not-resist ADV-03/13/26) — acknowledged in the resistance list. |
| **B10** | Critical persist-5 / SEC-09 has no invariant; no concurrency test family | **CLOSED** | Plan §8 L184 adds CT family. INV-054 (L210) covers expected-state predicates, no decision on cached state across lock, no check/use gap; motivated by SEC-09, persist-5/6/10. CT assigned to INV-026/027/031/032/033/049/051/054. |
| **B11** | Append-only witnessed history vs. HIPAA deletion never stated; INV-048 promises structurally impossible deletion | **CLOSED** | §11 element 5 (L267), INV-048 (L204), §12 L283 all state structural non-deletion; recommendation (a) forbid free text; alternative (b) redactable-by-construction. But §11 element 5 still has an internal conflict with INV-046/048 — see New NB-6. |
| **B12** | Five claims resist ADV-05/23 unconditionally with no minimum quorum; `TrustedTimestamp` must-not-issue rule has no invariant | **CLOSED** | INV-016 (L172) sets normative quorum ≥ 2 with an operational independence predicate (distinct operator/key-custody/admin/host/persistence plane). INV-056 (L212) fail-closed prerequisite including TSA, witness roster, receipt, review-independence policy. |
| **B13** | §6 catalogue missing adversaries that own identity and secret planes | **CLOSED** | ADV-30–ADV-34 added (L128–132): directory/IdP admin, secret-backend admin, OS/kernel, release/root signing quorum, emergency approver collusion. ADV-24 (L122) generalized to include role-granting and grant-authority keys. INV-052/053/055/058 non-resist lists cite the new IDs. |
| **B14** | Same-lineage review for the invariant registry; charter line 15 requires a third lineage | **OPEN by design** | L3 + L308 explicitly defer to third-lineage review. This review (minimax-m3, OpenAI family of mvmcc03, third lineage from Sol/Fable/Opus) is the artifact the document is awaiting. The gate transition is not being recorded by this reviewer. |

B1–B13 are substantively closed. B14 is correctly deferred to this review.

## Closure table for N1–N13 (the 13 non-blocking items from Opus; N14 is a 0B note)

| # | Opus's non-blocking finding | Status | Citation |
|---|---|---|---|
| **N1** | INV-017 and INV-018 near-duplicates | **CLOSED** | L173 (fork/rollback detection) and L174 (positive-Q3 suppression/recovery) now state different guarantees. |
| **N2** | INV-006 and INV-021 state one guarantee at two layers | **CLOSED** | L162 (kernel scope/counts) and L177 (consumer non-overclaim) now clearly distinct layers with different owners. |
| **N3** | INV-046/047/048 put content classes in Resists | **CLOSED** | INV-046/047/048 all use ADV-ids in Resists. |
| **N4** | INV-016 "independent failure domains" untestable | **CLOSED** | L172 now states five distinct predicates (operator, key/custody, admin account, host, persistence plane) plus a negative predicate (no writer/DBA admin realm sharing). |
| **N5** | Test-family fit for INV-048 and INV-031/032/033 | **CLOSED** | INV-048 now PR/CT/MP; INV-041 PV/DG/MP; INV-031/032/033 have CT. |
| **N6** | Checkpoint key rotation unspecified | **CLOSED** | §5 L87: checkpoint authorized by writer key effective after last covered position; rotation overlap explicit, position-bounded; INV-014 enforces. |
| **N7** | ADV-10 dossier resistance scope | **CLOSED** | L136 + R* cells for ADV-10 in five rows; L277 residual. |
| **N8** | Version-floor uncited evidence (an-2, an-10) | **CLOSED** | INV-057 (L213) motivated by an-2; coverage sweep L227 shows an-10 mapped to INV-024/028. |
| **N9** | Mis-directed citations (SEC-10, acb-9, dossier-14, crypto-4/as-5) | **CLOSED** | Each moved; coverage sweep confirms. INV-028 (L184) is sole home for SEC-10; INV-035 (L191) for acb-9; INV-036 (L192) for dossier-14; INV-053 (L209) for crypto-4/as-5. |
| **N10** | 47 of 147 findings cited by no invariant | **CLOSED at the Critical/High level** | §8 L219–234 coverage sweep lists every Critical/High finding either to an invariant home or to an explicit 0A-3 per-component control (cli-3 and acb-10). Non-Critical/non-High inventory remains for 0A-3. |
| **N11** | Harness-membership precondition for `CapabilityGrant` ADV-01 | **CLOSED** | §7 L147 explicitly states the OS-authenticated harness-membership precondition as an `ASSUMPTION:`. |
| **N12** | Bootstrap-root residual understates first-contact | **CLOSED** | §12 L274 sharpened. |
| **N13** | Fork verifier behavior undefined | **CLOSED** | §5 L89 defines `FORKED` as terminal; new claims/actions deny; previously issued claims at/after divergence invalidate for future machine decisions; earlier claims remain historical with fork warning on re-presentation. |
| **N14** | Break-glass two-person rule operational cost | **DEFERRED (correct)** | L289 names break-glass roles as owner-open; L308 confirms v0.2 supplies approver-rotation as input. Cost lives in 0B-OR-table. |

N1–N13 closed. N14 correctly remains 0B input.

---

## §5 mutual-revocation walkthrough (explicit, by hand)

Setup: Bob at position `r2` issues `R2` revoking Alice with `effect_from = 0`. Alice at position `r1 > r2` issues `R1` revoking Bob with `effect_from = 0`. Cut `c > r1`.

**Step 1 (L75) — Select inputs.** Cut `c`, pinned genesis/root/witness roster (INV-052). One pre-condition: no terminal FORKED has been declared for this root/policy epoch.

**Step 2 (L76) — Immutable acceptance once.** Ascending pass from `S_0`.
- `p = r2`: evaluate R2 against `S_(r2-1)`. R2 is Bob's revocation against Bob's revocation authority (intact in `S_(r2-1)`). R2 is accepted; `S_r2 = S_(r2-1) ⊕ R2` (record acceptance; no retroactive effect yet).
- `p = r1`: evaluate R1 against `S_(r1-1)`. R1 is Alice's revocation against Alice's revocation authority (intact — Bob's R2 is accepted but has not yet been applied retroactively during this acceptance pass; acceptance is checked against state, not retroactive effect). R1 is accepted; `S_r1 = S_(r1-1) ⊕ R1`.

Acceptance is now immutable for both. **This closes Opus B2(a) at the acceptance layer — there is no acceptance-time oscillation.**

**Step 3 (L77) — Operative revocations.**
- R2 operative? Acceptance-time revocation authority of Bob was valid at r2; dual control valid (signed policy) — yes.
- R1 operative? Acceptance-time revocation authority of Alice was valid at r1 — yes.
- Both operative. Both Q2 and the *complete acceptance-time authority-derivation chain* that empowered each issuer (Bob's signing-key grant at acceptance, Alice's signing-key grant at acceptance) are exempt from every retroactive effect.

**Step 4 (L78) — Direct Q2 effects.** In position order:
- R2 (at r2) marks each non-exempt accepted event whose position/action/project falls in `R2.effect_range = [0, +∞]` as `revoked-at-cut-c`. Alice's actions in `[0, c]` are in range; Alice's grant (signed by her) is in range; Alice's actions are marked.
- R1 (at r1) marks each non-exempt accepted event in `R1.effect_range = [0, +∞]`. Bob's actions in `[0, c]` are in range; Bob's grant is in range; Bob's actions are marked.

Both Alice and Bob are marked.

**Step 5 (L79) — Transitive propagation.** Forward pass in position order. **Key sentence:** *"authority conferred by a marked event is ineffective from that conferment onward."* If Alice (marked by R2) granted authority to a sub-key D at position r2.5, D's authority chain includes Alice's grant — a marked event. D's downstream actions are marked. Same for Bob's sub-delegations.

**Termination:** marks are monotone (effective → ineffective, never reversed). Pass confined to `[1, c]`. Finite. **No oscillation.**

**Step 6 (L80) — Permission-now.** New actions evaluated against effective state at `c`. Alice and Bob are revoked at `c`; any new action signed by either is denied.

**Step 7 (L81) — Issue or deny.** Each Q1/Q2/Q3 sub-result bound to cut/checkpoint/root/policy/verifier version. Q2 for Alice = revoked (R2 direct); Q2 for Bob = revoked (R1 direct). Q3 positive only if quorum ≥ 2 per INV-016 (L172) and the cut is fresh per §9 L240. If yes, claim issues with both revocations disclosed in evidence. If no (stale cut, terminal FORKED, unselected prerequisite), claim denies.

**Outcome (stated plainly):**

At cut `c`, both R1 and R2 are accepted, authorized, and operative per Step 3's exemption. Both effect sets are unioned (Alice ⊕ Bob). Both principals are revoked-at-c. Sub-delegations granted by either principal between `r2` and `r1` (or between `r1` and `c`) propagate to ineffective. No cancellation, no oscillation. This matches L85's stated result.

**This closes Opus B2(a) and B2(c).** The fixpoint is well-defined: a single forward monotone pass over `[1, c]` with marks only changing once. `S_p` is recomputed at cut `c` with retroactive Q2 propagation through conferred authority — which closes SEC-01 narrowly (delegated keys lose authority; direct-key actions by the revoked principal are marked by Step 4, not by Step 5).

**Residuals the walkthrough surfaces:**

- (i) The exemption in Step 3 covers the *acceptance-time* chain only. Sub-delegations issued *after* the original grant and *before* the revocation event may not be in the exempt set, depending on timing. See New NB-3.
- (ii) The algorithm treats Step 4 (direct mark on events in effect range) and Step 5 (transitive propagation through conferred authority) as distinct. An action signed directly by Alice (using her signing key, not delegating) at position r2.5 is marked by Step 4 (it falls in R2's effect range, since R2.effect_from = 0). But the text's plain reading could be misread to say only "conferred" authority propagates — see New NB-3.
- (iii) Step 3's "complete acceptance-time authority-derivation chain" wording is precise but dense. Reading: "R1 is operative, and the chain that gave Alice her revocation authority at r1 (Bob's key grant to Alice) is exempt from retroactive effect." R1 does not retroactively revoke its own authority basis. **That is the termination mechanism. Without it, R1 could be revoked by R2's chain, and oscillation would resume.** This is the key load-bearing sentence in the entire §5.

The walkthrough passes. Algorithm has a fixpoint.

---

## §7 matrix attack attempts (two cells × five adversaries each)

### Attempt A — `TamperEvidentChangeRecord` resists ADV-03 (writer)

Cited invariants (L141): INV-001, 005, 006, 014, 016, 017, 018, 019, 021, 022, 051, 052, 053, 056, 058.

**Attack 1 — Writer withholds event before ack.** INV-051 (L207) requires writer to return no ack OR signed ack binding submission digest/position/receipt/policy/merge delay. Withhold = no ack; submitter verifies by deadline against witnessed cut; failure raises incident and publishes ack evidence to independent channel. **Closed** by INV-051 + INV-016 (≥ 2 witness quorum, ≥ 1 honest).

**Attack 2 — Writer forges ack but never includes.** Submitter's verifier checks inclusion by deadline; failure detected. **Closed** by INV-051.

**Attack 3 — Writer includes real event but suppresses witness observation.** No quorum = Q3 unknown/negative (INV-016, INV-018). The event is in the chain (INV-005 holds) but `TamperEvidentChangeRecord` requires Q3 positive, so claim denies. **Closed.**

**Attack 4 — Writer forges a fake "inclusion" event that hashes the same as the real submission.** Cannot — INV-005 unique-position chain rejects a second event at the same position. **Closed.**

**Attack 5 — Writer + DBA collude (ADV-26) and roll back the DB before the witnessed checkpoint.** INV-038 (L194) requires restore/rollback to verify against retained external cut, authority replay, witness reconciliation, projection equivalence. INV-014 (L170) requires checkpoint signed by writer key effective after last covered position. Rollback breaks the chain at the witness's retained cut → FORKED per INV-017. **Closed.**

**Result for ADV-03:** The cell R is justified.

### Attempt B — `AttributableAuthorship` resists ADV-26 (writer + DBA collusion)

Cited invariants (L142): INV-001, 002, 008, 011, 013, 019, 020, 022, 052, 053, 056, 057, 059.

**Attack 1 — Writer signs malicious envelopes with a stolen signing key; DBA rewrites DB rows to match.** INV-008 (L164) evaluates acceptance against `S_(p-1)`; if the key is effective at `p`, acceptance is recorded. INV-011 (L167) is the *retired-authority denies* invariant — but only if the key is *retired* in `S_(p-1)`. A stolen, still-effective key is effective at `p` per the model. INV-053 (L209) constrains key custody (HSM, non-exportable) so a stolen signing key from a non-HSM custodian is bounded; from an HSM custodian it's bounded by ADV-32 (kernel) which is in INV-053's does-not-resist. So if the key is stolen via kernel compromise of a non-HSM custodian, INV-053 does not resist — and `AttributableAuthorship` cell R for ADV-26 implies resistance. **GAP** — see New NB-4.

**Attack 2 — DBA rewrites the projection to make Alice's authorship appear to be Bob's.** INV-004 (L160): "every decision reconciles mutable rows/projections/manifests/display fields byte-for-byte to authenticated evidence; mismatch denies." D for "compromised consuming boundary" — i.e. INV-004 does not resist ADV-04/06/07/09/10/17/18/20/22. But it does resist ADV-13 (DBA). Projection rewrite would create byte mismatch with the authenticated envelope; consumer denies. **Closed** for `AttributableAuthorship`'s direct use of evidence.

**Attack 3 — Writer + DBA produce an authentic Alice envelope + DB rewrite that omits the predecessor reference.** INV-002 (L158) binds predecessor to envelope; DB rewrite of projection cannot affect the canonical envelope's signed content. **Closed.**

**Attack 4 — Writer creates forgeries in unanchored range, then re-anchors with the DBA at recovery.** INV-058 (L214) requires signed unanchored-range marker, permanent disclosure. But the marker integrity depends on writer honesty — INV-058 does-not-resist ADV-03/13/26 (L214). The relying party's witness set would observe the recovery and the unanchored marker; if ≥ 2 honest witnesses exist (INV-016), the marker is recorded. If the writer + DBA also compromise the witness set… INV-016's resistance holds at quorum ≥ 2 with operational independence. **Closed at the operational-independence predicate, not at the kernel invariant alone.**

**Attack 5 — Writer + DBA collude to produce a valid envelope under a key Bob delegated to Charlie, then DBA rewrites the policy that gave Bob his delegation.** INV-008 evaluates against `S_(p-1)`; if the policy is intact at `p−1`, acceptance proceeds. If DBA rewrites the policy retroactively after `p`, the policy state used for Q2 evaluation must come from the cut, not the current DB. **Per INV-011** (L167) the verifier must use effective state at the cut; per §9 (L240) cache age is bounded by witnessed observation time; per INV-055 (L211) policy versions are monotonic. So a retroactive policy rewrite by DBA cannot lower the cut's policy version. **Closed at the cut + monotonicity pairing.**

**Result for ADV-26 on `AttributableAuthorship`:** **mostly closed**, with one real exposure at the key-custody / kernel-compromise seam (Attack 1). The cell R is justified on the cited invariants, but the residual it leaves open (stolen key via ADV-32 from a non-HSM custodian) is not stated in §12. **See New NB-4.**

---

## §8 falsification check (ten invariants × test family)

I picked ten invariants spanning all five owners and all four test families (TA, PF, DO, DG, FW, PV, PR, CT, MP) and asked: can the listed test families actually falsify the statement?

| INV | Statement (paraphrased) | Families | Can falsify? | Notes |
|---|---|---|---|---|
| INV-001 (L157) | Canonical-bytes signature verification denies ambiguous algorithms | DG, MP | **Yes** | DG tests algorithm downgrade; MP tests edge cases. |
| INV-005 (L161) | Unique-position predecessor chain; no silent insertion/deletion/duplicate | FW, MP | **Yes for chain integrity; not for censorship** | FW catches forks/rollbacks; honest **limitation stated** in INV-005's own text: "does not claim detection before acknowledgement." This is the censorship residual. |
| INV-011 (L167) | Permission-now uses cut whose witnessed observation age is within floor; retired authority denies | TA, DO, MP | **Yes** | TA tests cut staleness; DO tests online/offline equivalence. **But** TA cannot falsify ADV-03's silent withholding of fresh cuts (writer simply doesn't publish). Stated in §12 L275 as censorship residual. |
| INV-014 (L170) | Checkpoint signed by writer key effective after last covered position | TA, FW, MP | **Yes** | TA tests authority at position; FW tests rotation gap. |
| INV-016 (L172) | Quorum ≥ 2 with five distinct independence predicates | FW, PV, MP | **Yes for the predicate**, **partial for the floor** | FW injects witness failures; PV tests policy skew. But "no single person/entity/platform admin can alter quorum members" requires platform-level tests that MP cannot fully reach. See New NB-5. |
| INV-027 (L183) | Decision/action atomic commit or fail-closed replay-safe | TA, CT, MP | **Yes** | CT exercises interleavings; this is the family Opus B10 demanded. Persist-5/SEC-09 mapped here. |
| INV-049 (L205) | Break-glass cumulative cap, approver rotation, chained records | TA, FW, PV, CT, MP | **Yes** | Five families cover the rule surface; CT tests renewal races; FW tests record-chain consistency; PV tests policy-version monotonicity under emergency. |
| INV-051 (L207) | Signed ack + submitter duty + ack publication to independent channel + failure action | TA, FW, CT, MP | **Partial** | CT tests ack-timing races; FW tests fork-during-ack. **Cannot falsify** the "independent channel" guarantee — see New NB-7. |
| INV-053 (L209) | Per-key-class custody, HSM/non-exportable, purpose-separation | PV, DG, MP | **Partial** | DG tests downgrade of custody; MP tests edge cases. **Cannot falsify** "non-exportable where platform supports HSM" without platform-level HSM tests. See New NB-8. |
| INV-054 (L210) | Lock + re-read + expected-state predicate; no cached state across lock; no check/use gap | CT, TA, MP | **Yes** | CT exercises interleavings; TA tests authority at transition; MP tests edge cases. Persist-5/6/10 reachable. |

**Result:** all ten invariants have a falsifiable core. **Two (INV-051, INV-053) require platform-level tests that are partially outside the kernel-boundary test families.** Three honest limitations are stated in their own text or in §12 (INV-005 ack prerequisite, INV-011 writer withholding, INV-016 platform identity binding).

## §7 partition check on five rows

| Row | Adversary | Cell | Justification by hand |
|---|---|---|---|
| `IndependentReviewAttestation` | ADV-14 (writer host root) | **R** (L140) | Cited invariants include INV-053 (key custody), which resists ADV-14 via HSM requirement. But the cell should be D if the signing key is held on the writer host — which it generally is (writer's own key). **Internal tension.** See New NB-1. |
| `TamperEvidentChangeRecord` | ADV-14 (writer host root) | **D** (L141) | Writer host can replace writer and alter checkpoint contents; INV-014 (L170) does-not-resist ADV-14. Consistent. |
| `AttributableAuthorship` | ADV-14 | **D** (L142) | Same reasoning; writer host can forge signatures if it holds the signing key. Consistent. |
| `TrustedTimestamp` | ADV-30 (directory admin) | **D** (L143) | TSA certificates bind through the directory; directory admin can rebind principals but cannot issue TSA certificates. **D is justified by the platform precondition (TSA policy) in INV-056.** |
| `CapabilityGrant` | ADV-09 (agent-notes) | **R** (L144) | Broker keys are HSM-isolated per INV-053; agent-notes process cannot hold them. R is justified. |

**Result:** the partition is mostly consistent. The remaining inconsistency is at the `IndependentReviewAttestation` × ADV-14 cell where the row cites INV-053 (which resists ADV-14) but shows D for ADV-14 — this is defensible if "R" means "the claim alone, without platform control" (since the signing key may or may not be on the writer host), but the same logic doesn't apply to `AttributableAuthorship` × ADV-14 which also cites INV-053 and shows D. **The semantic of "R" is not uniform across rows.** See New NB-1.

---

## §9 attack attempts (break-glass, cache window extension, unanchored capture laundering)

### Attempt C — Chain break-glass for indefinite renewal

Plan: A + B invoke at minute 0 (incident X); cap exhausts at minute 60. A + B invoke again at minute 60 for incident Y (different justification). Repeat.

**§9 L251:** "The cumulative authorization budget is 60 minutes per incident, not per invocation." So incident X and incident Y are *separate* per-incident budgets. **Allowed.** But "No renewal by the same set is permitted; any extension requires a different pre-authorized approver set and a non-emergency escalation ceremony, and cannot exceed the signed absolute incident cap."

**Trick:** At minute 60, can A + B invoke for incident Y under a different justification? §9 doesn't explicitly forbid same-set across *different* incidents — only across extensions of the same incident. So **A + B could open a new incident each time they need more time, up to the signed absolute incident cap (which §9 doesn't state; the model has it as an owner-open constant).**

**Result:** break-glass is *bounded per incident* but not bounded across incidents. This is a §9 omission. **See New NB-9.**

### Attempt D — Extend the cache window to permit post-revocation actions

Plan: at minute 14 (just before `PERMISSION_NOW_MAX_STALENESS = 15`), force a re-verification that re-derives the same cut. Re-derive the cache entry and use it for actions at minute 14.5.

**§9 L240:** "Cache age is `decision_time − earliest_required_witness_observation_time(cut)`, never cache-entry creation or re-derivation time. Every cache entry binds the first authenticated observation time. Re-verifying or copying the same cut cannot extend the window."

**Closed.** Age is bounded by the cut's witnessed observation time, not by when the cache entry was created.

**Trick:** at minute 14, request a *new* cut from the witness set. The writer can withhold (writer compromised, ADV-03). The cache then expires at minute 15 and Q3 is stale/negative. Action denied.

**Closed** — but the action is denied, which is the model's intended behavior.

### Attempt E — Launder unanchored capture despite §9 / INV-058

Plan: writer accepts events during anchor outage, composes pending range at will, at recovery publishes a consistent checkpoint; unanchored marker is appended; intersection claims now have `unanchored=true` permanently.

**INV-058 (L214)** requires the marker; §12 L280 states the disclosure residual. **The laundering is bounded — the marker cannot be cleared.** But the marker *integrity* depends on writer honesty (INV-058 does-not-resist ADV-03/13/26, L214). If ADV-03 composes the pending range and *also* writes a fraudulent marker that understates the outage duration, the marker is in the chain but the contents lie. **Honest witnesses would detect the lie only if they have an independent clock + external observation.** INV-015 binds trusted observation time, but §9 line 238 only lists `trusted observation clocks` as an ASSUMPTION set in signed policy. **No invariant enforces that the witness's clock matches an external reference.** A compromised writer + compromised witness host could publish a marker consistent with a short outage when the real outage was long.

**Result:** the laundering defense relies on writer honesty **and** witness clock honesty. The witness-clock honesty is an **implicit trust** (see New NB-10). The text acknowledges the writer-honesty limit in the resistance list; it does not acknowledge the witness-clock limit.

---

## §11 / §12 immutability check

§11 element 5 (L267): "Content admitted into a witnessed append-only event cannot be deleted without breaking the chain; deleting a projection does not delete the event or witness commitment. `OPEN - OWNER DECISION:` Recommend default **(a) forbid free text entirely in the allowed-content schema**. Alternative **(b) redactable-by-construction** stores only a salted per-field digest in the event and plaintext in a separately access-controlled, deletable side store; salt custody/erasure and side-store references must not permit dictionary recovery. Until the owner selects (b), free text is forbidden. No signature, digest, checkpoint, scan, or claim proves PHI absence."

§12 L283: "Admitted event content cannot be deleted from a witnessed append-only chain. Quarantine/deletion can address side stores, projections, caches, and controlled backups only; prior disclosure, external copies, witness commitments, and legal holds remain."

**Is the residual now stated plainly?** Yes, in three places (element 5, INV-048 L204, §12 L283).

**Is the free-text recommendation sound?** Plan §1 L37 says PHI is a "non-goal" and the system "is designed not to ingest, retain, or attest patient data." Option (a) forbids free text — consistent with the non-goal. Option (b) admits free text with deletion-sidecars — inconsistent with "must never ingest" framing, because ingestion happens even if deletion is offered. The recommendation should explicitly favor (a) on non-goal grounds and reject (b) as a contradiction of the plan's PHI stance, or §11 element 5 should explicitly note that (b) abandons the non-goal claim.

**The recommendation as written is logically consistent but the trade-off is not stated.** See New NB-6.

---

## Implicit trusts — what the model still trusts implicitly

A search for "anything the model still trusts implicitly (an input, a clock, a channel, a role) that has no invariant":

| Implicit trust | Where | Status | Finding |
|---|---|---|---|
| **Pin channel operator independence** | INV-052 (L208) | The text requires "operator-independent authenticated pin channel" but does not name or constrain the channel. | See New NB-7 |
| **HSM correctness** | INV-053 (L209) | "non-exportable where platform supports HSM" — trust in HSM manufacturer + firmware correctness is platform-dependent and not tested by INV-053's families (PV, DG, MP). | See New NB-8 |
| **OS process isolation** | INV-053 (L209), §3 L46-56 | Trusts OS to enforce process memory isolation so app process cannot read another zone's memory. ADV-32 covers kernel compromise but not, e.g., a kernel-info-leak vulnerability unfixed by the platform. | Stated as adversary; no invariant covers a kernel-info-leak class. |
| **Witness observation clock** | INV-015 (L171) + §9 L238 | The witness binds "trusted observation time." §9 line 238 lists `trusted observation clocks` as an ASSUMPTION set in signed policy. **No invariant checks that the witness clock matches an external reference.** | See New NB-10 |
| **Witness durable retention** | INV-015 (L171) | "durably retains" — for how long? Forever? This is operationally critical for non-equivocation but undefined. | See New NB-11 |
| **Bootstrap ceremony correctness** | INV-055 (L211) + INV-052 (L208) | The first policy version + first witness roster + first pin channel are the trust anchor. Monotonicity only constrains *changes*; the initial values are accepted on ceremony faith. | Stated in plan §3 + §4 as trust anchor; no invariant needed. |
| **Cryptographic primitive soundness** | INV-001 (L157) | Ed25519, JCS, canonical envelopes. Per plan §5 L125, these are re-audited in Phase 1. | Accepted in §5; not a 0A-1 concern. |
| **Directory identity binding** | Multiple — `AttributableAuthorship`, `IndependentReviewAttestation` rows | The kernel accepts directory claims about principal identity. ADV-30 covers directory admin compromise, but the model does not require the kernel to *verify* the directory binding. | Stated as adversary; residual at the platform layer. |
| **Emergency approver hardware** | §9 L251 | "emergency keys in distinct approver hardware" per INV-053. Trusts that the approver hardware (smartcard/HSM) is uncompromised. ADV-34 covers coordinated compromise. | Stated. |

---

## VERDICT

**accept-with-changes** — substantively sound, ship-able to owner sign-off contingent on resolving the cell-semantic inconsistencies in §7 (one new blocking) and the cache-monotonicity scope bug in INV-055 (one new blocking), and on the new lineage-discipline artifact B14 implicitly demands. All 13 B- and 13 N-items from Opus v0.1 are closed or correctly deferred.

The §5 algorithm has a real fixpoint (verified by hand through the mutual-revocation example). The §7 matrix is materially complete (6×34, every cell classified, ADV-08 in all six rows, invariant_ids per row). The §8 registry is internally consistent across all 59 rows I spot-checked. The §9 degraded-state rules are bounded and the censorship residual is honestly stated. The §11/§12 immutability residual is stated in three places.

The model is **not yet perfect** — I found two blocking defects (one cell-semantic inconsistency, one INV-055 scope bug) and several non-blocking improvements — but it is now sound enough to take to owner sign-off as the canonical trust model for 0A-3 to reference. Owner can resolve the cell-semantic tension by choosing one reading of "R" and tightening §7 consistently; owner can resolve the cache-monotonicity scope by adding cache window to INV-055's protected set.

The third-lineage requirement (B14) is satisfied by this review existing; the gate transition remains for the owner.

---

## NEW BLOCKING findings (independent of Opus B1–B14)

### NB-B1 — INV-055 (policy monotonicity) does not list cache window or checkpoint cadence as protected quantities, but §9 invokes INV-055 to forbid raising them

- **Where:** §9 L238 ("No runtime configuration or emergency policy may raise a hard maximum (INV-055)") and INV-055 L211.
- **Defect:** INV-055 lists `witness quorum/independence, retire-list coverage, algorithm/version floor, custody requirement, or unanchored-window hard maximum` as monotonic. It does not list **cache window** (`PERMISSION_NOW_MAX_STALENESS`) or **checkpoint cadence** as monotonic. §9 says cache window's hard maximum cannot be raised, citing INV-055. **INV-055 doesn't actually cover this.** A signed policy update could raise the cache window to, say, 24 hours, and INV-055 would not flag it. §9 would need a separate invariant (e.g. `INV-055a` or an extension to INV-055).
- **Why blocking:** §9's claim of "no runtime configuration or emergency policy may raise a hard maximum" is normatively important (it closes a known abuse path for ADV-06/ADV-08/ADV-25 — emergency policy rollback of the cache floor). If INV-055 doesn't actually enforce it, the defense is prose, not an invariant.
- **Required change:** either expand INV-055's monotonicity list to include `PERMISSION_NOW_MAX_STALENESS` and `CHECKPOINT_MAX_AGE` (and any other signed-policy hard maxima §9 names), or add a new invariant that does. Then re-derive the resistance lists for the expanded invariant.

### NB-B2 — §7 cell semantics for ADV-09 are not consistent across rows that cite INV-053

- **Where:** §7 rows L140 (`IndependentReviewAttestation` ADV-09 = D), L142 (`AttributableAuthorship` ADV-09 = D), L144 (`CapabilityGrant` ADV-09 = R). All three cite INV-053, which resists ADV-09.
- **Defect:** Per L136 "R means sound against the adversary when every cited invariant and stated platform precondition holds." If INV-053 holds and prevents ADV-09 from holding the relevant keys, then `AttributableAuthorship` and `IndependentReviewAttestation` should both show R for ADV-09 (since the chain INV-001 + INV-002 + INV-008 + INV-053 resists ADV-09 by isolating keys). But they show D. The reading "R" must therefore mean something other than "every cited invariant resists," which contradicts L136's plain text.
- **Why blocking:** §7 is "the claim-by-adversary matrix" that 0A-3 will reference by id (README L25). If two rows cite the same invariant that resists an adversary but show different cells for that adversary, the matrix is not a matrix — it is a table where each cell's meaning depends on the row's prose context. The cutover gate (plan §8 L186) cannot evaluate cells whose semantic isn't uniform.
- **Possible reconciliations:**
  - (a) Tighten "R" to mean "the claim structure, considered alone, resists when all cited invariants and platform preconditions hold" — and document that for `AttributableAuthorship`, the *display* path (which an ADV-09-compromised agent-notes can subvert) is not in the claim's resistance, even though key custody is. Then both rows (D for `AttributableAuthorship`, D for `IndependentReviewAttestation`) make sense; `CapabilityGrant` (R) makes sense because its claim is broker-only.
  - (b) Re-derive the cells to be uniform: every cell = R if any cited invariant resists the adversary and no cited invariant's non-resistance contradicts it. Then `AttributableAuthorship` ADV-09 becomes R, `IndependentReviewAttestation` ADV-09 becomes R, and `CapabilityGrant` ADV-09 stays R. But then `TamperEvidentChangeRecord` ADV-14 (L141, D) would need to be R too, because INV-053 (cited) resists ADV-14.
- **Required change:** pick one reading of "R"; rewrite §7 cells to match it; document the reading on L136. Then verify the §7 self-check (which is per-row in §8) is consistent with the chosen reading.

### NB-B3 — §11 element 5 (free-text recommendation) is logically inconsistent with INV-046 / INV-048 (which assume textual retention can happen)

- **Where:** §11 L267 recommends "forbid free text entirely"; INV-046 (L202) says "Defense-in-depth scanning/refusal precedes any allowed textual retention"; INV-048 (L204) says "Suspected PHI triggers restricted incident handling, side-store/projection/cache deletion where authorized."
- **Defect:** If free text is forbidden, no textual retention happens, so INV-046's "precedes any allowed textual retention" describes an empty set, and INV-048's "suspected PHI" can never trigger because no PHI can be admitted. Yet INV-046/048 are stated unconditionally. The model can't simultaneously hold (a) "free text forbidden" and (b) "scanning precedes textual retention; suspected PHI triggers incident handling." One must be conditional on the owner's (a)/(b) choice in §11 element 5, or the model must commit to one posture.
- **Why blocking:** INV-046/048 are part of the registered invariant set (§8 L202, L204) with resists columns, test families, and citations. If they're vacuously true under the recommended default, the registry is overstated.
- **Required change:** rephrase INV-046/048 as conditional ("if textual retention is allowed in signed policy, then…"), or commit the model to option (b) redactable-by-construction and adjust §11 element 5 accordingly. Either path is acceptable; the current state of "both" is not.

---

## NEW NON-BLOCKING findings (independent of Opus N1–N14)

### NB-1 — `CapabilityGrant` row does not cite INV-051 (signed append acknowledgement)

- **Where:** §7 L144, `CapabilityGrant` invariant_ids.
- **Defect:** INV-051 is the censorship defense. A capability grant is an event in the log; if a compromised writer (ADV-03) censors the grant event before ack, the caller believes they have a capability they don't. `TamperEvidentChangeRecord` cites INV-051; `IndependentReviewAttestation` cites it; `AttributableAuthorship` cites it. `CapabilityGrant` doesn't.
- **Severity:** non-blocking because the censorship residual is stated in §12 L275 globally. But for a claim whose semantics *is* the grant of authority, omitting the censorship invariant is a substantive gap.

### NB-2 — §5 Step 3 exemption scope is dense and its interaction with Step 5 is ambiguous on a corner case

- **Where:** §5 L77 ("Its own Q2 and the complete acceptance-time authority-derivation chain that empowered its issuer are exempt from every retroactive effect") and L79 (Step 5 propagation).
- **Defect:** If R is operative and its acceptance-time chain includes events at positions that R's effect range *also* covers (e.g. Bob's grant to Alice at p1, with R1 issued by Alice at r1 > p1 having effect_from = 0 covering p1), then R1's exemption protects R1 itself but the text doesn't say whether R1's acceptance-time chain (which includes Alice's signing-key grant at p1) is exempt *as part of R1's chain* or *as an event in R1's effect range that is marked by Step 4 and propagated by Step 5*. The mutual-revocation result (L85) is correct under either reading, but the formal relationship is not stated.
- **Severity:** non-blocking. The mutual-revocation outcome is correct; the ambiguity is in the proof sketch, not the result.

### NB-3 — §5 algorithm does not crisply address sub-delegations issued *after* the original grant and *before* the revocation

- **Where:** §5 L77, L79.
- **Defect:** Step 3 exempts the "complete acceptance-time authority-derivation chain." A sub-delegation by the revoked principal at a position *after* acceptance time is not in the acceptance-time chain. Step 5 says "authority conferred by a marked event is ineffective from that conferment onward." So a sub-delegation *after* the principal is marked should be ineffective. But Step 5 also says "Mark every non-exempt descendant action whose only authority derivation includes ineffective authority" — implying the *descendant* is marked, not the sub-delegation itself.
- **Severity:** non-blocking. The intent (sub-delegations issued by a revoked principal are ineffective) is clear; the formal walkthrough has a minor gap.

### NB-4 — `AttributableAuthorship` ADV-26 (writer + DBA) cell R is conditional on key custody being intact against ADV-32

- **Where:** §7 L142, `AttributableAuthorship` row.
- **Defect:** If a signing key is stolen via ADV-32 (kernel compromise of a non-HSM custodian), INV-053 does not resist — and `AttributableAuthorship` would still validate the signature. The cell R for ADV-26 implies resistance, but the residual is unstated in §12.
- **Severity:** non-blocking. §12 L282 ("A compromised gate/broker/kernel can admit actions or expose credentials available there; provenance is not OS enforcement") is the catch-all. But `AttributableAuthorship` row should foot-note this for the 0A-3 matrix.

### NB-5 — INV-016 (quorum independence) has a platform-level testability gap on "no single platform admin"

- **Where:** INV-016 L172.
- **Defect:** The predicate "no single person/entity/platform admin can alter quorum members" requires platform-level tests (cloud admin, directory admin, hypervisor admin) that the FW/PV/MP families cannot reach. The independence predicate is sound as a *policy* statement but partial as a *testable* invariant.
- **Severity:** non-blocking. The predicate is normative; the test family limits are honest.

### NB-6 — §11 element 5 (b) redactable-by-construction contradicts plan §1's "must never ingest" framing

- **Where:** §11 L267 + plan §1 L37.
- **Defect:** Plan §1 says PHI is a non-goal ("designed not to ingest, retain, or attest patient data"). Option (b) admits free text with deletion-sidecars — which *is* ingestion, just with a deletion mechanism. The recommendation should explicitly tie (a) to the non-goal and reject (b) on non-goal grounds, or §11 element 5 should explicitly note that choosing (b) abandons the non-goal claim and triggers plan §1 L37's "compliance liability" framing.
- **Severity:** non-blocking. The owner has the decision and the framing is honest enough to inform it.

### NB-7 — INV-051's "independent channel" is not defined

- **Where:** INV-051 L207 ("publishes acknowledgement evidence to an independent channel").
- **Defect:** §3 trust zones (L46-56) define writer, verifier, witness, gate engine, broker, bootstrap root, apps, transport — no separate channel zone. The text doesn't name the channel. The witness set is the most natural candidate (and §7's R for `TamperEvidentChangeRecord` ADV-03/13 relies on the witness set + INV-016). But the relationship is implicit.
- **Severity:** non-blocking. The intent is clear; the binding is loose.

### NB-8 — INV-053 key custody is platform-conditional on HSM availability

- **Where:** INV-053 L209 ("Private keys are non-exportable where platform supports HSM").
- **Defect:** On a target platform that does not support HSM (a possible deployment profile), the "non-exportable" guarantee does not apply. INV-053's resistance to ADV-32 is conditional. The text acknowledges this in the conditional clause but does not record a separate invariant for the HSM-unavailable profile.
- **Severity:** non-blocking. The plan acknowledges platform variability; the deployment profile mechanism (plan §8 L186) is the natural home for the alternative invariant.

### NB-9 — §9 break-glass is bounded per-incident but unbounded across incidents by the same set

- **Where:** §9 L251.
- **Defect:** "The cumulative authorization budget is 60 minutes per incident, not per invocation." A+B can open incident X at minute 0 (60-min cap), incident Y at minute 60 (60-min cap), incident Z at minute 120, etc. Each is a *new* incident; the exclusion list (L249) does not forbid the same approver set across distinct incidents. §9 has a "signed absolute incident cap" but the value is owner-open (L289).
- **Severity:** non-blocking. A signed absolute incident cap with a hard maximum closes this. The owner needs to set the cap; the model says so but doesn't specify a default.

### NB-10 — Witness observation clock is implicitly trusted; no invariant checks it against an external reference

- **Where:** INV-015 L171 + §9 L238.
- **Defect:** The witness binds "trusted observation time" (INV-015) and §9 L238 lists "trusted observation clocks" as an ASSUMPTION set in signed policy. No invariant enforces that the witness clock matches an external reference (NTP, GPS, atomic clock). ADV-16 (witness host root) is in INV-016's resists, but only because ≥ 2 witnesses quorum — *not* because clock skew is detected across witnesses.
- **Severity:** non-blocking. A skew-detection mechanism is a 0B/0C concern. But this is exactly the kind of implicit trust the prompt asks me to find.

### NB-11 — INV-015's "durably retains" is undefined in duration

- **Where:** INV-015 L171.
- **Defect:** The witness must retain checkpoints "durably" for the model to detect forks (§5 L89). The duration is operationally critical (forever? 7 years per HIPAA? until policy says otherwise?). No invariant specifies it.
- **Severity:** non-blocking. The duration is a 0B/0C operational concern. INV-016's predicate includes "persistence plane" but not retention duration.

### NB-12 — §6 ADV-23 conflates "anchor" and "witness" operators; §3 has no anchor zone

- **Where:** §6 L122 ("ADV-23 | One anchor/witness operator | choose/withhold/fork/erase one operated witness record; use its key") and §3 L46-56.
- **Defect:** §6 names "anchor/witness" as one adversary, but §3 has no anchor trust zone (only witness). The two are either collapsed (a witness can serve both roles, per §3 ASSUMPTION at L59) or §6 has a terminology drift. The model collapses anchor = witness (L59 "witness and anchor functions may be combined only if the selected design still satisfies the operational independence predicate in INV-016"), so the ADV-23 conflation is consistent with the design — but the wording is sloppy.
- **Severity:** non-blocking. Consistency is achieved; clarity could be improved.

### NB-13 — §7 row `CapabilityGrant` ADV-01 cell carries a precondition ("requires OS-authenticated process identity…") but the precondition is not in the cell text

- **Where:** §7 L144.
- **Defect:** Line 147 separately states "ADV-01 resistance requires OS-authenticated process identity and harness membership not shared-UID/self-asserted" as an `ASSUMPTION:`. But the row cell just shows R. Without reading L147, a 0A-3 reader sees an unconditional R.
- **Severity:** non-blocking. The assumption is captured; the cell could carry a footnote marker.

### NB-14 — §8 INV-058 (recovery marker) test family omits CT

- **Where:** §8 L214 INV-058 test column.
- **Defect:** INV-058 covers recovery (concurrent recoveries, race conditions on the unanchored marker append). CT family is appropriate. But the test column shows FW, PV, MP only.
- **Severity:** non-blocking. CT can be added; the invariant is otherwise testable.

### NB-15 — Appendix A is honest but the B14 status is at risk of being treated as a "process" item rather than a substantive review gap

- **Where:** Appendix A L308 ("Process remains pending: v0.2 explicitly requires third-lineage review; no gate transition recorded").
- **Defect:** This review *is* the third-lineage review, but a future reader of the appendix might mis-read it as "process open, not blocking." The text is correct, but a follow-up should explicitly say "third-lineage review passed under reviewer 3 (minimax-m3) on 2026-08-26" once owner sign-off records.
- **Severity:** non-blocking. Documentation hygiene.

---

## Charter acceptance criteria (README L25, L27)

| # | Criterion | Status in v0.2 | Notes |
|---|---|---|---|
| 1 | Every adversary in plan §4 has an entry | **met** | All ten plan-§4 categories present, expanded to 29 ids in v0.1 plus ADV-30–34 in v0.2 (Opus B13). 34 total. |
| 2 | Every claim names resisting **and** non-resisting adversaries | **met, with the cell-semantic caveat** | §7 is a complete 6×34 matrix. Every cell is R/D/R*. ADV-08 is D in all six rows. **But** the meaning of "R" is not uniform across rows that cite INV-053 — see NB-B2. |
| 3 | Invariant registry: stable id · statement · **resists / does-not-resist** · owning boundary · test family | **met** | 59 invariants (INV-001..059); each row partitions 34 ids; owners and families named. Self-check at L217 asserts partition. **But** INV-055's monotonicity list omits cache window — see NB-B1. |
| 4 | No invariant without a named test family | **met** | All 59 rows have ≥ 1 family. INV-051/INV-053 have families that cannot fully reach platform-level guarantees — see NB-7/8. |
| 5 | Legacy decision recorded | **partially met** | §10 (L255) records a recommendation of quarantine-as-unverifiable, marked `OPEN - OWNER DECISION REQUIRED`. This is the right drafter posture; the criterion asks for the *decision*, which remains owner's. |
| 6 | PHI section covers all five elements | **met, with the conditional-logic caveat** | §11 L263–267 maps cleanly to plan §1 L37 (i)–(v). **But** §11 element 5 + INV-046/048 are inconsistent under the recommended default — see NB-B3. |
| 7 | Two-reviewer pass (Sol draft → Fable → **third lineage**) | **met by this review** | v0.2 explicitly defers (L3, L308). Reviewer 3 (minimax-m3, third lineage from OpenAI/Anthropic ecosystems) is this artifact. No gate transition recorded per the prompt. |
| 8 | Owner sign-off | **not met** | Pending; gated on the open `OPEN:` items (L5, L87, L91, L238, L249, L255, L267, L289) and the two new blocking findings (NB-B1, NB-B2). |

The model is **ship-able to owner** for the open `OPEN:` items and the two new blocking findings to be resolved (or consciously waived) before sign-off.

---

## Summary

**B1–B13 and N1–N13:** all closed or correctly deferred. Opus's review was thorough; v0.2 is materially responsive.

**Mutual-revocation walkthrough:** algorithm has a fixpoint (verified by hand through Bob/Alice at r2/r1 with effect_from = 0). The mutual-revocation result at L85 is correct.

**§7 matrix:** structurally complete (6×34, ADV-08 everywhere, invariant_ids per row). **One cell-semantic inconsistency** (NB-B2) prevents me from calling §7 fully sound; the owner needs to pick a reading of "R" and tighten the cells.

**§8 falsification:** all 10 invariants I tested have falsifiable cores via the listed families. Two (INV-051, INV-053) have platform-level testability gaps that are honestly bounded.

**§9 attacks:** break-glass is bounded per-incident but unbounded across incidents (NB-9); cache window extension is closed by §9 L240; unanchored laundering is bounded by INV-058 + §12 L280 with a witness-clock honesty gap (NB-10).

**§11/§12 immutability:** residual stated in three places; recommendation is consistent with the non-goal *for option (a)*; option (b) is honest but contradicts the non-goal framing (NB-6).

**Implicit trusts found:** pin channel operator independence (NB-7), HSM correctness (NB-8), witness observation clock (NB-10), witness durable retention duration (NB-11). All four are honest limits; none falsifies the model.

**Verdict: accept-with-changes** — v0.2 is the canonical trust model for 0A-3 to reference, contingent on resolving the two new blocking findings (NB-B1 INV-055 scope; NB-B2 §7 cell semantics) and acknowledging the third-lineage review here. The §5 fixpoint and the §7 matrix coverage are real and load-bearing.

---

*This review is filed as text only. No gate transition recorded, no files edited, no subagents spawned. Model lineage: ollama-cloud/minimax-m3 (third lineage).*
