# 0A-2 / 0A-3 / 0A-5 — reviewer 2 notes (Claude Opus, security-focused, 2026-08-26)

Drafts reviewed: `MECHANISM-TAXONOMY.md`, `MATRIX-SCHEMA.md`, `MATRIX.csv`, `BAKEOFF-RUBRIC.md`, against `README.md` (charter), `TRUST-MODEL.md` v0.2, `CONSOLIDATED-INVENTORY.md`, and my prior `REVIEW-0A1-opus.md`. No file was edited.

---

## VERDICT

| Work product | Verdict |
|---|---|
| **0A-2** — mechanism taxonomy + reproduction set | **rework** (7 blocking) — the partition and the 78-row derivation are correct and should be *retained*; the probe sketches and three ownership calls are not usable as written |
| **0A-3** — matrix schema + 147-row matrix | **rework** (5 blocking) — mechanically clean, but 30 rows carry a disposition the schema itself admits is unverified, and ≥7 rows contradict the accepted trust model or the taxonomy |
| **0A-5** — bake-off rubric | **rework** (6 blocking) — genuinely frozen-before-measurement and well structured, but the invariant gate as written disqualifies every candidate on paper, and it exercises none of the v0.2 invariants |

### What survived the attack (stated up front, because it is the load-bearing part)

I re-derived the charter selection rule by hand for the whole taxonomy, not six mechanisms. The arithmetic is exactly right:

- **147 findings, 103 mechanisms, each finding in exactly one mechanism.** Verified mechanically: 147 unique ids across the Mechanisms section, every count = 1, and the set equals the inventory's 147 ids. No orphan, no double-membership.
- **Matrix = 147 rows, one per inventory id, no duplicates.** Component tallies match the inventory row-for-row (acb 16, agent-notes 15, agent-suite 16, agent-wake 14, cairn 22, crypto 7, dossier 17, persist 16, regista-cli 11, trustlog 13). All `class` and `daybreak_severity` values match the inventory. All seven refs are lowercase 7-char and correctly mapped. Exactly the 13 SEC rows carry `verified_severity`.
- **78 is the right size.** Independent derivation: 59 mechanisms at effective severity ≥ High × 1 dominant selection = 59; + 18 second-component obligations (mechanisms spanning >1 component); + 1 extra mandatory Critical (`persist-4`, not the dominant pick of `row-envelope-reconciliation`) = **78**. The table contains 78 rows, 17 labelled "Second component" plus `acb-1`'s "Critical + second component" = 18. All 7 Criticals present. All 59 ≥High-bearing mechanisms have ≥1 entry. I checked the dominant-component and tie-break derivation by hand for `row-envelope-reconciliation`, `canonical-subject-reconciliation`, `executable-identity-binding`, `release-content-pinning`, `legacy-envelope-key-retirement`, `authority-at-chain-position`, `authenticated-approval-and-sod`, and `typed-gate-result-and-exit-semantics` — every one matches the stated rule, including the deliberately below-High picks (`SEC-04`, `SEC-06`, `SEC-08`).

The inflation, where it exists, is **not** rule misapplication — see NB-1.

---

## BLOCKING

### 0A-2 — taxonomy and reproduction set

**B1 — `MECHANISM-TAXONOMY.md:70`, `MATRIX.csv:65`: `cli-3` is assigned to the kernel, which `TRUST-MODEL.md:234` explicitly forbids.**
The v0.2 coverage sweep states, normatively: *"`cli-3` (secret disclosure), `acb-10` (TOML injection). Their matrix rows must remain owned by `app:regista-cli` and `broker`, respectively, with regression tests; **they are not silently assigned to the kernel**."* The taxonomy assigns `stored-secret-access-control` to "kernel-side service edge" and `MATRIX.csv:65` sets `owning_boundary=kernel`. This is the exact substitution the trust model was written to prevent, and it moves a High credential-disclosure defect out of the app backlog and into a boundary that will later claim invariant coverage for it.
*Required change:* set `cli-3` `owning_boundary` to the value the trust model names, and add `app:regista-cli` to the enum (see B8). Re-word the mechanism's owning-boundary sentence to match.

