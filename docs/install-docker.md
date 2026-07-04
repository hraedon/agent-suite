# Docker install guide

How to stand up the agent-suite Tier 0–1 core in Docker containers, using
Docker Compose for Postgres and the suite components. This is the fastest path
to a running suite for evaluation or for shops that already run Docker in
production.

After this guide, an operator will have a running suite with a green
`agent-suite doctor`.

---

## 1. Prerequisites

| Dependency | Requirement |
|------------|------------|
| Docker | 24+ with the Compose plugin |
| Postgres | Provided by the Compose file (or use an external instance) |
| Secret backend | Vault or AKV (see [secrets-vault.md](secrets-vault.md) or [secrets-akv.md](secrets-akv.md)) — Credential Manager is not available inside containers |
| Ports | 5432 (Postgres), the dossier web port (e.g. 8000) |

## 2. Prepare the Compose file

Create a `docker-compose.yml` (this is an operator file, kept outside the
repo — it references real hosts and secrets):

```yaml
services:
  suite-db:
    image: postgres:16
    environment:
      POSTGRES_USER: regista_app
      POSTGRES_PASSWORD: ${REGISTA_DB_PASSWORD}
      POSTGRES_DB: regista
    volumes:
      - suite-db-data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U regista_app"]
      interval: 5s
      timeout: 3s
      retries: 30

  suite:
    image: ghcr.io/example-org/agent-suite:latest
    env_file: suite.env
    depends_on:
      suite-db:
        condition: service_healthy
    ports:
      - "8000:8000"
    volumes:
      - suite-config:/etc/agent-suite

volumes:
  suite-db-data:
  suite-config:
```

Replace `suite-db.example` with the actual database hostname in `suite.env`.
The `REGISTA_DB_PASSWORD` is the Postgres bootstrap password — it is **not**
the suite's secret backend; the suite's DSN password is resolved via
`vault:` / `akv:` refs inside the container (see §3).

## 3. Configure suite.env

Create `suite.env` alongside the Compose file:

```env
REGISTA_DSN=postgresql://regista_app@suite-db:5432/regista
REGISTA_DSN_PASSWORD=vault:secret/agent-suite/regista#dsn_password
REGISTA_KEY_PATH=vault:secret/agent-suite/regista#signing_key
REGISTA_REQUIRE_SSL=false
```

Note `suite-db` (the Compose service name) replaces `suite-db.example` — the
container resolves it via Docker networking. Set `REGISTA_REQUIRE_SSL=false`
only if traffic stays on the Docker network; for production, terminate TLS at
a reverse proxy and set it to `true`.

Install the backend extra inside the container by extending the image or
mounting a custom entrypoint that runs `pip install agent-suite[vault]` before
bootstrap. See [`suite.env.example`](../suite.env.example) for the canonical
placeholder set.

## 4. Bootstrap

Start the stack, then run the bootstrap inside the suite container:

```bash
docker compose up -d suite-db
docker compose run --rm suite agent-suite bootstrap --dry-run --tier 0-1
docker compose run --rm suite agent-suite bootstrap --tier 0-1
```

The bootstrap runs the documented install order (see the
[bootstrap contract](bootstrap-contract.md) §1): it probes the secret backend
and Postgres (step 0–1), provisions schemas and keys (step 2), brings up the
faces (step 3), and enables provenance (step 4). It is idempotent — re-running
changes nothing already done.

## 5. Verify with doctor

```bash
docker compose run --rm suite agent-suite doctor
```

Or, if the suite container is already running:

```bash
docker compose exec suite agent-suite doctor --json
```

A component that isn't installed is reported as `absent` (not a failure —
Tier 2 may not be deployed). See the
[bootstrap contract](bootstrap-contract.md) §3.

## 6. Data persistence

The `suite-db-data` volume persists the Postgres data across container
recreations. Do **not** remove this volume — it holds the event log and key
registry. Back it up per your organization's Postgres backup policy.

The `suite-config` volume persists `/etc/agent-suite/suite.env`. For
production, mount `suite.env` as a read-only bind mount from the host instead
of a named volume, so it is managed by the operator's config management tool.

## 7. Verify the compatibility lock

```bash
docker compose run --rm suite agent-suite lock --check
```

This compares installed component versions against `SUITE.lock` and reports
drift. See the [bootstrap contract](bootstrap-contract.md) §4.

## 8. Next steps

- Onboard additional humans: see [multi-user-onboarding.md](multi-user-onboarding.md).
- Key rotation and leaver process: see [key-operations.md](key-operations.md).
- For a non-containerized install, see [install-linux.md](install-linux.md) or
  [install-windows.md](install-windows.md).
