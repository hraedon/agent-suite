# Operating the suite — upgrades, rollback, scheduled protection, alerting

**Status:** Runbook 2026-07-22 (Plan 005, runtime-provenance revision)
**Purpose:** How to operate the suite after deployment: advance the
compatibility lock, roll back, run scheduled backups with verify-restore,
and receive alerts when the suite is unhealthy. This is the difference
between "deployed once" and "operated."

See the [bootstrap contract](bootstrap-contract.md) for the install order,
lock format, and doctor umbrella that this runbook builds on.

---

## 1. Upgrades (WI-1.1)

The command has two deliberately separate modes. If the runtime differs from
the current lock, it performs an exact **reconciliation** to that lock and does
not rewrite it. Only a runtime that already matches may perform an **advancement**
to a new lock, gated by the interop proof and recorded as evidence.

### 1.1 Check for available advancements (read-only)

```bash
agent-suite upgrade --check
```

This reports, per component, whether a newer version is available — without
acting. Use this before planning an upgrade window.

To check one component:

```bash
agent-suite upgrade --check --component regista
```

### 1.2 Dry-run the upgrade plan

```bash
agent-suite upgrade --dry-run
```

The dry run reads the lock, detects the installation that owns each visible
CLI, and prints exact versioned commands without acting. Confirm the package,
interpreter/manager, target version, and any service restart before running.

### 1.3 Run the upgrade

```bash
agent-suite upgrade
```

This:

1. Loads the current `SUITE.lock` and probes the interpreter and distribution
   that own each selected visible CLI.
2. Refuses editable, system, absent, ambiguous, and unknown installations
   before any mutation. Managed user-pip, venv, pipx, and uv-tool installs are
   supported.
3. If any selected version drifts from the lock, installs only those exact
   locked versions. It does not mix repairs with newer-version advancement.
4. Otherwise resolves exact advancement targets and applies them through each
   installation's detected manager.
5. Revalidates provenance immediately before mutation, verifies every installed
   version afterward, and restarts a declared service where applicable.
6. Runs the interop gate against the existing lock for repair, or a temporary
   candidate lock for advancement.
7. On failure, rolls back only the mutation journal, in reverse order, to the
   versions captured before the transaction and verifies the restoration.
8. A successful repair leaves `SUITE.lock` byte-for-byte unchanged. A successful
   advancement writes the candidate lock.

To upgrade one component:

```bash
agent-suite upgrade --component regista
```

Component filtering is the normal way to reconcile a managed wheel while other
suite faces are intentionally installed editable for development. A whole-suite
operation fails closed if any component it would mutate is not manager-owned.

### 1.4 The interop gate

