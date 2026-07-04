# Linux install guide

How to stand up the agent-suite Tier 0–1 core (secret backend, Postgres,
regista, dossier, agent-notes, cairn) on a Linux host. The Tier 2 components
(acb, agent-wake) are optional — see the [bootstrap contract](bootstrap-contract.md)
§1 steps 5–6.

After this guide, an operator will have a running suite with a green
`agent-suite doctor`.

---

## 1. Prerequisites

| Dependency | Requirement |
|------------|------------|
| Python | 3.12 or 3.13 |
| Postgres | 14+ (reachable from this host) |
| Secret backend | Vault, AKV, or Windows Credential Manager (this host is Linux, so Vault or AKV — see [secrets-vault.md](secrets-vault.md) or [secrets-akv.md](secrets-akv.md)) |
| OS | systemd-based Linux (Ubuntu 22.04+, RHEL 9+) |
| Permissions | root (or sudo) for system-level config and service install |

## 2. Install agent-suite

```bash
pipx install agent-suite
```

Or, if you prefer a virtualenv:

```bash
python3.12 -m venv /opt/agent-suite
/opt/agent-suite/bin/pip install agent-suite
```

Install the secret-backend extra matching your chosen backend:

```bash
pipx inject agent-suite agent-suite[vault]    # for Vault
pipx inject agent-suite agent-suite[azure]    # for AKV
```

Verify the CLI is on the path:

```bash
agent-suite --help
```

## 3. Configure suite.env

Create the system-level config at `/etc/agent-suite/suite.env`:

```bash
sudo mkdir -p /etc/agent-suite
sudo cp suite.env.example /etc/agent-suite/suite.env
sudo $EDITOR /etc/agent-suite/suite.env
```

Fill in the placeholders. Secrets are backend refs, never literals:

```env
REGISTA_DSN=postgresql://regista_app@suite-db.example:5432/regista
REGISTA_DSN_PASSWORD=vault:secret/agent-suite/regista#dsn_password
REGISTA_KEY_PATH=vault:secret/agent-suite/regista#signing_key
REGISTA_REQUIRE_SSL=true
```

See [`suite.env.example`](../suite.env.example) for the canonical placeholder
set, and the relevant [secrets runbook](secrets-vault.md) for the backend refs.

## 4. Bootstrap

Run the bootstrap in dry-run first to confirm the plan:

```bash
agent-suite bootstrap --dry-run --tier 0-1
```

This prints the ordered steps (see the [bootstrap contract](bootstrap-contract.md)
§1) without acting. Confirm the secret backend and Postgres are reachable, then
run for real:

```bash
agent-suite bootstrap --tier 0-1
```

The bootstrap is idempotent — re-running it changes nothing that is already
done. A step that would clobber an existing irreversible artifact (a signing
key, a populated schema) **refuses and reports** rather than overwrites.

## 5. Verify with doctor

```bash
agent-suite doctor
```

For machine-readable output (monitoring, CI):

```bash
agent-suite doctor --json
agent-suite doctor --exit-code   # exits 1 if unhealthy
```

A component that isn't installed is reported as `absent` (not a failure —
Tier 2 may not be deployed). A component that's installed but unreachable is a
failure. See the [bootstrap contract](bootstrap-contract.md) §3.

## 6. Verify the compatibility lock

```bash
agent-suite lock --check
```

This compares installed component versions against `SUITE.lock` and reports
drift. A suite release is a green lock — see the
[bootstrap contract](bootstrap-contract.md) §4.

## 7. Optional: systemd services for the faces

dossier and agent-notes run as OS services. The bootstrap installs them; to
manage them directly:

```bash
sudo systemctl enable --now dossier
sudo systemctl enable --now agent-notes
```

The service units are installed by each component's own `install-harness`
(see the [install-harness contract](install-harness-contract.md)); agent-suite
calls them in order but does not define the unit files itself.

## 8. Next steps

- Onboard additional humans: see [multi-user-onboarding.md](multi-user-onboarding.md).
- Deploy Tier 2 (capabilities, signaling): `agent-suite bootstrap --tier 0-2`.
- Key rotation and leaver process: see [key-operations.md](key-operations.md).
