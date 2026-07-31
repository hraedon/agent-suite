# Secrets instantiation strategy — from root-token stopgap to team deployment

**Status: PROPOSED** (2026-07-30). This is the concrete plan for how secret
material is created, scoped, delivered, rotated, and revoked across a
multi-host, multi-principal deployment of the suite. It complements the
existing runbooks — [secrets-vault.md](secrets-vault.md) (mechanics of the
`vault:` ref), [key-custody-threat-model.md](key-custody-threat-model.md)
(why), and [key-operations.md](key-operations.md) (day-2 key ops) — by
answering the question those deliberately leave open: *who gets which
credential, from where, and what happens when it must die.*

## 1. Where we are (honest baseline)

- One Vault whose **only** KV mount is `kv/` (KV-v2); `approle/` and
  `kubernetes/` auth are enabled. There is no `secret/` mount: that is
  Vault's *dev-mode* default, which an earlier revision of
  [secrets-vault.md](secrets-vault.md) was written against — those
  `vault:secret/...` refs never matched the production server. The runbook
  and `suite.env.example` are reconciled to `vault:kv/...` alongside this
  document, and the runbook's earlier flat `agent-suite/...` layout is
  superseded by the per-deployment layout in §3.
  Operated today with a **root token held by the owner** — acceptable for a
  one-operator lab, disqualifying for a team.
- regista signing keys are **file-backed** on each dev host
  (`~/.config/regista/keys.json`); regista logs `keys.plaintext_at_rest` on
  every load. The same key file is present on multiple hosts — key
  compromise on one host is compromise of the estate's attribution story.
- At least one production `vault:` ref is **configured but unverified**:
  `suite.env` carries `vault:homelab/cairn/content-key#key`, while the
  secret lives at `kv/homelab/cairn/content-key` and regista's resolver
  reads the first ref segment as the *mount*. Component doctors check that
  a ref is set, not that it resolves. (Qualification gains a check for
  this — §6.)

## 2. Principles (the contract this strategy must satisfy)

1. **No root token in operation.** The root token exists sealed in
   break-glass custody; every routine operation runs under a scoped,
   expiring credential.
2. **One principal, one credential, one policy.** Every host *service* and
   every *actor* (human or agent) authenticates as itself. Nothing is
   shared, so anything can be revoked without collateral damage.
3. **Delivery is bootstrapped, not copied.** Secret material reaches a new
   host via single-use, response-wrapped delivery — never `scp`, never a
   committed file, never a chat message.
4. **Revocation is one command and it works.** Every credential maps to a
   single Vault object (AppRole SecretID accessor / KV path / lease) whose
   destruction severs exactly that principal.
5. **The audit trail is regista.** Vault knows *authentication* events; the
   suite's event chain knows *use*. Key issuance/rotation/revocation flow
   through regista's principal-key lifecycle (dossier dual-control), so the
   two ledgers cross-check.

## 3. Vault layout

All suite state lives under the existing KV-v2 mount, namespaced per
deployment (`prod` today; a `qual/` twin exists only during platform
qualification and is deleted afterward):

```
kv/agent-suite/<deployment>/
  shared/                      # read by every host service
    regista-dsn                #   field: password  (the only truly shared secret)
  hosts/<hostname>/            # read only by that host's AppRole
    cairn-content-key          #   field: key
    service-env                #   host-local operational secrets
  principals/<principal-id>/   # read only by that principal's AppRole
    signing-key                #   field: ed25519_private  (custody: see §4)
```

Policies are generated, not hand-written — one template each:

- `agent-suite-host-<hostname>`: read `shared/*` + `hosts/<hostname>/*`.
- `agent-suite-principal-<id>`: read `principals/<id>/*` only.
- `agent-suite-onboarder`: **create-only** under `principals/+/*`
  (`create` without `update`/`delete`, CAS required) plus AppRole
  role-creation on a constrained path prefix — the credential the
  onboarding flow runs under; it can mint new principals but cannot read
  or replace existing material.

AppRoles mirror the policies 1:1 (`host-<hostname>`,
`principal-<id>`, `onboarder`). RoleIDs are not secret and may live in
`suite.env`; SecretIDs are constrained: `secret_id_ttl=24h` for delivery,
`token_ttl=1h`, `token_max_ttl=4h`, `secret_id_num_uses` finite, and
CIDR-bound to the host where that is practical.

## 4. Signing-key custody (the part that is not just "put it in Vault")

