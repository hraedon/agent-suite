# Plan 024 — The R-08 predicate set

**Status: DRAFT for review, revision 3** (2026-08-03; r1 reviewed
NEEDS-CHANGES by cross-lineage design review — 7 majors, 15 mediums,
all addressed below). Closes Plan 023 **O-1** when ratified; O-1 is
required before M3, so this document gates M3. It also records the
**WI-241 decision** (key-registry scoping), which Plan 023 deferred to
the identity model deliberately.

Everything here traces to Plan 023: the five facts are R-08's rows; the
wire format is R-19–R-22; the trust model is R-07/R-09/R-10/R-11; the
honesty rules are R-01/R-03. Grounding facts about current capture were
inventoried 2026-08-03 from the cairn source and then independently
spot-checked (11 claims; 3 refuted and corrected here). File citations
are point-in-time and will drift.

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

**Leaf-grading rule** (r1 MED-16): structured fields are graded per
leaf, and a struct's *effective* grade for any composition rule is its
**weakest leaf**. A `workload_instance` whose host is probed but whose
`instance_id` is self-minted composes as `declared`, and no rule in §4
may treat it otherwise.

---

## 2. Common conventions

- **Principals** use the WI-055 ratified grammar: `human:<id>`,
  `agent:<id>`, `service:<id>` — stable opaque subject, never a login
  or display name. `key:*` is not a principal. `actor_id`,
  `actor_kind`, and `on_behalf_of` remain independent dimensions;
  disagreement is an explicit conflict state
  (`principal_kind_conflict`), never silently resolved — and per
  WI-055 refinement 1 the conflict state must be *computed and
  surfaced* by consumers, which today it is not (gap register).
- **Digests**: `sha256:<hex>` (hash-agility via the prefix; the
  sha-384 verification path is proven by test fixture — no production
  events use it today). Payload digests are over RFC 8785 canonical
  JSON. Existing capture stores `tool_args_hash` as bare hex — a
  normalization item for M3 (gap register), not a retroactive rewrite.
- **Times**: RFC 3339 UTC. Times inside predicates are the *signer's*
  clock, graded `declared`; the only timestamp in the system graded
  above `declared` is the ordering predicate's `integrated_at`. Every
  freshness or expiry rule in this document is therefore evaluated
  against `integrated_at`, never against two signer clocks (r1
  MED-15).
- **Workload instance** (new, required by R-07): the unit of "what
  ran":
  `{host, runtime_unit, instance_id, harness: {name, version, config_digest}}`.
  `instance_id` is a UUID **minted once per session** at
  `SessionStart` and persisted in the capture state directory for the
  session's lifetime — *not* per process: every capture hook
  invocation is its own short-lived process, so a per-process ID would
  churn many times within one session (r1 MAJ-7). Nothing on this
  estate mints such an ID today; the main loop has no instance
  identity at all (subagents get `agent_id`). M3 addition, cairn.
- **Evidence refs**: `{kind, id, digest}` triples, e.g.
  `{"kind": "regista-event", "id": "<event uuid>", "digest": "sha256:…"}`.

---

## 3. The five predicates

### 3.1 `authorization/v1` — who permitted this

| field | type | grade | backing today → target |
|---|---|---|---|
| `authorized_principal` | principal (`human:`/`service:`) | **declared** → attested at M3 | `on_behalf_of.principal_id` — ambient env config with a `human:unknown` fallback, absent on work-item `created` events entirely (the API takes no such parameter), so today this is an unverified self-statement (r1 MED-8/9). It becomes `attested` only when signed delegation records exist |
| `delegation_chain[]` | `{delegator, delegate, scope, granted_at, expires_at, evidence_ref}` | attested (target) | the chain-builder shape exists but has **no production callers**, and chain validation never inspects the `delegation_chain` key; `evidence_ref` is empty today. M3: signed delegation records replace ambient env delegation |
| `scope` | string (capability statement) | declared → attested at M3 | scope attestation carries `scope_statement`, presence-checked only |
| `instruction_ref` | evidence ref | measured | digest of the instruction span (transcript segment / tracker item body) constituting the grant |
| `granted_at` | time | declared | signer clock; expiry semantics per §2 (against `integrated_at`) |