The **local** interop gate is `doctor` (health) + `lock --check` (version
match). The **authoritative** interop proof is the CI job
([bootstrap-contract.md §5](bootstrap-contract.md#5-the-interop-test-what-makes-a-lock-green))
that drives one work-item across both faces to `done`. The lock commit
message should reference the CI interop run as evidence.

### 1.5 Commit the lock diff

After a green upgrade, commit the `SUITE.lock` diff with a message that
references the interop evidence:

```bash
git add SUITE.lock
git commit -m "upgrade: regista 0.4.0 -> 0.5.0 (interop green, CI run #123)"
```

---

## 2. Rollback (WI-1.2)

Rollback restores a prior committed lock — it is **not** an undo of data
changes.

### 2.1 Roll back to a prior lock

```bash
agent-suite upgrade --to HEAD~1
```

This loads `SUITE.lock` from the given git ref, restores each component to
the version pinned in that lock, and writes the lock file.

### 2.2 Migration-boundary refusal

Rollback **refuses** to cross a schema-migration boundary. If the target
lock's `schema_version` differs from the currently-deployed schema version,
the command refuses rather than half-applies:

```
refused: schema migration boundary — current schema_version is 38,
target lock pins 37. Schema migrations are one-way; rolling back would
leave the database in a state the old code cannot read. Restore from a
backup taken before the migration instead.
```

### 2.3 What rollback cannot undo

| What | Why | Mitigation |
|------|-----|------------|
| **Schema migrations** | A forward schema migration is irreversible | Refused by this command; restore from backup |
| **Workflow versions** | Old code may not understand events created under a new workflow | Warning only; regista's compatibility rules decide |
| **Data created after the target lock** | Events, work items, key registrations remain in the store | Not removed by code-level rollback; clean manually if needed |

---

## 3. Scheduled backup + verify-restore (WI-2.1)

Backups and verify-restore run on a cadence via the **OS scheduler**
(systemd timers on Linux, Windows Scheduled Tasks on Windows) — not a
daemon.

### 3.1 Install the schedules

```bash
sudo agent-suite schedule install
```

This writes systemd timer/unit files (or Windows PowerShell registration
scripts), enables/registers them, and then **verifies** each one. On Linux that
means the resolved `ExecStart` is an absolute existing executable, systemd's
own parse of `ExecStart` names it, and the timer is `active`. On Windows the
generated script registers the task and reads it back to verify the action,
arguments, start time, and daily/weekly/hourly trigger (including hourly
repetition). A schedule it cannot verify is reported
`failed` with the reason, and the command exits non-zero — writing a file is not
the success condition. `ExecStart` is resolved to an absolute path at install
time; see [install-linux.md §7](install-linux.md) for why, and for `--bin-dir`
when the CLIs are not on a system PATH. Each generated unit also pins an
explicit `PATH` of **only** the standard system directories: systemd runs the
unit as root with a stripped `PATH`, and without this the doctor that
`alert-check` shells out to would resolve different component binaries than the
operator sees — a different estate (WI-038). The pin is the system directories
only (not the directory the installer resolved `ExecStart` from) so a root-run
unit never searches a foreign or user-writable bin dir; an install that resolves
the CLI from a non-system bin dir is refused instead. The pin renders before
`EnvironmentFile`, so `suite.env` can still override it.

Before installing, set the scheduled-protection values in the system
`suite.env` (the Windows file is `%ProgramData%\agent-suite\suite.env`):

```env
AGENT_SUITE_BACKUP_DIR=/var/lib/agent-suite/backups
AGENT_SUITE_VERIFY_RESTORE_DSN=postgresql://DB-SERVICE-ACCOUNT:PASSWORD@suite-db.example:5432/regista_verify
```

On Windows, use a Windows backup path such as
`C:\ProgramData\agent-suite\backups`. `AGENT_SUITE_VERIFY_RESTORE_DSN` is
required by the weekly job and must identify a dedicated scratch database; it
must not be omitted and must not equal `REGISTA_DSN`. The weekly job never falls
back to the production DSN. The scheduled commands carry only these environment
variable names, not their values.

`schedule install` performs this configuration preflight in both normal and
`--dry-run` modes. If either required variable is absent, or the verification
DSN resolves to the same PostgreSQL database as `REGISTA_DSN`, the affected
schedules are reported `failed` and no schedule files/tasks are installed.

The schedules are:

| Schedule | Cadence | Command | Purpose |
|----------|---------|---------|---------|
| `agent-suite-backup` | Daily | `agent-suite backup --dir-env AGENT_SUITE_BACKUP_DIR` | Nightly `pg_dump` and manifest |
| `agent-suite-restore-verify` | Weekly | `agent-suite restore --dir-env AGENT_SUITE_BACKUP_DIR --dsn-env AGENT_SUITE_VERIFY_RESTORE_DSN` | Restore the latest dump into scratch, then run `verify-restore` |
| `agent-suite-doctor-alert` | Hourly | `agent-suite alert-check` | Periodic doctor + alert routing |
| `agent-suite-chain-integrity` | Weekly | `cairn integrity` | Full chain replay; records the verdict doctor reports (cairn WI-030) |

The weekly restore is scheduled for 04:00 (after the daily 00:00/02:00 backup
window on Linux/Windows respectively), so it does not race the dump that
produces the shared latest-dump file. The weekly *day* differs by platform:
systemd weekly units render `Mon *-*-* HH:MM:SS`, while Windows weekly
triggers register `-DaysOfWeek Sunday` (the same pattern the chain-integrity
schedule has always used). Both satisfy the weekly cadence; treat the day as
platform-defined rather than aligned.

The nightly source-side verification that `agent-suite backup` performs is a
health check of the live store, not proof that the dump can be restored. That
proof comes from the distinct weekly `restore` schedule: `pg_restore` loads the
dump into the configured scratch database and the existing restore pipeline then
calls `verify-restore` against that scratch DSN.

Run `sudo -E cairn integrity` once at install time (as root, with
`CAIRN_INTEGRITY_DIR` in scope from `/etc/agent-suite/suite.env` — a
non-root run records into the wrong per-user location): the alerting loop
(failed replay → doctor escalation → `alert-check`) closes only once a
first verdict or attempt marker exists, and the scheduled runs keep it
fresh from then on.
Keep `CAIRN_INTEGRITY_DIR` set in `suite.env` (see `suite.env.example`) so
the root-run timer and human-run doctors agree on the verdict location.

### 3.2 List schedules

```bash
agent-suite schedule list
```

### 3.3 Remove schedules

```bash
agent-suite schedule remove
```

### 3.4 Dry-run

```bash
agent-suite schedule install --dry-run
```

Prints the files that would be written without acting. It still resolves the
executables and fails if one is missing, so a dry run is a genuine preflight
rather than a preview.

### 3.5 Reference unit files

Shipped reference copies are in `deploy/systemd/` and `deploy/windows/`, rendered
against the documented `/usr/local/bin` install prefix — one of the directories
on systemd's own fixed `ExecStart` search path, so a copy installed verbatim on a
system-scoped host works. `schedule install` generates the same files with the
prefix it actually resolved on this host substituted in, which is the only form
that can be correct under both a system-scoped and a per-user layout. The
reference copies are for manual installation or review; a test keeps them
byte-identical to the generator.

### 3.6 Backup retention

The nightly backup writes exactly one dump at a fixed path —
`AGENT_SUITE_BACKUP_DIR/database.dump` plus its manifest — and **overwrites it
on every run**. There are no older copies in that directory to retain: history
exists only if external tooling (`restic`, filesystem snapshots, the backup
tool of choice) captures the file before the next nightly overwrite. Put the
directory under such tooling (the DR runbook recommends 30 days for daily full
backups); the weekly restore-verify job always reads the current
`database.dump`, so it proves the latest dump, not the retained history. See
the [DR runbook](disaster-recovery.md) §2.1 for the recommended cadence and
retention table.

---

## 4. Alerting (WI-3.1)

A scheduled `doctor` run checks suite health on a cadence. When the result
transitions to red/degraded (or recovers to green), the result is posted to
agent-wake's ingress for human delivery.

### 4.1 Configuration

Set the agent-wake ingress URL in `suite.env`:

```env
AGENT_WAKE_INGRESS_URL=http://wake.example/ingress
```

Or pass it explicitly:

```bash
agent-suite alert-check --wake-url http://wake.example/ingress
```

### 4.2 Debounce

Alerts are **state-change emissions**, not every-run spam:
- A stable red suite emits **one** alert on the transition to red; subsequent
  red runs are silent.
- When the suite recovers to green, **one** recovery notice is emitted.
- A stable green suite produces nothing.

State is stored in `/var/lib/agent-suite/last-doctor-state.json` (no daemon
— the state lives on disk between scheduled runs).

### 4.3 Alert payload

The alert posted to agent-wake contains:

```json
{
  "source": "agent-suite-doctor",
  "alert_kind": "red",
  "timestamp": "2026-07-09T12:00:00+0000",
  "suite_ok": false,
  "summary": "failed: regista; lock drift: 2 drift(s) detected"
}
```

agent-wake Plan 005 WI-1.4 owns the delivery leg (routing to a human via
the configured channel). This plan owns the scheduling and emitting.

---

## 5. Key rotation and store growth watch (WI-2.2)

`doctor` includes two suite-level checks that run by default:

### 5.1 Key rotation age

Checks each signing key's age against the rotation-cadence policy (default
90 days, per [key-operations.md](key-operations.md) §2):

| State | `checked` | Meaning | Action |
|-------|-----------|---------|--------|
| **ok** | true | Every active key is < 80% of cadence | None |
| **approaching** | true | A key is at 80-100% of cadence | Schedule rotation |
| **expired** | true | A key is past cadence | **Rotate immediately** — doctor fails |
| **unsupported** | false | regista's *parser* has no `principal list` verb | Feature request in regista |
| **unreachable** | false | regista absent, or the command ran and failed | **Read the detail** — this is usually a config gap on this host, not a regista gap |
| **error** | false | The registry read succeeded but could not be parsed | Report the output shape |

A key past its rotation cadence makes `suite_ok` false.

**Read `checked`, not just `ok` (WI-049).** Every non-`ok` state above leaves the
key ages unknown, and `ok` stays true because "this host cannot run the key-age
check" is not the same failure as "this host has an expired key". `checked: false`
is what distinguishes them, and the text report prefixes such a line with
`not checked —`. A zero next to no evidence of counting is the defect Lane G is
removing from regista's `principal_binding_failures`; the same rule applies here.

**`unsupported` requires evidence about regista, not a word in an error
message.** The Linux qualification host printed
`unsupported: regista does not support 'principal list'` on every doctor run
while the command worked from the same shell — the probe was passing regista's
global `--json` *after* the subcommand (argparse rejects that), had no project or
key path, and then matched `"unrecognized"` in argparse's complaint. The check now
reports `unsupported` only when regista's parser names the subcommand itself as
an invalid choice. Anything else is `unreachable` with regista's real diagnostic
and the remedy.

The check needs `REGISTA_PROJECT` and `REGISTA_KEY_PATH` in `suite.env`:
`regista principal list` resolves neither from a project-less invocation, so
without them it reports `unreachable`, not a clean bill of health.

### 5.2 Store growth telemetry

Surfaces per-project event counts and byte sizes (via `regista stats`) so the
regista Plan 028 archival decision is made from data. This check is
informational — it does not gate `suite_ok`.

`regista stats` does not exist yet, so this check reports `unsupported` on every
host today — a named state, not a crash, and now reached by the same
evidence-based detection as §5.1 rather than by scanning the message.

---

## 5.3 Onboarding a project from a signed spec (WI-053)

`agent-suite onboard <slug> --spec spec.yaml` signs the spec into regista as the
project's **event-zero**, so the audit chain runs spec → work → review → done.

Two inputs are **required**, because `regista spec sign` requires them:

| Input | Where it comes from | If missing |
|-------|--------------------|------------|
| `schema_version` | a top-level field in `spec.yaml` | the step **refuses** and names the field; the project is still provisioned, just spec-unanchored |
| `spec.md` | a sibling of `spec.yaml` (the human-readable companion) | the step **refuses** and names the file — regista rejects an empty spec.md hash, so this document is not optional |

Neither is guessed. Signing a `schema_version` the spec does not declare, or a
spec.md hash for a file that does not exist, would put a false claim in the chain.

**Re-running.** regista exposes no idempotent "already signed" signal, and
`sign_spec` mints a random spec entity id when none is given — so a naive re-run
would append a *second, unrelated* event-zero. The suite therefore derives the
spec entity id from the project slug and reads that entity's events first:

- **unchanged spec** → `already_done`. Nothing is written.
- **amended spec** (different content or `schema_version`) → a further
  `spec_signed` event on the *same* entity. The chain records both versions in
  order, which is what an amended founding spec should look like.
- **the pre-check itself fails** → the step fails. It never assumes "unsigned",
  because that assumption performs a write.

---

## 6. Cross-references

- [Bootstrap contract](bootstrap-contract.md) — the install order, lock
  format, and doctor umbrella this runbook operates
- [Disaster recovery](disaster-recovery.md) — backup/restore procedures
- [Key operations](key-operations.md) — key rotation policy
- [Install guides](install-linux.md) — platform-specific setup
