# Consolidated Security-Findings Inventory — Whole-Estate Daybreak Review

Working reference with integrated reproduction status. Original source reports live in
`~/wi337-collision-evidence/daybreak-*.txt`; crown-jewel verdicts in `verify-sec*.jsonl`.

- **Total findings: 147** across 10 component reports.
- **Verified findings: 83** — 13 regista trust-log crown-jewel findings plus 70 Phase 0A-2
  selections. Of these, 82 reproduced the mechanism and one (`crypto-4`) remains
  `not-reproducible` pending a Windows DPAPI executor.
- **Unverified findings: 64.** Their severities remain Daybreak's calibration. Items tagged
  *"suspected, needs reproduction"* in-report are flagged below.
- Reviewed refs differ per component: regista family at `7707c81`; cairn `74471ad`;
  dossier `d775b6d`; agent-suite `a153213`; agent-notes `235c2b6`; agent-wake `f6a0eed`;
  acb `f2df972`.

> Overlap caveat: `regista-crypto`, `regista-cli`, `regista-persist` are **the same codebase**
> as the crown-jewel trust-log scan (all at `7707c81`), run as separate Daybreak passes over
> different subsystems. Several of their findings re-discover crown-jewel SECs (called out in
> §5 Dedup). They are listed as distinct findings because they were filed as distinct findings,
> but a fix collapses them.

---

## 1. Executive tally

### Component × severity
(crown-jewel `trustlog` row uses **VERIFIED** severity; all others use Daybreak-stated severity)

| Component | Crit | High | Med | Low | Total | Rating |
|---|---:|---:|---:|---:|---:|---|
| regista trust-log (crown jewel, SEC-01..13) | 0 | 5 | 5 | 3 | 13 | **verified** |
| regista-crypto | 0 | 4 | 2 | 1 | 7 | Daybreak |
| regista-cli (external attack surface) | 0 | 3 | 6 | 2 | 11 | Daybreak |
| regista-persist | 4 | 6 | 3 | 3 | 16 | Daybreak |
| cairn (agent-provenance verifier) | 2 | 13 | 6 | 1 | 22 | Daybreak |
| dossier | 0 | 5 | 9 | 3 | 17 | Daybreak |
| agent-suite | 0 | 9 | 7 | 0 | 16 | Daybreak |
| agent-notes | 0 | 9 | 4 | 2 | 15 | Daybreak |
| agent-wake | 0 | 9 | 5 | 0 | 14 | Daybreak |
| acb (agent-capability-broker) | 1 | 10 | 4 | 1 | 16 | Daybreak |
| **TOTAL** | **7** | **73** | **51** | **16** | **147** | |

### Verified verdict tally

This tally covers all 147 inventory rows. `confirmed-at-different-severity` means the mechanism
reproduced but the verified severity or severity-carrying scope differs from Daybreak.

| Verified verdict | Count |
|---|---:|
| confirmed | 75 |
| confirmed-at-different-severity | 7 |
| not-reproducible | 1 |
| unverified | 64 |
| **TOTAL** | **147** |

### Component × VERIFIED severity (reproduced mechanisms only)

`crypto-4` is excluded because its Windows-only mechanism remains `not-reproducible`; unverified
rows are also excluded. Mixed labels are binned consistently with the existing crown-jewel tally
(`Medium-High` as High; SEC-06 `Low-Medium` as Medium; SEC-07 `Low-Medium` as Low).

| Component | Crit | High | Med | Low | Reproduced |
|---|---:|---:|---:|---:|---:|
| regista trust-log (SEC-01..13) | 0 | 5 | 5 | 3 | 13 |
| regista-crypto | 0 | 3 | 0 | 0 | 3 |
| regista-cli | 0 | 3 | 0 | 0 | 3 |
| regista-persist | 4 | 6 | 0 | 0 | 10 |
| cairn | 2 | 11 | 1 | 0 | 14 |
| dossier | 0 | 4 | 1 | 0 | 5 |
| agent-suite | 0 | 8 | 1 | 0 | 9 |
| agent-notes | 0 | 8 | 0 | 0 | 8 |
| agent-wake | 0 | 7 | 0 | 0 | 7 |
| acb | 1 | 9 | 0 | 0 | 10 |
| **TOTAL** | **7** | **64** | **8** | **3** | **82** |

### Systemic-class × severity
(each finding assigned ONE primary class; crown-jewel at verified severity)

| Class | Crit | High | Med | Low | Total |
|---|---:|---:|---:|---:|---:|
| **C1** Trust the unverified input | 4 | 18 | 5 | 1 | **28** |
| **C2** Retired/rotated/revoked keys retain authority | 0 | 9 | 2 | 0 | **11** |
| **C3** Signatures/authorizations not bound to context | 0 | 14 | 4 | 2 | **20** |
| **C4** Fail-open gates / missing authorization boundary | 2 | 22 | 12 | 2 | **38** |
| **C5** Other (DoS, injection/SSRF, TOCTOU, attribution, crypto-confusion) | 1 | 10 | 28 | 11 | **50** |
| **TOTAL** | **7** | **73** | **51** | **16** | **147** |

Headline: **C4 (fail-open / missing authz, 38)** and **C1 (trust unverified rows/artifacts, 28)**
dominate the high-severity mass. Together with **C3 (unbound signatures, 20)** and
**C2 (retired-key authority, 11)** the four systemic classes account for **97 of 147** findings;
C5 (50) is the long tail of DoS/TOCTOU/injection/attribution.

### Crown-jewel verified-severity corrections vs Daybreak

| SEC | WI | Daybreak | VERIFIED (true) | Verdict |
|---|---|---|---|---|
| SEC-01 | WI-351 | Critical | **High** (latent Critical) | CONFIRMED; offline bundle path not yet reachable (hardcoded `action_credentials={}`), so live/replay only today — becomes Critical when the credential section ships. Hard blocker. |
| SEC-02 | WI-352 | High | **High** | CONFIRMED end-to-end on Postgres. One current root replays a stored k-of-n signature array. |
| SEC-03 | WI-353 | High | **High** (offline) | CONFIRMED. Online verifier enforces validity window; offline replay/bundle discards it (online/offline divergence). |
| SEC-04 | WI-354 | High | **Medium-High** | CONFIRMED mechanism; public writer refuses the backdated append (wall-clock), so needs direct DB insert + registrar key. |
| SEC-05 | (dup WI-342) | High | **High — already tracked** | CONFIRMED but **duplicate of WI-342**. Close as dup. |
| SEC-06 | WI-357 | High | **Low-Medium** | CONFIRMED; private-module-only reachability, CLI structurally refuses the path. Real defect = docstring offering it as co-equal. |
| SEC-07 | WI-358 | High | **Low-Medium** | PARTIAL. `occurred_at` unreachable from any public API; private-writer footgun + spec question against §5.12. |
| SEC-08 | WI-356 | Medium | **Medium** | CONFIRMED. Not a dup of WI-346 (different field: payload `principal_kind` vs envelope `entity_kind`). No gate reads it today → latent. |
| SEC-09 | WI-359 | Medium | **Medium** (poss Med-High) | CONFIRMED, 2-cache runtime repro both directions (tool said "suspected"). |
| SEC-10 | WI-360 | Medium | **Low-Medium** | CONFIRMED mechanism; compensating controls (durably records `evidence_verified=NULL`, release gate fails closed). |
| SEC-11 | WI-355 | Medium | **Medium** | CONFIRMED ×2 incl. single-column stealth variant. One `UPDATE` flips a strict-profile gate. Detection exists (`replay()`) but assurance API doesn't consume it. |
| SEC-12 | WI-361 | Low | **Low** | CONFIRMED. Offline-verifier DoS only. |
| SEC-13 | WI-362 | Low | **Low** | CONFIRMED. Attribution/`signer_id` forgery by an existing rotated-in root; no authority bypass. |