**Does not claim:** that the authorized principal was personally
present, or that the scope was honored — execution and observation
carry those. A signature by an `agent:*` credential under an
`on_behalf_of` proves *a delegation was claimed*, not that the human
acted (WI-055 ratification wording).

**Verification:** the delegation chain must terminate in a `human:` or
`service:` principal enrolled per §5's trust root; each hop's
`evidence_ref` digest must resolve; the chain's validity window must
cover the composition's `integrated_at` (§4), not a signer clock.

### 3.2 `execution/v1` — what ran it

| field | type | grade (per leaf) | backing today → target |
|---|---|---|---|
| `workload_instance` | (§2) | host probed; `instance_id` declared → attested at M3; harness see §3.4 | host + session-scoped `instance_id` MISSING (M3, cairn) |
| `orchestrator` | `{name, version}` | probed at session attestation only | harness identity; distinct from the model |
| `credential_binding` | `{issuer, credential_id, issued_at, expires_at}` | attested | MISSING today — M3: acb-issued short-lived credential id (never the secret); L-1 may later swap in SVID identity, same shape (O-3 two-phase). **This is the only field that makes execution more than a self-description** — see §4's pre-M3 honesty note |
| `session_id` | UUID | **probed** (r2 R-5) | harness-supplied, UUIDv5-coerced by the bridge *when non-UUID* (generic `NAMESPACE_URL`) — not recomputable from captured bytes, so not `measured`; the predicate records `session_id_basis: native\|derived` |
| `parent_instance` | `{instance_id, session_id}` \| null | **probed** (r2 R-5) | subagent linkage exists per call and per start/stop window (harness-supplied identifiers); main-loop parentage lands with `instance_id` |
| `window` | `{start, end}` | declared | start = session attestation. **There is no end marker today**: `SessionEnd` emits nothing and `Stop` fires per turn, so `end` is "last Stop observed" — recorded as exactly that, `end_basis: "last_stop"`, until a real end event exists (r1 MED-14) |

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
| `model` | `{id, lineage, provider}` | declared | **nothing writes this today** (verified: every capture-path metadata site is a two-key literal; the verifier hardcodes `lineage_source="asserted"`). M3: the harness launch env supplies it to cairn per session. It stays `declared` permanently — an actor's statement about itself |
| `policy_digest` | digest | measured | system-prompt/config digest at session start (config-digest machinery exists; the prompt input is an M3 addition) |
| `input_digest` | digest | measured (target) | **no backing today**: no shipped integration emits a user message — the `UserPromptSubmit` hook is unwired and the bridge path unreachable (r1 MED-12). M3, cairn (gap register). Until then the field is absent, never fabricated |
| `output_digest` | digest (= statement subject) | measured | assistant-message digests exist (digest over full bytes, truncation-safe) |
| `tool_transcript_digest` | digest | measured (target) | **no rollup exists today**: the Stop-hook digest covers raw hook stdin, begin/end pairs are not link-digested, and `parent_action_event_id` is never populated (r1 MED-13). M3 (gap register) |

