# Chain-preserving redaction and erasure

**Status:** Design ratified by the owner 2026-07-19 (this document is the
worked design; implementation lands as a regista plan). Companion to
`key-custody-threat-model.md` and regista Plan 028 (retention/archival).

## 1. The problem

The suite's value rests on an append-only, hash-chained, signed event log.
Records-management law rests on the ability to destroy content: erasure
requests, retention schedules, legal disposition. A regulated deployment
will be asked how both can be true at once, and "we can't delete anything"
is a disqualifying answer. This document specifies how content is
destroyed without destroying verifiability — and states precisely what is
lost when it happens.

## 2. What the chain actually commits to (ground truth, 2026-07-19)

From `regista/_signing.py` and `regista/_events.py`:

- The signed scope (envelopes v1–v5) embeds the **raw payload dict**
  inline: `canonical_envelope = JCS({..., "payload": payload, ...})`.
- The per-event chain link is `H(canonical_envelope ‖ signature)`
  (sha-256), stored nowhere on the event's own row; it is recomputed by
  verifiers.
- From v3 onward, each successor's **signed** envelope embeds
  `prev_event_hash` (and `prev_global_event_hash` for the global chain).
  This is the load-bearing fact for redaction: the hash of event *E* is
  committed inside the signature of event *E+1*. An operator cannot
  substitute a different history for a removed event without breaking a
  signature they may not control.
- External anchor receipts (`_anchoring.py`) and sealed archive segments
  commit to these hashes again, outside the database.
- Field-level payload encryption already exists (`_encryption.py`):
  AES-256-GCM per field, `key_id` per blob, keys resolved through the
  secret backend, and a verifier vocabulary (`not_decrypted`,
  `digest_mismatch`) for fields that cannot be opened. For an encrypted
  field, the signed scope commits to the **ciphertext structure**, not
  the plaintext.

Consequence: payload content currently lives in at least
`events.payload`, `events.canonical_envelope`, archive segments,
exported bundles, projections (`work_items` columns), the agent-notes
native mirror and its pgvector embeddings, and any dossier caches.
Redaction is a *sweep*, not a column update.

## 3. The design: two mechanisms, one policy

There is a clear best answer, and it is not a single mechanism. Content
written **from now on** should be erasable by key destruction; content
**already written** in plaintext needs a tombstone protocol. Both
produce the same verifier-visible outcome: a chain that still verifies
end-to-end, with an explicit, signed, attributable record of what was
removed, by whom, and on what basis.

### 3.1 Forward path — classify at write, erase by key destruction

Sensitive fields are declared per workflow (a policy-pack concern) and
encrypted at write with `encrypt_fields()`, keyed by an **erasure
scope** — a named key covering the unit that would plausibly be erased
together (a data subject, a project-period, an incident). Erasure is
then:

1. a signed `erasure` event recording scope, legal basis, actor, and
   the affected key_id;
2. destruction of that key in the secret backend.

The chain is untouched — every envelope still verifies byte-for-byte,
because the signatures always committed to ciphertext. Bulk erasure
("everything about subject S") is one key destruction, not per-event
surgery.

**Required fix before this is erasure-grade:** `_compute_digest()` is
unsalted `sha256(plaintext)` and rides inside the signed envelope. After
key destruction, low-entropy values (names, emails, dates) remain
recoverable by guessing against the digest. The digest must be blinded —
compute it over `nonce ‖ plaintext` (the random per-blob nonce already
exists and is stored alongside). This changes only future writes; the
digest is self-describing via its `alg` prefix, so verifiers support
both forms.

**Required additions:** an erasure-scope registry (scope → key_id →
custody location, so provision/rotation/destruction are operable); a
workflow-level declaration of which payload fields are sensitive (so
classification is policy, not author diligence); and dossier/agent-notes
UX for encrypted fields they cannot open (render the field's verification
status, never crash on ciphertext).

### 3.2 Backward path — hash-retained tombstones for plaintext history

For an event *E* whose plaintext must be destroyed:

1. Append a signed `redaction` event *R* carrying: `event_id(E)`,
   `H(canonical_envelope(E) ‖ signature(E))` (the chain-link hash),
   `payload_canonical_hash(E)`, the redaction basis, and the approving
   actors.
2. Replace `events.payload` and `events.canonical_envelope` for *E* with
   a tombstone: `{redacted: true, redaction_event: id(R), envelope_hash:
   <retained link hash>}`. The signature row is retained.
