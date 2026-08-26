I could not run `git` against `/projects/regista`, `/projects/agent-provenance`, or `/projects/agent-capability-broker` in this session (Bash is restricted to `/projects/wt-plan-025`), so source tracing used the checked-out trees via Read/Grep. `regista` HEAD is `7707c81` and `agent-capability-broker` HEAD is `f2df972` — both **are** the reviewed refs (verified via `.git/refs/heads/main`). `agent-provenance` is checked out at `b00169c` on branch `agent/wi045-observed-model`, **not** `74471ad`; the cairn tracing below is therefore at a later ref and I flag where that matters.

---

# 1. TRUST-MODEL.md v0.3 — delta check on B1–B13

Verdicts derived from the v0.3 text only; Appendix A not relied on.

| # | Original defect | Status | v0.3 evidence (line cites) |
|---|---|---|---|
| **B1** | 14 §8 rows list the same ADV in both adversary columns (range shorthand) | **CLOSED** | Ranges eliminated; every row at `TRUST-MODEL.md:178–236` enumerates ids explicitly. Self-check asserted at `:238`. I hand-verified the partition on 12 rows (INV-004 `:181` 16+18=34; INV-011 `:188` 16+18; INV-013 `:190` 21+13; INV-015 `:192` 28+6; INV-016 `:193` 29+5; INV-019 `:196` 25+9; INV-024 `:201`; INV-028 `:205`; INV-030 `:207`; INV-042 `:219` 30+4; INV-049 `:226` 25+9 — ADV-06 no longer double-listed; INV-052 `:229` 28+6). Disjoint and total in every case. *But see NEW-3: a different self-contradiction class survives.* |
| **B2** | §5 retroactive rule has no fixpoint / no propagation / `S_p` undefined | **CLOSED** | Single ordered pass `:75–83`; acceptance immutable `:78`; operative-revocation exemption `:79`; direct marking `:80`; transitive propagation + termination argument `:81`; chosen-rule-and-cost statement `:85`; mutual/circular revocation resolved `:87`; INV-013 restated falsifiably `:190`. *But see NEW-4: the exemption's scope creates a new attack.* |
| **B3** | §7 is not a matrix; ADV-08 unclassified; no invariant ids | **CLOSED** | Literal 6×34 matrix `:140–147`; every cell filled; ADV-08 = `D` in all six rows; per-claim `invariant_ids` column present `:142–147`; `R`/`D`/`R*`/`N` semantics documented `:138`. *But see NEW-2: two columns disagree with §7's own derivation table.* |
| **B4** | Undetectable pre-anchor censorship by ADV-03/12/13/26 | **CLOSED** | INV-051 `:228` — signed ack binding submission digest, promised position, max merge delay; submitter verification duty; failure action; explicit "Never-acknowledged censorship remains residual". Residual added `:296`. Claim rows qualified: `:142` "acknowledged submissions only"; `:143` cites INV-051. |
| **B5** | No invariant governs pinned-input acquisition / first contact | **CLOSED** | INV-052 `:229` — operator-independent authenticated pin channel, predecessor/version-bound updates, log-vs-pin equivocation terminal, and the explicit first-contact limit ("may verify internal consistency only and must not issue trusted Q2/Q3/claims"). Cites `cairn-06`. §5 step 1 `:77`. Residual restated `:295`. |
| **B6** | ADV-09 resisted by all six claims; no key-custody invariant | **CLOSED** | INV-053 `:230` — per-key-class custody, governance/review keys unavailable to agent-notes/dossier, HSM-unavailable profile obligations. INV-059 `:236` — agent *and* human review admission, "apps cannot substitute another digest or directly use governance-authority signing keys". §7 now marks ADV-09 = `D` for `IndependentReviewAttestation` (`:142`) and `AttributableAuthorship` (`:144`). Mis-cited `crypto-4`/`as-5` moved off INV-033 (`:210` now cites `acb-12` only) onto INV-053. |
| **B7** | Cache TTL bounds the wrong quantity; renewable | **CLOSED** | `:261` — "Cache age is `decision_time - earliest_required_witness_observation_time(cut)`, never cache-entry creation or re-derivation time"; entries bind first authenticated observation time; re-verification cannot extend. Per-action criticality floors, revocation-publication bound. INV-011 `:188`, INV-012 `:189` ("re-derivation never refreshes cut age"). Residual `:300`. |
| **B8** | Break-glass renewable, can roll policy back, no non-equivocation, weak exclusions | **CLOSED** | (a) `BREAK_GLASS_INCIDENT_MAX` cumulative-per-incident + `BREAK_GLASS_CROSS_INCIDENT_MAX` `:270`; "No renewal by the same set…extension requires a different pre-authorized approver set" `:272`; INV-049 `:226`. (b) INV-055 `:232` monotonic floors incl. restore/emergency; `:272` "restore configuration only if `INV-055` floors and maxima do not weaken". (c) INV-049 `:226` — incident id, pre-issued monotonic sequence, predecessor digest, reserved recovery position. (d) `:270` now excludes IdP admin, secret-backend admin, bootstrap-host admin, release/root signer, **any** required witness operator. |
| **B9** | Unanchored capture laundered into tamper-evident history | **CLOSED** | INV-058 `:235` — chain-committed marker binding last-anchored/first-reanchored positions and exact intersecting range; "Every intersecting Q3/claim permanently discloses `unanchored=true`"; hard maximum window. §9 row `:266`. Residual `:303`. Correctly does **not** resist ADV-03/13/26 (`:235`). |
| **B10** | persist-5 / SEC-09 uncited; no concurrency test family | **CLOSED** | `CT` family defined `:172`; INV-054 `:231` cites `SEC-09`, `persist-5/6/10`; coverage sweep homes them `:249`. Plan reconciliation is real, not asserted: `025-provenance-security-remediation.md:184` now lists "concurrency/TOCTOU interleaving tests". |
| **B11** | Append-only history vs. HIPAA deletion never stated; INV-048 promised the impossible | **CLOSED** | §11.5 `:288` states structural non-deletion and the (a)/(b) choice with the non-goal rationale; INV-048 corrected `:225` ("admitted chain content is never promised deletable and no claim proves PHI absence"); residual `:306`. |
| **B12** | No minimum witness quorum; `TrustedTimestamp` must-not-issue unenforced | **CLOSED** | INV-016 `:193` — "Positive Q3 requires at least two witnesses" plus an operational independence predicate (distinct operator, key custody, admin account, host, persistence plane; no shared writer/DBA realm). INV-056 `:233` — unselected/invalid prerequisite policy must not issue, consumers deny. Residual `:308`. |
| **B13** | Missing ADV ids for IdP, secret backend, kernel, signing quorum; prose non-resists | **CLOSED** | ADV-30…ADV-34 added `:130–134`; ADV-24 `:124` now explicitly "including reviewer, role-granting, grant-authority, or other role held"; prose non-resists converted to ids throughout (spot-checked INV-031 `:208`, INV-032 `:209`, INV-033 `:210`, INV-035 `:212`, INV-049 `:226`, INV-050 `:227`). |