---

## 2. Cross-component patterns (one root cause, many findings)

The point of the review: the same structural defect recurs across independently-authored components.
Fixing the pattern collapses many findings.

### C1 — "Trust the unverified input" (28 findings)
A verifier/gate/UI/writer consumes a mutable DB row, projection, imported artifact, manifest, or
component output **without** verifying signature / reconciling row-vs-signed-envelope / checking
replay success.
- **Regista:** SEC-08, SEC-11; persist-1, persist-2, persist-4, persist-8, persist-9
- **cairn:** cairn-05, cairn-06, cairn-08, cairn-16
- **dossier:** dossier-1, dossier-2, dossier-4
- **agent-suite:** as-1, as-2, as-4, as-6, as-8, as-9, as-10
- **agent-notes:** an-7, an-8, an-15
- **agent-wake:** aw-7
- **acb:** acb-1, acb-5, acb-9

  **The "assurance/gate/UI trusts mutable rows" sub-collision** (this is the WI-337/SEC-11 thread
  that motivated the whole exercise): **SEC-11** ≡ persist-2 (+`_ops.py:133`) ≡ dossier-2 ≡
  dossier-4 ≡ an-8 ≡ persist-9 ≡ aw-7. A row/projection is read into an authority decision without
  reconciling it against its signed envelope. One reconciliation invariant, enforced everywhere,
  closes all of them.

### C2 — "Retired/rotated/revoked keys retain authority" (11 findings)
A key that was rotated out, revoked, superseded, expired, or removed can still sign / authenticate /
forge, or old signatures replay.
- **Regista:** SEC-01, SEC-03, SEC-06; crypto-2
- **cairn:** cairn-10 (retired keys forge legacy history), cairn-11 (revocation bypass via
  lexicographic timestamp compare), cairn-13 (retired *first* key forges integrity-marker MAC)
- **dossier:** dossier-12 (session cookie authoritative after account/authorization revocation)
- **agent-wake:** aw-4 (`secrets remove` doesn't revoke the running key), aw-9 (rotation leaves
  previous key fully authoritative, no expiry)
- **acb:** acb-12 (retired AppRole SecretID valid indefinitely after "successful" rotation)

### C3 — "Signatures/authorizations not bound to context" (20 findings)
A signature is valid but doesn't bind event id/seq/predecessor/nonce, source identity, project,
actor, idempotency key, or **executable identity** → replay / relabel / substitution.
- **Regista:** SEC-02 (no event-id/seq/nonce), SEC-04 (authority via caller timestamp not chain
  position), SEC-07 (validity via caller `occurred_at`), SEC-13 (rotated-in `signer_id` unbound);
  crypto-3 (rotation client = raw cross-protocol signing oracle); persist-3 (entity-namespace
  collision — events not bound to `(entity_kind, entity_id)`)
- **cairn:** cairn-03 (retroactive/cross-session scope attestation), cairn-04 (attestation session/
  principal not bound to signer)
- **dossier:** dossier-5 (`on_behalf_of` delegation not authorized), dossier-9 (entity type-confusion)
- **agent-suite:** as-11 (one suite-service key across every project — not project-bound)
- **agent-notes:** an-5 (records unresolved actor → `null`/spoofed), an-9 (outbox sig not bound to project; cross-project operation forgery, actor unchanged)
- **agent-wake:** aw-1 (identity outside HMAC), aw-2 (no nonce → replay), aw-3 (source relabel on
  shared key), aw-6 (`reply.source` not bound to connection), aw-13 (idempotency key unsigned),
  aw-14 (dedupe not bound to source)
- **acb:** acb-7 (`trusted_argv` authenticates a pathname, not executable identity)

### C4 — "Fail-open gates / missing authorization boundary" (38 findings)
A gate/authorization decision defaults permissive, is bypassable, or a missing/invalid input yields
broad rather than zero authority.
- **Regista:** SEC-05 (public genesis API, bare `gate_passed=True`), SEC-10 (default approval
  verifier `None`); cli-1 (workflow-scope authz bypass), cli-2 (low-priv mints project-trusted
  artifacts), cli-3 (credentials to every bearer), cli-6 (indefinite hook lease), cli-7 (truncated
  prefix → `VALID` without `--expect-head`), cli-11 (`/ready`,`/metrics` unauth); persist-7 (approval
  unsigned/permissive default), persist-13 (epoch trigger permits insert while identity absent)
- **cairn:** cairn-01 (filtered mode deletes real chain-break violations), cairn-02 (bundle-chain
  merge launders unverified → PASS, `all_ok` gap), cairn-07 (signatureless HMAC receipt counts as
  coverage), cairn-12 (un-MACed "legacy" verdict passes), cairn-15 (role gate fail-open for
  operator/unknown), cairn-20 (fixture-only conformance probe returns gating PASS)
- **dossier:** dossier-3 (replay `halted`/warnings treated as intact), dossier-13 (legacy revocation
  bypasses dual-control when lifecycle project absent), dossier-14 (config loader checks only
  `S_IWOTH`)
- **agent-suite:** as-3 (truthy non-boolean / ignored exit codes), as-7 (lock revision pin skipped
  when no revision), as-12 (dual-control fabricates principals from arbitrary strings), as-13
  (genesis verdict not consumed by first write), as-14 (workflow permits non-human acceptance),
  as-16 (opt-in exit semantics: blocked gates return 0)
- **agent-notes:** an-1 (self-review via `--same-lineage-acknowledged`, no operator authority),
  an-2 (lineage registry validation fails open under pinned dep), an-3 (native mode: no project/admin
  boundary), an-4 (gate-exempt `open→done`), an-6 (native verifier accepts unsigned ops / NullSigner),
  an-10 (`attest-gate` no operator authz), an-14 (web viewer unauthenticated by default)
- **agent-wake:** aw-5 (socket peer self-asserts adapter, no auth)
- **acb:** acb-2 (`harnesses` not enforced at checkout), acb-3 (caller substitutes Vault plane via
  env), acb-4 (non-Playwright MCP grants invisible to doctor), acb-6 (rogue findings are `warn` →
  exit 0), acb-8 (loader env vars `LD_PRELOAD`… bypass `trusted_argv`)

