# Key-operations runbook

The lifecycle policy for the suite's per-actor Ed25519 signing keys. This is
the **policy** document: it states cadence, SLAs, and controls concretely
enough to operate. The **mechanics** are implemented in regista (Plan 026:
enrollment, rotation, revocation, escrow); the **UX** is carried out in dossier
(Plan 015: the key-management interface an operator or human uses to enact
these steps). This runbook is the policy those two enact *by*.

See the [key-custody threat model](key-custody-threat-model.md) for the
security model these operations defend, and the [bootstrap contract](bootstrap-contract.md)
for where key provisioning sits in the install order (step 2).

---

## 1. Key inventory

| Key | What it signs | Where it lives | Who owns it |
|-----|--------------|----------------|-------------|
| **Per-principal (human)** | work-item mutations, reviews, acceptances | Secret backend at `principals/<principal_id>` | The human (via dossier); provisioned by the system admin |
| **Per-principal (agent)** | breadcrumb/memory writes, tool-call attestations | Secret backend at `principals/<principal_id>` | The agent's owning team; provisioned by the system admin |
| **System principal** | synthetic/migration events | Secret backend at `regista#signing_key` | The system admin |
| **Break-glass recovery** | emergency events when operational keys are unavailable | Offline, split custody (see §4) | Two escrow officers jointly |

## 2. Rotation cadence

| Key type | Recommended cadence | Rationale |
|----------|--------------------|----------|
| Human principal | Every 90 days, or per organizational policy | Limits the value of an extracted key (threat T2); aligns with typical enterprise PKI rotation |
| Agent principal | Every 90 days, or per organizational policy | Same rationale; agent keys are lower-privilege (threat T4) but should not be exempt |
| System principal | Every 90 days, or per organizational policy | Same rationale; the system principal signs migration events that must remain verifiable |
| Break-glass recovery | Annually, or after each use | Used rarely; rotation after use closes the window if the key was exposed during the emergency |

### Rotation procedure

Rotation is enacted via dossier's key-management UX (Plan 015) or the regista
CLI (Plan 026 WI-3.1). The mechanic is: enroll a new key for the principal,
set the old key's `valid_to` to the rotation timestamp, and leave both in the
registry so events signed by the old key *before* the window close remain
verifiable.

```bash
# Enroll a new key (regista Plan 026 WI-3.1):
regista provision-principal --principal-id <principal_id> --rotate

# The old key is windowed out (valid_to set); the new key is valid_from now.
# Both remain in the registry — verification reads valid_from/valid_to at
# verify time (threat T5 mitigation 1).
```

The old key should be deleted from the secret backend after the rotation
window closes (the key is windowed out in the registry regardless, but
removing it from the backend closes the fetch path). Confirm no events are
pending verification against the old key before deleting it.

### Rotation tracking

Track rotation dates in the operator's config management system (not in this
repo — no work-domain identifiers in committed files). The regista key registry
records `valid_from` / `valid_to` for every key; `regista principal list`
shows the current state.

## 3. Leaver process

**SLA:** Revoke the principal's signing key within **4 hours** of the
identity-source deprovision (e.g., the LDAP/Entra ID account is disabled).

**Who:** The system admin.

**How:**

1. Revoke the principal in regista (Plan 026 WI-3.1):

   ```bash
   regista principal revoke <principal_id>
   ```

   This sets the key's `valid_to` to the revocation timestamp. Events the key
   signed *before* revocation stay valid; events *after* are flagged by
   `regista verify` as `unregistered-signer` (see the
   [threat model](key-custody-threat-model.md) §T5).

2. Delete the principal's key from the secret backend to close the fetch path:

   ```bash
   # Vault:
   vault kv metadata delete secret/agent-suite/principals/<principal_id>
   # AKV:
   az keyvault secret delete --vault-name suite-secrets \
     --name principal-<principal_id>-key
   # Windows:
   cmdkey /delete:agent-suite/principals/<principal_id>/key
   ```

3. Confirm revocation:

   ```bash
   regista principal list    # the principal should show valid_to set
   ```

**Why 4 hours:** The window between identity-source deprovision and key
revocation is the period during which a departing principal's key could still
be fetched and used (if the identity source is down but the secret backend is
not). 4 hours is short enough to limit exposure and long enough to be
operationally realistic for a human-administered process. Tighten to
organizational policy if it requires faster.