**B2 — `MECHANISM-TAXONOMY.md:79` vs `MATRIX.csv:75`, and `:83` vs `:85`: two direct taxonomy↔matrix ownership contradictions.**
- `transition-role-default-deny` declares *"Owning boundary: gate-engine"* for `cairn-15, as-14, an-4`. `MATRIX.csv:75` gives `cairn-15` `owning_boundary=kernel`, `phase=Phase 2`; `as-14` and `an-4` get `gate-engine`/`Phase 3`. One mechanism, one declared boundary, three different matrix answers.
- `typed-gate-result-and-exit-semantics` declares *"bootstrap-root for suite and broker for capability health"* for `as-3, as-16, acb-6`. `MATRIX.csv:80` gives `as-3` `bootstrap-root`/`Phase 6` (correct), `MATRIX.csv:85` gives `as-16` `gate-engine`/`Phase 3` (contradicts), `acb-6` `broker` (correct). `as-16` is the same suite CLI exit-code defect as `as-3`.

These are not cosmetic: `owning_boundary` drives `phase`, and `phase` drives what lands in the first vertical slice.
*Required change:* reconcile each row against its mechanism's declared boundary, or make the mechanism entry state the per-finding split explicitly (as `row-envelope-reconciliation` and `entity-namespace-binding` already do correctly).

**B3 — `MECHANISM-TAXONOMY.md:19` vs `TRUST-MODEL.md:160-161`: `persist-9`'s primary mechanism is wrong, and `aw-7`'s divergence is unrecorded.**
The accepted v0.2 registry homes `persist-9` under **INV-005** (*"Accepted events form one unique-position predecessor chain… Motivated by `persist-9`, `cairn-01`, `persist-11/12`"*), not INV-004. The inventory's own text agrees: *"Global chain head trusted without reconciling to its named event → **validly signed fork**"* (`CONSOLIDATED-INVENTORY.md:177`). The taxonomy folds `persist-9` into `row-envelope-reconciliation`, whose closing control is envelope authentication and field reconciliation — which does not close a chain-head-selection fork. Conversely `aw-7` **is** in INV-004's motivation list but the taxonomy gives it a standalone mechanism (`queued-row-ingress-authenticity`). I think the `aw-7` split is substantively *better* than the inventory's dedup note (there is no signed envelope to reconcile against; the defect is an unauthenticated durable ingress) — but it is undeclared drift from an accepted document.
*Required change:* move `persist-9` to a chain-uniqueness/fork mechanism aligned with INV-005, or state the counter-argument in the entry. Record the `aw-7` divergence from INV-004 in the taxonomy so the dedup story stays auditable when `invariant_ids` is populated.

**B4 — `MECHANISM-TAXONOMY.md:147-226`: none of the 78 probe sketches is falsifiable as written — there is no pass/fail oracle and no `not-reproducible` vs `invalidated` discriminator.**
Every sketch has the form *"do X and demonstrate Y."* The charter (`README.md:35`) requires each reproduction to yield one of `confirmed / confirmed-at-different-severity / not-reproducible / invalidated` and says explicitly *"Non-reproducible ≠ invalidated: state which."* Nothing in any of the 78 rows states what observation would distinguish "the probe could not be built / the path is unreachable in this fixture" from "the finding's premise is false." `MATRIX-SCHEMA.md:39` then depends on that distinction (*"`invalidated` requires an attempted reproduction whose reviewed verdict is `invalidated`; `not-reproducible` alone never invalidates a row"*), so the discriminator is load-bearing and absent. An executor handed these sketches can only ever return `confirmed` or a shrug.
*Required change:* each row needs (a) the fixture/preconditions, (b) the concrete observable that constitutes `confirmed`, and (c) the observable that would constitute `invalidated` as distinct from `not-reproducible`.

**B5 — `MECHANISM-TAXONOMY.md:218`: the `crypto-4` sketch conflates two different claims.**
*"invoke Windows public-identity flow and demonstrate a machine-scope **decryptable** private-key blob reaches argv/output."* Observing a blob in argv establishes exposure; it does not establish machine-scope decryptability by the adversary, which is what makes it High. As written the probe will over-claim or under-claim depending on the executor. Same shape, weaker: `as-5` (`:224`) says "secret material appears in argv or diagnostics" without saying whether a *reference* appearing counts. Given `INV-053` now distinguishes references from material, the probe must too.
*Required change:* split into the two observations and state which one carries the severity.

**B6 — `MECHANISM-TAXONOMY.md:145`: "59 High-bearing mechanisms" is only reachable by reading "High-bearing" as "severity ≥ High", which the document never says.**
Strictly applying `README.md:33` (*"every mechanism that contains ≥1 High"*) with the taxonomy's own six-level ordering (`:7`) yields **56** mechanisms. The stated 59 is 56 + the three Critical-only-no-High mechanisms (`signed-policy-as-authority`, `filtered-verification-preserves-global-failures`, `locked-state-revalidation-at-commit`). The reading is right, but it is unstated and it is what puts `SEC-09` (Medium, already Opus-verified) into the set as `locked-state-revalidation-at-commit`'s second-component obligation — one of the 78 probes exists only because of an unwritten definition.
*Required change:* state the definition in Selection semantics and mark it for owner confirmation alongside the existing `OPEN:` at `:11`, since `MATRIX-SCHEMA.md:54` requires recomputation if High-bearing membership changes.

