# Holistic suite review — 2026-07-10

**Reviewer:** GPT-5.6 Sol  
**Scope:** agent-suite and its six constituents: regista, dossier,
agent-notes, agent-provenance, agent-capability-broker, and agent-wake.  
**Review posture:** architecture, correctness, operational cohesion, trust
claims, deployment evidence, and readiness for Codex onboarding.

## Executive assessment

The suite has a strong architecture and a credible product boundary. It is not
an accidental collection of utilities anymore: the store, human face, agent
face, provenance recorder, capability broker, signaling layer, and thin
orchestrator have distinct responsibilities and increasingly consistent
contracts. The event-sourced core, per-principal signing, replay, explicit
degradation, dry-run/idempotent installers, and cross-component health model
are unusually thoughtful foundations.

The suite is nevertheless **not ready for a high-assurance deployment claim**.
The limiting factor is not missing breadth. It is that several verification
and anchoring paths currently claim more than they prove, while deployment
documentation and configuration changes have crossed the suite's own safety
boundaries. These are repairable defects, not architectural collapse. The
right next move is a short correctness-and-claims closure, followed by the
planned Codex integration—not another expansion wave.

**Overall rating:** promising, coherent engineering system; suitable for
continued dogfood and controlled development; not yet suitable as evidence for
an external audit or regulated production assurance statement.

## Blocking findings

### F-1 — External anchoring does not commit to event content

**Severity:** Critical  
**Repository:** regista  
**State reviewed:** uncommitted Plan 019 implementation

The anchor batch selects `event_id` and `global_seq`, then computes its Merkle
root from event UUIDs. A payload, signature, actor field, or event-chain value
can be rewritten while preserving event UUIDs, leaving the external root
unchanged. This does not support the specification's stronger claim that
anchored events cannot be modified post-hoc without external detection.

**Required correction:** anchor a content-committing value. The simplest
candidate is the verified global chain head at the target sequence, bound to
the project, sequence, envelope version, and hash algorithm. Alternatively,
Merkleize canonical full-event digests. Verification must recompute from live
events through the target sequence before accepting the external receipt.

**Acceptance evidence:** mutate every security-relevant event field in negative
tests and prove bundle/receipt verification fails.

### F-2 — The live provenance proof can pass against unrelated events

**Severity:** Critical  
**Repository:** agent-provenance  
**State reviewed:** uncommitted Plan 009 proof

The proof records a store-wide event count, launches a harness session, then
selects the most recent session attestation and recent tool-end events matching
the harness version. It does not bind those queries to the session it launched
or require their sequence numbers to be after the baseline. Concurrent or
older activity can therefore satisfy the proof.

Its chain check counts rows with a null predecessor; it does not recompute any
event or global-chain hash. A chain containing non-null but forged hashes is
reported intact.

**Required correction:** give the proof a unique correlation marker and capture
the launched session ID; query only that session and sequence window. Invoke
the canonical replay/verification implementation rather than approximating
chain verification in SQL.

**Acceptance evidence:** concurrent decoy session, stale matching events,
mutated hash, missing event, wrong digest, and unavailable-store negative cases
must each fail for the intended named reason.

### F-3 — Anchor receipt concurrency and retry state are unsafe

**Severity:** High  
**Repository:** regista  
**State reviewed:** uncommitted Plan 019 implementation

The receipt insert catches a uniqueness violation and then queries using the
same PostgreSQL transaction. The transaction is already aborted, so the
idempotency path fails under the race it is meant to handle. In addition, only
confirmed receipts advance the batch cursor. Pending submissions select the
same events again, while the provider/root uniqueness constraint prevents a
new receipt. Failed receipts also occupy that uniqueness key without a defined
retry transition.

**Required correction:** serialize batch selection with an advisory/row lock or
use `INSERT ... ON CONFLICT` with a deterministic readback. Define a receipt
state machine and cursor rule for pending, committed, confirmed, failed, and
retryable submissions.

