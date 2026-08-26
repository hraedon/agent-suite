
> adversarial-reviewer-headless · gpt-5.6-sol

→ Skill "adversarial-review"
→ Read plans/025-provenance-security-remediation.md
→ Read SOL-V1-REVIEW.md
→ Read CONSOLIDATED-INVENTORY.md
# 1. v2 closes v1

| v1 finding | Status | Assessment |
|---|---|---|
| Diagnosis over-collapse / “97 findings collapse” | **RESOLVED** | v2 correctly demotes C1–C4 to triage categories, acknowledges their heterogeneous controls, and replaces numerical collapse with per-finding demonstration (`§2`, lines 52–62). The evidence-maturity caveat also appears explicitly (`§1`, lines 48–49). |
| Trust-model-first / three provenance questions | **PARTIAL** | The substantive model is now right: authentication, authorization at position, and completeness/non-equivocation are separated (`§3`, lines 66–86). But Phase 0 combines trust-model definition, anchor design, substrate evaluation, and deployment-model selection in one gate (`§8`, line 163). This needs an internal **0A → 0B ordering**: freeze adversaries, guarantees, authority semantics, and component trust boundaries before designing or scoring substrates. |
| C2 temporal authority | **RESOLVED** | v2 distinguishes historical authority, current signing permission, later verifier knowledge, and retroactive compromise invalidation; it anchors authority to authenticated log position rather than caller time (`§3`, lines 76–83). |
| Generic `Verified[T]` too coarse | **RESOLVED** | Scoped claims now include normalized claims, trust-root digest, policy version, checkpoint, completeness range, separate authentication/authorization/storage results, warnings, and verifier version (`§4`, lines 94–102). |
| Serialized results forgeable across process boundaries | **RESOLVED at plan level** | v2 explicitly rejects hidden constructors as a security boundary and requires either local verification or authenticated receipts (`§4`, line 104). The choice remains appropriately in Phase 0. I recommend local proof verification as the default; receipts should be an exception, not the baseline. |
| Caller-controlled trust root/cut | **RESOLVED** | Both must derive from pinned project policy (`§4`, line 106). |
| Signed fields versus display metadata | **RESOLVED** | Authoritative claims are separated from explicitly untrusted mutable display metadata (`§4`, line 108). |
| Verify-every-read availability hazard | **RESOLVED** | v2 specifies ingestion verification, incremental checkpoints, keyed verified projections, invalidation, bounded read proofs, and periodic replay (`§4`, line 110). |
| Fail-closed availability and recovery | **PARTIAL** | The required degraded-state, freshness, recovery, and break-glass concerns are now recognized (`§4`, line 112; `§6`, lines 142–144). However, Phase 0 does not clearly require concrete freshness semantics and break-glass authority as outputs. Those affect the trust model and should not wait for cutover runbooks. |
| Core does not close endpoint/project/socket/process C4 failures | **RESOLVED** | v2 explicitly lists those exclusions and routes them through the finding-to-control matrix (`§4`, line 114). |
| One universal signing envelope is inappropriate | **RESOLVED** | v2 limits sharing to framing and domain separation while retaining principal-specific semantics (`§2`, line 58). |
| Ledger is tamper-evident, not forgery prevention | **RESOLVED** | The distinction between malicious valid appends, history rewrite, omissions, stale views, and bypass is now accurate (`§5`, lines 118–122). |
| External anchors/witnesses are the real boundary | **RESOLVED** | Publisher, signing, custody, witness, checkpoint distribution, rollback/equivocation, cadence, and retention are all named (`§5`, line 122; `§6`, lines 134–146). |
| Substrate should be a threat-modelled bake-off | **RESOLVED** | All three options are live, tested against common adversary scenarios, operational burden is first-class, and there is no presumptive winner (`§5`, lines 120–130). |
| Rebuild-versus-patch false binary | **RESOLVED by explicit owner decision** | v2 adopts incremental vertical replacement rather than a monolithic rewrite (`§7`, lines 150–156). The emergency-containment recommendation was consciously declined because the suite is undeployed (`§7`, line 152). That is an acceptable risk decision, provided the old system is not used with real credentials or deployable data while rebuilding. |
| Reuse boundary requires crypto-protocol re-audit | **RESOLVED** | Reuse is conditional on fresh acceptance of every primitive and format (`§7`, line 156). |
| Legacy evidence containment | **PARTIAL** | Reject/quarantine/re-anchor is correctly identified (`§7`, line 157), but the decision has no explicit deadline. It must be made before the first vertical slice admits any legacy evidence, not left as a general program decision. |
| Phase-4 cutover contradiction | **RESOLVED** | v2 correctly makes cutover a named-invariant whole-program gate and acknowledges the Phase-6 acb Critical (`§8`, lines 169–173). I disagree with making it unconditionally whole-program, however; see the profile-based cutover proposal below. |
| Cairn-first against mutable authority / vertical slice | **PARTIAL** | Phase 1 now proves an end-to-end claim with authority lifecycle, checkpoint, cairn decision, gate, and UI (`§8`, line 164), and Phase 2 pairs cairn with its authority source (`§8`, line 165). Those phases now overlap ambiguously: either Phase 1 already includes the secure cairn/authority path, or Phase 2 does. Label Phase 1 as a disposable spike/pilot and Phase 2 as productionization, or merge them. |
| Data and protocol migration | **PARTIAL** | All requested migration activities now appear (`§8`, line 170), but as an unscheduled “cross-cutting phase.” It needs entry/exit criteria, ownership, ordering relative to each consumer migration, and a point after which legacy writes—not merely legacy verification—are impossible. |
| Finding-to-control matrix | **PARTIAL** | The artifact and row classifications are correctly required (`§2`, line 62), and reproduction requirements are stated (`§1`, line 48). But the Phase-0 gate does not require the matrix or reproductions before architecture freeze (`§8`, line 163). That contradicts lines 48–49 and should be fixed. |
| Explicit adversary model | **RESOLVED** | The adversaries and colluding combinations are enumerated, and each claim must state whom it resists (`§3`, lines 84–86). |
| Verification testing strategy | **PARTIAL** | Adversarial testing and performance measurement are present (`§8`, line 164), but v1’s property/state-machine tests, parser fuzzing, online/offline differential tests, downgrade tests, and fault injection are still not explicit acceptance requirements. |