**B7 — the chartered 0A-2 deliverables do not exist.**
`README.md:29` names `plans/025-0a/REPRODUCTIONS.md` **+ probes in the evidence repo**. What exists is a probe *plan* inside `MECHANISM-TAXONOMY.md`, with `ASSUMPTION:` at `:143` conceding *"no probe was run or written here."* No `REPRODUCTIONS.md`, no committed probes, no verdicts, no second-lineage verdict review, no `verified` column added to the inventory. Five of the six 0A-2 acceptance clauses are therefore not met (table below). I flag this as blocking on the *work product*, not on the drafter — the reproduction executors have not run — but the 0A exit gate (`README.md:63`) cannot be signed on the taxonomy alone.

### 0A-3 — schema and matrix

**B8 — `MATRIX-SCHEMA.md:22`: the `owning_boundary` enum cannot express what the trust model requires, and it silently collapses ten distinct taxonomy boundaries into `kernel`.**
The enum is `kernel | gate-engine | broker | bootstrap-root | app:agent-notes | app:dossier | transport`. It has no `app:regista-cli`, which `TRUST-MODEL.md:234` requires for `cli-3` (see B1). Separately, the taxonomy uses ten sub-boundaries that have no CSV representation and all land as `kernel`: *kernel temporal state machine, kernel persistence, kernel migration, kernel migration path, kernel migration verifier, kernel signing edge, kernel-side service edge, kernel service edge, kernel CLI edge, kernel conformance surface, kernel claim production*. The result is that **58 of 147 rows (39%) share one owner value** covering everything from `cli-9`'s `sign-genesis` symlink race to `persist-12`'s migration chain discontinuity. The acceptance criterion "no row with an empty owner" is met literally while the property it exists to guarantee — an accountable boundary per row — is not.
*Required change:* add `app:regista-cli`; either add the kernel sub-boundaries to the enum or add a `sub_boundary` note convention, and require that every row's value be derivable from its mechanism entry.

**B9 — `MATRIX.csv`: 30 rows (20%) carry `deferred-profile` on a premise the schema itself marks unverified — including 1 of 7 Criticals and 19 of 73 Highs.**
Every `acb` row (16) and every `agent-wake` row (14) is `deferred-profile`, `Phase 5`. `MATRIX-SCHEMA.md:38` permits this *"only while the affected capability or transport surface is absent and structurally unreachable in the relevant signed profile"* — and `:61` then concedes `ASSUMPTION: deferred-profile is valid provisionally for all broker and transport rows **only if** those surfaces meet the plan's machine-checkable structural-unreachability definition.` That predicate is unverified, and the signed-profile mechanism it depends on (`INV-037`) is itself an unbuilt Phase-6 control. Meanwhile both surfaces are demonstrably live in the estate today — the workspace's `cred-ldap-bind`, `cred-svc-da`, `cred-pypi` skills invoke `acb` directly, and agent-wake has open work items (WI-083). So the disposition is asserted, not established, for:
- `MATRIX.csv:27` **`acb-1`, Critical** — attacker-supplied manifest → attacker binary receives attacker-chosen secret.
- `MATRIX.csv:26` **`aw-7`, High** — which `TRUST-MODEL.md:160` places in the INV-004 row-vs-envelope cluster whose siblings (`SEC-11`, `persist-2/4/9`, `dossier-2/4`, `an-8`) are all `core` and Phase 1–4. Same invariant, one member deferred four phases behind a profile.
- `MATRIX.csv:143` `acb-10` (High, TOML injection), `:147` `acb-15`, `:148` `acb-16`, `:141` `aw-11`, `:142` `aw-12` — defects in the *current* tool on developer hosts, whose reachability has nothing to do with whether a future signed capability profile is enabled.

Nothing in the matrix or schema records *which* profile, or any gate that will force the change `:38` promises.
*Required change:* `deferred-profile` must be a per-finding determination with a named profile and a stated unreachability argument, not a per-component default. Until the structural-unreachability predicate is machine-checkable, `acb-1` and `aw-7` at minimum must carry `partially-mitigated` with residual ownership in notes.

