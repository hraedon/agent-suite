# Disaster recovery runbook — backup and restore the Postgres store

**Status:** Runbook 2026-07-04 (Plan 001 WI-4.1)
**Purpose:** Enable an operator to back up the suite's single Postgres store
and restore it — then prove the restore is cryptographically intact with
`agent-suite verify-restore` (Plan 001 WI-4.2). The entire suite runs on one
Postgres; losing it, or restoring a tampered copy, is the first-order
regulated risk.

---

## 1. What to back up

The suite's state lives entirely in one Postgres cluster. A complete backup
includes:

| What | Why | Owned by |
|------|-----|----------|
| **All project schemas** | Every project's event log, work items, and audit chain (regista Plan 025/026) | This runbook |
| **The key registry** (regista Plan 026) | The public-key registry that makes signature verification possible — without it, `verify-restore` cannot run | This runbook (part of the Postgres store) |
| **Archive bundles** (regista Plan 028) | Sealed event-chain archives for long-term retention | This runbook (file-level backup, §2.3) |
| **Private signing keys** | Held in the secret backend (Vault / AKV / DPAPI), not in Postgres | The secret backend's own DR |

> **A restore missing the key registry or archive bundles is incomplete.**
> The key registry is a schema inside the same Postgres cluster — a
> `pg_dump` of the `regista` database or a `pg_basebackup` of the cluster
> includes it automatically. Archive bundles are files on disk and must be
> backed up separately (§2.3). Private keys never live in Postgres; they are
> the secret backend's responsibility (see the per-backend runbooks:
> [`secrets-vault.md`](secrets-vault.md),
> [`secrets-akv.md`](secrets-akv.md),
> [`secrets-windows.md`](secrets-windows.md)).

---

## 2. Backup

### 2.1 Cadence

| Type | Frequency | Retention | Purpose |
|------|-----------|-----------|---------|
| Full base backup (`pg_basebackup` or `pg_dump`) | Daily | 30 days | Complete point-in-time restore |
| WAL archiving | Continuous (`archive_timeout=5min`) | 7 days | Point-in-time recovery (PITR) between full backups |
| Archive bundle backup | On creation | Per retention policy | Long-term sealed-chain retention |

> Adjust cadence to your regulatory retention requirements. The minimum is a
> daily full backup; WAL archiving narrows the recovery point objective
> (RPO) from 24h to minutes.

### 2.2 Postgres store backup

#### Full backup (logical — `pg_dump`)

```bash
pg_dump --format=custom \
  --host=suite-db.example \
  --username=regista_service \
  --file=/var/backups/agent-suite/suite-$(date +%Y%m%d).dump \
  regista
```

This produces a single custom-format dump containing all schemas in the
`regista` database, including every project schema and the key registry.

#### Full backup (physical — `pg_basebackup`, for PITR)

```bash
pg_basebackup \
  --host=suite-db.example \
  --username=replication \
  --pgdata=/var/backups/agent-suite/base \
  --format=tar \
  --gzip \
  --wal-method=stream \
  --write-recovery-conf
```

A physical base backup combined with archived WALs enables point-in-time
recovery. Configure WAL archiving in `postgresql.conf`:

```ini
archive_mode = on
archive_command = 'cp %p /var/backups/agent-suite/wal/%f'
archive_timeout = '5min'
```

### 2.3 Archive bundle backup

Archive bundles (regista Plan 028) are sealed files on disk. Back them up
with the file-level backup tool of your choice (rsync, restic, etc.):

```bash
rsync -av /var/lib/agent-suite/archives/ \
  backup-host:/backups/agent-suite/archives/
```

### 2.4 Secret backend backup

Private signing keys live in the secret backend, not in Postgres. Each
backend has its own DR procedure — see the per-backend runbooks. The suite
does not back up or restore private keys; it depends on the backend's own
resilience.

---

## 3. Restore procedure

> **Before restoring:** stop all suite services (dossier, agent-notes,
> cairn, acb, agent-wake) to prevent writes during restore. The Postgres
> server itself stays running (you are restoring *into* it).

### 3.1 Linux

#### Logical restore (from `pg_dump --format=custom`)

```bash
# Stop suite services
systemctl stop dossier agent-notes cairn acb agent-wake

# Drop and recreate the database (or restore into a fresh cluster)
dropdb --host=suite-db.example --username=postgres regista
createdb --host=suite-db.example --username=postgres regista

# Restore
pg_restore \
  --host=suite-db.example \
  --username=regista_service \
  --dbname=regista \
  --clean --if-exists \
  /var/backups/agent-suite/suite-20260704.dump

# Verify the restore is intact (§4)
agent-suite verify-restore \
  --dsn "postgresql://regista_service@suite-db.example:5432/regista"

# Restart services
systemctl start dossier agent-notes cairn acb agent-wake
```

#### Physical restore (from `pg_basebackup`, for PITR)

