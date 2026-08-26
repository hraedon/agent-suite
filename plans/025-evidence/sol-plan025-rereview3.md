## Per-item convergence checklist

| # | Round-2 checklist item | Status | Assessment |
|---:|---|---|---|
| 1 | Replace “library in regista” with a logical provenance kernel | **RESOLVED** | Boundary 1 now absorbs the trust-bearing portions of regista and cairn, while repository/process placement is deferred to 0C (`§3`, lines 79, 88–90). |
| 2 | Make decomposition/TCB selection an explicit Phase-0 deliverable | **PARTIAL** | Logical decomposition is explicit and D1 is reportedly approved (`lines 3, 73–88`); repository/process boundaries are correctly deferred to 0C (`lines 163–164`). But the document simultaneously says D1 remains to be ratified and that no architecture is frozen before 0A closes (`lines 73, 161, 191–194`). |
| 3 | Split Phase 0 into ordered 0A/0B/0C | **RESOLVED** | The ordering and outputs are explicit (`§8`, lines 160–164). |
| 4 | Decide legacy reject/quarantine/re-anchor before the first slice | **RESOLVED** | Required in the trust model and 0A, before legacy admission (`§4`, lines 106–108; `§8`, line 161). |
| 5 | Put Critical/representative-High reproduction and provisional 147-row ownership in the freeze gate | **PARTIAL** | The gate now requires all Criticals, representative Highs per distinct mechanism, and provisional ownership for all rows (`§2`, lines 59, 69; `§8`, line 161). But D1 has already frozen a material architectural decision, and “distinct mechanism”/“representative” has no taxonomy or selection rule. |
| 6 | Local proof verification by default; justify receipts | **RESOLVED** | Local verification is the default, with receipts limited to consumers that genuinely cannot host verification and with residual verifier-operator risk disclosed (`§5`, line 118; `§8`, line 163). |
| 7 | Consolidate gate infrastructure while retaining policy-specific schemas | **PARTIAL** | One engine owns versioned policy and atomic action admission (`§3`, line 80), and distinct review/lifecycle/genesis/release policies remain (`§8`, line 169). Explicit policy-specific schemas and compatibility/versioning rules are not stated. |
| 8 | Define agent-wake as non-authoritative transport | **RESOLVED** | Wake cannot authorize transitions, releases, or gate passes; receivers re-authorize through boundaries 2 or 3 (`§3`, line 84). |
| 9 | Keep acb as a separate enforcement TCB | **RESOLVED** | Boundary 3 remains separate and excludes Vault/subprocess/platform code from the cryptographic TCB (`§3`, line 81). |
| 10 | Profile-based cutover with disabled features structurally unreachable | **PARTIAL** | Profile-based cutover is adopted (`§8`, line 181), but “structurally unreachable” is asserted rather than defined as a deployable, testable invariant. |
| 11 | Resolve Phase-1/Phase-2 overlap | **PARTIAL** | One evolving implementation avoids two independent builds (`§8`, line 165), but “spike → hardened in place” lacks a security promotion gate. More importantly, protocol re-audit is deferred to Phase 2 even though Phase 1 calls its protocol-bearing slice “production quality” (`lines 165–167`). |
| 12 | Schedule migration and add explicit verification test families | **PARTIAL** | The testing families are now satisfactorily explicit (`§8`, line 179). Migration has sequencing and a legacy-write shutdown point (`line 177`), but remains “interleaved” without ownership, per-consumer ordering, a concrete entry gate, or compatibility-window exit criteria. |

## VERDICT: **sound-with-changes**

The security model and four-boundary architecture have converged. Phase 0A may start: none of the remaining issues requires returning to the seven-component design or rethinking the three provenance questions.

The plan is not yet safe to treat as an approved production roadmap. Its principal remaining defects are promotion/cutover semantics, compliance overstatement, and unresolved contradictions in its decision state.

## BLOCKING items

