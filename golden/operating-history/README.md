# Operating-history artifact — metadata manifest

This directory records the existence and integrity of the suite's operating-
history evidence without committing the production export itself. The full
bundle contains real operational events and identifiers from the production
store; per AGENTS.md's committed-identifier rule and Sol round-3 finding #3,
it must not be tracked in the public tree. It belongs in access-controlled
release evidence.

## Artifact record

| Field | Value |
|-------|-------|
| **Bundle file** | `regista-history-bundle-20260719.json` |
| **Exported** | 2026-07-19 |
| **Source** | Production converged store (access-controlled; hostname not committed) |
| **Event count** | 1,508 signed operational events |
| **Bundle hash** | `sha256:6e98a772e640c275b62421b52416088f9adb6488a9499ded3867f9821d318718` |
| **Chain verification** | Global chain and per-work-item chains verify; 1,508 signatures report `unverifiable (symmetric scheme)` |
| **External anchor receipts** | 0 (events predate anchoring adoption) |
| **Controlled location** | Operator's access-controlled release-evidence store; not in the public repository |

## What this proves, and what it doesn't (claims honesty)

- **Proves:** the exported history is internally consistent and tamper-evident
  — every event is hash-chained, and no event can be altered, inserted, or
  removed without breaking a chain the verifier recomputes from content.
- **Does not prove (yet):** third-party signature authenticity. The store's
  HMAC-era signatures are symmetric — verifying them requires the signing key,
  which an external auditor rightly does not get. Per-principal Ed25519
  (regista Plan 026) upgrades this artifact class to third-party-verifiable
  signatures via bundled public keys.
- **Also absent:** external anchor receipts (0 in this export). Once anchoring
  is routine, bundles carry receipts an auditor can check against the external
  witness.

## Why the full export is not committed

A denylist returning zero hits is not equivalent to privacy review. The bundle
contains 1,508 complete operational events with real content and identifiers.
The committed-identifier rule (AGENTS.md) and the publication-clearance
process require that production data not enter the public tree, regardless of
denylist scan results. The metadata above is sufficient for audit reference;
the full export is available in the operator's access-controlled evidence store.

## Synthetic fixture (to be created)

A synthetic chain-valid fixture will be added to this directory to exercise
the bundle-verification path without production data. Until then, operators
verify against the controlled export using:

```bash
pip install regista
regista bundle verify <path-to-controlled-export>.json
```
