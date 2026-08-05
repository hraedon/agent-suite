# Windows DPAPI secret backend

How to store the suite's secrets — the DSN password and per-actor Ed25519
signing keys — in the Windows Data Protection API (DPAPI) and reference them
from `suite.env` via the `windows:` prefix. regista's secret resolver
(`regista.secrets.resolve`, Plan 025 WI-1.2) reads `windows:` refs at load
time; the suite never holds a literal secret in a committed file.

The `windows:` scheme takes a **base64 DPAPI blob** — the ref *is* the
protected secret, not the name of a Credential Manager entry. regista
base64-decodes the blob and DPAPI-unprotects it (machine scope). This is the
shape the resolver actually accepts; the old `wincred:` prefix and the
credential-target form several docs printed are not recognised and resolve as
literal strings (WI-069).

This backend is for single-machine Windows deployments where the secret
perimeter is the Windows account/machine boundary. For multi-host deployments,
use [Vault](secrets-vault.md) or [AKV](secrets-akv.md) — DPAPI secrets do not
travel across machines.

See the [bootstrap contract](bootstrap-contract.md) for where secret resolution
sits in the install order (step 0), and the [key-custody threat model](key-custody-threat-model.md)
for why the signing keys live in the backend, not on disk.

---

## 1. Prerequisites

- Windows 11, Server 2022, or Server 2025.
- `pywin32` installed: `pip install agent-suite[windows]` (the `windows` extra
  pulls `pywin32`; the core stays stdlib-only — see `pyproject.toml`).
- The suite process running under the Windows account that owns the DPAPI keys
  (DPAPI keys are scoped to the user or machine — see §3).

## 2. Store the secrets

Protect each secret with DPAPI to produce a base64 blob; that blob is the
`windows:` reference. Use PowerShell's `ProtectedData` class (machine scope):

### DSN password

```powershell
$b = [Text.Encoding]::UTF8.GetBytes("<the DB-SERVICE-ACCOUNT role password>")
$e = [Security.Cryptography.ProtectedData]::Protect($b, $null, 'LocalMachine')
[Convert]::ToBase64String($e)   # <-- this base64 string is the windows: ref
```

### Regista system signing key

```powershell
$b = [Text.Encoding]::UTF8.GetBytes("<Ed25519 private key, base64>")
$e = [Security.Cryptography.ProtectedData]::Protect($b, $null, 'LocalMachine')
[Convert]::ToBase64String($e)   # <-- this base64 string is the windows: ref
```

### Per-principal signing keys

Each human and agent principal gets its own DPAPI-protected blob, generated
the same way and distinct per `principal_id`. `<principal_id>` is the stable
identifier regista assigns at enrollment (Plan 026 WI-3.3) — not a display
name.

## 3. Protection scope

DPAPI protects to one of two scopes:

- **User scope** (`CurrentUser`): only the Windows account that protected the
  data can unprotect it. Use this when the suite runs as a dedicated service
  account.
- **Machine scope** (`LocalMachine`, used above): any process on the machine
  can unprotect the blob. Use this only for shared service accounts on a
  locked-down host, and accept the wider blast radius (see the
  [threat model](key-custody-threat-model.md) §T2).

regista's `windows:` provider unprotects in machine scope (`LocalMachine`);
protect the blobs with `LocalMachine` so the suite process can read them.

## 4. Reference them from suite.env

In the system `suite.env`
(`%ProgramData%\agent-suite\suite.env`):

```env
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT@suite-db.example:5432/regista
REGISTA_KEY_PATH=C:\ProgramData\agent-suite\keys.json
REGISTA_REQUIRE_SSL=true
```

The `windows:` prefix tells regista's loader to base64-decode the blob and
DPAPI-unprotect it at load time. The format is:

```
windows:<base64-dpapi-blob>
```

The blob is the protected secret itself — there is no separate credential
target to look up. The resolved value reaches the process that needs it and is
**never written back to the file**. Compare with [`suite.env.example`](../suite.env.example),
which carries placeholders only.

There is no `REGISTA_DSN_PASSWORD` variable in regista's config vocabulary —
the DSN password is part of `REGISTA_DSN` (see the [bootstrap contract](bootstrap-contract.md)).
`REGISTA_KEY_PATH` is a path to a `keys.json` **file**, not a ref; custodied
signing keys are per-key `secret_ref` entries *inside* that file (see
[secrets-vault.md](secrets-vault.md) §4.1), each of which may carry a
`windows:<base64-dpapi-blob>` ref.

Per-principal key refs are resolved by dossier at sign time and are not stored
in the system `suite.env` — they are looked up by `principal_id` from the
authenticated session.

## 5. How resolution works

`regista.secrets.resolve("windows:AQAAANCMnd8B...")`:

1. Parses the `windows:` scheme; the rest is the base64 DPAPI blob.
2. Base64-decodes the blob.
3. DPAPI-unprotects it (machine scope) to recover the plaintext.
4. Returns the value to the caller; the caller uses it and clears it from
   memory after the operation (transient custody — see the
   [threat model](key-custody-threat-model.md) §T1).

DPAPI does not provide a per-read audit log the way Vault or AKV do. For
detection, rely on Windows Security event logs (object access auditing) and
the event-log correlation described in the
[threat model](key-custody-threat-model.md) §T1 mitigation 2.

## 6. Verify

After configuring `suite.env`, confirm the backend is reachable and the refs
resolve before bootstrapping:

```bash
agent-suite bootstrap --dry-run
```

Step 0 of the bootstrap (secret backend reachable) probes the resolver. If a
`windows:` ref cannot be resolved, the bootstrap aborts with a clear message
naming the failing ref — it does not proceed to provision against an
unresolvable secret. See the [bootstrap contract](bootstrap-contract.md) §1.