1. **Protocol re-audit is ordered after the protocol-bearing slice is declared production quality.**  
   Phase 1 necessarily exercises envelopes, signatures, authority state, checkpoints, claims, and gate admission, yet explicit primitive/format acceptance is Phase 2 (`§5`, line 125; `§8`, lines 165–167). A slice cannot be promoted—or satisfy a profile cutover—until every security primitive and format it touches has completed re-audit. “Daybreak and Opus did not forge it” is useful evidence, not proof of soundness.

   **Required change:** make protocol acceptance for slice-used functionality a Phase-1 exit criterion; Phase 2 should audit only newly introduced formats and paths.

2. **“Spike hardened in place” solves duplicate construction but not experimental-to-production promotion.**  
   The same codebase can mature safely, but only with a defined transition: no production credentials/data during spike mode, removal of test bypasses, threat-model reconciliation, clean release provenance, regression completion, and a fresh audit after the last security-affecting hardening change (`§8`, line 165). Otherwise an expedient spike can acquire production status through accumulated patches.

3. **Admissibility by isomorphism is legitimate design guidance, not a substitute for requirements validation.**  
   HIPAA §164.312 specifies safeguards, not an evidence format that auditors automatically “accept.” SLSA, sigstore, RFC 3161, ITGC, and SOC 2 address adjacent but different control objectives (`§7`, lines 143–154). The strategy fails when the analogy is merely syntactic—for example, “cross-lineage” is labeled independent review despite no organizational independence, or a `TrustedTimestamp` lacks an accepted TSA and validation policy.

   The plan partly recognizes this by requiring compliance blessing (`line 154`), but D3 still asks **whether/when** that review happens (`lines 191–194`). Those statements conflict.

   **Required change:** Phase 0 may draft the map internally, but claim naming and production acceptance require target risk/compliance/control-owner validation. Isomorphism should be presented as a hypothesis to validate, not acceptance “riding on precedent.”

4. **The PHI guarantee exceeds the proposed control.**  
   “Must never ingest” cannot be guaranteed by content classification alone (`§1`, line 37). PHI can appear in source, logs, screenshots, binary artifacts, encoded payloads, or model transcripts; classifiers have false negatives. A non-goal also does not remove incident obligations if PHI is accidentally captured.

   **Required change:** define allowed content and data minimization, scanning/refusal as defense-in-depth, treatment of opaque/encrypted artifacts, quarantine/deletion and incident handling, and an explicit residual statement that absence of PHI cannot be cryptographically inferred.

5. **Define “structurally unreachable” before using it as a cutover predicate.**  
   The current phrase is not testable (`§8`, line 181). A disabled feature should have no deployed route/service/executable, credential or secret binding, policy grant, dynamic plugin path, or invocation edge from enabled principals. Activation should require a signed profile transition. CI should inspect the deployment graph and run negative reachability tests under the profile’s adversaries.

## NON-BLOCKING items

1. **The four-boundary decomposition is substantially faithful, with several omissions.**
   - Capability enforcement dropped executable ownership/symlink/TOCTOU qualification; “content identity” alone does not cover the original acb boundary (`§3`, line 81; inventory `acb-7`, `CONSOLIDATED-INVENTORY.md`, lines 239, 334–336).
   - The bootstrap root no longer explicitly owns trust-root provisioning or trusted policy/config selection, and its intended offline/control-plane posture is absent (`§3`, line 82).
   - Dossier is non-authoritative for machine claims, but a compromised UI can still forge what a human believes they approved. The prior proposal explicitly retained browser/session and mis-rendering risk; v3’s “cannot mint a badge” is too absolute (`§3`, line 84).
   - The separate differential verifier for testing/audit is omitted. This is not fatal because the conformance suite remains (`§3`, line 90), but independent semantic cross-checking should survive.

2. **Ledger is not reintroduced as a security-presumptive winner, but the fit premise needs validation.**  
   V3 honestly separates operational fit from unproven security and keeps all three candidates live (`§6`, lines 131–139). That closes the v1 error. However, “very likely already operates SQL Server and AD” is an assumption, not an established requirement (`line 135`). Validate edition/licensing, DBA capability, HA/restore practices, digest-management support, and witness independence before assigning scoring weight. Also remove the suggestion that Phase 1 might begin on A before 0B concludes; Phase 1 is otherwise ordered after 0C (`lines 135, 160–165`).

