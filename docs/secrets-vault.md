# HashiCorp Vault secret backend

How to store the suite's secrets — the DSN password and per-actor Ed25519
signing keys — in HashiCorp Vault and reference them from `suite.env` via the
`vault:` prefix. regista's secret resolver (`regista.secrets.resolve`, Plan 025
WI-1.2) reads `vault:` refs at load time; the suite never holds a literal
secret in a committed file.

See the [bootstrap contract](bootstrap-contract.md) for where secret resolution
sits in the install order (step 0), and the [key-custody threat model](key-custody-threat-model.md)
for why the signing keys live in the backend, not on disk.

---

## 1. Prerequisites

- A Vault server (dev mode for evaluation, or a production cluster).
- `hvac` installed **in the environment of every component that resolves a
  `vault:` ref** — not just on the host. Each suite CLI is normally its own
  `uv tool` venv, and a provider is registered per *process*: `vault` appearing
  in `regista secrets --list-providers` says nothing about whether cairn or
  dossier can resolve their own refs. Install the `vault` extra for each
  (`uv tool install --with hvac …`) and confirm per component; the suite core
  stays stdlib-only (see `pyproject.toml`).
- `VAULT_ADDR` set to the Vault endpoint (e.g. `https://vault.example:8200`).
- Credentials reachable by every process that resolves a ref — see §8, which
  states plainly which methods each component can actually use today.

## 2. Set up Vault

### Dev mode (evaluation only)

```bash
vault server -dev -dev-root-token-id=dev-only-token
export VAULT_ADDR=http://vault.example:8200
export VAULT_TOKEN=dev-only-token
```

Dev mode keeps secrets in memory and is destroyed on restart. Use it only to
walk through the install; **never** for a real deployment.

### Production

