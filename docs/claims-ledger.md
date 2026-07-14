# Suite claims ledger

**Plan 008 §6.1 / WI-0.2**

This document is the single source of truth for security and assurance claims
made about the agent suite. Every security/assurance statement on the README
and operator docs maps to a ledger entry below. Claims that lack a positive
proof or adversarial proof are marked **provisional** or **experimental** —
never **supported**.

## How to read this ledger

Each entry follows the structure required by Plan 008 §6.1:

- **Protected asset** — what is being defended.
- **Threat actor** — who attacks (or what fails).
- **Trust boundary** — where the boundary sits.
- **Enforcing component** — which component owns the enforcement.
- **Positive proof** — a test or artifact that demonstrates the claim holds.
- **Adversarial/failure proof** — a test that demonstrates tampering or
  failure is detected.
- **Residual risk** — what is explicitly **not** claimed.
- **Supported profiles** — which deployment profiles (A, B, C) the claim
  applies to. See [`claims-ledger-index.md`](claims-ledger-index.md) for
  profile definitions.
- **Maturity** — `supported` (both proofs exist and pass), `experimental`
  (mechanism exists, proofs partial or recently added), `provisional`
  (mechanism incomplete or known defect unfixed).
- **Last verified release** — version tag or `unverified`.

### Deployment profiles

> `agent-suite` is implicitly present in every profile — it is the tool being
> run. It is omitted from `PROFILE_REQUIREMENTS` in code because it has no
> `doctor` command to check; it is listed here for completeness.

| Profile | Description | Required components |
|---------|-------------|---------------------|
| **A** | Provenance core | regista, agent-notes, agent-provenance, agent-suite |
| **B** | Team workflow | Profile A + dossier |
| **C** | Operated full suite | Profile B + agent-capability-broker, agent-wake |

---

## CL-001: Event integrity

| Field | Value |
|-------|-------|
| **Claim** | Events are append-only, signed, and replay-verifiable: the event log cannot be silently modified without detection. |
| **Protected asset** | The durable event log (regista Postgres store). |
| **Threat actor** | A malicious operator or DBA with direct database access who mutates event rows. |
| **Trust boundary** | The Postgres data directory / database connection. |
| **Enforcing component** | regista — canonical envelope, per-work-item hash chain, and global chain. |
| **Positive proof** | `tests/test_interop.py::test_drive_work_item_across_workflow_to_done` — drives a work-item through the canonical workflow and verifies `regista replay` reports zero drift, zero halts, zero warnings on the clean chain. |
| **Adversarial/failure proof** | `tests/test_tamper.py::test_tamper_detection` — Scenario 1 (mutated event body produces `replayed_drift > 0`) and Scenario 3 (forged `prev_event_hash` produces `warnings > 0`). |
| **Residual risk** | The current tamper test uses HMAC keys, not Ed25519 per-principal signing. The envelope/signature path is exercised but the full per-principal asymmetric signing chain (regista Plan 026) is not yet exercised in the suite-level interop test. Replay verifies integrity of recorded events; it does not prove that events were not omitted (deletion is not detected by replay alone — external anchoring, CL-012, addresses that, but is provisional). |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified (no tagged release; tests pass in CI) |

---

## CL-002: Per-principal attribution

| Field | Value |
|-------|-------|
| **Claim** | Every mutation is attributed to a registered principal with a valid signing key; a spoofed actor is detected. |
| **Protected asset** | The actor identity on each event. |
| **Threat actor** | An attacker who modifies the `actor_id` column to attribute a mutation to a different principal. |
| **Trust boundary** | The database row — an attacker with direct DB access changes `actor_id`. |
| **Enforcing component** | regista — canonical envelope binds actor to signature; `regista verify` checks actor↔signer equality. |
| **Positive proof** | `tests/test_interop.py` — the mixed chain contains distinct agent and human actors (`agent`, `reviewer`, `acceptor`), each with their own role registration. The spine-level test asserts `{"agent", "human"} <= {actor_ids}`. |
| **Adversarial/failure proof** | `tests/test_tamper.py::test_tamper_detection` — Scenario 2: spoofed `actor_id` with nulled `canonical_envelope` produces `halted > 0` (HMAC no longer matches). |
| **Residual risk** | The current test exercises HMAC-based attribution, not Ed25519 per-principal signing (regista Plan 026 is not yet landed in the suite-level test). The key-custody threat model (T3) notes that `actor_id` is derived from the authenticated session, not the request body — this is a dossier-side enforcement not tested in agent-suite CI. A compromised signing proxy (T1) can forge validly-signed events attributed to the victim — attribution proves *who signed*, not that the signatory intended the action. |
| **Supported profiles** | A, B, and C |
| **Maturity** | experimental |
| **Last verified release** | unverified |