### F-4 — Deployment evidence contains environment identifiers

**Severity:** High  
**Repository:** agent-suite  
**State reviewed:** committed deployment documentation

The committed deployment record retains a machine name, private network
addresses, principal names, and key-ID prefixes. This conflicts directly with
the repository rule that committed files contain placeholders only. The
identifier-scrub commit did not close the issue.

**Required correction:** replace the record with a sanitized evidence template
or a scrubbed report. Keep real deployment evidence in an access-controlled
operator system, not the public/source tree. Run the identifier gate with an
active local denylist before accepting the correction.

### F-5 — agent-notes DSN fallback can select the wrong database

**Severity:** High  
**Repository:** agent-notes  
**State reviewed:** committed deployment fix

The native agent-notes DSN resolver now falls back to the suite's regista DSN.
The deployment model explicitly uses separate regista and agent-notes
databases. A missing `AGENT_NOTES_DSN` can therefore become a connection to the
wrong database instead of an actionable configuration failure.

**Required correction:** keep native `AGENT_NOTES_DSN` and regista
`REGISTA_DSN` semantically distinct. If single-database deployment is desired,
make it an explicit, validated mode rather than a fallback. Add a negative test
where only `REGISTA_DSN` is set.

### F-6 — Suite doctor treats incomplete health JSON as healthy

**Severity:** High  
**Repository:** agent-suite  
**State reviewed:** committed doctor compatibility change

When a component omits top-level `ok`, the umbrella infers health by searching
its `checks` list for explicit failures. An empty object, missing checks, an
unknown check schema, or unrecognized status vocabulary therefore becomes
healthy. This violates the suite's fail-honest health rule.

**Required correction:** require the contract's top-level boolean for conforming
components. If a temporary compatibility path remains, accept only a
recognized, non-empty check schema and treat unknown/missing shape as failed or
unsupported—not OK. Regista and ACB now emit the common shape, so the legacy
exception should be removable.

## Secondary observations

### Harness-version parsing is not robust

The provenance installer takes the first whitespace-delimited token from
`<harness> --version`. At least one observed harness format yields a product
name rather than a version. Use per-harness parsers with fixtures and preserve
the complete raw version string separately if it is useful evidence.

### Live-proof scripts should use production abstractions

Direct SQL in proof scripts has already diverged from the verifier's real
semantics and interpolates schema names manually. Proofs should call public or
auditor-facing verification APIs wherever possible. If SQL is unavoidable,
use psycopg identifiers and validate project selection.

### Active identifier gates matter

Several repository hooks reported that their identifier gate was inactive
because no denylist was configured. The gate architecture exists, but an
inactive gate cannot support a publication or deployment claim. CI should have
a useful generic rule set, while operator environments add private denylist
terms without committing them.

### Test completion needs one source of truth

Focused suite and provenance tests were green, but agent-notes' focused test run
stalled after 64 passing tests and required interruption. The suite has made
good progress on CI, yet local proof still depends on knowing which tests need
external services and which should terminate deterministically. Mark and bound
integration tests so a green run is legible.

## Holistic evaluation by quality

### Architecture — strong

The ownership model is the suite's greatest strength:

- regista owns durable truth, signing, replay, and generic entity/event
  semantics;
- dossier and agent-notes are separate human and agent faces over shared truth;
- cairn owns harness provenance rather than embedding interception in every
  component;
- acb brokers capabilities without becoming a secret store;
- wake owns signaling without becoming an orchestrator;
- agent-suite remains a thin composition and operations layer.

These boundaries are coherent and should be defended. In particular, no
Codex-specific logic belongs in regista or dossier unless a genuinely generic
contract gap is found.

### Trust model — strong intent, incomplete proof

The system understands the right threats: operator forgery, signer binding,
key custody, degraded capture, missing events, replay, cross-lineage review,
and external anchoring. The current weakness is claim discipline at the last
metre. A non-null predecessor is not chain verification; a Merkle root of UUIDs
is not an event-content commitment; a recent event is not necessarily evidence
from the session under test.

