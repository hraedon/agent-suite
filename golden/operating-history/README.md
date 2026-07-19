# Operating-history artifact — the suite's own audit trail

**Exported:** 2026-07-19 from the production converged store
(mvmpostgres01, database `regista`, schema `regista`).
**Contents:** all 1,508 signed events of the regista project — the
work-item history of the spine being built, held in the store it built.
**Bundle hash:** `sha256:6e98a772e640c275b62421b52416088f9adb6488a9499ded3867f9821d318718`

## Verify it yourself (no database, no trust in the operator)

```bash
pip install regista
regista bundle verify golden/operating-history/regista-history-bundle-20260719.json
```

Expected: bundle hash, global chain, and per-work-item chains all
verify; 1,508 signatures report `unverifiable (symmetric scheme)`.

## What this proves, and what it doesn't (claims honesty)

- **Proves:** the exported history is internally consistent and
  tamper-evident — every event is hash-chained, and no event can be
  altered, inserted, or removed without breaking a chain the verifier
  recomputes from content. The bundle is self-contained: verification
  needs no access to the store or to hraedon infrastructure.
- **Does not prove (yet):** third-party signature authenticity. The
  store's HMAC-era signatures are symmetric — verifying them requires
  the signing key, which an external auditor rightly does not get. The
  verifier says so explicitly rather than overclaiming
  (`signature_check=enforced`, signatures reported unverifiable).
  Per-principal Ed25519 (regista Plan 026) upgrades this artifact class
  to third-party-verifiable signatures via bundled public keys.
- **Also absent:** external anchor receipts (0 in this export — the
  regista project's events predate anchoring adoption in dogfood).
  Once anchoring is routine, bundles carry receipts an auditor can
  check against the external witness.

Sanitization: contents scanned against the canonical identifier
denylist before commit (0 hits; lab identifiers are permitted per the
publication policy).

The narrative writeup of this artifact is deferred to the 1.0 release
story; this directory holds the evidence, dated and hash-pinned.