---

## 3. Full inventory (grouped by class, then component)

Severity column: **DB** = Daybreak-stated; **V** = VERIFIED severity where previously recorded.
**Verified** records the execution verdict and second-lineage status. `~` prefix on description =
report marks it "suspected, needs reproduction".

### Class C1 — Trust the unverified input

| ID | Component | DB | V | Verified | Location | Description |
|---|---|---|---|---|---|---|
| SEC-08 | trustlog | Med | Med | confirmed (2L: CONCUR) | `_trust_log.py:1917-1947`,`:2001-2038` | Principal registration/canonical kind never replayed; enrollment-supplied `principal_kind` trusted |
| SEC-11 | trustlog | Med | Med | confirmed (2L: CONCUR) | `_ops.py:122-157`,`_assurance.py:198-415`,`_lineage.py:112-147` | Assurance/gate results trust mutable DB columns without verifying signatures |
| persist-1 | persist | Crit | — | confirmed (2L: CONCUR) | `_transition.py:87,99,149`,`_workflow_api.py:101` | Workflow enforcement trusts mutable registry JSON, not the signed registration |
| persist-2 | persist | Crit | — | confirmed (2L: CONCUR) | `_transition.py:153`,`_events.py:1010`,`_lineage.py:112,233`,`_review_validators.py:180,254` | Review gates consume unverified, row/envelope-unreconciled event evidence (also `_ops.py:133`) |
| persist-4 | persist | Crit | — | confirmed (2L: CONCUR) | `043_lifecycle_operations.sql:12`,`principal_lifecycle.py:2227,2297,1222` | Durable lifecycle rows are mutable authority; `digest_value` never recomputed on rehydration |
| persist-8 | persist | High | — | confirmed (2L: CONCUR) | `_v6_writer.py:1266,1280,1299` | Workflow-registration admission doesn't verify event signatures; precedence from mutable `global_seq` |
| persist-9 | persist | Med | — | unverified (2L: —) | `_events.py:70,97`,`_v6_writer.py:1690,1820` | ~Global chain head trusted without reconciling to its named event → validly signed fork |
| cairn-05 | cairn | High | — | confirmed-at-different-severity (→ Medium) (2L: CONCUR-DIFF) | `verifier.py:481,509` | Filtered mode lets unverified out-of-window attestations suppress gap findings; invalid-signature evidence keeps the aggregate from PASSing |
| cairn-06 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:1195,1198` | Witness coverage roster is attacker-controlled; pinned keys don't establish expected roster |
| cairn-08 | cairn | High | — | confirmed (2L: CONCUR) | `verifier_types.py:535`,`verifier.py:1412,2385` | Bundle/chain roots not required or externally anchored; missing `bundle_hash` satisfies `all_ok` |
| cairn-16 | cairn | Med | — | unverified (2L: —) | `verifier.py:952,2104`,`verifier_types.py:520` | TSA batches fully forgeable (labeled NOT CHECKED); aggregate PASS ignores `verified=None` |
| dossier-1 | dossier | High | — | confirmed (2L: CONCUR) | `provenance.py:291,312,376` | Orphaned `tool_call_end` (no begin) rendered as a completed, "chain verified" execution |
| dossier-2 | dossier | High | — | confirmed (2L: CONCUR) | `issue_views.py:28,42`,`assurance.py:107,164`,`views.py:179` | "Human-accepted"/independent-review badge from unverified `actor_kind`/`transition` |
| dossier-4 | dossier | High | — | unverified (2L: —) | `app.py:692,723,783`,`views.py:176`,`web.py:128,143` | Routine work views trust mutable projection (`current_state`, title, assignee) without reconciliation |
| as-1 | agent-suite | High | — | confirmed (2L: CONCUR) | `genesis_gate.py:154` | Genesis gate executes unpinned PATH components that can forge every required probe |
| as-2 | agent-suite | High | — | confirmed (2L: CONCUR) | `doctor.py:1042`,`deploy.py:304` | Doctor/deploy can green or create an unauthenticated (unsigned) lock baseline |
| as-4 | agent-suite | High | — | unverified (2L: —) | `release_manifest.py:343`,`cli.py:1831` | Release manifest self-authenticated (recompute self-hash); verify succeeds with no subject |
| as-6 | agent-suite | High | — | confirmed (2L: CONCUR) | `verify_restore.py:176` | Restore verification accepts forged replay JSON despite a failed subprocess |
| as-8 | agent-suite | High | — | confirmed (2L: CONCUR) | `upgrade.py:275,616` | Upgrade/rollback install index artifacts without cryptographic release binding (no hashes) |
| as-9 | agent-suite | High | — | confirmed (2L: CONCUR) | `provisioning.py:191`,`identity.py:368` | Provisioning/offboarding trust unbound child records (wrong principal/project, retired keys left active) |
| as-10 | agent-suite | Med | — | unverified (2L: —) | `doctor.py:147` | Remote shared-service health forged over HTTP (truthy `ok`) |
| an-7 | agent-notes | High | — | confirmed (2L: CONCUR) | `cross_project.py:70,108`,`work_items.py:829`,`701_...sql:154` | Cross-project interchange strips signatures; ingest trusts arbitrary imported lifecycle state |
| an-8 | agent-notes | High | — | unverified (2L: —) | `_queries.py:22`,`_common.py:62`,`work_items.py:518`,`verifier.py:688` | Local projection rows trusted as governance state; regista-backed rows skipped "by construction" |
| an-15 | agent-notes | Low | — | unverified (2L: —) | `kernel.py:439,464` | ~Library `reconcile_entity()` merges unverified `remote_ops` (no sig/hash/lineage/lifecycle checks) |
| aw-7 | agent-wake | High | — | confirmed (2L: CONCUR) | `store.py:110,779`,`router.py:436,492` | DB write → pending rows have no MAC; `drain_pending` sends `event_json` past all ingress controls |
| acb-1 | acb | Crit | — | confirmed (2L: CONCUR) | `model.py:82`,`cli.py:454,511` | Caller can replace the authorization manifest (no signature/root/owner/digest check) |
| acb-5 | acb | High | — | confirmed (2L: CONCUR) | `providers.py:164,298`,`surface.py:173` | Attacker E2E wiring blessed by substring match on `playwright`; no executable-identity check |
| acb-9 | acb | High | — | confirmed (2L: CONCUR-DIFF) | `providers.py:383,389,324` | Reconciled MCP (`npx @playwright/mcp@pin`) trusts registry artifacts without content pinning |

### Class C2 — Retired/rotated/revoked keys retain authority

| ID | Component | DB | V | Verified | Location | Description |
|---|---|---|---|---|---|---|
| SEC-01 | trustlog | Crit | **High** | confirmed-at-different-severity (→ High) (2L: CONCUR) | `_action_delegation.py:507-624,722-765`,`_trust_log_export.py:1172-1228`,`_bundle.py:2257-2299` | Revoked/superseded key mints new action-delegation authority; fails open on withheld evidence |
| SEC-03 | trustlog | High | **High** | confirmed (2L: CONCUR) | `_trust_log.py:1988-2038`,`_bundle.py:2257-2364`,`_verification.py:336-341` | Key validity windows (`not_before`/`not_after`) discarded in replay; expired key stays active offline |
| SEC-06 | trustlog | High | **Low-Med** | confirmed-at-different-severity (→ Low-Medium) (2L: CONCUR) | `_estate_catalog.py:1056-1621`,`_cli.py:3796-3804` | Library catalog verification retains the removed-root forgery path the CLI already refuses |
| crypto-2 | crypto | High | — | confirmed (2L: CONCUR) | `_keys.py:515`,`_verification.py:2039`,`_replay.py:1229`,`_api_meta.py:80` | Retired/revoked legacy keys forge new accepted history; `KeySetResolver` discards status |
| cairn-10 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:97`,`_cli.py:168` | Retired key forges accepted "historical" v1–v4 events (legacy envelopes accepted by default) |
| cairn-11 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:1957` | Post-revocation check compares timestamp strings; `-05:00` sorts before `+00:00` → bypass |
| cairn-13 | cairn | High | — | confirmed (2L: CONCUR) | `_doctor.py:1129,1151` | Retired *first* key in key file forges integrity-marker MAC (no active/rotation/revocation check) |
| dossier-12 | dossier | Med | — | unverified (2L: —) | `app.py:401,413`,`auth/sessions.py:25`,`config.py:349` | Signed session cookie stays authoritative after account/group/authorization revocation (12h) |
| aw-4 | agent-wake | High | — | confirmed (2L: CONCUR) | `secrets.py:478,504` | `secrets remove` doesn't SIGHUP the daemon; removed/compromised key stays live until restart |
| aw-9 | agent-wake | High | — | confirmed (2L: CONCUR) | `secrets.py:451,472`,`gating.py:11` | Rotation leaves previous key fully authoritative with no expiry/immediate revoke |
| acb-12 | acb | High | — | confirmed (2L: CONCUR) | `onboard.py:52,1181,1199` | Retired AppRole SecretID (unlimited TTL/uses) stays valid after best-effort revoke fails silently |

### Class C3 — Signatures/authorizations not bound to context

| ID | Component | DB | V | Verified | Location | Description |
|---|---|---|---|---|---|---|
| SEC-02 | trustlog | High | **High** | confirmed (2L: CONCUR) | `_trust_log.py:409-441,677-725`,`_trust_log_writer.py:694-2388` | Detached root signatures cover payload core only (no event id/seq/predecessor/nonce) → replayable |
| SEC-04 | trustlog | High | **Med-High** | confirmed-at-different-severity (→ Medium-High) (2L: CONCUR) | `_trust_log.py:2263-2342`,`_trust_log_writer.py:1549-2449` | Expired registrar revived by backdating `occurred_at`; timestamps not monotone with chain position |
| SEC-07 | trustlog | High | **Low-Med** | confirmed-at-different-severity (→ Low-Medium) (2L: CONCUR) | `_action_delegation.py:694,763-765`,`_v6_writer.py:1793-1823` | Credential validity compared only to caller-controlled signed `occurred_at` |
| SEC-13 | trustlog | Low | **Low** | confirmed (2L: CONCUR) | `_trust_log.py:1487-1563`,`_trust_log_export.py:1052-1087`,`_estate_catalog.py:1092-1482` | Rotated-in root has no canonical `signer_id`; artifact signature can carry any signer ID |
| crypto-3 | crypto | High | — | confirmed (2L: CONCUR) | `client_signer.py:191`,`principal_lifecycle.py:865`,`_trust_log.py:429` | Rotation client is a raw Ed25519 signing oracle → cross-protocol signature substitution |
| persist-3 | persist | High | — | confirmed (2L: CONCUR) | `031_entity_generalization.sql:3`,`_events_api.py:93`,`_events.py:1020`,`_event_store.py:862` | Entity namespace collision: per-item reads filter `work_item_id` only, not `(entity_kind, entity_id)` |
| cairn-03 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:1581,1637,2024` | Scope attested retroactively / across sessions (coverage chosen by payload time, not event position) |
| cairn-04 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:774`,`adapter.py:315` | Session-attestation `session_id`/`principal_id` not bound to entity ID or signing actor |
| dossier-5 | dossier | High | — | confirmed (2L: CONCUR) | `attribution.py:38`,`provenance.py:183,197`,`views.py:151` | Signed `on_behalf_of` delegation claim trusted without checking signer is authorized to represent |
| dossier-9 | dossier | Med | — | confirmed (2L: CONCUR) | `knowledge.py:180,186,268` | Type confusion: any entity UUID rendered as a "verified knowledge note" (no `entity_kind=="note"`) |
| as-11 | agent-suite | Med | — | unverified (2L: —) | `provisioning.py:15` | One `suite-service` signing key deliberately registered across every host project |
| an-5 | agent-notes | High | — | confirmed (2L: CONCUR) | `_native.py:54,154`,`kernel.py:107` | Provenance resolves identity then records the raw unresolved inputs; missing actor → literal `"null"` |
| an-9 | agent-notes | High | — | confirmed-at-different-severity (→ High) (2L: CONCUR-DIFF) | `outbox.py:225,302`,`reconcile.py:173`,`outbox.py:76` | ~Outbox signature omits project identity; a signed item copied across project directories replays under wrong-project authority (actor unchanged) |
| aw-1 | agent-wake | High | — | confirmed (2L: CONCUR) | `ingest.py:377,396,446`,`gating.py:62` | `X-AgentWake-Identity` checked then stamped as `trigger_identity` but not covered by the HMAC |
| aw-2 | agent-wake | High | — | confirmed (2L: CONCUR) | `gating.py:33`,`ingest.py:156,347,452` | No timestamp/nonce; dedupe on unsigned `X-AgentWake-Event-Id` → captured body replay |
| aw-3 | agent-wake | High | — | unverified (2L: —) | `ingest.py:349,363,369` | `X-AgentWake-Source` not in the MAC; two sources sharing a key allow source relabel |
| aw-6 | agent-wake | High | — | unverified (2L: —) | `proto.py:142`,`socket_server.py:417`,`outbox.py:152,192` | `reply.source` not bound to connection/delivered wake; empty subscription passes → forged replies |
| aw-13 | agent-wake | Med | — | unverified (2L: —) | `outbox.py:192,199`,`wake_hmac.py:56` | ~Reply signature omits `reply_id`; `Idempotency-Key` unsigned; 5-min window, no nonce store → replay |
| aw-14 | agent-wake | Med | — | unverified (2L: —) | `store.py:103,360` | ~Dedupe globally keyed by event ID only (not source) → cross-source wake suppression |
| acb-7 | acb | High | — | unverified (2L: —) | `secret_sources.py:122,141`,`providers.py:1328` | Suite `trusted_argv` authenticates a pathname, not executable identity (digest/owner/symlink); TOCTOU |

### Class C4 — Fail-open gates / missing authorization boundary

| ID | Component | DB | V | Verified | Location | Description |
|---|---|---|---|---|---|---|
| SEC-05 | trustlog | High | **High** (dup) | confirmed (2L: CONCUR) | `_genesis_open.py`,`_api_genesis.py:17-45`,`_genesis.py:396-709` | Public `initialize_epoch()` accepts a completed envelope + bare `gate_passed=True` |
| SEC-10 | trustlog | Med | **Low-Med** | confirmed-at-different-severity (→ Low-Medium) (2L: CONCUR) | `principal_lifecycle.py:593-611,1133-1217` | Default approval verifier `None` accepts any caller-supplied `approver_id` (no auth) |
| cli-1 | regista-cli | High | — | confirmed (2L: CONCUR) | `sidecar/auth.py:19`,`routes.py:121`,`routes_hooks.py:33` | Workflow-scope authz bypass: only hook routes enforce `allowed_workflows` |
| cli-2 | regista-cli | High | — | confirmed (2L: CONCUR) | `routes.py:109,386,628`,`_workflow_api.py:60` | Any non-admin token mints project-trusted artifacts; actor discarded, signed as project identity |
| cli-3 | regista-cli | High | — | confirmed (2L: CONCUR) | `routes.py:477,580`,`_witness.py:445`,`_webhooks.py:45` | Witness/webhook stored credentials (Authorization headers) disclosed to every bearer token |
| cli-6 | regista-cli | Med | — | unverified (2L: —) | `models.py:253`,`routes_hooks.py:95`,`_hooks.py:103` | Any token leases whole hook queue indefinitely; workflow filter runs only after reservation |
| cli-7 | regista-cli | Med | — | unverified (2L: —) | `_cli.py:4246,4283,4315` | Truncated trust-log prefix returns `VALID`/exit 0 when `--expect-head` omitted (stale/retired authority) |
| cli-11 | regista-cli | Low | — | unverified (2L: —) | `routes.py:78`,`app.py:43`,`__main__.py:23` | `/ready`,`/metrics` bypass auth + rate limiting (DB `SELECT 1`, label disclosure) |
| persist-7 | persist | High | — | confirmed (2L: CONCUR) | `principal_lifecycle.py:249,1171,1182,1192` | Approval identity/evidence unsigned; permissive-by-default (no `ApprovalVerifier`) forges SoD |
| persist-13 | persist | Med | — | unverified (2L: —) | `049_epoch_boundary_guard.sql:45,55` | ~Epoch trigger permits any insert while `project_identity` absent (genesis visibility window) |
| cairn-01 | cairn | Crit | — | confirmed (2L: CONCUR) | `verifier.py:502,1427` | Filtered verification deletes every global-chain violation, incl. real deletions/dup positions |
| cairn-02 | cairn | Crit | — | confirmed (2L: CONCUR) | `verifier.py:2467`,`verifier_types.py:538` | Bundle-chain merge omits `unverified_events`; `all_ok` doesn't check `total==ok` → launders to PASS |
| cairn-07 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:1093,1219` | Signatureless HMAC receipt labeled "delegated", counts toward witness coverage |
| cairn-12 | cairn | High | — | unverified (2L: —) | `_doctor.py:1173,1316,1441` | Un-MACed "legacy" verdict falls through to green verified (contradicts "absence of MAC never a pass") |
| cairn-15 | cairn | High | — | confirmed (2L: CONCUR) | `verifier.py:166,2159` | Role gate fail-open for `operator`/unknown roles; `_ACTOR_ONLY_TRANSITIONS` unused |
| cairn-20 | cairn | Med | — | unverified (2L: —) | `_invariant_probe.py:23,113` | Conformance probe uses synthetic fixtures but returns gating PASS (`ok`) with no installed harness |
| dossier-3 | dossier | High | — | confirmed (2L: CONCUR) | `provenance.py:428,436,546`,`evidence.py:64,168` | Replay `halted>0`/warnings treated as `CHAIN_INTACT`; session list does zero per-event sig checks |
| dossier-13 | dossier | Med | — | unverified (2L: —) | `app.py:1717,1731`,`gateway.py:1267` | When lifecycle project unconfigured, revoke calls `principals.revoke()` w/o actor or dual-control |
| dossier-14 | dossier | Med | — | unverified (2L: —) | `config.py:83,96` | Config loader claims to reject group/world-writable but checks only `S_IWOTH` |
| as-3 | agent-suite | High | — | confirmed (2L: CONCUR) | `doctor.py:432` | Local doctor treats string `"false"` as truthy healthy; ignores contradictory child exit codes |
| as-7 | agent-suite | High | — | confirmed (2L: CONCUR) | `lock.py:893` | SUITE.lock revision pin skipped when wheel provenance has no revision (same-version malicious wheel) |
| as-12 | agent-suite | Med | — | unverified (2L: —) | `cli.py:1278` | Dual-control CLI turns any two arbitrary strings into MFA-authenticated requester+approver |
| as-13 | agent-suite | Med | — | confirmed (2L: CONCUR) | `cli.py:647` | ~Genesis verdict/receipt not consumed by first-write admission |
| as-14 | agent-suite | Med | — | unverified (2L: —) | `lifecycle.json:24`,`upgrade.py:1875` | Canonical workflow permits non-human acceptance; rollback silently crosses workflow versions |
| as-16 | agent-suite | Med | — | unverified (2L: —) | `cli.py:647`,`backup.py:110` | Omitting `--exit-code` makes blocked gates/red doctor return 0 (backup/restore does this internally) |
| an-1 | agent-notes | High | — | confirmed (2L: CONCUR) | `work_items.py:1216`,`_regista.py:327`,`work_item_model.py:336` | `--same-lineage-acknowledged` needs no operator/human authority; `actor_id` caller-selectable |
| an-2 | agent-notes | High | — | confirmed (2L: CONCUR) | `actor.py:130`,`SUITE.lock:23` | Lineage registry validation fails open (`registry_families()` → `None`) under pinned regista 0.5.5 |
| an-3 | agent-notes | High | — | confirmed (2L: CONCUR) | `actor.py:1`,`common.py:91`,`work_items.py:1062`,`work_item_model.py:240` | Native mode: no project/admin authorization boundary; `--force`/admin flags are ordinary switches |
| an-4 | agent-notes | High | — | confirmed (2L: CONCUR) | `lifecycle.py:92`,`_regista.py:88`,`_native.py:70`,`verifier.py:599` | Gate-exempt `open→done` (`close_from_open`) usable as general completion bypass |
| an-6 | agent-notes | High | — | confirmed (2L: CONCUR) | `kernel.py:122`,`envelope.py:127`,`verifier.py:101`,`verify.py:16` | Native ops default to `NullSigner`; verifier accepts `keyid:"null"` when no key supplied |
| an-10 | agent-notes | Med | — | unverified (2L: —) | `_native.py:421`,`work_items.py:1188`,`verifier.py:599` | `attest-gate` "operator-only" but has no authz; detector only checks the key exists |
| an-14 | agent-notes | Low | — | unverified (2L: —) | `web/app.py:42,84` | Web viewer bearer auth optional; disabled when env var absent → all records readable |
| aw-5 | agent-wake | High | — | confirmed (2L: CONCUR) | `socket_server.py:284,307`,`router.py:162,254` | Socket peer self-asserts adapter/destination; newest subscriber wins → wake hijack (same-UID) |
| acb-2 | acb | High | — | confirmed (2L: CONCUR) | `cli.py:517,535` | `exec` never identifies calling harness or checks `cap.harnesses` membership |
| acb-3 | acb | High | — | confirmed (2L: CONCUR) | `cred_vault.py:52,152,422`,`providers.py:989` | Caller-controlled `$ACB_VAULT_ENV` substitutes another capability's Vault access plane |
| acb-4 | acb | High | — | confirmed (2L: CONCUR) | `surface.py:173` | Reverse-surface audit ignores non-Playwright MCP servers → doctor stays green on rogue grants |
| acb-6 | acb | High | — | confirmed (2L: CONCUR) | `surface.py:129`,`cli.py:193,245` | Detected rogue capabilities are `warn` → `ok=True`/exit 0; CI gate accepts the host |
| acb-8 | acb | High | — | confirmed (2L: CONCUR) | `providers.py:84,567,1362` | Injection denylist omits `LD_PRELOAD`/`NODE_OPTIONS`/`BASH_ENV`… → bypass exact-argv qualification |

