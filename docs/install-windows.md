# Windows install guide

How to stand up the agent-suite Tier 0–1 core (secret backend, Postgres,
regista, dossier, agent-notes, cairn) on a Windows host. The Tier 2 components
(acb, agent-wake) are optional — see the [bootstrap contract](bootstrap-contract.md)
§1 steps 5–6.

After this guide, an operator will have a running suite with a green
`agent-suite doctor`.

---

## 1. Prerequisites

| Dependency | Requirement |
|------------|------------|
| Python | 3.12 or 3.13 (from python.org or the Microsoft Store) |
| Postgres | 14+ (reachable from this host) |
| Secret backend | Credential Manager (see [secrets-windows.md](secrets-windows.md)), Vault, or AKV |
| OS | Windows 10/11 or Windows Server 2019+ |
| Permissions | Administrator for system-level config and service install |

> **Security — run inside a dedicated VM.** On native Windows, Claude Code's
> harness-level sandboxing is **not available** — the agent runs with the
> operator's full Windows access. The isolation boundary is the VM/host, not
> the process. Run Claude Code on Windows inside a **dedicated VM** that has
> no ambient access to anything the agent shouldn't reach. cairn *records*
> what the agent did; it does not *constrain* it. See
> [bootstrap-contract.md §7](bootstrap-contract.md#7-substrate-posture-plan-003-wi-0)
> for the full posture decision.

## 2. Install agent-suite

```powershell
pip install agent-suite
```

Install the secret-backend extra matching your chosen backend:

```powershell
pip install agent-suite[windows]   # for Credential Manager / DPAPI
pip install agent-suite[vault]     # for Vault
pip install agent-suite[azure]     # for AKV
```

Verify the CLI is on the path:

```powershell
agent-suite --help
```

## 3. Configure suite.env

Create the system-level config at
`%ProgramData%\agent-suite\suite.env`:

```powershell
New-Item -ItemType Directory -Force -Path "$env:ProgramData\agent-suite"
Copy-Item suite.env.example "$env:ProgramData\agent-suite\suite.env"
notepad "$env:ProgramData\agent-suite\suite.env"
```

Fill in the placeholders. Secrets are backend refs, never literals:

```env
REGISTA_DSN=postgresql://regista_service@suite-db.example:5432/regista
REGISTA_DSN_PASSWORD=wincred:agent-suite/regista/dsn-password
REGISTA_KEY_PATH=wincred:agent-suite/regista/signing-key
REGISTA_REQUIRE_SSL=true
```

See [`suite.env.example`](../suite.env.example) for the canonical placeholder
set, and the relevant [secrets runbook](secrets-windows.md) for the backend
refs.

## 4. Bootstrap

Run the bootstrap in dry-run first to confirm the plan:

```powershell
agent-suite bootstrap --dry-run --tier 0-1
```

This prints the ordered steps (see the [bootstrap contract](bootstrap-contract.md)
§1) without acting. Confirm the secret backend and Postgres are reachable, then
run for real:

```powershell
agent-suite bootstrap --tier 0-1
```

The bootstrap is idempotent — re-running it changes nothing that is already
done. A step that would clobber an existing irreversible artifact (a signing
key, a populated schema) **refuses and reports** rather than overwrites.

## 5. Verify with doctor

```powershell
agent-suite doctor
```

For machine-readable output (monitoring, CI):

```powershell
agent-suite doctor --json
agent-suite doctor --exit-code   # exits 1 if unhealthy
```

A component that isn't installed is reported as `absent` (not a failure —
Tier 2 may not be deployed). A component that's installed but unreachable is a
failure. See the [bootstrap contract](bootstrap-contract.md) §3.

## 6. Verify the compatibility lock

```powershell
agent-suite lock --check
```

This compares installed component versions against `SUITE.lock` and reports
drift. A suite release is a green lock — see the
[bootstrap contract](bootstrap-contract.md) §4.

## 7. Optional: Windows Services for the faces

dossier and agent-notes run as Windows Services. The bootstrap installs them;
to manage them directly:

```powershell
Start-Service dossier
Start-Service agent-notes
```

The service definitions are installed by each component's own
`install-harness` (see the [install-harness contract](install-harness-contract.md));
agent-suite calls them in order but does not define the service configs itself.

## 8. Next steps

- Onboard additional humans: see [multi-user-onboarding.md](multi-user-onboarding.md).
- Deploy Tier 2 (capabilities, signaling): `agent-suite bootstrap --tier 0-2`.
- Key rotation and leaver process: see [key-operations.md](key-operations.md).