**B10 — `MATRIX.csv`: at least five rows assign an `owning_boundary` that contradicts the owner of the invariant `TRUST-MODEL.md:224-234` homes them under.**

| Row | Matrix owner | Trust-model home | Registry owner |
|---|---|---|---|
| `SEC-05` (`:61`), `as-13` (`:83`), `persist-13` (`:70`) | `gate-engine` | INV-009 (`TM:165`) | `bootstrap + kernel` |
| `acb-9` (`:29`) | `broker` | INV-035 (`TM:191`, moved there by N9) | `bootstrap` |
| `dossier-14` (`:79`) | `app:dossier` | INV-036 (`TM:192`, moved there by N9) | `bootstrap` |
| `cairn-15` (`:75`) | `kernel` | INV-024 (`TM:227`, `TM:180`) | `gate` |

`MATRIX-SCHEMA.md:36-37` will require these rows to cite `invariant_ids` before any closure claim. A row whose owner is not the invariant's owner cannot cite it without either re-homing the finding or re-assigning the invariant.
*Required change:* reconcile each pair, or add a note stating why boundary ≠ invariant owner for that row (legitimate for `INV-045`-style "each consumer" invariants, not for the single-owner ones above).

**B11 — `MATRIX.csv:52`: `an-5` is assigned `owning_boundary=kernel`, splitting it from `an-6` and `an-9`, which the same trust-model invariant groups with it.**
`TRUST-MODEL.md:209` (INV-053) cites *"`crypto-4`, `as-5`, `an-5/6/9`"*. The matrix gives `an-6` and `an-9` `app:agent-notes` and `an-5` `kernel`. `an-5`'s cited locations are agent-notes' own `_native.py` and `kernel.py` — the latter is agent-notes' internal module, not the provenance kernel. The taxonomy's phrase "kernel claim production" (`:57`) appears to have been read off the filename.
*Required change:* either move `an-5` to `app:agent-notes` at command ingress with a kernel claim input (the pattern `unsigned-operation-rejection` at `:86` already uses), or state why the same trio splits.

**B12 — `MATRIX.csv:122`: `cairn-18` is assigned `owning_boundary=app:dossier`, `phase=Phase 4`, on a component-merge that 0A explicitly does not decide.**
`cairn-18` is cairn's own `_portal.py` XSS. The note reads *"portal behavior moves to hardened human surface"* — a product-consolidation decision. `README.md:63` states *"No API, repo layout or component ownership is frozen by 0A."* Assigning the row to another product's boundary silently transfers a live defect to a backlog it is not on, and pushes it from cairn's own remediation to Phase 4.
*Required change:* keep the row on a cairn-accountable boundary with the consolidation recorded as an `ASSUMPTION:` in notes, or mark the boundary provisional the way dispositions are.

### 0A-5 — bake-off rubric

**B13 — `BAKEOFF-RUBRIC.md:68, 71, 72, 73, 74`: five of the seven adversary rows demand a PASS on invariants the trust model states do **not** resist that adversary. Combined with `:94`, every candidate is disqualifiable on paper.**

| Rubric row | Cited invariant | Trust model says |
|---|---|---|
| `ADV-03` (`:68`) | `INV-005`, `INV-014` | `TM:161`, `TM:170` — both list **ADV-03** under *does not resist* |
| `ADV-14` (`:71`) | `INV-005`, `INV-014` | both list **ADV-14** under *does not resist* |
| `ADV-23` (`:72`) | `INV-015` | `TM:171` lists **ADV-23** under *does not resist* |
| `ADV-26` (`:73`) | `INV-005`, `INV-014` | both list **ADV-26** under *does not resist* |
| `ADV-27` (`:74`) | `INV-015`, `INV-038` | `TM:171`, `TM:194` both list **ADV-27** under *does not resist* |

`§7.1` bullet 1 (`:94`) disqualifies on *"a demonstrated applicable `INV-*` failure"* with no residual carve-out. The `ADV-14` row's prose handles this correctly (*"A claim of forgery prevention is FAIL"*) but its invariant column does not, and the other four rows have no equivalent prose.
*Required change:* split each row's invariant column into **must-PASS (resists)** and **expected residual (does-not-resist)**, and amend `§7.1` bullet 1 so a demonstrated non-resistance the registry already concedes is *recorded as a residual*, never disqualifying. This is the same B1-class defect (an ID appearing on both sides of a resist boundary) that v0.2 fixed inside the registry and that the rubric has re-imported from outside.