Per-actor Ed25519 signing keys follow regista Plan 031: the **client signer
generates the keypair and custodies the private key; only the public key
enters the enrollment flow** (dossier `prepare_enrollment` → possession
challenge → dual-control approval → effective-use receipt). Vault's role
differs by principal type:

- **Agents / service principals**: the private key is written by the signer
  to `kv/agent-suite/<dep>/principals/<id>/signing-key`, readable only by
  that principal's AppRole. Custody backend `vault` (regista `_custody.py`
  already has the write path). The host never holds the key at rest
  outside Vault.
- **Humans**: keys stay in the human's own custody (file mode 0600 on
  their workstation now; DPAPI/OS keychain as the client signer grows
  support). Vault holds nothing for them — a human's key must not be
  readable by any machine credential.

Rotation and revocation are **regista lifecycle operations first** (so the
event chain records them, with dual control), and Vault operations second
(destroy the KV version / SecretID accessor). Today's `agent-suite offboard`
(multi-user-onboarding.md §6) revokes regista keys, deletes the custodied
key ref, and removes the overlay; **it must be extended** to also destroy
the principal's AppRole SecretID accessor and to assert both
authentication and signing now fail (with replay flagging any
post-revocation use) — that extension is part of the multi-user
lifecycle exercise, not yet shipped behavior.

## 5. Bootstrap trust — how a new host/principal gets its first secret

1. Operator (or CI) authenticates with their **own** identity and runs
   `agent-suite onboard`/host provisioning, which uses the `onboarder`
   AppRole.
2. Vault issues the new AppRole's SecretID **response-wrapped**
   (`-wrap-ttl=15m`, single unwrap). The wrapping token travels to the new
   host over SSH/WinRM as part of bootstrap; the host unwraps it exactly
   once — single-use is a property of the wrapping mechanism itself, not
   an added guarantee. A failed/expired unwrap is an ordinary error: the
   onboarding is re-run, and the audit log shows whether the original
   wrapping token was consumed by someone else in the interim.
3. The host writes only `{role_id, unwrapped secret_id}` to its local
   plane file (0600) and exchanges them for short-lived tokens from then
   on.

## 6. What qualification must prove (feeds the platform checklist)

- Every `vault:` ref in the host's `suite.env` **resolves end-to-end** at
  bootstrap and at doctor time (a ref that is set-but-unresolvable is a
  fail, not a warn — closes the §1 latent bug class).
- A production/AppRole host operates with **no `VAULT_TOKEN` in its
  environment** — AppRole only (guards against the ambient-token class of
  bug found in the acb Plan-009 review). Dev-mode installs per
  [secrets-vault.md](secrets-vault.md) §2 legitimately use `VAULT_TOKEN`;
  the check is scoped to hosts whose suite.env declares AppRole
  credentials.
- Cross-principal isolation: principal A's token cannot read principal
  B's `signing-key` path (negative test, asserted).
- Revocation: after `agent-suite offboard`, the principal's AppRole login
  fails, its KV path is destroyed, and a signed write attempt is rejected
  and flagged by replay.

## 7. Migration from the current estate (phased, per host)

1. Stand up the layout + policies + AppRoles under
   `kv/agent-suite/prod/` using the root token **once**, via an
   idempotent, reviewed script in `scripts/` — **a follow-up deliverable
   of this document**, not yet in the tree.
2. Move the shared DSN password and each host's cairn content key into the
   layout; fix `suite.env` refs to the canonical `vault:kv/...` form.
3. Per host: issue the host AppRole (response-wrapped), switch `suite.env`
   from file refs to `vault:` refs, run doctor + resolution checks, then
   delete the file-backed copies.
4. Per principal: enroll through the client-signer flow (§4); retire the
   shared `regista-prod-001` HMAC key after the last principal is on
   per-actor Ed25519 (regista supports the mixed-mode chain during the
   transition).
5. **Retire the root token**: generate a new root only via
   `vault operator generate-root` ceremony when needed; revoke the
   standing one; store unseal/recovery material per the break-glass
   runbook. From this point the strongest standing credential is the
   `onboarder` AppRole.

## 8. Open items

- AKV parity: this document is Vault-first because the estate runs Vault;
  the same shape maps to AKV (per-host service principals + Key Vault
  access policies) and `secrets-akv.md` should gain the mirrored layout
  when an AKV deployment first exists.
- The TOTP and `database/` mounts predate this strategy and are out of
  scope here.
- Kubernetes auth (`kubernetes/`) is enabled and unused by the suite; if
  suite components ever run in-cluster, per-service-account roles replace
  host AppRoles for those components.