### Class C5 — Other (sub-labeled)

| ID | Component | DB | V | Verified | Sub | Location | Description |
|---|---|---|---|---|---|---|---|
| SEC-09 | trustlog | Med | **Med** | confirmed (2L: CONCUR) | TOCTOU | `principal_lifecycle.py:1133-2865` | Lifecycle cancellation lost via stale per-process cache; `commit()` ignores locked-row state |
| SEC-12 | trustlog | Low | **Low** | confirmed (2L: CONCUR) | DoS | `_trust_log_export.py:856-909`,`_estate_catalog.py:1137-1140`,`_cli.py:5124-5127` | Trust-log export/catalog parsers have no size/count/depth limits (bundles do) |
| crypto-1 | crypto | High | — | confirmed (2L: CONCUR) | crypto-confusion | `verification.py:170-210`,`_signing.py:828`,`_verification.py:4059` | Attacker-selected HMAC consumes Ed25519 public key bytes → v5 `FULLY_AUTHENTICATED` forgery |
| crypto-4 | crypto | High | — | not-reproducible (2L: CONCUR) | cred-exposure | `_secrets.py:1596-1785`,`client_signer.py:39`,`_cli.py:1765` | ~Windows "public identity" exposes machine-scope DPAPI private-key blob in argv/output |
| crypto-5 | crypto | Med | — | unverified (2L: —) | crypto/predictable | `_secrets.py:315`,`_keys.py:208`,`_signing_scheme.py:115` | Malformed secret refs (`vualt:`, bad base64) fall through to predictable/empty HMAC key bytes |
| crypto-6 | crypto | Med | — | unverified (2L: —) | DoS | `_bundle.py:1440,1530,2696` | 512 MiB bundle cap runs after whole-file `read_bytes()`; one report entrypoint has no cap |
| crypto-7 | crypto | Low | — | unverified (2L: —) | DoS/error | `_encryption.py:217,269,339` | Malformed encrypted wrappers escape as uncaught `TypeError`/decode/JSON exceptions |
| cli-4 | regista-cli | Med | — | unverified (2L: —) | SSRF | `routes.py:441,484`,`_witness.py:129,760` | Witness/webhook outbound delivery → SSRF (loopback/link-local/rebinding) with response exfiltration |
| cli-5 | regista-cli | Med | — | unverified (2L: —) | DoS | `models.py:96,293`,`routes.py:201,518,643` | Unbounded read limits / ~10 MiB batches reach SQL LIMIT/fetchall/signing → resource exhaustion |
| cli-8 | regista-cli | Med | — | unverified (2L: —) | DoS | `_cli.py:3765,4271,5124` | Offline trust-log/catalog parsed via unbounded `read()`/`json.loads` before verification |
| cli-9 | regista-cli | Med | — | unverified (2L: —) | TOCTOU | `_cli.py:1961,1998` | `sign-genesis` output symlink race between `exists()` and `open(...,"w")` (`--force` prepositions) |
| cli-10 | regista-cli | Low | — | unverified (2L: —) | TOCTOU | `routes.py:535` | ~Compose-workflow symlink swap after containment validation before reopen |
| persist-5 | persist | Crit | — | confirmed (2L: CONCUR) | TOCTOU | `principal_lifecycle.py:1239,1245,1260,1644` | `commit()` locks row but checks cached `APPROVED`; cancelled op finalized (= SEC-09) |
| persist-6 | persist | High | — | confirmed (2L: CONCUR) | TOCTOU | `principal_lifecycle.py:842,852,1192,1214` | ~Possession/approval transitions update without expected-state predicate → resurrect cancellation |
| persist-10 | persist | Med | — | unverified (2L: —) | race | `principal_lifecycle.py:1388,1477,1494,1510` | ~Receipt/operation status last-writer-wins (no predicate) → downgrade/false failure of effective key |
| persist-11 | persist | High | — | confirmed (2L: CONCUR) | evidence-erasure | `027_archive_sequence_fix.sql:7` | Migration 027 `DROP TABLE IF EXISTS events_archive` with no non-empty check → audit erasure |
| persist-12 | persist | High | — | confirmed (2L: CONCUR) | integrity-gap | `030_global_event_chain.sql:13,22`,`035_...sql:26` | ~Upgrade seeds a new global chain at `NULL`; pre-upgrade history deletable without breaking suffix |
| persist-14 | persist | Low | — | unverified (2L: —) | DoS/race | `_events.py:549,557,914`,`_event_store.py:1134` | ~Idempotency recovery queries an aborted txn (no savepoint) → `InFailedSqlTransaction` |
| persist-15 | persist | Low | — | unverified (2L: —) | DoS/race | `_workflow_api.py:101,135` | ~Workflow registration check-then-insert race → deploy DoS instead of idempotent return |
| persist-16 | persist | Low | — | unverified (2L: —) | DoS | `_migrations.py:93,133`,`026_...sql:31` | Migration probes use unqualified `information_schema.tables` → cross-schema migration DoS |
| cairn-09 | cairn | High | — | confirmed (2L: CONCUR) | truncation | `_cli.py:634` | Export silently truncates at 10,000 events; partial bundle emitted+hashed as complete |
| cairn-14 | cairn | High | — | confirmed (2L: CONCUR) | DoS | `verifier.py:707,725` | File-provenance reads `payload.files[].path` (`/dev/zero`, FIFO) to EOF → verifier hangs |
| cairn-17 | cairn | Med | — | unverified (2L: —) | verify-DoS | `verifier.py:2452` | v6 cross-bundle links use obsolete `sha256(env‖sig)` not version-aware hash → genuine chains rejected |
| cairn-18 | cairn | Med | — | unverified (2L: —) | injection/XSS | `_portal.py:30,49,271` | Portal renders unverified bundle; `manifest.events_count` inserted unescaped → script execution |
| cairn-19 | cairn | Med | — | unverified (2L: —) | attribution | `_claude_hook.py:699,712` | `transcript_attestation` digest covers raw Stop-hook JSON, not the whole-session transcript |
| cairn-21 | cairn | Med | — | unverified (2L: —) | DoS | `verifier.py:181,367,402` | ~Whole file read/parsed before event-count enforcement; peak memory >> 512 MiB |
| cairn-22 | cairn | Low | — | unverified (2L: —) | DoS | `verifier.py:969,1011` | Malformed auxiliary sections raise on unchecked `.get()` → verification aborts (DoS) |
| dossier-6 | dossier | Med | — | unverified (2L: —) | info-disclosure | `app.py:485`,`health.py:98-703`,`ingress.yaml:33` | Public `/healthz` discloses schema names, project counts, trust-log config, paths, principal IDs |
| dossier-7 | dossier | Med | — | unverified (2L: —) | DoS | `app.py:512`,`lifecycle_http.py:123`,`gateway.py:530`,`provenance.py:492` | ~No app-level request-size or expensive-read budget (login body, full-replay pages) |
| dossier-8 | dossier | Med | — | unverified (2L: —) | DoS | `gateway.py:365,369,1354` | Hostile `display_key` bigint overflow (`::bigint`) denies work-item creation project-wide |
| dossier-10 | dossier | Med | — | unverified (2L: —) | clickjacking | `app.py:248,359`,`issue_detail.html:80` | ~No `frame-ancestors`/`X-Frame-Options` → UI-redress on transition/accept/lifecycle forms |
| dossier-11 | dossier | Med | — | unverified (2L: —) | DoS | `app.py:639` | Bound identities can't step up (`principal_id` vs `stable_id`) → denial of enroll/rotate/revoke |
| dossier-15 | dossier | Low | — | unverified (2L: —) | rate-limit | `auth/throttle.py:18,26`,`app.py:527` | Login throttle per-identifier only (4/5min); no IP/global budget → password spraying |
| dossier-16 | dossier | Low | — | unverified (2L: —) | collision | `notifications.py:188,206` | ~Principal IDs differing only in `_`-replaced chars map to same prefs file → overwrite |
| dossier-17 | dossier | Low | — | unverified (2L: —) | hardening | `app.py:359`,`base.html:45`,`issue_detail.html:96` | No CSP/HSTS/referrer/content-type/frame policy; inline scripts contradict claimed CSP |
| as-5 | agent-suite | High | — | confirmed (2L: CONCUR) | cred-exposure | `secret_refs.py:159`,`identity.py:493` | Inline private-key references exposed in argv and diagnostic output |
| as-15 | agent-suite | Med | — | unverified (2L: —) | TOCTOU | `scripts/agent-worktree:83` | ~Worktree base ref changes between validation and privileged project execution (hook/build) |
| an-11 | agent-notes | Med | — | unverified (2L: —) | truncation-bypass | `regista_face.py:212`,`regista/_contract.py:17`,`_transition.py:153` | ~Validators inspect latest 100k events; comment flood evicts author/pass identity → self-accept |
| an-12 | agent-notes | Med | — | unverified (2L: —) | logic-gap | `701_...sql:119`,`links.py:55` | Ready view treats blockers unresolved only in `open`/`claimed`; link add/remove has no authz |
| an-13 | agent-notes | Med | — | unverified (2L: —) | SSRF | `trigger_loop.py:73,90`,`http_transport.py:27` | DB-controlled `projects.wake_channel` used as unrestricted URL → HMAC-tagged POST SSRF |
| aw-8 | agent-wake | High | — | confirmed (2L: CONCUR) | TOCTOU/hijack | `main.py:70`,`socket_server.py:127,149` | ~Socket-path parent ownership/mode not validated; attacker rebinds fake server at path |
| aw-10 | agent-wake | Med | — | unverified (2L: —) | DoS | `socket_server.py:92,278` | No handshake/read timeout; pending handshakes bypass the 16-connection limit |
| aw-11 | agent-wake | Med | — | unverified (2L: —) | DoS | `ingest.py:216,353` | All local users share one `127.0.0.1`/`::1` bucket; unsigned floods starve signed senders |
| aw-12 | agent-wake | Med | — | unverified (2L: —) | DoS | `ingest.py:347,359` | ~Request bodies buffered before rate limiting → connection/memory consumption |
| acb-10 | acb | High | — | confirmed (2L: CONCUR) | injection | `cli.py:756,762,813,839` | `register` quotes but never escapes TOML → closing-quote injection forges capability tables |
| acb-11 | acb | Med | — | unverified (2L: —) | injection | `model.py:219`,`providers.py:963,1016` | ~Capability IDs/plane names permit newlines/metacharacters, interpolated unescaped into shims |
| acb-13 | acb | Med | — | unverified (2L: —) | TOCTOU | `onboard.py:1017,1060,1134` | ~Vault policy/role check and SecretID issuance not transactionally bound → broadened policy race |
| acb-14 | acb | Med | — | unverified (2L: —) | TOCTOU | `adapters.py:40,58,223` | ~Harness writes use `exists()`+`write_text()` not `O_EXCL`; symlink race overwrites/rewires |
| acb-15 | acb | Med | — | unverified (2L: —) | info-disclosure | `adapters.py:31` | Config backups use process umask not source mode → secret-bearing 0600 config readable |
| acb-16 | acb | Low | — | unverified (2L: —) | attribution | `provenance.py:21` | `ACB_STATE_DIR`/`ACB_AGENT` redirect+forge unsigned provenance → attribution bypass |