**Lineage rule (r1 MAJ-1 — replaces r1's contradictory wording):** a
missing or unpopulated `model` on **any** authorship predicate in a
composition yields lineage relation **UNKNOWN**, and UNKNOWN **fails**
a distinctness requirement exactly as SAME does (G-3; the three-state
`LineageRelation` landed in regista #25). There is no
"judged only across populated fields" carve-out — that carve-out *is*
the WI-239 fail-open, restated.

**Does not claim:** independence or correctness — and pre-M3 it cannot
even claim identity beyond self-declaration; see §4.

### 3.4 `observation/v1` — who witnessed it, and what was missed

| field | type | grade (per leaf) | backing today → target |
|---|---|---|---|
| `observer` | `{name: "cairn", version}` | probed (target) | cairn never stamps its own version into events today (verified) — M3: add; an observation claim without the observer's version is unattributable to a code revision |
| `harness` | `{name, version, config_digest}` | probed **at session attestation only**; the per-event copy is an env pin (default `"unknown"`, `config_digest` None) graded `declared`; the probed digest covers the first `settings.json` found, not the merged effective config — recorded as `config_digest_basis` (r1 MED-10) | exists today with exactly these caveats |
| `hooks_captured[]` / `hooks_excluded[]` | strings | **declared** | an install-time constant plus a local manifest, present in no signed payload and not evidence of what fired (r1 MED-11). Codex's verbatim uncaptured-path naming is the honest-exclusion shape to generalize. Target: the session attestation carries the installed hook set, and gap detection (below) covers "installed but never fired" |
| `completeness` | `{degradation_log_digest, truncation_policy, gaps[]}` | digest measured; policy declared (it is configuration); gaps measured | degradation JSONL exists and survives session end (verified) — its digest belongs IN the predicate. Gap taxonomy exists verifier-side; note: `ContentCoverageGap` is structurally unreachable on the primary harness today (agent-provenance WI-044, filed from this review) |
| `content_encryption` | `on\|off\|external` | measured for `on` (verified stance); `off`/`external` are config read-throughs that cannot distinguish "operator chose off" from "asked for on, key unusable" — fold into WI-044 (r1 MED-16) | field name matches the existing payload key (r1 minor) |
| `session_ref` | evidence ref | measured | session attestation event |

**Does not claim:** that what was captured is all that happened — it
claims the *inverse*: here is precisely what was not captured
(excluded hooks, degradations, truncations, withheld content with
reasons; `content_encryption_error` already lands inside the signed
payload today — keep that). This is R-01 as a schema: an observation
names its own boundary. A `SilenceGap` (a session that never reached
the log) is by definition assertable only by a *different* observer —
the doctor's cross-check, not the session's own predicate.

### 3.5 `ordering/v1` — when it was committed, immutably since

| field | type | grade | backing today → target |
|---|---|---|---|
| `log` | `{origin, log_id}` | attested | M4: Tessera (O-2 decision); today's stand-ins (RFC 3161 batches, witness receipts, bespoke Merkle) retire at M4 and are NOT modeled here |
| `checkpoint` | `{tree_size, root_hash, signature}` | attested | Tessera checkpoint format, verified with the log's published key |
| `inclusion_proof` | proof | attested | standard tile/inclusion proof; verified offline per R-21 |
| `statement_digest` | digest | measured | digest of the DSSE envelope this receipt covers |
| `integrated_at` | time | attested | the log's time — the system's only above-`declared` timestamp |

**Does not claim:** anything about content semantics. It is the one
predicate produced by infrastructure rather than an actor — R-11's
split made structural.

---

## 4. Composition — how the gates read

**Binding rule (r1 MAJ-3).** A composition is never "predicates
sharing a subject." A valid composition additionally requires:

1. **Instance agreement**: every actor-produced predicate in the
   composition carries the same `session_id` and (once it exists)
   `workload_instance.instance_id` as the execution predicate it
   composes with; a predicate naming a different session cannot be
   grafted onto this composition.
2. **Freshness**: each predicate's ordering receipt has
   `integrated_at` within the authorization's validity window, and the
   authorship receipt postdates the authorization receipt. Replaying a
   genuine past authorship statement (identical templated verdict text,
   identical subject digest) fails rule 1 on session mismatch and
   fails rule 2 on receipt ordering.
3. **Lineage**: per §3.3 — UNKNOWN anywhere fails distinctness.

**A review verdict (G-2) is TWO compositions, not one (r2 R-1).** The
**authored-work composition** (the work under review: its authorship,
execution, authorization predicates, internally bound by rules 1–3)
and the **review composition** (the verdict document: its authorship,
execution, authorization predicates, likewise internally bound). Each
is internally *same*-instance by rule 1; G-2's distinctness is
evaluated **across the two compositions**: the review's
`model.lineage` must be DISTINCT from the authored work's, and the
review's `workload_instance` must differ from the authored work's.
Both compositions must be present — absent or unpopulated
authored-work predicates yield UNKNOWN, which fails (§3.3, G-3). A
distinctness requirement evaluated inside a single composition is
vacuous by construction and is not G-2.

**Freshness rules are inert until M4 (r2 R-2), stated once:** every
freshness and expiry rule in this document is evaluated against
`integrated_at`, and `integrated_at` exists only when the ordering
predicate does (M4). Until then, rule 2 and §3.1's delegation-window
check are specified but non-executable; no pre-M4 consumer may claim
to have enforced them.

**What G-2 proves before and after M3 (r1 MAJ-2), stated plainly:**
pre-M3, `model.lineage` is a permanent self-declaration and
`instance_id` is self-minted, so a G-2 composition is a **composition
of declarations** — internally consistent, honestly graded, and
forgeable by a single actor willing to declare falsely. It becomes
independence *evidence* only when `credential_binding` is
broker-attested (M3) and the instance identity is bound to that
credential; the per-leaf grading rule (§1) makes this legible —
pre-M3 the composition's effective grade is `declared`, and no
consumer may present it as more (R-01). This is why R-10/M3 precedes
the corpus reset, and why the gap register orders R-10 first.

**A captured session (G-1)** is: one `observation` + one `execution` +
one `authorization` predicate over the session transcript subject,
plus `authorship` per assistant artifact, plus `ordering` receipts,
under the same binding rule.

---

## 5. The WI-241 decision — key-registry scoping

**Defect recap:** the ed25519 events in `agent_provenance` (16,275 and
growing as of 2026-08-03 — the archive scope must be pinned to a
snapshot sequence range, r1 minor) verify only against a key
registered in the `agent_notes` schema; bundles ship the wrong
registry. `agent_provenance.principal_keys` holds exactly one key —
the wrong one. The migration that created per-project registries
anticipated this: "A shared-catalog option can be added later if
principals span projects (Plan 026 §3)." They do — every real
principal on this estate spans projects. This decision therefore
**explicitly reverses regista Plan 026's per-project scoping** (r1
MED-22), with `public.projects` (migration 037) as the working
precedent for an estate-level table and its documented isolation
trade-off.

**Trust root, corrected (r1 MAJ-4).** The registry is **not** the
trust root — WI-209 exists precisely because it cannot be: the
registry lives in the same store as the events, so a malicious
operator can rewrite events, re-sign, and re-register keys under
victims' principal IDs. The root is the **anchored enrollment
timeline** (WI-209's `principal_enrolled` events, externally
anchored), with bundle-carried keys display-only per **agent-provenance
WI-043** (not regista WI-043 — r1 corrected a mis-citation). WI-209 is
**open**, not settled: this plan adopts its direction and makes it an
M3 dependency, it does not cite it as done. Empirical state, verified
during review: **zero `principal_enrolled` events exist in any
schema**, the signing key was provisioned with no chain event, and
`principal_keys` has no enrollment-event column — so nothing today can
reference an enrollment event, and the interim below is designed
accordingly.

**Decision (target, lands with M3):** principal keys are
**estate-scoped, not project-scoped**. One key registry, owned by C2,
keyed by the WI-055 canonical principal; projects reference it; the
anchored enrollment timeline (WI-209, implemented at M3) is its trust
root. Rotation/revocation stay per-key with validity windows,
unchanged.

**Interim (M1 archive, before M3), rebuilt after r1 MAJ-5:** the
frozen archive ships a **signed cross-registry key manifest** whose
entries carry what verification actually needs and what actually
exists:
`(key_id, principal, scheme, public_key_bytes, fingerprint,
source_schema, registration_record, asserter)` — public key **bytes**,
because a fingerprint cannot verify a signature; and a
`registration_record` (the `principal_keys` row's `registered_by` /
`registered_at` / provisioning provenance), because no enrollment
event exists to reference. The manifest is an `attested` record naming
its human asserter, per the WI-055 migration rule: it is a human claim
about history, not a derivable fact, and it must never satisfy
signature *binding* — historical events keep binding to their exact
recorded identities.

**The manifest's own trust anchor lives outside the archive (r2
R-3).** An archive-resident manifest key would reproduce the WI-209
threat one level up: whoever can rewrite the archive re-signs the
manifest and swaps the key bytes, and a negative test catches only an
*inconsistent* forgery, not a consistent one. The asserter's key
fingerprint is therefore published/escrowed **out of band** (the
WI-060 escrow channel; WI-209's `--trusted-fingerprints` input is the
natural verification shape), and A-4 verifies the manifest signature
against that out-of-band pin, never against material the archive
itself supplies.