**B14 — the rubric cites no invariant above `INV-049`. Every invariant added in v0.2 — `INV-051` through `INV-059`, and the `CT` test family — is untested, including the two the last review round forced into the plan.**
Cited set is `INV-001, 003–024, 028, 035, 036, 038, 039, 045, 049`. Three of the omissions are squarely substrate properties and produce concrete holes:

- **`INV-054` / `CT` (`TM:151`, `TM:210`)** — added by B10 of my prior review for the `SEC-09`/`persist-5/6/10` class; `TM:151` says *"`CT` is now in Plan 025 section 8."* The rubric has **no concurrency or interleaving workload at all**. "Race readers" appears once, inside `ADV-12`'s injection prose (`:69`), with no interleaving predicate. Expected-state/CAS support under concurrent authority transitions is precisely where Postgres, SQL Server Ledger and immudb differ materially — it is a substrate question, and the bake-off cannot answer it.
- **`INV-051` (`TM:207`)** — added by B4 for writer censorship. The Append predicate (`:51`) fails a candidate for *"silent insertion, deletion, duplicate, mismatch acceptance, or ambiguous authentication"* but not for **silently dropping a submitted event**: a never-appended event creates no discontinuity, so the `ADV-03` expected behaviour (*"clients locally reject discontinuity"*) never fires. A candidate with no acknowledgement/merge-deadline design at all passes both Append and `ADV-03`. This is the exact censorship hole `INV-051` was written to close, reopened.
- **`INV-052` (`TM:208`)** — added by B5 for pin acquisition. The Rollback predicate (`:57`) turns on *"the verifier learns the expected cut from pinned/local independent state"*, but the invariant that governs how a pin is acquired and what first-contact may conclude is never cited or tested.
- **`INV-058` (`TM:214`)** — no workload row exercises anchor outage → degraded operation → recovery → permanent `unanchored=true` disclosure, though `§7.2`'s 20-point "Recovery, degraded state" criterion (`:110`) scores exactly that.

*Required change:* add a concurrency/TOCTOU workload row citing `INV-054`; add acknowledgement-and-merge-deadline to the Append row citing `INV-051`; add pin acquisition and first-contact to the common controls citing `INV-052`; add an unanchored-range row citing `INV-058`. Then state, per omitted invariant, why it is out of scope for a substrate bake-off.

**B15 — `BAKEOFF-RUBRIC.md:52`: the Rotation predicate contradicts an accepted trust-model residual and will produce a false FAIL on every candidate.**
The predicate ends *"Acceptance based on caller time or **stale current-state cache** is FAIL."* But `INV-011` (`TM:167`) *defines* permission-now as using *"effective state at a cut whose witnessed observation age is within the action floor"*, and `TM:279` records as an intentional, accepted residual: *"Permission-now can lag a published revocation by at most the applicable cut-observation/action floor."* Under `§1.3`'s no-change-after-results rule, a frozen predicate that forbids conformant behaviour cannot be corrected mid-run.
*Required change:* qualify to "acceptance from a cut whose witnessed observation age exceeds the applicable action floor is FAIL," and record the floor value in the frozen scale profile.

**B16 — `BAKEOFF-RUBRIC.md:109-110`: two weighted criteria re-weight security that `§7.1` already treats as a gate, and one criterion's low anchors are unreachable.**
- *Operational sustainability and **witness independence*** carries **25 points**, with anchors `0 = not operable or independence absent` and `1 = heroic/manual and unowned`. But `§7.1` (`:96`) already disqualifies *"a witness design that does not place the required quorum in failure domains independent of the writer and DBA (`INV-016`)"*. Any candidate scoring 0 or 1 on independence has already been disqualified, so the criterion's usable range is roughly 3–5 — which inflates its effective weight and lets witness independence be double-counted: once as a gate, once as a quarter of the score.
- *Version-skew and policy governance* carries **5 points**, with `0 = unsafe skew or unsigned policy`. `INV-055` (`TM:211`, monotonic security floors: no rollback or emergency record may lower witness quorum, retire-list coverage, algorithm floor, or custody requirement) and `INV-057` (version floors) are **cited nowhere in `§4`, `§5`, or `§7.1`**. So a candidate that permits a signed rollback lowering witness quorum takes at most a 5-point deduction instead of failing a security invariant. That is security being converted into weight — the thing `§1.4` exists to prevent.

*Required change:* separate the independence gate from the operational-sustainability criterion and rewrite that criterion's anchors over the post-gate range; add `INV-055`/`INV-057` to `§7.1` as disqualifying, leaving only genuinely operational skew concerns in the 5-point criterion.