---

## 4. Criticals + top Highs (with one-line exploit)

### Critical (7)
- **acb-1** (C1) — Low-priv agent supplies its own unsigned `acb` manifest, declares any Vault ref
  its ambient identity permits and sets its own binary as `trusted_argv`; ACB injects the secret
  into the attacker's executable.
- **persist-1** (C1) — DB-write attacker edits `workflow_registry.definition` to remove `human_gate`
  or redirect `to_state=done`; a valid key then produces a legitimately signed event under malicious
  rules (v6 event still cites the benign registration hash).
- **persist-2** (C1) — DB-write attacker transiently rewrites author `transition`/`actor_id` before
  the review-validator query, restores after; yields a valid signed `adversarial_pass`/`accept` with
  no durable trace. (This is SEC-11 at the gate layer.)
- **persist-4** (C1) — DB-write attacker alters an approved revocation's `principal_id`/`old_key_id`
  while keeping its old `digest_value`; rehydration re-signs a registrar-signed revocation for a
  different victim.
- **persist-5** (C5/TOCTOU) — Registrar races `commit()` against cancellation; commit locks the now-
  cancelled row but uses cached `APPROVED`, emits the lifecycle event, overwrites to committed.
  (= verified SEC-09.)
- **cairn-01** (C4) — Bundle publisher deletes a single-event entity inside the filtered window and
  recomputes the unkeyed bundle hash; filtered mode deletes the resulting `global_seq_gap` violation
  and the report passes.
