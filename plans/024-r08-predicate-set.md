# Plan 024 — The R-08 predicate set

**Status: DRAFT for review** (2026-08-03). Closes Plan 023 **O-1** when
ratified; O-1 is required before M3, so this document gates M3. It also
records the **WI-241 decision** (key-registry scoping), which Plan 023
deferred to the identity model deliberately.

Everything here traces to Plan 023: the five facts are R-08's rows; the
wire format is R-19–R-22; the trust model is R-07/R-09/R-10/R-11; the
honesty rules are R-01/R-03. Where a field's backing evidence exists
today, the source is named; where it does not, the gap carries a
milestone (M3/M4) and an owner component. Grounding facts about current
capture were inventoried 2026-08-03 from the cairn source (rc-build
checkout at regista spine 0.5.5-era mains); file citations are
point-in-time and will drift.

---

## 1. Method

- **One predicate type per fact class (R-22).** Five predicate types,
  versioned independently:
  `https://hraedon.com/attestations/{authorization,execution,authorship,observation,ordering}/v1`
- **DSSE envelopes carrying in-toto v1 Statements (R-19).** The
  statement `subject` is always the concrete artifact the fact is about
  (a content digest — transcript, message, diff, verdict document),
  never a mutable record ID alone.
- **Attest, never mirror (R-03).** Predicates reference coordination
  records (work items, sessions) by opaque ID + digest; they never
  embed mutable state.
- **Offline verification (R-21).** Every field is verifiable from the
  statement, its signature, published key material, and the log
  receipt. Fields that cannot be are marked `declared` and must be
  treated as claims (R-01 — never upgrade a declaration to a
  measurement).
- **Actors sign claims only (R-11).** No predicate contains a
  server-assigned sequence number, prev-hash, or service timestamp as
  a signed field; ordering lives exclusively in the ordering predicate,
  recorded by the service and verified separately.

**Evidence grades** (every field carries one in the schema registry):

| grade | meaning |
|---|---|
| `measured` | recomputable from captured bytes (digests, sizes) |
| `probed` | read from a live system at capture time (`claude --version`) |
| `declared` | supplied by the actor about itself (model lineage today) |
| `attested` | vouched by an identified third party (broker, log, human) |

---

## 2. Common conventions

- **Principals** use the WI-055 ratified grammar: `human:<id>`,
  `agent:<id>`, `service:<id>` — stable opaque subject, never a login
  or display name. `key:*` is not a principal. `actor_id`,
  `actor_kind`, and `on_behalf_of` remain independent dimensions;
  disagreement is an explicit conflict state, never silently resolved.
- **Digests**: `sha256:<hex>` (hash-agility via the prefix; sha-384
  events exist and verify today). Payload digests are over RFC 8785
  canonical JSON.
- **Times**: RFC 3339 UTC. Times inside predicates are the *signer's*
  clock and are evidence-graded accordingly; trustworthy ordering comes
  only from the ordering predicate.
- **Workload instance** (new, required by R-07): the unit of "what
  ran", defined as
  `{host, runtime_unit, instance_id, harness: {name, version, config_digest}}`
  where `instance_id` is a UUID minted per process at startup —
  *nothing else on this estate distinguishes two concurrent sessions on
  one host today*. The capture path currently records harness
  name/version/config-digest (probed at session attestation) but **no
  host and no per-instance identity for the main loop** (subagents get
  `agent_id`; the main loop gets nothing) — both are M3 additions to
  cairn.
- **Evidence refs**: `{kind, id, digest}` triples, e.g.
  `{"kind": "regista-event", "id": "<event uuid>", "digest": "sha256:…"}`.

---

## 3. The five predicates

### 3.1 `authorization/v1` — who permitted this

| field | type | grade | backing today → target |
|---|---|---|---|
| `authorized_principal` | principal (`human:`/`service:`) | attested | `on_behalf_of.principal_id` (bridge sets on every event) |
| `delegation_chain[]` | `{delegator, delegate, scope, granted_at, expires_at, evidence_ref}` | attested | `build_delegation_chain` shape exists (outermost→innermost); evidence_ref is EMPTY today — M3: signed delegation records replace ambient env config |
| `scope` | string (capability statement) | declared → attested at M3 | scope attestation payload carries `scope_statement` today, self-declared |
| `instruction_ref` | evidence ref | measured | digest of the instruction span (transcript segment / tracker item body) that constitutes the grant |
| `granted_at` | time | declared | signer clock |

**Does not claim:** that the authorized principal was personally
present, or that the scope was honored — execution and observation
carry those. A signature by an `agent:*` credential under an
`on_behalf_of` proves *a delegation was claimed*, not that the human
acted (WI-055 ratification wording).

**Verification:** the delegation chain must terminate in a `human:` or
`service:` principal whose key/identity is enrolled; each hop's
`evidence_ref` digest must resolve; `expires_at` must cover the
execution predicate's window.