---

## CL-003: Tamper detection

| Field | Value |
|-------|-------|
| **Claim** | A single-field mutation of event content, signature, actor, or chain hash is detected with a distinct, named failure. |
| **Protected asset** | Any individual event field in the events table. |
| **Threat actor** | A DBA or attacker with write access to the Postgres events table who modifies one field at a time. |
| **Trust boundary** | The Postgres data directory. |
| **Enforcing component** | regista replay verification + agent-suite tamper test. |
| **Positive proof** | `tests/test_tamper.py::test_tamper_detection` — drives a clean chain to `done`, then restores the chain to clean between each scenario and confirms zero drift/halts/warnings on the clean baseline. |
| **Adversarial/failure proof** | `tests/test_tamper.py::test_tamper_detection` — four scenarios, each producing a distinct `ReplayReport` category: (1) mutated payload → `replayed_drift > 0`; (2) spoofed actor → `halted > 0`; (3) forged `prev_event_hash` → `warnings > 0`; (4) forged signature → `halted > 0`. |
| **Residual risk** | Each scenario is applied to a single event and restored before the next. Multi-field or cross-event tamper patterns are not tested. The test uses HMAC keys, not Ed25519 — the signature forgery scenario (4) replaces HMAC bytes, not an asymmetric signature. Deletion of an event (rather than mutation) is not covered by this test — that requires external anchoring (CL-012, provisional). |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified |

---

## CL-004: Cross-face interop

| Field | Value |
|-------|-------|
| **Claim** | A work item can be created by an agent, accepted by a human, and the mixed chain verifies. |
| **Protected asset** | The ability of the two face packages (agent-notes and dossier) to interoperate over a shared regista store. |
| **Threat actor** | Contract drift between the agent face and human face that silently breaks the mixed chain. |
| **Trust boundary** | The face-to-store boundary — each face connects independently to the same regista project. |
| **Enforcing component** | agent-suite interop CI + regista replay. |
| **Positive proof** | `tests/test_interop.py::test_drive_work_item_across_real_faces_to_done` — constructs `agent_notes.core.regista_face.RegistaFace` and `dossier.gateway.RegistaGateway`, drives one work-item across both, and verifies the mixed agent+human chain with zero drift. A spine-level test (`test_drive_work_item_across_workflow_to_done`) proves the workflow composes even without the face packages. |
| **Adversarial/failure proof** | `INTEROP_REQUIRE_FACES=1` in CI makes the face-level test **fail** (not skip) when the face packages are not importable — closing the "skip looks like pass" hole. The tamper test (CL-003) independently proves the chain catches forgery. |
| **Residual risk** | Both interop tests skip when regista or Docker is unavailable — they are not part of the default local test run. The face-level test additionally skips when the face packages are not installed (locally). The test uses a single project, single workflow, and a linear path to `done` — branching, rejection, or concurrent work-item paths are not exercised. |
| **Supported profiles** | B and C (Profile A has no human face) |
| **Maturity** | supported |
| **Last verified release** | unverified |

---

## CL-005: Post-restore integrity