**Explicitly rejected:** re-registering the existing key into
`agent_provenance` retroactively (rewrites history's shape); shipping
foreign-schema keys in bundles silently (the current failure, made
policy); treating the store-resident registry as a trust root.

---

## 6. Gap register — what must land, where, when

Ordered; the first row is the precondition for every `attested` grade
in this document (r1 MED-17).

| gap | owner | milestone |
|---|---|---|
| **R-10 actor-boundary signing** ("the first correctness fix", Plan 023) | regista (C2) | M3, first |
| anchored enrollment timeline (WI-209) + estate-scoped key registry — **precondition: anchors deployed** (r2 R-4): the estate has ZERO anchors today (open WI-060 residual), and an unanchored enrollment timeline is operator-asserted, no stronger than the registry it replaces | regista (C2) + WI-060 anchors | M3 |
| `credential_binding` issuance + logging | acb | M3 |
| host + session-scoped `instance_id` (main loop) in capture | cairn | M3 |
| `model.{id,lineage,provider}` supplied per session | harness launch env → cairn | M3 |
| cairn self-version stamped into observation payloads | cairn | M3 |
| `UserPromptSubmit` wiring (input_digest backing) | cairn | M3 |
| tool-transcript rollup digest (begin/end link digests; populate `parent_action_event_id`) | cairn | M3 |
| signed delegation records (replace ambient env delegation) | regista + cairn | M3 |
| degradation-log digest inside session attestation | cairn | M3 |
| `identity_consistency` computed and surfaced (WI-055 refinement 1) | regista replay/verify + dossier | M3 |
| digest-prefix normalization (`tool_args_hash` bare hex) | cairn | M3 |
| one lineage-relation implementation for both gate paths (WI-248 + WI-250) | regista | M3 |
| content-coverage detection reachable on primary harness (WI-044) | cairn | M3 |
| cross-registry key manifest for the frozen archive (§5 interim) | agent-suite archive procedure (WI-241 execution) | M1, before re-export |
| Tessera deployment + ordering predicate emission | new (C2 client) | M4 |
| DSSE/in-toto envelope emission for all five types | regista (C2) | M4 |

**Sequencing notes (r1 MED-18, minor):** WI-242 is an M1 blocker per
Plan 023 §12 — "orthogonal" here means only that this document doesn't
change its scope. WI-249 (segment linkage) must land **before** any
segment sealing resumes: the archive currently verifies only because
zero sealed segments exist, and sealing is itself a WI-060 residual —
fix the linkage first or the archive breaks the moment custody
improves.

---

## 7. Acceptance

- **A-1.** Schema registry: the five predicate schemas land as JSON
  Schema files; evidence grades are carried as a custom annotation
  keyword (`x-evidence-grade`, one of the four §1 values, on every
  leaf); CI validates examples against schemas and rejects a leaf
  without a grade.
- **A-2** (rescoped, r1 MAJ-6). G-1 dry run over **four** predicate
  types: one real captured session yields authorization, execution,
  authorship, and observation statements, hand-assembled if necessary,
  verifying offline with the live service stopped. `ordering/v1` is
  explicitly deferred to M4 — no stand-in is modeled, and the dry run
  records its absence rather than simulating a receipt.
- **A-3** (rescoped, r2 R-2 — ordering deferred exactly as in A-2).
  G-2 dry run over the four pre-M4 predicate types: one real
  cross-lineage review composes per §4's two-composition framing
  (freshness legs recorded as deferred, not simulated); a deliberately
  same-lineage pair is rejected; **and an UNKNOWN-lineage pair is
  rejected** — the case that actually occurred in production.
- **A-4** (rebuilt, r1 MAJ-5). WI-241 interim manifest: for a pinned
  snapshot sequence range, the archive's ed25519 slice verifies
  offline using only archive contents — key bytes from the manifest,
  binding checked against recorded identities, manifest signature and
  asserter checked. Test includes a negative: a manifest entry with a
  wrong public key fails the slice.

---

## 8. Deliberately excluded

- Predicate fields for tracker workflow state (R-03, R-17).
- A universal "event" predicate (R-22 — the five facts stay separate).
- Bespoke envelope or proof formats (R-05, R-19).
- Retroactive predicate synthesis for the historical corpus: the
  archive keeps its own frozen verifier; predicates begin at M3/M4.
  History is not rewritten into the new vocabulary (WI-055 migration
  rule).
- Modeling today's transparency stand-ins (RFC 3161, witness
  receipts) in `ordering/v1` — they retire at M4 (Plan 023).
