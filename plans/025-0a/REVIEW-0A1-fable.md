# 0A-1 TRUST-MODEL.md — reviewer 1 notes (Claude Fable, 2026-08-25, on v0.1-draft)

Verdict: **accept as draft for second-lineage review**. Charter acceptance criteria met at
drafting level (adversaries incl. collusions; every claim names resisting/non-resisting;
50 invariants each with a test family; legacy = OPEN with recommendation; PHI five
elements; twelve sections). Owner decisions and second review pending.

Findings (none blocking):
1. **Version-skew / downgrade across component versions** is covered only implicitly
   (INV-019 verifier version, INV-025 unknown policy version denies). Consider an explicit
   invariant: a consumer refuses claims from a verifier/protocol version below the pinned
   floor, and mixed-version estates cannot yield PASS from the weaker side. (Plan §8 PV family.)
2. **Checkpoint distribution channel** (how a verifier learns the expected cut out of band)
   is asserted as "signed project policy" but has no invariant of its own; INV-017 assumes a
   retained/pinned prior cut exists. Add an invariant for the initial-pin and pin-update path.
3. **Break-glass two-person rule** (§9) is right for the threat model but is exactly the kind
   of operational burden Plan §6 says must be weighed openly for a small adopter; flag for the
   0B operational-requirements table, not for weakening here.
4. Section 5 "wall-clock may enforce expiry only after pinned state/cut is selected" — good;
   make explicit which zone supplies the clock for `TrustedTimestamp` when no TSA is selected
   (currently: the claim must not issue — correct, keep).
5. Editorial: INV-004 owner "every consuming boundary" is fine but the matrix (0A-3) will need
   one owner per row — expect INV-004 to be cited by many rows with per-boundary controls.

Lineage note: drafter openai/gpt-5.6-sol; reviewer 1 anthropic (Fable); reviewer 2 to be
anthropic Opus on mvmcc02 (security-focused, probe-capable). Two lineages in the loop.
