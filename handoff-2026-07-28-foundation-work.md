# Handoff — foundation work toward a credible 1.0 (2026-07-28)

Paste this into a fresh session to continue. It is accurate as of the end of the
2026-07-28 session (model qwen3.8-max-preview). Read
`reflections/2026-07-28-qwen3-8-max-preview.md` for the subjective version.

## Where things stand (one paragraph)

Five units of work are **done, adversarially converged (2 rounds each, no
major-or-above), and committed locally** — but **not pushed** (pushing/publication
is owner-gated). The suite's credibility story (CL-002 per-principal Ed25519
attribution) is now `supported` with end-to-end proof; regista's Plan 031 durable
lifecycle is verified against Postgres; dossier has real two-person dual control
for key revocation on that lifecycle. The **single remaining critical-path blocker
is the client-side key-custody/signing helper** (regista Plan 031 §5) — without it,
enrollment/rotation/break-glass stay correctly fail-closed and full WI-1.4 + GJ-8
stay blocked. The owner chose that client signer as the next direction.

## Commits made this session (local only — do NOT push without the owner)

- **agent-suite** (was clean, now 2 commits ahead of origin/main):
  - `cc0fa3e` test(interop): per-principal Ed25519 end-to-end (CL-002 → supported)
  - `58bb0b3` docs: restore hraedon family-repo links (over-redaction fix)
- **regista** (now 4 ahead of origin/main; 3 were pre-existing):
  - `3c0e226` fix(principal-lifecycle): make durable lifecycle actually durable
- **dossier** (now 2 ahead of origin/main):
  - `65857cf` feat: GJ-5 activity golden journey + Foundation B durable revocation & dual control
  - `ccd75cc` chore: re-sync uv.lock

## ⚠️ The gotcha a fresh session will trip on (read first)

**dossier's venv has `regista` installed EDITABLE from `/projects/regista` source**
(done so dossier's lifecycle tests exercise the Foundation A rehydration fix).
Consequences:
- dossier's durable lifecycle tests PASS right now because they run against the
  local, committed-but-**unpublished** regista.
- A clean `uv sync` in dossier would pull `regista-hraedon >=0.5.3` from PyPI,
  which does **not** contain the Foundation A fix → dossier's durable tests would
  FAIL. Reconcile this (publish/lock regista, or deliberately pin the local path)
  before trusting dossier CI. See `/projects/dossier/uv.lock`,
  `/projects/dossier/pyproject.toml`.
- Postgres for tests: `regista-postgres-1` on localhost:5432 (Docker). The durable
  tests auto-skip if Postgres is unreachable.

## What to do next (owner chose: build the client signer)

**Next increment — Foundation B.2: client-side custody/signing helper, FILE-custody
mode first** (regista Plan 031 §5; read `regista/plans/031-...md` §3–§5 and
`dossier/plans/015-key-management-ux.md`). The flow the lifecycle demands:
1. Client generates an Ed25519 keypair, custodies the private key (file mode for
   dev; DPAPI/AKV later) — see existing `regista/_custody.py::store_private_key`
   and `regista/_secrets.py` (file/vault/azure/windows write paths already exist).
2. Client sends only the public key to dossier → `prepare_enrollment`/`prepare_rotation`.
3. `issue_possession_challenge(operation_id)` → client signs
   `challenge.signing_bytes()` → `submit_possession(operation_id, PossessionProof(...))`.
4. Dual-control approval (built: `approve_operation`, two-phase) → `commit`.
5. Effective-use: client signs a post-commit challenge → `EffectiveReceipt` →
   `record_effective_receipt` (without it the op is `committed_not_effective`).
Build the signer as a regista CLI/library client (Plan 031 §4: CLI + library call
the same core) that holds the private key in custody and never exposes it. Wire
dossier enrollment/rotation to initiate + approve, with the signer producing the
proofs. Then un-fail-close enroll/rotate for file custody. Adversarially review to
no majors (kimi/nemotron/glm/qwen; **reserve sol for final signoff only**).

**After that:** Foundation C (step-up infra, Plan 020 Phase 3 non-Entra — the
`approve_operation` seam has a `step_up_evidence` field with no producer); then
Vault qualification (CL-008 → supported); then sol signoff over all converged units.

## Blocked / deferred (do not attempt until the signer exists)

- Production enrollment/rotation, break-glass registration, effective-use proofs
  (all need the client signer).
- Full WI-1.4 and GJ-8 evidence disclosure (need signer + step-up).
- Entra/OIDC live qualification (Plan 020 Phase 1) needs a live Entra tenant.

## Known follow-ups (minors, non-blocking)

- dossier `_resolve_principal_kind` returns SERVICE for web-enrolled principals
  (legacy provision path has no lifecycle row) — audit-accuracy nuance.
- dossier `_handle_lifecycle_error` should be typed `NoReturn`.
- regista: cross-instance idempotent *prepare* raises spurious
  OPERATION_DIGEST_MISMATCH; `record_approval` lacks a FOR UPDATE re-check
  (duplicate-approval row under concurrent race; commit still protected).
- The dossier feature commit `65857cf` combines GJ-5 + Foundation B (app.py
  interleaved them) — atomic/green but two features in one commit.

## Working conventions (non-obvious, learned this session)

- **Adversarial review is the quality gate:** after each substantial tranche, run
  cross-lineage reviewers (kimi/nemotron/glm/qwen — NOT the implementer's lineage)
  until no major-or-above, then move on. It caught two CRITICALs this session that
  the implementer's own tests blessed (regista write-only persistence; dossier
  self-approval bypass). Trust it.
- **A probe `pass` is "implementation present," not "qualified."** Qualification =
  golden-journey proofs + claims ledger. Don't conflate them (the GJ-1–4 proof
  commands were vacuous — selected 0 tests — until this session fixed them).
- **Implemented-but-unexercised is the recurring risk** (regista lifecycle was fully
  built but `skipif(True)`). Never trust a green suite where the relevant tests skip.
- **Identifier gate:** canonical denylist `~/.config/agent-suite/forbidden-identifiers`
  holds work-domain tokens ONLY (never named in a tracked file — see
  `githooks/pre-commit`); `hraedon`/`hraedon.com`/`plm@hraedon.com`
  are the allowed published identity (the over-redaction of `hraedon` was a bug, now
  fixed). Run `scripts/check_committed_identifiers.py` before committing.
- **Don't push or flip public** — publication-review verdict is still REVOKED
  (2026-07-19 operating-history-export incident); the org-identity correction does
  not clear the repo.

## Verify current state quickly

```bash
cd /projects/agent-suite && uv run pytest tests/test_interop.py -q        # 4 pass
cd /projects/regista     && uv run pytest tests/test_principal_lifecycle_durable.py -q  # 31 pass (needs PG up)
cd /projects/dossier     && uv run pytest -q                              # 739 pass / 6 skip (needs PG up)
```