```bash
# Stop Postgres
systemctl stop postgresql

# Replace the data directory
rm -rf /var/lib/postgresql/data
tar -xzf /var/backups/agent-suite/base.tar.gz -C /var/lib/postgresql/

# Configure recovery target (optional: specific timestamp)
cat >> /var/lib/postgresql/data/recovery.conf << 'EOF'
restore_command = 'cp /var/backups/agent-suite/wal/%f %p'
recovery_target_time = '2026-07-04 14:30:00'
recovery_target_action = 'promote'
EOF

# Start Postgres — it replays WALs to the target
systemctl start postgresql

# Verify the restore is intact (§4)
agent-suite verify-restore \
  --dsn "postgresql://regista_service@suite-db.example:5432/regista"

# Restart suite services
systemctl start dossier agent-notes cairn acb agent-wake
```

### 3.2 Docker

#### Volume backup (running container)

```bash
# Back up the Postgres data volume
docker run --rm \
  -v agent-suite-postgres:/data \
  -v /var/backups/agent-suite:/backup \
  alpine tar czf /backup/postgres-volume-$(date +%Y%m%d).tar.gz -C /data .
```

#### Volume restore

```bash
# Stop the suite stack
docker compose down

# Restore the volume
docker run --rm \
  -v agent-suite-postgres:/data \
  -v /var/backups/agent-suite:/backup \
  alpine sh -c 'rm -rf /data/* && tar xzf /backup/postgres-volume-20260704.tar.gz -C /data/'

# Start the suite stack
docker compose up -d

# Verify the restore is intact (§4)
docker compose exec suite agent-suite verify-restore \
  --dsn "postgresql://regista_service@suite-db:5432/regista"
```

#### Logical restore (inside the container)

```bash
# Restore from a pg_dump custom-format file piped into the container
docker exec -i agent-suite-postgres \
  pg_restore \
  --username=regista_service \
  --dbname=regista \
  --clean --if-exists \
  < /var/backups/agent-suite/suite-20260704.dump

# Verify
docker exec agent-suite-postgres agent-suite verify-restore \
  --dsn "postgresql://regista_service@localhost:5432/regista"
```

### 3.3 Windows

#### Prerequisites

Install the PostgreSQL client tools (from the PostgreSQL installer or
pgAdmin), which provide `pg_dump` and `pg_restore` on `%PATH%`.

#### Logical backup

```powershell
pg_dump --format=custom `
  --host=suite-db.example `
  --username=regista_service `
  --file=C:\Backups\agent-suite\suite-$(Get-Date -Format yyyyMMdd).dump `
  regista
```

#### Logical restore

```powershell
# Stop suite services (Windows Services console or sc)
sc stop dossier
sc stop agent-notes
sc stop cairn

# Restore
pg_restore `
  --host=suite-db.example `
  --username=regista_service `
  --dbname=regista `
  --clean --if-exists `
  C:\Backups\agent-suite\suite-20260704.dump

# Verify the restore is intact (§4)
agent-suite verify-restore `
  --dsn "postgresql://regista_service@suite-db.example:5432/regista"

# Restart services
sc start dossier
sc start agent-notes
sc start cairn
```

---

## 4. Post-restore verification

After restoring the Postgres store, **always** run `verify-restore` to prove
the restored data is cryptographically intact and unaltered:

```bash
agent-suite verify-restore \
  --dsn "postgresql://regista_service@suite-db.example:5432/regista"
```

Or with explicit projects:

```bash
agent-suite verify-restore \
  --dsn "postgresql://regista_service@suite-db.example:5432/regista" \
  --project project-slug --project another-slug
```

`verify-restore` runs `regista replay` across every project's event chain
and reports one of four statuses per project:

| Status | Meaning | Action |
|--------|---------|--------|
| **verified** | The chain replays with zero drift — the restore is intact | Proceed to restart services |
| **drift** | The chain shows drift — the restored data was tampered or corrupted; the failing link is reported | **Do not restart services.** Investigate the backup source and restore path. |
| **unreachable** | The project could not be queried (connection or permission issue) | Check the DSN, network, and service-role grants |
| **error** | An unexpected error occurred (non-JSON output, malformed data) | Investigate the regista installation and version |

The suite is verified only if **all** projects report `verified`. A single
`drift` result means the restore is compromised — do not restart services;
investigate the backup source and restore path.

---

## 5. What makes a restore complete

A restore is complete **only** when all of the following are true:

1. **All project schemas restored** — every project's event log, work items,
   and audit chain are present.
2. **The key registry restored** — the public-key registry (regista Plan
   026) is present, so signature verification can run. A restore missing
   the key registry cannot be verified and is incomplete.
3. **Archive bundles restored** (if applicable) — any Plan 028 sealed-chain
   archives are restored to their expected location.
4. **`verify-restore` passes** — every project's chain replays with zero
   drift.

> A restore that passes `verify-restore` proves the store came back
> *unaltered* — not just that it came back. This is the difference between
> "we restored a backup" and "we restored a provably unaltered backup."

---

## 6. References

- [Bootstrap contract](bootstrap-contract.md) — the install order, doctor
  umbrella, and lock model this runbook supports
- [Key-custody threat model](key-custody-threat-model.md) — the per-actor
  signing model whose integrity `verify-restore` proves
- `agent-suite verify-restore` — the post-restore verification command
  (Plan 001 WI-4.2)
- regista Plan 025 — the event-log store and `replay` command
- regista Plan 026 — the key registry and per-actor signing
- regista Plan 028 — archive bundles (sealed-chain retention)