B14 (process) is satisfied outside this delta: third lineage `minimax-m3` reviewed and the owner accepted (`EXIT-0A.md:22`).

**13 of 13 closed.** The rework was real, not cosmetic.

---

# 2. VERDICT on v0.3

**accept-with-changes.**

The foundational objections are all genuinely closed against the text. The three NEW findings below are all in material that is *new in v0.2/v0.3* — the 6×34 matrix, the cell-difference derivation table (v0.3, per NB-B2), and the §5 exemption clause — and all three are mechanically correctable without touching the architecture. None of them re-opens B1–B13.

Two of the three are blocking **for 0B/0C use**, because `025-provenance-security-remediation.md:186` makes §7/§8's adversary columns the literal input to the cutover gate: an invariant whose columns are self-contradictory, or a claim cell that contradicts its own stated derivation, cannot be evaluated at that gate.

---

# 3. NEW findings

### NEW-1 (blocking) — §7's matrix and §7's own cell-difference table disagree on ADV-29 and ADV-30

`:153` states the contract: *"Rows are equal for every adversary not listed below."* Both listed columns fail.

**ADV-30** (`:166`): the table asserts `TamperEvidentChangeRecord` and `TrustedTimestamp` are `R`, **all other rows `D`** — and gives `ExternallyAuthenticatedBundle`'s reason explicitly: *"`D` because its cited set lacks an invariant authenticating its signer-policy directory binding against `ADV-30`."* But the matrix cell at `:147`, column 30, is **`R`**. (Anchor check: `:147` col 10 = `R*`, matching `:138`'s ADV-10 rule; 34 cells counted.)

