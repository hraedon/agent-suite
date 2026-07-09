# Operating the suite — upgrades, rollback, scheduled protection, alerting

**Status:** Runbook 2026-07-09 (Plan 005)
**Purpose:** How to operate the suite after deployment: advance the
compatibility lock, roll back, run scheduled backups with verify-restore,
and receive alerts when the suite is unhealthy. This is the difference
between "deployed once" and "operated."

See the [bootstrap contract](bootstrap-contract.md) for the install order,
lock format, and doctor umbrella that this runbook builds on.

---

## 1. Upgrades (WI-1.1)

An upgrade is a **lock transition, and it's evidence.** The old lock
transitions to a new lock, gated by the interop proof, recorded like any
other auditable change.

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

Prints the planned actions (pipx upgrade, docker pull, service restart)
without acting. Confirm the plan before running for real.

### 1.3 Run the upgrade

```bash
agent-suite upgrade
```

This:
1. Loads the current `SUITE.lock` (the source of truth for what's deployed).
2. Applies per-component upgrades (pipx upgrade / docker pull).
3. Restarts any OS service (dossier, agent-notes) after its component is upgraded.
4. Runs the **interop gate** — `doctor` (aggregated health) + `lock --check`
   (version match). A green local gate is necessary but not sufficient.
5. On green: regenerates `SUITE.lock` from the new versions and writes it.
6. On red: **rolls back** every upgraded component to its previously-pinned
   version and leaves the lock untouched.

To upgrade one component:

```bash
agent-suite upgrade --component regista
```

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
agent-suite schedule install
```

This writes systemd timer/unit files (or Windows PowerShell scripts) and
enables them. The schedules are:

| Schedule | Cadence | Command | Purpose |
|----------|---------|---------|---------|
| `agent-suite-backup` | Daily | `agent-suite backup --verify-restore` | Nightly pg_dump + weekly verify-restore |
| `agent-suite-doctor-alert` | Hourly | `agent-suite alert-check` | Periodic doctor + alert routing |

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

Prints the files that would be written without acting.

### 3.5 Reference unit files

Shipped reference copies are in `deploy/systemd/` and `deploy/windows/`.
The `schedule install` command generates identical files at the target
paths; the reference copies are for manual installation or review.

### 3.6 Backup retention

Backup retention is configured in the operator's environment (e.g.,
`pg_dump` retention policy, `restic` retention, or the backup tool of
choice). See the [DR runbook](disaster-recovery.md) §2.1 for the
recommended cadence and retention table.

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

| State | Meaning | Action |
|-------|---------|--------|
| **ok** | Key age < 80% of cadence | None |
| **approaching** | Key age 80-100% of cadence | Schedule rotation |
| **expired** | Key age > cadence | **Rotate immediately** — doctor fails |
| **unsupported** | regista doesn't expose `principal list` | Feature request in regista |
| **unreachable** | regista not installed or command failed | Check regista health |

A key past its rotation cadence makes `suite_ok` false.

### 5.2 Store growth telemetry

Surfaces per-project event counts and byte sizes (via `regista stats --json`)
so the regista Plan 028 archival decision is made from data. This check is
informational — it does not gate `suite_ok`.

If regista doesn't support `stats`, the check reports `unsupported` — a
named state, not a crash.

---

## 6. Cross-references

- [Bootstrap contract](bootstrap-contract.md) — the install order, lock
  format, and doctor umbrella this runbook operates
- [Disaster recovery](disaster-recovery.md) — backup/restore procedures
- [Key operations](key-operations.md) — key rotation policy
- [Install guides](install-linux.md) — platform-specific setup
