# Azure Key Vault secret backend

How to store the suite's secrets — the DSN password and per-actor Ed25519
signing keys — in Azure Key Vault and reference them from `suite.env` via the
`akv:` prefix. regista's secret resolver (`regista.secrets.resolve`, Plan 025
WI-1.2) reads `akv:` refs at load time; the suite never holds a literal
secret in a committed file.

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
(replace `WORK-DOMAIN` with your Azure-registered domain suffix). Use that
name in the `akv:` refs below.

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
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista
REGISTA_DSN_PASSWORD=akv:suite-secrets.WORK-DOMAIN.vault.azure.net/regista-dsn-password
REGISTA_KEY_PATH=akv:suite-secrets.WORK-DOMAIN.vault.azure.net/regista-signing-key
REGISTA_REQUIRE_SSL=true
```

The `akv:` prefix tells regista's loader to resolve the value from Key Vault at
load time. The format is:

```
akv:<vault-name>.<domain-suffix>.vault.azure.net/<secret-name>
```

The resolved value reaches the process that needs it and is **never written
back to the file**. Compare with [`suite.env.example`](../suite.env.example),
which carries placeholders only.

Per-principal key refs are resolved by dossier at sign time
(`akv:suite-secrets.WORK-DOMAIN.vault.azure.net/principal-<principal_id>-key`)
and are not stored in the system `suite.env` — they are looked up by
`principal_id` from the authenticated session.

## 5. How resolution works

`regista.secrets.resolve("akv:suite-secrets.WORK-DOMAIN.vault.azure.net/regista-signing-key")`:

1. Parses the `akv:` scheme and extracts the vault DNS name and secret name.
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
`akv:` ref cannot be resolved, the bootstrap aborts with a clear message
naming the failing ref — it does not proceed to provision against an
unresolvable secret. See the [bootstrap contract](bootstrap-contract.md) §1.