| Field | Value |
|-------|-------|
| **Claim** | A restored store passes replay verification — a backup that was tampered with or corrupted is detected. |
| **Protected asset** | The restored Postgres data after a backup-restore cycle. |
| **Threat actor** | Backup corruption (bit rot, storage failure, tampering with backup media). |
| **Trust boundary** | The restore boundary — the point where backup data is loaded into a running Postgres. |
| **Enforcing component** | agent-suite `verify-restore` + regista `replay`. |
| **Positive proof** | `tests/test_verify_restore.py::test_all_projects_verified` — stubbed replay returns zero drift for all projects; `verify_restore` reports `ok=True`. |
| **Adversarial/failure proof** | `tests/test_verify_restore.py::test_drift_detected` — stubbed replay returns `replayed_drift=2, halted=1` for one project; `verify_restore` reports `ok=False` with `DRIFT_DETECTED` status. Additional tests cover warnings detection (`test_warnings_detected`), unreachable projects (`test_unreachable_project`), and error handling (`test_non_json_output_is_error`). |
| **Residual risk** | Tests use stubbed runners — no live Postgres restore is tested in CI. The `verify_restore` command shells out to `regista replay` per project; if `regista replay` itself has a defect (as F-1/F-2 found in related paths), this test would not catch it. The test verifies that drift *reporting* works, not that a real restore+replay cycle passes end-to-end. |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified |

---

## CL-006: Idempotent bootstrap

| Field | Value |
|-------|-------|
| **Claim** | Re-running bootstrap changes nothing already done — each step is idempotent and a second run is a no-op. |
| **Protected asset** | The installed suite state (schemas, roles, keys, services). |
| **Threat actor** | Not a security threat — an operational hazard (accidental re-run that clobbers existing state). |
| **Trust boundary** | The bootstrap command boundary. |
| **Enforcing component** | agent-suite `bootstrap` module. |
| **Positive proof** | `tests/test_bootstrap.py::test_second_run_is_noop` — second run with "already exists" responses from component CLIs produces `ALREADY_DONE` status for provision, faces, and provenance steps, and `ok=True`. |
| **Adversarial/failure proof** | `tests/test_bootstrap.py::test_key_clobber_refused` — when `regista provision` returns "refuse: would clobber existing key", bootstrap reports `REFUSED` status and `ok=False`. `test_dry_run_acts_on_nothing` proves `--dry-run` issues zero commands. `test_missing_postgres_fails_with_named_message` proves a failed prerequisite aborts subsequent steps. |
| **Residual risk** | All tests use stubbed runners — no live infrastructure is provisioned. The README notes bootstrap is "contract-gated (scaffolded, awaiting component CLIs)" — full idempotency can only be proven when the component `provision`/`install-harness` contracts are landed. Per-user onboarding (step 7) is marked "not yet implemented" in the test. |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified |

---

## CL-007: Honest health

| Field | Value |
|-------|-------|
| **Claim** | `doctor` reports absent components as absent (not ok), unreachable components as failed, and never smooths a missing or unrecognizable health shape into "healthy." |
| **Protected asset** | The operator's trust in the health report. |
| **Threat actor** | A component that emits malformed or incomplete health JSON that the umbrella misclassifies as healthy. |
| **Trust boundary** | The `doctor --json` contract boundary between agent-suite and each component. |
| **Enforcing component** | agent-suite `doctor` module. |
| **Positive proof** | `tests/test_doctor.py::test_absent_tier2_is_absent_not_failure` — an absent Tier 2 component is `ABSENT`, not `FAILED`, and `suite_ok` remains `True`. `test_spine_absent_fails_suite` — an absent spine component makes `suite_ok=False`. `test_doctor_only_reads_never_writes` — doctor issues only `doctor --json` calls, no writes. |
| **Adversarial/failure proof** | `tests/test_doctor.py::test_missing_ok_with_empty_checks_is_failed`, `test_empty_dict_is_failed`, `test_missing_ok_with_all_ok_checks_is_failed`, `test_missing_ok_no_checks_key_is_failed` — when a component omits the top-level `ok` boolean, the umbrella treats it as `FAILED` regardless of the checks list. `test_nonzero_exit_is_failed` and `test_non_json_stdout_is_failed` cover unreachable/malformed cases. |
| **Residual risk** | **Holistic review F-6** found that the doctor compatibility path inferred health from the checks list when `ok` was missing. This is now fixed: the doctor requires a top-level `ok` boolean and treats its absence as `FAILED` (`doctor.py:235-242`). The legacy compatibility path has been removed. Unrecognized status vocabulary (e.g., a component returning `"status": "degraded-but-fine"`) is not explicitly tested beyond the `degraded` boolean field. |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported (F-6 fixed) |
| **Last verified release** | unverified |