**ADV-29** (`:165`): the table asserts only `IndependentReviewAttestation` is `D`. The matrix has **four** `D` cells at column 29: `:142`, `:144`, `:146`, `:147`. (Anchor checks: `:144` col 26 = `R‡`, matching footnote `:151`; `:146` col 1 = `R†`, matching footnote `:149`.)

The two errors point in opposite directions, so neither section can be taken as authoritative:

- For ADV-29 the **matrix is right**. ADV-29 = "Signer + DBA" (`:129`) is a strict superset of ADV-24 (`:124`). All four rows are `D` at ADV-24 (`:164`), so they must be `D` at ADV-29. Prose `:165` is wrong.
- For ADV-30 the **table is right**. `ExternallyAuthenticatedBundle`'s distinguishing field is "signer policy" (`:147`), which is directory-mediated; a directory/IdP admin binds an attacker principal into it and the bundle claim issues a false positive. Cell `:147`/30 should be `D`.

*Failure scenario:* 0B/0C evaluates the profile gate against `ExternallyAuthenticatedBundle` and concludes the bundle claim resists a directory administrator, when §7's own reasoning says it does not. In an AD-based target estate that is the most likely adversary in the whole catalogue.

*Required change:* fix `:147`/ADV-30 to `D`; fix `:165` to name all four `D` rows; then add a **stated monotonicity rule** for collusion adversaries — a cell must be `D` whenever any constituent adversary's cell is `D` — and a mechanical self-check alongside `:238`.

I checked the other 32 columns cell-by-cell against `:157–168`: ADV-06, 07, 09, 10, 14, 17, 18, 24, 31, 34 all match, and every unlisted column is genuinely uniform across the six rows. The defect is confined to these two columns.

### NEW-2 (blocking) — seven registry rows place ADV-24 in *Does not resist* and ADV-29 in *Resists*

Since ADV-29's capabilities strictly contain ADV-24's (`:124` vs `:129`), an invariant that a signer-key holder can defeat is defeated a fortiori by signer + DBA. These rows assert both:

| Row | ADV-24 | ADV-29 |
|---|---|---|
| INV-001 `:178` | does not resist | **resists** |
| INV-002 `:179` | does not resist | **resists** |
| INV-004 `:181` | does not resist | **resists** |
| INV-028 `:205` | does not resist | **resists** |
| INV-030 `:207` | does not resist | **resists** |
| INV-053 `:230` | does not resist | **resists** |
| INV-059 `:236` | does not resist | **resists** |

This is B1's defect class recurring in a form the `:238` self-check cannot see: `:238` verifies only disjointness and coverage, not consistency between a collusion adversary and its constituents. I checked the other three collusions (ADV-26 = 03+13, ADV-27 = 13+23, ADV-28 = 22+03) across all 59 rows and found no violations — the failure is specific to the ADV-24/ADV-29 pair, and it is the same root cause as NEW-1's ADV-29 column.

*Failure scenario:* `025-provenance-security-remediation.md:186` gates cutover on "every `TRUST-MODEL.md` invariant for its enabled components holds under the stated adversaries." A reviewer evaluating INV-028 (separation of duties) concludes it holds under signer+DBA collusion while the same row concedes a lone signer defeats it. 0A-3's `invariant_ids` column propagates that into the matrix rows citing these seven.

*Required change:* set ADV-29 to *Does not resist* in all seven rows; extend `:238` with `for each collusion C = X ∪ Y: C ∈ resists ⟹ X ∈ resists ∧ Y ∈ resists`.

### NEW-3 (blocking before the owner selects the §5 retroactive policy) — the step-3 exemption is an attacker-controlled immunity primitive that reintroduces SEC-01

`:79` grants the exemption unconditionally and unboundedly: *"Its own Q2 and every event in the complete authority-derivation chain used to authorize it at acceptance are exempt from **every** retroactive effect, even when an exempt event lies inside that revocation's or another operative revocation's effect range."*

Step 5 (`:81`) then propagates ineffectiveness only through **marked** events. An exempt event is never marked, so it confers effective authority forever.