3. **The language decision is placed too early.**  
   Operability is a valid criterion, and language-neutral protocol plus one authoritative implementation is sound (`§3`, line 90). But choosing Python versus .NET in 0A can pre-decide substrate and deployment outcomes that 0B/0C are meant to discover. In 0A, establish language constraints and evaluation criteria; select the implementation stack in 0C.

4. **“All 147 findings live in C” is inaccurate.**  
   The inventory includes governance authorization defects, capability/secret-release flaws, transport issues, supply-chain problems, and general parser/DoS bugs (`§1`, line 33; inventory lines 132–159, 284–337). C motivates the program, but not every finding is a cryptographic-provenance defect.

5. **“Non-repudiable provenance” is too broad.**  
   Signatures provide evidence under specified key-custody and compromise assumptions; they do not establish human intent or absolute non-repudiation (`§1`, lines 33–35; adversary qualification at §4, line 104). Prefer “attributable, tamper-evident provenance under named assumptions.”

6. **`IndependentReviewAttestation` needs a real independence policy.**  
   Different model lineage is useful diversity, but is not by itself ITGC segregation of duties. The claim must bind reviewer identity, role, organizational authority, conflicts, reviewed subject/digest, policy version, and human approval (`§7`, line 151).

7. **Decision-state text is stale and contradictory.**  
   The header records D1/D2 as approved, while §3 says “owner to ratify” and §9 still lists both as teed up (`lines 3, 73, 191–194`). Correct this before implementers use the document as the authoritative plan.

8. **Monday’s 0A package is underspecified operationally.**  
   Before starting, I would want:
   - a committed matrix schema and initial 147 rows;
   - a defined “distinct mechanism” taxonomy and representative-High selection rule;
   - access to the raw reports and reproducible probes, not only files under one user’s home directory (`lines 6, 59, 161`);
   - named owners/reviewers and acceptance criteria for each 0A artifact;
   - a trust-model template containing assets, data flows, trust zones, claims, adversary capabilities, collusions, residuals, and invariant identifiers;
   - clarification of what D1 fixed versus what remains open in 0C;
   - resolution of D3’s mandatory-versus-optional compliance review.

   These are startup inputs, not reasons to delay initial drafting.

## What I would do differently

1. **Run 0A as four independently reviewable work products**, not one broad gate:
   1. trust/adversary model and invariant registry;
   2. finding reproduction plus mechanism taxonomy;
   3. provisional finding→control→test matrix;
   4. admissibility hypotheses and PHI/data-boundary analysis.  
   Only then freeze the scoring rubric for 0B (`§8`, lines 160–164).

2. **Move the language decision and final claim vocabulary to 0C.**  
   In 0A, define portability, Windows operations, FIPS/HSM integration, deployment, and staffing criteria. Let the bake-off supply evidence before choosing .NET/Python or names such as `TrustedTimestamp` (`§3`, line 90; §7, lines 147–154).

3. **Treat Phase 1 as one repository/history but two formally gated maturity states:** experimental shadow slice and releasable slice. Require protocol acceptance, full security review after hardening, signed release artifacts, and proof that experimental modes are absent from the release (`§8`, line 165).

4. **Define deployment profiles as signed manifests with machine-checkable reachability graphs.**  
   The cutover test should derive enabled code, routes, identities, secrets, policies, and network edges from the manifest rather than relying on prose or configuration flags (`§8`, line 181).

5. **Keep Ledger as the operational-fit hypothesis, not the headline winner.**  
   Fix the scoring rubric before measurements, verify the assumed SQL Server estate, and require witnesses outside the SQL Server/DBA failure domain. On that basis, naming Ledger the current fit leader is honest; naming it the security leader would not be (`§6`, lines 131–139).