---

## CL-008: Secret safety

| Field | Value |
|-------|-------|
| **Claim** | Secrets are resolved at the edge (via `regista.secrets.resolve`), never logged, committed, or emitted in doctor, plan, or bootstrap output. |
| **Protected asset** | Private signing keys, DSN passwords, and secret-backend credentials. |
| **Threat actor** | An operator or CI system that accidentally commits a secret value to the repository or leaks it in a log. |
| **Trust boundary** | The secret-backend-to-process boundary — secrets cross this only via `regista.secrets.resolve`, never as literals in config files. |
| **Enforcing component** | agent-suite `bootstrap` + regista secret resolver + the identifier gate. |
| **Positive proof** | `docs/bootstrap-contract.md` §2 — "Secrets are backend refs (`vault:` / `akv:` / `wincred:` / `file:`), never literals in the system file." `tests/test_bootstrap.py::test_dry_run_acts_on_nothing` — `--dry-run` prints the plan without acting, and the plan contains no secret values. The `AGENTS.md` hard rule: "Never hold a secret; resolve it." |
| **Adversarial/failure proof** | `tests/test_bootstrap.py::test_dry_run_acts_on_nothing` — `--dry-run` prints the plan without acting, and the plan contains no secret values. The `AGENTS.md` hard rule: "Never hold a secret; resolve it." F-4 (deployment identifier scrub) is fixed — committed deployment docs use placeholders only. F-5 (agent-notes DSN fallback) is fixed — `tests/test_config.py::test_regista_dsn_does_not_fallback_to_native` verifies `REGISTA_DSN` does not satisfy the native agent-notes DSN. |
| **Residual risk** | **Holistic review F-4** was based on an incorrectly-scoped hand-rolled denylist that classified allowed homelab identifiers (machine names, private network addresses, principal names, key-ID prefixes) as forbidden work-domain identifiers. The canonical suite identifier gate (`~/.config/agent-suite/forbidden-identifiers`) has been installed; it scans only tracked files and passes cleanly. The key-custody threat model (T1) documents that the trusted-signing-proxy model means dossier holds private keys transiently in process memory — a compromised dossier process can re-fetch keys. No automated test verifies that secret values are absent from all generated output. |
| **Supported profiles** | A, B, and C |
| **Maturity** | provisional (F-4/F-5 fixed; canonical identifier gate installed; no secret backend CI-qualified; no dedicated secret-leak negative test) |
| **Last verified release** | unverified |

---

## CL-009: Lock integrity

| Field | Value |
|-------|-------|
| **Claim** | `SUITE.lock` pins exact component versions and regista schema/workflow/envelope versions, and `doctor` detects drift between the lock and installed components. |
| **Protected asset** | The known-good component set — the reproducibility of a suite deployment. |
| **Threat actor** | Silent component version drift (a `pip install` that upgrades a component without updating the lock). |
| **Trust boundary** | The `SUITE.lock` file — the committed manifest vs. the installed reality. |
| **Enforcing component** | agent-suite `lock` module + `doctor` drift detection. |
| **Positive proof** | `tests/test_lock.py::test_matching_lock_no_drift` — matching versions produce `matches=True, drift=[]`. `test_doctor_lock_section_reports_match` — doctor with a matching lock reports `matches=True`. `test_serialize_is_tomllib_parseable` — the lock file is valid TOML. `test_atomic_write_does_not_leave_partial` — write uses temp+rename. |
| **Adversarial/failure proof** | `tests/test_lock.py::test_version_mismatch_is_named_drift` — a version mismatch produces a `VERSION_MISMATCH` drift entry with component, locked, and current values. `test_quad_mismatch_is_named_drift` — a schema version change produces a `QUAD_MISMATCH` entry. `test_component_missing_from_lock_is_unexpected` and `test_component_in_lock_but_absent_is_missing` cover absent/unexpected components. `test_doctor_lock_section_reports_drift` — doctor with a version mismatch reports `matches=False`. `test_doctor_survives_malformed_lock` — malformed TOML is reported as `matches=False` with "unreadable" note. |
| **Residual risk** | Lock drift is detected by comparing `--version` output, not by verifying cryptographic integrity of the installed packages. A component that reports a false version string would not be caught. The lock does not pin transitive dependencies — only the six suite components. |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified |

---

## CL-010: Key rotation safety

| Field | Value |
|-------|-------|
| **Claim** | An unknown or revoked key status raises at startup or verification time; the system never silently proceeds with an unregistered signer. |
| **Protected asset** | The key registry — the set of valid signing keys per principal. |
| **Threat actor** | An attacker who uses a revoked key to sign events after revocation. |
| **Trust boundary** | The key registry boundary — `regista verify` reads the registry at verify time, not a cached copy. |
| **Enforcing component** | regista — key registry, `valid_from`/`valid_to` windows, `unregistered-signer` failure. |
| **Positive proof** | `docs/key-custody-threat-model.md` T5 — "regista verify reads the registry at verify time, not a cached copy. A revoked key produces an `unregistered-signer` failure for post-revocation events." `valid_from`/`valid_to` windows are the design (regista Plan 026 WI-3.1). |
| **Adversarial/failure proof** | `tests/test_adversarial_corpus.py::test_adversarial_mutation` (mutation `REVOKED_KEY`) — generates an Ed25519 keypair, registers the public key, creates an Ed25519-signed event, verifies the principal binding passes, revokes the key, and verifies the binding now fails with `key-revoked`. Exercises the `verify_event_principal_binding` path (regista Plan 026), not `replay`. |
| **Residual risk** | The test exercises Ed25519 key revocation via `verify_event_principal_binding`, not the full `replay` chain. The key-custody threat model (T5) identifies "a verifier uses a stale public-key registry snapshot" as a threat — the mitigation depends on regista always reading the live registry, which is not verified by an agent-suite test. Key rotation cadence is documented in `docs/key-operations.md` but not enforced automatically. |
| **Supported profiles** | B and C (Profile A has no human principals requiring rotation) |
| **Maturity** | experimental (positive proof via Ed25519 revocation test; full `replay`-level revocation detection not yet exercised) |
| **Last verified release** | unverified |

---

## CL-011: Delegation chain

| Field | Value |
|-------|-------|
| **Claim** | `on_behalf_of` is integrity-protected (included in the signed envelope) and temporally validated (the delegation is valid at the time of signing). |
| **Protected asset** | The delegation attribution on agent-signed events — proving which human an agent acted for. |
| **Threat actor** | A stolen agent key that attempts to attribute work to a human who did not delegate (T4 in the threat model). |
| **Trust boundary** | The agent-to-store boundary — the agent signs with its own key but records `on_behalf_of` in the envelope. |
| **Enforcing component** | regista — envelope includes `on_behalf_of`, verification checks the delegation chain. |
| **Positive proof** | `docs/key-custody-threat-model.md` T4 — "Agent-signed events are attributable to the agent principal, not the human — a stolen agent key forges the agent, not the human." The interop test's face-level path includes a cross-lineage reviewer (a different agent actor) demonstrating distinct agent principals. |
| **Adversarial/failure proof** | No test exercises a forged `on_behalf_of` field or a temporally invalid delegation. The tamper test (CL-003) does not include a delegation-field mutation scenario. |
| **Residual risk** | The `on_behalf_of` field's inclusion in the signed envelope and its temporal validation are specified in regista Plan 026 but not exercised in agent-suite tests. The threat model (T4) notes "a stolen agent key can forge that agent's actions within its project" — delegation proves *which agent* signed, not that the delegation was authorized by the named human. Agent key rotation is independent of human key rotation, so a rotated agent key's post-rotation events should fail — but this is untested at the suite level. |
| **Supported profiles** | B and C |
| **Maturity** | experimental |
| **Last verified release** | unverified |

---

## CL-012: External anchoring