3. Sweep the derived copies (§2 list) for *E*'s content.

**Verifier rule for tombstoned events:** the chain link for *E* is taken
from the retained `envelope_hash` instead of being recomputed, and is
cross-checked against the successor's signed `prev_event_hash`
commitment (and against anchor receipts where present). Content
verification for *E* reports `redacted (authorized by R)` — a designed
output, like the small-n statements elsewhere in the family, not a
failure state. A tombstone whose retained hash does not match the
successor's commitment **fails verification**: tombstoning cannot be
used to rewrite history, only to remove content from a position the
surrounding signatures still pin.

Chain-tail edge: if *E* is the newest event, no successor commits to its
hash yet — but *R* is appended after *E* and *R*'s signed payload
carries the retained hash, so the commitment always exists before
content is destroyed. Ordering is therefore mandatory: **R commits, then
the tombstone lands** (one transaction).

### 3.3 What is honestly lost, and stated

- For a tombstoned event, verifiers can no longer recompute integrity
  from content; they verify position and commitment. The claims ledger
  must carry this as a distinct assurance level.
- Retained hashes of plaintext-era content are unsalted commitments:
  a party who already holds a candidate plaintext can prove it matched,
  and low-entropy content is in principle guessable. This is the
  industry-standard residual (stated, not hidden); the forward path's
  blinded digests eliminate it for new content.
- Bundles exported before a redaction are outside the store's control.
  The redaction event gives any bundle-holder notice of what was
  redacted and when; policy (not cryptography) governs their disposal.
  This is the same residual class as any backup.

### 3.4 The rejected alternative, for the record

A v6 envelope committing to `H(payload)` instead of the payload (payload
held out-of-envelope) was considered and **rejected**: it weakens every
future event's content verification to solve a problem field encryption
already solves for exactly the fields that need it, and it doubles the
storage/verification model for no additional erasure power. Existing
envelope versions v1–v5 remain the only formats; redaction semantics are
a verifier-side protocol plus one new event kind, not an envelope break.

## 4. Policy layer (suite-level)

- **Authorization:** redaction and key destruction are dual-control
  (owner + one other principal once multi-principal lands; owner +
  recorded rationale until then). The `redaction`/`erasure` events are
  ordinary signed events — the audit trail of removal is itself
  tamper-evident.
- **Disposition:** retention schedules (regista Plan 028) *drive* the
  forward path: a schedule maps record classes to erasure scopes, so
  scheduled disposition is key rotation-to-destruction, not row surgery.
- **Legal hold:** a hold marks scopes/events as non-erasable; the
  erasure verbs refuse while a hold references them.

## 5. Architectural change inventory

regista (owner of all mechanics; one new plan):

1. Blind the encrypted-field digest (`_encryption.py`) — small, do first.
2. `redaction`/`erasure`/`legal_hold` event kinds + API verbs with the
   transactional commit-then-tombstone ordering (`_events.py`).
3. Verifier updates for the tombstone rule: replay/integrity
   (`_integrity.py`, `_replay.py`), bundle export+offline verify
   (`_bundle.py` — bundle format gains a tombstone representation),
   anchoring re-verification (`_anchoring.py` BLOCKING-2 recomputation
   must special-case tombstones), archive segments.
4. Erasure-scope key registry + custody through the existing secret
   backend indirection (`_secrets.py`, provision).
5. Derived-copy sweep hooks: projection scrub + a documented checklist
   for out-of-store copies (agent-notes mirror + embeddings, dossier
   caches, exported bundles).

Faces (adopt, don't invent): dossier renders encrypted/tombstoned fields
by verification status; agent-notes CLI ditto; both surface the
redaction event in the item's history view.

Suite level: this document; a claims-ledger entry distinguishing
"content-verified" from "position-verified (redacted)"; an operator
runbook for erasure-request intake → scope resolution → dual-control →
sweep → verify.

## 6. Sequencing note

The tombstone protocol should exist (at least verifier-side) **before**
the store accumulates significant business content at work, and the
digest blinding should land **before** field encryption sees real
sensitive data — both are far cheaper as contracts than as retrofits.
Neither blocks the current Gate 0→1 path; the natural home is a regista
plan scheduled with Plan 028's retention work, with the digest fix
cherry-picked early.
