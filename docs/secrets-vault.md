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
- `hvac` installed on the host that runs `agent-suite`:
  `pip install agent-suite[vault]` (the `vault` extra pulls `hvac`; the core
  stays stdlib-only — see `pyproject.toml`).
- `VAULT_ADDR` set to the Vault endpoint (e.g. `https://vault.example:8200`).
- `VAULT_TOKEN` (dev) or AppRole `role_id` + `secret_id` (production), reachable
  by the process that runs `agent-suite bootstrap`.

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
vault secrets enable -path=secret kv-v2

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
systemd `EnvironmentFile=`, a Windows service env block, or a root-owned file).
Rotate `secret_id` per your organizational policy — see
[key-operations.md](key-operations.md) §Rotation.

## 3. Store the secrets

### DSN password

The password for the `DB-SERVICE-ACCOUNT` Postgres role:

```bash
vault kv put secret/agent-suite/regista \
  dsn_password="<the DB-SERVICE-ACCOUNT role password>"
```

### Regista system signing key

The key regista uses for synthetic/migration events (the system principal —
see the [threat model](key-custody-threat-model.md) §1.1):

```bash
vault kv put secret/agent-suite/regista \
  signing_key="<Ed25519 private key, base64>"
```

### Per-principal signing keys

Each human and agent principal gets a key at a distinct path
(`secret/agent-suite/principals/<principal_id>`):

```bash
vault kv put secret/agent-suite/principals/<principal_id> \
  key="<Ed25519 private key, base64>"
```

`<principal_id>` is the stable identifier regista assigns at enrollment
(Plan 026 WI-3.3) — not a display name. Keep the path scheme stable; the
dossier signing proxy fetches keys by this path at sign time.

## 4. Reference them from suite.env

In the system `suite.env` (`/etc/agent-suite/suite.env` on Linux,
`%ProgramData%\agent-suite\suite.env` on Windows):

```env
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista
REGISTA_DSN_PASSWORD=vault:secret/agent-suite/regista#dsn_password
REGISTA_KEY_PATH=vault:secret/agent-suite/regista#signing_key
REGISTA_REQUIRE_SSL=true
```

The `vault:` prefix tells regista's loader to resolve the value from Vault at
load time; the `#field` suffix names the key within the KV path. The resolved
value reaches the process that needs it and is **never written back to the
file**. Compare with [`suite.env.example`](../suite.env.example), which carries
placeholders only.

Per-principal key paths are resolved by dossier at sign time
(`vault:secret/agent-suite/principals/<principal_id>#key`) and are not stored
in the system `suite.env` — they are looked up by `principal_id` from the
authenticated session.

## 5. How resolution works

`regista.secrets.resolve("vault:secret/agent-suite/regista#signing_key")`:

1. Parses the `vault:` scheme, the KV path (`secret/agent-suite/regista`),
   and the field (`signing_key`).
2. Authenticates to Vault via the configured AppRole (production) or static
   token (dev).
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
path "secret/data/agent-suite/principals/*" {
  capabilities = ["read"]
}
path "secret/data/agent-suite/regista" {
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

Step 0 of the bootstrap (secret backend reachable) probes the resolver. If a
`vault:` ref cannot be resolved, the bootstrap aborts with a clear message
naming the failing ref — it does not proceed to provision against an
unresolvable secret. See the [bootstrap contract](bootstrap-contract.md) §1.
