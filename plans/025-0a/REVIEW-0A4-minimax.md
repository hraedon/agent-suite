# 0A-4 ADMISSIBILITY-MAP.md + DATA-BOUNDARY.md — reviewer 2 notes (minimax-m3, non-drafter lineage, 2026-08-25)

# 0A-4 adversarial review — VERDICT per file
## Citations (ADMISSIBILITY-MAP)
All five citations verifiable and accurate to stated intent:
- **HIPAA §164.312** — (a)(1), (b), (c)(1), (d), (e)(1) are real provisions; (c)(2) "Mechanism to authenticate ePHI" is Addressable; map's "state safeguard objectives" framing is correct.
- **RFC 3161** — §2.1 (TSA requirements), §2.4.1 (TimeStampReq with `messageImprint`/`reqPolicy`/`nonce`/`certReq`/`extensions`), §2.4.2 (TSTInfo with `policy`/`messageImprint`/`serialNumber`/`genTime` + optional `accuracy`/`ordering`/`nonce`/`tsa`/`extensions`) all match the spec.
- **SLSA / in-toto Statement v1** — defensible: SLSA Provenance v1.0 wraps provenance predicates in an in-toto attestation envelope with subject digests; `buildDefinition` is the SLSA predicate; `runDetails` is part of SLSA v1.0.
- **AICPA TSC CC8.1** — broadly correct (CC8.1 = "Change Management"); map's `VERIFY:` flag is appropriate.
- **Sigstore** — "bundles package verification material for offline verification" is accurate.
No fabricated citations. No citation has been overreached.
---
## VERDICT — ADMISSIBILITY-MAP.md
**Accept-with-changes.**
**BLOCKING**
1. **Line 23 vs. TM §7 row (line 140): citation-set inconsistency on INV-059.** The `IndependentReviewAttestation` analogy text requires "all common section 7 fields" + reviewer/role/org/lineage/conflict + "subject digest/range + requested action" + "explicit human approval bound to the rendered subject digest" + policy id/version + "evaluated result" — and cites `INV-019..INV-023, INV-026, INV-028, INV-041`. The §7 matrix row (TM:140) additionally cites **INV-059** ("Agent or human review admission binds the exact presented subject digest, reviewer authenticated process/principal, role, policy, and resulting signed event; apps cannot substitute another digest or directly use governance-authority signing keys"). The map's analogy text should explicitly cite INV-059 (subject-digest binding is its exact statement) and INV-024 (gate input semantics) to match the §7 row's full citation set; otherwise the analogy's "fields required" and "independence policy" look narrower than the matrix claims.
**NON-BLOCKING**
1. **Line 22: independence policy citation `INV-022, INV-025..INV-028, INV-041` omits INV-028 from the explicit list while citing "SoD" concepts.** The map does cite INV-028 in the policy text but the bracketed ID list jumps `INV-025 through INV-028` (correctly includes it); no actual gap, just confirming.
2. **Line 50 (TrustedTimestamp analogy-breaking failure mode): the sharpest failure mode the model exposes — *log order ≠ wall-clock order under adversary-controlled witness observation time* — is partly captured ("Compromise of the accepted TSA or required time quorum remains a stated limit") but the **correlation of two witnesses through a single time-reference compromise** is named only at TM §12 L299, not surfaced as an analogy-breaking failure. The map's failure mode is at the *individual* witness level; the cross-witness correlation is the more acute break for the analogy under the trust model's `WITNESS_CLOCK_SKEW_MAX` semantics.
3. **Line 61 (CapabilityGrant analogy-breaking failure mode): missing the broker→executable TOCTOU window.** The map names "trusts a pathname rather than the executable image, permits environment substitution, releases an overbroad credential, or ignores expiry/revocation". The sharper failure is **the broker checks executable identity correctly, then the *executable itself* is a loader/interpreter that re-invokes attacker-chosen code at runtime** (i.e. the broker's "executed image" identity is satisfied but the actual executed code is attacker-controlled downstream). INV-031's "no check/use gap" addresses the broker boundary, not the post-broker loader chain. Add one sentence.
4. **Lines 11/13 (Citation posture): "AICPA Trust Services Criteria CC8.1 addresses authorization, design/development or acquisition, configuration, documentation, testing, approval, and implementation of changes"** is a paraphrase. AICPA TSC CC8.1's actual canonical text names "authorizes, designs, develops or acquires, configures, documents, tests, approves, and implements changes" — close match but the precise wording should be cited as a `VERIFY:` for the target's SOC 2 mapping rather than asserted here. Already partially mitigated by the `VERIFY:` tag; tighten the wording.
5. **Line 9 ("intentionally use only clauses or named data concepts that this engineering draft can identify confidently")** is honest; the map's "every entry has validation status `internal-hypothesis`" plus "Stage-1 conclusion" (line 74-76) is structurally correct. No statement is stronger than `internal-hypothesis` allows in the admissibility text itself.
---
## VERDICT — DATA-BOUNDARY.md
**Accept-with-changes (one blocking; needed for D-0A-1 consistency).**
**BLOCKING**
1. **Line 23 (the "Approved short text" class) is not consistent with D-0A-1's recommended default.** D-0A-1 recommends **forbid free text entirely**; §11.5 (TM:286) ties this to the PHI non-goal; D-0A-1's "Where it bites" column explicitly says *"DATA-BOUNDARY.md §1 'approved short text' class is then dropped."* As written, DATA-BOUNDARY §1 still defines an "Approved short text" class with caps (256 B/field, 1 KiB aggregate) and an `OPEN:` note saying *"The safer default is structured reason codes plus an external record digest."* Under D-0A-1's recommended default the row should be **struck** (or marked `DROPPED under D-0A-1 default`) and the `OPEN:` reframed to *"re-instate only if D-0A-1 selects (b) redactable-by-construction"*. Otherwise the artifact contradicts the decision it is implementing.
2. **Line 47 (Data minimization): "Free text is exceptional, bounded, scanned, and excluded from security decisions."** This is a quiet re-admission of free text under D-0A-1's recommended default. Under (a) forbid, free text is *not* an exceptional class; it is forbidden at admission. The current wording is consistent with the conditional posture (signed-policy textual retention) but not with D-0A-1's recommended default. Rewrite as *"Under the no-free-text default (D-0A-1 (a)), no free text is admitted; this exception clause is inactive. Under D-0A-1 (b), free text admitted into structured reason codes is bounded, scanned, and excluded from security decisions."*
3. **Line 65 (Scanning/refusal `ASSUMPTION:`)**: *"The scanner set will combine deterministic secret/direct-identifier patterns with a target-approved PHI detection service operating within the same approved data boundary."* Under D-0A-1 (a) the scanner is **inactive** — there is no free text to scan. The ASSUMPTION frames the conditional control (signed-policy textual retention) but the document does not make the conditional-vs-active status crisp. Mark explicitly: *"Under D-0A-1 (a) this scanner is inactive; the conditional retention branch of INV-046 is dormant."*
**NON-BLOCKING**
1. **Line 93 ("cryptographically erases ordinary-store and projection copies")** presupposes substrate-level encryption-at-rest with key-shred capability. The draft schema (§1 envelope caps) does not name encryption-at-rest as a property, and the witness commitment is append-only (TM §12 L304). If the substrate does not encrypt event bodies at rest, "cryptographic erasure" reduces to overwriting side-store copies. Add an `OPEN:` naming the substrate precondition.
2. **Line 33 (16 GiB opaque-artifact bound) and Line 34 (1 MiB bundle manifest, 10,000 digest-only subjects)** are correctly flagged `OPEN:`. Defensible at engineering level but should be re-validated against representative workload before 0C protocol acceptance, as the note states.
3. **Line 105 ("tombstone may contain only ids, disposition code, policy version, and authorization digest")** is consistent with the allowlist. Good.
4. **Section 7 (Invariant map) Line 121** — INV-048 residual row names ADV-13..20 and ADV-25 as adversaries an admin/root may exceed deletion authority against. TM §12 L304 confirms. Consistent.
5. **Line 127 (residual statement)**: "No signature, digest, checkpoint, schema allowlist, scanner result, refusal event, quarantine action, deletion record, backup expiry, or downstream attestation can prove that evidence contains no PHI." Honest, appropriately broad. No statement stronger than `internal-hypothesis` (the document doesn't carry that tag explicitly because it's not part of the admissibility map, but the structural posture is identical and the residual is correct).
---
## Charter 0A-4 acceptance (README:47-53)
| Criterion | Met? |
|---|---|
| Every claim has a failure mode | **met** (6/6) |
| Every claim has a validation status | **met** (6/6, all `internal-hypothesis`) |
| No entry claims acceptance | **met** (D3 stage-2 questions framed as questions) |
| Fable + Sol concur | **met** (deliverable of joint 0A-4 work) |
| Owner sign-off | **pending** (D-0A-1..6 owner decisions) |
| DATA-BOUNDARY covers 5 elements (allowed-content, minimisation, scanning, opaque-artifact, quarantine/deletion/incident, residual) | **met** (covers all six) |
**Charter acceptance: NOT YET MET** — pending the three DATA-BOUNDARY changes above (D-0A-1 alignment) and the ADMISSIBILITY-MAP INV-059 citation tightening. None is load-bearing for the trust model itself; all are load-bearing for the artifact's internal consistency with the owner-approved decision list.
---
## Independence-policy check (INV-028 / INV-059)
- INV-028 (TM:203) — "SoD uses authenticated distinct principals, role/org authority, conflicts, lineage, and approval; strings or lineage alone do not suffice." Map's independence policy (line 25) **complies**: requires distinct principal+human identity, organizational authority, conflicts declaration, lineage as auxiliary only, and explicit human approval bound to rendered subject digest.
- INV-059 (TM:234) — exact-subject-digest binding for review admission. Map's `IndependentReviewAttestation` requires exact rendered subject digest binding (line 24) **but the cited invariant list omits INV-059** (lists `INV-019..023, INV-026, INV-028, INV-041`). The §7 matrix row *does* cite INV-059. This is the citation-set drift noted above.
---
## Sharpest analogy-breaking failures (cross-check)
- `IndependentReviewAttestation` — sharpest: **stale-render TOCTOU** (reviewer reads digest `D1`, subject swaps to `D2` before approval-click). Map names this ("human saw different bytes from the bound subject"); INV-041 covers it. **OK.**
- `TamperEvidentChangeRecord` — sharpest: **signed-but-semantically-fraudulent append**. Map names it ("semantically fraudulent but valid append"). **OK.**
- `AttributableAuthorship` — sharpest: **bounded-scope signer key used cross-domain**. Map names it ("missing authority-at-position"). **OK.**
- `TrustedTimestamp` — sharpest: **correlated-witness time-reference compromise** (not just single-witness compromise). Partially captured ("required time quorum" → "TSA or required time quorum"); the *correlated* compromise is in TM §12 L299 but not surfaced as the analogy-breaker. **NB.**
- `CapabilityGrant` — sharpest: **broker-correct but post-broker loader/interpreter re-invokes attacker code**. Not named in map. **NB.**
- `ExternallyAuthenticatedBundle` — sharpest: **bundle signer key doubles as policy author**, so policy and signature share fate. Not named in map; extremely subtle but real. **NB (very low priority).**
