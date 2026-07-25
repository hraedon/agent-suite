# Multi-user onboarding

How to onboard additional humans onto a shared Postgres-backed suite. The
system admin stands up the suite once (see an [install guide](install-linux.md));
each additional human is onboarded with a single command that writes a
per-user overlay and provisions their signing key — without touching the
shared store.

This implements bootstrap step 7 and the configuration layering described in
the [bootstrap contract](bootstrap-contract.md) §2. The key-custody model is
in the [threat model](key-custody-threat-model.md).

---

## 1. The shared backend model

The suite uses one Postgres instance as the shared store. regista provisions a
schema and service role per project; each human and agent principal gets a
per-actor Ed25519 signing key stored in the secret backend. All principals
write to the same event log under their own `actor_id`, with per-actor
signatures (regista Plan 026).

```
┌─────────────────────────────────────────────────────────────┐
│  Postgres (shared)                                          │
│    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│    │ project A    │  │ project B    │  │ project C    │     │
│    │ schema+role  │  │ schema+role  │  │ schema+role  │     │
│    └──────┬───────┘  └──────┬───────┘  └──────┬───────┘     │
│           └──────────────────┴──────────────────┘            │
│                       event log (signed)                     │
└───────────────────────────────────────────────────────────────┘
        ▲              ▲              ▲
        │              │              │
   human-1          human-2        agent-1
   (dossier)        (dossier)     (agent-notes)
```

A human authenticates via LDAP; dossier resolves their `principal_id` from the
session, fetches their signing key from the secret backend, signs the event,
and clears the key (transient custody — see the
[threat model](key-custody-threat-model.md) §1.2).

## 2. System admin: one-time bootstrap

The system admin runs the initial bootstrap (see an
[install guide](install-linux.md)):

```bash
agent-suite bootstrap --tier 0-1
```

This writes the **system** `suite.env`
(`/etc/agent-suite/suite.env` or `%ProgramData%\agent-suite\suite.env`) with
shared facts: the DSN host, secret-backend pointers, and the project registry.
It also provisions the regista system principal key and the first project's
schema and service role. This is done **once**.

## 3. Onboard each additional human

For each new human, the system admin runs:

```bash
agent-suite bootstrap --user <principal_id>
```

This performs two things (bootstrap step 7):

1. **Writes a per-user `suite.env` overlay** at
   `~/.config/agent-suite/suite.env` (Linux) or
   `%APPDATA%\agent-suite\suite.env` (Windows), containing that human's
   `principal_id`, default project, and personal harness wiring.
2. **Provisions the principal's signing key** via `regista provision-principal`,
   which enrolls the principal and writes their Ed25519 key to the secret
   backend at `secret/agent-suite/principals/<principal_id>` (or the
   `akv:` / `wincred:` equivalent — see the relevant
   [secrets runbook](secrets-vault.md)).

The overlay does **not** touch the shared system `suite.env` — it layers on
top of it. The resolution precedence (from the
[bootstrap contract](bootstrap-contract.md) §2):

```
process env  >  per-user suite.env  >  system suite.env  >  tool default
```

### What goes in the per-user overlay

```env
# Per-user — written by `agent-suite bootstrap --user <principal_id>`
REGISTA_PRINCIPAL_ID=<principal_id>
AGENT_NOTES_PROJECT=project-slug
DOSSIER_PROJECTS=project-slug,another-slug
```

The shared DSN, secret-backend pointers, and SSL setting stay in the system
file — they are not duplicated per user.

## 4. Per-actor signing keys

Each human's Ed25519 private key is stored in the secret backend at a distinct
path, scoped to that `principal_id`:

| Backend | Path |
|---------|------|
| Vault | `vault:secret/agent-suite/principals/<principal_id>#key` |
| AKV | `akv:suite-secrets.WORK-DOMAIN.vault.azure.net/principal-<principal_id>-key` |
| Windows | `wincred:agent-suite/principals/<principal_id>/key` |

dossier retrieves the key at sign time and clears it after — the human never
handles the private key directly. This is the trusted-signing-proxy model
documented in the [threat model](key-custody-threat-model.md) §3.

Agent principals (the agent-notes CLI, cairn hooks) are onboarded the same
way, with their own `principal_id` and key. An agent signs `on_behalf_of` a
human; the delegation chain is recorded (see the
[threat model](key-custody-threat-model.md) §T4).

## 5. Re-running for an existing user

`agent-suite bootstrap --user <principal_id>` is idempotent: re-running it on
an already-onboarded user updates the overlay (e.g., to change their default
project) but does **not** clobber an existing signing key. If the principal
already has a key, the provision step refuses and reports rather than
overwriting — see the [bootstrap contract](bootstrap-contract.md) §1 step 2.

## 6. Leaver process

When a human leaves, revoke their principal within the SLA defined in
[key-operations.md](key-operations.md) §Leaver process. The system admin runs:

```bash
agent-suite offboard --user <principal_id> --reason leaver
```

This is the mirror of `bootstrap --user`. It:

1. Lists the principal's **active** keys and revokes each one
   (`regista principal revoke`), which windows the key out (`valid_to` is set
   to the revocation timestamp — see regista Plan 026 WI-3.1). Events the key
   signed *before* the revocation stay valid; events *after* are flagged by
   `regista verify` as `unregistered-signer` (see the
   [threat model](key-custody-threat-model.md) §T5).
2. **Deletes the custodied private key** from the secret backend
   (`regista secrets --ref <ref> --delete`), closing the fetch path.
3. Removes the leaver's per-user overlay (`--keep-overlay` to skip).

Use `--dry-run` first: it lists exactly which keys would be revoked and
deleted, and touches nothing.

```
offboard alice: done
  revoke_keys      done   revoked 1 key(s): key-1
  secret_backend   done   deleted 1 custodied key(s)
  user_overlay     done   overlay removed at /home/alice/.config/agent-suite/suite.env
```

Both steps matter and neither substitutes for the other: revocation stops the
key being *accepted*, deletion stops it being *fetched*.

### When it cannot finish

Two cases leave real work outstanding, and both exit nonzero with
`manual_action_required` rather than being folded into success:

- **The backend refuses.** `env:` references cannot be deleted from here —
  clearing the variable in this process would leave it set everywhere it
  matters. Unset it wherever it is defined.
- **The reference carries the key.** A `windows:` reference *is* the DPAPI
  blob, and a `literal:` reference *is* the value. There is nothing stored to
  delete, so every copy of the reference is a copy of the private key. Purge
  the reference from wherever it is recorded — config, backups, tickets.

```
offboard alice: manual_action_required
  revoke_keys      done                   revoked 1 key(s): key-1
  secret_backend   manual_action_required 1 reference(s) carry the key inline and
                                          must be discarded wherever they are
                                          recorded: windows:AQAAANCMnd8B...
  user_overlay     done                   overlay removed at ...
```

Automation must not read a `manual_action_required` offboarding as complete.
See the relevant [secrets runbook](secrets-vault.md) for backend specifics.

## 7. Verify

After onboarding a user, confirm their wiring is correct:

```bash
agent-suite doctor
```

The user can also verify their own principal is active:

```bash
regista principal list
```

## 8. Reference

- [bootstrap contract](bootstrap-contract.md) §2 — configuration layering
- [bootstrap contract](bootstrap-contract.md) §1 step 7 — per-user onboarding
- [key-custody threat model](key-custody-threat-model.md) — the signing model
- [key-operations.md](key-operations.md) — rotation, leaver, break-glass policy