- **cairn-02** (C4) — A bundle of signature-valid but referent-missing v6 events verdicts `unverified`;
  `verify_bundle_chain()` omits `unverified_events` and `all_ok` never checks `total==ok`, so the
  merged chain exits PASS.

### Top Highs (representative; full set in §3)
- **SEC-01** (C2, verified High/latent-Crit) — Retained revoked/superseded issuer key A mints a new
  root action-delegation to active principal B; verifier authenticates A via historical acceptance,
  bypassing current-status resolution. Blocker on shipping the credential section.
- **SEC-02** (C3, verified High) — One current root re-appends a stored `root_signatures` array over
  an unchanged payload; k-of-n threshold governance collapses to one-current-root; revoked registrar
  restored. Demonstrated on Postgres.
- **SEC-03** (C2, verified High) — Expired-but-status-active key authenticates offline; replay/bundle
  discards `not_before`/`not_after` that the online path honours.
- **crypto-1** (C5/crypto-confusion) — v5 event labeled `hmac-sha256` with the known Ed25519 public
  key as the HMAC key returns `FULLY_AUTHENTICATED` without any private key.
- **crypto-3** (C3) — Malicious registrar feeds `regista.event.v6\0‖attacker-envelope` to the rotation
  client, which signs it verbatim → cross-protocol signature under the principal's key.