The suite should adopt a simple rule: **every assurance sentence must point to
one executable positive proof and one tamper/failure proof.** If either does
not exist, phrase the capability as provisional.

### Operational cohesion — good and improving

Bootstrap, doctor, lock, upgrade, scheduling, restore verification, per-user
configuration, and component installers form a credible operator surface. The
recent real deployment was valuable because it exposed packaging, command
contract, configuration, and health-shape drift quickly.

The next maturity step is to turn that learning into hermetic convergence
tests: isolated HOME/config roots, synthetic secrets, exact install/reinstall/
uninstall checks, and no dependency on ambient harness state.

### Security and secret handling — good design, uneven documentation

Secret references, backend resolution, create-only behavior, backup-first
mutation, and no-clobber policies are sound. Some newer deployment prose falls
back to plaintext DSN examples and copying sensitive shared key material. The
operator docs should consistently lead with secret references and distinguish
verification material from signing authority.

### Code quality and testing — generally strong

The projects use strict typing, closed dispatch, focused dataclasses, fixture
tests, negative cases, and substantial CI. The main risk is not a lack of tests
but tests that encode an approximation of the claim. Verification code deserves
adversarial review above normal feature tests.

### Documentation and planning — unusually strong, needs consolidation

Plans, reflections, runbooks, contracts, and explicit non-goals make the suite
legible. The cost is document drift and duplicated plan numbers when work lands
in parallel. A small plan index per repository with number, status, owner,
supersedes, and implementation commit would reduce ambiguity without losing
the useful narrative history.

### Codex readiness — plan-ready, implementation pending

The Codex support plans are now merged:

- agent-suite Plan 007;
- agent-notes Plan 019;
- agent-provenance Plan 011;
- agent-capability-broker Plan 007;
- agent-wake Plan 006.

Most implementation is straightforward. The areas requiring focused ownership
are hook concurrency/correlation, safe TOML mutation, shared-hook coexistence,
and the distinction between next-session delivery and true external wake.
Codex support should begin after F-1 through F-6 have owners and the critical
proof defects are either fixed or explicitly fenced from assurance claims.

## Recommended execution order

### Gate 1 — Correct claims and prevent unsafe merge

1. Rework regista anchoring around a content-committing root and transactional
   state machine.
2. Rebuild the provenance live proof around captured session identity and the
   canonical verifier.
3. Scrub deployment evidence and activate identifier checks.
4. Remove the cross-database DSN fallback.
5. Make doctor fail honest on unknown health shapes.

### Gate 2 — Re-run adversarial convergence

1. Unit, strict typing, lint, and deterministic integration tests green in each
   changed repository.
2. Suite install → reinstall/no-op → doctor → uninstall in an isolated profile.
3. Tamper cases for event content, chain links, receipt bytes, session
   correlation, and missing hooks.
4. Record only sanitized, reproducible evidence.

### Gate 3 — Implement Codex support

1. Land contract/installer/skill and read-only adapter work in parallel.
2. Have Codex own or closely review provenance hooks, TOML mutation, and wake
   feasibility.
3. Finish with the suite-level local Codex interop proof and an honest coverage
   matrix.

## Validation performed during this review

- agent-suite: 232 tests passed, 2 skipped; Ruff and mypy passed.
- agent-provenance focused tests: 94 passed; Ruff passed.
- agent-notes focused run: 64 tests passed before the run stalled and was
  interrupted after approximately 100 seconds.
- Plan-only Codex merge commits were reviewed with `git diff --check` and merged
  without altering the existing regista or provenance work in progress.

## Bottom line

The suite is worth continuing. Its core decomposition and security instincts
are better than its current readiness level might suggest. The present gap is
between *having the right mechanisms* and *proving exactly what those mechanisms
guarantee*. Close that gap, keep claims narrower than evidence, and the suite
will be in a strong position for both Codex onboarding and a serious pilot.
