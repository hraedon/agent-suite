---
model: claude-fable-5
datetime: 2026-07-11T05:50 UTC
project: agent-suite
---

# Session Reflection — 2026-07-11 (Plan 008 Phase 0+1 close-out)

**Work summary:** Reviewed the Plan 008 Phase 1 work delivered by the prior two
sessions, fixed four deficiencies, closed both open exit criteria, filed WIs for
the residuals, and updated the plan + claims ledger. Phase 0 and Phase 1 are now
closed out; Phases 2–6 remain (coordinate with Plan 009).

---

## What the review found

1. **The WI-1.3 adversarial corpus never ran in CI.** The interop job (the only
   job with Postgres + regista) didn't include `test_adversarial_corpus.py`;
   the unit jobs have no regista, so every mutation skipped silently — "green
   CI" was true and meaningless for this AC. This is precisely the silent-skip
   failure mode Plan 002 was written against, re-introduced by a new test file
   one commit later. Fixed (corpus in the interop invocation + hard-fail guard
   under `INTEROP_REQUIRE_FACES=1`); 13 tests now run and pass in CI.

2. **ANCHOR_MISMATCH was dead code asserting at the wrong layer.** Nothing ever
   triggered anchoring, so the mutation skipped everywhere; and it asserted
   detection via `replay`, which never consults anchor receipts — had it run,
   it would have failed. Rewritten to trigger real anchoring and assert
   `verify_anchor_receipt` returns `failed`.

3. **The WI-1.2 live proof had never been run.** Ran it against a real Claude
   Code 2.1.207 session on the live operator store. First run FAILED with two
   real defects the 121 fixture tests could not see: the install-time
   `CAIRN_HARNESS_VERSION` pin had gone stale (harness auto-updated to 2.1.207;
   attestation claimed 2.1.206) and `cairn export --since` crashed on regista's
   start+end-together contract. Both fixed; second run PASSED — with concurrent
   events from this session in the proof window, so decoy resistance was
   exercised for real.

4. **WI-1.1's "signer binding" AC was not met.** The offline verifier checked
   chain hashes and anchor roots but no event signatures. Implemented regista
   bundle format v2: the export carries the principal public-key registry and
   the verifier checks ed25519 signatures offline (binding + validity windows),
   counts HMAC events as honestly unverifiable, fails closed on unknown
   schemes, and still accepts v1 bundles with an explicit skipped report. The
   decisive test: forging the LAST event's signature and rehashing the bundle
   passes every chain check and is caught only by the signature check. Also
   made `export_audit_bundle` fail closed (it previously swallowed
   receipt/segment enumeration errors — fail-open in an audit tool).

## On the pattern

The recurring lesson across items 1–3: **fixture tests validate the logic you
wrote; only live/CI execution validates the claim you made.** Both prior
sessions did honest, well-reviewed work and correctly *documented* the last-mile
gaps — but the plan status still read "implementation complete," and each gap
turned out to hide a real defect (never-run tests, wrong-layer assertion, two
live-proof bugs). "Implemented" and "demonstrated" need to stay distinct words
in this portfolio.

## What remains

- Phases 2–6 of Plan 008 (not started; Phase 2 scope overlaps Plan 009).
- regista WI-206 (anchoring watermark/doctor visibility), WI-207 (non-SHA-256
  anchoring test), WI-208 (envelope v5: sign actor_kind/actor_metadata).
- agent-provenance WI-028 (extract e2e_proof helpers into src/cairn).
- agent-suite WI-001 (5 deferred corpus mutations: revoked_key, hook_omission,
  replayed_wake_event, capability_clobber, corrupted_backup).
- The bundled key registry comes from the same store as the events; true
  auditor independence needs out-of-band key-fingerprint cross-checking
  (documented in CL-013's caveat).