*Constructed interaction.* Root key `K_R` is compromised at position 9.
1. Attacker signs delegations `D_1…D_n` (root → `M_1…M_n`) at positions 10…10+n.
2. Each `M_i` issues one throwaway revocation `R_i` (revoking an already-expired key). Each `R_i` is accepted; its acceptance-time authority chain is `{D_i, K_R's key-binding event}`.
3. The genuine root recovers and issues `R*` revoking `K_R` with `effect_from = 9`.

Step 4 marks `K_R`'s events from position 9 — **except** `D_1…D_n` and `K_R`'s key-binding event, all of which are exempt under `:79` because each sits in some `R_i`'s recorded acceptance-time chain. Step 5 therefore never marks anything derived from them. Every `M_i` retains its delegated authority after the root key that granted it has been retroactively revoked, and the mark is irreversible (`:80` "no mark is removed"; `:79` "later Q2 changes never deactivate an accepted revocation or its recorded authority basis").

This is SEC-01 — "revoked/superseded key mints new action-delegation authority" — reappearing as a modelling choice, exactly what the temporal model exists to close. The attacker chooses whether the exemption applies, at the cost of one cheap revocation per fraudulent delegate. Remediation requires enumerating and separately revoking every `M_i`, which is precisely what the defender cannot do for delegations they don't know about. §9 break-glass explicitly cannot help (`:272` "cannot make Q1/Q2/Q3 positive… delete/rewrite history"); §12 has no residual for it.

The mirror case is equally live: a *maliciously issued but validly authorized* revocation is permanently un-revokable, making it an irreversible authority-destruction weapon back to the maximum lookback. `:85` acknowledges only that propagation "can invalidate a large descendant set" — it does not acknowledge irreversibility or attacker-controlled immunity.

*Required change:* narrow the exemption. The acceptance-time chain should be exempt **only for the purpose of keeping that revocation operative** — i.e. `R_i` stays accepted and operative — while `D_i`'s own Q2 remains subject to marking for every *other* purpose. That preserves termination (still monotone: marks only go effective→ineffective) and kills the immunity. Then add a §12 residual naming the remaining irreversibility, and a §9 degraded-state row for "erroneous or malicious operative revocation" with a defined non-emergency remediation ceremony. `:93` currently defers issuer roles, maximum lookback and dual-control roles to the owner, all `OPEN:` — this must be resolved with them, not after.

### Non-blocking

- **N-a — total break-glass exposure is unstated.** `:270` scopes `BREAK_GLASS_CROSS_INCIDENT_MAX` to "the same approver set and affected boundary", and `:272` requires extensions to use a *different* set. Total exposure is therefore `pool_size × 120 min` per rolling 24h, and no cap on pool size is stated. 0C should bound the rotation pool explicitly, since `:270` leaves it `OPEN:`.
- **N-b — the normative registry does not carry the owner's decisions.** `:174` declares the registry normative, but INV-044 `:221` still reads "pending owner decision", and §10 `:276` / §11.5 `:288` still carry `OPEN - OWNER DECISION`, although `DECISIONS-0A.md:11,25` records D-0A-1 and D-0A-2 as decided and says "v0.3 text stands". Deliberate, but a 0C reader working from the registry alone will read an undecided schema.
- **N-c — INV-052 resists ADV-04/ADV-22/ADV-28 while naming the verifier as an owning boundary** (`:229`). Its operative clause ("First-contact… must not issue trusted Q2/Q3/claims") is a verifier duty a compromised verifier simply ignores. Compare INV-017 `:194`, same owner, which correctly lists ADV-04/15/22/28 as non-resisted. §7 is unaffected (ADV-04 is `D` in all six rows), so this is registry hygiene rather than a gate error — but it is the same shape as NEW-2.
- **N-d — INV-053's `Resists` column is profile-conditional but reads unconditional** (`:230`). Its resistance to ADV-14/15/16/18/19/20/21 holds only under an HSM profile; the statement says so in prose and footnote ‡ `:151` handles exactly one claim cell. The column itself carries no marker, so a gate evaluator reading `:230`'s columns on an HSM-unavailable profile gets the wrong answer for seven adversaries.

---

# 4. Batch-1 Critical verdicts