| Field | Value |
|-------|-------|
| **Claim** | Anchor receipts commit to event content (not just identifiers), so a post-hoc modification of event content, signature, actor, or chain hash is detectable by comparing the external receipt to the live store. |
| **Protected asset** | The event log's integrity against an attacker who can modify both the events table and the anchor receipts. |
| **Threat actor** | A malicious DBA who rewrites event content while preserving event UUIDs, leaving the external anchor root unchanged. |
| **Trust boundary** | The external anchoring boundary — the point where event content is committed to an external system (anchor receipt). |
| **Enforcing component** | regista Plan 019 — `compute_content_anchor`, `verify_content_anchor`, `AnchorProvider` protocol. |
| **Positive proof** | `tests/test_anchoring.py::TestAnchoringIntegration::test_verify_anchor_receipt_confirmed` — a clean anchor over a single event verifies as `confirmed`. `TestComputeContentAnchor` — 7 tests verify the anchor is deterministic and changes with each binding field (chain head, project, seq, envelope version, hash algorithm) including adversarial collision tests. `TestVerifyContentAnchorChainIntegrity` — 3 tests verify chain link validation and genesis handling. `TestVerifyContentAnchorPayloadHash` — 2 tests verify `payload_canonical_hash` consistency. |
| **Adversarial/failure proof** | `tests/test_anchoring.py::TestAnchoringIntegration` — 6 tamper tests: tampered root, payload, signature, actor, prev_global_hash, and envelope each produce `FAILED`. `TestAnchoringPayloadMutationIntegration` — 2 tests document the payload-only-mutation limitation (mutation of `payload` jsonb without touching `canonical_envelope` is NOT detected by the anchor; signature verification during replay would catch this). `TestCreateAnchorReceiptConflictPersistence` — 3 tests verify ON CONFLICT handling, retryable upgrade, and no-downgrade. `TestTriggerAnchoringFailurePersistence` — 3 tests verify failure persistence and retry. |
| **Residual risk** | The anchor does not detect mutation of `actor_kind` or `actor_metadata` (not included in the canonical signing envelope — see spec §17.9.2; tracked as regista WI-208). The `payload` jsonb column can be mutated without detection if `canonical_envelope` is left unchanged. Deletion of the last event in a batch leaves the anchor covering remaining events. The pre-anchor window (events after the last confirmed anchor) is defended only by HMAC/Ed25519. OTS verify returns `pending` when a Bitcoin node is unreachable, which can mask a tamper signal (BC-300). The `committed` status is declared but never set by any provider, and stale pending/retryable receipts block the anchoring watermark with no doctor visibility (both tracked as regista WI-206). |
| **Supported profiles** | A, B, and C |
| **Maturity** | experimental (bundle v2 export + offline verification implemented, including offline event-signature verification against the bundled principal key registry — 2026-07-11) |
| **Last verified release** | unverified |

---

## CL-013: Offline verification