**B17 — `BAKEOFF-RUBRIC.md:110` and `:98`: 20 points are scored from break-glass evidence that no workload or adversary row ever produces.**
Criterion 2 requires *"dual-control emergency flow and audit closure"*; `§7.1` disqualifies on *"break-glass resuming ordinary operation without the required re-verification and reconciliation (`INV-038`, `INV-049`)."* But `§4` has no break-glass row and `§5` has no break-glass adversary — `ADV-34` (emergency approver collusion, `TM:132`) is not among the seven scenarios. The only place break-glass appears is `§6`'s table (`:84-86`), which asks the candidate to **record** behaviour. `§7.2:118` states *"A vendor feature list, architectural preference, or unvalidated target-environment assumption is not measurement"* — by its own rule, 20 points are being awarded for description.
*Required change:* add a mandatory break-glass workload row (invoke, act, expire, reconcile, close) exercising `INV-049`'s cumulative cap and chained pre-numbered records, or move break-glass out of the scored criterion.

**B18 — `BAKEOFF-RUBRIC.md:31` + `:14` + `:11`: the time box plus the no-change freeze makes universal `INCOMPLETE` the likely outcome, and unfixable once frozen.**
5 engineer-days per candidate must cover: environment build; 10 workload rows including clean-host restore and a full projection rebuild; 7 adversary scenarios with before/after cut and digest capture; the `§6` operational table; **and Windows *and* Linux client/driver exercises for every candidate** (`:38`). `§1.6` then makes unfinished mandatory work `INCOMPLETE`, *"which is disqualifying"*. `§1.3` forbids changing the workload after measurement begins. If the box is short — and for three unfamiliar substrates including an immudb build and a SQL Server 2022 Ledger HA/restore rehearsal, it is — the frozen rubric produces no eligible candidate and no permitted remedy.
*Required change:* designate a **mandatory security core** (the rows whose incompleteness disqualifies) distinct from rows that may record `INCOMPLETE` without disqualification, and have the owner size the box against the core before the freeze. Note `§3`'s own `ASSUMPTION:` already marks the figure as unapproved.

---

## NON-BLOCKING