Trace targets: regista at `7707c81` (= checkout HEAD, verified), acb at `f2df972` (= checkout HEAD, verified), cairn traced at `b00169c` (**not** the reviewed `74471ad` — see caveat below the table).

| Finding | Exercises the vulnerable path? | Fails if the vuln were absent? | Severity justified? | Verdict |
|---|---|---|---|---|
| **persist-1** | Yes. `_transition.py:87–99` reads `definition` straight from the mutable `workflow_registry` row and resolves the transition from it; nothing reconciles it to the signed registration. `_v6_writer.py:1250–1319` (`resolve_workflow_binding`) sources the signed `definition_hash` from the `workflow_registered` **event**, so the emitted envelope carries the benign hash — the probe's `envelope["workflow"]["definition_hash"]` assertion (`test_persist_1.py:67`) rests on real divergence. | Yes — a fix rebinding transition resolution to the signed registration raises `RegistaError` → `pytest.fail` at `:55`. | Yes, and **stronger than stated**: `_replay.py:1447–1477` also replays against the same mutable row, so offline replay does not detect it either. | **CONCUR** |
| **persist-2** | Yes. `_events.py:40–67` (`_row_to_event`) hydrates `actor_id`/`actor_metadata` from mutable columns with no envelope reconciliation; `_transition.py:153–159` feeds those to `_review_validators.derive_authors` (`:180–228`), and `_check_separation_of_duties` (`:254–263`) compares `ctx.actor_id` against the row-derived set. | Yes — a row↔envelope reconciliation denies → `pytest.fail` at `:76`. | Yes (SEC-11 at the gate layer). | **CONCUR**, with a regression-test caveat: the probe mutates the rows *permanently*, whereas the inventory (`CONSOLIDATED-INVENTORY.md:383–385`) describes the transient rewrite-then-restore variant that leaves no durable trace. A fix that only detects durable row/envelope mismatch would make this probe pass while the transient attack still works. The regression test derived from it must add the restore step. |
| **persist-4** | Yes. `principal_lifecycle.py:2297–2301` copies `digest_value` verbatim out of the row into the rehydrated `LifecycleOperation`, never recomputing it over `principal_id`/`old_key_id`. `_operation` `:2850–2861` → `_load_operation_from_db` `:2319–2339` for a fresh instance; `commit()` `:1225` then compares that stored digest to `expected_digest` and passes. `_operation_from_row` validates the authority binding against `actor_id` and `requested_authority` (`:2255–2264`) but **not** `principal_id` — which is exactly what the probe substitutes. | Yes — digest recomputation raises → `pytest.fail` at `:94`. | Yes; the emitted `principal_key_revoked` names the victim (`:111`). | **CONCUR** |
| **persist-5** | Yes, precisely. `commit()` at `:1240–1244` selects `state … FOR UPDATE`, then uses `existing_row["state"]` **only** for the already-committed short-circuit (`:1245`); the authorization check at `:1260` reads `operation.state` — the in-memory object returned by `_operation` `:2857–2859`, which returns the process cache without consulting the DB. Textbook check-under-lock-on-stale-state. | Yes — a CAS inside the lock raises → `pytest.fail` at `:48`. | Yes. This is the SEC-09 twin and the direct motivation for INV-054 `:231`. | **CONCUR** |
| **cairn-01** | Yes at the traced ref. `verifier.py:446–449` unconditionally strips **every** `global_seq_gap` from `chain_contiguity_violations` in filtered mode; `:442` additionally sets `chain_integrity_ok = None`, which `all_ok` (`verifier_types.py:495`) treats as not-failed. So filtered verification cannot fail on chain evidence at all. | Yes — `assert report.all_ok` (`:99`) flips. | Yes; broader than the finding text, since chain-integrity checking is disabled wholesale in filtered mode, not just gap reporting. | **CONCUR** (ref caveat) |
| **cairn-02** | Partially verifiable. At `b00169c` the merge loop `verifier.py:2503–2528` copies `total_events`, `ok`, `signature_failed`, `hash_mismatch`, `revoked_key` and the violation lists but carries no per-bundle unverified counter, and `all_ok` `verifier_types.py:494–517` has **no `total == ok` term** — both halves of the finding. However `unverified_events`, the field the probe asserts on (`:44,53`), **does not exist anywhere in cairn at `b00169c`**. It existed at `74471ad`; I cannot read that ref. | Yes at the reviewed ref — a fix adding `merged.unverified_events += r.unverified_events` flips `:53` and `:55`. | Yes, on the evidence in `results/cairn-02.txt` (`single_all_ok=False` → `merged_all_ok=True` over the same bundle). | **CONCUR on the recorded run**; flag that this probe is **not currently re-runnable as a regression test** — against present cairn it raises `AttributeError`, not a clean assertion failure. |
| **acb-1** | Yes for the manifest-authentication mechanism. `model.py:106–127` (`resolve_manifest`) returns the `-m` path with no owner, mode, digest or signature check; `parse_manifest` `:194–203` is plain `tomllib`; `cli.py:512` accepts it and `providers.py:1218–1271` resolves and injects into an attacker-chosen child. | Yes — manifest authentication makes `rc != 0` → `assert rc == 0` (`:40`) fails. | **Partially.** See below. | **CONCUR on the finding; DISPUTE the verdict-file reasoning sentence.** |

