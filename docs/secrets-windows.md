# Windows Credential Manager / DPAPI secret backend

How to store the suite's secrets — the DSN password and per-actor Ed25519
signing keys — in Windows Credential Manager (backed by DPAPI) and reference
them from `suite.env` via the `wincred:` prefix. regista's secret resolver
(`regista.secrets.resolve`, Plan 025 WI-1.2) reads `wincred:` refs at load
time; the suite never holds a literal secret in a committed file.

This backend is for single-machine Windows deployments where the secret
perimeter is the Windows account boundary (DPAPI encrypts to the user or
machine scope). For multi-host deployments, use [Vault](secrets-vault.md) or
[AKV](secrets-akv.md) — DPAPI secrets do not travel across machines.

See the [bootstrap contract](bootstrap-contract.md) for where secret resolution
sits in the install order (step 0), and the [key-custody threat model](key-custody-threat-model.md)
for why the signing keys live in the backend, not on disk.

---

## 1. Prerequisites

- Windows 10/11 or Windows Server 2019+.
- `pywin32` installed: `pip install agent-suite[windows]` (the `windows` extra
  pulls `pywin32`; the core stays stdlib-only — see `pyproject.toml`).
- The suite process running under the Windows account that owns the
  credentials (DPAPI keys are scoped to the user or machine — see §3).

## 2. Store the secrets

Use PowerShell's `cmdkey` or the Credential Manager UI. Credentials are stored
as Generic Credentials with a target name the suite will reference.

### DSN password

```powershell
cmdkey /generic:agent-suite/regista/dsn-password /user:regista_service /pass:"<the regista_service role password>"
```

### Regista system signing key

```powershell
cmdkey /generic:agent-suite/regista/signing-key /user:regista /pass:"<Ed25519 private key, base64>"
```

### Per-principal signing keys

Each human and agent principal gets a credential with a target name containing
the `principal_id`:

```powershell
cmdkey /generic:agent-suite/principals/<principal_id>/key /user:<principal_id> /pass:"<Ed25519 private key, base64>"
```

`<principal_id>` is the stable identifier regista assigns at enrollment
(Plan 026 WI-3.3) — not a display name.

## 3. Credential scope

DPAPI credentials are encrypted to one of two scopes:

- **User scope** (default): only the Windows account that stored the credential
  can read it. Use this when the suite runs as a dedicated service account —
  store the credentials while logged in as that account.
- **Machine scope**: any process on the machine can read the credential. Use
  this only for shared service accounts on a locked-down host, and accept the
  wider blast radius (see the [threat model](key-custody-threat-model.md) §T2).

The `cmdkey` examples above store at user scope. For machine scope, use the
`/machine` flag or store via the Cryptography API with
`CryptProtectData(..., dwFlags=CRYPTPROTECT_LOCAL_MACHINE)`.

## 4. Reference them from suite.env

In the system `suite.env`
(`%ProgramData%\agent-suite\suite.env`):

```env
REGISTA_DSN=postgresql://regista_service@suite-db.example:5432/regista
REGISTA_DSN_PASSWORD=wincred:agent-suite/regista/dsn-password
REGISTA_KEY_PATH=wincred:agent-suite/regista/signing-key
REGISTA_REQUIRE_SSL=true
```

The `wincred:` prefix tells regista's loader to resolve the value from
Credential Manager at load time. The format is:

```
wincred:<credential-target-name>
```

The resolved value reaches the process that needs it and is **never written
back to the file**. Compare with [`suite.env.example`](../suite.env.example),
which carries placeholders only.

Per-principal key refs are resolved by dossier at sign time
(`wincred:agent-suite/principals/<principal_id>/key`) and are not stored in
the system `suite.env` — they are looked up by `principal_id` from the
authenticated session.

## 5. How resolution works

`regista.secrets.resolve("wincred:agent-suite/regista/signing-key")`:

1. Parses the `wincred:` scheme and extracts the credential target name.
2. Opens the Credential Manager store (user scope by default).
3. Reads the credential by target name and extracts the password field.
4. Returns the value to the caller; the caller uses it and clears it from
   memory after the operation (transient custody — see the
   [threat model](key-custody-threat-model.md) §T1).

Credential Manager does not provide a per-read audit log the way Vault or AKV
do. For detection, rely on Windows Security event logs (object access auditing)
and the event-log correlation described in the
[threat model](key-custody-threat-model.md) §T1 mitigation 2.

## 6. Verify

After configuring `suite.env`, confirm the backend is reachable and the refs
resolve before bootstrapping:

```bash
agent-suite bootstrap --dry-run
```

Step 0 of the bootstrap (secret backend reachable) probes the resolver. If a
`wincred:` ref cannot be resolved, the bootstrap aborts with a clear message
naming the failing ref — it does not proceed to provision against an
unresolvable secret. See the [bootstrap contract](bootstrap-contract.md) §1.