- **cli-2** (C4) — Any authenticated non-admin token registers a workflow; the actor is discarded and
  the event is signed as the project identity (`actor_kind="system"`) → malicious YAML looks
  project-authorized.
- **cairn-10 / cairn-13** (C2) — A retired key forges pre-revocation "historical" events, and the
  retired *first* key in the file forges the doctor integrity-marker MAC → green verdict.
- **dossier-2 / dossier-3** (C1/C4) — A DB writer flips `actor_kind` to `human` (or leaves replay
  `halted>0`) and dossier shows a green "human-accepted"/"chain verified" badge. (SEC-11 in the UI.)
- **an-6** (C4) — Native ops default to `NullSigner`; the verifier accepts `keyid:"null"`, so a DB/
  artifact writer forges arbitrary lifecycle payloads that pass hash+signature+actor policy.
- **aw-7** (C1) — SQLite write inserts a pending row with forged source/kind/content; `drain_pending`
  delivers it past all HTTP auth, identity, route, and dedupe checks.
- **acb-8** (C4) — A manifest maps a resolved secret to `LD_PRELOAD`; the exact trusted binary loads
  the attacker library before `main` and exfiltrates every other injected credential — exact-argv
  qualification bypassed without changing argv.

---

## 5. Dedup notes (same defect re-found)

