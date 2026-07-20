# Publication review

**Date:** 2026-07-04  
**Reviewer:** Claude (GLM 5.2)  
**Verdict:** REVOKED — re-review required before publication.

**2026-07-19 update:** The prior CLEARED verdict is revoked. A 5.18 MB
production operating-history export (`golden/operating-history/regista-
history-bundle-20260719.json`) was committed containing 1,508 complete
operational events with real identifiers and content. The export was
identified as coming from the production store in the committed README. A
denylist scan returning zero hits is not equivalent to privacy review — the
committed-identifier rule (AGENTS.md §"No work-domain identifiers") and this
review's own deployment-topology standard are violated. The export has been
removed from the tracked tree and replaced with a metadata manifest; a full
re-review is required before the repository can be cleared for publication.

## What was checked

### Identifier gate

`scripts/identifier-gate.py` was run against the full tree. The following
identifiers were scrubbed and the gate is now **blocking** in CI:

| Identifier | Type | Action |
|------------|------|--------|
| `Paul Merritt` | real name | Replaced with `YOUR-ORG` placeholder |
| `plm@hraedon.com` | personal email | Removed from `pyproject.toml` |
| `mvmpostgres01` | internal hostname | Replaced with `suite-db.example` |
| `hraedon.com` | internal domain | Scrubbed from `pyproject.toml` (was in email) |
| `hraedon/` | internal GitHub org prefix | Scrubbed from all tracked files; replaced with `YOUR-ORG/` (2026-07-10) |
| `regista_app` | internal DB service account | Replaced with `DB-SERVICE-ACCOUNT` placeholder (via F-4 scrub; was `regista_service`, itself a real identifier) |
| `agent_notes_app` | internal DB service account | Added to gate (not present in tree) |
| `itadmin` | OS username | Added to gate (not present in tree) |

The `hraedon` GitHub org name is **now in the gate** (as `hraedon/`) — it is an
internal org, not a public one. All tracked files use the `YOUR-ORG/` placeholder.

### Architecture boundary

`tests/test_architecture.py` asserts that every core module (`cli`,
`components`, `doctor`, `lock`, `bootstrap`, `verify_restore`) imports only the
standard library and its own modules — never a backend SDK or a component's
code. This is the mechanical enforcement of AGENTS.md's "thin orchestration"
rule. **Passes.**

### Tests

- `ruff check src tests scripts` — clean
- `mypy --strict src` — 7 files, no issues
- `pytest` (venv, stubbed) — 115 passed
- `pytest` (system, live Postgres via Docker) — interop + tamper tests pass

### Secrets

No secrets, keys, or passwords are committed. The `suite.env.example` file
contains placeholders only (`suite-db.example`, `DB-SERVICE-ACCOUNT`). The
`.gitignore` excludes `suite.env`, `*.env`, `secrets/`, `*.db`, and
`SUITE.local.lock`.

### Deployment topology

The docs reference deployment topology (Postgres hosts, secret backends,
service accounts) using **placeholders only** (`suite-db.example`,
`vault.example:8200`, `WORK-DOMAIN.vault.azure.net`, `DB-SERVICE-ACCOUNT`). No
real hostnames, domains, or principal IDs appear in any committed file.
