---
model: qwen3.8-max-preview
datetime: 2026-07-28T23:30 UTC
project: agent-suite (+ regista, dossier)
---

# Session Reflection — 2026-07-28

**Work summary:** Drove the suite toward credible production deployment across five
adversarially-converged units: proved CL-002 per-principal Ed25519 attribution
end-to-end (experimental→supported) and CL-010→provisional; restored the
over-redacted `hraedon` repo links; closed the dossier GJ-5 activity golden
journey (and fixed the *vacuous* GJ-1–4 proof commands that selected 0 tests);
verified regista's Plan 031 durable lifecycle (found+fixed a CRITICAL
write-only-persistence bug); and wired dossier revocation to the lifecycle with
real two-person dual control (found+fixed a CRITICAL self-approval bypass).
Committed locally in 5 commits across 3 repos; nothing pushed.

---

## On the project

The suite's biggest asset is its honesty machinery, and this session was a stress
test of it. The claims ledger (with maturity levels), the probe-emitted feature
matrix, the release board as a machine-readable gate, and the cross-lineage
adversarial review process are not theater — they caught real things. The feature
probes told me the code *exists*; the adversarial rounds told me where it *lied
about itself*. Those are different signals and the project wisely keeps them
distinct (a probe `pass` is explicitly "implementation presence, not
qualification").

What still feels fragile is the boundary between "built" and "wired." Regista's
durable lifecycle was *fully implemented* — 1448 lines, clean dataclasses, the
whole state machine — and yet it had never been run against Postgres (the tests
were `skipif(True)`), and it had a write-only-persistence bug that broke the one
property ("durable") it was named for. Implemented-but-unexercised code is the
project's recurring risk pattern, and the defense is mechanical: never trust a
green suite where the relevant tests are skipped.

## On the work done

The adversarial process earned its keep twice, and both times the implementer's
*own tests blessed the bug*:

1. **Regista rehydration (Foundation A).** `_operation()` read only from the
   in-memory dict; the DB was write-only. prepare-on-A + commit-on-B (the exact
   shape dossier drives across HTTP requests) failed with OPERATION_NOT_FOUND.
   The 27 "durable" tests all used one instance, so they passed while the
   cross-instance contract was broken. I'm confident in the fix (digest
   reconstructed from persisted columns for exact `compare_digest` match;
   fail-closed enums; challenges deliberately left process-local) because the new
   cross-instance tests genuinely open a second `Regista` and assert
   frozen-dataclass equality.

2. **Dossier self-approval bypass (Foundation B).** `approve_operation` was the
   only place enforcing approver≠initiator, and `_revoke_principal_lifecycle`
   bypassed it *exactly when approver==initiator* — the one case that matters —
   while the route passed `approver=actor`. One admin could revoke any key alone.
   The fix (two-phase: prepare → a different admin approves+commits) is sound and
   `test_pg_revoke_self_approval_rejected_http` proves Alice/Alice→400. I'm
   confident in this one.

What I'd want a second pair of eyes on: the dossier commit is a *combined* GJ-5 +
Foundation B commit because `app.py` interleaves both and splitting by file would
have broken commit-integrity (the GJ-5 tests need the GJ-5 `app.py` hunks). It's
atomic and green, but it's two features in one commit — impure by the project's
own atomicity standard. Also, `dossier`'s venv has `regista` installed **editable
from /projects/regista source**, so dossier's lifecycle tests exercise the
locally-committed (unpublished) regista. A fresh `uv sync` in dossier would pull
`regista-hraedon` from PyPI, which does **not** yet contain the Foundation A
rehydration fix — dossier's durable tests would then fail. This is an environment
coupling that needs to be made explicit (publish regista, or pin dossier to the
local path deliberately) before dossier CI can be trusted.

## On what remains

**The single biggest blocker** for "credible production deployment" is the
**client-side key-custody/signing helper** (regista Plan 031 §5). The lifecycle
is custody-separated — the web process must never hold private keys — so
enrollment/rotation/break-glass need an out-of-process signer that generates the
keypair and signs the possession + effective-use challenges. It doesn't exist.
Until it does, those flows are correctly fail-closed and full WI-1.4 + GJ-8 stay
blocked. This is what everything is still "designing around." Sequence:

1. **Client signer, FILE-custody mode first** (dev/operator): generate Ed25519
   outside the web process, sign possession challenges, produce effective-use
   receipts; wire dossier enrollment/rotation to the lifecycle through it.
   Windows-DPAPI/AKV modes follow. (The user chose this as the next direction.)
2. **Foundation C — step-up infra** (Plan 020 Phase 3, non-Entra): auth_time
   tracking, protected-op registry, recent-auth check, digest-bound step-up.
   The `approve_operation` seam already has a `step_up_evidence` field with no
   producer; this completes the dual-control story.
3. **Vault qualification** (CL-008 provisional→supported): a CI-qualified
   end-to-end secret-resolution test. Independent, tractable.
4. **sol signoff** over the five converged units (deliberately deferred — sol is
   exacting and reserved for final review).

"Needed before this can ship" vs "nice to have": the client signer, step-up, and
a published/locked regista are *needed*; Vault qualification and the Profile C
preview work are *nice to have* for a Profile B pilot.

## Gaps to flag

- **Environment coupling (load-bearing, under-exercised):** dossier's lifecycle
  tests depend on the *local* regista (Foundation A rehydration fix), which is
  committed but **not published**. `uv.lock` still requires `regista-hraedon
  >=0.5.3` from PyPI. A clean dossier checkout/CI would install the old regista
  and the durable tests would fail. Reconcile before trusting dossier CI
  (`/projects/dossier/uv.lock`, `/projects/dossier/pyproject.toml`).
- **principal_kind audit accuracy:** `_resolve_principal_kind` (dossier
  `gateway.py:714`) uses `lifecycle.describe`, which falls back to
  `PrincipalKind.SERVICE` when no `lifecycle_operations` row exists. Web-enrolled
  principals use the legacy `provision_principal` path (no lifecycle row), so
  their revocation events record `SERVICE` regardless of real kind. Audit-accuracy
  nuance, not a bypass; resolves when enrollment migrates to the lifecycle.
- **Pre-existing Foundation A minors (regista):** cross-instance idempotent
  *prepare* raises a spurious `OPERATION_DIGEST_MISMATCH` (prepare-by-key doesn't
  rehydrate); `record_approval` lacks a `FOR UPDATE` re-check (duplicate-approval
  row under a concurrent multi-instance race — commit itself is still protected).
  Both pre-existing, both minor.
- **`_handle_lifecycle_error` (dossier `app.py`) should be typed `NoReturn`** —
  it always raises; current `-> None` can trip mypy possibly-unbound downstream.
- **`describe()` returns DRAFT for an active-key-with-no-history principal**
  (regista `principal_lifecycle.py`) — edge case, reconcile flags it.
- **regista is ahead 4 of origin; dossier/agent-suite have unpushed commits.**
  Nothing was pushed (owner-gated). The publication-review verdict is still
  REVOKED (2026-07-19 operating-history incident) — do not treat the org-identity
  correction as clearing the repo for publication.
- **Profile C (acb, wake) untouched this session** — explicitly preview; not on
  the Profile B critical path.