# 2. Verdict on v2

## **VERDICT: sound-with-changes**

v2 closes the substantive security-model defects from v1. I no longer consider the provenance mechanism itself fundamentally underspecified.

The remaining important issue is structural: the plan grants full design latitude at `lines 8–11`, but its implementation sections still assume:

- the core lives “in regista” (`§4`, line 92);
- cairn remains a separate verifier project;
- agent-suite and agent-notes retain separate gate implementations;
- remediation proceeds largely by current component (`§8`, lines 165–170).

That is not yet reasoning from purpose to structure. It is the existing seven-project topology with a shared library inserted into it.

The plan is safe to enter a redesigned Phase 0 after the convergence checklist below is incorporated. It is not ready to freeze APIs, repositories, or component ownership.

# 3. STRUCTURE proposal

## Greenfield decomposition

I would build **four trust-bearing security boundaries**, only three of which are normally in the runtime data path.

### 1. Provenance kernel

Absorb the trust-bearing portions of **regista + cairn** into one project/release boundary:

- canonical event and envelope protocol;
- append-only log interface and authenticated checkpoints;
- temporal key/authority state machine;
- inclusion/consistency/completeness proof verification;
- scoped claim production;
- local verifier SDK/CLI;
- optional receipt issuer;
- legacy-evidence quarantine and migration tooling.

The log writer, verifier, and witness still run in separate trust zones. “One project” must not mean “trust the server’s self-verdict.” Clients verify proofs locally, and witnesses retain independent checkpoint state.