### 3.2 `execution/v1` — what ran it

| field | type | grade | backing today → target |
|---|---|---|---|
| `workload_instance` | (§2) | probed → attested at M3 | harness name/version/config_digest exist; host + `instance_id` MISSING (M3, cairn) |
| `orchestrator` | `{name, version}` | probed | harness identity; distinct from the model |
| `credential_binding` | `{issuer, credential_id, issued_at, expires_at}` | attested | MISSING today — M3: acb-issued short-lived credential id (never the secret); L-1 may later swap in SVID identity, same field shape (O-3 two-phase) |
| `session_id` | UUID | measured | harness `session_id`, UUIDv5-coerced by the bridge |
| `parent_instance` | `{instance_id, session_id}` \| null | measured | subagent linkage (`subagent_start/stop` + per-call `subagent` identity); main-loop parentage lands with `instance_id` |
| `window` | `{start, end}` | declared | session attestation → Stop/SessionEnd |

**Does not claim:** what the workload produced (authorship) or that the
capture was complete (observation). Per R-04/R-09, credential
possession here is containment evidence, not authorship evidence.

**Verification:** `credential_binding.credential_id` resolves against
the broker's issuance log; G-4's revocation test operates on exactly
this binding; two concurrent sessions on one host must yield distinct
`instance_id`s (test).

### 3.3 `authorship/v1` — what produced the content

| field | type | grade | backing today → target |
|---|---|---|---|
| `model` | `{id, lineage, provider}` | declared | **NOTHING writes this today** — the verifier already reads `actor_metadata.model_lineage` for assurance but no capture-path writer supplies it. M3: the harness env (`AGENT_SUITE_ACTOR_ID` launch config) supplies it to cairn per session; it stays `declared` — an actor's statement about itself |
| `policy_digest` | digest | measured | system-prompt/config digest at session start (cairn config digest machinery exists; add the prompt input) |
| `input_digest` | digest | measured | user/assistant message digests exist today (`message_digest`) |
| `output_digest` | digest (= statement subject) | measured | assistant message / transcript digests exist |
| `tool_transcript_digest` | digest | measured | tool-call event chain digests (begin/end pairs with args-hash + result digests exist per call; the session-level rollup is the transcript attestation) |