**NB-1 — the 78-probe workload comes from taxonomy granularity, not from rule misapplication.** 74 of 103 mechanisms are **singletons** (only 29 have >1 member). For a singleton containing a High, "reproduce the highest-severity finding in the most-populated component" degenerates to "reproduce that finding." The set therefore covers 72 of the 80 findings rated ≥High — 90% of the estate's severe findings, at 53% of all findings. The charter's own example vocabulary is coarser (`unbounded-parse` alone would absorb several of Sol's separate resource mechanisms). Either merge near-synonymous singletons, or have the owner explicitly accept a ~78-probe 0A-2 before probes are commissioned. This belongs with the existing `OPEN:` at `MECHANISM-TAXONOMY.md:11`.

**NB-2 — 102 of 103 mechanisms sit wholly inside one C-class.** Only `executable-identity-binding` (`as-1` C1, `acb-5` C1, `acb-7` C3) crosses. The taxonomy is a strict *refinement* of the inventory's triage classes rather than an independent decomposition — which is what `README.md:31` asked for ("finer than C1–C5"), so this is not a defect. But it means the taxonomy inherits every C-class mis-assignment in the inventory unexamined, and no mechanism was discovered by regrouping across classes. Worth one sentence of disclosure in the taxonomy's status line.

**NB-3 — `MECHANISM-TAXONOMY.md:28` vs `:77`: `checked-evidence-required-for-pass` and `aggregate-verdict-completeness` are not distinct mechanisms.** `cairn-16` is *"Unchecked or indeterminate evidence contributes to PASS"*; `cairn-02` is *"PASS omits unverified counts… or inconsistent totals."* The inventory describes `cairn-16` as *"aggregate PASS ignores `verified=None`"* (`:181`) and `cairn-02` as *"`all_ok` doesn't check `total==ok`"* (`:256`) — the same failed mechanism, and `TRUST-MODEL.md:178` homes both under a single `INV-022`. Merging would place `cairn-16` in a Critical-bearing mechanism without changing the reproduction set. Either merge, or state the distinguishing predicate.

**NB-4 — `MECHANISM-TAXONOMY.md:32`: `as-10`'s primary mechanism is a stretch.** `subprocess-result-authenticity` is defined as *"Parsed child **or remote** output is accepted despite process/transport failure"* — the "or remote" clause exists only to accommodate `as-10`, which has no subprocess. `as-10` is *"Remote shared-service health forged over HTTP (truthy `ok`)"*: an unauthenticated channel plus truthy parsing, i.e. `network-endpoint-authentication` + `typed-gate-result-and-exit-semantics`. `as-10` is Medium and unselected, so impact is low; but the definition was widened to fit a member rather than the member placed by definition.

**NB-5 — `MECHANISM-TAXONOMY.md:9`: the "second component" rule is under-specified for mechanisms spanning 3–4 components.** `authenticated-approval-and-sod` spans trustlog/persist/agent-suite/agent-notes; the charter says only *"additionally reproduce one in a second component."* Sol picked `an-1` over `as-12` and `SEC-10` — defensible (different logical product, High severity) but not derivable from any stated rule, so the set is not independently reproducible at that row. Extend the tie-break ASSUMPTION to cover second-component choice.

**NB-6 — the SEC severity scale is ambiguous and load-bearing.** The taxonomy's six-level ordering (`:7`) makes `SEC-04` Medium-High, `SEC-06`/`SEC-07`/`SEC-10` Low-Medium; the inventory's four-column tally (`:31`) buckets them into High/Med/Low differently. I verified the ambiguity does **not** flip any mechanism's High-bearing status today (each affected mechanism has another High member), but `MATRIX-SCHEMA.md:54` requires recomputation when verified severities land, so the mapping must be pinned first.

**NB-7 — `BAKEOFF-RUBRIC.md:128`: the candidate-B independence bullet is narrower than the invariant it cites.** It requires the quorum outside *"SQL Server, SQL host/cluster, backup platform, DBA credentials, DBA management plane, and DBA reporting chain."* It omits **`ADV-30` (directory/IdP administrator)** and **`ADV-31` (secret-backend administrator)** — both added in v0.2 (`TM:128-129`), both listed under `INV-016`'s *resists* set (`TM:172`), and `INV-016`'s own predicate says *"no single person/entity/platform admin can alter quorum members."* On a Windows/AD estate the AD admin who can grant DBA rights and owns the identity plane of any Windows-hosted witness is the obvious single point, and `§8` does not ask about them.

**NB-8 — `BAKEOFF-RUBRIC.md:122`: `§8` blocks "environment-fit evidence" from receiving weight but never says which of the seven criteria that is.** Licensing (10), Platform integration (15), Operational sustainability (25) and Recovery (20) are all arguably environment-fit; an assessor could read it as Licensing only and let B keep 90 points. `:130`'s *"receive no favorable environment-fit assumption"* is not a number. Name the blocked criteria and the treatment while `OPEN` (I suggest: criterion not scored, candidate not eligible for a weighted total).

**NB-9 — `BAKEOFF-RUBRIC.md:120`: the premise checklist is B-only, which is chartered but asymmetric.** A and C also rest on unvalidated premises (a second independent witness operator that does not exist yet; immudb licensing/support and staffing). `§1.7` says no candidate is pre-scored, but only B's premises face a gate. Apply `§7.2:118`'s evidence rule symmetrically in the result record even though only B gets the formal checklist.

**NB-10 — `BAKEOFF-RUBRIC.md:23`: candidate A is described in the requirement vocabulary, B and C as products.** A's entry *is* the target design (signed append-only log + witnessed transparency-log checkpoints); the workload predicates are then written in that vocabulary (cuts, checkpoints, inclusion/consistency proofs). That is legitimate — the requirements are the requirements — but the rubric should say plainly that describing A in the predicates' own terms confers no credit and that A must be measured, not asserted.

**NB-11 — `BAKEOFF-RUBRIC.md:64` vs candidate B's verification mechanism.** `§5` says *"A database's or writer's self-report is not independent detection"* and `§7.1`'s last bullet disqualifies *"dependence on a centralized unauthenticated/self-authenticated verdict."* SQL Server's Ledger verification runs inside the instance. B may therefore be structurally ineligible — which would be a pre-judgement, contrary to `§1.7`. State the discriminator now: in-database verification satisfies the requirement only if the digest chain is independently verifiable by an external verifier from independently retained digests, and name the evidence that settles it.

**NB-12 — process/traceability.** (a) The taxonomy and the reproduction set were committed together, so there is no evidentiary separation for `README.md:31`'s *"the taxonomy is written before selection and committed."* Split the commits or record the taxonomy's frozen digest. (b) `MATRIX.csv` `owning_boundary`, `phase` and `profile_gate` all encode target-decomposition design choices, but only `disposition` is marked provisional (`MATRIX-SCHEMA.md:35`); given `README.md:63`, the other three should carry the same provisional marker. (c) `MECHANISM-TAXONOMY.md:143`'s `ASSUMPTION:` correctly notes the reviewed refs, but the file has no version header matching `TRUST-MODEL.md`'s convention — add one so the freeze gate can cite a version rather than a path.

---

## Charter acceptance criteria

### 0A-2 (`README.md:29-37`)

| Criterion | Status |
|---|---|
| Mechanism taxonomy: each of the 147 findings tagged with a mechanism finer than C1–C5 | **met** — verified: 147 unique ids, each in exactly one of 103 mechanisms |
| Taxonomy written before selection and committed | **met in substance, not in evidence** — same commit, no separation (NB-12a) |
| Selection rule correctly applied for representative Highs | **met** — 59 mechanisms + 18 second-component + 1 extra Critical = 78, re-derived independently (B6 caveat on the unstated "High-bearing" definition) |
| All 7 Criticals reproduced unconditionally | **not met** — all 7 are *planned*; none attempted |
| Every High-bearing mechanism has ≥1 attempted reproduction | **not met** — all 59 covered *in the plan*; none attempted |
| Each reproduction is an executable probe with observed outcome and verdict | **not met** — 78 prose sketches, no oracle, no verdict discriminator (B4, B5) |
| Probes committed and re-runnable | **not met** — no probes exist (B7) |
| Verdicts reviewed by a second lineage | **not met** — nothing to review |
| Inventory severities updated with a `verified` column | **not met** |
| Deliverable at `plans/025-0a/REPRODUCTIONS.md` | **not met** — content is in `MECHANISM-TAXONOMY.md` |

### 0A-3 (`README.md:39-45`)

| Criterion | Status |
|---|---|
| 147 rows present | **met** — exactly 147 data rows, one per inventory id, no duplicates, component tallies match |
| Every row has `mechanism` | **met** — all nonempty, all are declared taxonomy slugs |
| Every row has provisional `disposition` | **met literally**; **contested for 30 rows** (B9) |
| Every row has `owning_boundary`, none empty | **met literally**; **not met in substance** (B8, B10, B11, B12) |
| Every `fully-closed-by-kernel` row cites an `INV-` id | **met** — zero such rows, and `MATRIX-SCHEMA.md:59` states honestly why. This is the right call |
| Committed schema matches the charter's 16 columns | **met** — header is exact; `MATRIX-SCHEMA.md:3` correctly notes the charter's parentheticals are not header text |
| Schema reviewed by a second lineage (gate infrastructure, WI-008 two-reviewer rule) | **not met** — this review does not concur; see B8 |

### 0A-5 (`README.md:55-59`)

| Criterion | Status |
|---|---|
| Rubric committed before 0B starts | **met** |
| No candidate pre-scored | **met** — no scores anywhere; `§1.7` states it explicitly and `§2` labels B's fit an open hypothesis |
| Candidates A/B/C defined with neutral test boundaries | **met** (NB-10, NB-11) |
| Falsification workload: append, rotation, proof, checkpoint, fork/rollback, restore, representative reads | **met** — all seven present, plus revocation-with-effect-range and projection rebuild. **Incomplete** for concurrency, censorship-acknowledgement, pin acquisition, unanchored range, break-glass (B14, B17) |
| Adversary scenarios from 0A-1 **by invariant id** | **not met** — 7 scenarios present, but 5 of 7 cite invariants that do not resist the adversary being run (B13); selection rule for the 7-of-34 is unstated |
| Operational-requirements table columns (plan §6) | **met** — seven columns, all three candidates populated with required-evidence prompts |
| Weights | **met arithmetically** (7 criteria = 100); **contested** — security re-weighted (B16) |
| Premise-validation checklist for B (5 chartered elements) | **met** — all five present; **insufficient** as a gate (B16 independence scope NB-7, criterion mapping NB-8) |
| Language/stack criteria recorded for 0C | **met** — `§9`, five criteria, correctly marked decision-criteria-only |
| Two lineages concur | **not met** — this review does not concur |

---

## Recommended sequencing

B1, B2, B3, B10, B11 are single-row corrections against documents that already exist and can be fixed in one pass. B8 and B9 change the schema and 30 dispositions and should be resolved before any probe is commissioned, since `MATRIX-SCHEMA.md:54` requires recomputing representative-High coverage if membership shifts. B4/B5 (probe falsifiability) gate the 0A-2 executors and are the highest-value fix in this round. B13–B18 gate the rubric freeze; B13 and B14 are the two that would otherwise make 0B produce an unusable result, and B14 is the second time the concurrency/TOCTOU family has had to be argued into a Plan 025 artifact after being accepted into the plan.