| Field | Value |
|-------|-------|
| **Claim** | An exported bundle can be verified without production database access or private keys — a third-party auditor can independently confirm the integrity of the event chain. |
| **Protected asset** | The ability to audit the event log without trusting the production system. |
| **Threat actor** | A malicious operator who presents a selectively edited export to an auditor. |
| **Trust boundary** | The export boundary — the point where event data leaves the production system and enters the auditor's environment. |
| **Enforcing component** | agent-provenance — bundle export and verification (Plan 009); live proof (`src/cairn/proof.py`). |
| **Positive proof** | `tests/test_e2e_proof.py::test_happy_path_passes` — a clean session with correct session binding, harness version, tool calls, digests, correlation marker, and chain integrity passes all checks. `test_run_proof_passes_with_clean_verifier_report` — the proof passes when the canonical verifier reports all checks clean. `test_chain_integrity_clean_report_passes` — chain integrity check passes on a clean VerificationReport. |
| **Adversarial/failure proof** | `tests/test_e2e_proof.py` — 15 negative tests covering every F-2 acceptance case: `test_concurrent_decoy_session_does_not_satisfy_proof` (session_binding), `test_stale_events_before_baseline_not_picked_up` (session_binding), `test_mutated_prev_global_event_hash_detected` (chain), `test_missing_event_detected`, `test_wrong_digest_detected` (digest), `test_empty_events_fails_clearly` (session_binding), `test_correlation_marker_not_referenced_fails` (correlation), `test_unknown_harness_version_fails` (harness_version), `test_chain_integrity_signature_failure_detected`, `test_chain_integrity_hash_mismatch_detected`. Each test asserts both `not result.passed` and the specific named check that failed. |
| **Residual risk** | The live proof discovers the launched session by finding the post-baseline session whose tool calls reference a unique correlation file, rather than capturing a session ID up-front (Claude Code's hook protocol doesn't expose it before the session runs). The session-binding/digest/correlation logic runs through the script's own SQL+Python rather than a public cairn API (the chain check itself is canonical via `cairn verify` CLI). **WI-1.2 update (2026-07-11):** `tests/test_proof_wiring.py` exercises `_query_events` SQL round-trip, `_run_canonical_verifier` subprocess path, and `_parse_verifier_report` JSON parse against a real regista store. **Live proof RUN 2026-07-11 against a real Claude Code 2.1.207 session on the live operator store — PROOF PASSED**, with concurrent events from another live session in the proof window (concurrent-decoy resistance exercised for real). The first run caught and fixed two defects: a stale install-time harness-version pin (now live-detected at session start) and a `cairn export --since` crash (open half-window now completed). The proof remains a manual operator runbook, not a CI job (needs live harness + store). regista bundle v2 now verifies asymmetric event signatures offline against the bundled principal key registry; HMAC-signed events are counted `signatures_unverifiable` (the secret is deliberately not exported) and an unknown scheme fails closed. Caveat: the bundled key registry comes from the same store as the events — for independence from a malicious operator the auditor must cross-check key fingerprints out-of-band. Tracked as regista WI-209 (bundle v3): derive registry trust from the anchored chain (`principal_enrolled` events carry the fingerprint inside the anchored timeline), enforce enrollment-before-use ordering, report anchor coverage per binding, and accept auditor-pinned fingerprints — leaving the genesis window and unanchored tail as the named residuals. |
| **Supported profiles** | A, B, and C |
| **Maturity** | experimental (offline bundle verification with signature verification implemented; live proof passed against a real session 2026-07-11) |
| **Last verified release** | unverified |

---

## CL-014: Upgrade safety

| Field | Value |
|-------|-------|
| **Claim** | Upgrade is an evidence-producing transition with a rollback path: the lock advances only after advancement checks pass, and rollback is refused across schema migration boundaries. |
| **Protected asset** | The suite's version coherence — the guarantee that a deployed set of components is the set that passed interop. |
| **Threat actor** | Not a security threat — an operational hazard (an upgrade that silently advances to an incompatible version or a rollback that crosses a schema migration). |
| **Trust boundary** | The `SUITE.lock` file — the transition point between one known-good set and the next. |
| **Enforcing component** | agent-suite `upgrade` module. |
| **Positive proof** | `tests/test_upgrade.py::test_upgrade_check_only_is_read_only` — `--check` discovers advancements via read-only `pip` calls without writing. `test_upgrade_dry_run_does_not_act` — `--dry-run` produces `SKIPPED` apply steps. `test_rollback_succeeds_when_schema_matches` — rollback to a prior lock with matching schema version succeeds and writes the lock file. |
| **Adversarial/failure proof** | `tests/test_upgrade.py::test_rollback_refuses_schema_migration_boundary` — rollback across a schema version boundary (38 → 37) is `REFUSED_MIGRATION_BOUNDARY` with `ok=False`. `test_rollback_fails_when_git_ref_missing` — a bad git ref fails with `FAILED` status. `test_rollback_refuses_when_current_schema_unknown` — rollback refuses when it cannot determine the current schema version. `test_upgrade_without_lock_fails` — upgrade without a lock file fails. `test_upgrade_unknown_component_fails` — unknown component name fails. |
| **Residual risk** | All tests use stubbed runners — no live `pip install` or `git` operations are tested. The upgrade does not run the interop test before advancing the lock (that is a manual or CI gate, not enforced by the `upgrade` command itself). Rollback reinstalls components via `pipx install` but does not verify that the reinstalled versions match the target lock. The migration boundary check compares schema versions only — workflow or envelope version changes that require migration are not separately gated. |
| **Supported profiles** | A, B, and C |
| **Maturity** | supported |
| **Last verified release** | unverified |