- **SEC-05 = WI-342.** Public genesis-API bypass. Verified as a straight duplicate — close as dup.
  (Still counted in the crown-jewel 13.)
- **SEC-09 ≡ persist-5 (+ persist-6).** Stale per-process lifecycle cache. persist-5 is the same
  commit-path defect; persist-6 is the reverse (possession/approval resurrecting a cancelled op).
- **SEC-10 ≡ persist-7; echoed by as-12, an-1.** Permissive-by-default approval / separation-of-duties:
  no `ApprovalVerifier` (SEC-10, persist-7), any-two-strings dual control (as-12), no-operator-authority
  self-review acknowledgment (an-1).
- **SEC-11 = the central "assurance/gate/UI trusts mutable rows" collision.** Re-found as: persist-2
  (gate layer + `_ops.py:133`), dossier-2 (human-accepted badge), dossier-4 (routine views),
  an-8 (projection = governance state), persist-9 and aw-7 (chain head / pending rows). This is the
  WI-337 thread — one row↔signed-envelope reconciliation invariant, enforced at every read, closes them.
- **SEC-12 ≡ crypto-6 ≡ cli-8 ≡ cairn-21 (rel. cairn-09/cairn-14).** "Parse/allocate the published
  artifact before the size/count/depth cap" — the same DoS class across regista and cairn offline
  verifiers.
- **SEC-01/SEC-03 family ≡ crypto-2.** "Retired/revoked/expired key retains signing authority" — the
  key-status invariant (WI-337/347/348/349) that `_action_delegation`, legacy verification, and the
  KeySetResolver each fail to consume.
- **persist-3 ≈ dossier-9.** Entity-kind not bound to the read: persist-3 injects cross-entity events
  into a work item's history; dossier-9 renders any entity as a "verified knowledge note."
- **SEC-05 ≈ as-13.** "Genesis verdict/receipt not consumed by the first write."
- **Fail-open exit-code / truthy-value handling** recurs: as-3 (`"false"` truthy), as-16 (opt-in
  `--exit-code`), cairn-15 (role gate), cairn-12/cairn-20 (marker/probe), an-6 (NullSigner),
  cli-11 (unauth `/ready`), acb-6 (rogue = warn → exit 0).
- **Identity-not-bound-to-signature (C3)** recurs across transports: regista SEC-02/04/07/13,
  agent-wake aw-1/2/3/6/13/14, agent-notes an-5/an-9, acb-7, dossier-5 — same root shape
  (valid signature, missing binding to id/seq/nonce/source/project/actor/executable).

---

### Provenance / limits of this synthesis
- Crown-jewel severities and verdicts are from the Claude Opus probe-executor runs in
  `transcripts/verify-sec*.jsonl` (2026-08-25), with Daybreak/Fable second-lineage review as
  recorded. The SEC-01 reproducer's existing resolver caveat remains unchanged.
- Phase 0A-2 execution was performed by `openai/gpt-5.6-sol` on 2026-08-25. Evidence and verdicts
  are under `probes/critical/`, `probes/highs-regista/`, `probes/highs-apps/`,
  `probes/highs-apps-rerun/`, and `probes/highs-broker-transport/`.
- Second-lineage evidence/oracle review was performed by `ollama-cloud/minimax-m3` on 2026-08-25;
  each evidence directory's `REVIEW-minimax.md` is authoritative for `CONCUR` versus
  `CONCUR-AT-DIFFERENT-SEVERITY`. The narrowed cairn-05 and an-9 language follows that review.
- `crypto-4` remains `not-reproducible`, not invalidated, pending a Windows DPAPI executor. Every
  other `unverified` row was outside the 78-finding Phase 0A-2 selection and retains Daybreak severity.
- File:line citations are copied from the reports as-is; regista paths are relative to
  `src/regista/`, cairn to `src/cairn/`, etc. (report prefixes like `/projects/...` or `/tmp/...`
  are stripped for readability).