**Does not claim:** independence or correctness. G-3's rule lives here:
an absent `model.lineage` is **UNKNOWN** and lowers assurance — the
regista three-state `LineageRelation` (landed in #25) is the consumer.

**Verification:** `output_digest` recomputable from captured content
(or its encrypted blob's stored plaintext digest); lineage distinctness
for G-2 is judged only across `authorship` predicates whose `model`
fields are populated — two verdicts with the same `lineage` never
satisfy a cross-lineage requirement, and UNKNOWN escalates as SAME.

### 3.4 `observation/v1` — who witnessed it, and what was missed

| field | type | grade | backing today → target |
|---|---|---|---|
| `observer` | `{name: "cairn", version}` | probed | **cairn never stamps its own version into events today** (only harness identity) — M3: add; an observation claim without the observer's version is unattributable to a code revision |
| `harness` | `{name, version, config_digest}` | probed | exists on every payload today |
| `hooks_captured[]` / `hooks_excluded[]` | strings | measured | install-time hook set is known (`HOOK_EVENTS`); Codex's reduced set + verbatim uncaptured-path naming already models the honest-exclusion shape |
| `completeness` | `{degradation_log_digest, truncation_policy, gaps[]}` | measured | degradation JSONL exists and survives session end — its digest belongs IN the predicate; gap taxonomy exists verifier-side (sequence, contiguity, attestation, silence, content-coverage) and is referenced by type name |
| `content_stance` | `on\|off\|external` | measured | already recorded as the *verified* stance, never merely configured — keep exactly this semantic |
| `session_ref` | evidence ref | measured | session attestation event |

**Does not claim:** that what was captured is all that happened — it
claims the *inverse*: here is precisely what was not captured
(excluded hooks, degradations, truncations, withheld content with
reasons). This is R-01 as a schema: an observation names its own
boundary. A `SilenceGap` (a session that never reached the log) is by
definition assertable only by a *different* observer — the doctor's
cross-check, not the session's own predicate.

**Verification:** degradation log digest matches the preserved file;
every content field is either present, encrypted-with-digest, or
withheld-with-reason (`content_encryption_error` already lands inside
the signed payload today — keep that).

### 3.5 `ordering/v1` — when it was committed, immutably since

| field | type | grade | backing today → target |
|---|---|---|---|
| `log` | `{origin, log_id}` | attested | M4: Tessera (O-2 decision); today's stand-ins (RFC 3161 batches, witness receipts, bespoke Merkle) retire at M4 and are NOT modeled here |
| `checkpoint` | `{tree_size, root_hash, signature}` | attested | Tessera checkpoint format, verified with the log's published key |
| `inclusion_proof` | proof | attested | standard tile/inclusion proof; verified offline per R-21 |
| `statement_digest` | digest | measured | digest of the DSSE envelope this receipt covers |
| `integrated_at` | time | attested | the log's time, the only timestamp in the system graded above `declared` |

**Does not claim:** anything about content semantics. It is the one
predicate produced by infrastructure rather than an actor, which is
exactly R-11's split: actors sign claims; the service records order;
each is verified separately.

**Verification:** G-1's walk: statement digest → inclusion proof →
checkpoint → log key. No live service.

---

## 4. Composition — how the gates read

A **review verdict** (G-2) is: an `authorship` predicate over the
verdict document (distinct `model.lineage`), an `execution` predicate
(distinct `workload_instance` — the actual G-2 requirement), an
`authorization` predicate (who asked for the review), all over the same
statement subject, each with an `ordering` receipt. Lineage
distinctness alone is *never* sufficient; instance distinctness alone
is *never* sufficient; G-2 requires both to be present and distinct,
and any UNKNOWN escalates (G-3).

A **captured session** (G-1) is: one `observation` + one `execution` +
one `authorization` predicate over the session transcript subject, plus
`authorship` per assistant artifact, plus `ordering` receipts for all
of the above.

---

## 5. The WI-241 decision — key-registry scoping

**Defect recap:** 12,866 `agent_provenance` ed25519 events verify only
against a key registered in the `agent_notes` schema; bundles ship the
wrong registry; third-party offline verification of that slice fails.
The migration comment in `038_principal_keys.sql` anticipated this:
"a shared-catalog option can be added later if principals span
projects." They do — every real principal on this estate spans
projects.

**Decision (target, lands with M3):** principal keys are
**estate-scoped, not project-scoped**. One key registry, owned by C2,
keyed by the WI-055 canonical principal; projects reference it.
Enrollment is the anchored trust root (the WI-209/WI-043 decision:
bundle-carried keys are display-only; the registry is the root).
Rationale: a principal's signing identity is a property of the
principal, not of the schema a given event landed in — per-project
registries are how the WI-241 defect happens *by construction*.
Rotation/revocation stay per-key with validity windows, unchanged.

**Interim (M1 archive, before M3):** the frozen archive may ship a
**signed cross-registry key manifest** — `(key_id, principal,
fingerprint, source_schema, enrollment_event_ref)` for every key that
signed archived events — so offline verification of the ed25519 slice
works against the archive *without pretending* the key was registered
where it was not. The manifest is an `attested` record naming its
asserter, per the WI-055 migration rule (a human claim about history,
not a derivable fact).

**Explicitly rejected:** re-registering the existing key into
`agent_provenance` retroactively (rewrites history's shape); shipping
foreign-schema keys in bundles silently (the current failure, made
policy).

---

## 6. Gap register — what must land, where, when

| gap | owner | milestone |
|---|---|---|
| host + main-loop `instance_id` in capture | cairn | M3 |
| `model.{id,lineage,provider}` supplied per session | harness launch env → cairn | M3 |
| cairn self-version stamped into observation payloads | cairn | M3 |
| `credential_binding` issuance + logging | acb | M3 |
| signed delegation records (replace ambient env delegation) | regista + cairn | M3 |
| estate-scoped key registry | regista (C2) | M3 |
| cross-registry key manifest for the frozen archive | agent-suite archive procedure | M1 (before re-export) |
| degradation-log digest inside session attestation | cairn | M3 |
| Tessera deployment + ordering predicate emission | new (C2 client) | M4 |
| DSSE/in-toto envelope emission for all five types | regista (C2) | M4 |

Nothing in this table blocks the team's current M1 lane (WI-249/242/248
are orthogonal); the M1 item here is only the key manifest, which
WI-241 execution picks up.

---

## 7. Acceptance

- **A-1.** Schema registry: the five predicate schemas land as JSON
  Schema files with per-field evidence grades; CI validates examples
  against them.
- **A-2.** G-1 dry run: one real captured session yields all five
  statement kinds, hand-assembled if necessary, verifying offline with
  the live service stopped — *before* M4 automates emission.
- **A-3.** G-2 dry run: one real cross-lineage review verdict composes
  per §4, and a deliberately same-lineage pair is rejected by the
  composition rule.
- **A-4.** WI-241 interim manifest: the M1 archive re-export verifies
  its ed25519 slice offline using only archive contents.

---

## 8. Deliberately excluded

- Predicate fields for tracker workflow state (R-03, R-17).
- A universal "event" predicate (R-22 — the five facts stay separate).
- Bespoke envelope or proof formats (R-05, R-19).
- Retroactive predicate synthesis for the historical corpus: the
  archive keeps its own frozen verifier; predicates begin at M3/M4.
  History is not rewritten into the new vocabulary (WI-055 migration
  rule).