**For agent principals:** An agent principal is revoked the same way. The
owning team is notified; the agent's harness wiring should be removed
(`agent-suite bootstrap --user <principal_id> --uninstall` or the component's
`install-harness --uninstall`).

## 4. Break-glass

Break-glass is the emergency path for when operational keys are unavailable
(key loss, backend outage, principal compromise requiring immediate
re-signing). It uses a **recovery key** held in split-custody escrow, distinct
from any single principal's operational key (see the
[threat model](key-custody-threat-model.md) §T2 mitigation 3).

### When permitted

Break-glass is permitted only when:

- A principal's signing key is lost or corrupted and the event must be signed
  before a new key can be provisioned through the normal rotation path.
- The secret backend is unreachable and a signed event cannot wait for
  backend recovery (e.g., a safety-critical work-item state transition).
- A principal is suspected compromised and events must be re-attested under a
  controlled key while the compromise is investigated.

Break-glass is **not** permitted as a convenience path, a substitute for
rotation, or a way to bypass per-actor attribution.

### Dual control (two-person rule)

Break-glass requires **two authorized officers** to enact:

1. Each officer retrieves one half of the split recovery key from their offline
   escrow location (see §5).
2. The halves are combined to reconstruct the full key.
3. The event is signed under the recovery principal's `actor_id`, with both
   officers' identities recorded in the event metadata.
4. The combined key is used and cleared; the halves return to escrow.

No single officer can enact break-glass alone. This is the control that makes
the recovery key's existence defensible — see the
[threat model](key-custody-threat-model.md) §T2 mitigation 3.

### Review of break-glass use

Every break-glass invocation is:

1. **Logged as an event** in the regista event log, attributed to the recovery
   principal, with both officers' identities in the metadata (regista Plan 026
   WI-3.3).
2. **Reviewed within 24 hours** by a third party (a security officer or the
   system admin's manager) who confirms the invocation was permitted under
   §4 (when permitted) and that the event signed was legitimate.
3. **Triggers a rotation of the recovery key** after each use (see §2 cadence:
   "rotation after use closes the window if the key was exposed during the
   emergency").

The review is the audit story: a break-glass invocation without a matching
review record within 24 hours is an alert condition.

## 5. Escrow / backup custody

The break-glass recovery key lives **offline, in split custody**:

- The full key is split into **two halves** (e.g., via Shamir's secret sharing
  or a simple XOR split — the split mechanism is a regista Plan 026 WI-3.3
  implementation detail).
- **Half A** is held by one escrow officer (e.g., the system admin).
- **Half B** is held by a second escrow officer (a different individual —
  e.g., a security officer or a senior operator).
- Each half is stored **offline** (printed, on a USB drive in a physical safe,
  or in a separate secret-backend instance not reachable from the suite
  network). Neither half alone can reconstruct the key.
- The holders' identities are recorded in the operator's config management
  system (not in this repo).

### Escrow rotation

- The recovery key is rotated annually, or after each break-glass use (see §2).
- On rotation, new halves are generated and distributed to the escrow
  officers; the old halves are destroyed.

### Escrow access audit

Access to the escrow locations (physical safe open, offline media read) should
be logged by whatever physical or procedural control governs them. This is
outside the suite's software audit path but is part of the break-glass review
(§4): the reviewer confirms the escrow was accessed under dual control.

## 6. Cross-references

| Topic | Where the mechanics live | Where the UX lives | Where the policy lives |
|-------|--------------------------|---------------------|------------------------|
| Enrollment | regista Plan 026 WI-3.3 | dossier Plan 015 | This doc §1 |
| Rotation | regista Plan 026 WI-3.1 | dossier Plan 015 | This doc §2 |
| Revocation (leaver) | regista Plan 026 WI-3.1 | dossier Plan 015 | This doc §3 |
| Break-glass | regista Plan 026 WI-3.3 | dossier Plan 015 | This doc §4 |
| Escrow | regista Plan 026 WI-3.3 | dossier Plan 015 | This doc §5 |
| Threat model | — | — | [key-custody-threat-model.md](key-custody-threat-model.md) |
| Install order | — | — | [bootstrap-contract.md](bootstrap-contract.md) §1 step 2 |