Cairn should not independently reconstruct key lifecycle, chain semantics, or PASS aggregation. Its useful provenance-analysis semantics become claim types or policy modules in the kernel. A separate differential verifier may exist for testing and audit, but not as a second production interpretation.

**Difference from v2:** the core should not merely be “a library in regista consumed by cairn.” Regista’s log and cairn’s verifier are two halves of one security protocol and should have one specification, conformance suite, release train, and vulnerability boundary.

### 2. Governance and gate engine

Consolidate trust-bearing gate logic currently split across:

- agent-notes review/lifecycle gates;
- agent-suite genesis/release gates;
- assorted acceptance and dual-control checks.

This engine should:

- accept only scoped kernel claims and authenticated caller identity;
- evaluate deterministic, versioned policy;
- emit a context-bound decision event;
- atomically bind the decision to the action it admits;
- own default-DENY, separation-of-duties, transition, and policy-version semantics.

`agent-notes` remains the work-tracking application and projection owner. Its durable governance record is the kernel event history, not mutable tracker rows. `agent-suite` remains orchestration and deployment, not a second policy evaluator.

Genesis and human review are different policies, but they need not be different gate infrastructures.

### 3. Capability enforcement broker

**acb remains separate and trust-bearing.** It sits at an OS/process/secret-release boundary that the provenance kernel cannot enforce.

It should consume authenticated `CapabilityGrant` claims, then independently enforce:

- caller/harness identity;
- executable content identity and ownership;
- environment restrictions;
- short-lived credentials and revocation;
- fail-closed execution.

Do not absorb this into the provenance kernel. That would enlarge the cryptographic TCB with Vault, subprocess, package, and platform-specific code.

### 4. Minimal bootstrap/update root

A reduced `agent-suite` remains security-sensitive because it installs binaries, pins versions, provisions trust roots, and selects policy/configuration. It should be a small offline/control-plane TCB:

- signed lock and artifact verification;
- trusted executable resolution;
- deterministic provisioning;
- rollback and restore verification;
- no independent runtime gate semantics.

This is outside the normal provenance decision path but cannot honestly be called non-trust-bearing.

## Non-trust-bearing applications and infrastructure

### agent-notes

A domain application over the governance engine:

- commands and projections;
- work-item UX;
- no local NullSigner mode;
- no independent authority or transition interpretation;
- projections may be rebuilt from authenticated governance events.

### dossier

A pure human surface:

- renders scoped claims and explicitly untrusted metadata;
- does not manufacture badges or verdicts;
- compromise may mis-render to a human, so browser/session security still matters, but it cannot mint a machine-consumable trusted claim.

### agent-wake

Keep it separate from the provenance architecture:

- wake is delivery, not authority;
- messages need transport authentication, replay control, peer binding, and resource limits;
- a wake message must never itself authorize a transition, secret release, or gate pass;
- receivers re-authorize the requested action through the governance or capability boundary.

This removes most of agent-wake from the provenance TCB. Its current findings remain real transport-security defects, but they should not dictate the kernel architecture.

## Smallest trust-bearing set

For runtime provenance decisions:

1. provenance kernel;
2. governance/gate engine;
3. capability broker, only when capability release is enabled.

For complete deployment security, add the minimized bootstrap/update root.

This is materially smaller than seven mutually trusting projects. It eliminates duplicate lifecycle interpretation, duplicate PASS aggregation, mutable governance sources of truth, and scattered fail-open gate code. It does **not** eliminate endpoint authentication, OS enforcement, parser safety, or supply-chain controls; those remain explicit boundaries.

# 4. Remaining disagreements and convergence checklist

## Remaining disagreements

1. **The plan says shapes are open but prematurely locates the core in regista.**  
   `§4`, line 92 should describe a logical provenance kernel, with repository and process boundaries decided in Phase 0.

