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
| Python | 3.12, 3.13, or 3.14 |
| Postgres | 18+ (reachable from this host) — the same floor as [deployment-guide.md](deployment-guide.md) §2.1 |
| Postgres role | the DSN's role needs **CREATEROLE**: `regista provision` creates a per-project service role, and without it provisioning applies the schema migrations and then fails (WI-046) |
| pgvector | required in the agent-notes database (`CREATE EXTENSION vector`, superuser) — see [deployment-guide.md](deployment-guide.md) §2.2 |
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
REGISTA_DSN=postgresql://DB-SERVICE-ACCOUNT:PASSWORD@suite-db.example:5432/regista
REGISTA_KEY_PATH=/etc/agent-suite/keys.json
REGISTA_REQUIRE_SSL=true
CAIRN_CONTENT_KEY_REF=vault:kv/agent-suite/hosts/HOSTNAME/cairn/content_key
```

`REGISTA_KEY_PATH` is a path to a `keys.json` **file**, not a ref — a custodied
signing key is a `secret_ref` entry *inside* that file
([secrets-vault.md](secrets-vault.md) §4.1). There is no
`REGISTA_DSN_PASSWORD` variable in regista's config vocabulary; the DSN password
is part of `REGISTA_DSN`. A `vault:` ref is
`vault:<mount>/<path…>/<field>` — the field is the **last path segment**, never
a `#field` suffix. `agent-suite bootstrap` step 0 resolves every ref this file
names and aborts on the ones that do not.

See [`suite.env.example`](../suite.env.example) for the canonical placeholder
set, and the relevant [secrets runbook](secrets-vault.md) for the backend refs.

**On a Profile B host (one that runs dossier), the `PROFILE B` block in
`suite.env.example` is not optional.** dossier refuses to start without
`DOSSIER_SESSION_SECRET`, and eleven further variables decide whether the
deployment is safe — TLS and cookie posture, deny-by-default project access, the
identity binding that makes a human's acceptance attributable to that human, and
the `DOSSIER_HUMAN_SIGNING` posture that refuses a write which could only be
signed with the shared store key. The Linux qualification had to discover the
whole set by restarting dossier and reading each crash in turn, because the file
this section calls canonical named two of them (WI-047).

`DOSSIER_SESSION_SECRET` is the one variable that cannot live in this file:
dossier resolves no backend ref for it (dossier WI-036), so it must reach
dossier's own process as a literal. Inject it through the unit
(`EnvironmentFile=` pointing at a 0600 root-owned file, or `LoadCredential=`)
rather than putting it in the shared `suite.env`, which `bootstrap-contract.md`
§2 forbids.

What each component's config actually requires is declared in
`src/agent_suite/config_surface.py`, and `tests/test_config_surface.py` asserts
this file covers it — plus, wherever dossier is installed, that the declaration
still matches dossier's own config module.

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

On a host deployed from release wheels, add the release manifest so the doctor
verifies the artifacts instead of trusting their version strings — a wheel
install carries no VCS revision, so the manifest is the only thing it can be
checked against:

```bash
agent-suite doctor --exit-code --profile B \
  --release-manifest release-manifest.json \
  --artifact-wheels-dir ./wheels          # keep the release wheels: they unlock
                                          # the full manifest -> installed-files
                                          # hash chain
```

`--profile X` scopes *requirement strictness*: a required component that is
absent reds the verdict, while a non-required component the host simply does not
deploy does not. A component that is installed and broken still reds the verdict
wherever it sits — configure it or uninstall it. See the
[bootstrap contract](bootstrap-contract.md) §3.1-§3.2 and
[release manifest](release-manifest.md).

Note the difference between `ok` and `binds_release_identity` in the attestation
output: the second is only true when the tree holds no content outside the hash
chain (no bytecode caches, no unrecorded files, no unaccounted `.pth`). Routine
health does not require it; `--require-artifact-binding` does.

## 6. Verify the compatibility lock

```bash
agent-suite lock --check
```

This compares installed component versions against `SUITE.lock` and reports
drift. A suite release is a green lock — see the
[bootstrap contract](bootstrap-contract.md) §4.

## 7. Install the OS services and the scheduled operations

Two commands, both root, both idempotent, both re-runnable after an upgrade:

```bash
sudo agent-suite install-services      # the long-running faces (dossier)
sudo agent-suite schedule install      # the timers (backup, doctor-alert, chain-integrity)
```

Add `--dry-run` to either to see the plan and act on nothing. Both are real
preflights under `--dry-run`: they resolve the executables the units would run
and fail if one is missing, rather than printing a plan that cannot work.

`install-services` invokes each component's own `install-service` — the
components that run as OS services are declared once, in agent-suite's component
table, so you do not have to know which. Today that is **dossier**;
**agent-notes is a CLI, not a daemon**, and has no Tier 0–1 service (its
`agent-notes-bridge` / `-requeue` / `-trigger-loop` units are optional
harness-side helpers, installed from that repo's `deploy/` if you want them).

Verify:

```bash
systemctl status dossier
systemctl list-timers 'agent-suite-*'
```

### These units are generated, not shipped

The unit files are produced at install time from the location your component
CLIs are actually installed at, and both commands **verify** rather than report
success for having written a file:

- the resolved `ExecStart` is an absolute, existing, executable path;
- systemd's own parse of `ExecStart` names that executable;
- the unit is `active` (the service for `install-services`, the timer for
  `schedule install`).

Any of those failing is a non-zero exit and a named reason.

The reason units are generated rather than shipped inside the wheels is that
systemd resolves an unqualified `ExecStart` only against its own **fixed** search
path — `/usr/local/sbin`, `/usr/local/bin`, `/usr/sbin`, `/usr/bin`, … — and
never the invoking user's `PATH`. A single static file cannot be correct on both
a system-scoped install (§2) and a per-user one under `~/.local/bin`. Shipping
the text is what produced WI-045, where all three timers failed `203/EXEC` and
the weekly chain-integrity timer never fired on any host that installed it.

So: **install the component CLIs on a system PATH**, as §2 prescribes. If they
live somewhere non-standard, say so once:

```bash
sudo agent-suite install-services --bin-dir /opt/agent-suite/bin
sudo agent-suite schedule install  --bin-dir /opt/agent-suite/bin
```

If a CLI cannot be resolved to an absolute path, installation **refuses and
names it** rather than writing a unit that would fail at first start. Note that
`sudo` replaces `PATH` with `secure_path`, so a CLI installed only under a
user's `~/.local/bin` is invisible to the install — and would be invisible to
systemd too. That refusal is the correct outcome, not an obstacle to work around:
running a root unit out of a user-writable directory is a privilege-escalation
shape.

Reference renderings of every unit, against the `/usr/local/bin` prefix, are in
agent-suite's `deploy/systemd/` and dossier's `deploy/systemd/` for review or
manual install.

## 8. Next steps

- Onboard additional humans: see [multi-user-onboarding.md](multi-user-onboarding.md).
- Deploy Tier 2 (capabilities, signaling): `agent-suite bootstrap --tier 0-2`.
- Key rotation and leaver process: see [key-operations.md](key-operations.md).
