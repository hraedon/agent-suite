# Azure Key Vault secret backend

How to store the suite's secrets — the DSN password and per-actor Ed25519
signing keys — in Azure Key Vault and reference them from `suite.env` via the
`azure:` prefix. regista's secret resolver (`regista.secrets.resolve`, Plan 025
WI-1.2) reads `azure:` refs at load time; the suite never holds a literal
secret in a committed file.

The `azure:` scheme takes a **bare Key Vault secret name** — the vault itself
is named by the `AZURE_KEY_VAULT_NAME` environment variable (regista builds the
vault URL as `https://<name>.vault.azure.net`), and is **not** embedded in the
ref. This is the shape the resolver actually accepts; the old `akv:` prefix and
the vault-DNS-embedded form several docs printed are not recognised and
resolve as literal strings (WI-069).

See the [bootstrap contract](bootstrap-contract.md) for where secret resolution
sits in the install order (step 0), and the [key-custody threat model](key-custody-threat-model.md)
for why the signing keys live in the backend, not on disk.

---

## 1. Prerequisites

- An Azure subscription with permission to create a Key Vault.
- `azure-identity` and `azure-keyvault-secrets` installed on the host that
  runs `agent-suite`: `pip install agent-suite[azure]` (the `azure` extra pulls
  both libraries; the core stays stdlib-only — see `pyproject.toml`).
- A Managed Identity (preferred) or service principal assigned to the host
  running the suite, with Key Vault read access.

## 2. Set up Azure Key Vault

### Create the vault

```bash
az keyvault create \
  --name suite-secrets \
  --resource-group suite-rg \
  --enable-rbac-authorization true
```

The vault's DNS name will be `https://suite-secrets.WORK-DOMAIN.vault.azure.net/`
(replace `WORK-DOMAIN` with your Azure-registered domain suffix). regista does
**not** read that name from the ref — it reads `AZURE_KEY_VAULT_NAME` from the
environment (see §4), so set that variable to the vault name (`suite-secrets`).

### Grant the suite identity read access

With Managed Identity (preferred — no secret in config):

```bash
az role assignment create \
  --role "Key Vault Secrets User" \
  --assignee <managed-identity-principal-id> \
  --scope <key-vault-resource-id>
```

With a service principal, grant the same role to the principal's object id.
Managed Identity is the recommended posture: there is no client secret to
rotate or leak — the identity is bound to the Azure resource (see the
[threat model](key-custody-threat-model.md) §T2 mitigation 1).

## 3. Store the secrets

### DSN password

```bash
az keyvault secret set \
  --vault-name suite-secrets \
  --name regista-dsn-password \
  --value "<the DB-SERVICE-ACCOUNT role password>"
```

### Regista system signing key

```bash
az keyvault secret set \
  --vault-name suite-secrets \
  --name regista-signing-key \
  --value "<Ed25519 private key, base64>"
```

### Per-principal signing keys

Each human and agent principal gets a secret named
`principal-<principal_id>-key`:

```bash
az keyvault secret set \
  --vault-name suite-secrets \
  --name principal-<principal_id>-key \
  --value "<Ed25519 private key, base64>"
```

`<principal_id>` is the stable identifier regista assigns at enrollment
(Plan 026 WI-3.3) — not a display name. Use hyphens (`-`) in the secret name;
Key Vault secret names must match `^[0-9a-zA-Z-]+$`.

## 4. Reference them from suite.env

In the system `suite.env` (`/etc/agent-suite/suite.env` on Linux,
`%ProgramData%\agent-suite\suite.env` on Windows):

```env
AZURE_KEY_VAULT_NAME=suite-secrets
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista
REGISTA_KEY_PATH=/etc/agent-suite/keys.json
REGISTA_REQUIRE_SSL=true
```

The `azure:` prefix tells regista's loader to resolve the value from Key Vault
at load time. The format is:

```
azure:<secret-name>
```

`AZURE_KEY_VAULT_NAME` names the vault (regista builds the URL as
`https://<name>.vault.azure.net`); the secret name after `azure:` is the bare
Key Vault secret name. Key Vault secret names must match `^[0-9a-zA-Z-]+$`.

The resolved value reaches the process that needs it and is **never written
back to the file**. Compare with [`suite.env.example`](../suite.env.example),
which carries placeholders only.

There is no `REGISTA_DSN_PASSWORD` variable in regista's config vocabulary —
the DSN password is part of `REGISTA_DSN` (see the [bootstrap contract](bootstrap-contract.md)).
`REGISTA_KEY_PATH` is a path to a `keys.json` **file**, not a ref; custodied
signing keys are per-key `secret_ref` entries *inside* that file (see
[secrets-vault.md](secrets-vault.md) §4.1), each of which may carry an
`azure:<secret-name>` ref.

Per-principal key refs are resolved by dossier at sign time
(`azure:principal-<principal_id>-key`) and are not stored in the system
`suite.env` — they are looked up by `principal_id` from the authenticated
session.

## 5. How resolution works

`regista.secrets.resolve("azure:regista-signing-key")` with
`AZURE_KEY_VAULT_NAME=suite-secrets`:

1. Parses the `azure:` scheme; the rest (`regista-signing-key`) is the secret
   name. The vault URL is `https://suite-secrets.vault.azure.net`, built from
   `AZURE_KEY_VAULT_NAME` — the vault name is **not** embedded in the ref.
2. Authenticates via `DefaultAzureCredential` (Managed Identity in production,
   or the developer's `az login` session locally).
3. Reads the secret value from Key Vault.
4. Returns the value to the caller; the caller uses it and clears it from
   memory after the operation (transient custody — see the
   [threat model](key-custody-threat-model.md) §T1).

Every secret read is recorded in Key Vault's diagnostic logs. Correlating
these against the event log's signed events is the detection story for
key-access anomalies — see the [threat model](key-custody-threat-model.md)
§T1 mitigation 2.

## 6. Verify

After configuring `suite.env`, confirm the backend is reachable and the refs
resolve before bootstrapping:

```bash
agent-suite bootstrap --dry-run
```

Step 0 of the bootstrap (secret backend reachable) probes the resolver. If an
`azure:` ref cannot be resolved, the bootstrap aborts with a clear message
naming the failing ref — it does not proceed to provision against an
unresolvable secret. See the [bootstrap contract](bootstrap-contract.md) §1.