2. **Phase 0 needs sequential gates.**  
   Use:
   - **0A:** adversaries, guarantees, temporal authority, deployment trust zones, legacy policy, degraded-state semantics, and candidate decomposition;
   - **0B:** substrate/anchor bake-off against 0A;
   - **0C:** select decomposition, substrate, local-verification/receipt policy, and migration architecture.

3. **Do not make receipts the default.**  
   A receipt authenticates what a verifier said; it does not make the verifier correct. It introduces another high-value signing key, lifecycle, revocation path, freshness problem, and potentially centralized availability dependency. Prefer local verification of bounded proofs. Use receipts only where a consumer cannot host the verifier, and state which verifier-operator compromises they do not resist.

4. **Cutover should be deployment-profile based, not unconditionally whole-program.**  
   If acb is disabled and absent from the supported profile, acb-1 should not block release of the provenance/tracking profile. The gate should require:
   - all invariants for enabled components;
   - disabled components to be structurally unreachable;
   - no unsupported feature represented as secure.

   This is more consistent with v2’s “supported attack surfaces” language than a monolithic seven-project cutover.

5. **Phase 1 and Phase 2 overlap.**  
   Merge them, or define Phase 1 as a throwaway architecture spike and Phase 2 as hardened production implementation. Do not build the same cairn/authority vertical twice.

6. **The matrix and reproductions must be Phase-0 gates.**  
   Before freezing architecture: reproduce all Criticals, representative Highs from every distinct mechanism—not merely each broad C-class—and populate at least provisional control ownership for all 147 findings.

7. **Migration needs a real phase plan.**  
   Specify dual-write/read behavior, checkpoint boundaries, legacy write shutdown, compatibility duration, rollback constraints, and when quarantine becomes permanent rejection.

8. **Testing requirements remain under-specified.**  
   Add mandatory:
   - temporal-authority state-machine/property tests;
   - parser and proof fuzzing with pre-allocation limits;
   - online/offline differential verification;
   - protocol downgrade tests;
   - fork, rollback, stale-checkpoint, and witness fault injection;
   - policy/version-skew tests;
   - projection rebuild equivalence tests.

## Possible over-correction

- **“One library consumed by every component” is too implementation-specific.** It may create language coupling and turn a package version into a distributed trust boundary. Specify one protocol and one authoritative implementation, with local SDK/sidecar forms as needed.
- **A separately-custodied receipt key may add more risk than value** unless a real cross-process constraint demands receipts.
- **A whole-program cutover couples optional infrastructure unnecessarily.** Supported-profile gates produce a smaller, earlier, and more honest secure release.
- **Three full substrate prototypes could become expensive.** Time-box the bake-off and implement only the minimum common workload needed to falsify a candidate: append, rotation, proof, checkpoint, fork/rollback, restore, and representative read performance.

## Convergence checklist before Phase 0

- [ ] Replace “library in regista” with a logical provenance-kernel decision.
- [ ] Add component-decomposition/TCB selection as an explicit Phase-0 deliverable.
- [ ] Split Phase 0 into ordered 0A/0B/0C gates.
- [ ] Decide legacy reject/quarantine/re-anchor semantics before the first slice.
- [ ] Put Critical/representative-High reproduction and the provisional 147-row matrix in the architecture-freeze gate.
- [ ] Choose local proof verification as the default; justify every receipt boundary.
- [ ] Consolidate gate infrastructure while retaining policy-specific schemas.
- [ ] Define agent-wake as non-authoritative transport.
- [ ] Keep acb as a separate enforcement TCB.
- [ ] Make cutover profile-based, with disabled features structurally unreachable.
- [ ] Resolve the Phase-1/Phase-2 overlap.
- [ ] Schedule migration and add explicit verification test families.

With those changes, I expect broad agreement: v2’s trust model and remediation strategy are now sound; the remaining work is to make the plan’s structure match its newly declared design latitude.