Stand up a Vault cluster per the
[Vault production deployment guide](https://developer.hashicorp.com/vault/tutorials/operations/raft-deployment-guide),
then enable KV v2 and create an AppRole for the suite:

```bash
vault secrets enable -path=kv kv-v2   # substitute your own mount name

vault auth enable approle
vault write auth/approle/role/agent-suite \
  secret_id_ttl=24h \
  secret_id_num_uses=0 \
  token_ttl=1h \
  token_max_ttl=4h

# Capture both for the suite process environment:
vault read -field=role_id auth/approle/role/agent-suite/role-id
vault write -f -field=secret_id auth/approle/role/agent-suite/secret-id
```

Store the `role_id` and `secret_id` where the suite process can read them (a
systemd `EnvironmentFile=`, a Windows service env block, or a root-owned file);
§8.1 gives the variable names. Rotate `secret_id` per your organizational
policy — see [key-operations.md](key-operations.md) §Rotation.

> **Read §8.1 before you build a host on this.** Standing up the AppRole is not
> the same as the suite being able to use it. On regista as currently released it
> **cannot**: `VaultProvider` authenticates with `VAULT_TOKEN` and nothing else.
> §8.1 says what that means and what changes it.

## 3. Store the secrets

### DSN password

The password for the `DB-SERVICE-ACCOUNT` Postgres role:

```bash
vault kv put kv/agent-suite/regista \
  dsn_password="<the DB-SERVICE-ACCOUNT role password>"
```

### Regista system signing key

The key regista uses for synthetic/migration events (the system principal —
see the [threat model](key-custody-threat-model.md) §1.1):

```bash
vault kv put kv/agent-suite/regista \
  signing_key="<Ed25519 private key, base64>"
```

### Per-principal signing keys

Each human and agent principal gets a key at a distinct path
(`kv/agent-suite/principals/<principal_id>`):

```bash
vault kv put kv/agent-suite/principals/<principal_id> \
  key="<Ed25519 private key, base64>"
```

`<principal_id>` is the stable identifier regista assigns at enrollment
(Plan 026 WI-3.3) — not a display name. Keep the path scheme stable; the
dossier signing proxy fetches keys by this path at sign time.

## 4. Reference them from suite.env

### The ref shape: `vault:<mount>/<path…>/<field>`

**The field is the last path segment. There is no `#field` suffix** — regista's
`VaultProvider.resolve` splits on `/`, takes the first segment as the mount, the
last as the field, and the middle as the KV path (it requires at least four
segments). This is what `regista secrets --help` documents, and this file, three
install runbooks and `suite.env.example` all printed the `#field` form until
WI-039. That form is worse than a clean error: against a real mount, appending
`#hmac_key` to `vault:kv/agent-suite/hosts/h/regista` *parses* to mount `kv`,
path `agent-suite/hosts/h`, and a field named `regista` + `#hmac_key` — a
**different, neighbouring secret**, which a permissive policy will happily read.

Substitute your own mount for `kv` below; there is no default, and the `secret/`
mount this document used to print does not exist on every Vault.

### Two variables that are not refs

- **`REGISTA_KEY_PATH` is a path to a `keys.json` **file**,** not a resolvable
  ref: regista reads it with `Path(...).read_text()`. Backend refs belong
  *inside* that file, as per-key `secret_ref` + `encoding` entries (§4.1).
- **`REGISTA_DSN_PASSWORD` does not exist** in regista's config vocabulary
  (`regista._config` `_CANONICAL`/`_ALIASES`) and is silently ignored. The DSN
  password is part of `REGISTA_DSN`. `agent-suite bootstrap` step 0 now reports
  both of these as configuration errors rather than proceeding.

In the system `suite.env` (`/etc/agent-suite/suite.env` on Linux,
`%ProgramData%\agent-suite\suite.env` on Windows):

```env
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista
REGISTA_KEY_PATH=/etc/agent-suite/keys.json
REGISTA_REQUIRE_SSL=true
# Refs for the components that do take one directly:
CAIRN_CONTENT_KEY_REF=vault:kv/agent-suite/hosts/HOSTNAME/cairn/content_key
```

The `vault:` prefix tells regista's resolver to fetch the value at load time.
The resolved value reaches the process that needs it and is **never written back
to the file**. Compare with [`suite.env.example`](../suite.env.example), which
carries placeholders only.

### 4.1 Custodied signing keys — the form that works

`keys.json` carries one entry per key; a custodied key names its ref instead of
its material:

```json
{
  "keys": [
    {
      "key_id": "HOSTNAME-2026-07",
      "scheme": "hmac-sha256",
      "status": "active",
      "secret_ref": "vault:kv/agent-suite/hosts/HOSTNAME/regista/hmac_key",
      "encoding": "base64"
    }
  ]
}
```

This is the form the Linux qualification proved on a real Vault: the runtime
logs `key_sources={'HOSTNAME-2026-07': 'secret_ref:vault'}`. The file itself
holds no secret, so it needs no more protection than its directory.

Per-principal key paths are resolved by dossier at sign time
(`vault:kv/agent-suite/principals/<principal_id>/key`) and are not stored
in the system `suite.env` — they are looked up by `principal_id` from the
authenticated session.

## 5. How resolution works

`regista.secrets.resolve("vault:kv/agent-suite/regista/signing_key")`:

1. Parses the `vault:` scheme, the mount (`kv`), the KV path
   (`agent-suite/regista`), and the field (`signing_key`) — the **last**
   segment.
2. Authenticates to Vault. **On regista as currently released this is
   `VAULT_TOKEN` and only `VAULT_TOKEN`** — see §8.1. AppRole login is regista
   WI-228 and is not on regista's main at the time of writing.
3. Reads the secret value from KV v2.
4. Returns the value to the caller; the caller uses it and clears it from
   memory after the operation (transient custody — see the
   [threat model](key-custody-threat-model.md) §T1).

Every `secrets.resolve` call is recorded in Vault's audit log. Correlating
audit-log entries against the event log's signed events is the detection
story for key-access anomalies — see the [threat model](key-custody-threat-model.md)
§T1 mitigation 2.

## 6. Per-principal Vault policies (hardening)

For a stricter posture, scope the AppRole policy so the suite can read each
principal's key only at its path:

```hcl
path "kv/data/agent-suite/principals/*" {
  capabilities = ["read"]
}
path "kv/metadata/agent-suite/principals/*" {
  capabilities = ["read"]
}
path "kv/data/agent-suite/regista" {
  capabilities = ["read"]
}
```

A v2 hardening (per-session-scoped policies so dossier can read only the
active principal's key) is described in the
[key-custody threat model](key-custody-threat-model.md) §T1 mitigation 3; v1
grants the AppRole read access to all principal paths.

## 7. Verify

After configuring `suite.env`, confirm the backend is reachable and the refs
resolve before bootstrapping:

```bash
agent-suite bootstrap --dry-run
```

Step 0 of the bootstrap **enumerates every backend ref this host's resolved
config names** — suite env vars carrying a backend scheme, plus the per-key
`secret_ref` entries inside `REGISTA_KEY_PATH`'s `keys.json` — and resolves each
one. If a ref cannot be resolved, the bootstrap aborts naming the failing ref;
it does not proceed to provision against an unresolvable secret. Malformed
shapes (the `#field` form, a three-segment ref) are caught before any network
call, because against a real mount they resolve *something else* rather than
failing.

Until WI-041 that step ran `regista secrets --list-providers`, which proves a
provider class is registered in regista's process — not that anything resolves.
A host whose only `vault:` ref was 403 passed it. Note the remaining limit,
which the step states in its own output: refs are resolved through **regista's**
environment, so a ref belonging to another component still depends on that
component having `hvac` in its own venv (§1), and that component's own doctor is
what checks it. See the [bootstrap contract](bootstrap-contract.md) §1.

## 8. How each component authenticates — and what does not work yet

The Linux qualification (Plan 020 Lane C) proved the custody *design*: a scoped
policy, an AppRole, response-wrapped SecretID delivery shown to be single-use, and
cross-principal reads denied. It could not prove the AppRole *posture*, because:

> **regista's `VaultProvider` has no AppRole login.** It reads `VAULT_TOKEN` and
> NOTHING ELSE. With no `VAULT_TOKEN` set, resolving a host's own key fails with
> `[KEY_LOAD_ERROR] vault: authentication failed`. The qualification had to write
> an undocumented shim (`with-vault-approle`) that exchanged role_id+secret_id for
> a one-hour token and exec'd the real command, purely so the rest of the run
> could proceed. That shim is a compensating control, not evidence that
> AppRole-only works. Filed as **regista WI-221**.

So on regista as currently released, a Vault-backed host carries a `VAULT_TOKEN`.
Anything in this runbook that reads as "the production posture is AppRole" is
describing the target, not the present. Say so to whoever asks.

### 8.1 The AppRole variables (regista WI-228 — not yet on regista main)

regista WI-228 adds the AppRole login and a `custody:vault_auth` doctor row that
reports **which** method authenticated, so an operator can tell an AppRole host
from a token host without guessing. Its convention, which
`suite.env.example` now carries:

| Variable | Purpose |
|----------|---------|
| `VAULT_ADDR` | the Vault endpoint |
| `VAULT_ROLE_ID` | the AppRole RoleID, inline |
| `VAULT_ROLE_ID_FILE` | ...or a file holding it (preferred: keeps it out of the process env) |
| `VAULT_SECRET_ID_FILE` | a file holding the SecretID — **preferred over inline** |
| `VAULT_SECRET_ID` | inline SecretID, for cases where a file is impossible |
| `VAULT_SECRET_ID_RESPONSE_WRAPPED` | `1` when `VAULT_SECRET_ID_FILE` holds a response-**wrapping token** rather than the SecretID itself. Requires `VAULT_SECRET_ID_FILE`; setting it with an inline SecretID is an error, not a silent downgrade |
| `VAULT_APPROLE_MOUNT_POINT` | the auth mount (default `approle`) |
| `VAULT_TOKEN` | **dev only.** A static token, kept so `vault server -dev` still works |

Two properties worth knowing, both verified in regista's WI-228 branch:

- **It never falls back to `VAULT_TOKEN`.** A RoleID present with no SecretID is
  an error naming the missing variable, not a quiet downgrade to token auth — a
  fallback would turn a hardening step into a silent weakening.
- **Response-wrapped delivery is one-shot**, which the qualification confirmed
  against the live Vault: a second unwrap of the same token returns HTTP 400.

**Status check before you rely on this.** WI-228 was not merged to regista's main
at the time of writing. Confirm with:

```sh
regista doctor --json | jq '.checks[] | select(.name == "custody:vault_auth")'
```

An AppRole host reports `ok` with `vault auth: AppRole at auth/<mount> … No
VAULT_TOKEN required`. A token host reports `warn` and says it is the dev-only
method. If the row is absent entirely, the installed regista predates WI-228 and
`VAULT_TOKEN` is your only option.

> The suite-wide custody *strategy* document referenced by Plan 020 §Lane C
> (`docs/secrets-instantiation.md`) is **not on any main** — it lives in an
> unmerged agent-suite PR. This runbook (`secrets-vault.md`) is the merged one.
> Do not build a host against a claim that only exists there.