**acb-1, in detail.** `VERDICTS.md:11` states *"This establishes critical secret release to attacker code."* The executed probe does not establish that. It declares `source="env"` with `from_env="VICTIM_SECRET"`; `providers.py:1204–1211` reads that variable out of ACB's **own** process environment, and `:1267` builds the child environment as `os.environ.copy()` — so the child already inherits `VICTIM_SECRET` before any injection. No confidentiality boundary is crossed in the run that was recorded.

The Critical severity in the inventory rests on a different path: `CONSOLIDATED-INVENTORY.md:377–379` — *"declares any Vault ref its ambient identity permits… ACB injects the secret into the attacker's executable."* That is the escalation, and it is architecturally present (the same `_resolve` dispatch at `providers.py:1212–1215` routes to `cred_vault.resolve(cap)` with the manifest-supplied ref), but **no executed probe covers `source="vault"` or `source="suite"`**. `REVIEW-minimax.md:17` reaches this ground and resolves it as "carried by the mechanism"; I agree the *finding* and its Critical severity stand, and I concur with the verdict. What I dispute is the evidentiary claim in `VERDICTS.md`'s reasoning column, and the practical consequence: the regression test derived from this probe will not detect a fix that authenticates the manifest for `env` but leaves the vault-ref path open. A second probe on `source="vault"` should be added before this row is treated as closing acb-1 at the cutover gate.

**Batch-level notes.** The harness is sound: `run_critical_probes.py:54–56` hard-fails on `HEAD != reviewed_ref`, and `:57–58` digests `git archive HEAD`, which binds the fixture to the exact tree. No probe monkeypatches the component under test (`test_acb_1.py`'s `monkeypatch.setenv` is environment setup, not a component patch), and `_regista_probe.ordinary_project:44–50` creates a genuine signed v6 project per test.

---

# 5. Should anything in the 0A exit be reopened?

No. The three NEW findings are bounded and mechanical — two are table-consistency errors correctable by editing eleven cells and one prose row, and the third is a scoping clause in one sentence of §5 — and none of them disturbs a freeze-gate criterion: the seven Criticals reproduce at their reviewed refs with a real HEAD guard and a second-lineage CONCUR (criterion 2), the 78-row sweep and the 147-row matrix are unaffected (criteria 3–4), the rubric freeze and D-0A-1..11 are untouched (criteria 5–6), and all thirteen of my original blocking items on 0A-1 are genuinely closed against the v0.3 text, which is what criterion 1 turned on. `EXIT-0A.md:18` already carries this pass forward as advisory precisely so that a late confirmatory finding does not have to unwind a gate. What the findings *do* require is a scheduled erratum: NEW-1 and NEW-2 must be corrected in a v0.4 before §7/§8's adversary columns are used as the cutover-gate input that `025-provenance-security-remediation.md:186` makes them, and NEW-3 must be resolved with the owner at the same time as the `OPEN:` retroactive-revocation parameters at `TRUST-MODEL.md:93` — that is, before 0C selects the retroactive policy, not after. One 0A-3 consequence to check when NEW-2 is applied: the seven affected invariants (INV-001, 002, 004, 028, 030, 053, 059) are cited across the matrix's `invariant_ids` column, so the ADV-29 correction should be re-run through the Fable scripted check rather than hand-patched.
